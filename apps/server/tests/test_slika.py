"""Stran slike po V5-R01: listanje s položajem, drobtine, stanja, upravljanje.

Kar je stran znala že prej (povečan prikaz, premik, ponovna obdelava, arhiv),
varujejo testi svojih zahtev v `test_admin.py` in `test_arhiv.py`. Tu je samo
tisto, kar je V5-R01 dodala ali prestavila (`docs/poc/POC-02.md`, stran Slika).
"""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.casi import cas_z_imenom_dneva
from app.db import MaterialsRepository, PolozajVPredmetu
from app.models import Material
from tests.conftest import CVEK_ID, vsebina_strani
from tests.test_admin import UUID_DVA, UUID_ENA, UUID_TRI, zapisi


@pytest.fixture(autouse=True)
def _druzina_ima_otroka(otrok: str) -> str:
    return otrok


def tri_zaporedne(motor: Engine, slike: Path) -> None:
    """Tri slike matematike; najnovejša je `UUID_TRI`, najstarejša `UUID_ENA`."""
    zapisi(motor, slike, UUID_ENA, "MAT", "2026-09-04T07:30:00+00:00")
    zapisi(motor, slike, UUID_DVA, "MAT", "2026-09-04T08:30:00+00:00")
    zapisi(motor, slike, UUID_TRI, "MAT", "2026-09-04T09:30:00+00:00")


def stran(odjemalec: TestClient, material_id: str) -> str:
    odgovor = odjemalec.get(f"/admin/materials/{material_id}")
    assert odgovor.status_code == 200
    return odgovor.text


def listanje(besedilo: str) -> str:
    """Listanje na strani (ne puščici povečanega prikaza), brez oznak."""
    zacetek = besedilo.index('<nav class="listanje"')
    return besedilo[zacetek : besedilo.index("</nav>", zacetek)]


def nastavi(motor: Engine, material_id: str, **polja: object) -> None:
    with Session(motor) as seja:
        seja.execute(update(Material).where(Material.id == material_id).values(**polja))
        seja.commit()


class TestPolozaj:
    def test_mesto_in_stevilo_v_istem_vrstnem_redu_kot_sosedi(
        self, motor: Engine, slike: Path
    ) -> None:
        tri_zaporedne(motor, slike)
        zapisi(motor, slike, "druga-snov", "SLJ", "2026-09-04T10:00:00+00:00")

        with Session(motor) as seja:
            repozitorij = MaterialsRepository(seja, CVEK_ID)
            polozaji = {
                ime: repozitorij.polozaj_v_predmetu(seja.get_one(Material, ime))
                for ime in (UUID_TRI, UUID_DVA, UUID_ENA)
            }

        # Najnovejša je prva; slika drugega predmeta v štetje ne sodi.
        assert polozaji == {
            UUID_TRI: PolozajVPredmetu(prejsnji=None, naslednji=UUID_DVA, mesto=1, vseh=3),
            UUID_DVA: PolozajVPredmetu(prejsnji=UUID_TRI, naslednji=UUID_ENA, mesto=2, vseh=3),
            UUID_ENA: PolozajVPredmetu(prejsnji=UUID_DVA, naslednji=None, mesto=3, vseh=3),
        }

    def test_arhivirana_slika_ne_steje_in_sama_nima_polozaja(
        self, motor: Engine, slike: Path
    ) -> None:
        tri_zaporedne(motor, slike)
        nastavi(motor, UUID_DVA, archived_at=datetime(2026, 9, 5, tzinfo=UTC))

        with Session(motor) as seja:
            repozitorij = MaterialsRepository(seja, CVEK_ID)
            arhivirana = repozitorij.polozaj_v_predmetu(seja.get_one(Material, UUID_DVA))
            najstarejsa = repozitorij.polozaj_v_predmetu(seja.get_one(Material, UUID_ENA))

        assert arhivirana is None
        assert najstarejsa == PolozajVPredmetu(
            prejsnji=UUID_TRI, naslednji=None, mesto=2, vseh=2
        )


