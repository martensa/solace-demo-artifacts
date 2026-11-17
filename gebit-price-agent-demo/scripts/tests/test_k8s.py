"""k8s/ against spec 12.4 and 3.1."""

from __future__ import annotations

import pytest
from conftest import ROOT, load, load_all

TABLE = {  # deployment: module, ports, DSN key, descriptor mount (spec 12.4)
    "gpos-pos": ("gposdemo.pos", {"grpc": 50051, "http": 8771}, "DSN_POS", True),
    "gpos-wws": ("gposdemo.wws", {"grpc": 50053, "http": 8773}, "DSN_WWS", False),
    "gpos-loyalty": ("gposdemo.loyalty", {"grpc": 50052, "http": 8772}, "DSN_LOYALTY", False),
    "gpos-engine": ("gposdemo.engine", {"http": 8765}, "DSN_ENGINE", False),
    "gpos-gate": ("gposdemo.engine.gate", {"http": 8766}, "DSN_ENGINE", False),
    "gpos-ui": ("gposdemo.ui", {"http": 8090}, None, True),
}
FILES = {"gpos-pos": "pos", "gpos-wws": "wws", "gpos-loyalty": "loyalty",
         "gpos-engine": "engine", "gpos-gate": "gate", "gpos-ui": "ui"}


def objects(name: str) -> dict[str, dict]:
    return {d["kind"]: d for d in load_all(f"k8s/{FILES[name]}.yaml")}


def test_kustomization_lists_every_file_and_the_image() -> None:
    k = load("k8s/kustomization.yaml")
    assert k["namespace"] == "gpos-demo"
    assert sorted(k["resources"]) == sorted(
        p.name for p in (ROOT / "k8s").glob("*.yaml") if p.name != "kustomization.yaml")
    assert k["images"] == [{"name": "gpos-demo",
                            "newName": "registry.solace.lab/gpos-demo/gpos-demo",
                            "newTag": "0.1.3"}]
    assert k["labels"][0]["pairs"] == {"app.kubernetes.io/part-of": "gpos-demo"}


@pytest.mark.parametrize("name", TABLE)
def test_deployment_shape(name: str) -> None:
    module, ports, dsn, descriptors = TABLE[name]
    pod = objects(name)["Deployment"]["spec"]["template"]["spec"]
    (container,) = pod["containers"]
    assert container["command"] == ["python", "-m", module]
    assert (container["image"], container["imagePullPolicy"]) == ("gpos-demo", "Always")
    assert {p["name"]: p["containerPort"] for p in container["ports"]} == ports
    env = {e["name"]: e for e in container["env"]}
    if dsn:
        assert env["GPOS_DSN"]["valueFrom"]["secretKeyRef"] == {"name": "gpos-db", "key": dsn}
    else:
        assert "GPOS_DSN" not in env
    assert [list(s.values())[0]["name"] for s in container["envFrom"]] == [
        "gpos-config", "gpos-broker"]
    mounts = {m["mountPath"] for m in container["volumeMounts"]}
    assert ("/descriptors" in mounts) == descriptors and "/tmp" in mounts
    assert pod["automountServiceAccountToken"] is False
    assert pod["imagePullSecrets"] == [{"name": "registry-pull-secret"}]
    assert pod["securityContext"] == {"runAsNonRoot": True, "runAsUser": 10001,
                                      "runAsGroup": 10001,
                                      "seccompProfile": {"type": "RuntimeDefault"}}
    assert container["securityContext"] == {"allowPrivilegeEscalation": False,
                                            "readOnlyRootFilesystem": True,
                                            "capabilities": {"drop": ["ALL"]}}
    assert container["resources"] == {"requests": {"cpu": "50m", "memory": "128Mi"},
                                      "limits": {"memory": "384Mi"}}
    for probe, period in (("readinessProbe", 5), ("livenessProbe", 20)):
        assert container[probe]["httpGet"] == {"path": "/health", "port": "http"}
        assert container[probe]["periodSeconds"] == period
    tmp = next(v for v in pod["volumes"] if v["name"] == "tmp")
    assert tmp["emptyDir"] == {"sizeLimit": "50Mi"}
    if descriptors:
        desc = next(v for v in pod["volumes"] if v["name"] == "descriptors")
        assert desc["secret"] == {"secretName": "gpos-gebit-descriptors"}


@pytest.mark.parametrize("name", TABLE)
def test_service_ports(name: str) -> None:
    ports = {p["name"]: p for p in objects(name)["Service"]["spec"]["ports"]}
    for pname, port in TABLE[name][1].items():
        expected = 80 if name == "gpos-ui" else port
        assert (ports[pname]["port"], ports[pname]["targetPort"]) == (expected, pname)
        assert ports[pname].get("appProtocol") == (
            "kubernetes.io/h2c" if pname == "grpc" else None)


