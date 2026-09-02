import os
import gc
import pytest


@pytest.fixture(autouse=True)
def _no_network_warmup(monkeypatch):
    """The login screen fires a /health warmup ping on open. In tests that
    must never touch the real network (or block on a DNS/connect timeout)."""
    try:
        monkeypatch.setattr(
            "app.services.auth_client.AuthClient.warmup",
            lambda self: None,
            raising=False,
        )
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _reset_domain_store():
    """Give every test a fresh DomainStore singleton with no leftover
    subscribers from a previous test's (now-destroyed) MainWindow."""
    try:
        from app.state.domain_store import reset_domain_store
        reset_domain_store()
    except Exception:
        pass
    yield
    try:
        from app.state.domain_store import reset_domain_store
        reset_domain_store()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _qt_thread_teardown():
    """Stop any QThreads still running at end of test.

    Several widget tests build a full ``MainWindow`` (which starts a sync
    timer + background ``QThread``) without an explicit teardown. When the
    Python object is later garbage-collected with its thread still running,
    Qt aborts the interpreter ("QThread: Destroyed while thread is still
    running"). This fixture drains the event loop and joins live threads so
    the suite exits cleanly and results are trustworthy.
    """
    yield
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QThread, QCoreApplication
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        gc.collect()
        for obj in list(gc.get_objects()):
            if isinstance(obj, QThread):
                try:
                    if obj.isRunning():
                        obj.quit()
                        obj.wait(3000)
                except RuntimeError:
                    pass  # underlying C++ object already gone
        # Stop any BoundaryClock left running by a test that did not close its
        # MainWindow — a stray single-shot timer firing later would recompute
        # against a store whose subscribers belong to a destroyed window.
        try:
            from app.state.boundary_clock import BoundaryClock
            for obj in list(gc.get_objects()):
                if isinstance(obj, BoundaryClock):
                    try:
                        obj.stop()
                    except Exception:
                        pass
        except Exception:
            pass
        if app is not None:
            app.processEvents()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def set_test_db_reset(monkeypatch):
    """Ensure tests run in reset mode.
    The environment variable ``CAR_RENTAL_DB_RESET`` is set to ``1`` for the duration
    of each test, guaranteeing a clean SQLite database. After the test it is
    restored to its previous value (or removed if it was not set)."""
    original = os.getenv("CAR_RENTAL_DB_RESET", None)
    monkeypatch.setenv("CAR_RENTAL_DB_RESET", "1")
    yield
    if original is None:
        monkeypatch.delenv("CAR_RENTAL_DB_RESET", raising=False)
    else:
        monkeypatch.setenv("CAR_RENTAL_DB_RESET", original)
