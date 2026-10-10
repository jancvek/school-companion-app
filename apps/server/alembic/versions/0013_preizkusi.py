"""Shranjeni preizkusi (V4-R08).

Ena nova tabela in nič drugega: nobenega obstoječega stolpca se ta migracija
ne dotakne, zato obstoječih vrstic ni treba ne prepisovati ne polniti. Isti
razred kot `0005_kvizi` in `0010_urnik`.

Oblika je iz `docs/odlocitve/ADR-053` F in `ADR-055`:

- **Stolpca stanja ni** in osi arhiva tudi ne. Vrstica obstaja samo za končan
  preizkus, ne ureja se in ne briše (`ADR-011`).
- **`source_md` je besedilo**, ne seznam slik: slike se arhivirajo in brišejo,
  prepisi, iz katerih je preizkus nastal, pa morajo ostati (`ADR-055` E).
- **`base_id`** kaže na preizkus, ki je bil izhodišče; `NULL` pri preizkusu
  iz snovi.

Revision ID: 0013_preizkusi
Revises: 0012_google_poverilnica
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_preizkusi"
down_revision: str | None = "0012_google_poverilnica"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Ime na enem mestu, da `upgrade` in `downgrade` ne moreta zdrsniti narazen.
PREIZKUSI = "preizkusi"

#: Tuji ključi so poimenovani in ne prepuščeni dialektnemu privzetku.
KLJUC_DRUZINE = "fk_preizkusi_family_id"
KLJUC_OTROKA = "fk_preizkusi_child_id"
KLJUC_AVTORJA = "fk_preizkusi_saved_by"
KLJUC_OSNOVE = "fk_preizkusi_base_id"


def upgrade() -> None:
    """Ustvari `preizkusi`."""
    op.create_table(
        PREIZKUSI,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("family_id", sa.String(length=36), nullable=False),
        sa.Column("child_id", sa.String(length=36), nullable=False),
        sa.Column("subject", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("test_md", sa.Text(), nullable=False),
        sa.Column("solutions_md", sa.Text(), nullable=False),
        sa.Column("source_md", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("saved_by", sa.String(length=36), nullable=False),
        sa.Column("base_id", sa.String(length=36), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        # Brez `ondelete`, kot pri vseh ključih na `families` in `users`:
        # družina in račun se ne brišeta, ampak deaktivirata. Tudi preizkus se
        # ne briše, zato ključ nase ne potrebuje pravila.
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], name=KLJUC_DRUZINE),
        sa.ForeignKeyConstraint(["child_id"], ["users.id"], name=KLJUC_OTROKA),
        sa.ForeignKeyConstraint(["saved_by"], ["users.id"], name=KLJUC_AVTORJA),
        sa.ForeignKeyConstraint(["base_id"], [f"{PREIZKUSI}.id"], name=KLJUC_OSNOVE),
    )
    op.create_index(op.f(f"ix_{PREIZKUSI}_family_id"), PREIZKUSI, ["family_id"])
    op.create_index(op.f(f"ix_{PREIZKUSI}_child_id"), PREIZKUSI, ["child_id"])


def downgrade() -> None:
    """Vrne shemo v stanje `0012_google_poverilnica`.

    **Vsi shranjeni preizkusi se pri tem izgubijo dokončno** — isti razred kot
    `downgrade` v `0005_kvizi` in `0010_urnik`. Snov, iz katere so nastali,
    ostane: ta migracija se `materials` ne dotika v nobeno smer.
    """
    op.drop_index(op.f(f"ix_{PREIZKUSI}_child_id"), table_name=PREIZKUSI)
    op.drop_index(op.f(f"ix_{PREIZKUSI}_family_id"), table_name=PREIZKUSI)
    op.drop_table(PREIZKUSI)
