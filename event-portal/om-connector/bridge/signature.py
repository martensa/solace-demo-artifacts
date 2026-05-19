"""HMAC signature verification for Event Portal webhooks.

Event Portal signs each webhook with a shared secret using HMAC-SHA256
and ships the hex digest in a header (commonly `Solace-Signature` or
`X-EventPortal-Signature` depending on edition). The exact header name is
configurable so the bridge can run against on-prem builds that use a
different name.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Iterable


DEFAULT_HEADERS = ("Solace-Signature", "X-EventPortal-Signature")


class SignatureError(ValueError):
    """Webhook signature missing or did not match."""


def verify(
    *,
    body: bytes,
    headers: dict,
    secret: str,
    header_candidates: Iterable[str] = DEFAULT_HEADERS,
) -> None:
    """Raise `SignatureError` unless one of the candidate headers matches.

    Header lookup is case-insensitive. The digest may be prefixed with
    `sha256=` (GitHub-style) — we strip it before comparison.
    """
    if not secret:
        raise SignatureError("No webhook secret configured")

    lowered = {k.lower(): v for k, v in headers.items()}
    provided = next(
        (lowered[h.lower()] for h in header_candidates if h.lower() in lowered),
        None,
    )
    if not provided:
        raise SignatureError(
            f"None of {list(header_candidates)} present on webhook request"
        )
    if provided.startswith("sha256="):
        provided = provided[len("sha256="):]

    expected = hmac.new(
        secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, provided.strip()):
        raise SignatureError("Webhook signature mismatch")
