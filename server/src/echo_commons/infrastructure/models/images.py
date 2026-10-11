from typing import Literal

import httpx
from pydantic import BaseModel, Field


class SubmittedTask(BaseModel):
    task_id: str = Field(min_length=1)


class SubmitResponse(BaseModel):
    code: Literal[200]
    data: list[SubmittedTask] = Field(min_length=1, max_length=1)


class ResultImage(BaseModel):
    url: list[str] = Field(min_length=1)


class TaskResult(BaseModel):
    images: list[ResultImage] = Field(default_factory=list)


class ProviderTask(BaseModel):
    id: str
    status: Literal["pending", "processing", "completed", "failed", "cancelled"]
    result: TaskResult | None = None


class TaskResponse(BaseModel):
    code: Literal[200]
    data: ProviderTask


class ImageGateway:
    def __init__(self, base_url: str, credential: str | None, timeout: float):
        self.base_url, self.credential = base_url.rstrip("/"), credential
        self.client = httpx.AsyncClient(timeout=timeout)

    def require_credential(self):
        if not self.credential or not self.credential.strip():
            raise ImageModelUnavailable("Image generation credentials are not configured")

    def headers(self):
        self.require_credential()
        return {"Authorization": f"Bearer {self.credential}"}

    async def submit(self, parameters):
        response = await self.client.post(
            f"{self.base_url}/images/generations", headers=self.headers(), json=parameters
        )
        response.raise_for_status()
        return SubmitResponse.model_validate(response.json()).data[0].task_id

    async def query(self, task_id):
        response = await self.client.get(f"{self.base_url}/tasks/{task_id}", headers=self.headers())
        response.raise_for_status()
        task = TaskResponse.model_validate(response.json()).data
        if task.id != task_id:
            raise ValueError("Provider returned a different task")
        return task

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


class ImageModelUnavailable(ValueError):
    code = "image_model_unavailable"
