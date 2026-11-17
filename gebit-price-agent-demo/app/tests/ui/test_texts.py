"""Fixed UI texts (10.5) and the colour scheme (10.4), served once to the pages."""

from __future__ import annotations

import json
import re

import pytest

from gposdemo.ui import texts


def test_reason_labels_verbatim() -> None:
    assert texts.REASON_LABELS == {"slow_seller": "Ladenhüter", "season_end": "Saisonende",
                                   "customer_behaviour": "Kundenverhalten"}


def test_state_texts_verbatim() -> None:
    assert texts.STATE_TEXTS == {
        "ready": "Vorschlag bereit",
        "pending": "Liegt in Agent Mesh bei der Marktleitung",
        "approved": "Freigegeben",
        "rejected": "Abgelehnt – kein neuer Preis",
        "expired": "Abgelaufen – kein neuer Preis",
        "blocked": "Blockiert durch Leitplanke",
        "failed": "Technischer Fehler",
        "superseded": "Zurückgesetzt",
        "deferred": "Zurückgestellt – offene Freigabe an dieser Kasse, nicht nachgeholt",
        "duplicate_request": "Zweite Freigabeanfrage erkannt – Preis ist bereits aktiv",
    }


def test_monitor_texts_of_10_4() -> None:
    assert texts.CLAIM == "KI schlägt vor. Regeln prüfen. Mensch entscheidet."
    assert texts.BADGES == ("Simulator (GEBIT Purchase API 2.50)", "Lab",
                            "Solace Agent Mesh 2.542.1")
    assert [s["label"] for s in texts.STATIONS] == [
        "Kasse", "Analyse in Agent Mesh", "KI prüft und empfiehlt", "Freigabe Marktleitung",
        "Neuer Preis"]
    assert texts.CONSENT_YES == "Karte mit Profil-Einwilligung"
    assert texts.CONSENT_NO == "Karte ohne Profil-Einwilligung – Kundenverhalten nicht genutzt"
    assert texts.STAMP_APPROVED == "Freigegeben · Marktleitung · in Agent Mesh"
    assert texts.STAMP_BY == "empfohlen von KI (planning), geprüft von der Engine"
    assert texts.STAMPS == {"rejected": "Abgelehnt", "expired": "Abgelaufen",
                            "blocked": "Blockiert"}
    assert texts.OTHER_CANDIDATES == "weitere Kandidaten (nicht vorgeschlagen)"
    assert texts.REF30_LINE.format(ref30="9,99") == (
        "Niedrigster Preis der letzten 30 Tage: 9,99 €")
    assert texts.PENDING_SINCE.format(elapsed="0:12") == (
        "Liegt in Agent Mesh bei der Marktleitung seit 0:12")
    assert texts.NEXT_SCAN.format(price="7,99") == "Nächster Scan: 7,99 € AKTION"
    assert texts.AGENT_ASKS.format(model=texts.model_name("fast"),
                                   family=texts.API_FAMILIES["wws"],
                                   tool="get_sales_performance") == (
        "Claude Haiku 4.5 fragt Warenwirtschaft: get_sales_performance")
    assert texts.SIMPLIFICATION == ("Vereinfachung: Messe-Aktionen zählen für den "
                                    "30-Tage-Tiefstpreis nicht mit (Wiederholbarkeit)")
    assert texts.RECAP_AFTER_S == 90


def test_chip_colour_scheme() -> None:
    for code in ("slow_seller", "season_end", "customer_behaviour"):
        assert texts.CHIPS[code]["tone"] == "red" and not texts.CHIPS[code]["lock"]
    assert texts.CHIPS["on_plan"] == {"tone": "green", "lock": False, "text": "läuft nach Plan"}
    assert texts.CHIPS["neutral"] == {"tone": "grey", "lock": False, "text": "unauffällig"}
    for code in ("excluded", "action"):
        assert texts.CHIPS[code]["tone"] == "grey" and texts.CHIPS[code]["lock"]
    assert texts.SOURCE_TONES == {"rule": "turquoise", "ai": "violet", "human": "orange",
                                  "till": "blue"}


