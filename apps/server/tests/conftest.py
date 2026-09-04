"""Skupna postavitev testov strežnika.

Baza je SQLite v pomnilniku, ne Postgres (odločitev 2 v `docs/plan/V1-R02.md`):
zbirka mora biti zelena na svežem klonu in brez Dockerja. Zato gre vsa
poslovna logika skozi plast repozitorija in nikjer ne uporablja tipov ali
stavkov, ki bi jih poznal samo Postgres.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from app.main import create_app
from app.models import Base
from app.settings import Settings

#: Ključ, ki v testih velja za pravega.
KLJUC = "kljuc-za-teste"


@pytest.fixture
def slike(tmp_path: Path) -> Path:
    """Mapa, ki v testih igra `/data/images`."""
    mapa = tmp_path / "images"
    mapa.mkdir()
    return mapa


@pytest.fixture
def nastavitve(slike: Path) -> Settings:
    """Nastavitve ene testne instance."""
    return Settings(api_key=KLJUC, database_url="sqlite://", images_dir=slike)


@pytest.fixture
def motor() -> Iterator[Engine]:
    """SQLite v pomnilniku, deljen med nitmi.

    `TestClient` poganja endpointe v drugi niti kot test, zato privzeta
    omejitev SQLite na eno nit ne pride v poštev, `StaticPool` pa poskrbi, da
    vse niti vidijo isto bazo — sicer bi vsaka dobila svojo prazno.
    """
    motor = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(motor)
    yield motor
    motor.dispose()


@pytest.fixture
def aplikacija(nastavitve: Settings, motor: Engine) -> FastAPI:
    """Aplikacija nad testno bazo in testno mapo za slike."""
    return create_app(nastavitve=nastavitve, motor=motor)


@pytest.fixture
def odjemalec(aplikacija: FastAPI) -> Iterator[TestClient]:
    """Odjemalec brez privzetega ključa — vsak test ga pošlje sam."""
    with TestClient(aplikacija) as odjemalec:
        yield odjemalec
