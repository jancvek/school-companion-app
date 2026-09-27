"""Kartica „danes" na domači strani admina (V3-R13).

Pokriva tabelo „Test casi" iz `docs/plan/V3-R13.md`, razen primera „Druga
družina", ki je v `test_tesnjenje.py` ob ostalih primerih meje družine.

Nobeden od testov ne bere ure stroja: čista funkcija dobi dan kot argument,
testi strani pa `danes` zamenjajo v modulih usmerjevalnikov. Sicer bi bil
izid odvisen od dneva v tednu, ko zbirka teče — in test za vikend bi bil ob
delavnikih zelen, ne da bi karkoli dokazal.
"""

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event

from app.danes import KarticaDanes, VrsticaOtroka, je_vikend, sestavi_kartico
from app.db import ClanDruzine
from app.models import Material
from tests.conftest import BRAT_ID, OTROK_ID, je_seja, ustvari_otroka
from tests.test_dnevi import lokalno, zapisi

#: Ponedeljek. Datumi so zapisani na roko in ne izračunani iz `danes()`.
PONEDELJEK = date(2026, 9, 7)
TOREK = date(2026, 9, 8)
SOBOTA = date(2026, 9, 12)
NEDELJA = date(2026, 9, 13)
#: Dan pred `PONEDELJEK` — „včeraj" v testih strani.
NEDELJA_PREJ = PONEDELJEK - timedelta(days=1)

#: Tretji otrok za primer deaktiviranega; `id` je poljuben, a stalen.
DEAKTIVIRAN_ID = "2c3d4e5f-6a7b-4c8d-9e0f-1a2b3c4d5e6f"


