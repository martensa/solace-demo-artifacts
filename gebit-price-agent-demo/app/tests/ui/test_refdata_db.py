"""The /kasse reference data against the seeded database the services read (marker db).

Scenario buttons scan EANs and assign cards; they only work when every EAN is an
article of the booth store and every card is an active loyalty card. The monitor's
consent hint ("Karte mit/ohne Profil-Einwilligung") comes from ``personas.yaml`` via
``/api/cards`` and must say what the loyalty service will decide.
"""

from __future__ import annotations

import pytest

from gposdemo.common.config import Settings
from gposdemo.ui import refdata

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def data(settings: Settings) -> refdata.RefData:
    return refdata.load(settings.data_dir)


def test_every_scenario_ean_is_an_article_of_the_booth_store(scratch_db,
                                                             data: refdata.RefData) -> None:
    eans = sorted({s["value"] for sc in data.scenarios for s in sc["steps"]
                   if s["op"] == "scan"})
    db = scratch_db.admin_db()
    try:
        rows = db.fetch(
            "select a.gtin, a.article_id, p.regular_price from wws.article a "
            "join wws.article_price p on p.article_number = a.article_number "
            "and p.store_id = '101' where a.gtin = any(%s)", (eans,))
    finally:
        db.close()
    found = {r["gtin"]: r for r in rows}
    assert sorted(found) == eans
    assert found["2099100000018"]["article_id"] == "ID100001"
    assert str(found["2099100000018"]["regular_price"]) == "9.99"


def test_every_card_is_active_with_the_persona_and_consent_of_the_ui(
        scratch_db, data: refdata.RefData) -> None:
    db = scratch_db.admin_db()
    try:
        rows = db.fetch(
            "select c.card_value, c.status, m.persona_label, s.profiling "
            "from loyalty.card c join loyalty.member m on m.member_id = c.member_id "
            "join loyalty.consent s on s.member_id = c.member_id")
    finally:
        db.close()
    seeded = {r["card_value"]: r for r in rows}
    for card in data.cards:
        row = seeded[card.card]
        assert row["status"] == "ACTIVE", card.card
        assert row["persona_label"] == card.persona, card.card
        assert row["profiling"] is card.consent_profiling, card.card
    scenario_cards = {s["value"] for sc in data.scenarios for s in sc["steps"]
                      if s["op"] == "card"}
    assert scenario_cards == {"CLUB-1001", "CLUB-1003"}
    assert seeded["CLUB-1001"]["profiling"] is True
    assert seeded["CLUB-1003"]["profiling"] is False
