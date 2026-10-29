import asyncio
import os
import subprocess
import tomllib
from contextlib import suppress
from time import perf_counter

from echo_commons.infrastructure.game_analysis.rapfi.contracts import (
    RapfiAnalysis,
    RapfiError,
    RapfiSettings,
    release_manifest,
)
from echo_commons.infrastructure.game_analysis.rapfi.protocol import (
    AnalysisReader,
    about_version,
    position_commands,
)


class RapfiProcess:
    def __init__(self, settings: RapfiSettings):
        self.settings = settings
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._closed = False
        self._version = ""

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process and self._process.returncode is None else None

    async def _send(self, *commands: str) -> None:
        self._process.stdin.write(("\n".join(commands) + "\n").encode("ascii"))
        await self._process.stdin.drain()

    async def _read(self) -> str:
        line = await self._process.stdout.readline()
        if not line:
            raise RapfiError("process_exited", "Rapfi exited before returning a result")
        text = line.decode("utf-8", errors="replace").strip()
        if text.startswith(("ERROR", "UNKNOWN")):
            raise RapfiError("engine_rejected", text)
        return text

    async def _start(self) -> None:
        if self._closed:
            raise RapfiError("closed", "The application has closed its Rapfi process")
        if self._process is not None and self._process.returncode is None:
            return
        executable = self.settings.executable_path()
        if not executable.is_file():
            raise RapfiError("not_installed", f"Install Rapfi first: {executable}")
        root = executable.parent
        with (root / "config.toml").open("rb") as handle:
            config = tomllib.load(handle)
        if (
            config["general"]["coord_conversion_mode"] != "none"
            or config["database"]["enable_by_default"]
            or config["model"]["evaluator"]["type"] != "mix9svq"
        ):
            raise RapfiError(
                "invalid_configuration",
                "Rapfi requires native coordinates, mix9svq and no database",
            )
        starting = asyncio.create_task(
            asyncio.create_subprocess_exec(
                str(executable),
                cwd=root,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        )
        try:
            self._process = await asyncio.shield(starting)
        except asyncio.CancelledError:
            # 创建进程期间取消时也取得实际句柄，交由调用方完整回收。
            self._process = await starting
            raise
        await self._send("ABOUT")
        while not (version := about_version(await self._read())):
            pass
        if not version.startswith(release_manifest()["version_prefix"]):
            raise RapfiError("unsupported_version", f"Unsupported Rapfi version: {version}")
        self._version = version
        await self._send("START 15")
        while await self._read() != "OK":
            pass
        await self._send(
            "INFO rule 0",
            f"INFO thread_num {self.settings.threads}",
            f"INFO hash_size {self.settings.hash_memory_mb * 1024}",
            "INFO timeout_match 0",
            "INFO show_detail 2",
            "INFO pondering 0",
            "INFO caution_factor 5",
        )

    async def analyze(
        self,
        stones: tuple[tuple[int, int, int], ...],
        *,
        candidates: int,
        time_ms: int,
        blocked: tuple[tuple[int, int], ...] = (),
    ) -> RapfiAnalysis:
        async with self._lock:
            started = perf_counter()
            try:
                async with asyncio.timeout(self.settings.timeout_seconds):
                    await self._start()
                    await self._send("RESTART")
                    while await self._read() != "OK":
                        pass
                    await self._send(
                        f"INFO timeout_turn {time_ms}",
                        *position_commands(stones),
                        "YXBLOCKRESET",
                    )
                    if blocked:
                        await self._send("YXBLOCK", *(f"{x},{y}" for x, y in blocked), "DONE")
                    await self._send(f"YXNBEST {candidates}")
                    reader = AnalysisReader()
                    while (best := reader.feed(await self._read())) is None:
                        pass
                    manifest = release_manifest()
                    return RapfiAnalysis(
                        best_move=best,
                        lines=tuple(reader.lines[key] for key in sorted(reader.lines)),
                        engine_version=self._version,
                        release=manifest["release"],
                        weight=manifest["weight"],
                        budget_ms=time_ms,
                        elapsed_ms=round((perf_counter() - started) * 1000),
                        threads=self.settings.threads,
                        hash_memory_mb=self.settings.hash_memory_mb,
                    )
            except TimeoutError as error:
                await self._terminate()
                raise RapfiError(
                    "analysis_timeout", "Rapfi exceeded its request deadline"
                ) from error
            except (asyncio.CancelledError, RapfiError):
                await self._terminate()
                raise
            except (OSError, ValueError, KeyError) as error:
                await self._terminate()
                raise RapfiError("analysis_failed", str(error)) from error

    async def _terminate(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
            await process.wait()

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            if self._process is not None and self._process.returncode is None:
                try:
                    await self._send("END")
                    await asyncio.wait_for(self._process.wait(), timeout=2)
                except (TimeoutError, OSError):
                    pass
            await self._terminate()
