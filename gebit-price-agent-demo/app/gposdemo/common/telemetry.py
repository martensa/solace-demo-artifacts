"""Tool-call telemetry of all MCP servers (UC1-BUILD-SPEC 7.2, 8.1).

Every tool call publishes ``gpos/v1/telemetry/tool/{service}/{tool}`` (class
``telemetry``, always Direct, straight to the bus, not through an outbox). Engine and
gate pass their ``Db`` and additionally write ``engine.tool_call``. A failure in this
path is logged and never breaks the tool.
"""

from __future__ import annotations

import logging

from . import topics
from .bus import Bus
from .clock import DEFAULT_TZ, iso_ts
from .db import Db
from .jsonutil import compact

log = logging.getLogger(__name__)

SUMMARY_MAX = 120


def shorten(text: str, limit: int = SUMMARY_MAX) -> str:
    """One line of at most ``limit`` characters, cut with ``…``."""
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


class Telemetry:
    """Publisher of ``tool_call`` events for one service (``pos``, ``wws``, ``loyalty``,
    ``engine``, ``gate``)."""

    def __init__(self, bus: Bus, service: str, db: Db | None = None, *, tz: str = DEFAULT_TZ):
        self.bus = bus
        self.service = service
        self.db = db
        self.tz = tz

    def payload(self, tool: str, caller: str, run_id: str, ref: str, ms: int, ok: bool,
                summary: str) -> dict[str, object]:
        """The event body of 7.2 (keys in this order)."""
        return {"schema_version": "1", "type": "tool_call", "ts": iso_ts(tz=self.tz),
                "service": self.service, "tool": tool, "caller": caller, "ref": ref,
                "run_id": run_id, "ms": ms, "ok": ok, "summary": shorten(summary)}

    def tool_call(self, tool: str, caller: str, run_id: str, ref: str, ms: int, ok: bool,
                  summary: str) -> None:
        """Publish one ``tool_call`` event (and write ``engine.tool_call`` with a db).

        Never raises.
        """
        try:
            body = self.payload(tool, caller, run_id, ref, ms, ok, summary)
            self.bus.publish(
                topics.telemetry_tool(self.service, tool), compact(body),
                props={"eventType": "tool_call", "source": f"gpos-{self.service}",
                       "apiVersion": "gpos-v1", "traceId": ref or run_id})
        except Exception:  # noqa: BLE001 - telemetry must never break a tool
            log.warning("telemetry publish %s/%s failed", self.service, tool, exc_info=True)
        if self.db is None:
            return
        try:
            self.db.fetch(
                "insert into engine.tool_call (service, tool, caller, run_id, ref, ms, ok, "
                "summary) values (%s, %s, %s, %s, %s, %s, %s, %s)",
                (self.service, tool, caller, run_id or None, ref or None, ms, ok,
                 shorten(summary)))
        except Exception:  # noqa: BLE001 - telemetry must never break a tool
            log.warning("engine.tool_call insert %s/%s failed", self.service, tool,
                        exc_info=True)
