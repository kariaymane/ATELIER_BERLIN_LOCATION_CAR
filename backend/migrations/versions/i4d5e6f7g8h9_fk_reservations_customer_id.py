"""add foreign key constraint from reservations.customer_id to clients.id

Revision ID: i4d5e6f7g8h9
Revises: h3c4d5e6f7g8
Create Date: 2026-09-04 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i4d5e6f7g8h9"
down_revision: Union[str, None] = "h3c4d5e6f7g8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Clean up any dangling customer_id references before adding the foreign key constraint
    op.execute(
        """
        UPDATE reservations
        SET customer_id = NULL
        WHERE customer_id IS NOT NULL
          AND customer_id NOT IN (SELECT id FROM clients)
        """
    )
    with op.batch_alter_table("reservations") as batch:
        batch.create_foreign_key(
            "fk_reservations_customer_id_clients",
            "clients",
            ["customer_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("reservations") as batch:
        batch.drop_constraint("fk_reservations_customer_id_clients", type_="foreignkey")
