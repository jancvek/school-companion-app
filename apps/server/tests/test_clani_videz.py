"""Družina po V5-R01: kartice članov, oznaka Google, napaka ob polju, potrditev.

Pravila o članih (kdo sme koga, kode zavrnitev, seje) varuje `test_clani.py`.
Tu je, kar je V5-R01 dodala po `docs/poc/POC-02.md`, posnetki 12 do 14.
"""

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db import ClaniRepository
from app.main import create_app
from app.models import Credential
from tests.conftest import (
    BRAT_ID,
    CVEK_ID,
    OTROK_ID,
    STARS_IDENTIFIKATOR,
    PrijavljenOdjemalec,
    naredi_testne_nastavitve,
    prijavi,
    ustvari_starsa,
    vsebina_strani,
)

POT = "/admin/family"


@pytest.fixture(autouse=True)
def _druzina_ima_otroka(otrok: str) -> str:
    return otrok


def povezi_google(motor: Engine, user_id: str) -> None:
    """Google poverilnica na računu, kot jo zapiše `V3-R08`."""
    zdaj = datetime.now(UTC)
    with Session(motor) as seja:
        seja.add(
            Credential(
                id=str(uuid4()),
                user_id=user_id,
                kind="google",
                identifier=f"sub-{user_id}",
                secret_hash=None,
                label="nekdo@gmail.test",
                created_at=zdaj,
                updated_at=zdaj,
            )
        )
        seja.commit()


@pytest.fixture
def odjemalec_g(slike: object, motor: Engine, stars: str) -> Iterator[PrijavljenOdjemalec]:
    """Prijavljen starš v namestitvi, ki Googla **ima**."""
    nastavitve = naredi_testne_nastavitve(slike).model_copy(  # type: ignore[arg-type]
        update={
            "google_client_id": "odjemalec-1",
            "google_client_secret": "skrivnost-1",
            "domena": "solski.test",
        }
    )
    aplikacija = create_app(nastavitve=nastavitve, motor=motor)
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
        prijavi(odjemalec, motor, stars)
        yield odjemalec


def kartica(besedilo: str, ime: str) -> str:
    """Kartica člana z danim imenom, od `<li class="clan` do `</li>`."""
    for blok in re.findall(r'<li class="clan.*?</li>', besedilo, re.S):
        if f"<h3>{ime}</h3>" in blok:
            return blok
    raise AssertionError(f"kartice {ime} ni")


def oznake(blok: str) -> list[str]:
    return re.findall(r'<span class="oznaka[^"]*">([^<]+)</span>', blok)


class TestRepozitorij:
    def test_clan_pove_ali_ima_google(self, motor: Engine, stars: str) -> None:
        z_googlom = ustvari_starsa(motor, identifikator="ana@primer.test", prikazno_ime="Ana")
        povezi_google(motor, z_googlom)

        with Session(motor) as seja:
            clani = {clan.display_name: clan for clan in ClaniRepository(seja, CVEK_ID).clani()}

        assert clani["Ana"].google_povezan is True
        assert clani["Dejan"].google_povezan is False
        assert clani["Maša"].google_povezan is False
        # Google poverilnica ne podvoji vrstice in ne zamenja identifikatorja.
        assert len(clani) == 3
        assert clani["Ana"].identifier == "ana@primer.test"


