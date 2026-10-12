"""Ogrodje spletnega pregleda: meni, števci in slog (V5-R01).

Odločitve so v `docs/odlocitve/ADR-056` (meni, tema, pisava) in `ADR-060`
(slog v datoteki, števci). Kako ogrodje **izgleda**, testi ne dokažejo — to je
ročni pregled v fazi 9b; dokažejo, kaj je v izrisu in v datoteki sloga.
"""

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, event, update
from sqlalchemy.orm import Session

from app import meni, prijava
from app.models import Material, Quiz
from app.routers.admin import MAPA_PREDLOG
from tests.conftest import (
    PrijavljenOdjemalec,
    je_seja,
    meni_strani,
    prijavi,
    slog_admina,
    slog_papirja,
    slog_zaslona,
    ustvari_starsa,
    vsebina_strani,
)
from tests.test_admin import UUID_DVA, UUID_ENA, zapisi
from tests.test_kvizi import objavi, snov


@pytest.fixture(autouse=True)
def _druzina_ima_otroka(otrok: str) -> str:
    """Družina Cvek ima otroka, kot na produkciji; brez njega kviza ni."""
    return otrok


@pytest.fixture
def lastnikov_odjemalec(aplikacija: FastAPI, motor: Engine) -> Iterator[PrijavljenOdjemalec]:
    lastnik = ustvari_starsa(
        motor,
        identifikator="lastnik@primer.test",
        prikazno_ime="Lastnik",
        lastnik_sistema=True,
    )
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
        prijavi(odjemalec, motor, lastnik)
        yield odjemalec


def postavke_menija(besedilo: str) -> list[tuple[str, str]]:
    """(naslov, oznaka) vsake postavke menija, v vrstnem redu izrisa."""
    seznam = meni_strani(besedilo)
    seznam = seznam[seznam.index('<ul class="meni-postavke">') : seznam.index("</ul>")]
    return re.findall(r'<a href="([^"]+)"[^>]*>\s*<span>([^<]+)</span>', seznam)


def stevec(besedilo: str, oznaka: str) -> str | None:
    """Števec ob postavki menija ali `None`, kadar ga ni."""
    najdeno = re.search(
        rf"<span>{re.escape(oznaka)}</span>\s*(?:<span class=\"meni-stevec\">(\d+)</span>)?",
        meni_strani(besedilo),
    )
    assert najdeno is not None, oznaka
    return najdeno.group(1)


#: Zamrznjeni podatki testov (slog izpred V5-R01).
MAPA_PODATKOV = Path(__file__).parent / "podatki"


