"""Shared fixtures of all gpos-demo test packages (WP-A, UC1-BUILD-SPEC 13.1).

Fixtures
  settings            ``Settings`` of service ``"test"`` (GPOS_BUS=memory, store 199 tools,
                      demo date 2027-02-16, local Showcase descriptor set)
  make_settings       ``make_settings(service, **ENV) -> Settings`` with env overrides
  memory_bus          fresh ``MemoryBus`` per test
  showcase_set        path of the Showcase descriptor set (built from ``proto/`` if stale)
  showcase_pool       ``DescriptorPool`` of that set
  gebit_pool          ``DescriptorPool`` of the GEBIT sets (skips without them)
  scratch_db          session DB with ``postgres/sql/*`` and the generated seed (marker db)
  scratch_db_factory  ``factory(sql_files, seed=False) -> ScratchDb`` for own schemas
  solace_settings     ``Settings`` for the lab broker solace-1 (marker integration)

Postgres: the host container ``postgres`` (``PG_CONTAINER``) on ``localhost:5432``
(``PG_HOST``/``PG_PORT``). The superuser credentials are read from the container's
environment at runtime and never printed. Every scratch DB gets a unique name and a
unique role prefix ``gpos_ut_<6 hex>``, so parallel sessions never collide; DB and
roles are dropped at session end. Without a reachable container the fixtures skip.

Markers: ``gebit`` tests are skipped when the GEBIT descriptor sets are not found
(``GEBIT_DESCRIPTOR_SETS`` = os.pathsep-separated files, or ``GEBIT_DESCRIPTOR_DIR``
with ``purchase-api-2.50.0.pb`` and ``receipt-api-2.13.0.pb``). They are read at
runtime only and never copied.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import psycopg
import pytest
from google.protobuf import descriptor_pool
from psycopg import sql
from psycopg.conninfo import make_conninfo

from gposdemo.common import protoc
from gposdemo.common.bus import MemoryBus
from gposdemo.common.config import Settings, load_settings
from gposdemo.common.db import Db
from gposdemo.common.descriptors import load_pool

REPO = Path(__file__).resolve().parents[2]
SQL_DIR = REPO / "postgres" / "sql"
GEN_SEED = REPO / "postgres" / "gen_seed.py"
BSG_ENV = REPO.parent / "bsg-trading-desk-demo" / ".env"
GEBIT_FILES = ("purchase-api-2.50.0.pb", "receipt-api-2.13.0.pb")
SERVICE_ROLES = {"pos": "pos", "wws": "wws", "loyalty": "loyalty", "engine": "engine",
                 "gate": "engine"}
DEMO_DATE = "2027-02-16"


# --------------------------------------------------------------------------- GEBIT
def gebit_descriptor_sets() -> list[str]:
    """GEBIT descriptor files from the environment, or ``[]`` when any is missing."""
    raw = os.environ.get("GEBIT_DESCRIPTOR_SETS", "").strip()
    if raw:
        paths = [os.path.expanduser(p) for p in raw.split(os.pathsep) if p.strip()]
    elif os.environ.get("GEBIT_DESCRIPTOR_DIR", "").strip():
        folder = Path(os.path.expanduser(os.environ["GEBIT_DESCRIPTOR_DIR"].strip()))
        paths = [str(folder / name) for name in GEBIT_FILES]
    else:
        return []
    return paths if paths and all(Path(p).is_file() for p in paths) else []


def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("gebit") and not gebit_descriptor_sets():
        pytest.skip("GEBIT descriptor sets not found "
                    "(set GEBIT_DESCRIPTOR_SETS or GEBIT_DESCRIPTOR_DIR)")


# --------------------------------------------------------------------------- settings
@pytest.fixture(scope="session")
def showcase_set() -> Path:
    """Local Showcase descriptor set (``build/descriptors/showcase.pb``), fresh."""
    return protoc.ensure_local()


@pytest.fixture(scope="session")
def make_settings(showcase_set: Path) -> Callable[..., Settings]:
    """``make_settings(service="test", **ENV)``: test settings with env overrides."""
    base = {
        "GPOS_DEMO_DATE": DEMO_DATE, "GPOS_TZ": "Europe/Berlin", "GPOS_COUNTRY": "DE",
        "GPOS_COMPANY": "999", "GPOS_BOOTH_LOCATION": "Root.DE.999.101.01",
        "GPOS_TEST_LOCATION": "Root.DE.999.199.99",
        "GPOS_PROBE_LOCATION": "Root.DE.999.199.98", "GPOS_DELIVERY": "direct",
        "GPOS_BUS": "memory", "GPOS_TOOL_STORE": "199",
        "SHOWCASE_DESCRIPTOR_SET": str(showcase_set),
        "GEBIT_DESCRIPTOR_SETS": os.pathsep.join(gebit_descriptor_sets()),
        "POLICY_FILE": str(REPO / "policy" / "pricing-policy.yaml"),
        "DATA_DIR": str(REPO / "data"), "GATE_MIN_DELAY_S": "3", "GATE_GUARD": "block",
        "LOG_LEVEL": "INFO",
    }

    def make(service: str = "test", **env: str) -> Settings:
        return load_settings(service, {**base, **env})

    return make


@pytest.fixture(scope="session")
def settings(make_settings: Callable[..., Settings]) -> Settings:
    """Settings of the test process (service ``"test"``)."""
    return make_settings("test")


@pytest.fixture
def memory_bus() -> Iterator[MemoryBus]:
    """A fresh in-process bus; closed after the test."""
    bus = MemoryBus()
    yield bus
    bus.close()


@pytest.fixture(scope="session")
def showcase_pool(showcase_set: Path) -> descriptor_pool.DescriptorPool:
    """Pool of the Showcase set (wws + loyalty)."""
    return load_pool([str(showcase_set)])


@pytest.fixture(scope="session")
def gebit_pool() -> descriptor_pool.DescriptorPool:
    """Pool of the GEBIT purchase + receipt sets; skips when they are not available."""
    paths = gebit_descriptor_sets()
    if not paths:
        pytest.skip("GEBIT descriptor sets not found")
    return load_pool(paths)


# --------------------------------------------------------------------------- postgres
class PgUnavailable(Exception):
    """The host Postgres container cannot be used."""


@dataclass(frozen=True)
class PgAdmin:
    """Superuser access to the host container (credentials read at runtime)."""

    container: str
    host: str
    port: int
    user: str
    password: str = field(repr=False)

    @classmethod
    def discover(cls) -> PgAdmin:
        container = os.environ.get("PG_CONTAINER", "postgres")
        try:
            proc = subprocess.run(
                ["docker", "inspect", "--format", "{{json .Config.Env}}", container],
                capture_output=True, text=True, timeout=20, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PgUnavailable(f"docker not usable: {exc}") from exc
        if proc.returncode != 0:
            raise PgUnavailable(f"container {container!r} not found")
        env = dict(item.split("=", 1) for item in json.loads(proc.stdout) if "=" in item)
        admin = cls(container, os.environ.get("PG_HOST", "localhost"),
                    int(os.environ.get("PG_PORT", "5432")),
                    env.get("POSTGRES_USER", "postgres"), env.get("POSTGRES_PASSWORD", ""))
        try:
            admin.connect().close()
        except psycopg.Error as exc:
            raise PgUnavailable(f"postgres on {admin.host}:{admin.port} unreachable") from exc
        return admin

    def conninfo(self, dbname: str, user: str | None = None, password: str | None = None) -> str:
        return make_conninfo(host=self.host, port=self.port, dbname=dbname,
                             user=user or self.user,
                             password=self.password if password is None else password,
                             connect_timeout=5)

    def connect(self, dbname: str = "postgres") -> psycopg.Connection:
        return psycopg.connect(self.conninfo(dbname), autocommit=True)

    def psql(self, dbname: str, script: str, label: str, variables: dict[str, str]) -> None:
        """Run ``script`` with psql inside the container (psql meta-commands work)."""
        cmd = ["docker", "exec", "-i", "-e", "PGPASSWORD", self.container, "psql", "-X", "-q",
               "-U", self.user, "-v", "ON_ERROR_STOP=1"]
        for key, value in variables.items():
            cmd += ["-v", f"{key}={value}"]
        cmd += ["-d", dbname, "-f", "-"]
        proc = subprocess.run(cmd, input=script.encode("utf-8"), capture_output=True,
                              timeout=600, check=False,
                              env={**os.environ, "PGPASSWORD": self.password})
        if proc.returncode != 0:
            tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-8:]
            raise RuntimeError(f"psql {label} failed in {dbname}:\n" + "\n".join(tail))


@dataclass
class ScratchDb:
    """A throwaway database with its own role prefix (``gpos_ut_<6 hex>``).

    ``dsn(service)`` logs in as the service role (``pos``, ``wws``, ``loyalty``,
    ``engine``; ``gate`` uses ``engine``); ``admin_dsn`` as the container superuser.
    """

    admin: PgAdmin = field(repr=False)
    name: str
    role_prefix: str
    demo_date: date
    files: list[str] = field(default_factory=list)
    seeded: bool = False
    seed_files: list[Path] = field(default_factory=list, repr=False)
    passwords: dict[str, str] = field(default_factory=dict, repr=False)

    def role(self, service: str) -> str:
        """``<prefix>_<role>``; ``gate`` maps to ``engine``, other names map to themselves."""
        return f"{self.role_prefix}_{SERVICE_ROLES.get(service, service)}"

    def dsn(self, service: str) -> str:
        role = self.role(service)
        if role not in self.passwords:
            raise KeyError(f"role {role} does not exist in {self.name}")
        return self.admin.conninfo(self.name, role, self.passwords[role])

    @property
    def admin_dsn(self) -> str:
        return self.admin.conninfo(self.name)

    def db(self, service: str, max_size: int = 3) -> Db:
        """A ``Db`` pool logged in as the service role (close it after use)."""
        return Db(self.dsn(service), max_size, application_name=f"ut-{service}")

    def admin_db(self, max_size: int = 2) -> Db:
        """A ``Db`` pool logged in as the superuser (for assertions and cleanup)."""
        return Db(self.admin_dsn, max_size, application_name="ut-admin")

    def psql_file(self, path: Path) -> None:
        """Run one SQL file with ``-v role_prefix=… -v demo_date=…`` (as superuser)."""
        variables = {"role_prefix": self.role_prefix, "demo_date": self.demo_date.isoformat()}
        self.admin.psql(self.name, path.read_text(encoding="utf-8"), path.name, variables)
        self.files.append(path.name)

    def reseed(self) -> None:
        """Re-run the generated seed files (each replaces its seed data, 5.7)."""
        if not self.seeded:
            raise RuntimeError(f"{self.name} has no seed")
        for path in self.seed_files:
            self.psql_file(path)


def _set_role_passwords(db: ScratchDb) -> None:
    with db.admin.connect() as conn:
        roles = [r[0] for r in conn.execute(
            "select rolname from pg_roles where starts_with(rolname, %s) order by 1",
            (f"{db.role_prefix}_",))]
        for role in roles:
            password = secrets.token_urlsafe(18)
            conn.execute(sql.SQL("alter role {} password {}").format(
                sql.Identifier(role), sql.Literal(password)))
            db.passwords[role] = password


def _generate_seed(demo_date: date, out: Path) -> list[Path]:
    proc = subprocess.run(
        [sys.executable, str(GEN_SEED), "--demo-date", demo_date.isoformat(), "--out", str(out)],
        capture_output=True, text=True, timeout=300, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"gen_seed.py failed:\n{proc.stderr.strip()[-2000:]}")
    return sorted(out.glob("*.sql"))


def create_scratch_db(admin: PgAdmin, sql_files: Sequence[Path], *, demo_date: date,
                      seed_dir: Path | None) -> ScratchDb:
    """Create the DB, run the DDL files (names not starting with ``9``) in name order,
    set role passwords, then (with ``seed_dir``) the generated seeds and the checks."""
    prefix = f"gpos_ut_{secrets.token_hex(3)}"
    with admin.connect() as conn:
        conn.execute(sql.SQL("create database {}").format(sql.Identifier(prefix)))
    db = ScratchDb(admin, prefix, prefix, demo_date)
    try:
        ordered = sorted(sql_files, key=lambda p: p.name)
        for path in (p for p in ordered if not p.name.startswith("9")):
            db.psql_file(path)
        _set_role_passwords(db)
        if seed_dir is not None:
            db.seed_files = _generate_seed(demo_date, seed_dir)
            for path in db.seed_files:
                db.psql_file(path)
            db.seeded = True
            for path in (p for p in ordered if p.name.startswith("9")):
                db.psql_file(path)
    except BaseException:
        drop_scratch_db(db)
        raise
    return db


def drop_scratch_db(db: ScratchDb) -> None:
    """Drop the database (forcing out sessions) and every role with its prefix."""
    with db.admin.connect() as conn:
        conn.execute(sql.SQL("drop database if exists {} with (force)").format(
            sql.Identifier(db.name)))
        roles = [r[0] for r in conn.execute(
            "select rolname from pg_roles where starts_with(rolname, %s)",
            (f"{db.role_prefix}_",))]
        for role in roles:
            conn.execute(sql.SQL("drop role if exists {}").format(sql.Identifier(role)))


@pytest.fixture(scope="session")
def pg_admin() -> PgAdmin:
    """Superuser access to the host container; skips when it is unreachable."""
    try:
        return PgAdmin.discover()
    except PgUnavailable as exc:
        pytest.skip(f"postgres unavailable: {exc}")


@pytest.fixture(scope="session")
def scratch_db_factory(pg_admin: PgAdmin, settings: Settings,
                       tmp_path_factory: pytest.TempPathFactory
                       ) -> Iterator[Callable[..., ScratchDb]]:
    """``factory(sql_files, seed=False)``; every DB is dropped at session end."""
    created: list[ScratchDb] = []

    def create(sql_files: Sequence[Path], *, seed: bool = False) -> ScratchDb:
        seed_dir = tmp_path_factory.mktemp("seed") if seed else None
        db = create_scratch_db(pg_admin, sql_files, demo_date=settings.demo_date,
                               seed_dir=seed_dir)
        created.append(db)
        return db

    yield create
    for db in created:
        drop_scratch_db(db)


@pytest.fixture(scope="session")
def scratch_db(scratch_db_factory: Callable[..., ScratchDb]) -> ScratchDb:
    """DB with ``postgres/sql/*`` (00..40), the seed of ``gen_seed.py`` for the demo date
    and ``95-checks.sql``; skips while WP-B's SQL files are missing."""
    files = sorted(SQL_DIR.glob("*.sql"))
    if not files:
        pytest.skip("postgres/sql/*.sql not there yet (WP-B)")
    return scratch_db_factory(files, seed=GEN_SEED.is_file())


# --------------------------------------------------------------------------- broker
def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().removeprefix("export ").strip()] = value.strip().strip("'\"")
    return values


def _reachable(host_url: str) -> bool:
    host, _, port = host_url.removeprefix("tcp://").partition(":")
    try:
        with socket.create_connection((host, int(port or 55555)), timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def solace_settings(make_settings: Callable[..., Settings]) -> Settings:
    """Settings for solace-1 from the Mac (``tcp://localhost:55557``, VPN default).

    Credentials: ``SOLACE_USERNAME``/``SOLACE_PASSWORD`` or ``MQTT_USERNAME``/
    ``MQTT_PASSWORD`` of ``../bsg-trading-desk-demo/.env``; skips without them or when
    the broker port is closed. Direct messages only (DMR backlog, finding 20).
    """
    user = os.environ.get("SOLACE_USERNAME", "")
    password = os.environ.get("SOLACE_PASSWORD", "")
    if not (user and password):
        bsg = _read_env_file(BSG_ENV)
        user, password = bsg.get("MQTT_USERNAME", ""), bsg.get("MQTT_PASSWORD", "")
    if not (user and password):
        pytest.skip("no broker credentials (SOLACE_* or bsg-trading-desk-demo/.env)")
    host = os.environ.get("GPOS_UT_SOLACE_HOST", "tcp://localhost:55557")
    if not _reachable(host):
        pytest.skip(f"broker {host} unreachable")
    return make_settings("test", GPOS_BUS="solace", SOLACE_HOST=host, SOLACE_VPN="default",
                         SOLACE_USERNAME=user, SOLACE_PASSWORD=password)
