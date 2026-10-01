import asyncio

from echo_commons.infrastructure.models.protocol import ModelGateway, ModelRequest, ModelResponse


class ModelBudget:
    def __init__(self, gateway: ModelGateway, concurrency: int) -> None:
        if concurrency < 1:
            raise ValueError("Model concurrency must be positive")
        self.gateway = gateway
        self._semaphore = asyncio.Semaphore(concurrency)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        async with self._semaphore:
            return await self.gateway.generate(request)
