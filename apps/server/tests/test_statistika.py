"""Testi statistike čez kvize (V2-R04).

Pokrivajo tabelo „Test casi" iz `docs/plan/V2-R04.md`. Pravila štetja in
razvrščanja se preverjajo neposredno nad `app/statistika.py`, strani pa skozi
pravo pot: kviz nastane v sestavljalniku, poskusi pridejo po poti telefona —
tako kot v produkciji. Kjer test zanima, da statistika bere dnevnik in ne
števca, se poskus vstavi naravnost v bazo.

Časi so v **tekočem** šolskem letu in ne v zapisanem koledarskem — sicer bi
zbirka čez leto dni sama od sebe pordečila (`CLAUDE.md`, ponovljivost).
"""

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select, update
from sqlalchemy.orm import Session

from app.casi import (
    meseci_solskega_leta,
    oznaka_solskega_leta,
    solsko_leto,
    solsko_leto_od_do,
)
from app.db import MaterialsRepository, PoskusZaStatistiko
from app.models import Material, Question, QuestionAttempt, Quiz, QuizItem
from app.statistika import (
    Razporeditev,
    je_pravilna,
    odstotek,
    po_mesecih,
    po_snoveh,
    po_vprasanjih,
    razdeli,
    razvrsti,
    solska_leta,
)
from app.subjects import PREDMETI
from tests.conftest import CVEK_ID, OTROK_ID, SejaTesta
from tests.test_kvizi import UUID_DVA, UUID_ENA, UUID_TRI, objavi, snov, upokoji
from tests.test_resevanje import poskus, poslji
from tests.test_rezultat import postavke

#: Tekoče šolsko leto — privzeto okno strani.
TEKOCE = solsko_leto(datetime.now(UTC))

#: Trenutek sredi tekočega šolskega leta.
KDAJ = datetime(TEKOCE, 10, 15, 8, 0, tzinfo=UTC)


def vprasanje(stevilka: int, material_id: str = UUID_ENA) -> str:
    """Besedilo vprašanja, kot ga zapiše `snov` iz `test_kvizi.py`."""
    return f"Vprašanje {stevilka} iz {material_id[:4]}?"


def kviz_z_ocenami(
    odjemalec: TestClient,
    motor: Engine,
    material_ids: list[str],
    ocene: list[str],
    telefon: SejaTesta,
    *,
    koliko: int,
    kdaj: datetime = KDAJ,
    subject: str | None = "MAT",
    vstop: str = "nova",
) -> str:
    """Objavi kviz in prvim `len(ocene)` postavkam pošlje poskuse po poti telefona.

    Ocen je lahko manj kot postavk — takrat kviz ostane napol rešen.
    """
    quiz_id = objavi(
        odjemalec, motor, material_ids, koliko=koliko, subject=subject, vstop=vstop
    )
    idji = postavke(motor, quiz_id)[: len(ocene)]
    if ocene:
        odgovor = poslji(
            odjemalec,
            [
                poskus(
                    postavka_id,
                    rating=ocena,
                    answered_at=(kdaj + timedelta(minutes=i)).isoformat(),
                )
                for i, (postavka_id, ocena) in enumerate(zip(idji, ocene, strict=True))
            ],
            telefon,
        )
        assert odgovor.status_code == 200, odgovor.text
    return quiz_id


def vstavi_poskus(
    motor: Engine,
    quiz_item_id: str,
    *,
    rating: str = "srednje",
    mode: str = "samoocena",
    kdaj: datetime = KDAJ,
    child_id: str = OTROK_ID,
) -> None:
    """Poskus naravnost v bazi, mimo poti telefona."""
    with Session(motor) as seja:
        seja.add(
            QuestionAttempt(
                child_id=child_id,
                family_id=CVEK_ID,
                id=str(uuid4()),
                quiz_item_id=quiz_item_id,
                mode=mode,
                rating=rating,
                shown_at=kdaj,
                revealed_at=kdaj,
                answered_at=kdaj,
                received_at=kdaj,
            )
        )
        seja.commit()


def pregled(odjemalec: TestClient, poizvedba: str = "") -> str:
    odgovor = odjemalec.get(f"/admin/statistics{poizvedba}")
    assert odgovor.status_code == 200, odgovor.text
    return odgovor.text


def predmet(odjemalec: TestClient, koda: str = "MAT", poizvedba: str = "") -> str:
    odgovor = odjemalec.get(f"/admin/statistics/subjects/{koda}{poizvedba}")
    assert odgovor.status_code == 200, odgovor.text
    return odgovor.text


def vrstica(besedilo: str, kljuc: str) -> str:
    """Vrstica tabele (`<tr>…</tr>`), ki vsebuje `kljuc`."""
    for kos in besedilo.split("<tr")[1:]:
        kos = kos.split("</tr>")[0]
        if kljuc in kos:
            return kos
    raise AssertionError(f"Vrstice s {kljuc!r} ni.")


