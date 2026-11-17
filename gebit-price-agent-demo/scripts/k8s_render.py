"""k8s_render.py -- the kustomize render of k8s/ minus every Ingress whose host and
path another namespace already serves (used by scripts/install.sh k8s).

The ingress-nginx admission webhook rejects a second Ingress with the same host and
path ("host ... and path ... is already defined in ingress <ns>/<name>"), which fails
`kubectl apply` for that object. The demo never touches other namespaces (hard rule 3),
so such an Ingress is left out with a WARNING on stderr; everything else is applied
unchanged. Once the owner removes the foreign Ingress, the next `install.sh k8s`
creates the left-out one.

  kubectl kustomize k8s \\
    | k8s_render.py --namespace gpos-demo --cluster-ingresses ingresses.json \\
    | kubectl apply -f -

``ingresses.json`` is the output of `kubectl get ingress -A -o json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

Route = tuple[str, str]  # (host, path)


def routes(ingress: Mapping[str, Any]) -> set[Route]:
    """Every (host, path) of an Ingress; a rule without paths counts as path "/"."""
    found: set[Route] = set()
    for rule in (ingress.get("spec") or {}).get("rules") or []:
        host = rule.get("host") or ""
        paths = ((rule.get("http") or {}).get("paths")) or [{"path": "/"}]
        found |= {(host, p.get("path") or "/") for p in paths}
    return found


def foreign_routes(cluster: Iterable[Mapping[str, Any]], namespace: str) -> dict[Route, str]:
    """(host, path) -> "<namespace>/<name>" of every Ingress outside ``namespace``."""
    held: dict[Route, str] = {}
    for ingress in cluster:
        meta = ingress.get("metadata") or {}
        if meta.get("namespace") == namespace:
            continue
        for route in sorted(routes(ingress)):
            held.setdefault(route, f"{meta.get('namespace')}/{meta.get('name')}")
    return held


def drop_foreign_ingresses(docs: Iterable[dict[str, Any]],
                           cluster: Iterable[Mapping[str, Any]],
                           namespace: str) -> tuple[list[dict[str, Any]], list[str]]:
    """(objects to apply, one warning per left-out Ingress)."""
    held = foreign_routes(cluster, namespace)
    kept: list[dict[str, Any]] = []
    warnings: list[str] = []
    for doc in docs:
        clash = sorted(r for r in routes(doc) if r in held) if doc.get("kind") == "Ingress" else []
        if not clash:
            kept.append(doc)
            continue
        host, path = clash[0]
        warnings.append(f"Ingress {doc['metadata']['name']} left out: host {host} path {path} "
                        f"is served by ingress {held[clash[0]]} (other namespace, not touched;"
                        " remove it, then re-run scripts/install.sh k8s)")
    return kept, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--namespace", required=True, help="namespace of the demo")
    ap.add_argument("--cluster-ingresses", type=Path, required=True,
                    help="output of `kubectl get ingress -A -o json`")
    args = ap.parse_args(argv)
    docs = [d for d in yaml.safe_load_all(sys.stdin) if d]
    cluster = json.loads(args.cluster_ingresses.read_text(encoding="utf-8")).get("items", [])
    kept, warnings = drop_foreign_ingresses(docs, cluster, args.namespace)
    for line in warnings:
        print(f"   WARNING: {line}", file=sys.stderr)
    yaml.safe_dump_all(kept, sys.stdout, sort_keys=False, allow_unicode=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
