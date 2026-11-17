"""Error codes of the POS simulator (UC1-BUILD-SPEC 4.5).

The gRPC layer turns a :class:`PosError` into the gRPC status, the status message
``"<CODE>: <text>"`` and the trailing metadata ``gpos-error-code`` (``grpcutil.abort``).

* ``POS-001`` NOT_FOUND: transaction unknown
* ``POS-002`` FAILED_PRECONDITION: wrong transaction status
* ``POS-003`` NOT_FOUND: article unknown (WWS)
* ``POS-004`` UNAVAILABLE: backend (WWS, loyalty) not reachable
* ``POS-005`` INVALID_ARGUMENT: invalid request field (unknown till location or
  position, item count, amount); additive to 4.5, see ``build/notes/WP-E.md``
* ``LOY-*``: passed through from the loyalty service (``LOY-001`` card unknown or
  blocked)
"""

from __future__ import annotations

import grpc


class PosError(Exception):
    """A business error with gRPC status and ``gpos-error-code``."""

    def __init__(self, status: grpc.StatusCode, code: str, text: str):
        super().__init__(f"{code}: {text}")
        self.status = status
        self.code = code
        self.text = text


def unknown_transaction(tx_id: str) -> PosError:
    """``POS-001``"""
    return PosError(grpc.StatusCode.NOT_FOUND, "POS-001", f"Transaktion {tx_id} unbekannt")


def wrong_status(command: str, status: str, allowed: tuple[str, ...]) -> PosError:
    """``POS-002``"""
    return PosError(grpc.StatusCode.FAILED_PRECONDITION, "POS-002",
                    f"{command} im Status {status} nicht erlaubt (erlaubt: {', '.join(allowed)})")


def already_voided(position_id: str) -> PosError:
    """``POS-002`` for a position that is voided already."""
    return PosError(grpc.StatusCode.FAILED_PRECONDITION, "POS-002",
                    f"Position {position_id} ist bereits storniert")


def nothing_to_pay() -> PosError:
    """``POS-002`` for a payment start on a basket without effectual lines."""
    return PosError(grpc.StatusCode.FAILED_PRECONDITION, "POS-002",
                    "Bon ohne gültige Zeilen kann nicht bezahlt werden")


def unknown_article(key: str) -> PosError:
    """``POS-003``"""
    return PosError(grpc.StatusCode.NOT_FOUND, "POS-003", f"Artikel {key} unbekannt")


def backend_unavailable(backend: str, detail: str) -> PosError:
    """``POS-004``"""
    return PosError(grpc.StatusCode.UNAVAILABLE, "POS-004",
                    f"{backend} nicht erreichbar: {detail}")


def invalid_argument(text: str) -> PosError:
    """``POS-005``"""
    return PosError(grpc.StatusCode.INVALID_ARGUMENT, "POS-005", text)