def test_kasse_texts_of_10_3() -> None:
    assert texts.TILL_HEAD.format(till="01") == "Kasse 01 · Messestand"
    assert list(texts.TILL_STATUS.values()) == ["Bereit", "Bon offen", "Zahlung",
                                                "Abgeschlossen"]
    assert texts.EAN_PLACEHOLDER == "EAN scannen oder tippen"
    assert [texts.BUTTONS[k] for k in ("new", "void", "pay", "cancel")] == [
        "Neuer Bon", "Zeile stornieren", "Bezahlen (bar)", "Abbrechen"]
    assert texts.TEST_TILL_SWITCH == "Testkasse 99"
    assert texts.SCENARIO_STEP_MS == 1200
    assert "Inbox-Wächter (make demo-watch)" in texts.RESET_HINT
    assert "make demo-reset ab." in texts.RESET_HINT


def test_counters_line_s1() -> None:
    line = texts.counters_line({"pos_events": 13, "sam_runs": 6, "agent_runs": 3,
                                "agent_runs_by_model": {"fast": 2, "planning": 1},
                                "agent_tool_calls": 2, "approvals": 1})
    assert line == ("13 Kassenereignisse → 6 SAM-Läufe → 3 KI-Agenten-Läufe "
                    "(fast 2, planning 1) · 2 API-Abfragen der Agenten → 1 Freigabe(n)")
    assert texts.LLM_HINT == "≈ 1–2 KI-Aufrufe je Agentenlauf"


def test_counters_line_without_models_defaults_to_zero() -> None:
    line = texts.counters_line({"pos_events": 0, "sam_runs": 0, "agent_runs": 0,
                                "agent_tool_calls": 0, "approvals": 0})
    assert "0 KI-Agenten-Läufe (fast 0, planning 0) · " in line


@pytest.mark.parametrize("alias, model", [
    ("fast", "fast"), ("planning", "planning"), ("", "fast"), (None, "fast"),
    ("Planning", "fast"), ("sonnet", "fast"), (1, "fast")])
def test_model_rule_missing_or_unknown_is_fast(alias: object, model: str) -> None:
    assert texts.model_of(alias) == model
    assert texts.model_name(alias) == texts.MODEL_NAMES[model]


def test_models_and_recommendation_texts() -> None:
    assert texts.MODEL_NAMES == {"fast": "Claude Haiku 4.5", "planning": "Claude Sonnet 5"}
    assert texts.RULE_ANALYSIS == "Regel-Analyse (ohne KI)"
    assert texts.AI_RECOMMENDATION.format(model="planning", name="Claude Sonnet 5") == (
        "KI-Empfehlung · planning (Claude Sonnet 5)")
    # a legacy proposal (ai_model "") shows the fast agent
    assert texts.AI_RECOMMENDATION.format(model=texts.model_of(""),
                                          name=texts.model_name("")) == (
        "KI-Empfehlung · fast (Claude Haiku 4.5)")
    assert texts.NO_CHANGE_RECOMMENDED == "Keine Preisänderung empfohlen"
    assert texts.EVIDENCE_TITLE.format(model="fast", name="Claude Haiku 4.5") == (
        "Belege · fast (Claude Haiku 4.5)")
    assert texts.EVIDENCE_HOLDS == {"yes": "Anlass bestätigt",
                                    "no": "Anlass nicht bestätigt", "unknown": "Beleg unklar"}
    assert texts.EVIDENCE_LINE.format(article="GEBIT Ente (Quietscheente gelb)",
                                      reason=texts.REASON_LABELS["slow_seller"],
                                      holds=texts.EVIDENCE_HOLDS["yes"]) == (
        "GEBIT Ente (Quietscheente gelb) · Ladenhüter: Anlass bestätigt")
    assert texts.TEMPLATE_TEXT == "Vorlagentext der Engine (KI-Text verworfen)"
    assert texts.GUARDRAILS_TITLE == "Leitplanken der Engine (ohne KI)"
    assert texts.RUN_LABEL_DENIED == "Abgelehnt"
    assert texts.REVIEW_WITHOUT_AI == "Regel-Analyse (ohne KI) – keine Preisanpassung nötig"
    assert texts.MONITOR_LABELS["timeline"] == "KI-Schritte"
    assert not hasattr(texts, "AI_PROPOSAL") and not hasattr(texts, "AI_DECLINES")


