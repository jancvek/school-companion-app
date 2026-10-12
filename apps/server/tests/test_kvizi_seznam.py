"""Stran z vsemi kvizi in zadnji štirje na Predmetih (V5-R01).

`GET /admin/quizzes` je nova pot (`docs/odlocitve/ADR-056` G): vsi kvizi
družine, filter po stanju in po otroku, delitev po mesecih. Predmeti pokažejo
zadnje štiri in povezavo sem; razdelki-povezave na dnu `/admin` so odpadli.
"""

import re
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.models import Quiz
from app.routers import kvizi
from app.routers.kvizi import STANJE_CAKA, STANJE_PREKLICAN, STANJE_RESEN, stanje_kviza
from tests.conftest import (
    BRAT_ID,
    CVEK_ID,
    OTROK_ID,
    TUJ_OTROK_ID,
    PrijavljenOdjemalec,
    prijavi,
    ustvari_otroka,
    vsebina_strani,
)

POT = "/admin/quizzes"


@pytest.fixture(autouse=True)
def _druzina_ima_otroka(otrok: str) -> str:
    return otrok


def kviz(
    motor: Engine,
    ime: str,
    *,
    nastal: datetime,
    otrok: str = OTROK_ID,
    resen: bool = False,
    preklican: bool = False,
    predmet: str | None = "MAT",
) -> str:
    """Kviz brez postavk v danem stanju; vrne njegov `id` (= ime, za berljivost)."""
    with Session(motor) as seja:
        seja.add(
            Quiz(
                id=ime,
                family_id=CVEK_ID,
                child_id=otrok,
                name=ime,
                subject=predmet,
                created_at=nastal,
                solved_at=nastal if resen else None,
                canceled_at=nastal if preklican else None,
            )
        )
        seja.commit()
    return ime


def dne(mesec: int, dan: int, ura: int = 10) -> datetime:
    return datetime(2026, mesec, dan, ura, tzinfo=UTC)


def imena_kvizov(besedilo: str) -> list[str]:
    """Imena kvizov v tabeli, v vrstnem redu izrisa."""
    return re.findall(r'<td class="glavna"><a href="/admin/quizzes/[^"]+">([^<]+)</a>', besedilo)


def zavihki(besedilo: str, oznaka: str) -> list[tuple[str, str, bool]]:
    """(besedilo, naslov, izbran) zavihkov skupine z danim `aria-label`."""
    zacetek = besedilo.index(f'<ul class="zavihki" aria-label="{oznaka}">')
    skupina = besedilo[zacetek : besedilo.index("</ul>", zacetek)]
    return [
        (" ".join(re.sub(r"<[^>]+>", " ", vsebina).split()), naslov, bool(izbran))
        for naslov, izbran, vsebina in re.findall(
            r'<a href="([^"]+)"( aria-current="true")?>(.*?)</a>', skupina, re.S
        )
    ]


@pytest.fixture
def stirje(motor: Engine, brat: str) -> None:
    """Štirje kvizi v vseh stanjih, pri dveh otrocih in v dveh mesecih."""
    kviz(motor, "caka-masa", nastal=dne(10, 8))
    kviz(motor, "resen-masa", nastal=dne(10, 6), resen=True)
    kviz(motor, "preklican-nejc", nastal=dne(9, 29), otrok=BRAT_ID, preklican=True)
    kviz(motor, "caka-nejc", nastal=dne(9, 20), otrok=BRAT_ID)


class TestStanjeKviza:
    def test_tri_stanja(self) -> None:
        zdaj = dne(10, 1)

        def stanje(resen: bool, preklican: bool) -> str:
            return stanje_kviza(
                Quiz(solved_at=zdaj if resen else None, canceled_at=zdaj if preklican else None)
            )

        assert stanje(False, False) == STANJE_CAKA
        assert stanje(True, False) == STANJE_RESEN
        assert stanje(False, True) == STANJE_PREKLICAN

    def test_preklic_ima_prednost_pred_resenostjo(self) -> None:
        # `ADR-019` C: telefon je kviz lahko rešil, preden je izvedel za preklic.
        zdaj = dne(10, 1)

        assert stanje_kviza(Quiz(solved_at=zdaj, canceled_at=zdaj)) == STANJE_PREKLICAN


