"""DDL, seed and 95-checks on a real Postgres (marker db, UC1-BUILD-SPEC 5, 13.1).

Uses its own scratch DB from WP-A's ``scratch_db_factory`` (unique DB and role prefix,
dropped at session end), so re-seeding here never disturbs other packages' tests.
The factory already runs 00..40, the generated seeds and 95-checks.sql once.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
import pytest

pytestmark = pytest.mark.db

DDL_FILES = ("00-roles.sql", "10-pos.sql", "20-wws.sql", "30-loyalty.sql",
             "31-loyalty-uc1.sql", "40-engine.sql")
SEED_FILES = ("90-seed-wws.sql", "91-seed-loyalty.sql", "92-seed-pos.sql")

# catalog and data of the four schemas; equal before and after a run = idempotent
FINGERPRINT = """
with nsp as (
  select oid, nspname from pg_namespace where nspname in ('pos','wws','loyalty','engine')),
cat as (
  select format('nsp %s %s %s', n.nspname, pg_get_userbyid(p.nspowner), p.nspacl) as x
    from nsp n join pg_namespace p on p.oid = n.oid
  union all
  select format('rel %s %s %s %s', c.oid::regclass, c.relkind, pg_get_userbyid(c.relowner),
                coalesce(c.relacl::text, ''))
    from pg_class c join nsp n on n.oid = c.relnamespace
  union all
  select format('col %s.%s %s %s %s', a.attrelid::regclass, a.attname,
                format_type(a.atttypid, a.atttypmod), a.attnotnull,
                coalesce(pg_get_expr(d.adbin, d.adrelid), ''))
    from pg_attribute a join pg_class c on c.oid = a.attrelid
    join nsp n on n.oid = c.relnamespace
    left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
   where a.attnum > 0 and not a.attisdropped
  union all
  select format('con %s %s %s', conrelid::regclass, conname, pg_get_constraintdef(c.oid))
    from pg_constraint c join nsp n on n.oid = c.connamespace
  union all
  select format('idx %s', pg_get_indexdef(i.indexrelid))
    from pg_index i join pg_class c on c.oid = i.indexrelid
    join nsp n on n.oid = c.relnamespace
  union all
  select format('roleset %s', s.setconfig) from pg_db_role_setting s
   where s.setdatabase = (select oid from pg_database where datname = current_database())),
tabs as (
  select c.oid::regclass::text as t from pg_class c join nsp n on n.oid = c.relnamespace
   where c.relkind = 'r'),
