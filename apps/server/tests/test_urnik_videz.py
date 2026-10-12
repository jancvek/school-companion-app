"""Urnik po V5-R01: teden na pogled, razlike pri predlogu in slika urnika.

Kar je urnik znal že prej (mreža, predlog, potrditev, manjki), varuje
`test_urnik.py`. Tu je novo vedenje iz `docs/poc/POC-02.md` in
`docs/odlocitve/ADR-060` G.
"""

import io
import json
import re
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db import ScheduleRepository
from app.routers.urnik import SPOROCILO_NI_SLIKE_URNIKA, teden_na_pogled
from app.storage import mapa_urnikov
from app.urnik import Urnik, Vnos, razlike
from app.vision import PredlogUrnika, razcleni_urnik
from tests.conftest import BRAT_ID, CVEK_ID, OTROK_ID, TUJA_DRUZINA_ID, vsebina_strani
from tests.test_urnik import POT_PREDLOGA, SLIKA, odjemalec_s_klicalcem

POT = "/admin/schedule"
PON, TOR, SRE, CET, PET = 0, 1, 2, 3, 4


@pytest.fixture(autouse=True)
def _druzina_ima_otroka(otrok: str) -> str:
    return otrok


@pytest.fixture
def sklad() -> Iterator[ExitStack]:
    """Zapre vse, kar test odpre (odjemalca s podtaknjenim klicalcem)."""
    with ExitStack() as odprto:
        yield odprto


def potrdi(motor: Engine, otrok: str, *vnosi: Vnos, slika: str | None = None) -> None:
    ScheduleRepository(Session(motor), CVEK_ID).potrdi(otrok, list(vnosi), slika)


def predlog(*celice: tuple[str, str | None]) -> PredlogUrnika:
    """Predlog modela iz parov (dan, koda); `None` je nepreslikana celica."""
    return razcleni_urnik(
        json.dumps(
            {
                "readable": True,
                "cells": [
                    {"day": dan, "text": koda or "ŠPO", "subject": koda} for dan, koda in celice
                ],
            }
        )
    )


def naloz(odjemalec: TestClient, otrok: str, csrf: str) -> str:
    odgovor = odjemalec.post(
        POT_PREDLOGA,
        data={"csrf": csrf, "otrok": otrok},
        files={"slika": ("urnik.png", io.BytesIO(SLIKA), "image/png")},
    )
    assert odgovor.status_code == 200
    return str(odgovor.text)


def spremenjene(besedilo: str) -> set[str]:
    """Imena polj celic, ki so v mreži označene kot spremenjene."""
    return set(re.findall(r'<td class="spremenjena">\s*<select name="(c\d_[A-Z]+)"', besedilo))


class TestRazlike:
    VELJAVEN = Urnik.iz_vnosov([Vnos(PON, "MAT"), Vnos(TOR, "SLJ"), Vnos(SRE, "LUM", True)])

    def test_enak_urnik_nima_razlik(self) -> None:
        assert razlike(self.VELJAVEN, self.VELJAVEN) == frozenset()

    def test_dodana_odstranjena_in_spremenjena_celica(self) -> None:
        nov = Urnik.iz_vnosov(
            [
                Vnos(PON, "MAT"),  # ostane
                Vnos(CET, "GEO"),  # dodana
                Vnos(SRE, "LUM"),  # „se ne slika" → „se slika"
            ]  # torkova SLJ je odstranjena
        )

        assert razlike(nov, self.VELJAVEN) == {(CET, "GEO"), (SRE, "LUM"), (TOR, "SLJ")}

    def test_brez_veljavnega_urnika_razlik_ni(self) -> None:
        # Vse je novo; pika na vsaki celici ne bi povedala ničesar.
        assert razlike(self.VELJAVEN, None) == frozenset()


class TestTedenNaPogled:
    def test_predmeti_po_dnevih_v_vrstnem_redu_urnika(self) -> None:
        urnik = Urnik.iz_vnosov([Vnos(PON, "SLJ"), Vnos(PON, "NAR"), Vnos(SRE, "LUM", True)])

        teden = teden_na_pogled(urnik, danasnji=SRE)

        assert [dan["ime"] for dan in teden] == ["Ponedeljek", "Torek", "Sreda", "Četrtek", "Petek"]
        # `PREDMETI` in ne abeceda ali vrstni red vnosa: NAR pred SLJ.
        assert [p["koda"] for p in teden[PON]["predmeti"]] == ["NAR", "SLJ"]
        assert teden[PON]["predmeti"][0]["barva"] == "#3d7856"
        assert teden[SRE]["predmeti"] == [
            {
                "koda": "LUM",
                "oznaka": "Likovna umetnost",
                "barva": "#6f55a0",
                "se_ne_slika": True,
            }
        ]
        assert [dan["je_danes"] for dan in teden] == [False, False, True, False, False]

    def test_ob_vikendu_ni_oznacen_noben_dan(self) -> None:
        teden = teden_na_pogled(Urnik.iz_vnosov([Vnos(PON, "MAT")]), danasnji=5)

        assert not any(dan["je_danes"] for dan in teden)

    def test_brez_urnika_ni_tedna(self) -> None:
        assert teden_na_pogled(None, danasnji=PON) == []


