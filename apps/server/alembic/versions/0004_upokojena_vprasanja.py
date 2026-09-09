"""Vprašanje se ob ponovni obdelavi upokoji, ne izbriše.

En `NULL`-abilen stolpec na `questions` in nič drugega: `retired_at IS NULL`
odslej pomeni veljavno vprašanje. Obstoječe vrstice ostanejo `NULL`, torej
veljavne — prepisa podatkov ni in prepisa tabele ni, ker gre za navaden
`ADD COLUMN`, ki ga zna tudi SQLite.

Razlog je v `docs/odlocitve/ADR-015`, ki nadomesti odločitev **A1** iz
`ADR-009`: `V2-R01` bo kviz vezal na `question_id`, zato gumb „Pošlji v
obdelavo" vprašanja ne sme več pobrisati.

Revision ID: 0004_upokojena_vprasanja
Revises: 0003_arhiv
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_upokojena_vprasanja"
down_revision: str | None = "0003_arhiv"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Ime stolpca na enem mestu, da `upgrade` in `downgrade` ne moreta zdrsniti
#: narazen — isti razlog kot pri seznamih v `0002_obdelava` in `0003_arhiv`.
STOLPEC = "retired_at"


def upgrade() -> None:
    """Doda `retired_at`; obstoječe vrstice ostanejo veljavne."""
    op.add_column(
        "questions", sa.Column(STOLPEC, sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Vrne shemo v stanje `0003_arhiv`.

    **Podatek o upokojitvi se pri tem izgubi dokončno in tiho.** Nobena
    vrstica ne izgine — za razliko od `downgrade` v `0003_arhiv`, ki sirote
    res pobriše — vendar shema pred to migracijo razlike med veljavnim in
    upokojenim vprašanjem ne zna zapisati in je ni kam shraniti. Ponoven
    `upgrade` stolpec vrne prazen, torej so **vsa** nekdaj upokojena
    vprašanja spet veljavna: sestavljalnik kvizov (`V2-R01`) bi jih ponudil,
    kot da prejšnjih obdelav ni bilo. Vrnitev čez to migracijo je zato
    smiselna samo nad bazo, v kateri se ponovna obdelava še ni zgodila.

    `batch_alter_table` tu ni potreben — `DROP COLUMN` na stolpcu brez
    omejitev zna tudi SQLite, ki ga poganjajo testi migracije.
    """
    op.drop_column("questions", STOLPEC)
