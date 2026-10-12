"""Statistika in prijava po V5-R01 (`docs/poc/POC-02.md`, posnetki 22 do 25).

Kaj statistika šteje, varuje `test_statistika.py`; prijavo, seje in CSRF
`test_prijava.py`. Tu je samo, kar je V5-R01 prestavila ali dodala.
"""

import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app import prijava
from app.main import create_app
from tests.conftest import (
    PrijavljenOdjemalec,
    SejaTesta,
    naredi_testne_nastavitve,
    vsebina_strani,
)
from tests.test_kvizi import UUID_ENA, objavi, snov
from tests.test_resevanje import OCENJENO, POKAZANO, RAZKRITO, poskus, poslji
from tests.test_rezultat import postavke

BARVE = (
    ("NAR", "#3d7856"),
    ("MAT", "#2d5a8e"),
    ("TJA", "#8a3a5b"),
    ("GEO", "#8b5a26"),
    ("SLJ", "#a63f3b"),
    ("LUM", "#6f55a0"),
    ("ZGO", "#6a5843"),
    ("TIT", "#44636e"),
    ("DKE", "#5a7530"),
    ("GUM", "#2b7a80"),
)


@pytest.fixture(autouse=True)
def _druzina_ima_otroka(otrok: str) -> str:
    return otrok


@pytest.fixture
def z_ocenami(odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta) -> None:
    """Snov z dvema vprašanjema, postavljena v dveh kvizih: eno večkrat, eno enkrat."""
    snov(motor, slike, UUID_ENA, vprasanj=2)
    prvi = objavi(odjemalec, motor, [UUID_ENA], koliko=2)
    poslji(odjemalec, [poskus(p, rating="tezko") for p in postavke(motor, prvi)], telefon)
    drugi = objavi(odjemalec, motor, [UUID_ENA], koliko=1, vstop="rocna")
    # Drugi kviz je rešen **dan pozneje**: zaporedje ocen je urejeno po času
    # odgovora, in dva odgovora z istim časom nimata določenega vrstnega reda.
    kasneje = {
        polje: (trenutek + timedelta(days=1)).isoformat()
        for polje, trenutek in (
            ("shown_at", POKAZANO),
            ("revealed_at", RAZKRITO),
            ("answered_at", OCENJENO),
        )
    }
    poslji(
        odjemalec,
        [poskus(p, rating="lahko", **kasneje) for p in postavke(motor, drugi)],
        telefon,
    )


class TestStatistika:
    def test_predmeti_nosijo_cip_v_barvi_in_povezavo(
        self, odjemalec: TestClient, z_ocenami: None
    ) -> None:
        besedilo = odjemalec.get("/admin/statistics?leto=vse").text

        assert re.search(
            r'<span class="cip" style="--barva: #2d5a8e"><span class="koda">MAT</span></span>\s*'
            r'<a href="/admin/statistics/subjects/MAT\?leto=vse">Matematika</a>',
            besedilo,
        )

    def test_predmet_brez_ocen_ima_prazen_pas_in_crtico(
        self, odjemalec: TestClient, z_ocenami: None
    ) -> None:
        besedilo = odjemalec.get("/admin/statistics?leto=vse").text
        vrstica_geo = besedilo[besedilo.index('<span class="koda">GEO</span>') :]
        vrstica_geo = vrstica_geo[: vrstica_geo.index("</tr>")]

        assert 'class="razporeditev prazna"' in vrstica_geo
        assert '<span class="drobno">—</span>' in vrstica_geo

    def test_kartica_skupaj_ima_stevila_sirok_pas_in_pravilo(
        self, odjemalec: TestClient, z_ocenami: None
    ) -> None:
        besedilo = odjemalec.get("/admin/statistics?leto=vse").text
        zacetek = besedilo.index('<section class="kartica statistika-skupaj">')
        kartica = besedilo[zacetek : besedilo.index("</section>", zacetek)]

        assert re.findall(r"<dt>([^<]+)</dt><dd>([^<]+)</dd>", kartica) == [
            ("Ocen", "3"),
            ("Pravilnih", "100 %"),
            ("Težkih", "67 %"),
        ]
        assert 'class="razporeditev sirok"' in kartica
        assert "Ocene so samoocena po razkritju odgovora" in kartica
        # Predmeti so po urniku, ne po težavnosti.
        assert "Najtežje je zgoraj" not in kartica

    def test_legenda_nasteje_stiri_ocene_v_vrstnem_redu_pasu(
        self, odjemalec: TestClient
    ) -> None:
        besedilo = odjemalec.get("/admin/statistics").text
        zacetek = besedilo.index('<ul class="legenda-ocen">')
        legenda = besedilo[zacetek : besedilo.index("</ul>", zacetek)]

        assert re.findall(r'<span class="pika pas-(\d)"[^>]*></span>([^<]+)</li>', legenda) == [
            ("0", "Nisem vedela"),
            ("1", "Težko"),
            ("2", "Srednje"),
            ("3", "Lahko"),
        ]


