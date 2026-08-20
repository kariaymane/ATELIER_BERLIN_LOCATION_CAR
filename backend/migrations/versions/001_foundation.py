"""Phase 1 - Foundation schema

Revision ID: 001_foundation
Revises: None
Create Date: 2026-08-09

Creates all Phase 1 tables with PostgreSQL constraints:
- users (with role CHECK)
- vehicles (with status, fuel, transmission CHECKs and VIN/registration UNIQUE)
- reservations (with EXCLUSION constraint for double-booking prevention)
- audit_logs (immutable)
- refresh_tokens
- idempotency_keys
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP

revision: str = "001_foundation"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable required extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # Users table
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("username", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="EMPLOYEE"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint(
            "role IN ('ADMIN', 'MANAGER', 'EMPLOYEE', 'MOBILE_USER')",
            name="ck_users_valid_role",
        ),
        sa.CheckConstraint("length(email) >= 5", name="ck_users_email_min_length"),
        sa.CheckConstraint("length(username) >= 3", name="ck_users_username_min_length"),
    )

    # Vehicles table
    op.create_table(
        "vehicles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("registration", sa.String(20), unique=True, nullable=False, index=True),
        sa.Column("vin", sa.String(17), unique=True, nullable=False, index=True),
        sa.Column("brand", sa.String(100), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("color", sa.String(50), nullable=False),
        sa.Column("fuel_type", sa.String(20), nullable=False),
        sa.Column("transmission", sa.String(20), nullable=False),
        sa.Column("current_mileage", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("purchase_mileage", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("purchase_price", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("daily_rental_price", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="AVAILABLE"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint(
            "status IN ('AVAILABLE', 'RESERVED', 'RENTED', 'MAINTENANCE', 'SOLD', 'INACTIVE')",
            name="ck_vehicles_valid_status",
        ),
        sa.CheckConstraint(
            "fuel_type IN ('GASOLINE', 'DIESEL', 'ELECTRIC', 'HYBRID', 'LPG')",
            name="ck_vehicles_valid_fuel_type",
        ),
        sa.CheckConstraint(
            "transmission IN ('MANUAL', 'AUTOMATIC')",
            name="ck_vehicles_valid_transmission",
        ),
        sa.CheckConstraint("current_mileage >= 0", name="ck_vehicles_mileage_non_negative"),
        sa.CheckConstraint("purchase_mileage >= 0", name="ck_vehicles_purchase_mileage_non_negative"),
        sa.CheckConstraint("purchase_price >= 0", name="ck_vehicles_purchase_price_non_negative"),
        sa.CheckConstraint("daily_rental_price >= 0", name="ck_vehicles_daily_price_non_negative"),
        sa.CheckConstraint("year >= 1990 AND year <= 2035", name="ck_vehicles_valid_year"),
        sa.CheckConstraint("length(vin) = 17", name="ck_vehicles_vin_length"),
    )

    # Reservations table
    op.create_table(
        "reservations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("vehicle_id", UUID(as_uuid=True), sa.ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("start_datetime", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("end_datetime", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("daily_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("num_days", sa.Integer(), nullable=False),
        sa.Column("total_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("deposit", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("payment_status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("status", sa.String(20), nullable=False, server_default="RESERVED"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint(
            "status IN ('RESERVED', 'ACTIVE', 'COMPLETED', 'CANCELLED')",
            name="ck_reservations_valid_status",
        ),
        sa.CheckConstraint(
            "payment_status IN ('PENDING', 'PARTIAL', 'PAID', 'REFUNDED')",
            name="ck_reservations_valid_payment_status",
        ),
        sa.CheckConstraint("end_datetime > start_datetime", name="ck_reservations_end_after_start"),
        sa.CheckConstraint("daily_price >= 0", name="ck_reservations_daily_price_non_negative"),
        sa.CheckConstraint("total_price >= 0", name="ck_reservations_total_price_non_negative"),
        sa.CheckConstraint("deposit >= 0", name="ck_reservations_deposit_non_negative"),
        sa.CheckConstraint("num_days >= 1", name="ck_reservations_min_days"),
    )

    # EXCLUSION constraint for double-booking prevention
    # This is the CRITICAL constraint that prevents overlapping reservations
    # at the PostgreSQL level, even under concurrent requests.
    op.execute("""
        ALTER TABLE reservations ADD CONSTRAINT excl_reservations_no_overlap
            EXCLUDE USING gist (
                vehicle_id WITH =,
                tstzrange(start_datetime, end_datetime, '[)') WITH &&
            )
            WHERE (status NOT IN ('CANCELLED'))
    """)

    # Audit logs table (immutable, append-only)
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("entity_type", sa.String(50), nullable=False, index=True),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("action", sa.String(50), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("old_values", JSONB(), nullable=True),
        sa.Column("new_values", JSONB(), nullable=True),
        sa.Column("device_id", sa.String(100), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()"), index=True),
    )

    # Refresh tokens table
    op.create_table(
        "refresh_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("token_hash", sa.String(255), unique=True, nullable=False),
        sa.Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("device_id", sa.String(100), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    # Idempotency keys table
    op.create_table(
        "idempotency_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("key", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("endpoint", sa.String(255), nullable=False),
        sa.Column("status_code", sa.String(10), nullable=True),
        sa.Column("response_body", JSONB(), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    # Create updated_at trigger function
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    # Apply updated_at triggers
    for table in ["users", "vehicles", "reservations"]:
        op.execute(f"""
            CREATE TRIGGER trigger_{table}_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column();
        """)


def downgrade() -> None:
    # Drop triggers
    for table in ["users", "vehicles", "reservations"]:
        op.execute(f"DROP TRIGGER IF EXISTS trigger_{table}_updated_at ON {table}")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column()")

    # Drop tables in reverse dependency order
    op.drop_table("idempotency_keys")
    op.drop_table("refresh_tokens")
    op.drop_table("audit_logs")
    op.drop_table("reservations")
    op.drop_table("vehicles")
    op.drop_table("users")
