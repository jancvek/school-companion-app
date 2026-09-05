"""Testi zanke v ozadju in njenega priklopa na življenjski cikel aplikacije.

`pytest-asyncio` ni odvisnost te zbirke in ga tudi ne uvajamo zaradi treh
testov: korutine tečejo skozi `asyncio.run`, kar je za to, kar se tu preverja,
dovolj in ne doda ničesar v `pyproject.toml`.

Čakanja na uro tu ni. Kjer test potrebuje „zanka je naredila naslednji obhod",
to pove dogodek, ki ga postavi lažni obhod — ne `sleep`, ki bi bil na
obremenjenem stroju enkrat prekratek.
"""

import asyncio
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.main import create_app
from app.models import STATUS_NOV, STATUS_PRIPRAVLJEN, STATUS_V_OBDELAVI, Material
from app.settings import Settings
from app.vision import IzidKlica
from app.worker import Obdelovalec, obnovi_obticale
from tests.conftest import KLJUC, OKOLJSKE_NASTAVITVE, naredi_testne_nastavitve
from tests.test_obdelava import UUID_ENA, preberi, uspesen_izid, zapisi


def naredi_obdelovalca(
    tovarna_sej: sessionmaker[Session],
    slike: Path,
    klicalec: Callable[[Path], IzidKlica],
    interval: float = 0.01,
) -> Obdelovalec:
    return Obdelovalec(
        tovarna_sej=tovarna_sej, klicalec=klicalec, images_dir=slike, interval=interval
    )