class TestPravilaMenija:
    """`app/meni.py` — brez strežnika."""

    def test_postavke_in_vrstni_red_so_iz_dogovora(self) -> None:
        sestavljen = meni.sestavi_meni("/admin", lastnik_sistema=True, stevci=None)

        assert [p.oznaka for p in sestavljen.vsebina] == [
            "Predmeti",
            "Po dnevih",
            "Kvizi",
            "Testi",
            "Urnik",
            "Statistika",
        ]
        assert [p.oznaka for p in sestavljen.uprava] == ["Družina", "Arhiv", "Sistem"]

    def test_sistem_je_samo_za_lastnika_sistema(self) -> None:
        sestavljen = meni.sestavi_meni("/admin", lastnik_sistema=False, stevci=None)

        assert "Sistem" not in [p.oznaka for p in sestavljen.uprava]

    @pytest.mark.parametrize(
        ("pot", "izbrana"),
        [
            ("/admin", "Predmeti"),
            ("/admin/subjects/MAT", "Predmeti"),
            ("/admin/materials/abc", "Predmeti"),
            ("/admin/transcripts", "Predmeti"),
            ("/admin/days", "Po dnevih"),
            ("/admin/quizzes", "Kvizi"),
            ("/admin/quizzes/new", "Kvizi"),
            ("/admin/assessments/abc", "Testi"),
            ("/admin/schedule", "Urnik"),
            ("/admin/statistics/subjects/MAT", "Statistika"),
            ("/admin/family/members/x/password", "Družina"),
            ("/admin/archive", "Arhiv"),
            ("/admin/system/families/x", "Sistem"),
        ],
    )
    def test_izbrana_je_natanko_postavka_strani(self, pot: str, izbrana: str) -> None:
        sestavljen = meni.sestavi_meni(pot, lastnik_sistema=True, stevci=None)

        vse = sestavljen.vsebina + sestavljen.uprava
        assert [p.oznaka for p in vse if p.izbrana] == [izbrana]

    def test_pot_ki_se_le_zacne_enako_ni_izbrana(self) -> None:
        # Isto pravilo kot pri izvzetju iz žetona: `/admin/days` in
        # `/admin/days/…`, ne pa `/admin/daysabc`.
        sestavljen = meni.sestavi_meni("/admin/daysabc", lastnik_sistema=True, stevci=None)

        assert not any(p.izbrana for p in sestavljen.vsebina + sestavljen.uprava)

    def test_stevec_nic_se_ne_izrise(self) -> None:
        sestavljen = meni.sestavi_meni(
            "/admin",
            lastnik_sistema=False,
            stevci=meni.Stevci(slik=5, cakajocih_kvizov=0, testov=2, arhiviranih=0),
        )

        stevci = {p.oznaka: p.stevec for p in sestavljen.vsebina + sestavljen.uprava}
        assert stevci == {
            "Predmeti": 5,
            "Po dnevih": None,
            "Kvizi": None,
            "Testi": 2,
            "Urnik": None,
            "Statistika": None,
            "Družina": None,
            "Arhiv": None,
        }

    @pytest.mark.parametrize(
        ("pot", "brez"),
        [
            ("/admin/system", True),
            ("/admin/system/families/x", True),
            ("/admin/systematic", False),
            ("/admin", False),
            ("/admin/family", False),
        ],
    )
    def test_brez_stevcev_je_samo_pod_sistemom(self, pot: str, brez: bool) -> None:
        assert meni.je_brez_stevcev(pot) is brez

    @pytest.mark.parametrize(
        ("ime", "izpis"),
        [
            ("Cvek", "Družina Cvek"),
            ("  Novak ", "Družina Novak"),
            ("Družina Novak", "Družina Novak"),
            ("družina Kos", "družina Kos"),
        ],
    )
    def test_ime_druzine_se_ne_podvoji(self, ime: str, izpis: str) -> None:
        assert meni.ime_druzine(ime) == izpis

    def test_zacetnica(self) -> None:
        assert meni.zacetnica(" dejan ") == "D"
        assert meni.zacetnica("Žiga") == "Ž"
        assert meni.zacetnica("") == ""


