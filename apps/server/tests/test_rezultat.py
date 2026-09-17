"""Testi rezultata rešenega kviza in strani za tisk (V2-R03).

Pokrivajo tabelo „Test casi" iz `docs/plan/V2-R03.md`.

Kviz nastane skozi sestavljalnik (`objavi`), poskusi pa skozi pot telefona
(`POST /quiz-attempts`) — tako je `solved_at` postavil strežnik sam, kot v
produkciji, in ne test.
"""

import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select, update
from sqlalchemy.orm import Session

from app.casi import trajanje
from app.models import Material, Question, QuestionAttempt, Quiz, QuizItem
from tests.conftest import CVEK_ID
from tests.test_kvizi import UUID_DVA, UUID_ENA, objavi, snov, upokoji
from tests.test_resevanje import poskus, poslji


def postavke(motor: Engine, quiz_id: str) -> list[str]:
    """Identifikatorji postavk kviza po zaporedju."""
    with Session(motor) as seja:
        return list(
            seja.scalars(
                select(QuizItem.id)
                .where(QuizItem.quiz_id == quiz_id)
                .order_by(QuizItem.position)
            )
        )


def resen_kviz(
    odjemalec: TestClient,
    motor: Engine,
    slike: Path,
    ocene: Sequence[str],
    *,
    material_id: str = UUID_ENA,
) -> str:
    """Kviz iz ene snovi z `len(ocene)` vprašanji, rešen z danimi ocenami.

    Ocena na mestu *i* gre postavki s `position` *i + 1*; besedilo te postavke
    je `Vprašanje {i + 1} iz 3f2b?` (glej `snov` v `test_kvizi.py`).
    """
    snov(motor, slike, material_id, vprasanj=len(ocene))
    quiz_id = objavi(odjemalec, motor, [material_id], koliko=len(ocene))
    odgovor = poslji(
        odjemalec,
        [
            poskus(postavka_id, rating=ocena)
            for postavka_id, ocena in zip(postavke(motor, quiz_id), ocene, strict=True)
        ],
    )
    assert odgovor.status_code == 200, odgovor.text
    return quiz_id


def stran(odjemalec: TestClient, quiz_id: str) -> str:
    odgovor = odjemalec.get(f"/admin/quizzes/{quiz_id}")
    assert odgovor.status_code == 200, odgovor.text
    return odgovor.text


def tisk(odjemalec: TestClient, quiz_id: str, poizvedba: str = "") -> str:
    odgovor = odjemalec.get(f"/admin/quizzes/{quiz_id}/print{poizvedba}")
    assert odgovor.status_code == 200, odgovor.text
    return odgovor.text


def del_za_tisk(besedilo: str) -> str:
    """Samo del, ki gre na papir — brez obrazca z oznakami ocen."""
    return besedilo[besedilo.index('<div class="tisk">') :]


def vprasanje(stevilka: int) -> str:
    return f"Vprašanje {stevilka} iz 3f2b?"


#: Oštevilčena vprašanja v seznamu: `(številka, besedilo)`.
OSTEVILCENO = re.compile(r'<li value="(\d+)">\s*<p class="vprasanje">([^<]+)</p>')


