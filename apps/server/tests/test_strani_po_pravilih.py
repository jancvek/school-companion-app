"""Strani, ki so nov videz dobile po pravilih in ne po posnetku (V5-R01).

`docs/poc/POC-02.md`, *Strani po pravilih*: potrditvene strani, arhiv,
prepisi, račun, sistem, 404, tisk kviza, shranjeni testi. Kriterij zahteve je
oster: **nobena stran pod `/admin` ne ostane v starem slogu** — to varuje
prvi razred tega modula nad datotekami predlog, ne nad posameznimi izrisi.
"""

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.models import Material
from app.routers.admin import MAPA_PREDLOG
from tests.conftest import (
    CVEK_ID,
    PrijavljenOdjemalec,
    prijavi,
    slog_zaslona,
    ustvari_starsa,
    vsebina_strani,
)
from tests.test_admin import UUID_ENA, zapisi

#: Predlogi urejevalnika in ogleda preizkusa s svojim slogom in skripto, ki po
#: `ADR-054` in `ADR-055` ostaneta, kot sta. Dobita ogrodje in barve.
UREJEVALNIK = frozenset(
    {"preizkus.html", "preizkus-ogled.html", "_preizkus-izris.html", "_preizkus-slog.html"}
)

#: Razredi sloga pred V5-R01, ki jih nova predloga ne sme več nositi.
STARI_RAZREDI = frozenset(
    {"gumb-obdelava", "opozorilo", "izid", "vstopi", "mreza", "stevec", "kdo", "izbor", "predmet"}
)


@pytest.fixture(autouse=True)
def _druzina_ima_otroka(otrok: str) -> str:
    return otrok


@pytest.fixture
def lastnikov_odjemalec(aplikacija: FastAPI, motor: Engine) -> Iterator[PrijavljenOdjemalec]:
    lastnik = ustvari_starsa(
        motor, identifikator="lastnik@primer.test", prikazno_ime="Lastnik", lastnik_sistema=True
    )
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
        prijavi(odjemalec, motor, lastnik)
        yield odjemalec


def razredi_predloge(besedilo: str) -> set[str]:
    """Vsa imena razredov iz atributov `class` (brez izrazov predloge)."""
    imena: set[str] = set()
    for vrednost in re.findall(r'class="([^"]*)"', besedilo):
        cisto = re.sub(r"\{[{%].*?[%}]\}", " ", vrednost)
        imena.update(cisto.split())
    return imena


class TestNobenaStranVStaremSlogu:
    def predloge(self) -> list[Path]:
        return [pot for pot in sorted(MAPA_PREDLOG.glob("*.html")) if pot.name not in UREJEVALNIK]

    def test_nobena_predloga_ne_nosi_starih_razredov(self) -> None:
        najdeno = {
            pot.name: sorted(razredi_predloge(pot.read_text(encoding="utf-8")) & STARI_RAZREDI)
            for pot in self.predloge()
        }

        assert {ime: stari for ime, stari in najdeno.items() if stari} == {}

    def test_gumb_ima_povsod_izrecen_pomen(self) -> None:
        # Gumb brez dodatnega razreda je bil pred V5-R01 uničujoče dejanje; v
        # novih predlogah je vsak gumb polni, obrobljen, nevaren ali nepovraten.
        gumbi = {"polni", "obrobljen", "nevaren", "nepovraten"}
        for pot in self.predloge():
            for vrednost in re.findall(r'class="([^"]*)"', pot.read_text(encoding="utf-8")):
                imena = set(vrednost.split())
                if "gumb" in imena:
                    assert imena & gumbi, f"{pot.name}: class=\"{vrednost}\""

    def test_nobena_predloga_nima_svojega_sloga(self) -> None:
        for pot in self.predloge():
            assert "<style" not in pot.read_text(encoding="utf-8").lower(), pot.name

    def test_vsaka_stran_stoji_na_ogrodju(self) -> None:
        for pot in self.predloge():
            if pot.name.startswith("_") or pot.name == "osnova.html":
                continue
            # Javna predstavitvena stran namenoma ne stoji na ogrodju pregleda:
            # to nosi meni in slog admina (V6-R03, `ADR-063` B). Vsa druga
            # pravila tega razreda zanjo veljajo.
            if pot.name == "predstavitev.html":
                continue
            assert '{% extends "osnova.html" %}' in pot.read_text(encoding="utf-8"), pot.name

    def test_slog_nima_vec_prehodnega_razdelka(self) -> None:
        slog = slog_zaslona()

        assert "pred prenovo" not in slog
        for razred in ("izid", "vstopi", "mreza", "stevec", "kdo"):
            assert not re.search(rf"\.{razred}[ ,{{.:]", slog), razred

    def test_razredi_urejevalnika_ne_trcijo_z_novim_slogom(self) -> None:
        """Urejevalnik ima svoje `.potrditev`, `.slicice` in `.orodja` (`ADR-054`)."""
        slog = slog_zaslona()

        for razred in ("potrditev", "slicice", "orodja"):
            assert not re.search(rf"\.{razred}(?![\w-])", slog), razred


