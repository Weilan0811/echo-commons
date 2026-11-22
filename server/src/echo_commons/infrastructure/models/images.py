import httpx

from .image_contracts import ImageConfiguration, ImageRequest
from .image_providers.apimart import APIMartImages
from .image_providers.dashscope import DashScopeImages
from .image_providers.minimax import MiniMaxImages


class ImageModelUnavailable(ValueError):
    code = "image_model_unavailable"


class ImageGateway:
    def __init__(self, configuration: ImageConfiguration, credentials, timeout: float):
        self.configuration, self.credentials = configuration, credentials
        self.client = httpx.AsyncClient(timeout=timeout)
        self.adapters = {
            "apimart": APIMartImages(),
            "dashscope": DashScopeImages(),
            "minimax": MiniMaxImages(),
        }

    def require_credential(self, configuration=None):
        configuration = configuration or self.configuration
        credential = self.credentials.get(configuration.credential_ref)
        if not credential or not credential.strip():
            raise ImageModelUnavailable("Image generation credentials are not configured")
        return credential

    def freeze(self, request: ImageRequest):
        self.require_credential()
        self.adapters[self.configuration.provider].payload(self.configuration, request)
        return {"configuration": self.configuration.model_dump(), "request": request.model_dump()}

    def _resolve(self, parameters):
        config = ImageConfiguration.model_validate(parameters["configuration"])
        credential = self.require_credential(config)
        return config, self.adapters[config.provider], {"Authorization": f"Bearer {credential}"}

    async def submit(self, parameters):
        config, adapter, headers = self._resolve(parameters)
        return await adapter.submit(
            self.client, config, ImageRequest.model_validate(parameters["request"]), headers
        )

    async def query(self, task_id, parameters):
        config, adapter, headers = self._resolve(parameters)
        return await adapter.query(self.client, config, task_id, headers)

    async def download(self, url):
        # 下载地址不携带供应商授权头，流式读取控制实际下载大小。
        async with self.client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            result = bytearray()
            async for chunk in response.aiter_bytes():
                result.extend(chunk)
                if len(result) > 32 * 1024 * 1024:
                    raise ValueError("Generated image exceeds download limit")
            return bytes(result)

    async def close(self):
        await self.client.aclose()