class TestStran:
    def test_potrjen_urnik_ima_teden_na_pogled_in_zlozeno_mrezo(
        self, aplikacija: FastAPI, motor: Engine, stars: str, sklad: ExitStack
    ) -> None:
        potrdi(motor, OTROK_ID, Vnos(PON, "MAT"), Vnos(SRE, "LUM", se_ne_slika=True))
        odjemalec = sklad.enter_context(
            odjemalec_s_klicalcem(aplikacija, motor, stars, lambda _: predlog())
        )

        besedilo = odjemalec.get(POT).text

        assert "<strong>Urnik je potrjen</strong> od " in besedilo
        assert '<section class="teden urnik-teden"' in besedilo
        assert re.search(r'<span class="cip">MAT</span>\s*<span>\s*Matematika', besedilo)
        assert re.search(
            r'<li class="se-ne-slika"[^>]*>\s*<span class="cip crtkan">LUM</span>.*?se ne slika',
            besedilo,
            re.S,
        )
        # Mreža je na strani, a zložena: `details` brez `open`.
        assert '<details class="kartica urnik-uredi" id="uredi">' in besedilo

    def test_brez_urnika_je_mreza_odprta_in_stran_pove_kaj_narediti(
        self, odjemalec: TestClient
    ) -> None:
        besedilo = odjemalec.get(POT).text

        assert "<strong>Urnika še ni.</strong>" in besedilo
        assert "urnik-teden" not in besedilo
        assert '<details class="kartica urnik-uredi" id="uredi" open>' in besedilo

    def test_polja_mreze_so_nespremenjena(self, odjemalec: TestClient, motor: Engine) -> None:
        """`ADR-056` I: imena in vrednosti polj ostanejo, barvo da slog."""
        potrdi(motor, OTROK_ID, Vnos(PON, "MAT"), Vnos(TOR, "GUM", se_ne_slika=True))

        besedilo = odjemalec.get(POT).text

        assert len(re.findall(r'<select name="c[0-4]_[A-Z]{3}"', besedilo)) == 50
        assert re.search(
            r'<select name="c0_MAT".*?<option value="da"\s+selected>je</option>', besedilo, re.S
        )
        assert re.search(
            r'<select name="c1_GUM".*?<option value="brez"\s+selected>se ne slika</option>',
            besedilo,
            re.S,
        )
        assert '<form method="post" action="/admin/schedule">' in besedilo
        assert '<tr style="--barva: #2d5a8e">' in besedilo
        assert "<script" not in besedilo.lower()

    def test_zavihki_otrok_so_povezave_in_samo_pri_vec_otrocih(
        self, odjemalec: TestClient, brat: str
    ) -> None:
        besedilo = odjemalec.get(f"{POT}?otrok={BRAT_ID}").text
        zacetek = besedilo.index('<ul class="zavihki" aria-label="Otrok">')
        zavihki = besedilo[zacetek : besedilo.index("</ul>", zacetek)]

        assert re.findall(r'<a href="([^"]+)"( aria-current="true")?>([^<]+)</a>', zavihki) == [
            (f"{POT}?otrok={OTROK_ID}", "", "Maša"),
            (f"{POT}?otrok={BRAT_ID}", ' aria-current="true"', "Nejc"),
        ]
        # Brez obrazca z gumbom „Pokaži".
        assert '<select name="otrok">' not in besedilo

    def test_en_otrok_nima_zavihkov_in_imena(self, odjemalec: TestClient) -> None:
        vsebina = vsebina_strani(odjemalec.get(POT).text)

        assert 'aria-label="Otrok"' not in vsebina
        assert "Maša" not in vsebina


class TestRazlikeVPredlogu:
    def test_oznacene_so_natanko_celice_ki_se_razlikujejo(
        self, aplikacija: FastAPI, motor: Engine, stars: str, sklad: ExitStack
    ) -> None:
        potrdi(motor, OTROK_ID, Vnos(PON, "MAT"), Vnos(TOR, "SLJ"))
        odjemalec = sklad.enter_context(
            odjemalec_s_klicalcem(
                aplikacija, motor, stars, lambda _: predlog(("pon", "MAT"), ("cet", "GEO"))
            )
        )

        besedilo = naloz(odjemalec, OTROK_ID, odjemalec.csrf)

        # Ponedeljkova matematika ostane; četrtkova geografija je nova,
        # torkova slovenščina izgine.
        assert spremenjene(besedilo) == {"c3_GEO", "c1_SLJ"}
        assert "označene s piko" in besedilo
        assert 'aria-label="GEO, četrtek, spremenjeno"' in besedilo
        assert "Urnik s slike je prebran, a še ni shranjen." in besedilo
        # Predlog ni potrjen urnik: tedna na pogled tu ni, mreža je odprta.
        assert "urnik-teden" not in besedilo
        assert '<details class="kartica urnik-uredi" id="uredi" open>' in besedilo

    def test_brez_veljavnega_urnika_ni_oznacena_nobena(
        self, aplikacija: FastAPI, motor: Engine, stars: str, sklad: ExitStack
    ) -> None:
        odjemalec = sklad.enter_context(
            odjemalec_s_klicalcem(aplikacija, motor, stars, lambda _: predlog(("pon", "MAT")))
        )

        besedilo = naloz(odjemalec, OTROK_ID, odjemalec.csrf)

        assert spremenjene(besedilo) == set()
        assert "označene s piko" not in besedilo

    def test_predlog_enak_urniku_nima_pik(
        self, aplikacija: FastAPI, motor: Engine, stars: str, sklad: ExitStack
    ) -> None:
        potrdi(motor, OTROK_ID, Vnos(PON, "MAT"))
        odjemalec = sklad.enter_context(
            odjemalec_s_klicalcem(aplikacija, motor, stars, lambda _: predlog(("pon", "MAT")))
        )

        assert spremenjene(naloz(odjemalec, OTROK_ID, odjemalec.csrf)) == set()


