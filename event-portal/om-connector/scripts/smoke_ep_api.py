#!/usr/bin/env python3
"""Solace Event Portal API smoke test.

Walks every endpoint the connector + bridge depend on and reports the
result so we can catch payload-shape surprises BEFORE the workshop.

Reads the EP token from `EP_API_TOKEN` (env var). Never put a real token
on the command line or in the repo.

Usage:
    EP_API_TOKEN=... python scripts/smoke_ep_api.py [--base-url URL]

Exit codes:
    0  all critical endpoints OK
    1  one or more critical endpoints failed
    2  bad invocation (missing token, etc.)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

DEFAULT_BASE = "https://api.solace.cloud/api/v2"


# Critical: the connector cannot ingest without these. Non-critical:
# the bridge or reconcile path benefits from them but the demo still
# works without (workshop falls back to pull-only).
CRITICAL = "critical"
OPTIONAL = "optional"


@dataclass
class CheckResult:
    name: str
    severity: str
    passed: bool
    status_code: Optional[int] = None
    message: str = ""
    sample_keys: List[str] = field(default_factory=list)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument(
        "--json", action="store_true", help="emit a machine-readable JSON report"
    )
    args = parser.parse_args(argv)

    token = os.environ.get("EP_API_TOKEN")
    if not token:
        print("ERROR: set EP_API_TOKEN in the environment", file=sys.stderr)
        return 2

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "om-connector-smoke-test/1.0",
        }
    )

    base = args.base_url.rstrip("/")
    results: List[CheckResult] = []

    # ---- 1. Application Domains (root of everything) -----------------------
    r, body = _get(session, f"{base}/architecture/applicationDomains",
                   params={"pageSize": 5})
    results.append(_eval_list(r, body, "applicationDomains", CRITICAL,
                              expected_keys=("id", "name")))
    first_domain_id, first_domain_name = _first_id_name(body)

    # ---- 2. A single Application Domain by id -------------------------------
    if first_domain_id:
        r, body = _get(session,
                       f"{base}/architecture/applicationDomains/{first_domain_id}")
        results.append(_eval_single(r, body, "applicationDomains/{id}", CRITICAL,
                                    expected_keys=("id", "name")))

    # ---- 3. Events in that domain ------------------------------------------
    first_event_id = None
    first_event_name = None
    if first_domain_id:
        r, body = _get(session, f"{base}/architecture/events",
                       params={"applicationDomainId": first_domain_id, "pageSize": 5})
        results.append(_eval_list(r, body, "events", CRITICAL,
                                  expected_keys=("id", "name", "applicationDomainId")))
        first_event_id, first_event_name = _first_id_name(body)

    # ---- 4. Event versions of that event ----------------------------------
    first_event_version_id = None
    first_schema_version_id = None
    if first_event_id:
        r, body = _get(session, f"{base}/architecture/eventVersions",
                       params={"eventIds": first_event_id, "pageSize": 5})
        results.append(_eval_list(r, body, "eventVersions", CRITICAL,
                                  expected_keys=("id", "version")))
        items = (body or {}).get("data") if isinstance(body, dict) else None
        if items:
            first = items[0]
            first_event_version_id = first.get("id")
            first_schema_version_id = first.get("schemaVersionId")
            # Verify deliveryDescriptor structure assumed in mappers.extract_topic_address
            dd = first.get("deliveryDescriptor") or {}
            addr_levels = (dd.get("address") or {}).get("addressLevels")
            results.append(
                CheckResult(
                    name="eventVersion.deliveryDescriptor.address.addressLevels present",
                    severity=CRITICAL,
                    passed=bool(addr_levels),
                    message="addressLevels missing" if not addr_levels
                    else f"{len(addr_levels)} levels found",
                )
            )

    # ---- 5. Single event / single event version ----------------------------
    if first_event_id:
        r, body = _get(session, f"{base}/architecture/events/{first_event_id}")
        results.append(_eval_single(r, body, "events/{id}", CRITICAL,
                                    expected_keys=("id", "name", "applicationDomainId")))
    if first_event_version_id:
        r, body = _get(session,
                       f"{base}/architecture/eventVersions/{first_event_version_id}")
        results.append(_eval_single(r, body, "eventVersions/{id}", CRITICAL,
                                    expected_keys=("id", "version")))

    # ---- 6. Schema + schema version --------------------------------------
    if first_schema_version_id:
        r, body = _get(session,
                       f"{base}/architecture/schemaVersions/{first_schema_version_id}")
        results.append(_eval_single(r, body, "schemaVersions/{id}", CRITICAL,
                                    expected_keys=("id", "schemaId", "content")))
        schema_id = ((body or {}).get("data") or {}).get("schemaId")
        if schema_id:
            r, body = _get(session, f"{base}/architecture/schemas/{schema_id}")
            results.append(_eval_single(r, body, "schemas/{id}", CRITICAL,
                                        expected_keys=("id", "name", "schemaType")))

    # ---- 7. Applications + application versions ----------------------------
    first_app_id = None
    first_app_version_id = None
    if first_domain_id:
        r, body = _get(session, f"{base}/architecture/applications",
                       params={"applicationDomainId": first_domain_id, "pageSize": 5})
        results.append(_eval_list(r, body, "applications", CRITICAL,
                                  expected_keys=("id", "name", "applicationDomainId")))
        first_app_id, _ = _first_id_name(body)
    if first_app_id:
        r, body = _get(session, f"{base}/architecture/applicationVersions",
                       params={"applicationIds": first_app_id, "pageSize": 5})
        results.append(_eval_list(r, body, "applicationVersions", CRITICAL,
                                  expected_keys=("id", "version")))
        items = (body or {}).get("data") if isinstance(body, dict) else None
        if items:
            first_app_version_id = items[0].get("id")
            # Check produced/consumed field naming
            produced = items[0].get("declaredProducedEventVersionIds")
            consumed = items[0].get("declaredConsumedEventVersionIds")
            results.append(
                CheckResult(
                    name="applicationVersion.declaredProducedEventVersionIds present",
                    severity=CRITICAL,
                    passed=produced is not None,
                    message=f"value: {produced!r}",
                )
            )
            results.append(
                CheckResult(
                    name="applicationVersion.declaredConsumedEventVersionIds present",
                    severity=CRITICAL,
                    passed=consumed is not None,
                    message=f"value: {consumed!r}",
                )
            )

    # ---- 8. AsyncAPI export (optional, used by `mode: asyncapi`) -----------
    if first_app_version_id:
        url = f"{base}/architecture/applicationVersions/{first_app_version_id}/asyncApi"
        r = session.get(url, params={"asyncApiVersion": "2.5.0", "format": "json"},
                        timeout=30)
        results.append(
            CheckResult(
                name="applicationVersions/{id}/asyncApi",
                severity=OPTIONAL,
                passed=r.status_code == 200,
                status_code=r.status_code,
                message="OK" if r.status_code == 200 else r.text[:200],
            )
        )

    # ---- 9. Modeled Event Meshes (optional) --------------------------------
    r, body = _get(session, f"{base}/architecture/modeledEventMeshes",
                   params={"pageSize": 5})
    results.append(_eval_list(r, body, "modeledEventMeshes", OPTIONAL,
                              expected_keys=("id", "name")))

    # ---- 10. Audit events (used by --reconcile) ----------------------------
    r, body = _get(session, f"{base}/architecture/auditEvents",
                   params={"pageSize": 5})
    results.append(_eval_list(r, body, "auditEvents", OPTIONAL,
                              expected_keys=("id",)))

    # ---- 11. Webhook subscriptions (used by --register-webhook) ------------
    r, body = _get(session, f"{base}/architecture/eventPortalWebhooks",
                   params={"pageSize": 5})
    results.append(_eval_list(r, body, "eventPortalWebhooks (GET)", OPTIONAL,
                              expected_keys=("id",)))

    # ----------------------------- report --------------------------------
    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=2, default=str))
    else:
        _print_report(results)

    critical_fail = any(
        (not r.passed) and r.severity == CRITICAL for r in results
    )
    return 1 if critical_fail else 0


# --------------------------------------------------------------- helpers


def _get(session: requests.Session, url: str, params=None):
    try:
        r = session.get(url, params=params, timeout=30)
    except requests.RequestException as exc:
        return None, {"_error": str(exc), "url": url}
    body = None
    try:
        body = r.json()
    except Exception:
        body = {"_raw": r.text[:500]}
    return r, body


def _first_id_name(body):
    if not isinstance(body, dict):
        return None, None
    items = body.get("data") or []
    if not items:
        return None, None
    return items[0].get("id"), items[0].get("name")


def _eval_list(r, body, name, severity, *, expected_keys=()):
    if r is None:
        return CheckResult(name=name, severity=severity, passed=False,
                           message=f"request failed: {body.get('_error')}")
    if r.status_code != 200:
        return CheckResult(name=name, severity=severity, passed=False,
                           status_code=r.status_code, message=r.text[:200])
    if not isinstance(body, dict) or "data" not in body:
        return CheckResult(name=name, severity=severity, passed=False,
                           status_code=r.status_code,
                           message="response missing `data` envelope")
    items = body["data"] or []
    sample_keys = sorted(items[0].keys()) if items and isinstance(items[0], dict) else []
    missing = [k for k in expected_keys if items and k not in items[0]]
    if missing:
        return CheckResult(name=name, severity=severity, passed=False,
                           status_code=r.status_code,
                           message=f"missing expected fields: {missing}",
                           sample_keys=sample_keys)
    paging = (body.get("meta") or {}).get("pagination") or {}
    total = paging.get("totalCount")
    return CheckResult(name=name, severity=severity, passed=True,
                       status_code=r.status_code,
                       message=(f"{len(items)} returned, totalCount={total}"
                                if total is not None else f"{len(items)} returned"),
                       sample_keys=sample_keys)


def _eval_single(r, body, name, severity, *, expected_keys=()):
    if r is None:
        return CheckResult(name=name, severity=severity, passed=False,
                           message=f"request failed: {body.get('_error')}")
    if r.status_code == 404:
        return CheckResult(name=name, severity=severity, passed=False,
                           status_code=404, message="not found")
    if r.status_code != 200:
        return CheckResult(name=name, severity=severity, passed=False,
                           status_code=r.status_code, message=r.text[:200])
    if not isinstance(body, dict):
        return CheckResult(name=name, severity=severity, passed=False,
                           status_code=r.status_code,
                           message="response not a JSON object")
    item = body.get("data") if "data" in body else body
    if not isinstance(item, dict):
        return CheckResult(name=name, severity=severity, passed=False,
                           status_code=r.status_code,
                           message="response missing `data` object")
    sample_keys = sorted(item.keys())
    missing = [k for k in expected_keys if k not in item]
    if missing:
        return CheckResult(name=name, severity=severity, passed=False,
                           status_code=r.status_code,
                           message=f"missing expected fields: {missing}",
                           sample_keys=sample_keys)
    return CheckResult(name=name, severity=severity, passed=True,
                       status_code=r.status_code, message="OK",
                       sample_keys=sample_keys)


def _print_report(results: List[CheckResult]) -> None:
    cols = ("OK", "STATUS", "SEVERITY", "ENDPOINT", "DETAIL")
    rows = []
    for r in results:
        rows.append((
            "OK" if r.passed else "FAIL",
            str(r.status_code or "-"),
            r.severity,
            r.name,
            r.message,
        ))
    widths = [max(len(c), max(len(row[i]) for row in rows)) for i, c in enumerate(cols)]
    fmt = "  ".join(f"{{:{w}}}" for w in widths)
    print(fmt.format(*cols))
    print(fmt.format(*["-" * w for w in widths]))
    for row in rows:
        print(fmt.format(*row))
    print()
    print(f"  Total: {len(results)}, "
          f"failed: {sum(1 for r in results if not r.passed)}")
    crit_fail = [r for r in results if not r.passed and r.severity == CRITICAL]
    if crit_fail:
        print(f"  Critical failures: {len(crit_fail)}")
        for r in crit_fail:
            print(f"    - {r.name}: {r.message}")
    # Show sample keys for endpoints that PASSED — useful to see if the
    # API ships new fields we should mirror onto OM as custom properties.
    print()
    print("Sample top-level keys per endpoint (for diff against mappers.py):")
    for r in results:
        if r.passed and r.sample_keys:
            print(f"  {r.name}:")
            print(f"    {', '.join(r.sample_keys)}")


if __name__ == "__main__":
    sys.exit(main())
