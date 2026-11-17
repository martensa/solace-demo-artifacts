"""Schema and cross-reference checks of data/*.yaml (UC1-BUILD-SPEC 1.3, 6.1-6.4, 5.7)."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
YAML_FILES = ("articles.yaml", "seasons.yaml", "central_actions.yaml", "personas.yaml",
              "scenarios.yaml")
YAML11_BOOLEAN_WORDS = {"no", "on", "off", "yes", "y", "n", "true", "false"}

# 6.1 tag -> (label, default VAT); Hafermilch 100030 is the only 19 % article of molkerei
CATEGORY_VAT = {
    "obst_gemuese": 7, "molkerei_fruehstueck": 7, "kaffee_tee": 7, "suesswaren_snacks": 7,
    "getraenke": 19, "drogerie_haushalt": 19, "spielwaren_geschenke": 19, "buch": 7,
}
VAT_EXCEPTIONS = {"100030": 19}
ARTICLE_KEYS = {"number", "gtin", "name", "cat", "pack", "qty", "unit", "vat", "price",
                "cost", "plan", "w", "stock", "listed"}
ARTICLE_OPTIONAL = {"season", "price_bound", "role", "price_change", "next_delivery"}
ROLES = {"100001": "hero_slow_seller", "100002": "agent_says_no",
         "100008": "hero_season_end", "100009": "guardrail_central_action",
         "100012": "hero_customer_behaviour", "100028": "guardrail_price_bound"}
MEMBER_KEYS = {"id", "card", "persona", "key", "segment", "salutation", "consent", "tags",
               "history", "anonymous"}

# 1.3 data/scenarios.yaml (binding: the /kasse buttons and the e2e runs use it)
SCENARIOS = [
    ("S1", "Ladenhüter", ["new", "2099100000018", "2099100000049", "2099100000100", "pay"]),
    ("S2", "Saisonende", ["new", "2099100000087", "2099100000131", "pay"]),
    ("S3", "Kundenverhalten",
     ["new", "card:CLUB-1001", "2099100000124", "2099100000179", "pay"]),
    ("S4", "Alles im Plan", ["new", "2099100000049", "2099100000162", "2099100000216", "pay"]),
    ("S5", "Leitplanke", ["new", "2099100000094", "2099100000285", "pay"]),
    ("S6", "Ohne Einwilligung", ["new", "card:CLUB-1003", "2099100000124", "pay"]),
    ("S7", "Zwei Kandidaten", ["new", "2099100000018", "2099100000087", "pay"]),
    ("S8", "Agent rät ab", ["new", "2099100000025", "2099100000100", "pay"]),
    ("S1b", "Ente nach Freigabe", ["new", "2099100000018", "pay"]),
]


def ean13_check_digit(first12: str) -> int:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return (10 - total % 10) % 10


def _walk_keys(node: Any) -> list[Any]:
    if isinstance(node, dict):
        return list(node) + [k for v in node.values() for k in _walk_keys(v)]
    if isinstance(node, list):
        return [k for item in node for k in _walk_keys(item)]
    return []


def _step_label(step: dict[str, Any]) -> str:
    match step["op"]:
        case "new" | "pay":
            return step["op"]
        case "card":
            return f"card:{step['value']}"
        case _:
            return step["value"]


# ------------------------------------------------------------------- all files


@pytest.mark.parametrize("name", YAML_FILES)
def test_no_yaml11_boolean_or_non_string_keys(name: str) -> None:
    with (DATA_DIR / name).open(encoding="utf-8") as handle:
        keys = _walk_keys(yaml.safe_load(handle))
    assert keys, name
    assert all(isinstance(k, str) for k in keys), [k for k in keys if not isinstance(k, str)]
    assert not {k.lower() for k in keys} & YAML11_BOOLEAN_WORDS


# -------------------------------------------------------------------- articles


def test_thirty_articles_numbered_in_file_order(articles: list[dict[str, Any]]) -> None:
    assert [a["number"] for a in articles] == [str(100001 + i) for i in range(30)]


def test_every_article_has_string_key_number(articles: list[dict[str, Any]]) -> None:
    for article in articles:
        assert "number" in article and isinstance(article["number"], str)


def test_article_keys(articles: list[dict[str, Any]]) -> None:
    for article in articles:
        keys = set(article)
        assert ARTICLE_KEYS <= keys, (article["number"], ARTICLE_KEYS - keys)
        assert keys <= ARTICLE_KEYS | ARTICLE_OPTIONAL, (article["number"], keys)


def test_gtin_prefix_20_and_check_digit(articles: list[dict[str, Any]]) -> None:
    for article in articles:
        gtin = article["gtin"]
        assert isinstance(gtin, str) and len(gtin) == 13 and gtin.isdigit()
        assert gtin.startswith("20")
        assert gtin[:12] == "2099100" + article["number"][-5:]
        assert int(gtin[12]) == ean13_check_digit(gtin[:12]), gtin


def test_gtins_numbers_and_names_unique(articles: list[dict[str, Any]]) -> None:
    for key in ("number", "gtin", "name"):
        values = [a[key] for a in articles]
        assert len(values) == len(set(values)), key


def test_categories_vat_and_units(articles: list[dict[str, Any]]) -> None:
    for article in articles:
        assert article["cat"] in CATEGORY_VAT
        expected_vat = VAT_EXCEPTIONS.get(article["number"], CATEGORY_VAT[article["cat"]])
        assert article["vat"] == expected_vat, article["number"]
        assert article["unit"] in ("g", "ml", "Stück")
        assert isinstance(article["qty"], int) and article["qty"] > 0


def test_numbers_types_and_positive_margin(articles: list[dict[str, Any]]) -> None:
    for article in articles:
        assert len(article["w"]) == 8
        assert all(isinstance(v, int) and v >= 0 for v in article["w"])
        assert isinstance(article["stock"], int) and article["stock"] >= 0
        assert isinstance(article["plan"], int) and article["plan"] > 0
        price, cost = Decimal(str(article["price"])), Decimal(str(article["cost"]))
        net = price / (1 + Decimal(article["vat"]) / 100)
        assert Decimal(0) < cost < net, article["number"]
        assert price == price.quantize(Decimal("0.01")) and cost == cost.quantize(
            Decimal("0.01"))
        assert isinstance(article["listed"], date)


def test_roles_price_bound_change_and_delivery(articles: list[dict[str, Any]]) -> None:
    assert {a["number"]: a["role"] for a in articles if "role" in a} == ROLES
    assert [a["number"] for a in articles if a.get("price_bound")] == ["100028"]
    assert [a["number"] for a in articles if a["cat"] == "buch"] == ["100028"]
    changes = {a["number"]: a["price_change"] for a in articles if "price_change" in a}
    assert changes == {"100012": {"date": date(2027, 1, 11), "from": 12.99}}
    deliveries = {a["number"]: a["next_delivery"] for a in articles if "next_delivery" in a}
    assert deliveries == {"100012": {"expected_on": date(2027, 2, 18), "qty": 24}}


def test_hero_master_data(articles_by_number: dict[str, dict[str, Any]]) -> None:
    ente = articles_by_number["100001"]
    assert (ente["name"], ente["price"], ente["cost"], ente["plan"], ente["stock"]) == (
        "GEBIT Ente (Quietscheente gelb)", 9.99, 5.20, 35, 96)
    assert articles_by_number["100008"]["season"] == "valentinstag"
    assert articles_by_number["100009"]["season"] == "winter"
    assert articles_by_number["100002"]["season"] == "ostern"
    assert articles_by_number["100012"]["price"] == 14.49


# ------------------------------------------------- seasons and central actions


def test_seasons(seasons: list[dict[str, Any]]) -> None:
    assert [(s["code"], s["label"], s["start"], s["end"]) for s in seasons] == [
        ("valentinstag", "Valentinstag", date(2027, 1, 18), date(2027, 2, 14)),
        ("winter", "Winter", date(2026, 11, 1), date(2027, 2, 28)),
        ("ostern", "Ostern", date(2027, 3, 1), date(2027, 3, 28)),
    ]


def test_article_seasons_exist(articles: list[dict[str, Any]],
                               seasons: list[dict[str, Any]]) -> None:
    codes = {s["code"] for s in seasons}
    assert {a["season"] for a in articles if "season" in a} <= codes


def test_central_action(central_actions: list[dict[str, Any]],
                        articles_by_number: dict[str, dict[str, Any]]) -> None:
    assert central_actions == [{
        "article": "100009", "price": 2.99, "from": "2027-02-08T08:00",
        "to": "2027-02-21T20:00", "ref30": 3.49,
        "reason_code": "REASON_CODE_CENTRAL_PROMOTION", "label": "Zentralaktion Winterende"}]
    action = central_actions[0]
    article = articles_by_number[action["article"]]
    assert action["price"] < article["price"]
    assert action["ref30"] == article["price"]  # 30 days before 08.02. only the regular


# -------------------------------------------------------------------- personas


def test_program(personas: dict[str, Any]) -> None:
    assert personas["program"] == {
        "id": "POINTS-ID", "name": "POINTS", "display": "Markt-Bonus",
        "account_type": "POINTS-ACCOUNT-ID", "currency_id": "POINTS-CURRENCY-ID",
        "currency_name": "Points", "base_promotion_id": "promotion-base-points",
        "earn_eur_per_point": 2.00}


def test_tag_vocabulary(personas: dict[str, Any]) -> None:
    tags = personas["tags"]
    assert {t for t, label in tags.items() if label is None} == set(CATEGORY_VAT)
    assert {t: label for t, label in tags.items() if label is not None} == {
        "familie": "Familie", "saison": "Saisonartikel"}


def test_members_and_cards(personas: dict[str, Any]) -> None:
    members = personas["members"]
    assert [(m["id"], m["card"], m["persona"], m["key"]) for m in members] == [
        ("M-1001", "CLUB-1001", "Kaffeepause", "kaffeepause"),
        ("M-1002", "CLUB-1002", "Familieneinkauf", "familieneinkauf"),
        ("M-1003", "CLUB-1003", "Feierabend", "feierabend"),
        ("M-1004", "CLUB-1004", "Genuss & Saison", "genuss_saison"),
        ("M-1005", "CLUB-GAST", "Gastkarte", "gast"),
    ]
    assert [(m["consent"]["offers"], m["consent"]["profiling"]) for m in members] == [
        (True, True), (True, True), (True, False), (True, True), (False, False)]
    assert [m["id"] for m in members if m.get("anonymous")] == ["M-1005"]
    assert members[4]["tags"] == [] and members[4]["history"] == []


def test_members_carry_no_personal_attributes(personas: dict[str, Any]) -> None:
    for member in personas["members"]:
        assert set(member) <= MEMBER_KEYS, member["id"]
        assert member["salutation"] in ("FORMAL", "INFORMAL")


def test_member_tags_and_history_articles_exist(
        personas: dict[str, Any], articles_by_number: dict[str, dict[str, Any]]) -> None:
    for member in personas["members"]:
        assert set(member["tags"]) <= set(personas["tags"]), member["id"]
        for rule in member["history"]:
            assert rule["article"] in articles_by_number, (member["id"], rule)


def test_history_entries_lie_on_their_cadence(personas: dict[str, Any],
                                              demo_date: date) -> None:
    for member in personas["members"]:
        for rule in member["history"]:
            first, last, every = rule["first"], rule["last"], rule["every_days"]
            assert isinstance(rule["qty"], int) and rule["qty"] > 0
            assert first <= last < demo_date
            if every == 0:
                assert first == last, rule
            else:
                assert (last - first).days % every == 0, rule


def test_kaffeepause_espresso_every_second_tuesday(personas: dict[str, Any]) -> None:
    rule = next(r for r in personas["members"][0]["history"] if r["article"] == "100012")
    days = [rule["first"] + timedelta(days=14 * k) for k in range(4)]
    assert days[-1] == rule["last"] == date(2027, 1, 12)
    assert all(d.weekday() == 1 for d in days)  # Tuesday


# ------------------------------------------------------------------- scenarios


def test_scenarios_exactly_as_spec(scenarios: list[dict[str, Any]]) -> None:
    actual = [(s["id"], s["label"], [_step_label(step) for step in s["steps"]])
              for s in scenarios]
    assert actual == SCENARIOS


def test_scenario_steps_well_formed(scenarios: list[dict[str, Any]]) -> None:
    for scenario in scenarios:
        assert set(scenario) == {"id", "label", "steps"}
        steps = scenario["steps"]
        assert steps[0] == {"op": "new"} and steps[-1] == {"op": "pay"}
        for step in steps[1:-1]:
            assert step["op"] in ("card", "scan") and set(step) == {"op", "value"}
            assert isinstance(step["value"], str)


def test_scenario_eans_and_cards_exist(scenarios: list[dict[str, Any]],
                                       articles: list[dict[str, Any]],
                                       personas: dict[str, Any]) -> None:
    gtins = {a["gtin"] for a in articles}
    cards = {m["card"] for m in personas["members"]}
    for scenario in scenarios:
        for step in scenario["steps"]:
            if step["op"] == "scan":
                assert step["value"] in gtins, (scenario["id"], step)
            if step["op"] == "card":
                assert step["value"] in cards, (scenario["id"], step)
