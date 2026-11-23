"""k8s/ against spec 12.4 and 3.1, the AKS path table (AKS-MIGRATION-PLAN 0.2, 1.4,
A18), scripts/k8s_render.py and scripts/aks-check.sh.

Layout: k8s/base (target-neutral), k8s/overlays/lab (renders byte-identical to the
pre-split `kubectl kustomize k8s`, pinned in overlays/lab/expected-render.yaml),
k8s/overlays/aks (one public name), k8s/postgres-aks (demo DB on AKS). Render tests
need `kubectl kustomize` (offline) and skip without kubectl; everything else reads
the files.
"""

from __future__ import annotations

import ast
import io
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import ROOT, load, load_all

FQDN = "eurocis-showcase.germanywestcentral.cloudapp.azure.com"
K8S = ROOT / "k8s"
NGINX = "nginx.ingress.kubernetes.io/"

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
    return {d["kind"]: d for d in load_all(f"k8s/base/{FILES[name]}.yaml")}


def kustomize(rel: str) -> str:
    """`kubectl kustomize <rel>` (offline); the test skips without kubectl."""
    kubectl = shutil.which("kubectl")
    if not kubectl:
        pytest.skip("kubectl not installed (kubectl kustomize renders offline)")
    return subprocess.run([kubectl, "kustomize", str(ROOT / rel)], capture_output=True,
                          text=True, check=True).stdout


def rendered(rel: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(kustomize(rel)) if d]


# ============================================================ layout and kustomizations
def test_base_kustomization_lists_every_file_and_names_nothing_target_specific() -> None:
    k = load("k8s/base/kustomization.yaml")
    assert k["namespace"] == "gpos-demo"
    assert sorted(k["resources"]) == sorted(
        p.name for p in (K8S / "base").glob("*.yaml") if p.name != "kustomization.yaml")
    assert k["labels"][0]["pairs"] == {"app.kubernetes.io/part-of": "gpos-demo"}
    assert not {"images", "patches"} & set(k)
    text = "".join(p.read_text(encoding="utf-8") for p in (K8S / "base").glob("*.yaml"))
    text = re.sub(r"(?m)^\s*#.*$", "", text)  # without comments
    text = text.replace("SAM_URL: https://sam.solace.lab", "")  # lab default, aks patches it
    for word in ("imagePullSecrets", "solace.lab", "azurecr.io", "Ingress", "Certificate"):
        assert word not in text, word


def test_lab_overlay_holds_everything_lab_only() -> None:
    k = load("k8s/overlays/lab/kustomization.yaml")
    assert k["namespace"] == "gpos-demo"
    assert k["resources"] == ["../../base", "certificate.yaml", "ingress-ui.yaml",
                              "ingress-grpc.yaml"]
    assert k["images"] == [{"name": "gpos-demo",
                            "newName": "registry.solace.lab/gpos-demo/gpos-demo",
                            "newTag": "0.1.3"}]
    (patch,) = k["patches"]
    assert patch["target"] == {"kind": "Deployment"}
    assert yaml.safe_load(patch["patch"]) == [{
        "op": "add", "path": "/spec/template/spec/imagePullSecrets",
        "value": [{"name": "registry-pull-secret"}]}]


def test_aks_overlay_has_no_image_and_patches_pull_secret_and_config() -> None:
    k = load("k8s/overlays/aks/kustomization.yaml")
    assert k["namespace"] == "gpos-demo"
    assert k["resources"] == ["../../base", "ingress-ui.yaml", "ingress-grpc.yaml"]
    assert "images" not in k  # the ACR name is not in the repo: k8s_render.py --image
    inline, by_file = k["patches"]
    assert inline["target"] == {"kind": "Deployment"}
    assert yaml.safe_load(inline["patch"]) == [{
        "op": "add", "path": "/spec/template/spec/imagePullSecrets",
        "value": [{"name": "acr-pull"}]}]
    assert by_file == {"path": "configmap-patch.yaml"}
    patch = load("k8s/overlays/aks/configmap-patch.yaml")
    assert patch["metadata"]["name"] == "gpos-config"
    assert patch["data"] == {"SAM_URL": f"https://{FQDN}", "GPOS_GRPC_REFLECTION_SCOPE": "all"}


def test_every_k8s_file_is_used_and_the_top_level_entry_is_the_lab() -> None:
    assert load("k8s/kustomization.yaml")["resources"] == ["overlays/lab"]
    used = {K8S / "kustomization.yaml", K8S / "overlays/lab/expected-render.yaml"}
    for kfile in K8S.rglob("kustomization.yaml"):
        k = load(str(kfile.relative_to(ROOT)))
        used.add(kfile)
        used |= {kfile.parent / r for r in k.get("resources", []) if r.endswith(".yaml")}
        used |= {kfile.parent / p["path"] for p in k.get("patches", []) if "path" in p}
    assert sorted(map(str, K8S.rglob("*.yaml"))) == sorted(map(str, used))


