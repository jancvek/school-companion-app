"""Google prijava skozi strežnik: povezovanje, prijava in odstranitev (V3-R08).

Omrežja se ne dotaknemo — `create_app` dobi ponarejen `OdjemalecGoogla`
(`docs/odlocitve/ADR-046` F). Vse ostalo je prava koda: plasti, piškotki,
vezivo stanja in baza.

Testi so pisani kot **tok**, ne kot klici posameznih poti: povratni klic je
smiseln samo za odhodom, ki ga je sprožil, in prav razmik med njima je tisto,
kar `ADR-046` D varuje.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app import google, prijava
from app.db import PrijavaRepository
from app.google import NapakaGoogla, OdjemalecGoogla, RacunGoogla
from app.main import create_app
from app.models import POVERILNICA_GESLO, POVERILNICA_GOOGLE, Credential, Family, User
from app.settings import Settings
from tests.conftest import (
    CVEK_ID,
    STARS_IDENTIFIKATOR,
    PrijavljenOdjemalec,
    naredi_testne_nastavitve,
    prijavi,
    ustvari_otroka,
    ustvari_starsa,
)

SUB = "104829371928374651"
EMAIL = "ana@primer.test"

#: Drugi starš družine Cvek — za primer „ta Google je že pri nekom drugem".
DRUGI_STARS_ID = "3c4d5e6f-7a8b-4c9d-8e0f-1a2b3c4d5e6f"


class PonarejenGoogle(OdjemalecGoogla):
    """Odjemalec, ki namesto Googla vrne, kar mu je test naročil.

    Šteje tudi klice: test, ki trdi „do Googla sploh ni prišlo, ker zahtevi
    nismo verjeli", mora to **dokazati**, ne le domnevati (`ADR-046` D, korak 3).
    """

    def __init__(
        self, racun: RacunGoogla | None = None, napaka: NapakaGoogla | None = None
    ) -> None:
        self.racun_za_vrniti = racun or RacunGoogla(sub=SUB, email=EMAIL, email_verified=True)
        self.napaka = napaka
        self.klici: list[str] = []

    def racun(self, koda: str) -> RacunGoogla:
        self.klici.append(koda)
        if self.napaka is not None:
            raise self.napaka
        return self.racun_za_vrniti


@pytest.fixture
def ponaredek() -> PonarejenGoogle:
    return PonarejenGoogle()


def _nastavitve_z_googlom(slike: Any) -> Settings:
    return naredi_testne_nastavitve(slike).model_copy(
        update={
            "google_client_id": "odjemalec-1",
            "google_client_secret": "skrivnost-1",
            "domena": "solski.test",
        }
    )


@pytest.fixture
def aplikacija_z_googlom(
    slike: Any, motor: Engine, ponaredek: PonarejenGoogle
) -> FastAPI:
    return create_app(
        nastavitve=_nastavitve_z_googlom(slike), motor=motor, odjemalec_googla=ponaredek
    )


@pytest.fixture
def odjemalec_g(
    aplikacija_z_googlom: FastAPI, motor: Engine, stars: str
) -> Iterator[PrijavljenOdjemalec]:
    """Prijavljen starš v namestitvi, ki Googla ima."""
    with PrijavljenOdjemalec(
        aplikacija_z_googlom, base_url="https://testserver", follow_redirects=False
    ) as odjemalec:
        prijavi(odjemalec, motor, stars)
        yield odjemalec


@pytest.fixture
def brez_prijave(aplikacija_z_googlom: FastAPI) -> Iterator[PrijavljenOdjemalec]:
    """Obiskovalec brez seje — tak, ki se šele prijavlja."""
    with PrijavljenOdjemalec(
        aplikacija_z_googlom, base_url="https://testserver", follow_redirects=False
    ) as odjemalec:
        yield odjemalec


# --- Pomočniki -------------------------------------------------------------


def _stanje_iz(odgovor: Any) -> str:
    """`state`, ki ga je strežnik poslal Googlu.

    Tip odgovora je `Any` in ne `httpx.Response`: `TestClient` te različice
    Starlette vrača svoj, vendorirani `httpx`, ki za preverjevalnik tipov ni
    isti razred. Isti razlog kot pri `_prijava_s_tujim_racunom` v
    `test_tesnjenje.py`.
    """
    return dict(httpx.URL(odgovor.headers["location"]).params)["state"]


def _zacni_povezovanje(odjemalec: PrijavljenOdjemalec) -> str:
    odgovor = odjemalec.post(google.POT_POVEZAVE)
    assert odgovor.status_code == 303, odgovor.text[:300]
    return _stanje_iz(odgovor)


def _zacni_prijavo(odjemalec: PrijavljenOdjemalec) -> str:
    """Obišče prijavno stran (da dobi CSRF piškotek) in klikne Googlov gumb."""
    stran = odjemalec.get(prijava.POT_PRIJAVE)
    zeton = stran.cookies.get(prijava.PISKOTEK_CSRF_PRIJAVE) or odjemalec.cookies.get(
        prijava.PISKOTEK_CSRF_PRIJAVE
    )
    odgovor = odjemalec.post(google.POT_PRIJAVE, data={"csrf": zeton})
    assert odgovor.status_code == 303, odgovor.text[:300]
    return _stanje_iz(odgovor)


def _povratek(
    odjemalec: PrijavljenOdjemalec, stanje: str, koda: str = "koda-1", **dodatno: str
) -> Any:
    return odjemalec.get(
        google.POT_POVRATNA, params={"code": koda, "state": stanje, **dodatno}
    )


def _poverilnice(motor: Engine, user_id: str) -> list[Credential]:
    with Session(motor) as seja:
        return list(
            seja.scalars(select(Credential).where(Credential.user_id == user_id)).all()
        )


def _google_poverilnica(motor: Engine, user_id: str) -> Credential | None:
    return next(
        (p for p in _poverilnice(motor, user_id) if p.kind == POVERILNICA_GOOGLE), None
    )


def _stevilo_uporabnikov(motor: Engine) -> int:
    with Session(motor) as seja:
        return len(list(seja.scalars(select(User)).all()))


def _povezi_google(
    motor: Engine, user_id: str, *, sub: str = SUB, email: str | None = EMAIL
) -> None:
    """Že povezan Google račun — izhodišče testov prijave."""
    zdaj = datetime.now(UTC)
    with Session(motor) as seja:
        seja.add(
            Credential(
                id=str(uuid4()),
                user_id=user_id,
                kind=POVERILNICA_GOOGLE,
                identifier=sub,
                secret_hash=None,
                label=email,
                created_at=zdaj,
                updated_at=zdaj,
            )
        )
        seja.commit()


# --- Povezovanje -----------------------------------------------------------


class TestPovezovanje:
    def test_srecna_pot(
        self, odjemalec_g: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        stanje = _zacni_povezovanje(odjemalec_g)
        odgovor = _povratek(odjemalec_g, stanje)

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == f"{google.POT_RACUNA}?izid={google.IZID_POVEZANO}"

        poverilnica = _google_poverilnica(motor, stars)
        assert poverilnica is not None
        # `identifier` je `sub` in **ne** e-naslov (`ADR-046` A).
        assert poverilnica.identifier == SUB
        assert poverilnica.label == EMAIL
        assert poverilnica.secret_hash is None

    def test_odhod_pelje_na_google_z_nasim_odjemalcem(
        self, odjemalec_g: PrijavljenOdjemalec
    ) -> None:
        odgovor = odjemalec_g.post(google.POT_POVEZAVE)
        naslov = httpx.URL(odgovor.headers["location"])
        assert str(naslov.copy_with(query=None)) == google.NASLOV_PRIVOLITVE
        assert dict(naslov.params)["client_id"] == "odjemalec-1"

    def test_piskotek_stanja_ima_vse_tri_zastavice(
        self, odjemalec_g: PrijavljenOdjemalec
    ) -> None:
        """`HttpOnly`, `Secure`, `SameSite=Lax` — vsaka nosi svoj del veziva."""
        odgovor = odjemalec_g.post(google.POT_POVEZAVE)
        glava = odgovor.headers["set-cookie"]
        assert google.PISKOTEK_STANJA in glava
        assert "HttpOnly" in glava
        assert "Secure" in glava
        assert "SameSite=lax" in glava.replace("Lax", "lax")

    def test_geslo_in_uporabnik_ostaneta(
        self, odjemalec_g: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        pred = _poverilnice(motor, stars)
        _povratek(odjemalec_g, _zacni_povezovanje(odjemalec_g))
        po = _poverilnice(motor, stars)

        geslo_pred = next(p for p in pred if p.kind == POVERILNICA_GESLO)
        geslo_po = next(p for p in po if p.kind == POVERILNICA_GESLO)
        assert geslo_po.secret_hash == geslo_pred.secret_hash
        assert len(po) == len(pred) + 1

    def test_nepotrjen_email_se_ne_poveze(
        self, slike: Any, motor: Engine, stars: str
    ) -> None:
        ponaredek = PonarejenGoogle(
            RacunGoogla(sub=SUB, email=EMAIL, email_verified=False)
        )
        aplikacija = create_app(
            nastavitve=_nastavitve_z_googlom(slike), motor=motor, odjemalec_googla=ponaredek
        )
        with PrijavljenOdjemalec(
            aplikacija, base_url="https://testserver", follow_redirects=False
        ) as odjemalec:
            prijavi(odjemalec, motor, stars)
            odgovor = _povratek(odjemalec, _zacni_povezovanje(odjemalec))

        assert odgovor.status_code == 409
        assert google.SPOROCILO_NEPOTRJEN in odgovor.text
        assert _google_poverilnica(motor, stars) is None

    def test_sub_pri_drugem_uporabniku(
        self, odjemalec_g: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Eden Google račun pripada enemu uporabniku."""
        drugi = ustvari_starsa(
            motor,
            user_id=DRUGI_STARS_ID,
            identifikator="drugi@primer.test",
            prikazno_ime="Bojan",
        )
        _povezi_google(motor, drugi)

        odgovor = _povratek(odjemalec_g, _zacni_povezovanje(odjemalec_g))

        assert odgovor.status_code == 409
        assert google.SPOROCILO_ZASEDEN in odgovor.text
        assert _google_poverilnica(motor, stars) is None
        # Tuja povezava se ni premaknila.
        assert _google_poverilnica(motor, drugi) is not None

    def test_dvakratna_povezava_istega_racuna(
        self, odjemalec_g: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Drugi klik ne podvoji vrstice in ne pade s 500.

        Sporočilo je „že povezan" in ne „zaseden": račun je tvoj in pot naprej
        obstaja (odstrani ga), kar je natanko razlika, zaradi katere sta
        sporočili dve.
        """
        _povratek(odjemalec_g, _zacni_povezovanje(odjemalec_g))
        odgovor = _povratek(odjemalec_g, _zacni_povezovanje(odjemalec_g))

        assert odgovor.status_code == 409
        assert google.SPOROCILO_ZE_POVEZAN in odgovor.text
        assert len(_poverilnice(motor, stars)) == 2

    def test_drugi_google_racun_na_istem_starsu(
        self, slike: Any, motor: Engine, stars: str
    ) -> None:
        """Gumba za to ni, `POST` na pot pa je mogoč tudi brez gumba.

        Brez preverbe bi nastali **dve** vrstici `kind='google'`: druga bi bila
        v nastavitvah nevidna in prek vmesnika neodstranljiva, oba `sub` pa bi
        odpirala prijavo.
        """
        _povezi_google(motor, stars, sub="prvi-sub", email="prvi@primer.test")
        ponaredek = PonarejenGoogle(
            RacunGoogla(sub="drugi-sub", email="drugi@primer.test", email_verified=True)
        )
        aplikacija = create_app(
            nastavitve=_nastavitve_z_googlom(slike),
            motor=motor,
            odjemalec_googla=ponaredek,
        )
        with PrijavljenOdjemalec(
            aplikacija, base_url="https://testserver", follow_redirects=False
        ) as odjemalec:
            prijavi(odjemalec, motor, stars)
            odgovor = _povratek(odjemalec, _zacni_povezovanje(odjemalec))

        assert odgovor.status_code == 409
        assert google.SPOROCILO_ZE_POVEZAN in odgovor.text
        google_vrstice = [
            p for p in _poverilnice(motor, stars) if p.kind == POVERILNICA_GOOGLE
        ]
        assert len(google_vrstice) == 1
        assert google_vrstice[0].identifier == "prvi-sub"

    def test_nedosegljiv_google(self, slike: Any, motor: Engine, stars: str) -> None:
        ponaredek = PonarejenGoogle(napaka=NapakaGoogla(google.SPOROCILO_NEDOSEGLJIV))
        aplikacija = create_app(
            nastavitve=_nastavitve_z_googlom(slike), motor=motor, odjemalec_googla=ponaredek
        )
        with PrijavljenOdjemalec(
            aplikacija, base_url="https://testserver", follow_redirects=False
        ) as odjemalec:
            prijavi(odjemalec, motor, stars)
            odgovor = _povratek(odjemalec, _zacni_povezovanje(odjemalec))

        assert odgovor.status_code == 409
        assert (
            google.SPOROCILA_POVEZAVE[google.OZNAKA_NEDOSEGLJIV] in odgovor.text
        )
        assert _google_poverilnica(motor, stars) is None

    def test_zavrnjena_privolitev(
        self, odjemalec_g: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Google pove `error=access_denied`; kode ni."""
        stanje = _zacni_povezovanje(odjemalec_g)
        odgovor = odjemalec_g.get(
            google.POT_POVRATNA, params={"state": stanje, "error": "access_denied"}
        )

        assert odgovor.status_code == 409
        assert google.SPOROCILA_POVEZAVE[google.OZNAKA_ZAVRNJENO] in odgovor.text
        assert _google_poverilnica(motor, stars) is None


# --- Vezivo stanja (`ADR-046` D) -------------------------------------------


class TestVezivo:
    """Najpomembnejši razred te datoteke.

    Vsak test tu opisuje napad, ki bi brez veziva izgledal kot povsem običajno
    delovanje — zato nobeden od njih ne sme le preveriti kode odgovora, ampak
    tudi to, da poverilnica **ni** nastala.
    """

    def test_tuj_state_ne_velja(
        self,
        odjemalec_g: PrijavljenOdjemalec,
        motor: Engine,
        stars: str,
        ponaredek: PonarejenGoogle,
    ) -> None:
        _zacni_povezovanje(odjemalec_g)
        odgovor = _povratek(odjemalec_g, "state-ki-ga-nisem-poslal")

        assert odgovor.status_code == 303
        assert google.OZNAKA_STANJE in odgovor.headers["location"]
        assert _google_poverilnica(motor, stars) is None
        # Do Googla sploh ni prišlo: zahtevi nismo verjeli (`ADR-046` D, korak 3).
        assert ponaredek.klici == []

    def test_brez_piskotka_ne_velja(
        self,
        odjemalec_g: PrijavljenOdjemalec,
        motor: Engine,
        stars: str,
        ponaredek: PonarejenGoogle,
    ) -> None:
        """Povratek brez odhoda — napadalčeva povezava, poslana žrtvi."""
        stanje = _zacni_povezovanje(odjemalec_g)
        odjemalec_g.cookies.delete(google.PISKOTEK_STANJA)

        odgovor = _povratek(odjemalec_g, stanje)

        assert odgovor.status_code == 303
        assert google.OZNAKA_STANJE in odgovor.headers["location"]
        assert _google_poverilnica(motor, stars) is None
        assert ponaredek.klici == []

    def test_piskotek_velja_samo_enkrat(
        self, odjemalec_g: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Enkratna raba je del veziva, ne pospravljanje."""
        stanje = _zacni_povezovanje(odjemalec_g)
        prvi = _povratek(odjemalec_g, stanje)
        assert prvi.status_code == 303
        assert google.IZID_POVEZANO in prvi.headers["location"]

        drugi = _povratek(odjemalec_g, stanje)

        assert drugi.status_code == 303
        assert google.OZNAKA_STANJE in drugi.headers["location"]
        # Prva povezava je ostala; druga ni nastala.
        assert len(_poverilnice(motor, stars)) == 2

    def test_povezovanje_vrnjeno_pod_drugo_sejo(
        self,
        aplikacija_z_googlom: FastAPI,
        motor: Engine,
        stars: str,
        ponaredek: PonarejenGoogle,
    ) -> None:
        """Tok začne Ana, dokonča ga Bojan — poverilnica ne sme biti Bojanova.

        Brez te preverbe bi napadalec svoj Google račun prilepil na žrtvin
        račun in v njeno družino vstopal, kolikor dolgo bi hotel.
        """
        bojan = ustvari_starsa(
            motor,
            user_id=DRUGI_STARS_ID,
            identifikator="bojan@primer.test",
            prikazno_ime="Bojan",
        )

        with PrijavljenOdjemalec(
            aplikacija_z_googlom, base_url="https://testserver", follow_redirects=False
        ) as odjemalec:
            prijavi(odjemalec, motor, stars)
            stanje = _zacni_povezovanje(odjemalec)
            # Ista naprava, druga seja: Ana se odjavi, prijavi se Bojan.
            prijavi(odjemalec, motor, bojan)
            odgovor = _povratek(odjemalec, stanje)

        assert odgovor.status_code == 409
        assert _google_poverilnica(motor, stars) is None
        assert _google_poverilnica(motor, bojan) is None
        assert ponaredek.klici == []

    def test_povezovanje_vrnjeno_brez_seje(
        self,
        aplikacija_z_googlom: FastAPI,
        motor: Engine,
        stars: str,
        ponaredek: PonarejenGoogle,
    ) -> None:
        with PrijavljenOdjemalec(
            aplikacija_z_googlom, base_url="https://testserver", follow_redirects=False
        ) as odjemalec:
            prijavi(odjemalec, motor, stars)
            stanje = _zacni_povezovanje(odjemalec)
            odjemalec.cookies.delete(prijava.PISKOTEK_SEJE)
            odgovor = _povratek(odjemalec, stanje)

        # Brez seje ni kam povedati na strani računa; pove prijavna stran.
        assert odgovor.status_code == 303
        assert prijava.POT_PRIJAVE in odgovor.headers["location"]
        assert _google_poverilnica(motor, stars) is None
        assert ponaredek.klici == []

    def test_prijavni_piskotek_ne_odpre_povezovanja(
        self, odjemalec_g: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Stanje z namenom `prijava` ne sme povezati računa.

        Sicer bi napadalec sprožil **prijavni** tok, ki uporabnika ne zahteva,
        in z njim povezal račun tistega, ki je pravkar prijavljen.
        """
        ponarejeno = google.novo_stanje(google.Namen.PRIJAVA)
        odjemalec_g.cookies.set(google.PISKOTEK_STANJA, ponarejeno.zapis())

        odgovor = _povratek(odjemalec_g, ponarejeno.nakljucje)

        # Tok je „prijava": ker `sub` ni povezan z nikomer, prijave ni — in
        # predvsem: povezava ni nastala.
        assert odgovor.status_code == 303
        assert google.OZNAKA_NEPOVEZAN in odgovor.headers["location"]
        assert _google_poverilnica(motor, stars) is None


# --- Prijava ---------------------------------------------------------------


class TestPrijavaZGooglom:
    def test_povezan_racun_se_prijavi(
        self, brez_prijave: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        _povezi_google(motor, stars)
        odgovor = _povratek(brez_prijave, _zacni_prijavo(brez_prijave))

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == prijava.PRIVZETI_CILJ
        assert brez_prijave.cookies.get(prijava.PISKOTEK_SEJE)

    def test_obe_poti_vodita_v_isto_sejo(
        self, brez_prijave: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Kriterij 2: geslo in Google dasta vrstico v isti tabeli `sessions`.

        Seja iz Googla ni posebna vrsta seje in je po ničemer ni mogoče ločiti
        od geselne — to je natanko tisto, kar `ADR-027` pomeni s „poverilnica
        ni uporabnik".
        """
        _povezi_google(motor, stars)
        _povratek(brez_prijave, _zacni_prijavo(brez_prijave))
        zeton_googla = brez_prijave.cookies.get(prijava.PISKOTEK_SEJE)

        with Session(motor) as seja_baze:
            seja = PrijavaRepository(seja_baze).seja(
                prijava.zgostitev_zetona(zeton_googla or "")
            )
        assert seja is not None
        assert seja.user_id == stars
        assert seja.family_id == CVEK_ID

        # Ista seja odpre `/admin` kot vsaka druga.
        stran = brez_prijave.get("/admin")
        assert stran.status_code == 200

    def test_neznan_sub_ne_ustvari_uporabnika(
        self, brez_prijave: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Kriterij 3: registracija ostane zaprta (`ADR-025`)."""
        pred = _stevilo_uporabnikov(motor)

        odgovor = _povratek(brez_prijave, _zacni_prijavo(brez_prijave))

        assert odgovor.status_code == 303
        assert google.OZNAKA_NEPOVEZAN in odgovor.headers["location"]
        assert _stevilo_uporabnikov(motor) == pred
        assert not brez_prijave.cookies.get(prijava.PISKOTEK_SEJE)
        with Session(motor) as seja:
            assert list(seja.scalars(select(Family)).all()).__len__() == 1

    def test_sporocilo_ne_izda_ali_racun_obstaja(
        self, brez_prijave: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Neznan, deaktiviran in ugasnjen dajo **isto** oznako."""
        odgovor = _povratek(brez_prijave, _zacni_prijavo(brez_prijave))
        neznan = odgovor.headers["location"]

        _povezi_google(motor, stars)
        with Session(motor) as seja:
            seja.get(User, stars).is_active = False  # type: ignore[union-attr]
            seja.commit()

        odgovor = _povratek(brez_prijave, _zacni_prijavo(brez_prijave))
        assert odgovor.headers["location"] == neznan

    def test_ugasnjena_druzina_ne_more_v_admin(
        self, brez_prijave: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        _povezi_google(motor, stars)
        with Session(motor) as seja:
            seja.get(Family, CVEK_ID).is_active = False  # type: ignore[union-attr]
            seja.commit()

        odgovor = _povratek(brez_prijave, _zacni_prijavo(brez_prijave))

        assert google.OZNAKA_NEPOVEZAN in odgovor.headers["location"]
        assert not brez_prijave.cookies.get(prijava.PISKOTEK_SEJE)

    def test_otrok_z_google_poverilnico_ne_pride_v_admin(
        self, brez_prijave: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Poti do take poverilnice ni; pravilo mora vseeno biti tam, kjer
        seja nastane (`ADR-036` D, `ADR-046` H)."""
        otrok = ustvari_otroka(motor)
        _povezi_google(motor, otrok)

        odgovor = _povratek(brez_prijave, _zacni_prijavo(brez_prijave))

        assert google.OZNAKA_NEPOVEZAN in odgovor.headers["location"]
        assert not brez_prijave.cookies.get(prijava.PISKOTEK_SEJE)

    def test_oznaka_se_osvezi(
        self, slike: Any, motor: Engine, stars: str
    ) -> None:
        """E-naslov je prikaz; ob prijavi se popravi na zadnjega znanega."""
        _povezi_google(motor, stars, email="stari@primer.test")
        ponaredek = PonarejenGoogle(
            RacunGoogla(sub=SUB, email="novi@primer.test", email_verified=True)
        )
        aplikacija = create_app(
            nastavitve=_nastavitve_z_googlom(slike), motor=motor, odjemalec_googla=ponaredek
        )
        with PrijavljenOdjemalec(
            aplikacija, base_url="https://testserver", follow_redirects=False
        ) as odjemalec:
            _povratek(odjemalec, _zacni_prijavo(odjemalec))

        poverilnica = _google_poverilnica(motor, stars)
        assert poverilnica is not None
        assert poverilnica.label == "novi@primer.test"
        # `sub` se ne dotakne nikoli — to je ključ, po katerem smo jo našli.
        assert poverilnica.identifier == SUB

    def test_gumb_brez_csrf_zetona(self, brez_prijave: PrijavljenOdjemalec) -> None:
        """Tuja stran toka ne sme sprožiti (`ADR-035` D)."""
        odgovor = brez_prijave.post(google.POT_PRIJAVE, data={"csrf": "izmisljen"})
        assert odgovor.status_code == 403

    def test_prijavna_stran_pokaze_samo_znano_oznako(
        self, brez_prijave: PrijavljenOdjemalec
    ) -> None:
        """Skozi naslov gre oznaka, ne besedilo.

        Sicer bi kdorkoli s pripravljeno povezavo narisal poljubno sporočilo
        na prijavno stran — in prav ta stran je tista, kjer je tako sporočilo
        vabilo.
        """
        vsiljeno = "Vpisi geslo se enkrat na drugi strani"
        odgovor = brez_prijave.get(prijava.POT_PRIJAVE, params={"napaka": vsiljeno})
        assert vsiljeno not in odgovor.text

        znana = brez_prijave.get(
            prijava.POT_PRIJAVE, params={"napaka": google.OZNAKA_NEPOVEZAN}
        )
        assert google.SPOROCILO_NEPOVEZAN in znana.text


# --- Odstranitev -----------------------------------------------------------


class TestOdstranitev:
    def test_odstranitev_pusti_geslo_in_uporabnika(
        self, odjemalec_g: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Kriterij 6."""
        _povezi_google(motor, stars)

        odgovor = odjemalec_g.post(google.POT_ODSTRANITVE)

        assert odgovor.status_code == 303
        assert _google_poverilnica(motor, stars) is None
        preostale = _poverilnice(motor, stars)
        assert len(preostale) == 1
        assert preostale[0].kind == POVERILNICA_GESLO
        assert preostale[0].secret_hash is not None
        with Session(motor) as seja:
            assert seja.get(User, stars) is not None

    def test_odstranitev_ne_odjavi(
        self, odjemalec_g: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Ni ponastavitev gesla: seje ostanejo."""
        _povezi_google(motor, stars)
        odjemalec_g.post(google.POT_ODSTRANITVE)

        assert odjemalec_g.get(google.POT_RACUNA).status_code == 200

    def test_brez_gesla_se_odstranitev_zavrne(
        self, aplikacija_z_googlom: FastAPI, motor: Engine
    ) -> None:
        """Račun, ki bi se s tem zaklenil sam iz sebe (`ADR-046` G)."""
        brez_gesla = ustvari_starsa(
            motor, identifikator="brez@primer.test", prikazno_ime="Brez", geslo=None
        )
        _povezi_google(motor, brez_gesla)

        with PrijavljenOdjemalec(
            aplikacija_z_googlom, base_url="https://testserver", follow_redirects=False
        ) as odjemalec:
            prijavi(odjemalec, motor, brez_gesla)
            odgovor = odjemalec.post(google.POT_ODSTRANITVE)
            stran = odjemalec.get(google.POT_RACUNA)

        assert odgovor.status_code == 403
        assert google.SPOROCILO_ZADNJA_POVERILNICA in odgovor.text
        assert _google_poverilnica(motor, brez_gesla) is not None
        # Isto pravilo, ki dejanje zavrne, ga tudi ne ponudi.
        assert google.POT_ODSTRANITVE not in stran.text
        assert google.SPOROCILO_ZADNJA_POVERILNICA in stran.text

    def test_odstranitev_brez_povezave(
        self, odjemalec_g: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Podvojena oddaja: stanje je že tako, kot naj bi bilo po dejanju."""
        odgovor = odjemalec_g.post(google.POT_ODSTRANITVE)
        assert odgovor.status_code == 303
        assert _poverilnice(motor, stars).__len__() == 1

    def test_ne_odstrani_tuje_povezave(
        self, odjemalec_g: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        drugi = ustvari_starsa(
            motor,
            user_id=DRUGI_STARS_ID,
            identifikator="drugi@primer.test",
            prikazno_ime="Bojan",
        )
        _povezi_google(motor, drugi)

        odjemalec_g.post(google.POT_ODSTRANITVE)

        assert _google_poverilnica(motor, drugi) is not None


# --- Stran -----------------------------------------------------------------


class TestStranRacuna:
    def test_pokaze_oba_nacina(
        self, odjemalec_g: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        _povezi_google(motor, stars)
        odgovor = odjemalec_g.get(google.POT_RACUNA)

        assert odgovor.status_code == 200
        assert STARS_IDENTIFIKATOR in odgovor.text
        assert EMAIL in odgovor.text

    def test_brez_povezave_ponudi_povezovanje(
        self, odjemalec_g: PrijavljenOdjemalec
    ) -> None:
        odgovor = odjemalec_g.get(google.POT_RACUNA)
        assert google.POT_POVEZAVE in odgovor.text

    def test_glava_pelje_na_racun(self, odjemalec_g: PrijavljenOdjemalec) -> None:
        assert f'href="{google.POT_RACUNA}"' in odjemalec_g.get("/admin").text

    def test_sub_ni_nikoli_izrisan(
        self, odjemalec_g: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """Stran pokaže e-naslov, ne ključa. `sub` na strani nima česa iskati."""
        _povezi_google(motor, stars)
        assert SUB not in odjemalec_g.get(google.POT_RACUNA).text

    def test_brez_seje_pelje_na_prijavo(
        self, brez_prijave: PrijavljenOdjemalec
    ) -> None:
        """Pot je pod `/admin` in nima nobene izjeme (`ADR-046` B)."""
        for pot in (google.POT_RACUNA, google.POT_POVEZAVE, google.POT_ODSTRANITVE):
            odgovor = (
                brez_prijave.get(pot)
                if pot == google.POT_RACUNA
                else brez_prijave.post(pot, data={"csrf": "x"})
            )
            assert odgovor.status_code == 303, pot
            assert prijava.POT_PRIJAVE in odgovor.headers["location"], pot

    def test_csrf_je_obvezen(self, odjemalec_g: PrijavljenOdjemalec) -> None:
        for pot in (google.POT_POVEZAVE, google.POT_ODSTRANITVE):
            assert odjemalec_g.post(pot, data={"csrf": ""}).status_code == 403, pot


# --- Namestitev brez Googla (`ADR-046` F) ----------------------------------


class TestBrezGoogla:
    """Privzeta namestitev Googla nima in mora delovati natanko kot prej."""

    def test_poti_pod_adminom_vrnejo_404(self, odjemalec: PrijavljenOdjemalec) -> None:
        assert odjemalec.get(google.POT_RACUNA).status_code == 404
        assert odjemalec.post(google.POT_POVEZAVE).status_code == 404
        assert odjemalec.post(google.POT_ODSTRANITVE).status_code == 404

    def test_poti_zunaj_admina_vrneta_404(
        self, aplikacija: FastAPI
    ) -> None:
        with PrijavljenOdjemalec(
            aplikacija, base_url="https://testserver", follow_redirects=False
        ) as odjemalec:
            assert odjemalec.post(google.POT_PRIJAVE, data={"csrf": "x"}).status_code == 404
            assert odjemalec.get(google.POT_POVRATNA).status_code == 404

    def test_prijavna_stran_nima_gumba(self, aplikacija: FastAPI) -> None:
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            assert google.POT_PRIJAVE not in odjemalec.get(prijava.POT_PRIJAVE).text

    def test_glava_nima_povezave(self, odjemalec: PrijavljenOdjemalec) -> None:
        assert google.POT_RACUNA not in odjemalec.get("/admin").text

    def test_streznik_normalno_tece(self, odjemalec: PrijavljenOdjemalec) -> None:
        """Manjkajoča nastavitev ustavi eno zmožnost, ne strežnika."""
        assert odjemalec.get("/admin").status_code == 200
        assert odjemalec.get("/health").status_code == 200


# --- Popravki po prvem pregledu ---------------------------------------------


class TestVhodOdZunaj:
    """Povratni klic je javna pot; vsak njen vhod je poljuben niz."""

    @pytest.mark.parametrize("vsiljeno", ["ž", "😀", "a\u0301"])
    def test_ne_ascii_state_ne_da_500_in_pobrise_piskotek(
        self, aplikacija_z_googlom: FastAPI, motor: Engine, stars: str, vsiljeno: str
    ) -> None:
        """Dve trditvi hkrati, ker sta bili obe pokvarjeni z isto vrstico.

        `compare_digest` nad `str` z ne-ASCII znakom vrže `TypeError`. Ta je
        ušel pred `_koncaj`, zato odgovor ni bil le 500 z golim angleškim
        besedilom — **piškotek stanja je ostal živ** in jamstvo `ADR-046` D o
        enkratni rabi je padlo.
        """
        with PrijavljenOdjemalec(
            aplikacija_z_googlom,
            base_url="https://testserver",
            follow_redirects=False,
            raise_server_exceptions=False,
        ) as odjemalec:
            prijavi(odjemalec, motor, stars)
            _zacni_povezovanje(odjemalec)
            odgovor = odjemalec.get(
                google.POT_POVRATNA, params={"code": "k", "state": vsiljeno}
            )

            assert odgovor.status_code != 500, odgovor.text[:200]
            assert "Internal Server Error" not in odgovor.text
            assert odjemalec.cookies.get(google.PISKOTEK_STANJA) is None

        assert _google_poverilnica(motor, stars) is None

    # Drugi vhod od zunaj je **piskotek** (`user_id` v stanju), ki ga Starlette
    # dekodira v latin-1. Testa na tej ravni zanj ni in ne more biti: `httpx`
    # glavo `Cookie` kodira v ASCII in take vrednosti sploh ne poslje, medtem
    # ko surov odjemalec bajt 0xE9 poslje brez tezav. Pravilo zato pokriva test
    # enote (`test_ne_ascii_uporabnik_v_piskotku_je_neujemanje`), ki klice isto
    # skupno funkcijo `_enaka` kot ta pot.


class TestBesediloPoTokovih:
    """Napaka pove tam, kjer jo bo bralec videl, in tako, kot se ga tiče."""

    def test_povezovanje_ne_pove_naj_se_prijavi(
        self, odjemalec_g: PrijavljenOdjemalec
    ) -> None:
        stanje = _zacni_povezovanje(odjemalec_g)
        odgovor = odjemalec_g.get(
            google.POT_POVRATNA, params={"state": stanje, "error": "access_denied"}
        )

        assert odgovor.status_code == 409
        assert "prijaviš z geslom" not in odgovor.text
        assert google.SPOROCILA_POVEZAVE[google.OZNAKA_ZAVRNJENO] in odgovor.text

    def test_prijava_brez_seje_pove_naj_se_prijavi(
        self, brez_prijave: PrijavljenOdjemalec
    ) -> None:
        """Isti oznaki na prijavni strani pripada prijavno besedilo."""
        stanje = _zacni_prijavo(brez_prijave)
        odgovor = brez_prijave.get(
            google.POT_POVRATNA, params={"state": stanje, "error": "access_denied"}
        )
        assert odgovor.status_code == 303

        stran = brez_prijave.get(prijava.POT_PRIJAVE, params={"napaka": google.OZNAKA_ZAVRNJENO})
        assert google.SPOROCILO_ZAVRNJENO in stran.text


class TestStranPoveKjeSeNastaviGeslo:
    def test_racun_pelje_na_stran_druzine(
        self, odjemalec_g: PrijavljenOdjemalec
    ) -> None:
        """Trditev „nastavi ga lastnik sistema" od `V3-R06` ne drži več."""
        besedilo = odjemalec_g.get(google.POT_RACUNA).text
        assert "nastavi ga lastnik sistema" not in besedilo
        assert 'href="/admin/family"' in besedilo

    def test_starsi_si_geslo_res_lahko_nastavi_sam(
        self, odjemalec_g: PrijavljenOdjemalec, stars: str
    ) -> None:
        """Protitest: stran ne sme kazati na dejanje, ki bi bilo zavrnjeno."""
        odgovor = odjemalec_g.post(
            f"/admin/family/members/{stars}/password",
            data={"geslo": "novo-geslo-123", "geslo_znova": "novo-geslo-123"},
        )
        assert odgovor.status_code == 303, odgovor.text[:300]


class TestOznakaIzidaNaRacunu:
    def test_vsiljeno_besedilo_se_ne_izrise(
        self, odjemalec_g: PrijavljenOdjemalec
    ) -> None:
        """Isto varovalo kot na prijavni strani: skozi naslov gre oznaka."""
        vsiljeno = "Poslji geslo na drugo stran"
        odgovor = odjemalec_g.get(google.POT_RACUNA, params={"izid": vsiljeno})

        assert odgovor.status_code == 200
        assert vsiljeno not in odgovor.text

    def test_znana_oznaka_se_izrise(self, odjemalec_g: PrijavljenOdjemalec) -> None:
        odgovor = odjemalec_g.get(
            google.POT_RACUNA, params={"izid": google.IZID_ODSTRANJENO}
        )
        assert google.SPOROCILO_ODSTRANJENO in odgovor.text


# --- Kar bi Google lahko tiho pokvaril drugje -------------------------------


class TestSeStarejseZahteve:
    """Google ne sme razveljaviti trditev, ki so jih postavile prejšnje zahteve."""

    def test_ponastavitev_gesla_pobije_tudi_google_sejo(
        self, aplikacija_z_googlom: FastAPI, motor: Engine, stars: str
    ) -> None:
        """`V3-R06`: ponastavitev prekliče **vse** seje, na vseh napravah.

        Z `V3-R08` seje ne nastajajo več samo iz gesla. Trditev „vse seje" bi
        brez tega testa tiho postala „vse geselne seje" — in starš, ki mu je
        kdo prevzel račun, bi po ponastavitvi ostal prevzet.
        """
        _povezi_google(motor, stars)
        drugi = ustvari_starsa(
            motor,
            user_id=DRUGI_STARS_ID,
            identifikator="drugi@primer.test",
            prikazno_ime="Bojan",
        )

        with PrijavljenOdjemalec(
            aplikacija_z_googlom, base_url="https://testserver", follow_redirects=False
        ) as z_googlom:
            _povratek(z_googlom, _zacni_prijavo(z_googlom))
            assert z_googlom.get("/admin").status_code == 200

            with PrijavljenOdjemalec(
                aplikacija_z_googlom, base_url="https://testserver", follow_redirects=False
            ) as drug_odjemalec:
                prijavi(drug_odjemalec, motor, drugi)
                odgovor = drug_odjemalec.post(
                    f"/admin/family/members/{stars}/password",
                    data={"geslo": "novo-geslo-123", "geslo_znova": "novo-geslo-123"},
                )
                assert odgovor.status_code == 303, odgovor.text[:300]

            # Seja, ki je nastala prek Googla, je padla enako kot geselna.
            po = z_googlom.get("/admin")
            assert po.status_code == 303
            assert prijava.POT_PRIJAVE in po.headers["location"]

    def test_google_poverilnica_ne_odpre_geselne_prijave(
        self, brez_prijave: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        """`sub` ni uporabniško ime.

        `PrijavaRepository.poverilnica` filtrira po vrsti prav zato: skupna
        poizvedba bi pomenila, da se je mogoče prijaviti z `sub` kot
        identifikatorjem in praznim geslom.
        """
        _povezi_google(motor, stars)
        stran = brez_prijave.get(prijava.POT_PRIJAVE)
        zeton = brez_prijave.cookies.get(prijava.PISKOTEK_CSRF_PRIJAVE)

        odgovor = brez_prijave.post(
            prijava.POT_PRIJAVE,
            data={"identifikator": SUB, "geslo": "", "csrf": zeton},
        )

        assert odgovor.status_code == 401
        assert not brez_prijave.cookies.get(prijava.PISKOTEK_SEJE)
        assert stran.status_code == 200
