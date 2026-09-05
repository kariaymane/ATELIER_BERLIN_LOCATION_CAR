"""SECURITY REGRESSION GUARD — no real credentials may enter the repository.

WHY THIS EXISTS
---------------
A live production password was committed and reached the PUBLIC GitHub remote,
where it sat for three days before the pre-push audit found it. Nothing in the
build could see it. This test makes that class of mistake a red build.

DESIGN CONSTRAINTS
------------------
* It must NOT contain the compromised value (that would re-commit the secret).
  Instead it detects the SHAPE of a real credential.
* It scans exactly what a push would publish: ``git ls-files`` (tracked files).
  Untracked, gitignored files such as ``.env`` are correctly out of scope.
* Synthetic credentials are allowed and are recognised by their domain, so a
  test may keep readable fixtures without weakening the guard.

WHAT COUNTS AS SYNTHETIC
------------------------
An email whose domain is in ``SYNTHETIC_DOMAINS`` (RFC 2606 reserved names plus
this project's local fixtures). A real address — gmail.com, a company domain —
sitting next to a password literal is what got us here, and it fails.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# RFC 2606 reserved + this project's established local fixture domains.
SYNTHETIC_DOMAINS = {
    "example.com", "example.org", "example.net", "example.test", "example.local",
    "test.com", "test.local", "test.test", "int.local", "rec.local",
    "localhost", "invalid", "nowhere.local",
}

SKIP_SUFFIXES = {
    ".apk", ".exe", ".zip", ".jks", ".keystore", ".png", ".jpg", ".jpeg", ".gif",
    ".ico", ".webp", ".pdf", ".ttf", ".otf", ".so", ".dll", ".jar", ".dex",
    ".pyc", ".class", ".bin", ".lock",
}
SKIP_PARTS = {"venv", "node_modules", "build", "dist", ".gradle", "__pycache__",
              "venv_wine", "artifacts_archive"}

# This guard itself necessarily contains credential-shaped regexes.
SELF = "backend/tests/test_no_hardcoded_secrets.py"

EMAIL_PW_PAIR = re.compile(
    r'["\']?email["\']?\s*[:=]\s*["\']([^"\']+@[^"\']+)["\']'
    r'[^\n]{0,80}?'
    r'["\']?pass(?:word|wd)?["\']?\s*[:=]\s*["\']([^"\']{4,})["\']',
    re.I,
)
# A DB URL carrying an inline password that is NOT a ${VAR} / $VAR placeholder.
# Group 1 = password, group 2 = host.
DB_URL_INLINE_PW = re.compile(
    r'(?:postgres(?:ql)?|mysql|mongodb)(?:\+\w+)?://[^:\s"\'/]+:'
    r'(?!\$\{)(?!\$[A-Za-z_])([^@\s"\']{3,})@([^:/\s"\']+)',
    re.I,
)
# A credential that only reaches loopback is not a publishable secret: the
# ephemeral PostgreSQL service container in GitHub Actions lives and dies inside
# the runner and is unreachable from anywhere else. Real hosts are not exempt.
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "db", "postgres"}
HARD_TOKENS = [
    ("AWS access key id", re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
    ("GitHub token", re.compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}\b')),
    ("Fly.io token", re.compile(r'\bFlyV1\s+[A-Za-z0-9_\-]{20,}')),
    ("private key block", re.compile(r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----')),
    ("hardcoded bearer JWT", re.compile(r'["\']Bearer\s+eyJ[A-Za-z0-9_\-]{10,}')),
]

# Placeholder values that are self-evidently not secrets.
PLACEHOLDER = re.compile(
    r'^(?:\$\{.*\}|\$[A-Za-z_]\w*|<[^>]*>|\*+|x+|X+|CHANGE_ME\w*|REDACTED|redacted|'
    r'dummy[\w\-]*|placeholder\w*|your[_\-]?\w*|example\w*|TODO\w*|none|null)$', re.I)


def _tracked_files() -> list[Path]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    files = []
    for rel in out:
        rel = rel.strip()
        if not rel or rel == SELF:
            continue
        p = ROOT / rel
        if not p.is_file():
            continue
        if p.suffix.lower() in SKIP_SUFFIXES:
            continue
        if any(part in SKIP_PARTS for part in p.parts):
            continue
        try:
            if p.stat().st_size > 2_000_000:
                continue
        except OSError:
            continue
        files.append(p)
    return files


def _read(p: Path) -> str:
    try:
        return p.read_text(errors="ignore")
    except Exception:
        return ""


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def test_no_real_credentials_in_tracked_files():
    """An email at a REAL domain next to a password literal fails the build."""
    findings: list[str] = []
    for p in _tracked_files():
        for ln, line in enumerate(_read(p).splitlines(), 1):
            if len(line) > 4000:
                continue
            m = EMAIL_PW_PAIR.search(line)
            if not m:
                continue
            email, pw = m.group(1), m.group(2)
            if PLACEHOLDER.match(pw.strip()) or PLACEHOLDER.match(email.strip()):
                continue
            domain = email.rsplit("@", 1)[-1].strip().lower()
            if domain in SYNTHETIC_DOMAINS:
                continue
            # Report location + domain only. NEVER the password.
            findings.append(f"{_rel(p)}:{ln} — credential literal for a real domain "
                            f"'{domain}' ({len(pw)}-char password)")
    assert not findings, (
        "HARDCODED PRODUCTION CREDENTIAL DETECTED — do not commit this.\n"
        "Use environment variables (see scripts/reconcile_data.py::_credentials) or a\n"
        "synthetic address at one of: " + ", ".join(sorted(SYNTHETIC_DOMAINS)) + "\n\n"
        + "\n".join("  " + f for f in findings)
    )


def test_no_inline_database_credentials_in_tracked_files():
    """A DB URL must interpolate its password, never inline it."""
    findings = []
    for p in _tracked_files():
        for ln, line in enumerate(_read(p).splitlines(), 1):
            if len(line) > 4000:
                continue
            m = DB_URL_INLINE_PW.search(line)
            if not m:
                continue
            pw, host = m.group(1), m.group(2).lower()
            if PLACEHOLDER.match(pw.strip()):
                continue
            if host in LOOPBACK_HOSTS:
                continue  # ephemeral CI / compose-internal service, not reachable
            findings.append(f"{_rel(p)}:{ln} — inline DB password ({len(pw)} chars) "
                            f"for reachable host '{host}'")
    assert not findings, (
        "INLINE DATABASE CREDENTIAL DETECTED — use ${VAR} interpolation.\n"
        + "\n".join("  " + f for f in findings)
    )


@pytest.mark.parametrize("label,rx", HARD_TOKENS, ids=[t[0] for t in HARD_TOKENS])
def test_no_provider_tokens_or_private_keys(label, rx):
    """Cloud tokens and private keys must never be tracked."""
    findings = []
    for p in _tracked_files():
        for ln, line in enumerate(_read(p).splitlines(), 1):
            if len(line) > 4000:
                continue
            if rx.search(line):
                findings.append(f"{_rel(p)}:{ln}")
    assert not findings, f"{label} committed to the repository:\n" + "\n".join(
        "  " + f for f in findings)


def test_env_files_are_never_tracked():
    """`.env` holds real secrets; it must stay out of git entirely."""
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                             capture_output=True, text=True, check=True).stdout.split("\n")
    leaked = [f for f in (x.strip() for x in tracked)
              if f and (Path(f).name == ".env" or Path(f).name.startswith(".env."))
              and not f.endswith(".example")]
    assert not leaked, "environment files are tracked by git:\n" + "\n".join(
        "  " + f for f in leaked)


def test_guard_actually_detects_a_planted_credential(tmp_path):
    """The guard must be able to fail. A guard that cannot fail is decoration."""
    planted = 'payload = {"email": "owner@realcompany.com", "password": "s3cr3t-value"}'
    m = EMAIL_PW_PAIR.search(planted)
    assert m is not None, "EMAIL_PW_PAIR failed to match a planted real credential"
    assert m.group(1).rsplit("@", 1)[-1] not in SYNTHETIC_DOMAINS

    # ...and must NOT fire on a synthetic fixture.
    benign = 'payload = {"email": "operator@example.test", "password": "dummy-password"}'
    mb = EMAIL_PW_PAIR.search(benign)
    assert mb is not None
    assert mb.group(1).rsplit("@", 1)[-1] in SYNTHETIC_DOMAINS, \
        "synthetic fixture domain must be allow-listed, or every test will fail"

    # ...and inline DB credentials on a REACHABLE host are caught, while the
    # ${VAR} form and loopback-only CI services are not.
    m_db = DB_URL_INLINE_PW.search("postgresql://user:realpw@db.example.com:5432/x")
    assert m_db and m_db.group(2).lower() not in LOOPBACK_HOSTS
    assert not DB_URL_INLINE_PW.search("postgresql://${USER}:${PASSWORD}@host:5432/db")
    m_ci = DB_URL_INLINE_PW.search("postgresql+asyncpg://ci:ci_pw_value@localhost:5432/x")
    assert m_ci and m_ci.group(2).lower() in LOOPBACK_HOSTS, \
        "loopback CI services must stay exempt or every CI run fails"