def razdelek(besedilo: str, od: str, do: str | None = None) -> str:
    """Del strani med dvema oznakama."""
    zacetek = besedilo.index(od)
    konec = besedilo.index(do, zacetek) if do is not None else len(besedilo)
    return besedilo[zacetek:konec]


# --- Čiste funkcije ------------------------------------------------------------


OSNOVA = PoskusZaStatistiko(
    rating="srednje",
    answered_at=datetime(2026, 10, 1, 8, 0, tzinfo=UTC),
    quiz_id="k1",
    kviz_ime="MAT — 1. 10. 2026",
    kviz_preklican=False,
    question_id="q1",
    vprasanje="Vprašanje?",
    odgovor="Odgovor.",
    subject="MAT",
    material_id="m1",
    material_taken_at=datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
    upokojeno=False,
)


@pytest.fixture(autouse=True)
def _druzina_ima_otroka(otrok: str) -> str:
    """Družina Cvek ima otroka — tako kot na produkciji (migracija `0008`).

    Od `V3-R07` je otrok del pomena teh strani: kviz brez naslovljenca ne
    obstaja (`docs/odlocitve/ADR-039` A), statistika in pregled po dnevih pa
    sta vezana nanj (B). Brez te vrstice bi testi tekli nad družino, kakršne
    na produkciji ni, in bi merili prazno stran.

    `autouse`, ker gre za **okolje** teh testov in ne za njihov vhod; test, ki
    potrebuje družino **brez** otroka, ga deaktivira ali izbriše sam.
    """
    return otrok


def p(question_id: str = "q1", rating: str = "srednje", **polja: Any) -> PoskusZaStatistiko:
    return replace(OSNOVA, question_id=question_id, rating=rating, **polja)


class TestPravilnostInOdstotki:
    def test_pravilnost_je_izpeljana_iz_ocene(self) -> None:
        assert [je_pravilna(o) for o in ("nisem_vedela", "tezko", "srednje", "lahko")] == [
            False,
            True,
            True,
            True,
        ]

    def test_razporeditev_stirih_ocen(self) -> None:
        razporeditev = Razporeditev()
        for ocena in ("nisem_vedela", "tezko", "srednje", "lahko"):
            razporeditev.dodaj(ocena)

        assert razporeditev.poskusov == 4
        assert odstotek(razporeditev.pravilnih, razporeditev.poskusov) == 75
        assert odstotek(razporeditev.tezkih, razporeditev.poskusov) == 50

    @pytest.mark.parametrize(
        ("del_", "celota", "pricakovano"),
        [(7, 8, 88), (1, 8, 13), (1, 3, 33), (2, 3, 67), (0, 5, 0), (5, 5, 100)],
    )
    def test_polovica_navzgor(self, del_: int, celota: int, pricakovano: int) -> None:
        # 12,5 in 87,5: Pythonov `round` bi prvega zaokrožil navzdol.
        assert odstotek(del_, celota) == pricakovano

    def test_brez_poskusov_ni_odstotka(self) -> None:
        assert odstotek(0, 0) is None


class TestRazvrstitev:
    def test_po_delezu_tezkih_in_enkrat_postavljena_spodaj(self) -> None:
        poskusi = [
            p("A", "tezko"),
            p("A", "lahko"),
            p("B", "nisem_vedela"),
            p("B", "tezko"),
            p("B", "nisem_vedela"),
            p("C", "nisem_vedela"),
        ]

        veckrat, enkrat = razvrsti(po_vprasanjih(poskusi))

        assert [v.question_id for v in veckrat] == ["B", "A"]
        # C ima 100 % težkih, a en sam poskus še ni „vztrajno" (`ADR-021` C).
        assert [v.question_id for v in enkrat] == ["C"]

    def test_izenacen_delez_da_prednost_vec_poskusom(self) -> None:
        poskusi = [p("A", "tezko"), p("A", "tezko"), *[p("B", "tezko") for _ in range(3)]]

        veckrat, _ = razvrsti(po_vprasanjih(poskusi))

        assert [v.question_id for v in veckrat] == ["B", "A"]

    def test_nato_novejsi_zadnji_poskus(self) -> None:
        prej = datetime(2026, 10, 1, tzinfo=UTC)
        poskusi = [
            p("A", "tezko", answered_at=prej),
            p("A", "lahko", answered_at=prej),
            p("B", "tezko", answered_at=prej),
            p("B", "lahko", answered_at=prej + timedelta(days=1)),
        ]

        veckrat, _ = razvrsti(po_vprasanjih(poskusi))

        assert [v.question_id for v in veckrat] == ["B", "A"]

    def test_zaporedje_je_kronolosko(self) -> None:
        poskusi = [
            p("A", "nisem_vedela", answered_at=datetime(2026, 10, 1, tzinfo=UTC)),
            p("A", "lahko", answered_at=datetime(2026, 11, 1, tzinfo=UTC)),
        ]

        [statistika] = po_vprasanjih(poskusi)

        assert [vnos.ocena for vnos in statistika.zaporedje] == ["nisem_vedela", "lahko"]


