"""Solace Event Portal -> OpenMetadata webhook bridge.

Listens for Event Portal change notifications (either over HTTPS directly
or off a Solace topic) and applies the deltas to OpenMetadata via the
ometa SDK. Shares mapping logic with `connector.mappers` so the bridge and
the daily reconciliation pull cannot drift.
"""
__version__ = "0.1.0"
