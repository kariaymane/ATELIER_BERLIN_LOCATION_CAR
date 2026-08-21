"""Add customer_name and customer_phone to reservations

Revision ID: 002_customer_fields
Revises: 001_foundation
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002_customer_fields"
down_revision: Union[str, None] = "001_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reservations", sa.Column("customer_name", sa.String(255), nullable=True))
    op.add_column("reservations", sa.Column("customer_phone", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("reservations", "customer_phone")
    op.drop_column("reservations", "customer_name")
