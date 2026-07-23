from datetime import datetime, timezone

import pytest

from app.ingest.parsers import parse_order_date


def test_iso8601_with_z_suffix():
    dt, fmt = parse_order_date("2026-06-03T20:11:00Z")
    assert fmt == "iso8601"
    assert dt == datetime(2026, 6, 3, 20, 11, tzinfo=timezone.utc)


def test_slash_dates_are_day_first():
    # 31/10/2025 only makes sense day-first; the parser must not try month-first.
    dt, fmt = parse_order_date("31/10/2025")
    assert fmt == "dmy"
    assert dt == datetime(2025, 10, 31, tzinfo=timezone.utc)


def test_ambiguous_slash_date_still_day_first():
    dt, _ = parse_order_date("05/03/2026")
    assert (dt.day, dt.month) == (5, 3)


def test_epoch_seconds_as_string():
    dt, fmt = parse_order_date("1768191660")
    assert fmt == "epoch"
    assert dt == datetime.fromtimestamp(1768191660, tz=timezone.utc)


def test_epoch_seconds_as_int():
    dt, fmt = parse_order_date(1768191660)
    assert fmt == "epoch"
    assert dt.tzinfo is not None


def test_epoch_outside_plausible_range_rejected():
    with pytest.raises(ValueError):
        parse_order_date("99")  # 1970 — not a plausible order date


def test_garbage_rejected():
    for bad in ("not-a-date", "32/01/2026", None, [], True):
        with pytest.raises(ValueError):
            parse_order_date(bad)


def test_naive_iso_assumed_utc():
    dt, _ = parse_order_date("2026-06-03T20:11:00")
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0