class TestListanjeNaStrani:
    def test_srednja_slika_ima_obe_povezavi_in_polozaj(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        tri_zaporedne(motor, slike)

        vrstica = listanje(stran(odjemalec, UUID_DVA))

        assert "2 od 3" in vrstica
        # Novejša levo, starejša desno — in **brez** sidra povečave: te
        # povezave peljejo na stran sosede, ne v njen povečan prikaz.
        assert re.findall(r'<a class="gumb obrobljen majhen" href="([^"]+)">', vrstica) == [
            f"/admin/materials/{UUID_TRI}",
            f"/admin/materials/{UUID_ENA}",
        ]
        assert vrstica.index("Novejša") < vrstica.index("2 od 3") < vrstica.index("Starejša")

    def test_na_robu_gumb_ni_povezava(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        tri_zaporedne(motor, slike)

        najnovejsa = listanje(stran(odjemalec, UUID_TRI))
        najstarejsa = listanje(stran(odjemalec, UUID_ENA))

        assert "1 od 3" in najnovejsa
        assert re.findall(r'href="([^"]+)"', najnovejsa) == [f"/admin/materials/{UUID_DVA}"]
        assert re.search(
            r'<span class="gumb obrobljen majhen onemogocen" aria-disabled="true">.*?Novejša',
            najnovejsa,
            re.S,
        )
        assert "3 od 3" in najstarejsa
        assert re.findall(r'href="([^"]+)"', najstarejsa) == [f"/admin/materials/{UUID_DVA}"]

    def test_edina_slika_je_ena_od_ene(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        vrstica = listanje(stran(odjemalec, UUID_ENA))

        assert "1 od 1" in vrstica
        assert "href=" not in vrstica

    def test_arhivirana_slika_listanja_nima(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        tri_zaporedne(motor, slike)
        nastavi(motor, UUID_DVA, archived_at=datetime(2026, 9, 5, tzinfo=UTC))

        besedilo = stran(odjemalec, UUID_DVA)

        assert '<nav class="listanje"' not in besedilo
        assert " od " not in vsebina_strani(besedilo).split("<h1>")[0]

    def test_slika_brez_datoteke_listanje_ima_povecave_pa_ne(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        tri_zaporedne(motor, slike)
        zapisi(motor, slike, "brez-datoteke", "MAT", "2026-09-04T10:30:00+00:00", vsebina=None)

        besedilo = stran(odjemalec, "brez-datoteke")

        assert "1 od 4" in listanje(besedilo)
        assert 'id="prekritje"' not in besedilo
        assert "<script" not in besedilo


class TestGlavaStraniSlike:
    def test_naslov_je_dan_z_imenom_in_uro(self) -> None:
        # 4. 9. 2026 ob 7:30 UTC je v Ljubljani petek ob 9:30.
        trenutek = datetime(2026, 9, 4, 7, 30, tzinfo=UTC)

        assert cas_z_imenom_dneva(trenutek) == "Petek, 4. september ob 09:30"

    def test_naslov_dan_cez_lokalno_polnoc(self) -> None:
        # Nedelja ob 22:30 UTC je v Ljubljani že ponedeljek.
        trenutek = datetime(2026, 9, 6, 22, 30, tzinfo=UTC)

        assert cas_z_imenom_dneva(trenutek) == "Ponedeljek, 7. september ob 00:30"

    def test_drobtine_vodijo_na_predmete_in_predmet(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        besedilo = stran(odjemalec, UUID_ENA)
        zacetek = besedilo.index('<ol class="drobtine">')
        drobtine = besedilo[zacetek : besedilo.index("</ol>", zacetek)]

        assert re.findall(r'<a href="([^"]+)">([^<]+)</a>', drobtine) == [
            ("/admin", "Predmeti"),
            ("/admin/subjects/MAT", "Matematika"),
        ]
        # Tretja drobtina je teden slike na strani predmeta in ni povezava.
        assert '<li aria-current="page">31. avgust \u2013 4. september</li>' in drobtine

    def test_glava_nosi_naslov_predmet_in_barvo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        besedilo = stran(odjemalec, UUID_ENA)

        assert "<h1>Petek, 4. september ob 09:30</h1>" in besedilo
        assert '<span class="platnica majhna" style="--barva: #2d5a8e"' in besedilo
        assert '<p class="pod">MAT — Matematika</p>' in besedilo

    @pytest.mark.parametrize(
        ("polja", "razred", "stanje"),
        [
            ({"status": "new"}, "caka", "čaka na obdelavo"),
            ({"status": "processing"}, "caka", "v obdelavi"),
            ({"status": "failed", "error": "ni šlo"}, "napaka", "napaka"),
            ({"status": "ready", "readable": True}, "ok", "obdelano"),
            ({"status": "ready", "readable": False}, "napaka", "obdelano — slika ni berljiva"),
        ],
    )
    def test_oznaka_stanja_ima_barvo_stanja(
        self,
        odjemalec: TestClient,
        motor: Engine,
        slike: Path,
        polja: dict[str, object],
        razred: str,
        stanje: str,
    ) -> None:
        zapisi(motor, slike)
        nastavi(motor, UUID_ENA, **polja)

        besedilo = stran(odjemalec, UUID_ENA)

        oznaka = f'<span class="oznaka {razred}"><span class="prva-velika">{stanje}</span></span>'
        assert oznaka in besedilo

    def test_arhivirana_slika_ima_drugo_oznako(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        nastavi(motor, UUID_ENA, archived_at=datetime(2026, 9, 5, tzinfo=UTC))

        besedilo = stran(odjemalec, UUID_ENA)

        assert '<span class="oznaka"><strong>v arhivu</strong></span>' in besedilo


class TestVsebinaInUpravljanje:
    def test_ucna_vsebina_je_pred_upravljanjem_in_tehnicnimi_podatki(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Kaj šteje kot »ok« v `POC-02`: učna vsebina prva, upravljanje ne moti."""
        zapisi(motor, slike)
        nastavi(
            motor,
            UUID_ENA,
            status="ready",
            readable=True,
            summary="Povzetek snovi.",
            transcript="Prepis snovi.",
            model="model-x",
            prompt="poslano",
        )

        vsebina = vsebina_strani(stran(odjemalec, UUID_ENA))
        mesta = [
            vsebina.index(niz)
            for niz in (
                "<h2>Povzetek</h2>",
                "<h2>Vprašanja</h2>",
                "<h2>Prepis</h2>",
                "<h2>Upravljanje</h2>",
                "<summary>Tehnični podatki</summary>",
                "Poslani prompt",
            )
        ]

        assert mesta == sorted(mesta)
        # Tehnični podatki so zloženi: `details` brez `open`.
        assert '<details class="kartica tehnicno">' in vsebina

    def test_vsako_dejanje_pove_posledico_in_obdrzi_svoj_obrazec(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        besedilo = stran(odjemalec, UUID_ENA)
        zacetek = besedilo.index('<section class="kartica upravljanje">')
        upravljanje = besedilo[zacetek : besedilo.index("</section>", zacetek)]

        assert re.findall(r"<h3>([^<]+)</h3>", upravljanje) == [
            "Premakni v drug predmet",
            "Obdelaj znova",
            "Arhiviraj",
        ]
        assert upravljanje.count('<div class="dejanje">') == 3
        assert upravljanje.count('<p class="drobno">') == 3
        # `ADR-056` I: poti, metode in imena polj so, kot so bili.
        assert f'method="post" action="/admin/materials/{UUID_ENA}/subject"' in upravljanje
        assert '<select id="premik-predmet" name="subject">' in upravljanje
        assert f'<form method="post" action="/admin/materials/{UUID_ENA}/reprocess">' in upravljanje
        # Uničujoče dejanje je rdeče obrobljeno, ne polno.
        assert (
            f'<a class="gumb majhen nevaren" href="/admin/materials/{UUID_ENA}/archive">'
            in upravljanje
        )

    def test_nepovratno_brisanje_je_edini_polno_rdec_gumb(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        zdaj = datetime(2026, 9, 5, tzinfo=UTC)
        nastavi(motor, UUID_ENA, archived_at=zdaj, device_deleted_at=zdaj)

        besedilo = stran(odjemalec, UUID_ENA)

        assert besedilo.count("nepovraten") == 1
        assert (
            f'<a class="gumb majhen nepovraten" href="/admin/materials/{UUID_ENA}/delete">'
            "Izbriši dokončno</a>" in besedilo
        )

    def test_povecavo_odpreta_slika_in_gumb_obe_povezavi_na_izvirnik(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # `ADR-024`, meja 3: brez skripte obe povezavi odpreta datoteko.
        zapisi(motor, slike)

        besedilo = stran(odjemalec, UUID_ENA)

        povezave = re.findall(r'<a class="([^"]+)" href="([^"]+)" data-povecava>', besedilo)
        assert povezave == [
            ("povecaj", f"/admin/materials/{UUID_ENA}/image"),
            ("gumb obrobljen majhen", f"/admin/materials/{UUID_ENA}/image"),
        ]
        assert 'querySelectorAll("a[data-povecava]")' in besedilo
