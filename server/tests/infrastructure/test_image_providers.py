import asyncio
from pathlib import Path

import pytest

from echo_commons.infrastructure.models.image_contracts import ImageConfiguration, ImageRequest
from echo_commons.infrastructure.models.images import ImageGateway
from echo_commons.infrastructure.models.registry import load_model_registry

SERVER = Path(__file__).resolve().parents[2]


def test_frozen_image_configuration_survives_default_provider_change():
    models = load_model_registry(
        SERVER / "config/model-registry.toml", SERVER / "config/model-secrets.toml"
    )
    if not models.credentials.get("minimax"):
        pytest.skip("需要本地MiniMax凭据验证引用解析")
    original = ImageConfiguration(
        provider="minimax",
        model="MiniMax-H3-Image",
        base_url="https://api.minimax.cn/v1",
        credential_ref="minimax",
    )
    gateway = ImageGateway(original, models.credentials, 120)
    parameters = gateway.freeze(ImageRequest(prompt="原创图书馆", width=1024, height=1024))
    gateway.configuration = ImageConfiguration(
        provider="dashscope",
        model="qwen-image-3.0",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        credential_ref="dashscope",
    )
    restored, _, headers = gateway._resolve(parameters)
    assert restored == original
    assert headers["Authorization"] == "Bearer " + models.credentials["minimax"]
    assert "Authorization" not in str(parameters)
    asyncio.run(gateway.close())
