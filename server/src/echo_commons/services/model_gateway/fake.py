"""Deterministic Model Gateway used by Harness and Runtime tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from echo_server.services.model_gateway.protocol import (
    ModelGatewayError,
    ModelRequest,
    ModelResponse,
)


class FakeModelGateway:
    """Return a pre-scripted sequence without network or provider dependencies."""

    provider = "fake"
    model = "fake-scripted"

    def __init__(self, responses: Iterable[ModelResponse | Exception]) -> None:
        self._responses = deque(responses)
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self._responses:
            raise ModelGatewayError("fake_gateway_exhausted", retryable=False)
        response = self._responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response
