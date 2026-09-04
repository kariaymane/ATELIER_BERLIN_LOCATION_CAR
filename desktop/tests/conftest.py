import os
import gc
import sys
import pathlib
import pytest

# Repo root on sys.path so ``from shared.X import ...`` (used by
# app.sync.dashboard_cache) resolves regardless of which test modules are
# collected. Previously this only worked as a side effect of
# ``test_e2e_sync_hover.py`` running early — a load-order landmine that made a
# partial test selection fail with ModuleNotFoundError: No module named 'shared'.
_REPO_ROOT = str(pathlib.Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


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
def set_test_db_reset(tmp_path, monkeypatch):
    """Ensure tests run in isolated reset mode against a temporary SQLite database.
    Production database is NEVER touched or reset by tests."""
    test_data = tmp_path / "data"
    test_data.mkdir(parents=True, exist_ok=True)
    test_db = test_data / "car_rental_local.db"
    test_url = f"sqlite:///{test_db}"

    original_reset = os.getenv("CAR_RENTAL_DB_RESET", None)
    original_dir = os.getenv("CAR_RENTAL_DATA_DIR", None)
    original_url = os.getenv("CAR_RENTAL_SQLITE_URL", None)

    monkeypatch.setenv("CAR_RENTAL_DB_RESET", "1")
    monkeypatch.setenv("CAR_RENTAL_DATA_DIR", str(test_data))
    monkeypatch.setenv("CAR_RENTAL_SQLITE_URL", test_url)

    import app.config
    monkeypatch.setattr(app.config, "DATA_DIR", test_data)
    monkeypatch.setattr(app.config, "DB_PATH", test_db)
    monkeypatch.setattr(app.config, "SQLITE_URL", test_url)

    # Force reset database engine to bind to the test url
    import app.database
    if app.database._engine is not None:
        try:
            app.database._engine.dispose()
        except Exception:
            pass
    app.database._engine = None
    app.database._session_factory = None

    yield

    if app.database._engine is not None:
        try:
            app.database._engine.dispose()
        except Exception:
            pass
    app.database._engine = None
    app.database._session_factory = None

    if original_reset is None:
        monkeypatch.delenv("CAR_RENTAL_DB_RESET", raising=False)
    else:
        monkeypatch.setenv("CAR_RENTAL_DB_RESET", original_reset)

    if original_dir is None:
        monkeypatch.delenv("CAR_RENTAL_DATA_DIR", raising=False)
    else:
        monkeypatch.setenv("CAR_RENTAL_DATA_DIR", original_dir)

    if original_url is None:
        monkeypatch.delenv("CAR_RENTAL_SQLITE_URL", raising=False)
    else:
        monkeypatch.setenv("CAR_RENTAL_SQLITE_URL", original_url)
