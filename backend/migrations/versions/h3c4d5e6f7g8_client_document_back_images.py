"""client identity documents: add verso (back) image columns

Revision ID: h3c4d5e6f7g8
Revises: g2b3c4d5e6f7
Create Date: 2026-08-29 12:05:00.000000

A Moroccan CIN and a driving licence are both two-sided. The legacy columns
``identity_card_image`` / ``driving_license_image`` are treated as the RECTO
(front). This migration adds the matching VERSO (back) columns. They are
nullable and default NULL — every existing client keeps its front image and
simply has no back image until one is uploaded. No data migration, no
destructive change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h3c4d5e6f7g8"
down_revision: Union[str, None] = "g2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.add_column(sa.Column("identity_card_image_back", sa.Text(), nullable=True))
        batch.add_column(sa.Column("driving_license_image_back", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.drop_column("driving_license_image_back")
        batch.drop_column("identity_card_image_back")
