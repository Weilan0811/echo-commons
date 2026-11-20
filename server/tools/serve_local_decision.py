import argparse
from contextlib import nullcontext
from pathlib import Path

import torch
from startlux_decide.backends import bidirectional
from startlux_decide.cli import main as startlux_main
from torch.nn.attention import SDPBackend, sdpa_kernel


def attention_kernels(device):
    if device.type != "cuda":
        return nullcontext()
    # Windows的PyTorch构建可能没有融合注意力，数学内核保留相同的双向计算。
    return sdpa_kernel(
        [SDPBackend.FLASH_ATTENTION, SDPBackend.EFFICIENT_ATTENTION, SDPBackend.MATH],
        set_priority=True,
    )


def main():
    parser = argparse.ArgumentParser(description="启动StartLux Transformers本地决策服务")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--name")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--max-model-len", type=int, default=8192)
    arguments = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("此启动入口需要可用的CUDA环境")
    if not arguments.model.is_dir():
        raise ValueError("模型目录不存在")
    if arguments.max_model_len < 1 or arguments.max_model_len > 8192:
        raise ValueError("数学注意力启动入口的上下文范围为1至8192 tokens")
    # 服务进程使用兼容的内核集合，保留StartLux原有启动自检与请求协议。
    bidirectional._kernel_guard = attention_kernels
    command = [
        "serve",
        "--model",
        str(arguments.model.resolve()),
        "--backend",
        "transformers",
        "--device",
        "cuda",
        "--dtype",
        "bfloat16",
        "--host",
        arguments.host,
        "--port",
        str(arguments.port),
        "--max-model-len",
        str(arguments.max_model_len),
    ]
    if arguments.name:
        command.extend(["--name", arguments.name])
    return startlux_main(command)


if __name__ == "__main__":
    main()