class TestObhod:
    """En obhod zanke."""

    def test_obhod_obdela_cakajoc_zapis(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        zapisi(motor, slike)
        izid = uspesen_izid()
        obdelovalec = naredi_obdelovalca(tovarna_sej, slike, lambda pot: izid)

        assert asyncio.run(obdelovalec.en_obhod()) == 1
        assert preberi(motor).status == STATUS_PRIPRAVLJEN

    def test_obhod_brez_dela_ne_naredi_nicesar(
        self, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        obdelovalec = naredi_obdelovalca(tovarna_sej, slike, lambda pot: uspesen_izid())

        assert asyncio.run(obdelovalec.en_obhod()) == 0


class TestZanka:
    """Zagon, ustavitev in preživetje napake."""

    def test_zazeni_obnovi_obticale_in_obdela(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Robni primer iz `v1.md`: zapis v `processing` se ob zagonu vrne v vrsto.

        Tu se preverja obe polovici hkrati — da se vrne **in** da ga zanka
        potem res pobere. Sama vrnitev v `new` brez tega ne pomeni ničesar.
        """
        zapisi(motor, slike, status=STATUS_V_OBDELAVI)
        izid = uspesen_izid()
        obdelan = asyncio.Event()

        def klicalec(pot: Path) -> IzidKlica:
            obdelan.set()
            return izid

        async def teci() -> None:
            obdelovalec = naredi_obdelovalca(tovarna_sej, slike, klicalec)
            obdelovalec.zazeni()
            try:
                await asyncio.wait_for(obdelan.wait(), timeout=5)
            finally:
                await obdelovalec.ustavi()

        asyncio.run(teci())

        assert preberi(motor).status == STATUS_PRIPRAVLJEN

    def test_zanka_prezivi_odpoved_obhoda(
        self, slike: Path, tovarna_sej: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Če bi zanka ob izjemi umrla, bi obdelava tiho zamrla do ponovnega zagona.

        Prvi obhod vrže; test čaka na **drugi**. Brez lovljenja izjeme v zanki
        drugega obhoda ne bi bilo in test bi padel na časovni omejitvi.
        """
        obhodi = 0
        drugi_obhod = asyncio.Event()

        def lazni_obhod(*args: Any, **kwargs: Any) -> int:
            nonlocal obhodi
            obhodi += 1
            if obhodi == 1:
                raise RuntimeError("baza ni dosegljiva")
            drugi_obhod.set()
            return 0

        monkeypatch.setattr("app.worker.obdelaj_cakajoce", lazni_obhod)

        async def teci() -> None:
            obdelovalec = naredi_obdelovalca(tovarna_sej, slike, lambda pot: uspesen_izid())
            obdelovalec.zazeni()
            try:
                await asyncio.wait_for(drugi_obhod.wait(), timeout=5)
            finally:
                await obdelovalec.ustavi()

        asyncio.run(teci())

        assert obhodi >= 2

    def test_ustavitev_ne_caka_celega_razmika(
        self, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Zaustavitev strežnika ne sme viseti pol minute.

        Razmik je namenoma velik: če bi ustavitev čakala nanj, bi test padel
        na svoji časovni omejitvi.
        """

        async def teci() -> None:
            obdelovalec = naredi_obdelovalca(
                tovarna_sej, slike, lambda pot: uspesen_izid(), interval=3600
            )
            obdelovalec.zazeni()
            await asyncio.wait_for(obdelovalec.ustavi(), timeout=5)

        asyncio.run(teci())

    def test_ustavitev_brez_zagona_ne_pade(
        self, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        obdelovalec = naredi_obdelovalca(tovarna_sej, slike, lambda pot: uspesen_izid())

        asyncio.run(obdelovalec.ustavi())


class TestObnovitevObZagonu:
    """`obnovi_obticale` kot samostojna funkcija."""

    def test_vrne_koliko_jih_je_bilo(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        zapisi(motor, slike, status=STATUS_V_OBDELAVI)

        assert obnovi_obticale(tovarna_sej) == 1
        assert preberi(motor).status == STATUS_NOV

    def test_brez_obticalih_ne_javi_nicesar(self, tovarna_sej: sessionmaker[Session]) -> None:
        assert obnovi_obticale(tovarna_sej) == 0


class TestPriklopNaAplikacijo:
    """Kdaj se zanka sploh zažene."""

    def test_brez_kljuca_se_obdelava_ne_zazene(
        self, aplikacija: FastAPI, motor: Engine, slike: Path
    ) -> None:
        """ADR-009: manjkajoč `OPENAI_API_KEY` pomeni mirujočo obdelavo, ne `failed`.

        Zapis ostane `new` — torej se obdela sam, ko ključ dodaš in strežnik
        zaženeš znova. To hkrati drži celo zbirko stran od omrežja: testne
        nastavitve ključa nimajo, zato v nobenem drugem testu zanka ne teče.
        """
        zapisi(motor, slike)

        with TestClient(aplikacija):
            assert aplikacija.state.klicalec is None
            assert aplikacija.state.obdelovalec is None

        assert preberi(motor).status == STATUS_NOV

    def test_s_klicalcem_obdelava_stece(self, motor: Engine, slike: Path) -> None:
        """Priklop na `lifespan`: ko klicalec je, se zanka zažene in dela."""
        zapisi(motor, slike)
        izid = uspesen_izid()

        nastavitve = Settings(
            api_key=KLJUC,
            database_url="sqlite://",
            images_dir=slike,
            worker_interval_seconds=0.01,
        )
        aplikacija = create_app(
            nastavitve=nastavitve, motor=motor, klicalec=lambda pot: izid
        )

        with TestClient(aplikacija) as odjemalec:
            assert aplikacija.state.obdelovalec is not None
            # Zahteva na strežnik med tem, ko obdelava teče: preverba živosti
            # ne sme čakati na klic modela. Zanka dela v svoji niti, zato se
            # na izid čaka z rokom in ne s fiksnim spanjem.
            assert odjemalec.get("/health").status_code == 200
            rok = time.monotonic() + 5
            while time.monotonic() < rok and preberi(motor).status != STATUS_PRIPRAVLJEN:
                time.sleep(0.01)

        assert preberi(motor).status == STATUS_PRIPRAVLJEN

    def test_kljuc_v_nastavitvah_naredi_klicalca(self, motor: Engine, slike: Path) -> None:
        """Brez podanega klicalca ga aplikacija zgradi sama — a le, če ključ je.

        Odjemalec tu nastane, vendar se ne uporabi: `create_app` ne pošlje
        nobene zahteve, `TestClient` pa se v tem testu ne odpre.
        """
        nastavitve = Settings(
            api_key=KLJUC,
            database_url="sqlite://",
            images_dir=slike,
            openai_api_key="ta-kljuc-obstaja",
        )

        aplikacija = create_app(nastavitve=nastavitve, motor=motor)

        assert aplikacija.state.klicalec is not None


def test_material_v_obdelavi_ni_izmisljen(motor: Engine, slike: Path) -> None:
    """Varovalo pomožne funkcije `zapisi`: status v bazi je res tak, kot pravi.

    Brez tega bi lahko vsi testi obnovitve tekli nad zapisom v `new` in bili
    zeleni, ne da bi karkoli obnovili.
    """
    zapisi(motor, slike, status=STATUS_V_OBDELAVI)

    with Session(motor) as seja:
        material = seja.get(Material, UUID_ENA)
        assert material is not None
        assert material.status == STATUS_V_OBDELAVI


class TestZbirkaJeNeodvisnaOdOkolja:
    """Da „testi ne kličejo omrežja" ostane lastnost kode, ne lastnost stroja.

    `Settings` je `BaseSettings`: polje, ki ga klicatelj ne poda, pride iz
    okolja. `OPENAI_API_KEY` je na stroju lastnika povsem pričakovano ime — in
    če bi ga zbirka podedovala, bi `create_app` zgradil pravi odjemalec,
    `TestClient` bi pognal življenjski cikel in testne slike bi zares
    odpotovale k OpenAI, na račun lastnika.
    """

    def test_seja_okoljskih_nastavitev_nima(self) -> None:
        """Neposreden dokaz, da fixture iz `conftest` res očisti okolje."""
        prisotne = [ime for ime in OKOLJSKE_NASTAVITVE if ime in os.environ]

        assert prisotne == []

    def test_kljuc_v_okolju_ne_zazene_obdelave(
        self, motor: Engine, slike: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tudi če ključ v okolju je, ga testna aplikacija ne pobere.

        Mutacijski test za `conftest`: če bi `naredi_testne_nastavitve` polje
        `openai_api_key` spet prepustile privzetku, bi ta test padel — in ne bi,
        kot prej, padel šele na stroju, kjer je spremenljivka slučajno
        nastavljena.

        Nastavitve nastanejo **v telesu testa** in ne prek fixture: fixture bi
        nastal pred `monkeypatch.setenv` in spremenljivke sploh ne bi videl.
        """
        monkeypatch.setenv("OPENAI_API_KEY", "sk-lazen-kljuc-iz-okolja")
        zapisi(motor, slike)

        aplikacija = create_app(nastavitve=naredi_testne_nastavitve(slike), motor=motor)

        with TestClient(aplikacija):
            assert aplikacija.state.klicalec is None
            assert aplikacija.state.obdelovalec is None

        assert preberi(motor).status == STATUS_NOV

    def test_ime_modela_v_nastavitvah_se_v_testih_ne_uporabi(
        self, nastavitve: Settings
    ) -> None:
        """Varovalo: če bi kak test vseeno prišel do klica, ne bi šel v pravi model."""
        assert nastavitve.openai_model == "model-ki-se-ne-uporabi"
        assert nastavitve.openai_api_key == ""
