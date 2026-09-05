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
from sqlalchemy import create_engine, inspect

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


def test_migrirana_shema_se_ujema_z_modeli(baza: str) -> None:
    """Če se model in migracija razideta, mora to javiti test, ne namestitev."""
    command.upgrade(alembic_nastavitve(baza), "head")

    iz_migracije = create_engine(baza)
    iz_modelov = create_engine("sqlite://")
    try:
        Base.metadata.create_all(iz_modelov)

        stolpci_migracije = {
            (s["name"], type(s["type"]).__name__, s["nullable"])
            for s in inspect(iz_migracije).get_columns("materials")
        }
        stolpci_modelov = {
            (s["name"], type(s["type"]).__name__, s["nullable"])
            for s in inspect(iz_modelov).get_columns("materials")
        }

        assert stolpci_migracije == stolpci_modelov
    finally:
        iz_migracije.dispose()
        iz_modelov.dispose()


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
