"""Alembic migracija mora dati isto shemo kot modeli.

Zakaj to sploh potrebuje test: migracija je na kritični poti zagona — servis
`api` požene `alembic upgrade head` pred `uvicorn` (`docker-compose.yml`).
Napaka v njej pomeni, da vsebnik sploh ne vstane. Testi sicer shemo postavijo
z `Base.metadata.create_all`, zato bi se migracija in modeli lahko tiho
razšla, migracije pa nihče ne bi pognal do prve namestitve.

Test teče nad SQLite, ker Docker ni pogoj za zeleno zbirko (odločitev 2 v
`docs/plan/V1-R02.md`). Migracija je dialekt-varna: `CREATE EXTENSION vector`
se izvede samo nad Postgresom. Prav zato ostane `CREATE EXTENSION` **edino**,
česar ta test ne pokrije.
"""

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.models import Base

KOREN = Path(__file__).resolve().parent.parent


def alembic_nastavitve(database_url: str) -> Config:
    config = Config(str(KOREN / "alembic.ini"))
    config.set_main_option("script_location", str(KOREN / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture
def baza(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    # `DATABASE_URL` gre stran, čeprav ima izrecna nastavitev v `env.py` že
    # prednost. Ta test dela `downgrade base`; če bi se kdaj povezal na živo
    # bazo, bi v njej spustil tabelo `materials`. Dve ograji sta tu poceni,
    # posledica ene same napake pa ni.
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # Datoteka in ne `:memory:`: Alembic si odpre svojo povezavo, baza v
    # pomnilniku pa z njo ne bi bila ista.
    return f"sqlite:///{tmp_path / 'test.db'}"


def test_migracija_ustvari_tabelo_materials(baza: str) -> None:
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        assert "materials" in inspect(motor).get_table_names()
    finally:
        motor.dispose()


@pytest.mark.parametrize("tabela", ["materials", "questions"])
def test_migrirana_shema_se_ujema_z_modeli(baza: str, tabela: str) -> None:
    """Če se model in migracija razideta, mora to javiti test, ne namestitev.

    Primerja se **vsaka** tabela iz modelov, ne samo `materials`: nova tabela,
    ki bi jo kdo dodal samo v modele, bi sicer testom ušla in bi jo opazil
    šele vsebnik ob zagonu.
    """
    command.upgrade(alembic_nastavitve(baza), "head")

    iz_migracije = create_engine(baza)
    iz_modelov = create_engine("sqlite://")
    try:
        Base.metadata.create_all(iz_modelov)

        stolpci_migracije = {
            (s["name"], type(s["type"]).__name__, s["nullable"])
            for s in inspect(iz_migracije).get_columns(tabela)
        }
        stolpci_modelov = {
            (s["name"], type(s["type"]).__name__, s["nullable"])
            for s in inspect(iz_modelov).get_columns(tabela)
        }

        assert stolpci_migracije == stolpci_modelov
    finally:
        iz_migracije.dispose()
        iz_modelov.dispose()


def test_migracija_pokrije_vse_tabele_iz_modelov(baza: str) -> None:
    """Varovalo za test zgoraj: ta ima seznam tabel zapisan na roko.

    Brez te trditve bi bila enajsta tabela v modelih neopažena — parametri
    testa bi je preprosto ne omenjali in vse bi ostalo zeleno.
    """
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        iz_migracije = set(inspect(motor).get_table_names()) - {"alembic_version"}
        assert iz_migracije == set(Base.metadata.tables)
    finally:
        motor.dispose()


def test_vprasanja_kazejo_na_material(baza: str) -> None:
    """Tuji ključ s kaskado je druga mreža poleg kaskade v ORM.

    Na SQLite je brez `PRAGMA foreign_keys=ON` neaktiven, zato ga tu ne
    preverjamo z brisanjem, ampak v shemi — na Postgresu je prav on tisti, ki
    prepreči osirotela vprašanja pri brisanju mimo ORM.
    """
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        kljuci = inspect(motor).get_foreign_keys("questions")
        assert len(kljuci) == 1
        assert kljuci[0]["referred_table"] == "materials"
        assert kljuci[0]["constrained_columns"] == ["material_id"]
        assert kljuci[0]["referred_columns"] == ["id"]
        assert kljuci[0]["options"]["ondelete"].upper() == "CASCADE"
    finally:
        motor.dispose()


def test_obstojeci_zapis_prezivi_migracijo(baza: str) -> None:
    """Vrstica iz V1-R02 mora migracijo prestati nedotaknjena.

    To je smisel tega, da so novi stolpci `NULL`-abilni. Če bi kdaj kdo enemu
    dodal `nullable=False` brez privzetka, bi `upgrade` nad polno bazo padel —
    in vsebnik se ne bi zagnal.
    """
    config = alembic_nastavitve(baza)
    command.upgrade(config, "0001_materials")

    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            povezava.execute(
                text(
                    "INSERT INTO materials "
                    "(id, subject, taken_at, image_path, status, received_at) "
                    "VALUES ('star', 'MAT', '2026-09-01 08:00:00', "
                    "'/data/images/star.jpg', 'new', '2026-09-01 08:05:00')"
                )
            )

        command.upgrade(config, "head")

        with motor.connect() as povezava:
            vrstica = povezava.execute(
                text("SELECT status, transcript, readable FROM materials WHERE id = 'star'")
            ).one()

        # Status ostane `new`, torej ga worker pobere kot vsako drugo sliko;
        # novi stolpci so prazni, ne izmišljeni.
        assert vrstica.status == "new"
        assert vrstica.transcript is None
        assert vrstica.readable is None
    finally:
        motor.dispose()


def test_primarni_kljuc_je_id(baza: str) -> None:
    """Idempotentnost stoji na tem, da je `id` primarni ključ."""
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        assert inspect(motor).get_pk_constraint("materials")["constrained_columns"] == ["id"]
    finally:
        motor.dispose()


def test_migracija_se_da_razveljaviti(baza: str) -> None:
    config = alembic_nastavitve(baza)
    command.upgrade(config, "head")

    motor = create_engine(baza)
    try:
        # Najprej se prepričamo, da je migracija res tekla **nad to** bazo.
        # Brez tega bi bila zaključna trditev izpolnjena tudi, če bi Alembic
        # delal nad neko drugo bazo, ta pa bi bila ves čas prazna — in test bi
        # bil zelen prav takrat, ko bi bilo najbolj narobe.
        assert "materials" in inspect(motor).get_table_names()

        command.downgrade(config, "base")

        assert "materials" not in inspect(motor).get_table_names()
    finally:
        motor.dispose()


def test_izrecna_nastavitev_ima_prednost_pred_okoljem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regresija: `DATABASE_URL` ne sme preusmeriti migracije drugam.

    Če bi okolje premagalo izrecno nastavitev, bi `pytest` v lupini z
    izvoženim `DATABASE_URL` migriral živo bazo — in `downgrade base` bi v njej
    spustil tabelo `materials`.
    """
    ciljna = tmp_path / "ciljna.db"
    tuja = tmp_path / "tuja.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tuja}")

    command.upgrade(alembic_nastavitve(f"sqlite:///{ciljna}"), "head")

    assert ciljna.exists()
    # Tuje baze se migracija ne sme niti dotakniti.
    assert not tuja.exists()
