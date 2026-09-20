"""Testi urnika in manjkov (V3-R09).

Pokrivajo tabelo „Test casi" iz `docs/plan/V3-R09.md`. Štiri plasti, vsaka v
svojem razredu in vsaka preizkušena tam, kjer pravilo res živi:

- **pravila** (`app/urnik.py`) — čiste funkcije, brez baze in brez izrisa;
- **branje odgovora modela** (`app/vision.py`) — čista funkcija nad nizom;
- **repozitorij** (`ScheduleRepository`) — zamenjava kot ena transakcija;
- **poti** (`/admin/schedule`) — obrazec, predlog, potrditev, zavrnitve.

Manjki na `/admin/days` so v `tests/test_dnevi.py`, kjer je že vse, kar tisto
stran postavi: tam se dokaže tudi, da otrok brez urnika vidi stran natanko
tako kot pred to zahtevo.
"""

import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db import ScheduleRepository
from app.main import POTI_S_SVOJIM_CSRF
from app.models import Material, Question, Schedule
from app.routers.urnik import POT_PREDLOGA, PREDPONA, ime_polja
from app.urnik import DNEVI, Urnik, Vnos, manjkajoci_predmeti
from app.vision import NapakaObdelave, PredlogUrnika, razcleni_urnik
from tests.conftest import CVEK_ID, PrijavljenOdjemalec

PON, TOR, SRE, CET, PET = DNEVI

#: Enopikselni PNG. Vsebina ni pomembna — klicalec je v testih namestnik —,
#: pomembno je, da gre skozi `multipart` kot prava datoteka.
SLIKA = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def urnik(*vnosi: Vnos) -> Urnik:
    """Urnik iz naštetih vnosov."""
    return Urnik.iz_vnosov(vnosi)


def je(dan: int, predmet: str) -> Vnos:
    """Predmet je ta dan na urniku in se slika."""
    return Vnos(dan=dan, predmet=predmet)


def ne_slika(dan: int, predmet: str) -> Vnos:
    """Predmet je ta dan na urniku, a se ne slika (`ADR-028` F2)."""
    return Vnos(dan=dan, predmet=predmet, se_ne_slika=True)


class TestPravilaManjkov:
    """`manjkajoci_predmeti`: kdaj manjko nastane in kdaj ne."""

    def test_delno_poslikan_dan_nasteje_ostale(self) -> None:
        manjki = manjkajoci_predmeti(
            urnik(je(PON, "MAT"), je(PON, "SLJ"), je(PON, "TJA")), PON, ["MAT"]
        )

        assert manjki == ("TJA", "SLJ")

    def test_vrstni_red_je_po_predmetih_in_ne_po_abecedi(self) -> None:
        """`PREDMETI` gre `NAR, MAT, TJA, GEO, SLJ, …` — abeceda bi dala drugo."""
        manjki = manjkajoci_predmeti(
            urnik(je(SRE, "SLJ"), je(SRE, "MAT"), je(SRE, "NAR")), SRE, ["GEO"]
        )

        assert manjki == ("NAR", "MAT", "SLJ")

    def test_dan_brez_ene_same_slike_nima_manjkov(self) -> None:
        """`ADR-028` E2: sicer je vsak praznik vrstica s petimi manjki."""
        manjki = manjkajoci_predmeti(urnik(je(PON, "MAT"), je(PON, "SLJ")), PON, [])

        assert manjki == ()

    def test_brez_urnika_ni_manjkov(self) -> None:
        assert manjkajoci_predmeti(None, PON, ["MAT"]) == ()

    def test_predmet_ki_se_ne_slika_ne_javlja_manjka(self) -> None:
        manjki = manjkajoci_predmeti(
            urnik(je(PON, "MAT"), ne_slika(PON, "LUM")), PON, ["MAT"]
        )

        assert manjki == ()

    def test_ista_zastavica_velja_po_dnevih_in_ne_po_predmetu(self) -> None:
        """`ADR-028` F2: `se_ne_slika` je lastnost **vnosa**, ne predmeta."""
        tedenski = urnik(je(PON, "MAT"), ne_slika(PON, "LUM"), je(SRE, "LUM"), je(SRE, "MAT"))

        assert manjkajoci_predmeti(tedenski, PON, ["MAT"]) == ()
        assert manjkajoci_predmeti(tedenski, SRE, ["MAT"]) == ("LUM",)

    def test_poslikan_predmet_zunaj_urnika_se_ne_javlja(self) -> None:
        """Urnik je pričakovanje, ne pravilo — in manjka tudi ne zapre."""
        manjki = manjkajoci_predmeti(urnik(je(PON, "MAT"), je(PON, "SLJ")), PON, ["GEO"])

        assert manjki == ("MAT", "SLJ")

    def test_vse_poslikano_nima_manjkov(self) -> None:
        manjki = manjkajoci_predmeti(urnik(je(PON, "MAT"), je(PON, "SLJ")), PON, ["MAT", "SLJ"])

        assert manjki == ()

    def test_dan_brez_urnika_nima_manjkov(self) -> None:
        """Sobota in nedelja obstajata v koledarju, na urniku pa ne."""
        assert manjkajoci_predmeti(urnik(je(PON, "MAT")), 5, ["GEO"]) == ()
        assert manjkajoci_predmeti(urnik(je(PON, "MAT")), TOR, ["GEO"]) == ()

    def test_dve_uri_istega_predmeta_zahtevata_eno_sliko(self) -> None:
        """Urnik je množica: podvojen vnos ne nastane in ne šteje dvakrat."""
        dvakrat = urnik(je(PON, "MAT"), je(PON, "MAT"))

        assert dvakrat.predmeti_dneva(PON) == ("MAT",)
        assert manjkajoci_predmeti(dvakrat, PON, ["MAT"]) == ()

    def test_ob_podvojitvi_obvelja_oznaceni_vnos(self) -> None:
        """„Ta dan se ne slika" je izjema, ki jo je starš postavil namenoma."""
        assert urnik(je(PON, "LUM"), ne_slika(PON, "LUM")).predmeti_dneva(PON) == ()
        assert urnik(ne_slika(PON, "LUM"), je(PON, "LUM")).predmeti_dneva(PON) == ()


