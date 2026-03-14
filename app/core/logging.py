"""
Structured JSON logging for production observability.
Every log line is parseable by Datadog / CloudWatch / Loki.
"""
import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor


def add_app_info(
    logger: logging.Logger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    from app.core.config import get_settings

    settings = get_settings()
    event_dict["app"] = settings.APP_NAME
    event_dict["version"] = settings.APP_VERSION
    event_dict["env"] = settings.ENVIRONMENT
    return event_dict


def configure_logging(debug: bool = False) -> None:
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_app_info,
        structlog.processors.StackInfoRenderer(),
    ]

    if debug:
        renderer: Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

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
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
