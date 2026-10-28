import asyncio
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from support.application import settings_for
from support.reflection import seed

from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.app.settings import load_settings
from echo_commons.execution.lease import LeaseLostError, with_heartbeat
from echo_commons.infrastructure.models.openai_compatible import OpenAICompatibleGateway
from echo_commons.infrastructure.models.protocol import ModelGatewayError
from echo_commons.modules.reflection.contracts.diagnosis import DiagnosisPolicy, DiagnosisReport
from echo_commons.modules.reflection.domain.graph import ReflectionArtifact, ReflectionNodeKind
from echo_commons.modules.reflection.tasks.projection import project_node_input


def test_diagnosis_switches_and_report_contract(tmp_path):
    fact = DiagnosisPolicy(facts_enabled=True)
    summary = DiagnosisPolicy(summaries_enabled=True)
    for kind in ReflectionNodeKind:
        assert fact.enabled(kind) == (kind is ReflectionNodeKind.FACT_EXTRACT)
        assert summary.enabled(kind) == (
            kind
            in {
                ReflectionNodeKind.SEGMENT_SUMMARY_PLAN,
                ReflectionNodeKind.CONTINUITY_COMPRESS,
                ReflectionNodeKind.COGNITION_REFLECT,
                ReflectionNodeKind.CORE_MEMORY_VIEW,
            }
        )
    assert DiagnosisReport(passed=True).issues == ()
    for data in (
        {"passed": False},
        {"passed": "true"},
        {
            "passed": True,
            "issues": [{"location": "items[0]", "evidence": "材料1", "requirement": "保留否定"}],
        },
    ):
        with pytest.raises(ValidationError):
            DiagnosisReport.model_validate(data)
    path = tmp_path / "settings.toml"
    path.write_text(
        "schema_version=1\n[reflection.diagnosis]\nfacts_enabled=true\n"
        "summaries_enabled=false\nmax_revisions=2\n",
        encoding="utf-8",
    )
    assert load_settings(path).reflection_diagnosis == fact


def test_reflection_input_omits_conversation_contract_and_keeps_sources(tmp_path):
    async def run():
        async with application_lifecycle(settings_for(tmp_path, workers=False)) as app:
            seed(app)
            lease = await app.reflection_queue.claim("projection", datetime.now(UTC))
            prepared = app.reflection_execution.prepare(lease.task_id, attempt=lease.attempt)
            projection = project_node_input(prepared.invocation.context)
            names = {name for name, _ in projection.identity_sections}
            assert "agent_contract" not in names
            assert "character_profile" in names
            assert "character_voice" not in names
            assert projection.evidence_refs
            assert app.gateway.usage_tracker.snapshot() == {}

    asyncio.run(run())


@pytest.mark.model
def test_real_diagnosis_reuses_approved_draft_after_restart_and_commits_once(tmp_path):
    async def run():
        settings = settings_for(tmp_path, workers=False).model_copy(
            update={
                "reflection_diagnosis": DiagnosisPolicy(summaries_enabled=True),
                "reflection_max_output_tokens": 2048,
            }
        )
        async with application_lifecycle(settings) as app:
            seed(app)
            lease = await app.reflection_queue.claim("diagnosis", datetime.now(UTC))
            prepared = app.reflection_execution.prepare(
                lease.task_id,
                attempt=lease.attempt,
                deadline_utc=datetime.now(UTC) + timedelta(seconds=240),
            )
            result = await with_heartbeat(
                app.reflection_queue, lease, app.reflection_commit.diagnosis.run(lease, prepared), 5
            )
            with app.database.read() as connection:
                steps = connection.execute(
                    "SELECT * FROM reflection_draft_steps WHERE node_task_id=? ORDER BY step_id",
                    (lease.task_id,),
                ).fetchall()
            assert steps[-1]["report_json"] is not None
            assert DiagnosisReport.model_validate_json(steps[-1]["report_json"]).passed
            assert result.usage_summary.model_request_count >= 2
            changed = prepared.invocation.model_copy(
                update={
                    "execution_policy": prepared.invocation.execution_policy.model_copy(
                        update={"model_profile": "strong"}
                    )
                }
            )
            assert app.reflection_commit.diagnosis._load(lease, changed)[0] is None
        async with application_lifecycle(settings) as app:
            restored = app.reflection_execution.prepare(lease.task_id, attempt=lease.attempt)
            replay = await app.reflection_commit.diagnosis.run(lease, restored)
            assert replay.output == result.output
            assert replay.usage_summary.model_request_count == 0
            assert app.gateway.usage_tracker.snapshot() == {}
            artifact = app.reflection_commit.commit(
                lease, restored.invocation, replay, datetime.now(UTC)
            )
            assert isinstance(artifact, ReflectionArtifact)
            assert artifact == app.reflection_commit.commit(
                lease, restored.invocation, replay, datetime.now(UTC)
            )
            with pytest.raises(LeaseLostError):
                await app.reflection_commit.diagnosis.run(lease, restored)

    asyncio.run(run())


