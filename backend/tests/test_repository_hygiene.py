"""Guard public source boundaries without excluding legitimate engineering files."""
from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def tracked_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        check=True, capture_output=True,
    )
    return [Path(p.decode()) for p in result.stdout.split(b"\0") if p]


def test_no_runtime_backups_or_installers_in_source():
    suffixes = {".apk", ".aab", ".exe", ".msi", ".dump", ".backup", ".bak",
                ".old", ".tmp", ".log", ".db", ".sqlite", ".sqlite3"}
    runtime_dirs = {"uploads", "backups", "artifacts_archive", ".aistudio"}
    findings = [str(p) for p in tracked_paths()
                if p.suffix.lower() in suffixes
                or runtime_dirs.intersection(p.parts)
                or ".before_" in p.name]
    assert not findings, "Private/runtime files are tracked: " + ", ".join(findings)


def test_root_documentation_excludes_internal_work_products():
    patterns = ("*_REPORT*.md", "*_AUDIT*.md", "*_FORENSIC*.md", "*_GATE*.md",
                "*_WALKTHROUGH*.md", "*_ANALYSIS*.md", "PROMPT*.md", "AI_*.md")
    findings = [str(p) for p in tracked_paths() if len(p.parts) == 1
                and any(fnmatch.fnmatch(p.name.upper(), pat.upper()) for pat in patterns)]
    assert not findings, "Internal work products belong outside the repository: " + ", ".join(findings)


def test_environment_templates_have_no_secret_defaults():
    secret_fields = {"POSTGRES_PASSWORD", "JWT_SECRET", "JWT_REFRESH_SECRET", "ADMIN_PASSWORD"}
    for name in ("backend/.env.example", "docker/.env.example"):
        for line in (ROOT / name).read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key in secret_fields:
                assert not value.strip(), f"{name}: {key} must be supplied privately"


@pytest.mark.parametrize("path", [
    ".env", "backend/.env.production", "desktop/app/data/settings.json",
    "docker/fly.toml", "backups/database.sql", "database.dump", "data.backup",
    "temporary.bak", "temporary.old", "temporary.tmp", "server.log",
    "artifacts_archive/release.apk", "mobile/app/release.aab",
    "mobile/local.properties", "desktop/build/application.exe",
])
def test_private_and_generated_paths_are_ignored(path):
    result = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "--no-index", "--quiet", path],
        check=False,
    )
    assert result.returncode == 0, f"Missing ignore rule: {path}"


@pytest.mark.parametrize("path", [
    "backend/.env.example", "desktop/.env.example", "docker/.env.example",
    "docker/postgres/init.sql", "mobile/gradle/wrapper/gradle-wrapper.jar",
    "shared/fleet_status_cases.json", "shared/revenue_cases.json",
])
def test_required_templates_and_fixtures_are_trackable(path):
    result = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "--no-index", "--quiet", path],
        check=False,
    )
    assert result.returncode == 1, f"Required source is ignored: {path}"


def test_public_document_links_resolve():
    for path in (ROOT / "README.md", ROOT / "SECURITY.md", ROOT / "docs/deployment.md"):
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text()):
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            local = target.split("#", 1)[0]
            assert (path.parent / local).exists(), f"Broken link in {path.name}: {local}"


def test_migrations_and_source_are_not_replaced_by_build_output():
    for path in ("backend/app/main.py", "desktop/app/main.py",
                 "mobile/app/src/main/java/com/example/MainActivity.kt",
                 "backend/migrations/env.py", "docker/Dockerfile.backend",
                 "packaging/windows/ATELIER_BERLIN_LOCATION_CAR.spec"):
        assert (ROOT / path).is_file()
    assert list((ROOT / "backend/migrations/versions").glob("*.py"))


def test_dashboard_does_not_reintroduce_a_dedicated_reserved_indicator():
    desktop = (ROOT / "desktop/app/ui/dashboard.py").read_text()
    android = (ROOT / "mobile/app/src/main/java/com/example/ui/screens/DashboardScreen.kt").read_text()
    assert "_card_reserved" not in desktop
    assert "metrics?.reservedVehicles" not in android
    for language in ("fr", "ar"):
        catalog = (ROOT / f"desktop/app/i18n/{language}.json").read_text()
        assert '"reserved_fleet"' not in catalog


def test_login_view_does_not_duplicate_authentication_or_fixture_helpers():
    import ast

    module = ast.parse((ROOT / "desktop/app/ui/login_window.py").read_text())
    view = next(node for node in module.body
                if isinstance(node, ast.ClassDef) and node.name == "LoginWindow")
    methods = {node.name for node in view.body if isinstance(node, ast.FunctionDef)}
    assert not methods.intersection({"_try_local_login", "_cache_credentials", "_cache_credentials_locally"})
