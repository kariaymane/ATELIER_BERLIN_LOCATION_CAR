"""
Guard: the revenue / dashboard / auth hot paths must derive time from the ONE
contract (shared.money_time.now_business / datetime.now(tz)), never a naive
`datetime.now()` / `datetime.utcnow()`.

A bare naive now is what produced the recurring "can't subtract offset-naive
and offset-aware datetime" 500s (FORENSIC_ROOT_CAUSE_ANALYSIS.md §7). This
test fails the build the moment one reappears in a guarded module.
"""
import pathlib
import re

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1] / "app"

# Modules where a naive clock is a correctness bug.
GUARDED = [
    "services/revenue_service.py",
    "services/dashboard_service.py",
    "repositories/rental_repository.py",
    "services/fleet_status.py",
    "services/auth_service.py",
]

_NAIVE_NOW = re.compile(r"datetime\.now\(\s*\)|datetime\.utcnow\(\s*\)")


@pytest.mark.parametrize("rel", GUARDED)
def test_no_naive_now_in_guarded_module(rel):
    path = _BACKEND / rel
    src = path.read_text()
    hits = [
        f"{rel}:{i}: {line.strip()}"
        for i, line in enumerate(src.splitlines(), 1)
        if _NAIVE_NOW.search(line) and not line.lstrip().startswith("#")
    ]
    assert not hits, "naive datetime.now()/utcnow() found:\n" + "\n".join(hits)


def test_shared_money_time_is_the_contract():
    from shared.money_time import now_business, BUSINESS_TZ

    n = now_business()
    assert n.tzinfo is not None
    assert "Casablanca" in str(BUSINESS_TZ)
