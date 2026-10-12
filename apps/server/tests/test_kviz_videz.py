"""Izbor snovi, predogled, kviz in Po dnevih po V5-R01.

Kar so te strani znale že prej, varujejo `test_kvizi.py`, `test_rezultat.py`
in `test_dnevi.py`. Tu je novo vedenje iz `docs/poc/POC-02.md`: delitev po
tednih, „Izberi vse / Počisti izbor", zvezna številka v predogledu, pas
razporeditve in zavihki.
"""

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.casi import dan_in_ura, danes, pas
from app.models import STATUS_V_OBDELAVI
from app.tedni import oznaka_tedna, ponedeljek_tedna
from tests.conftest import BRAT_ID, OTROK_ID, SejaTesta, vsebina_strani
from tests.test_kvizi import (
    UUID_DVA,
    UUID_ENA,
    izbirnik,
    je_izbirna,
    je_obkljukana,
    objavi,
    snov,
)
from tests.test_resevanje import poskus, poslji
from tests.test_rezultat import postavke

UUID_TRI = "33333333-3333-4333-8333-333333333333"


@pytest.fixture(autouse=True)
def _druzina_ima_otroka(otrok: str) -> str:
    return otrok


def opoldne(dan: date) -> datetime:
    """Poldne tega dne v domačem pasu, zapisano v UTC."""
    return datetime(dan.year, dan.month, dan.day, 12, tzinfo=pas()).astimezone(UTC)


class TestOznakaTedna:
    def test_ta_prejsnji_in_starejsi_teden(self) -> None:
        danasnji = date(2026, 10, 8)  # četrtek

        assert oznaka_tedna(date(2026, 10, 5), danasnji) == "Ta teden"
        assert oznaka_tedna(date(2026, 9, 28), danasnji) == "Prejšnji teden"
        assert oznaka_tedna(date(2026, 9, 21), danasnji) == "21.\u201325. september"

    def test_dan_in_ura_je_v_domacem_pasu(self) -> None:
        # Četrtek ob 8:41 UTC je v Ljubljani ob 10:41.
        assert dan_in_ura(datetime(2026, 10, 8, 8, 41, tzinfo=UTC)) == "Četrtek, 8. 10. ob 10:41"


