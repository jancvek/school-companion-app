"""Vrstni red vstavljanja, kadar ena transakcija ustvari starša in otroka tujega ključa.

Popravek `V6-R02`: registracija je na produkciji padla s 500, ker je SQLAlchemy
`credentials` vstavil pred `users`. Med `Family`, `User` in `Credential` ni
`relationship()`, zato vrstnega reda `INSERT` ne zagotavlja nič razen izrecnega
`flush()`; Postgres tuje ključe preverja ob vsakem stavku.

Skupni `motor` iz `conftest.py` tega ne ujame: SQLite brez
`PRAGMA foreign_keys=ON` ključev ne uveljavlja. Ti testi zato tečejo nad svojim
motorjem z vklopljenimi ključi in poleg tega berejo **zaporedje izvedenih
stavkov** — vklopljeni ključi sami bi ostali zeleni vsakič, ko bi vrstni red
izpadel prav po sreči.
"""

import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import (
    ClaniRepository,
    DruzineRepository,
    IdentifikatorZaseden,
    PrijavaRepository,
    naredi_tovarno_sej,
)
from app.models import VLOGA_STARS, Base, Credential, Family, LoginAttempt, User
from tests.conftest import CVEK_ID

KO = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)

_INSERT = re.compile(r"^\s*INSERT INTO (\w+)", re.IGNORECASE)


@pytest.fixture
def motor_s_kljuci() -> Iterator[Engine]:
    """Kot `motor` iz `conftest.py`, a s tujimi ključi, ki veljajo — kot na Postgresu."""
    motor = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(motor, "connect")
    def _vklopi_kljuce(povezava: Any, _zapis: Any) -> None:
        povezava.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(motor)
    with Session(motor) as seja:
        seja.add(Family(id=CVEK_ID, name="Cvek", created_at=datetime(2026, 9, 1, tzinfo=UTC)))
        seja.commit()
    yield motor
    motor.dispose()


@pytest.fixture
def vstavljanja(motor_s_kljuci: Engine) -> list[str]:
    """Imena tabel v vrstnem redu, v katerem je motor izvedel `INSERT`."""
    tabele: list[str] = []

    @event.listens_for(motor_s_kljuci, "before_cursor_execute")
    def _zabelezi(
        _povezava: Any, _kazalec: Any, stavek: str, _parametri: Any, _kontekst: Any, _vec: bool
    ) -> None:
        zadetek = _INSERT.match(stavek)
        if zadetek is not None:
            tabele.append(zadetek.group(1))

    return tabele


def _seja(motor: Engine) -> Session:
    """Seja, kakršno dobi zahteva — iz iste tovarne kot v aplikaciji."""
    return naredi_tovarno_sej(motor)()


def _stetje(motor: Engine) -> tuple[int, int, int, int]:
    """(družin, uporabnikov, poverilnic, poskusov prijave)."""
    with Session(motor) as seja:
        return (
            seja.scalar(select(func.count(Family.id))) or 0,
            seja.scalar(select(func.count(User.id))) or 0,
            seja.scalar(select(func.count(Credential.id))) or 0,
            seja.scalar(select(func.count(LoginAttempt.id))) or 0,
        )


def _registriraj(seja: Session, *, sub: str = "sub-1") -> None:
    PrijavaRepository(seja).registriraj(
        ime_druzine="Kovačevi",
        prikazno_ime="Ana",
        sub=sub,
        email="ana@primer.test",
        oznaka_poskusa="registracija",
        ip_address=None,
        ko=KO,
    )


def _odpri_druzino(seja: Session, *, identifier: str = "ana@primer.test") -> None:
    DruzineRepository(seja).ustvari_z_prvim_starsem(
        ime_druzine="Kovačevi",
        prikazno_ime="Ana",
        identifier=identifier,
        secret_hash="zgostitev",
        ko=KO,
    )


def _dodaj_clana(seja: Session, *, identifier: str = "ana@primer.test") -> None:
    ClaniRepository(seja, CVEK_ID).ustvari_clana(
        role=VLOGA_STARS,
        display_name="Ana",
        identifier=identifier,
        secret_hash="zgostitev",
        ko=KO,
    )


#: Pot, tabele v edinem vrstnem redu, ki ga tuji ključi dovolijo, in koliko
#: vrstic (družin, uporabnikov, poverilnic, poskusov) pot doda.
POTI: list[Any] = [
    pytest.param(
        _registriraj, ["families", "users", "credentials"], (1, 1, 1, 1), id="registriraj"
    ),
    pytest.param(
        _odpri_druzino,
        ["families", "users", "credentials"],
        (1, 1, 1, 0),
        id="ustvari_z_prvim_starsem",
    ),
    pytest.param(_dodaj_clana, ["users", "credentials"], (0, 1, 1, 0), id="ustvari_clana"),
]


class TestKljuciVeljajo:
    """Varovalo testa samega: brez tega bi bil ves modul zelen tudi brez popravka."""

    def test_motor_zavrne_poverilnico_brez_uporabnika(self, motor_s_kljuci: Engine) -> None:
        with Session(motor_s_kljuci) as seja:
            seja.add(
                Credential(
                    id="p-1",
                    user_id="ni-takega",
                    kind="password",
                    identifier="nikogar@primer.test",
                    secret_hash=None,
                    created_at=KO,
                    updated_at=KO,
                )
            )
            with pytest.raises(IntegrityError):
                seja.commit()


class TestVrstniRed:
    @pytest.mark.parametrize(("pot", "red", "dodano"), POTI)
    def test_stars_tujega_kljuca_je_vstavljen_pred_otrokom(
        self,
        motor_s_kljuci: Engine,
        vstavljanja: list[str],
        pot: Callable[[Session], None],
        red: list[str],
        dodano: tuple[int, int, int, int],
    ) -> None:
        prej = _stetje(motor_s_kljuci)

        with _seja(motor_s_kljuci) as seja:
            pot(seja)

        # `login_attempts` tujega ključa nima; kje v zaporedju pristane, ni
        # del pogodbe.
        assert [tabela for tabela in vstavljanja if tabela != "login_attempts"] == red
        po = _stetje(motor_s_kljuci)
        assert tuple(b - a for a, b in zip(prej, po, strict=True)) == dodano

    @pytest.mark.parametrize(("pot", "red", "dodano"), POTI)
    def test_zaseden_identifikator_ne_pusti_nicesar(
        self,
        motor_s_kljuci: Engine,
        pot: Callable[[Session], None],
        red: list[str],
        dodano: tuple[int, int, int, int],
    ) -> None:
        """Izrecen `flush()` ne sme načeti „ene transakcije": družina in starš,
        vstavljena pred poverilnico, ki pade na enoličnosti, morata izginiti."""
        with _seja(motor_s_kljuci) as seja:
            pot(seja)
        po_prvi = _stetje(motor_s_kljuci)

        with _seja(motor_s_kljuci) as seja, pytest.raises(IdentifikatorZaseden):
            pot(seja)

        assert _stetje(motor_s_kljuci) == po_prvi
