"""k8s_render.py -- the kustomize render of k8s/overlays/<target> made ready to apply
(used by scripts/install.sh k8s):

1. ``--image REF`` (TARGET=aks): REF becomes the image of every container of every
   Deployment of the demo. The ACR name is not in the repo, so k8s/overlays/aks keeps
   the base placeholder ``gpos-demo`` and install.sh passes
   ``--image "$GPOS_IMAGE:$GPOS_VERSION"`` from .env.aks. REF must name a tag or a
   digest. Without ``--image`` a render that still has the placeholder is refused
   (exit 2), so the AKS overlay is never applied with an unpullable image; the lab
   overlay sets its image itself and passes unchanged.
2. Every Ingress whose host and path another namespace already serves is left out.
   The ingress-nginx admission webhook rejects a second Ingress with the same host and
   path ("host ... and path ... is already defined in ingress <ns>/<name>"), which
   fails `kubectl apply` for that object. The demo never touches other namespaces
   (hard rule 3), so such an Ingress is left out with a WARNING on stderr; everything
   else is applied unchanged. Once the owner removes the foreign Ingress, the next
   `install.sh k8s` creates the left-out one.

  kubectl kustomize k8s/overlays/$TARGET \\
    | k8s_render.py --namespace gpos-demo --cluster-ingresses ingresses.json \\
        [--image REF] \\
    | kubectl apply -f -

``ingresses.json`` is the output of `kubectl get ingress -A -o json`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

Route = tuple[str, str]  # (host, path)

PLACEHOLDER_IMAGE = "gpos-demo"  # image name of k8s/base, replaced by every overlay
# [registry[:port]/]path[:tag][@sha256:digest] with a tag or a digest (Docker reference
# grammar, lowercase repository path, no whitespace)
_COMPONENT = r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
_IMAGE_REF = re.compile(
    r"^(?:(?P<registry>[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*(?::[0-9]+)?)/)?"
    rf"(?P<path>{_COMPONENT}(?:/{_COMPONENT})*)"
    r"(?::(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}))?"
    r"(?:@(?P<digest>sha256:[0-9a-f]{64}))?$")


class RenderError(Exception):
    """The render must not be applied (message for stderr)."""


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


def valid_image(ref: str) -> bool:
    """True for a pullable reference with a tag or a digest (``reg/path:tag[@sha256:..]``)."""
    match = _IMAGE_REF.match(ref)
    return bool(match) and bool(match.group("tag") or match.group("digest"))


def _containers(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Containers and init containers of a Deployment's pod template."""
    pod = ((doc.get("spec") or {}).get("template") or {}).get("spec") or {}
    return [*(pod.get("initContainers") or []), *(pod.get("containers") or [])]


def set_image(docs: Iterable[dict[str, Any]], image: str) -> int:
    """Set ``image`` on every container of every Deployment; returns how many."""
    if not valid_image(image):
        raise RenderError(f"--image {image!r} is not an image reference with a tag or a "
                          "digest (registry/path:tag); check GPOS_IMAGE and GPOS_VERSION "
                          "in .env.aks")
    count = 0
    for doc in docs:
        if doc.get("kind") != "Deployment":
            continue
        for container in _containers(doc):
            container["image"] = image
            count += 1
    if not count:
        raise RenderError("--image given, but the render has no Deployment container")
    return count


def placeholder_images(docs: Iterable[Mapping[str, Any]]) -> list[str]:
    """``<Deployment>/<container>`` of every container still on the base placeholder."""
    return [f"{doc['metadata']['name']}/{c.get('name')}"
            for doc in docs if doc.get("kind") == "Deployment"
            for c in _containers(doc) if c.get("image") == PLACEHOLDER_IMAGE]


def render(docs: list[dict[str, Any]], cluster: Iterable[Mapping[str, Any]], namespace: str,
           image: str | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """``--image`` (or the placeholder check), then the foreign-Ingress filter."""
    if image is not None:
        set_image(docs, image)
    left = placeholder_images(docs)
    if left:
        raise RenderError(f"image placeholder {PLACEHOLDER_IMAGE!r} left in {', '.join(left)}:"
                          " the aks overlay needs --image REF (scripts/install.sh passes"
                          " $GPOS_IMAGE:$GPOS_VERSION from .env.aks)")
    return drop_foreign_ingresses(docs, cluster, namespace)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--namespace", required=True, help="namespace of the demo")
    ap.add_argument("--cluster-ingresses", type=Path, required=True,
                    help="output of `kubectl get ingress -A -o json`")
    ap.add_argument("--image", metavar="REF",
                    help="image for every container of the demo Deployments (aks)")
    args = ap.parse_args(argv)
    docs = [d for d in yaml.safe_load_all(sys.stdin) if d]
    cluster = json.loads(args.cluster_ingresses.read_text(encoding="utf-8")).get("items", [])
    try:
        kept, warnings = render(docs, cluster, args.namespace, args.image)
    except RenderError as exc:
        print(f"k8s_render.py: {exc}", file=sys.stderr)
        return 2
    for line in warnings:
        print(f"   WARNING: {line}", file=sys.stderr)
    yaml.safe_dump_all(kept, sys.stdout, sort_keys=False, allow_unicode=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
