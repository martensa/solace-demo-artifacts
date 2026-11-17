"""``python -m gposdemo.loyalty [--dump-tools]`` (UC1-BUILD-SPEC 2.4, 8.5).

``run()`` = ``create(...)``, ``start()``, then MCP blocking on ``MCP_PORT``.
``--dump-tools`` prints ``tools/list`` and exits without settings, DB, bus or
descriptors (the tool list is static).
"""

from __future__ import annotations

import contextlib
import logging
import signal
import sys
from types import FrameType

from gposdemo.common import log, mcputil
from gposdemo.common.bus import make_bus
from gposdemo.common.config import load_settings
from gposdemo.common.db import Db

from . import SERVICE, create
from .tools import build_mcp

logger = logging.getLogger("gposdemo.loyalty")


def _exit_on_sigterm(_signum: int, _frame: FrameType | None) -> None:
    """uvicorn re-raises SIGTERM after its graceful shutdown; leaving with ``SystemExit(0)``
    lets the ``finally`` blocks stop gRPC and close bus and DB (pod stop)."""
    raise SystemExit(0)


def run() -> int:
    """Serve gpos-loyalty until the process is stopped (SIGTERM ends it cleanly)."""
    signal.signal(signal.SIGTERM, _exit_on_sigterm)
    settings = load_settings(SERVICE)
    log.configure(settings.log_level, SERVICE)
    if not settings.dsn:
        logger.error("GPOS_DSN is not set (Secret gpos-db, key DSN_LOYALTY)")
        return 2
    with contextlib.ExitStack() as cleanup:
        db = Db(settings.dsn, application_name="gpos-loyalty")
        cleanup.callback(db.close)
        bus = make_bus(settings, "gpos-loyalty")
        cleanup.callback(bus.close)
        app = create(settings, bus, db)
        app.start()
        cleanup.callback(app.stop)
        logger.info("gRPC LoyaltyService on port %d", app.grpc_port)
        mcputil.run(app.mcp, settings.mcp_port)
    return 0


def main() -> int:
    """Entry point of the container command."""
    if mcputil.wants_dump_tools():
        mcputil.dump_tools(build_mcp(None, None))
        return 0
    return run()


if __name__ == "__main__":
    sys.exit(main())