dat as (
  select t, (xpath('/row/h/text()', query_to_xml(format(
           'select count(*) || '':'' || md5(coalesce(string_agg(x::text, ''|'' '
           'order by x::text), '''')) as h from %s x', t), false, true, '')))[1]::text as h
    from tabs)
select (select md5(string_agg(x, E'\\n' order by x)) from cat) as ddl,
       (select string_agg(t || '=' || h, E'\\n' order by t) from dat) as data
"""


def fingerprint(conninfo: str) -> tuple[str, dict[str, str]]:
    with psycopg.connect(conninfo, autocommit=True) as conn:
        row = conn.execute(FINGERPRINT).fetchone()
    assert row is not None
    ddl, data = row
    return ddl, dict(line.split("=", 1) for line in data.splitlines())


@pytest.fixture(scope="module")
def own_db(scratch_db_factory: Callable[..., Any], sql_dir: Path) -> Any:
    files = sorted(sql_dir.glob("*.sql"))
    assert [f.name for f in files] == [*DDL_FILES, "95-checks.sql"]
    return scratch_db_factory(files, seed=True)


def test_factory_ran_ddl_seed_and_checks(own_db: Any) -> None:
    assert own_db.files == [*DDL_FILES, *SEED_FILES, "95-checks.sql"]


def test_seed_row_counts(own_db: Any) -> None:
    _, data = fingerprint(own_db.admin_dsn)
    counts = {table: int(h.split(":", 1)[0]) for table, h in data.items()}
    assert {t: n for t, n in counts.items() if n} == {
        "wws.season": 3, "wws.article": 30, "wws.article_price": 60,
        "wws.price_history": 64, "wws.price_action": 2, "wws.sales_plan": 60,
        "wws.sales_daily": 2880, "wws.stock": 60, "wws.inbound_delivery": 2,
        "loyalty.program": 1, "loyalty.article_ref": 30, "loyalty.tag_vocabulary": 10,
        "loyalty.member": 5, "loyalty.card": 5, "loyalty.consent": 5,
        "loyalty.member_tag": 8, "loyalty.account": 5,
        "loyalty.purchase": 52,        # 12 + 13 + 12 + 15 + 0 (5.7)
        "loyalty.purchase_line": 128,  # 34 + 73 + 0 + 21 + 0 (M-1003 without profiling)
        "loyalty.article_week_stats": 240, "pos.till": 3}


def test_ddl_and_seed_rerun_change_nothing(own_db: Any, sql_dir: Path) -> None:
    before = fingerprint(own_db.admin_dsn)
    for name in DDL_FILES:
        own_db.psql_file(sql_dir / name)
    own_db.reseed()
    own_db.psql_file(sql_dir / "95-checks.sql")
    assert fingerprint(own_db.admin_dsn) == before


def test_checks_reject_a_deviation_from_the_golden_values(own_db: Any, sql_dir: Path) -> None:
    with psycopg.connect(own_db.admin_dsn, autocommit=True) as conn:
        conn.execute("update wws.stock set on_hand = 95 "
                     "where article_number = '100001' and store_id = '101'")
    try:
        with pytest.raises(RuntimeError, match=r"95-checks: \d+ of \d+ checks failed") as exc:
            own_db.psql_file(sql_dir / "95-checks.sql")
        assert 'S1 100001 sold/plan, sell_through, avg 28d, stock, weeks of supply: ' \
               'expected "9/35 0.26 14.75 96 6.5", got "9/35 0.26 14.75 95 6.4"' in str(exc.value)
    finally:
        own_db.reseed()
    own_db.psql_file(sql_dir / "95-checks.sql")


def test_service_roles_and_search_path(own_db: Any) -> None:
    with psycopg.connect(own_db.dsn("wws"), autocommit=True) as conn:
        assert conn.execute("select count(*) from article").fetchone() == (30,)
    with psycopg.connect(own_db.dsn("engine"), autocommit=True) as conn:
        assert conn.execute("select count(*) from pos.till").fetchone() == (3,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("insert into pos.till values ('97', '199', 'x', 'test', true)")
    with psycopg.connect(own_db.dsn("pos"), autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select count(*) from wws.article")
    with psycopg.connect(own_db.dsn("loyalty"), autocommit=True) as conn:
        assert conn.execute(
            "select segment_label from member where member_id = 'M-1001'").fetchone() == (
            "Stammkundin, preisbewusst",)


def test_one_open_proposal_per_till_and_uc1_columns(own_db: Any) -> None:
    review = ("insert into engine.review (review_id, tx_id, store_id, till_id, status) "
              "values (%s, gen_random_uuid(), '199', '99', 'prepared')")
    proposal = (
        "insert into engine.proposal (proposal_id, review_id, tx_id, store_id, till_id, "
        "article_number, article_name, reason, step_requested, step_pct, regular_price, "
        "new_price, ref30, pct_shown, margin_pct_new, valid_from, valid_to, headline, "
        "rationale, facts_line, text_source, guardrails, proposal_hash, status) values "
        "(%s, %s, gen_random_uuid(), '199', '99', '100001', 'GEBIT Ente', 'slow_seller', "
        "20, 20, 9.99, 7.99, 9.99, 20, 22.6, now(), now() + interval '7 days', 'h', 'r', "
        "'f', 'ai', '[]', 'abc', %s)")
    with psycopg.connect(own_db.dsn("engine")) as conn:
        try:
            for i, status in enumerate(("approved", "ready")):
                conn.execute(review, (f"GR-TEST-{i}",))
                conn.execute(proposal, (f"GP-TEST-{i}", f"GR-TEST-{i}", status))
            conn.execute(review, ("GR-TEST-2",))
            with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
                conn.execute(proposal, ("GP-TEST-2", "GR-TEST-2", "pending"))
            conn.execute("insert into engine.approval (proposal_id, run_id, checked_at) "
                         "values ('GP-TEST-1', 'run-1', now())")
            row = conn.execute(
                "select p.note, a.apply_calls, a.sam_error_at from engine.proposal p "
                "join engine.approval a using (proposal_id) "
                "where p.proposal_id = 'GP-TEST-1'").fetchone()
        finally:
            conn.rollback()
    assert row == ("", 0, None)
