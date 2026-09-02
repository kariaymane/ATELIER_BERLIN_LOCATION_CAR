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