def test_configmap_has_the_lab_values_and_no_secret() -> None:
    data = load("k8s/configmap.yaml")["data"]
    assert {k: data[k] for k in ("GPOS_DEMO_DATE", "GPOS_BOOTH_LOCATION", "GPOS_PROBE_LOCATION",
                                 "GPOS_TEST_LOCATION", "GATE_GUARD", "GATE_MIN_DELAY_S",
                                 "PROPOSAL_EXPIRY_SECONDS", "POS_ADMIN_URL", "WWS_GRPC")} == {
        "GPOS_DEMO_DATE": "2027-02-16", "GPOS_BOOTH_LOCATION": "Root.DE.999.101.01",
        "GPOS_PROBE_LOCATION": "Root.DE.999.199.98", "GPOS_TEST_LOCATION": "Root.DE.999.199.99",
        "GATE_GUARD": "block", "GATE_MIN_DELAY_S": "3", "PROPOSAL_EXPIRY_SECONDS": "150",
        "POS_ADMIN_URL": "http://gpos-pos:8771", "WWS_GRPC": "gpos-wws:50053"}
    assert not {k for k in data if k.startswith(("SOLACE_", "DSN_", "LLM", "OPENAI"))
                or "KEY" in k or "PASSWORD" in k}


def test_ingresses_satisfy_kyverno() -> None:
    hosts = {}
    for doc in load_all("k8s/ingress-ui.yaml") + load_all("k8s/ingress-grpc.yaml"):
        notes = doc["metadata"]["annotations"]
        assert notes["nginx.ingress.kubernetes.io/ssl-redirect"] == "true"
        assert notes["nginx.ingress.kubernetes.io/proxy-body-size"] == "4m"
        (tls,) = doc["spec"]["tls"]
        (rule,) = doc["spec"]["rules"]
        assert tls == {"hosts": [rule["host"]], "secretName": "gpos-demo-tls"}
        backend = rule["http"]["paths"][0]["backend"]["service"]
        hosts[rule["host"]] = (backend["name"], backend["port"]["name"],
                               notes.get("nginx.ingress.kubernetes.io/backend-protocol"))
    assert hosts == {"gpos.solace.lab": ("gpos-ui", "http", None),
                     "gpos-grpc.solace.lab": ("gpos-pos", "grpc", "GRPC"),
                     "gpos-wws-grpc.solace.lab": ("gpos-wws", "grpc", "GRPC"),
                     "gpos-loyalty-grpc.solace.lab": ("gpos-loyalty", "grpc", "GRPC")}
    ui = load("k8s/ingress-ui.yaml")["metadata"]["annotations"]
    assert ui["nginx.ingress.kubernetes.io/proxy-buffering"] == "off"
    assert ui["nginx.ingress.kubernetes.io/proxy-read-timeout"] == "3600"


def test_certificate_from_the_lab_issuer() -> None:
    spec = load("k8s/certificate.yaml")["spec"]
    assert spec["secretName"] == "gpos-demo-tls"
    assert spec["dnsNames"] == ["gpos.solace.lab", "gpos-grpc.solace.lab",
                                "gpos-wws-grpc.solace.lab", "gpos-loyalty-grpc.solace.lab"]
    assert spec["privateKey"] == {"algorithm": "ECDSA", "size": 256, "rotationPolicy": "Always"}
    assert (spec["duration"], spec["renewBefore"]) == ("2160h", "720h")
    assert spec["issuerRef"]["name"] == "solace-lab-ca-issuer"
    assert spec["issuerRef"]["kind"] == "ClusterIssuer"


def _ingress(namespace: str, name: str, host: str, path: str = "/") -> dict:
    return {"kind": "Ingress", "metadata": {"namespace": namespace, "name": name},
            "spec": {"rules": [{"host": host, "http": {"paths": [{"path": path}]}}]}}


def test_install_leaves_out_an_ingress_whose_host_another_namespace_serves() -> None:
    from k8s_render import drop_foreign_ingresses

    docs = load_all("k8s/ingress-ui.yaml") + load_all("k8s/ingress-grpc.yaml")
    cluster = [_ingress("gpos-g0", "gpos-g0-grpc", "gpos-grpc.solace.lab"),
               _ingress("gpos-demo", "gpos-ui", "gpos.solace.lab"),        # our own: kept
               _ingress("other", "wws-sub", "gpos-wws-grpc.solace.lab", "/sub")]  # other path
    kept, warnings = drop_foreign_ingresses(docs, cluster, "gpos-demo")
    assert [d["metadata"]["name"] for d in kept] == ["gpos-ui", "gpos-wws-grpc",
                                                     "gpos-loyalty-grpc"]
    assert warnings == ["Ingress gpos-grpc left out: host gpos-grpc.solace.lab path / is served "
                        "by ingress gpos-g0/gpos-g0-grpc (other namespace, not touched; remove "
                        "it, then re-run scripts/install.sh k8s)"]


def test_install_applies_everything_without_a_foreign_ingress() -> None:
    from k8s_render import drop_foreign_ingresses

    docs = [load("k8s/configmap.yaml"), *load_all("k8s/ingress-grpc.yaml")]
    kept, warnings = drop_foreign_ingresses(docs, [], "gpos-demo")
    assert kept == docs and warnings == []
