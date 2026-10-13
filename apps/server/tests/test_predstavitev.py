"""Javna predstavitvena stran na `/` (V6-R03).

Kriteriji so v `docs/verzije/v6.md`, odločitve v `docs/odlocitve/ADR-059` in
`ADR-063`. Stran je obljuba javnosti, zato testi poleg poti varujejo še troje:
da je za vsakogar ista (brez seje, piškotkov in baze), da v njej ni skripte in
tujih virov, in da imena, ki jih navaja iz vmesnika, pridejo od tam, kjer jih
vmesnik hrani.

Ujemanja s posnetki 01, vodoravnega drsenja pri 390 px in zavihka Omrežje test
ne dokaže; to je ročni pregled v fazi 9b.
"""

import html
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event

from app import main, predstavitev, prijava, registracija, sistem
from app.main import create_app
from app.models import STANJE_CAKA, STANJE_ZAVRNJENA
from app.routers import javno, vstop
from app.subjects import OZNAKE_OCEN, PREDMETI
from tests.conftest import PrijavljenOdjemalec, prijavi
from tests.test_racun import _nastavitve_z_googlom
from tests.test_registracija import _odjemalec_za, ustvari_registrirano

KOREN = Path(__file__).resolve().parents[3]
SLOG = main.MAPA_STATICNIH / "javno" / "slog.css"
PREDLOGE = main.MAPA_STATICNIH.parent / "templates"


@pytest.fixture
def aplikacija_g(slike: Any, motor: Engine) -> FastAPI:
    """Namestitev z Googlom — samo taka ponuja registracijo."""
    return create_app(nastavitve=_nastavitve_z_googlom(slike), motor=motor)


@pytest.fixture
def obiskovalec(aplikacija_g: FastAPI) -> Iterator[PrijavljenOdjemalec]:
    """Nekdo brez seje in brez računa."""
    with PrijavljenOdjemalec(
        aplikacija_g, base_url="https://testserver", follow_redirects=False
    ) as odjemalec:
        yield odjemalec


@pytest.fixture(params=[STANJE_CAKA, STANJE_ZAVRNJENA])
def neodobreni(
    request: pytest.FixtureRequest, aplikacija: FastAPI, motor: Engine
) -> Iterator[PrijavljenOdjemalec]:
    """Seja starša, čigar zahtevek čaka oziroma je bil zavrnjen."""
    _, user_id = ustvari_registrirano(motor, request.param)
    with _odjemalec_za(aplikacija, motor, user_id) as odjemalec:
        yield odjemalec


@pytest.fixture
def brez_googla(aplikacija: FastAPI) -> Iterator[TestClient]:
    """Obiskovalec namestitve, ki Googla ni nastavila (privzeta testna)."""
    with TestClient(aplikacija, follow_redirects=False) as odjemalec:
        yield odjemalec


@pytest.fixture
def stran(obiskovalec: PrijavljenOdjemalec) -> str:
    """Izrisana stran namestitve z Googlom, kot jo dobi nekdo brez seje."""
    odgovor = obiskovalec.get(predstavitev.POT)
    assert odgovor.status_code == 200, odgovor.text[:300]
    return str(odgovor.text)


