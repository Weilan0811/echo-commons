import json

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.recovery import FailureCategory
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.contracts.run import AgentOutput, AgentRunResult

CHARACTER_MESSAGE_CONTRACT = OutputContractRef(kind="character_message", version="v1")


class CharacterMessageProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    thought: str = ""
    utterance: str = Field(min_length=1)
    reply_to: int | None = Field(default=None, strict=True, ge=1)

    @field_validator("utterance")
    @classmethod
    def meaningful_utterance(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("utterance must contain text")
        return value


class OutputRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, TypeAdapter[BaseModel]] = {}

    def register(
        self, contract: OutputContractRef, model: type[BaseModel] | TypeAdapter[BaseModel]
    ) -> None:
        if contract.schema_id in self._adapters:
            raise ValueError(f"duplicate output contract: {contract.schema_id}")
        self._adapters[contract.schema_id] = (
            model if isinstance(model, TypeAdapter) else TypeAdapter(model)
        )

    def parse(self, contract: OutputContractRef, payload: dict[str, object]) -> BaseModel:
        return self._require(contract).validate_python(payload)

    def schema(self, contract: OutputContractRef) -> dict[str, object]:
        return self._require(contract).json_schema()

    def _require(self, contract: OutputContractRef) -> TypeAdapter[BaseModel]:
        adapter = self._adapters.get(contract.schema_id)
        if adapter is None:
            raise ExecutionError("agent_input_contract_invalid", FailureCategory.CONFIGURATION)
        return adapter

    def restore_result(self, serialized: str) -> AgentRunResult:
        data = json.loads(serialized)
        output = data.get("output")
        if output is not None:
            contract = OutputContractRef.model_validate(output["contract"])
            data["output"] = AgentOutput(
                contract=contract, payload=self.parse(contract, output["payload"])
            )
        return AgentRunResult.model_validate(data)
