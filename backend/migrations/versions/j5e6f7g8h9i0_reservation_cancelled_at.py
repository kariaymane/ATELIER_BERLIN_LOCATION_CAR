"""add reservations.cancelled_at (interruption instant for realised-revenue cap)

Revision ID: j5e6f7g8h9i0
Revises: i4d5e6f7g8h9
Create Date: 2026-09-04 01:00:00.000000

Why: when a rental is CANCELLED *after it has started* (maintenance
interruption), the canonical revenue rule preserves only the days realised
BEFORE the interruption. That needs the interruption instant. Previously the
code fell back to the original ``end_datetime``, which made an interrupted
rental silently recognise its FULL contract value once wall-clock time passed
that end — and made a closed period's revenue change retroactively.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j5e6f7g8h9i0"
down_revision: Union[str, None] = "i4d5e6f7g8h9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reservations",
        sa.Column("cancelled_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    # Backfill existing MAINTENANCE-cancelled rows with a best-effort instant so
    # their realised revenue stops drifting: min(updated_at, end_datetime).
    op.execute(
        """
        UPDATE reservations
        SET cancelled_at = LEAST(updated_at, end_datetime)
        WHERE status = 'CANCELLED'
          AND cancellation_reason = 'MAINTENANCE'
          AND cancelled_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("reservations", "cancelled_at")
