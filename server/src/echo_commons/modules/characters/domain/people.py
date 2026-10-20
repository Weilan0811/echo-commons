from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PersonModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PersonRegistration(PersonModel):
    player_id: str = Field(min_length=1)
    person_id: UUID
    display_name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)


class PersonView(PersonRegistration):
    pass


class BoundPerson(PersonModel):
    person_id: UUID
    actor_kind: Literal["player", "character"]
    actor_id: str = Field(min_length=1)


class PersonBinding(BoundPerson):
    player_id: str = Field(min_length=1)


class PersonBindingView(PersonBinding):
    community_id: str


class AuthoredRelationship(PersonModel):
    relationship_id: UUID
    target_person_id: UUID
    target_name: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def nonblank(self):
        if not self.target_name.strip() or not self.content.strip():
            raise ValueError("Relationship name and content must be nonempty")
        return self


class RelationshipSuggestion(PersonModel):
    name: str = Field(min_length=1, max_length=80)
    identity_hint: str = Field(default="", max_length=500)
    content: str = Field(min_length=1, max_length=4000)
    source_refs: tuple[str, ...] = Field(min_length=1, max_length=16)


class RelationshipSeed(PersonModel):
    relationship_id: UUID
    acquaintance: bool
    affection: float = Field(ge=0, le=100, allow_inf_nan=False)
    trust: float = Field(ge=0, le=100, allow_inf_nan=False)
    attachment: float = Field(ge=0, le=100, allow_inf_nan=False)
    attitude: str = Field(min_length=1, max_length=1500)
    evidence_quote: str = Field(min_length=1, max_length=1500)
    support_quote: str = Field(default="", max_length=1500)


class RelationshipSeeds(PersonModel):
    relationships: tuple[RelationshipSeed, ...] = Field(max_length=40)