class TestIzborSnovi:
    def test_seznam_je_po_tednih_najnovejsi_prvi(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        ta = ponedeljek_tedna(danes())
        snov(motor, slike, UUID_ENA, taken_at=opoldne(ta))
        snov(motor, slike, UUID_DVA, taken_at=opoldne(ta - timedelta(days=7)))
        snov(motor, slike, UUID_TRI, taken_at=opoldne(ta - timedelta(days=21)))

        besedilo = izbirnik(odjemalec)
        deli = re.findall(
            r'<h2 class="naslov-tedna">([^<]+)</h2>|name="snov" value="([^"]+)"', besedilo
        )

        zapis = [naslov or snov_id for naslov, snov_id in deli]
        assert zapis[:4] == ["Ta teden", UUID_ENA, "Prejšnji teden", UUID_DVA]
        # Starejši teden nosi razpon dni in ne imena.
        assert re.fullmatch(r"\d+\..*", zapis[4])
        assert zapis[5] == UUID_TRI

    def test_izberi_vse_obkljuka_izbirne_in_samo_te(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)
        snov(motor, slike, UUID_DVA)
        snov(motor, slike, UUID_TRI, status=STATUS_V_OBDELAVI, readable=None, vprasanj=0)

        besedilo = odjemalec.get(
            "/admin/quizzes/new", params={"vstop": "rocna", "subject": "MAT", "izbor": "vse"}
        ).text

        assert je_obkljukana(besedilo, UUID_ENA)
        assert je_obkljukana(besedilo, UUID_DVA)
        # Neizbirna snov okenca nima, torej je „Izberi vse" ne more izbrati.
        assert not je_izbirna(besedilo, UUID_TRI)
        assert besedilo.count(" checked") == 2

    def test_pocisti_izbor_preglasi_pravilo_vstopa(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)
        # Vstop „nova" bi snov sicer obkljukal.
        assert je_obkljukana(izbirnik(odjemalec, vstop="nova"), UUID_ENA)

        besedilo = odjemalec.get(
            "/admin/quizzes/new", params={"vstop": "nova", "subject": "MAT", "izbor": "nic"}
        ).text

        assert not je_obkljukana(besedilo, UUID_ENA)

    def test_neznana_vrednost_izbora_pusti_pravilo_vstopa(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)

        besedilo = odjemalec.get(
            "/admin/quizzes/new", params={"vstop": "rocna", "subject": "MAT", "izbor": "da"}
        ).text

        assert not je_obkljukana(besedilo, UUID_ENA)

    def test_povezavi_izbora_nosita_vstop_predmet_stevilo_in_otroka(
        self, odjemalec: TestClient, motor: Engine, slike: Path, brat: str
    ) -> None:
        snov(motor, slike, UUID_ENA)

        besedilo = odjemalec.get(
            "/admin/quizzes/new",
            params={"vstop": "rocna", "subject": "MAT", "stevilo": "7", "otrok": BRAT_ID},
        ).text

        osnova = f"/admin/quizzes/new?vstop=rocna&amp;subject=MAT&amp;stevilo=7&amp;otrok={BRAT_ID}"
        assert f'<a href="{osnova}&amp;izbor=vse">Izberi vse</a>' in besedilo
        assert f'<a href="{osnova}&amp;izbor=nic">Počisti izbor</a>' in besedilo

    def test_ze_uporabljena_snov_to_pove_in_ostane_izbirna(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)
        snov(motor, slike, UUID_DVA)
        objavi(odjemalec, motor, [UUID_ENA])

        besedilo = izbirnik(odjemalec, vstop="rocna")

        assert besedilo.count("· že v kvizu") == 1
        assert je_izbirna(besedilo, UUID_ENA)

    def test_obrazec_ohrani_pot_in_polja_in_steje_brez_skripte(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """`ADR-056` I in F."""
        snov(motor, slike, UUID_ENA)

        besedilo = izbirnik(odjemalec)

        assert '<form method="post" action="/admin/quizzes/preview">' in besedilo
        assert re.search(r'<input type="number" id="[^"]+" name="stevilo"', besedilo)
        assert '<input type="hidden" name="vstop" value="nova">' in besedilo
        assert f'<input type="hidden" name="otrok" value="{OTROK_ID}">' in besedilo
        assert '<span class="stevilo-izbranih"></span>' in besedilo
        assert '<button class="gumb polni" type="submit">Sestavi</button>' in besedilo
        assert "<script" not in besedilo.lower()

    def test_koraka_povesta_kje_si(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)

        izbor = izbirnik(odjemalec)
        predogled = odjemalec.post(
            "/admin/quizzes/preview",
            data={"vstop": "nova", "subject": "MAT", "stevilo": "3", "snov": [UUID_ENA]},
        ).text

        assert re.search(r'<li aria-current="step"><span class="korak-st">1</span>', izbor)
        assert re.search(r'<li class="opravljen">.*?Izberi snov</li>', predogled, re.S)
        assert re.search(r'<li aria-current="step"><span class="korak-st">2</span>', predogled)


class TestPredogled:
    def test_stevilka_vprasanja_tece_zvezno_cez_snovi(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=3, taken_at=datetime(2026, 9, 4, 8, tzinfo=UTC))
        snov(motor, slike, UUID_DVA, vprasanj=2, taken_at=datetime(2026, 9, 3, 8, tzinfo=UTC))

        besedilo = odjemalec.post(
            "/admin/quizzes/preview",
            data={
                "vstop": "nova",
                "subject": "MAT",
                "stevilo": "5",
                "snov": [UUID_ENA, UUID_DVA],
            },
        ).text

        assert re.findall(r'<li value="(\d+)">', besedilo) == ["1", "2", "3", "4", "5"]
        # Druga snov se začne pri 4 in ne znova pri 1.
        druga = besedilo[besedilo.index(f'href="/admin/materials/{UUID_DVA}"') :]
        assert re.findall(r'<li value="(\d+)">', druga) == ["4", "5"]

    def test_objava_in_vrnitev_ohranita_obrazca(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """`ADR-056` I: dva obrazca, iste poti in ista polja."""
        snov(motor, slike, UUID_ENA, vprasanj=2)

        besedilo = odjemalec.post(
            "/admin/quizzes/preview",
            data={"vstop": "nova", "subject": "MAT", "stevilo": "2", "snov": [UUID_ENA]},
        ).text

        assert re.findall(r'<form method="post" action="([^"]+)">', vsebina_strani(besedilo)) == [
            "/admin/quizzes",
            "/admin/quizzes/new",
        ]
        assert besedilo.count('name="vprasanje"') == 2
        assert re.search(r'<input type="text" id="[^"]+" name="ime"', besedilo)
        assert f'<input type="hidden" name="snov" value="{UUID_ENA}">' in besedilo
        assert "<strong>Ta stran ničesar ne shrani.</strong>" in besedilo


class TestKviz:
    def test_objavljen_kviz_pove_da_caka(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=2)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=2)

        besedilo = odjemalec.get(f"/admin/quizzes/{quiz_id}").text

        assert '<span class="oznaka caka">objavljen</span>' in besedilo
        assert "Kviz čaka na reševanje na telefonu." in besedilo
        assert 'class="razporeditev' not in besedilo
        assert '<a href="/admin/quizzes">Kvizi</a>' in vsebina_strani(besedilo)

    def test_resen_kviz_ima_pas_razporeditve_in_legendo(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=4)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=4)
        idji = postavke(motor, quiz_id)
        ocene = ["nisem_vedela", "lahko", "lahko", "lahko"]
        poslji(
            odjemalec,
            [poskus(p, rating=ocena) for p, ocena in zip(idji, ocene, strict=True)],
            telefon,
        )

        besedilo = odjemalec.get(f"/admin/quizzes/{quiz_id}").text

        assert '<span class="oznaka ok">rešen</span>' in besedilo
        # Pas: četrtina najtežjih, tri četrtine lahkih; prazni skupini nimata dela.
        assert re.findall(r'<span class="pas-(\d)" style="width: ([\d.]+)%"></span>', besedilo) == [
            ("0", "25.0"),
            ("3", "75.0"),
        ]
        legenda = besedilo[besedilo.index('<ul class="legenda-ocen">') :]
        legenda = legenda[: legenda.index("</ul>")]
        assert [" ".join(re.sub(r"<[^>]+>", " ", vrstica).split()) for vrstica in
                re.findall(r"<li>(.*?)</li>", legenda, re.S)] == [
            "Nisem vedela 1",
            "Težko 0",
            "Srednje 0",
            "Lahko 3",
        ]
        # Skupine nosijo barvo ocene, od najtežje navzdol.
        assert re.findall(r'<section class="skupina kartica ocena-(\d)">', besedilo) == [
            "0",
            "1",
            "2",
            "3",
        ]

    def test_preklic_je_vrstica_upravljanja_in_ohrani_obrazec(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=1)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=1)

        besedilo = odjemalec.get(f"/admin/quizzes/{quiz_id}").text

        assert re.search(
            rf'<form method="post" action="/admin/quizzes/{quiz_id}/cancel">\s*'
            r'<input type="hidden" name="csrf" value="[^"]+">\s*'
            r'<button class="gumb majhen nevaren" type="submit">Prekliči kviz</button>',
            besedilo,
        )

    def test_preklican_kviz_gumba_za_preklic_nima(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=1)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=1)
        odjemalec.post(f"/admin/quizzes/{quiz_id}/cancel", follow_redirects=False)

        besedilo = odjemalec.get(f"/admin/quizzes/{quiz_id}").text

        assert '<span class="oznaka precrtana">preklican</span>' in besedilo
        assert "/cancel" not in besedilo


