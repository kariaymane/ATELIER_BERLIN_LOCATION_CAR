"""
Pytest wrapper: full startup E2E (login -> MainWindow visible -> navigation).

Runs tests/e2e_startup_check.py as an isolated process because it drives a
complete QApplication lifecycle including a real login flow.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_startup_login_mainwindow_visible(tmp_path):
    project_root = Path(__file__).resolve().parent.parent
    test_data = tmp_path / "data"
    test_data.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(project_root)
    env["CAR_RENTAL_DB_RESET"] = "1"
    env["CAR_RENTAL_DATA_DIR"] = str(test_data)
    env["CAR_RENTAL_SQLITE_URL"] = f"sqlite:///{test_data / 'car_rental_local.db'}"
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    result = subprocess.run(
        [sys.executable, str(project_root / "tests" / "e2e_startup_check.py")],
        capture_output=True, text=True, timeout=120, env=env,
    )
    assert "E2E STARTUP TEST PASS" in result.stdout, (
        f"stdout:\n{result.stdout[-2000:]}\nstderr:\n{result.stderr[-2000:]}"
    )