# ============================================================ base (spec 12.4)
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
    assert "imagePullSecrets" not in pod  # per target: overlays/lab and overlays/aks
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
    data = load("k8s/base/configmap.yaml")["data"]
    assert {k: data[k] for k in ("GPOS_DEMO_DATE", "GPOS_BOOTH_LOCATION", "GPOS_PROBE_LOCATION",
                                 "GPOS_TEST_LOCATION", "GATE_GUARD", "GATE_MIN_DELAY_S",
                                 "PROPOSAL_EXPIRY_SECONDS", "POS_ADMIN_URL", "WWS_GRPC")} == {
        "GPOS_DEMO_DATE": "2027-02-16", "GPOS_BOOTH_LOCATION": "Root.DE.999.101.01",
        "GPOS_PROBE_LOCATION": "Root.DE.999.199.98", "GPOS_TEST_LOCATION": "Root.DE.999.199.99",
        "GATE_GUARD": "block", "GATE_MIN_DELAY_S": "3", "PROPOSAL_EXPIRY_SECONDS": "150",
        "POS_ADMIN_URL": "http://gpos-pos:8771", "WWS_GRPC": "gpos-wws:50053"}
    assert "GPOS_GRPC_REFLECTION_SCOPE" not in data  # lab default "own"; aks overlay: all
    assert not {k for k in data if k.startswith(("SOLACE_", "DSN_", "LLM", "OPENAI"))
                or "KEY" in k or "PASSWORD" in k}


# ============================================================ lab overlay
def test_lab_ingresses_satisfy_kyverno() -> None:
    hosts = {}
    for doc in load_all("k8s/overlays/lab/ingress-ui.yaml") + load_all(
            "k8s/overlays/lab/ingress-grpc.yaml"):
        notes = doc["metadata"]["annotations"]
        assert notes[NGINX + "ssl-redirect"] == "true"
        assert notes[NGINX + "proxy-body-size"] == "4m"
        (tls,) = doc["spec"]["tls"]
        (rule,) = doc["spec"]["rules"]
        assert tls == {"hosts": [rule["host"]], "secretName": "gpos-demo-tls"}
        backend = rule["http"]["paths"][0]["backend"]["service"]
        hosts[rule["host"]] = (backend["name"], backend["port"]["name"],
                               notes.get(NGINX + "backend-protocol"))
    assert hosts == {"gpos.solace.lab": ("gpos-ui", "http", None),
                     "gpos-grpc.solace.lab": ("gpos-pos", "grpc", "GRPC"),
                     "gpos-wws-grpc.solace.lab": ("gpos-wws", "grpc", "GRPC"),
                     "gpos-loyalty-grpc.solace.lab": ("gpos-loyalty", "grpc", "GRPC")}
    ui = load("k8s/overlays/lab/ingress-ui.yaml")["metadata"]["annotations"]
    assert ui[NGINX + "proxy-buffering"] == "off"
    assert ui[NGINX + "proxy-read-timeout"] == "3600"


def test_certificate_from_the_lab_issuer() -> None:
    spec = load("k8s/overlays/lab/certificate.yaml")["spec"]
    assert spec["secretName"] == "gpos-demo-tls"
    assert spec["dnsNames"] == ["gpos.solace.lab", "gpos-grpc.solace.lab",
                                "gpos-wws-grpc.solace.lab", "gpos-loyalty-grpc.solace.lab"]
    assert spec["privateKey"] == {"algorithm": "ECDSA", "size": 256, "rotationPolicy": "Always"}
    assert (spec["duration"], spec["renewBefore"]) == ("2160h", "720h")
    assert spec["issuerRef"]["name"] == "solace-lab-ca-issuer"
    assert spec["issuerRef"]["kind"] == "ClusterIssuer"


def lab_image() -> str:
    image = load("k8s/overlays/lab/kustomization.yaml")["images"][0]
    return f"{image['newName']}:{image['newTag']}"


def expected_lab_render() -> str:
    """expected-render.yaml without its comment header; the image tag follows the lab
    overlay's newTag (a tag bump such as 0.1.4 needs no new expected render)."""
    lines = (K8S / "overlays/lab/expected-render.yaml").read_text(encoding="utf-8")
    lines = lines.splitlines(keepends=True)
    while lines and lines[0].startswith("#"):
        lines.pop(0)
    return re.sub(r"registry\.solace\.lab/gpos-demo/gpos-demo:\S+", lab_image(), "".join(lines))


def test_lab_render_is_byte_identical_to_the_pre_split_render() -> None:
    expected = expected_lab_render()
    assert expected.count(lab_image()) == len(TABLE)
    assert kustomize("k8s/overlays/lab") == expected
    assert kustomize("k8s") == expected  # top-level entry = lab overlay


# ============================================================ renders per target
def test_renders_carry_the_targets_pull_secret_image_and_config() -> None:
    lab, aks = rendered("k8s/overlays/lab"), rendered("k8s/overlays/aks")
    for docs, secret, image in ((lab, "registry-pull-secret", lab_image()),
                                (aks, "acr-pull", "gpos-demo")):
        deployments = [d for d in docs if d["kind"] == "Deployment"]
        assert sorted(d["metadata"]["name"] for d in deployments) == sorted(TABLE)
        for dep in deployments:
            pod = dep["spec"]["template"]["spec"]
            assert pod["imagePullSecrets"] == [{"name": secret}]
            assert {c["image"] for c in pod["containers"]} == {image}
        assert {d["metadata"]["namespace"] for d in docs if d["kind"] != "Namespace"} == {
            "gpos-demo"}
    aks_config = next(d for d in aks if d["kind"] == "ConfigMap")["data"]
    assert (aks_config["SAM_URL"], aks_config["GPOS_GRPC_REFLECTION_SCOPE"]) == (
        f"https://{FQDN}", "all")
    assert "solace.lab" not in kustomize("k8s/overlays/aks")
    assert not [d for d in aks if d["kind"] == "Certificate"]
    names = sorted(d["metadata"]["name"] for d in aks if d["kind"] == "Ingress")
    assert names == sorted(AKS_INGRESSES)


