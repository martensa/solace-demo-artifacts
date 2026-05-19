"""Filter patterns for Event Portal ingestion.

Modeled after OpenMetadata's `FilterPattern` (`includes` / `excludes` lists of
regular expressions) so the configuration shape is familiar to anyone who has
used the Kafka or other native connectors.

Policy: **allow-list only**. If `includes` is empty, NOTHING matches. The
default-deny posture is deliberate — an EP account can hold thousands of
domains across business units; defaulting to "ingest everything" is a
governance risk and a footgun for the first ingestion run.

Pattern config shape (passed as JSON in `connectionOptions`):

    {
      "includes": ["orders\\..*", "billing\\..*"],
      "excludes": [".*\\.internal"]
    }

Empty includes -> no match. excludes is applied AFTER includes.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Pattern

logger = logging.getLogger(__name__)


class FilterParseError(ValueError):
    """Raised when a filter pattern from connectionOptions is malformed."""


@dataclass(frozen=True)
class FilterPattern:
    """Allow-list-first include/exclude regex matcher.

    Compiled patterns are cached on construction so `match()` is hot-path
    cheap.
    """

    includes: List[Pattern[str]] = field(default_factory=list)
    excludes: List[Pattern[str]] = field(default_factory=list)

    # ------------------------------------------------------------------ build

    @classmethod
    def empty(cls) -> "FilterPattern":
        """Convenience: an instance that matches nothing."""
        return cls(includes=[], excludes=[])

    @classmethod
    def from_value(cls, value: Any) -> "FilterPattern":
        """Build from a connectionOptions value.

        Accepts:
          * dict already shaped `{includes: [...], excludes: [...]}`
          * JSON-encoded string of the same shape
          * comma-separated string (legacy) -> treated as `includes`
          * None / empty -> empty pattern (matches nothing)
        """
        if value is None or value == "":
            return cls.empty()
        if isinstance(value, FilterPattern):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return cls.empty()
            if stripped.startswith("{"):
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise FilterParseError(f"Invalid filter JSON: {exc}") from exc
                if not isinstance(parsed, dict):
                    raise FilterParseError("Filter JSON must be an object")
                return cls._from_dict(parsed)
            # legacy comma-separated includes
            return cls(
                includes=[_compile(s.strip()) for s in stripped.split(",") if s.strip()],
                excludes=[],
            )
        if isinstance(value, dict):
            return cls._from_dict(value)
        raise FilterParseError(
            f"Cannot interpret filter value of type {type(value).__name__}"
        )

    @classmethod
    def _from_dict(cls, raw: Dict[str, Any]) -> "FilterPattern":
        return cls(
            includes=[_compile(p) for p in (raw.get("includes") or [])],
            excludes=[_compile(p) for p in (raw.get("excludes") or [])],
        )

    # ---------------------------------------------------------------- match

    @property
    def is_empty_allow_list(self) -> bool:
        """True if no includes are defined - i.e. nothing will match."""
        return not self.includes

    def match(self, value: Optional[str]) -> bool:
        """Return True if `value` should be ingested.

        Allow-list-only semantics:
          * No `includes` -> always False (default-deny).
          * Otherwise: at least one `includes` regex must match,
            AND no `excludes` regex matches.
        """
        if not value or not self.includes:
            return False
        if any(p.search(value) for p in self.excludes):
            return False
        return any(p.search(value) for p in self.includes)

    def filter(self, values: Iterable[str]) -> List[str]:
        """Return only the values that pass `match`."""
        return [v for v in values if self.match(v)]


# ---------------------------------------------------------------- helpers


def _compile(pattern: str) -> Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise FilterParseError(
            f"Invalid regex {pattern!r}: {exc}"
        ) from exc


def parse_filter_options(opts: Dict[str, Any]) -> Dict[str, FilterPattern]:
    """Pull all known *FilterPattern keys out of a connectionOptions map.

    Returns a dict with one FilterPattern per known key. Missing keys
    default to `FilterPattern.empty()` (default-deny).

    Known keys:
      * domainFilterPattern
      * eventFilterPattern
      * schemaFilterPattern
      * applicationFilterPattern
    """
    keys = (
        "domainFilterPattern",
        "eventFilterPattern",
        "schemaFilterPattern",
        "applicationFilterPattern",
    )
    return {k: FilterPattern.from_value(opts.get(k)) for k in keys}
