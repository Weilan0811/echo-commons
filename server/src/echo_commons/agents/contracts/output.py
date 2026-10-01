from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from echo_commons.agents.contracts.refs import OutputContractRef

CHARACTER_MESSAGE_CONTRACT = OutputContractRef(kind="character_message", version="v1")


class CharacterMessageProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    thought: str = ""
    utterance: str = Field(min_length=1)
    reply_to_message_id: str | None = None


class OutputRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, TypeAdapter] = {}

    def register(self, contract: OutputContractRef, model: type[BaseModel]) -> None:
        if contract.schema_id in self._adapters:
            raise ValueError(f"duplicate output contract: {contract.schema_id}")
        self._adapters[contract.schema_id] = TypeAdapter(model)

    def parse(self, contract: OutputContractRef, payload: dict[str, object]) -> BaseModel:
        return self._adapters[contract.schema_id].validate_python(payload)
