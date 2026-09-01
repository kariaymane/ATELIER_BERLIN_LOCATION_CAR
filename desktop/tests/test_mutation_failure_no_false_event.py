"""Regression (Root Cause #6): a failed mutation must roll back, surface a
visible error, and NOT emit a false global refresh event.
"""
import os
import sys

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["CAR_RENTAL_DB_RESET"] = "1"

from PySide6.QtWidgets import QApplication, QMessageBox

from app.database import init_local_db, get_local_session
from app.models.maintenance import LocalMaintenance
from app.services.event_bus import get_event_bus
from app.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def clean_db():
    init_local_db()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_failed_maintenance_create_rolls_back_and_shows_error_and_no_event(qapp, request, monkeypatch):
    w = MainWindow(user_data={"user_id": "u1", "role": "ADMIN", "full_name": "A",
                              "access_token": "x", "refresh_token": "x", "offline": True})
    request.addfinalizer(lambda: (w.close(), w.deleteLater(), qapp.processEvents()))
    w._run_sync = lambda *a, **k: None

    events = []
    get_event_bus().data_refreshed.connect(lambda: events.append(1))

    errors = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: errors.append(a)))

    # Force the commit to fail mid-mutation. Committed mutations now run through
    # DomainStore.mutate(), which opens its session via
    # ``app.database.get_local_session`` — patch there.
    import app.database as db

    rev_before = w._store.revision
    real_session = get_local_session

    class _BoomSession:
        def __init__(self, inner):
            self._inner = inner
            self.rolled_back = False

        def __getattr__(self, n):
            return getattr(self._inner, n)

        def commit(self):
            raise RuntimeError("simulated DB failure")

        def rollback(self):
            self.rolled_back = True
            return self._inner.rollback()

    holder = {}

    def _fake():
        s = _BoomSession(real_session())
        holder["s"] = s
        return s

    monkeypatch.setattr(db, "get_local_session", _fake)

    w._create_maintenance_record({
        "vehicle_id": "v-x", "type": "Entretien",
        "start_datetime": "2026-01-01T00:00:00+00:00", "parts": [],
    })

    assert holder["s"].rolled_back is True, "must roll back on failure"
    assert len(errors) == 1, "must show a visible error dialog"
    assert events == [], "must NOT emit a false global refresh event"
    assert w._store.revision == rev_before, "a failed mutation must NOT publish a new revision"

    # And nothing was persisted.
    monkeypatch.undo()
    s = get_local_session()
    try:
        assert s.query(LocalMaintenance).count() == 0
    finally:
        s.close()
