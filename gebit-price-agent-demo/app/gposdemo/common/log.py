"""Logging setup of every gpos-demo process (``LOG_LEVEL``, 3.1).

One line per record on stderr: ``<time> <level> <service> <logger>: <message>``.
Libraries that log every request at INFO are lowered to WARNING.
"""

from __future__ import annotations

import logging

FORMAT = "%(asctime)s %(levelname)s {service} %(name)s: %(message)s"
QUIET_LOGGERS = ("httpx", "httpcore", "mcp.server.streamable_http", "mcp.server.lowlevel.server",
                 "uvicorn.access")


def configure(level: str = "INFO", service: str = "gpos") -> None:
    """Configure the root logger once per process (later calls replace the handlers)."""
    numeric = logging.getLevelName(level.upper())
    if not isinstance(numeric, int):
        raise ValueError(f"unknown LOG_LEVEL {level!r}")
    logging.basicConfig(level=numeric, format=FORMAT.format(service=f"gpos-{service}"),
                        force=True)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(max(numeric, logging.WARNING))
