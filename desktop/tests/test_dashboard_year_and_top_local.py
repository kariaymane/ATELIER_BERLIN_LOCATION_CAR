"""
Desktop offline dashboard — year-to-date revenue + canonical local "Top 5
véhicules les plus loués".

Guards:
  * compute_overview_rows now also yields year_revenue / year_rentals using the
    exact canonical recognition-at-start rule (a wider window, not a new formula)
  * compute_top_vehicles_rows ranks vehicles by revenue with the SAME
    eligibility as backend RentalRepository.get_vehicle_stats
    (status != CANCELLED AND start_datetime <= now) — so the panel is never
    blank offline and never contradicts the server
  * DomainStore.snapshot carries top_vehicles

CASE D (cancelled excluded), CASE F (sorted desc), CASE C (history appears).
"""
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from app.sync.dashboard_cache import compute_overview_rows, compute_top_vehicles_rows

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
FLEET = {"total_vehicles": 3, "available": 1, "rented": 2, "reserved": 0, "maintenance": 0}


def _res(vid, status, start_iso, total, days=2):
    return {"vehicle_id": vid, "status": status, "start_datetime": start_iso,
            "num_days": days, "total_price": total}


DATA = [
    _res("A", "COMPLETED", "2026-01-15T09:00:00Z", 5000.0),
    _res("A", "COMPLETED", "2026-02-15T09:00:00Z", 1000.0),
    _res("B", "ACTIVE",    "2026-01-20T09:00:00Z", 3000.0),
    _res("C", "COMPLETED", "2026-08-27T09:00:00Z", 800.0),
    _res("A", "CANCELLED", "2026-01-25T09:00:00Z", 9999.0),   # CASE D
    _res("B", "RESERVED",  "2027-01-15T09:00:00Z", 7777.0),    # next year — excluded
]
VEH = [
    {"id": "A", "registration": "AA-1", "brand": "Dacia", "model": "Logan"},
    {"id": "B", "registration": "BB-2", "brand": "Renault", "model": "Clio"},
    {"id": "C", "registration": "CC-3", "brand": "Peugeot", "model": "208"},
]


def test_year_revenue_is_canonical_and_month_is_zero():
    ov = compute_overview_rows(DATA, FLEET, now=NOW)
    # 5000 (A Jan) + 1000 (A Feb) + 3000 (B Jan) + 800 (C Aug) — all started,
    # all in 2026. CANCELLED 9999 excluded; the 2027 booking excluded.
    assert ov["year_revenue"] == pytest.approx(9800.0)
    assert ov["month_revenue"] == pytest.approx(0.0)     # nothing started in September
    assert ov["week_revenue"] == pytest.approx(0.0)


def test_top_vehicles_ranked_by_revenue_excludes_cancelled_and_future():
    top = compute_top_vehicles_rows(DATA, VEH, now=NOW, limit=5)
    assert [t["vehicle_id"] for t in top] == ["A", "B", "C"]     # 6000 > 3000 > 800
    a = top[0]
    assert a["rental_count"] == 2            # the CANCELLED one is not counted
    assert a["total_revenue"] == pytest.approx(6000.0)
    assert a["brand"] == "Dacia" and a["model"] == "Logan"       # enriched from VEH


def test_top_vehicles_empty_only_when_no_started_noncancelled_history():
    only_future_and_cancelled = [
        _res("X", "CANCELLED", "2026-01-01T09:00:00Z", 100.0),
        _res("X", "RESERVED", "2027-06-01T09:00:00Z", 200.0),
    ]
    assert compute_top_vehicles_rows(only_future_and_cancelled, VEH, now=NOW) == []


def test_domain_store_snapshot_exposes_top_vehicles():
    from app.state.domain_store import DomainSnapshot
    snap = DomainSnapshot()
    assert hasattr(snap, "top_vehicles")
    assert snap.top_vehicles == ()
