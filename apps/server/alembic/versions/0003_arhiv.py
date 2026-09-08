"""Arhiv slik in vprašanja, ki preživijo material.

Tri stvari naenkrat, ker so ena odločitev (`docs/odlocitve/ADR-011` in
`ADR-012`):

1. `materials` dobi `archived_at` in `device_deleted_at` — arhiv je svoja os,
   ne peto stanje `status`.
2. `questions.material_id` postane `NULL`-abilen in tuji ključ se z `CASCADE`
   prevesi na `SET NULL` — dokončno brisanje slike odslej vprašanj ne vzame.
3. `questions` dobi denormaliziran izvor (`subject`, `material_taken_at`), ki
   se za obstoječe vrstice napolni iz njihovega materiala; brez tega bi
   vprašanje po brisanju materiala ne vedelo več, iz česa je nastalo.

Vsi novi stolpci so `NULL`-abilni. Vrstice iz V1-R02 in V1-R03 morajo
migracijo prestati nedotaknjene.

Revision ID: 0003_arhiv
Revises: 0002_obdelava
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_arhiv"
down_revision: str | None = "0002_obdelava"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Stolpci arhiva na `materials`. Na enem mestu, da `upgrade` in `downgrade`
#: ne moreta zdrsniti narazen (isti razlog kot v `0002_obdelava`).
STOLPCI_ARHIVA: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("archived_at", sa.DateTime(timezone=True)),
    ("device_deleted_at", sa.DateTime(timezone=True)),
)

#: Denormaliziran izvor na `questions`.
STOLPCI_IZVORA: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("subject", sa.String(length=16)),
    ("material_taken_at", sa.DateTime(timezone=True)),
)

#: Ime tujega ključa, kakršnega je Postgres samodejno dal nepoimenovanemu
#: ključu iz `0002_obdelava` (`<tabela>_<stolpec>_fkey`).
STARI_FK = "questions_material_id_fkey"

#: Ime, ki ga tuji ključ dobi odslej. Poimenovan je zato, da ga naslednja
#: migracija ne bo lovila po dialektnem privzetku.
NOVI_FK = "fk_questions_material_id"

#: Zapolnitev izvora iz materiala. Dialekt-nevtralen `UPDATE` s poizvedbo v
#: `SET`, ker `UPDATE ... FROM` na SQLite ne obstaja.
ZAPOLNI_IZVOR = """
UPDATE questions
   SET subject = (SELECT m.subject FROM materials m WHERE m.id = questions.material_id),
       material_taken_at = (SELECT m.taken_at FROM materials m WHERE m.id = questions.material_id)
 WHERE material_id IS NOT NULL
"""


def _questions_pred_migracijo() -> sa.Table:
    """Tabela `questions`, kakršno je pustila `0002_obdelava`.

    Potrebna je za `batch_alter_table` nad SQLite, ki tabelo prepiše na novo
    in zato potrebuje njeno definicijo. Tuji ključ je tu **poimenovan**,
    čeprav v bazi ni: paketni način dela nad to definicijo in ne nad
    odsevom baze, `drop_constraint` pa brez imena ne more prijeti.
    """
    return sa.Table(
        "questions",
        sa.MetaData(),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("material_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["material_id"], ["materials.id"], ondelete="CASCADE", name=STARI_FK
        ),
        sa.Index("ix_questions_material_id", "material_id"),
    )


def _questions_po_migraciji() -> sa.Table:
    """Tabela `questions` po tej migraciji — za `downgrade` na SQLite."""
    return sa.Table(
        "questions",
        sa.MetaData(),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("material_id", sa.String(length=36), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(length=16), nullable=True),
        sa.Column("material_taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["material_id"], ["materials.id"], ondelete="SET NULL", name=NOVI_FK
        ),
        sa.Index("ix_questions_material_id", "material_id"),
    )


def upgrade() -> None:
    """Doda arhiv, prevesi tuji ključ na `SET NULL` in zapolni izvor."""
    for ime, tip in STOLPCI_ARHIVA:
        op.add_column("materials", sa.Column(ime, tip, nullable=True))

    # Tuji ključ najprej, šele nato novi stolpci: paketni način tabelo prepiše
    # po definiciji iz `copy_from`, in stolpca, ki ga tam ni, bi ob tem
    # izgubil.
    if op.get_context().dialect.name == "sqlite":
        with op.batch_alter_table(
            "questions", copy_from=_questions_pred_migracijo(), recreate="always"
        ) as paket:
            paket.alter_column(
                "material_id", existing_type=sa.String(length=36), nullable=True
            )
            paket.drop_constraint(STARI_FK, type_="foreignkey")
            paket.create_foreign_key(
                NOVI_FK, "materials", ["material_id"], ["id"], ondelete="SET NULL"
            )
    else:
        op.alter_column(
            "questions", "material_id", existing_type=sa.String(length=36), nullable=True
        )
        op.drop_constraint(STARI_FK, "questions", type_="foreignkey")
        op.create_foreign_key(
            NOVI_FK, "questions", "materials", ["material_id"], ["id"], ondelete="SET NULL"
        )

    for ime, tip in STOLPCI_IZVORA:
        op.add_column("questions", sa.Column(ime, tip, nullable=True))

    op.execute(ZAPOLNI_IZVOR)


def downgrade() -> None:
    """Vrne shemo v stanje `0002_obdelava`.

    **Vprašanja brez materiala se pri tem izbrišejo.** Shema pred to migracijo
    jih ne zna zapisati (`material_id` je tam `NOT NULL`), zato jih ni kam
    vrniti. To je znana in edina nepovratna poteza tega `downgrade`; nastopi
    samo tam, kjer je bil kak material že dokončno izbrisan.
    """
    op.execute("DELETE FROM questions WHERE material_id IS NULL")

    if op.get_context().dialect.name == "sqlite":
        # Vse v enem prepisu tabele: dva spuščena stolpca, vrnjena
        # obveznost in tuji ključ nazaj na `CASCADE`.
        with op.batch_alter_table(
            "questions", copy_from=_questions_po_migraciji(), recreate="always"
        ) as paket:
            for ime, _ in STOLPCI_IZVORA:
                paket.drop_column(ime)
            paket.alter_column(
                "material_id", existing_type=sa.String(length=36), nullable=False
            )
            paket.drop_constraint(NOVI_FK, type_="foreignkey")
            paket.create_foreign_key(
                STARI_FK, "materials", ["material_id"], ["id"], ondelete="CASCADE"
            )
    else:
        for ime, _ in STOLPCI_IZVORA:
            op.drop_column("questions", ime)
        op.alter_column(
            "questions", "material_id", existing_type=sa.String(length=36), nullable=False
        )
        op.drop_constraint(NOVI_FK, "questions", type_="foreignkey")
        op.create_foreign_key(
            STARI_FK, "questions", "materials", ["material_id"], ["id"], ondelete="CASCADE"
        )

    with op.batch_alter_table("materials") as paket:
        for ime, _ in STOLPCI_ARHIVA:
            paket.drop_column(ime)
