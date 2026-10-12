"""Starš upravlja uporabnike svoje družine (V3-R06, V6-R01).

Pokriva tabelo „Test casi" iz `docs/plan/V3-R06.md`; odločitve so v
`docs/odlocitve/ADR-038`, pravila v `app/clani.py`.

Od `V6-R01` otrok nima ne uporabniškega imena ne gesla (`ADR-058`,
`ADR-061`): starš ga doda samo z imenom, telefon mu poveže s QR kodo in mu
namesto ponastavitve gesla prekliče prijave. Testi, ki so dokazovali otrokovo
geslo, so zato zamenjani s testi tega vedenja; kar velja za geslo, dokazujejo
naprej na staršu.

Meje družine ta datoteka **ne** dokazuje — to počne `tests/test_tesnjenje.py`
za vsako od devetih poti in za vsako javno metodo `ClaniRepository`, z dvema
resničnima družinama in s posnetkom stanja pred in po. Tu je zato samo
neobstoječ `user_id`: da je besedilo `404` isto kot za tujega člana in da se ta
dva primera navzven ne ločita.

Vsak test, ki pravi „geslo deluje", gre skozi **pravo prijavno pot** in ne
primerja zgostitev: zgostitev, ki se ujema sama s sabo, ne dokaže, da se z njo
da prijaviti. Isto velja za „telefon je povezan": žeton se prebere s strani,
kot ga prebere kamera, in unovči na `POST /auth/link`.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clani, povezava, prijava
from app.db import (
    ClaniRepository,
    PrijavaRepository,
    je_zaseden_identifikator,
)
from app.models import (
    VLOGA_OTROK,
    VLOGA_STARS,
    Credential,
    LinkToken,
    Material,
    User,
    UserSession,
)
from tests.conftest import (
    CVEK_ID,
    GESLO_STARSA,
    OTROK_IDENTIFIKATOR,
    STARS_IDENTIFIKATOR,
    PrijavljenOdjemalec,
    SejaTesta,
    prijavi,
    ustvari_otroka,
    ustvari_sejo,
    ustvari_starsa,
    vsebina_strani,
)
from tests.test_druzine import DRUGA_ID, dodaj_druzino
from tests.test_kvizi import UUID_ENA, snov
from tests.test_prijava import prijavi_se

POT = "/admin/family"

#: Vnosa, ki ju obrazca sprejmeta, kadar test ne preizkuša prav vnosa.
NOV_OTROK = {"ime": "Nika"}
NOV_STARS = {
    "ime": "Ana",
    "enaslov": "ana@primer.test",
    "geslo": "anino-geslo-12",
    "geslo_znova": "anino-geslo-12",
}


#: Drugi starš družine v testih ponastavitve gesla.
ANA = "ana@primer.test"
GESLO_ANE = "anino-geslo-12"


def otrok_po_imenu(motor: Engine, ime: str) -> User | None:
    """Otrok s tem prikaznim imenom; identifikatorja od `V6-R01` nima."""
    with Session(motor) as seja:
        return seja.scalars(
            select(User).where(User.display_name == ime, User.role == VLOGA_OTROK)
        ).one_or_none()


def poverilnic(motor: Engine, user_id: str) -> int:
    with Session(motor) as seja:
        return len(
            list(seja.scalars(select(Credential.id).where(Credential.user_id == user_id)))
        )


def povezav(motor: Engine) -> int:
    with Session(motor) as seja:
        return len(list(seja.scalars(select(LinkToken.id))))


def obrazec_otroka(besedilo: str) -> str:
    """Izsek strani z obrazcem za dodajanje otroka — brez obrazca za starša."""
    najdeno = re.search(r'<details[^>]*id="dodaj-otroka".*?</details>', besedilo, re.DOTALL)
    assert najdeno is not None, "obrazca za dodajanje otroka ni v izrisu"
    return najdeno.group(0)


def povezava_s_strani(besedilo: str) -> str:
    """Naslov, ki ga nosi gumb „Odpri na tem telefonu"."""
    najdeno = re.search(r'href="(school-companion://[^"]+)"', besedilo)
    assert najdeno is not None, "na strani ni povezave, ki bi odprla aplikacijo"
    return unescape(najdeno.group(1))


def zeton_s_strani(odjemalec: PrijavljenOdjemalec, user_id: str) -> str:
    """Pritisne „Poveži telefon" in prebere žeton, kot bi ga prebrala kamera."""
    odgovor = odjemalec.post(pot_clana(user_id, "link"))
    assert odgovor.status_code == 200, odgovor.text
    zetoni = parse_qs(urlsplit(povezava_s_strani(odgovor.text)).query)["z"]
    assert len(zetoni) == 1
    return zetoni[0]


def povezi(odjemalec: PrijavljenOdjemalec, zeton: str) -> Any:
    """Unovči žeton po pravi poti telefona (V6-R01)."""
    return odjemalec.post(prijava.POT_POVEZAVE_TELEFONA, json={"token": zeton})


def uporabnik(motor: Engine, identifikator: str) -> User | None:
    """Oseba za danim identifikatorjem, prebrana mimo repozitorija."""
    with Session(motor) as seja:
        return seja.scalars(
            select(User).join(Credential, Credential.user_id == User.id).where(
                Credential.identifier == identifikator
            )
        ).one_or_none()


def sej(motor: Engine, user_id: str) -> int:
    with Session(motor) as seja:
        return len(
            list(seja.scalars(select(UserSession.id).where(UserSession.user_id == user_id)))
        )


def zgostitev_v_bazi(motor: Engine, identifikator: str) -> str | None:
    with Session(motor) as seja:
        return seja.scalars(
            select(Credential.secret_hash).where(Credential.identifier == identifikator)
        ).one()


def pot_clana(user_id: str, dejanje: str) -> str:
    return f"{POT}/members/{user_id}/{dejanje}"


@pytest.fixture
def lastnik(motor: Engine) -> str:
    """Lastnik sistema — starš z zastavico, kakršno postavi migracija `0008`."""
    return ustvari_starsa(
        motor,
        identifikator="lastnik@primer.test",
        prikazno_ime="Lastnik",
        lastnik_sistema=True,
    )


