"""POS facade: REST ``POST /api/pos/{Method}`` -> GEBIT gRPC (UC1-BUILD-SPEC 4.2, 10.1).

* Only the seven GEBIT commands of 4.2 pass; any other method answers 404.
* The body is the proto3 JSON of the command without ``header``; the BFF sets
  ``header.traceId`` = ``kasse-<till>-<8 hex>`` (a client header is replaced).
* ``CreatePurchaseTransaction`` gets ``location`` of the till (``?till=98`` probe,
  ``?till=99`` test, default booth), ``employeeId`` ``booth`` and ``cashdrawerId`` =
  till.
* Answer ``{"ok": true, "result": {...}, "traceId", "ms"}`` or
  ``{"ok": false, "code", "grpc", "message", "traceId"}`` with HTTP 409
  (precondition), 404 (unknown), 400 (invalid), 503 (unreachable), 502 (other).

The GEBIT messages come from the runtime descriptor sets (``GEBIT_DESCRIPTOR_SETS``,
mounted, never in the image); without them the facade answers 503.
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import grpc
from google.protobuf import json_format
from google.protobuf.message import DecodeError

from ..common.config import Settings
from ..common.descriptors import PURCHASE_SVC, load_pool
from ..common.grpcutil import Client, error_code
from ..common.topics import parse_location
from .clients import GRPC_TIMEOUT_S, grpc_serving

log = logging.getLogger(__name__)

ALLOWED_METHODS = (
    "CreatePurchaseTransaction", "AddArticle", "VoidArticlePosition",
    "AssignLoyaltyMembership", "StartPaymentProcess", "CreateCashPayment",
    "CancelPurchaseTransaction",
)
CREATE = "CreatePurchaseTransaction"
EMPLOYEE_ID = "booth"
CODE_UNKNOWN_METHOD = "BFF-001"
CODE_BAD_REQUEST = "BFF-002"
CODE_NO_DESCRIPTORS = "BFF-003"
_CODED = re.compile(r"^([A-Z]{2,8}-\d{3}): (.*)$", re.DOTALL)

HTTP_BY_GRPC: dict[grpc.StatusCode, int] = {
    grpc.StatusCode.FAILED_PRECONDITION: 409,
    grpc.StatusCode.ABORTED: 409,
    grpc.StatusCode.ALREADY_EXISTS: 409,
    grpc.StatusCode.NOT_FOUND: 404,
    grpc.StatusCode.INVALID_ARGUMENT: 400,
    grpc.StatusCode.OUT_OF_RANGE: 400,
    grpc.StatusCode.UNAVAILABLE: 503,
    grpc.StatusCode.DEADLINE_EXCEEDED: 503,
}


@dataclass(frozen=True)
class FacadeResult:
    """HTTP status and JSON body of one facade call."""

    status: int
    body: dict[str, Any]
    request: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == 200


def tills(s: Settings) -> dict[str, str]:
    """Till id -> location: booth (``01``), probe (``98``), test (``99``)."""
    return {parse_location(loc)[3]: loc
            for loc in (s.booth_location, s.probe_location, s.test_location)}


def split_status(details: str, code: str = "") -> tuple[str, str]:
    """``"POS-002: wrong state"`` -> ``("POS-002", "wrong state")``.

    ``code`` is the ``gpos-error-code`` trailer; without it the code is read from the
    status message (4.1: ``"<CODE>: <Text>"``).
    """
    match = _CODED.match(details)
    if match and (not code or match.group(1) == code):
        return match.group(1), match.group(2)
    return code, details


def _failure(status: int, code: str, grpc_name: str, message: str,
             trace_id: str = "") -> FacadeResult:
    body = {"ok": False, "code": code, "grpc": grpc_name, "message": message}
    if trace_id:
        body["traceId"] = trace_id
    return FacadeResult(status, body)


class PosFacade:
    """The GEBIT ``PurchaseTransactionService`` behind ``/api/pos/{Method}``."""

    def __init__(self, settings: Settings, client: Client | None, reason: str = ""):
        self.settings = settings
        self.tills = tills(settings)
        self.booth_till = parse_location(settings.booth_location)[3]
        self._client = client
        self._reason = reason
        self._health_channel = client.channel if client else grpc.insecure_channel(
            settings.pos_grpc)

    @classmethod
    def from_settings(cls, settings: Settings) -> PosFacade:
        """Load the GEBIT pool from ``GEBIT_DESCRIPTOR_SETS``; without it the facade is
        disabled (503) and says why."""
        if not settings.gebit_descriptor_sets:
            return cls(settings, None, "GEBIT_DESCRIPTOR_SETS ist nicht gesetzt")
        try:
            pool = load_pool(settings.gebit_descriptor_sets)
        except (OSError, ValueError, KeyError, DecodeError) as exc:
            log.error("GEBIT descriptor sets not loadable: %s", exc)
            return cls(settings, None, f"GEBIT-Deskriptoren nicht ladbar: {exc}")
        return cls(settings, Client(pool, PURCHASE_SVC, settings.pos_grpc))

    @property
    def ready(self) -> bool:
        """True when the GEBIT descriptors are loaded."""
        return self._client is not None

    def healthy(self) -> bool:
        """Descriptors loaded and the POS gRPC server is serving."""
        return self.ready and grpc_serving(self._health_channel)

    def till_or_none(self, till: str | None) -> str | None:
        """The till id for the ``till`` query (default booth) or ``None`` if unknown."""
        value = till or self.booth_till
        return value if value in self.tills else None

    def _prepare(self, method: str, body: Mapping[str, Any], till: str,
                 trace_id: str) -> dict[str, Any]:
        request = {k: v for k, v in body.items() if k != "header"}
        request["header"] = {"traceId": trace_id}
        if method == CREATE:
            request.update(location=self.tills[till], employeeId=EMPLOYEE_ID,
                           cashdrawerId=till)
        return request

    def call(self, method: str, body: Any, till: str | None = None) -> FacadeResult:
        """Validate, call POS and map the answer (never raises)."""
        if method not in ALLOWED_METHODS:
            return _failure(404, CODE_UNKNOWN_METHOD, "", f"Methode nicht erlaubt: {method}")
        till_id = self.till_or_none(till)
        if till_id is None:
            return _failure(400, CODE_BAD_REQUEST, "INVALID_ARGUMENT",
                            f"Unbekannte Kasse: {till}")
        if not isinstance(body, Mapping):
            return _failure(400, CODE_BAD_REQUEST, "INVALID_ARGUMENT",
                            "Body muss ein JSON-Objekt sein")
        if self._client is None:
            return _failure(503, CODE_NO_DESCRIPTORS, "UNAVAILABLE", self._reason)
        trace_id = f"kasse-{till_id}-{secrets.token_hex(4)}"
        request = self._prepare(method, body, till_id, trace_id)
        try:
            message = self._client.request(method, request)
        except json_format.ParseError as exc:
            return _failure(400, CODE_BAD_REQUEST, "INVALID_ARGUMENT", str(exc), trace_id)
        started = time.perf_counter()
        try:
            reply = self._client.call(method, message, timeout=GRPC_TIMEOUT_S)
        except grpc.RpcError as err:
            return self._grpc_failure(err, trace_id)
        ms = round((time.perf_counter() - started) * 1000)
        result = json_format.MessageToDict(reply, descriptor_pool=self._client.pool)
        return FacadeResult(200, {"ok": True, "result": result, "traceId": trace_id,
                                  "ms": ms}, request)

    @staticmethod
    def _grpc_failure(err: grpc.RpcError, trace_id: str) -> FacadeResult:
        status = err.code() if isinstance(err, grpc.Call) else grpc.StatusCode.UNKNOWN
        details = (err.details() if isinstance(err, grpc.Call) else "") or ""
        code, message = split_status(details, error_code(err))
        return _failure(HTTP_BY_GRPC.get(status, 502), code, status.name, message, trace_id)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
        else:
            self._health_channel.close()