class TestRazdelitev:
    def test_brez_vprasanja_in_neprepoznana_ocena_se_stejeta_posebej(self) -> None:
        razdeljeno = razdeli([p(), p(question_id=None), p(rating="xyz")])  # type: ignore[arg-type]

        assert len(razdeljeno.stejejo) == 1
        assert razdeljeno.brez_vprasanja == 1
        assert razdeljeno.neprepoznanih == 1


class TestSnovi:
    def test_izbrisana_snov_se_zdruzi_po_casu_posnetka(self) -> None:
        cas_ena = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
        cas_dva = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)
        poskusi = [
            p("A", material_id=None, material_taken_at=cas_ena),
            p("B", material_id=None, material_taken_at=cas_ena),
            p("C", material_id=None, material_taken_at=cas_dva),
            p("D", material_id="m1"),
        ]

        snovi = po_snoveh(po_vprasanjih(poskusi))

        assert sorted(len(snov.vprasanj) for snov in snovi) == [1, 1, 2]
        assert {snov.material_id for snov in snovi} == {None, "m1"}

    def test_najtezja_snov_zgoraj(self) -> None:
        poskusi = [p("A", "lahko", material_id="m1"), p("B", "tezko", material_id="m2")]

        assert [snov.material_id for snov in po_snoveh(po_vprasanjih(poskusi))] == ["m2", "m1"]


class TestSolskoLeto:
    def test_meja_ob_lokalni_polnoci(self) -> None:
        # Poleti je lokalna polnoč 1. 9. ob 22:00 UTC prejšnjega dne.
        assert solsko_leto(datetime(2026, 8, 31, 21, 30, tzinfo=UTC)) == 2025
        assert solsko_leto(datetime(2026, 8, 31, 22, 30, tzinfo=UTC)) == 2026

    def test_meji_v_utc(self) -> None:
        assert solsko_leto_od_do(2026) == (
            datetime(2026, 8, 31, 22, 0, tzinfo=UTC),
            datetime(2027, 8, 31, 22, 0, tzinfo=UTC),
        )

    def test_naiven_cas_je_utc(self) -> None:
        # SQLite vrne naiven čas.
        assert solsko_leto(datetime(2026, 8, 31, 22, 30)) == 2026

    def test_meseci_od_septembra_do_avgusta(self) -> None:
        meseci = meseci_solskega_leta(2026)

        assert len(meseci) == 12
        assert meseci[0] == (2026, 9)
        assert meseci[-1] == (2027, 8)

    def test_oznaka(self) -> None:
        assert oznaka_solskega_leta(2026) == "2026/27"
        assert oznaka_solskega_leta(2099) == "2099/00"

    def test_mesec_po_domacem_casu(self) -> None:
        # 1. 10. ob 00:30 po domačem času je 30. 9. ob 22:30 UTC.
        poskusi = [p(answered_at=datetime(2026, 9, 30, 22, 30, tzinfo=UTC))]

        meseci = dict(po_mesecih(poskusi, 2026))

        assert meseci[(2026, 10)].poskusov == 1
        assert meseci[(2026, 9)].poskusov == 0

    def test_solska_leta_samo_s_poskusi(self) -> None:
        casi = [datetime(2024, 10, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)]

        assert solska_leta(casi) == [2026, 2024]


# --- Strani --------------------------------------------------------------------


class TestSrecnaPot:
    @pytest.fixture
    def stanje(self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta) -> None:
        """Vprašanje 1 dvakrat (*Nisem vedela*, *Težko*), vprašanje 2 enkrat (*Lahko*)."""
        snov(motor, slike, UUID_ENA, vprasanj=2)
        kviz_z_ocenami(odjemalec, motor, [UUID_ENA], ["nisem_vedela", "lahko"], telefon, koliko=2)
        kviz_z_ocenami(
            odjemalec,
            motor,
            [UUID_ENA],
            ["tezko"],
            telefon,
            koliko=1,
            kdaj=KDAJ + timedelta(days=7),
        )

    @pytest.mark.usefixtures("stanje")
    def test_pregled_steje_poskuse_predmeta(self, odjemalec: TestClient) -> None:
        mat = vrstica(pregled(odjemalec), '<span class="koda">MAT</span>')

        assert "3 poskusi" in mat
        assert "Nisem vedela 1" in mat
        assert "Težko 1" in mat
        assert "Lahko 1" in mat

    @pytest.mark.usefixtures("stanje")
    def test_vprasanje_dvakrat_je_med_veckrat_postavljenimi(self, odjemalec: TestClient) -> None:
        besedilo = predmet(odjemalec)
        veckrat = razdelek(besedilo, 'id="veckrat"', 'id="enkrat"')
        enkrat = razdelek(besedilo, 'id="enkrat"')

        assert vprasanje(1) in veckrat
        # *Težko* je pravilen odgovor, dan s trudom: 50 % pravilnih, 100 % težkih.
        assert "2 poskusa · pravilnih 50 % · težkih 100 %" in veckrat
        assert vprasanje(2) not in veckrat
        assert vprasanje(2) in enkrat

    @pytest.mark.usefixtures("stanje")
    def test_snov_je_agregirana(self, odjemalec: TestClient) -> None:
        snov_vrstica = vrstica(
            razdelek(predmet(odjemalec), "<h2>Snovi</h2>"), f"/admin/materials/{UUID_ENA}"
        )

        assert "2 vprašanji" in snov_vrstica
        assert "3 poskusi" in snov_vrstica

    @pytest.mark.usefixtures("stanje")
    def test_obe_strani_povesta_da_je_samoocena(self, odjemalec: TestClient) -> None:
        for besedilo in (pregled(odjemalec), predmet(odjemalec)):
            assert "samoocena" in besedilo


