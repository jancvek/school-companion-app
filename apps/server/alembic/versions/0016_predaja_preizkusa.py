"""Shranjen preizkus ima stanje predaje (V4-R10).

Dva stolpca na `preizkusi` in nič drugega (`docs/odlocitve/ADR-068` A):

- `given_at` — kdaj je starš test dal otroku (stanje *v reševanju*).
- `solved_at` — kdaj ga je otrok rešil (stanje *rešen*).

Oba sta `NULL` dovoljena in brez privzetka: obstoječi preizkusi so po
migraciji *shranjeni*, kar je resnica — nihče jih še ni označil.

Revision ID: 0016_predaja_preizkusa
Revises: 0015_odobritev_druzine
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_predaja_preizkusa"
down_revision: str | None = "0015_odobritev_druzine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Imena na enem mestu, da `upgrade` in `downgrade` ne moreta zdrsniti narazen.
PREIZKUSI = "preizkusi"
DAN = "given_at"
RESEN = "solved_at"


def upgrade() -> None:
    """Doda oba časa; obstoječe vrstice ostanejo nedotaknjene."""
    op.add_column(PREIZKUSI, sa.Column(DAN, sa.DateTime(timezone=True), nullable=True))
    op.add_column(PREIZKUSI, sa.Column(RESEN, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Vrne shemo v stanje `0015_odobritev_druzine`.

    Stanje predaje se izgubi dokončno; vrstice ostanejo. Razveljavitev se ne
    ustavi, ker izguba nikomur ne odpre dostopa — drugače kot pri
    `0015_odobritev_druzine` (`ADR-068`, *Posledice*).
    """
    op.drop_column(PREIZKUSI, RESEN)
    op.drop_column(PREIZKUSI, DAN)
