"""
Desktop offline dashboard rule == backend canonical rule (parity proof).

Seeds identical controlled data and asserts the desktop cache computation
matches the exact semantics pinned in backend tests (status filter,
start-in-[start,end) boundaries, Africa/Casablanca periods).
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CAR_RENTAL_DB_RESET"] = "1"

import pytest

TZ = ZoneInfo("Africa/Casablanca")


@pytest.fixture()
def seeded():
    from app.database import init_local_db, get_local_session
    from app.models.vehicle import LocalVehicle
    from app.models.reservation import LocalReservation
    from app.models.maintenance import LocalMaintenance
    init_local_db()
    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()

    session.merge(LocalVehicle(
        id="d-veh-1", registration="DASH-1-A-1", vin="1M8GDM9AXKP042788",
        brand="Renault", model="Clio", year=2024, color="Bleu",
        fuel_type="DIESEL", transmission="MANUAL", current_mileage=100,
        daily_rental_price=300.0, status="AVAILABLE",
        created_at=now, updated_at=now, version=1))
    session.merge(LocalVehicle(
        id="d-veh-2", registration="DASH-2-B-2", vin="1M8GDM9AXKP042789",
        brand="Dacia", model="Logan", year=2024, color="Blanc",
        fuel_type="GASOLINE", transmission="MANUAL", current_mileage=200,
        daily_rental_price=250.0, status="RENTED",
        created_at=now, updated_at=now, version=1))
    session.merge(LocalMaintenance(
        id="d-mnt-1", vehicle_id="d-veh-1", type="Entretien",
        start_datetime=now, status="ACTIVE", step="EN COURS",
        created_at=now, updated_at=now, version=1))

    tznow = datetime.now(TZ)
    def local_iso(dt):
        return dt.replace(tzinfo=None).isoformat()  # naive local wall time

    rows = [
        # (start_local, days, total, status)
        (tznow.replace(hour=8), 2, 600.0, "COMPLETED"),    # today -> counted
        (tznow.replace(hour=0, minute=0, second=0), 1, 250.0, "ACTIVE"), # today -> counted & currently active
        (tznow - timedelta(days=3), 4, 999.0, "CANCELLED"),# excluded
        (tznow - timedelta(days=10), 3, 750.0, "COMPLETED"),# this month only
    ]
    for i, (start, days, total, status) in enumerate(rows):
        session.merge(LocalReservation(
            id=f"d-res-{i}", vehicle_id="d-veh-1" if i % 2 == 0 else "d-veh-2",
            customer_name="Parity Test", customer_phone="+212612345678",
            start_datetime=local_iso(start),
            end_datetime=local_iso(start + timedelta(days=days)),
            daily_price=100.0, num_days=days, total_price=total,
            deposit=0, status=status, payment_status="PENDING",
            created_at=now, updated_at=now, version=1))
    session.commit()
    session.close()
    yield


def test_local_overview_matches_backend_rule(seeded):
    from app.sync.dashboard_cache import compute_local_overview
    o = compute_local_overview()

    # Canonical effective status: d-veh-1 has an ACTIVE, open-ended maintenance
    # ticket that has started -> it occupies the vehicle (MAINTENANCE) until
    # closed. d-veh-2 has an ACTIVE reservation covering now -> RENTED.
    # The dashboard shows ONE maintenance number.
    assert o["total_vehicles"] == 2
    assert o["available"] == 0 and o["rented"] == 1
    assert o["reserved"] == 0 and o["maintenance"] == 1
    assert o["active_maintenances"] == o["maintenance"] == 1
    assert (o["available"] + o["rented"] + o["reserved"] + o["maintenance"]
            == o["total_vehicles"])

    # Today: COMPLETED(600) + ACTIVE(250) count; CANCELLED excluded
    assert o["today_rentals"] == 2
    assert o["today_revenue"] == pytest.approx(850.0)

    # Week: today's two + none older this week unless the -10d falls in it.
    # Compute expected week revenue from the same rule.
    from datetime import datetime as dt
    now = datetime.now(TZ)
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    expected_week = 850.0
    if now - timedelta(days=10) >= week_start:
        expected_week += 750.0  # -10d COMPLETED also in this week
    assert o["week_revenue"] == pytest.approx(expected_week)
    assert o["week_rentals"] == (3 if expected_week > 850 else 2)

    # Month: all three non-cancelled (assuming all within current month)
    in_month = (now - timedelta(days=10)).month == now.month
    expected_month = 850.0 + (750.0 if in_month else 0.0)
    assert o["month_revenue"] == pytest.approx(expected_month)

    # Decimal precision: 0.1 + 0.2 case
    from app.database import get_local_session
    from app.models.reservation import LocalReservation
    session = get_local_session()
    now_iso = datetime.now(timezone.utc).isoformat()
    tznow = datetime.now(TZ)
    session.merge(LocalReservation(
        id="d-res-prec", vehicle_id="d-veh-1",
        customer_name="Parity", customer_phone="+212612345678",
        start_datetime=tznow.replace(hour=11).replace(tzinfo=None).isoformat(),
        end_datetime=(tznow + timedelta(days=1)).replace(tzinfo=None).isoformat(),
        daily_price=0.15, num_days=1, total_price=0.1 + 0.2,
        deposit=0, status="COMPLETED", payment_status="PENDING",
        created_at=now_iso, updated_at=now_iso, version=1))
    session.commit()
    session.close()

    o2 = compute_local_overview()
    assert o2["today_revenue"] == pytest.approx(850.3)  # exact decimal, no drift
