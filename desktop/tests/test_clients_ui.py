"""
Clients module UI tests — list rendering, search, details fallback math.

The details dialog offline fallback must reproduce the canonical backend
business rule exactly: CANCELLED excluded from totals, num_days canonical,
per-vehicle breakdown aggregated.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CAR_RENTAL_DB_RESET"] = "1"

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture()
def seeded_db():
    from app.database import init_local_db, get_local_session
    from app.models.client import LocalClient
    from app.models.vehicle import LocalVehicle
    from app.models.reservation import LocalReservation
    init_local_db()
    session = get_local_session()
    now = datetime.now(timezone.utc).isoformat()

    session.merge(LocalClient(
        id="cli-ui-1", first_name="Karim", last_name="Idrissi",
        phone="+212611223344", email="karim@test.local", cin_number="EE777888",
        status="ACTIVE", created_at=now, updated_at=now, version=1,
    ))
    session.merge(LocalVehicle(
        id="veh-a", registration="AA-1-A-1", vin="1M8GDM9AXKP042788",
        brand="Dacia", model="Logan", year=2024, color="Blanc",
        fuel_type="DIESEL", transmission="MANUAL", current_mileage=100,
        daily_rental_price=100.0, status="AVAILABLE",
        created_at=now, updated_at=now, version=1,
    ))
    rows = [
        # start, days, total, status  (all windows are historical -> none is
        # "en cours"/active right now, whatever the stored status)
        ("2026-06-01T10:00:00+00:00", 3, 300.0, "COMPLETED"),
        ("2026-07-01T10:00:00+00:00", 5, 500.0, "ACTIVE"),
        ("2026-08-01T10:00:00+00:00", 2, 200.0, "COMPLETED"),
        ("2026-09-01T10:00:00+00:00", 4, 400.0, "CANCELLED"),
    ]
    for i, (start, days, total, status) in enumerate(rows):
        start_dt = datetime.fromisoformat(start)
        session.merge(LocalReservation(
            id=f"res-ui-{i}", vehicle_id="veh-a",
            customer_name="Karim Idrissi", customer_phone="+212611223344",
            start_datetime=start,
            end_datetime=(start_dt + timedelta(days=days)).isoformat(),
            daily_price=100.0, num_days=days, total_price=total,
            deposit=0, status=status, payment_status="PENDING",
            created_at=now, updated_at=now, version=1,
        ))
    session.commit()
    session.close()
    yield


def _client_row():
    return {
        "id": "cli-ui-1", "first_name": "Karim", "last_name": "Idrissi",
        "phone": "+212611223344", "email": "karim@test.local",
        "cin_number": "EE777888", "status": "ACTIVE",
    }


def test_clients_list_renders_and_filters(qapp, seeded_db):
    from app.ui.clients.client_list import ClientsWidget
    w = ClientsWidget(api_client=None)
    w.refresh_data()
    assert w._table.rowCount() >= 1
    # Search by CIN narrows to matching client
    w._search.setText("EE777888")
    assert w._table.rowCount() == 1
    found_item = w._table.item(0, 0)
    assert "Karim" in found_item.text()


def test_client_details_offline_matches_canonical_rule(qapp, seeded_db):
    """Offline cache math must equal the backend rule exactly."""
    from app.ui.clients.client_details import ClientDetailsDialog
    dlg = ClientDetailsDialog(_client_row(), api_client=None)
    dlg._apply_offline_fallback()

    def val(key):
        return dlg._kpi_cards[key].text()

    assert val("total_rentals") == "3"
    assert val("total_days") == "10"
    assert val("total_amount").startswith("1000.00")
    # active_rentals (En cours) is time-derived (start <= now < end): every
    # window in this fixture is historical, so none is currently ongoing —
    # not even the row still carrying an ACTIVE status.
    assert val("active_rentals") == "0"
    assert val("completed_rentals") == "2"
    assert val("cancelled_rentals") == "1"
    assert val("vehicles_rented") == "1"
    # History lists all four including cancelled
    assert dlg._table.rowCount() == 4
    dlg.close()


def test_client_details_live_report_applied(qapp, seeded_db):
    from app.ui.clients.client_details import ClientDetailsDialog
    report = {
        "summary": {
            "total_rentals": 3, "total_days": 10, "total_amount": 1000.0,
            "active_rentals": 1, "completed_rentals": 2,
            "cancelled_rentals": 1, "vehicles_rented": 2,
        },
        "rentals": [
            {"id": "r1", "vehicle_brand": "Dacia", "vehicle_model": "Logan",
             "vehicle_registration": "AA-1-A-1", "start_datetime": "2026-06-01T10:00:00Z",
             "end_datetime": "2026-06-04T10:00:00Z", "num_days": 3,
             "daily_price": 100.0, "total_price": 300.0, "status": "COMPLETED"},
        ],
        "vehicles": [
            {"vehicle_id": "veh-a", "registration": "AA-1-A-1", "brand": "Dacia",
             "model": "Logan", "rentals": 2, "days": 5, "amount": 500.0},
        ],
    }
    dlg = ClientDetailsDialog(_client_row(), api_client=None)
    dlg._on_report_ready(report)
    assert dlg._kpi_cards["total_rentals"].text() == "3"
    assert dlg._kpi_cards["total_amount"].text().startswith("1000.00")
    assert "Dacia" in dlg._vehicles_lbl.text()
    assert dlg._table.rowCount() == 1
    dlg.close()


def test_missing_documents_show_unavailable(qapp, seeded_db):
    from app.i18n import t as _
    from app.ui.clients.client_details import ClientDetailsDialog
    dlg = ClientDetailsDialog(_client_row(), api_client=None)
    for key, thumb in dlg._doc_thumbs.items():
        text = thumb.text()
        assert "disponible" in text or "متوفر" in text
    dlg.close()
