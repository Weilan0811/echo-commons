"""Small V2 context builders shared by isolated Agent tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from echo_server.agents.contracts import (
    AgentMessage,
    CharacterStateSnapshot,
    ContextRequest,
    ContextSnapshotV2,
    IdentityContext,
    RelationshipStateSnapshot,
    SituationView,
)

DEFAULT_CONTEXT_TIME = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def build_test_snapshot(
    *,
    conversation_id: str = "xiaojin",
    character_id: str = "xiaojin",
    sender_id: str = "local-player",
    player_text: str = "hello",
    context_version: str = "context-v1",
    now_utc: datetime = DEFAULT_CONTEXT_TIME,
    baseline_resource_id: str = "baseline",
    baseline_content: str = "baseline content",
    baseline_version: str = "v1",
    profile_content: str = "identity content",
    profile_version: str = "v1",
    stage_summary: str = "",
) -> ContextSnapshotV2:
    """Build a minimal canonical snapshot without legacy compatibility fields."""

    message = AgentMessage(
        message_id=uuid4(),
        sender_type="player",
        sender_id=sender_id,
        text=player_text,
        server_timestamp_utc=now_utc,
    )
    return ContextSnapshotV2(
        conversation_id=conversation_id,
        character_id=character_id,
        context_version=context_version,
        now_utc=now_utc,
        request=ContextRequest(
            conversation_id=conversation_id,
            character_id=character_id,
            trigger_message=message,
            input_messages=(message,),
        ),
        identity=IdentityContext(
            contract_resource_id=baseline_resource_id,
            contract_content=baseline_content,
            contract_version=baseline_version,
            character_id=character_id,
            bundle_version=profile_version,
            profile_resource_id=f"{character_id}.profile",
            profile_content=profile_content,
            profile_version=profile_version,
        ),
        character_state=CharacterStateSnapshot(
            character_id=character_id,
            availability_status="",
            availability_updated_at_utc=now_utc,
        ),
        relationship_state=RelationshipStateSnapshot(
            subject_id=sender_id,
            updated_at_utc=now_utc,
        ),
        situation=SituationView(stage_summary=stage_summary),
    )


__all__ = ["build_test_snapshot"]
