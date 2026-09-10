"""Poskusi reševanja kviza in rešenost kviza.

Dvoje in nič drugega: nov `NULL`-abilen stolpec `quizzes.solved_at` in nova
tabela `question_attempts`. Obstoječih vrstic ta migracija ne prepisuje —
objavljeni kvizi ostanejo nerešeni (`solved_at IS NULL`), kar je res.

Razlogi za obliko so v `docs/odlocitve/ADR-017` (C), `ADR-012`, `ADR-014` in
`ADR-019`:

- `solved_at` pride šele zdaj, ker ga edini zna napolniti zapis poskusov
  (`ADR-017` C).
- Poskus je **dogodek**: ena vrstica na odgovor, `id` generira telefon, zato
  ponovljen prenos ne podvoji zapisa (`ADR-012`). Nosi `mode`, zaenkrat vedno
  `samoocena` (`ADR-014`).
- `quiz_item_id` je **enoličen**: postavka ima največ en poskus (`ADR-019` E).
- `question_id` tu **ni**: izpeljiv je prek `quiz_items.question_id`, podvojen
  pa bi se lahko razšel.
- Tuji ključ na postavko je **brez `ondelete`**. Poskus nosi statistiko, zato
  naj baza brisanje kviza s poskusi raje zavrne, kot da jih tiho vzame s sabo.

Revision ID: 0006_poskusi
Revises: 0005_kvizi
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_poskusi"
down_revision: str | None = "0005_kvizi"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Imena na enem mestu, da `upgrade` in `downgrade` ne moreta zdrsniti narazen.
KVIZI = "quizzes"
RESEN = "solved_at"
POSKUSI = "question_attempts"

#: Omejitvi sta poimenovani in ne prepuščeni dialektnemu privzetku — isti
#: razlog kot v `0005_kvizi`.
KLJUC_POSTAVKE = "question_attempts_quiz_item_id_fkey"
ENOLICNA_POSTAVKA = "question_attempts_quiz_item_id_key"


def upgrade() -> None:
    """Doda `quizzes.solved_at` in ustvari `question_attempts`."""
    op.add_column(KVIZI, sa.Column(RESEN, sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        POSKUSI,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("quiz_item_id", sa.String(length=36), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("rating", sa.String(length=16), nullable=False),
        # Trije žigi s telefona (`ADR-019` D) in eden s strežnika.
        sa.Column("shown_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["quiz_item_id"], ["quiz_items.id"], name=KLJUC_POSTAVKE),
        # Enoličnost je tudi indeks, zato posebnega indeksa na `quiz_item_id` ni.
        sa.UniqueConstraint("quiz_item_id", name=ENOLICNA_POSTAVKA),
    )


def downgrade() -> None:
    """Vrne shemo v stanje `0005_kvizi`.

    **Vsi poskusi in podatek o rešenosti se pri tem izgubijo dokončno.** Kvizi in
    njihove postavke ostanejo; ponoven `upgrade` bi vse kvize spet naredil
    nerešene in telefon bi jih prenesel znova. Vrnitev čezenj je zato smiselna
    samo nad bazo, v kateri kviz še ni bil rešen.

    Najprej tabela, nato stolpec: tabela na stolpec ne kaže, zato vrstni red
    tu ni nujen, je pa obraten od `upgrade` po istem pravilu kot povsod.
    `DROP COLUMN` na stolpcu brez omejitev zna tudi SQLite (glej `0004`).
    """
    op.drop_table(POSKUSI)
    op.drop_column(KVIZI, RESEN)
