"""postgres/gen_seed.py (UC1-BUILD-SPEC 5.7, 6.2-6.5): rows and rendered SQL."""

import shutil
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any
from zoneinfo import ZoneInfo

import pytest

TZ = ZoneInfo("Europe/Berlin")
D = date(2027, 2, 16)
WINDOW = [D - timedelta(days=56) + timedelta(days=7 * k) for k in range(8)]

Rows = dict[str, list[dict[str, Any]]]


def local(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


# ------------------------------------------------------------------ sales_daily


def test_split_week_without_remainder(gen_seed: ModuleType) -> None:
    monday = date(2027, 2, 8)
    assert gen_seed.split_week(100, monday) == [
        (monday + timedelta(days=i), units) for i, units in enumerate((14, 15, 15, 16, 19, 21))]


def test_split_week_largest_remainder_and_tie_to_earlier_weekday(gen_seed: ModuleType) -> None:
    monday = date(2027, 2, 8)
    # quotas 1.4 1.5 1.5 1.6 1.9 2.1: +1 for Fri (.9), Thu (.6) and Tue (.5 before Wed .5)
    assert [u for _, u in gen_seed.split_week(10, monday)] == [1, 2, 1, 2, 2, 2]
    tuesday = date(2027, 2, 9)  # the demo windows start on a Tuesday
    assert gen_seed.split_week(9, tuesday) == [
        (date(2027, 2, 9), 1), (date(2027, 2, 10), 1), (date(2027, 2, 11), 2),
        (date(2027, 2, 12), 2), (date(2027, 2, 13), 2), (date(2027, 2, 15), 1)]


def test_weekly_sums_exact_for_every_article_and_store(
        wws_rows: Rows, articles_by_number: dict[str, dict[str, Any]]) -> None:
    sums: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * 8)
    for row in wws_rows["wws.sales_daily"]:
        week = (row["day"] - WINDOW[0]).days // 7
        sums[(row["article_number"], row["store_id"])][week] += row["units"]
    assert len(sums) == 60
    for (number, _store), weekly in sums.items():
        assert weekly == articles_by_number[number]["w"], number


def test_daily_rows_mon_to_sat_within_the_8_weeks(wws_rows: Rows) -> None:
    rows = wws_rows["wws.sales_daily"]
    assert len(rows) == 30 * 2 * 8 * 6
    assert all(r["day"].weekday() != 6 for r in rows)
    assert all(WINDOW[0] <= r["day"] <= D - timedelta(days=1) for r in rows)
    per_pair = Counter((r["article_number"], r["store_id"]) for r in rows)
    assert set(per_pair.values()) == {48}


def test_ente_last_seven_days(wws_rows: Rows) -> None:
    last7 = [r for r in wws_rows["wws.sales_daily"] if r["article_number"] == "100001"
             and r["store_id"] == "101" and r["day"] >= D - timedelta(days=7)]
    assert sum(r["units"] for r in last7) == 9
    assert {r["day"].isoweekday() for r in last7} == {1, 2, 3, 4, 5, 6}


# ---------------------------------------------------------------- master data


def test_articles_rows(wws_rows: Rows, articles: list[dict[str, Any]]) -> None:
    rows = wws_rows["wws.article"]
    assert [(r["article_number"], r["article_id"], r["gtin"], r["sort_order"]) for r in rows] == [
        (a["number"], "ID" + a["number"], a["gtin"], i) for i, a in enumerate(articles, 1)]
    labels = {r["category"]: r["category_label"] for r in rows}
    assert labels == {
        "spielwaren_geschenke": "Spielwaren & Geschenke", "obst_gemuese": "Obst & Gemüse",
        "suesswaren_snacks": "Süßwaren & Snacks", "getraenke": "Getränke",
        "molkerei_fruehstueck": "Molkerei & Frühstück", "kaffee_tee": "Kaffee & Tee",
        "drogerie_haushalt": "Drogerie & Haushalt", "buch": "Bücher"}
    kochbuch = rows[27]
    assert (kochbuch["price_bound"], kochbuch["vat_pct"], kochbuch["season_code"]) == (
        True, Decimal("7"), None)


def test_both_stores_identical(wws_rows: Rows) -> None:
    for table in ("wws.article_price", "wws.sales_plan", "wws.sales_daily", "wws.stock",
                  "wws.price_history", "wws.inbound_delivery", "wws.price_action"):
        by_store: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
        for row in wws_rows[table]:
            key = tuple(v for k, v in row.items()
                        if k not in ("store_id", "action_id", "delivery_id"))
            by_store[row["store_id"]].append(key)
        assert set(by_store) == {"101", "199"}, table
        assert by_store["101"] == by_store["199"], table


