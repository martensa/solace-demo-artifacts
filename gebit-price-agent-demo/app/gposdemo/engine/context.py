"""Shared dependencies of the engine's parts (one instance per process)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ..common.bus import Bus
from ..common.config import Settings
from ..common.db import Db
from ..common.topics import parse_location
from .clients import LoyaltyClient, WwsClient
from .policy import Policy
from .state import Emitter


@dataclass(frozen=True)
class Context:
    settings: Settings
    db: Db
    bus: Bus
    wws: WwsClient
    loyalty: LoyaltyClient
    policy: Policy
    emitter: Emitter
    clock: Callable[[], datetime]

    @property
    def zone(self) -> ZoneInfo:
        return self.settings.zone

    @property
    def demo_date(self) -> date:
        return self.settings.demo_date

    def known_till(self, store_id: str, till_id: str) -> bool:
        """Booth (101/01), probe (199/98) or test till (199/99) of the settings."""
        tills = {parse_location(loc)[2:] for loc in (self.settings.booth_location,
                                                     self.settings.probe_location,
                                                     self.settings.test_location)}
        return (store_id, till_id) in tills
