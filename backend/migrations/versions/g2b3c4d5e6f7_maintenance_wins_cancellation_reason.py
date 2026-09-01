"""reservation.cancellation_reason + maintenance wins over reservations

Revision ID: g2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-29 12:00:00.000000

Canonical business rule change
------------------------------
Previously an active maintenance period that overlapped a reservation was
*rejected* (Postgres trigger ``trg_check_overlap_maint`` raised, and the
maintenance API returned HTTP 409). The product rule is now: **maintenance
wins**. When an active maintenance overlaps a reservation for the same vehicle,
the reservation is atomically moved to ``CANCELLED`` with a machine-readable
``cancellation_reason = 'MAINTENANCE'``. The reservation row is preserved for
history/audit — it is never deleted or hidden.

This migration:
  1. adds ``reservations.cancellation_reason`` (nullable, backward compatible);
  2. drops ``trg_check_overlap_maint`` (the maintenance-side rejection) while
     keeping ``trg_check_overlap_res`` (a *new* reservation still may not be
     booked onto a vehicle already in maintenance);
  3. repairs existing contradictions: any RESERVED/ACTIVE reservation that
     overlaps an ACTIVE maintenance for the same vehicle is cancelled with the
     canonical reason.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g2b3c4d5e6f7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New column — nullable, no default: existing rows keep NULL.
    with op.batch_alter_table("reservations") as batch:
        batch.add_column(sa.Column("cancellation_reason", sa.String(length=50), nullable=True))

    bind = op.get_bind()

    # 2. Drop the maintenance-side rejection trigger (PostgreSQL only). The
    #    check_reservation_maintenance_overlap() function is rewritten so that
    #    trg_check_overlap_res only guards the reservation side.
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_check_overlap_maint ON maintenances;")
        op.execute(
            """
            CREATE OR REPLACE FUNCTION check_reservation_maintenance_overlap()
            RETURNS TRIGGER AS $func$
            DECLARE
                overlapping_maint UUID;
            BEGIN
                IF NEW.status NOT IN ('CANCELLED', 'COMPLETED') THEN
                    SELECT id INTO overlapping_maint FROM maintenances
                    WHERE vehicle_id = NEW.vehicle_id
                    AND status NOT IN ('CANCELLED', 'COMPLETED')
                    AND tstzrange(start_datetime, COALESCE(expected_end_datetime, actual_end_datetime, start_datetime + interval '1 day'), '[)') &&
                        tstzrange(NEW.start_datetime, NEW.end_datetime, '[)')
                    LIMIT 1;

                    IF overlapping_maint IS NOT NULL THEN
                        RAISE EXCEPTION 'Vehicle is in maintenance during this reservation period';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $func$ LANGUAGE plpgsql;
            """
        )

    # 3. One-way data repair: cancel reservations that already contradict an
    #    active maintenance. Portable SQL (no UPDATE ... FROM / alias).
    op.execute(
        """
        UPDATE reservations
        SET status = 'CANCELLED',
            cancellation_reason = 'MAINTENANCE',
            version = version + 1
        WHERE status IN ('RESERVED', 'ACTIVE')
          AND id IN (
              SELECT r.id
              FROM reservations r
              JOIN maintenances m ON m.vehicle_id = r.vehicle_id
              WHERE m.status = 'ACTIVE'
                AND r.start_datetime < COALESCE(m.expected_end_datetime, m.actual_end_datetime, m.start_datetime)
                AND r.end_datetime  > m.start_datetime
          );
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        # Restore the original two-sided rejection function + trigger.
        op.execute(
            """
            CREATE OR REPLACE FUNCTION check_reservation_maintenance_overlap()
            RETURNS TRIGGER AS $func$
            DECLARE
                overlapping_res UUID;
                overlapping_maint UUID;
            BEGIN
                IF TG_TABLE_NAME = 'maintenances' AND NEW.status NOT IN ('COMPLETED', 'CANCELLED') THEN
                    SELECT id INTO overlapping_res FROM reservations
                    WHERE vehicle_id = NEW.vehicle_id
                    AND status NOT IN ('CANCELLED', 'COMPLETED')
                    AND tstzrange(start_datetime, end_datetime, '[)') &&
                        tstzrange(NEW.start_datetime, COALESCE(NEW.expected_end_datetime, NEW.actual_end_datetime, NEW.start_datetime + interval '1 day'), '[)')
                    LIMIT 1;
                    IF overlapping_res IS NOT NULL THEN
                        RAISE EXCEPTION 'Vehicle is reserved during this maintenance period';
                    END IF;
                ELSIF TG_TABLE_NAME = 'reservations' AND NEW.status NOT IN ('CANCELLED', 'COMPLETED') THEN
                    SELECT id INTO overlapping_maint FROM maintenances
                    WHERE vehicle_id = NEW.vehicle_id
                    AND status NOT IN ('CANCELLED', 'COMPLETED')
                    AND tstzrange(start_datetime, COALESCE(expected_end_datetime, actual_end_datetime, start_datetime + interval '1 day'), '[)') &&
                        tstzrange(NEW.start_datetime, NEW.end_datetime, '[)')
                    LIMIT 1;
                    IF overlapping_maint IS NOT NULL THEN
                        RAISE EXCEPTION 'Vehicle is in maintenance during this reservation period';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $func$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS trg_check_overlap_maint ON maintenances;
            CREATE TRIGGER trg_check_overlap_maint
            BEFORE INSERT OR UPDATE ON maintenances
            FOR EACH ROW EXECUTE FUNCTION check_reservation_maintenance_overlap();
            """
        )

    # The data repair (cancelled reservations) is intentionally not reversed —
    # those cancellations reflect a real business conflict.
    with op.batch_alter_table("reservations") as batch:
        batch.drop_column("cancellation_reason")
