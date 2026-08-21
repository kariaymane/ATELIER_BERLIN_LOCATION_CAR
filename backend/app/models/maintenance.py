"""
Maintenance model to track vehicle repairs, inspections, and maintenance events.
"""
from sqlalchemy import (
    Column, String, Text, ForeignKey, Numeric, CheckConstraint, DDL, event, Boolean
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

from app.database import Base
from app.models.base import TimestampMixin, VersionMixin, generate_uuid


class Maintenance(Base, TimestampMixin, VersionMixin):
    __tablename__ = "maintenances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    vehicle_id = Column(
        UUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Existing fields mapped to user requests where possible
    type = Column(String(50), nullable=False) # Maps to maintenance_type (accident, panne, vidange, freins, etc.)
    title = Column(String(255), nullable=True) # Custom title
    description = Column(Text, nullable=True) # Maps to problem_description
    diagnosis = Column(Text, nullable=True)
    repair_description = Column(Text, nullable=True)

    start_datetime = Column(TIMESTAMP(timezone=True), nullable=False) # Maps to date
    expected_end_datetime = Column(TIMESTAMP(timezone=True), nullable=True)
    actual_end_datetime = Column(TIMESTAMP(timezone=True), nullable=True)

    mileage = Column(Numeric(10, 2), nullable=True)
    location = Column(String(255), nullable=True) # Maps to garage_name
    technician_name = Column(String(255), nullable=True)
    invoice_number = Column(String(255), nullable=True)

    # Oil Specific Fields
    oil_brand = Column(String(100), nullable=True)
    oil_viscosity = Column(String(50), nullable=True)
    oil_quantity = Column(Numeric(5, 2), nullable=True)
    oil_filter_changed = Column(Boolean, default=False, nullable=False)
    air_filter_changed = Column(Boolean, default=False, nullable=False)
    fuel_filter_changed = Column(Boolean, default=False, nullable=False)
    cabin_filter_changed = Column(Boolean, default=False, nullable=False)

    # Financials
    estimated_cost = Column(Numeric(10, 2), nullable=True)
    parts_cost = Column(Numeric(10, 2), default=0, nullable=False)
    labor_cost = Column(Numeric(10, 2), default=0, nullable=False)
    other_cost = Column(Numeric(10, 2), default=0, nullable=False)
    actual_cost = Column(Numeric(10, 2), nullable=True) # Maps to total_cost

    # Next Maintenance Alerts
    next_maintenance_date = Column(TIMESTAMP(timezone=True), nullable=True)
    next_maintenance_mileage = Column(Numeric(10, 2), nullable=True)

    # Workflow
    step = Column(String(50), nullable=False, default="EN ATTENTE")
    status = Column(String(20), nullable=False, default="ACTIVE") # ACTIVE, COMPLETED, CANCELLED, SCHEDULED, IN_PROGRESS
    notes = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Relationships
    parts = relationship("MaintenancePart", back_populates="maintenance", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "step IN ('EN ATTENTE', 'DIAGNOSTIC', 'REPARATION', 'CONTROLE', 'TERMINE')",
            name="ck_maintenances_valid_step",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'COMPLETED', 'CANCELLED', 'SCHEDULED', 'IN_PROGRESS')",
            name="ck_maintenances_valid_status",
        ),
    )

    def __repr__(self):
        return f"<Maintenance(id={self.id}, vehicle={self.vehicle_id}, type={self.type})>"


class MaintenancePart(Base, TimestampMixin):
    __tablename__ = "maintenance_parts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    maintenance_id = Column(
        UUID(as_uuid=True),
        ForeignKey("maintenances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    part_name = Column(String(255), nullable=False)
    quantity = Column(Numeric(10, 2), nullable=False, default=1)
    unit_price = Column(Numeric(10, 2), nullable=False, default=0)
    total_price = Column(Numeric(10, 2), nullable=False, default=0)
    notes = Column(Text, nullable=True)

    maintenance = relationship("Maintenance", back_populates="parts")


# Cross-table trigger for Reservation vs Maintenance overlap
_create_overlap_triggers = DDL("""
    DO $$
    BEGIN
        CREATE OR REPLACE FUNCTION check_reservation_maintenance_overlap()
        RETURNS TRIGGER AS $func$
        DECLARE
            overlapping_res UUID;
            overlapping_maint UUID;
        BEGIN
            -- If inserting/updating a maintenance record
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

            -- If inserting/updating a reservation record
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

        DROP TRIGGER IF EXISTS trg_check_overlap_res ON reservations;
        CREATE TRIGGER trg_check_overlap_res
        BEFORE INSERT OR UPDATE ON reservations
        FOR EACH ROW EXECUTE FUNCTION check_reservation_maintenance_overlap();
    END $$;
""")

event.listen(
    Maintenance.__table__,
    "after_create",
    _create_overlap_triggers.execute_if(dialect="postgresql"),
)
