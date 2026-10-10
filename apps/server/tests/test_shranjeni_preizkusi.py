"""Shranjeni preizkusi (V4-R08): shranjevanje, pregled, ogled, test na osnovi.

Pokriva tabelo „Test casi" iz `docs/plan/V4-R08.md`. Tesnjenje med družinama
je v `test_tesnjenje.py`, migracija v `test_migracija.py`.

Obnašanja strani v brskalniku (opozorila pred izgubo dela, Shrani in Zavrzi,
izris ogleda, tisk) pytest ne izvede — to je ročni preizkus v fazi 9b
(`docs/odlocitve/ADR-054`, `ADR-055`). Tu so trditve o tem, kaj strežnik
zapiše in kaj stran **vsebuje**.
"""

import html
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app import preizkus
from app.db import PreizkusiRepository
from app.main import create_app
from app.models import Material, Preizkus
from app.settings import Settings
from tests.conftest import (
    BRAT_ID,
    CVEK_ID,
    OTROK_ID,
    TUJ_OTROK_ID,
    PrijavljenOdjemalec,
    ustvari_otroka,
)
from tests.test_admin import UUID_DVA, UUID_ENA, arhiviraj, zapisi
from tests.test_preizkusi import VELJAVEN, LazenKlicalec, generiraj, sestavi, snov_s_prepisom

#: Naslovljenec mora biti otrok družine (`PreizkusiRepository.shrani`), zato
#: privzeti otrok obstaja v vsakem testu te datoteke.
pytestmark = pytest.mark.usefixtures("otrok")

#: Identifikator, kakršnega urejevalnik dobi od strežnika.
NOV_ID = "d1e2f3a4-b5c6-4d7e-8f90-a1b2c3d4e5f6"
DRUG_ID = "f6e5d4c3-b2a1-4f09-8e7d-6c5b4a392817"
OSNOVA_ID = "a9b8c7d6-e5f4-4a3b-8c2d-1e0f9a8b7c6d"
NEZNAN_ID = "00000000-0000-4000-8000-000000000000"

DAN_POZNEJE = "2026-09-05T07:30:00+00:00"
PRVI = datetime(2026, 10, 1, 8, tzinfo=UTC)
TRETJI = datetime(2026, 10, 3, 16, 5, tzinfo=UTC)

#: Imena stolpcev tabele, za primerjavo cele vrstice pred in po.
STOLPCI = tuple(stolpec.name for stolpec in Preizkus.__table__.columns)


@pytest.fixture
def klicalec() -> LazenKlicalec:
    return LazenKlicalec()


@pytest.fixture
def aplikacija(nastavitve: Settings, motor: Engine, klicalec: LazenKlicalec) -> FastAPI:
    """Prepiše fixture iz `conftest.py`: aplikacija ima klicalca preizkusa."""
    return create_app(nastavitve=nastavitve, motor=motor, klicalec_preizkusa=klicalec)


def shrani(odjemalec: PrijavljenOdjemalec, **polja: Any) -> Any:
    """`POST /admin/assessments`, kot ga pošlje skripta ob „Shrani"."""
    podatki: dict[str, Any] = {
        "id": NOV_ID,
        "subject": "MAT",
        "snov": [UUID_ENA],
        "test_md": VELJAVEN["test_md"],
        "resitve_md": VELJAVEN["resitve_md"],
        "model": "model-iz-odgovora",
    }
    podatki.update(polja)
    return odjemalec.post("/admin/assessments", data=podatki)


def vsi(motor: Engine) -> list[Preizkus]:
    """Vse vrstice `preizkusi`, najstarejša prva."""
    with Session(motor) as seja:
        return list(seja.scalars(select(Preizkus).order_by(Preizkus.saved_at, Preizkus.id)))


def v_bazo(
    motor: Engine,
    stars: str,
    preizkus_id: str = OSNOVA_ID,
    *,
    child_id: str = OTROK_ID,
    subject: str = "MAT",
    title: str = "Ulomki, prvič",
    test_md: str = "# Ulomki, prvič\n\n## 1. Seštej (2 točki)\n\n$\\frac{1}{4}$ [odgovor]",
    source_md: str = "## MAT — 1. september 2026, 09:00\n\n### Prepis\nZAMRZNJENA-SNOV",
    saved_at: datetime | None = None,
) -> str:
    """Shranjen preizkus neposredno v bazo — stanje, ne pot do njega."""
    with Session(motor) as seja:
        seja.add(
            Preizkus(
                id=preizkus_id,
                family_id=CVEK_ID,
                child_id=child_id,
                subject=subject,
                title=title,
                test_md=test_md,
                solutions_md="# Rešitve\n\n## 1.\n\n**1/4**",
                source_md=source_md,
                model="model-osnove",
                saved_at=saved_at or datetime(2026, 10, 1, 8, 0, tzinfo=UTC),
                saved_by=stars,
            )
        )
        seja.commit()
    return preizkus_id