def test_espresso_price_history_and_delivery(wws_rows: Rows) -> None:
    history = [(r["valid_from"], r["valid_to"], r["price"], r["kind"])
               for r in wws_rows["wws.price_history"]
               if r["article_number"] == "100012" and r["store_id"] == "101"]
    assert history == [
        (local(2026, 11, 18), local(2027, 1, 11), Decimal("12.99"), "REGULAR"),
        (local(2027, 1, 11), None, Decimal("14.49"), "REGULAR")]
    assert [(r["delivery_id"], r["expected_on"], r["quantity"])
            for r in wws_rows["wws.inbound_delivery"]] == [
        ("DL-101-100012-20270218", date(2027, 2, 18), 24),
        ("DL-199-100012-20270218", date(2027, 2, 18), 24)]


def test_regular_history_starts_90_days_back(wws_rows: Rows) -> None:
    rows = [r for r in wws_rows["wws.price_history"] if r["kind"] == "REGULAR"]
    assert len(rows) == 62
    assert {r["valid_from"] for r in rows if r["article_number"] != "100012"} == {
        local(2026, 11, 18)}


def test_central_action(wws_rows: Rows) -> None:
    actions = wws_rows["wws.price_action"]
    assert [(a["action_id"], a["store_id"]) for a in actions] == [
        ("PA-SEED-100009", "101"), ("PA-SEED-100009-199", "199")]
    action = actions[0]
    assert action | {"action_id": None, "store_id": None} == {
        "action_id": None, "article_number": "100009", "store_id": None, "kind": "CENTRAL",
        "regular_price": Decimal("3.49"), "action_price": Decimal("2.99"), "pct_shown": 14,
        "ref30": Decimal("3.49"), "valid_from": local(2027, 2, 8, 8),
        "valid_to": local(2027, 2, 21, 20), "proposal_id": None,
        "reason_code": "REASON_CODE_CENTRAL_PROMOTION", "originator": "zentrale",
        "approver": None, "created_at": local(2027, 2, 8, 8)}
    promo = [(r["price"], r["valid_from"], r["valid_to"]) for r in wws_rows["wws.price_history"]
             if r["kind"] == "PROMO" and r["store_id"] == "101"]
    assert promo == [(Decimal("2.99"), local(2027, 2, 8, 8), local(2027, 2, 21, 20))]


def test_tills(gen_seed: ModuleType) -> None:
    (till,) = gen_seed.pos_tables()
    assert till.rows == (("01", "101", "Root.DE.999.101.01", "booth", True),
                         ("98", "199", "Root.DE.999.199.98", "probe", True),
                         ("99", "199", "Root.DE.999.199.99", "test", True))


# ------------------------------------------------------------------- loyalty


def test_members_cards_consent(loyalty_rows: Rows) -> None:
    members = loyalty_rows["loyalty.member"]
    assert [(m["member_id"], m["customer_ref"], m["anonymous"], m["segment_label"])
            for m in members] == [
        ("M-1001", "CUST-DEMO-M-1001", False, "Stammkundin, preisbewusst"),
        ("M-1002", "CUST-DEMO-M-1002", False, "Familie, Wocheneinkauf"),
        ("M-1003", "CUST-DEMO-M-1003", False, "Spontaneinkauf"),
        ("M-1004", "CUST-DEMO-M-1004", False, "Genießer, saisonaffin"),
        ("M-1005", None, True, "Gast")]
    assert [(c["card_value"], c["card_type"]) for c in loyalty_rows["loyalty.card"]] == [
        ("CLUB-1001", "PHYSICAL"), ("CLUB-1002", "PHYSICAL"), ("CLUB-1003", "PHYSICAL"),
        ("CLUB-1004", "PHYSICAL"), ("CLUB-GAST", "GUEST")]
    assert {(c["policy_version"], c["source"]) for c in loyalty_rows["loyalty.consent"]} == {
        ("2027-01", "seed")}
    assert len(loyalty_rows["loyalty.tag_vocabulary"]) == 10
    assert [(a["account_id"], a["balance"]) for a in loyalty_rows["loyalty.account"]][0] == (
        "ACC-M-1001-POINTS", Decimal("0.00"))


def test_purchases_per_member(loyalty_rows: Rows) -> None:
    counts = Counter(p["member_id"] for p in loyalty_rows["loyalty.purchase"])
    assert {m: counts.get(m, 0) for m in ("M-1001", "M-1002", "M-1003", "M-1004", "M-1005")} == {
        "M-1001": 12, "M-1002": 13, "M-1003": 12, "M-1004": 15, "M-1005": 0}


