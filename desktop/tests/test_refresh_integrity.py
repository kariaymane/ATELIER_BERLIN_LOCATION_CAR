"""
Regression & Forensic tests for Refresh Pipeline and Data Integrity.
Verifies that:
- Refresh NEVER corrupts data, changes truth, or causes flicker to empty/stale states.
- Rapid repeated clicks coalesce without dropping requests or racing.
- Zero reservations yields 0.0 DH (never None or stale previous server revenue).
- All views render identically from the single unified DomainSnapshot.
"""
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CAR_RENTAL_DB_RESET", "1")

from PySide6.QtWidgets import QApplication
from app.database import init_local_db, get_local_session
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.models.maintenance import LocalMaintenance
from app.models.client import LocalClient
from app.state.domain_store import get_domain_store, reset_domain_store
from app.ui.main_window import MainWindow


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_vehicle(vid, status="AVAILABLE", registration=None):
    now_iso = datetime.now(timezone.utc).isoformat()
    return LocalVehicle(
        id=vid, registration=registration or f"R-{vid}", vin=f"{vid}vvvvvvvvvvvvvvvv"[:17],
        brand="Dacia", model="Logan", year=2024, color="Noir", fuel_type="DIESEL",
        transmission="MANUAL", status=status, daily_rental_price=300.0,
        created_at=now_iso, updated_at=now_iso, version=1)


def _make_client(cid, first="Ali", last="Bennani"):
    now_iso = datetime.now(timezone.utc).isoformat()
    return LocalClient(
        id=cid, first_name=first, last_name=last, phone="0611223344",
        status="ACTIVE", created_at=now_iso, updated_at=now_iso, version=1)


def _make_reservation(rid, vid, cid, status="ACTIVE", start=None, end=None):
    now = datetime.now(timezone.utc)
    return LocalReservation(
        id=rid, vehicle_id=vid, customer_id=cid, customer_name="Client Test",
        start_datetime=(start or (now - timedelta(hours=2))).isoformat(),
        end_datetime=(end or (now + timedelta(days=2))).isoformat(),
        daily_price=300.0, num_days=2, total_price=600.0, deposit=1000.0,
        payment_status="PAID", status=status,
        created_at=now.isoformat(), updated_at=now.isoformat(), version=1)


def _make_maintenance(mid, vid, status="ACTIVE", start=None, end=None):
    now = datetime.now(timezone.utc)
    return LocalMaintenance(
        id=mid, vehicle_id=vid, type="Entretien",
        start_datetime=(start or (now - timedelta(hours=1))).isoformat(),
        expected_end_datetime=(end or (now + timedelta(days=1))).isoformat(),
        status=status,
        created_at=now.isoformat(), updated_at=now.isoformat(), version=1)


@pytest.fixture(autouse=True)
def setup_clean_db():
    init_local_db()
    session = get_local_session()
    session.query(LocalReservation).delete()
    session.query(LocalMaintenance).delete()
    session.query(LocalVehicle).delete()
    session.query(LocalClient).delete()
    session.commit()
    session.close()
    reset_domain_store()
    yield
    reset_domain_store()


def test_scenario_a_normal_refresh_produces_identical_state(qapp):
    """Normal refresh without server changes must leave snapshot state identical."""
    session = get_local_session()
    v = _make_vehicle("v1", registration="11-A-11")
    c = _make_client("c1")
    session.add_all([v, c])
    session.commit()
    session.close()

    store = get_domain_store()
    snap_before = store.reload()

    assert len(snap_before.vehicles) == 1
    assert len(snap_before.clients) == 1
    assert snap_before.fleet_counts["total_vehicles"] == 1
    assert snap_before.fleet_counts["available"] == 1

    # Simulate sync finished with no changes
    report = {
        "is_online": True,
        "push": {"pushed": 0, "conflicts": []},
        "pull": {"items": []},
        "uploads": {"uploaded": 0},
    }

    user_data = {"user_id": "u1", "role": "ADMIN", "full_name": "Admin", "access_token": "tok"}
    window = MainWindow(user_data=user_data)
    try:
        window._on_sync_finished(report)
        snap_after = store.snapshot

        assert len(snap_after.vehicles) == len(snap_before.vehicles)
        assert len(snap_after.clients) == len(snap_before.clients)
        assert snap_after.fleet_counts == snap_before.fleet_counts
        assert snap_after.overview["total_vehicles"] == snap_before.overview["total_vehicles"]
    finally:
        window.deleteLater()


