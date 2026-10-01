"""Deterministic orchestration loops and proposal approval."""

from echo_server.runtime.proposals import ProposalReviewer, ReviewCode, ReviewResult
from echo_server.runtime.recovery import decide_agent_run, decide_review

__all__ = [
    "ApplicationRuntime",
    "ConversationWorker",
    "ProposalReviewer",
    "ReviewCode",
    "ReviewResult",
    "decide_agent_run",
    "decide_review",
]


def __getattr__(name: str):
    if name == "ApplicationRuntime":
        from echo_server.runtime.application_runtime import ApplicationRuntime

        return ApplicationRuntime
    if name == "ConversationWorker":
        from echo_server.runtime.conversation_worker import ConversationWorker

        return ConversationWorker
    raise AttributeError(name)