def daj_bratu(motor: Engine, material_id: str) -> None:
    """Snov pripiše drugemu otroku družine."""
    with Session(motor) as seja:
        material = seja.get(Material, material_id)
        assert material is not None
        material.child_id = BRAT_ID
        seja.commit()


# --- Pravila (`app/preizkus.py`) ---


class TestNaslov:
    def test_naslov_je_prva_vrstica_z_enim_grebenom(self) -> None:
        assert preizkus.naslov_iz_testa("\n# Ulomki \n\n## 1. Naloga", "x") == "Ulomki"

    def test_naloga_ni_naslov(self) -> None:
        assert preizkus.naslov_iz_testa("## 1. Naloga (2 točki)\n\nIzračunaj.", "Nadomestni") == (
            "Nadomestni"
        )

    def test_prazen_naslov_pade_na_nadomestnega(self) -> None:
        assert preizkus.naslov_iz_testa("#  \nbesedilo", "Nadomestni") == "Nadomestni"

    def test_predolg_naslov_se_obreze_na_sirino_stolpca(self) -> None:
        naslov = preizkus.naslov_iz_testa("# " + "a" * 300, "x")

        assert naslov == "a" * preizkus.NAJDALJSI_NASLOV


class TestNaslovljenec:
    def test_snov_enega_otroka_doloci_naslovljenca_ne_glede_na_polje(self) -> None:
        assert preizkus.izberi_naslovljenca(["a", "a"], "") == "a"
        # Polje iz brskalnika ne preglasi tega, kar pove snov.
        assert preizkus.izberi_naslovljenca(["a", "a"], "b") == "a"

    def test_pri_vec_otrocih_velja_samo_otrok_te_snovi(self) -> None:
        assert preizkus.izberi_naslovljenca(["a", "b"], "b") == "b"
        assert preizkus.izberi_naslovljenca(["a", "b"], "") is None
        assert preizkus.izberi_naslovljenca(["a", "b"], "c") is None

    def test_brez_snovi_naslovljenca_ni(self) -> None:
        assert preizkus.izberi_naslovljenca([], "a") is None


class TestEnakIzhodiscu:
    def test_konci_vrstic_in_robni_presledki_ne_stejejo(self) -> None:
        assert preizkus.je_enak_izhodiscu("a\nb\n", " r ", "a\r\nb", "r")

    def test_sprememba_testa_ali_resitev_steje(self) -> None:
        assert not preizkus.je_enak_izhodiscu("a", "r", "b", "r")
        assert not preizkus.je_enak_izhodiscu("a", "r", "a", "s")


# --- Shrani ---


