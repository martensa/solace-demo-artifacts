"""Domain errors of gpos-wws and their gRPC mapping (UC1-BUILD-SPEC 4.1, 4.5).

``WwsError`` carries the gRPC status, the ``gpos-error-code`` and a German text; the
gRPC layer turns it into ``grpcutil.abort`` and the MCP layer into an error JSON.

Codes of 4.5 plus two additive codes for requests the 4.5 table does not cover
(recorded in ``build/notes/WP-C.md``): ``WWS-002`` (incomplete or invalid request)
and ``WWS-003`` (unknown price action).
"""

from __future__ import annotations

import grpc

ARTICLE_UNKNOWN = "WWS-001"
INVALID_REQUEST = "WWS-002"
ACTION_UNKNOWN = "WWS-003"
NO_REDUCTION = "WWS-010"
ACTION_RUNNING = "WWS-011"
PRICE_BOUND = "WWS-012"
REGULAR_MISMATCH = "WWS-020"

STATUS: dict[str, grpc.StatusCode] = {
    ARTICLE_UNKNOWN: grpc.StatusCode.NOT_FOUND,
    INVALID_REQUEST: grpc.StatusCode.INVALID_ARGUMENT,
    ACTION_UNKNOWN: grpc.StatusCode.NOT_FOUND,
    NO_REDUCTION: grpc.StatusCode.INVALID_ARGUMENT,
    ACTION_RUNNING: grpc.StatusCode.FAILED_PRECONDITION,
    PRICE_BOUND: grpc.StatusCode.FAILED_PRECONDITION,
    REGULAR_MISMATCH: grpc.StatusCode.ABORTED,
}


class WwsError(Exception):
    """A request the WWS refuses: ``code`` from 4.5, ``text`` German, one line."""

    def __init__(self, code: str, text: str):
        super().__init__(f"{code}: {text}")
        self.code = code
        self.text = text

    @property
    def status(self) -> grpc.StatusCode:
        """gRPC status of :attr:`code` (4.5)."""
        return STATUS[self.code]


def article_unknown(article_number: str, store_id: str) -> WwsError:
    """``WWS-001``: the article has no price in the store (or does not exist)."""
    return WwsError(ARTICLE_UNKNOWN, f"Artikel {article_number or '?'} im Laden "
                                     f"{store_id or '?'} unbekannt")


def invalid(text: str) -> WwsError:
    """``WWS-002``: a mandatory field is missing or a value is out of range."""
    return WwsError(INVALID_REQUEST, text)