class TestIzDnevnika:
    def test_poskus_mimo_api_je_takoj_stet(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=2)
        quiz_id = kviz_z_ocenami(odjemalec, motor, [UUID_ENA], [], telefon, koliko=2)
        prva, _ = postavke(motor, quiz_id)

        assert "0 poskusov" in vrstica(pregled(odjemalec), '<span class="koda">MAT</span>')

        vstavi_poskus(motor, prva)

        assert "1 poskus" in vrstica(pregled(odjemalec), '<span class="koda">MAT</span>')

    def test_steje_samo_samoocena(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=2)
        quiz_id = kviz_z_ocenami(odjemalec, motor, [UUID_ENA], [], telefon, koliko=2)
        prva, druga = postavke(motor, quiz_id)
        vstavi_poskus(motor, prva, rating="lahko")
        vstavi_poskus(motor, druga, rating="nisem_vedela", mode="abc")

        assert "1 poskus" in vrstica(pregled(odjemalec), '<span class="koda">MAT</span>')
        besedilo = predmet(odjemalec)
        assert vprasanje(1) in besedilo
        # Načina se nikoli ne povprečita (`ADR-014`).
        assert vprasanje(2) not in besedilo


class TestKajSteje:
    def test_preklican_kviz_steje_in_je_oznacen(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=1)
        quiz_id = kviz_z_ocenami(odjemalec, motor, [UUID_ENA], ["tezko"], telefon, koliko=1)
        preklic = odjemalec.post(f"/admin/quizzes/{quiz_id}/cancel", follow_redirects=False)
        assert preklic.status_code == 303

        besedilo = predmet(odjemalec)

        assert "1 poskus" in besedilo
        assert "preklican kviz" in besedilo

    def test_napol_resen_kviz_steje_samo_ocenjeno(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=3)
        kviz_z_ocenami(odjemalec, motor, [UUID_ENA], ["srednje"], telefon, koliko=3)

        mat = vrstica(pregled(odjemalec), '<span class="koda">MAT</span>')

        assert "1 poskus" in mat
        assert vprasanje(2) not in predmet(odjemalec)

    def test_upokojeno_vprasanje_steje_z_oznako(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=1)
        kviz_z_ocenami(odjemalec, motor, [UUID_ENA], ["tezko"], telefon, koliko=1)
        upokoji(motor)
        with Session(motor) as seja:
            seja.add(
                Question(
                    family_id=CVEK_ID,
                    id="nova-serija-1",
                    material_id=UUID_ENA,
                    position=1,
                    question="Vprašanje iz nove serije?",
                    answer="Odgovor.",
                    subject="MAT",
                )
            )
            seja.commit()

        besedilo = predmet(odjemalec)

        assert vprasanje(1) in besedilo
        assert "upokojeno" in besedilo
        assert "1 poskus" in vrstica(razdelek(besedilo, "<h2>Snovi</h2>"), UUID_ENA)
        # Nova serija je nova identiteta brez poskusov (`ADR-021` D).
        assert "Vprašanje iz nove serije?" not in besedilo

    def test_arhivirana_snov_steje_z_oznako(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=1)
        kviz_z_ocenami(odjemalec, motor, [UUID_ENA], ["tezko"], telefon, koliko=1)
        with Session(motor) as seja:
            seja.execute(update(Material).where(Material.id == UUID_ENA).values(archived_at=KDAJ))
            seja.commit()

        besedilo = predmet(odjemalec)

        assert "v arhivu" in besedilo
        assert f"/admin/materials/{UUID_ENA}" in besedilo

    def test_izbrisana_snov_steje_brez_povezave(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=1)
        kviz_z_ocenami(odjemalec, motor, [UUID_ENA], ["tezko"], telefon, koliko=1)
        with Session(motor) as seja:
            seja.execute(
                update(Material)
                .where(Material.id == UUID_ENA)
                .values(archived_at=KDAJ, device_deleted_at=KDAJ)
            )
            seja.commit()
            assert MaterialsRepository(seja, CVEK_ID).pobrisi(UUID_ENA) is not None

        besedilo = predmet(odjemalec)

        assert vprasanje(1) in besedilo
        assert "snov izbrisana" in besedilo
        assert f"/admin/materials/{UUID_ENA}" not in besedilo

    def test_poskus_brez_vprasanja_ne_izpade_molce(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=1)
        quiz_id = kviz_z_ocenami(odjemalec, motor, [UUID_ENA], ["tezko"], telefon, koliko=1)
        with Session(motor) as seja:
            seja.execute(
                update(QuizItem).where(QuizItem.quiz_id == quiz_id).values(question_id=None)
            )
            seja.commit()

        assert "1 poskus brez vprašanja" in pregled(odjemalec)

    def test_neprepoznana_ocena_ne_izpade_molce(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=1)
        kviz_z_ocenami(odjemalec, motor, [UUID_ENA], ["tezko"], telefon, koliko=1)
        with Session(motor) as seja:
            seja.execute(update(QuestionAttempt).values(rating="xyz"))
            seja.commit()

        besedilo = predmet(odjemalec)

        assert "1 poskus z neprepoznano oceno" in besedilo
        assert "V tem obdobju pri tem predmetu ni nobene ocene." in besedilo


