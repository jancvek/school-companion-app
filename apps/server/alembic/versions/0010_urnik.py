"""Urnik otroka in njegovi vnosi (V3-R09).

Dve novi tabeli in nič drugega: nobenega obstoječega stolpca se ta migracija
ne dotakne, zato obstoječih vrstic ni treba ne prepisovati ne polniti. Isti
razred kot `0005_kvizi`, ne kot `0007_druzine`, ki je podatke premikal.

Oblika je iz `docs/odlocitve/ADR-028` in `ADR-041`:

- `schedules` **nima** stolpca `status`. Veljavnost je os (`replaced_at IS
  NULL`), po istem vzorcu kot arhiv (`ADR-011`) in upokojitev vprašanj
  (`ADR-015`). Enoličnost veljavnega urnika uveljavlja ena pot pisanja v eni
  transakciji in **ne** delni indeks: tega bi bilo treba zapisati dvakrat, za
  SQLite in za Postgres, in dve različici istega pravila se razideta.
- `schedules` **nima** revizijske sledi klica, za razliko od `materials`.
  Potrjen urnik ni odgovor modela — starš ga vmes popravi —, zato bi sled ob
  njem opisovala nekaj, česar vrstica ne vsebuje (`ADR-042`).
- `schedule_entries` **nima** stolpca `family_id`. Vnos brez urnika ne obstaja
  (`schedule_id` je `NOT NULL`), zato je njegova družina družina urnika — ista
  izpeljava kot pri `quiz_items` (`ADR-029` C).
- `schedule_entries` **nima** stolpca za uro ali zaporedje. Urnik je množica
  predmetov na dan; dve uri istega predmeta zahtevata vsaj eno sliko in sta
  zato ista reč (`ADR-028`). To pove enoličnost para *dan + predmet*.

Revision ID: 0010_urnik
Revises: 0009_otrok_na_zapisu
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_urnik"
down_revision: str | None = "0009_otrok_na_zapisu"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Imena na enem mestu, da `upgrade` in `downgrade` ne moreta zdrsniti narazen
#: — isti razlog kot v `0005_kvizi`.
URNIKI = "schedules"
VNOSI = "schedule_entries"

#: Tuji ključi so poimenovani in ne prepuščeni dialektnemu privzetku.
#: `0003_arhiv` je moral ime ugibati; te napake ne ponavljamo.
KLJUC_DRUZINE = "fk_schedules_family_id"
KLJUC_OTROKA = "fk_schedules_child_id"
KLJUC_URNIKA = "fk_schedule_entries_schedule_id"

#: Enoličnost para *dan + predmet* znotraj urnika.
ENOLICNOST = "uq_schedule_entries_dan"


def upgrade() -> None:
    """Ustvari `schedules` in `schedule_entries`."""
    op.create_table(
        URNIKI,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("family_id", sa.String(length=36), nullable=False),
        sa.Column("child_id", sa.String(length=36), nullable=False),
        # Nepotrjenega urnika ni: predlog živi v obrazcu in nikoli v bazi
        # (`ADR-041` B). Zato je čas potrditve obvezen in stanja `draft` ni.
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        # `NULL` = veljaven urnik. Enosmerno; nazaj na `NULL` ne gre nikoli.
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
        # `NULL` ni manjkajoč podatek, ampak resnica o nastanku: ta urnik je
        # starš natipkal in ne prebral s slike (`ADR-041` E).
        sa.Column("image_path", sa.String(length=1024), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        # Brez `ondelete`, kot pri vseh ključih na `families` in `users`:
        # družina in račun se ne brišeta, ampak deaktivirata.
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], name=KLJUC_DRUZINE),
        sa.ForeignKeyConstraint(["child_id"], ["users.id"], name=KLJUC_OTROKA),
    )

    op.create_table(
        VNOSI,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("schedule_id", sa.String(length=36), nullable=False),
        # `date.weekday()`: 0 = ponedeljek … 4 = petek. Sobote in nedelje
        # urnik ne pozna (`ADR-041` F).
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=16), nullable=False),
        # „Ta predmet se ta dan ne slika" (`ADR-028` F2). Lastnost vnosa in ne
        # predmeta: seznam predmetov je skupen vsem družinam, pričakovanje pa
        # je last ene.
        sa.Column("skip_photo", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # `CASCADE`: vnos brez urnika nima pomena, enako kot postavka brez
        # kviza. To ne nasprotuje `ADR-012` — ta govori o vprašanjih, ki nosijo
        # statistiko in morajo snov preživeti.
        sa.ForeignKeyConstraint(
            ["schedule_id"], [f"{URNIKI}.id"], name=KLJUC_URNIKA, ondelete="CASCADE"
        ),
        sa.UniqueConstraint("schedule_id", "weekday", "subject", name=ENOLICNOST),
    )

    op.create_index(op.f(f"ix_{URNIKI}_family_id"), URNIKI, ["family_id"])
    op.create_index(op.f(f"ix_{URNIKI}_child_id"), URNIKI, ["child_id"])
    op.create_index(op.f(f"ix_{VNOSI}_schedule_id"), VNOSI, ["schedule_id"])


def downgrade() -> None:
    """Vrne shemo v stanje `0009_otrok_na_zapisu`.

    **Vsi urniki in vsi njihovi vnosi se pri tem izgubijo dokončno** — isti
    razred kot `downgrade` v `0005_kvizi`, kjer izginejo cele vrstice, in ne
    kot `0004`, kjer se izgubi le en podatek. Slike urnikov na disku ostanejo;
    ta migracija se datotek ne dotika ne v eno ne v drugo smer, zato je
    vrnitev čeznjo varna glede diska in nepovratna glede baze.

    Vrstni red je obrnjen glede na `upgrade` — najprej otrok, nato starš —
    sicer bi tuji ključ na Postgresu brisanje `schedules` zavrnil.
    """
    op.drop_index(op.f(f"ix_{VNOSI}_schedule_id"), table_name=VNOSI)
    op.drop_index(op.f(f"ix_{URNIKI}_child_id"), table_name=URNIKI)
    op.drop_index(op.f(f"ix_{URNIKI}_family_id"), table_name=URNIKI)
    op.drop_table(VNOSI)
    op.drop_table(URNIKI)
