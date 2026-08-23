"""add_client_documents_and_update_admin

Revision ID: 5dfe7eb02006
Revises: b55b363237ff
Create Date: 2026-08-22 20:20:15.123456

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '5dfe7eb02006'
down_revision: Union[str, None] = 'b55b363237ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. Add client document fields to reservations (acting as client data model)
    op.add_column('reservations', sa.Column('customer_email', sa.String(length=255), nullable=True))
    op.add_column('reservations', sa.Column('identity_card_image', sa.Text(), nullable=True))
    op.add_column('reservations', sa.Column('driving_license_image', sa.Text(), nullable=True))

    # 2. Fix Postgres exclusion constraint for double booking (ignore COMPLETED)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'excl_reservations_no_overlap') THEN
                ALTER TABLE reservations DROP CONSTRAINT excl_reservations_no_overlap;
            END IF;
            
            ALTER TABLE reservations ADD CONSTRAINT excl_reservations_no_overlap
                EXCLUDE USING gist (
                    vehicle_id WITH =,
                    tstzrange(start_datetime, end_datetime, '[)') WITH &&
                )
                WHERE (status NOT IN ('CANCELLED', 'COMPLETED'));
        END $$;
    """)
    
    # NOTE: Admin credentials are NOT managed here.
    # Initial admin creation is handled at startup from ADMIN_EMAIL /
    # ADMIN_PASSWORD environment variables (see app.main._create_initial_admin).
    # Never hardcode credentials or password hashes in migrations.

def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'excl_reservations_no_overlap') THEN
                ALTER TABLE reservations DROP CONSTRAINT excl_reservations_no_overlap;
            END IF;
            
            ALTER TABLE reservations ADD CONSTRAINT excl_reservations_no_overlap
                EXCLUDE USING gist (
                    vehicle_id WITH =,
                    tstzrange(start_datetime, end_datetime, '[)') WITH &&
                )
                WHERE (status NOT IN ('CANCELLED'));
        END $$;
    """)

    op.drop_column('reservations', 'driving_license_image')
    op.drop_column('reservations', 'identity_card_image')
    op.drop_column('reservations', 'customer_email')
