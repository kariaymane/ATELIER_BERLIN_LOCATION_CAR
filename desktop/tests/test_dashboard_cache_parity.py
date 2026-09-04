"""
CROSS-RUNTIME PARITY — desktop offline revenue engine vs the normative spec.

Every case in ``shared/revenue_cases.json`` is pushed through the desktop
``dashboard_cache.revenue_between_rows`` (the ONE desktop revenue function).
Its output must equal ``shared/revenue_reference.py`` — the same file the
backend and mobile parity tests assert against — so the desktop Dashboard,
the backend and the phone can never show a different chiffre d'affaires.
"""
import json
import os
import pathlib
import sys
from datetime import date, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CAR_RENTAL_DB_RESET"] = "1"

import pytest

_SHARED = pathlib.Path(__file__).resolve().parents[2] / "shared"
sys.path.insert(0, str(_SHARED))
from revenue_reference import revenue_between as ref_revenue  # noqa: E402
from money_time import period_bounds as ref_period_bounds  # noqa: E402

_CASES = json.loads((_SHARED / "revenue_cases.json").read_text())


@pytest.mark.parametrize("case", _CASES["revenue_cases"], ids=lambda c: c["name"])
def test_desktop_revenue_matches_reference(case):
    from app.sync.dashboard_cache import revenue_between_rows

    now = datetime.fromisoformat(case["now"])
    rows = [
        {
            "status": r["status"],
            "cancellation_reason": r.get("cancellation_reason"),
            "cancelled_at": r.get("cancelled_at"),
            "start_datetime": r["start_datetime"],
            "end_datetime": r.get("end_datetime"),
            "num_days": r["num_days"],
            "daily_price": r["daily_price"],
            "total_price": r["total_price"],
        }
        for r in case["reservations"]
    ]
    for q in case["queries"]:
        fd, td = date.fromisoformat(q["from"]), date.fromisoformat(q["to"])
        rev, days = revenue_between_rows(rows, fd, td, now)
        assert rev == pytest.approx(q["expected_revenue"]), (
            f"{case['name']} {q['from']}..{q['to']}: desktop {rev} != {q['expected_revenue']}"
        )
        assert days == q["expected_days"]
        assert rev == pytest.approx(ref_revenue(case["reservations"], fd, td, now))


@pytest.mark.parametrize("pc", _CASES["period_bounds_cases"],
                         ids=lambda c: f"{c['name']}@{c['now'][:10]}")
def test_desktop_named_period_bounds_match_shared(pc):
    from app.sync.dashboard_cache import _named_period_date_bounds, _now_biz

    now = _now_biz(datetime.fromisoformat(pc["now"]))
    fd, td = _named_period_date_bounds(pc["name"], now)
    assert fd.isoformat() == pc["start"]
    assert td.isoformat() == pc["end"]
    # and identical to the shared money_time implementation
    s, e = ref_period_bounds(pc["name"], datetime.fromisoformat(pc["now"]))
    assert fd == s.date() and td == e.date()


def test_overview_exposes_both_maintenance_keys():
    """C1: the online payload uses `active_maintenance_tickets`, the offline
    path historically only set `active_maintenances`. Both must always be
    present so the UI's key lookup cannot miss."""
    from app.sync.dashboard_cache import compute_overview_rows

    fleet = {"total_vehicles": 3, "available": 0, "rented": 1,
             "reserved": 0, "maintenance": 2}
    o = compute_overview_rows([], fleet, now=datetime.fromisoformat("2026-09-15T12:00:00+01:00"))
    assert o["active_maintenances"] == 2
    assert o["active_maintenance_tickets"] == 2
    assert o["maintenance"] == 2
