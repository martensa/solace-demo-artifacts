"""Fixtures of the WP-F tests (engine and gate).

Unit tests (no marker) use the policy, the fictional data and the Showcase protos.
Tests marked ``db`` run engine and gate on WP-A's ``scratch_db`` against gRPC stubs of
WWS and loyalty (``fakes.py``), with an injectable clock and the in-memory bus; the
engine tables are emptied before each such test.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from google.protobuf import descriptor_pool

from gposdemo.common.bus import MemoryBus
from gposdemo.common.config import Settings
from gposdemo.common.db import Db
from gposdemo.engine import Engine
from gposdemo.engine import create as create_engine
from gposdemo.engine.gate import Gate
from gposdemo.engine.gate import create as create_gate
from gposdemo.engine.policy import Policy, load_policy
from tests.engine.fakes import (
    DATA_DIR,
    POLICY_FILE,
    Backends,
    D,
    Facts,
    FakeClock,
    PosWriter,
    Showcase,
    facts,
    gen_seed,
    start_backends,
)

ENGINE_TABLES = ("engine.event_inbox", "engine.insight", "engine.tool_call",
                 "engine.price_change", "engine.approval", "engine.proposal", "engine.review",
                 "engine.audit_event", "engine.event_outbox")


@pytest.fixture(scope="session")
def policy() -> Policy:
    return load_policy(POLICY_FILE)


@pytest.fixture(scope="session")
def sources() -> Any:
    return gen_seed().load_sources(DATA_DIR)


@pytest.fixture
def showcase(sources: Any) -> Showcase:
    return Showcase(sources, D)


@pytest.fixture
def get_facts(showcase: Showcase, showcase_pool: descriptor_pool.DescriptorPool
              ) -> Callable[..., Facts]:
    """``get_facts(number, store="101", membership_id=None)`` via the proto round trip."""

    def make(number: str, store: str = "101", membership_id: str | None = None) -> Facts:
        return facts(showcase, showcase_pool, number, store, membership_id)

    return make


# ------------------------------------------------------------------ db tests
@pytest.fixture(scope="session")
def backends(showcase_pool: descriptor_pool.DescriptorPool, sources: Any) -> Iterator[Backends]:
    running = start_backends(showcase_pool, Showcase(sources, D))
    yield running
    running.stop()


@pytest.fixture
def stubs(backends: Backends) -> Backends:
    """The stub servers with a fresh state (no booth actions, no failure switch)."""
    backends.showcase.reset()
    backends.wws.unavailable = False
    return backends


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def engine_db(scratch_db: Any) -> Iterator[Db]:
    """``Db`` as the engine role on empty engine tables (sequences keep counting)."""
    admin = scratch_db.admin_db()
    admin.fetch(f"truncate {', '.join(ENGINE_TABLES)}")
    admin.close()
    db = scratch_db.db("engine", max_size=4)
    yield db
    db.close()


@pytest.fixture
def pos(scratch_db: Any, stubs: Backends) -> Iterator[PosWriter]:
    db = scratch_db.db("pos", max_size=2)
    yield PosWriter(db, stubs.showcase)
    db.close()


@pytest.fixture
def service_settings(make_settings: Callable[..., Settings], scratch_db: Any,
                     stubs: Backends) -> Callable[..., Settings]:
    """``service_settings("engine"|"gate", **ENV)`` pointing at the stubs and scratch DB."""

    def make(service: str, **env: str) -> Settings:
        return make_settings(service, WWS_GRPC=stubs.wws_target,
                             LOYALTY_GRPC=stubs.loyalty_target,
                             GPOS_DSN=scratch_db.dsn(service), **env)

    return make


@pytest.fixture
def engine(service_settings: Callable[..., Settings], memory_bus: MemoryBus, engine_db: Db,
           clock: FakeClock) -> Iterator[Engine]:
    """Engine on the scratch DB; threads not started (tests drive watchdog and relay)."""
    app = create_engine(service_settings("engine"), memory_bus, engine_db, clock=clock)
    yield app
    app.stop()


@pytest.fixture
def make_gate(service_settings: Callable[..., Settings], memory_bus: MemoryBus,
              engine_db: Db, clock: FakeClock) -> Iterator[Callable[..., Gate]]:
    """``make_gate(**ENV)``: a gate on the same DB (e.g. ``GATE_GUARD="f2"``)."""
    made: list[Gate] = []

    def make(**env: str) -> Gate:
        gate = create_gate(service_settings("gate", **env), memory_bus, engine_db,
                           clock=clock)
        made.append(gate)
        return gate

    yield make
    for gate in made:
        gate.stop()


@pytest.fixture
def gate(make_gate: Callable[..., Gate]) -> Gate:
    return make_gate()
