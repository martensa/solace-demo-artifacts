"""Business ids ``<prefix>-YYMMDD-NNNN`` (UC1-BUILD-SPEC 5.6).

Reviews ``GR-``, proposals ``GP-`` (engine sequences), price actions ``PA-`` (WWS);
``YYMMDD`` is the business date, ``NNNN`` the sequence value, at least four digits.
"""

from __future__ import annotations

import re
from datetime import date

_PREFIX = re.compile(r"^[A-Z]{2,8}$")


def make_id(prefix: str, business_date: date, seq: int) -> str:
    """``make_id("GP", date(2027, 2, 16), 3)`` -> ``"GP-270216-0003"``."""
    if not _PREFIX.match(prefix):
        raise ValueError(f"id prefix must be 2-8 capital letters, got {prefix!r}")
    if seq < 1:
        raise ValueError(f"sequence value must be positive, got {seq}")
    return f"{prefix}-{business_date:%y%m%d}-{seq:04d}"