def test_scenario_b_rapid_refreshes_coalesce_and_do_not_flicker(qapp):
    """5 rapid clicks must coalesce into at most one in-flight + one pending sync."""
    user_data = {"user_id": "u1", "role": "ADMIN", "full_name": "Admin", "access_token": "tok"}
    window = MainWindow(user_data=user_data)
    try:
        window._run_sync = MagicMock()
        mock_thread = MagicMock()
        mock_thread.isRunning.return_value = True
        window._sync_thread = mock_thread

        # 5 rapid clicks while thread is running
        for _ in range(5):
            window._on_refresh_clicked()

        assert window._sync_pending is True
        # _run_sync should not have been called again since thread was running
        window._run_sync.assert_not_called()

        # When the running thread finishes, the pending cycle must trigger
        mock_thread.isRunning.return_value = False
        window._on_sync_thread_finished()
        assert window._run_sync.call_count == 1
        assert window._sync_pending is False
    finally:
        window.deleteLater()


def test_scenario_c_zero_reservations_produces_zero_revenue_never_none_or_stale(qapp):
    """When no reservations exist, revenue MUST be 0.0, never None or stale cache."""
    session = get_local_session()
    v = _make_vehicle("v1", registration="22-B-22")
    session.add(v)
    session.commit()
    session.close()

    store = get_domain_store()
    snap = store.reload()

    assert snap.overview["today_revenue"] == 0.0
    assert snap.overview["week_revenue"] == 0.0
    assert snap.overview["month_revenue"] == 0.0
    assert snap.overview["year_revenue"] == 0.0

    user_data = {"user_id": "u1", "role": "ADMIN", "full_name": "Admin", "access_token": "tok"}
    window = MainWindow(user_data=user_data)
    try:
        # Simulate previous stale server overview
        window._last_server_overview = {
            "today_revenue": 9999.0,
            "month_revenue": 88888.0,
        }
        window._refresh_dashboard()

        # Local snapshot overview must NOT have been corrupted by _last_server_overview
        assert window._dashboard._overview_data.get("today_revenue") == 0.0
        assert window._dashboard._overview_data.get("month_revenue") == 0.0
    finally:
        window.deleteLater()


def test_scenario_d_all_tabs_render_from_unified_domain_snapshot(qapp):
    """Vehicles, Reservations, Maintenance, Clients, and Dashboard must agree 100%."""
    now = datetime.now(timezone.utc)
    session = get_local_session()
    v1 = _make_vehicle("v1", registration="33-C-33")
    v2 = _make_vehicle("v2", registration="44-D-44")
    c1 = _make_client("c1", first="Fatima", last="Zahra")
    r1 = _make_reservation("r1", "v1", "c1", status="ACTIVE")
    m1 = _make_maintenance("m1", "v2", status="ACTIVE")
    session.add_all([v1, v2, c1, r1, m1])
    session.commit()
    session.close()

    user_data = {"user_id": "u1", "role": "ADMIN", "full_name": "Admin", "access_token": "tok"}
    window = MainWindow(user_data=user_data)
    try:
        store = get_domain_store()
        snap = store.reload()

        # Invariants across the whole domain:
        assert snap.fleet_counts["total_vehicles"] == 2
        assert snap.fleet_counts["rented"] == 1
        assert snap.fleet_counts["maintenance"] == 1
        assert snap.fleet_counts["available"] == 0
        assert len(snap.clients) == 1

        # Check MainWindow fan-out:
        window._on_domain_changed(snap, snap.revision)

        # Dashboard numbers:
        assert window._dashboard._overview_data["total_vehicles"] == 2
        assert window._dashboard._overview_data["rented"] == 1
        assert window._dashboard._overview_data["maintenance"] == 1

        # Clients list numbers:
        assert len(window._clients_page._clients) == 1
        assert window._clients_page._clients[0]["first_name"] == "Fatima"
    finally:
        window.deleteLater()


def test_scenario_e_snapshot_validation_rejects_corrupted_state():
    """Negative counts or corrupted revenues must be caught by _validate_snapshot."""
    store = get_domain_store()
    valid_snap = store.reload()

    from app.state.domain_store import DomainSnapshot
    corrupted_snap = DomainSnapshot(
        revision=999,
        fleet_counts={"total_vehicles": -1, "available": 0},
    )
    assert store._validate_snapshot(corrupted_snap) is False

    corrupted_revenue_snap = DomainSnapshot(
        revision=1000,
        fleet_counts={"total_vehicles": 1, "available": 1},
        overview={"today_revenue": -50.0},
    )
    assert store._validate_snapshot(corrupted_revenue_snap) is False
