"""Skupna postavitev testov strežnika.

Baza je SQLite v pomnilniku, ne Postgres (odločitev 2 v `docs/plan/V1-R02.md`):
zbirka mora biti zelena na svežem klonu in brez Dockerja. Zato gre vsa
poslovna logika skozi plast repozitorija in nikjer ne uporablja tipov ali
stavkov, ki bi jih poznal samo Postgres.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any, NamedTuple
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import prijava
from app.db import PrijavaRepository, SejaUporabnika, naredi_tovarno_sej
from app.main import create_app
from app.models import (
    POVERILNICA_GESLO,
    VLOGA_OTROK,
    VLOGA_STARS,
    Base,
    Credential,
    Family,
    User,
)
from app.settings import Settings

#: Poverilnici, ki jih uporabljajo testi. Gesli sta dolgi toliko, kot zahteva
#: `app/prijava.py` za svojo vlogo — prekratko geslo zavrne ukaz, ne prijava,
#: a test naj ne stoji na kombinaciji, ki v resnici ne more nastati.
#: Otrokovo je od V3-R04 vsaj 8 znakov (`docs/odlocitve/ADR-036` E).
STARS_IDENTIFIKATOR = "stars@primer.test"
GESLO_STARSA = "geslo-starsa-12"
OTROK_IDENTIFIKATOR = "otrok"
GESLO_OTROKA = "geslo-otroka"

#: Stalen `id` otroka družine Cvek (V3-R07). Stalen in ne `uuid4()`, ker ga
#: pomožne funkcije testov potrebujejo kot **privzetek** pri gradnji snovi,
#: kvizov in poskusov — `child_id` je od `ADR-039` obvezen. Test, ki
#: potrebuje drugega otroka, ga ustvari z izrecnim `user_id`.
OTROK_ID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


@cache
def zgostitev(geslo: str) -> str:
    """Zgostitev gesla, izračunana največ enkrat na zagon zbirke.

    argon2 je namenoma počasen (~60 ms). Brez te predpomnilne plasti bi vsak
    test, ki potrebuje uporabnika, plačal to ceno znova.
    """
    return prijava.zgosti_geslo(geslo)


def je_seja(stavek: str) -> bool:
    """Ali je ta stavek SQL branje ali osvežitev seje.

    Števci poizvedb v `test_kvizi.py` in `test_rezultat.py` merijo, koliko
    poizvedb naredi **stran**. Branje seje je od V3-R03 infrastruktura vsake
    zahteve pod `/admin` (`ADR-035` A) in ni poizvedba strani; njegovo ceno —
    natanko ena na zahtevo — varuje `test_druzine.py`.

    Ujemanje je po stavku nad tabelo `sessions`, ne po pojavitvi besede
    kjerkoli: prihodnja poizvedba, ki bi `sessions` samo omenila v `JOIN`, bi
    se sicer tiho prenehala šteti.
    """
    zacetki = ("FROM sessions", "UPDATE sessions", "DELETE FROM sessions")
    return any(zacetek in stavek for zacetek in zacetki)


#: Družina, ki jo ima vsaka testna baza (V3-R01). Isti `id` kot Cvek v
#: migraciji `0007_druzine`, da je baza po `create_all` enaka migrirani.
CVEK_ID = "5b0f6c2e-8d3a-4c7e-9a1b-2f4d6e8c0a13"

#: Spremenljivke okolja, ki jih `Settings` prebere sama.
#:
#: `Settings` je `BaseSettings`: vsako polje, ki ga klicatelj ne poda, pride iz
#: okolja. Na stroju lastnika je `OPENAI_API_KEY` povsem pričakovano ime — in
#: če bi ga zbirka podedovala, bi `create_app` zgradil **pravi** odjemalec
#: OpenAI, `TestClient` bi pognal življenjski cikel, worker bi stekel in testne
#: slike bi zares odpotovale na api.openai.com, na račun lastnika. „Testi ne
#: kličejo omrežja" mora biti lastnost kode, ne lastnost stroja, na katerem
#: tečejo (CLAUDE.md: zbirka je zelena tudi na svežem klonu).
OKOLJSKE_NASTAVITVE = (
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
    """Mapa, ki v testih igra `/data/images`.

    Vrne **koren**, kot `Settings.images_dir`. Mapa družine Cvek je že
    ustvarjena, ker vanjo pišejo pomočniki testov (`slike / CVEK_ID`).
    """
    mapa = tmp_path / "images"
    (mapa / CVEK_ID).mkdir(parents=True)
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
    # Družina, ki jo po `0007_druzine` ima vsaka baza; brez nje vsaka pot pade
    # na izbiri družine (`app/dependencies.py`).
    with Session(motor) as seja:
        seja.add(Family(id=CVEK_ID, name="Cvek", created_at=datetime(2026, 9, 1, tzinfo=UTC)))
        seja.commit()
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


class PrijavljenOdjemalec(TestClient):
    """`TestClient`, ki v obrazce pod `/admin` sam doda CSRF žeton svoje seje.

    Brez tega bi vsak od približno stotih `POST` v zbirki nosil isto vrstico o
    žetonu, in test bi govoril o CSRF namesto o tem, kar preverja. Žeton se
    doda **samo, kadar ga test ni podal** — test, ki CSRF preverja, ga poda
    (napačnega ali praznega) in ga ta razred ne prepiše.

    `/admin/login` je izvzet: tam žeton ne pride iz seje (te še ni), ampak iz
    piškotka prijavnega obrazca, in ga testi prijave postavijo sami.
    """

    #: CSRF žeton seje tega odjemalca.
    csrf: str = ""

    def post(self, url: str, **kwargs: Any) -> Any:  # type: ignore[override]
        pot = str(url)
        if pot.startswith("/admin") and pot != prijava.POT_PRIJAVE:
            podatki = kwargs.get("data")
            if podatki is None:
                kwargs["data"] = {"csrf": self.csrf}
            elif isinstance(podatki, dict) and "csrf" not in podatki:
                kwargs["data"] = {**podatki, "csrf": self.csrf}
        return super().post(url, **kwargs)


def ustvari_starsa(
    motor: Engine,
    *,
    user_id: str | None = None,
    family_id: str = CVEK_ID,
    identifikator: str = STARS_IDENTIFIKATOR,
    prikazno_ime: str = "Dejan",
    geslo: str | None = GESLO_STARSA,
    vloga: str = VLOGA_STARS,
    aktiven: bool = True,
    lastnik_sistema: bool = False,
) -> str:
    """Ustvari uporabnika s poverilnico in vrne njegov `id`.

    `geslo=None` pomeni račun brez nastavljenega gesla — stanje, v katerem
    uporabnika pusti migracija `0008_uporabniki`. `lastnik_sistema` postavi
    zastavico, ki jo sicer postavi ista migracija; poti `V3-R06` je ne
    podelijo nikomur (`docs/odlocitve/ADR-038` G).
    """
    user_id = user_id if user_id is not None else str(uuid4())
    zdaj = datetime.now(UTC)
    with Session(motor) as seja:
        seja.add(
            User(
                id=user_id,
                family_id=family_id,
                role=vloga,
                display_name=prikazno_ime,
                is_system_owner=lastnik_sistema,
                is_active=aktiven,
                created_at=zdaj,
            )
        )
        seja.add(
            Credential(
                id=str(uuid4()),
                user_id=user_id,
                kind=POVERILNICA_GESLO,
                identifier=identifikator,
                secret_hash=zgostitev(geslo) if geslo is not None else None,
                created_at=zdaj,
                updated_at=zdaj,
            )
        )
        seja.commit()
    return user_id


class SejaTesta(NamedTuple):
    """Seja, ki jo je postavil test, skupaj z žetonom.

    Oboje, ker je v bazi samo zgostitev žetona: brskalnik potrebuje `csrf`,
    telefon pa žeton. Vračanje dvojice je cenejše od globalne preslikave, ki
    bi živela čez cel zagon zbirke.
    """

    zeton: str
    seja: SejaUporabnika

    @property
    def glave(self) -> dict[str, str]:
        """Glava, s katero se s to sejo izkaže telefon (V3-R04)."""
        return {"Authorization": f"Bearer {self.zeton}"}


def ustvari_sejo(motor: Engine, user_id: str, *, potece: datetime | None = None) -> SejaTesta:
    """Postavi sejo danemu uporabniku.

    Seja nastane **mimo prijavne poti**, ker skoraj noben test v zbirki ne
    preverja prijave, ampak to, kar je za njo; prava prijava bi vsakemu od njih
    dodala eno zgostitev argon2 (~60 ms) in en korak brez pomena za test.
    Prijavni poti imata svoje teste v `tests/test_prijava.py`.

    `potece` poda test, ki potrebuje **poteklo** sejo; privzeto je rok običajen.
    """
    zeton = prijava.nov_zeton()
    zdaj = datetime.now(UTC)
    with Session(motor) as seja_baze:
        repo = PrijavaRepository(seja_baze)
        repo.ustvari_sejo(
            user_id=user_id,
            token_hash=prijava.zgostitev_zetona(zeton),
            csrf_token=prijava.nov_zeton(),
            ko=zdaj,
            potece=potece if potece is not None else zdaj + prijava.TRAJANJE_SEJE,
            device_label="testi",
        )
        seja = repo.seja(prijava.zgostitev_zetona(zeton))
    assert seja is not None
    return SejaTesta(zeton, seja)


def prijavi(odjemalec: PrijavljenOdjemalec, motor: Engine, user_id: str) -> None:
    """Postavi sejo danemu uporabniku in jo naloži v odjemalca brskalnika."""
    postavljena = ustvari_sejo(motor, user_id)
    odjemalec.cookies.set(prijava.PISKOTEK_SEJE, postavljena.zeton)
    odjemalec.csrf = postavljena.seja.csrf_token


def ustvari_otroka(
    motor: Engine,
    *,
    user_id: str | None = OTROK_ID,
    family_id: str = CVEK_ID,
    identifikator: str = OTROK_IDENTIFIKATOR,
    prikazno_ime: str = "Maša",
    geslo: str | None = GESLO_OTROKA,
    aktiven: bool = True,
) -> str:
    """Otrok v družini — uporabnik, ki se prijavlja na telefonu (V3-R04).

    Privzeti `user_id` je stalen (`OTROK_ID`), da se ujema s privzetkom, s
    katerim pomožne funkcije testov gradijo snov, kvize in poskuse (V3-R07).
    Drugega otroka test ustvari z izrecnim `user_id` in svojim
    `identifikator` — ta je enoličen čez celo namestitev.
    """
    return ustvari_starsa(
        motor,
        user_id=user_id,
        family_id=family_id,
        identifikator=identifikator,
        prikazno_ime=prikazno_ime,
        geslo=geslo,
        vloga=VLOGA_OTROK,
        aktiven=aktiven,
    )


@pytest.fixture
def otrok(motor: Engine) -> str:
    """Otrok družine Cvek, v čigar imenu govorijo poti telefona."""
    return ustvari_otroka(motor)


@pytest.fixture
def telefon(motor: Engine, otrok: str) -> SejaTesta:
    """Veljavna seja telefona; `telefon.glave` gre v vsako zahtevo telefona."""
    return ustvari_sejo(motor, otrok)


@pytest.fixture
def stars(motor: Engine) -> str:
    """Starš družine Cvek, s katerim so prijavljeni testi admin strani."""
    return ustvari_starsa(motor)


@pytest.fixture
def odjemalec(aplikacija: FastAPI, motor: Engine, stars: str) -> Iterator[PrijavljenOdjemalec]:
    """Odjemalec s sejo starša družine Cvek.

    Žetona telefona ne nosi: poti telefona ga v vsakem testu podajo same
    (fixture `telefon`), admin poti pa ga ne potrebujejo — `/admin` je izvzet
    iz `ZetonMiddleware` in ima svojo plast.

    Naslov je **`https`**, ker ima piškotek seje zastavico `Secure` in ga
    odjemalec čez `http` ne bi poslal — kar je natanko obnašanje brskalnika.
    """
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
        prijavi(odjemalec, motor, stars)
        yield odjemalec


