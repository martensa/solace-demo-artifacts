#!/usr/bin/env python3
"""Render the two event-mesh entrypoints of the gpos demo (spec 9.6).

  scripts/render_mesh.py                 render into mesh/.rendered/ (chmod 600)
  scripts/render_mesh.py --switch-r1     allow an R1_MODE change (hard rule 4)
  scripts/render_mesh.py --mark-applied  record R1_MODE as applied (mesh/.rendered/r1_mode)
  scripts/render_mesh.py --r1-topics     print the five R1 topics of the booth till
  scripts/render_mesh.py --write-broker-env FILE
                                         SOLACE_* for the k8s Secret gpos-broker (chmod 600)

Output (mesh/.rendered/ is the repo root of two manifests):
  manifest-booth.yaml + entrypoints/gpos-booth-events.yaml
  manifest-probe.yaml + entrypoints/gpos-probe-events.yaml

R1_MODE=own (default) keeps the `existingQueueName` block of rule r1_booth_till
and drops its `subscriptions`; R1_MODE=sam the other way round; the marker lines
go. The last applied mode lives in mesh/.rendered/r1_mode: a render with another
mode stops (exit 3) unless --switch-r1 is given, because a switch leaves an
orphaned queue that scripts/broker.sh r1-switch has to remove (finding 21).

Credentials are read at runtime (BROKER_USERNAME/BROKER_PASSWORD or
MQTT_USERNAME/MQTT_PASSWORD from BROKER_CREDENTIALS_FROM) and never printed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path

import yaml

from opslib import (DEMO_DIR, RUN_IDENTITY_DEFAULT, OpsError, broker_credentials, demo_env,
                    location_parts, write_private)

TEMPLATES = DEMO_DIR / "mesh" / "entrypoints"
RENDERED = DEMO_DIR / "mesh" / ".rendered"
R1_MODES = ("own", "sam")
ENTRYPOINTS = {"booth": "gpos-booth-events", "probe": "gpos-probe-events"}
RULES = {
    "booth": ("r1_booth_till", "r3_basket_review", "r4_price_approval"),
    "probe": ("p1_probe_till", "p3_probe_review", "p4_probe_approval"),
}
SECRET_KEYS = ("__BROKER_USERNAME__", "__BROKER_PASSWORD__")
_PLACEHOLDER = re.compile(r"__[A-Z0-9_]+__")
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.:/@>*-]+$")
_MARKER = re.compile(r"^\s*# (>>>|<<<) R1_MODE=(own|sam)\s*$")

MANIFEST = """\
# RENDERED by scripts/render_mesh.py -- contains no secret itself, but lives
# next to the rendered entrypoint (chmod 600). Apply as sam_admin, NEVER --prune:
#   cd mesh/.rendered && sam config apply -m {file}
kind: manifest
name: gpos-uc1-{part}-entrypoint
description: >-
  EuroCIS price agent UC1: the rendered {entrypoint} entrypoint with the broker
  credentials of the lab.
target:
  name: solace-lab
  url: {sam_url}
  auth:
    type: oauth
resources:
  entrypoints:
    - {entrypoint}