class TestSlikaUrnika:
    def test_predlog_pokaze_pravkar_nalozeno_sliko(
        self, aplikacija: FastAPI, motor: Engine, stars: str, sklad: ExitStack
    ) -> None:
        odjemalec = sklad.enter_context(
            odjemalec_s_klicalcem(aplikacija, motor, stars, lambda _: predlog(("pon", "MAT")))
        )

        besedilo = naloz(odjemalec, OTROK_ID, odjemalec.csrf)
        [slika_id] = re.findall(r'name="slika_id" value="([^"]+)"', besedilo)

        assert f'<img src="{POT}/image/{slika_id}"' in besedilo
        odgovor = odjemalec.get(f"{POT}/image/{slika_id}")
        assert odgovor.status_code == 200
        assert odgovor.content == SLIKA
        # Datoteka je shranjena kot `.jpg`; vrsto pove vsebina.
        assert odgovor.headers["content-type"] == "image/png"

    def test_potrjen_urnik_pokaze_sliko_iz_katere_je_nastal(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        slika_id = str(uuid4())
        mapa = mapa_urnikov(slike, CVEK_ID)
        mapa.mkdir(parents=True, exist_ok=True)
        (mapa / f"{slika_id}.jpg").write_bytes(b"\xff\xd8\xff jpeg")
        potrdi(motor, OTROK_ID, Vnos(PON, "MAT"), slika=str(mapa / f"{slika_id}.jpg"))

        besedilo = odjemalec.get(POT).text

        assert f'<img src="{POT}/image/{slika_id}"' in besedilo
        assert "Iz te slike je nastal potrjeni urnik." in besedilo
        assert odjemalec.get(f"{POT}/image/{slika_id}").headers["content-type"] == "image/jpeg"

    def test_natipkan_urnik_in_urnik_z_izgubljeno_sliko_kartice_nimata(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        potrdi(motor, OTROK_ID, Vnos(PON, "MAT"))
        assert "Prebrana slika" not in odjemalec.get(POT).text

        izgubljena = mapa_urnikov(slike, CVEK_ID) / f"{uuid4()}.jpg"
        potrdi(motor, OTROK_ID, Vnos(PON, "MAT"), slika=str(izgubljena))
        assert "Prebrana slika" not in odjemalec.get(POT).text

    @pytest.mark.parametrize(
        "slika_id",
        ["ni-uuid", "main.py", "00000000-0000-4000-8000-000000000000"],
    )
    def test_neveljaven_ali_neobstojec_id_je_404(
        self, odjemalec: TestClient, slika_id: str
    ) -> None:
        odgovor = odjemalec.get(f"{POT}/image/{slika_id}")

        assert odgovor.status_code == 404
        assert SPOROCILO_NI_SLIKE_URNIKA in odgovor.text

    def test_pot_iz_mape_ne_uide(self, odjemalec: TestClient) -> None:
        # S poševnico v naslovu poti sploh ni; odgovor je 404 in nič drugega.
        odgovor = odjemalec.get(f"{POT}/image/..%2F..%2Fmain")

        assert odgovor.status_code == 404

    def test_slika_tuje_druzine_je_404_z_istim_besedilom(
        self, odjemalec: TestClient, slike: Path
    ) -> None:
        slika_id = str(uuid4())
        tuja = mapa_urnikov(slike, TUJA_DRUZINA_ID)
        tuja.mkdir(parents=True, exist_ok=True)
        (tuja / f"{slika_id}.jpg").write_bytes(b"tuja slika urnika")

        odgovor = odjemalec.get(f"{POT}/image/{slika_id}")

        assert odgovor.status_code == 404
        assert SPOROCILO_NI_SLIKE_URNIKA in odgovor.text
        assert b"tuja slika urnika" not in odgovor.content

    def test_brez_seje_pelje_na_prijavo(self, aplikacija: FastAPI, stars: str) -> None:
        from tests.conftest import PrijavljenOdjemalec

        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brez_seje:
            odgovor = brez_seje.get(f"{POT}/image/{uuid4()}", follow_redirects=False)

        assert odgovor.status_code == 303
