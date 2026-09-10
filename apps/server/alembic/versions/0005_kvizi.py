"""Kviz kot objekt in njegove zamrznjene postavke.

Dve novi tabeli in nič drugega: nobenega obstoječega stolpca se ta migracija
ne dotakne, zato obstoječih vrstic ni treba ne prepisovati ne polniti.

Razloga za obliko sta `docs/odlocitve/ADR-016` (E) in `ADR-017`:

- `quiz_items` hrani `question_id` **in** kopijo obeh besedil. Ključ nosi
  identiteto, ki jo bo potrebovala `V2-R04`; kopija nosi berljivost, ko bo
  izvorna snov dokončno izbrisana in bo `questions.material_id` `NULL`
  (`ADR-012`).
- `quizzes` **nima** stolpca `status`: stanje se izpelje iz `canceled_at`, po
  istem vzorcu, kot je arhiv svoja os v `ADR-011`.
- `quizzes` **nima** stolpca `solved_at`. Doda ga migracija `V2-R02`, skupaj s
  poskusi, ki ga edini znajo napolniti (`ADR-017` C). Stolpec, ki ga nihče ne
  piše in ne bere, je ostanek generatorja in ne priprava na prihodnost — isti
  argument, s katerim je `ADR-016` (D) zavrnil `quiz_sources`.
- `quiz_items` **nima** stolpca `material_id`. Pot do snovi gre prek
  `question_id → questions.material_id`, kar vzdrži zato, ker se vprašanja
  nikoli ne brišejo, snov po brisanju materiala pa je razpoznavna iz
  denormaliziranih `questions.subject` in `questions.material_taken_at`
  (`ADR-017` B).

Revision ID: 0005_kvizi
Revises: 0004_upokojena_vprasanja
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_kvizi"
down_revision: str | None = "0004_upokojena_vprasanja"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Imena na enem mestu, da `upgrade` in `downgrade` ne moreta zdrsniti narazen
#: — isti razlog kot pri seznamih stolpcev v `0002_obdelava` in `0003_arhiv`.
KVIZI = "quizzes"
POSTAVKE = "quiz_items"

#: Tuja ključa sta poimenovana in ne prepuščena dialektnemu privzetku.
#: `0003_arhiv` je moral ugibati ime, ki ga je pustil `0001_materials`; te
#: napake ne ponavljamo.
KLJUC_KVIZA = "quiz_items_quiz_id_fkey"
KLJUC_VPRASANJA = "quiz_items_question_id_fkey"


def upgrade() -> None:
    """Ustvari `quizzes` in `quiz_items`."""
    op.create_table(
        KVIZI,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        # `NULL` pomeni kviz čez več predmetov („Kaj smo se danes učili").
        sa.Column("subject", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        POSTAVKE,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("quiz_id", sa.String(length=36), nullable=False),
        # `NULL`-abilen zaradi `ON DELETE SET NULL`. V praksi se to ne zgodi —
        # vprašanja se ne brišejo — a shema mora povedati isto kot ključ.
        sa.Column("question_id", sa.String(length=36), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        # Kopija ob objavi. Ni podvajanje iz nemarnosti: to je edino, kar kviz
        # izpred let še zna prikazati, ko izvorne snovi ni več.
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # `CASCADE`: postavka brez kviza nima pomena. To je edina kaskada
        # brisanja v shemi in ne nasprotuje `ADR-012` — ta govori o vprašanjih,
        # ki morajo material preživeti, ne o postavkah kviza.
        sa.ForeignKeyConstraint(
            ["quiz_id"], [f"{KVIZI}.id"], name=KLJUC_KVIZA, ondelete="CASCADE"
        ),
        # `SET NULL` in ne `CASCADE`: če bi kdaj kdo vprašanje vseeno pobrisal,
        # naj kviz izgubi ključ, ne pa postavke — besedilo je zamrznjeno v njej.
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.id"],
            name=KLJUC_VPRASANJA,
            ondelete="SET NULL",
        ),
    )

    op.create_index(op.f(f"ix_{POSTAVKE}_quiz_id"), POSTAVKE, ["quiz_id"])
    op.create_index(op.f(f"ix_{POSTAVKE}_question_id"), POSTAVKE, ["question_id"])


def downgrade() -> None:
    """Vrne shemo v stanje `0004_upokojena_vprasanja`.

    **Vsi kvizi in vse njihove postavke se pri tem izgubijo dokončno.** Za
    razliko od `downgrade` v `0004`, kjer se izgubi le podatek o upokojitvi,
    tu izginejo cele vrstice — sheme pred to migracijo ni kam zapisati. Vrnitev
    čezenj je zato smiselna samo nad bazo, v kateri kviz še ni bil objavljen.

    Vprašanja ostanejo nedotaknjena: `quiz_items` kaže nanje, ne obratno.

    Vrstni red je obrnjen glede na `upgrade` — najprej otrok, nato starš —
    sicer bi tuji ključ na Postgresu brisanje `quizzes` zavrnil.
    """
    op.drop_index(op.f(f"ix_{POSTAVKE}_question_id"), table_name=POSTAVKE)
    op.drop_index(op.f(f"ix_{POSTAVKE}_quiz_id"), table_name=POSTAVKE)
    op.drop_table(POSTAVKE)
    op.drop_table(KVIZI)