# ============================================================ AKS path table (0.2)
AKS_INGRESSES = ("gpos-ui", "gpos-ui-pos", "gpos-ui-demo", "gpos-ui-events", "gpos-grpc",
                 "gpos-wws-grpc", "gpos-loyalty-grpc", "gpos-grpc-reflection")
# every BFF route exactly once: PUBLIC (an AKS path, ingress named) or OPEN (on purpose
# no path; without one a request lands at SAM's "/")
PUBLIC = {
    "/kasse": "gpos-ui",
    "/monitor": "gpos-ui",
    "/static/shared/texts.js": "gpos-ui",
    "/static/": "gpos-ui",
    "/api/catalog": "gpos-ui",
    "/api/cards": "gpos-ui",
    "/api/scenarios": "gpos-ui",
    "/api/state": "gpos-ui",
    "/api/proposals/{proposal_id}": "gpos-ui",
    "/api/pos/{method}": "gpos-ui-pos",
    "/api/demo/reset": "gpos-ui-demo",
    "/api/events": "gpos-ui-events",
}
OPEN = {
    "/": "SAM owns / on the name; the BFF redirect to /monitor is unreachable",
    "/health": "SAM owns /health; the probes call the BFF in the cluster",
    "/freigabe": "owner decision pending (AKS-MIGRATION-PLAN 7.1)",
    "/foto": "owner decision pending (AKS-MIGRATION-PLAN 7.1)",
    "/op": "owner decision pending (AKS-MIGRATION-PLAN 7.1)",
    "/etikett": "owner decision pending (AKS-MIGRATION-PLAN 7.1)",
}
# paths of SAM (/, API, gateway, discovery) and Keycloak that no gpos path may shadow
FOREIGN = ("/", "/health", "/api/v1/user", "/api/v2/tasks", "/api/v1/auth/callback",
           "/gw/dev/", "/.well-known/openid-configuration", "/login", "/assets/index.js",
           "/auth/realms/solace-lab/protocol/openid-connect/auth", "/auth/resources/x")
LIMITS = {  # ingress -> (limit-rpm, limit-burst-multiplier, limit-connections)
    "gpos-ui": (None, None, None), "gpos-ui-pos": ("120", "1", None),
    "gpos-ui-demo": ("2", "1", None), "gpos-ui-events": (None, None, "10"),
    "gpos-grpc": ("60", "1", None), "gpos-wws-grpc": ("60", "1", None),
    "gpos-loyalty-grpc": ("60", "1", None), "gpos-grpc-reflection": (None, None, None),
}
# ingress-nginx annotations the overlay may use: all parsed by Traefik v3.7's
# kubernetesIngressNGINX provider (pkg/provider/kubernetes/ingress-nginx/annotations.go)
SUPPORTED = {"ssl-redirect", "proxy-body-size", "proxy-request-buffering", "proxy-buffering",
             "proxy-read-timeout", "proxy-send-timeout", "backend-protocol", "limit-rpm",
             "limit-burst-multiplier", "limit-connections"}


def aks_ingresses() -> dict[str, dict]:
    docs = load_all("k8s/overlays/aks/ingress-ui.yaml") + load_all(
        "k8s/overlays/aks/ingress-grpc.yaml")
    assert all(d["kind"] == "Ingress" for d in docs)
    return {d["metadata"]["name"]: d for d in docs}


def aks_paths() -> list[tuple[str, dict, dict]]:
    """(ingress name, path entry, annotations) of every AKS path."""
    return [(name, path, ing["metadata"].get("annotations") or {})
            for name, ing in aks_ingresses().items()
            for rule in ing["spec"]["rules"] for path in rule["http"]["paths"]]


def prefix_match(path: str, request: str) -> bool:
    """pathType Prefix: element-wise (Kubernetes; Traefik: Path(p) || PathPrefix(p/))."""
    if path == "/":
        return True
    base = path.rstrip("/")
    return request == base or request.startswith(base + "/")


def sample(route: str) -> str:
    """A concrete request path for a BFF route (templates filled, mounts entered)."""
    return re.sub(r"\{[^}]+\}", "x", route) + ("x" if route.endswith("/") else "")


def matches(request: str) -> list[tuple[str, str]]:
    return [(name, p["path"]) for name, p, _ in aks_paths() if prefix_match(p["path"], request)]


def bff_routes() -> set[str]:
    """Every path of app/gposdemo/ui/bff.py: @app.<method>("...") and app.mount("...")."""
    source = (ROOT / "app/gposdemo/ui/bff.py").read_text(encoding="utf-8")
    for other in ("add_api_route", "add_route", "include_router", "APIRouter", "Mount("):
        assert other not in source, f"bff.py registers routes via {other}: extend bff_routes()"
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "app"):
            first = node.args[0] if node.args else None
            assert isinstance(first, ast.Constant), ast.unparse(node)
            path = first.value
            found.add(path.rstrip("/") + "/" if node.func.attr == "mount" else path)
    return found


def test_every_bff_route_is_classified_exactly_once() -> None:
    routes = bff_routes()
    assert not set(PUBLIC) & set(OPEN)
    unclassified = routes - set(PUBLIC) - set(OPEN)
    assert not unclassified, (f"new BFF route(s) {sorted(unclassified)}: add each to PUBLIC "
                              "(with a path in k8s/overlays/aks) or to OPEN (no path)")
    assert set(PUBLIC) <= routes, f"stale PUBLIC entries {sorted(set(PUBLIC) - routes)}"
    assert {"/", "/health"} <= routes


