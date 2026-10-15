from echo_commons.modules.conversations.repositories.queue import ConversationQueueRepository
from echo_commons.modules.conversations.tasks.queue import ConversationQueue
from support.recovery import conversation_recovery
from support.social import build_planning_system, send


def queue_system(tmp_path, policy):
    system = build_planning_system(tmp_path)
    send(system)
    system.planner.plan()
    system.queue = ConversationQueue(
        system.database,
        ConversationQueueRepository(),
        system.social,
        system.completion,
        policy,
        conversation_recovery(system, policy),
    )
    return system
