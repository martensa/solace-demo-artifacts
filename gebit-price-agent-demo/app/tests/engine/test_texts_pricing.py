"""Pricing helpers, guardrail list, text validator and notify texts (6.7, 7.2, 11.3, 11.6)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from gposdemo.common.fmt import dt_label
from gposdemo.engine import notify, pricing, texts, validator
from gposdemo.engine.guardrails import guardrail_rows
from gposdemo.engine.policy import Policy
from gposdemo.engine.pricing import PriceChange
from gposdemo.engine.records import ProposalRecord
from tests.engine.fakes import ENTE, ESPRESSO, PRALINEN, ZONE, D, Facts

S1_RATIONALE = "Nur 9 von 35 geplanten Enten in 7 Tagen verkauft; der Bestand reicht 6,5 Wochen."
S1_FACTS_LINE = "9/35 verkauft (7 Tage) · Bestand 96 · Reichweite 6,5 Wo."
VALID_TO = datetime(2027, 2, 23, 20, 0, tzinfo=ZONE)


def proposal(**changes: Any) -> ProposalRecord:
    """The S1 proposal of the 7.2 example (GEBIT Ente 9,99 -> 7,99)."""
    base = ProposalRecord(
        proposal_id="GP-270216-0003", review_id="GR-270216-0007",
        tx_id="5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11", store_id="101", till_id="01",
        article_number=ENTE, article_name="GEBIT Ente (Quietscheente gelb)",
        reason="slow_seller", step_requested=20, step_pct=20, clamped=False,
        regular_price=Decimal("9.99"), new_price=Decimal("7.99"), ref30=Decimal("9.99"),
        pct_shown=20, margin_pct_new=Decimal("22.6"), base_price_label=None,
        valid_from=datetime(2027, 2, 16, tzinfo=ZONE), valid_to=VALID_TO,
        headline="GEBIT Ente: Abverkauf ankurbeln", rationale=S1_RATIONALE,
        facts_line=S1_FACTS_LINE, note="", text_source="ai", guardrails=[],
        proposal_hash="0123456789", status="pending", status_reason=None, run_id_stage="r3",
        run_id_approval="r4", created_at=datetime.now(ZONE), pending_at=None, decided_at=None)
    return replace(base, **changes)


# ------------------------------------------------------------------ pricing
def test_validity_from_business_date(policy: Policy) -> None:
    valid_from, valid_to = pricing.validity(D, policy, ZONE)
    assert (valid_from.timestamp(), valid_to.timestamp()) == (1802732400, 1803409200)
    assert valid_to.isoformat() == "2027-02-23T20:00:00+01:00"
    assert dt_label(valid_to) == "Di 23.02. 20:00"


def test_base_price_labels() -> None:
    assert pricing.base_price_label(Decimal("5.49"), Decimal("200"), "g") == "27,45 €/kg"
    assert pricing.base_price_label(Decimal("2.99"), Decimal("1000"), "ml") == "2,99 €/l"
    assert pricing.base_price_label(Decimal("3.29"), Decimal("9000"), "ml") == "0,37 €/l"
    assert pricing.base_price_label(Decimal("7.99"), Decimal("1"), "Stück") == ""


@pytest.mark.parametrize(("change", "new_price", "expected"), [
    (PriceChange(date(2027, 1, 11), Decimal("12.99"), Decimal("14.49")), Decimal("12.99"),
     "Rücknahme der Preiserhöhung vom 11.01."),
    (PriceChange(date(2027, 1, 11), Decimal("12.99"), Decimal("14.49")), Decimal("11.49"), ""),
    (PriceChange(date(2026, 11, 17), Decimal("12.99"), Decimal("14.49")), Decimal("12.99"), ""),
    (PriceChange(date(2027, 1, 11), Decimal("14.49"), Decimal("12.99")), Decimal("11.99"), ""),
    (None, Decimal("7.99"), "")])
def test_price_note(change: PriceChange | None, new_price: Decimal, expected: str) -> None:
    assert pricing.price_note(change, new_price, D) == expected


def test_margin_of_vollmilch_blocks_every_step(get_facts: Callable[..., Facts],
                                               policy: Policy) -> None:
    a = get_facts("100010").article
    opts = pricing.step_options(a.price.regular_price, a.cost_net, a.vat_percent, policy)
    assert [o.price for o in opts] == [Decimal("0.99"), Decimal("0.89"), Decimal("0.79")]
    assert pricing.max_step(opts) == 0


def test_guardrails_of_the_s1_example(get_facts: Callable[..., Facts], policy: Policy) -> None:
    a = get_facts(ENTE).article
    opts = pricing.step_options(a.price.regular_price, a.cost_net, a.vat_percent, policy)
    rows = guardrail_rows(pricing.option_for(opts, 20), opts, regular=a.price.regular_price,
                          price_bound=False, action_open=False,
                          valid_to_label="Di 23.02. 20:00",
                          min_margin_pct=policy.guardrails.min_margin_pct)
    assert rows == [
        {"rule": "Nur Senkung", "ok": True},
        {"rule": "Mindestmarge 20 %", "ok": True, "value": "22,6 %"},
        {"rule": "Keine laufende Aktion", "ok": True}, {"rule": "Nicht preisgebunden", "ok": True},
        {"rule": "Preispunkt ,99", "ok": True},
        {"rule": "Befristet bis Di 23.02. 20:00", "ok": True},
        {"rule": "Ein offener Vorschlag je Kasse", "ok": True},
        {"rule": "−30 % gesperrt", "ok": False, "value": "Marge 11,5 %", "info": True}]


def test_guardrails_of_espresso_show_two_blocked_steps(get_facts: Callable[..., Facts],
                                                       policy: Policy) -> None:
    a = get_facts(ESPRESSO).article
    opts = pricing.step_options(a.price.regular_price, a.cost_net, a.vat_percent, policy)
    rows = guardrail_rows(pricing.option_for(opts, 10), opts, regular=a.price.regular_price,
                          price_bound=False, action_open=False, valid_to_label="x",
                          min_margin_pct=Decimal(20))
    info = [r for r in rows if r.get("info")]
    assert [r["rule"] for r in info] == ["−20 % gesperrt", "−30 % gesperrt"]
    assert info[0]["value"] == "Marge 17,1 %"
    pralinen = get_facts(PRALINEN).article
    opts = pricing.step_options(pralinen.price.regular_price, pralinen.cost_net,
                                pralinen.vat_percent, policy)
    rows = guardrail_rows(pricing.option_for(opts, 30), opts,
                          regular=pralinen.price.regular_price, price_bound=False,
                          action_open=False, valid_to_label="x", min_margin_pct=Decimal(20))
    assert {"rule": "Preispunkt ,49", "ok": True} in rows


# ------------------------------------------------------------------ validator
def checked(policy: Policy, headline: str, rationale: str = S1_RATIONALE,
            facts_line: str = S1_FACTS_LINE) -> validator.ProposalTexts:
    return validator.proposal_texts(
        headline, rationale, facts_line, article_name="GEBIT Ente (Quietscheente gelb)",
        reason="slow_seller",
        facts="9 von 35 geplanten Stück verkauft (7 Tage), Reichweite 6,5 Wochen, Bestand 96",
        allowed_amounts={"9,99", "7,99"}, limits=policy.texts)


def test_clean_text() -> None:
    assert validator.clean("Ente­­n ab​verkauf\x07en") == "Enten abverkaufen"
    assert validator.clean("Zeile 1\nZeile\t2  ") == "Zeile 1 Zeile 2"
    assert validator.clean("Glühwein") == "Glühwein"


def test_agent_texts_kept(policy: Policy) -> None:
    t = checked(policy, "GEBIT Ente: Abverkauf ankurbeln")
    assert (t.source, t.headline, t.rationale, t.facts_line) == (
        "ai", "GEBIT Ente: Abverkauf ankurbeln", S1_RATIONALE, S1_FACTS_LINE)
    assert checked(policy, "Ente jetzt für 7,99 € statt 9,99 €").source == "template"
    assert checked(policy, "GEBIT Ente jetzt für 7,99 € statt 9,99 €").source == "ai"


def test_foreign_euro_amount_gives_template(policy: Policy) -> None:
    t = checked(policy, "GEBIT Ente: Abverkauf ankurbeln",
                rationale="Für 6,99 € verkauft sich die Ente sicher besser.")
    assert t.source == "template"
    assert t.headline == "GEBIT Ente (Quietscheente gelb): Abverkauf ankurbeln"
    assert t.rationale == ("9 von 35 geplanten Stück verkauft (7 Tage), Reichweite 6,5 "
                           "Wochen, Bestand 96.")
    assert checked(policy, "GEBIT Ente: nur 5,99 €").source == "template"


def test_missing_article_name_gives_template(policy: Policy) -> None:
    assert checked(policy, "Quietscheente: Abverkauf ankurbeln").source == "template"


def test_foreign_percent_gives_template(policy: Policy) -> None:
    """11.3 step 7: a percentage the planner computed is never shown."""
    allowed = {"20"} | validator.number_tokens(["9 von 35 geplanten Stück verkauft (7 Tage)"])
    base = {"article_name": "GEBIT Ente (Quietscheente gelb)", "reason": "slow_seller",
            "facts": "9 von 35 geplanten Stück verkauft (7 Tage), Reichweite 6,5 Wochen",
            "allowed_amounts": {"9,99", "7,99"}, "limits": policy.texts,
            "allowed_percents": allowed}
    ok = validator.proposal_texts("GEBIT Ente: −20 % für den Abverkauf", S1_RATIONALE,
                                  S1_FACTS_LINE, **base)  # type: ignore[arg-type]
    assert ok.source == "ai"
    bad = validator.proposal_texts("GEBIT Ente: 25 % Rabatt", S1_RATIONALE, S1_FACTS_LINE,
                                   **base)  # type: ignore[arg-type]
    assert bad.source == "template"
    assert validator.proposal_texts(
        "GEBIT Ente: Abverkauf ankurbeln", "Nur 26 % der Planmenge verkauft.", S1_FACTS_LINE,
        **base).source == "template"  # type: ignore[arg-type]
    line = validator.proposal_texts("GEBIT Ente: Abverkauf ankurbeln", S1_RATIONALE,
                                    "Abverkauf 26 % des Plans", **base)  # type: ignore[arg-type]
    assert (line.source, line.facts_line) == ("ai", base["facts"])


def test_allowed_percents_of_s2_and_s3() -> None:
    """S3: "47 %" (facts) and "46,7 %" (evidence numbers) pass; S2: "30 %" against the
    shown −31 % does not."""
    s3 = {"10"} | validator.number_tokens([
        "Stammartikel der Karte: zuletzt vor 35 Tagen (sonst alle 14 Tage); Kartenkunden "
        "kaufen 47 % seltener", "overdue_factor=2.5; cardholder_drop_pct=46.7"])
    assert {"47", "46,7", "2,5", "3"} <= s3
    assert validator.foreign_percents("Kartenkunden −47 % (46,7 %), Senkung 10 %", s3) == []
    assert validator.foreign_percents("Senkung um 20 %", s3) == ["20"]
    s2 = {"31"} | validator.number_tokens(["Saison Valentinstag endete am 14.02., "
                                           "Restbestand 46"])
    assert validator.foreign_percents("Herzpralinen 30 % günstiger", s2) == ["30"]
    assert validator.foreign_percents("Herzpralinen −31 %", s2) == []


def test_last_change_gives_no_percentages(policy: Policy) -> None:
    """11.3 step 7 (UC1-32): the full S3 evidence carries ``last_change``; its date and
    prices are no percentages, so "11 %" or "13 %" in the S3 texts still give the
    template, while every other number of the evidence stays allowed."""
    facts = ("Stammartikel der Karte: zuletzt vor 35 Tagen (sonst alle 14 Tage); "
             "Kartenkunden kaufen 47 % seltener")
    numbers = ("overdue_factor=2.5; cardholder_drop_pct=46.7; days_since_last=35; "
               "median_interval_days=14; margin_pct=34.3; last_change=2027-01-11 12,99->14,49")
    allowed = validator.allowed_percents(10, facts, numbers)
    assert allowed == {"10", "35", "14", "47", "2,5", "3", "46,7", "34,3", "34"}
    assert allowed == validator.allowed_percents(10, facts, numbers.replace("->", " → "))
    assert {"1", "11", "13", "2027", "12,99", "14,49"}.isdisjoint(allowed)
    base = {"article_name": "Espresso Bohnen kräftig", "reason": "customer_behaviour",
            "facts": facts, "allowed_amounts": {"14,49", "12,99"}, "limits": policy.texts,
            "allowed_percents": allowed}
    rationale = "Die Karte kauft seit 35 Tagen nicht mehr, sonst alle 14 Tage."
    for headline, source in (("Espresso: Kartenkunden kaufen 46,7 % seltener", "ai"),
                             ("Espresso: 11 % günstiger für die Karte", "template"),
                             ("Espresso: jetzt 13 % sparen", "template")):
        texts_ = validator.proposal_texts(headline, rationale, "Senkung 10 %",
                                          **base)  # type: ignore[arg-type]
        assert texts_.source == source, headline


def test_overlong_texts_are_cut_at_a_word_end(policy: Policy) -> None:
    long_headline = "GEBIT Ente " + "sehr " * 20
    t = checked(policy, long_headline, rationale="Wort " * 60, facts_line="x " * 80)
    assert len(t.headline) <= 70 and t.headline.endswith("…") and " sehr…" in t.headline
    assert len(t.rationale) <= 240 and t.rationale.endswith("Wort…")
    assert len(t.facts_line) <= 120 and t.facts_line.endswith("…")
    assert t.source == "ai"


# ------------------------------------------------------------------ notify (11.6)
def test_inform_texts_s1() -> None:
    title, message = notify.inform(proposal(), ZONE, Decimal(20))
    assert title == "Preisvorschlag GEBIT Ente (Quietscheente gelb): 9,99 € → 7,99 € (−20 %)"
    assert message == (
        "Anlass: Ladenhüter – 9/35 verkauft (7 Tage) · Bestand 96 · Reichweite 6,5 Wo. "
        f"KI-Empfehlung: {S1_RATIONALE} Leitplanken: Marge 22,6 % ≥ 20 %, keine laufende "
        "Aktion, Preispunkt ,99. Niedrigster Preis der letzten 30 Tage: 9,99 €. Gültig bis "
        "Di 23.02. 20:00. Bitte die folgende Freigabeanfrage beantworten "
        "(Ref GP-270216-0003).")


def test_inform_texts_with_note_ending_and_template() -> None:
    p = proposal(article_name="Espresso Bohnen kräftig", regular_price=Decimal("14.49"),
                 new_price=Decimal("12.99"), ref30=Decimal("14.49"), pct_shown=10,
                 margin_pct_new=Decimal("26.7"), reason="customer_behaviour",
                 note="Rücknahme der Preiserhöhung vom 11.01.", text_source="template",
                 rationale="Kartenkunden kaufen 47 % seltener.")
    title, message = notify.inform(p, ZONE, Decimal(20))
    assert title == "Preisvorschlag Espresso Bohnen kräftig: 14,49 € → 12,99 € (−10 %)"
    assert "Anlass: Kundenverhalten – " in message
    assert "Begründung: Kartenkunden kaufen 47 % seltener. Leitplanken" in message
    assert "KI-Empfehlung" not in message and "KI-Begründung" not in message
    assert ("Niedrigster Preis der letzten 30 Tage: 14,49 €. Rücknahme der Preiserhöhung "
            "vom 11.01. Gültig bis Di 23.02. 20:00.") in message
    s2 = proposal(new_price=Decimal("5.49"))
    assert "Preispunkt ,49." in notify.inform(s2, ZONE, Decimal(20))[1]


def test_inform_message_limit_shortens_the_rationale() -> None:
    p = proposal(rationale="Langer Satz " * 40, facts_line="F" * 120,
                 note="Rücknahme der Preiserhöhung vom 11.01.",
                 article_name="Sehr langer Artikelname " * 4)
    title, message = notify.inform(p, ZONE, Decimal(20))
    assert len(title) <= 90 and title.startswith("Preisvorschlag Sehr langer")
    assert title.endswith("…: 9,99 € → 7,99 € (−20 %)")
    assert 590 <= len(message) <= 600 and "Satz…" in message
    assert message.endswith("(Ref GP-270216-0003).")


@pytest.mark.parametrize(("outcome", "reason", "title", "message"), [
    ("approved", "", "Preis aktiv: GEBIT Ente (Quietscheente gelb) 7,99 € bis Di 23.02. 20:00",
     "Freigegeben in Agent Mesh. Ab dem nächsten Scan kostet GEBIT Ente (Quietscheente gelb) "
     "7,99 € statt 9,99 €. Ref GP-270216-0003, Aktion PA-270216-0003."),
    ("rejected", texts.REASON_REJECTED,
     "Abgelehnt: GEBIT Ente (Quietscheente gelb) bleibt bei 9,99 €",
     "Abgelehnt in Agent Mesh. Kein neuer Preis. Ref GP-270216-0003."),
    ("rejected", "", "Abgelehnt: GEBIT Ente (Quietscheente gelb) bleibt bei 9,99 €",
     "Abgelehnt in Agent Mesh. Kein neuer Preis. Ref GP-270216-0003."),
    ("rejected", texts.REASON_REJECTED_ERROR,
     "Abgelehnt: GEBIT Ente (Quietscheente gelb) bleibt bei 9,99 €",
     "Abgelehnt in Agent Mesh (Agent meldete einen Fehler). Kein neuer Preis. "
     "Ref GP-270216-0003."),
    ("blocked", "Hash passt nicht.", "Nicht angewendet: GEBIT Ente (Quietscheente gelb)",
     "Hash passt nicht. Ref GP-270216-0003."),
    ("failed", "Hash passt nicht.", "Nicht angewendet: GEBIT Ente (Quietscheente gelb)",
     "Hash passt nicht. Ref GP-270216-0003."),
    ("failed", texts.REASON_TECHNICAL, "Nicht angewendet: GEBIT Ente (Quietscheente gelb)",
     "Technischer Fehler – kein neuer Preis. Ref GP-270216-0003."),
    ("failed", "", "Nicht angewendet: GEBIT Ente (Quietscheente gelb)",
     "Technischer Fehler – kein neuer Preis. Ref GP-270216-0003."),
    ("superseded", "", "Zurückgesetzt: GEBIT Ente (Quietscheente gelb) bleibt bei 9,99 €",
     "Der Vorschlag wurde durch einen Reset beendet. Ref GP-270216-0003."),
    ("expired", "", "Abgelaufen: GEBIT Ente (Quietscheente gelb) bleibt bei 9,99 €",
     "Keine Antwort binnen 2 Minuten. Ref GP-270216-0003."),
    ("unknown", "", "", "")])
def test_tell_texts(outcome: str, reason: str, title: str, message: str) -> None:
    assert notify.tell(outcome, proposal(), ZONE, "PA-270216-0003", reason) == (
        title, message)


def test_probe_texts() -> None:
    assert notify.PROBE_TITLE == "gpos Preflight: Benachrichtigung ok"
    assert notify.PROBE_MESSAGE == "Testmeldung der Anmeldeprüfung, keine Aktion nötig."
