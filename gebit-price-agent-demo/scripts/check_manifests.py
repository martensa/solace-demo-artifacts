#!/usr/bin/env python3
"""Compare the six connector manifests with the running services (spec 8.5).

  scripts/check_manifests.py            static checks + live tools/list of every
                                        service (kubectl exec deploy/gpos-ui --
                                        python -m gposdemo.ui.ctl tools-list <svc>)
  scripts/check_manifests.py --static   only the files: generated (no PLACEHOLDER),
                                        tool names as in the spec, outputSchema on
                                        workflow tools only

Runs on the Mac before every mesh apply (scripts/install.sh mesh); exit 1 on any
difference, with the connector and tool named. TARGET=aks: .env.aks and kubectl
with the AKS kubeconfig and context (scripts/opslib.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path

from gen_connector_manifest import (CONNECTORS, CTL_NAMES, ConnectorSpec, build_entries,
                                    contract_errors, is_placeholder, manifest_entries,
                                    tool_list)
from opslib import DEMO_DIR, OpsError, demo_env, kubectl_ui


def static_errors(spec: ConnectorSpec, root: Path = DEMO_DIR) -> list[str]:
    path = root / spec.path
    if not path.is_file():
        return [f"{spec.path}: missing"]
    if is_placeholder(path):
        return [f"{spec.path}: still the PLACEHOLDER manifest (make manifests)"]
    return contract_errors(spec, manifest_entries(path))


def diff_entries(spec: ConnectorSpec, stored: list[dict], live: list[dict]) -> list[str]:
    """Differences between the stored manifest and the live tools/list."""
    errors = []
    stored_by_name = {e["name"]: e for e in stored}
    live_by_name = {e["name"]: e for e in live}
    for name in sorted(set(stored_by_name) | set(live_by_name)):
        a, b = stored_by_name.get(name), live_by_name.get(name)
        if a is None or b is None:
            errors.append(f"{spec.path}: {name} only {'live' if a is None else 'in the file'}")
            continue
        for key in ("description", "inputSchema", "outputSchema"):
            if a.get(key) != b.get(key):
                errors.append(f"{spec.path}: {name}.{key} differs from the running service")
    return errors


def live_tools(env: Mapping[str, str], service: str) -> list[dict]:
    proc = kubectl_ui(env, ["-m", "gposdemo.ui.ctl", "tools-list", CTL_NAMES[service]])
    if proc.returncode != 0:
        raise OpsError(f"ui.ctl tools-list {CTL_NAMES[service]} failed: "
                       f"{' '.join(proc.stderr.split())[-240:]}")
    return tool_list(json.loads(proc.stdout))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--static", action="store_true", help="files only, no cluster")
    args = ap.parse_args(argv)
    errors = [e for spec in CONNECTORS for e in static_errors(spec)]
    if not errors and not args.static:
        cache: dict[str, list[dict]] = {}
        try:
            env = demo_env()
            for spec in CONNECTORS:
                if spec.service not in cache:
                    cache[spec.service] = build_entries(live_tools(env, spec.service))
                errors += diff_entries(spec, manifest_entries(DEMO_DIR / spec.path),
                                       cache[spec.service])
        except (OpsError, ValueError) as exc:
            errors.append(str(exc))
    for error in errors:
        print(f"MANIFEST: {error}", file=sys.stderr)
    scope = "static" if args.static else "static + live"
    print(f"check_manifests ({scope}): {'FAILED' if errors else 'ok'}, "
          f"{len(CONNECTORS)} connectors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
