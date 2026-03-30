import logging
import sys
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, merge_contextvars
from structlog.types import EventDict, Processor


def add_app_context(logger: Any, method: str, event_dict: EventDict) -> EventDict:
    event_dict.setdefault("app", "agentic-purchase")
    return event_dict


def drop_color_message_key(logger: Any, method: str, event_dict: EventDict) -> EventDict:
    event_dict.pop("color_message", None)
    return event_dict


def setup_logging(log_level: str = "INFO", json_logs: bool = False) -> None:
    shared_processors: list[Processor] = [
        merge_contextvars,              # FIRST: injects bound context vars into every log line
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_app_context,
        drop_color_message_key,
        structlog.stdlib.ExtraAdder(),
    ]

    if json_logs:
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())

    # Quiet noisy libraries
    for noisy in ("httpx", "httpcore", "asyncio", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def bind_request_context(**kwargs: Any) -> None:
    """
    Bind key-value pairs to all subsequent log calls in this async context.

    Backed by structlog context vars — each asyncio task has its own copy,
    so concurrent requests never bleed into each other.

    Common usage:
        bind_request_context(saga_id=saga_id)
        bind_request_context(agent="vision", saga_id=saga_id)
    """
    bind_contextvars(**kwargs)


def clear_request_context() -> None:
    """
    Clear all context vars bound in this async context.

    Call at the end of a request or background task to prevent stale
    values from appearing on unrelated future log lines.
    """
    clear_contextvars()
