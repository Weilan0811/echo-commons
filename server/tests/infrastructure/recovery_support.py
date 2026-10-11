from echo_commons.execution.records import ExecutionRecorder
from echo_commons.execution.recovery import QueuePolicy, RecoveryPolicy
from echo_commons.modules.conversations.repositories.queue import ConversationQueueRepository
from echo_commons.modules.conversations.tasks.recovery import ConversationRecovery
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.recovery import ReflectionRecovery

DEFAULT_POLICY = QueuePolicy()


def conversation_recovery(system, policy=DEFAULT_POLICY):
    return ConversationRecovery(
        RecoveryPolicy(policy),
        ExecutionRecorder(system.database),
        ConversationQueueRepository(),
        system.social_lifecycle,
    )


def reflection_recovery(database, policy):
    return ReflectionRecovery(
        RecoveryPolicy(policy), ExecutionRecorder(database), NodeRepository(), RunRepository()
    )