class TestBranjePredloga:
    """`razcleni_urnik`: kaj sprejmemo od modela."""

    def odgovor(self, **polja: object) -> str:
        privzeto: dict[str, object] = {"readable": True, "cells": []}
        return json.dumps({**privzeto, **polja})

    def test_prebere_celice_in_preslika_kode(self) -> None:
        predlog = razcleni_urnik(
            self.odgovor(
                cells=[
                    {"day": "pon", "text": "Matematika", "subject": "MAT"},
                    {"day": "pet", "text": "Slovenščina", "subject": "SLJ"},
                ]
            )
        )

        assert predlog.readable is True
        assert [(c.dan, c.koda) for c in predlog.celice] == [(PON, "MAT"), (PET, "SLJ")]

    def test_koda_se_prebere_ne_glede_na_velikost_crk(self) -> None:
        predlog = razcleni_urnik(
            self.odgovor(cells=[{"day": "tor", "text": "mat", "subject": " mat "}])
        )

        assert predlog.celice[0].koda == "MAT"

    def test_neznana_koda_ostane_nepreslikana_in_ne_izpade(self) -> None:
        """Kriterij `V3-R09`: celica se staršu pokaže in ne izpade molče."""
        predlog = razcleni_urnik(
            self.odgovor(cells=[{"day": "tor", "text": "Šport", "subject": "SPO"}])
        )

        assert predlog.celice[0].koda is None
        assert predlog.nepreslikane == predlog.celice
        assert predlog.nepreslikane[0].besedilo == "Šport"

    def test_prazen_subject_je_nepreslikana_celica(self) -> None:
        predlog = razcleni_urnik(
            self.odgovor(cells=[{"day": "sre", "text": "Kosilo", "subject": ""}])
        )

        assert predlog.nepreslikane[0].besedilo == "Kosilo"

    def test_neberljiv_urnik_s_celicami_je_napaka(self) -> None:
        """Isto sklepanje kot pri vprašanjih: ne vemo, kateri polovici verjeti."""
        with pytest.raises(NapakaObdelave):
            razcleni_urnik(
                self.odgovor(
                    readable=False,
                    cells=[{"day": "pon", "text": "MAT", "subject": "MAT"}],
                )
            )

    def test_neberljiv_urnik_brez_celic_je_v_redu(self) -> None:
        assert razcleni_urnik(self.odgovor(readable=False)).readable is False

    def test_neveljaven_json_je_napaka_s_slovenskim_sporocilom(self) -> None:
        with pytest.raises(NapakaObdelave) as napaka:
            razcleni_urnik("{ni json")

        assert "JSON" in napaka.value.sporocilo

    def test_neznan_dan_je_napaka(self) -> None:
        """Šesti stolpec urnika ne sme priti skozi (`ADR-041` F)."""
        with pytest.raises(NapakaObdelave):
            razcleni_urnik(
                self.odgovor(cells=[{"day": "sob", "text": "MAT", "subject": "MAT"}])
            )


