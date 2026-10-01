from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import UUID

from echo_commons.app.settings import Settings

LOGGER_NAME = "echo_commons"
MAX_FIELD_LENGTH = 256

_base_logger = logging.getLogger(LOGGER_NAME)
if not any(isinstance(handler, logging.NullHandler) for handler in _base_logger.handlers):
    # Library-style imports stay quiet until the application explicitly configures output.
    _base_logger.addHandler(logging.NullHandler())

# Keeping this list explicit prevents a future call site from accidentally
# putting player text, prompts, or model output into an operational log.
ALLOWED_FIELDS = frozenset(
    {
        "request_id",
        "correlation_id",
        "task_id",
        "proposal_id",
        "message_id",
        "client_msg_id",
        "agent_id",
        "worker_id",
        "attempt_count",
        "duration_ms",
        "error_code",
        "error_type",
        "context_version",
        "status_code",
        "method",
        "path",
        "batch_size",
        "retryable",
        "retry_delay_seconds",
        "server_version",
        "recovered_count",
        "run_status",
        "stop_reason",
        "harness_version",
        "model_profile",
        "status",
        "step_count",
        "tool_call_count",
        "model_request_count",
        "invocation_id",
        "provider",
        "access_route",
        "model_vendor",
        "model",
        "provider_attempt",
        "input_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "output_tokens",
        "total_tokens",
        "cache_hit_ratio",
        "provider_model_request_count",
        "provider_cache_hit_ratio",
        "ttft_ms",
        "response_kind",
        "finish_reason",
    }
)


class JsonLogFormatter(logging.Formatter):
    """Render one bounded JSON object per line for console and file output."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.now(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
        }
        for field in ALLOWED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                entry[field] = value
        if record.exc_info is not None:
            entry["error_type"] = record.exc_info[0].__name__
            entry["traceback"] = "".join(traceback.format_tb(record.exc_info[2]))
        return json.dumps(entry, ensure_ascii=False, separators=(",", ":"))


def get_logger(component: str | None = None) -> logging.Logger:
    """Return a child logger under the service-owned logger namespace."""

    name = LOGGER_NAME if not component else f"{LOGGER_NAME}.{component}"
    return logging.getLogger(name)


def close_logging() -> None:
    _remove_owned_handlers(get_logger())


def configure_logging(settings: Settings) -> logging.Logger:
    """Configure owned handlers once per application configuration.

    The service owns only the ``echo_commons`` logger.  Uvicorn and third-party
    loggers are left alone so importing the application does not reconfigure a
    host process unexpectedly.
    """

    logger = get_logger()
    logger.setLevel(_resolve_level(settings.log_level))
    logger.propagate = False
    _remove_owned_handlers(logger)

    formatter = JsonLogFormatter()
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    _mark_owned(console_handler)
    logger.addHandler(console_handler)

    if settings.log_path:
        try:
            log_path = Path(settings.log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=max(1, settings.log_max_bytes),
                backupCount=max(0, settings.log_backup_count),
                encoding="utf-8",
                delay=True,
            )
            file_handler.setFormatter(formatter)
            _mark_owned(file_handler)
            logger.addHandler(file_handler)
        except OSError as exc:
            # Logging failure must not prevent the game service from starting;
            # the console handler remains available as the fallback channel.
            log_event(
                logger,
                logging.WARNING,
                "logging.file_unavailable",
                error_type=exc.__class__.__name__,
            )

    return logger


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **fields: object,
) -> None:
    """Emit a redacted event with only approved scalar context fields."""

    safe_fields = {
        key: _safe_scalar(value)
        for key, value in fields.items()
        if key in ALLOWED_FIELDS and value is not None
    }
    logger.log(level, event, extra={"event": event, **safe_fields})


def _remove_owned_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, "_echo_owned", False):
            logger.removeHandler(handler)
            handler.close()


def _mark_owned(handler: logging.Handler) -> None:
    handler._echo_owned = True


def _resolve_level(level_name: str) -> int:
    level = getattr(logging, level_name.upper(), logging.INFO)
    return level if isinstance(level, int) else logging.INFO


def _safe_scalar(value: object) -> str | int | float | bool:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    return str(value)[:MAX_FIELD_LENGTH]
