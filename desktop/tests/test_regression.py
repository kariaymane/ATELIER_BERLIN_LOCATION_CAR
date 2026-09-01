import pytest
from datetime import datetime, timezone, timedelta
from app.sync.dashboard_cache import compute_local_overview
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.database import get_local_session, init_local_db
from app.ui.main_window import MainWindow

def test_regression_01_dashboard_kpi_cache_equals_backend(monkeypatch):
    """
    Test that the desktop dashboard cache computes rented and reserved correctly
    based on overlaps, matching the backend exactly.

    CANONICAL RULE (time-derived "currently in location", not status-derived):
    a reservation — RESERVED or ACTIVE — whose window contains `now`
    (start <= now < end) means the car is physically out -> RENTED. This
    business has no separate pickup step, so RESERVED-covering-now counts
    exactly like ACTIVE-covering-now. RESERVED is reserved for a booking that
    has NOT started yet (see test_regression_04).
    """
    init_local_db()
    session = get_local_session()

    # 1. Setup mock vehicles
    now = datetime.now(timezone.utc)
    v1 = LocalVehicle(id="v1", registration="123", vin="123", brand="Test", model="A", year=2024, color="Red", fuel_type="Gas", transmission="Auto", status="AVAILABLE", created_at=now.isoformat(), updated_at=now.isoformat())
    v2 = LocalVehicle(id="v2", registration="124", vin="124", brand="Test", model="B", year=2024, color="Red", fuel_type="Gas", transmission="Auto", status="AVAILABLE", created_at=now.isoformat(), updated_at=now.isoformat())
    session.add(v1)
    session.add(v2)

    now = datetime.now(timezone.utc)

    # 2. Covering-now reservation, stored status ACTIVE -> RENTED
    r1 = LocalReservation(
        id="r1", vehicle_id="v1", status="ACTIVE", daily_price=0, num_days=1, total_price=0, created_at=now.isoformat(), updated_at=now.isoformat(),
        start_datetime=(now - timedelta(hours=1)).isoformat(),
        end_datetime=(now + timedelta(hours=1)).isoformat()
    )

    # 3. Covering-now reservation, stored status RESERVED -> ALSO RENTED
    #    (time-derived: the window already contains now, whatever the status).
    r2 = LocalReservation(
        id="r2", vehicle_id="v2", status="RESERVED", daily_price=0, num_days=1, total_price=0, created_at=now.isoformat(), updated_at=now.isoformat(),
        start_datetime=(now - timedelta(hours=1)).isoformat(),
        end_datetime=(now + timedelta(hours=1)).isoformat()
    )

    session.add(r1)
    session.add(r2)
    session.commit()

    metrics = compute_local_overview(session)

    # Both reservations cover `now` -> both count as RENTED regardless of
    # their stored RESERVED/ACTIVE status. Neither is "reserved" (upcoming).
    assert metrics["rented"] == 2
    assert metrics["reserved"] == 0
    assert metrics["total_vehicles"] == 2
    assert metrics["available"] == 0

def test_regression_03_vehicle_effective_status():
    """
    Test that Vehicle List computes effective status as RENTED if an ACTIVE reservation overlaps.
    """
    init_local_db()
    session = get_local_session()
    
    # Vehicle is physically AVAILABLE in DB
    now = datetime.now(timezone.utc)
    v1 = LocalVehicle(id="v1", registration="123", vin="123", brand="Test", model="A", year=2024, color="Red", fuel_type="Gas", transmission="Auto", status="AVAILABLE", created_at=now.isoformat(), updated_at=now.isoformat())
    session.add(v1)
    
    now = datetime.now(timezone.utc)
    r1 = LocalReservation(
        id="r1", vehicle_id="v1", status="ACTIVE", daily_price=0, num_days=1, total_price=0, created_at=now.isoformat(), updated_at=now.isoformat(),
        start_datetime=(now - timedelta(hours=1)).isoformat(),
        end_datetime=(now + timedelta(hours=1)).isoformat()
    )
    session.add(r1)
    session.commit()
    
    # Instead of full UI test which might be complex to setup headless, 
    # we replicate the exact logic from _load_vehicles_from_local
    rented_vids = set()
    from app.utils.datetime_utils import parse_datetime_utc
    for r in session.query(LocalReservation).filter(LocalReservation.status != "CANCELLED").all():
        r_start = parse_datetime_utc(r.start_datetime)
        r_end = parse_datetime_utc(r.end_datetime)
        if r_start and r_end and r_start <= now < r_end:
            if (r.status or "").upper() == "ACTIVE":
                rented_vids.add(r.vehicle_id)
                
    assert "v1" in rented_vids

def test_regression_04_future_reservation_does_not_make_rented():
    """
    A future reservation does NOT make the vehicle RENTED now — it is not yet
    physically out, so it does not count toward "en location". It IS an
    upcoming booking though, so the dashboard surfaces it as RESERVED (not
    AVAILABLE): "available" means nothing at all is booked for this car.
    """
    init_local_db()
    session = get_local_session()

    now = datetime.now(timezone.utc)
    v1 = LocalVehicle(id="v1", registration="123", vin="123", brand="Test", model="A", year=2024, color="Red", fuel_type="Gas", transmission="Auto", status="AVAILABLE", created_at=now.isoformat(), updated_at=now.isoformat())
    session.add(v1)

    now = datetime.now(timezone.utc)
    r1 = LocalReservation(
        id="r1", vehicle_id="v1", status="ACTIVE", daily_price=0, num_days=1, total_price=0, created_at=now.isoformat(), updated_at=now.isoformat(),
        start_datetime=(now + timedelta(hours=1)).isoformat(),
        end_datetime=(now + timedelta(hours=2)).isoformat()
    )
    session.add(r1)
    session.commit()

    metrics = compute_local_overview(session)
    assert metrics["rented"] == 0
    assert metrics["reserved"] == 1
    assert metrics["available"] == 0