def test_purchase_lines_per_member(loyalty_rows: Rows) -> None:
    member_of = {p["purchase_transaction_id"]: p["member_id"]
                 for p in loyalty_rows["loyalty.purchase"]}
    counts = Counter(member_of[ln["purchase_transaction_id"]]
                     for ln in loyalty_rows["loyalty.purchase_line"])
    # M-1001: 12 croissants + 12 milk + 6 cantuccini + 4 espresso; M-1002: 13 x 5 weekly
    # articles + 7 chocolate + 1 Ente; M-1004: 12 chocolate + 6 cantuccini + 1 + 2
    assert counts == {"M-1001": 34, "M-1002": 73, "M-1004": 21}


def test_purchase_headers(loyalty_rows: Rows) -> None:
    purchases = loyalty_rows["loyalty.purchase"]
    first = purchases[0]
    assert first["purchase_transaction_id"] == uuid.uuid5(uuid.NAMESPACE_URL,
                                                          "M-1001-2026-11-24")
    assert (first["receipt_number"], first["closed_at"], first["location"]) == (
        "SEED-M-1001-20261124", local(2026, 11, 24, 10, 30), "Root.DE.999.101.01")
    assert all(p["is_seed"] and p["transaction_type"] == "SALE"
               and p["points_earned"] == Decimal("0.00") and p["closed_at"].date() < D
               for p in purchases)
    assert len({p["purchase_transaction_id"] for p in purchases}) == len(purchases)


def test_kaffeepause_espresso_purchases(loyalty_rows: Rows) -> None:
    by_tx = {p["purchase_transaction_id"]: p for p in loyalty_rows["loyalty.purchase"]}
    espresso = sorted((by_tx[ln["purchase_transaction_id"]]["closed_at"].date(),
                       ln["effective_value_eur"])
                      for ln in loyalty_rows["loyalty.purchase_line"]
                      if ln["article_number"] == "100012")
    assert espresso == [(date(2026, 12, 1), Decimal("12.99")),
                        (date(2026, 12, 15), Decimal("12.99")),
                        (date(2026, 12, 29), Decimal("12.99")),
                        (date(2027, 1, 12), Decimal("14.49"))]
    in_8w = [d for d, _ in espresso if D - timedelta(days=56) <= d <= D - timedelta(days=1)]
    assert in_8w == [date(2026, 12, 29), date(2027, 1, 12)]


def test_lines_only_with_profiling_and_totals(loyalty_rows: Rows) -> None:
    lines = defaultdict(list)
    for line in loyalty_rows["loyalty.purchase_line"]:
        lines[line["purchase_transaction_id"]].append(line)
    for purchase in loyalty_rows["loyalty.purchase"]:
        tx_lines = lines[purchase["purchase_transaction_id"]]
        if purchase["member_id"] == "M-1003":
            assert tx_lines == [] and purchase["total_eur"] == Decimal("9.35")
        else:
            assert tx_lines and purchase["total_eur"] == sum(
                ln["effective_value_eur"] for ln in tx_lines)
            assert len({ln["position_id"] for ln in tx_lines}) == len(tx_lines)


def test_cardholder_stats_rule_and_espresso_override(
        loyalty_rows: Rows, articles: list[dict[str, Any]]) -> None:
    stats = defaultdict(list)
    for row in loyalty_rows["loyalty.article_week_stats"]:
        stats[row["article_number"]].append(row)
    assert len(stats) == 30 and all(len(rows) == 8 for rows in stats.values())
    assert [r["week_start"] for r in stats["100012"]] == WINDOW
    assert [r["member_purchases"] for r in stats["100012"]] == [22, 24, 21, 23, 13, 12, 11, 12]
    assert [r["member_purchases"] for r in stats["100001"]] == [19, 20, 17, 15, 12, 9, 7, 5]
    for article in articles:
        rows = stats[article["number"]]
        for row in rows:
            purchases = row["member_purchases"]
            assert row["distinct_members"] == int(Decimal(purchases) * Decimal("0.8")
                                                  + Decimal("0.5"))
        if article["number"] != "100012":
            assert [r["member_purchases"] for r in rows] == [
                int(Decimal(w) * Decimal("0.55") + Decimal("0.5")) for w in article["w"]]


# ---------------------------------------------------------- types and rendering