class TestPotrditveneStrani:
    def kartica(self, besedilo: str) -> str:
        zacetek = besedilo.index('<section class="kartica kartica-potrditve">')
        return besedilo[zacetek : besedilo.index("</section>", zacetek)]

    def test_arhiviranje_ni_nepovratno_in_ohrani_obrazec(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        kartica = self.kartica(odjemalec.get(f"/admin/materials/{UUID_ENA}/archive").text)

        assert "<h1>Arhivirati to sliko?</h1>" in kartica
        assert re.findall(r'<li class="(\w+)">', kartica) == ["takoj", "ostane", "tece"]
        assert "nepovraten" not in kartica
        assert re.search(
            rf'<form method="post" action="/admin/materials/{UUID_ENA}/archive"[^>]*>\s*'
            r'<input type="hidden" name="csrf" value="[^"]+">\s*'
            r'<button class="gumb polni" type="submit">Da, arhiviraj</button>',
            kartica,
        )
        preklic = f'<a class="gumb obrobljen" href="/admin/materials/{UUID_ENA}">Prekliči</a>'
        assert preklic in kartica

    def test_dokoncno_brisanje_je_polno_rdece(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        zdaj = datetime(2026, 9, 5, tzinfo=UTC)
        with Session(motor) as seja:
            seja.execute(
                update(Material)
                .where(Material.id == UUID_ENA)
                .values(archived_at=zdaj, device_deleted_at=zdaj)
            )
            seja.commit()

        kartica = self.kartica(odjemalec.get(f"/admin/materials/{UUID_ENA}/delete").text)

        assert "<h1>Izbrisati to snov dokončno?</h1>" in kartica
        gumb = '<button class="gumb nepovraten" type="submit">Da, izbriši dokončno</button>'
        assert gumb in kartica
        assert re.findall(r'<li class="(\w+)">', kartica) == ["takoj", "ostane"]

    def test_ponastavitev_gesla_ima_posledice_in_polji(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        ana = ustvari_starsa(motor, identifikator="ana@primer.test", prikazno_ime="Ana")

        kartica = self.kartica(odjemalec.get(f"/admin/family/members/{ana}/password").text)

        assert "<strong>Ana</strong>" in kartica
        assert "<h1>Ponastaviti geslo?</h1>" in kartica
        assert re.findall(r'<input type="password" id="[\w-]+" name="(\w+)"', kartica) == [
            "geslo",
            "geslo_znova",
        ]
        assert f'action="/admin/family/members/{ana}/password"' in kartica

    def test_deaktivacija_druzine_je_kartica_s_posledicami(
        self, lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        from tests.test_druzine import DRUGA_ID, dodaj_druzino

        dodaj_druzino(motor)

        besedilo = lastnikov_odjemalec.get(f"/admin/system/families/{DRUGA_ID}/deactivate").text
        kartica = self.kartica(besedilo)

        assert "<h1>Deaktivirati družino?</h1>" in kartica
        assert re.findall(r'<li class="(\w+)">', kartica) == ["takoj", "tece", "ostane"]
        assert '<button class="gumb nepovraten" type="submit">' in kartica

    def test_stran_z_napako_pove_kaj_se_je_zgodilo_in_pelje_na_predmete(
        self, odjemalec: TestClient
    ) -> None:
        odgovor = odjemalec.get("/admin/materials/ni-ga")

        assert odgovor.status_code == 404
        kartica = self.kartica(odgovor.text)
        assert "<p>Zapisa s tem identifikatorjem na strežniku ni.</p>" in kartica
        assert '<a class="gumb obrobljen" href="/admin">Nazaj na Predmete</a>' in kartica


class TestOstaleStrani:
    def test_arhiv_je_mreza_slicic_z_oznako_in_datumom(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        with Session(motor) as seja:
            seja.execute(
                update(Material)
                .where(Material.id == UUID_ENA)
                .values(archived_at=datetime(2026, 9, 5, 8, tzinfo=UTC))
            )
            seja.commit()

        besedilo = odjemalec.get("/admin/archive").text

        assert '<ul class="arhiv">' in besedilo
        assert '<span class="oznaka">v arhivu</span>' in besedilo
        assert "arhivirano 5. 9. 2026 ob 10:00" in besedilo
        assert f'<img src="/admin/materials/{UUID_ENA}/image" alt="" loading="lazy">' in besedilo

    def test_prazen_arhiv_pove_kako_pride_slika_vanj(self, odjemalec: TestClient) -> None:
        assert "Arhiv je prazen." in vsebina_strani(odjemalec.get("/admin/archive").text)

    def test_sistem_kaze_druzine_kot_kartice(
        self, lastnikov_odjemalec: PrijavljenOdjemalec
    ) -> None:
        besedilo = lastnikov_odjemalec.get("/admin/system").text

        assert re.search(
            rf'<li class="clan">.*?<a href="/admin/system/families/{CVEK_ID}">Cvek</a>',
            besedilo,
            re.S,
        )
        assert '<span class="oznaka ok">tvoja družina</span>' in besedilo
        # `ADR-056` I: obrazec nove družine ima iste poti in polja.
        assert '<form method="post" action="/admin/system/families">' in besedilo
        polja = re.findall(r'<input type="(?:text|password)" id="[\w-]+" name="(\w+)"', besedilo)
        assert polja == ["ime_druzine", "ime", "enaslov", "geslo", "geslo_znova"]

    def test_stran_druzine_kaze_starse_kot_kartice(
        self, lastnikov_odjemalec: PrijavljenOdjemalec
    ) -> None:
        besedilo = lastnikov_odjemalec.get(f"/admin/system/families/{CVEK_ID}").text

        assert '<li><a href="/admin/system">Družine</a></li>' in besedilo
        assert re.search(r'<li class="clan">.*?<h3>Lastnik</h3>', besedilo, re.S)
        assert '<span class="oznaka">lastnik sistema</span>' in besedilo

    def test_tisk_kviza_ima_zaslonski_del_v_ogrodju_in_papir_nespremenjen(self) -> None:
        predloga = (MAPA_PREDLOG / "kviz-tisk.html").read_text(encoding="utf-8")

        # Zaslonski del se ne tiska; del za papir ima iste razrede kot prej.
        assert '<div class="ne-tiskaj">' in predloga
        for razred in ("tisk", "tisk-vprasanja", "prostor", "kljuc"):
            assert f'class="{razred}"' in predloga
        zaslon = predloga[: predloga.index('<div class="tisk">')]
        assert '<ol class="drobtine">' in zaslon
        assert '<button class="gumb polni" type="submit">Pokaži za tisk</button>' in zaslon
        assert '<input type="hidden" name="izbor" value="1">' in zaslon


class TestPotiOstanejo:
    """`ADR-056` I: poti in metode ostanejo; novi sta natanko dve poti `GET`."""

    #: Število parov (metoda, pot) v `openapi()` pred V5-R01. Zapisano na
    #: roko: nova pot mora ta test podreti, da se nekdo vpraša, ali je bila
    #: dogovorjena (`ADR-060` G in „Novi parametri obstoječih poti").
    PRED_V5_R01 = 73

    NOVI = frozenset(
        {("GET", "/admin/quizzes"), ("GET", "/admin/schedule/image/{slika_id}")}
    )

    #: Pari, ki jih je dodala `V6-R01` (`docs/odlocitve/ADR-061` D), s soglasjem
    #: lastnika. Popis ostane zapisan na roko: vsaka pot, ki je ni ne tu ne
    #: zgoraj, test še naprej podre.
    V6_R01 = frozenset(
        {
            ("POST", "/auth/link"),
            ("GET", "/admin/family/members/{user_id}/link"),
            ("POST", "/admin/family/members/{user_id}/link"),
            ("GET", "/admin/family/members/{user_id}/revoke"),
            ("POST", "/admin/family/members/{user_id}/revoke"),
        }
    )

    #: Pari, ki jih je dodala `V6-R02` (`docs/odlocitve/ADR-062` I, K, L), s
    #: soglasjem lastnika: okno registracije, izbris zavrnjenega računa ter
    #: lastnikova odobritev in zavrnitev.
    V6_R02 = frozenset(
        {
            ("GET", "/admin/register"),
            ("POST", "/admin/register"),
            ("GET", "/admin/racun/izbrisi"),
            ("POST", "/admin/racun/izbrisi"),
            ("GET", "/admin/system/families/{family_id}/approve"),
            ("POST", "/admin/system/families/{family_id}/approve"),
            ("GET", "/admin/system/families/{family_id}/reject"),
            ("POST", "/admin/system/families/{family_id}/reject"),
        }
    )

    def test_dodani_sta_natanko_dve_poti_get(self, aplikacija: FastAPI) -> None:
        pari = {
            (metoda.upper(), pot)
            for pot, metode in aplikacija.openapi()["paths"].items()
            for metoda in metode
        }

        assert pari >= self.NOVI
        assert pari >= self.V6_R01
        assert pari >= self.V6_R02
        assert len(pari) == (
            self.PRED_V5_R01 + len(self.NOVI) + len(self.V6_R01) + len(self.V6_R02)
        )
        # Slika urnika se samo bere.
        assert ("POST", "/admin/schedule/image/{slika_id}") not in pari
