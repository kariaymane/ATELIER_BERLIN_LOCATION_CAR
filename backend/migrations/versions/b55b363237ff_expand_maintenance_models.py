"""expand maintenance models

Revision ID: b55b363237ff
Revises: 74cde196b244
Create Date: 2026-08-20 03:29:01.403488

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b55b363237ff'
down_revision: Union[str, None] = '74cde196b244'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('maintenance_parts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('maintenance_id', sa.UUID(), nullable=False),
    sa.Column('part_name', sa.String(length=255), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('total_price', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['maintenance_id'], ['maintenances.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_maintenance_parts_maintenance_id'), 'maintenance_parts', ['maintenance_id'], unique=False)
    op.add_column('maintenances', sa.Column('title', sa.String(length=255), nullable=True))
    op.add_column('maintenances', sa.Column('diagnosis', sa.Text(), nullable=True))
    op.add_column('maintenances', sa.Column('repair_description', sa.Text(), nullable=True))
    op.add_column('maintenances', sa.Column('technician_name', sa.String(length=255), nullable=True))
    op.add_column('maintenances', sa.Column('invoice_number', sa.String(length=255), nullable=True))
    op.add_column('maintenances', sa.Column('oil_brand', sa.String(length=100), nullable=True))
    op.add_column('maintenances', sa.Column('oil_viscosity', sa.String(length=50), nullable=True))
    op.add_column('maintenances', sa.Column('oil_quantity', sa.Numeric(precision=5, scale=2), nullable=True))

    # Adding defaults for existing boolean columns using server_default
    op.add_column('maintenances', sa.Column('oil_filter_changed', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('maintenances', sa.Column('air_filter_changed', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('maintenances', sa.Column('fuel_filter_changed', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('maintenances', sa.Column('cabin_filter_changed', sa.Boolean(), server_default='false', nullable=False))

    op.add_column('maintenances', sa.Column('parts_cost', sa.Numeric(precision=10, scale=2), server_default='0', nullable=False))
    op.add_column('maintenances', sa.Column('labor_cost', sa.Numeric(precision=10, scale=2), server_default='0', nullable=False))
    op.add_column('maintenances', sa.Column('other_cost', sa.Numeric(precision=10, scale=2), server_default='0', nullable=False))

    op.add_column('maintenances', sa.Column('next_maintenance_date', postgresql.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('maintenances', sa.Column('next_maintenance_mileage', sa.Numeric(precision=10, scale=2), nullable=True))

    op.drop_constraint('ck_maintenances_valid_status', 'maintenances', type_='check')
    op.create_check_constraint('ck_maintenances_valid_status', 'maintenances', "status IN ('ACTIVE', 'COMPLETED', 'CANCELLED', 'SCHEDULED', 'IN_PROGRESS')")

def downgrade() -> None:
    op.drop_constraint('ck_maintenances_valid_status', 'maintenances', type_='check')
    op.create_check_constraint('ck_maintenances_valid_status', 'maintenances', "status IN ('ACTIVE', 'COMPLETED', 'CANCELLED')")

    op.drop_column('maintenances', 'next_maintenance_mileage')
    op.drop_column('maintenances', 'next_maintenance_date')
    op.drop_column('maintenances', 'other_cost')
    op.drop_column('maintenances', 'labor_cost')
    op.drop_column('maintenances', 'parts_cost')
    op.drop_column('maintenances', 'cabin_filter_changed')
    op.drop_column('maintenances', 'fuel_filter_changed')
    op.drop_column('maintenances', 'air_filter_changed')
    op.drop_column('maintenances', 'oil_filter_changed')
    op.drop_column('maintenances', 'oil_quantity')
    op.drop_column('maintenances', 'oil_viscosity')
    op.drop_column('maintenances', 'oil_brand')
    op.drop_column('maintenances', 'invoice_number')
    op.drop_column('maintenances', 'technician_name')
    op.drop_column('maintenances', 'repair_description')
    op.drop_column('maintenances', 'diagnosis')
    op.drop_column('maintenances', 'title')

    op.drop_index(op.f('ix_maintenance_parts_maintenance_id'), table_name='maintenance_parts')
    op.drop_table('maintenance_parts')
