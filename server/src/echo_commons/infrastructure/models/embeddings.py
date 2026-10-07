import asyncio
import json
import logging

import numpy as np
from openai import AsyncOpenAI

from echo_commons.agents.contracts.run import UsageSummary
from echo_commons.execution.model_budget import ModelBudget
from echo_commons.infrastructure.models.errors import classify_provider_error
from echo_commons.infrastructure.models.metrics import ProviderUsageTracker
from echo_commons.infrastructure.models.protocol import ModelGatewayError
from echo_commons.infrastructure.models.registry import ModelConfigurationError, ModelRegistry
from echo_commons.modules.memory.domain.policy import VectorPolicy

logger = logging.getLogger("echo_commons.embeddings")


class EmbeddingGateway:
    def __init__(self, registry: ModelRegistry, policy: VectorPolicy, budget: ModelBudget) -> None:
        if not policy.enabled:
            raise ValueError("Disabled vector retrieval must not construct a gateway")
        self.registry, self.policy, self.budget = registry, policy, budget
        self.usage_tracker = ProviderUsageTracker()
        self._client: AsyncOpenAI | None = None

    @property
    def identity(self) -> str:
        try:
            entry = self.registry.resolve(self.policy.profile)
        except ModelConfigurationError:
            return json.dumps([self.policy.profile, "unconfigured", self.policy.dimensions])
        return json.dumps(
            [entry.model_vendor, entry.base_url, entry.model, self.policy.dimensions],
            separators=(",", ":"),
        )

    async def embed(
        self, texts: tuple[str, ...], *, background: bool = False
    ) -> tuple[np.ndarray, ...]:
        if not texts or len(texts) > self.policy.batch_size:
            raise ValueError("Embedding request exceeds material count budget")
        if sum(map(len, texts)) > self.policy.batch_max_chars:
            raise ValueError("Embedding request exceeds text budget")
        entry = self.registry.resolve(self.policy.profile)
        credential = self.registry.credential_for(entry)
        if not credential:
            raise ModelGatewayError(
                code="provider_not_configured", retryable=False, provider_attempt=0
            )
        if self._client is None:
            self._client = AsyncOpenAI(api_key=credential, base_url=entry.base_url, max_retries=0)
        async with asyncio.timeout(self.policy.timeout_seconds):
            async with self.budget.slot(2 if background else 0):
                for attempt in range(1, entry.max_retries + 2):
                    try:
                        response = await self._client.embeddings.create(
                            model=entry.model,
                            input=list(texts),
                            encoding_format="float",
                            timeout=min(entry.request_timeout_seconds, self.policy.timeout_seconds),
                        )
                    except Exception as error:
                        failure = classify_provider_error(error, provider_attempt=attempt)
                        logger.warning(
                            "Embedding call failed: %s, attempt=%s", failure.code, attempt
                        )
                        if not failure.retryable or attempt > entry.max_retries:
                            raise failure from error
                        await asyncio.sleep(entry.retry_backoff_seconds)
                        continue
                    vectors = tuple(
                        np.asarray(item.embedding, dtype=np.float32)
                        for item in sorted(response.data, key=lambda item: item.index)
                    )
                    if len(vectors) != len(texts) or any(
                        value.shape != (self.policy.dimensions,)
                        or not np.isfinite(value).all()
                        or np.linalg.norm(value) == 0
                        for value in vectors
                    ):
                        raise ModelGatewayError(
                            code="invalid_embedding_response",
                            retryable=False,
                            provider_attempt=attempt,
                        )
                    usage = UsageSummary(
                        model_request_count=1,
                        input_tokens=response.usage.prompt_tokens,
                        total_tokens=response.usage.total_tokens,
                    )
                    self.usage_tracker.record(entry.model_vendor, usage)
                    logger.info(
                        "Embedding call completed: model=%s, input_tokens=%s, materials=%s",
                        entry.model,
                        usage.input_tokens,
                        len(texts),
                    )
                    return vectors
        raise RuntimeError("Embedding request did not finish")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
