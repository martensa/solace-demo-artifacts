"""Graceful shutdown for the bridge (Wave 5 / #13).

The long-running bridge modes (polling, solace) install SIGTERM/SIGINT
handlers that flip a stop event; once the loop drains, :func:`shutdown`
runs the ordered teardown: flush the dedupe store, drain the write-back
queue (deferred to Wave 4.5, hence import-guarded), and close the EP + OM
clients. Every step is best-effort and isolated -- one failing teardown
must not skip the others, and shutdown must never raise.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def shutdown(
    *,
    ep_client: Any = None,
    om: Any = None,
    dedupe: Any = None,
    grace_seconds: int = 10,
) -> Dict[str, bool]:
    """Tear down bridge resources in order. Returns a summary of what ran.

    Safe to call from a ``finally`` block. ``grace_seconds`` bounds the
    (future) write-back queue drain; the other steps are fast and
    synchronous.
    """
    summary = {
        "dedupe_flushed": False,
        "writeback_drained": False,
        "ep_closed": False,
        "om_closed": False,
    }
    logger.info("Graceful shutdown started (grace=%ds)", grace_seconds)

    summary["dedupe_flushed"] = _flush_dedupe(dedupe)
    summary["writeback_drained"] = _drain_writeback(grace_seconds)
    summary["ep_closed"] = _close("Event Portal client", ep_client)
    summary["om_closed"] = _close("OpenMetadata client", om)

    logger.info("Graceful shutdown complete: %s", summary)
    return summary


def _flush_dedupe(dedupe: Any) -> bool:
    if dedupe is None or not hasattr(dedupe, "flush"):
        return False
    try:
        dedupe.flush()
        return True
    except Exception:  # noqa: BLE001 - never let teardown raise
        logger.warning("dedupe flush failed during shutdown", exc_info=True)
        return False


def _drain_writeback(grace_seconds: int) -> bool:
    """Drain the OM->EP write-back queue if write-back is present.

    Write-back is Wave 4.5 / #49 (deferred); ``bridge.writeback`` does not
    exist in 0.9.0, so the import guard makes this a clean no-op. When the
    module lands it only needs to expose ``drain(timeout)``.
    """
    try:
        from . import writeback  # type: ignore
    except ImportError:
        return False
    drain = getattr(writeback, "drain", None)
    if drain is None:
        return False
    try:
        drain(grace_seconds)
        return True
    except Exception:  # noqa: BLE001 - never let teardown raise
        logger.warning("write-back drain failed during shutdown", exc_info=True)
        return False


def _close(label: str, client: Optional[Any]) -> bool:
    if client is None or not hasattr(client, "close"):
        return False
    try:
        client.close()
        return True
    except Exception:  # noqa: BLE001 - never let teardown raise
        logger.warning("%s close failed during shutdown", label, exc_info=True)
        return False
