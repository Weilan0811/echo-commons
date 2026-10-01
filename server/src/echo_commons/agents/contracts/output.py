import json

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.contracts.run import AgentOutput, AgentRunResult

CHARACTER_MESSAGE_CONTRACT = OutputContractRef(kind="character_message", version="v1")


class CharacterMessageProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    thought: str = ""
    utterance: str = Field(min_length=1)
    reply_to_message_id: str | None = None

    @field_validator("utterance")
    @classmethod
    def meaningful_utterance(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("utterance must contain text")
        return value


class OutputRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, TypeAdapter] = {}

    def register(self, contract: OutputContractRef, model: type[BaseModel]) -> None:
        if contract.schema_id in self._adapters:
            raise ValueError(f"duplicate output contract: {contract.schema_id}")
        self._adapters[contract.schema_id] = TypeAdapter(model)

    def parse(self, contract: OutputContractRef, payload: dict[str, object]) -> BaseModel:
        return self._adapters[contract.schema_id].validate_python(payload)

    def schema(self, contract: OutputContractRef) -> dict[str, object]:
        return self._adapters[contract.schema_id].json_schema()

    def restore_result(self, serialized: str) -> AgentRunResult:
        data = json.loads(serialized)
        output = data.get("output")
        if output is not None:
            contract = OutputContractRef.model_validate(output["contract"])
            data["output"] = AgentOutput(
                contract=contract, payload=self.parse(contract, output["payload"])
            )
        return AgentRunResult.model_validate(data)
