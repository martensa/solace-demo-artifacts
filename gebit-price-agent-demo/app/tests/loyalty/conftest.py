"""Fixtures of the gpos-loyalty tests (WP-D, UC1-BUILD-SPEC 13.1).

``loyalty_app`` runs the real service (``create(settings, bus, db)``) on the seeded
scratch DB of WP-A with gRPC on a free port; ``client`` talks to it through the
runtime Showcase pool. Tests that change data use ``restore`` so the shared session
DB is back at its seed state afterwards (day reset: runtime purchases deleted, seed
consents restored). Helpers live in ``tests.loyalty.helpers``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from google.protobuf import descriptor_pool

from gposdemo.common import grpcutil
from gposdemo.common.bus import MemoryBus
from gposdemo.common.config import Settings
from gposdemo.common.db import Db
from gposdemo.common.descriptors import LOYALTY_SVC
from gposdemo.loyalty import LoyaltyApp, create


@pytest.fixture(scope="session")
def loyalty_settings(make_settings: Callable[..., Settings]) -> Settings:
    """Settings of service ``loyalty`` with gRPC on a free port."""
    return make_settings("loyalty", GRPC_PORT="0")


@pytest.fixture(scope="session")
def loyalty_db(scratch_db: Any) -> Iterator[Db]:
    """Pool logged in as the loyalty role of the seeded scratch DB."""
    db = scratch_db.db("loyalty")
    yield db
    db.close()


@pytest.fixture(scope="session")
def telemetry_bus() -> MemoryBus:
    """Bus of the running app; tests ``clear()`` it before they look at telemetry."""
    return MemoryBus()


@pytest.fixture(scope="session")
def loyalty_app(loyalty_settings: Settings, telemetry_bus: MemoryBus, loyalty_db: Db
                ) -> Iterator[LoyaltyApp]:
    """The real service on the scratch DB, gRPC started."""
    app = create(loyalty_settings, telemetry_bus, loyalty_db)
    app.start()
    yield app
    app.stop()


@pytest.fixture(scope="session")
def client(loyalty_app: LoyaltyApp, showcase_pool: descriptor_pool.DescriptorPool
           ) -> Iterator[grpcutil.Client]:
    """gRPC client of the running ``LoyaltyService``."""
    c = grpcutil.Client(showcase_pool, LOYALTY_SVC, f"localhost:{loyalty_app.grpc_port}")
    yield c
    c.close()


@pytest.fixture
def restore(loyalty_app: LoyaltyApp) -> Iterator[None]:
    """After the test: day reset (runtime purchases gone, seed consents back)."""
    yield
    loyalty_app.service.reset_demo_state("booth", True, "pytest")
