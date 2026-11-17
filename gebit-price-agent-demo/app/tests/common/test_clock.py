"""clock: business time vs technical time, windows, proto timestamps (3.2, 7.2)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from google.protobuf.descriptor_pool import DescriptorPool

from gposdemo.common import clock
from gposdemo.common.config import Settings
from gposdemo.common.descriptors import Types


def test_demo_now_keeps_the_wall_clock_but_uses_the_demo_date(settings: Settings) -> None:
    real = datetime(2026, 11, 11, 13, 20, 1, 412000, tzinfo=UTC)  # 14:20:01 CET
    now = clock.demo_now(settings, real)
    assert now.date() == date(2027, 2, 16)
    assert (now.hour, now.minute, now.second, now.microsecond) == (14, 20, 1, 412000)
    assert now.utcoffset() == timedelta(hours=1)
    assert clock.demo_today(settings) == date(2027, 2, 16)


def test_demo_now_without_argument_is_aware_business_time(settings: Settings) -> None:
    now = clock.demo_now(settings)
    assert now.date() == settings.demo_date
    assert now.tzinfo is not None


def test_real_now_is_utc() -> None:
    assert clock.real_now().utcoffset() == timedelta(0)


def test_windows_end_yesterday_both_edges_inclusive() -> None:
    d = date(2027, 2, 16)
    assert clock.past_window(d, 56) == (date(2026, 12, 22), date(2027, 2, 15))
    assert clock.past_window(d, 84) == (date(2026, 11, 24), date(2027, 2, 15))
    assert clock.past_window(d, 7) == (date(2027, 2, 9), date(2027, 2, 15))
    w8 = clock.past_window(d, 56)
    assert clock.in_window(date(2026, 12, 22), w8)
    assert not clock.in_window(date(2026, 12, 21), w8)
    assert clock.in_window(date(2027, 2, 15), w8)
    assert not clock.in_window(d, w8)  # booth purchases (date D) never count


def test_example_epochs_of_7_2_are_business_time(settings: Settings) -> None:
    valid_from = clock.demo_at(settings, settings.demo_date)
    valid_to = clock.demo_at(settings, date(2027, 2, 23), 20)
    assert clock.offset_ts_json(valid_from) == {"seconds": "1802732400", "offset": 60}
    assert clock.offset_ts_json(valid_to) == {"seconds": "1803409200", "offset": 60}
    ended = clock.from_ts({"seconds": "1802769300", "offset": 60})
    assert ended.date() == settings.demo_date
    assert (ended.hour, ended.minute) == (10, 15)


def test_ts_json_roundtrip_with_nanos() -> None:
    t = datetime(2026, 11, 11, 13, 20, 1, 412000, tzinfo=UTC)
    data = clock.ts_json(t)
    assert data == {"seconds": "1794403201", "nanos": 412000000}
    assert clock.from_ts(data) == t
    assert clock.from_ts(data, "Europe/Berlin").hour == 14


def test_iso_ts_has_milliseconds_and_offset() -> None:
    t = datetime(2026, 11, 11, 13, 20, 1, 412345, tzinfo=UTC)
    assert clock.iso_ts(t) == "2026-11-11T14:20:01.412+01:00"


def test_from_ts_reads_a_message(showcase_pool: DescriptorPool) -> None:
    msg = Types(showcase_pool).new("de.showcase.wws.v1.datatype.OffsetTimestamp",
                                   seconds=1803409200, offset=60)
    value = clock.from_ts(msg)
    assert value.isoformat() == "2027-02-23T20:00:00+01:00"