class TestRepozitorij:
    """`ScheduleRepository`: veljavnost, zamenjava, meja družine."""

    def repo(self, motor: Engine, family_id: str = CVEK_ID) -> ScheduleRepository:
        return ScheduleRepository(Session(motor), family_id)

    def test_brez_urnika_vrne_none(self, motor: Engine, otrok: str) -> None:
        assert self.repo(motor).urnik(otrok) is None

    def test_potrditev_zapise_vnose(self, motor: Engine, otrok: str) -> None:
        self.repo(motor).potrdi(otrok, [je(PON, "MAT"), ne_slika(PON, "LUM")], None)

        zapisan = self.repo(motor).urnik(otrok)
        assert zapisan is not None
        assert zapisan.predmeti_dneva(PON) == ("MAT",)
        assert manjkajoci_predmeti(zapisan, PON, ["GEO"]) == ("MAT",)

    def test_nov_urnik_prejsnjega_upokoji_in_ne_izbrise(
        self, motor: Engine, otrok: str
    ) -> None:
        """`ADR-041` C: „nič se ne briše, vse se upokoji" velja tudi tu."""
        self.repo(motor).potrdi(otrok, [je(PON, "MAT")], None)
        self.repo(motor).potrdi(otrok, [je(PON, "SLJ")], None)

        with Session(motor) as seja:
            vsi = list(seja.scalars(select(Schedule).where(Schedule.child_id == otrok)))
            veljavni = [zapis for zapis in vsi if zapis.replaced_at is None]

        assert len(vsi) == 2, "star urnik se ne sme izbrisati"
        assert len(veljavni) == 1, "veljaven je vedno en sam"
        assert self.repo(motor).urnik(otrok).predmeti_dneva(PON) == ("SLJ",)

    def test_urnik_je_last_otroka_in_ne_druzine(
        self, motor: Engine, otrok: str, brat: str
    ) -> None:
        self.repo(motor).potrdi(otrok, [je(PON, "MAT")], None)
        self.repo(motor).potrdi(brat, [je(PON, "SLJ")], None)

        assert self.repo(motor).urnik(otrok).predmeti_dneva(PON) == ("MAT",)
        assert self.repo(motor).urnik(brat).predmeti_dneva(PON) == ("SLJ",)

    def test_tuj_otrok_ne_dobi_urnika(
        self, motor: Engine, otrok: str, tuj_otrok: str
    ) -> None:
        """Izolacija je lastnost kode (`ADR-025`), ne le usmerjevalnika."""
        assert self.repo(motor).potrdi(tuj_otrok, [je(PON, "MAT")], None) is None

        with Session(motor) as seja:
            assert seja.scalars(select(Schedule)).all() == []

    def test_veljavnost_odloca_os_in_ne_vrstni_red(
        self, motor: Engine, otrok: str
    ) -> None:
        """`replaced_at IS NULL` je **edino**, kar določa veljaven urnik.

        Ta test je nastal iz mutacijskega preizkusa: brez njega je bila
        odstranitev pogoja `replaced_at IS NULL` iz `veljaven` neopažena, ker
        razvrstitev po `confirmed_at DESC` navadno vrne pravega tudi brez
        filtra. „Navadno" pa ni jamstvo, in tu se to vidi črno na belem:
        `potrdi` da staremu urniku `replaced_at` in novemu `confirmed_at`
        **isti trenutek**, zato razvrstitev med njima sploh ne loči in odloča
        naključni UUID v drugem ključu.

        Vrstica se zato postavi na roko in ne skozi `potrdi`: upokojen urnik s
        **poznejšim** časom potrditve je stanje, ki ga pot ne ustvari, bralec
        pa ga mora vseeno pravilno presoditi.
        """
        self.repo(motor).potrdi(otrok, [je(PON, "MAT")], None)

        with Session(motor) as seja:
            seja.add(
                Schedule(
                    id="upokojen-a-novejsi",
                    family_id=CVEK_ID,
                    child_id=otrok,
                    confirmed_at=datetime(2099, 1, 1, tzinfo=UTC),
                    replaced_at=datetime(2099, 1, 2, tzinfo=UTC),
                    image_path=None,
                )
            )
            seja.commit()

        veljaven = self.repo(motor).veljaven(otrok)
        assert veljaven is not None
        assert veljaven.id != "upokojen-a-novejsi"
        assert self.repo(motor).urnik(otrok).predmeti_dneva(PON) == ("MAT",)

    def test_slika_se_zapise_kadar_je(self, motor: Engine, otrok: str) -> None:
        self.repo(motor).potrdi(otrok, [je(PON, "MAT")], "/data/images/x/urniki/y.jpg")

        with Session(motor) as seja:
            zapis = seja.scalars(select(Schedule)).one()
        assert zapis.image_path == "/data/images/x/urniki/y.jpg"

    def test_natipkan_urnik_nima_slike(self, motor: Engine, otrok: str) -> None:
        """`None` ni manjkajoč podatek, ampak resnica o nastanku (`ADR-041` E)."""
        self.repo(motor).potrdi(otrok, [je(PON, "MAT")], None)

        with Session(motor) as seja:
            assert seja.scalars(select(Schedule)).one().image_path is None


