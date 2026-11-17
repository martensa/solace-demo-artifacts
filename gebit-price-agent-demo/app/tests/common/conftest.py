"""Fixtures of the WP-A tests: a tiny scratch DB with one outbox schema ``ut``."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from gposdemo.common.db import Db

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def ut_scratch(scratch_db_factory: Callable[..., Any]) -> Any:
    """Throwaway DB with schema ``ut`` (outbox form of 5.1), role ``<prefix>_ut``."""
    return scratch_db_factory([FIXTURES / "outbox.sql"])


@pytest.fixture
def ut_db(ut_scratch: Any) -> Iterator[Db]:
    """``Db`` as role ``<prefix>_ut`` on an empty ``ut.event_outbox``."""
    db = ut_scratch.db("ut", max_size=4)
    db.fetch("truncate ut.event_outbox restart identity")
    yield db
    db.close()