class TestMeniVIzrisu:
    def test_meni_ima_postavke_iz_dogovora(self, odjemalec: PrijavljenOdjemalec) -> None:
        besedilo = odjemalec.get("/admin").text

        assert postavke_menija(besedilo) == [
            ("/admin", "Predmeti"),
            ("/admin/days", "Po dnevih"),
            ("/admin/quizzes", "Kvizi"),
            ("/admin/assessments", "Testi"),
            ("/admin/schedule", "Urnik"),
            ("/admin/statistics", "Statistika"),
            ("/admin/family", "Družina"),
            ("/admin/archive", "Arhiv"),
        ]

    def test_lastnik_sistema_vidi_se_sistem(
        self, lastnikov_odjemalec: PrijavljenOdjemalec
    ) -> None:
        besedilo = lastnikov_odjemalec.get("/admin").text

        assert postavke_menija(besedilo)[-1] == ("/admin/system", "Sistem")

    def test_izbrana_postavka_je_oznacena(self, odjemalec: PrijavljenOdjemalec) -> None:
        besedilo = meni_strani(odjemalec.get("/admin/days").text)

        assert re.findall(r'<a href="([^"]+)" aria-current="page"', besedilo) == ["/admin/days"]

    def test_meni_pove_druzino_osebo_vlogo_in_odjavo(
        self, odjemalec: PrijavljenOdjemalec
    ) -> None:
        besedilo = meni_strani(odjemalec.get("/admin").text)

        assert "Družina Cvek" in besedilo
        assert "Dejan" in besedilo
        assert '<span class="meni-vloga">starš</span>' in besedilo
        # Odjava je obrazec `POST` z žetonom v prvi vrstici, kot povsod.
        assert re.search(
            rf'<form method="post" action="{prijava.POT_ODJAVE}">\s*'
            r'<input type="hidden" name="csrf" value="[^"]+">',
            besedilo,
        )

    def test_meni_ni_del_vsebine_in_se_ne_tiska(self, odjemalec: PrijavljenOdjemalec) -> None:
        besedilo = odjemalec.get("/admin").text

        assert '<nav class="meni ne-tiskaj"' in besedilo
        assert "<nav" not in vsebina_strani(besedilo)

    def test_prijavna_stran_menija_nima(self, aplikacija: FastAPI, stars: str) -> None:
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brez_seje:
            besedilo = brez_seje.get(prijava.POT_PRIJAVE).text

        assert "<nav" not in besedilo
        assert '<body class="brez-menija prijavna">' in besedilo

    def test_stran_z_napako_ima_meni(self, odjemalec: PrijavljenOdjemalec) -> None:
        odgovor = odjemalec.get("/admin/tega-ni")

        assert odgovor.status_code == 404
        assert postavke_menija(odgovor.text)[0] == ("/admin", "Predmeti")


