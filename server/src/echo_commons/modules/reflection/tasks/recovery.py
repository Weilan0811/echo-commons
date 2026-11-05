import sqlite3
from datetime import datetime

from echo_commons.agents.contracts.recovery import (
    FailureCategory,
    RecoveryAction,
    TaskRecoveryDecision,
)
from echo_commons.execution.contracts import TaskLease
from echo_commons.execution.observations import ExecutionEventPayload, ExecutionObservation
from echo_commons.execution.records import ExecutionRecorder
from echo_commons.execution.recovery import AppliedRecovery, RecoveryPolicy, decision
from echo_commons.modules.reflection.contexts.actors import source_actors
from echo_commons.modules.reflection.contexts.sources import ReflectionSourceUnavailable
from echo_commons.modules.reflection.domain.node import ReflectionNodeTaskStatus
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.dependencies import bind_ready_inputs
from echo_commons.modules.reflection.tasks.projection import project_node_input
from echo_commons.shared.validation import TimeOrderError

REVIEW_HINTS = {
    "reflection_fact_decision_invalid": (
        "请按候选编号逐项返回一次操作。add 的 target 为 null；support、correct 的 target "
        "使用允许的旧事实编号。每项旧事实最多更新一次。"
    ),
    "reflection_relationship_description_required": (
        "当前目标已有有效证据且描述为空，请依据本次材料生成有限的首次关系描述，不能返回 no_op。"
    ),
    "reflection_relationship_attitude_too_long": (
        "关系描述超过本次 content 字符上限，请保留有依据的认识，缩短正文，不填写分数。"
    ),
    "reflection_view_target_unknown": "请仅依据当前对象的关系材料撰写正文。",
    "reflection_core_memory_too_long": (
        "核心记忆超过本次 content 字符上限。请压缩重复表达，保留姓名、约定对象和关键事实。"
    ),
    "reflection_candidate_limit_exceeded": "请合并重复内容并遵守本节点的候选数量额度。",
    "reflection_output_too_long": "请缩短本节点输出的 JSON，使其符合长度限制。",
    "reflection_summary_required": "请按照本节点契约生成段摘要，本节点需要正式摘要产物。",
    "reflection_digest_required": "请按照本节点契约生成连续性摘要，本节点需要正式摘要产物。",
    "reflection_evidence_unknown": "请仅引用本次输入允许的 evidence_refs。",
    "reflection_relationship_target_unknown": "请仅选择本次输入允许的关系目标。",
    "reflection_relationship_evidence_mismatch": (
        "请修正各人物的 sources，只从该目标的 allowed_sources 选择，并包含 direct_sources。"
        "不能使用第三人的发言或只读前情。段摘要规划无法确定可靠依据时，保留 summary，"
        "将 relationship_reflect 设为 false、relationship_targets 设为 []。"
    ),
    "reflection_evidence_mismatch": "请核对每项依据，重复材料编号只填写一次。",
    "reflection_evidence_missing": "请为每项记忆填写真正支持正文的允许材料编号。",
    "reflection_record_reference_unknown": (
        "请按本节点结构输出，使用本次提供的编号，并检查依据类型；只读前情不能作为新变化的依据。"
    ),
    "reflection_action_mismatch": "请使用本节点允许的行动类型。",
}


