"""Clients of the BFF to the other services, strictly over their contracts.

* Engine HTTP API (11.8): ``/api/state``, ``/api/proposals/{id}``, ``/api/reset``,
  ``/api/sam-error``, ``/health``
* POS admin (11.8): ``GET /admin/till/{till}``, ``POST /admin/reset``
* WWS gRPC ``MerchandiseService`` (4.3): ``ListArticles``, ``ResetDemoState``
* Loyalty gRPC ``LoyaltyService`` (4.4): ``ResetDemoState``

Every failure surfaces as :class:`UpstreamError` naming the service; nothing here
retries (the callers decide).
"""

from __future__ import annotations

import logging
from typing import Any

import grpc
import httpx
from google.protobuf import descriptor_pool
from grpc_health.v1 import health_pb2, health_pb2_grpc

from ..common.descriptors import LOYALTY_SVC, WWS_SVC
from ..common.grpcutil import Client, error_code

log = logging.getLogger(__name__)

HTTP_TIMEOUT_S = 3.0
GRPC_TIMEOUT_S = 5.0
HEALTH_TIMEOUT_S = 0.7
UI_IDENTITY = "gpos-ui"
LOYALTY_VISIT = "booth"


class UpstreamError(Exception):
    """A call to another service failed (unreachable, timeout or error answer)."""

    def __init__(self, service: str, message: str, status: int | None = None):
        super().__init__(f"{service}: {message}")
        self.service = service
        self.message = message
        self.status = status


def grpc_serving(channel: grpc.Channel, timeout: float = HEALTH_TIMEOUT_S) -> bool:
    """``grpc.health.v1`` check of the whole server (service ``""``)."""
    try:
        reply = health_pb2_grpc.HealthStub(channel).Check(
            health_pb2.HealthCheckRequest(service=""), timeout=timeout)
    except grpc.RpcError:
        return False
    return reply.status == health_pb2.HealthCheckResponse.SERVING


def _rpc_error(service: str, err: grpc.RpcError) -> UpstreamError:
    code = err.code() if isinstance(err, grpc.Call) else None
    details = err.details() if isinstance(err, grpc.Call) else str(err)
    name = code.name if code else "UNKNOWN"
    return UpstreamError(service, f"{error_code(err) or name}: {details}")


class _Http:
    """A small JSON-over-HTTP client with one error type."""

    def __init__(self, service: str, base_url: str, *, timeout: float = HTTP_TIMEOUT_S,
                 transport: httpx.BaseTransport | None = None):
        self.service = service
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def request(self, method: str, path: str, *, json: Any = None,
                params: dict[str, str] | None = None, allow_404: bool = False) -> Any:
        """JSON answer of ``method path``; ``None`` for a 404 when ``allow_404``."""
        try:
            response = self._http.request(method, path, json=json, params=params)
        except httpx.HTTPError as exc:
            raise UpstreamError(self.service, f"{type(exc).__name__}: {exc}") from exc
        if allow_404 and response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise UpstreamError(self.service, f"HTTP {response.status_code} "
                                f"{' '.join(response.text.split())[:200]}",
                                response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamError(self.service, "answer is not JSON") from exc

    def healthy(self) -> bool:
        """``GET /health`` answers 200."""
        try:
            return self._http.get("/health", timeout=HEALTH_TIMEOUT_S).status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._http.close()


class EngineClient(_Http):
    """Engine HTTP API (``ENGINE_URL``, 11.8)."""

    def __init__(self, base_url: str, *, timeout: float = HTTP_TIMEOUT_S,
                 transport: httpx.BaseTransport | None = None):
        super().__init__("engine", base_url, timeout=timeout, transport=transport)

    def state(self, store: str, till: str) -> dict[str, Any]:
        """``GET /api/state?store=&till=`` -> ``{"review", "proposal", "counts"}``."""
        return self.request("GET", "/api/state", params={"store": store, "till": till}) or {}

    def proposal(self, proposal_id: str) -> dict[str, Any] | None:
        """``GET /api/proposals/{id}``; ``None`` when the engine does not know it."""
        return self.request("GET", f"/api/proposals/{proposal_id}", allow_404=True)

    def reset(self, scope: str, store_id: str) -> dict[str, Any]:
        """``POST /api/reset`` (step 1 of the reset chain, 11.7)."""
        return self.request("POST", "/api/reset", json={"scope": scope, "store_id": store_id})

    def sam_error(self, rule: str, store: str, till: str, error: str) -> dict[str, Any]:
        """``POST /api/sam-error`` for an R4/P4 ``errorOutput`` (11.8)."""
        return self.request("POST", "/api/sam-error",
                            json={"rule": rule, "store": store, "till": till, "error": error})


class PosAdminClient(_Http):
    """POS admin routes (``POS_ADMIN_URL``, 11.8)."""

    def __init__(self, base_url: str, *, timeout: float = HTTP_TIMEOUT_S,
                 transport: httpx.BaseTransport | None = None):
        super().__init__("pos", base_url, timeout=timeout, transport=transport)

    def till(self, till: str) -> dict[str, Any]:
        """``GET /admin/till/{till}`` -> ``{"open_tx": null | {...}}``."""
        return self.request("GET", f"/admin/till/{till}") or {}

    def reset(self) -> dict[str, Any]:
        """``POST /admin/reset`` (step 3 of the reset chain: open baskets -> RESET)."""
        return self.request("POST", "/admin/reset", json={}) or {}


class _Grpc:
    """A Showcase gRPC client with health and one error type."""

    def __init__(self, service: str, pool: descriptor_pool.DescriptorPool, full_name: str,
                 target: str):
        self.service = service
        self._client = Client(pool, full_name, target)

    def _call(self, method: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._client.call_json(method, body, timeout=GRPC_TIMEOUT_S)
        except grpc.RpcError as err:
            raise _rpc_error(self.service, err) from err

    def healthy(self) -> bool:
        return grpc_serving(self._client.channel)

    def close(self) -> None:
        self._client.close()


def _header(trace_id: str) -> dict[str, Any]:
    return {"traceId": trace_id, "originator": {"identityId": UI_IDENTITY}}


class WwsClient(_Grpc):
    """``de.showcase.wws.v1.service.MerchandiseService`` (``WWS_GRPC``)."""

    def __init__(self, pool: descriptor_pool.DescriptorPool, target: str):
        super().__init__("wws", pool, WWS_SVC, target)

    def list_articles(self, store: str) -> list[dict[str, Any]]:
        """``ListArticles{store_id}`` as proto3 JSON articles (business time, 4.3)."""
        return self._call("ListArticles", {"storeId": store}).get("articles", [])

    def reset(self, store: str, full: bool, trace_id: str) -> dict[str, Any]:
        """``ResetDemoState{store_id, full}`` (step 2 of the reset chain)."""
        self._call("ResetDemoState", {"header": _header(trace_id), "storeId": store,
                                      "full": full})
        return {"store_id": store, "full": full}


class LoyaltyClient(_Grpc):
    """``de.showcase.loyalty.v1.service.LoyaltyService`` (``LOYALTY_GRPC``)."""

    def __init__(self, pool: descriptor_pool.DescriptorPool, target: str):
        super().__init__("loyalty", pool, LOYALTY_SVC, target)

    def reset(self, full_day: bool, trace_id: str) -> dict[str, Any]:
        """``ResetDemoState{visit_id: "booth", full_day_reset}`` (step 4)."""
        self._call("ResetDemoState", {"header": _header(trace_id), "visitId": LOYALTY_VISIT,
                                      "fullDayReset": full_day})
        return {"visit_id": LOYALTY_VISIT, "full_day_reset": full_day}
