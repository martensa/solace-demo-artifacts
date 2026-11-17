"""scripts/render_mesh.py against spec 9.6 (placeholders, R1_MODE, r1_mode memory)."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
import yaml

import render_mesh

R1_TOPICS = [
    "gebit/rp/purchase/v2/basket/PositionAdded/DE/999/101/01/>",
    "gebit/rp/purchase/v2/basket/ArticlePositionVoided/DE/999/101/01/>",
    "gebit/rp/purchase/v2/loyalty/LoyaltyMembershipAssigned/DE/999/101/01/>",
    "gebit/rp/purchase/v2/purchase_transaction/PurchaseTransactionClosed/DE/999/101/01/>",
    "gebit/rp/purchase/v2/purchase_transaction/PurchaseTransactionCancelled/DE/999/101/01/>",
]


def render(tmp_path: Path, *extra: str) -> int:
    empty = tmp_path / "empty.env"
    empty.write_text("")
    return render_mesh.main(["--env-file", str(empty), "--out", str(tmp_path / "out"), *extra])


def rules(tmp_path: Path, part: str) -> dict[str, dict]:
    name = render_mesh.ENTRYPOINTS[part]
    doc = yaml.safe_load((tmp_path / "out" / "entrypoints" / f"{name}.yaml").read_text())
    return {r["name"]: r for r in doc["spec"]["values"]["event_rules"]}


def test_booth_own_mode_binds_the_own_queue(tmp_path: Path, dummy_broker) -> None:
    assert render(tmp_path) == 0
    booth = rules(tmp_path, "booth")
    assert list(booth) == ["r1_booth_till", "r3_basket_review", "r4_price_approval"]
    assert booth["r1_booth_till"]["existingQueueName"] == "gpos-booth-r1"
    assert "subscriptions" not in booth["r1_booth_till"]
    assert booth["r3_basket_review"]["subscriptions"] == [
        {"topic": "gpos/v1/review/request/101/01/>", "qos": 1}]
    assert booth["r4_price_approval"]["subscriptions"] == [
        {"topic": "gpos/v1/approval/request/101/01/>", "qos": 1}]
    for rule, short in zip(booth.values(), ("r1", "r3", "r4"), strict=True):
        assert rule["defaultUserIdentity"] == "marktleitung@solace.lab"
        assert rule["successOutput"]["topic"] == f"gpos/v1/sam/done/{short}"
        assert rule["errorOutput"]["topic"] == f"gpos/v1/sam/error/{short}"
        assert rule["acknowledgmentPolicy"] == {"mode": "on_receive"}
        assert rule["inputExpression"] == "input.payload:"


def test_booth_sam_mode_subscribes_the_five_events(tmp_path: Path, dummy_broker,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R1_MODE", "sam")
    assert render(tmp_path) == 0
    r1 = rules(tmp_path, "booth")["r1_booth_till"]
    assert "existingQueueName" not in r1
    assert [s["topic"] for s in r1["subscriptions"]] == R1_TOPICS


def test_probe_entrypoint_uses_till_98_of_store_199(tmp_path: Path, dummy_broker) -> None:
    assert render(tmp_path) == 0
    probe = rules(tmp_path, "probe")
    assert list(probe) == ["p1_probe_till", "p3_probe_review", "p4_probe_approval"]
    assert [s["topic"] for s in probe["p1_probe_till"]["subscriptions"]] == [
        t.replace("DE/999/101/01", "DE/999/199/98") for t in R1_TOPICS]
    assert probe["p3_probe_review"]["subscriptions"][0]["topic"] == (
        "gpos/v1/review/request/199/98/>")
    assert probe["p4_probe_approval"]["subscriptions"][0]["topic"] == (
        "gpos/v1/approval/request/199/98/>")
    assert {r["targetWorkflowName"] for r in probe.values()} == {
        "gpos-pos-event", "gpos-basket-review", "gpos-price-approval"}
    assert [r["successOutput"]["topic"] for r in probe.values()] == [
        "gpos/v1/sam/done/p1", "gpos/v1/sam/done/p3", "gpos/v1/sam/done/p4"]


def test_credentials_survive_quoting_and_are_private(tmp_path: Path, dummy_broker,
                                                     capsys: pytest.CaptureFixture) -> None:
    user, password = dummy_broker
    assert render(tmp_path) == 0
    out = tmp_path / "out"
    for part, name in render_mesh.ENTRYPOINTS.items():
        path = out / "entrypoints" / f"{name}.yaml"
        values = yaml.safe_load(path.read_text())["spec"]["values"]
        assert (values["broker_username"], values["broker_password"]) == (user, password)
        assert values["broker_url"] == "ws://host.docker.internal:8008"
        assert values["broker_vpn"] == "default"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE((out / f"manifest-{part}.yaml").stat().st_mode) == 0o600
        text = path.read_text()
        assert "__" not in text and "R1_MODE=" not in text
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    printed = capsys.readouterr()
    assert password not in printed.out + printed.err


def test_manifests_name_exactly_one_entrypoint(tmp_path: Path, dummy_broker) -> None:
    assert render(tmp_path) == 0
    for part, name in render_mesh.ENTRYPOINTS.items():
        manifest = yaml.safe_load((tmp_path / "out" / f"manifest-{part}.yaml").read_text())
        assert manifest["resources"] == {"entrypoints": [name]}
        assert manifest["target"]["url"] == "https://sam.solace.lab"


def test_r1_mode_switch_needs_the_flag(tmp_path: Path, dummy_broker,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    assert render(tmp_path) == 0
    assert render(tmp_path, "--mark-applied") == 0
    assert (tmp_path / "out" / "r1_mode").read_text() == "own\n"
    monkeypatch.setenv("R1_MODE", "sam")
    assert render(tmp_path) == 3                     # hard rule 4: no silent switch
    assert render(tmp_path, "--switch-r1") == 0
    assert (tmp_path / "out" / "r1_mode").read_text() == "own\n"   # recorded only after apply


def test_unknown_r1_mode_is_refused(tmp_path: Path, dummy_broker,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R1_MODE", "both")
    assert render(tmp_path) == 2


def test_missing_credentials_file_is_reported(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch,
                                              capsys: pytest.CaptureFixture) -> None:
    for key in ("BROKER_USERNAME", "BROKER_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BROKER_CREDENTIALS_FROM", str(tmp_path / "missing.env"))
    assert render(tmp_path) == 2
    assert "missing.env missing" in capsys.readouterr().err


def test_credentials_from_the_bsg_style_file(tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("BROKER_USERNAME", "BROKER_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    creds = tmp_path / "bsg.env"
    creds.write_text("MQTT_USERNAME=bsg-user\nMQTT_PASSWORD='s3cr#t'\n")
    monkeypatch.setenv("BROKER_CREDENTIALS_FROM", str(creds))
    assert render(tmp_path) == 0
    doc = yaml.safe_load((tmp_path / "out/entrypoints/gpos-booth-events.yaml").read_text())
    assert (doc["spec"]["values"]["broker_username"],
            doc["spec"]["values"]["broker_password"]) == ("bsg-user", "s3cr#t")


def test_r1_topics_and_broker_env(tmp_path: Path, dummy_broker) -> None:
    user, password = dummy_broker
    assert render_mesh.r1_topics({}) == R1_TOPICS
    target = tmp_path / "broker.env"
    assert render_mesh.main(["--env-file", str(tmp_path / "none"),
                             "--write-broker-env", str(target)]) == 0
    lines = dict(line.split("=", 1) for line in target.read_text().splitlines())
    assert lines == {"SOLACE_HOST": "tcp://host.docker.internal:55557", "SOLACE_VPN": "default",
                     "SOLACE_USERNAME": user, "SOLACE_PASSWORD": password}
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_marker_blocks_are_selected() -> None:
    text = ("a\n  # >>> R1_MODE=own\n  own\n  # <<< R1_MODE=own\n"
            "  # >>> R1_MODE=sam\n  sam\n  # <<< R1_MODE=sam\nb\n")
    assert render_mesh.select_r1_block(text, "own") == "a\n  own\nb\n"
    assert render_mesh.select_r1_block(text, "sam") == "a\n  sam\nb\n"
