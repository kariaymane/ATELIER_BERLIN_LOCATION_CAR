"""Normative period-bounds contract — shared/money_time.py.

Every named reporting period the dashboard offers resolves to the exact
half-open [start, end) interval pinned in shared/revenue_cases.json. Locks
week-start-Monday, month/year wrap, and the yesterday/last_* offsets.
"""
import json
import pathlib
import sys
from datetime import date, datetime

import pytest

_SHARED = pathlib.Path(__file__).resolve().parents[2] / "shared"
sys.path.insert(0, str(_SHARED))
from money_time import (  # noqa: E402
    period_bounds, custom_bounds, PERIOD_NAMES, fmt_display_date, parse_iso_date,
)

_CASES = json.loads((_SHARED / "revenue_cases.json").read_text())


@pytest.mark.parametrize("pc", _CASES["period_bounds_cases"],
                         ids=lambda c: f"{c['name']}@{c['now'][:10]}")
def test_period_bounds_match_vectors(pc):
    s, e = period_bounds(pc["name"], datetime.fromisoformat(pc["now"]))
    assert s.date().isoformat() == pc["start"]
    assert e.date().isoformat() == pc["end"]
    assert s.tzinfo is not None and e.tzinfo is not None


def test_all_period_names_resolve():
    now = datetime.fromisoformat("2026-09-16T12:00:00+01:00")
    for name in PERIOD_NAMES:
        s, e = period_bounds(name, now)
        assert s < e


def test_unknown_period_raises():
    with pytest.raises(ValueError):
        period_bounds("fortnight")


def test_custom_bounds_end_is_exclusive_after_inclusive_ui_date():
    s, e = custom_bounds(date(2026, 9, 1), date(2026, 9, 30))
    assert s.date() == date(2026, 9, 1)
    assert e.date() == date(2026, 10, 1)  # 30th counts -> exclusive 1 Oct


def test_custom_bounds_swaps_reversed_range():
    s, e = custom_bounds(date(2026, 9, 30), date(2026, 9, 1))
    assert s.date() == date(2026, 9, 1)
    assert e.date() == date(2026, 10, 1)


def test_display_format_is_ddmmyyyy():
    assert fmt_display_date(date(2026, 9, 2)) == "02/09/2026"
    assert fmt_display_date(parse_iso_date("2026-12-31")) == "31/12/2026"


def test_naive_datetime_policy_is_unified_across_shared_modules():
    """v1.1.0 audit P2-4: a naive datetime must be read as business-local
    (Africa/Casablanca) by EVERY shared engine — not UTC by some and local by
    others. A single naive value (SQLite round-trip / legacy row) must not shift
    revenue vs fleet-status by ~1 h."""
    from datetime import datetime, timezone
    from shared.money_time import to_business, BUSINESS_TZ
    from shared.revenue_reference import _as_datetime as rev_parse
    from shared.fleet_status_reference import _parse as fleet_parse

    naive = datetime(2026, 9, 4, 10, 0, 0)  # no tzinfo

    # money_time: naive -> business-local
    mt = to_business(naive)
    assert mt.tzinfo is not None
    assert mt.utcoffset() == datetime(2026, 9, 4, tzinfo=BUSINESS_TZ).utcoffset()

    # revenue engine agrees (compare the absolute instant)
    assert rev_parse(naive).astimezone(timezone.utc) == mt.astimezone(timezone.utc)

    # fleet-status engine agrees
    assert fleet_parse(naive) == mt.astimezone(timezone.utc)