@pytest.mark.parametrize("route", sorted(PUBLIC))
def test_public_route_has_exactly_one_aks_path(route: str) -> None:
    (hit,) = matches(sample(route))
    assert hit[0] == PUBLIC[route]


@pytest.mark.parametrize("route", sorted(OPEN))
def test_open_route_has_no_aks_path(route: str) -> None:
    for request in {route, sample(route), route.rstrip("/") + "/x"}:
        assert not matches(request), (route, matches(request))


def test_aks_paths_shadow_neither_sam_nor_keycloak_and_none_is_dead() -> None:
    for request in FOREIGN:
        assert not matches(request), (request, matches(request))
    served = [sample(r) for r in PUBLIC]
    for name, path, _ in aks_paths():
        if name.startswith("gpos-ui"):
            assert any(prefix_match(path["path"], s) for s in served), (name, path["path"])


def test_aks_ingresses_shape() -> None:
    ingresses = aks_ingresses()
    assert sorted(ingresses) == sorted(AKS_INGRESSES)
    for name, ing in ingresses.items():
        spec, notes = ing["spec"], ing["metadata"].get("annotations") or {}
        assert spec["ingressClassName"] == "nginx", name
        assert spec["tls"] == [{"hosts": [FQDN]}], name  # Traefik default cert, no secretName
        assert [r["host"] for r in spec["rules"]] == [FQDN], name
        assert notes[NGINX + "ssl-redirect"] == "true", name
        assert all(isinstance(v, str) for v in notes.values()), name  # "on"/"1" quoted
        assert {k.removeprefix(NGINX) for k in notes} <= SUPPORTED, name
        assert all(k.startswith(NGINX) for k in notes), name
        for path in spec["rules"][0]["http"]["paths"]:
            assert path["pathType"] == "Prefix", (name, path["path"])
            assert re.fullmatch(r"/[A-Za-z0-9._/-]*", path["path"]), path["path"]  # strict
        rpm, burst, conns = LIMITS[name]
        assert (notes.get(NGINX + "limit-rpm"), notes.get(NGINX + "limit-burst-multiplier"),
                notes.get(NGINX + "limit-connections")) == (rpm, burst, conns), name


def test_gpos_ui_routes_buffer_and_limit_the_body_except_sse() -> None:
    for route in PUBLIC:
        ((hit_name, _),) = matches(sample(route))
        notes = aks_ingresses()[hit_name]["metadata"]["annotations"]
        backend = {p["backend"]["service"]["name"] for n, p, _ in aks_paths() if n == hit_name}
        assert backend == {"gpos-ui"}, route
        if route == "/api/events":
            assert notes[NGINX + "proxy-buffering"] == "off"
            assert notes[NGINX + "proxy-request-buffering"] == "off"
            assert NGINX + "proxy-body-size" not in notes
            assert notes[NGINX + "proxy-read-timeout"] == "3600"
            continue
        # under Traefik the body limit only acts with request buffering on
        assert notes[NGINX + "proxy-body-size"] == "4m", route
        assert notes[NGINX + "proxy-request-buffering"] == "on", route


def service_names() -> dict[str, str]:
    """PURCHASE_SVC, WWS_SVC, LOYALTY_SVC from app/gposdemo/common/descriptors.py."""
    tree = ast.parse((ROOT / "app/gposdemo/common/descriptors.py").read_text(encoding="utf-8"))
    return {n.targets[0].id: n.value.value for n in tree.body
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id.endswith("_SVC")}


GRPC = {"PURCHASE_SVC": ("gpos-grpc", "gpos-pos"), "WWS_SVC": ("gpos-wws-grpc", "gpos-wws"),
        "LOYALTY_SVC": ("gpos-loyalty-grpc", "gpos-loyalty")}


def grpc_notes_ok(notes: dict) -> None:
    assert notes[NGINX + "backend-protocol"] == "GRPC"
    assert notes[NGINX + "proxy-read-timeout"] == notes[NGINX + "proxy-send-timeout"] == "3600"
    assert notes[NGINX + "proxy-request-buffering"] == "off"
    assert NGINX + "proxy-body-size" not in notes


@pytest.mark.parametrize("key", GRPC)
def test_each_grpc_service_has_exactly_one_public_prefix_path(key: str) -> None:
    svc = service_names()[key]
    ingress, service = GRPC[key]
    hits = [(n, p, notes) for n, p, notes in aks_paths() if p["path"] == f"/{svc}/"]
    assert len(hits) == 1, hits
    ((name, path, notes),) = hits
    assert (name, path["pathType"]) == (ingress, "Prefix")
    assert path["backend"]["service"] == {"name": service, "port": {"name": "grpc"}}
    grpc_notes_ok(notes)
    assert matches(f"/{svc}/AnyMethod") == [(ingress, f"/{svc}/")]  # all RPCs, one route


def test_reflection_goes_to_pos_and_health_stays_internal() -> None:
    for version in ("v1", "v1alpha"):
        hit = matches(f"/grpc.reflection.{version}.ServerReflection/ServerReflectionInfo")
        assert hit == [("gpos-grpc-reflection", f"/grpc.reflection.{version}.ServerReflection/")]
    reflection = aks_ingresses()["gpos-grpc-reflection"]
    grpc_notes_ok(reflection["metadata"]["annotations"])
    for rule in reflection["spec"]["rules"]:
        for path in rule["http"]["paths"]:
            assert path["backend"]["service"] == {"name": "gpos-pos", "port": {"name": "grpc"}}
    assert not matches("/grpc.health.v1.Health/Check")
    assert not matches("/grpc.health.v1.Health/Watch")