class TestOkno:
    def test_privzeto_je_tekoce_solsko_leto(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=2)
        kviz_z_ocenami(odjemalec, motor, [UUID_ENA], ["tezko"], telefon, koliko=1)
        kviz_z_ocenami(
            odjemalec,
            motor,
            [UUID_ENA],
            ["lahko"],
            telefon,
            koliko=1,
            kdaj=KDAJ.replace(year=TEKOCE - 1),
        )

        privzeto = pregled(odjemalec)

        assert f"Šolsko leto {oznaka_solskega_leta(TEKOCE)}" in privzeto
        assert "1 poskus" in vrstica(privzeto, '<span class="koda">MAT</span>')
        assert "2 poskusa" in vrstica(
            pregled(odjemalec, "?leto=vse"), '<span class="koda">MAT</span>'
        )

    def test_meja_leta_ob_polnoci(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=2)
        # 23:30 in 00:30 po domačem (poletnem) času.
        kviz_z_ocenami(
            odjemalec,
            motor,
            [UUID_ENA],
            ["tezko"],
            telefon,
            koliko=1,
            kdaj=datetime(2026, 8, 31, 21, 30, tzinfo=UTC),
        )
        kviz_z_ocenami(
            odjemalec,
            motor,
            [UUID_ENA],
            ["lahko"],
            telefon,
            koliko=1,
            kdaj=datetime(2026, 8, 31, 22, 30, tzinfo=UTC),
        )

        staro = vrstica(pregled(odjemalec, "?leto=2025"), '<span class="koda">MAT</span>')
        novo = vrstica(pregled(odjemalec, "?leto=2026"), '<span class="koda">MAT</span>')

        assert "1 poskus" in staro
        assert "Težko 1" in staro
        assert "1 poskus" in novo
        assert "Lahko 1" in novo

    def test_meja_leta_je_polodprta(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        """Poskus **točno** ob lokalni polnoči 1. 9. sodi v novo leto in ne v obe.

        Samo 30 minut pred mejo in po njej ne loči `>=` od `>` in `<` od `<=`.
        """
        snov(motor, slike, UUID_ENA, vprasanj=1)
        kviz_z_ocenami(
            odjemalec,
            motor,
            [UUID_ENA],
            ["tezko"],
            telefon,
            koliko=1,
            kdaj=datetime(2026, 8, 31, 22, 0, tzinfo=UTC),
        )

        assert "0 poskusov" in vrstica(
            pregled(odjemalec, "?leto=2025"), '<span class="koda">MAT</span>'
        )
        assert "1 poskus" in vrstica(
            pregled(odjemalec, "?leto=2026"), '<span class="koda">MAT</span>'
        )

    def test_leto_samo_s_poskusi_drugega_nacina_ni_ponujeno(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=1)
        quiz_id = kviz_z_ocenami(odjemalec, motor, [UUID_ENA], [], telefon, koliko=1)
        [postavka] = postavke(motor, quiz_id)
        vstavi_poskus(motor, postavka, mode="abc", kdaj=KDAJ.replace(year=TEKOCE - 3))

        izbira = razdelek(pregled(odjemalec), 'class="izbira-let"', "</p>")

        assert f"?leto={TEKOCE - 3}" not in izbira

    def test_vse_ima_vrstico_na_solsko_leto(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=2)
        kviz_z_ocenami(
            odjemalec,
            motor,
            [UUID_ENA],
            ["tezko"],
            telefon,
            koliko=1,
            kdaj=datetime(2025, 10, 1, 8, 0, tzinfo=UTC),
        )
        kviz_z_ocenami(
            odjemalec,
            motor,
            [UUID_ENA],
            ["lahko"],
            telefon,
            koliko=1,
            kdaj=datetime(2026, 10, 1, 8, 0, tzinfo=UTC),
        )

        besedilo = predmet(odjemalec, poizvedba="?leto=vse")
        casovnica = razdelek(besedilo, "<h2>Po šolskih letih</h2>", "<h2>Snovi</h2>")

        assert "1 poskus" in vrstica(casovnica, "2025/26")
        assert "1 poskus" in vrstica(casovnica, "2026/27")

    def test_izbira_ponudi_leta_s_poskusi_tekoce_in_vse(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=2)
        kviz_z_ocenami(
            odjemalec,
            motor,
            [UUID_ENA],
            ["tezko"],
            telefon,
            koliko=1,
            kdaj=KDAJ.replace(year=TEKOCE - 2),
        )

        izbira = razdelek(pregled(odjemalec), 'class="izbira-let"', "</p>")

        assert oznaka_solskega_leta(TEKOCE) in izbira
        assert f"?leto={TEKOCE - 2}" in izbira
        assert f"?leto={TEKOCE - 1}" not in izbira
        assert "?leto=vse" in izbira

    @pytest.mark.parametrize("vrednost", ["abc", "99999", "-1", "٢٠٢٦"])
    def test_nerazberljivo_leto_je_privzetek(
        self, odjemalec: TestClient, vrednost: str
    ) -> None:
        besedilo = pregled(odjemalec, f"?leto={vrednost}")

        assert "ni mogoče prebrati" in besedilo
        assert f"Šolsko leto {oznaka_solskega_leta(TEKOCE)}" in besedilo

    def test_leto_brez_poskusov(self, odjemalec: TestClient) -> None:
        besedilo = pregled(odjemalec, "?leto=2019")

        assert "Šolsko leto 2019/20" in besedilo
        assert "V tem obdobju ni nobene ocene." in besedilo

    def test_povezava_na_predmet_ohrani_okno(self, odjemalec: TestClient) -> None:
        assert 'href="/admin/statistics/subjects/MAT?leto=vse"' in pregled(odjemalec, "?leto=vse")


class TestCasovnica:
    def test_dvanajst_mesecev_tudi_prazni(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=2)
        kviz_z_ocenami(
            odjemalec,
            motor,
            [UUID_ENA],
            ["tezko"],
            telefon,
            koliko=1,
            kdaj=datetime(TEKOCE, 9, 15, 8, 0, tzinfo=UTC),
        )
        kviz_z_ocenami(
            odjemalec,
            motor,
            [UUID_ENA],
            ["lahko"],
            telefon,
            koliko=1,
            kdaj=datetime(TEKOCE, 11, 15, 8, 0, tzinfo=UTC),
        )

        casovnica = razdelek(predmet(odjemalec), "<h2>Po mesecih</h2>", "<h2>Snovi</h2>")

        assert casovnica.count("<tr") == 1 + 12
        oktober = vrstica(casovnica, f"oktober {TEKOCE}")
        assert "0 poskusov" in oktober
        assert "—" in oktober
        assert "1 poskus" in vrstica(casovnica, f"september {TEKOCE}")
        assert "1 poskus" in vrstica(casovnica, f"november {TEKOCE}")

    def test_zaporedje_ocen_z_datumi_in_kvizi(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=1)
        kvizi = [
            kviz_z_ocenami(
                odjemalec,
                motor,
                [UUID_ENA],
                [ocena],
                telefon,
                koliko=1,
                kdaj=datetime(TEKOCE, mesec, 1, 8, 0, tzinfo=UTC),
            )
            for mesec, ocena in ((12, "lahko"), (10, "nisem_vedela"), (11, "tezko"))
        ]

        zaporedje = razdelek(predmet(odjemalec), 'class="drobno zaporedje"', "</p>")

        datumi = [f"1. {mesec}. {TEKOCE}" for mesec in (10, 11, 12)]
        assert [zaporedje.index(d) for d in datumi] == sorted(zaporedje.index(d) for d in datumi)
        assert zaporedje.index("Nisem vedela") < zaporedje.index("Težko")
        assert zaporedje.index("Težko") < zaporedje.index("Lahko")
        for quiz_id in kvizi:
            assert f"/admin/quizzes/{quiz_id}" in zaporedje


class TestPredmeti:
    def test_prazna_baza(self, odjemalec: TestClient) -> None:
        besedilo = pregled(odjemalec)

        assert "V tem obdobju ni nobene ocene." in besedilo
        for predmet_ in PREDMETI:
            assert f'<span class="koda">{predmet_.koda}</span>' in besedilo

    def test_predmet_brez_poskusov(self, odjemalec: TestClient) -> None:
        assert "V tem obdobju pri tem predmetu ni nobene ocene." in predmet(odjemalec, "GEO")

    def test_neznana_koda_brez_poskusov_je_404(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get("/admin/statistics/subjects/XXX")

        assert odgovor.status_code == 404
        assert "Predmeta s to kodo ni" in odgovor.text

    def test_neznana_koda_s_poskusi(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, subject="XXX", vprasanj=1)
        kviz_z_ocenami(odjemalec, motor, [UUID_ENA], ["tezko"], telefon, koliko=1, subject="XXX")

        besedilo = pregled(odjemalec)

        assert besedilo.index('<span class="koda">GUM</span>') < besedilo.index(
            '<span class="koda">XXX</span>'
        )
        assert vprasanje(1) in predmet(odjemalec, "XXX")

    def test_neznana_koda_samo_s_poskusi_drugega_nacina_je_404(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, subject="XXX", vprasanj=1)
        quiz_id = kviz_z_ocenami(odjemalec, motor, [UUID_ENA], [], telefon, koliko=1, subject="XXX")
        [postavka] = postavke(motor, quiz_id)
        vstavi_poskus(motor, postavka, mode="abc")

        assert odjemalec.get("/admin/statistics/subjects/XXX").status_code == 404

    def test_stran_predmeta_kaze_samo_ta_predmet(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=1)
        snov(motor, slike, UUID_DVA, subject="GEO", vprasanj=1)
        kviz_z_ocenami(odjemalec, motor, [UUID_ENA], ["lahko"], telefon, koliko=1)
        kviz_z_ocenami(odjemalec, motor, [UUID_DVA], ["tezko"], telefon, koliko=1, subject="GEO")

        mat = predmet(odjemalec, "MAT")

        assert vprasanje(1) in mat
        assert vprasanje(1, UUID_DVA) not in mat
        assert "1 poskus" in razdelek(mat, '<p class="pod">', "</p>")
        assert "Težko 1" not in razdelek(mat, "<h2>Snovi</h2>")
        besedilo = pregled(odjemalec)
        assert "Lahko 1" in vrstica(besedilo, '<span class="koda">MAT</span>')
        assert "Težko 1" in vrstica(besedilo, '<span class="koda">GEO</span>')

    def test_dnevni_kviz_steje_pod_predmetom_vprasanja(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        """Predmet seštevka je `questions.subject`, ne `quizzes.subject`.

        Dnevni kviz predmeta nima; če bi ga statistika vzela iz kviza, bi
        njegovi poskusi s strani predmetov tiho izginili.
        """
        snov(motor, slike, UUID_ENA, vprasanj=1)
        kviz_z_ocenami(
            odjemalec, motor, [UUID_ENA], ["tezko"], telefon, koliko=1, subject=None, vstop="danes"
        )
        with Session(motor) as seja:
            assert seja.scalars(select(Quiz.subject)).one() is None

        assert "1 poskus" in vrstica(pregled(odjemalec), '<span class="koda">MAT</span>')
        assert vprasanje(1) in predmet(odjemalec)

    def test_najtezje_zgoraj_samo_kjer_je_res(self, odjemalec: TestClient) -> None:
        # Pregled je po urniku, stran predmeta po težavnosti.
        assert "Najtežje je zgoraj" not in pregled(odjemalec)
        assert "Najtežje je zgoraj" in predmet(odjemalec)


class TestVidnost:
    def test_poti_statistike_so_samo_pod_admin(self, aplikacija: FastAPI) -> None:
        # Iz sheme OpenAPI in ne iz `aplikacija.routes`: FastAPI 0.14x vključene
        # usmerjevalnike tam hrani kot `_IncludedRouter` brez poti, in test bi
        # jih ne videl. Pot, ki bi bila iz sheme izvzeta, test podre (`assert
        # poti`), ne pa tiho spusti skozi.
        vse = list(aplikacija.openapi()["paths"])
        poti = [pot for pot in vse if "statistics" in pot]

        assert poti, vse
        assert all(pot.startswith("/admin/") for pot in poti), poti

    def test_stran_je_brez_kljuca(self, odjemalec: TestClient) -> None:
        assert odjemalec.get("/admin/statistics").status_code == 200

    def test_povezava_na_admin(self, odjemalec: TestClient) -> None:
        assert 'href="/admin/statistics"' in odjemalec.get("/admin").text


class TestPoizvedbe:
    @staticmethod
    def _stej(motor: Engine, klic: Callable[[], object]) -> int:
        stevec = 0

        def poslusalec(*_: object) -> None:
            nonlocal stevec
            stevec += 1

        event.listen(motor, "before_cursor_execute", poslusalec)
        try:
            klic()
        finally:
            event.remove(motor, "before_cursor_execute", poslusalec)
        return stevec

    def test_stran_predmeta_je_stalno_stevilo_poizvedb(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=1)
        kviz_z_ocenami(odjemalec, motor, [UUID_ENA], ["tezko"], telefon, koliko=1)
        ena = self._stej(motor, lambda: predmet(odjemalec))

        for material_id, dan in ((UUID_DVA, 5), (UUID_TRI, 6)):
            snov(
                motor,
                slike,
                material_id,
                vprasanj=10,
                taken_at=datetime(2026, 9, dan, 7, 30, tzinfo=UTC),
            )
        kviz_z_ocenami(odjemalec, motor, [UUID_DVA, UUID_TRI], ["srednje"] * 20, telefon, koliko=10)
        mnogo = self._stej(motor, lambda: predmet(odjemalec))

        assert re.search(r"Postavljena enkrat · 21 vprašanj", predmet(odjemalec))
        assert mnogo == ena


class TestIzbiraOtroka:
    """Statistika je od `V3-R07` ločena po otroku (`ADR-039` B).

    Skupne številke čez dva otroka ni: delež *Nisem vedela* čez oba ni podatek
    o nobenem od njiju, statistika pa je pripomoček za pogovor z enim otrokom
    (`ADR-021` A).
    """

    def test_pri_enem_otroku_izbirnika_ni(self, odjemalec: TestClient) -> None:
        """Kriterij `V3-R07`: vmesnik družine z enim otrokom se ne spremeni."""
        assert "Otrok:" not in pregled(odjemalec)
        assert "Otrok:" not in predmet(odjemalec)

    def test_pri_dveh_otrocih_je_izbirnik_na_obeh_straneh(
        self, odjemalec: TestClient, brat: str
    ) -> None:
        assert "Otrok:" in pregled(odjemalec)
        assert "Otrok:" in predmet(odjemalec)

    def test_steje_samo_poskuse_izbranega_otroka(
        self,
        odjemalec: TestClient,
        motor: Engine,
        slike: Path,
        otrok: str,
        brat: str,
        telefon: SejaTesta,
    ) -> None:
        """Isti kviz, dva odgovarjalca — vsak vidi svoje in samo svoje."""
        snov(motor, slike, UUID_ENA, vprasanj=3)
        quiz_id = kviz_z_ocenami(odjemalec, motor, [UUID_ENA], [], telefon, koliko=3)
        prva, druga, tretja = postavke(motor, quiz_id)
        vstavi_poskus(motor, prva, rating="lahko", child_id=otrok)
        vstavi_poskus(motor, druga, rating="nisem_vedela", child_id=brat)
        vstavi_poskus(motor, tretja, rating="nisem_vedela", child_id=brat)

        kljuc = '<span class="koda">MAT</span>'
        assert "1 poskus" in vrstica(pregled(odjemalec, f"?otrok={otrok}"), kljuc)
        assert "2 poskusa" in vrstica(pregled(odjemalec, f"?otrok={brat}"), kljuc)

    def test_privzeti_otrok_je_prvi_po_imenu(
        self,
        odjemalec: TestClient,
        motor: Engine,
        slike: Path,
        otrok: str,
        brat: str,
        telefon: SejaTesta,
    ) -> None:
        """`Maša` je po abecedi pred `Nejc`, zato je privzeta ona (`ADR-039` B)."""
        snov(motor, slike, UUID_ENA, vprasanj=1)
        quiz_id = kviz_z_ocenami(odjemalec, motor, [UUID_ENA], [], telefon, koliko=1)
        vstavi_poskus(motor, postavke(motor, quiz_id)[0], child_id=brat)

        # Maša nima nobenega poskusa — privzeti pogled je zato prazen in ne
        # bratov. Brez privzetka bi stran pokazala številke napačnega otroka.
        assert "V tem obdobju ni nobene ocene." in pregled(odjemalec)
        assert "V tem obdobju ni nobene ocene." not in pregled(odjemalec, f"?otrok={brat}")

    def test_tuj_otrok_je_404_na_obeh_straneh(
        self, odjemalec: TestClient, tuj_otrok: str
    ) -> None:
        for pot in ("/admin/statistics", "/admin/statistics/subjects/MAT"):
            odgovor = odjemalec.get(pot, params={"otrok": tuj_otrok})
            assert odgovor.status_code == 404, pot
            assert "Tega otroka v tvoji družini ni." in odgovor.text

    def test_izbira_leta_ohrani_otroka(self, odjemalec: TestClient, brat: str) -> None:
        besedilo = pregled(odjemalec, f"?otrok={brat}")

        assert f"otrok={brat}" in besedilo
        assert "leto=vse" in besedilo

    def test_povezava_na_predmet_ohrani_otroka(
        self, odjemalec: TestClient, brat: str
    ) -> None:
        besedilo = pregled(odjemalec, f"?otrok={brat}")

        assert "/admin/statistics/subjects/MAT?leto=" in besedilo
        assert f"otrok={brat}" in besedilo
