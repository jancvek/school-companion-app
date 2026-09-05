"""Izid vision obdelave: novi stolpci na materials in tabela questions.

Vsi novi stolpci so `NULL`-abilni. To ni popustljivost, ampak pogoj: v bazi so
že vrstice iz V1-R02, ki obdelave niso videle, in te morajo migracijo prestati
nedotaknjene. Worker jih pobere kot vsako drugo, ker so še vedno `new`.

Revision ID: 0002_obdelava
Revises: 0001_materials
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_obdelava"
down_revision: str | None = "0001_materials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Stolpci, ki jih ta migracija doda k `materials`.
#:
#: Seznam je na enem mestu zato, da `upgrade` in `downgrade` ne moreta zdrsniti
#: narazen: pozabljen stolpec v `downgrade` bi pomenil, da `downgrade base` ne
#: pripelje nazaj v prvotno stanje, in tega bi test opazil šele posredno.
#: Pari `(ime, tip)`, ne gotovi `sa.Column`: en `Column` se ne da vstaviti v
#: dve tabeli, kopiranje pa je v SQLAlchemy opuščeno.
NOVI_STOLPCI: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("readable", sa.Boolean()),
    ("transcript", sa.Text()),
    ("summary", sa.Text()),
    ("prompt", sa.Text()),
    ("raw_response", sa.Text()),
    ("model", sa.String(length=128)),
    ("input_tokens", sa.Integer()),
    ("output_tokens", sa.Integer()),
    ("error", sa.Text()),
)


def upgrade() -> None:
    """Doda stolpce izida in tabelo vprašanj."""
    for ime, tip in NOVI_STOLPCI:
        op.add_column("materials", sa.Column(ime, tip, nullable=True))

    op.create_table(
        "questions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("material_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        # `ondelete="CASCADE"` je druga mreža poleg kaskade v ORM. Na
        # Postgresu drži tudi pri brisanju mimo ORM; na SQLite je brez
        # `PRAGMA foreign_keys=ON` sam po sebi neaktiven, zato prva mreža
        # (`cascade="all, delete-orphan"` v `app/models.py`) ni odveč.
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_questions_material_id", "questions", ["material_id"])


def downgrade() -> None:
    """Odstrani tabelo vprašanj in stolpce izida.

    Stolpci se spuščajo v `batch_alter_table`: `ALTER TABLE ... DROP COLUMN`
    zna SQLite šele od 3.35 naprej, paketni način pa tabelo ob potrebi
    prepiše. Nad Postgresom je to navaden `ALTER TABLE`.
    """
    op.drop_index("ix_questions_material_id", table_name="questions")
    op.drop_table("questions")

    with op.batch_alter_table("materials") as paket:
        for ime, _ in NOVI_STOLPCI:
            paket.drop_column(ime)
