"""unstick vehicles left in MAINTENANCE with no active maintenance

Revision ID: f1a2b3c4d5e6
Revises: c8e41a7b2d95
Create Date: 2026-08-29 00:00:00.000000

Background
----------
`vehicle.status` was set to ``MAINTENANCE`` when a maintenance ticket was
created but a code regression stopped clearing it on completion. Vehicles
therefore accumulated a permanent ``MAINTENANCE`` flag and looked
un-bookable everywhere. Availability is now derived from the maintenance
*schedule*, so any vehicle flagged ``MAINTENANCE`` while it has no
ACTIVE maintenance ticket is stale and must be reset to ``AVAILABLE``.
Structural states (``SOLD`` / ``INACTIVE``) are never touched.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "c8e41a7b2d95"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Portable form (valid on PostgreSQL and SQLite): no UPDATE table alias.
    op.execute(
        """
        UPDATE vehicles
        SET status = 'AVAILABLE',
            version = version + 1
        WHERE status = 'MAINTENANCE'
          AND id NOT IN (
              SELECT vehicle_id FROM maintenances WHERE status = 'ACTIVE'
          );
        """
    )


def downgrade() -> None:
    # One-way data repair; nothing to undo.
    pass