# ============================================================ k8s/postgres-aks
def test_postgres_aks_is_postgres_18_by_digest_on_its_own_namespace() -> None:
    k = load("k8s/postgres-aks/kustomization.yaml")
    assert k["namespace"] == "gpos-data"
    assert k["resources"] == ["namespace.yaml", "postgres.yaml", "networkpolicy.yaml"]
    assert load("k8s/postgres-aks/namespace.yaml")["metadata"]["name"] == "gpos-data"
    docs = {d["kind"]: d for d in load_all("k8s/postgres-aks/postgres.yaml")}
    sts, svc = docs["StatefulSet"], docs["Service"]
    assert sts["metadata"]["name"] == svc["metadata"]["name"] == sts["spec"]["serviceName"] \
        == "gpos-postgres"
    assert sts["spec"]["replicas"] == 1
    pod = sts["spec"]["template"]["spec"]
    (container,) = pod["containers"]
    assert re.fullmatch(r"docker\.io/library/postgres:18-trixie@sha256:[0-9a-f]{64}",
                        container["image"])
    assert "imagePullSecrets" not in pod  # public image, upstream by digest
    assert pod["automountServiceAccountToken"] is False
    assert {k: pod["securityContext"][k] for k in ("runAsUser", "runAsGroup", "fsGroup",
                                                   "runAsNonRoot")} == {
        "runAsUser": 999, "runAsGroup": 999, "fsGroup": 999, "runAsNonRoot": True}
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    env = {e["name"]: e for e in container["env"]}
    assert env["POSTGRES_PASSWORD"]["valueFrom"]["secretKeyRef"] == {
        "name": "gpos-postgres-admin", "key": "password"}
    assert not {e for e in env if e != "POSTGRES_PASSWORD"}  # image defaults (PGDATA)
    mounts = {m["mountPath"]: m["name"] for m in container["volumeMounts"]}
    assert mounts["/var/lib/postgresql"] == "data"  # Postgres 18 image layout
    (claim,) = sts["spec"]["volumeClaimTemplates"]
    assert claim["metadata"]["name"] == "data"
    assert claim["spec"]["storageClassName"] == "managed-csi"
    assert claim["spec"]["resources"]["requests"]["storage"] == "8Gi"
    for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
        assert container[probe]["exec"]["command"][0] == "pg_isready", probe
    assert container["resources"]["limits"]["memory"]
    assert svc["spec"]["ports"] == [{"name": "postgres", "port": 5432,
                                     "targetPort": "postgres"}]
    assert svc["spec"]["selector"] == sts["spec"]["selector"]["matchLabels"]


def test_postgres_aks_accepts_only_the_demo_namespace() -> None:
    policy = load("k8s/postgres-aks/networkpolicy.yaml")
    assert policy["spec"]["podSelector"]["matchLabels"] == {"app": "gpos-postgres"}
    (rule,) = policy["spec"]["ingress"]
    assert rule["from"] == [{"namespaceSelector": {"matchLabels": {
        "kubernetes.io/metadata.name": "gpos-demo"}}}]
    assert rule["ports"] == [{"protocol": "TCP", "port": 5432}]


def test_postgres_aks_render() -> None:
    docs = rendered("k8s/postgres-aks")
    assert sorted(d["kind"] for d in docs) == ["Namespace", "NetworkPolicy", "Service",
                                               "StatefulSet"]
    assert {d["metadata"].get("namespace") for d in docs if d["kind"] != "Namespace"} == {
        "gpos-data"}


# ============================================================ scripts/k8s_render.py
def _ingress(namespace: str, name: str, host: str, path: str = "/") -> dict:
    return {"kind": "Ingress", "metadata": {"namespace": namespace, "name": name},
            "spec": {"rules": [{"host": host, "http": {"paths": [{"path": path}]}}]}}


def lab_ingresses() -> list[dict]:
    return load_all("k8s/overlays/lab/ingress-ui.yaml") + load_all(
        "k8s/overlays/lab/ingress-grpc.yaml")


def test_install_leaves_out_an_ingress_whose_host_another_namespace_serves() -> None:
    from k8s_render import drop_foreign_ingresses

    docs = lab_ingresses()
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

    docs = [load("k8s/base/configmap.yaml"), *load_all("k8s/overlays/lab/ingress-grpc.yaml")]
    kept, warnings = drop_foreign_ingresses(docs, [], "gpos-demo")
    assert kept == docs and warnings == []


def test_aks_paths_coexist_with_sam_and_keycloak_on_the_one_name() -> None:
    from k8s_render import drop_foreign_ingresses

    cluster = [_ingress("sam-solace-lab", "agent-mesh", FQDN, "/"),
               _ingress("iam", "keycloak", FQDN, "/auth/realms/solace-lab/"),
               _ingress("traefik", "cm-acme-http-solver-x", FQDN,
                        "/.well-known/acme-challenge/token")]
    docs = list(aks_ingresses().values())
    kept, warnings = drop_foreign_ingresses(docs, cluster, "gpos-demo")
    assert kept == docs and warnings == []


