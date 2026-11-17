"""``gpos-pos``: simulator of the GEBIT Purchase API 2.50.0 (UC1-BUILD-SPEC 4.2, WP-E).

gRPC ``PurchaseTransactionService`` on port 50051 (from the runtime GEBIT descriptor
sets, never from the repo), basket state in schema ``pos``, events through the outbox,
prices from ``gpos-wws``, memberships and purchases at ``gpos-loyalty``, MCP server
``gpos-pos-api`` plus ``/health`` and ``/admin/...`` on port 8771.

``create(settings, bus, db)`` (2.4) and ``run()`` live in :mod:`gposdemo.pos.server`.
"""

from .server import PosApp, create, run

__all__ = ["PosApp", "create", "run"]