class TestSeznam:
    """Kriterij: seznam članov družine z vlogo in stanjem."""

    def test_pokaze_clane_z_vlogo_in_stanjem(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str
    ) -> None:
        ustvari_starsa(
            motor, identifikator="bivsa@primer.test", prikazno_ime="Bivša", aktiven=False
        )

        besedilo = odjemalec.get(POT).text

        assert "Dejan" in besedilo
        assert "Maša" in besedilo
        assert STARS_IDENTIFIKATOR in besedilo
        assert "starš" in besedilo
        assert "otrok" in besedilo
        assert "deaktiviran račun" in besedilo

    def test_otrok_nima_uporabniskega_imena_ima_pa_povezavo_telefona(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """V6-R01: otroka ne določa ime za prijavo, ampak telefon, ki mu ga povežeš.

        Otrok iz `conftest` geselno poverilnico v bazi še ima (stanje pred
        migracijo `0014`); stran njenega identifikatorja vseeno ne pokaže.
        """
        otrok = ustvari_otroka(motor, identifikator="zelo-posebno-ime")

        besedilo = odjemalec.get(POT).text

        assert "zelo-posebno-ime" not in besedilo
        assert "Uporabniško ime" not in besedilo
        assert f'action="{pot_clana(otrok, "link")}"' in besedilo
        assert "Poveži telefon" in besedilo
        assert f'href="{pot_clana(otrok, "revoke")}"' in besedilo

    def test_stars_brez_gesla_je_oznacen(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Stanje, v katerem starša pusti migracija (`ADR-035` G)."""
        ustvari_starsa(motor, identifikator="brez@primer.test", prikazno_ime="Brez", geslo=None)

        assert "geslo ni nastavljeno" in odjemalec.get(POT).text

    def test_otrok_ni_oznacen_kot_racun_brez_gesla(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Otrok gesla nima po zasnovi; oznaka bi starša pošiljala iskat dejanje, ki ga ni."""
        with Session(motor) as seja:
            ClaniRepository(seja, CVEK_ID).ustvari_otroka(
                display_name="Nika", ko=datetime.now(UTC)
            )

        besedilo = odjemalec.get(POT).text

        assert "Nika" in besedilo
        assert "geslo ni nastavljeno" not in besedilo

    def test_nalepka_o_geslu_pove_isto_kot_zavrnitev(
        self, odjemalec: PrijavljenOdjemalec
    ) -> None:
        """Nalepka v obrazcu in meja, po kateri se zavrača, sta ista številka.

        Vtipkana v predlogo bi se lahko razšla, ne da bi kak test padel:
        sporočilo o napaki se gradi iz `NAJKRAJSE_GESLO`, nalepka pa ne bi.
        Geslo ima od `V6-R01` samo starš.
        """
        besedilo = odjemalec.get(POT).text

        assert f"vsaj {prijava.NAJKRAJSE_GESLO[VLOGA_STARS]} znakov" in besedilo
        assert VLOGA_OTROK not in prijava.NAJKRAJSE_GESLO

    # V6-R02: družina brez otroka dobi na `/admin` prvo stran po odobritvi
    # (`ADR-062` E); ta test govori o pregledu, zato otrok obstaja.
    @pytest.mark.usefixtures("otrok")
    def test_povezava_je_na_pregledu(self, odjemalec: PrijavljenOdjemalec) -> None:
        """Brez vhoda s `/admin` je stran dosegljiva samo z vtipkanim naslovom."""
        assert f'href="{POT}"' in odjemalec.get("/admin").text


class TestDodajanjeOtroka:
    """Kriterij `V6-R01`: samo prikazno ime; uporabniškega imena in gesla ni."""

    def test_otrok_nastane_samo_z_imenom_in_brez_poverilnice(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        odgovor = odjemalec.post(f"{POT}/children", data=NOV_OTROK, follow_redirects=False)

        assert odgovor.status_code == 303
        nova = otrok_po_imenu(motor, "Nika")
        assert nova is not None
        assert nova.role == VLOGA_OTROK
        assert nova.family_id == CVEK_ID
        assert nova.is_active is True
        assert nova.is_system_owner is False
        assert poverilnic(motor, nova.id) == 0

    def test_nov_otrok_se_poveze_s_kodo_s_svoje_kartice(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Cela pot kriterija: dodaj, poveži, aplikacija dobi sejo tega otroka."""
        odjemalec.post(f"{POT}/children", data=NOV_OTROK)
        nova = otrok_po_imenu(motor, "Nika")
        assert nova is not None

        odgovor = povezi(odjemalec, zeton_s_strani(odjemalec, nova.id))

        assert odgovor.status_code == 200
        assert odgovor.json()["user_id"] == nova.id
        assert odgovor.json()["display_name"] == "Nika"

    def test_obrazec_nima_polj_za_uporabnisko_ime_in_geslo(
        self, odjemalec: PrijavljenOdjemalec
    ) -> None:
        obrazec = obrazec_otroka(odjemalec.get(f"{POT}?dodaj=otrok").text)

        assert 'name="ime"' in obrazec
        assert 'name="uporabnisko_ime"' not in obrazec
        assert 'name="geslo"' not in obrazec
        assert 'type="password"' not in obrazec

    def test_poslano_uporabnisko_ime_in_geslo_se_prezreta(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Star obrazec v odprtem zavihku ne sme ustvariti poverilnice."""
        odjemalec.post(
            f"{POT}/children",
            data={
                **NOV_OTROK,
                "uporabnisko_ime": "nika",
                "geslo": "nikino-geslo",
                "geslo_znova": "nikino-geslo",
            },
        )

        nova = otrok_po_imenu(motor, "Nika")
        assert nova is not None
        assert poverilnic(motor, nova.id) == 0
        assert uporabnik(motor, "nika") is None

    def test_ime_se_obreze(self, odjemalec: PrijavljenOdjemalec, motor: Engine) -> None:
        odjemalec.post(f"{POT}/children", data={"ime": "  Nika  "})

        assert otrok_po_imenu(motor, "Nika") is not None

    @pytest.mark.parametrize(
        ("ime", "sporocilo"),
        [("   ", clani.SPOROCILO_PRAZNO_IME), ("x" * 201, clani.SPOROCILO_PREDOLGO_IME)],
        ids=["prazno-ime", "predolgo-ime"],
    )
    def test_neveljavno_ime_ne_ustvari_nicesar(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, ime: str, sporocilo: str
    ) -> None:
        odgovor = odjemalec.post(f"{POT}/children", data={"ime": ime})

        assert odgovor.status_code == 400
        assert sporocilo in obrazec_otroka(odgovor.text)
        with Session(motor) as seja:
            assert list(seja.scalars(select(User.id).where(User.role == VLOGA_OTROK))) == []

    def test_dva_otroka_z_istim_imenom_sta_dovoljena(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Enoličnosti prikaznega imena ni (`docs/plan/V6-R01.md`, faza 1)."""
        odjemalec.post(f"{POT}/children", data=NOV_OTROK)

        odgovor = odjemalec.post(f"{POT}/children", data=NOV_OTROK, follow_redirects=False)

        assert odgovor.status_code == 303
        with Session(motor) as seja:
            imena = list(seja.scalars(select(User.display_name).where(User.role == VLOGA_OTROK)))
        assert imena == ["Nika", "Nika"]


class TestDodajanjeStarsa:
    """Kriterij: prikazno ime, e-naslov, začetno geslo."""

    def test_stars_nastane_in_se_prijavi_na_spletni_strani(
        self, odjemalec: PrijavljenOdjemalec, aplikacija: FastAPI, motor: Engine
    ) -> None:
        odgovor = odjemalec.post(f"{POT}/parents", data=NOV_STARS, follow_redirects=False)

        assert odgovor.status_code == 303
        nova = uporabnik(motor, "ana@primer.test")
        assert nova is not None
        assert nova.role == VLOGA_STARS
        assert nova.family_id == CVEK_ID
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as drug:
            prijavljen = prijavi_se(drug, "ana@primer.test", NOV_STARS["geslo"])
        assert prijavljen.status_code == 303

    def test_novi_stars_ni_lastnik_sistema(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """`ADR-038` G: sicer bi si starš lastnika sistema ustvaril sam."""
        odjemalec.post(f"{POT}/parents", data=NOV_STARS)

        nova = uporabnik(motor, "ana@primer.test")
        assert nova is not None
        assert nova.is_system_owner is False

    @pytest.mark.parametrize(
        "enaslov", ["ana", "ana@", "@primer.test", "ana@pri mer.test", "a@b@c"]
    )
    def test_kar_ni_enaslov_se_zavrne(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, enaslov: str
    ) -> None:
        odgovor = odjemalec.post(f"{POT}/parents", data={**NOV_STARS, "enaslov": enaslov})

        assert odgovor.status_code == 400
        assert clani.SPOROCILO_NI_ENASLOV in odgovor.text
        assert uporabnik(motor, enaslov) is None

    def test_neujemanje_gesel_ne_ustvari_nicesar(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Do `V6-R01` je to dokazoval obrazec za otroka; geslo ima odslej samo starš."""
        odgovor = odjemalec.post(
            f"{POT}/parents", data={**NOV_STARS, "geslo_znova": "nekaj-cisto-drugega"}
        )

        assert odgovor.status_code == 400
        assert clani.SPOROCILO_GESLI_SE_NE_UJEMATA in odgovor.text
        assert uporabnik(motor, "ana@primer.test") is None

    def test_zaseden_enaslov_ne_ustvari_nicesar(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        odgovor = odjemalec.post(
            f"{POT}/parents", data={**NOV_STARS, "enaslov": STARS_IDENTIFIKATOR}
        )

        assert odgovor.status_code == 400
        assert clani.SPOROCILO_IDENTIFIKATOR_ZASEDEN in odgovor.text
        with Session(motor) as seja:
            assert len(list(seja.scalars(select(User.id)))) == 1

    def test_zasedenost_ne_ubeze_z_velikimi_crkami(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Normalizacija teče **pred** vstavljanjem, sicer bi nastal dvojnik (`ADR-038` E)."""
        odgovor = odjemalec.post(
            f"{POT}/parents", data={**NOV_STARS, "enaslov": f"  {STARS_IDENTIFIKATOR.upper()} "}
        )

        assert odgovor.status_code == 400
        assert clani.SPOROCILO_IDENTIFIKATOR_ZASEDEN in odgovor.text
        with Session(motor) as seja:
            assert len(list(seja.scalars(select(User.id)))) == 1

    def test_enaslov_se_normalizira(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """`ADR-038` E: brez tega bi `Ana@…` in `ana@…` bila dva računa."""
        odjemalec.post(f"{POT}/parents", data={**NOV_STARS, "enaslov": "  Ana@Primer.TEST "})

        assert uporabnik(motor, "ana@primer.test") is not None

    def test_vnos_se_vrne_geslo_pa_nikoli(self, odjemalec: PrijavljenOdjemalec) -> None:
        """Kriterij `ADR-038` F: geslo ne sme pristati v HTML."""
        odgovor = odjemalec.post(
            f"{POT}/parents", data={**NOV_STARS, "geslo_znova": "nekaj-cisto-drugega"}
        )

        assert 'value="Ana"' in odgovor.text
        assert 'value="ana@primer.test"' in odgovor.text
        assert NOV_STARS["geslo"] not in odgovor.text
        assert "nekaj-cisto-drugega" not in odgovor.text

    def test_enajst_znakov_je_za_starsa_premalo(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Meja je 12 (`prijava.NAJKRAJSE_GESLO`); enajst znakov je prvi, ki ne gre."""
        kratko = "enajst-znak"
        assert len(kratko) == 11

        odgovor = odjemalec.post(
            f"{POT}/parents", data={**NOV_STARS, "geslo": kratko, "geslo_znova": kratko}
        )

        assert odgovor.status_code == 400
        assert "vsaj 12" in odgovor.text
        assert uporabnik(motor, "ana@primer.test") is None


class TestPonastavitevGesla:
    """Kriterij: ponastavitev prekliče vse seje uporabnika, na vseh napravah.

    Od `V6-R01` geslo ima samo starš, zato razred govori o drugem staršu;
    otrokov nadomestek je `TestPrekliciPrijave`.
    """

    @pytest.fixture
    def ana(self, motor: Engine) -> str:
        """Drugi starš družine, ki mu prvi ponastavlja geslo."""
        return ustvari_starsa(motor, identifikator=ANA, prikazno_ime="Ana", geslo=GESLO_ANE)

    def test_novo_geslo_dela_staro_ne_in_seje_padejo(
        self, odjemalec: PrijavljenOdjemalec, aplikacija: FastAPI, motor: Engine, ana: str
    ) -> None:
        ustvari_sejo(motor, ana)
        ustvari_sejo(motor, ana)
        assert sej(motor, ana) == 2
        novo = "novo-geslo-za-ano"

        odgovor = odjemalec.post(
            pot_clana(ana, "password"),
            data={"geslo": novo, "geslo_znova": novo},
            follow_redirects=False,
        )

        assert odgovor.status_code == 303
        # Obe seji sta bili preklicani, ne samo tista, ki je bila pri roki.
        assert sej(motor, ana) == 0
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as drug:
            assert prijavi_se(drug, ANA, GESLO_ANE).status_code == 401
            assert prijavi_se(drug, ANA, novo).status_code == 303

    def test_ponastavitev_sebi_odjavi_tudi_to_sejo(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """`ADR-038` D: pravilo velja brez izjeme, tudi za sejo, ki kliče."""
        novo = "novo-geslo-dejan"

        odgovor = odjemalec.post(
            pot_clana(stars, "password"),
            data={"geslo": novo, "geslo_znova": novo},
            follow_redirects=False,
        )

        assert odgovor.status_code == 303
        assert sej(motor, stars) == 0
        naslednja = odjemalec.get(POT, follow_redirects=False)
        assert naslednja.status_code == 303
        assert naslednja.headers["location"].startswith(prijava.POT_PRIJAVE)

    def test_prekratko_geslo_ne_spremeni_nicesar(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, ana: str
    ) -> None:
        ustvari_sejo(motor, ana)
        prej = zgostitev_v_bazi(motor, ANA)

        odgovor = odjemalec.post(
            pot_clana(ana, "password"), data={"geslo": "kratko", "geslo_znova": "kratko"}
        )

        assert odgovor.status_code == 400
        assert zgostitev_v_bazi(motor, ANA) == prej
        assert sej(motor, ana) == 1

    def test_vmesna_stran_sama_ne_spremeni_nicesar(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, ana: str
    ) -> None:
        """Kriterij: dejanje je `POST`, ne `GET`."""
        ustvari_sejo(motor, ana)
        prej = zgostitev_v_bazi(motor, ANA)

        odgovor = odjemalec.get(pot_clana(ana, "password"))

        assert odgovor.status_code == 200
        assert "Ana" in odgovor.text
        assert zgostitev_v_bazi(motor, ANA) == prej
        assert sej(motor, ana) == 1

    def test_otroku_gesla_ni_mogoce_ponastaviti(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str, telefon: SejaTesta
    ) -> None:
        """Kriterij `V6-R01`: ponastavitve gesla za otroka ni več (`ADR-058` E).

        Otrok iz `conftest` geselno poverilnico v bazi še ima; pot je vseeno
        ne prepiše in sej ne prekliče. Sporočilo pove, kaj je namesto tega.
        """
        prej = zgostitev_v_bazi(motor, OTROK_IDENTIFIKATOR)

        for odgovor in (
            odjemalec.get(pot_clana(otrok, "password")),
            odjemalec.post(
                pot_clana(otrok, "password"),
                data={"geslo": "novo-geslo-masa", "geslo_znova": "novo-geslo-masa"},
            ),
        ):
            assert odgovor.status_code == 403
            assert clani.SPOROCILO_OTROK_NIMA_GESLA in odgovor.text

        assert zgostitev_v_bazi(motor, OTROK_IDENTIFIKATOR) == prej
        assert sej(motor, otrok) == 1

    def test_seznam_otroku_ponastavitve_ne_ponudi(
        self, odjemalec: PrijavljenOdjemalec, otrok: str
    ) -> None:
        assert pot_clana(otrok, "password") not in odjemalec.get(POT).text

    def test_clan_brez_poverilnice_dobi_razlago_ne_tihe_preusmeritve(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Shema osebo brez poverilnice dopušča; „opravljeno" za nič ne gre."""
        brez = str(uuid4())
        with Session(motor) as seja:
            seja.add(
                User(
                    id=brez,
                    family_id=CVEK_ID,
                    role=VLOGA_STARS,
                    display_name="Brez poverilnice",
                    is_system_owner=False,
                    is_active=True,
                    created_at=datetime.now(UTC),
                )
            )
            seja.commit()

        odgovor = odjemalec.post(
            pot_clana(brez, "password"),
            data={"geslo": "novo-geslo-tukaj", "geslo_znova": "novo-geslo-tukaj"},
            follow_redirects=False,
        )

        # Od V6-R02 (`ADR-062` O) je to pravilo in ne izid pisanja: starš brez
        # geselne poverilnice — tak je vsak, ki se registrira z Googlom — dobi
        # `403` z razlago, še preden se karkoli poskusi zapisati.
        assert odgovor.status_code == 403
        assert clani.SPOROCILO_STARS_BREZ_GESLA in odgovor.text

    def test_lastniku_sistema_drug_stars_gesla_ne_ponastavi(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, lastnik: str
    ) -> None:
        """`ADR-038` G. Zavrnitev je `403` in ne `404`: člana **vidiš**."""
        prej = zgostitev_v_bazi(motor, "lastnik@primer.test")

        for odgovor in (
            odjemalec.get(pot_clana(lastnik, "password")),
            odjemalec.post(
                pot_clana(lastnik, "password"),
                data={"geslo": "vlomljeno-geslo", "geslo_znova": "vlomljeno-geslo"},
            ),
        ):
            assert odgovor.status_code == 403
            assert clani.SPOROCILO_TUJE_GESLO_LASTNIKA in odgovor.text

        assert zgostitev_v_bazi(motor, "lastnik@primer.test") == prej

    def test_lastnik_sistema_sebi_geslo_ponastavi(
        self, aplikacija: FastAPI, motor: Engine, lastnik: str
    ) -> None:
        novo = "lastnikovo-novo-geslo"
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            prijavi(odjemalec, motor, lastnik)

            odgovor = odjemalec.post(
                pot_clana(lastnik, "password"),
                data={"geslo": novo, "geslo_znova": novo},
                follow_redirects=False,
            )

        assert odgovor.status_code == 303
        assert zgostitev_v_bazi(motor, "lastnik@primer.test") is not None
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as drug:
            assert prijavi_se(drug, "lastnik@primer.test", novo).status_code == 303

    def test_seznam_dejanja_ne_ponudi_tam_kjer_bi_ga_zavrnil(
        self, odjemalec: PrijavljenOdjemalec, lastnik: str
    ) -> None:
        """Ponujen klik, ki se konča s `403`, je napaka seznama, ne uporabnice."""
        assert pot_clana(lastnik, "password") not in odjemalec.get(POT).text


class TestPoveziTelefon:
    """Kriteriji `V6-R01`: stran s QR kodo in gumbom, žeton po `ADR-061` B."""

    def test_stran_ima_kodo_in_gumb_z_isto_povezavo(
        self, odjemalec: PrijavljenOdjemalec, otrok: str
    ) -> None:
        odgovor = odjemalec.post(pot_clana(otrok, "link"))

        assert odgovor.status_code == 200
        naslov = povezava_s_strani(odgovor.text)
        assert naslov.startswith("school-companion://povezi?z=")
        assert "Odpri na tem telefonu" in odgovor.text
        # QR ni okras: je natanko slika naslova, ki ga nosi gumb. Drugačen
        # naslov bi dal drugačno sliko in ta primerjava bi padla.
        assert povezava.qr_svg(naslov) in odgovor.text
        assert povezava.qr_svg(naslov + "x") not in odgovor.text

    @pytest.mark.parametrize("dejanje", ["link", "revoke"])
    def test_krozec_nosi_otrokovo_zacetnico_ne_starseve(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, dejanje: str
    ) -> None:
        """Obdelovalec konteksta ključe poti prepiše (`docs/02-izkusnje.md`).

        Ključ `zacetnica` je njegov — začetnica prijavljenega starša za meni —,
        zato je kartica sprva kazala „D" ob otroku. Najdeno ob ogledu strani.
        """
        nika = ustvari_otroka(motor, identifikator="nika", prikazno_ime="Nika")
        pot = pot_clana(nika, dejanje)

        besedilo = vsebina_strani(
            (odjemalec.post(pot) if dejanje == "link" else odjemalec.get(pot)).text
        )

        assert '<span class="krozec velik" aria-hidden="true">N</span>' in besedilo

    def test_povezava_nosi_samo_zeton(self, odjemalec: PrijavljenOdjemalec, otrok: str) -> None:
        """`ADR-061` C: naslova strežnika v povezavi ni."""
        naslov = povezava_s_strani(odjemalec.post(pot_clana(otrok, "link")).text)

        razbito = urlsplit(naslov)
        assert razbito.scheme == "school-companion"
        assert list(parse_qs(razbito.query)) == ["z"]
        assert "http" not in naslov

    def test_shema_je_shema_aplikacije(self) -> None:
        """Koda, ki je telefon ne odpre, je tiha napaka; shema je v `app.json`."""
        nastavitve = json.loads(
            (Path(__file__).parents[2] / "mobile" / "app.json").read_text(encoding="utf-8")
        )

        assert nastavitve["expo"]["scheme"] == povezava.SHEMA

    def test_stran_se_ne_shrani_in_nima_skripte(
        self, odjemalec: PrijavljenOdjemalec, otrok: str
    ) -> None:
        odgovor = odjemalec.post(pot_clana(otrok, "link"))

        assert odgovor.headers["cache-control"] == "no-store"
        assert "<script" not in odgovor.text
        assert "http://" not in vsebina_strani(odgovor.text).replace(
            'xmlns="http://www.w3.org/2000/svg"', ""
        )

    def test_v_bazi_je_samo_zgostitev_vezana_na_otroka(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str
    ) -> None:
        zeton = zeton_s_strani(odjemalec, otrok)

        with Session(motor) as seja:
            vrstice = list(seja.scalars(select(LinkToken)))

        assert len(vrstice) == 1
        assert vrstice[0].token_hash == prijava.zgostitev_zetona(zeton)
        assert vrstice[0].token_hash != zeton
        assert vrstice[0].child_id == otrok
        assert vrstice[0].family_id == CVEK_ID

    def test_zeton_je_nakljucen(self, odjemalec: PrijavljenOdjemalec, otrok: str) -> None:
        prvi = zeton_s_strani(odjemalec, otrok)
        drugi = zeton_s_strani(odjemalec, otrok)

        assert prvi != drugi
        assert len(prvi) >= 43

    def test_rok_je_deset_minut_in_stran_to_pove(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str
    ) -> None:
        odgovor = odjemalec.post(pot_clana(otrok, "link"))

        with Session(motor) as seja:
            vrstica = seja.scalars(select(LinkToken)).one()
        assert vrstica.expires_at - vrstica.created_at == timedelta(minutes=10)
        assert "10 minut" in odgovor.text

    def test_nov_zeton_razveljavi_prejsnjega(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str
    ) -> None:
        prvi = zeton_s_strani(odjemalec, otrok)
        drugi = zeton_s_strani(odjemalec, otrok)

        assert povezi(odjemalec, prvi).status_code == 401
        assert povezi(odjemalec, drugi).status_code == 200
        with Session(motor) as seja:
            assert list(seja.scalars(select(LinkToken.id))) == []

    def test_nov_zeton_enega_otroka_ne_razveljavi_zetona_drugega(
        self, odjemalec: PrijavljenOdjemalec, otrok: str, brat: str
    ) -> None:
        masin = zeton_s_strani(odjemalec, otrok)
        zeton_s_strani(odjemalec, brat)

        odgovor = povezi(odjemalec, masin)

        assert odgovor.status_code == 200
        assert odgovor.json()["user_id"] == otrok

    def test_zeton_da_sejo_pravega_otroka(
        self, odjemalec: PrijavljenOdjemalec, otrok: str, brat: str
    ) -> None:
        odgovor = povezi(odjemalec, zeton_s_strani(odjemalec, brat))

        assert odgovor.json()["user_id"] == brat
        assert odgovor.json()["display_name"] == "Nejc"

    def test_nova_koda_ne_odjavi_povezanega_telefona(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str, telefon: SejaTesta
    ) -> None:
        """`ADR-058` E: dva telefona sta dovoljena."""
        odjemalec.post(pot_clana(otrok, "link"))

        assert sej(motor, otrok) == 1
        assert odjemalec.get("/quizzes/pending", headers=telefon.glave).status_code == 200

    def test_starsu_telefona_ni_mogoce_povezati(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        odgovor = odjemalec.post(pot_clana(stars, "link"))

        assert odgovor.status_code == 403
        assert clani.SPOROCILO_TELEFON_SAMO_OTROKU in odgovor.text
        assert povezav(motor) == 0
        assert pot_clana(stars, "link") not in odjemalec.get(POT).text

    def test_deaktiviranemu_otroku_telefona_ni_mogoce_povezati(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        bivsi = ustvari_otroka(motor, identifikator="bivsi", prikazno_ime="Bivši", aktiven=False)

        odgovor = odjemalec.post(pot_clana(bivsi, "link"))

        assert odgovor.status_code == 403
        assert clani.SPOROCILO_POVEZAVA_DEAKTIVIRANEMU in odgovor.text
        assert povezav(motor) == 0
        assert pot_clana(bivsi, "link") not in odjemalec.get(POT).text

    def test_repozitorij_zetona_ne_ustvari_komur_ne_sme(
        self, motor: Engine, stars: str
    ) -> None:
        """Druga plast: pogoj je v stavku, ne samo v usmerjevalniku (`ADR-061` D)."""
        bivsi = ustvari_otroka(motor, identifikator="bivsi", prikazno_ime="Bivši", aktiven=False)
        zdaj = datetime.now(UTC)

        with Session(motor) as seja:
            repo = ClaniRepository(seja, CVEK_ID)
            for kdo in (stars, bivsi, str(uuid4())):
                assert not repo.ustvari_povezavo(
                    kdo,
                    token_hash=prijava.zgostitev_zetona(prijava.nov_zeton()),
                    ko=zdaj,
                    potece=zdaj + prijava.TRAJANJE_POVEZAVE,
                )

        assert povezav(motor) == 0

    def test_brez_csrf_zetona_koda_ne_nastane(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str
    ) -> None:
        odgovor = odjemalec.post(pot_clana(otrok, "link"), data={"csrf": "ni-pravi"})

        assert odgovor.status_code == 403
        assert povezav(motor) == 0

    def test_get_ne_ustvari_kode_in_pelje_na_seznam(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str
    ) -> None:
        """Stran ni zaznamek; osvežen naslov ne sme biti videti kot `405`."""
        odgovor = odjemalec.get(pot_clana(otrok, "link"), follow_redirects=False)

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == POT
        assert povezav(motor) == 0


class TestPrekliciPrijave:
    """Kriterij `V6-R01`: „Prekliči prijave" z vmesno potrditvijo (`ADR-058` E)."""

    def test_vmesna_stran_sama_ne_spremeni_nicesar(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str, telefon: SejaTesta
    ) -> None:
        odgovor = odjemalec.get(pot_clana(otrok, "revoke"))

        assert odgovor.status_code == 200
        assert "Maša" in odgovor.text
        assert f'action="{pot_clana(otrok, "revoke")}"' in odgovor.text
        assert sej(motor, otrok) == 1

    def test_izbrise_vse_otrokove_seje(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str, telefon: SejaTesta
    ) -> None:
        druga_naprava = ustvari_sejo(motor, otrok)
        assert sej(motor, otrok) == 2

        odgovor = odjemalec.post(pot_clana(otrok, "revoke"), follow_redirects=False)

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == POT
        assert sej(motor, otrok) == 0
        assert odjemalec.get("/quizzes/pending", headers=telefon.glave).status_code == 401
        assert odjemalec.get("/quizzes/pending", headers=druga_naprava.glave).status_code == 401

    def test_razveljavi_tudi_neporabljeno_kodo(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str
    ) -> None:
        """`ADR-061` G: preklic, po katerem bi koda še veljala, ni preklic."""
        zeton = zeton_s_strani(odjemalec, otrok)

        odjemalec.post(pot_clana(otrok, "revoke"))

        assert povezi(odjemalec, zeton).status_code == 401
        assert povezav(motor) == 0
        assert sej(motor, otrok) == 0

    def test_drugih_ne_odjavi(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        stars: str,
        otrok: str,
        telefon: SejaTesta,
        brat: str,
    ) -> None:
        bratov_telefon = ustvari_sejo(motor, brat)
        bratova_koda = zeton_s_strani(odjemalec, brat)

        odjemalec.post(pot_clana(otrok, "revoke"))

        assert sej(motor, brat) == 1
        assert sej(motor, stars) == 1
        assert odjemalec.get("/quizzes/pending", headers=bratov_telefon.glave).status_code == 200
        assert odjemalec.get(POT).status_code == 200
        assert povezi(odjemalec, bratova_koda).status_code == 200

    def test_podatki_ostanejo_in_otrok_ostane_aktiven(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        slike: Any,
        otrok: str,
        telefon: SejaTesta,
    ) -> None:
        snov(motor, slike, UUID_ENA)

        odjemalec.post(pot_clana(otrok, "revoke"))

        with Session(motor) as seja:
            oseba = seja.get(User, otrok)
            assert oseba is not None
            assert oseba.is_active is True
            assert len(list(seja.scalars(select(Material.id)))) == 1

    def test_po_preklicu_se_telefon_poveze_znova(
        self, odjemalec: PrijavljenOdjemalec, otrok: str, telefon: SejaTesta
    ) -> None:
        odjemalec.post(pot_clana(otrok, "revoke"))

        odgovor = povezi(odjemalec, zeton_s_strani(odjemalec, otrok))

        assert odgovor.status_code == 200
        assert odgovor.json()["user_id"] == otrok

    def test_starsu_prijav_ni_mogoce_preklicati(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        for odgovor in (
            odjemalec.get(pot_clana(stars, "revoke")),
            odjemalec.post(pot_clana(stars, "revoke")),
        ):
            assert odgovor.status_code == 403
            assert clani.SPOROCILO_PREKLIC_SAMO_OTROKU in odgovor.text

        assert sej(motor, stars) == 1
        assert pot_clana(stars, "revoke") not in odjemalec.get(POT).text

    def test_brez_csrf_zetona_seje_ostanejo(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str, telefon: SejaTesta
    ) -> None:
        odgovor = odjemalec.post(pot_clana(otrok, "revoke"), data={"csrf": "ni-pravi"})

        assert odgovor.status_code == 403
        assert sej(motor, otrok) == 1


class TestDeaktivacija:
    """Kriterij: prijava ne gre več, seje padejo, podatki ostanejo."""

    def test_otrok_se_ne_poveze_seje_padejo_podatki_ostanejo(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        slike: Any,
        otrok: str,
        telefon: SejaTesta,
    ) -> None:
        """Od `V6-R01` je otrokova „prijava" povezava telefona (`ADR-061` G).

        Koda, ustvarjena tik pred deaktivacijo, pade skupaj s sejami, in nove
        ni mogoče ustvariti.
        """
        snov(motor, slike, UUID_ENA)
        koda = zeton_s_strani(odjemalec, otrok)

        odgovor = odjemalec.post(pot_clana(otrok, "deactivate"), follow_redirects=False)

        assert odgovor.status_code == 303
        assert sej(motor, otrok) == 0
        assert povezav(motor) == 0
        assert povezi(odjemalec, koda).status_code == 401
        assert odjemalec.post(pot_clana(otrok, "link")).status_code == 403
        assert odjemalec.get("/quizzes/pending", headers=telefon.glave).status_code == 401
        with Session(motor) as seja:
            oseba = seja.get(User, otrok)
            assert oseba is not None, "člana se ne briše, le deaktivira"
            assert oseba.is_active is False
            assert zgostitev_v_bazi(motor, OTROK_IDENTIFIKATOR) is not None
            assert len(list(seja.scalars(select(Material.id)))) == 1

    def test_sebe_ni_mogoce_deaktivirati(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Z **drugim** aktivnim staršem v družini je sporočilo „sebe ne".

        Par s testom nad edinim staršem spodaj: ločnica med sporočiloma je
        prav to, ali je nasvet „naj to naredi drugi starš" izvedljiv.
        """
        ustvari_starsa(motor, identifikator="druga@primer.test", prikazno_ime="Druga")

        for odgovor in (
            odjemalec.get(pot_clana(stars, "deactivate")),
            odjemalec.post(pot_clana(stars, "deactivate")),
        ):
            assert odgovor.status_code == 403
            assert clani.SPOROCILO_NE_SEBE in odgovor.text

        with Session(motor) as seja:
            oseba = seja.get(User, stars)
            assert oseba is not None and oseba.is_active is True

    def test_drug_aktiven_stars_se_da_deaktivirati(
        self, aplikacija: FastAPI, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Dokler sta aktivna dva, en pade — pravilo o zadnjem staršu ne ovira."""
        drugi = ustvari_starsa(motor, identifikator="druga@primer.test", prikazno_ime="Druga")
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as drug:
            prijavi(drug, motor, drugi)

            odgovor = drug.post(pot_clana(stars, "deactivate"), follow_redirects=False)

        assert odgovor.status_code == 303
        with Session(motor) as seja:
            oseba = seja.get(User, stars)
            assert oseba is not None and oseba.is_active is False

    def test_edini_stars_dobi_izvedljiv_nasvet_in_ostane_aktiven(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Starš, ki je v družini sam, dobi pravilo o **zadnjem staršu**.

        Dvoje naenkrat, in oboje je bilo najdeno v pregledu:

        - Sporočilo mora povedati izvedljiv naslednji korak (`CLAUDE.md` §1b).
          „Naj to naredi drugi starš v družini" v enostarševski družini ni
          izvedljivo; „najprej dodaj drugega starša" je.
        - To je hkrati edina pot, po kateri je pravilo o zadnjem staršu
          dosegljivo čez HTTP, zato tu visi tudi dokaz, da je **priklopljeno na
          pravo število**: ob `aktivnih_starsev=99` v `routers/clani.py` bi
          odgovor nosil `SPOROCILO_NE_SEBE` in ta test bi padel.
        """
        for odgovor in (
            odjemalec.get(pot_clana(stars, "deactivate")),
            odjemalec.post(pot_clana(stars, "deactivate")),
        ):
            assert odgovor.status_code == 403
            assert clani.SPOROCILO_ZADNJI_STARS in odgovor.text
            assert clani.SPOROCILO_NE_SEBE not in odgovor.text

        with Session(motor) as seja:
            oseba = seja.get(User, stars)
            assert oseba is not None and oseba.is_active is True

    def test_aktivnih_starsev_steje_samo_aktivne_starse_te_druzine(
        self, motor: Engine, stars: str, otrok: str
    ) -> None:
        """Število, na katerem pravilo stoji, mora šteti pravo stvar."""
        ustvari_starsa(
            motor, identifikator="bivsa@primer.test", prikazno_ime="Bivša", aktiven=False
        )
        dodaj_druzino(motor)
        ustvari_starsa(
            motor, family_id=DRUGA_ID, identifikator="tuj@primer.test", prikazno_ime="Tuj"
        )

        with Session(motor) as seja:
            koliko = ClaniRepository(seja, CVEK_ID).aktivnih_starsev()

        # Otrok ni starš, deaktivirana ni aktivna, tuja ni naša.
        assert koliko == 1

        ustvari_starsa(motor, identifikator="druga@primer.test", prikazno_ime="Druga")
        with Session(motor) as seja:
            assert ClaniRepository(seja, CVEK_ID).aktivnih_starsev() == 2

    def test_lastnika_sistema_ni_mogoce_deaktivirati(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, lastnik: str
    ) -> None:
        """Velja tudi takrat, ko v družini ostane dovolj aktivnih staršev."""
        ustvari_starsa(motor, identifikator="druga@primer.test", prikazno_ime="Druga")

        odgovor = odjemalec.post(pot_clana(lastnik, "deactivate"))

        assert odgovor.status_code == 403
        assert clani.SPOROCILO_LASTNIK_SISTEMA in odgovor.text
        with Session(motor) as seja:
            oseba = seja.get(User, lastnik)
            assert oseba is not None and oseba.is_active is True

    def test_ze_deaktiviranega_ni_kaj_deaktivirati(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        bivsi = ustvari_otroka(motor, identifikator="bivsi", prikazno_ime="Bivši", aktiven=False)

        odgovor = odjemalec.post(pot_clana(bivsi, "deactivate"))

        assert odgovor.status_code == 409
        assert clani.SPOROCILO_ZE_DEAKTIVIRAN in odgovor.text


class TestAktivacija:
    """`ADR-038` A: deaktivacija je obrnljiva, seje pa se ne vrnejo."""

    def test_deaktiviran_otrok_se_po_aktivaciji_spet_poveze(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str, telefon: SejaTesta
    ) -> None:
        odjemalec.post(pot_clana(otrok, "deactivate"))
        assert odjemalec.post(pot_clana(otrok, "link")).status_code == 403

        odgovor = odjemalec.post(pot_clana(otrok, "activate"), follow_redirects=False)

        assert odgovor.status_code == 303
        assert povezi(odjemalec, zeton_s_strani(odjemalec, otrok)).status_code == 200

    def test_seje_iz_pred_deaktivacije_se_ne_vrnejo(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str, telefon: SejaTesta
    ) -> None:
        odjemalec.post(pot_clana(otrok, "deactivate"))

        odjemalec.post(pot_clana(otrok, "activate"))

        assert sej(motor, otrok) == 0
        assert odjemalec.get("/quizzes/pending", headers=telefon.glave).status_code == 401

    def test_ze_aktivnega_ni_kaj_aktivirati(
        self, odjemalec: PrijavljenOdjemalec, otrok: str
    ) -> None:
        odgovor = odjemalec.post(pot_clana(otrok, "activate"))

        assert odgovor.status_code == 409
        assert clani.SPOROCILO_ZE_AKTIVEN in odgovor.text


class TestNeznanClan:
    """Meje družine dokazuje `test_tesnjenje.py`; tu je le, da se ne ločita."""

    @pytest.mark.parametrize("dejanje", ["password", "deactivate", "activate", "revoke"])
    @pytest.mark.parametrize("metoda", ["GET", "POST"])
    def test_neznan_user_id_je_404(
        self, odjemalec: PrijavljenOdjemalec, dejanje: str, metoda: str
    ) -> None:
        izmisljen = "11111111-2222-4333-8444-555555555555"
        pot = pot_clana(izmisljen, dejanje)

        # `post` odjemalca doda CSRF žeton; `request` ga ne bi in odgovor bi
        # bil `403` iz vmesne plasti, ki pot pregleda pred usmerjevalnikom.
        odgovor = (
            odjemalec.get(pot, follow_redirects=False)
            if metoda == "GET"
            else odjemalec.post(pot, follow_redirects=False)
        )

        assert odgovor.status_code == 404
        # Isto besedilo kot za tujega člana (`test_tesnjenje.py`): razlika bi
        # povedala, da tuj račun obstaja.
        assert "Tega člana ni v tvoji družini" in odgovor.text

    def test_neznanemu_user_id_koda_ne_nastane(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """`POST …/link` ima svoj test: njegov `GET` namenoma ne pogleda v bazo."""
        odgovor = odjemalec.post(pot_clana("11111111-2222-4333-8444-555555555555", "link"))

        assert odgovor.status_code == 404
        assert "Tega člana ni v tvoji družini" in odgovor.text
        assert povezav(motor) == 0


class TestPravila:
    """Pravila brez HTTP — kar velja tu, velja na vseh poteh, ki jih kličejo."""

    def test_sebe_ne(self) -> None:
        assert (
            clani.zakaj_ne_sme_deaktivirati(
                izvajalec_id="jaz",
                clan_id="jaz",
                clan_vloga=VLOGA_STARS,
                clan_je_lastnik_sistema=False,
                aktivnih_starsev=5,
            )
            == clani.SPOROCILO_NE_SEBE
        )

    def test_edini_stars_dobi_zadnjega_starsa_in_ne_sebe(self) -> None:
        """Vrstni red pravil: izvedljiv nasvet prevlada nad „sebe ne".

        Oba pogoja sta izpolnjena hkrati (cilj sem jaz **in** sem zadnji
        aktivni starš); pravilo, ki pove izvedljiv naslednji korak, mora
        zmagati (`CLAUDE.md` §1b).
        """
        assert (
            clani.zakaj_ne_sme_deaktivirati(
                izvajalec_id="jaz",
                clan_id="jaz",
                clan_vloga=VLOGA_STARS,
                clan_je_lastnik_sistema=False,
                aktivnih_starsev=1,
            )
            == clani.SPOROCILO_ZADNJI_STARS
        )

    def test_zadnji_aktivni_stars_ne(self) -> None:
        assert (
            clani.zakaj_ne_sme_deaktivirati(
                izvajalec_id="jaz",
                clan_id="drugi",
                clan_vloga=VLOGA_STARS,
                clan_je_lastnik_sistema=False,
                aktivnih_starsev=1,
            )
            == clani.SPOROCILO_ZADNJI_STARS
        )

    def test_otroka_pravilo_zadnjega_starsa_ne_zadeva(self) -> None:
        """Družina brez aktivnega otroka je dopustna; brez starša ni."""
        assert (
            clani.zakaj_ne_sme_deaktivirati(
                izvajalec_id="jaz",
                clan_id="otrok",
                clan_vloga=VLOGA_OTROK,
                clan_je_lastnik_sistema=False,
                aktivnih_starsev=1,
            )
            is None
        )

    def test_dva_aktivna_starsa_dopuscata_deaktivacijo(self) -> None:
        assert (
            clani.zakaj_ne_sme_deaktivirati(
                izvajalec_id="jaz",
                clan_id="drugi",
                clan_vloga=VLOGA_STARS,
                clan_je_lastnik_sistema=False,
                aktivnih_starsev=2,
            )
            is None
        )

    def test_lastnik_sistema_sebi_sme_drug_pa_ne(self) -> None:
        assert (
            clani.zakaj_ne_sme_ponastaviti_gesla(
                izvajalec_id="lastnik",
                clan_id="lastnik",
                clan_vloga=VLOGA_STARS,
                clan_je_lastnik_sistema=True,
            )
            is None
        )
        assert (
            clani.zakaj_ne_sme_ponastaviti_gesla(
                izvajalec_id="drug",
                clan_id="lastnik",
                clan_vloga=VLOGA_STARS,
                clan_je_lastnik_sistema=True,
            )
            == clani.SPOROCILO_TUJE_GESLO_LASTNIKA
        )

    def test_otrok_gesla_nima_zato_ga_nihce_ne_ponastavi(self) -> None:
        """`V6-R01`: pravilo velja tudi, če bi otrok to poskusil zase."""
        for izvajalec in ("stars", "otrok"):
            assert (
                clani.zakaj_ne_sme_ponastaviti_gesla(
                    izvajalec_id=izvajalec,
                    clan_id="otrok",
                    clan_vloga=VLOGA_OTROK,
                    clan_je_lastnik_sistema=False,
                )
                == clani.SPOROCILO_OTROK_NIMA_GESLA
            )

    @pytest.mark.parametrize(
        ("vloga", "aktiven", "pricakovano"),
        [
            (VLOGA_OTROK, True, None),
            (VLOGA_OTROK, False, clani.SPOROCILO_POVEZAVA_DEAKTIVIRANEMU),
            (VLOGA_STARS, True, clani.SPOROCILO_TELEFON_SAMO_OTROKU),
            (VLOGA_STARS, False, clani.SPOROCILO_TELEFON_SAMO_OTROKU),
        ],
    )
    def test_telefon_se_poveze_samo_aktivnemu_otroku(
        self, vloga: str, aktiven: bool, pricakovano: str | None
    ) -> None:
        assert (
            clani.zakaj_ne_sme_povezati_telefona(clan_vloga=vloga, clan_aktiven=aktiven)
            == pricakovano
        )

    def test_prijave_se_preklicejo_samo_otroku(self) -> None:
        assert clani.zakaj_ne_sme_preklicati_prijav(clan_vloga=VLOGA_OTROK) is None
        assert (
            clani.zakaj_ne_sme_preklicati_prijav(clan_vloga=VLOGA_STARS)
            == clani.SPOROCILO_PREKLIC_SAMO_OTROKU
        )

    def test_predolg_vnos_se_zavrne_preden_pride_do_baze(self) -> None:
        """Meja je širina stolpca; na SQLite je baza ne bi uveljavila."""
        assert clani.preveri_prikazno_ime("x" * 201) == clani.SPOROCILO_PREDOLGO_IME
        assert clani.preveri_prikazno_ime("x" * 200) is None
        assert clani.preveri_enaslov("x" * 310 + "@primer.test") == clani.SPOROCILO_PREDOLG_ENASLOV

    def test_normalizacija_je_obrez_in_male_crke(self) -> None:
        assert prijava.normaliziraj_identifikator("  Masa@Primer.TEST ") == "masa@primer.test"


class TestPrevodNapakeBaze:
    """Zasedeno ime se od vsake druge kršitve integritete mora ločiti."""

    @pytest.mark.parametrize(
        "besedilo",
        [
            "UNIQUE constraint failed: credentials.identifier",
            'duplicate key value violates unique constraint "credentials_identifier_key"',
        ],
        ids=["sqlite", "postgres"],
    )
    def test_zasedeno_ime_prepozna_oba_dialekta(self, besedilo: str) -> None:
        assert je_zaseden_identifikator(IntegrityError("stavek", None, Exception(besedilo)))

    @pytest.mark.parametrize(
        "besedilo",
        [
            'insert or update on table "users" violates foreign key constraint'
            ' "fk_users_family_id"',
            "UNIQUE constraint failed: sessions.token_hash",
        ],
        ids=["tuji-kljuc", "druga-enolicnost"],
    )
    def test_druga_krsitev_se_ne_predstavi_kot_zasedeno_ime(self, besedilo: str) -> None:
        """Sicer bi napaka poslala uporabnico iskat drugo ime, ki ni težava."""
        assert not je_zaseden_identifikator(IntegrityError("stavek", None, Exception(besedilo)))

    def test_ustvari_clana_druge_krsitve_ne_pogoltne(
        self, motor: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nepričakovana kršitev integritete mora priti ven, ne v sporočilo.

        Sprožilec je trčenje primarnega ključa `users.id`, ne tuji ključ:
        SQLite tujih ključev privzeto ne uveljavlja (`docs/01-arhitektura.md`),
        zato bi bil test nad njim zelen iz napačnega razloga. Vnaprej znan
        `uuid4` je edini način, kako v tej bazi ustvariti kršitev, ki **ni**
        zasedeni identifikator.
        """
        monkeypatch.setattr(
            "app.db.uuid4", lambda: "11111111-1111-4111-8111-111111111111"
        )
        with Session(motor) as seja:
            repo = ClaniRepository(seja, CVEK_ID)
            repo.ustvari_clana(
                role=VLOGA_OTROK,
                display_name="Prva",
                identifier="prva",
                secret_hash="x",
                ko=datetime.now(UTC),
            )

            # Drug identifikator, isti `id` osebe: to ni zasedeno ime.
            with pytest.raises(IntegrityError):
                repo.ustvari_clana(
                    role=VLOGA_OTROK,
                    display_name="Druga",
                    identifier="druga",
                    secret_hash="x",
                    ko=datetime.now(UTC),
                )


class TestOkoliska:
    """Kar se je moralo spremeniti drugje, da ta zahteva drži."""

    def test_prijava_ne_locuje_velikih_in_malih_crk(
        self, aplikacija: FastAPI, motor: Engine, stars: str
    ) -> None:
        """`ADR-038` E: sicer bi enoličnost imena pomenila nekaj drugega."""
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            odgovor = prijavi_se(odjemalec, STARS_IDENTIFIKATOR.upper(), GESLO_STARSA)

        assert odgovor.status_code == 303

    def test_omejevanje_ugibanja_se_z_velikimi_crkami_ne_izmuzne(
        self, aplikacija: FastAPI, motor: Engine, stars: str
    ) -> None:
        """Števec teče po normaliziranem identifikatorju, ne po vtipkanem."""
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            for _ in range(prijava.PRAG_POSKUSOV):
                prijavi_se(odjemalec, STARS_IDENTIFIKATOR, "to-geslo-ni-pravo")

        with Session(motor) as seja:
            repo_zamik = prijava.koliko_cakati(
                PrijavaRepository(seja), STARS_IDENTIFIKATOR.upper(), datetime.now(UTC)
            )

        assert repo_zamik == prijava.ZAMIK_SEKUND