def clan(user_id: str, ime: str, *, aktiven: bool = True) -> ClanDruzine:
    """Otrok, kakršnega vrne `ClaniRepository.otroci`."""
    return ClanDruzine(
        user_id=user_id,
        role="otrok",
        display_name=ime,
        identifier=ime.lower(),
        geslo_nastavljeno=True,
        is_active=aktiven,
        is_system_owner=False,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def slika(subject: str) -> Material:
    """Slika, kakor jo vrne `seznam_po_obdobju`; čista funkcija bere samo predmet."""
    return Material(subject=subject)


MASA = clan(OTROK_ID, "Maša")
NEJC = clan(BRAT_ID, "Nejc")


class TestSestava:
    """Čista funkcija: dan, otroci, slike → kartica."""

    @pytest.mark.parametrize("dan", [SOBOTA, NEDELJA], ids=["sobota", "nedelja"])
    def test_vikend_nima_vrstic_tudi_s_slikami(self, dan: date) -> None:
        kartica = sestavi_kartico(dan, [MASA], {OTROK_ID: [slika("MAT")]}, vec_otrok=False)

        assert kartica == KarticaDanes(je_vikend=True, vrstice=())

    def test_petek_ni_vikend(self) -> None:
        assert not je_vikend(date(2026, 9, 11))
        assert je_vikend(SOBOTA)
        assert je_vikend(NEDELJA)

    def test_brez_slik(self) -> None:
        kartica = sestavi_kartico(PONEDELJEK, [MASA], {}, vec_otrok=False)

        assert kartica is not None
        assert not kartica.je_vikend
        (vrstica,) = kartica.vrstice
        assert not vrstica.ima_slike
        assert vrstica.stanje == "Danes še ni slik"
        assert vrstica.predmeti_opis == ""

    def test_s_slikami_po_urniku(self) -> None:
        slike = [slika("MAT"), slika("NAR"), slika("MAT")]

        kartica = sestavi_kartico(PONEDELJEK, [MASA], {OTROK_ID: slike}, vec_otrok=False)

        assert kartica is not None
        (vrstica,) = kartica.vrstice
        assert vrstica.ima_slike
        assert vrstica.stanje == "Danes že poslikano"
        # NAR je na urniku pred MAT, čeprav je bila MAT poslikana prej.
        assert vrstica.predmeti == (("NAR", 1), ("MAT", 2))
        assert vrstica.predmeti_opis == "NAR 1 · MAT 2"

    def test_neznana_koda_na_koncu_in_ne_izpade(self) -> None:
        slike = [slika("XXX"), slika("AAA"), slika("MAT")]

        kartica = sestavi_kartico(PONEDELJEK, [MASA], {OTROK_ID: slike}, vec_otrok=False)

        assert kartica is not None
        assert kartica.vrstice[0].predmeti_opis == "MAT 1 · AAA 1 · XXX 1"

    def test_brez_otroka_ni_kartice_tudi_med_vikendom(self) -> None:
        assert sestavi_kartico(PONEDELJEK, [], {}, vec_otrok=False) is None
        assert sestavi_kartico(SOBOTA, [], {}, vec_otrok=False) is None

    def test_dva_otroka_vsak_svoje(self) -> None:
        slike = {OTROK_ID: [slika("MAT")], BRAT_ID: [slika("SLJ"), slika("SLJ")]}

        kartica = sestavi_kartico(PONEDELJEK, [MASA, NEJC], slike, vec_otrok=True)

        assert kartica is not None
        assert [(v.stanje, v.predmeti_opis) for v in kartica.vrstice] == [
            ("Maša — danes že poslikano", "MAT 1"),
            ("Nejc — danes že poslikano", "SLJ 2"),
        ]

    def test_ime_samo_pri_vec_otrocih(self) -> None:
        """`ADR-039` F3 in `ADR-051`: pri enem otroku ime ne loči ničesar."""
        ena = sestavi_kartico(PONEDELJEK, [MASA], {}, vec_otrok=False)
        # En aktiven otrok, a družina ima še deaktiviranega: ime se izriše,
        # ker tako šteje tudi izbirnik (`ADR-039` B).
        z_deaktiviranim = sestavi_kartico(PONEDELJEK, [MASA], {}, vec_otrok=True)

        assert ena is not None and z_deaktiviranim is not None
        assert ena.vrstice[0].ime is None
        assert "Maša" not in ena.vrstice[0].stanje
        assert z_deaktiviranim.vrstice[0].stanje == "Maša — danes še ni slik"

    def test_povezava_z_otrokom_samo_pri_vec_otrocih(self) -> None:
        ena = sestavi_kartico(PONEDELJEK, [MASA], {}, vec_otrok=False)
        dva = sestavi_kartico(PONEDELJEK, [MASA, NEJC], {}, vec_otrok=True)

        assert ena is not None and dva is not None
        assert ena.vrstice[0].href == "/admin/days?dan=2026-09-07"
        assert [v.href for v in dva.vrstice] == [
            f"/admin/days?dan=2026-09-07&otrok={OTROK_ID}",
            f"/admin/days?dan=2026-09-07&otrok={BRAT_ID}",
        ]

    def test_besedilo_nima_glagola_s_spolom(self) -> None:
        for predmeti in ((), (("MAT", 1),)):
            stanje = VrsticaOtroka(ime="Maša", predmeti=predmeti, href="").stanje
            assert not re.search(r"slikal[a]?\b", stanje)


# --- Stran ---


def kartica(besedilo: str) -> str:
    """Samo kartica; prazno, kadar je na strani ni."""
    najdeno = re.search(r'<section class="danes".*?</section>', besedilo, re.S)
    return najdeno.group(0) if najdeno else ""


def vrstice(besedilo: str) -> list[str]:
    """Besedilo vrstic kartice, s stisnjenimi presledki."""
    return [
        " ".join(re.sub(r"<[^>]+>", " ", vrstica).split())
        for vrstica in re.findall(r"<li>.*?</li>", kartica(besedilo), re.S)
    ]


@pytest.fixture
def dan(monkeypatch: pytest.MonkeyPatch) -> list[date]:
    """Današnji dan za obe strani; privzeto ponedeljek.

    Seznam z enim elementom, da ga test lahko prestavi; `danes` se zamenja v
    **obeh** usmerjevalnikih, ker test enakosti nabora primerja prav njiju.
    """
    izbrani = [PONEDELJEK]
    monkeypatch.setattr("app.routers.admin.danes", lambda: izbrani[0])
    monkeypatch.setattr("app.routers.dnevi.danes", lambda: izbrani[0])
    return izbrani


class TestStran:
    def test_brez_slik(
        self, odjemalec: TestClient, otrok: str, dan: list[date]
    ) -> None:
        assert vrstice(odjemalec.get("/admin").text) == ["○ Danes še ni slik"]

    def test_s_slikami(
        self, odjemalec: TestClient, motor: Engine, slike: Path, otrok: str, dan: list[date]
    ) -> None:
        zapisi(motor, slike, "mat-1", subject="MAT", taken_at=lokalno(PONEDELJEK, 8))
        zapisi(motor, slike, "nar-1", subject="NAR", taken_at=lokalno(PONEDELJEK, 9))
        zapisi(motor, slike, "mat-2", subject="MAT", taken_at=lokalno(PONEDELJEK, 10))

        assert vrstice(odjemalec.get("/admin").text) == [
            "✓ Danes že poslikano NAR 1 · MAT 2"
        ]

    @pytest.mark.parametrize("vikend", [SOBOTA, NEDELJA], ids=["sobota", "nedelja"])
    def test_vikend(
        self,
        odjemalec: TestClient,
        motor: Engine,
        slike: Path,
        otrok: str,
        dan: list[date],
        vikend: date,
    ) -> None:
        dan[0] = vikend
        zapisi(motor, slike, "vikend", subject="MAT", taken_at=lokalno(vikend))

        vsebina = kartica(odjemalec.get("/admin").text)

        assert "Danes je vikend." in vsebina
        assert "<li>" not in vsebina
        assert "MAT" not in vsebina

    def test_meja_dneva_je_lokalna_polnoc(
        self, odjemalec: TestClient, motor: Engine, slike: Path, otrok: str, dan: list[date]
    ) -> None:
        # 23:30 in 00:10 po domačem (poletnem) času. Druga je v UTC še vedno
        # ponedeljek — prav zato dokazuje lokalno mejo in ne UTC.
        pozno = datetime(2026, 9, 7, 21, 30, tzinfo=UTC)
        polnoc = datetime(2026, 9, 7, 22, 10, tzinfo=UTC)
        zapisi(motor, slike, "pozno", subject="MAT", taken_at=pozno)
        zapisi(motor, slike, "polnoc", subject="SLJ", taken_at=polnoc)

        assert vrstice(odjemalec.get("/admin").text) == ["✓ Danes že poslikano MAT 1"]

        dan[0] = TOREK
        assert vrstice(odjemalec.get("/admin").text) == ["✓ Danes že poslikano SLJ 1"]

    def test_vcerajsnja_in_arhivirana_ne_stejeta(
        self, odjemalec: TestClient, motor: Engine, slike: Path, otrok: str, dan: list[date]
    ) -> None:
        zapisi(motor, slike, "vceraj", subject="MAT", taken_at=lokalno(NEDELJA_PREJ))
        zapisi(
            motor,
            slike,
            "arhiv",
            subject="MAT",
            taken_at=lokalno(PONEDELJEK),
            arhivirano=datetime(2026, 9, 7, 12, tzinfo=UTC),
        )

        assert vrstice(odjemalec.get("/admin").text) == ["○ Danes še ni slik"]

    def test_dva_otroka(
        self,
        odjemalec: TestClient,
        motor: Engine,
        slike: Path,
        otrok: str,
        brat: str,
        dan: list[date],
    ) -> None:
        zapisi(motor, slike, "masina", subject="MAT", taken_at=lokalno(PONEDELJEK), child_id=otrok)
        zapisi(motor, slike, "nejc-1", subject="SLJ", taken_at=lokalno(PONEDELJEK), child_id=brat)
        zapisi(motor, slike, "nejc-2", subject="SLJ", taken_at=lokalno(PONEDELJEK), child_id=brat)

        besedilo = odjemalec.get("/admin").text

        assert vrstice(besedilo) == [
            "✓ Maša — danes že poslikano MAT 1",
            "✓ Nejc — danes že poslikano SLJ 2",
        ]
        assert f'href="/admin/days?dan=2026-09-07&amp;otrok={otrok}"' in kartica(besedilo)
        assert f'href="/admin/days?dan=2026-09-07&amp;otrok={brat}"' in kartica(besedilo)

    def test_en_otrok_povezava_brez_otroka(
        self, odjemalec: TestClient, otrok: str, dan: list[date]
    ) -> None:
        vsebina = kartica(odjemalec.get("/admin").text)

        assert 'href="/admin/days?dan=2026-09-07"' in vsebina
        assert "otrok=" not in vsebina

    def test_deaktiviran_otrok_nima_vrstice_a_steje_za_povezavo(
        self, odjemalec: TestClient, motor: Engine, otrok: str, dan: list[date]
    ) -> None:
        ustvari_otroka(
            motor,
            user_id=DEAKTIVIRAN_ID,
            identifikator="ana",
            prikazno_ime="Ana",
            aktiven=False,
        )

        besedilo = odjemalec.get("/admin").text

        # Ime je vidno: družina ima dva otroka, kot ju šteje izbirnik
        # (`ADR-039` F3 in B), čeprav je aktiven samo eden.
        assert vrstice(besedilo) == ["○ Maša — danes še ni slik"]
        # Izbirnik na `/admin/days` šteje tudi deaktiviranega, zato brez
        # `?otrok=` povezava ne bi pripeljala do Maše, ampak do privzetka —
        # Ane, ki je po abecedi prva.
        assert f'href="/admin/days?dan=2026-09-07&amp;otrok={otrok}"' in kartica(besedilo)

    @pytest.mark.parametrize("dan_strani", [PONEDELJEK, SOBOTA], ids=["delavnik", "vikend"])
    def test_brez_aktivnega_otroka_ni_kartice(
        self,
        odjemalec: TestClient,
        motor: Engine,
        dan: list[date],
        dan_strani: date,
    ) -> None:
        dan[0] = dan_strani
        ustvari_otroka(motor, aktiven=False)

        besedilo = odjemalec.get("/admin").text

        assert kartica(besedilo) == ""
        assert "Danes je vikend." not in besedilo

    def test_kartica_je_nad_predmeti(
        self, odjemalec: TestClient, otrok: str, dan: list[date]
    ) -> None:
        besedilo = odjemalec.get("/admin").text

        assert 0 <= besedilo.index('<section class="danes"') < besedilo.index("<h1>Predmeti</h1>")

    def test_vrstni_red_seznama_predmetov_ostane_urnik(
        self, odjemalec: TestClient, motor: Engine, slike: Path, otrok: str, dan: list[date]
    ) -> None:
        """Kartica nad seznamom nosi kodo MAT; seznam predmetov mora ostati po urniku."""
        zapisi(motor, slike, "mat", subject="MAT", taken_at=lokalno(PONEDELJEK))
        besedilo = odjemalec.get("/admin").text
        assert "MAT 1" in kartica(besedilo)

        najdeno = re.search(r'<ul class="predmeti">.*?</ul>', besedilo, re.S)
        assert najdeno is not None
        seznam = najdeno.group(0)
        assert seznam.index(">NAR<") < seznam.index(">MAT<") < seznam.index(">TJA<")

    def test_nabor_je_isti_kot_na_pregledu_po_dnevih(
        self,
        odjemalec: TestClient,
        motor: Engine,
        slike: Path,
        otrok: str,
        brat: str,
        dan: list[date],
    ) -> None:
        """Isti dan, isti otrok: kartica in `/admin/days` naštejeta isto (`ADR-050` A1)."""
        zapisi(motor, slike, "d-1", subject="MAT", taken_at=lokalno(PONEDELJEK, 8))
        zapisi(motor, slike, "d-2", subject="MAT", taken_at=lokalno(PONEDELJEK, 9))
        zapisi(motor, slike, "d-3", subject="GEO", taken_at=lokalno(PONEDELJEK, 23, 30))
        zapisi(motor, slike, "vceraj", subject="MAT", taken_at=lokalno(NEDELJA_PREJ))
        zapisi(motor, slike, "jutri", subject="MAT", taken_at=lokalno(TOREK, 0, 10))
        zapisi(
            motor,
            slike,
            "arhiv",
            subject="SLJ",
            taken_at=lokalno(PONEDELJEK),
            arhivirano=datetime(2026, 9, 7, 12, tzinfo=UTC),
        )
        zapisi(motor, slike, "bratova", subject="SLJ", taken_at=lokalno(PONEDELJEK), child_id=brat)

        (masina, _) = vrstice(odjemalec.get("/admin").text)
        dnevi = odjemalec.get(f"/admin/days?dan=2026-09-07&otrok={otrok}").text

        assert masina == "✓ Maša — danes že poslikano MAT 2 · GEO 1"
        assert "3 slike" in dnevi
        assert re.search(r"MAT — Matematika\s*<span>2 sliki</span>", dnevi)
        assert re.search(r"GEO — Geografija\s*<span>1 slika</span>", dnevi)
        assert "SLJ — " not in dnevi

    @pytest.mark.parametrize(
        ("dan_strani", "pricakovano"),
        [(PONEDELJEK, 2), (SOBOTA, 0)],
        ids=["delavnik", "vikend"],
    )
    def test_poizvedba_na_otroka_med_vikendom_nobena(
        self,
        odjemalec: TestClient,
        motor: Engine,
        otrok: str,
        brat: str,
        dan: list[date],
        dan_strani: date,
        pricakovano: int,
    ) -> None:
        """Po en klic `seznam_po_obdobju` na aktivnega otroka; med vikendom nobenega."""
        dan[0] = dan_strani
        stevec = 0

        def zabelezi(
            _povezava: object, _kazalec: object, stavek: str, *_ostalo: object
        ) -> None:
            nonlocal stevec
            if not je_seja(stavek) and "materials.taken_at >=" in stavek:
                stevec += 1

        event.listen(motor, "before_cursor_execute", zabelezi)
        try:
            assert odjemalec.get("/admin").status_code == 200
        finally:
            event.remove(motor, "before_cursor_execute", zabelezi)

        assert stevec == pricakovano
