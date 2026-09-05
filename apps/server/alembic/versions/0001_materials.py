"""Tabela materials in razširitev vector.

Razširitev `vector` se omogoči zdaj, ker jo prinese slika `pgvector/pgvector`
in ker jo zahteva kriterij V1-R02. Vektorskih stolpcev tu **ni** — iskanje po
pomenu je V2 (odločitev 3 v `docs/plan/V1-R02.md`).

Revision ID: 0001_materials
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_materials"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Ustvari razširitev in tabelo."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "materials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject", sa.String(length=16), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("image_path", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Odstrani tabelo. Razširitev pusti pri miru — lahko jo rabi kdo drug."""
    op.drop_table("materials")
