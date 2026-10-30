import platform
import tomllib
from importlib.resources import files
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


def release_manifest() -> dict:
    return tomllib.loads(
        files("echo_commons.resources.game_analysis")
        .joinpath("rapfi.toml")
        .read_text(encoding="utf-8")
    )


class RapfiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    directory: str = "../data/game-analysis/rapfi/250615"
    executable: str | None = None
    threads: int = Field(default=1, ge=1, le=256)
    hash_memory_mb: int = Field(default=64, ge=1)
    search_time_ms: int = Field(default=500, ge=40, le=60000)
    candidates: int = Field(default=6, ge=1, le=32)
    timeout_seconds: float = Field(default=10, gt=0, allow_inf_nan=False)

    def executable_path(self) -> Path:
        name = self.executable
        if name is None:
            key = f"{platform.system().lower()}-{platform.machine().lower()}"
            name = release_manifest()["executables"].get(key)
            if name is None:
                raise ValueError(f"No bundled Rapfi executable for {key}")
        return Path(self.directory).resolve() / name


class RapfiError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class RapfiLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rank: int
    moves: tuple[tuple[int, int], ...]
    score: int | str
    depth: int
    nodes: int
    time_ms: int


class RapfiAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    best_move: tuple[int, int]
    lines: tuple[RapfiLine, ...]
    engine_version: str
    release: str
    weight: str
    budget_ms: int
    elapsed_ms: int
    threads: int
    hash_memory_mb: int