class ReflectionRecovery:
    def __init__(
        self,
        policy: RecoveryPolicy,
        recorder: ExecutionRecorder,
        nodes: NodeRepository,
        runs: RunRepository,
    ) -> None:
        self.policy, self.recorder, self.nodes, self.runs = policy, recorder, nodes, runs
        self.artifacts = ArtifactRepository()

    def classify(self, error: Exception) -> TaskRecoveryDecision:
        if isinstance(error, TimeOrderError):
            return decision("task_time_order_invalid", FailureCategory.PERSISTENCE)
        if isinstance(error, ReflectionSourceUnavailable):
            return decision(error.code, FailureCategory.SOURCE)
        return self.policy.classify(error)

    def review(self, code: str, *, repairable: bool = True) -> TaskRecoveryDecision:
        if repairable and code in REVIEW_HINTS:
            return decision(
                code, FailureCategory.REVIEW, RecoveryAction.RETRY_TASK, hint=REVIEW_HINTS[code]
            )
        category = (
            FailureCategory.SOURCE
            if code
            in (
                "reflection_input_mismatch",
                "reflection_source_unavailable",
                "reflection_evidence_missing",
            )
            else FailureCategory.CONFIGURATION
            if code == "reflection_contract_mismatch"
            else FailureCategory.HARNESS
            if code in ("invocation_identity_mismatch", "reflection_output_missing")
            else FailureCategory.REVIEW
        )
        return decision(code, category)

    def hint(self, connection: sqlite3.Connection, task_id: str, generation: int) -> str | None:
        return self.policy.hint(
            self.recorder.repository.latest(connection, "reflection", task_id, generation)
        )

    def reject(self, connection, lease, code, invocation, result, now):
        repairable = True
        if code == "reflection_evidence_unknown":
            repairable = bool(project_node_input(invocation.context).evidence_refs)
        elif code == "reflection_relationship_target_unknown":
            repairable = bool(source_actors(invocation.context.graph_snapshot))
        return self.apply(connection, lease, self.review(code, repairable=repairable), now)

    def apply(
        self,
        connection: sqlite3.Connection,
        lease: TaskLease,
        recovery: TaskRecoveryDecision,
        now: datetime,
        *,
        expired: bool = False,
        observation: ExecutionObservation | None = None,
    ) -> AppliedRecovery | None:
        node = self.nodes.get(connection, lease.task_id)
        scope = self.runs.scope(connection, str(node.graph_run_id))
        run = self.runs.get(
            connection, scope.community_id, scope.character_id, str(node.graph_run_id)
        )
        if run.is_terminal or (
            not expired
            and not node.has_valid_lease(
                worker_id=lease.owner,
                now_utc=now,
                attempt_count=lease.attempt,
                lease_generation=lease.generation,
            )
        ):
            self.recorder.record(
                connection,
                lease,
                "result_ignored",
                ExecutionEventPayload(reason_code="lease_lost"),
                now,
            )
            return None
        if recovery.failure.code in ("agent_suspended", "agent_cancelled"):
            eligible = connection.execute(
                "SELECT 1 FROM character_instances i JOIN communities c USING(community_id) "
                "WHERE i.character_id=? AND i.availability_status='available' "
                "AND c.status='active'",
                (run.character_id,),
            ).fetchone()
            recovery = (
                decision(
                    "reflection_temporarily_unavailable",
                    FailureCategory.SOURCE,
                    RecoveryAction.DEFER,
                )
                if eligible is None
                else decision("agent_run_state_invalid", FailureCategory.HARNESS)
            )
        applied = self.policy.plan(
            recovery,
            lease.attempt - node.attempt_base_count,
            now,
            retry_delays=(30, 120, 600)
            if recovery.failure.category is FailureCategory.PROVIDER
            and recovery.action is RecoveryAction.RETRY_TASK
            else None,
        )
        if applied.action is RecoveryAction.IGNORE:
            self.recorder.record(
                connection, lease, "result_ignored", ExecutionEventPayload(recovery=applied), now
            )
            return applied
        node = node.apply_recovery(
            worker_id=lease.owner,
            now_utc=now,
            target_state=ReflectionNodeTaskStatus(applied.task_state),
            available_at_utc=applied.next_attempt_at_utc or now,
            error_code=applied.decision.failure.code,
            attempt_count=lease.attempt,
            lease_generation=lease.generation,
            expired=expired,
        )
        self.nodes.save(connection, node)
        self.recorder.record(
            connection,
            lease,
            "recovery_applied",
            self.recorder.recovery_payload(connection, lease, applied, observation),
            now,
        )
        if node.status is ReflectionNodeTaskStatus.FAILED:
            if node.node_key in run.required_node_keys:
                self.runs.save(connection, run.fail(now_utc=now, error_code=node.last_error_code))
                for other in self.nodes.for_graph(connection, str(run.graph_run_id)):
                    if not other.is_terminal:
                        cancelled = other.cancel(now_utc=now, reason_code="required_node_failed")
                        self.nodes.save(
                            connection,
                            cancelled,
                        )
                        self.recorder.node_transition(
                            connection, cancelled, run, "required_node_failed", now
                        )
            else:
                bind_ready_inputs(
                    connection, str(run.graph_run_id), now, self.runs, self.nodes, self.artifacts
                )
        return applied
