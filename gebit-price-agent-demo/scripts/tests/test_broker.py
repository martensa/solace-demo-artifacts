"""scripts/broker.py: R1 queue convergence and orphan listing (spec 9.6, hard rule 4)
against an in-memory SEMP v2 double (no broker)."""

from __future__ import annotations

import base64
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

import broker
import opslib
from opslib import OpsError

TOPICS = [f"gebit/rp/purchase/v2/{e}/DE/999/101/01/>" for e in (
    "basket/PositionAdded", "basket/ArticlePositionVoided", "loyalty/LoyaltyMembershipAssigned",
    "purchase_transaction/PurchaseTransactionClosed",
    "purchase_transaction/PurchaseTransactionCancelled")]
NOT_FOUND = (400, {"meta": {"error": {"status": "NOT_FOUND"}}})


@pytest.fixture(autouse=True)
def lab_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests pin the lab: a TARGET exported by the caller's shell (or `TARGET=aks
    make test`) must not leak in, also not through the paths fixed at import."""
    monkeypatch.delenv("TARGET", raising=False)
    monkeypatch.setattr(opslib, "TARGET", "lab")


class FakeSemp(broker.Semp):
    """Queues, subscriptions and txFlows of one VPN, addressed like SEMP v2."""

    def __init__(self) -> None:
        super().__init__("http://semp.test", "default", "Basic x")
        self.queues: dict[str, dict] = {}
        self.subs: dict[str, list[str]] = {}
        self.flows: dict[str, int] = {}
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, dict]:
        path, _, query = path.partition("?")
        parts = [urllib.parse.unquote(p) for p in path.split("/")]
        self.calls.append((method, "/".join(parts)))
        api, queue = parts[0], parts[4] if len(parts) > 4 else None
        if method == "GET" and api == "monitor" and queue is None:
            where = urllib.parse.unquote(query.split("where=")[1]).split("==")[1].rstrip("*")
            return 200, {"data": [{"queueName": q} for q in self.queues if q.startswith(where)]}
        if queue is not None and queue not in self.queues and not (method == "POST"):
            return NOT_FOUND
        if method == "POST" and queue is None:
            self.queues[body["queueName"]] = {k: v for k, v in body.items() if k != "queueName"}
            self.subs[body["queueName"]] = []
            return 200, {}
        tail = parts[5] if len(parts) > 5 else None
        if tail == "txFlows":
            return 200, {"data": [{"clientName": "gwe"}] * self.flows.get(queue, 0)}
        if tail == "subscriptions":
            if method == "GET":
                return 200, {"data": [{"subscriptionTopic": t} for t in self.subs[queue]]}
            if method == "POST":
                self.subs[queue].append(body["subscriptionTopic"])
            else:
                self.subs[queue].remove(parts[6])
            return 200, {}
        if method == "GET":
            return 200, {"data": self.queues[queue]}
        if method == "PATCH":
            self.queues[queue].update(body)
        elif method == "DELETE":
            del self.queues[queue]
        return 200, {}


def test_create_uses_the_g0_10_attributes() -> None:
    semp = FakeSemp()
    actions = broker.converge_r1(semp, "gpos-booth-r1", TOPICS)
    assert semp.queues["gpos-booth-r1"] == {
        "accessType": "exclusive", "permission": "consume", "respectTtlEnabled": True,
        "maxTtl": 20, "maxRedeliveryCount": 1, "maxMsgSpoolUsage": 50,
        "ingressEnabled": True, "egressEnabled": True}
    assert semp.subs["gpos-booth-r1"] == TOPICS
    assert actions[0] == "created queue gpos-booth-r1" and len(actions) == 6
    assert broker.converge_r1(semp, "gpos-booth-r1", TOPICS) == []      # converged


def test_drift_is_patched_never_recreated() -> None:
    semp = FakeSemp()
    broker.converge_r1(semp, "gpos-booth-r1", TOPICS)
    semp.queues["gpos-booth-r1"].update(maxTtl=0, egressEnabled=False)
    semp.subs["gpos-booth-r1"].append("gpos/old/>")
    semp.calls.clear()
    actions = broker.converge_r1(semp, "gpos-booth-r1", TOPICS)
    assert actions == ["patched egressEnabled, maxTtl", "- gpos/old/>"]
    assert not any(m in ("POST", "DELETE") and p.endswith("queues/gpos-booth-r1")
                   for m, p in semp.calls)
    assert semp.queues["gpos-booth-r1"]["maxTtl"] == 20


def test_orphans_are_sam_queues_without_flows(capsys: pytest.CaptureFixture) -> None:
    semp = FakeSemp()
    prefix = broker.SAM_QUEUE_PREFIX_DEFAULT
    for name, flows in ((f"{prefix}ep1/r3_basket_review", 1), (f"{prefix}ep1/r2_old", 0),
                        ("gpos-booth-r1", 0)):
        semp.queues[name], semp.subs[name], semp.flows[name] = {}, [], flows
    assert broker.cmd_orphans(semp, prefix) == broker.EXIT_FINDING
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"queues under {prefix}: 2, without txFlows: 1"
    assert [ln.strip() for ln in lines if "ORPHAN" in ln] == [f"ORPHAN {prefix}ep1/r2_old"]


def test_switch_own_to_sam_unsubscribes_the_own_queue() -> None:
    semp = FakeSemp()
    broker.converge_r1(semp, "gpos-booth-r1", TOPICS)
    assert broker.cmd_r1_switch(semp, {}, "gpos-booth-r1", "own", "sam", "p/") == 0
    assert semp.subs["gpos-booth-r1"] == [] and "gpos-booth-r1" in semp.queues


def test_switch_sam_to_own_deletes_the_sam_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    semp = FakeSemp()
    sam_queue = f"{broker.SAM_QUEUE_PREFIX_DEFAULT}ep-42/r1_booth_till"
    semp.queues[sam_queue], semp.subs[sam_queue] = {}, []
    monkeypatch.setattr(broker, "booth_entrypoint_id", lambda env: "ep-42")
    assert broker.cmd_r1_switch(semp, {}, "gpos-booth-r1", "sam", "own",
                                broker.SAM_QUEUE_PREFIX_DEFAULT) == 0
    assert sam_queue not in semp.queues
    with pytest.raises(OpsError):
        broker.cmd_r1_switch(semp, {}, "gpos-booth-r1", "own", "own", "p/")


def test_rule_queues_follow_r1_mode() -> None:
    prefix = broker.SAM_QUEUE_PREFIX_DEFAULT
    assert broker.rule_queues("ep", "booth", "own", "gpos-booth-r1", prefix) == [
        "gpos-booth-r1", f"{prefix}ep/r3_basket_review", f"{prefix}ep/r4_price_approval"]
    assert broker.rule_queues("ep", "booth", "sam", "gpos-booth-r1", prefix)[0] == (
        f"{prefix}ep/r1_booth_till")
    assert broker.rule_queues("ep", "probe", "own", "gpos-booth-r1", prefix) == [
        f"{prefix}ep/p1_probe_till", f"{prefix}ep/p3_probe_review",
        f"{prefix}ep/p4_probe_approval"]


def test_semp_password_is_read_not_echoed(tmp_path: Path) -> None:
    tfvars = tmp_path / "terraform.tfvars"
    tfvars.write_text('solace_1_url = "http://x"\nsolace_1_password = "tf-se cret"\n')
    assert broker.read_semp_password(tfvars, "solace_1_password") == "tf-se cret"
    with pytest.raises(OpsError, match="solace_2_password not found"):
        broker.read_semp_password(tfvars, "solace_2_password")


def test_lab_session_reads_the_tfvars_and_never_probes(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """TARGET unset = lab: SEMP_PASSWORD_FROM as before, no port probe, no forward,
    no Key Vault (AKS-MIGRATION-PLAN 1.4)."""
    tfvars = tmp_path / "terraform.tfvars"
    tfvars.write_text('solace_1_password = "tf-pw"\n')
    for key in ("TARGET", "SEMP_URL", "SEMP_USER", "BROKER_VPN"):
        monkeypatch.delenv(key, raising=False)

    def forbidden(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("no AKS preflight in the lab")

    monkeypatch.setattr(broker, "listening", forbidden)
    monkeypatch.setattr(broker, "kv_secret", forbidden)
    monkeypatch.setattr(broker, "port_forward", forbidden)
    with broker.semp_session({"SEMP_PASSWORD_FROM": str(tfvars)}) as semp:
        assert (semp.base, semp.vpn) == ("http://localhost:8080", "default")
        assert semp.auth == "Basic " + base64.b64encode(b"admin:tf-pw").decode()