class TestPoDnevih:
    def test_zavihki_obdobja_oznacijo_izbranega(self, odjemalec: TestClient) -> None:
        def izbran(poizvedba: str) -> list[str]:
            besedilo = odjemalec.get(f"/admin/days{poizvedba}").text
            zacetek = besedilo.index('<ul class="zavihki" aria-label="Obdobje">')
            zavihki = besedilo[zacetek : besedilo.index("</ul>", zacetek)]
            return re.findall(r'aria-current="true">([^<]+)<', zavihki)

        vceraj = (danes() - timedelta(days=1)).isoformat()
        assert izbran("") == ["Danes"]
        assert izbran(f"?dan={vceraj}") == ["Včeraj"]
        assert izbran("?obdobje=teden") == ["Zadnjih 7 dni"]
        # Poljuben starejši dan ni nobeden od treh.
        assert izbran("?dan=2026-01-05") == []

    def test_ta_teden_se_imenuje_zadnjih_sedem_dni(self, odjemalec: TestClient) -> None:
        besedilo = odjemalec.get("/admin/days?obdobje=teden").text

        assert "Zadnjih 7 dni" in besedilo
        assert "Ta teden" not in besedilo

    def test_zavihki_otrok_nosijo_obdobje_naprej(
        self, odjemalec: TestClient, brat: str
    ) -> None:
        teden = odjemalec.get("/admin/days?obdobje=teden").text
        dan = odjemalec.get("/admin/days?dan=2026-09-07").text

        assert f'href="/admin/days?obdobje=teden&amp;otrok={BRAT_ID}"' in teden
        assert f'href="/admin/days?dan=2026-09-07&amp;otrok={BRAT_ID}"' in dan
        assert '<select name="otrok">' not in teden

    def test_dan_je_kartica_z_naslovom_cipi_in_manjki(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        from sqlalchemy.orm import Session

        from app.db import ScheduleRepository
        from app.urnik import Vnos
        from tests.conftest import CVEK_ID
        from tests.test_dnevi import zapisi

        ponedeljek = date(2026, 9, 7)
        zapisi(motor, slike, "mat", subject="MAT", taken_at=opoldne(ponedeljek))
        ScheduleRepository(Session(motor), CVEK_ID).potrdi(
            OTROK_ID, [Vnos(0, "MAT"), Vnos(0, "SLJ")], None
        )

        besedilo = odjemalec.get("/admin/days?dan=2026-09-07").text

        assert "<h2>Ponedeljek, 7. september</h2>" in besedilo
        assert '<span class="cip" style="--barva: #2d5a8e">MAT</span>' in besedilo
        # Manjko je črtkan čip v barvi predmeta; bralnik zaslona dobi poved.
        assert '<span class="skrito">Manjka: SLJ.</span>' in besedilo
        assert (
            '<span class="cip crtkan" aria-hidden="true" style="--barva: #a63f3b">SLJ</span>'
            in besedilo
        )

    def test_prazen_dan_je_ena_vrstica(self, odjemalec: TestClient) -> None:
        besedilo = odjemalec.get("/admin/days?dan=2026-09-07").text

        assert re.search(
            r'<section class="dan-prazen">\s*<h2>Ponedeljek, 7. september</h2>\s*'
            r"<p>Tega dne ni nobene slike.</p>",
            besedilo,
        )
