"""Fixtures of the WP-B tests (data/*.yaml, postgres/gen_seed.py, postgres/sql/*)."""

import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data"
SQL_DIR = ROOT / "postgres" / "sql"
GEN_SEED = ROOT / "postgres" / "gen_seed.py"
DEMO_DATE = date(2027, 2, 16)


def load_yaml(name: str) -> Any:
    with (DATA_DIR / name).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture(scope="session")
def gen_seed() -> ModuleType:
    """postgres/gen_seed.py as a module (it is a script, not part of gposdemo)."""
    spec = importlib.util.spec_from_file_location("gpos_gen_seed", GEN_SEED)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def articles() -> list[dict[str, Any]]:
    return load_yaml("articles.yaml")


@pytest.fixture(scope="session")
def articles_by_number(articles: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {a["number"]: a for a in articles}


@pytest.fixture(scope="session")
def seasons() -> list[dict[str, Any]]:
    return load_yaml("seasons.yaml")


@pytest.fixture(scope="session")
def central_actions() -> list[dict[str, Any]]:
    return load_yaml("central_actions.yaml")


@pytest.fixture(scope="session")
def personas() -> dict[str, Any]:
    return load_yaml("personas.yaml")


@pytest.fixture(scope="session")
def scenarios() -> list[dict[str, Any]]:
    return load_yaml("scenarios.yaml")


@pytest.fixture(scope="session")
def sources(gen_seed: ModuleType) -> Any:
    return gen_seed.load_sources(DATA_DIR)


@pytest.fixture(scope="session")
def demo_date() -> date:
    return DEMO_DATE


@pytest.fixture(scope="session")
def sql_dir() -> Path:
    return SQL_DIR


def _rows(tables: list[Any]) -> dict[str, list[dict[str, Any]]]:
    return {t.name: [dict(zip(t.columns, row, strict=True)) for row in t.rows]
            for t in tables}


@pytest.fixture(scope="session")
def wws_rows(gen_seed: ModuleType, sources: Any) -> dict[str, list[dict[str, Any]]]:
    """Seed rows of schema wws for 2027-02-16: table name -> rows as dicts."""
    return _rows(gen_seed.wws_tables(sources, DEMO_DATE))


@pytest.fixture(scope="session")
def loyalty_rows(gen_seed: ModuleType, sources: Any) -> dict[str, list[dict[str, Any]]]:
    """Seed rows of schema loyalty for 2027-02-16: table name -> rows as dicts."""
    return _rows(gen_seed.loyalty_tables(sources, DEMO_DATE))
