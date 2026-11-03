import json

import pytest
from fastapi.testclient import TestClient
from support.activities import message
from support.activity_actions import ALICE, CHARACTER, create_character_black, play_in
from support.application import settings_for
from support.http import create_group
from test_activity_models import decision_settings

from echo_commons.app.main import create_app
from echo_commons.execution.clock import utc_now
from echo_commons.modules.activities.gameplay.contracts import AnalysisRequest


@pytest.mark.model
@pytest.mark.parametrize("local", [False, True], ids=["ordinary", "local"])
def test_complete_match_with_expression_and_event_exchange(
    tmp_path, local, record_testsuite_property
):
    settings = decision_settings(tmp_path) if local else settings_for(tmp_path, workers=False)
    settings = settings.model_copy(
        update={
            "retry_backoff_seconds": 0,
            "debug_capture_enabled": True,
            "debug_capture_path": str(tmp_path / "captures"),
        }
    )
    with TestClient(create_app(settings)) as client:
        create_group(client, memory_mode="simple")
        app = client.app.state.application
        game = create_character_black(app)
        message(client, game, "来一盘吧，有什么有意思的变化也可以聊聊，不用每一步都解释。")
        worker = app.supervisor.workers["activities-0"]
        for step in range(500):
            app.planner.plan()
            client.portal.call(worker.run_once)
            with app.database.read() as connection:
                context = app.game_queries.participant_context(
                    connection, "community", CHARACTER, game
                )
                current = context.game
                failures = [
                    dict(r)
                    for r in connection.execute(
                        "SELECT task_id,last_error_code FROM activity_tasks WHERE status='failed'"
                    )
                ]
                assert not failures, failures
                if current.status == "finished":
                    break
                opponent = app.game_queries.participant_context(
                    connection, "community", ALICE, game
                )
                view = app.games.read_view(connection, opponent.access)
            if view.opportunities:
                # 对手思考前处理已经决定的表达，表达仍由正式队列执行。
                client.portal.call(app.activity_expressions.queue.recover, utc_now())
                if worker.expression_dispatcher:
                    client.portal.call(worker.expression_dispatcher.dispatch_once)
                analysis = client.portal.call(
                    app.game_analysis.analyze,
                    AnalysisRequest(view=view, opportunity=view.opportunities[0]),
                )
                action = next(
                    c.action
                    for c in analysis.candidates
                    if c.candidate_id == analysis.recommended_candidate_id
                )
                with app.database.transaction() as connection:
                    play_in(app, connection, game, ALICE, action)
            print(f"local={local}, step={step}, version={current.state_version}", flush=True)
        else:
            pytest.fail("Match did not reach a real result")
        for _ in range(25):
            app.planner.plan()
            if not client.portal.call(worker.run_once):
                break
        with app.database.read() as connection:
            assert current.status == "finished"
            assert (
                connection.execute("SELECT COUNT(*) FROM activity_working_memory").fetchone()[0]
                == 0
            )
            pending = connection.execute(
                "SELECT COUNT(*) FROM activity_expression_tasks WHERE status IN "
                "('pending','processing','retry_wait')"
            ).fetchone()[0]
            assert pending == 0
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()
            report = {
                "game": current.model_dump(mode="json"),
                "messages": [
                    dict(r)
                    for r in connection.execute(
                        "SELECT sequence,text,activity_result_id FROM messages WHERE "
                        "sender_kind='character'"
                    )
                ],
                "expressions": [
                    dict(r)
                    for r in connection.execute(
                        "SELECT task_id,status,last_error_code FROM activity_expression_tasks"
                    )
                ],
                "opportunities": [
                    dict(r)
                    for r in connection.execute("SELECT * FROM activity_reaction_opportunities")
                ],
                "calls": [
                    dict(r)
                    for r in connection.execute(
                        "SELECT task_kind,payload_json FROM task_execution_events WHERE "
                        "event_kind='run_finished'"
                    )
                ],
            }
        record_testsuite_property(f"exchange_{local}", json.dumps(report, ensure_ascii=False))
