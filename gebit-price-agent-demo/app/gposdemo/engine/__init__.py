"""``gpos-engine``: event intake, scan analysis, basket review, proposals, guardrails,
outcome, watchdog and outbox relay (UC1-BUILD-SPEC 11). The gate is the separate
service ``gposdemo.engine.gate``."""

from .app import Engine, create, run

__all__ = ["Engine", "create", "run"]
