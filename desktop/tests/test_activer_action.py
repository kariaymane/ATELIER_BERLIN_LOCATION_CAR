""""Activer" (RESERVED -> ACTIVE) — an explicit operational bookkeeping
action, kept strictly separate from the time-derived "en location" KPI.

CANONICAL RULE (see shared/fleet_status_reference.py):
    OPERATIONAL STATUS       RESERVED / ACTIVE / COMPLETED / CANCELLED
    CURRENT PHYSICAL RENTAL  start <= now < end, and not CANCELLED

A reservation covering `now` is "en location" (RENTED) whether its stored
status is RESERVED or ACTIVE. Clicking "Activer" changes the OPERATIONAL
status only — it must not be required, and must not change, the KPI that
was already true before the click.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from PySide6.QtWidgets import QApplication

from app.database import get_local_session, init_local_db
from app.models.vehicle import LocalVehicle
from app.models.reservation import LocalReservation
from app.sync.queue import SyncQueueItem
from app.sync.dashboard_cache import compute_local_overview
from app.ui.main_window import MainWindow

NOW = datetime.now(timezone.utc)
VID = "veh-activer"
RID = "res-activer"


@pytest.fixture(autouse=True)
def clean_db():
    init_local_db()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def window(qapp):
    w = MainWindow(user_data={"user_id": "u1", "role": "ADMIN", "full_name": "A",
                              "access_token": "x", "refresh_token": "x", "offline": True})
    w._run_sync = lambda *a, **k: None
    w._clients_page.refresh_data = lambda *a, **k: None
    if hasattr(w, "_sync_timer"):
        w._sync_timer.stop()
    yield w
    w.close()
    w.deleteLater()
    qapp.processEvents()


def _seed_reservation(status="RESERVED"):
    s = get_local_session()
    s.add(LocalVehicle(
        id=VID, brand="Dacia", model="Logan", status="AVAILABLE",
        daily_rental_price=200, registration="ACT-1", vin="11111111111111111",
        year=2024, color="Blanc", fuel_type="Diesel", transmission="Manual",
        created_at=NOW.isoformat(), updated_at=NOW.isoformat(),
    ))
    s.add(LocalReservation(
        id=RID, vehicle_id=VID, customer_name="Client Activer",
        start_datetime=(NOW - timedelta(hours=1)).isoformat(),
        end_datetime=(NOW + timedelta(days=3)).isoformat(),
        daily_price=200, num_days=3, total_price=600, deposit=0,
        status=status, created_at=NOW.isoformat(), updated_at=NOW.isoformat(),
        version=1,
    ))
    s.commit()
    s.close()


def test_reserved_covering_now_is_already_rented_before_activation(window):
    _seed_reservation(status="RESERVED")
    window._load_vehicles_from_local()

    ov = compute_local_overview()
    assert ov["rented"] == 1
    assert ov["reserved"] == 0
    vstatus = {v["id"]: v["status"] for v in window._vehicle_list._vehicles_data}
    assert vstatus[VID] == "RENTED"


def test_activer_transitions_status_but_kpi_stays_rented(window):
    """RESERVED --Activer--> ACTIVE. The KPI was YES before and stays YES —
    Activer is bookkeeping, not a precondition for "en location"."""
    _seed_reservation(status="RESERVED")
    window._load_vehicles_from_local()
    before = compute_local_overview()
    assert before["rented"] == 1

    window._reservations._activate_reservation(RID)

    s = get_local_session()
    res = s.query(LocalReservation).filter_by(id=RID).one()
    assert res.status == "ACTIVE"
    # exactly one reservation UPDATE queued for the server
    kinds = [(i.entity_type, i.operation) for i in s.query(SyncQueueItem).all()]
    assert ("reservation", "UPDATE") in kinds
    s.close()

    window._load_vehicles_from_local()
    after = compute_local_overview()
    assert after["rented"] == 1          # unchanged — still "en location"
    assert after["reserved"] == 0
    vstatus = {v["id"]: v["status"] for v in window._vehicle_list._vehicles_data}
    assert vstatus[VID] == "RENTED"      # unchanged


def test_activate_button_only_offered_for_reserved_rows(window):
    """The 'Activer' action is offered only while status == RESERVED — an
    already-ACTIVE reservation has nothing left to activate."""
    _seed_reservation(status="ACTIVE")
    window._reservations.refresh_data()
    table = window._reservations._table
    assert table.rowCount() == 1
    action_widget = table.cellWidget(0, 5)
    assert action_widget is not None
    labels = [c.text() for c in action_widget.findChildren(type(action_widget)) if False]
    # Simplest robust check: no QPushButton in the action cell is the
    # "Activer" i18n string when the reservation is already ACTIVE.
    from PySide6.QtWidgets import QPushButton
    from app.i18n import t
    texts = [b.text() for b in action_widget.findChildren(QPushButton)]
    assert t("reservations.action_activate") not in texts


def test_activate_button_offered_for_reserved_rows(window):
    _seed_reservation(status="RESERVED")
    window._reservations.refresh_data()
    table = window._reservations._table
    action_widget = table.cellWidget(0, 5)
    from PySide6.QtWidgets import QPushButton
    from app.i18n import t
    texts = [b.text() for b in action_widget.findChildren(QPushButton)]
    assert t("reservations.action_activate") in texts