class TestKartice:
    def test_otroci_in_starsi_sta_loceni_skupini(self, odjemalec: TestClient) -> None:
        vsebina = vsebina_strani(odjemalec.get(POT).text)

        otroci = vsebina[vsebina.index("<h2>Otroci</h2>") : vsebina.index("<h2>Starši</h2>")]
        starsi = vsebina[vsebina.index("<h2>Starši</h2>") :]
        assert "<h3>Maša</h3>" in otroci and "<h3>Dejan</h3>" not in otroci
        assert "<h3>Dejan</h3>" in starsi and "<h3>Maša</h3>" not in starsi
        assert "<h1>Družina Cvek</h1>" in vsebina

    def test_kartica_starsa_pove_da_si_to_ti(self, odjemalec: TestClient) -> None:
        blok = kartica(odjemalec.get(POT).text, "Dejan")

        assert oznake(blok) == ["to si ti", "aktiven račun"]
        assert f"<strong>{STARS_IDENTIFIKATOR}</strong>" in blok

    def test_kartica_otroka_vodi_na_njegov_urnik(
        self, odjemalec: TestClient, brat: str
    ) -> None:
        besedilo = odjemalec.get(POT).text

        assert f'<a href="/admin/schedule?otrok={OTROK_ID}">Urnik</a>' in kartica(besedilo, "Maša")
        assert f'<a href="/admin/schedule?otrok={BRAT_ID}">Urnik</a>' in kartica(besedilo, "Nejc")
        assert "Urnik</a>" not in kartica(besedilo, "Dejan")

    def test_pri_enem_otroku_povezava_na_urnik_nima_parametra(
        self, odjemalec: TestClient
    ) -> None:
        assert '<a href="/admin/schedule">Urnik</a>' in kartica(odjemalec.get(POT).text, "Maša")

    def test_deaktiviran_clan_je_oznacen_in_ima_samo_aktivacijo(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        ustvari_starsa(motor, identifikator="ana@primer.test", prikazno_ime="Ana", aktiven=False)

        blok = kartica(odjemalec.get(POT).text, "Ana")

        assert '<li class="clan deaktiviran">' in blok
        assert "deaktiviran račun" in oznake(blok)
        assert re.findall(r'<a[^>]*href="[^"]+/(\w+)"', blok) == ["password", "activate"]

    def test_unicujoce_dejanje_je_oznaceno(self, odjemalec: TestClient, motor: Engine) -> None:
        ustvari_starsa(motor, identifikator="ana@primer.test", prikazno_ime="Ana")

        blok = kartica(odjemalec.get(POT).text, "Ana")

        assert re.search(r'<a class="nevarno" href="[^"]+/deactivate">Deaktiviraj</a>', blok)


class TestOznakaGoogle:
    def test_google_in_geslo(self, odjemalec_g: TestClient, motor: Engine, stars: str) -> None:
        povezi_google(motor, stars)

        blok = kartica(odjemalec_g.get(POT).text, "Dejan")

        assert "Google in geslo" in oznake(blok)
        assert ">Ponastavi geslo</a>" in blok

    def test_samo_google_ponudi_nastavitev_gesla(
        self, odjemalec_g: TestClient, motor: Engine
    ) -> None:
        brez_gesla = ustvari_starsa(
            motor, identifikator="maja@primer.test", prikazno_ime="Maja", geslo=None
        )
        povezi_google(motor, brez_gesla)

        blok = kartica(odjemalec_g.get(POT).text, "Maja")

        assert "samo Google" in oznake(blok)
        # „Geslo ni nastavljeno" bi bilo ob „samo Google" isto povedano dvakrat.
        assert "geslo ni nastavljeno" not in oznake(blok)
        assert ">Nastavi geslo</a>" in blok

    def test_samo_geslo_nima_oznake(self, odjemalec_g: TestClient) -> None:
        blok = kartica(odjemalec_g.get(POT).text, "Dejan")

        assert not any("Google" in oznaka for oznaka in oznake(blok))

    def test_racun_brez_gesla_in_brez_googla_to_pove(
        self, odjemalec_g: TestClient, motor: Engine
    ) -> None:
        ustvari_starsa(motor, identifikator="maja@primer.test", prikazno_ime="Maja", geslo=None)

        assert "geslo ni nastavljeno" in oznake(kartica(odjemalec_g.get(POT).text, "Maja"))

    def test_namestitev_brez_googla_oznake_ne_kaze(
        self, odjemalec: TestClient, motor: Engine, stars: str
    ) -> None:
        # Poverilnica obstaja, a ta namestitev Googla nima (`ADR-046` F).
        povezi_google(motor, stars)

        besedilo = odjemalec.get(POT).text

        assert "Google" not in vsebina_strani(besedilo)
        assert "Moj račun" not in besedilo

    def test_moj_racun_samo_na_svoji_kartici(
        self, odjemalec_g: TestClient, motor: Engine
    ) -> None:
        ustvari_starsa(motor, identifikator="ana@primer.test", prikazno_ime="Ana")

        besedilo = odjemalec_g.get(POT).text

        assert '<a href="/admin/racun">Moj račun</a>' in kartica(besedilo, "Dejan")
        assert "Moj račun" not in kartica(besedilo, "Ana")


class TestDodajanje:
    def test_obrazca_sta_zlozena_in_ohranita_poti_in_polja(
        self, odjemalec: TestClient
    ) -> None:
        """`ADR-056` I: isti `POST`, ista imena polj.

        Od `V6-R01` ima obrazec za otroka samo prikazno ime (`ADR-058` A).
        """
        besedilo = odjemalec.get(POT).text

        assert '<details class="kartica" id="dodaj-otroka">' in besedilo
        assert '<details class="kartica" id="dodaj-starsa">' in besedilo
        assert '<form method="post" action="/admin/family/children">' in besedilo
        assert '<form method="post" action="/admin/family/parents">' in besedilo
        polja = re.findall(r'<input type="(?:text|password)" id="[^"]+" name="([^"]+)"', besedilo)
        assert polja == ["ime", "ime", "enaslov", "geslo", "geslo_znova"]

    @pytest.mark.parametrize(
        ("dodaj", "odprt"), [("otrok", "dodaj-otroka"), ("stars", "dodaj-starsa")]
    )
    def test_gumb_na_vrhu_odpre_obrazec_brez_skripte(
        self, odjemalec: TestClient, dodaj: str, odprt: str
    ) -> None:
        zacetna = odjemalec.get(POT).text
        besedilo = odjemalec.get(f"{POT}?dodaj={dodaj}").text

        assert f'href="/admin/family?dodaj={dodaj}#{odprt}"' in zacetna
        assert re.findall(r'<details class="kartica" id="([^"]+)" open>', besedilo) == [odprt]
        assert "<script" not in besedilo.lower()

    def test_neznana_vrednost_ne_odpre_nicesar(self, odjemalec: TestClient) -> None:
        assert " open>" not in odjemalec.get(f"{POT}?dodaj=vse").text

    @pytest.mark.parametrize(
        ("pot", "odprt", "podatki", "ob"),
        [
            ("children", "dodaj-otroka", {"ime": ""}, "otrok-ime"),
            (
                "parents",
                "dodaj-starsa",
                {"ime": "", "enaslov": "nov@primer.test", "geslo": "geslo-1234-56"},
                "stars-ime",
            ),
            (
                "parents",
                "dodaj-starsa",
                {"ime": "Nov", "enaslov": "ni naslov", "geslo": "geslo-1234-56"},
                "stars-enaslov",
            ),
            (
                "parents",
                "dodaj-starsa",
                {"ime": "Nov", "enaslov": "nov@primer.test", "geslo": "kratko"},
                "stars-geslo",
            ),
        ],
    )
    def test_napaka_stoji_ob_polju_ki_jo_je_povzrocilo(
        self, odjemalec: TestClient, pot: str, odprt: str, podatki: dict[str, str], ob: str
    ) -> None:
        """Otrok ima od `V6-R01` eno samo polje; ostala tri mesta dokazuje starš."""
        odgovor = odjemalec.post(
            f"{POT}/{pot}", data={**podatki, "geslo_znova": podatki.get("geslo", "")}
        )

        assert odgovor.status_code == 400
        besedilo = odgovor.text
        # Natanko ena napaka, v obrazcu, ki je odprt.
        assert besedilo.count('class="napaka-polja"') == 1
        assert re.findall(r'<details class="kartica" id="([^"]+)" open>', besedilo) == [odprt]
        zacetek = besedilo.index(f'id="{ob}"')
        do_napake = besedilo[zacetek : besedilo.index('class="napaka-polja"', zacetek)]
        # Med poljem in napako ni drugega polja z drugo skupino.
        assert do_napake.count('<div class="polje') <= 1
        assert do_napake.count("z-napako") == 0
        assert besedilo.count("z-napako") == 1

    def test_zaseden_enaslov_je_napaka_ob_enaslovu(self, odjemalec: TestClient) -> None:
        """Zasedenost je od `V6-R01` mogoča samo pri staršu: otrok imena za prijavo nima."""
        podatki = {
            "ime": "Druga",
            "enaslov": "stars@primer.test",  # že zaseden (`conftest`)
            "geslo": "geslo-1234-56",
            "geslo_znova": "geslo-1234-56",
        }

        besedilo = odjemalec.post(f"{POT}/parents", data=podatki).text

        blok = besedilo[besedilo.index('id="stars-enaslov"') :]
        blok = blok[: blok.index("</div>")]
        assert '<span class="napaka-polja">To ime je že zasedeno. Izberi drugo.</span>' in blok

    def test_geslo_se_ob_napaki_ne_vrne(self, odjemalec: TestClient) -> None:
        besedilo = odjemalec.post(
            f"{POT}/parents",
            data={
                "ime": "",
                "enaslov": "nov@primer.test",
                "geslo": "tajno-1234-56",
                "geslo_znova": "x",
            },
        ).text

        assert "tajno-1234-56" not in besedilo


class TestPotrditev:
    @pytest.fixture
    def ana(self, motor: Engine) -> str:
        return ustvari_starsa(motor, identifikator="ana@primer.test", prikazno_ime="Ana")

    def test_deaktivacija_je_kartica_s_posledicami(
        self, odjemalec: TestClient, ana: str
    ) -> None:
        besedilo = odjemalec.get(f"{POT}/members/{ana}/deactivate").text
        zacetek = besedilo.index('<section class="kartica kartica-potrditve">')
        kartica_potrditve = besedilo[zacetek : besedilo.index("</section>", zacetek)]

        # Kdo zgoraj, naslov kot vprašanje brez imena v povedi.
        assert "<strong>Ana</strong>" in kartica_potrditve
        assert "<h1>Deaktivirati račun?</h1>" in kartica_potrditve
        # Kaj se zgodi takoj, kaj teče naprej, kaj ostane.
        assert re.findall(r'<li class="(\w+)">', kartica_potrditve) == [
            "takoj",
            "tece",
            "ostane",
            "ostane",
        ]
        # Polno rdeč gumb samo tu; „Prekliči" je obrobljena povezava nazaj.
        assert '<button class="gumb nepovraten" type="submit">' in kartica_potrditve
        assert f'<a class="gumb obrobljen" href="{POT}">Prekliči</a>' in kartica_potrditve
        assert re.search(
            rf'<form method="post" action="{POT}/members/{ana}/deactivate"[^>]*>\s*'
            r'<input type="hidden" name="csrf"',
            kartica_potrditve,
        )

    def test_aktivacija_ni_rdeca(self, odjemalec: TestClient, motor: Engine) -> None:
        ana = ustvari_starsa(
            motor, identifikator="ana@primer.test", prikazno_ime="Ana", aktiven=False
        )

        besedilo = odjemalec.get(f"{POT}/members/{ana}/activate").text

        assert "<h1>Vrniti račun v uporabo?</h1>" in besedilo
        assert "nepovraten" not in besedilo
        assert '<button class="gumb polni" type="submit">' in besedilo


def test_lastnikova_potrditev_uporablja_isto_kartico(
    aplikacija: FastAPI, motor: Engine
) -> None:
    """`clani-stanje.html` deli z `/admin/system` (V3-R05); videz je isti."""
    lastnik = ustvari_starsa(
        motor, identifikator="lastnik@primer.test", prikazno_ime="Lastnik", lastnik_sistema=True
    )
    ana = ustvari_starsa(motor, identifikator="ana@primer.test", prikazno_ime="Ana")
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
        prijavi(odjemalec, motor, lastnik)
        odgovor = odjemalec.get(f"/admin/system/families/{CVEK_ID}/parents/{ana}/deactivate")

    assert odgovor.status_code == 200
    assert '<section class="kartica kartica-potrditve">' in odgovor.text
    assert f'href="/admin/system/families/{CVEK_ID}">Prekliči</a>' in odgovor.text
