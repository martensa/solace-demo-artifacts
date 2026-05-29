"""Multi-step Test-Connection routine.

OpenMetadata's native sources expose a list of named connection steps
(see e.g. KafkaConnection.test_connection: GetClusters, CheckSchemaRegistry,
...). The UI lights each step green / red individually. We follow the same
pattern so users get actionable feedback instead of "connection failed".

Steps for the Solace EP source:

  1. **EP API reachable** - basic HTTP roundtrip to /applicationDomains
     with the supplied baseUrl. Catches DNS / TLS / firewall issues.
  2. **EP token valid** - 401 vs anything else.
  3. **At least one include-domain accessible** - returns 0 domains?
     Either the token has no scope on the targeted domains, or the
     allow-list excludes everything (=> default-deny footgun).
  4. **Broker reachable** (only when `sampleDataEnabled`) - one SMF
     connect / disconnect against the configured broker. Skipped if
     sample data is off.

Each step result is a dataclass so callers (the OM workflow + the bridge
self-check endpoint) can render them consistently.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from .event_portal_client import EventPortalAuthError, EventPortalClient
from .filters import FilterPattern

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    name: str
    passed: bool
    message: str = ""


@dataclass
class TestConnectionReport:
    steps: List[StepResult]

    @property
    def passed(self) -> bool:
        return all(s.passed for s in self.steps)

    def __str__(self) -> str:
        return "\n".join(
            f"{'OK ' if s.passed else 'FAIL'}  {s.name}: {s.message}"
            for s in self.steps
        )


# ---------------------------------------------------------------- steps


def step_ep_api_reachable(client: EventPortalClient) -> StepResult:
    try:
        # Single page, single item; cheaper than test_connection() because we
        # interpret the response ourselves.
        resp = client.session.get(
            f"{client.base_url}/architecture/applicationDomains",
            params={"pageSize": 1, "pageNumber": 1},
            timeout=client.timeout,
        )
    except Exception as exc:
        return StepResult("EP API reachable", False, f"Network error: {exc}")
    if resp.status_code in (200, 401):
        return StepResult("EP API reachable", True, f"HTTP {resp.status_code}")
    return StepResult(
        "EP API reachable", False, f"Unexpected HTTP {resp.status_code}"
    )


def step_ep_token_valid(client: EventPortalClient) -> StepResult:
    try:
        client.test_connection()
    except EventPortalAuthError as exc:
        return StepResult("EP token valid", False, str(exc))
    except Exception as exc:
        return StepResult("EP token valid", False, f"Unexpected: {exc}")
    return StepResult("EP token valid", True, "Token accepted")


def step_filtered_domains_present(
    client: EventPortalClient, domain_filter: FilterPattern
) -> StepResult:
    if domain_filter.is_empty_allow_list:
        return StepResult(
            "At least one domain matches filter",
            False,
            "domainFilterPattern.includes is empty - allow-list-only default "
            "means nothing will be ingested. Configure includes to opt in.",
        )
    try:
        all_domains = client.list_application_domains()
    except Exception as exc:
        return StepResult(
            "At least one domain matches filter", False, f"List failed: {exc}",
        )
    matched = [d for d in all_domains if domain_filter.match(d.get("name"))]
    if not matched:
        return StepResult(
            "At least one domain matches filter",
            False,
            f"{len(all_domains)} domain(s) visible to token, "
            f"none match domainFilterPattern.includes.",
        )
    return StepResult(
        "At least one domain matches filter",
        True,
        f"{len(matched)} of {len(all_domains)} domain(s) match",
    )


def step_broker_reachable(broker_config: Optional[dict]) -> StepResult:
    """Best-effort SMF connect/disconnect. Skipped if no broker config."""
    if not broker_config:
        return StepResult(
            "Broker reachable", True, "Sample data disabled, skipped"
        )
    try:
        from solace.messaging.messaging_service import MessagingService
    except ImportError:
        return StepResult(
            "Broker reachable", False,
            "solace-pubsubplus not installed but sampleDataEnabled=true",
        )
    try:
        service = (
            MessagingService.builder()
            .from_properties(
                {
                    "solace.messaging.transport.host": broker_config["host"],
                    "solace.messaging.service.vpn-name": broker_config["vpn"],
                    "solace.messaging.authentication.scheme.basic.username":
                        broker_config["username"],
                    "solace.messaging.authentication.scheme.basic.password":
                        broker_config["password"],
                }
            )
            .build()
        )
        service.connect()
        service.disconnect()
    except Exception as exc:
        return StepResult("Broker reachable", False, f"Connect failed: {exc}")
    return StepResult("Broker reachable", True, "Connected and disconnected")


# ------------------------------------------------------------ orchestration


def run_test_connection(
    client: EventPortalClient,
    *,
    domain_filter: FilterPattern,
    broker_config: Optional[dict] = None,
) -> TestConnectionReport:
    """Run the full test-connection sequence.

    Each step runs independently; earlier failures don't short-circuit so
    the UI can show a complete picture of what's broken.
    """
    return TestConnectionReport(
        steps=[
            step_ep_api_reachable(client),
            step_ep_token_valid(client),
            step_filtered_domains_present(client, domain_filter),
            step_broker_reachable(broker_config),
        ]
    )
