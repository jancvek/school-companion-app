"""Ukaz `nastavi-geslo` (V3-R03).

Geslo pride s tipkovnice in nikoli iz argumenta ali okolja
(`docs/odlocitve/ADR-035` G). Ta zbirka preverja tudi, da je v bazi zgostitev
argon2id in nikjer nič berljivega.
"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app import ukazi
from app.models import VLOGA_OTROK, Credential
from app.prijava import geslo_se_ujema
from tests.conftest import (
    GESLO_STARSA,
    OTROK_IDENTIFIKATOR,
    STARS_IDENTIFIKATOR,
    PrijavljenOdjemalec,
    ustvari_starsa,
)
from tests.test_prijava import prijavi_se


class Tipkovnica:
    """Vnaprej pripravljeni odgovori na vprašanja ukaza."""

    def __init__(self, *odgovori: str) -> None:
        self.odgovori = list(odgovori)
        self.vprasanja: list[str] = []

    def __call__(self, vprasanje: str) -> str:
        self.vprasanja.append(vprasanje)
        return self.odgovori.pop(0) if self.odgovori else ""


@pytest.fixture
def izpisi() -> Iterator[list[str]]:
    """Kar bi ukaz izpisal v terminal."""
    vrstice: list[str] = []
    yield vrstice


def zgostitev_v_bazi(motor: Engine, identifikator: str) -> str | None:
    with Session(motor) as seja:
        return seja.scalars(
            select(Credential.secret_hash).where(Credential.identifier == identifikator)
        ).one()


class TestNastaviGeslo:
    def test_zapise_zgostitev_argon2id_in_ne_gesla(
        self, motor: Engine, izpisi: list[str]
    ) -> None:
        ustvari_starsa(motor, geslo=None)
        novo = "novo-geslo-za-starsa"

        koda = ukazi.nastavi_geslo(
            STARS_IDENTIFIKATOR,
            vprasaj=Tipkovnica(novo, novo),
            izpisi=izpisi.append,
            motor=motor,
        )

        assert koda == 0
        zgostitev = zgostitev_v_bazi(motor, STARS_IDENTIFIKATOR)
        assert zgostitev is not None
        assert zgostitev.startswith("$argon2id$")
        assert novo not in zgostitev
        assert geslo_se_ujema(zgostitev, novo)

    def test_po_ukazu_se_je_mogoce_prijaviti(
        self, aplikacija: FastAPI, motor: Engine, izpisi: list[str]
    ) -> None:
        """Ukaz in prijava se morata ujemati — sicer je zgostitev brez pomena."""
        ustvari_starsa(motor, geslo=None)
        novo = "geslo-ki-bo-delovalo"
        ukazi.nastavi_geslo(
            STARS_IDENTIFIKATOR,
            vprasaj=Tipkovnica(novo, novo),
            izpisi=izpisi.append,
            motor=motor,
        )

        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            odgovor = prijavi_se(odjemalec, geslo=novo)

        assert odgovor.status_code == 303

    def test_neznan_identifikator(self, motor: Engine, izpisi: list[str]) -> None:
        koda = ukazi.nastavi_geslo(
            "ni-ga@primer.test",
            vprasaj=Tipkovnica("karkoli", "karkoli"),
            izpisi=izpisi.append,
            motor=motor,
        )

        assert koda == ukazi.NAPAKA
        assert izpisi == [ukazi.SPOROCILO_NI_RACUNA]

    def test_gesli_se_ne_ujemata(self, motor: Engine, izpisi: list[str]) -> None:
        ustvari_starsa(motor)

        koda = ukazi.nastavi_geslo(
            STARS_IDENTIFIKATOR,
            vprasaj=Tipkovnica("dovolj-dolgo-geslo", "nekaj-cisto-drugega"),
            izpisi=izpisi.append,
            motor=motor,
        )

        assert koda == ukazi.NAPAKA
        assert izpisi == [ukazi.SPOROCILO_NEUJEMANJE]
        # Staro geslo ostane v veljavi.
        assert geslo_se_ujema(zgostitev_v_bazi(motor, STARS_IDENTIFIKATOR), GESLO_STARSA)

    def test_prazno_geslo(self, motor: Engine, izpisi: list[str]) -> None:
        ustvari_starsa(motor)

        koda = ukazi.nastavi_geslo(
            STARS_IDENTIFIKATOR, vprasaj=Tipkovnica("", ""), izpisi=izpisi.append, motor=motor
        )

        assert koda == ukazi.NAPAKA
        assert izpisi == [ukazi.SPOROCILO_PRAZNO]

    def test_prekratko_geslo_starsa(self, motor: Engine, izpisi: list[str]) -> None:
        ustvari_starsa(motor, geslo=None)
        prekratko = "a" * 11

        koda = ukazi.nastavi_geslo(
            STARS_IDENTIFIKATOR,
            vprasaj=Tipkovnica(prekratko, prekratko),
            izpisi=izpisi.append,
            motor=motor,
        )

        assert koda == ukazi.NAPAKA
        assert "vsaj 12" in izpisi[0]
        assert zgostitev_v_bazi(motor, STARS_IDENTIFIKATOR) is None

    def test_otrokovo_geslo_sme_biti_kratko(self, motor: Engine, izpisi: list[str]) -> None:
        """`ADR-026`: otrokovo geslo je kratko in bo ostalo kratko."""
        ustvari_starsa(
            motor, identifikator=OTROK_IDENTIFIKATOR, geslo=None, vloga=VLOGA_OTROK
        )

        koda = ukazi.nastavi_geslo(
            OTROK_IDENTIFIKATOR,
            vprasaj=Tipkovnica("masa", "masa"),
            izpisi=izpisi.append,
            motor=motor,
        )

        assert koda == 0

    def test_tri_znaki_so_premalo_tudi_otroku(self, motor: Engine, izpisi: list[str]) -> None:
        ustvari_starsa(
            motor, identifikator=OTROK_IDENTIFIKATOR, geslo=None, vloga=VLOGA_OTROK
        )

        koda = ukazi.nastavi_geslo(
            OTROK_IDENTIFIKATOR,
            vprasaj=Tipkovnica("mas", "mas"),
            izpisi=izpisi.append,
            motor=motor,
        )

        assert koda == ukazi.NAPAKA
        assert "vsaj 4" in izpisi[0]


class TestUkaznaVrstica:
    def test_geslo_v_argumentu_se_zavrne(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Argument bi ostal v zgodovini lupine in v seznamu procesov."""
        koda = ukazi.glavni(["nastavi-geslo", STARS_IDENTIFIKATOR, "geslo-v-argumentu"])

        assert koda == ukazi.NAPAKA
        assert ukazi.SPOROCILO_GESLO_V_ARGUMENTU in capsys.readouterr().out

    def test_brez_podukaza_je_napaka(self) -> None:
        with pytest.raises(SystemExit):
            ukazi.glavni([])
