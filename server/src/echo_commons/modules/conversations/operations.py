from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from echo_commons.modules.conversations.domain.conversation import Membership
from echo_commons.shared.actors import ActorRef


class MembershipOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    community_id: str
    conversation_id: str
    actor: ActorRef
    action: Literal["join", "leave"]
    player_id: str | None = None
    expected_membership_version: int | None = Field(default=None, ge=0)
    expected_membership_id: str | None = None


class MembershipResult(BaseModel):
    membership: Membership
    membership_version: int
    self_membership_status: Literal["current", "past"]


class ArchiveOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    community_id: str
    conversation_id: str
    player_id: str
    expected_state_version: int = Field(ge=1)


class ListPreferenceOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    community_id: str
    conversation_id: str
    player_id: str
    hidden: bool


class ArchiveResult(BaseModel):
    conversation_id: str
    state_version: int
    status: Literal["archived"]


class ListPreferenceResult(BaseModel):
    conversation_id: str
    hidden: bool
