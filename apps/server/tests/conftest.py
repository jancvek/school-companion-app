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
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import naredi_tovarno_sej
from app.main import create_app
from app.models import Base
from app.settings import Settings

#: Ključ, ki v testih velja za pravega.
KLJUC = "kljuc-za-teste-dovolj-dolg"

#: Spremenljivke okolja, ki jih `Settings` prebere sama.
#:
#: `Settings` je `BaseSettings`: vsako polje, ki ga klicatelj ne poda, pride iz
#: okolja. Na stroju lastnika sta `OPENAI_API_KEY` in `API_KEY` povsem
#: pričakovani imeni — in če bi ju zbirka podedovala, bi `create_app` zgradil
#: **pravi** odjemalec OpenAI, `TestClient` bi pognal življenjski cikel, worker
#: bi stekel in testne slike bi zares odpotovale na api.openai.com, na račun
#: lastnika. „Testi ne kličejo omrežja" mora biti lastnost kode, ne lastnost
#: stroja, na katerem tečejo (CLAUDE.md: zbirka je zelena tudi na svežem klonu).
OKOLJSKE_NASTAVITVE = (
    "API_KEY",
    "DATABASE_URL",
    "IMAGES_DIR",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_TIMEOUT_SECONDS",
    "WORKER_INTERVAL_SECONDS",
)


@pytest.fixture(scope="session", autouse=True)
def okolje_brez_nastavitev() -> Iterator[None]:
    """Za celo sejo odstrani spremenljivke, ki jih `Settings` bere sama.

    Velja povsod, tudi tam, kjer test `Settings()` ustvari sam. Posamezen test
    si sme spremenljivko z `monkeypatch.setenv` vrniti, kadar prav njo
    preizkuša.
    """
    with pytest.MonkeyPatch.context() as okolje:
        for ime in OKOLJSKE_NASTAVITVE:
            okolje.delenv(ime, raising=False)
        yield


@pytest.fixture
def slike(tmp_path: Path) -> Path:
    """Mapa, ki v testih igra `/data/images`."""
    mapa = tmp_path / "images"
    mapa.mkdir()
    return mapa


def naredi_testne_nastavitve(slike: Path) -> Settings:
    """Nastavitve ene testne instance.

    **Vsako polje je podano izrecno.** Privzetek bi prišel iz okolja, in prav
    `openai_api_key` je tisto, katerega odsotnost drži worker (in s tem celo
    zbirko) stran od omrežja — glej `OKOLJSKE_NASTAVITVE` zgoraj.

    Funkcija in ne samo fixture: fixture nastane **pred** telesom testa, zato
    test, ki hoče preveriti prav odpornost na okolje, spremenljivke z
    `monkeypatch.setenv` ne more nastaviti pravočasno. Tak test kliče to
    funkcijo sam, in s tem preverja isto kodo, ki jo dobijo vsi ostali.

    Ime se namenoma ne začne s `test`: `python_functions = test*` bi tako
    funkcijo pobral kot testno.
    """
    return Settings(
        api_key=KLJUC,
        database_url="sqlite://",
        images_dir=slike,
        openai_api_key="",
        openai_model="model-ki-se-ne-uporabi",
        openai_timeout_seconds=1.0,
        worker_interval_seconds=0.01,
    )


@pytest.fixture
def nastavitve(slike: Path) -> Settings:
    """Nastavitve za teste, ki jih ne zanima, od kod pridejo."""
    return naredi_testne_nastavitve(slike)


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
def tovarna_sej(motor: Engine) -> sessionmaker[Session]:
    """Tovarna sej nad testno bazo.

    Obdelava (V1-R03) dela mimo zahtev HTTP in ima za vsak korak svojo sejo,
    zato jo testi poganjajo neposredno nad tem, ne prek odjemalca.
    """
    return naredi_tovarno_sej(motor)


@pytest.fixture
def aplikacija(nastavitve: Settings, motor: Engine) -> FastAPI:
    """Aplikacija nad testno bazo in testno mapo za slike."""
    return create_app(nastavitve=nastavitve, motor=motor)


@pytest.fixture
def odjemalec(aplikacija: FastAPI) -> Iterator[TestClient]:
    """Odjemalec brez privzetega ključa — vsak test ga pošlje sam."""
    with TestClient(aplikacija) as odjemalec:
        yield odjemalec
