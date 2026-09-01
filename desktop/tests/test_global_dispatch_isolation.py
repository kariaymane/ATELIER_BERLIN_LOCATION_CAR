"""Regression (Root Cause #5): MainWindow._on_global_data_refreshed must
isolate every view refresh. One view raising an exception must NOT stop the
other views from refreshing.
"""
import os
import sys

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from PySide6.QtWidgets import QApplication

from app.database import init_local_db
from app.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def clean_db():
    init_local_db()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_one_failing_view_does_not_block_the_others(qapp, request):
    w = MainWindow(user_data={"user_id": "u1", "role": "ADMIN", "full_name": "A",
                              "access_token": "x", "refresh_token": "x", "offline": True})
    request.addfinalizer(lambda: (w.close(), w.deleteLater(), qapp.processEvents()))

    calls = []
    w._load_vehicles_from_local = lambda: calls.append("vehicles")
    w._refresh_dashboard = lambda: calls.append("dashboard")

    def boom():
        calls.append("reservations")
        raise RuntimeError("simulated bad row in reservations view")

    w._reservations.refresh_data = boom
    w._maintenance.refresh_data = lambda: calls.append("maintenance")
    w._clients_page.refresh_data = lambda: calls.append("clients")

    # Must not raise
    w._on_global_data_refreshed()

    assert calls == ["vehicles", "dashboard", "reservations", "maintenance", "clients"], (
        "every view must be attempted even though 'reservations' raised"
    )


def test_dispatch_still_propagates_after_a_view_raises_twice(qapp, request):
    w = MainWindow(user_data={"user_id": "u1", "role": "ADMIN", "full_name": "A",
                              "access_token": "x", "refresh_token": "x", "offline": True})
    request.addfinalizer(lambda: (w.close(), w.deleteLater(), qapp.processEvents()))

    hits = {"maintenance": 0, "clients": 0}
    w._load_vehicles_from_local = lambda: None
    w._refresh_dashboard = lambda: None
    w._reservations.refresh_data = lambda: (_ for _ in ()).throw(ValueError("x"))
    w._maintenance.refresh_data = lambda: hits.__setitem__("maintenance", hits["maintenance"] + 1)
    w._clients_page.refresh_data = lambda: hits.__setitem__("clients", hits["clients"] + 1)

    w._on_global_data_refreshed()
    w._on_global_data_refreshed()

    assert hits == {"maintenance": 2, "clients": 2}
