from pydantic import ValidationError

from echo_commons.agents.contracts.invocation import AgentInvocation
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.run import AgentOutput
from echo_commons.infrastructure.models.protocol import ModelResponse, ModelResponseKind


class ModelOutputError(ValueError):
    code = "invalid_model_output"


def parse_terminal_output(
    response: ModelResponse, invocation: AgentInvocation, outputs: OutputRegistry
) -> AgentOutput:
    if response.kind is not ModelResponseKind.TERMINAL or response.output is None:
        raise ModelOutputError("Model response requires terminal output")
    try:
        payload = outputs.parse(invocation.output_contract, response.output)
    except ValidationError as error:
        raise ModelOutputError("Output does not match its registered contract") from error
    return AgentOutput(contract=invocation.output_contract, payload=payload)