def _besedilo(stran: str) -> str:
    """Vidno besedilo strani: brez oznak, z razvozlanimi znaki in enojnimi presledki."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", stran)))


class TestPot:
    def test_vrne_stran_brez_seje_in_brez_zetona(self, obiskovalec: PrijavljenOdjemalec) -> None:
        odgovor = obiskovalec.get(predstavitev.POT)

        assert odgovor.status_code == 200
        assert odgovor.headers["content-type"].startswith("text/html")
        assert "<h1>" in odgovor.text

    def test_ne_postavi_nobenega_piskotka(self, obiskovalec: PrijavljenOdjemalec) -> None:
        odgovor = obiskovalec.get(predstavitev.POT)

        assert "set-cookie" not in odgovor.headers
        assert not obiskovalec.cookies

    def test_prijavljen_stars_dobi_isto_stran(
        self, aplikacija_g: FastAPI, motor: Engine, stars: str, stran: str
    ) -> None:
        """Brez preusmeritve na `/admin` in brez ene same razlike (`ADR-063` A)."""
        with PrijavljenOdjemalec(
            aplikacija_g, base_url="https://testserver", follow_redirects=False
        ) as odjemalec:
            prijavi(odjemalec, motor, stars)
            odgovor = odjemalec.get(predstavitev.POT)

        assert odgovor.status_code == 200
        assert odgovor.text == stran
        assert "set-cookie" not in odgovor.headers

    def test_ne_izvede_nobenega_stavka_v_bazi(
        self, obiskovalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        stavki: list[str] = []

        @event.listens_for(motor, "before_cursor_execute")
        def _zabelezi(
            _p: Any, _k: Any, stavek: str, _par: Any, _kon: Any, _vec: bool
        ) -> None:
            stavki.append(stavek)

        assert obiskovalec.get(predstavitev.POT).status_code == 200
        assert stavki == []

    def test_usmerjevalnik_nima_odvisnosti_s_sejo_ali_bazo(self) -> None:
        """Varovalo izvora: stran ne sme dobiti poti do podatkov družine."""
        izvor = Path(javno.__file__).read_text(encoding="utf-8")

        assert "app.db" not in izvor
        assert "app.dependencies" not in izvor
        assert "request.state" not in izvor

    @pytest.mark.parametrize("metoda", ["POST", "PUT", "DELETE"])
    def test_druga_metoda_je_405(self, obiskovalec: PrijavljenOdjemalec, metoda: str) -> None:
        assert obiskovalec.request(metoda, predstavitev.POT).status_code == 405

    @pytest.mark.parametrize("pot", ["/materials", "/quizzes/pending", "/x", "/index.html"])
    def test_izvzeta_je_tocna_pot_ne_predpona(
        self, obiskovalec: PrijavljenOdjemalec, pot: str
    ) -> None:
        assert obiskovalec.get(pot).status_code == 401, pot


class TestBrezSkripteInTujihVirov:
    """`ADR-059` B: brez skripte, sledenja, piškotkov in virov tretjih strani."""

    def test_v_strani_ni_skripte(self, stran: str) -> None:
        assert "<script" not in stran.lower()
        assert re.search(r"\son[a-z]+\s*=", stran) is None
        assert "javascript:" not in stran.lower()

    def test_vsak_naslov_v_strani_je_lokalen(self, stran: str) -> None:
        naslovi = re.findall(r'(?:href|src|action)="([^"]*)"', stran)

        assert naslovi
        for naslov in naslovi:
            assert naslov.startswith(("/", "#")), naslov
            assert not naslov.startswith("//"), naslov
        assert "<form" not in stran
        assert "<img" not in stran
        assert "<iframe" not in stran

    def test_slog_ne_kaze_na_tuj_streznik(self) -> None:
        slog = SLOG.read_text(encoding="utf-8")
        naslovi = re.findall(r"url\(([^)]*)\)", slog)

        assert len(naslovi) == 4
        for naslov in naslovi:
            assert naslov.strip("\"'").startswith("../pisave/"), naslov
        assert "@import" not in slog
        assert "http" not in slog

    def test_slog_je_edina_zunanja_datoteka_in_je_javna(
        self, stran: str, obiskovalec: PrijavljenOdjemalec
    ) -> None:
        povezave = re.findall(r"<link[^>]*>", stran)

        assert povezave == [f'<link rel="stylesheet" href="{predstavitev.POT_SLOGA}">']
        odgovor = obiskovalec.get(predstavitev.POT_SLOGA)
        assert odgovor.status_code == 200
        assert odgovor.headers["content-type"].startswith("text/css")
        assert "set-cookie" not in odgovor.headers


class TestVsebina:
    def test_razdelki_so_v_dogovorjenem_vrstnem_redu(self, stran: str) -> None:
        """`docs/poc/POC-03.md`, *Dogovorjeno*."""
        naslovi = re.findall(r"<h[12]>(.*?)</h[12]>", stran, re.S)

        assert [_besedilo(n).strip() for n in naslovi] == [
            "Test za tisk iz tega, kar se je otrok res učil .",
            "Sestavi test v pogovoru",
            "Kvizi, ki jih otrok reši na telefonu",
            "Kako deluje",
            "Ena družina, dve orodji",
            "Kako ravnamo s podatki",
            "Kako do računa",
        ]

    def test_meni_kaze_na_sidra_ki_obstajajo(self, stran: str) -> None:
        meni = re.search(r'<nav class="glava-meni".*?</nav>', stran, re.S)
        assert meni is not None

        assert re.findall(r'<a href="#([^"]+)">\s*([^<]+?)\s*</a>', meni.group(0)) == [
            ("testi", "Testi"),
            ("kvizi", "Kvizi"),
            ("kako-deluje", "Kako deluje"),
            ("druzina", "Za otroka in starše"),
            ("zasebnost", "Zasebnost"),
        ]
        idji = set(re.findall(r'\sid="([^"]+)"', stran))
        for sidro in re.findall(r'href="#([^"]+)"', stran):
            assert sidro in idji, sidro

    def test_prijava_in_registracija_vodita_na_pravi_poti(self, stran: str) -> None:
        glava = stran.split("</header>")[0]

        assert f'href="{prijava.POT_PRIJAVE}">Prijava</a>' in glava
        assert f'href="{registracija.POT}">Registracija</a>' in glava
        assert stran.count(f'href="{registracija.POT}"') == 3  # glava, uvod, plošča
        assert registracija.POT == "/admin/register"
        assert prijava.POT_PRIJAVE == "/admin/login"

    def test_brez_googla_gumbov_registracije_ni(self, brez_googla: TestClient) -> None:
        odgovor = brez_googla.get(predstavitev.POT)

        assert odgovor.status_code == 200
        assert registracija.POT not in odgovor.text
        assert "Registr" not in odgovor.text
        assert f'href="{prijava.POT_PRIJAVE}"' in odgovor.text
        assert "Kako do računa" in odgovor.text

    def test_kartica_o_zunanji_storitvi_nosi_besedilo_soglasja(self, stran: str) -> None:
        """En vir besedila (`ADR-059` E, `ADR-063` D) — dobesedno, ne podobno."""
        kartica = re.search(r'<li class="opozorilna">(.*?)</li>', stran, re.S)
        assert kartica is not None

        assert f"<p>{html.escape(sistem.BESEDILO_ZASEBNOST_JAVNO)}</p>" in kartica.group(1)
        assert "OpenAI" in sistem.BESEDILO_ZASEBNOST_JAVNO
        assert "ni objavljena" not in _besedilo(stran)

    def test_okno_registracije_kaze_isto_besedilo(self) -> None:
        """Druga polovica „enega vira": soglasje bere isto konstanto."""
        izvor = (PREDLOGE / "registracija.html").read_text(encoding="utf-8")
        usmerjevalnik = Path(vstop.__file__).read_text(encoding="utf-8")

        assert "{{ besedilo_zasebnost }}" in izvor
        assert '"besedilo_zasebnost": sistem.BESEDILO_ZASEBNOST_JAVNO' in usmerjevalnik

    def test_ocene_so_tiste_iz_vmesnika(self, stran: str) -> None:
        """Preimenovanje ocene v aplikaciji mora spremeniti tudi stran."""
        telefon = re.findall(r'<span class="telefon-ocena o\d">([^<]+)</span>', stran)

        assert telefon == list(OZNAKE_OCEN.values())
        assert telefon[0] == "Nisem vedela"
        nastete = ", ".join(oznaka.lower() for oznaka in OZNAKE_OCEN.values())
        assert f"Štiri stopnje: {nastete}." in stran

    def test_polica_ima_vse_predmete_v_njihovih_barvah(self, stran: str) -> None:
        polica = re.search(r'<ul class="polica".*?</ul>', stran, re.S)
        assert polica is not None

        assert re.findall(
            r'<li style="--barva: (#[0-9a-f]{6})"><span>([A-Z]{3})</span></li>', polica.group(0)
        ) == [(predmet.barva, predmet.koda) for predmet in PREDMETI]

    def test_imena_gumbov_so_tista_iz_pregleda(self, stran: str) -> None:
        """Trditve 6, 10 in 12 iz plana: stran navaja imena, kot jih piše pregled."""
        urejevalnik = (PREDLOGE / "preizkus.html").read_text(encoding="utf-8")
        ogled = (PREDLOGE / "preizkus-ogled.html").read_text(encoding="utf-8")
        predogled = (PREDLOGE / "kvizi-predogled.html").read_text(encoding="utf-8")

        for ime in ("↶ Razveljavi", "↷ Uveljavi", "Natisni / PDF", "Shrani", "Kreiraj test"):
            assert f">{ime}</button>" in urejevalnik, ime
            assert ime in stran, ime
        assert '"Posodobi test"' in urejevalnik
        assert "Posodobi test" in stran
        assert ">Nov test na tej osnovi</a>" in ogled
        assert "»Nov test na tej osnovi«" in stran
        assert ">Objavi</button>" in predogled
        assert '<span class="lazni-gumb poln">Objavi</span>' in stran

    def test_popravki_trditev_iz_adr_063(self, stran: str) -> None:
        besedilo = _besedilo(stran)

        # G1: gumb se imenuje »Kreiraj test«; »Sestavi test« je samo naslov razdelka.
        assert "klikneš »Kreiraj test«" in besedilo
        assert "»Sestavi test«" not in besedilo
        assert besedilo.count("Sestavi test") == 1
        # G2: predlogov-gumbov v prikazu klepeta ni.
        for predlog in ("Skrajšaj na eno stran", "Več prostora za računanje", "Dodaj nalogo"):
            assert predlog not in besedilo
        # G3 in G4.
        assert "Umaknjeno gre v arhiv" in besedilo
        assert "Nič se ne izgubi" not in besedilo
        assert (
            "Skrbnik sistema vidi ime družine, imena in e-naslove staršev ter število otrok."
            in besedilo
        )
        # G5 in G6.
        assert "za matematiko, drugi predmeti sledijo" in besedilo
        assert "Registracija vzame minuto." in besedilo
        # Potrjeno ob planu: opombe „se zatikajo" v prikazu statistike ni.
        assert "kandidat" not in besedilo
        assert "Ulomki se zatikajo" not in besedilo

    def test_stran_ne_obljublja_cesar_ni(self, stran: str) -> None:
        besedilo = _besedilo(stran).lower()

        for beseda in ("trgovin", "google play", "iphone", "ios", "e-pošt", "kmalu", "brezplač"):
            assert beseda not in besedilo, beseda

    def test_prikazi_niso_dosegljivi_s_tipkovnico(self, stran: str) -> None:
        """Narisani gumbi niso gumbi: v prikazih ni ničesar, kar bi dobilo fokus."""
        for znacka in ("<button", "<input", "<select", "<textarea", "tabindex"):
            assert znacka not in stran, znacka
        for zacetek in (
            '<div class="uvod-prikaz" aria-hidden="true">',
            '<div class="prikaz urejevalnik" aria-hidden="true">',
            '<div class="kvizi-mreza" aria-hidden="true">',
        ):
            assert stran.count(zacetek) == 1, zacetek
            # Do naslednjega besedila strani v prikazu ni nobene povezave.
            prikaz = re.split(r'<ul class="(?:polica|lastnosti)"', stran.split(zacetek)[1])[0]
            assert "<a " not in prikaz, zacetek


