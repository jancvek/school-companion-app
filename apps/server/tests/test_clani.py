"""Starš upravlja uporabnike svoje družine (V3-R06).

Pokriva tabelo „Test casi" iz `docs/plan/V3-R06.md`; odločitve so v
`docs/odlocitve/ADR-038`, pravila v `app/clani.py`.

Meje družine ta datoteka **ne** dokazuje — to počne `tests/test_tesnjenje.py`
za vsako od devetih poti in za vsako javno metodo `ClaniRepository`, z dvema
resničnima družinama in s posnetkom stanja pred in po. Tu je zato samo
neobstoječ `user_id`: da je besedilo `404` isto kot za tujega člana in da se ta
dva primera navzven ne ločita.

Vsak test, ki pravi „geslo deluje", gre skozi **pravo prijavno pot** in ne
primerja zgostitev: zgostitev, ki se ujema sama s sabo, ne dokaže, da se z njo
da prijaviti.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app import clani, prijava
from app.db import PrijavaRepository
from app.models import VLOGA_OTROK, VLOGA_STARS, Credential, Material, User, UserSession
from tests.conftest import (
    CVEK_ID,
    GESLO_OTROKA,
    GESLO_STARSA,
    OTROK_IDENTIFIKATOR,
    STARS_IDENTIFIKATOR,
    PrijavljenOdjemalec,
    SejaTesta,
    prijavi,
    ustvari_otroka,
    ustvari_sejo,
    ustvari_starsa,
)
from tests.test_kvizi import UUID_ENA, snov
from tests.test_prijava import prijavi_se

POT = "/admin/family"

#: Vnosa, ki ju obrazca sprejmeta, kadar test ne preizkuša prav vnosa.
NOV_OTROK = {
    "ime": "Nika",
    "uporabnisko_ime": "nika",
    "geslo": "nikino-geslo",
    "geslo_znova": "nikino-geslo",
}
NOV_STARS = {
    "ime": "Ana",
    "enaslov": "ana@primer.test",
    "geslo": "anino-geslo-12",
    "geslo_znova": "anino-geslo-12",
}


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


def prijava_otroka(
    odjemalec: PrijavljenOdjemalec, geslo: str, ime: str = OTROK_IDENTIFIKATOR
) -> Any:
    """Prijava otroka po pravi poti telefona (V3-R04)."""
    return odjemalec.post("/auth/login", json={"identifier": ime, "password": geslo})


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
        assert OTROK_IDENTIFIKATOR in besedilo
        assert "starš" in besedilo
        assert "otrok" in besedilo
        assert "deaktiviran račun" in besedilo

    def test_racun_brez_gesla_je_oznacen(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Stanje, v katerem uporabnika pusti migracija (`ADR-035` G)."""
        ustvari_otroka(motor, identifikator="brez", prikazno_ime="Brez", geslo=None)

        assert "geslo ni nastavljeno" in odjemalec.get(POT).text

    def test_povezava_je_na_pregledu(self, odjemalec: PrijavljenOdjemalec) -> None:
        """Brez vhoda s `/admin` je stran dosegljiva samo z vtipkanim naslovom."""
        assert f'href="{POT}"' in odjemalec.get("/admin").text


