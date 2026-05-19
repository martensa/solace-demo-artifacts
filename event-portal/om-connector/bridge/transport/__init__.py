"""Transport implementations for the bridge.

A transport is anything that turns inbound webhook payloads into calls to
the dispatcher. Both transports share the same Dispatcher + handlers and
the same Event Portal client; only the ingress shape differs.
"""
from .http import build_http_app
from .solace import run_solace_consumer

__all__ = ["build_http_app", "run_solace_consumer"]
