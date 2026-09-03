"""
Reservation model with PostgreSQL EXCLUSION constraint for double-booking prevention.

The EXCLUSION constraint uses btree_gist and tstzrange to ensure no two
active reservations for the same vehicle can overlap in time.
This is enforced at the DATABASE level, not the application level.
"""
from sqlalchemy import (
    Column, String, Integer, Numeric, Text, DDL,
    CheckConstraint, ForeignKey, event,
)
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

from app.database import Base
from app.models.base import TimestampMixin, VersionMixin, generate_uuid


class Reservation(Base, TimestampMixin, VersionMixin):
    __tablename__ = "reservations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    vehicle_id = Column(
        UUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    customer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    customer_name = Column(String(255), nullable=True)
    customer_phone = Column(String(20), nullable=True)
    customer_email = Column(String(255), nullable=True)
    identity_card_image = Column(Text, nullable=True)
    driving_license_image = Column(Text, nullable=True)
    start_datetime = Column(TIMESTAMP(timezone=True), nullable=False)
    end_datetime = Column(TIMESTAMP(timezone=True), nullable=False)
    daily_price = Column(Numeric(10, 2), nullable=False)
    num_days = Column(Integer, nullable=False)
    total_price = Column(Numeric(12, 2), nullable=False)
    deposit = Column(Numeric(10, 2), nullable=False, default=0)
    payment_status = Column(String(20), nullable=False, default="PENDING")
    status = Column(String(20), nullable=False, default="RESERVED")
    # Machine-readable cause when status == 'CANCELLED'. Canonical values:
    # 'MAINTENANCE' (auto-cancelled because an active maintenance period
    # overlapped this reservation). NULL for manual/other cancellations.
    # The human-facing translation lives in the UI i18n layer, never here.
    cancellation_reason = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('RESERVED', 'ACTIVE', 'COMPLETED', 'CANCELLED')",
            name="ck_reservations_valid_status",
        ),
        CheckConstraint(
            "payment_status IN ('PENDING', 'PARTIAL', 'PAID', 'REFUNDED')",
            name="ck_reservations_valid_payment_status",
        ),
        CheckConstraint(
            "end_datetime > start_datetime",
            name="ck_reservations_end_after_start",
        ),
        CheckConstraint(
            "daily_price >= 0",
            name="ck_reservations_daily_price_non_negative",
        ),
        CheckConstraint(
            "total_price >= 0",
            name="ck_reservations_total_price_non_negative",
        ),
        CheckConstraint(
            "deposit >= 0",
            name="ck_reservations_deposit_non_negative",
        ),
        CheckConstraint(
            "num_days >= 1",
            name="ck_reservations_min_days",
        ),
    )

    def __repr__(self):
        return f"<Reservation(id={self.id}, vehicle={self.vehicle_id}, status={self.status})>"


# The EXCLUSION constraint must be created via raw DDL because SQLAlchemy
# does not natively support PostgreSQL EXCLUSION constraints.
# This prevents double booking at the database level.
_create_exclusion_constraint = DDL("""
    DO $$
    BEGIN
        CREATE EXTENSION IF NOT EXISTS btree_gist;
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'excl_reservations_no_overlap'
        ) THEN
            ALTER TABLE reservations ADD CONSTRAINT excl_reservations_no_overlap
                EXCLUDE USING gist (
                    vehicle_id WITH =,
                    tstzrange(start_datetime, end_datetime, '[)') WITH &&
                )
                WHERE (status NOT IN ('CANCELLED', 'COMPLETED'));
        END IF;
    END $$;
""")

event.listen(
    Reservation.__table__,
    "after_create",
    _create_exclusion_constraint.execute_if(dialect="postgresql"),
)
