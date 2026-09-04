"""
DomainStore — the ONE canonical in-memory projection of the desktop's offline
domain state (vehicles, reservations, maintenance) above local SQLite.

WHY THIS EXISTS (Increment 2 of the 100%-live program)
------------------------------------------------------
Before: every view opened its own SQLite session, ran its own query, derived
its own idea of "fleet status", and was refreshed by an argument-less
``data_refreshed`` pulse that MainWindow fanned out by hand. A missed or
throwing callback left a tab silently stale; two views could disagree.

Now: exactly one component (this one) holds the authoritative in-memory
snapshot. It is rebuilt atomically from a single SQLite read, carries a
monotonic ``revision``, and is published to every subscriber with per-subscriber
exception isolation. Views render *from the snapshot*; they do not invent a
competing global state.

CONTRACT
--------
* ``get_domain_store()``            -> process-wide singleton
* ``store.snapshot``               -> current immutable DomainSnapshot
* ``store.revision``               -> monotonic int (0 before the first reload)
* ``store.subscribe(cb) -> unsub``  -> cb(snapshot, revision); called on every
                                      reload; one raising subscriber never
                                      blocks the others and never propagates
* ``store.reload()``               -> rebuild snapshot from SQLite, bump
                                      revision, notify subscribers
* ``store.mutate(fn)``             -> run fn(session) inside ONE transaction;
                                      on commit -> reload(); on error ->
                                      rollback and re-raise, NO reload,
                                      NO revision bump, NO notification
* ``store.snapshot.next_boundary`` -> earliest FUTURE instant (aware UTC) at
                                      which some vehicle's effective status can
                                      change with no user action, or None
* ``store.recompute_effective(now)`` -> re-derive effective status / fleet
                                      counts for the CURRENT rows against
                                      ``now`` (NO SQLite read, NO network).
                                      Publishes a new revision ONLY if the
                                      canonical state actually changed;
                                      otherwise a no-op. Returns True/False.
                                      This is the temporal-transition path
                                      driven by ``BoundaryClock`` (Increment 3).

The effective-status derivation is delegated to ``app.utils.fleet_status``
(the Increment-1 canonical spec) — this module never re-implements it. The
session build and the in-memory temporal recompute call the SAME pure core
(`compute_fleet_sets_rows` / `effective_statuses_rows`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)

Subscriber = Callable[["DomainSnapshot", int], None]


@dataclass(frozen=True)
class DomainSnapshot:
    """An immutable point-in-time projection of the local domain.

    ``vehicles`` dicts carry ``status`` = the canonical *effective* status
    (SOLD/INACTIVE/MAINTENANCE/RENTED/RESERVED/AVAILABLE) and ``raw_status`` =
    the persisted column, so no consumer needs to re-derive anything.
    """
    revision: int = 0
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    vehicles: tuple = ()
    reservations: tuple = ()
    maintenances: tuple = ()
    clients: tuple = ()
    effective: dict = field(default_factory=dict)      # vehicle_id -> effective status
    fleet_counts: dict = field(default_factory=dict)   # canonical mutually-exclusive buckets
    overview: dict = field(default_factory=dict)       # dashboard overview (compute_local_overview)
    top_vehicles: tuple = ()                           # "Top 5 les plus loués" (canonical, offline)
    next_boundary: Optional[datetime] = None           # earliest future time-driven transition
    is_live: bool = False                              # True when overview reflects authoritative server data
    server_timestamp: Optional[datetime] = None        # timestamp of server response

    def vehicle(self, vehicle_id: str) -> Optional[dict]:
        for v in self.vehicles:
            if str(v.get("id")) == str(vehicle_id):
                return v
        return None

    def client(self, client_id: str) -> Optional[dict]:
        for c in self.clients:
            if str(c.get("id")) == str(client_id):
                return c
        return None

    def effective_status(self, vehicle_id: str) -> Optional[str]:
        return self.effective.get(str(vehicle_id))

    @property
    def current_reservations(self) -> tuple:
        """Active rentals or reserved bookings (ACTIVE, RESERVED)."""
        return tuple(
            r for r in self.reservations
            if (r.get("status") or "").upper() in ("ACTIVE", "RESERVED")
        )

    @property
    def historical_reservations(self) -> tuple:
        """Completed or cancelled reservations (COMPLETED, CANCELLED)."""
        return tuple(
            r for r in self.reservations
            if (r.get("status") or "").upper() in ("COMPLETED", "CANCELLED")
        )


_EMPTY = DomainSnapshot()


class DomainStore:
    _FLEET_KEYS = ("total_vehicles", "available", "rented", "reserved", "maintenance")

    def __init__(self, now_fn: Optional[Callable[[], datetime]] = None) -> None:
        self._snapshot: DomainSnapshot = _EMPTY
        self._revision: int = 0
        self._subscribers: list[Subscriber] = []
        self._reloading: bool = False
        # Authoritative server dashboard state (Server Authority Invariant)
        self._server_overview: Optional[dict] = None
        self._server_top_vehicles: Optional[list] = None
        self._server_generation: int = 0
        self._server_timestamp: Optional[datetime] = None
        # Injectable clock source — the SAME one the BoundaryClock uses, so a
        # temporal recompute at `now` is consistent with the snapshot built at
        # `now`. Defaults to the real wall clock.
        self._now_fn: Callable[[], datetime] = now_fn or (lambda: datetime.now(timezone.utc))

    def set_now_fn(self, now_fn: Callable[[], datetime]) -> None:
        self._now_fn = now_fn

    def now(self) -> datetime:
        return self._now_fn()

    # ── server authority methods ─────────────────────────────────────────
    def update_server_dashboard(self, overview: dict, top_vehicles: Optional[list] = None, generation: int = 0) -> DomainSnapshot:
        """Apply authoritative live server dashboard data to the DomainStore.

        Server overview may provide server metrics that are not locally derivable (e.g. revenue).
        BUT fleet state metrics MUST be derived from the canonical fleet-state computation
        using the current synchronized vehicle/reservation/maintenance snapshot.
        Reconcile fleet keys immediately against canonical local state after fetch.
        """
        if self._server_generation > 0 and generation < self._server_generation:
            logger.info("DomainStore: Dropping stale server dashboard update gen %s (current %s)",
                        generation, self._server_generation)
            return self._snapshot

        if self._snapshot is _EMPTY:
            from app.database import get_local_session
            sess = get_local_session()
            try:
                self._snapshot = self._build_snapshot(sess, self._revision, self.now())
            finally:
                sess.close()

        ov = dict(overview)
        # Immediately reconcile fleet keys against canonical local fleet counts
        if self._snapshot is not _EMPTY and self._snapshot.fleet_counts:
            for k in self._FLEET_KEYS:
                if k in self._snapshot.fleet_counts:
                    ov[k] = self._snapshot.fleet_counts[k]

        self._server_overview = ov
        if top_vehicles is not None:
            self._server_top_vehicles = list(top_vehicles)
        self._server_generation = max(self._server_generation, generation)
        self._server_timestamp = self.now()

        # Update current snapshot with server authoritative metrics
        if self._snapshot is not _EMPTY:
            self._snapshot = DomainSnapshot(
                revision=self._revision,
                generated_at=self._snapshot.generated_at,
                vehicles=self._snapshot.vehicles,
                reservations=self._snapshot.reservations,
                maintenances=self._snapshot.maintenances,
                clients=self._snapshot.clients,
                effective=self._snapshot.effective,
                fleet_counts=self._snapshot.fleet_counts,
                overview=dict(self._server_overview),
                top_vehicles=tuple(self._server_top_vehicles or self._snapshot.top_vehicles),
                next_boundary=self._snapshot.next_boundary,
                is_live=True,
                server_timestamp=self._server_timestamp,
            )
        return self._snapshot

    def clear_server_dashboard(self) -> None:
        """Clear authoritative server dashboard state (used on explicit logout/disconnect)."""
        self._server_overview = None
        self._server_top_vehicles = None
        self._server_generation = 0
        self._server_timestamp = None

    # ── read side ────────────────────────────────────────────────────────
    @property
    def snapshot(self) -> DomainSnapshot:
        return self._snapshot

    @property
    def revision(self) -> int:
        return self._revision

    # ── subscription ────────────────────────────────────────────────────
    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        """Register a callback invoked as ``callback(snapshot, revision)`` on
        every reload. Returns a zero-arg unsubscribe function."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

        def _unsub() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return _unsub

    def _notify(self) -> None:
        snap, rev = self._snapshot, self._revision
        for cb in list(self._subscribers):
            try:
                cb(snap, rev)
            except Exception:  # one bad subscriber must not stop the rest
                logger.error("DomainStore subscriber %r failed at revision %s",
                             getattr(cb, "__qualname__", cb), rev, exc_info=True)

    # ── write / refresh side ────────────────────────────────────────────
    def reload(self, session=None) -> DomainSnapshot:
        """Rebuild the snapshot from SQLite, bump the revision, notify.

        Re-entrancy safe: a subscriber that itself triggers a reload is
        ignored (the outer reload already reflects committed state)."""
        if self._reloading:
            # A subscriber (or a view entrypoint it calls) asked for another
            # reload while we are already publishing — the snapshot in flight
            # already reflects committed state, so this is a no-op.
            return self._snapshot
        self._reloading = True
        try:
            own = session is None
            if own:
                from app.database import get_local_session
                session = get_local_session()
            try:
                snap = self._build_snapshot(session, self._revision + 1, self.now())
                if not self._validate_snapshot(snap):
                    logger.error("DomainStore: snapshot validation failed at revision %s, keeping previous valid state (revision %s)",
                                 snap.revision, self._revision)
                    return self._snapshot
            finally:
                if own:
                    session.close()
            self._snapshot = snap
            self._revision = snap.revision
            # Notify while still marked reloading so re-entrant reload() calls
            # from subscribers collapse to a no-op instead of recursing.
            self._notify()
        finally:
            self._reloading = False
        return self._snapshot

    @staticmethod
    def _validate_snapshot(snap: DomainSnapshot) -> bool:
        """Validate critical snapshot invariants before publishing to UI.
        Guarantees that no corrupted or physically impossible state is published.
        """
        try:
            fc = snap.fleet_counts or {}
            for k in ("total_vehicles", "available", "rented", "reserved", "maintenance"):
                val = fc.get(k, 0)
                if val < 0:
                    logger.error("Snapshot validation failed: negative count for %s = %s", k, val)
                    return False

            ov = snap.overview or {}
            for k in ("today_revenue", "week_revenue", "month_revenue", "year_revenue"):
                val = ov.get(k)
                if val is not None and (not isinstance(val, (int, float)) or val < 0):
                    logger.error("Snapshot validation failed: invalid revenue %s = %s", k, val)
                    return False
            return True
        except Exception as e:
            logger.error("Snapshot validation encountered error: %s", e)
            return False

    def mutate(self, fn: Callable[[object], None]) -> DomainSnapshot:
        """Run ``fn(session)`` inside a single SQLite transaction.

        On success: commit, then reload() (bump revision + notify).
        On any exception: rollback, re-raise, and DO NOT reload — no false
        'state changed' signal is ever emitted for a failed mutation.
        """
        from app.database import get_local_session
        session = get_local_session()
        try:
            fn(session)
            session.commit()
        except Exception:
            session.rollback()
            session.close()
            raise
        # commit succeeded — publish the new state from a fresh read
        try:
            self.reload()
        finally:
            session.close()
        return self._snapshot

    # ── snapshot construction (single canonical derivation) ─────────────
    def _build_snapshot(self, session, revision: int, now: Optional[datetime] = None) -> DomainSnapshot:
        from app.models.vehicle import LocalVehicle
        from app.models.reservation import LocalReservation
        from app.models.maintenance import LocalMaintenance
        from app.models.client import LocalClient
        now = now or datetime.now(timezone.utc)
        vehicles = session.query(LocalVehicle).all()
        reservations = session.query(LocalReservation).all()
        maintenances = session.query(LocalMaintenance).all()
        clients = session.query(LocalClient).order_by(LocalClient.last_name).all()

        # 1. Establish the real vehicle ID set first
        valid_vids_raw = {v.id for v in vehicles if v.id is not None}
        valid_vids_str = {str(v.id) for v in vehicles if v.id is not None}

        # 2. Filter reservations and maintenances against real vehicle IDs
        valid_reservations = [
            r for r in reservations
            if r.vehicle_id in valid_vids_raw or str(r.vehicle_id) in valid_vids_str
        ]
        valid_maintenances = [
            m for m in maintenances
            if m.vehicle_id in valid_vids_raw or str(m.vehicle_id) in valid_vids_str
        ]

        # 3. Fleet count and effective status calculation MUST use the filtered reservation/maintenance data
        from app.utils.fleet_status import (
            compute_fleet_sets_rows, effective_status as _eff, compute_fleet_counts_rows,
        )

        rented_vids, reserved_vids, maint_vids, _total = compute_fleet_sets_rows(
            vehicles, valid_reservations, valid_maintenances, now=now
        )
        fleet_counts = compute_fleet_counts_rows(
            vehicles, valid_reservations, valid_maintenances, now=now
        )

        vehicle_dicts: list[dict] = []
        effective: dict[str, str] = {}
        for v in vehicles:
            try:
                images_list = [img.image_url for img in v.images] if hasattr(v, "images") else []
            except Exception as e:
                images_list = []
                logger.warning("DomainStore: could not load images for vehicle %s: %s",
                               getattr(v, "id", "?"), e)
            eff = _eff(v.status, v.id, rented_vids, reserved_vids, maint_vids)
            effective[str(v.id)] = eff
            vehicle_dicts.append({
                "id": v.id,
                "registration": v.registration,
                "vin": v.vin,
                "brand": v.brand,
                "model": v.model,
                "year": v.year,
                "color": v.color,
                "fuel_type": v.fuel_type,
                "transmission": v.transmission,
                "current_mileage": v.current_mileage,
                "purchase_mileage": v.purchase_mileage,
                "purchase_price": v.purchase_price,
                "daily_rental_price": v.daily_rental_price,
                "status": eff,              # canonical EFFECTIVE status
                "raw_status": v.status,     # persisted structural column
                "image_url": v.image_url,
                "images": images_list,
                "assurance_expiry": v.assurance_expiry,
                "vignette_expiry": v.vignette_expiry,
                "visite_technique_expiry": v.visite_technique_expiry,
                "carte_grise_expiry": v.carte_grise_expiry,
                "autres_label": v.autres_label,
                "autres_expiry": v.autres_expiry,
                "notes": v.notes,
                "created_at": getattr(v, "created_at", None),
            })

        def _res_dict(r) -> dict:
            return {
                "id": r.id, "vehicle_id": r.vehicle_id,
                "customer_id": getattr(r, "customer_id", None),
                "customer_name": r.customer_name,
                "customer_phone": getattr(r, "customer_phone", None),
                "customer_email": getattr(r, "customer_email", None),
                "start_datetime": r.start_datetime, "end_datetime": r.end_datetime,
                "daily_price": r.daily_price, "num_days": r.num_days,
                "total_price": r.total_price, "deposit": r.deposit,
                "payment_status": r.payment_status, "status": r.status,
                "cancellation_reason": getattr(r, "cancellation_reason", None),
                "cancelled_at": getattr(r, "cancelled_at", None),
                "notes": r.notes, "created_at": r.created_at, "updated_at": r.updated_at,
                "version": r.version,
            }

        def _maint_dict(m) -> dict:
            return {
                "id": m.id, "vehicle_id": m.vehicle_id, "type": m.type,
                "title": m.title, "description": m.description,
                "start_datetime": m.start_datetime,
                "expected_end_datetime": m.expected_end_datetime,
                "actual_end_datetime": m.actual_end_datetime,
                "status": m.status, "step": m.step,
                "estimated_cost": m.estimated_cost, "actual_cost": m.actual_cost,
                "parts_cost": m.parts_cost, "labor_cost": m.labor_cost,
                "other_cost": m.other_cost,
                "created_at": m.created_at, "updated_at": m.updated_at,
                "version": m.version,
            }

        def _client_dict(c) -> dict:
            return {
                "id": str(c.id),
                "first_name": c.first_name or "",
                "last_name": c.last_name or "",
                "phone": c.phone or "",
                "email": c.email or "",
                "cin_number": getattr(c, "cin_number", "") or "",
                "license_number": getattr(c, "license_number", "") or "",
                "status": getattr(c, "status", "ACTIVE"),
                "photo_url": getattr(c, "photo_url", None),
                "identity_card_image": getattr(c, "identity_card_image", None),
                "identity_card_image_back": getattr(c, "identity_card_image_back", None),
                "driving_license_image": getattr(c, "driving_license_image", None),
                "driving_license_image_back": getattr(c, "driving_license_image_back", None),
                "notes": getattr(c, "notes", None),
                "version": getattr(c, "version", 1),
                "created_at": getattr(c, "created_at", None),
                "updated_at": getattr(c, "updated_at", None),
            }

        res_dicts = tuple(
            sorted(
                (_res_dict(r) for r in valid_reservations),
                key=lambda x: (x.get("start_datetime") or "", x.get("created_at") or "", x.get("id") or ""),
                reverse=True,
            )
        )
        maint_dicts = tuple(_maint_dict(m) for m in valid_maintenances)
        client_dicts = tuple(_client_dict(c) for c in clients)

        if self._server_overview is not None:
            # Server overview provides server-authoritative metrics (e.g. revenue),
            # but fleet state metrics MUST reflect canonical local fleet counts.
            for k in self._FLEET_KEYS:
                if k in fleet_counts:
                    self._server_overview[k] = fleet_counts[k]
            overview = dict(self._server_overview)
            top_vehicles = tuple(self._server_top_vehicles or ())
            is_live = True
        else:
            try:
                from app.sync.dashboard_cache import compute_overview_rows, compute_top_vehicles_rows
                overview = compute_overview_rows(res_dicts, fleet_counts, maintenances=maint_dicts, now=now)
                top_vehicles = tuple(
                    compute_top_vehicles_rows(res_dicts, vehicle_dicts, now=now, limit=5)
                )
            except Exception as e:
                logger.error("DomainStore: local overview computation failed: %s", e, exc_info=True)
                overview = dict(fleet_counts)
                top_vehicles = ()
            is_live = False

        from app.utils.fleet_status import next_boundary_rows
        # include local midnight so the dashboard period (today/week/month)
        # cards roll over automatically at 00:00 Africa/Casablanca.
        nb = next_boundary_rows(res_dicts, maint_dicts, now, include_midnight=True)

        return DomainSnapshot(
            revision=revision,
            generated_at=now,
            vehicles=tuple(vehicle_dicts),
            reservations=res_dicts,
            maintenances=maint_dicts,
            clients=client_dicts,
            effective=effective,
            fleet_counts=fleet_counts,
            overview=overview,
            top_vehicles=top_vehicles,
            next_boundary=nb,
            is_live=is_live,
            server_timestamp=self._server_timestamp,
        )

    # ── temporal recompute (NO SQLite, NO network) ─────────────────────────
    _FLEET_KEYS = ("total_vehicles", "available", "rented", "reserved", "maintenance")

    def recompute_effective(self, now: Optional[datetime] = None) -> bool:
        """Re-derive effective status + fleet counts for the CURRENT snapshot
        rows against ``now``. Publishes a new revision ONLY when the canonical
        state actually changed; a boundary that changes nothing is a silent
        no-op (no revision bump, no notification). Returns whether it published.
        """
        if self._reloading:
            return False
        from app.utils.fleet_status import (
            effective_statuses_rows, compute_fleet_counts_rows, next_boundary_rows,
        )
        from app.sync.dashboard_cache import compute_overview_rows
        now = now or self.now()
        base = self._snapshot

        vehicles_raw = [{"id": v["id"], "status": v.get("raw_status")} for v in base.vehicles]
        new_effective = effective_statuses_rows(
            vehicles_raw, list(base.reservations), list(base.maintenances), now)
        new_counts = compute_fleet_counts_rows(
            vehicles_raw, list(base.reservations), list(base.maintenances), now)
        new_boundary = next_boundary_rows(
            list(base.reservations), list(base.maintenances), now, include_midnight=True)
        try:
            new_overview = compute_overview_rows(list(base.reservations), new_counts, maintenances=list(base.maintenances), now=now)
        except Exception:
            new_overview = dict(base.overview or {})

        if self._server_overview is not None:
            # Time has advanced across a boundary while holding server metrics.
            # Evolve the authoritative fleet counts to match current wall-clock
            # reality, so the Dashboard and Vehicles pages stay strictly coherent.
            for k in self._FLEET_KEYS:
                if k in new_counts:
                    self._server_overview[k] = new_counts[k]
            # A calendar-date change can roll ANY period boundary (day / week /
            # month / year). The server's figure for a rolled period is now
            # stale, so adopt the local time-derived recompute for every period
            # card until the next server fetch. Same pro-rata engine as the
            # backend, so this is the canonical number, not a guess.
            prev_d = base.generated_at.date() if base.generated_at else None
            if prev_d is not None and now.date() != prev_d:
                for _p in ("today", "week", "month", "year"):
                    for _suffix in ("_revenue", "_rentals"):
                        _k = _p + _suffix
                        if _k in new_overview:
                            self._server_overview[_k] = new_overview[_k]
                if "today_returns" in new_overview:
                    self._server_overview["today_returns"] = new_overview["today_returns"]
            effective_overview = dict(self._server_overview)
        else:
            effective_overview = new_overview

        changed = (
            new_effective != base.effective
            or new_counts != base.fleet_counts
            or effective_overview != base.overview
            or new_overview != base.overview
        )
        if not changed:
            return False  # boundary reached but nothing changed — silent no-op

        self._reloading = True
        try:
            new_vehicles = tuple(
                {**v, "status": new_effective.get(str(v["id"]), v["status"])}
                for v in base.vehicles
            )

            self._revision += 1
            self._snapshot = DomainSnapshot(
                revision=self._revision,
                generated_at=now,
                vehicles=new_vehicles,
                reservations=base.reservations,
                maintenances=base.maintenances,
                clients=base.clients,
                effective=new_effective,
                fleet_counts=new_counts,
                overview=effective_overview,
                top_vehicles=tuple(self._server_top_vehicles) if self._server_top_vehicles is not None else base.top_vehicles,
                next_boundary=new_boundary,
                is_live=self._server_overview is not None,
                server_timestamp=self._server_timestamp,
            )
            self._notify()
        finally:
            self._reloading = False
        return True


# ── process-wide singleton ─────────────────────────────────────────────
_STORE: Optional[DomainStore] = None


def get_domain_store() -> DomainStore:
    global _STORE
    if _STORE is None:
        _STORE = DomainStore()
    return _STORE


def reset_domain_store(now_fn: Optional[Callable[[], datetime]] = None) -> DomainStore:
    """Test helper — drop the singleton and its subscribers."""
    global _STORE
    _STORE = DomainStore(now_fn=now_fn)
    return _STORE
