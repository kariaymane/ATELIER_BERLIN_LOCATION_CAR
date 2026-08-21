"""Add maintenance table

Revision ID: 003_maintenance
Revises: 002_customer_fields
Create Date: 2026-08-11
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003_maintenance"
down_revision: Union[str, None] = "002_customer_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        "maintenances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_datetime", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expected_end_datetime", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("actual_end_datetime", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("mileage", sa.Numeric(10, 2), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(10, 2), nullable=True),
        sa.Column("actual_cost", sa.Numeric(10, 2), nullable=True),
        sa.Column("step", sa.String(50), nullable=False, server_default="EN ATTENTE"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("step IN ('EN ATTENTE', 'DIAGNOSTIC', 'REPARATION', 'CONTROLE', 'TERMINE')", name="ck_maintenances_valid_step"),
        sa.CheckConstraint("status IN ('ACTIVE', 'COMPLETED', 'CANCELLED')", name="ck_maintenances_valid_status")
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION update_maintenances_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ language 'plpgsql';

        CREATE TRIGGER trg_maintenances_updated_at
            BEFORE UPDATE ON maintenances
            FOR EACH ROW
            EXECUTE FUNCTION update_maintenances_updated_at();

        CREATE OR REPLACE FUNCTION check_reservation_maintenance_overlap()
        RETURNS TRIGGER AS $$
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
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_check_overlap_maint
        BEFORE INSERT OR UPDATE ON maintenances
        FOR EACH ROW EXECUTE FUNCTION check_reservation_maintenance_overlap();

        CREATE TRIGGER trg_check_overlap_res
        BEFORE INSERT OR UPDATE ON reservations
        FOR EACH ROW EXECUTE FUNCTION check_reservation_maintenance_overlap();
    """)

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_check_overlap_res ON reservations;")
    op.execute("DROP TRIGGER IF EXISTS trg_check_overlap_maint ON maintenances;")
    op.execute("DROP FUNCTION IF EXISTS check_reservation_maintenance_overlap();")
    op.execute("DROP TRIGGER IF EXISTS trg_maintenances_updated_at ON maintenances;")
    op.execute("DROP FUNCTION IF EXISTS update_maintenances_updated_at();")
    op.drop_table("maintenances")
