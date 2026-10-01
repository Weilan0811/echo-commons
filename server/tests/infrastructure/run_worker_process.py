import argparse
import asyncio

from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.app.settings import load_settings


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--secrets", required=True)
    arguments = parser.parse_args()
    settings = load_settings().model_copy(
        update={
            "database_path": arguments.database,
            "log_path": arguments.log,
            "model_registry_path": arguments.registry,
            "model_secrets_path": arguments.secrets,
            "worker_enabled": True,
            "model_concurrency": 1,
            "lease_seconds": 10,
            "lease_heartbeat_interval_seconds": 1,
            "lease_safety_margin_seconds": 1,
            "worker_poll_interval_seconds": 0.03,
            "quiet_window_seconds": 0,
        }
    )
    async with application_lifecycle(settings):
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
