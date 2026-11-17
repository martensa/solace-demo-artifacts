"""Cards (6.4) and scenarios (1.3) of /kasse, from ``DATA_DIR``."""

from __future__ import annotations

from pathlib import Path

import pytest

from gposdemo.common.config import Settings
from gposdemo.ui import refdata

S1_TO_S8 = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S1b"]


@pytest.fixture(scope="module")
def data(settings: Settings) -> refdata.RefData:
    return refdata.load(settings.data_dir)


def test_cards_have_exactly_the_public_fields(data: refdata.RefData) -> None:
    cards = [c.public() for c in data.cards]
    assert cards[0] == {"card": "CLUB-1001", "persona": "Kaffeepause",
                        "consent_profiling": True}
    assert {c["card"] for c in cards} == {"CLUB-1001", "CLUB-1002", "CLUB-1003", "CLUB-1004",
                                          "CLUB-GAST"}
    assert all(set(c) == {"card", "persona", "consent_profiling"} for c in cards)


def test_feierabend_has_no_profiling_consent(data: refdata.RefData) -> None:
    feierabend = data.card("CLUB-1003")
    assert feierabend is not None and feierabend.persona == "Feierabend"
    assert feierabend.consent_profiling is False
    assert data.card("M-1001") == data.card("CLUB-1001")
    assert data.card("CLUB-9999") is None


def test_scenarios_s1_to_s8_and_s1b(data: refdata.RefData) -> None:
    assert [s["id"] for s in data.scenarios] == S1_TO_S8
    for scenario in data.scenarios:
        assert scenario["steps"][0] == {"op": "new"}
        assert scenario["steps"][-1] == {"op": "pay"}
        assert all(s["op"] in ("new", "card", "scan", "pay") for s in scenario["steps"])


def test_scenario_s1_and_s3_steps(data: refdata.RefData) -> None:
    by_id = {s["id"]: s for s in data.scenarios}
    assert by_id["S1"] == {"id": "S1", "label": "Ladenhüter", "steps": [
        {"op": "new"}, {"op": "scan", "value": "2099100000018"},
        {"op": "scan", "value": "2099100000049"}, {"op": "scan", "value": "2099100000100"},
        {"op": "pay"}]}
    assert by_id["S3"]["steps"][1] == {"op": "card", "value": "CLUB-1001"}
    assert by_id["S6"]["steps"][1] == {"op": "card", "value": "CLUB-1003"}
    assert by_id["S8"]["label"] == "Agent rät ab"


@pytest.mark.parametrize("text, error", [
    ("- {id: X, label: x, steps: [{op: scan, value: '1'}]}", "must start with op new"),
    ("- {id: X, label: x, steps: [{op: new}, {op: fly}]}", "invalid step"),
    ("- {id: X, label: x, steps: [{op: new}, {op: scan}]}", "needs a string value"),
    ("- {id: X, label: x, steps: [{op: new, value: '1'}]}", "takes no value"),
    ("{id: X}", "expected a list"),
])
def test_invalid_scenarios_are_rejected(tmp_path: Path, text: str, error: str) -> None:
    path = tmp_path / "scenarios.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        refdata.load_scenarios(path)


def test_category_rank_follows_6_1() -> None:
    tags = ["buch", "obst_gemuese", "unbekannt", "getraenke"]
    assert sorted(tags, key=refdata.category_rank) == ["obst_gemuese", "getraenke", "buch",
                                                       "unbekannt"]


def test_api_cards_and_scenarios(ui) -> None:
    cards = ui.client.get("/api/cards").json()
    assert cards[0] == {"card": "CLUB-1001", "persona": "Kaffeepause",
                        "consent_profiling": True}
    scenarios = ui.client.get("/api/scenarios").json()
    assert [s["id"] for s in scenarios] == S1_TO_S8
    assert scenarios[0]["steps"][0] == {"op": "new"}
