"""Fixtures of the gpos-wws tests (WP-C).

``articles`` reads ``data/articles.yaml`` (the seed source) for unit tests. The ``db``
fixtures run gpos-wws against the session scratch DB of WP-A (seeded for 2027-02-16):
``wws_app`` is one ``create(settings, bus, db)`` per module with the gRPC server
started on a free port and the relay *not* started (tests drain it explicitly), and
``clean_wws`` restores the seeded price-action state after every test.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from google.protobuf.descriptor_pool import DescriptorPool

from gposdemo.common import grpcutil
from gposdemo.common.bus import MemoryBus
from gposdemo.common.config import Settings
from gposdemo.common.db import Db
from gposdemo.common.descriptors import WWS_SVC
from gposdemo.wws import WwsApp, create

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data"


@pytest.fixture(scope="session")
def articles() -> dict[str, dict[str, Any]]:
    """``data/articles.yaml`` by article number; numbers as ``Decimal`` (5.7)."""
    raw = yaml.safe_load((DATA / "articles.yaml").read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for item in raw:
        entry = dict(item)
        for key in ("price", "cost", "plan", "vat", "qty"):
            entry[key] = Decimal(str(entry[key]))
        out[str(entry["number"])] = entry
    return out


@pytest.fixture(scope="module")
def wws_bus() -> Iterator[MemoryBus]:
    bus = MemoryBus()
    yield bus
    bus.close()


@pytest.fixture(scope="module")
def wws_db(scratch_db: Any) -> Iterator[Db]:
    """``Db`` logged in as the wws role of the scratch DB."""
    db = scratch_db.db("wws", max_size=4)
    yield db
    db.close()


@pytest.fixture(scope="module")
def admin_db(scratch_db: Any) -> Iterator[Db]:
    """Superuser ``Db`` for assertions and cleanup."""
    db = scratch_db.admin_db()
    yield db
    db.close()


@pytest.fixture(scope="module")
def wws_settings(make_settings: Callable[..., Settings], scratch_db: Any) -> Settings:
    """Service settings: store 199 for the agent tools, free gRPC port."""
    return make_settings("wws", GPOS_DSN=scratch_db.dsn("wws"), GRPC_PORT="0")


@pytest.fixture(scope="module")
def wws_app(wws_settings: Settings, wws_bus: MemoryBus, wws_db: Db) -> Iterator[WwsApp]:
    app = create(wws_settings, wws_bus, wws_db)
    app.grpc_server.start()
    yield app
    app.grpc_server.stop(0).wait()


@pytest.fixture(scope="module")
def client(wws_app: WwsApp, showcase_pool: DescriptorPool) -> Iterator[grpcutil.Client]:
    """gRPC client of ``MerchandiseService`` on the module's server."""
    c = grpcutil.Client(showcase_pool, WWS_SVC, f"localhost:{wws_app.grpc_port}")
    yield c
    c.close()


def restore_seed_actions(admin: Db) -> None:
    """Back to the seeded action state: no booth actions, central actions open, empty
    outbox and audit."""
    admin.fetch("delete from wws.price_action where kind = 'BOOTH'")
    admin.fetch("update wws.price_action set ended_at = null, end_reason = null "
                "where kind = 'CENTRAL'")
    admin.fetch("truncate wws.event_outbox, wws.audit")


@pytest.fixture
def clean_wws(admin_db: Db, wws_bus: MemoryBus) -> Iterator[None]:
    """Seeded action state before and after the test, empty bus record."""
    restore_seed_actions(admin_db)
    wws_bus.clear()
    yield
    restore_seed_actions(admin_db)