class TestVsiKvizi:
    def test_brez_filtra_pokaze_vse_najnovejsi_prvi(
        self, odjemalec: TestClient, stirje: None
    ) -> None:
        odgovor = odjemalec.get(POT)

        assert odgovor.status_code == 200
        assert imena_kvizov(odgovor.text) == [
            "caka-masa",
            "resen-masa",
            "preklican-nejc",
            "caka-nejc",
        ]

    @pytest.mark.parametrize(
        ("stanje", "pricakovani"),
        [
            ("cakajo", ["caka-masa", "caka-nejc"]),
            ("reseni", ["resen-masa"]),
            ("preklicani", ["preklican-nejc"]),
        ],
    )
    def test_filter_po_stanju(
        self, odjemalec: TestClient, stirje: None, stanje: str, pricakovani: list[str]
    ) -> None:
        assert imena_kvizov(odjemalec.get(f"{POT}?stanje={stanje}").text) == pricakovani

    def test_filter_po_otroku(self, odjemalec: TestClient, stirje: None) -> None:
        besedilo = odjemalec.get(f"{POT}?otrok={BRAT_ID}").text

        assert imena_kvizov(besedilo) == ["preklican-nejc", "caka-nejc"]

    def test_oba_filtra_hkrati(self, odjemalec: TestClient, stirje: None) -> None:
        besedilo = odjemalec.get(f"{POT}?stanje=cakajo&otrok={BRAT_ID}").text

        assert imena_kvizov(besedilo) == ["caka-nejc"]

    def test_preklican_in_resen_je_samo_med_preklicanimi(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        kviz(motor, "oboje", nastal=dne(10, 1), resen=True, preklican=True)

        assert imena_kvizov(odjemalec.get(f"{POT}?stanje=preklicani").text) == ["oboje"]
        assert imena_kvizov(odjemalec.get(f"{POT}?stanje=reseni").text) == []
        assert imena_kvizov(odjemalec.get(f"{POT}?stanje=cakajo").text) == []

    def test_zavihki_stanja_nosijo_stevila_in_izbranega(
        self, odjemalec: TestClient, stirje: None
    ) -> None:
        besedilo = odjemalec.get(f"{POT}?stanje=reseni").text

        assert zavihki(besedilo, "Stanje") == [
            ("Vsi 4", POT, False),
            ("Čakajo 2", f"{POT}?stanje=cakajo", False),
            ("Rešeni 1", f"{POT}?stanje=reseni", True),
            ("Preklicani 1", f"{POT}?stanje=preklicani", False),
        ]

    def test_stevila_stanj_veljajo_za_izbranega_otroka(
        self, odjemalec: TestClient, stirje: None
    ) -> None:
        besedilo = odjemalec.get(f"{POT}?otrok={OTROK_ID}").text

        assert [oznaka for oznaka, _, _ in zavihki(besedilo, "Stanje")] == [
            "Vsi 2",
            "Čakajo 1",
            "Rešeni 1",
            "Preklicani 0",
        ]

    def test_zavihka_nosita_drug_drugega(self, odjemalec: TestClient, stirje: None) -> None:
        """Menjava stanja ne sme tiho ponastaviti otroka in obratno."""
        besedilo = odjemalec.get(f"{POT}?stanje=cakajo&otrok={BRAT_ID}").text

        assert all(
            naslov.endswith(f"otrok={BRAT_ID}") for _, naslov, _ in zavihki(besedilo, "Stanje")
        )
        assert zavihki(besedilo, "Otrok") == [
            ("Oba", f"{POT}?stanje=cakajo", False),
            ("Maša", f"{POT}?stanje=cakajo&amp;otrok={OTROK_ID}", False),
            ("Nejc", f"{POT}?stanje=cakajo&amp;otrok={BRAT_ID}", True),
        ]

    def test_trije_otroci_dobijo_zavihek_vsi(
        self, odjemalec: TestClient, motor: Engine, brat: str
    ) -> None:
        ustvari_otroka(motor, user_id=None, identifikator="zala", prikazno_ime="Zala")

        assert zavihki(odjemalec.get(POT).text, "Otrok")[0][0] == "Vsi"

    def test_deaktiviran_otrok_ostane_med_zavihki(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        # `ADR-039` F2: njegovi kvizi ostanejo in morajo biti dosegljivi.
        ustvari_otroka(
            motor, user_id=BRAT_ID, identifikator="nejc", prikazno_ime="Nejc", aktiven=False
        )
        kviz(motor, "nejcev", nastal=dne(10, 1), otrok=BRAT_ID)

        besedilo = odjemalec.get(f"{POT}?otrok={BRAT_ID}").text

        assert imena_kvizov(besedilo) == ["nejcev"]
        assert "Nejc" in [oznaka for oznaka, _, _ in zavihki(besedilo, "Otrok")]

    def test_en_otrok_nima_zavihkov_ne_stolpca_ne_imena(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        # `ADR-039` F3: pri enem otroku imena ni nikjer.
        kviz(motor, "edini", nastal=dne(10, 1))

        besedilo = vsebina_strani(odjemalec.get(POT).text)

        assert 'aria-label="Otrok"' not in besedilo
        assert ">Otrok<" not in besedilo
        assert "Maša" not in besedilo

    def test_pri_dveh_otrocih_je_ime_vrednost_v_svojem_stolpcu(
        self, odjemalec: TestClient, stirje: None
    ) -> None:
        besedilo = odjemalec.get(POT).text

        assert '<th scope="col">Otrok</th>' in besedilo
        assert "<td>Maša</td>" in besedilo
        assert "<td>Nejc</td>" in besedilo

    def test_delitev_po_mesecih(self, odjemalec: TestClient, stirje: None) -> None:
        besedilo = odjemalec.get(POT).text
        vrstice = re.findall(
            r'<tr class="mesec"><td colspan="\d">([^<]+)</td>'
            r'|<td class="glavna"><a[^>]+>([^<]+)</a>',
            besedilo,
        )

        assert [mesec or ime for mesec, ime in vrstice] == [
            "Oktober 2026",
            "caka-masa",
            "resen-masa",
            "September 2026",
            "preklican-nejc",
            "caka-nejc",
        ]

    def test_mesec_je_v_domacem_pasu(self, odjemalec: TestClient, motor: Engine) -> None:
        # 30. 9. ob 23:30 UTC je v Ljubljani že 1. 10. ob 1:30.
        kviz(motor, "cez-polnoc", nastal=datetime(2026, 9, 30, 23, 30, tzinfo=UTC))

        besedilo = odjemalec.get(POT).text

        assert "Oktober 2026" in besedilo
        assert "September 2026" not in besedilo

    def test_vrstica_nosi_predmet_datum_stanje_in_stevilo(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        kviz(motor, "resen", nastal=dne(10, 6), resen=True)
        kviz(motor, "cez-vse", nastal=dne(10, 5), predmet=None)

        besedilo = odjemalec.get(POT).text

        assert '<span class="cip" style="--barva: #2d5a8e">MAT</span>' in besedilo
        # Kviz čez več predmetov barve predmeta nima.
        assert '<span class="cip" style="--barva: var(--zamolklo)">Vsi predmeti</span>' in besedilo
        assert '<span class="oznaka ok">rešen 6. 10.</span>' in besedilo
        assert "<td>6. 10.</td>" in besedilo

    def test_neznano_stanje_je_400(self, odjemalec: TestClient, stirje: None) -> None:
        odgovor = odjemalec.get(f"{POT}?stanje=vsi")

        assert odgovor.status_code == 400
        assert kvizi.SPOROCILO_NEZNANO_STANJE in odgovor.text
        assert imena_kvizov(odgovor.text) == []

    @pytest.mark.parametrize("otrok", [TUJ_OTROK_ID, "ni-otrok"])
    def test_tuj_ali_neznan_otrok_je_404(
        self, odjemalec: TestClient, stirje: None, tuj_otrok: str, otrok: str
    ) -> None:
        odgovor = odjemalec.get(f"{POT}?otrok={otrok}")

        assert odgovor.status_code == 404
        assert kvizi.SPOROCILO_NEZNAN_OTROK in odgovor.text
        assert imena_kvizov(odgovor.text) == []

    def test_prazna_parametra_stejeta_kot_brez_filtra(
        self, odjemalec: TestClient, stirje: None
    ) -> None:
        assert len(imena_kvizov(odjemalec.get(f"{POT}?stanje=&otrok=").text)) == 4

    def test_prazen_seznam_pove_kaj_narediti(self, odjemalec: TestClient) -> None:
        besedilo = odjemalec.get(POT).text

        assert "Objavljenega kviza še ni." in besedilo
        assert "<table" not in besedilo

    def test_prazen_filter_ponudi_vse(self, odjemalec: TestClient, stirje: None) -> None:
        besedilo = odjemalec.get(f"{POT}?stanje=reseni&otrok={BRAT_ID}").text

        assert "Pri tej izbiri ni nobenega kviza." in besedilo
        assert f'<a href="{POT}">Pokaži vse kvize</a>' in besedilo

    def test_obrazec_za_nov_kviz_ohrani_pot_in_polja(self, odjemalec: TestClient) -> None:
        """`ADR-056` I: isti `GET`, isti imeni polj in iste vrednosti kot prej."""
        besedilo = odjemalec.get(POT).text

        assert '<form method="get" action="/admin/quizzes/new"' in besedilo
        assert '<select id="nov-kviz-predmet" name="subject">' in besedilo
        assert re.search(r'<button[^>]+name="vstop" value="nova">', besedilo)
        assert re.search(r'<button[^>]+name="vstop" value="rocna">', besedilo)
        assert 'href="/admin/quizzes/new?vstop=danes"' in besedilo
        assert besedilo.count("<option ") == 10

    def test_brez_aktivnega_otroka_obrazca_ni(
        self, aplikacija: FastAPI, motor: Engine, stars: str
    ) -> None:
        # Brez samodejnega otroka: družina, ki ima samo deaktiviranega.
        from sqlalchemy import update

        from app.models import User

        with Session(motor) as seja:
            seja.execute(update(User).where(User.id == OTROK_ID).values(is_active=False))
            seja.commit()
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            prijavi(odjemalec, motor, stars)
            besedilo = odjemalec.get(POT).text

        assert 'action="/admin/quizzes/new"' not in besedilo
        assert "vstop=danes" not in besedilo
        assert 'href="/admin/family"' in vsebina_strani(besedilo)

    def test_stran_je_brez_skripte(self, odjemalec: TestClient, stirje: None) -> None:
        assert "<script" not in odjemalec.get(POT).text.lower()

    def test_pot_new_ni_prebrana_kot_kviz(self, odjemalec: TestClient) -> None:
        # Vrstni red registracije: nova prazna pot ne sme zasenčiti `/new`.
        odgovor = odjemalec.get(f"{POT}/new?subject=MAT&vstop=rocna")

        assert odgovor.status_code == 200
        assert "Kviza s tem naslovom ni" not in odgovor.text


class TestPredmetiKazejoZadnjeStiri:
    def test_stirje_najnovejsi_in_povezava_na_vse(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        for dan in range(1, 6):
            kviz(motor, f"kviz-{dan}", nastal=dne(10, dan))

        besedilo = odjemalec.get("/admin").text

        assert imena_kvizov(besedilo) == ["kviz-5", "kviz-4", "kviz-3", "kviz-2"]
        assert f'<a href="{POT}">Vsi kvizi</a>' in besedilo

    def test_na_predmetih_ni_delitve_po_mesecih_in_datum_nosi_leto(
        self, odjemalec: TestClient, stirje: None
    ) -> None:
        besedilo = odjemalec.get("/admin").text

        assert 'class="mesec"' not in besedilo
        assert "<td>8. 10. 2026</td>" in besedilo

    def test_razdelkov_povezav_na_dnu_ni_vec(self, odjemalec: TestClient) -> None:
        """`ADR-056` G: nadomesti jih meni."""
        vsebina = vsebina_strani(odjemalec.get("/admin").text)

        for naslov in ("Pregled po dnevih", "Urnik", "Družina", "Sistem", "Statistika", "Testi"):
            assert f"<h2>{naslov}</h2>" not in vsebina
        for pot in ("/admin/days", "/admin/schedule", "/admin/statistics", "/admin/assessments"):
            assert f'href="{pot}"' not in vsebina

    def test_kartica_danes_nosi_datum_z_imenom_dneva(self, odjemalec: TestClient) -> None:
        # `conftest` pritrdi današnji dan domače strani na sredo, 16. 9. 2026.
        assert "sreda, 16. september" in odjemalec.get("/admin").text

    def test_zvezek_nosi_barvo_predmeta_in_prazen_je_oznacen(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        besedilo = odjemalec.get("/admin").text

        assert re.search(
            r'<a class="zvezek prazen"\s+href="/admin/subjects/MAT"\s+style="--barva: #2d5a8e">',
            besedilo,
        )
