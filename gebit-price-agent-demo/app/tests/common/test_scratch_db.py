"""The scratch_db fixture itself: WP-B's postgres/sql/* with a unique role prefix."""

from __future__ import annotations

import re
from typing import Any

import pytest

pytestmark = pytest.mark.db


def test_scratch_db_layout(scratch_db: Any) -> None:
    assert re.fullmatch(r"gpos_ut_[0-9a-f]{6}", scratch_db.role_prefix)
    assert scratch_db.name == scratch_db.role_prefix
    assert scratch_db.files[:6] == ["00-roles.sql", "10-pos.sql", "20-wws.sql",
                                    "30-loyalty.sql", "31-loyalty-uc1.sql", "40-engine.sql"]
    if scratch_db.seeded:
        assert scratch_db.files[6:] == ["90-seed-wws.sql", "91-seed-loyalty.sql",
                                        "92-seed-pos.sql", "95-checks.sql"]
    admin = scratch_db.admin_db()
    try:
        schemas = {r["nspname"] for r in admin.fetch(
            "select nspname from pg_namespace where nspname in "
            "('pos','wws','loyalty','engine')")}
        assert schemas == {"pos", "wws", "loyalty", "engine"}
        roles = {r["rolname"] for r in admin.fetch(
            "select rolname from pg_roles where starts_with(rolname, %s)",
            (scratch_db.role_prefix + "_",))}
        assert roles == {f"{scratch_db.role_prefix}_{s}" for s in
                         ("pos", "wws", "loyalty", "engine")}
    finally:
        admin.close()


@pytest.mark.parametrize(("service", "schema"), [
    ("pos", "pos"), ("wws", "wws"), ("loyalty", "loyalty"), ("engine", "engine"),
    ("gate", "engine")])
def test_service_roles_log_in_with_their_search_path(scratch_db: Any, service: str,
                                                     schema: str) -> None:
    db = scratch_db.db(service)
    try:
        row = db.fetch("select current_user as u, current_setting('search_path') as sp")[0]
        assert row["u"] == scratch_db.role(service)
        assert row["sp"] == schema
        assert db.fetch(f"select count(*) >= 0 as ok from {schema}.event_outbox"
                        if schema != "loyalty" else "select true as ok") == [{"ok": True}]
    finally:
        db.close()


def test_engine_reads_pos_but_cannot_write_it(scratch_db: Any) -> None:
    db = scratch_db.db("engine")
    try:
        assert db.fetch("select count(*) >= 0 as ok from pos.basket") == [{"ok": True}]
        with pytest.raises(Exception, match="permission denied"):
            db.fetch("delete from pos.basket")
    finally:
        db.close()