def demo_docs() -> list[dict[str, Any]]:
    """Base Deployments plus one init container, a ConfigMap and an Ingress."""
    docs = [d for n in FILES.values() for d in load_all(f"k8s/base/{n}.yaml")]
    pod = next(d for d in docs if d["kind"] == "Deployment")["spec"]["template"]["spec"]
    pod["initContainers"] = [{"name": "init", "image": "gpos-demo"}]
    return [*docs, load("k8s/base/configmap.yaml"), *load_all("k8s/overlays/aks/ingress-ui.yaml")]


@pytest.mark.parametrize("ref", [
    "exampleacr.azurecr.io/gpos-demo/gpos-demo:0.1.3",
    "exampleacr.azurecr.io/gpos-demo/gpos-demo:0.1.4@sha256:" + "a" * 64,
    "registry.example:5000/gpos-demo/gpos-demo@sha256:" + "0" * 64,
    "gpos-demo/gpos-demo:latest"])
def test_valid_image_references(ref: str) -> None:
    from k8s_render import valid_image

    assert valid_image(ref)


@pytest.mark.parametrize("ref", [
    "", "gpos-demo", ".azurecr.io/gpos-demo/gpos-demo:0.1.3", ":0.1.3",
    "exampleacr.azurecr.io/gpos-demo/gpos-demo", "exampleacr.azurecr.io/Gpos/gpos:0.1.3",
    "exampleacr.azurecr.io/gpos-demo/gpos-demo:0.1.3 ", "a b:1", "x/y:1@sha256:abc"])
def test_invalid_image_references(ref: str) -> None:
    from k8s_render import valid_image

    assert not valid_image(ref)


def test_image_replaces_every_demo_container_and_nothing_else() -> None:
    from k8s_render import render

    docs = demo_docs()
    before = [d for d in docs if d["kind"] != "Deployment"]
    snapshot = yaml.safe_dump_all(before)
    image = "exampleacr.azurecr.io/gpos-demo/gpos-demo:0.1.3"
    kept, warnings = render(docs, [], "gpos-demo", image)
    images = [c["image"] for d in kept if d["kind"] == "Deployment"
              for c in [*d["spec"]["template"]["spec"].get("initContainers", []),
                        *d["spec"]["template"]["spec"]["containers"]]]
    assert images == [image] * 7 and warnings == []
    assert yaml.safe_dump_all([d for d in kept if d["kind"] != "Deployment"]) == snapshot


def test_render_refuses_the_placeholder_and_a_bad_image() -> None:
    from k8s_render import RenderError, render

    with pytest.raises(RenderError, match="placeholder 'gpos-demo' left in .*gpos-pos/pos"):
        render(demo_docs(), [], "gpos-demo")
    with pytest.raises(RenderError, match="not an image reference"):
        render(demo_docs(), [], "gpos-demo", ".azurecr.io/gpos-demo/gpos-demo:0.1.3")
    with pytest.raises(RenderError, match="no Deployment container"):
        render([load("k8s/base/configmap.yaml")], [], "gpos-demo",
               "exampleacr.azurecr.io/gpos-demo/gpos-demo:0.1.3")
    lab = [{"kind": "Deployment", "metadata": {"name": "gpos-ui"}, "spec": {"template": {
        "spec": {"containers": [{"name": "ui", "image": "registry.solace.lab/x/y:1"}]}}}}]
    assert render(lab, [], "gpos-demo") == (lab, [])  # lab: no --image, unchanged


def test_main_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                         capsys: pytest.CaptureFixture[str]) -> None:
    from k8s_render import main

    ingresses = tmp_path / "ingresses.json"
    ingresses.write_text('{"items": []}', encoding="utf-8")
    text = yaml.safe_dump_all(demo_docs())
    args = ["--namespace", "gpos-demo", "--cluster-ingresses", str(ingresses)]
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    assert main(args) == 2
    out = capsys.readouterr()
    assert out.out == "" and "needs --image REF" in out.err
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    assert main([*args, "--image", "exampleacr.azurecr.io/gpos-demo/gpos-demo:0.1.3"]) == 0
    docs = list(yaml.safe_load_all(capsys.readouterr().out))
    assert {c["image"] for d in docs if d["kind"] == "Deployment"
            for c in d["spec"]["template"]["spec"]["containers"]} == {
        "exampleacr.azurecr.io/gpos-demo/gpos-demo:0.1.3"}


