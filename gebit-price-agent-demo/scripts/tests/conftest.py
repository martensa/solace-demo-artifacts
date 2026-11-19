"""Offline tests of WP-H (scripts/, mesh/, k8s/): no cluster, no SAM, no broker.

Run from the demo root:  .venv/bin/python -m pytest scripts/tests -q
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
# The tests are target-neutral: opslib fixes its paths from TARGET at import, so an
# exported TARGET=aks of the shell must not reach it (the aks tests set TARGET themselves)
os.environ.pop("TARGET", None)


def load(rel: str) -> dict:
    return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))


def load_all(rel: str) -> list[dict]:
    return [d for d in yaml.safe_load_all((ROOT / rel).read_text(encoding="utf-8")) if d]


@pytest.fixture
def dummy_broker(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """Broker credentials for rendering; the password has YAML-hostile characters."""
    user, password = "gpos-test-user", 'p"w\\d #x: {y}'
    monkeypatch.setenv("BROKER_USERNAME", user)
    monkeypatch.setenv("BROKER_PASSWORD", password)
    for key in ("R1_MODE", "GPOS_BOOTH_LOCATION", "GPOS_PROBE_LOCATION", "SAM_RUN_IDENTITY",
                "BROKER_WS_URL", "BROKER_VPN", "R1_QUEUE"):
        monkeypatch.delenv(key, raising=False)
    return user, password
