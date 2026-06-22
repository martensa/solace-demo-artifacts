"""Event Portal v2 REST API client.

Wraps `https://api.solace.cloud/api/v2/architecture/...` with:
  * Bearer token auth
  * Page-by-page iteration of list endpoints
  * Retry / backoff on transient failures (429, 5xx)
  * Helpers for resolving the latest version of an event / application
  * AsyncAPI export per application version
  * Webhook subscription CRUD (used by the bridge to self-register)
  * Audit-event feed (used as reconciliation hint)

The client is intentionally schema-free (returns dicts) so the connector
can evolve without re-generating types every time the Event Portal API
ships a new field.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterator, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import telemetry

logger = logging.getLogger(__name__)


class EventPortalAuthError(Exception):
    """API token missing, expired, or unauthorized for the target resource."""


class EventPortalNotSupported(Exception):
    """Endpoint exists in the connector but not in this EP edition.

    Raised by webhook-CRUD methods on Solace Cloud Event Portal v2 (the
    /architecture/eventPortalWebhooks endpoint family is not part of the
    public v2 API as of mid-2026). Callers should catch this and fall
    back to UI-side configuration or the polling bridge mode.
    """


class EventPortalClient:
    """Thin wrapper around the Solace Event Portal REST API."""

    DEFAULT_BASE_URL = "https://api.solace.cloud/api/v2"
    DEFAULT_PAGE_SIZE = 100

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_token: Optional[str] = None,
        timeout: int = 30,
        page_size: int = DEFAULT_PAGE_SIZE,
    ):
        if not api_token:
            raise EventPortalAuthError("No API token configured for Event Portal")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.page_size = page_size

        self.session = requests.Session()
        retry = Retry(
            total=5,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST", "PUT", "DELETE", "PATCH"),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
            "User-Agent": "openmetadata-solace-eventportal-connector/0.2",
        })

    # ------------------------------------------------------------------ health

    def test_connection(self) -> None:
        """Hit a lightweight endpoint to validate token + network path."""
        resp = self.session.get(
            f"{self.base_url}/architecture/applicationDomains",
            params={"pageSize": 1, "pageNumber": 1},
            timeout=self.timeout,
        )
        if resp.status_code == 401:
            telemetry.record_ep_auth_failure()
            raise EventPortalAuthError("Event Portal rejected the API token")
        resp.raise_for_status()

    def close(self) -> None:
        self.session.close()

    # ----------------------------------------------------------- pagination

    def _paginate(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Iterate every item across all pages of a list endpoint.

        Event Portal v2 returns `meta.pagination.totalPages`; we walk page
        numbers 1..totalPages. Endpoints that omit pagination metadata are
        treated as single-page responses.
        """
        params = dict(params or {})
        params.setdefault("pageSize", self.page_size)
        page = 1
        while True:
            params["pageNumber"] = page
            resp = self.session.get(
                f"{self.base_url}{path}", params=params, timeout=self.timeout
            )
            if resp.status_code == 401:
                telemetry.record_ep_auth_failure()
                raise EventPortalAuthError("Event Portal token unauthorized")
            resp.raise_for_status()
            body = resp.json()
            for item in body.get("data") or []:
                yield item
            paging = (body.get("meta") or {}).get("pagination") or {}
            total_pages = int(paging.get("totalPages") or 0)
            if page >= total_pages or total_pages == 0:
                return
            page += 1

    # ------------------------------------------------------------- resources

    def list_application_domains(
        self,
        names: Optional[List[str]] = None,
        since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if since:
            params["updatedTime"] = f"gte:{since}"
        domains = list(
            self._paginate("/architecture/applicationDomains", params=params or None)
        )
        if names:
            wanted = {n.strip() for n in names if n.strip()}
            domains = [d for d in domains if d.get("name") in wanted]
        return domains

    def get_application_domain(self, domain_id: str) -> Optional[Dict[str, Any]]:
        return self._get_single(f"/architecture/applicationDomains/{domain_id}")

    def list_applications(
        self,
        application_domain_id: str,
        since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"applicationDomainId": application_domain_id}
        if since:
            params["updatedTime"] = f"gte:{since}"
        return list(self._paginate("/architecture/applications", params=params))

    def list_application_versions(self, application_id: str) -> List[Dict[str, Any]]:
        return list(
            self._paginate(
                "/architecture/applicationVersions",
                params={"applicationIds": application_id},
            )
        )

    def get_latest_application_version(
        self, application_id: str
    ) -> Optional[Dict[str, Any]]:
        return _latest(self.list_application_versions(application_id))

    def list_events(
        self,
        application_domain_id: str,
        since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"applicationDomainId": application_domain_id}
        if since:
            params["updatedTime"] = f"gte:{since}"
        return list(self._paginate("/architecture/events", params=params))

    def list_event_versions(self, event_id: str) -> List[Dict[str, Any]]:
        return list(
            self._paginate(
                "/architecture/eventVersions",
                params={"eventIds": event_id},
            )
        )

    def get_latest_event_version(self, event_id: str) -> Optional[Dict[str, Any]]:
        return _latest(self.list_event_versions(event_id))

    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        return self._get_single(f"/architecture/events/{event_id}")

    def get_event_version(
        self, event_version_id: str
    ) -> Optional[Dict[str, Any]]:
        return self._get_single(
            f"/architecture/eventVersions/{event_version_id}"
        )

    def get_application(self, application_id: str) -> Optional[Dict[str, Any]]:
        return self._get_single(f"/architecture/applications/{application_id}")

    def get_application_version(
        self, application_version_id: str
    ) -> Optional[Dict[str, Any]]:
        return self._get_single(
            f"/architecture/applicationVersions/{application_version_id}"
        )

    def get_schema(self, schema_id: str) -> Optional[Dict[str, Any]]:
        return self._get_single(f"/architecture/schemas/{schema_id}")

    def get_schema_version(
        self, schema_version_id: str
    ) -> Optional[Dict[str, Any]]:
        return self._get_single(
            f"/architecture/schemaVersions/{schema_version_id}"
        )

    def list_schemas(
        self,
        application_domain_id: str,
        since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List EP Schemas in a domain (Wave 3 #52).

        ``applicationDomainId`` is singular for /architecture/schemas (EP v2
        confirms this) and matches the /architecture/events convention --
        ``applicationDomainIds`` plural would 400.
        """
        params: Dict[str, Any] = {"applicationDomainId": application_domain_id}
        if since:
            params["updatedTime"] = f"gte:{since}"
        return list(self._paginate("/architecture/schemas", params=params))

    def list_schema_versions(self, schema_id: str) -> List[Dict[str, Any]]:
        """List versions of a single EP Schema."""
        return list(
            self._paginate(
                "/architecture/schemaVersions",
                params={"schemaIds": schema_id, "pageSize": 100},
            )
        )

    def get_latest_schema_version(
        self, schema_id: str
    ) -> Optional[Dict[str, Any]]:
        return _latest(self.list_schema_versions(schema_id))

    def export_application_asyncapi(
        self,
        application_version_id: str,
        spec_version: str = "2.5.0",
        format_: str = "json",
    ) -> Optional[str]:
        """Download an AsyncAPI document for one application version."""
        resp = self.session.get(
            f"{self.base_url}/architecture/applicationVersions/"
            f"{application_version_id}/asyncApi",
            params={"asyncApiVersion": spec_version, "format": format_},
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    # -------------------------------------------------- event APIs (Wave 3 #44/#45)

    def list_event_apis(
        self, application_domain_id: str, since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List EP Event APIs in a domain (Cloud Enterprise + Self-Managed)."""
        params: Dict[str, Any] = {"applicationDomainIds": application_domain_id}
        if since:
            params["updatedTime"] = f"gte:{since}"
        return list(
            self._paginate("/architecture/eventApis", params=params)
        )

    def list_event_api_versions(self, event_api_id: str) -> List[Dict[str, Any]]:
        return list(
            self._paginate(
                "/architecture/eventApiVersions",
                params={"eventApiIds": event_api_id, "pageSize": 100},
            )
        )

    def get_latest_event_api_version(
        self, event_api_id: str
    ) -> Optional[Dict[str, Any]]:
        versions = self.list_event_api_versions(event_api_id)
        return versions[-1] if versions else None

    def list_event_api_products(
        self, application_domain_id: str, since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List EP Event API Products (EAPP) in a domain."""
        params: Dict[str, Any] = {"applicationDomainIds": application_domain_id}
        if since:
            params["updatedTime"] = f"gte:{since}"
        return list(
            self._paginate("/architecture/eventApiProducts", params=params)
        )

    def list_event_api_product_versions(
        self, event_api_product_id: str
    ) -> List[Dict[str, Any]]:
        return list(
            self._paginate(
                "/architecture/eventApiProductVersions",
                params={
                    "eventApiProductIds": event_api_product_id,
                    "pageSize": 100,
                },
            )
        )

    def get_latest_event_api_product_version(
        self, event_api_product_id: str
    ) -> Optional[Dict[str, Any]]:
        versions = self.list_event_api_product_versions(event_api_product_id)
        return versions[-1] if versions else None

    # ----------------------------------------------------------- modeled mesh

    def list_modeled_event_meshes(
        self, since: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List Modeled Event Meshes if the EP edition exposes them.

        Solace Cloud Event Portal v2 does NOT ship this endpoint (verified
        via smoke test). Returns `[]` on 404 so callers can keep going.
        """
        params: Dict[str, Any] = {}
        if since:
            params["updatedTime"] = f"gte:{since}"
        try:
            return list(
                self._paginate(
                    "/architecture/modeledEventMeshes", params=params or None
                )
            )
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                logger.info(
                    "modeledEventMeshes endpoint not present in this EP edition; "
                    "DataProduct emission will be skipped."
                )
                return []
            raise

    def get_modeled_event_mesh(self, mesh_id: str) -> Optional[Dict[str, Any]]:
        return self._get_single(f"/architecture/modeledEventMeshes/{mesh_id}")

    # ----------------------------------------------------- custom attributes

    def list_custom_attribute_definitions(
        self,
    ) -> List[Dict[str, Any]]:
        """List EP custom-attribute definitions across all entity types.

        Used by the bootstrap auto-discovery (Wave 1 #43) to pre-create
        one OM Classification per CA name, so that tag values seen on
        ingested entities have a parent to reference. Returns `[]` on
        404 for EP editions that do not expose the endpoint.

        Definition shape (verified on seall 2026-05):
            {
              "id": "...",
              "name": "DataRetention",
              "valueType": "STRING",
              "associatedEntityTypes": ["event"],
              ...
            }
        """
        try:
            return list(
                self._paginate(
                    "/architecture/customAttributeDefinitions"
                )
            )
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                logger.info(
                    "customAttributeDefinitions endpoint not present in this"
                    " EP edition; CA-tag discovery will be skipped."
                )
                return []
            raise

    # ----------------------------------------------------------- webhooks

    def list_webhook_subscriptions(self) -> List[Dict[str, Any]]:
        """Not supported in Solace Cloud Event Portal v2."""
        raise EventPortalNotSupported(
            "Webhook subscriptions are not exposed by the EP v2 REST API. "
            "Configure notifications via the Solace Cloud UI (if available "
            "in your edition), or run the bridge in BRIDGE_MODE=polling."
        )

    def create_webhook_subscription(
        self,
        *,
        name: str,
        target_url: str,
        secret: Optional[str] = None,
        event_types: Optional[List[str]] = None,
        application_domain_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Not supported in Solace Cloud Event Portal v2."""
        raise EventPortalNotSupported(
            "Webhook subscriptions are not exposed by the EP v2 REST API. "
            "Configure notifications via the Solace Cloud UI (if available "
            "in your edition), or run the bridge in BRIDGE_MODE=polling."
        )

    def delete_webhook_subscription(self, subscription_id: str) -> None:
        """Not supported in Solace Cloud Event Portal v2."""
        raise EventPortalNotSupported(
            "Webhook subscriptions are not exposed by the EP v2 REST API."
        )

    # --------------------------------------------------------------- helpers

    def _get_single(self, path: str) -> Optional[Dict[str, Any]]:
        resp = self.session.get(f"{self.base_url}{path}", timeout=self.timeout)
        if resp.status_code == 404:
            return None
        if resp.status_code == 401:
            telemetry.record_ep_auth_failure()
            raise EventPortalAuthError("Event Portal token unauthorized")
        resp.raise_for_status()
        return resp.json().get("data")


# ------------------------------------------------------------------- helpers


def _latest(versions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick the highest semver-ish version, preferring released states."""
    if not versions:
        return None

    def rank(v: Dict[str, Any]):
        state = (v.get("stateId") or v.get("state") or "").upper()
        # EP v2 returns a NUMERIC stateId ("1".."4"); older editions send
        # the state name. Rank both vocabularies (mirrors _STATE_TAG in
        # mappers.py) so latest-selection honours lifecycle state on v2 --
        # otherwise every state fell through to the default rank and a
        # higher-semver Draft could beat a Released version.
        state_rank = {
            "1": 2, "2": 3, "3": 1, "4": 0,           # EP v2 numeric stateId
            "RELEASED": 3, "DRAFT": 2, "DEPRECATED": 1, "RETIRED": 0,
        }.get(state, 1)
        version = v.get("version") or "0.0.0"
        try:
            parts = tuple(int(p) for p in str(version).split("."))
        except (ValueError, TypeError):
            parts = (0,)
        return (state_rank, parts)

    return sorted(versions, key=rank, reverse=True)[0]


class EventPortalWriter:
    """Write-scoped EP client for OM -> EP governance write-back (Wave 4.5 /
    #49).

    Deliberately SEPARATE from ``EventPortalClient`` so the read path can
    never accidentally write: it takes the ``ep-token-writer`` token, not
    the reader token. Only ``bridge.writeback`` constructs it, and only
    when write-back is enabled AND not in dry-run.

    CONTRACT CAVEAT: the exact EP v2 wire shape for setting custom-attribute
    values on an entity (verb / path / body) must be VERIFIED against a live
    tenant before enabling live writes -- it is isolated in the two methods
    below. The whole feature ships dry-run + flag-off precisely so this can
    be confirmed under shadow deploy first (see the plan exit criterion).
    """

    def __init__(
        self,
        base_url: str = EventPortalClient.DEFAULT_BASE_URL,
        writer_token: Optional[str] = None,
        timeout: int = 30,
    ):
        if not writer_token:
            raise EventPortalAuthError(
                "No writer token configured for EP write-back (ep-token-writer)"
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST", "PATCH", "PUT"),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({
            "Authorization": f"Bearer {writer_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "openmetadata-solace-eventportal-connector/writeback",
        })

    def set_entity_custom_attributes(
        self,
        entity_path: str,
        entity_id: str,
        custom_attributes: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """PATCH custom-attribute values onto an EP entity.

        ``entity_path`` is the EP architecture sub-path (e.g.
        ``applications``, ``events``). ``custom_attributes`` is a list of
        ``{customAttributeDefinitionId | name, value}``.

        VERIFY against live EP v2 before prod: assumed contract is
        ``PATCH /architecture/<entity_path>/{id}`` with body
        ``{"customAttributes": [...]}``.
        """
        url = f"{self.base_url}/architecture/{entity_path}/{entity_id}"
        resp = self.session.patch(
            url, json={"customAttributes": custom_attributes}, timeout=self.timeout
        )
        if resp.status_code == 401:
            telemetry.record_ep_auth_failure()
            raise EventPortalAuthError("Event Portal writer token unauthorized")
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def ensure_custom_attribute_definition(
        self,
        name: str,
        associated_entity_types: List[str],
        value_type: str = "STRING",
    ) -> Dict[str, Any]:
        """Create an EP custom-attribute definition if absent (idempotent).

        VERIFY against live EP v2 before prod: assumed contract is
        ``POST /architecture/customAttributeDefinitions`` with
        ``{name, valueType, associatedEntityTypes}``.
        """
        listing = self.session.get(
            f"{self.base_url}/architecture/customAttributeDefinitions",
            params={"pageSize": 100},
            timeout=self.timeout,
        )
        if listing.status_code == 401:
            telemetry.record_ep_auth_failure()
            raise EventPortalAuthError("Event Portal writer token unauthorized")
        listing.raise_for_status()
        for existing in (listing.json().get("data") or []):
            if existing.get("name") == name:
                return existing
        resp = self.session.post(
            f"{self.base_url}/architecture/customAttributeDefinitions",
            json={
                "name": name,
                "valueType": value_type,
                "associatedEntityTypes": associated_entity_types,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("data") or {}

    def close(self) -> None:
        self.session.close()
