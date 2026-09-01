"""INCREMENT 6A — forensic P0 regression guards (desktop).

P0-A: the maintenance form must CONVERT Africa/Casablanca local wall time to
the UTC instant (like the reservation form), never relabel it.

P0-B: no desktop view may present the RAW ``LocalVehicle.status`` column as the
current effective fleet status — the Vehicle Detail modal and the maintenance
vehicle picker must both agree with the canonical DomainStore snapshot.

Covers the brief's Test A / F / G.
"""
import os
import sys
import time
import types
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from datetime import datetime, timedelta, timezone
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QDateTime, QDate, QTime

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.maintenance import LocalMaintenance
from app.state.domain_store import get_domain_store
from app.utils.datetime_utils import parse_datetime_utc


@pytest.fixture(autouse=True)
def _db():
    init_local_db()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def casablanca_tz():
    """Run the body with the process clock on Africa/Casablanca (UTC+1, no DST
    in January)."""
    prev = os.environ.get("TZ")
    os.environ["TZ"] = "Africa/Casablanca"
    time.tzset()
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = prev
        time.tzset()


def _mk_vehicle(session, vid, status="AVAILABLE"):
    session.add(LocalVehicle(
        id=vid, brand="Peugeot", model="208", status=status,
        daily_rental_price=250, registration=f"6A-{vid[-4:]}",
        vin=f"VIN{vid[-13:]:0<13}", year=2024, color="Black",
        fuel_type="Diesel", transmission="Manual",
        created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
    ))


# ── Test A — Casablanca local time is CONVERTED, not relabelled ──────────────
def test_maintenance_form_converts_local_time_to_utc(qapp, casablanca_tz):
    from app.ui.maintenance.maintenance_list import MaintenanceFormDialog

    dialog = MaintenanceFormDialog({"id": "v1", "brand": "P", "model": "208",
                                    "registration": "X"})
    # 18:00 on 2026-01-15, Africa/Casablanca local == 17:00Z (UTC+1).
    dialog._start_dt.setDateTime(QDateTime(QDate(2026, 1, 15), QTime(18, 0, 0)))
    dialog._end_dt.setDateTime(QDateTime(QDate(2026, 1, 16), QTime(18, 0, 0)))
    dialog._desc.setPlainText("vidange")

    captured = {}
    dialog.saved.connect(lambda d: captured.update(d))
    dialog._on_save()

    start = parse_datetime_utc(captured["start_datetime"])
    assert start == datetime(2026, 1, 15, 17, 0, tzinfo=timezone.utc), (
        f"expected 17:00Z (local 18:00 converted), got {start.isoformat()}")
    # The old relabel bug would have produced 18:00Z:
    assert start != datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc)

    end = parse_datetime_utc(captured["expected_end_datetime"])
    assert end == datetime(2026, 1, 16, 17, 0, tzinfo=timezone.utc)


# ── Test F — future maintenance: every desktop observer says AVAILABLE ───────
def test_future_maintenance_converges_available_across_desktop_views(qapp, monkeypatch, request):
    from app.ui.main_window import MainWindow
    import app.ui.vehicles.vehicle_list as vl_mod

    session = get_local_session()
    _mk_vehicle(session, "v-6a-future")
    session.commit()

    mw = MainWindow(user_data={"user_id": "u-1", "access_token": "d", "offline": True})
    request.addfinalizer(lambda: (mw.close(), mw.deleteLater(), qapp.processEvents()))
    qapp.processEvents()

    future = datetime.now(timezone.utc) + timedelta(days=1)
    mw._create_maintenance_record({
        "vehicle_id": "v-6a-future", "type": "Entretien", "title": "T",
        "start_datetime": future.isoformat(),
        "expected_end_datetime": (future + timedelta(days=2)).isoformat(),
        "parts": [],
    })
    qapp.processEvents()

    snap = mw._store.snapshot
    assert snap.effective["v-6a-future"] == "AVAILABLE"
    assert snap.fleet_counts["maintenance"] == 0
    assert (snap.overview or {}).get("maintenance", 0) == 0

    # Vehicles list card
    card = next(v for v in mw._vehicle_list._vehicles_data if v["id"] == "v-6a-future")
    assert card["status"] == "AVAILABLE"

    # Vehicle Detail modal — simulate the backend having stuck the raw column,
    # then confirm the modal is still fed the canonical (AVAILABLE) status.
    session2 = get_local_session()
    vrow = session2.query(LocalVehicle).filter_by(id="v-6a-future").first()
    vrow.status = "MAINTENANCE"          # raw contradiction injected
    session2.commit()

    captured = {}
    monkeypatch.setattr(
        vl_mod, "VehicleDetailModal",
        lambda vehicle, parent=None: captured.update(vehicle)
        or types.SimpleNamespace(vehicle=vehicle, exec=lambda: 0),
    )
    row = vl_mod.VehicleRow(dict(card))
    row._show_details()
    assert captured["status"] == "AVAILABLE", (
        "Vehicle Detail modal showed the raw column, not the canonical status")


# ── Test G — maintenance vehicle picker agrees with canonical status ────────
def test_maintenance_picker_uses_canonical_effective_status(qapp):
    from app.ui.maintenance.maintenance_list import MaintenanceFormDialog

    session = get_local_session()
    _mk_vehicle(session, "v-6a-active")
    _mk_vehicle(session, "v-6a-sched")
    now = datetime.now(timezone.utc)
    session.add(LocalMaintenance(
        id="m-active", vehicle_id="v-6a-active", type="Panne", status="ACTIVE",
        start_datetime=(now - timedelta(hours=1)).isoformat(),
        expected_end_datetime=(now + timedelta(hours=2)).isoformat(),
        step="DIAGNOSTIC", created_at=now.isoformat(), updated_at=now.isoformat(),
        version=1,
    ))
    session.add(LocalMaintenance(
        id="m-sched", vehicle_id="v-6a-sched", type="Entretien", status="ACTIVE",
        start_datetime=(now + timedelta(days=2)).isoformat(),
        expected_end_datetime=(now + timedelta(days=3)).isoformat(),
        step="DIAGNOSTIC", created_at=now.isoformat(), updated_at=now.isoformat(),
        version=1,
    ))
    session.commit()

    get_domain_store().reload()

    dialog = MaintenanceFormDialog(None)  # picker branch
    ids = {dialog._vehicle_combo.itemData(i)
           for i in range(dialog._vehicle_combo.count())}

    assert "v-6a-active" not in ids   # effective MAINTENANCE -> excluded
    assert "v-6a-sched" in ids        # effective AVAILABLE (future) -> selectable
