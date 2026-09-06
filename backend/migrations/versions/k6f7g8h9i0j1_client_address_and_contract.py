"""client profile: add postal address and contract document

Revision ID: k6f7g8h9i0j1
Revises: j5e6f7g8h9i0
Create Date: 2026-09-05 10:00:00.000000

The Client window now edits the full client profile (nom, prénom, CIN,
téléphone, adresse, email, permis, documents). Two authoritative columns were
missing from the ``clients`` table:

  - ``address``        : the client's postal address (free text, nullable)
  - ``contract_image`` : the signed rental contract scan, the fifth document
                         slot alongside CIN recto/verso and permis recto/verso

Both are nullable with a NULL default, so every existing client row stays
valid and unchanged. No data migration, no destructive change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k6f7g8h9i0j1"
down_revision: Union[str, None] = "j5e6f7g8h9i0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.add_column(sa.Column("address", sa.Text(), nullable=True))
        batch.add_column(sa.Column("contract_image", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.drop_column("contract_image")
        batch.drop_column("address")