# ============================================================ scripts/aks-check.sh
FAKE_TOOLS = r'''
import os, sys
from urllib.parse import urlsplit

FAULTS = set(filter(None, os.environ.get("FAKE_AKS", "").split(",")))
HSTS = "max-age=604800" + ("; includeSubDomains" if "hsts-sub" in FAULTS else "")
SAM = ("200", {"content-type": "text/html"}, "<html><title>Solace Agent Mesh</title></html>")


def respond(method, url):
    parts = urlsplit(url)
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    if parts.scheme == "http":
        return "308", {"location": f"https://{parts.netloc}{path}"}, ""
    if path == "/kasse?till=99" and "kasse-sam" not in FAULTS:
        return "200", {"content-type": "text/html"}, "<title>Kasse - Messestand</title>"
    if path == "/monitor":
        return "200", {"content-type": "text/html"}, "<title>Messemonitor</title>"
    if path == "/api/state?till=99":
        headers = {"content-type": "application/json"}
        if "cookie" in FAULTS:
            headers["set-cookie"] = "s=1"
        return "200", headers, '{"till": "99"}'
    if path == "/api/events":
        return "200", {"content-type": "text/event-stream"}, "retry: 3000\n\nevent: hello\n\n"
    if path == "/auth/realms/solace-lab/.well-known/openid-configuration":
        return "200", {"content-type": "application/json"}, \
            '{"issuer":"https://%s/auth/realms/solace-lab"}' % parts.netloc
    if path == "/auth/admin/" and "kc-admin-open" in FAULTS:
        return "302", {"location": "http://127.0.0.1:18081/auth/admin/master/console/"}, ""
    if path.startswith("/grafana/") and "grafana-403" in FAULTS:  # Traefik ipAllowList
        return "403", {"content-type": "text/plain; charset=utf-8"}, "Forbidden"
    if path == "/grafana/login" and "grafana-open" in FAULTS:
        return "200", {"content-type": "text/html"}, "<title>Grafana</title>"
    if path == "/grafana/api/health" and "grafana-open" in FAULTS:
        return "200", {"content-type": "application/json"}, \
            '{"database": "ok", "version": "12.4.3"}'
    if path == "/SEMP/v2/monitor/about/api" and FAULTS & {"semp-open", "semp-json"}:
        # a routed broker without credentials: 401 with SEMP's JSON error envelope
        headers = {"content-type": "application/json"}
        if "semp-open" in FAULTS:
            headers["www-authenticate"] = 'Basic realm="Solace PubSub+"'
        return "401", headers, ('{"meta":{"error":{"description":"Unauthorized",'
                                '"status":"UNAUTHORIZED"},"responseCode":401}}')
    if path == "/graph" and "prometheus-basic" in FAULTS:  # behind an auth wall, no body
        return "401", {"www-authenticate": 'Basic realm="Prometheus"'}, ""
    if path == "/api/rawdata" and "sam-bearer" in FAULTS:  # SAM's own API refuses: closed
        return "401", {"content-type": "application/json",
                       "www-authenticate": 'Bearer realm="sam", error="invalid_token"'}, \
            '{"error":"unauthorized"}'
    if method == "POST" and path.endswith("/AksCheckNoSuchMethod"):
        return "200", {"content-type": "application/grpc", "grpc-status": "12"}, ""
    if path == "/grpc.health.v1.Health/Check" and "health-open" in FAULTS:
        return "200", {"content-type": "application/grpc", "grpc-status": "0"}, ""
    return SAM


def curl(args):
    opts, url, i = {"-X": "GET"}, None, 0
    while i < len(args):
        if args[i] in ("-D", "-o", "-w", "-X", "-H", "-A", "--data-binary", "--max-time",
                       "--connect-timeout"):
            opts[args[i]] = args[i + 1]
            i += 2
            continue
        url = args[i] if args[i].startswith("http") else url
        i += 1
    with open(os.environ["FAKE_LOG"], "a") as log:
        log.write("curl " + " ".join(args) + "\n")
    if "down" in FAULTS:
        sys.stderr.write("curl: (7) Failed to connect\n")
        sys.stdout.write(opts["-w"].replace("%{http_code}", "000"))
        return 7
    code, headers, body = respond(opts["-X"], url)
    if url.startswith("https://"):
        headers.setdefault("strict-transport-security", HSTS)
    with open(opts["-D"], "w") as f:
        f.write(f"HTTP/2 {code}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items())
                + "\r\n")
    with open(opts["-o"], "w") as f:
        f.write(body)
    sys.stdout.write(opts["-w"].replace("%{http_code}", code))
    return 28 if url.endswith("/api/events") else 0


def openssl(args):
    if args[0] == "s_client":
        print("-----BEGIN CERTIFICATE-----\nRkFLRQ==\n-----END CERTIFICATE-----")
    elif "-outform" in args:
        sys.stdout.write(sys.stdin.read())
    elif "-checkend" in args:
        return 1 if "cert-expiring" in FAULTS else 0
    else:
        print("issuer=C=US, O=Let's Encrypt, CN=R12" if "-issuer" in args
              else "notAfter=Apr 15 10:00:00 2027 GMT")
    return 0


def grpcurl(args):
    with open(os.environ["FAKE_LOG"], "a") as log:
        log.write("grpcurl " + " ".join(args) + "\n")
    if "grpc-list-fail" in FAULTS:
        sys.stderr.write("Failed to list services: server does not support reflection\n")
        return 1
    print("de.gebit.rp.purchase.purchase.v2.service.PurchaseTransactionService")
    print("grpc.reflection.v1.ServerReflection")
    return 0


tool = os.path.basename(sys.argv[0])
sys.exit({"curl": curl, "openssl": openssl, "grpcurl": grpcurl}[tool](sys.argv[1:]))
'''
AKS_CHECKS = ["tls", "sam /", "http -> https 308", "/kasse", "/monitor", "/api/state",
              "kein Cookie (gpos)", "hsts", "/api/events (SSE)", "oidc-issuer",
              "keycloak-admin zu", "keycloak master zu", "grafana allowlist", "prometheus zu",
              "traefik-dashboard zu", "semp zu", "grpcurl list", "grpc purchase", "grpc wws",
              "grpc loyalty", "grpc health zu"]