class TestStevci:
    def test_prazna_druzina_nima_nobenega_stevca(self, odjemalec: PrijavljenOdjemalec) -> None:
        besedilo = odjemalec.get("/admin").text

        assert "meni-stevec" not in besedilo

    def test_stevci_stejejo_slike_cakajoce_kvize_in_arhiv(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=2)
        snov(motor, slike, UUID_DVA, vprasanj=2)
        zapisi(motor, slike, "33333333-3333-4333-8333-333333333333")
        zapisi(motor, slike, "44444444-4444-4444-8444-444444444444")
        with Session(motor) as seja:
            seja.execute(
                update(Material)
                .where(Material.id == "44444444-4444-4444-8444-444444444444")
                .values(archived_at=datetime.now(UTC))
            )
            seja.commit()
        cakajoc = objavi(odjemalec, motor, [UUID_ENA], koliko=1)
        resen = objavi(odjemalec, motor, [UUID_DVA], koliko=1)
        preklican = objavi(odjemalec, motor, [UUID_ENA, UUID_DVA], koliko=1, vstop="rocna")
        with Session(motor) as seja:
            seja.execute(update(Quiz).where(Quiz.id == resen).values(solved_at=datetime.now(UTC)))
            seja.execute(
                update(Quiz).where(Quiz.id == preklican).values(canceled_at=datetime.now(UTC))
            )
            seja.commit()

        besedilo = odjemalec.get("/admin/days").text

        assert stevec(besedilo, "Predmeti") == "3"
        # Rešen in preklican ne čakata.
        assert stevec(besedilo, "Kvizi") == "1"
        assert stevec(besedilo, "Arhiv") == "1"
        assert stevec(besedilo, "Testi") is None
        assert cakajoc  # kviz, ki šteje

    def test_stevci_so_ena_poizvedba_na_stran(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        """Meni je na vsaki strani, zato sme stati eno poizvedbo, ne štirih."""
        zapisi(motor, slike)
        stavki: list[str] = []

        def zabelezi(_p: object, _k: object, stavek: str, *_ostalo: object) -> None:
            if not je_seja(stavek):
                stavki.append(stavek.lower())

        event.listen(motor, "before_cursor_execute", zabelezi)
        try:
            # Stran z napako sama ne bere ničesar: kar ostane, je meni.
            odjemalec.get("/admin/tega-ni")
        finally:
            event.remove(motor, "before_cursor_execute", zabelezi)

        assert len(stavki) == 1, stavki
        # Vsak od štirih podizrazov nosi pogoj družine.
        assert stavki[0].count("family_id") == 4

    def test_pod_sistemom_stevcev_ni_in_meni_ne_bere_nicesar(
        self, lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        """`ADR-060` F: lastnikove strani ne preberejo vsebine nobene družine."""
        zapisi(motor, slike)
        assert stevec(lastnikov_odjemalec.get("/admin").text, "Predmeti") == "1"
        stavki: list[str] = []

        def zabelezi(_p: object, _k: object, stavek: str, *_ostalo: object) -> None:
            stavki.append(stavek.lower())

        event.listen(motor, "before_cursor_execute", zabelezi)
        try:
            besedilo = lastnikov_odjemalec.get("/admin/system").text
        finally:
            event.remove(motor, "before_cursor_execute", zabelezi)

        assert "meni-stevec" not in besedilo
        assert postavke_menija(besedilo)[-1] == ("/admin/system", "Sistem")
        for stavek in stavki:
            for tabela in ("materials", "quizzes", "preizkusi", "questions"):
                assert tabela not in stavek, stavek


class TestOgrodjeVsakeStrani:
    #: Strani brez parametra v poti; ostale pokrijejo testi svojih zahtev.
    STRANI = (
        "/admin",
        "/admin/archive",
        "/admin/subjects/MAT",
        "/admin/days",
        "/admin/schedule",
        "/admin/statistics",
        "/admin/statistics/subjects/MAT",
        "/admin/family",
        "/admin/assessments",
        "/admin/quizzes/new?subject=MAT&vstop=rocna",
        "/admin/quizzes",
        "/admin/family?dodaj=otrok",
    )

    @pytest.mark.parametrize("pot", STRANI)
    def test_stran_ima_meni_in_slog_iz_datoteke(
        self, odjemalec: PrijavljenOdjemalec, pot: str
    ) -> None:
        odgovor = odjemalec.get(pot)

        assert odgovor.status_code == 200, pot
        povezava = '<link rel="stylesheet" href="/admin/static/admin/slog.css">'
        assert odgovor.text.count(povezava) == 1
        assert odgovor.text.count("<nav") == 1
        assert odgovor.text.count("<main>") == 1
        # Vgrajenega sloga ogrodje nima več (`ADR-060` A).
        assert "<style" not in odgovor.text

    def test_ogrodje_nima_vgrajenega_sloga_ne_skripte(self) -> None:
        osnova = (MAPA_PREDLOG / "osnova.html").read_text(encoding="utf-8").lower()

        assert "<style" not in osnova
        assert "<script" not in osnova
        assert " style=" not in osnova

    def test_tema_sledi_sistemu_brez_preklopa(self, odjemalec: PrijavljenOdjemalec) -> None:
        besedilo = odjemalec.get("/admin").text

        assert '<meta name="color-scheme" content="light dark">' in besedilo


class TestSlog:
    #: Žetoni iz `docs/poc/POC-02.md`, prepisani sem: (svetla, temna).
    ZETONI: ClassVar[dict[str, tuple[str, str]]] = {
        "ozadje": ("#eef1f4", "#12171d"),
        "ploskev": ("#ffffff", "#1a2129"),
        "ploskev-2": ("#f6f8fa", "#212a33"),
        "rob": ("#d7dde4", "#2e3944"),
        "besedilo": ("#17202b", "#e6ebf0"),
        "zamolklo": ("#586474", "#9aa6b4"),
        "poudarek": ("#2f5d50", "#7cc0a8"),
        "poudarek-mehko": ("#e3eeea", "#1f3530"),
        "nevarno": ("#a2402f", "#e38b79"),
        "nevarno-mehko": ("#f6e6e2", "#3a2420"),
        "opozorilo": ("#7a5a12", "#e2c27a"),
        "opozorilo-mehko": ("#f4ecd9", "#352c17"),
        "nalepka": ("#fffdf8", "#f3efe6"),
    }

    @staticmethod
    def _blok(slog: str, zacetek: str) -> str:
        """Besedilo bloka, ki se začne z `zacetek`, do ujemajočega zaklepaja."""
        od = slog.index(zacetek)
        globina = 0
        for mesto in range(slog.index("{", od), len(slog)):
            globina += {"{": 1, "}": -1}.get(slog[mesto], 0)
            if globina == 0:
                return slog[od : mesto + 1]
        raise AssertionError(zacetek)

    def test_svetli_zetoni_so_iz_dogovora(self) -> None:
        svetli = self._blok(slog_zaslona(), ":root {")

        for ime, (svetla, _temna) in self.ZETONI.items():
            assert f"--{ime}: {svetla};" in svetli, ime

    def test_temni_zetoni_so_iz_dogovora_in_vsak_ima_temno_razlicico(self) -> None:
        temni = self._blok(slog_zaslona(), "@media (prefers-color-scheme: dark)")

        for ime, (_svetla, temna) in self.ZETONI.items():
            assert f"--{ime}: {temna};" in temni, ime

    def test_temna_tema_velja_samo_za_zaslon(self) -> None:
        # Papir je svetel tudi pri temnem sistemu: zunaj dela za zaslon bi se
        # kviz natisnil s svetlim besedilom na belem listu.
        assert slog_admina().count("prefers-color-scheme") == 1
        assert slog_zaslona().count("@media (prefers-color-scheme: dark)") == 1

    def test_pisava_je_z_lastnega_streznika_v_stirih_rezah(self) -> None:
        slog = slog_admina()
        reze = re.findall(
            r'@font-face \{\s*font-family: "Atkinson Hyperlegible Next";\s*'
            r"font-weight: (\d+);[^}]*?src: url\(\"([^\"]+)\"\)",
            slog,
        )

        assert [teza for teza, _ in reze] == ["400", "500", "700", "800"]
        mapa = MAPA_PREDLOG.parent / "static" / "admin"
        for _teza, naslov in reze:
            # Relativen naslov, ki se razreši na datoteko v repozitoriju.
            assert (mapa / naslov).resolve().is_file(), naslov
        assert '"Atkinson Hyperlegible Next", system-ui' in slog

    def test_nobena_zahteva_ne_gre_na_zunanji_vir(self) -> None:
        slog = slog_admina()

        assert "@import" not in slog
        for naslov in re.findall(r"url\(([^)]+)\)", slog):
            assert naslov.strip("\"'").startswith("../pisave/"), naslov
        assert "//" not in re.sub(r"/\*.*?\*/", "", slog, flags=re.S)

    def test_predloge_ne_nalagajo_nicesar_od_zunaj(self) -> None:
        for pot in sorted(MAPA_PREDLOG.glob("*.html")):
            besedilo = pot.read_text(encoding="utf-8")
            # Vir, ki ga brskalnik naloži sam (slog, skripta, slika, pisava).
            # Navadna povezava `<a href>` na tujo stran ni zahteva strani.
            zunanji = re.findall(
                r'<(?:link|script|img|source|iframe)[^>]*?(?:src|href)="((?:https?:)?//[^"]*)"',
                besedilo,
            )
            assert zunanji == [], f"{pot.name}: {zunanji}"
            assert not re.search(r"url\(\s*[\"']?(?:https?:)?//", besedilo), pot.name

    def test_fokus_in_zmanjsano_gibanje(self) -> None:
        slog = slog_zaslona()

        assert re.search(r":focus-visible \{[^}]*outline: 3px solid", slog)
        assert "outline: none" not in slog and "outline: 0" not in slog
        assert "@media (prefers-reduced-motion: reduce)" in slog

    def test_locilo_telefona_je_860(self) -> None:
        assert "@media (max-width: 860px)" in slog_zaslona()

    def test_papir_je_dobesedno_slog_izpred_v5_r01(self) -> None:
        """`ADR-056` H: tisk se ne spremeni.

        Del za papir je cel slog, ki ga je ogrodje nosilo pred V5-R01, in
        nič drugega. Zamrznjena kopija je prepis `<style>` iz `osnova.html`
        na `main` tik pred to zahtevo; kdor jo popravi, spremeni papir.
        """
        zamrznjen = (MAPA_PODATKOV / "slog_pred_v5_r01.css").read_text(encoding="utf-8")

        assert slog_papirja().strip("\n") == zamrznjen.strip("\n")

    def test_nobeno_pravilo_ne_stoji_zunaj_zaslona_in_papirja(self) -> None:
        # Pravilo zunaj obeh delov bi veljalo povsod — tudi na papirju, ki se
        # po `ADR-056` H ne sme spremeniti. Zunaj sme samo pisava: `@font-face`
        # ničesar ne oblikuje, dokler ga pravilo ne uporabi.
        slog = re.sub(r"/\*.*?\*/", "", slog_admina(), flags=re.S)
        for del_sloga in (slog_zaslona(), slog_papirja()):
            brez_opomb = re.sub(r"/\*.*?\*/", "", del_sloga, flags=re.S)
            assert slog.count(brez_opomb) == 1
            slog = slog.replace(brez_opomb, "")
        slog = re.sub(r"@font-face \{[^}]*\}", "", slog)

        assert slog.split() == ["@media", "screen", "{}", "@media", "print", "{}"]

    def test_del_za_zaslon_nima_pravil_za_tisk(self) -> None:
        assert "print" not in slog_zaslona()

    @pytest.mark.parametrize("razred", ["oznaka", "znacka"])
    def test_oznaka_napake_ni_okvir_urejevalnika(self, razred: str) -> None:
        """Urejevalnik ima odstavek `.napaka` z okvirjem (`ADR-054`).

        Njegovo pravilo sme zadeti samo odstavek: oznaka in značka z razredom
        `napaka` sta majhni tableti in bi z njegovim odmikom in robom postali
        okvirja sredi vrstice.
        """
        slog = slog_zaslona()
        izbirniki = re.findall(r"(?m)^([^{}@/\n][^{}]*?)\s*\{", slog)
        okvirji = [i for i in izbirniki if ".napaka:not(.obvestilo)" in i]

        assert okvirji, "pravilo urejevalnika je izginilo"
        for izbirnik in okvirji:
            for del_izbirnika in izbirnik.split(","):
                if ".napaka" in del_izbirnika:
                    assert del_izbirnika.strip().startswith("p.napaka"), izbirnik
        assert re.search(rf"\.{razred}\.napaka \{{", slog)

    def test_list_a4_ostane_papir_tudi_na_zaslonu(self) -> None:
        # Po višini lista merilnik računa strani (`ADR-054`); splošna pravila
        # novega videza za naslove, povezave in prelom besed ga ne smejo doseči.
        slog = slog_zaslona()

        assert ".list { overflow-wrap: normal; font-variant-numeric: normal; }" in slog
        assert ".list h1, .list h2, .list h3, .list h4 { line-height: inherit; }" in slog
        naslovi = ".list h3, .list h4 { font-size: revert; font-weight: revert; margin: revert; }"
        assert naslovi in slog
        assert ".list a { color: revert; }" in slog

    def test_prijava_ne_stoji_na_has(self) -> None:
        # Postavitev prijavne strani nosi razred telesa; `:has()` sme biti samo
        # nadgradnja, brez katere stran še deluje.
        assert "body.prijavna main {" in slog_zaslona()
        assert not re.search(r"body[^{]*:has\(", slog_zaslona())