class TestSlog:
    def test_tema_sirina_in_fokus(self) -> None:
        slog = SLOG.read_text(encoding="utf-8")

        assert "@media (prefers-color-scheme: dark)" in slog
        assert "color-scheme: light dark" in slog
        assert ":focus-visible" in slog
        assert "@media (max-width: 960px)" in slog
        assert "@media (max-width: 560px)" in slog
        # Brez `outline: none`, ki bi fokus skril.
        assert re.search(r"outline:\s*(none|0)\b", slog) is None

    def test_vsak_razred_iz_strani_ima_pravilo(self, stran: str) -> None:
        """Preimenovan razred v predlogi naj ne ostane tiho brez sloga."""
        slog = SLOG.read_text(encoding="utf-8")
        razredi = {r for skupina in re.findall(r'class="([^"]+)"', stran) for r in skupina.split()}

        brez_pravila = {r for r in razredi if f".{r}" not in slog}
        assert brez_pravila == set()


class TestPovezaveNazaj:
    """`ADR-063` C: povezave, ki jih je `ADR-062` B odložil do te zahteve."""

    def test_okno_registracije_ima_domaco_stran(self, obiskovalec: PrijavljenOdjemalec) -> None:
        stran = obiskovalec.get(registracija.POT).text

        assert f'<a href="{predstavitev.POT}">← Domača stran</a>' in stran

    def test_soglasje_kaze_na_pravila_zasebnosti(self) -> None:
        izvor = (PREDLOGE / "registracija.html").read_text(encoding="utf-8")

        assert '<a href="{{ pot_zasebnosti }}">pravila zasebnosti</a>' in izvor
        assert predstavitev.POT_ZASEBNOSTI == "/#zasebnost"
        # Celotno besedilo ostane ob polju, ne samo za povezavo.
        assert "<details>" in izvor

    def test_moj_racun_ima_pot_na_domaco_stran(self, neodobreni: PrijavljenOdjemalec) -> None:
        stran = neodobreni.get(registracija.POT_RACUNA).text

        assert f'<a href="{predstavitev.POT}">Na domačo stran</a>' in stran


class TestDokumenti:
    def test_namen_ne_trdi_vec_da_registracije_ni(self) -> None:
        namen = (KOREN / "docs" / "00-namen.md").read_text(encoding="utf-8")

        assert "registracije ni" not in namen
        assert "Ni odprta platforma" not in namen

    def test_arhitektura_ne_trdi_vec_da_preizkus_ni_opravljen(self) -> None:
        arhitektura = (KOREN / "docs" / "01-arhitektura.md").read_text(encoding="utf-8")

        assert "še ni preverjeno" not in arhitektura


def test_namestitev_z_googlom_je_res_z_googlom(slike: Any, motor: Engine) -> None:
    """Varovalo postavitve: `stran` zgoraj mora biti stran z gumbi registracije."""
    aplikacija = create_app(nastavitve=_nastavitve_z_googlom(slike), motor=motor)

    with TestClient(aplikacija) as odjemalec:
        assert registracija.POT in odjemalec.get(predstavitev.POT).text
