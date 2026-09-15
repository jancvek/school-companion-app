"""Družina kot lastnik podatkov (V3-R01).

Tabela `families` in obvezen `family_id` na `materials`, `questions`,
`quizzes` in `question_attempts`. Vse obstoječe vrstice dobijo družino
**Cvek**, vse obstoječe slike se premaknejo v njeno mapo. Razlogi so v
`docs/odlocitve/ADR-025` in `ADR-029`, postopek v `docs/plan/V3-R01.md`.

Štiri stvari, ki niso očitne:

- **Cvek ima stalen `id`.** Premik datotek ni del transakcije baze. Če
  migracija pade po premiku, se baza vrne, datoteke pa ostanejo v novi mapi;
  ponovni zagon mora ciljati isto mapo, sicer bi slike obtičale v mapi družine,
  ki je nihče ne pozna.
- **Premik je idempotenten.** Vir obstaja in cilja ni → premakni; vira ni →
  pusti. Pot v bazi se prepiše v vsakem primeru. Tako prekinjen in neprekinjen
  zagon prideta do istega stanja.
- **Prepiše se samo pot slike, ki leži neposredno v korenu `IMAGES_DIR`.** Pot
  drugje ostane, kakršna je — aplikacija jo je že doslej štela za „ni na disku".
  Datoteke brez vrstice in ostanki v `.tmp/` ostanejo nedotaknjeni.
- **Isto velja v obratno smer.** `downgrade` slike vrne pred DDL; če DDL nato
  pade, ostane baza na `0007` s potmi v mapi Cvek, slike pa so že v korenu.
  Pozdravi se s **ponovnim `downgrade`** (enako idempotenten), ne z `upgrade`.

Revision ID: 0007_druzine
Revises: 0006_poskusi
"""

import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0007_druzine"
down_revision: str | None = "0006_poskusi"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DRUZINE = "families"
STOLPEC = "family_id"

#: Tabele, ki dobijo `family_id`. `quiz_items` ga ne dobi (`ADR-029` C).
TABELE = ("materials", "questions", "quizzes", "question_attempts")

#: Stalen `id` družine Cvek — glej docstring modula.
CVEK_ID = "5b0f6c2e-8d3a-4c7e-9a1b-2f4d6e8c0a13"
CVEK_IME = "Cvek"

SPOROCILO_BREZ_MAPE = (
    "Manjka spremenljivka okolja IMAGES_DIR. Migracija 0007_druzine premakne "
    "slike v mapo družine in mora vedeti, kje so. V Docker Compose jo poda servis "
    "`api`; pri ročnem zagonu jo izvozi sam (glej apps/server/okolje.primer)."
)


def _kljuc(tabela: str) -> str:
    return f"fk_{tabela}_{STOLPEC}"


def _indeks(tabela: str) -> str:
    return f"ix_{tabela}_{STOLPEC}"


def _koren_slik(povezava: sa.Connection) -> Path | None:
    """Mapa slik iz okolja, ali `None`, kadar ni kaj premikati.

    Brez `IMAGES_DIR` nad bazo z materiali je napaka: tih privzetek bi na
    razvojnem stroju prepisal poti v bazi, datotek pa ne bi premaknil.
    """
    vrednost = os.environ.get("IMAGES_DIR")
    if vrednost:
        return Path(vrednost)
    if povezava.execute(sa.text("SELECT 1 FROM materials")).first() is None:
        return None
    raise RuntimeError(SPOROCILO_BREZ_MAPE)


def _prestavi_slike(povezava: sa.Connection, iz_mape: Path, v_mapo: Path) -> None:
    """Poti slik iz `iz_mape` prepiše v `v_mapo` in datoteke premakne. Idempotentno."""
    iz = iz_mape.resolve(strict=False)
    vrstice = povezava.execute(sa.text("SELECT id, image_path FROM materials")).all()
    for material_id, image_path in vrstice:
        stara = Path(image_path)
        if stara.parent.resolve(strict=False) != iz:
            continue

        nova = v_mapo / stara.name
        povezava.execute(
            sa.text("UPDATE materials SET image_path = :pot WHERE id = :id"),
            {"pot": str(nova), "id": material_id},
        )
        if stara.is_file() and not nova.exists():
            nova.parent.mkdir(parents=True, exist_ok=True)
            stara.replace(nova)


def upgrade() -> None:
    """Ustvari `families` s Cvek, pripiše družino vsem vrsticam, premakne slike."""
    povezava = op.get_bind()
    # Pred vsakim DDL: na SQLite DDL ni v transakciji, zato bi padec pozneje
    # pustil napol spremenjeno shemo.
    koren = _koren_slik(povezava)

    op.create_table(
        DRUZINE,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Tip na parametru, da čas pretvori SQLAlchemy in ne privzeti adapter
    # sqlite3, ki je od Pythona 3.12 opuščen.
    povezava.execute(
        sa.text(
            "INSERT INTO families (id, name, created_at) VALUES (:id, :ime, :kdaj)"
        ).bindparams(sa.bindparam("kdaj", type_=sa.DateTime(timezone=True))),
        {"id": CVEK_ID, "ime": CVEK_IME, "kdaj": datetime.now(UTC)},
    )

    for tabela in TABELE:
        # Najprej `NULL`-abilen, nato zapolnjen, šele nato obvezen: `NOT NULL`
        # brez privzetka nad polno tabelo bi `ADD COLUMN` zavrnil.
        op.add_column(tabela, sa.Column(STOLPEC, sa.String(length=36), nullable=True))
        povezava.execute(
            sa.text(f"UPDATE {tabela} SET {STOLPEC} = :id"),
            {"id": CVEK_ID},
        )
        # Na SQLite paketni način tabelo prepiše (`ALTER` omejitve tam ni), na
        # Postgresu izvede navadne `ALTER`.
        with op.batch_alter_table(tabela) as paket:
            paket.alter_column(STOLPEC, existing_type=sa.String(length=36), nullable=False)
            paket.create_foreign_key(_kljuc(tabela), DRUZINE, [STOLPEC], ["id"])
            paket.create_index(_indeks(tabela), [STOLPEC])

    # Datoteke zadnje: kar je pred njimi, se ob napaki vrne samo.
    if koren is not None:
        _prestavi_slike(povezava, koren, koren / CVEK_ID)


def downgrade() -> None:
    """Vrne shemo v stanje `0006_poskusi` in slike v koren.

    **Z več kot eno družino se ne izvede.** Shema pred to migracijo družin ne
    pozna, zato bi vrnitev podatke dveh družin nepovratno pomešala.

    Vrstic ne izgubi nobene; izgubi se samo podatek o družini, ki je pri eni
    sami družini izpeljiv.
    """
    povezava = op.get_bind()
    druzine = list(povezava.execute(sa.text("SELECT id FROM families")).scalars())
    if len(druzine) > 1:
        raise RuntimeError(
            f"V bazi je {len(druzine)} družin. Vrnitev pred 0007_druzine bi pomešala "
            "njihove podatke in slike, zato se ne izvede. Najprej se odloči, katera "
            "družina ostane."
        )

    koren = _koren_slik(povezava)
    if koren is not None and druzine:
        _prestavi_slike(povezava, koren / druzine[0], koren)

    for tabela in reversed(TABELE):
        with op.batch_alter_table(tabela) as paket:
            paket.drop_index(_indeks(tabela))
            paket.drop_constraint(_kljuc(tabela), type_="foreignkey")
            paket.drop_column(STOLPEC)

    op.drop_table(DRUZINE)
