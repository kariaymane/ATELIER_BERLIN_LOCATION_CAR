import os
import pytest

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