"""


def select_r1_block(text: str, mode: str) -> str:
    """Keep the lines between the markers of `mode`, drop the other block, drop
    every marker line."""
    out, skipping = [], None
    for line in text.splitlines(keepends=True):
        marker = _MARKER.match(line)
        if marker:
            opening, block = marker.group(1) == ">>>", marker.group(2)
            if opening and block != mode:
                skipping = block
            elif not opening and block == skipping:
                skipping = None
            continue
        if skipping is None:
            out.append(line)
    if skipping is not None:
        raise OpsError(f"template: R1_MODE={skipping} block not closed")
    return "".join(out)


def placeholder_values(env: Mapping[str, str]) -> dict[str, str]:
    """Every __X__ of both templates; the two secrets are added by render()."""
    booth = location_parts(env.get("GPOS_BOOTH_LOCATION", "Root.DE.999.101.01"))
    probe = location_parts(env.get("GPOS_PROBE_LOCATION", "Root.DE.999.199.98"))
    return {
        "__BROKER_WS_URL__": env.get("BROKER_WS_URL", "ws://host.docker.internal:8008"),
        "__BROKER_VPN__": env.get("BROKER_VPN", "default"),
        "__RUN_IDENTITY__": env.get("SAM_RUN_IDENTITY", RUN_IDENTITY_DEFAULT),
        "__STORE__": booth[2],
        "__TILL__": booth[3],
        "__BOOTH__": "/".join(booth),
        "__R1_QUEUE__": env.get("R1_QUEUE", "gpos-booth-r1"),
        "__PROBE_STORE__": probe[2],
        "__PROBE_TILL__": probe[3],
        "__PROBE__": "/".join(probe),
    }


def substitute(text: str, values: Mapping[str, str], secrets: Mapping[str, str]) -> str:
    """Secrets only as whole double-quoted scalars, JSON-escaped (valid YAML);
    all other values must be plain topic/URL characters."""
    for key, value in secrets.items():
        quoted = f'"{key}"'
        if text.count(key) != text.count(quoted):
            raise OpsError(f"template: {key} must stand alone in double quotes")
        text = text.replace(quoted, json.dumps(value, ensure_ascii=False))
    for key, value in values.items():
        if key in text and not _SAFE_VALUE.match(value):
            raise OpsError(f"value for {key} has unexpected characters")
        text = text.replace(key, value)
    left = sorted(set(_PLACEHOLDER.findall(text)))
    if left:
        raise OpsError(f"template: unknown placeholder(s) {', '.join(left)}")
    return text


def check_rendered(doc: dict, part: str, mode: str) -> None:
    """The rendered document is the entrypoint the spec names, with permanent
    rule names and a valid R1 binding."""
    if doc.get("kind") != "entrypoint" or doc.get("name") != ENTRYPOINTS[part]:
        raise OpsError(f"rendered {part}: unexpected kind/name")
    rules = doc["spec"]["values"]["event_rules"]
    names = tuple(r["name"] for r in rules)
    if names != RULES[part]:
        raise OpsError(f"rendered {part}: rule names {names} != {RULES[part]} (hard rule 4)")
    for rule in rules:
        has_queue, has_subs = "existingQueueName" in rule, "subscriptions" in rule
        if has_queue == has_subs:
            raise OpsError(f"rendered {part}: rule {rule['name']} needs exactly one of "
                           "existingQueueName and subscriptions")
        if has_queue and not (part == "booth" and rule["name"] == "r1_booth_till"
                              and mode == "own"):
            raise OpsError(f"rendered {part}: existingQueueName only on r1_booth_till "
                           "with R1_MODE=own")


def render_part(part: str, env: Mapping[str, str], mode: str, out: Path) -> Path:
    template = TEMPLATES / f"{ENTRYPOINTS[part]}.yaml.template"
    text = template.read_text(encoding="utf-8")
    if part == "booth":
        text = select_r1_block(text, mode)
    user, password = broker_credentials(env)
    text = substitute(text, placeholder_values(env),
                      {"__BROKER_USERNAME__": user, "__BROKER_PASSWORD__": password})
    doc = yaml.safe_load(text)
    values = doc["spec"]["values"]
    if values["broker_username"] != user or values["broker_password"] != password:
        raise OpsError(f"rendered {part}: credentials did not survive YAML quoting")
    check_rendered(doc, part, mode)
    target = out / "entrypoints" / f"{ENTRYPOINTS[part]}.yaml"
    write_private(target, text)
    manifest = MANIFEST.format(file=f"manifest-{part}.yaml", part=part,
                               entrypoint=ENTRYPOINTS[part],
                               sam_url=env.get("SAM_URL", "https://sam.solace.lab"))
    write_private(out / f"manifest-{part}.yaml", manifest)
    return target


def r1_mode(env: Mapping[str, str]) -> str:
    mode = env.get("R1_MODE", "own")
    if mode not in R1_MODES:
        raise OpsError(f"R1_MODE={mode!r}: expected own or sam")
    return mode


def recorded_mode(out: Path) -> str | None:
    path = out / "r1_mode"
    return path.read_text(encoding="utf-8").strip() if path.is_file() else None


def r1_topics(env: Mapping[str, str]) -> list[str]:
    """The five subscriptions of the R1_MODE=sam block with the booth path:
    the single source for the own queue gpos-booth-r1 (scripts/broker.py)."""
    text = select_r1_block((TEMPLATES / "gpos-booth-events.yaml.template")
                           .read_text(encoding="utf-8"), "sam")
    text = substitute(text, placeholder_values(env),
                      {"__BROKER_USERNAME__": "x", "__BROKER_PASSWORD__": "x"})
    rules = yaml.safe_load(text)["spec"]["values"]["event_rules"]
    r1 = next(r for r in rules if r["name"] == "r1_booth_till")
    return [s["topic"] for s in r1["subscriptions"]]


def write_broker_env(env: Mapping[str, str], target: Path) -> None:
    user, password = broker_credentials(env)
    lines = {
        "SOLACE_HOST": env.get("BROKER_SMF_URL", "tcp://host.docker.internal:55557"),
        "SOLACE_VPN": env.get("BROKER_VPN", "default"),
        "SOLACE_USERNAME": user,
        "SOLACE_PASSWORD": password,
    }
    if any("\n" in v for v in lines.values()):
        raise OpsError("broker settings must not contain line breaks")
    write_private(target, "".join(f"{k}={v}\n" for k, v in lines.items()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=RENDERED, help="output directory")
    ap.add_argument("--env-file", type=Path, help="use this file instead of the demo .env")
    ap.add_argument("--switch-r1", action="store_true", help="allow an R1_MODE change")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--mark-applied", action="store_true",
                       help="record R1_MODE as applied (after the booth apply)")
    group.add_argument("--r1-topics", action="store_true", help="print the five R1 topics")
    group.add_argument("--write-broker-env", type=Path, metavar="FILE",
                       help="write SOLACE_* for the Secret gpos-broker")
    args = ap.parse_args(argv)
    try:
        env = demo_env(args.env_file)
        mode = r1_mode(env)
        if args.r1_topics:
            print("\n".join(r1_topics(env)))
            return 0
        if args.write_broker_env:
            write_broker_env(env, args.write_broker_env)
            return 0
        if args.mark_applied:
            write_private(args.out / "r1_mode", f"{mode}\n")
            print(f"r1_mode: {mode} recorded")
            return 0
        previous = recorded_mode(args.out)
        if previous and previous != mode and not args.switch_r1:
            print(f"ERROR: R1_MODE changes {previous} -> {mode}. Run "
                  "scripts/install.sh mesh --switch-r1 so that scripts/broker.sh "
                  f"r1-switch {previous} {mode} removes the orphaned queue "
                  "(hard rule 4).", file=sys.stderr)
            return 3
        for part in ("booth", "probe"):
            target = render_part(part, env, mode, args.out)
            suffix = f" (R1_MODE={mode})" if part == "booth" else ""
            print(f"rendered: {target}{suffix}")
        if previous and previous != mode:
            print(f"R1_MODE switch {previous} -> {mode}: apply the booth entrypoint, "
                  f"then scripts/broker.sh r1-switch {previous} {mode}")
        return 0
    except OpsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
