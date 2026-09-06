"""
Dashboard rebuild — the desktop side of the 20 mandated scenarios.

These tests pin the contract the rebuild is built on:

  * every card is rendered from ONE snapshot DTO (no per-card fetch, no
    per-key merge of server and local numbers),
  * a failed fetch shows "—", NEVER a fabricated zero,
  * the four fleet categories are mutually exclusive and reconcile,
  * the local (offline) DTO is computed by the SAME shared spec as the
    backend, so the two runtimes cannot disagree.
"""
import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("CAR_RENTAL_DB_RESET", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.dashboard import DashboardWidget, UNKNOWN  # noqa: E402

TZ = ZoneInfo("Africa/Casablanca")


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def make_dto(**over):
    """A complete, self-consistent snapshot DTO."""
    dto = {
        "schema_version": 2,
        "generated_at": "2026-09-05T14:03:07+01:00",
        "business_timezone": "Africa/Casablanca",
        "currency": "MAD",
        "source": "server",
        "revenue": {
            "amount": 12500.0, "currency": "MAD", "period": "month",
            "period_start": "2026-09-01", "period_end": "2026-10-01",
            "period_end_inclusive": "2026-09-30",
            "period_start_at": "2026-09-01T00:00:00+01:00",
            "period_end_at": "2026-10-01T00:00:00+01:00",
            "rentals": 7, "rental_days": 41,
        },
        "reservations_today": {
            "count": 3, "starting_today": 3, "ending_today": 2,
            "in_progress": 5, "date": "2026-09-05",
        },
        "maintenance": {
            "active_tickets": 2, "open_tickets": 4,
            "vehicles_in_maintenance": 1, "fleet_maintenance_vehicles": 1,
        },
        "vehicles": {
            "total": 10, "ready_to_rent": 4, "active_rental": 3,
            "reserved": 2, "maintenance": 1,
            "excluded_structural": 1, "fleet_size": 11,
        },
        "top_vehicles": [
            {"rank": 1, "vehicle_id": "v1", "registration": "A-1", "brand": "Dacia",
             "model": "Logan", "rental_count": 9, "rental_days": 20, "revenue": 9000.0},
            {"rank": 2, "vehicle_id": "v2", "registration": "B-2", "brand": "Renault",
             "model": "Clio", "rental_count": 4, "rental_days": 8, "revenue": 4000.0},
        ],
        "integrity": {"ok": True, "violations": []},
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(dto.get(k), dict):
            dto[k] = {**dto[k], **v}
        else:
            dto[k] = v
    return dto


# ── ONE snapshot drives every card ───────────────────────────────────────


def test_every_card_comes_from_one_snapshot(qapp):
    w = DashboardWidget()
    w.apply_snapshot(make_dto())

    assert "12 500.00 DH" in w._revenue_value_lbl.full_text()
    assert w._card_day.value_text() == "3"           # réservations du jour
    assert w._card_maintenance.value_text() == "2"   # maintenances en cours
    assert w._card_available.value_text() == "4"     # prêts à louer
    assert w._card_rented.value_text() == "3"        # en location
    assert w._card_fleet_maintenance.value_text() == "1"
    assert [v["registration"] for v in w._top_vehicles_data] == ["A-1", "B-2"]
    w.close()


def test_snapshot_timestamp_comes_from_the_server_not_the_repaint(qapp):
    """§17 — 'Mis à jour à HH:MM:SS' must report when the data was generated."""
    w = DashboardWidget()
    w.apply_snapshot(make_dto(generated_at="2026-09-05T09:15:42+01:00"))
    assert "09:15:42" in w._last_refresh_lbl.text()
    assert "En direct" in w._last_refresh_lbl.text()
    w.close()


def test_fleet_categories_reconcile_line_is_shown(qapp):
    w = DashboardWidget()
    w.apply_snapshot(make_dto())
    text = w._fleet_total_lbl.text()
    assert "8" in text or "10" in text          # total
    for part in ("4", "3", "1"):
        assert part in text
    w.close()


def test_period_selection_does_not_move_the_operational_counters(qapp):
    """§16 — a historical revenue period must not re-scope 'en location'."""
    w = DashboardWidget()
    w.apply_snapshot(make_dto())
    before = (w._card_available.value_text(), w._card_rented.value_text(),
              w._card_fleet_maintenance.value_text(),
              w._card_day.value_text())

    # Same fleet, different revenue window — only the money changes.
    w.apply_snapshot(make_dto(revenue={"period": "last_year", "amount": 0.0,
                                       "period_start": "2025-01-01",
                                       "period_end": "2026-01-01",
                                       "period_end_inclusive": "2025-12-31"}))
    after = (w._card_available.value_text(), w._card_rented.value_text(),
             w._card_fleet_maintenance.value_text(),
             w._card_day.value_text())
    assert before == after
    assert "0.00 DH" in w._revenue_value_lbl.full_text()
    w.close()


# ── §18: an API failure is NEVER a zero ──────────────────────────────────


def test_api_failure_shows_unknown_never_fake_zeroes(qapp):
    w = DashboardWidget()
    w.apply_snapshot(make_dto())          # good data first
    w.apply_unavailable("connection refused")

    for card in (w._card_day, w._card_maintenance, w._card_available,
                 w._card_rented, w._card_fleet_maintenance):
        assert card.value_text() == UNKNOWN, "a failed fetch must not render 0"
        assert card.value_text() != "0"
    assert "0" not in w._revenue_value_lbl.full_text()
    assert not w._banner.isHidden()
    assert "connection refused" in w._banner.text()
    assert "Indisponible" in w._last_refresh_lbl.text()
    w.close()


def test_provider_returning_none_becomes_the_unavailable_state(qapp):
    w = DashboardWidget()
    w.set_snapshot_provider(lambda period, f, t_: None)
    w.request_snapshot()
    w._snapshot_worker.wait(3000)
    qapp.processEvents()
    assert w._card_rented.value_text() == UNKNOWN
    assert not w._banner.isHidden()
    w.close()


def test_provider_raising_becomes_the_unavailable_state(qapp):
    def boom(period, f, t_):
        raise RuntimeError("backend 503")

    w = DashboardWidget()
    w.set_snapshot_provider(boom)
    w.request_snapshot()
    w._snapshot_worker.wait(3000)
    qapp.processEvents()
    assert w._card_available.value_text() == UNKNOWN
    assert "backend 503" in w._banner.text()
    w.close()


def test_a_real_zero_is_still_rendered_as_zero(qapp):
    """An empty but SUCCESSFUL snapshot shows 0 — the point is only that a
    FAILURE must not look like one."""
    w = DashboardWidget()
    w.apply_snapshot(make_dto(
        revenue={"amount": 0.0}, reservations_today={"count": 0},
        maintenance={"active_tickets": 0},
        vehicles={"total": 0, "ready_to_rent": 0, "active_rental": 0,
                  "reserved": 0, "maintenance": 0,
                  "excluded_structural": 0, "fleet_size": 0},
        top_vehicles=[],
    ))
    assert w._card_rented.value_text() == "0"
    assert "0.00 DH" in w._revenue_value_lbl.full_text()
    w.close()


# ── empty states ─────────────────────────────────────────────────────────


def test_empty_top5_shows_a_clean_empty_state(qapp):
    w = DashboardWidget()
    w.apply_snapshot(make_dto(top_vehicles=[]))
    texts = [w._top_layout.itemAt(i).widget().text()
             for i in range(w._top_layout.count())]
    assert any("Aucune location" in x for x in texts)
    w.close()


def test_unavailable_top5_is_not_the_empty_state(qapp):
    """"No rentals yet" and "we could not ask" must not look the same."""
    w = DashboardWidget()
    w.apply_unavailable("timeout")
    texts = [w._top_layout.itemAt(i).widget().text()
             for i in range(w._top_layout.count())]
    assert not any("Aucune location" in x for x in texts)
    assert any("indispon" in x.lower() for x in texts)
    w.close()


# ── offline / integrity signalling ───────────────────────────────────────


def test_local_source_is_labelled_as_cache_not_as_live(qapp):
    w = DashboardWidget()
    w.apply_snapshot(make_dto(source="local"))
    assert "Indisponible" in w._last_refresh_lbl.text() or "Hors ligne / Cache" in w._last_refresh_lbl.text()
    assert not w._banner.isHidden()
    assert w._card_rented.value_text() == "3"   # still shows the numbers
    w.close()


def test_integrity_violation_raises_a_visible_banner(qapp):
    w = DashboardWidget()
    w.apply_snapshot(make_dto(integrity={
        "ok": False, "violations": ["fleet does not reconcile: 9 != 10"]}))
    assert not w._banner.isHidden()
    assert "reconcile" in w._banner.text()
    w.close()


# ── request plumbing ─────────────────────────────────────────────────────


def test_period_change_requests_exactly_one_snapshot_with_the_right_range(qapp):
    calls = []

    def provider(period, f, t_):
        calls.append((period, f, t_))
        return make_dto(revenue={"period": period})

    w = DashboardWidget()
    w.set_snapshot_provider(provider)
    names = [w._period_combo.itemData(i) for i in range(w._period_combo.count())]
    assert names == ["today", "yesterday", "week", "last_week", "month",
                     "last_month", "year", "last_year", "custom"]

    today = datetime.now(TZ).date()
    w._period_combo.setCurrentIndex(names.index("today"))
    w._snapshot_worker.wait(3000)
    qapp.processEvents()
    assert calls[-1] == ("today", today, today)
    assert len(calls) == 1, "a period change must fetch ONE snapshot, not one per card"

    w._period_combo.setCurrentIndex(names.index("last_month"))
    w._snapshot_worker.wait(3000)
    qapp.processEvents()
    period, f, t_ = calls[-1]
    assert period == "last_month"
    assert f.day == 1 and (t_ + timedelta(days=1)).day == 1
    w.close()


def test_custom_range_passes_the_inclusive_end_date(qapp):
    calls = []

    def provider(period, f, t_):
        calls.append((period, f, t_))
        return make_dto()

    w = DashboardWidget()
    w.set_snapshot_provider(provider)
    names = [w._period_combo.itemData(i) for i in range(w._period_combo.count())]
    w._period_combo.setCurrentIndex(names.index("custom"))
    assert w._custom_row.isHidden() is False

    from PySide6.QtCore import QDate
    w._date_from.setDate(QDate(2026, 3, 1))
    w._snapshot_worker.wait(3000)
    w._date_to.setDate(QDate(2026, 3, 15))
    w._snapshot_worker.wait(3000)
    qapp.processEvents()
    assert calls[-1] == ("custom", date(2026, 3, 1), date(2026, 3, 15))
    w.close()


def test_a_superseded_snapshot_reply_is_discarded(qapp):
    w = DashboardWidget()
    w.apply_snapshot(make_dto())
    w._snapshot_req_id = 5
    stale = make_dto(vehicles={"total": 99, "ready_to_rent": 99, "active_rental": 99,
                               "reserved": 0, "maintenance": 0,
                               "excluded_structural": 0, "fleet_size": 198})
    w._on_snapshot_done(stale, "", 4)
    assert w._card_rented.value_text() == "3", "an older reply must not overwrite a newer one"
    w.close()


def test_period_presets_use_the_business_timezone(qapp):
    """The presets must agree with the server's Casablanca day boundaries,
    not with whatever timezone the operator's laptop is set to."""
    from app.ui.dashboard import _business_today
    assert _business_today() == datetime.now(TZ).date()


# ── local DTO == backend DTO (cross-runtime) ─────────────────────────────


class _Snap:
    def __init__(self, vehicles, reservations, maintenances):
        self.vehicles = tuple(vehicles)
        self.reservations = tuple(reservations)
        self.maintenances = tuple(maintenances)


def test_local_snapshot_uses_the_persisted_status_not_the_derived_one(qapp):
    """A DomainStore vehicle dict carries the DERIVED status in ``status``;
    feeding that back into the spec would corrupt the buckets."""
    from app.sync.dashboard_snapshot import build_local_snapshot

    now = datetime(2026, 9, 5, 12, 0, tzinfo=TZ)
    snap = _Snap(
        vehicles=[{"id": "v1", "status": "RENTED", "raw_status": "AVAILABLE",
                   "registration": "A-1", "brand": "Dacia", "model": "Logan"}],
        reservations=[{
            "id": "r1", "vehicle_id": "v1", "status": "RESERVED",
            "cancellation_reason": None, "cancelled_at": None,
            "start_datetime": now - timedelta(days=1),
            "end_datetime": now + timedelta(days=2),
            "num_days": 3, "total_price": 900.0, "daily_price": 300.0,
        }],
        maintenances=[],
    )
    dto = build_local_snapshot(snap, period="month", now=now)
    v = dto["vehicles"]
    assert (v["ready_to_rent"], v["active_rental"], v["maintenance"]) \
        == (0, 1, 0)
    assert v["total"] == 1
    assert dto["source"] == "local"
    assert dto["integrity"]["ok"] is True


def test_local_snapshot_matches_the_shared_spec_exactly(qapp):
    """The desktop port must be the SAME computation as the backend port —
    both are thin wrappers over shared/dashboard_reference.build_snapshot."""
    from app.sync.dashboard_snapshot import build_local_snapshot, rows_from_domain_snapshot
    from shared.dashboard_reference import build_snapshot

    now = datetime(2026, 9, 5, 12, 0, tzinfo=TZ)
    snap = _Snap(
        vehicles=[
            {"id": "v1", "raw_status": "AVAILABLE", "status": "RENTED",
             "registration": "A-1", "brand": "Dacia", "model": "Logan"},
            {"id": "v2", "raw_status": "AVAILABLE", "status": "AVAILABLE",
             "registration": "B-2", "brand": "Renault", "model": "Clio"},
        ],
        reservations=[{
            "id": "r1", "vehicle_id": "v1", "status": "COMPLETED",
            "cancellation_reason": None, "cancelled_at": None,
            "start_datetime": now - timedelta(days=10),
            "end_datetime": now - timedelta(days=8),
            "num_days": 2, "total_price": 600.0, "daily_price": 300.0,
        }],
        maintenances=[],
    )
    vehicles, reservations, maintenances = rows_from_domain_snapshot(snap)
    expected = build_snapshot(vehicles, reservations, maintenances,
                              period="month", now=now, source="local")
    assert build_local_snapshot(snap, period="month", now=now) == expected


def test_maintenance_wins_over_an_in_progress_rental_offline_too(qapp):
    from app.sync.dashboard_snapshot import build_local_snapshot

    now = datetime(2026, 9, 5, 12, 0, tzinfo=TZ)
    snap = _Snap(
        vehicles=[{"id": "v1", "raw_status": "AVAILABLE", "status": "RENTED",
                   "registration": "A-1", "brand": "D", "model": "L"}],
        reservations=[{
            "id": "r1", "vehicle_id": "v1", "status": "ACTIVE",
            "cancellation_reason": None, "cancelled_at": None,
            "start_datetime": now - timedelta(days=1),
            "end_datetime": now + timedelta(days=1),
            "num_days": 2, "total_price": 400.0, "daily_price": 200.0,
        }],
        maintenances=[{
            "id": "m1", "vehicle_id": "v1", "status": "IN_PROGRESS",
            "start_datetime": now - timedelta(hours=2),
            "expected_end_datetime": now + timedelta(days=1),
            "actual_end_datetime": None,
        }],
    )
    v = build_local_snapshot(snap, now=now)["vehicles"]
    assert (v["ready_to_rent"], v["active_rental"], v["maintenance"]) \
        == (0, 0, 1)