class TestShrani:
    def test_shrani_naredi_en_zapis_z_vsemi_polji(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path, stars: str
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")
        pred = datetime.now(UTC) - timedelta(seconds=5)

        odgovor = shrani(odjemalec)

        assert odgovor.status_code == 200, odgovor.text
        assert odgovor.json() == {"pot": f"/admin/assessments/{NOV_ID}"}
        (zapis,) = vsi(motor)
        assert zapis.id == NOV_ID
        assert zapis.family_id == CVEK_ID
        assert zapis.child_id == OTROK_ID
        assert zapis.subject == "MAT"
        assert zapis.title == "Preverjanje znanja"
        assert zapis.test_md == VELJAVEN["test_md"]
        assert zapis.solutions_md == VELJAVEN["resitve_md"]
        assert zapis.source_md.startswith("## MAT — 4. september 2026, 09:30")
        assert "Ulomke seštevamo." in zapis.source_md
        assert zapis.model == "model-iz-odgovora"
        assert zapis.saved_by == stars
        assert zapis.base_id is None
        assert zapis.saved_at.replace(tzinfo=UTC) >= pred

    def test_snovi_naslova_in_otroka_streznik_ne_vzame_iz_brskalnika(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path, brat: str
    ) -> None:
        # Snov je od enega otroka, zato je naslovljenec on — tudi če brskalnik
        # pošlje brata. Besedilo snovi in naslov se ne sprejmeta v nobeni obliki.
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        odgovor = shrani(
            odjemalec,
            otrok=brat,
            source_md="PODTAKNJENA-SNOV",
            snov_md="PODTAKNJENA-SNOV",
            title="PODTAKNJEN-NASLOV",
            naslov="PODTAKNJEN-NASLOV",
            child_id=brat,
            saved_by=brat,
        )

        assert odgovor.status_code == 200
        (zapis,) = vsi(motor)
        assert zapis.child_id == OTROK_ID
        assert "PODTAKNJENA-SNOV" not in zapis.source_md
        assert zapis.title == "Preverjanje znanja"
        assert zapis.saved_by != brat

    def test_test_brez_naslova_dobi_nadomestnega_s_predmetom(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        shrani(odjemalec, test_md="## 1. Naloga (2 točki)\n\nIzračunaj.")

        (zapis,) = vsi(motor)
        assert re.fullmatch(r"Test — MAT — \d{1,2}\. \d{1,2}\. \d{4}", zapis.title), zapis.title

    def test_ponovljen_shrani_ne_naredi_drugega_zapisa(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        prvi = shrani(odjemalec)
        # Drugi klik z istim identifikatorjem, tudi z drugo vsebino in po
        # tem, ko je snov že arhivirana: ponovitev, ne popravek.
        arhiviraj(motor, UUID_ENA)
        drugi = shrani(odjemalec, test_md="# Drugačen test")

        assert prvi.json() == drugi.json() == {"pot": f"/admin/assessments/{NOV_ID}"}
        (zapis,) = vsi(motor)
        assert zapis.test_md == VELJAVEN["test_md"]

    @pytest.mark.parametrize(
        ("polja", "del_sporocila"),
        [
            ({"test_md": "  \n"}, "Testa še ni"),
            ({"model": " "}, "ni več mogoče shraniti"),
            ({"id": "ni-uuid"}, "ni več mogoče shraniti"),
            ({"id": NOV_ID.upper()}, "ni več mogoče shraniti"),
            ({"id": ""}, "ni več mogoče shraniti"),
            ({"subject": "SLJ"}, "samo pri matematiki"),
            ({"snov": []}, "Izbrane snovi ni več"),
            ({"snov": [NEZNAN_ID]}, "Izbrane snovi ni več"),
        ],
    )
    def test_neveljaven_vnos_je_400_s_slovenskim_sporocilom_in_brez_zapisa(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        slike: Path,
        polja: dict[str, Any],
        del_sporocila: str,
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        odgovor = shrani(odjemalec, **polja)

        assert odgovor.status_code == 400
        assert del_sporocila in odgovor.json()["napaka"]
        assert vsi(motor) == []

    def test_predolgo_ime_modela_se_obreze(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        shrani(odjemalec, model="m" * 300)

        (zapis,) = vsi(motor)
        assert zapis.model == "m" * preizkus.NAJDALJSI_MODEL

    def test_snov_arhivirana_med_delom_izpade_iz_zapisa(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "PRVA-SNOV")
        snov_s_prepisom(motor, slike, UUID_DVA, "DRUGA-SNOV", taken_at="2026-09-05T07:30:00+00:00")
        arhiviraj(motor, UUID_DVA)

        odgovor = shrani(odjemalec, snov=[UUID_ENA, UUID_DVA])

        assert odgovor.status_code == 200
        (zapis,) = vsi(motor)
        assert "PRVA-SNOV" in zapis.source_md
        assert "DRUGA-SNOV" not in zapis.source_md

    def test_vsa_snov_arhivirana_shranjevanje_zavrne(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")
        arhiviraj(motor, UUID_ENA)

        odgovor = shrani(odjemalec)

        assert odgovor.status_code == 400
        assert "Test natisni" in odgovor.json()["napaka"]
        assert vsi(motor) == []


class TestNaslovljenecObShranjevanju:
    @pytest.fixture
    def snov_dveh(self, motor: Engine, slike: Path, brat: str) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Mašina snov.")
        snov_s_prepisom(motor, slike, UUID_DVA, "Nejčeva snov.", taken_at=DAN_POZNEJE)
        daj_bratu(motor, UUID_DVA)

    @pytest.mark.usefixtures("snov_dveh")
    def test_snov_dveh_otrok_brez_izbire_se_ne_shrani(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        odgovor = shrani(odjemalec, snov=[UUID_ENA, UUID_DVA])

        assert odgovor.status_code == 400
        assert "Izberi otroka" in odgovor.json()["napaka"]
        assert vsi(motor) == []

    @pytest.mark.usefixtures("snov_dveh")
    def test_izbrani_otrok_snovi_postane_naslovljenec(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        odgovor = shrani(odjemalec, snov=[UUID_ENA, UUID_DVA], otrok=BRAT_ID)

        assert odgovor.status_code == 200
        (zapis,) = vsi(motor)
        assert zapis.child_id == BRAT_ID

    @pytest.mark.usefixtures("snov_dveh")
    def test_otrok_tuje_druzine_ni_naslovljenec(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, tuj_otrok: str
    ) -> None:
        odgovor = shrani(odjemalec, snov=[UUID_ENA, UUID_DVA], otrok=TUJ_OTROK_ID)

        assert odgovor.status_code == 400
        assert vsi(motor) == []

    def test_otrok_brez_snovi_v_izboru_ni_naslovljenec(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path, brat: str
    ) -> None:
        # Tretji otrok družine, ki v izboru nima nobene slike.
        tretji = ustvari_otroka(motor, user_id=None, identifikator="ana", prikazno_ime="Ana")
        snov_s_prepisom(motor, slike, UUID_ENA, "Mašina snov.")
        snov_s_prepisom(motor, slike, UUID_DVA, "Nejčeva snov.", taken_at=DAN_POZNEJE)
        daj_bratu(motor, UUID_DVA)

        odgovor = shrani(odjemalec, snov=[UUID_ENA, UUID_DVA], otrok=tretji)

        assert odgovor.status_code == 400
        assert vsi(motor) == []

    def test_deaktiviran_otrok_je_dovoljen_naslovljenec(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        # Test je na papirju in prijave ne potrebuje (`ADR-055` H) — za
        # razliko od kviza, ki deaktiviranega otroka ne ponudi (`ADR-039` A).
        ustvari_otroka(
            motor, user_id=BRAT_ID, identifikator="nejc", prikazno_ime="Nejc", aktiven=False
        )
        snov_s_prepisom(motor, slike, UUID_ENA, "Mašina snov.")
        snov_s_prepisom(motor, slike, UUID_DVA, "Nejčeva snov.", taken_at=DAN_POZNEJE)
        daj_bratu(motor, UUID_DVA)

        stran = sestavi(odjemalec, "MAT", UUID_ENA, UUID_DVA).text
        odgovor = shrani(odjemalec, snov=[UUID_ENA, UUID_DVA], otrok=BRAT_ID)

        assert f'<option value="{BRAT_ID}">Nejc</option>' in stran
        assert odgovor.status_code == 200, odgovor.text
        (zapis,) = vsi(motor)
        assert zapis.child_id == BRAT_ID

    @pytest.mark.usefixtures("snov_dveh")
    def test_urejevalnik_ponudi_izbirnik_samo_pri_snovi_vec_otrok(
        self, odjemalec: PrijavljenOdjemalec
    ) -> None:
        mesana = sestavi(odjemalec, "MAT", UUID_ENA, UUID_DVA).text
        ena = sestavi(odjemalec, "MAT", UUID_ENA).text

        izbirnik = mesana[mesana.index('<select id="otrok">') : mesana.index("</select>")]
        assert re.findall(r'<option value="([^"]*)">', izbirnik) == ["", OTROK_ID, BRAT_ID]
        assert "Maša" in izbirnik
        assert "Nejc" in izbirnik
        assert '<select id="otrok">' not in ena


class TestDostop:
    def test_brez_seje_nove_poti_peljejo_na_prijavo(
        self, aplikacija: FastAPI, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brez_seje:
            for metoda, pot in (
                ("GET", "/admin/assessments"),
                ("POST", "/admin/assessments"),
                ("GET", f"/admin/assessments/{OSNOVA_ID}"),
                ("GET", f"/admin/assessments/{OSNOVA_ID}/compose"),
            ):
                odgovor = brez_seje.request(metoda, pot, follow_redirects=False)

                assert odgovor.status_code == 303, pot
                assert odgovor.headers["location"].startswith("/admin/login"), pot
        assert [zapis.id for zapis in vsi(motor)] == [OSNOVA_ID]

    def test_brez_csrf_zetona_se_ne_shrani(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        odgovor = shrani(odjemalec, csrf="napacen")

        assert odgovor.status_code == 403
        assert vsi(motor) == []


# --- Pregled ---


class TestPregled:
    def test_prazen_pregled_pove_kako_test_nastane(self, odjemalec: PrijavljenOdjemalec) -> None:
        odgovor = odjemalec.get("/admin/assessments")

        assert odgovor.status_code == 200
        assert "Shranjenega testa še ni" in odgovor.text
        assert "<table" not in odgovor.text

    def test_najnovejsi_je_prvi_z_datumom_predmetom_in_naslovom(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars, OSNOVA_ID, title="Starejši", saved_at=PRVI)
        v_bazo(motor, stars, NOV_ID, title="Novejši", saved_at=TRETJI)
        v_bazo(
            motor,
            stars,
            DRUG_ID,
            title="Slovnica",
            subject="SLJ",
            saved_at=datetime(2026, 10, 2, 8, tzinfo=UTC),
        )

        besedilo = odjemalec.get("/admin/assessments").text

        vrstice = re.findall(r'<td><a href="([^"]+)">([^<]+)</a></td>', besedilo)
        assert vrstice == [
            (f"/admin/assessments/{NOV_ID}", "Novejši"),
            (f"/admin/assessments/{DRUG_ID}", "Slovnica"),
            (f"/admin/assessments/{OSNOVA_ID}", "Starejši"),
        ]
        # Domači čas: 16:05 UTC je oktobra 18:05.
        assert "3. 10. 2026" in besedilo
        assert "18:05" in besedilo
        assert "<td>MAT</td>" in besedilo
        assert "<td>SLJ</td>" in besedilo

    def test_filter_po_predmetu(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars, OSNOVA_ID, title="Ulomki")
        v_bazo(motor, stars, DRUG_ID, title="Slovnica", subject="SLJ")

        vsi_testi = odjemalec.get("/admin/assessments").text
        samo_mat = odjemalec.get("/admin/assessments?predmet=MAT").text
        prazen = odjemalec.get("/admin/assessments?predmet=").text
        neznan = odjemalec.get("/admin/assessments?predmet=XYZ")

        assert 'href="/admin/assessments?predmet=MAT"' in vsi_testi
        assert 'href="/admin/assessments?predmet=SLJ"' in vsi_testi
        assert "Ulomki" in samo_mat
        assert "Slovnica" not in samo_mat
        assert "<strong>MAT</strong>" in samo_mat
        assert "Ulomki" in prazen
        assert "Slovnica" in prazen
        # Neznana koda ni napaka: prazen seznam in pot nazaj.
        assert neznan.status_code == 200
        assert "Pri predmetu XYZ ni shranjenega testa" in neznan.text
        assert "Ulomki" not in neznan.text

    def test_stolpec_z_otrokom_samo_pri_vec_otrocih(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)

        en_otrok = odjemalec.get("/admin/assessments").text

        assert "<th>Otrok</th>" not in en_otrok
        assert "Maša" not in en_otrok

    def test_pri_dveh_otrocih_vrstica_pove_cigav_je_test(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str, brat: str
    ) -> None:
        v_bazo(motor, stars, OSNOVA_ID, title="Mašin")
        v_bazo(motor, stars, NOV_ID, title="Nejčev", child_id=brat)

        besedilo = odjemalec.get("/admin/assessments").text

        assert "<th>Otrok</th>" in besedilo
        assert "<td>Maša</td>" in besedilo
        assert "<td>Nejc</td>" in besedilo

    def test_pregled_je_brez_skripte_in_brez_obrazca_za_pisanje(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)

        besedilo = odjemalec.get("/admin/assessments").text

        assert "<script" not in besedilo
        # Edini obrazec na strani je odjava v glavi: brisanja in arhiva ni.
        assert re.findall(r'<form method="post" action="([^"]+)"', besedilo) == ["/admin/logout"]


class TestPovezave:
    def test_pregled_admina_vodi_na_shranjene_teste(self, odjemalec: PrijavljenOdjemalec) -> None:
        assert '<a href="/admin/assessments">Shranjeni testi</a>' in odjemalec.get("/admin").text

    def test_stran_matematike_pove_koliko_testov_je_shranjenih(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path, stars: str
    ) -> None:
        zapisi(motor, slike)

        brez = odjemalec.get("/admin/subjects/MAT").text
        v_bazo(motor, stars, OSNOVA_ID)
        v_bazo(motor, stars, NOV_ID)
        v_bazo(motor, stars, DRUG_ID, subject="SLJ")
        z_dvema = odjemalec.get("/admin/subjects/MAT").text

        assert '<a href="/admin/assessments?predmet=MAT">Shranjeni testi (0)</a>' in brez
        assert '<a href="/admin/assessments?predmet=MAT">Shranjeni testi (2)</a>' in z_dvema

    def test_povezava_je_tudi_na_matematiki_brez_slik(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)

        assert "Shranjeni testi (1)" in odjemalec.get("/admin/subjects/MAT").text


# --- Ogled ---


class TestOgled:
    def test_ogled_nosi_test_resitve_in_snov(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)

        odgovor = odjemalec.get(f"/admin/assessments/{OSNOVA_ID}")

        assert odgovor.status_code == 200
        besedilo = html.unescape(odgovor.text)
        assert "<h1 class=\"ne-tiskaj\">Ulomki, prvič</h1>" in besedilo
        assert "MAT · shranjeno 1. 10. 2026" in besedilo
        assert "model model-osnove" in besedilo
        assert '<textarea id="vir-test" hidden># Ulomki, prvič' in besedilo
        assert "$\\frac{1}{4}$ [odgovor]" in besedilo
        assert '<textarea id="vir-resitve" hidden># Rešitve' in besedilo
        assert "ZAMRZNJENA-SNOV" in besedilo
        assert f'href="/admin/assessments/{OSNOVA_ID}/compose">Nov test na tej osnovi' in besedilo

    def test_besedilo_testa_gre_v_stran_ubezano(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        # Shranjen test je besedilo modela: v izris strežnika ne sme kot HTML.
        v_bazo(
            motor,
            stars,
            title="<b>Naslov</b>",
            test_md="# X\n</textarea><script>alert(1)</script>",
            source_md="</textarea><img src=x onerror=alert(2)>",
        )

        besedilo = odjemalec.get(f"/admin/assessments/{OSNOVA_ID}").text

        assert "<script>alert(1)" not in besedilo
        assert "<img src=x" not in besedilo
        assert "<b>Naslov</b>" not in besedilo
        assert "&lt;/textarea&gt;&lt;script&gt;alert(1)" in besedilo

    def test_ogled_ne_klice_streznika_in_nima_obrazca_za_pisanje(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)

        besedilo = odjemalec.get(f"/admin/assessments/{OSNOVA_ID}").text
        skripta = besedilo[besedilo.rindex("<script>") : besedilo.rindex("</script>")]

        assert re.findall(r'<script src="([^"]+)"', besedilo) == [
            "/admin/static/vendor/marked-15.0.12/marked.min.js",
            "/admin/static/vendor/katex-0.16.22/katex.min.js",
            "/admin/static/vendor/katex-0.16.22/contrib/auto-render.min.js",
        ]
        for prepovedano in (
            "fetch(",
            "XMLHttpRequest",
            "sendBeacon",
            "localStorage",
            "sessionStorage",
            ".submit(",
            "location",
        ):
            assert prepovedano not in skripta, prepovedano
        # Isto čiščenje kot v urejevalniku: en sam zapis HTML, pred čiščenjem.
        assert skripta.count("innerHTML") == 1
        assert "predloga.innerHTML = marked.parse(vir," in skripta
        assert "if (!DOVOLJENE[element.tagName])" in skripta
        assert re.findall(r'<form method="post" action="([^"]+)"', besedilo) == ["/admin/logout"]
        assert "potrebuje JavaScript" in besedilo

    def test_tisk_je_isti_kot_v_urejevalniku(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)

        besedilo = odjemalec.get(f"/admin/assessments/{OSNOVA_ID}").text

        assert "@page { size: A4; margin: 15mm 18mm; }" in besedilo
        assert ".list .naloga { break-inside: avoid; page-break-inside: avoid; }" in besedilo
        assert "body:not(.z-resitvami) #list-resitve { display: none; }" in besedilo
        assert 'id="z-resitvami"' in besedilo

    @pytest.mark.parametrize("pripona", ["", "/compose"])
    def test_neznan_test_je_404(self, odjemalec: PrijavljenOdjemalec, pripona: str) -> None:
        odgovor = odjemalec.get(f"/admin/assessments/{NEZNAN_ID}{pripona}")

        assert odgovor.status_code == 404
        assert "Tega testa ni med shranjenimi testi tvoje družine" in odgovor.text

    def test_ogled_pove_iz_katerega_testa_je_nastal(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)
        shrani(odjemalec, osnova=OSNOVA_ID, snov=[], test_md="# Ulomki, drugič")

        besedilo = odjemalec.get(f"/admin/assessments/{NOV_ID}").text

        assert f'<a href="/admin/assessments/{OSNOVA_ID}">Ulomki, prvič</a>' in besedilo


# --- Nov test na tej osnovi ---


class TestNaOsnovi:
    def test_urejevalnik_nosi_izhodisce_in_njegovo_snov_brez_slicic(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path, stars: str
    ) -> None:
        zapisi(motor, slike)
        v_bazo(motor, stars)

        odgovor = odjemalec.get(f"/admin/assessments/{OSNOVA_ID}/compose")

        assert odgovor.status_code == 200
        besedilo = html.unescape(odgovor.text)
        assert "Nov test na osnovi — MAT" in besedilo
        assert f'<input type="hidden" name="osnova" value="{OSNOVA_ID}">' in besedilo
        assert 'name="snov"' not in besedilo
        assert 'class="slicica"' not in besedilo
        assert '<textarea id="osnova-test" hidden># Ulomki, prvič' in besedilo
        assert '<textarea id="osnova-resitve" hidden># Rešitve' in besedilo
        assert "ZAMRZNJENA-SNOV" in besedilo
        assert f'href="/admin/assessments/{OSNOVA_ID}">← Nazaj na shranjeni test' in besedilo

    def test_nov_zapis_dobi_svoj_identifikator(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)

        prvi = odjemalec.get(f"/admin/assessments/{OSNOVA_ID}/compose").text
        drugi = odjemalec.get(f"/admin/assessments/{OSNOVA_ID}/compose").text

        idji = [re.search(r'data-id="([0-9a-f-]{36})"', stran) for stran in (prvi, drugi)]
        assert all(idji)
        assert len({najdeno.group(1) for najdeno in idji if najdeno} | {OSNOVA_ID}) == 3

    def test_model_dobi_snov_iz_zapisa_in_ne_trenutne_snovi_predmeta(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        slike: Path,
        stars: str,
        klicalec: LazenKlicalec,
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "TRENUTNA-SNOV")
        v_bazo(motor, stars)

        odgovor = generiraj(
            odjemalec,
            osnova=OSNOVA_ID,
            # Brskalnik bi lahko poslal tudi izbor in tuj predmet; pri testu
            # na osnovi oboje določi zapis.
            snov=[UUID_ENA],
            subject="SLJ",
            test_md="# Ulomki, prvič",
            resitve_md="# Rešitve",
            zelja="Dodaj nalogo.",
        )

        assert odgovor.status_code == 200, odgovor.text
        assert "ZAMRZNJENA-SNOV" in klicalec.vhod
        assert "TRENUTNA-SNOV" not in klicalec.vhod
        assert "TRENUTNI TEST:" in klicalec.vhod
        assert "DOSEDANJE ŽELJE" not in klicalec.vhod

    def test_shrani_naredi_novo_vrstico_in_izvirnika_ne_spremeni(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path, stars: str, brat: str
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "TRENUTNA-SNOV")
        v_bazo(motor, stars, child_id=brat)
        (prej,) = vsi(motor)
        izvirnik = {stolpec: getattr(prej, stolpec) for stolpec in STOLPCI}

        odgovor = shrani(
            odjemalec,
            osnova=OSNOVA_ID,
            # Vse to bi pri testu iz snovi odločalo; tu ne sme.
            snov=[UUID_ENA],
            subject="SLJ",
            otrok=OTROK_ID,
            test_md="# Ulomki, drugič\n\n## 1. Nova naloga (3 točke)",
        )

        assert odgovor.status_code == 200, odgovor.text
        stari, novi = vsi(motor)
        assert {s: getattr(stari, s) for s in STOLPCI} == izvirnik
        assert novi.id == NOV_ID
        assert novi.base_id == OSNOVA_ID
        assert novi.child_id == brat
        assert novi.subject == "MAT"
        assert novi.source_md == stari.source_md
        assert novi.title == "Ulomki, drugič"
        assert novi.model == "model-iz-odgovora"
        assert novi.saved_by == stars

    def test_test_enak_izhodiscu_se_ne_shrani(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)
        (izhodisce,) = vsi(motor)

        odgovor = shrani(
            odjemalec,
            osnova=OSNOVA_ID,
            snov=[],
            # Brskalnik vrne besedilo polja z drugačnimi konci vrstic.
            test_md=izhodisce.test_md.replace("\n", "\r\n") + "\n",
            resitve_md=izhodisce.solutions_md,
        )

        assert odgovor.status_code == 400
        assert "enak shranjenemu" in odgovor.json()["napaka"]
        assert len(vsi(motor)) == 1

    def test_neznana_osnova_je_404_pri_modelu_in_pri_shranjevanju(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path, klicalec: LazenKlicalec
    ) -> None:
        # Veljaven izbor ne reši neznane osnove: ne pade tiho na snov predmeta.
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        model = generiraj(odjemalec, osnova=NEZNAN_ID)
        shranjevanje = shrani(odjemalec, osnova=NEZNAN_ID)

        assert model.status_code == 404
        assert shranjevanje.status_code == 404
        assert "Tega testa ni" in model.json()["napaka"]
        assert "Tega testa ni" in shranjevanje.json()["napaka"]
        assert klicalec.klici == []
        assert vsi(motor) == []


# --- Skripta urejevalnika: kar se da preveriti brez brskalnika ---


class TestSkriptaShranjevanja:
    @pytest.fixture
    def stran(self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path) -> str:
        zapisi(motor, slike)
        besedilo: str = sestavi(odjemalec, "MAT", UUID_ENA).text
        return besedilo

    def test_urejevalnik_dobi_identifikator_novega_zapisa(self, stran: str) -> None:
        najdeno = re.search(r'data-id="([^"]+)"', stran)

        assert najdeno is not None
        assert str(UUID(najdeno.group(1), version=4)) == najdeno.group(1)
        assert 'telo.append("id", koren.getAttribute("data-id"));' in stran

    def test_shrani_in_zavrzi_sta_pred_prvim_korakom_onemogocena(self, stran: str) -> None:
        assert 'type="button" id="shrani" disabled>Shrani</button>' in stran
        assert 'type="button" id="zavrzi" disabled>Zavrzi</button>' in stran
        # Nespremenjeno izhodišče se ne shrani (`ADR-055` F).
        assert "gumbShrani.disabled = caka || kazalec === 0;" in stran
        assert "gumbZavrzi.disabled = caka || koraki.length === 0;" in stran

    def test_shrani_poslje_model_zadnjega_veljavnega_koraka(self, stran: str) -> None:
        assert 'model: typeof podatki.model === "string" ? podatki.model : ""' in stran
        assert "var koncan = koraki[kazalec - 1];" in stran
        assert 'telo.append("model", koncan.model);' in stran

    def test_opozorilo_pred_izgubo_dela_je_v_strani(self, stran: str) -> None:
        skripta = stran[stran.rindex("<script>") : stran.rindex("</script>")]

        assert '<dialog class="potrditev ne-tiskaj" id="potrditev">' in stran
        assert "<p>Test in pogovor bosta izbrisana.</p>" in stran
        assert 'window.addEventListener("beforeunload"' in skripta
        # Brez neshranjenega dela opozorila ni: pogoj je en sam za vse tri poti.
        assert "return koraki.length > 0 && !zapusca;" in skripta
        # Tri uporabe: zapiranje okna, povezave, obrazci.
        assert skripta.count("!neshranjeno()") == 3
        assert "potrditev.showModal();" in skripta

    def test_po_shranjevanju_skripta_odpre_naslov_ki_ga_vrne_streznik(self, stran: str) -> None:
        skripta = stran[stran.rindex("<script>") : stran.rindex("</script>")]

        assert "window.location.assign(podatki.pot);" in skripta
        odhod = skripta.index("window.location.assign(podatki.pot);")
        assert skripta.index("zapusca = true;") < odhod


# --- Repozitorij ---


class TestRepozitorij:
    def test_tuj_otrok_avtor_ali_izhodisce_je_napaka_klicatelja(
        self, motor: Engine, stars: str, tuj_otrok: str
    ) -> None:
        osnovno: dict[str, Any] = {
            "preizkus_id": NOV_ID,
            "child_id": OTROK_ID,
            "saved_by": stars,
            "subject": "MAT",
            "title": "T",
            "test_md": "# T",
            "solutions_md": "",
            "source_md": "snov",
            "model": "m",
        }
        with Session(motor) as seja:
            repozitorij = PreizkusiRepository(seja, CVEK_ID)
            for sprememba in (
                {"child_id": tuj_otrok},
                {"child_id": stars},
                {"saved_by": OTROK_ID},
                {"saved_by": tuj_otrok},
                {"base_id": NEZNAN_ID},
            ):
                with pytest.raises(ValueError):
                    repozitorij.shrani(**{**osnovno, **sprememba})

        assert vsi(motor) == []