def run_aks_check(tmp_path: Path, faults: str = "", grafana: str | None = None
                  ) -> tuple[int, dict[str, str], str]:
    """aks-check.sh with fake curl/openssl/grpcurl -> (exit, check -> OK|FEHLER, log);
    ``grafana`` sets AKS_CHECK_GRAFANA (None: unset, the default "zu")."""
    bash = Path("/bin/bash")
    if not bash.exists():
        pytest.skip("/bin/bash missing")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    for tool in ("curl", "openssl", "grpcurl"):
        (fake_bin / tool).write_text(f"#!{sys.executable} -S\n{FAKE_TOOLS}", encoding="utf-8")
        (fake_bin / tool).chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("", encoding="utf-8")
    env = {"PATH": f"{fake_bin}:/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
           "FAKE_AKS": faults, "FAKE_LOG": str(log), "LC_ALL": "C"}
    if grafana is not None:
        env["AKS_CHECK_GRAFANA"] = grafana
    proc = subprocess.run([str(bash), str(ROOT / "scripts/aks-check.sh")], env=env,
                          capture_output=True, text=True, timeout=120)
    results = {}
    for line in proc.stdout.splitlines()[:-1]:
        status, rest = line.split(" ", 1)
        name = next(c for c in sorted(AKS_CHECKS, key=len, reverse=True)
                    if rest.strip().startswith(c))
        results[name] = status
    assert proc.stdout.splitlines()[-1].startswith("aks-check: "), proc.stdout + proc.stderr
    return proc.returncode, results, log.read_text(encoding="utf-8")


def test_aks_check_all_ok(tmp_path: Path) -> None:
    code, results, log = run_aks_check(tmp_path)
    assert list(results) == AKS_CHECKS
    assert set(results.values()) == {"OK"}
    assert code == 0
    assert "/api/pos/" not in log and "/api/demo/" not in log  # never the limited writes
    assert all(f"https://{FQDN}" in line or f"http://{FQDN}" in line or "grpcurl" in line
               for line in log.splitlines())
    # -q first: curl ignores ~/.curlrc, an "insecure" line there cannot fake the TLS check
    assert all(line.startswith("curl -q ") for line in log.splitlines()
               if line.startswith("curl"))
    assert not list(tmp_path.glob("aks-check.*"))  # temp dir removed


def test_aks_check_reports_each_fault(tmp_path: Path) -> None:
    faults = ("kasse-sam,hsts-sub,grafana-open,health-open,kc-admin-open,cookie,cert-expiring,"
              "grpc-list-fail")
    code, results, _ = run_aks_check(tmp_path, faults)
    assert code == 1
    assert {c for c, s in results.items() if s == "FEHLER"} == {
        "tls", "/kasse", "hsts", "grafana allowlist", "grpc health zu", "keycloak-admin zu",
        "kein Cookie (gpos)", "grpcurl list"}
    code, results, _ = run_aks_check(tmp_path, "down")
    assert code == 1 and results["grpc health zu"] == results["semp zu"] == "FEHLER"


@pytest.mark.parametrize("fault, check", [("semp-open", "semp zu"), ("semp-json", "semp zu"),
                                          ("prometheus-basic", "prometheus zu")])
def test_aks_check_sees_a_target_behind_a_login_as_open(tmp_path: Path, fault: str,
                                                       check: str) -> None:
    # SEMP needs Basic auth: a routed broker never shows sempVersion to aks-check
    code, results, _ = run_aks_check(tmp_path, fault)
    assert code == 1
    assert {c for c, s in results.items() if s == "FEHLER"} == {check}


def test_aks_check_counts_the_allowlist_403_as_closed(tmp_path: Path) -> None:
    # outside the allowlist Traefik answers 403 before Grafana: closed for this caller
    code, results, _ = run_aks_check(tmp_path, "grafana-403")
    assert code == 0 and set(results.values()) == {"OK"}


@pytest.mark.parametrize("faults, ok", [("grafana-open", True), ("grafana-403", False),
                                        ("", False)])
def test_aks_check_frei_needs_grafana_to_answer(tmp_path: Path, faults: str, ok: bool) -> None:
    # from an allowlisted IP Grafana must answer; a 403 or no route (SAM) is a failure
    code, results, _ = run_aks_check(tmp_path, faults, grafana="frei")
    assert results["grafana allowlist"] == ("OK" if ok else "FEHLER")
    assert {c for c, s in results.items() if s == "FEHLER"} <= {"grafana allowlist"}
    assert code == (0 if ok else 1)


def test_aks_check_refuses_an_unknown_grafana_mode(tmp_path: Path) -> None:
    proc = subprocess.run(["/bin/bash", str(ROOT / "scripts/aks-check.sh")],
                          env={"PATH": "/usr/bin:/bin", "AKS_CHECK_GRAFANA": "offen"},
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2 and "AKS_CHECK_GRAFANA=zu|frei" in proc.stderr


def test_aks_check_keeps_a_bearer_401_of_sam_closed(tmp_path: Path) -> None:
    code, results, _ = run_aks_check(tmp_path, "sam-bearer")
    assert code == 0 and set(results.values()) == {"OK"}


def test_aks_check_is_bash_32_and_reads_no_env_file() -> None:
    path = ROOT / "scripts/aks-check.sh"
    code = re.sub(r"(?m)^\s*#.*$", "", path.read_text(encoding="utf-8"))  # without comments
    assert subprocess.run(["/bin/bash", "-n", str(path)]).returncode == 0
    assert os.access(path, os.X_OK)
    for word in (".env", "kubectl", "az ", "KUBECONFIG", "mapfile", "declare -A", "set -x",
                 "/api/pos", "/api/demo"):
        assert word not in code, word
