"""Stran predmeta po tednih in razlogi praznih dni (V5-R01).

Odločitve so v `docs/odlocitve/ADR-060` C, D in E. Trije sloji: razvrstitev v
tedne (`app/tedni.py`), pravilo praznega dne (`app/urnik.py`) in izris strani.
Vsi testi strani tečejo na sredo, 16. 9. 2026 (`conftest.DAN_DOMACE_STRANI`).
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from app.db import ScheduleRepository
from app.tedni import ponedeljek_tedna, razvrsti_po_tednih, v_tednih
from app.urnik import (
    PRAZEN_BREZ_RAZLOGA,
    PRAZEN_MANJKA,
    PRAZEN_NI_NA_URNIKU,
    PRAZEN_SE_PRIDE,
    PrazenDan,
    Urnik,
    Vnos,
    prazen_dan_predmeta,
)
from tests.conftest import BRAT_ID, CVEK_ID, OTROK_ID, je_seja, vsebina_strani
from tests.test_dnevi import zapisi

LJUBLJANA = ZoneInfo("Europe/Ljubljana")
POT = "/admin/subjects/MAT"

#: Sreda, na katero `conftest` pritrdi današnji dan strani.
DANES = date(2026, 9, 16)
PON, TOR, SRE, CET, PET = 0, 1, 2, 3, 4


def lokalno(dan: date, ura: int = 10, minuta: int = 0) -> datetime:
    """Trenutek v domačem pasu, zapisan v UTC — kot ga pošlje telefon."""
    return datetime(dan.year, dan.month, dan.day, ura, minuta, tzinfo=LJUBLJANA).astimezone(UTC)


@pytest.fixture(autouse=True)
def _druzina_ima_otroka(otrok: str) -> str:
    return otrok


def potrdi_urnik(motor: Engine, otrok: str, *vnosi: Vnos) -> None:
    ScheduleRepository(Session(motor), CVEK_ID).potrdi(otrok, list(vnosi), None)


# --- Razvrstitev ---


class TestRazvrstitev:
    def test_najnovejsi_teden_je_prvi_in_prazen_teden_ne_nastane(self) -> None:
        tedni = razvrsti_po_tednih(
            [(date(2026, 9, 15), "c"), (date(2026, 9, 1), "a")]  # vmes je teden brez slik
        )

        assert [teden.ponedeljek for teden in tedni] == [date(2026, 9, 14), date(2026, 8, 31)]

    def test_teden_ima_pet_dni_tudi_brez_slik(self) -> None:
        [teden] = razvrsti_po_tednih([(date(2026, 9, 15), "a")])

        assert [dan.ime for dan in teden.dnevi] == ["Pon", "Tor", "Sre", "Čet", "Pet"]
        assert [len(dan.snovi) for dan in teden.dnevi] == [0, 1, 0, 0, 0]

    def test_vikend_dobi_stolpec_samo_s_sliko(self) -> None:
        [s_soboto] = razvrsti_po_tednih([(date(2026, 9, 19), "a")])
        [z_nedeljo] = razvrsti_po_tednih([(date(2026, 9, 20), "a")])

        assert [dan.ime for dan in s_soboto.dnevi][-1] == "Sob"
        # Samo dan s sliko: nedelja brez sobote.
        assert [dan.ime for dan in z_nedeljo.dnevi] == ["Pon", "Tor", "Sre", "Čet", "Pet", "Ned"]
        assert z_nedeljo.dnevi[-1].je_vikend

    def test_znotraj_dneva_od_najstarejse_naprej(self) -> None:
        # Vhod je od najnovejše navzdol, kot ga vrne `seznam_po_predmetu`.
        [teden] = razvrsti_po_tednih([(date(2026, 9, 15), "druga"), (date(2026, 9, 15), "prva")])

        assert teden.dnevi[TOR].snovi == ("prva", "druga")
        assert teden.stevilo == 2

    def test_nedelja_sodi_v_teden_ki_se_konca_z_njo(self) -> None:
        assert ponedeljek_tedna(date(2026, 9, 20)) == date(2026, 9, 14)
        assert ponedeljek_tedna(date(2026, 9, 21)) == date(2026, 9, 21)

    @pytest.mark.parametrize(
        ("dnevi", "razpon"),
        [
            ([date(2026, 10, 6)], "5.\u20139. oktober"),
            ([date(2026, 9, 29)], "28. september \u2013 2. oktober"),
            ([date(2026, 10, 10)], "5.\u201310. oktober"),
            ([date(2026, 12, 30)], "28. december \u2013 1. januar"),
        ],
    )
    def test_razpon(self, dnevi: list[date], razpon: str) -> None:
        [teden] = razvrsti_po_tednih([(dan, "a") for dan in dnevi])

        assert teden.razpon == razpon

    def test_oznaka_tedna(self) -> None:
        ta, prejsnji, starejsi = razvrsti_po_tednih(
            [(date(2026, 9, 15), "a"), (date(2026, 9, 8), "b"), (date(2026, 9, 1), "c")]
        )

        assert ta.oznaka(DANES) == "Ta teden"
        assert prejsnji.oznaka(DANES) == "Prejšnji teden"
        assert starejsi.oznaka(DANES) is None
        # V nedeljo je „ta teden" še vedno teden, ki se z njo konča.
        assert ta.oznaka(date(2026, 9, 20)) == "Ta teden"

    @pytest.mark.parametrize(
        ("koliko", "izpis"),
        [(1, "1 tednu"), (2, "2 tednih"), (5, "5 tednih"), (21, "21 tednih"), (101, "101 tednu")],
    )
    def test_tedni_v_mestniku(self, koliko: int, izpis: str) -> None:
        assert v_tednih(koliko) == izpis


# --- Pravilo praznega dne ---

MAT_V_PON = Urnik.iz_vnosov([Vnos(PON, "MAT"), Vnos(TOR, "SLJ")])
PONEDELJEK = date(2026, 9, 14)
TOREK = date(2026, 9, 15)


class TestPrazenDan:
    def test_brez_urnikov_ni_razloga(self) -> None:
        assert prazen_dan_predmeta("MAT", PONEDELJEK, DANES, {}, {"a"}) == PrazenDan(
            PRAZEN_BREZ_RAZLOGA
        )

    def test_predmeta_ta_dan_ni_na_urniku(self) -> None:
        izid = prazen_dan_predmeta("MAT", TOREK, DANES, {"a": MAT_V_PON}, {"a"})

        assert izid == PrazenDan(PRAZEN_NI_NA_URNIKU)

    def test_se_ne_slika_velja_kot_ni_na_urniku(self) -> None:
        urnik = Urnik.iz_vnosov([Vnos(PON, "MAT", se_ne_slika=True)])

        izid = prazen_dan_predmeta("MAT", PONEDELJEK, DANES, {"a": urnik}, {"a"})

        assert izid == PrazenDan(PRAZEN_NI_NA_URNIKU)

    def test_manjka_ko_je_otrok_ta_dan_poslikal_kaj_drugega(self) -> None:
        izid = prazen_dan_predmeta("MAT", PONEDELJEK, DANES, {"a": MAT_V_PON}, {"a"})

        assert izid == PrazenDan(PRAZEN_MANJKA, komu_manjka=("a",))

    def test_dan_brez_ene_same_slike_ni_manjko(self) -> None:
        """`ADR-028` E2: praznik in odsotnost nista manjko."""
        izid = prazen_dan_predmeta("MAT", PONEDELJEK, DANES, {"a": MAT_V_PON}, set())

        assert izid == PrazenDan(PRAZEN_BREZ_RAZLOGA)

    def test_slikanje_drugega_otroka_ne_sprozi_manjka(self) -> None:
        # Slikal je brat, ki predmeta ta dan nima; otrok, ki ga ima, ni slikal nič.
        urniki = {"a": MAT_V_PON, "b": Urnik.iz_vnosov([Vnos(TOR, "MAT")])}

        izid = prazen_dan_predmeta("MAT", PONEDELJEK, DANES, urniki, {"b"})

        assert izid == PrazenDan(PRAZEN_BREZ_RAZLOGA)

    def test_pri_vec_otrocih_manjka_tistim_ki_predmet_imajo_in_so_slikali(self) -> None:
        urniki = {"a": MAT_V_PON, "b": MAT_V_PON, "c": Urnik.iz_vnosov([Vnos(TOR, "MAT")])}

        izid = prazen_dan_predmeta("MAT", PONEDELJEK, DANES, urniki, {"b", "c"})

        assert izid == PrazenDan(PRAZEN_MANJKA, komu_manjka=("b",))

    @pytest.mark.parametrize("dan", [DANES, date(2026, 9, 17), date(2026, 9, 21)])
    def test_danes_in_prihodnji_dan_se_prideta(self, dan: date) -> None:
        urnik = Urnik.iz_vnosov([Vnos(d, "MAT") for d in (PON, SRE, CET)])

        # Tudi če je otrok danes že slikal kaj drugega: pouk še traja.
        izid = prazen_dan_predmeta("MAT", dan, DANES, {"a": urnik}, {"a"})

        assert izid == PrazenDan(PRAZEN_SE_PRIDE)

    def test_vceraj_ni_vec_se_pride(self) -> None:
        urnik = Urnik.iz_vnosov([Vnos(TOR, "MAT")])

        izid = prazen_dan_predmeta("MAT", TOREK, DANES, {"a": urnik}, {"a"})

        assert izid.stanje == PRAZEN_MANJKA

    def test_prihodnji_dan_brez_predmeta_ni_se_pride(self) -> None:
        # „Še pride" bi tu obljubil sliko, ki je urnik ne predvideva.
        izid = prazen_dan_predmeta("MAT", date(2026, 9, 18), DANES, {"a": MAT_V_PON}, set())

        assert izid == PrazenDan(PRAZEN_NI_NA_URNIKU)


# --- Stran ---


@dataclass(frozen=True)
class DanStrani:
    """En dan, kot ga izriše stran predmeta."""

    #: Razredi poleg `dan`: `danes-dan`, `prazen-dan` in stanje praznega dne.
    razredi: tuple[str, ...]
    glava: str
    slike: tuple[str, ...]
    obkljukane: tuple[str, ...]
    razlog: str | None

    @property
    def stanje(self) -> str | None:
        """Stanje praznega dne ali `None`, kadar dan ima slike."""
        return self.razredi[-1] if "prazen-dan" in self.razredi else None


def dnevi_strani(besedilo: str) -> list[DanStrani]:
    """Dnevi vseh tednov na strani, v vrstnem redu izrisa."""
    bloki = re.split(r'<div class="dan(?=[ "])', vsebina_strani(besedilo))[1:]
    dnevi = []
    for blok in bloki:
        glava = re.search(r'<h3 class="dan-glava">(.*?)</h3>', blok, re.S)
        assert glava is not None
        razlog = re.search(r'<p class="razlog">(.*?)</p>', blok, re.S)
        dnevi.append(
            DanStrani(
                razredi=tuple(blok[: blok.index('"')].split()),
                glava=" ".join(re.sub(r"<[^>]+>", " ", glava.group(1)).split()),
                slike=tuple(re.findall(r'name="snov" value="([^"]+)"', blok)),
                obkljukane=tuple(
                    re.findall(r'name="snov" value="([^"]+)"[^>]*\schecked>', blok)
                ),
                razlog=razlog.group(1).strip() if razlog else None,
            )
        )
    return dnevi


def dan_strani(besedilo: str, glava: str) -> DanStrani:
    [dan] = [dan for dan in dnevi_strani(besedilo) if dan.glava.startswith(glava)]
    return dan


def glave_tednov(besedilo: str) -> list[str]:
    return [
        " ".join(re.sub(r"<[^>]+>", " ", glava).split())
        for glava in re.findall(
            r'<header class="teden-glava">(.*?)<a class="izberi"', besedilo, re.S
        )
    ]


class TestStranPoTednih:
    def test_tedni_najnovejsi_prvi_prazen_teden_ni_izrisan(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, "ta", taken_at=lokalno(date(2026, 9, 15)))
        zapisi(motor, slike, "prejsnji", taken_at=lokalno(date(2026, 9, 8)))
        zapisi(motor, slike, "star-1", taken_at=lokalno(date(2026, 8, 25)))
        zapisi(motor, slike, "star-2", taken_at=lokalno(date(2026, 8, 25), 11))

        besedilo = odjemalec.get(POT).text

        # Teden od 31. 8. do 4. 9. nima slik in ga ni.
        assert glave_tednov(besedilo) == [
            "14.\u201318. september Ta teden 1 slika",
            "7.\u201311. september Prejšnji teden 1 slika",
            "24.\u201328. avgust 2 sliki",
        ]
        assert "4 slike v 3 tednih, najnovejši teden zgoraj." in besedilo

    def test_slika_je_pod_svojim_dnem_in_danes_je_oznacen(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, "torkova", taken_at=lokalno(date(2026, 9, 15)))
        zapisi(motor, slike, "danasnja", taken_at=lokalno(DANES))

        besedilo = odjemalec.get(POT).text

        assert dan_strani(besedilo, "Tor 15. 9.").slike == ("torkova",)
        danes = dan_strani(besedilo, "Sre 16. 9.")
        assert danes.slike == ("danasnja",)
        assert danes.glava == "Sre 16. 9. danes"
        assert "danes-dan" in danes.razredi
        assert "danes-dan" not in dan_strani(besedilo, "Tor 15. 9.").razredi

    def test_teden_se_lomi_ob_lokalni_polnoci(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Nedelja ob 22:30 UTC je v Ljubljani že ponedeljek ob 0:30.
        zapisi(motor, slike, "cez-polnoc", taken_at=datetime(2026, 9, 6, 22, 30, tzinfo=UTC))
        zapisi(motor, slike, "pred-polnocjo", taken_at=datetime(2026, 9, 6, 21, 30, tzinfo=UTC))

        besedilo = odjemalec.get(POT).text

        assert dan_strani(besedilo, "Pon 7. 9.").slike == ("cez-polnoc",)
        assert dan_strani(besedilo, "Ned 6. 9.").slike == ("pred-polnocjo",)

    def test_vikend_stolpec_samo_v_tednu_s_sobotno_sliko(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, "sobotna", taken_at=lokalno(date(2026, 9, 12)))
        zapisi(motor, slike, "torkova", taken_at=lokalno(date(2026, 9, 1)))

        besedilo = odjemalec.get(POT).text
        glave = [dan.glava[:3] for dan in dnevi_strani(besedilo)]

        delavniki = ["Pon", "Tor", "Sre", "Čet", "Pet"]
        assert glave == [*delavniki, "Sob", *delavniki]
        assert 'style="--stolpcev: 6"' in besedilo
        assert 'style="--stolpcev: 5"' in besedilo
        # Vikend dan praznega stanja nima; urnik ga ne pozna.
        assert dan_strani(besedilo, "Sob 12. 9.").razlog is None

    def test_arhivirana_slika_ni_na_strani(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, "vidna", taken_at=lokalno(date(2026, 9, 15)))
        zapisi(
            motor,
            slike,
            "arhivirana",
            taken_at=lokalno(date(2026, 9, 1)),
            arhivirano=datetime(2026, 9, 2, tzinfo=UTC),
        )

        besedilo = odjemalec.get(POT).text

        assert "arhivirana" not in besedilo
        assert len(glave_tednov(besedilo)) == 1


class TestPrazniDneviNaStrani:
    @pytest.fixture
    def teden(self, motor: Engine, slike: Path) -> None:
        """Slika v torek, da se teden od 14. do 18. 9. sploh izriše."""
        zapisi(motor, slike, "torkova", taken_at=lokalno(date(2026, 9, 15)))

    def test_brez_urnika_prazni_dnevi_nimajo_razloga(
        self, odjemalec: TestClient, teden: None
    ) -> None:
        dnevi = dnevi_strani(odjemalec.get(POT).text)

        assert [dan.razlog for dan in dnevi] == [None] * 5
        assert [dan.stanje for dan in dnevi] == [
            "brez-razloga",
            None,  # torek ima sliko
            "brez-razloga",
            "brez-razloga",
            "brez-razloga",
        ]

    def test_stiri_stanja_v_enem_tednu(
        self, odjemalec: TestClient, motor: Engine, slike: Path, teden: None
    ) -> None:
        # MAT je v pon, tor, čet in pet; v sredo ga ni.
        potrdi_urnik(motor, OTROK_ID, *(Vnos(dan, "MAT") for dan in (PON, TOR, CET, PET)))
        # Ponedeljek: slikal je slovenščino, matematike ne → manjka.
        zapisi(motor, slike, "slj", subject="SLJ", taken_at=lokalno(date(2026, 9, 14)))

        dnevi = dnevi_strani(odjemalec.get(POT).text)

        assert [(dan.stanje, dan.razlog) for dan in dnevi] == [
            ("manjka", "Po urniku je bil ta predmet, slik ni."),
            (None, None),  # torek ima sliko
            ("ni-na-urniku", "Ni na urniku."),
            ("se-pride", "Še pride."),
            ("se-pride", "Še pride."),
        ]

    def test_dan_brez_ene_same_slike_ni_rdec(
        self, odjemalec: TestClient, motor: Engine, teden: None
    ) -> None:
        """`ADR-028` E2 na strani predmeta: otrok v ponedeljek ni slikal ničesar."""
        potrdi_urnik(motor, OTROK_ID, Vnos(PON, "MAT"), Vnos(TOR, "MAT"))

        ponedeljek = dan_strani(odjemalec.get(POT).text, "Pon 14. 9.")

        assert ponedeljek.stanje == "brez-razloga"
        assert ponedeljek.razlog is None

    def test_arhivirana_slika_drugega_predmeta_ne_steje_kot_slikanje(
        self, odjemalec: TestClient, motor: Engine, slike: Path, teden: None
    ) -> None:
        potrdi_urnik(motor, OTROK_ID, Vnos(PON, "MAT"), Vnos(TOR, "MAT"))
        zapisi(
            motor,
            slike,
            "slj-arhiv",
            subject="SLJ",
            taken_at=lokalno(date(2026, 9, 14)),
            arhivirano=datetime(2026, 9, 15, tzinfo=UTC),
        )

        assert dan_strani(odjemalec.get(POT).text, "Pon 14. 9.").stanje == "brez-razloga"

    def test_slikanje_drugega_predmeta_steje_k_lokalnemu_dnevu(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Slovenščina v nedeljo ob 22:30 UTC je v Ljubljani ponedeljek ob 0:30:
        # otrok je **v ponedeljek** slikal nekaj drugega, zato matematika
        # tisti dan manjka. Po dnevu v UTC bi bil ponedeljek brez razloga.
        potrdi_urnik(motor, OTROK_ID, Vnos(PON, "MAT"), Vnos(TOR, "MAT"))
        zapisi(motor, slike, "mat-tor", taken_at=lokalno(date(2026, 9, 8)))
        zapisi(
            motor,
            slike,
            "slj-cez-polnoc",
            subject="SLJ",
            taken_at=datetime(2026, 9, 6, 22, 30, tzinfo=UTC),
        )

        assert dan_strani(odjemalec.get(POT).text, "Pon 7. 9.").stanje == "manjka"

    def test_danasnji_dan_je_se_pride_tudi_ce_je_otrok_ze_slikal_drugo(
        self, odjemalec: TestClient, motor: Engine, slike: Path, teden: None
    ) -> None:
        potrdi_urnik(motor, OTROK_ID, Vnos(SRE, "MAT"), Vnos(TOR, "MAT"))
        zapisi(motor, slike, "slj-danes", subject="SLJ", taken_at=lokalno(DANES))

        assert dan_strani(odjemalec.get(POT).text, "Sre 16. 9.").razlog == "Še pride."

    def test_se_ne_slika_je_ni_na_urniku(
        self, odjemalec: TestClient, motor: Engine, slike: Path, teden: None
    ) -> None:
        potrdi_urnik(motor, OTROK_ID, Vnos(PON, "MAT", se_ne_slika=True), Vnos(TOR, "MAT"))
        zapisi(motor, slike, "slj", subject="SLJ", taken_at=lokalno(date(2026, 9, 14)))

        assert dan_strani(odjemalec.get(POT).text, "Pon 14. 9.").razlog == "Ni na urniku."

    def test_pri_enem_otroku_razlog_nima_imena(
        self, odjemalec: TestClient, motor: Engine, slike: Path, teden: None
    ) -> None:
        potrdi_urnik(motor, OTROK_ID, Vnos(PON, "MAT"), Vnos(TOR, "MAT"))
        zapisi(motor, slike, "slj", subject="SLJ", taken_at=lokalno(date(2026, 9, 14)))

        besedilo = odjemalec.get(POT).text

        assert "Maša" not in vsebina_strani(besedilo)

    def test_pri_dveh_otrocih_je_ime_vrednost_pred_besedilom(
        self, odjemalec: TestClient, motor: Engine, slike: Path, teden: None, brat: str
    ) -> None:
        # Oba imata matematiko v ponedeljek; slovenščino je slikal samo Nejc.
        potrdi_urnik(motor, OTROK_ID, Vnos(PON, "MAT"), Vnos(TOR, "MAT"))
        potrdi_urnik(motor, BRAT_ID, Vnos(PON, "MAT"))
        zapisi(
            motor,
            slike,
            "slj-nejc",
            subject="SLJ",
            taken_at=lokalno(date(2026, 9, 14)),
            child_id=BRAT_ID,
        )

        razlog = dan_strani(odjemalec.get(POT).text, "Pon 14. 9.").razlog

        # `ADR-039` F3: ime za ločilom, nikoli za predlogom. Maši ne manjka —
        # tisti dan ni slikala ničesar (E2).
        assert razlog == "Nejc · po urniku je bil ta predmet, slik ni."

    def test_urnik_enega_otroka_zadosca_da_je_dan_na_urniku(
        self, odjemalec: TestClient, motor: Engine, teden: None, brat: str
    ) -> None:
        potrdi_urnik(motor, OTROK_ID, Vnos(TOR, "MAT"))
        potrdi_urnik(motor, BRAT_ID, Vnos(CET, "MAT"))

        besedilo = odjemalec.get(POT).text

        assert dan_strani(besedilo, "Čet 17. 9.").razlog == "Še pride."
        assert dan_strani(besedilo, "Pet 18. 9.").razlog == "Ni na urniku."

    def test_predmet_brez_slik_ne_bere_urnikov(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        potrdi_urnik(motor, OTROK_ID, Vnos(PON, "MAT"))
        stavki: list[str] = []

        def zabelezi(_p: object, _k: object, stavek: str, *_ostalo: object) -> None:
            if not je_seja(stavek):
                stavki.append(stavek.lower())

        event.listen(motor, "before_cursor_execute", zabelezi)
        try:
            odgovor = odjemalec.get(POT)
        finally:
            event.remove(motor, "before_cursor_execute", zabelezi)

        assert "še ni nobene slike" in odgovor.text
        assert not any("schedule" in stavek for stavek in stavki)


class TestIzborTednaInDneva:
    @pytest.fixture
    def dva_tedna(self, motor: Engine, slike: Path) -> None:
        zapisi(motor, slike, "pon-1", taken_at=lokalno(date(2026, 9, 14), 9))
        zapisi(motor, slike, "pon-2", taken_at=lokalno(date(2026, 9, 14), 10))
        zapisi(motor, slike, "tor", taken_at=lokalno(date(2026, 9, 15)))
        zapisi(motor, slike, "prej", taken_at=lokalno(date(2026, 9, 8)))

    def obkljukane(self, besedilo: str) -> list[str]:
        return [slika for dan in dnevi_strani(besedilo) for slika in dan.obkljukane]

    def test_povezavi_sta_na_isto_stran_s_parametrom(
        self, odjemalec: TestClient, dva_tedna: None
    ) -> None:
        besedilo = odjemalec.get(POT).text

        assert f'<a class="izberi" href="{POT}?teden=2026-09-14">Izberi teden</a>' in besedilo
        assert f'<a class="izberi" href="{POT}?dan=2026-09-14">Izberi dan</a>' in besedilo
        # Prazen dan nima česa izbrati.
        assert f'href="{POT}?dan=2026-09-16"' not in besedilo

    def test_izberi_teden_obkljuka_natanko_slike_tedna(
        self, odjemalec: TestClient, dva_tedna: None
    ) -> None:
        besedilo = odjemalec.get(f"{POT}?teden=2026-09-14").text

        assert self.obkljukane(besedilo) == ["pon-1", "pon-2", "tor"]

    def test_izberi_dan_obkljuka_natanko_slike_dneva(
        self, odjemalec: TestClient, dva_tedna: None
    ) -> None:
        besedilo = odjemalec.get(f"{POT}?dan=2026-09-14").text

        assert self.obkljukane(besedilo) == ["pon-1", "pon-2"]

    @pytest.mark.parametrize(
        "poizvedba",
        [
            "?teden=2026-09-15",
            "?teden=vse",
            "?dan=2026-09-16",
            "?dan=14.9.2026",
            "?teden=",
            "?dan=",
        ],
    )
    def test_vrednost_ki_je_stran_ne_izrise_ne_obkljuka_nicesar(
        self, odjemalec: TestClient, dva_tedna: None, poizvedba: str
    ) -> None:
        # Teden se imenuje po ponedeljku; torek ni ime nobenega tedna.
        assert "checked" not in odjemalec.get(f"{POT}{poizvedba}").text

    def test_izberi_vse_se_vedno_obkljuka_vse(
        self, odjemalec: TestClient, dva_tedna: None
    ) -> None:
        assert len(self.obkljukane(odjemalec.get(f"{POT}?vse=1").text)) == 4


class TestSlicica:
    def test_ura_in_stanje_samo_kadar_ni_obdelano(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        from app.models import Material

        zapisi(motor, slike, "caka", taken_at=lokalno(date(2026, 9, 15), 9, 5))
        zapisi(motor, slike, "obdelana", taken_at=lokalno(date(2026, 9, 15), 9, 6))
        zapisi(motor, slike, "neberljiva", taken_at=lokalno(date(2026, 9, 15), 9, 7))
        with Session(motor) as seja:
            for ime, berljiva in (("obdelana", True), ("neberljiva", False)):
                zapis = seja.get(Material, ime)
                assert zapis is not None
                zapis.status, zapis.readable = "ready", berljiva
            seja.commit()

        besedilo = odjemalec.get(POT).text

        znacke = re.findall(
            r'<span class="znacka (\w+)" title="([^"]+)">([^<]+)</span>', besedilo
        )
        assert znacke == [
            ("caka", "čaka na obdelavo", "čaka"),
            ("napaka", "obdelano — slika ni berljiva", "ni berljiva"),
        ]
        ure = re.findall(r'<span class="cas">([^<]+)</span>', besedilo)
        assert ure == ["09:05", "09:06", "09:07"]

    def test_ime_otroka_na_slicici_samo_pri_vec_otrocih(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, "edina", taken_at=lokalno(date(2026, 9, 15)))

        assert '<span class="otrok">' not in odjemalec.get(POT).text

    def test_vrstica_izbora_steje_brez_skripte(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        from tests.conftest import slog_admina

        zapisi(motor, slike, "edina", taken_at=lokalno(date(2026, 9, 15)))

        besedilo = odjemalec.get(POT).text
        slog = slog_admina()

        assert "<script" not in besedilo.lower()
        assert '<span class="stevilo-izbranih"></span>' in besedilo
        assert 'input[name="snov"]:checked { counter-increment: izbranih; }' in slog
        # Brez `:has()` vrstica ostane vidna: skrije jo samo brskalnik, ki ga zna.
        skrije = 'form:not(:has(input[name="snov"]:checked)) .vrstica-izbora { display: none; }'
        znotraj = re.search(r"@supports selector\(:has\(\*\)\) \{(.*?)\n\}", slog, re.S)
        assert znotraj is not None
        assert skrije in znotraj.group(1)
        assert slog.count(skrije) == 1