class TestDodajanjeOtroka:
    """Kriterij: prikazno ime, uporabniško ime, začetno geslo. Brez e-naslova."""

    def test_otrok_nastane_in_se_z_geslom_prijavi_v_aplikaciji(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        odgovor = odjemalec.post(f"{POT}/children", data=NOV_OTROK, follow_redirects=False)

        assert odgovor.status_code == 303
        nova = uporabnik(motor, "nika")
        assert nova is not None
        assert nova.role == VLOGA_OTROK
        assert nova.family_id == CVEK_ID
        assert nova.is_active is True
        assert nova.is_system_owner is False
        assert prijava_otroka(odjemalec, NOV_OTROK["geslo"], "nika").status_code == 200

    def test_uporabnisko_ime_se_normalizira(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """`ADR-038` E: brez tega bi `Nika` in `nika` bila dva računa."""
        odjemalec.post(f"{POT}/children", data={**NOV_OTROK, "uporabnisko_ime": "  NiKa "})

        assert uporabnik(motor, "nika") is not None

    def test_zasedeno_ime_ne_ustvari_nicesar(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str
    ) -> None:
        odgovor = odjemalec.post(
            f"{POT}/children", data={**NOV_OTROK, "uporabnisko_ime": OTROK_IDENTIFIKATOR}
        )

        assert odgovor.status_code == 400
        assert clani.SPOROCILO_IDENTIFIKATOR_ZASEDEN in odgovor.text
        assert uporabnik(motor, "nika") is None
        with Session(motor) as seja:
            assert len(list(seja.scalars(select(User.id)))) == 2

    def test_zasedenost_ne_ubeze_z_velikimi_crkami(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str
    ) -> None:
        """Normalizacija teče **pred** vstavljanjem, sicer bi nastal dvojnik."""
        odgovor = odjemalec.post(
            f"{POT}/children", data={**NOV_OTROK, "uporabnisko_ime": OTROK_IDENTIFIKATOR.upper()}
        )

        assert odgovor.status_code == 400
        assert clani.SPOROCILO_IDENTIFIKATOR_ZASEDEN in odgovor.text

    @pytest.mark.parametrize(
        ("polje", "vrednost", "sporocilo"),
        [
            ("ime", "   ", clani.SPOROCILO_PRAZNO_IME),
            ("uporabnisko_ime", "", clani.SPOROCILO_PRAZNO_UPORABNISKO_IME),
            ("uporabnisko_ime", "nika@primer.test", clani.SPOROCILO_UPORABNISKO_IME_Z_AFNO),
            ("uporabnisko_ime", "ni ka", clani.SPOROCILO_PRESLEDEK_V_IMENU),
            ("geslo", "kratko", None),
        ],
        ids=["prazno-ime", "prazno-uporabnisko", "afna", "presledek", "kratko-geslo"],
    )
    def test_neveljaven_vnos_ne_ustvari_nicesar(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        polje: str,
        vrednost: str,
        sporocilo: str | None,
    ) -> None:
        podatki = {**NOV_OTROK, polje: vrednost}
        if polje == "geslo":
            podatki["geslo_znova"] = vrednost

        odgovor = odjemalec.post(f"{POT}/children", data=podatki)

        assert odgovor.status_code == 400
        if sporocilo is not None:
            assert sporocilo in odgovor.text
        else:
            assert "vsaj 8" in odgovor.text
        assert uporabnik(motor, "nika") is None
        assert uporabnik(motor, "nika@primer.test") is None

    def test_neujemanje_gesel_ne_ustvari_nicesar(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        odgovor = odjemalec.post(
            f"{POT}/children", data={**NOV_OTROK, "geslo_znova": "nekaj-drugega"}
        )

        assert odgovor.status_code == 400
        assert clani.SPOROCILO_GESLI_SE_NE_UJEMATA in odgovor.text
        assert uporabnik(motor, "nika") is None

    def test_vnos_se_vrne_geslo_pa_nikoli(self, odjemalec: PrijavljenOdjemalec) -> None:
        """Kriterij `ADR-038` F: geslo ne sme pristati v HTML."""
        odgovor = odjemalec.post(
            f"{POT}/children", data={**NOV_OTROK, "geslo_znova": "nekaj-drugega"}
        )

        assert 'value="Nika"' in odgovor.text
        assert 'value="nika"' in odgovor.text
        assert NOV_OTROK["geslo"] not in odgovor.text


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

    def test_starsevo_geslo_je_daljse_od_otrokovega(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Enajst znakov je dovolj za otroka in premalo za starša (`ADR-036` E)."""
        kratko = "enajst-zna"

        odgovor = odjemalec.post(
            f"{POT}/parents", data={**NOV_STARS, "geslo": kratko, "geslo_znova": kratko}
        )

        assert odgovor.status_code == 400
        assert "vsaj 12" in odgovor.text
        assert uporabnik(motor, "ana@primer.test") is None


class TestPonastavitevGesla:
    """Kriterij: ponastavitev prekliče vse seje uporabnika, na vseh napravah."""

    def test_novo_geslo_dela_staro_ne_in_seje_padejo(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str, telefon: SejaTesta
    ) -> None:
        druga_naprava = ustvari_sejo(motor, otrok)
        assert sej(motor, otrok) == 2
        novo = "novo-geslo-masa"

        odgovor = odjemalec.post(
            pot_clana(otrok, "password"),
            data={"geslo": novo, "geslo_znova": novo},
            follow_redirects=False,
        )

        assert odgovor.status_code == 303
        assert sej(motor, otrok) == 0
        assert prijava_otroka(odjemalec, GESLO_OTROKA).status_code == 401
        assert prijava_otroka(odjemalec, novo).status_code == 200
        # Obe seji sta bili preklicani, ne samo tista, ki je bila pri roki.
        assert odjemalec.get("/quizzes/pending", headers=telefon.glave).status_code == 401
        assert odjemalec.get("/quizzes/pending", headers=druga_naprava.glave).status_code == 401

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
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str, telefon: SejaTesta
    ) -> None:
        prej = zgostitev_v_bazi(motor, OTROK_IDENTIFIKATOR)

        odgovor = odjemalec.post(
            pot_clana(otrok, "password"), data={"geslo": "kratko", "geslo_znova": "kratko"}
        )

        assert odgovor.status_code == 400
        assert zgostitev_v_bazi(motor, OTROK_IDENTIFIKATOR) == prej
        assert sej(motor, otrok) == 1

    def test_vmesna_stran_sama_ne_spremeni_nicesar(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str, telefon: SejaTesta
    ) -> None:
        """Kriterij: dejanje je `POST`, ne `GET`."""
        prej = zgostitev_v_bazi(motor, OTROK_IDENTIFIKATOR)

        odgovor = odjemalec.get(pot_clana(otrok, "password"))

        assert odgovor.status_code == 200
        assert "Maša" in odgovor.text
        assert zgostitev_v_bazi(motor, OTROK_IDENTIFIKATOR) == prej
        assert sej(motor, otrok) == 1

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
                    role=VLOGA_OTROK,
                    display_name="Brez poverilnice",
                    is_system_owner=False,
                    is_active=True,
                    created_at=datetime.now(UTC),
                )
            )
            seja.commit()

        odgovor = odjemalec.post(
            pot_clana(brez, "password"),
            data={"geslo": "novo-geslo-tu", "geslo_znova": "novo-geslo-tu"},
            follow_redirects=False,
        )

        assert odgovor.status_code == 409
        assert clani.SPOROCILO_NI_SPREMENJENO in odgovor.text

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


class TestDeaktivacija:
    """Kriterij: prijava ne gre več, seje padejo, podatki ostanejo."""

    def test_otrok_se_ne_prijavi_seje_padejo_podatki_ostanejo(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        slike: Any,
        otrok: str,
        telefon: SejaTesta,
    ) -> None:
        snov(motor, slike, UUID_ENA)

        odgovor = odjemalec.post(pot_clana(otrok, "deactivate"), follow_redirects=False)

        assert odgovor.status_code == 303
        assert sej(motor, otrok) == 0
        assert prijava_otroka(odjemalec, GESLO_OTROKA).status_code == 401
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

    def test_zadnjega_aktivnega_starsa_ni_mogoce_deaktivirati(
        self, aplikacija: FastAPI, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Drugi starš ga sme deaktivirati **šele**, ko v družini ostane še kdo."""
        drugi = ustvari_starsa(motor, identifikator="druga@primer.test", prikazno_ime="Druga")
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as drug:
            prijavi(drug, motor, drugi)
            # Zdaj sta aktivna dva: prvi pade.
            assert drug.post(
                pot_clana(stars, "deactivate"), follow_redirects=False
            ).status_code == 303
            # Ostal je en sam aktiven starš — in to je ta, ki kliče.
            zavrnjeno = drug.post(pot_clana(drugi, "deactivate"))

        assert zavrnjeno.status_code == 403
        with Session(motor) as seja:
            oseba = seja.get(User, drugi)
            assert oseba is not None and oseba.is_active is True

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

    def test_deaktiviran_otrok_se_po_aktivaciji_spet_prijavi(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, otrok: str, telefon: SejaTesta
    ) -> None:
        odjemalec.post(pot_clana(otrok, "deactivate"))
        assert prijava_otroka(odjemalec, GESLO_OTROKA).status_code == 401

        odgovor = odjemalec.post(pot_clana(otrok, "activate"), follow_redirects=False)

        assert odgovor.status_code == 303
        assert prijava_otroka(odjemalec, GESLO_OTROKA).status_code == 200

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

    @pytest.mark.parametrize("dejanje", ["password", "deactivate", "activate"])
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
                izvajalec_id="lastnik", clan_id="lastnik", clan_je_lastnik_sistema=True
            )
            is None
        )
        assert (
            clani.zakaj_ne_sme_ponastaviti_gesla(
                izvajalec_id="drug", clan_id="lastnik", clan_je_lastnik_sistema=True
            )
            == clani.SPOROCILO_TUJE_GESLO_LASTNIKA
        )

    def test_predolg_vnos_se_zavrne_preden_pride_do_baze(self) -> None:
        """Meja je širina stolpca; na SQLite je baza ne bi uveljavila."""
        assert clani.preveri_prikazno_ime("x" * 201) == clani.SPOROCILO_PREDOLGO_IME
        assert clani.preveri_prikazno_ime("x" * 200) is None
        assert (
            clani.preveri_uporabnisko_ime("x" * 321) == clani.SPOROCILO_PREDOLGO_UPORABNISKO_IME
        )

    def test_normalizacija_je_obrez_in_male_crke(self) -> None:
        assert prijava.normaliziraj_identifikator("  Masa@Primer.TEST ") == "masa@primer.test"


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