class TestStranUrnika:
    """`GET /admin/schedule` in `POST /admin/schedule`."""

    def polja(self, **celice: str) -> dict[str, str]:
        """Mreža kot jo odda brskalnik: `ime_polja` → vrednost."""
        return {ime_polja(dan, koda): vrednost for (dan, koda), vrednost in celice.items()}  # type: ignore[misc]

    def test_stran_pokaze_mrezo_vseh_desetih_predmetov(
        self, odjemalec: PrijavljenOdjemalec, otrok: str
    ) -> None:
        odgovor = odjemalec.get(PREDPONA)

        assert odgovor.status_code == 200
        for koda in ("NAR", "MAT", "TJA", "GEO", "SLJ", "LUM", "ZGO", "TIT", "DKE", "GUM"):
            assert ime_polja(PON, koda) in odgovor.text

    def test_mreza_je_urejljiva_tudi_brez_slike(
        self, odjemalec: PrijavljenOdjemalec, otrok: str
    ) -> None:
        """`ADR-041` E — kriterij, ki je razširil prvotni obseg."""
        odgovor = odjemalec.post(
            PREDPONA,
            data={"otrok": otrok, ime_polja(PON, "MAT"): "da"},
            follow_redirects=False,
        )

        assert odgovor.status_code == 303
        with Session(odjemalec.app.state.motor) as seja:  # type: ignore[attr-defined]
            assert seja.scalars(select(Schedule)).one().image_path is None

    def test_potrditev_je_celotna_zamenjava_in_ne_krpanje(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str
    ) -> None:
        odjemalec.post(
            PREDPONA,
            data={"otrok": otrok, ime_polja(PON, "MAT"): "da", ime_polja(PON, "SLJ"): "da"},
        )
        odjemalec.post(PREDPONA, data={"otrok": otrok, ime_polja(PON, "SLJ"): "da"})

        zapisan = ScheduleRepository(Session(motor), CVEK_ID).urnik(otrok)
        assert zapisan is not None
        assert zapisan.predmeti_dneva(PON) == ("SLJ",), "MAT je moral izpasti"

    def test_zastavica_se_ne_slika_pride_skozi_obrazec(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str
    ) -> None:
        odjemalec.post(
            PREDPONA,
            data={"otrok": otrok, ime_polja(PON, "MAT"): "da", ime_polja(PON, "LUM"): "brez"},
        )

        zapisan = ScheduleRepository(Session(motor), CVEK_ID).urnik(otrok)
        assert zapisan is not None
        assert zapisan.predmeti_dneva(PON) == ("MAT",)
        assert manjkajoci_predmeti(zapisan, PON, ["GEO"]) == ("MAT",)

    def test_neznana_koda_je_400_in_ne_spremeni_nicesar(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str
    ) -> None:
        odgovor = odjemalec.post(PREDPONA, data={"otrok": otrok, "c0_SPO": "da"})

        assert odgovor.status_code == 400
        assert "SPO" in odgovor.text
        assert ScheduleRepository(Session(motor), CVEK_ID).urnik(otrok) is None

    def test_neznan_dan_je_400_in_ne_spremeni_nicesar(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str
    ) -> None:
        odgovor = odjemalec.post(PREDPONA, data={"otrok": otrok, "c9_MAT": "da"})

        assert odgovor.status_code == 400
        assert ScheduleRepository(Session(motor), CVEK_ID).urnik(otrok) is None

    def test_tuj_otrok_je_404_z_istim_besedilom_kot_neobstojec(
        self, odjemalec: PrijavljenOdjemalec, otrok: str, tuj_otrok: str
    ) -> None:
        tuji = odjemalec.get(PREDPONA, params={"otrok": tuj_otrok})
        izmisljen = odjemalec.get(PREDPONA, params={"otrok": "ni-tak-id"})

        assert tuji.status_code == izmisljen.status_code == 404
        assert "Tega otroka v tvoji družini ni." in tuji.text
        assert "Tega otroka v tvoji družini ni." in izmisljen.text

    def test_potrditev_za_tujega_otroka_ne_zapise_nicesar(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str, tuj_otrok: str
    ) -> None:
        odgovor = odjemalec.post(
            PREDPONA, data={"otrok": tuj_otrok, ime_polja(PON, "MAT"): "da"}
        )

        assert odgovor.status_code == 404
        with Session(motor) as seja:
            assert seja.scalars(select(Schedule)).all() == []

    def test_izbirnika_pri_enem_otroku_ni(
        self, odjemalec: PrijavljenOdjemalec, otrok: str
    ) -> None:
        """`ADR-039` F3: ime otroka se pri enem otroku ne izriše nikjer."""
        odgovor = odjemalec.get(PREDPONA)

        assert "Maša" not in odgovor.text

    def test_pri_dveh_otrocih_je_izbirnik(
        self, odjemalec: PrijavljenOdjemalec, otrok: str, brat: str
    ) -> None:
        odgovor = odjemalec.get(PREDPONA)

        assert "Maša" in odgovor.text
        assert "Nejc" in odgovor.text

    def test_csrf_zeton_je_obvezen(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str
    ) -> None:
        odgovor = odjemalec.post(
            PREDPONA, data={"csrf": "", "otrok": otrok, ime_polja(PON, "MAT"): "da"}
        )

        assert odgovor.status_code == 403
        with Session(motor) as seja:
            assert seja.scalars(select(Schedule)).all() == []