def test_numbers_are_decimal_never_float(gen_seed: ModuleType, sources: Any) -> None:
    tables = (gen_seed.wws_tables(sources, D) + gen_seed.loyalty_tables(sources, D)
              + gen_seed.pos_tables())
    values = [v for t in tables for row in t.rows for v in row]
    assert not [v for v in values if isinstance(v, float)]
    assert sources.article("100001").price == Decimal("9.99")
    assert isinstance(sources.program.earn_eur_per_point, Decimal)


def test_sql_literals(gen_seed: ModuleType) -> None:
    lit = gen_seed.sql_literal
    assert lit(None) == "null" and lit(True) == "true" and lit(14) == "14"
    assert lit(Decimal("9.99")) == "9.99" and lit(Decimal("2.00")) == "2.00"
    assert lit("Kochbuch „Regional kochen“") == "'Kochbuch „Regional kochen“'"
    assert lit("it's") == "'it''s'"
    assert lit(date(2027, 2, 16)) == "'2027-02-16'"
    assert lit(local(2027, 2, 21, 20)) == "'2027-02-21 20:00:00+01:00'"


def test_rendered_files_are_transactions_under_the_service_role(
        gen_seed: ModuleType, sources: Any) -> None:
    files = gen_seed.render_seed(sources, D)
    assert list(files) == ["90-seed-wws.sql", "91-seed-loyalty.sql", "92-seed-pos.sql"]
    for name, schema in zip(files, ("wws", "loyalty", "pos"), strict=True):
        text = files[name]
        assert "\\if :{?role_prefix}\n\\else\n\\set role_prefix gpos\n\\endif\n" in text
        assert f"\\set r_{schema} :role_prefix _{schema}\n" in text
        assert f'begin;\nset local role :"r_{schema}";\n' in text
        assert text.endswith("\ncommit;\n") and text.count("begin;") == 1
    assert ("truncate wws.season, wws.article, wws.article_price, wws.price_history, "
            "wws.price_action, wws.sales_plan, wws.sales_daily, wws.stock, "
            "wws.inbound_delivery cascade;") in files["90-seed-wws.sql"]
    assert ("truncate loyalty.program, loyalty.article_ref, loyalty.tag_vocabulary, "
            "loyalty.member, loyalty.card, loyalty.consent, loyalty.member_tag, "
            "loyalty.account, loyalty.purchase, loyalty.purchase_line, "
            "loyalty.article_week_stats, loyalty.points_ledger, loyalty.coupon, "
            "loyalty.offer cascade;") in files["91-seed-loyalty.sql"]
    assert "truncate" not in files["92-seed-pos.sql"]
    assert "on conflict (till_id) do update set" in files["92-seed-pos.sql"]


def test_render_is_deterministic(gen_seed: ModuleType, sql_dir: Path) -> None:
    data_dir = sql_dir.parent.parent / "data"
    first = gen_seed.render_seed(gen_seed.load_sources(data_dir), D)
    second = gen_seed.render_seed(gen_seed.load_sources(data_dir), D)
    assert first == second


def test_cli_writes_the_three_files(gen_seed: ModuleType, sources: Any,
                                    tmp_path: Path) -> None:
    out = tmp_path / "generated"
    assert gen_seed.main(["--demo-date", "2027-02-16", "--out", str(out)]) == 0
    expected = gen_seed.render_seed(sources, D)
    assert sorted(p.name for p in out.iterdir()) == sorted(expected)
    for name, text in expected.items():
        assert (out / name).read_text(encoding="utf-8") == text


def _data_copy(sql_dir: Path, tmp_path: Path) -> Path:
    data = tmp_path / "data"
    shutil.copytree(sql_dir.parent.parent / "data", data)
    return data


def test_cli_rejects_invalid_data(gen_seed: ModuleType, sql_dir: Path, tmp_path: Path,
                                  capsys: pytest.CaptureFixture[str]) -> None:
    data = _data_copy(sql_dir, tmp_path)
    articles = data / "articles.yaml"
    articles.write_text(articles.read_text(encoding="utf-8").replace(
        'number: "100001"', "number: 100001"), encoding="utf-8")
    code = gen_seed.main(["--demo-date", "2027-02-16", "--out", str(tmp_path / "out"),
                          "--data-dir", str(data)])
    assert code == 1
    assert "articles[0].number: non-empty string expected" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_purchases_must_lie_before_the_demo_date(gen_seed: ModuleType, sources: Any) -> None:
    with pytest.raises(gen_seed.SeedDataError, match="not before demo date"):
        gen_seed.loyalty_tables(sources, date(2027, 2, 13))