class TestStatistikaPredmeta:
    def test_veckrat_postavljena_so_prva_enkrat_postavljena_zlozena(
        self, odjemalec: TestClient, z_ocenami: None
    ) -> None:
        vsebina = vsebina_strani(odjemalec.get("/admin/statistics/subjects/MAT?leto=vse").text)
        mesta = [
            vsebina.index(niz)
            for niz in (
                "statistika-skupaj",
                '<h2 id="veckrat">Postavljena večkrat · 1 vprašanje</h2>',
                "<h2>Po šolskih letih</h2>",
                "<h2>Snovi</h2>",
                '<details class="kartica" id="enkrat">',
            )
        ]

        assert mesta == sorted(mesta)
        assert "<summary>Postavljena enkrat · 1 vprašanje</summary>" in vsebina

    def test_zaporedje_ocen_je_vrsta_kartic_s_povezavo_na_kviz(
        self, odjemalec: TestClient, z_ocenami: None
    ) -> None:
        vsebina = vsebina_strani(odjemalec.get("/admin/statistics/subjects/MAT?leto=vse").text)
        veckrat = vsebina[vsebina.index('id="veckrat"') : vsebina.index("<h2>Po šolskih letih")]

        ocene = re.findall(
            r'<span class="ocena-v-zaporedju">\s*[\d. ]+<strong>([^<]+)</strong>\s*'
            r'\(<a href="/admin/quizzes/[^"]+">',
            veckrat,
        )
        assert ocene == ["Težko", "Lahko"]
        assert veckrat.count("→") == 1

    def test_glava_ima_drobtine_platnico_in_najtezje_zgoraj(
        self, odjemalec: TestClient, z_ocenami: None
    ) -> None:
        besedilo = odjemalec.get("/admin/statistics/subjects/MAT?leto=vse").text

        assert '<li><a href="/admin/statistics?leto=vse">Statistika</a></li>' in besedilo
        assert '<span class="platnica majhna" style="--barva: #2d5a8e"' in besedilo
        assert "Najtežje je zgoraj." in besedilo


class TestPrijava:
    @pytest.fixture
    def brez_seje(self, aplikacija: FastAPI, stars: str) -> PrijavljenOdjemalec:
        return PrijavljenOdjemalec(aplikacija, base_url="https://testserver")

    def test_stran_je_brez_menija_s_plosco_in_desetimi_hrbti(
        self, brez_seje: PrijavljenOdjemalec
    ) -> None:
        besedilo = brez_seje.get(prijava.POT_PRIJAVE).text

        assert "<nav" not in besedilo
        assert '<div class="prijava-plosca" aria-hidden="true">' in besedilo
        hrbti = re.findall(
            r'<li style="--barva: (#[0-9a-f]{6})"><span>([A-Z]{3})</span></li>', besedilo
        )
        assert [(koda, barva) for barva, koda in hrbti] == list(BARVE)

    def test_obrazec_ohrani_pot_polja_in_zeton(self, brez_seje: PrijavljenOdjemalec) -> None:
        """`ADR-056` I."""
        besedilo = brez_seje.get(prijava.POT_PRIJAVE).text

        assert re.search(
            r'<form method="post" action="/admin/login" class="prijava">\s*'
            r'<input type="hidden" name="csrf" value="[^"]+">\s*'
            r'<input type="hidden" name="cilj" value="[^"]*">',
            besedilo,
        )
        assert re.findall(r'<input class="ime" type="(\w+)" id="\w+" name="(\w+)"', besedilo) == [
            ("email", "identifikator"),
            ("password", "geslo"),
        ]
        assert "<script" not in besedilo.lower()

    def test_slog_in_pisava_prijavne_strani_sta_dosegljiva_brez_seje(
        self, brez_seje: PrijavljenOdjemalec
    ) -> None:
        besedilo = brez_seje.get(prijava.POT_PRIJAVE).text
        [slog] = re.findall(r'<link rel="stylesheet" href="([^"]+)">', besedilo)

        odgovor = brez_seje.get(slog, follow_redirects=False)

        assert odgovor.status_code == 200
        for pisava in re.findall(r'url\("(\.\./pisave/[^"]+)"\)', odgovor.text):
            pot = "/admin/static/" + pisava.removeprefix("../")
            assert brez_seje.get(pot, follow_redirects=False).status_code == 200, pot

    def test_napaka_je_obvestilo_nad_obrazcem(self, brez_seje: PrijavljenOdjemalec) -> None:
        stran = brez_seje.get(prijava.POT_PRIJAVE)
        zeton = re.search(r'name="csrf" value="([^"]+)"', stran.text)
        assert zeton is not None

        odgovor = brez_seje.post(
            prijava.POT_PRIJAVE,
            data={"csrf": zeton.group(1), "identifikator": "nekdo@primer.test", "geslo": "x" * 12},
        )

        besedilo = odgovor.text
        assert '<p class="obvestilo napaka">' in besedilo
        assert besedilo.index('<p class="obvestilo napaka">') < besedilo.index(
            '<form method="post" action="/admin/login"'
        )

    def test_brez_googla_ni_ne_gumba_ne_locila(self, brez_seje: PrijavljenOdjemalec) -> None:
        besedilo = brez_seje.get(prijava.POT_PRIJAVE).text

        assert "Google" not in besedilo
        assert "locilo-ali" not in besedilo

    def test_z_googlom_je_gumb_svoj_obrazec_pod_locilom(
        self, slike: Path, motor: Engine, stars: str
    ) -> None:
        nastavitve = naredi_testne_nastavitve(slike).model_copy(
            update={
                "google_client_id": "odjemalec-1",
                "google_client_secret": "skrivnost-1",
                "domena": "solski.test",
            }
        )
        aplikacija = create_app(nastavitve=nastavitve, motor=motor)
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            besedilo = odjemalec.get(prijava.POT_PRIJAVE).text

        assert besedilo.index("locilo-ali") < besedilo.index('action="/auth/google/login"')
        assert re.search(
            r'<form method="post" action="/auth/google/login" class="prijava">\s*'
            r'<input type="hidden" name="csrf" value="[^"]+">\s*'
            r'<button class="gumb obrobljen sirok" type="submit">Prijava z Google računom</button>',
            besedilo,
        )