class TestNeresenKviz:
    """Rezultat ima samo rešen kviz; nerešen je tak kot pred V2-R03."""

    def test_brez_poskusov_ni_rezultata(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=2)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=2)

        besedilo = stran(odjemalec, quiz_id)

        assert 'class="skupina"' not in besedilo
        assert "/print" not in besedilo
        assert "samoocena" not in besedilo

    def test_delno_ocenjen_kviz_ni_rezultat(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=2)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=2)
        poslji(odjemalec, [poskus(postavke(motor, quiz_id)[0], rating="tezko")])

        besedilo = stran(odjemalec, quiz_id)

        assert 'class="skupina"' not in besedilo
        assert "razmislek" not in besedilo

    def test_opombe_izvora_so_samo_v_rezultatu(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Stran nerešenega kviza se ne spremeni (odločitev 3 v planu)."""
        snov(motor, slike, UUID_ENA, vprasanj=1)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=1)
        prej = stran(odjemalec, quiz_id)

        with Session(motor) as seja:
            seja.execute(
                update(Material)
                .where(Material.id == UUID_ENA)
                .values(archived_at=datetime.now(UTC))
            )
            seja.commit()
        upokoji(motor, UUID_ENA)

        assert stran(odjemalec, quiz_id) == prej

    def test_tisk_neresenega_je_409(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=1)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=1)

        odgovor = odjemalec.get(f"/admin/quizzes/{quiz_id}/print")

        assert odgovor.status_code == 409
        assert "še ni rešen" in odgovor.text
        assert odgovor.headers["content-type"].startswith("text/html")

    def test_tisk_neznanega_je_404(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get("/admin/quizzes/ni-ga/print")

        assert odgovor.status_code == 404
        assert odgovor.headers["content-type"].startswith("text/html")


class TestSkupine:
    """Vprašanja po oceni, najtežja zgoraj, s številom v vsaki skupini."""

    def test_skupine_so_od_najtezje_navzdol(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(
            odjemalec, motor, slike, ["lahko", "nisem_vedela", "tezko", "srednje"]
        )

        besedilo = stran(odjemalec, quiz_id)

        naslovi = [besedilo.index(f"<h2>{oznaka} · ") for oznaka in
                   ("Nisem vedela", "Težko", "Srednje", "Lahko")]
        assert naslovi == sorted(naslovi)
        # Vprašanje 2 (nisem vedela) stoji pred vprašanjem 1 (lahko), čeprav
        # je v kvizu za njim.
        assert besedilo.index(vprasanje(2)) < besedilo.index(vprasanje(1))
        assert besedilo.index(vprasanje(3)) < besedilo.index(vprasanje(4))
        assert besedilo.index(vprasanje(4)) < besedilo.index(vprasanje(1))

    def test_stevilo_v_vsaki_skupini_tudi_nic(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko", "tezko", "lahko"])

        besedilo = stran(odjemalec, quiz_id)

        assert "<h2>Nisem vedela · 0 vprašanj</h2>" in besedilo
        assert "<h2>Težko · 2 vprašanji</h2>" in besedilo
        assert "<h2>Srednje · 0 vprašanj</h2>" in besedilo
        assert "<h2>Lahko · 1 vprašanje</h2>" in besedilo
        assert "Brez ocene" not in besedilo

    def test_znotraj_skupine_po_zaporedju_s_stevilko_v_kvizu(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(
            odjemalec, motor, slike, ["srednje", "tezko", "lahko", "srednje", "tezko"]
        )

        besedilo = stran(odjemalec, quiz_id)

        tezka = besedilo[besedilo.index("<h2>Težko") : besedilo.index("<h2>Srednje")]
        assert [int(st) for st, _ in OSTEVILCENO.findall(tezka)] == [2, 5]

    def test_pri_vsakem_vprasanju_je_odgovor(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko", "lahko", "srednje"])

        besedilo = stran(odjemalec, quiz_id)

        for i in (1, 2, 3):
            assert f"Odgovor {i}." in besedilo

    def test_bere_zamrznjeno_besedilo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko"])
        with Session(motor) as seja:
            najdeno = seja.get(Question, f"{UUID_ENA}-v1")
            assert najdeno is not None
            najdeno.question = "PODTAKNJENO"
            najdeno.answer = "PODTAKNJENO"
            seja.commit()

        besedilo = stran(odjemalec, quiz_id)

        assert vprasanje(1) in besedilo
        assert "Odgovor 1." in besedilo
        assert "PODTAKNJENO" not in besedilo

    def test_resen_nepreklican_kviz_se_da_preklicati(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Odločitev 2 v planu: rezultat gumba za preklic ne skrije."""
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko"])

        besedilo = stran(odjemalec, quiz_id)

        assert "Prekliči kviz" in besedilo
        assert f'action="/admin/quizzes/{quiz_id}/cancel"' in besedilo

    def test_pove_da_je_samoocena(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko"])

        assert "Mašina samoocena" in stran(odjemalec, quiz_id)

    def test_rezultat_ponudi_tisk(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko"])

        assert f'href="/admin/quizzes/{quiz_id}/print"' in stran(odjemalec, quiz_id)

    def test_neprepoznana_ocena_ne_izpade_molce(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Strežnik take ocene ne sprejme; če bi v bazi vseeno bila, je vidna."""
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko", "lahko"])
        with Session(motor) as seja:
            seja.execute(
                update(QuestionAttempt)
                .where(QuestionAttempt.rating == "lahko")
                .values(rating="neznana")
            )
            seja.commit()

        besedilo = stran(odjemalec, quiz_id)

        assert "<h2>Brez ocene · 1 vprašanje</h2>" in besedilo
        assert besedilo.index("<h2>Lahko") < besedilo.index("<h2>Brez ocene")
        assert vprasanje(2) in besedilo


class TestTrajanje:
    """Razmislek (pokazano → razkrito) in ocena (razkrito → ocenjeno)."""

    ZACETEK = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)

    @pytest.mark.parametrize(
        ("sekund", "pricakovano"),
        [
            (0, "0 s"),
            (59, "59 s"),
            (60, "1 min 0 s"),
            (65, "1 min 5 s"),
            (3600, "1 h 0 min"),
            (3725, "1 h 2 min"),
        ],
    )
    def test_oblike(self, sekund: int, pricakovano: str) -> None:
        assert trajanje(self.ZACETEK, self.ZACETEK + timedelta(seconds=sekund)) == pricakovano

    def test_delci_sekunde_se_odrezejo(self) -> None:
        assert trajanje(self.ZACETEK, self.ZACETEK + timedelta(seconds=59.9)) == "59 s"

    def test_negativno_je_pomisljaj(self) -> None:
        assert trajanje(self.ZACETEK, self.ZACETEK - timedelta(seconds=3)) == "—"

    def test_naiven_in_pasoven_cas(self) -> None:
        """SQLite vrne naiven čas; razume se kot UTC."""
        naiven = self.ZACETEK.replace(tzinfo=None)

        assert trajanje(naiven, self.ZACETEK + timedelta(seconds=14)) == "14 s"
        assert trajanje(self.ZACETEK, naiven + timedelta(seconds=14)) == "14 s"

    def test_na_strani(self, odjemalec: TestClient, motor: Engine, slike: Path) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=1)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=1)
        poslji(
            odjemalec,
            [
                poskus(
                    postavke(motor, quiz_id)[0],
                    rating="tezko",
                    shown_at=self.ZACETEK.isoformat(),
                    revealed_at=(self.ZACETEK + timedelta(seconds=14)).isoformat(),
                    answered_at=(self.ZACETEK + timedelta(seconds=16)).isoformat(),
                )
            ],
        )

        assert "razmislek 14 s · ocena 2 s" in stran(odjemalec, quiz_id)


class TestIzvor:
    """Povezava na sliko in prepis ali jasno sporočilo, zakaj je ni."""

    @staticmethod
    def _arhiviraj(motor: Engine, material_id: str = UUID_ENA) -> None:
        with Session(motor) as seja:
            seja.execute(
                update(Material)
                .where(Material.id == material_id)
                .values(archived_at=datetime.now(UTC))
            )
            seja.commit()

    def test_snov_obstaja(self, odjemalec: TestClient, motor: Engine, slike: Path) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko"])

        besedilo = stran(odjemalec, quiz_id)

        assert f'href="/admin/materials/{UUID_ENA}"' in besedilo
        assert "slika in prepis" in besedilo
        assert "v arhivu" not in besedilo
        assert "slike ni na disku" not in besedilo
        assert "ponovno obdelana" not in besedilo

    def test_snov_v_arhivu(self, odjemalec: TestClient, motor: Engine, slike: Path) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko"])
        self._arhiviraj(motor)

        besedilo = stran(odjemalec, quiz_id)

        assert f'href="/admin/materials/{UUID_ENA}"' in besedilo
        assert "v arhivu" in besedilo
        assert "počiščena" not in besedilo

    def test_arhiv_s_pociscena_sliko(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko"])
        self._arhiviraj(motor)
        (slike / CVEK_ID / f"{UUID_ENA}.jpg").unlink()

        besedilo = stran(odjemalec, quiz_id)

        assert f'href="/admin/materials/{UUID_ENA}"' in besedilo
        assert "v arhivu, slika počiščena — prepis je na strani snovi" in besedilo

    def test_aktivna_snov_brez_slike(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko"])
        (slike / CVEK_ID / f"{UUID_ENA}.jpg").unlink()

        besedilo = stran(odjemalec, quiz_id)

        assert "slike ni na disku" in besedilo
        assert "v arhivu" not in besedilo

    def test_slika_zunaj_mape_slik_ni_na_disku(
        self, odjemalec: TestClient, motor: Engine, slike: Path, tmp_path: Path
    ) -> None:
        """Isto pravilo kot v izbirniku: datoteka zunaj `images_dir` ne šteje."""
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko"])
        zunaj = tmp_path / "zunaj.jpg"
        zunaj.write_bytes(b"slika")
        with Session(motor) as seja:
            seja.execute(
                update(Material).where(Material.id == UUID_ENA).values(image_path=str(zunaj))
            )
            seja.commit()

        assert "slike ni na disku" in stran(odjemalec, quiz_id)

    def test_dokoncno_izbrisana_snov(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko"])
        with Session(motor) as seja:
            material = seja.get(Material, UUID_ENA)
            assert material is not None
            seja.delete(material)
            seja.commit()

        besedilo = stran(odjemalec, quiz_id)

        assert f'href="/admin/materials/{UUID_ENA}"' not in besedilo
        assert "izvorne slike ni več na strežniku" in besedilo
        assert vprasanje(1) in besedilo

    def test_ponovno_obdelana_snov(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko"])
        upokoji(motor, UUID_ENA)

        besedilo = stran(odjemalec, quiz_id)

        assert f'href="/admin/materials/{UUID_ENA}"' in besedilo
        assert "prepis na strani snovi je novejši od tega vprašanja" in besedilo


class TestPreklicanInResen:
    """Preklic ima prednost pri stanju; rezultat se vseeno pokaže (odl. 1)."""

    def test_preklic_na_vrhu_rezultat_pod_njim(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko"])
        odjemalec.post(f"/admin/quizzes/{quiz_id}/cancel", follow_redirects=False)

        besedilo = stran(odjemalec, quiz_id)

        assert "Kviz je preklican" in besedilo
        assert "Kviz je rešen" not in besedilo
        assert besedilo.index("Kviz je preklican") < besedilo.index("<h2>Težko")
        assert "Prekliči kviz" not in besedilo

    def test_tisk_preklicanega_in_resenega(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko"])
        odjemalec.post(f"/admin/quizzes/{quiz_id}/cancel", follow_redirects=False)

        assert vprasanje(1) in del_za_tisk(tisk(odjemalec, quiz_id))


class TestTisk:
    """Vprašanja brez odgovorov, prelom, ključ z istim oštevilčenjem."""

    OCENE = ("lahko", "tezko", "srednje", "nisem_vedela", "tezko")

    @staticmethod
    def _obkljukana(besedilo: str, koda: str) -> bool:
        zacetek = besedilo.index(f'value="{koda}"')
        element = besedilo[besedilo.rindex("<input", 0, zacetek) : besedilo.index(">", zacetek)]
        return "checked" in element

    def test_privzeto_nisem_vedela_in_tezko(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, self.OCENE)

        besedilo = tisk(odjemalec, quiz_id)
        papir = del_za_tisk(besedilo)

        for i in (2, 4, 5):
            assert vprasanje(i) in papir
        for i in (1, 3):
            assert vprasanje(i) not in papir
        assert self._obkljukana(besedilo, "nisem_vedela")
        assert self._obkljukana(besedilo, "tezko")
        assert not self._obkljukana(besedilo, "srednje")
        assert not self._obkljukana(besedilo, "lahko")

    def test_izbor_ocen(self, odjemalec: TestClient, motor: Engine, slike: Path) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, self.OCENE)

        besedilo = tisk(odjemalec, quiz_id, "?izbor=1&ocena=lahko")
        papir = del_za_tisk(besedilo)

        assert vprasanje(1) in papir
        for i in (2, 3, 4, 5):
            assert vprasanje(i) not in papir
        assert self._obkljukana(besedilo, "lahko")
        assert not self._obkljukana(besedilo, "tezko")

    def test_vse_odkljukano_ni_privzetek(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, self.OCENE)

        besedilo = tisk(odjemalec, quiz_id, "?izbor=1")

        assert 'class="tisk"' not in besedilo
        assert 'class="kljuc"' not in besedilo
        assert "ni kaj natisniti" in besedilo

    def test_nic_ne_ustreza(self, odjemalec: TestClient, motor: Engine, slike: Path) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, ["lahko", "srednje"])

        besedilo = tisk(odjemalec, quiz_id)

        assert 'class="kljuc"' not in besedilo
        assert "ni kaj natisniti" in besedilo

    def test_neznana_koda_se_prezre(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, self.OCENE)

        papir = del_za_tisk(tisk(odjemalec, quiz_id, "?izbor=1&ocena=xyz&ocena=tezko"))

        assert [besedilo for _, besedilo in OSTEVILCENO.findall(papir)][:2] == [
            vprasanje(2),
            vprasanje(5),
        ]

    def test_odgovori_so_samo_v_kljucu(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, self.OCENE)

        papir = del_za_tisk(tisk(odjemalec, quiz_id))
        meja = papir.index('<section class="kljuc">')

        for i in (2, 4, 5):
            assert f"Odgovor {i}." not in papir[:meja]
            assert f"Odgovor {i}." in papir[meja:]

    def test_isto_ostevilcenje_od_najtezje(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, self.OCENE)

        papir = del_za_tisk(tisk(odjemalec, quiz_id))
        meja = papir.index('<section class="kljuc">')
        vprasanja = OSTEVILCENO.findall(papir[:meja])
        kljuc = OSTEVILCENO.findall(papir[meja:])

        # Nisem vedela (4) pred težkima (2, 5), oštevilčeno znova od 1.
        assert vprasanja == [("1", vprasanje(4)), ("2", vprasanje(2)), ("3", vprasanje(5))]
        assert kljuc == vprasanja

    def test_na_papirju_ni_naslovov_skupin(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, self.OCENE)

        besedilo = tisk(odjemalec, quiz_id)
        papir = del_za_tisk(besedilo)

        assert "Nisem vedela" in besedilo  # v obrazcu za zaslon
        assert "Nisem vedela" not in papir
        assert "Težko" not in papir
        assert "razmislek" not in papir

    def test_prostor_za_odgovor(self, odjemalec: TestClient, motor: Engine, slike: Path) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, self.OCENE)

        papir = del_za_tisk(tisk(odjemalec, quiz_id))
        meja = papir.index('<section class="kljuc">')

        assert papir[:meja].count('<div class="prostor"></div>') == 3

    def test_slog_za_tisk(self, odjemalec: TestClient, motor: Engine, slike: Path) -> None:
        """Postavitve testi ne dokažejo; dokažejo le, da pravila obstajajo."""
        quiz_id = resen_kviz(odjemalec, motor, slike, self.OCENE)

        besedilo = tisk(odjemalec, quiz_id)
        slog = besedilo[besedilo.index("@media print") :]

        assert "header, .ne-tiskaj { display: none; }" in slog
        assert re.search(r"\.kljuc \{[^}]*break-before: page", slog)
        assert '<div class="ne-tiskaj">' in besedilo
        assert "Ctrl+P" in besedilo
        assert "<script" not in besedilo.lower()

    @staticmethod
    def _poslji_obrazec(
        odjemalec: TestClient, besedilo: str, obkljukaj: set[str]
    ) -> str:
        """Pošlje obrazec za izbor ocen, kot bi ga brskalnik.

        Vse — cilj, skrita polja, imena in vrednosti kljukic — se prebere iz
        **izrisa** in ne vtipka v test. Sicer bi test preverjal pot z URL-jem,
        ki ga je sestavil sam, obrazec pa bi se lahko pokvaril neopazno
        (pregled V2-R03, K1).
        """
        blok = besedilo[besedilo.index('<form method="get"') :]
        blok = blok[: blok.index("</form>")]
        akcija = re.search(r'action="([^"]+)"', blok)
        assert akcija is not None

        polja: list[tuple[str, str]] = []
        for vnos in re.findall(r"<input ([^>]*)>", blok):
            atributi = dict(re.findall(r'(\w+)="([^"]*)"', vnos))
            skrito = atributi.get("type") == "hidden"
            obkljukano = (
                atributi.get("type") == "checkbox" and atributi["value"] in obkljukaj
            )
            if skrito or obkljukano:
                polja.append((atributi["name"], atributi["value"]))

        # Tako, kot brskalnik zapiše obrazec `GET`: polja v naslovu, po vrsti.
        odgovor = odjemalec.get(f"{akcija.group(1)}?{urlencode(polja)}")
        assert odgovor.status_code == 200, odgovor.text
        return odgovor.text

    def test_obrazec_posreduje_izbrano_oceno(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, self.OCENE)

        besedilo = self._poslji_obrazec(odjemalec, tisk(odjemalec, quiz_id), {"lahko"})
        papir = del_za_tisk(besedilo)

        assert vprasanje(1) in papir
        for i in (2, 3, 4, 5):
            assert vprasanje(i) not in papir

    def test_obrazec_brez_kljukic_ni_privzetek(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Odkljukano vse mora ostati odkljukano, ne se vrniti v privzetek."""
        quiz_id = resen_kviz(odjemalec, motor, slike, self.OCENE)

        besedilo = self._poslji_obrazec(odjemalec, tisk(odjemalec, quiz_id), set())

        assert 'class="tisk"' not in besedilo
        assert "ni kaj natisniti" in besedilo
        assert not any(
            self._obkljukana(besedilo, koda)
            for koda in ("nisem_vedela", "tezko", "srednje", "lahko")
        )

    def test_tisk_bere_zamrznjeno_besedilo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Vprašanja in ključ iz postavke, ne iz `questions` (`ADR-016` E)."""
        quiz_id = resen_kviz(odjemalec, motor, slike, ["tezko"])
        with Session(motor) as seja:
            najdeno = seja.get(Question, f"{UUID_ENA}-v1")
            assert najdeno is not None
            najdeno.question = "PODTAKNJENO VPRAŠANJE"
            najdeno.answer = "PODTAKNJEN ODGOVOR"
            seja.commit()

        papir = del_za_tisk(tisk(odjemalec, quiz_id))

        assert vprasanje(1) in papir
        assert "Odgovor 1." in papir
        assert "PODTAKNJEN" not in papir

    def test_papir_nosi_ime_kviza(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        quiz_id = resen_kviz(odjemalec, motor, slike, self.OCENE)
        with Session(motor) as seja:
            kviz = seja.get(Quiz, quiz_id)
            assert kviz is not None
            ime = kviz.name

        papir = del_za_tisk(tisk(odjemalec, quiz_id))

        assert f"<h1>{ime}</h1>" in papir
        assert f"Ključ — {ime}" in papir


def stej_poizvedbe(motor: Engine, klic: Callable[[], object]) -> int:
    """Koliko stavkov je proti bazi opravil dani klic.

    Branje seje se ne šteje: od V3-R03 ga opravi `SejaMiddleware` pri **vsaki**
    zahtevi pod `/admin` in ni poizvedba strani, ki jo test meri
    (`docs/odlocitve/ADR-035` A). Njegovo ceno — natanko ena na zahtevo —
    varuje `test_druzine.py`.
    """
    stevec = 0

    def zabelezi(
        _povezava: object, _kazalec: object, stavek: str, *_ostalo: object
    ) -> None:
        nonlocal stevec
        if "sessions" not in stavek:
            stevec += 1

    event.listen(motor, "before_cursor_execute", zabelezi)
    try:
        klic()
    finally:
        event.remove(motor, "before_cursor_execute", zabelezi)
    return stevec


class TestPoizvedbe:
    """Rezultat ne sme brati poskusa ali snovi na postavko."""

    def test_rezultat_je_pet_poizvedb(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Družina pride iz seje in ne iz poizvedbe (V3-R03), branja seje pa
        # `stej_poizvedbe` ne šteje — obojega zato tu ni treba zamenjati.
        snov(motor, slike, UUID_ENA, vprasanj=10)
        snov(motor, slike, UUID_DVA, vprasanj=10)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA, UUID_DVA], koliko=10)
        poslji(odjemalec, [poskus(p, rating="tezko") for p in postavke(motor, quiz_id)])

        koliko = stej_poizvedbe(motor, lambda: odjemalec.get(f"/admin/quizzes/{quiz_id}"))

        assert koliko <= 5, f"rezultat je opravil {koliko} poizvedb"

    def test_nereseni_kviz_ne_placa_poizvedb_rezultata(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=3)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=3)
        nereseni = stej_poizvedbe(motor, lambda: odjemalec.get(f"/admin/quizzes/{quiz_id}"))

        poslji(odjemalec, [poskus(p, rating="tezko") for p in postavke(motor, quiz_id)])
        reseni = stej_poizvedbe(motor, lambda: odjemalec.get(f"/admin/quizzes/{quiz_id}"))

        # Poskusi in snovi: natanko dve več, obe samo pri rešenem.
        assert reseni == nereseni + 2
