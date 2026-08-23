"""create clients table

Revision ID: c8e41a7b2d95
Revises: 5dfe7eb02006
Create Date: 2026-08-23 16:40:00.000000

Creates the `clients` table required by the Client model / API / sync bootstrap.
Without it, every client endpoint and `/api/v1/sync/bootstrap` fails on
databases migrated only up to 5dfe7eb02006.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c8e41a7b2d95'
down_revision: Union[str, None] = '5dfe7eb02006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'clients',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('uuid_generate_v4()')),
        sa.Column('first_name', sa.String(length=100), nullable=False),
        sa.Column('last_name', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('cin_number', sa.String(length=50), nullable=True),
        sa.Column('identity_card_image', sa.Text(), nullable=True),
        sa.Column('license_number', sa.String(length=50), nullable=True),
        sa.Column('driving_license_image', sa.Text(), nullable=True),
        sa.Column('photo_url', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default='ACTIVE'),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text('NOW()')),
        sa.Column('version', sa.Integer(), nullable=False,
                  server_default=sa.text('1')),
    )
    op.create_index('ix_clients_email', 'clients', ['email'])
    op.create_index('ix_clients_phone', 'clients', ['phone'])
    op.create_index('ix_clients_cin_number', 'clients', ['cin_number'])


def downgrade() -> None:
    op.drop_index('ix_clients_cin_number', table_name='clients')
    op.drop_index('ix_clients_phone', table_name='clients')
    op.drop_index('ix_clients_email', table_name='clients')
    op.drop_table('clients')
