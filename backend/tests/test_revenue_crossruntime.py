"""CROSS-RUNTIME PARITY — backend revenue engine vs the normative spec.

Every case in ``shared/revenue_cases.json`` is materialised as real DB rows and
pushed through ``app.services.revenue_service.revenue_between`` (the ONE engine
behind every dashboard revenue number). Its output must equal
``shared/revenue_reference.py`` for every query — the same file the desktop and
mobile parity tests assert against, so the three runtimes cannot drift.
"""
import json
import pathlib
import sys
import uuid
from datetime import datetime, timedelta

import pytest

from app.models.vehicle import Vehicle
from app.models.reservation import Reservation
from app.services.revenue_service import revenue_between
from shared.money_time import start_of_day, parse_iso_date

_SHARED = pathlib.Path(__file__).resolve().parents[2] / "shared"
sys.path.insert(0, str(_SHARED))
from revenue_reference import revenue_between as ref_revenue  # noqa: E402

_CASES = json.loads((_SHARED / "revenue_cases.json").read_text())


async def _vehicle(db_session) -> Vehicle:
    uid = uuid.uuid4().hex[:6]
    v = Vehicle(
        registration=f"CRT-{uid}", vin=f"WREVCROSS{uid}XX", brand="Test",
        model="Rev", year=2024, color="Blanc", fuel_type="DIESEL",
        transmission="MANUAL", current_mileage=1000,
        daily_rental_price=100.0, status="AVAILABLE",
    )
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)
    return v


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _CASES["revenue_cases"], ids=lambda c: c["name"])
async def test_backend_revenue_matches_reference(case, db_session):
    now = datetime.fromisoformat(case["now"])
    for r in case["reservations"]:
        start = datetime.fromisoformat(r["start_datetime"])
        veh = await _vehicle(db_session)
        db_session.add(Reservation(
            vehicle_id=veh.id,
            customer_name="X",
            start_datetime=start,
            end_datetime=start + timedelta(days=int(r["num_days"])),
            daily_price=r["daily_price"],
            num_days=int(r["num_days"]),
            total_price=r["total_price"],
            deposit=0,
            status=r["status"],
            payment_status="PAID",
        ))
    await db_session.commit()

    for q in case["queries"]:
        s = start_of_day(parse_iso_date(q["from"]))
        e = start_of_day(parse_iso_date(q["to"]))

        result = await revenue_between(db_session, s, e, now=now)

        assert result["revenue"] == pytest.approx(q["expected_revenue"]), (
            f"{case['name']} {q['from']}..{q['to']}: backend {result['revenue']} "
            f"!= expected {q['expected_revenue']}"
        )
        assert result["rental_days"] == q["expected_days"], (
            f"{case['name']} {q['from']}..{q['to']}: days {result['rental_days']} "
            f"!= {q['expected_days']}"
        )
        ref = ref_revenue(case["reservations"], parse_iso_date(q["from"]),
                          parse_iso_date(q["to"]), now)
        assert result["revenue"] == pytest.approx(ref)