@pytest.mark.model
def test_real_diagnosis_failure_restores_writer_without_repeating_generation(tmp_path):
    async def run():
        settings = settings_for(tmp_path, workers=False).model_copy(
            update={
                "reflection_diagnosis": DiagnosisPolicy(summaries_enabled=True),
                "reflection_max_output_tokens": 2048,
                "retry_backoff_seconds": 0,
            }
        )
        async with application_lifecycle(settings) as app:
            seed(app)
            lease = await app.reflection_queue.claim("failure", datetime.now(UTC))
            prepared = app.reflection_execution.prepare(lease.task_id, attempt=lease.attempt)
            diagnosis = app.reflection_commit.diagnosis
            entry = app.models.resolve(diagnosis.profile)
            # 绑定但不监听的端口产生真实连接失败，不替代模型实现。
            with socket.socket() as unavailable:
                unavailable.bind(("127.0.0.1", 0))
                port = unavailable.getsockname()[1]
                registry = replace(
                    app.models,
                    entries={
                        **app.models.entries,
                        entry.entry_id: replace(
                            entry, base_url=f"http://127.0.0.1:{port}", max_retries=0
                        ),
                    },
                )
                gateway = OpenAICompatibleGateway(registry)
                diagnosis.gateway = gateway
                try:
                    with pytest.raises(ModelGatewayError) as failed:
                        await with_heartbeat(
                            app.reflection_queue, lease, diagnosis.run(lease, prepared), 5
                        )
                finally:
                    await gateway.close()
            with app.database.read() as connection:
                writer = diagnosis.steps.latest_writer(connection, lease)
                assert writer is not None
                assert diagnosis.steps.report(connection, writer["step_id"]) is None
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM reflection_artifacts WHERE node_task_id=?",
                        (lease.task_id,),
                    ).fetchone()[0]
                    == 0
                )
            await app.reflection_queue.apply_recovery(
                lease, datetime.now(UTC), app.reflection_queue.recovery.classify(failed.value)
            )
        async with application_lifecycle(settings) as app:
            for _ in range(50):
                resumed = await app.reflection_queue.claim("restored", datetime.now(UTC))
                if resumed is not None and resumed.task_id == lease.task_id:
                    break
                await asyncio.sleep(1)
            assert resumed is not None
            assert resumed.task_id == lease.task_id
            prepared = app.reflection_execution.prepare(resumed.task_id, attempt=resumed.attempt)
            diagnosis = app.reflection_commit.diagnosis
            result = await with_heartbeat(
                app.reflection_queue, resumed, diagnosis.run(resumed, prepared), 5
            )
            with app.database.read() as connection:
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM reflection_draft_steps WHERE node_task_id=? "
                        "AND phase='writer' AND revision=0",
                        (lease.task_id,),
                    ).fetchone()[0]
                    == 1
                )
            assert isinstance(
                app.reflection_commit.commit(
                    resumed, prepared.invocation, result, datetime.now(UTC)
                ),
                ReflectionArtifact,
            )

    asyncio.run(run())