def test_s1_timeline_verbatim() -> None:
    """6.3: the S1 KI-Schritte with display names (golden values 9,99 € -> 7,99 €)."""
    steps, fast, planning = texts.TIMELINE_STEPS, texts.model_name("fast"), \
        texts.model_name("planning")
    assert steps["rules"].format(candidates=1) == (
        "Regel-Analyse (ohne KI): 1 Kandidat(en) markiert")
    assert steps["evidenceDone"].format(model=fast, n=2) == (
        "Claude Haiku 4.5 prüft Belege über 2 API-Abfragen")
    assert steps["evidenceDetail"].format(holding=1, checked=1) == "1 von 1 Anlässen bestätigt"
    assert [texts.AGENT_ASKS.format(model=fast, family=texts.API_FAMILIES[s], tool=t)
            for s, t in (("pos", "get_transaction"), ("wws", "get_sales_performance"))] == [
        "Claude Haiku 4.5 fragt Kasse: get_transaction",
        "Claude Haiku 4.5 fragt Warenwirtschaft: get_sales_performance"]
    assert steps["planningPropose"].format(
        model=planning, article="GEBIT Ente (Quietscheente gelb)",
        reason=texts.REASON_LABELS["slow_seller"]) == (
        "Claude Sonnet 5 empfiehlt: GEBIT Ente (Quietscheente gelb) (Ladenhüter)")
    assert steps["engine"].format(old="9,99", new="7,99") == (
        "Engine prüft Leitplanken und rechnet den Preis (ohne KI): 9,99 € → 7,99 €")
    assert steps["approver"].format(model=fast) == (
        "Claude Haiku 4.5 legt der Marktleitung die Freigabe vor")
    assert steps["evidenceRunning"].format(model=fast) == "Claude Haiku 4.5 prüft Belege …"
    assert steps["planningRunning"].format(model=planning) == (
        "Claude Sonnet 5 wertet die Belege aus …")
    assert steps["planningNoAction"].format(model=planning) == (
        "Claude Sonnet 5 empfiehlt: keine Preisänderung")
    assert steps["planningFailed"].format(model=planning) == (
        "Claude Sonnet 5: keine Empfehlung (Lauf abgebrochen)")
    assert steps["engineBlocked"].format(reason="KI-Empfehlung ohne bestätigten Beleg") == (
        "Engine blockiert die Empfehlung: KI-Empfehlung ohne bestätigten Beleg")
    # every placeholder is one of the documented ones (the JS fills the same names)
    known = {"model", "n", "holding", "checked", "article", "reason", "old", "new",
             "candidates"}
    for text in steps.values():
        assert set(re.findall(r"\{(\w+)\}", text)) <= known


def test_texts_js_is_one_frozen_object_with_raw_umlauts() -> None:
    js = texts.texts_js()
    match = re.fullmatch(r"window\.GPOS_TEXTS = Object\.freeze\((.*)\);\n", js, re.DOTALL)
    assert match
    bundle = json.loads(match.group(1))
    assert bundle["states"] == texts.STATE_TEXTS
    assert bundle["reasons"]["slow_seller"] == "Ladenhüter"
    assert bundle["kasse"]["buttons"]["pay"] == "Bezahlen (bar)"
    assert bundle["runLabels"] == {"ok": "ok", "error": "Fehler", "expired": "Abgelaufen",
                                   "denied": "Abgelehnt"}
    assert (bundle["models"], bundle["defaultModel"]) == (["fast", "planning"], "fast")
    assert bundle["modelNames"] == texts.MODEL_NAMES
    monitor = bundle["monitor"]
    assert monitor["timelineSteps"] == texts.TIMELINE_STEPS
    assert (monitor["ruleAnalysis"], monitor["aiRecommendation"], monitor["templateText"],
            monitor["guardrailsTitle"], monitor["stampBy"]) == (
        texts.RULE_ANALYSIS, texts.AI_RECOMMENDATION, texts.TEMPLATE_TEXT,
        texts.GUARDRAILS_TITLE, texts.STAMP_BY)
    assert monitor["evidenceHolds"] == texts.EVIDENCE_HOLDS
    assert (monitor["evidenceTitle"], monitor["evidenceLine"],
            monitor["noChangeRecommended"]) == (texts.EVIDENCE_TITLE, texts.EVIDENCE_LINE,
                                                texts.NO_CHANGE_RECOMMENDED)
    assert "aiProposal" not in monitor and "aiDeclines" not in monitor
    assert "\\u" not in js and "Ladenhüter" in js


def test_texts_js_served(ui) -> None:
    response = ui.client.get("/static/shared/texts.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.text == texts.texts_js()