class TestPredlogSSlike:
    """`POST /admin/schedule/proposal` — nalaganje in branje slike."""

    def naredi_odjemalec(
        self, aplikacija: FastAPI, motor: Engine, stars: str, klicalec: object
    ) -> PrijavljenOdjemalec:
        """Odjemalec nad aplikacijo, ki ima podtaknjenega klicalca urnika."""
        from tests.conftest import prijavi

        aplikacija.state.klicalec_urnika = klicalec
        odjemalec = PrijavljenOdjemalec(aplikacija, base_url="https://testserver")
        odjemalec.__enter__()
        prijavi(odjemalec, motor, stars)
        return odjemalec

    def naloz(self, odjemalec: PrijavljenOdjemalec, otrok: str) -> object:
        return odjemalec.post(
            POT_PREDLOGA,
            data={"csrf": odjemalec.csrf, "otrok": otrok},
            files={"slika": ("urnik.png", io.BytesIO(SLIKA), "image/png")},
        )

    def test_prebrani_predmeti_pridejo_v_mrezo(
        self, aplikacija: FastAPI, motor: Engine, stars: str, otrok: str
    ) -> None:
        def klicalec(_: Path) -> PredlogUrnika:
            return razcleni_urnik(
                json.dumps(
                    {
                        "readable": True,
                        "cells": [{"day": "pon", "text": "Matematika", "subject": "MAT"}],
                    }
                )
            )

        odjemalec = self.naredi_odjemalec(aplikacija, motor, stars, klicalec)
        odgovor = self.naloz(odjemalec, otrok)

        assert odgovor.status_code == 200  # type: ignore[attr-defined]
        # Celica ponedeljek/MAT je izbrana; ostale ostanejo prazne.
        assert 'name="slika_id"' in odgovor.text  # type: ignore[attr-defined]

    def test_predlog_sam_ne_zapise_urnika(
        self, aplikacija: FastAPI, motor: Engine, stars: str, otrok: str
    ) -> None:
        """Nepotrjen predlog ne sproži manjka, ker vrstice sploh ni."""

        def klicalec(_: Path) -> PredlogUrnika:
            return razcleni_urnik(
                json.dumps(
                    {
                        "readable": True,
                        "cells": [{"day": "pon", "text": "MAT", "subject": "MAT"}],
                    }
                )
            )

        odjemalec = self.naredi_odjemalec(aplikacija, motor, stars, klicalec)
        self.naloz(odjemalec, otrok)

        with Session(motor) as seja:
            assert seja.scalars(select(Schedule)).all() == []

    def test_nepreslikane_celice_se_izpisejo(
        self, aplikacija: FastAPI, motor: Engine, stars: str, otrok: str
    ) -> None:
        def klicalec(_: Path) -> PredlogUrnika:
            return razcleni_urnik(
                json.dumps(
                    {
                        "readable": True,
                        "cells": [{"day": "tor", "text": "Šport", "subject": ""}],
                    }
                )
            )

        odjemalec = self.naredi_odjemalec(aplikacija, motor, stars, klicalec)
        odgovor = self.naloz(odjemalec, otrok)

        assert "Šport" in odgovor.text  # type: ignore[attr-defined]
        assert "torek" in odgovor.text  # type: ignore[attr-defined]

    def test_neuspel_klic_pove_kaj_narediti_in_pusti_urnik_pri_miru(
        self, aplikacija: FastAPI, motor: Engine, stars: str, otrok: str
    ) -> None:
        ScheduleRepository(Session(motor), CVEK_ID).potrdi(otrok, [je(PON, "MAT")], None)

        def klicalec(_: Path) -> PredlogUrnika:
            raise NapakaObdelave("Model se ni odzval v 120 sekundah.")

        odjemalec = self.naredi_odjemalec(aplikacija, motor, stars, klicalec)
        odgovor = self.naloz(odjemalec, otrok)

        assert odgovor.status_code == 200  # type: ignore[attr-defined]
        assert "Model se ni odzval" in odgovor.text  # type: ignore[attr-defined]
        zapisan = ScheduleRepository(Session(motor), CVEK_ID).urnik(otrok)
        assert zapisan is not None
        assert zapisan.predmeti_dneva(PON) == ("MAT",), "prejšnji urnik mora ostati cel"

    def test_neberljiva_slika_pove_kaj_narediti(
        self, aplikacija: FastAPI, motor: Engine, stars: str, otrok: str
    ) -> None:
        def klicalec(_: Path) -> PredlogUrnika:
            return PredlogUrnika(readable=False, celice=())

        odjemalec = self.naredi_odjemalec(aplikacija, motor, stars, klicalec)
        odgovor = self.naloz(odjemalec, otrok)

        assert "ni bilo mogoče brati" in odgovor.text  # type: ignore[attr-defined]

    def test_neuspel_klic_ne_pusti_slike_na_disku(
        self, aplikacija: FastAPI, motor: Engine, stars: str, otrok: str, slike: Path
    ) -> None:
        def klicalec(_: Path) -> PredlogUrnika:
            raise NapakaObdelave("Klic ni uspel.")

        odjemalec = self.naredi_odjemalec(aplikacija, motor, stars, klicalec)
        self.naloz(odjemalec, otrok)

        mapa = slike / CVEK_ID / "urniki"
        assert list(mapa.glob("*.jpg")) == []

    def test_datoteka_ki_ni_slika_je_zavrnjena(
        self, aplikacija: FastAPI, motor: Engine, stars: str, otrok: str
    ) -> None:
        def klicalec(_: Path) -> PredlogUrnika:  # pragma: no cover - ne sme se poklicati
            raise AssertionError("klicalec se ne sme poklicati")

        odjemalec = self.naredi_odjemalec(aplikacija, motor, stars, klicalec)
        odgovor = odjemalec.post(
            POT_PREDLOGA,
            data={"csrf": odjemalec.csrf, "otrok": otrok},
            files={"slika": ("urnik.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
        )

        assert "samo sliko" in odgovor.text

    def test_brez_kljuca_pove_da_je_mreza_se_vedno_urejljiva(
        self, aplikacija: FastAPI, motor: Engine, stars: str, otrok: str
    ) -> None:
        """`ADR-009` B2 v malem: odsotnost ključa je stanje, ne napaka."""
        odjemalec = self.naredi_odjemalec(aplikacija, motor, stars, None)
        odgovor = odjemalec.get(PREDPONA)

        assert odgovor.status_code == 200
        assert "ključ za OpenAI ni nastavljen" in odgovor.text

    def test_nalaganje_brez_csrf_zetona_je_zavrnjeno(
        self, aplikacija: FastAPI, motor: Engine, stars: str, otrok: str
    ) -> None:
        """Varovalo 1 iz `ADR-043`: izvzeta pot žeton res preveri sama."""

        def klicalec(_: Path) -> PredlogUrnika:  # pragma: no cover - ne sme se poklicati
            raise AssertionError("klicalec se ne sme poklicati brez žetona")

        odjemalec = self.naredi_odjemalec(aplikacija, motor, stars, klicalec)
        odgovor = odjemalec.post(
            POT_PREDLOGA,
            data={"csrf": "ponarejen", "otrok": otrok},
            files={"slika": ("urnik.png", io.BytesIO(SLIKA), "image/png")},
        )

        assert odgovor.status_code == 403

    def test_nalaganje_brez_seje_pelje_na_prijavo(self, aplikacija: FastAPI) -> None:
        """Izvzetje velja za CSRF, **ne** za sejo (`ADR-043`)."""
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            odgovor = odjemalec.post(
                POT_PREDLOGA,
                data={"csrf": "karkoli"},
                files={"slika": ("urnik.png", io.BytesIO(SLIKA), "image/png")},
                follow_redirects=False,
            )

        assert odgovor.status_code == 303
        assert odgovor.headers["location"].startswith("/admin/login")


def test_izvzeti_nabor_je_enoclanski() -> None:
    """Varovalo 2 iz `ADR-043`.

    Nova pot naj v `POTI_S_SVOJIM_CSRF` ne zaide tiho: kdor bo dodal drugo, bo
    moral podreti ta test in s tem prebrati `ADR-043` — kjer piše, da se pri
    **drugi** taki poti odločitev pretehta in se `multipart` morda nauči plast
    sama.
    """
    assert frozenset({POT_PREDLOGA}) == POTI_S_SVOJIM_CSRF


def test_urnik_ni_snov(
    odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path, otrok: str
) -> None:
    """Kriterij `V3-R09`: slika urnika se ne pojavi nikjer, kjer je snov.

    Dokaz je regresijski in ne sklepanje iz kode: potrjen urnik s sliko se
    pomete \u010dez **vse \u0161tiri povr\u0161ine**, ki jih kriterij na\u0161teje \u2014 izbirnik
    kvizov, statistiko, stran predmeta in pregled po dnevih \u2014 in \u010dez obe
    tabeli, ki nosita snov. Slika res nastane na disku, da test ne bi bil
    zelen samo zato, ker je ni.
    """
    slika_id = "6f1c0d64-2a3b-4c5d-8e9f-0a1b2c3d4e5f"
    mapa = slike / CVEK_ID / "urniki"
    mapa.mkdir(parents=True, exist_ok=True)
    (mapa / f"{slika_id}.jpg").write_bytes(SLIKA)

    ScheduleRepository(Session(motor), CVEK_ID).potrdi(
        otrok, [je(PON, "MAT")], str(mapa / f"{slika_id}.jpg")
    )

    # Snovi in vpra\u0161anja iz nje ne nastanejo.
    with Session(motor) as seja:
        assert seja.scalars(select(Material)).all() == []
        assert seja.scalars(select(Question)).all() == []

    # In nikjer je ni videti \u2014 ne po `id` ne po mapi, v kateri le\u017ei.
    for pot in (
        "/admin/quizzes/new?vstop=danes",
        "/admin/statistics?leto=vse",
        "/admin/subjects/MAT",
        "/admin/days?obdobje=teden",
        "/admin",
    ):
        besedilo = odjemalec.get(pot).text
        assert slika_id not in besedilo, pot
        assert "urniki" not in besedilo, pot


def test_slika_urnika_ne_gre_v_obdelavo(motor: Engine, slike: Path, otrok: str) -> None:
    """Iz slike urnika ne nastane nobeno vpra\u0161anje.

    Obdelava hodi po `materials` in urnika tam ni, zato ne dobi ni\u010desar za
    delo. Test to pove\u017ee z **workerjem samim** in ne le z odsotnostjo vrstice:
    kdor bi kdaj urnik vrinil v `materials`, bi tu dobil pet vpra\u0161anj o
    ponedeljkovi mre\u017ei in ta test bi padel.
    """
    from app.db import naredi_tovarno_sej
    from app.obdelava import obdelaj_cakajoce

    mapa = slike / CVEK_ID / "urniki"
    mapa.mkdir(parents=True, exist_ok=True)
    (mapa / "u.jpg").write_bytes(SLIKA)
    ScheduleRepository(Session(motor), CVEK_ID).potrdi(
        otrok, [je(PON, "MAT")], str(mapa / "u.jpg")
    )

    def klicalec(_: Path) -> object:  # pragma: no cover - ne sme se poklicati
        raise AssertionError("obdelava se slike urnika ne sme dotakniti")

    assert obdelaj_cakajoce(naredi_tovarno_sej(motor), klicalec, slike) == 0  # type: ignore[arg-type]

    with Session(motor) as seja:
        assert seja.scalars(select(Question)).all() == []


def test_upokojen_urnik_se_ne_bere(motor: Engine, otrok: str) -> None:
    """Zamenjava je ena transakcija; upokojeni vnosi ne smejo v manjke."""
    repo = ScheduleRepository(Session(motor), CVEK_ID)
    repo.potrdi(otrok, [je(PON, "MAT"), je(PON, "SLJ")], None)
    repo.potrdi(otrok, [je(PON, "MAT")], None)

    zapisan = ScheduleRepository(Session(motor), CVEK_ID).urnik(otrok)
    assert zapisan is not None
    assert manjkajoci_predmeti(zapisan, PON, ["GEO"]) == ("MAT",)


def test_zamenjava_se_zgodi_v_enem_trenutku(motor: Engine, otrok: str) -> None:
    """Upokojitev starega in potrditev novega nosita **isti** \u010das.

    Ni okras: zamenjava je ena transakcija in en trenutek, zato med njima ni
    hipa, v katerem bi otrok imel dva veljavna urnika ali nobenega. Prav zato
    razvrstitev po `confirmed_at` med njima ne lo\u010di in veljavnost dolo\u010da
    izklju\u010dno os `replaced_at` \u2014 glej
    `TestRepozitorij.test_veljavnost_odloca_os_in_ne_vrstni_red`.
    """
    repo = ScheduleRepository(Session(motor), CVEK_ID)
    repo.potrdi(otrok, [je(PON, "MAT")], None)
    repo.potrdi(otrok, [je(PON, "SLJ")], None)

    with Session(motor) as seja:
        urniki = list(seja.scalars(select(Schedule).order_by(Schedule.confirmed_at)))

    star, nov = urniki
    assert star.replaced_at is not None
    assert star.replaced_at == nov.confirmed_at
    assert nov.replaced_at is None


def test_urnik_enega_otroka_ni_urnik_drugega(motor: Engine, otrok: str, brat: str) -> None:
    """Manjki se ra\u010dunajo po otroku, \u010digar je snov (`V3-R07`).

    Bratov urnik se ne sme podedovati: dokler ga nima, zanj manjkov ni, tudi
    kadar ima sestra poln urnik.
    """
    ScheduleRepository(Session(motor), CVEK_ID).potrdi(otrok, [je(PON, "MAT")], None)

    assert ScheduleRepository(Session(motor), CVEK_ID).urnik(brat) is None
    assert manjkajoci_predmeti(
        ScheduleRepository(Session(motor), CVEK_ID).urnik(brat), PON, ["GEO"]
    ) == ()
