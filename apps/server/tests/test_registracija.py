"""Registracija starša z Googlom in odobritev lastnika (V6-R02).

Kriteriji so v `docs/verzije/v6.md`, odločitve v `docs/odlocitve/ADR-057`
(kaj) in `ADR-062` (kako). Razdelki sledijo kriterijem: pravila brez
strežnika, povratni klic, oddaja obrazca, meji, zapora neodobrene družine,
„Moj račun", izbris, lastnikova stran in prva stran po odobritvi.

Google je ponarejen (`tests/test_racun.py`), zato zbirka ne gre na omrežje.
"""

import importlib
import pkgutil
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

import app.routers
from app import clani, google, main, prijava, registracija, sistem
from app.db import ClaniRepository, DruzineRepository
from app.google import RacunGoogla
from app.main import create_app
from app.models import (
    POVERILNICA_GOOGLE,
    STANJE_CAKA,
    STANJE_ODOBRENA,
    STANJE_ZAVRNJENA,
    VLOGA_STARS,
    Credential,
    Family,
    LoginAttempt,
    User,
    UserSession,
)
from tests.conftest import (
    CVEK_ID,
    STARS_IDENTIFIKATOR,
    PrijavljenOdjemalec,
    meni_strani,
    naredi_testne_nastavitve,
    prijavi,
    ustvari_otroka,
    ustvari_starsa,
)
from tests.test_ogrodje import stevec
from tests.test_prijava import naslov, zeton_obrazca
from tests.test_racun import (
    EMAIL,
    SUB,
    PonarejenGoogle,
    _nastavitve_z_googlom,
    _povezi_google,
    _povratek,
    _stanje_iz,
    _zacni_prijavo,
)

POT_RACUNA = "/admin/racun"
POT_IZBRISA = "/admin/racun/izbrisi"
PRED_VZHODOM = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


# --- Postavitev --------------------------------------------------------------


@pytest.fixture
def ponaredek() -> PonarejenGoogle:
    return PonarejenGoogle(RacunGoogla(sub=SUB, email=EMAIL, email_verified=True, name="Ana Kovač"))


@pytest.fixture
def aplikacija_g(slike: Any, motor: Engine, ponaredek: PonarejenGoogle) -> FastAPI:
    """Namestitev z Googlom — registracija brez njega ne obstaja."""
    return create_app(
        nastavitve=_nastavitve_z_googlom(slike), motor=motor, odjemalec_googla=ponaredek
    )


@pytest.fixture
def obiskovalec(aplikacija_g: FastAPI) -> Iterator[PrijavljenOdjemalec]:
    """Nekdo brez seje in brez računa."""
    with PrijavljenOdjemalec(
        aplikacija_g, base_url="https://testserver", follow_redirects=False
    ) as odjemalec:
        yield odjemalec


def _zacni_registracijo(odjemalec: PrijavljenOdjemalec) -> str:
    """Odpre okno registracije in klikne „Nadaljuj z Googlom"; vrne `state`."""
    stran = odjemalec.get(registracija.POT)
    assert stran.status_code == 200, stran.text[:300]
    odgovor = odjemalec.post(
        google.POT_PRIJAVE,
        data={"csrf": zeton_obrazca(stran.text), "namen": google.Namen.REGISTRACIJA.value},
    )
    assert odgovor.status_code == 303, odgovor.text[:300]
    return _stanje_iz(odgovor)


def _do_obrazca(odjemalec: PrijavljenOdjemalec) -> Any:
    """Skozi Google do obrazca zahtevka; vrne izrisano stran z obrazcem."""
    povratek = _povratek(odjemalec, _zacni_registracijo(odjemalec))
    assert povratek.status_code == 303
    assert povratek.headers["location"] == registracija.POT
    stran = odjemalec.get(registracija.POT)
    assert stran.status_code == 200
    return stran


def _oddaj(
    odjemalec: PrijavljenOdjemalec,
    stran: Any,
    *,
    ime_druzine: str = "Kovačevi",
    ime: str = "Ana Kovač",
    soglasje: bool = True,
    **dodatno: str,
) -> Any:
    podatki = {
        "csrf": zeton_obrazca(stran.text),
        "ime_druzine": ime_druzine,
        "ime": ime,
        **dodatno,
    }
    if soglasje:
        podatki["soglasje"] = "da"
    return odjemalec.post(registracija.POT, data=podatki)


def _podtakni_istovetnost(odjemalec: PrijavljenOdjemalec, zapis: str) -> None:
    """Zamenja piškotek istovetnosti. Najprej izbriše pravega: ta ima domeno
    strežnika, ročno postavljeni pa ne, in v posodi bi sicer ostala oba."""
    odjemalec.cookies.delete(registracija.PISKOTEK)
    odjemalec.cookies.set(registracija.PISKOTEK, zapis)


def _registriraj(odjemalec: PrijavljenOdjemalec, **vnos: Any) -> Any:
    """Cela pot: Google, obrazec, oddaja."""
    return _oddaj(odjemalec, _do_obrazca(odjemalec), **vnos)


def _stetje(motor: Engine) -> tuple[int, int, int, int]:
    """(družin, uporabnikov, poverilnic, sej) — kar registracija ustvari."""
    with Session(motor) as seja:
        return (
            seja.scalar(select(func.count(Family.id))) or 0,
            seja.scalar(select(func.count(User.id))) or 0,
            seja.scalar(select(func.count(Credential.id))) or 0,
            seja.scalar(select(func.count(UserSession.id))) or 0,
        )


def _druzina(motor: Engine, family_id: str) -> Family | None:
    with Session(motor) as seja:
        return seja.get(Family, family_id)


def _edina_nova(motor: Engine) -> Family:
    """Družina, ki ni Cvek — tista, ki jo je ustvarila registracija."""
    with Session(motor) as seja:
        return seja.scalars(select(Family).where(Family.id != CVEK_ID)).one()


def ustvari_registrirano(
    motor: Engine,
    stanje: str,
    *,
    ime_druzine: str = "Kovačevi",
    stars: str = "Ana Kovač",
    sub: str | None = None,
    email: str | None = "ana.kovac@primer.test",
    oddano: datetime = PRED_VZHODOM,
) -> tuple[str, str]:
    """Družina, kakršno pusti registracija, v danem stanju; `(family_id, user_id)`."""
    family_id, user_id = str(uuid4()), str(uuid4())
    with Session(motor) as seja:
        seja.add(
            Family(
                id=family_id,
                name=ime_druzine,
                is_active=True,
                status=stanje,
                consent_at=oddano,
                decided_at=None if stanje == STANJE_CAKA else oddano + timedelta(days=2),
                created_at=oddano,
            )
        )
        seja.add(
            User(
                id=user_id,
                family_id=family_id,
                role=VLOGA_STARS,
                display_name=stars,
                is_system_owner=False,
                is_active=True,
                created_at=oddano,
            )
        )
        seja.add(
            Credential(
                id=str(uuid4()),
                user_id=user_id,
                kind=POVERILNICA_GOOGLE,
                identifier=sub or f"sub-{user_id}",
                secret_hash=None,
                label=email,
                created_at=oddano,
                updated_at=oddano,
            )
        )
        seja.commit()
    return family_id, user_id


def _odjemalec_za(aplikacija: FastAPI, motor: Engine, user_id: str) -> PrijavljenOdjemalec:
    odjemalec = PrijavljenOdjemalec(
        aplikacija, base_url="https://testserver", follow_redirects=False
    )
    prijavi(odjemalec, motor, user_id)
    return odjemalec


@pytest.fixture
def cakajoci(aplikacija: FastAPI, motor: Engine) -> Iterator[PrijavljenOdjemalec]:
    """Seja starša, čigar družina čaka na odobritev."""
    _, user_id = ustvari_registrirano(motor, STANJE_CAKA)
    with _odjemalec_za(aplikacija, motor, user_id) as odjemalec:
        yield odjemalec


@pytest.fixture
def zavrnjeni(aplikacija: FastAPI, motor: Engine) -> Iterator[PrijavljenOdjemalec]:
    """Seja starša, čigar zahtevek je bil zavrnjen."""
    _, user_id = ustvari_registrirano(motor, STANJE_ZAVRNJENA)
    with _odjemalec_za(aplikacija, motor, user_id) as odjemalec:
        yield odjemalec


@pytest.fixture
def lastnik(motor: Engine) -> str:
    return ustvari_starsa(
        motor,
        identifikator="lastnik@primer.test",
        prikazno_ime="Lastnik",
        lastnik_sistema=True,
    )


@pytest.fixture
def lastnikov(aplikacija: FastAPI, motor: Engine, lastnik: str) -> Iterator[PrijavljenOdjemalec]:
    with _odjemalec_za(aplikacija, motor, lastnik) as odjemalec:
        yield odjemalec


# --- Pravila brez strežnika ---------------------------------------------------


class TestPodpisIstovetnosti:
    """`ADR-062` G: `sub` do obrazca pride samo podpisan."""

    KLJUC = b"k" * 32
    KDO = registracija.Istovetnost(sub="104829", email="ana@primer.test", name="Ana Kovač")
    ZDAJ = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)

    def test_zapis_se_prebere_nazaj(self) -> None:
        zapis = registracija.zapisi_istovetnost(self.KDO, self.KLJUC, self.ZDAJ)

        assert registracija.preberi_istovetnost(zapis, self.KLJUC, self.ZDAJ) == self.KDO

    def test_drug_kljuc_ne_velja(self) -> None:
        """Ponovni zagon strežnika: nov ključ, stari piškotki so brez vrednosti."""
        zapis = registracija.zapisi_istovetnost(self.KDO, self.KLJUC, self.ZDAJ)

        assert registracija.preberi_istovetnost(zapis, b"x" * 32, self.ZDAJ) is None

    def test_spremenjena_vsebina_ne_velja(self) -> None:
        """Napadalec zamenja vsebino s svojo in obdrži tuj podpis."""
        tuj = registracija.Istovetnost(sub="zrtev", email="zrtev@primer.test", name="Žrtev")
        nas = registracija.zapisi_istovetnost(self.KDO, self.KLJUC, self.ZDAJ)
        njegov = registracija.zapisi_istovetnost(tuj, b"napadalcev-kljuc" * 2, self.ZDAJ)
        ponarejen = f"{njegov.split('.')[0]}.{nas.split('.')[1]}"

        assert registracija.preberi_istovetnost(ponarejen, self.KLJUC, self.ZDAJ) is None

    def test_po_roku_ne_velja(self) -> None:
        zapis = registracija.zapisi_istovetnost(self.KDO, self.KLJUC, self.ZDAJ)
        tik_pred = self.ZDAJ + registracija.VELJAVNOST - timedelta(seconds=1)

        assert registracija.preberi_istovetnost(zapis, self.KLJUC, tik_pred) == self.KDO
        assert (
            registracija.preberi_istovetnost(zapis, self.KLJUC, self.ZDAJ + registracija.VELJAVNOST)
            is None
        )

    @pytest.mark.parametrize(
        "zapis",
        [None, "", "brez-pike", "a.b.c", "ž.ž", ".", "e30.x", "%%%.%%%", "é" * 40 + ".abc"],
    )
    def test_smeti_so_molk_ne_izjema(self, zapis: str | None) -> None:
        """Piškotek je vnos od zunaj; nobena oblika ne sme dati izjeme (500)."""
        assert registracija.preberi_istovetnost(zapis, self.KLJUC, self.ZDAJ) is None

    def test_pravilno_podpisana_vsebina_brez_polj_ne_velja(self) -> None:
        vsebina = registracija._b64(b'{"sub":"","email":"","name":"","exp":9999999999}')
        zapis = f"{vsebina}.{registracija._podpis(self.KLJUC, vsebina)}"

        assert registracija.preberi_istovetnost(zapis, self.KLJUC, self.ZDAJ) is None

    def test_kljuc_je_ob_vsakem_zagonu_drug(self, aplikacija: FastAPI, nastavitve: Any) -> None:
        druga = create_app(nastavitve=nastavitve, motor=aplikacija.state.motor)

        assert len(aplikacija.state.kljuc_registracije) == 32
        assert aplikacija.state.kljuc_registracije != druga.state.kljuc_registracije


class TestPravila:
    def test_meja_cakajocih(self) -> None:
        tik_pod = registracija.NAJVEC_CAKAJOCIH - 1

        assert not registracija.je_prek_meje(cakajocih=tik_pod, v_oknu=0)
        assert registracija.je_prek_meje(cakajocih=registracija.NAJVEC_CAKAJOCIH, v_oknu=0)

    def test_dnevna_meja(self) -> None:
        tik_pod = registracija.NAJVEC_NA_OKNO - 1

        assert not registracija.je_prek_meje(cakajocih=0, v_oknu=tik_pod)
        assert registracija.je_prek_meje(cakajocih=0, v_oknu=registracija.NAJVEC_NA_OKNO)

    def test_meji_sta_dogovorjeni(self) -> None:
        """`ADR-062` F: 20 čakajočih, 10 na 24 ur; meje po IP ni."""
        assert registracija.NAJVEC_CAKAJOCIH == 20
        assert registracija.NAJVEC_NA_OKNO == 10
        assert timedelta(hours=24) == registracija.OKNO_REGISTRACIJ

    def test_nepotrjen_ali_manjkajoc_enaslov_ne_zacne(self) -> None:
        zacne = registracija.zakaj_ne_sme_zaceti

        assert zacne(email="a@b.test", email_verified=True, enaslov_ima_geslo=False) is None
        assert (
            zacne(email="a@b.test", email_verified=False, enaslov_ima_geslo=False)
            == registracija.OZNAKA_NEPOTRJEN
        )
        assert (
            zacne(email=None, email_verified=True, enaslov_ima_geslo=False)
            == registracija.OZNAKA_NEPOTRJEN
        )
        assert (
            zacne(email="a@b.test", email_verified=True, enaslov_ima_geslo=True)
            == registracija.OZNAKA_GESLO
        )

    def test_obrazec_zahteva_imeni_in_soglasje(self) -> None:
        preveri = registracija.preveri_obrazec

        assert preveri(ime_druzine="Kovačevi", ime="Ana", soglasje=True) is None
        assert (
            preveri(ime_druzine="Kovačevi", ime="Ana", soglasje=False)
            == registracija.SPOROCILO_BREZ_SOGLASJA
        )
        assert (
            preveri(ime_druzine="  ", ime="Ana", soglasje=True)
            == registracija.SPOROCILO_PRAZNO_IME_DRUZINE
        )
        assert preveri(ime_druzine="Kovačevi", ime=" ", soglasje=True) == clani.SPOROCILO_PRAZNO_IME
        assert (
            preveri(ime_druzine="K" * (sistem.NAJDALJSE_IME_DRUZINE + 1), ime="Ana", soglasje=True)
            == sistem.SPOROCILO_PREDOLGO_IME_DRUZINE
        )

    def test_prehodi_stanja(self) -> None:
        """`ADR-062` K: odobrene ni mogoče zavrniti."""
        assert sistem.zakaj_ne_sme_odobriti(STANJE_CAKA) is None
        assert sistem.zakaj_ne_sme_odobriti(STANJE_ZAVRNJENA) is None
        assert sistem.zakaj_ne_sme_odobriti(STANJE_ODOBRENA) is not None
        assert sistem.zakaj_ne_sme_zavrniti(STANJE_CAKA) is None
        assert sistem.zakaj_ne_sme_zavrniti(STANJE_ODOBRENA) is not None
        assert sistem.zakaj_ne_sme_zavrniti(STANJE_ZAVRNJENA) is not None

    def test_besedili_o_zunanji_storitvi(self) -> None:
        """`ADR-062` C: javno pove, kam gredo slike; nobeno ne trdi, da aplikacija ni objavljena."""
        assert "OpenAI" in sistem.BESEDILO_ZASEBNOST_JAVNO
        assert "tvoja družina" in sistem.BESEDILO_ZASEBNOST_JAVNO
        for besedilo in (sistem.BESEDILO_ZASEBNOST, sistem.BESEDILO_ZASEBNOST_JAVNO):
            assert "ni objavljena" not in besedilo


# --- Okno registracije in povratni klic ---------------------------------------


class TestOkno:
    def test_zacetek_ponudi_google_in_prijavo(self, obiskovalec: PrijavljenOdjemalec) -> None:
        stran = obiskovalec.get(registracija.POT)

        assert stran.status_code == 200
        assert "Nadaljuj z Googlom" in stran.text
        assert "Iz Google računa vzamemo" in stran.text
        assert f'href="{prijava.POT_PRIJAVE}"' in stran.text
        assert 'name="namen" value="registracija"' in stran.text
        # Brez menija. Povezavo „Domača stran" je `ADR-062` B odložil do
        # `V6-R03`; da zdaj je, preverja `tests/test_predstavitev.py`.
        assert '<nav class="meni' not in stran.text

    def test_brez_googla_strani_ni(self, aplikacija: FastAPI) -> None:
        """Registracija je samo z Googlom (`ADR-057` A)."""
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            assert odjemalec.get(registracija.POT).status_code == 404
            assert odjemalec.post(registracija.POT, data={"csrf": "x"}).status_code == 404

    def test_prijavna_stran_vodi_na_registracijo(self, obiskovalec: PrijavljenOdjemalec) -> None:
        besedilo = obiskovalec.get(prijava.POT_PRIJAVE).text

        assert f'href="{registracija.POT}"' in besedilo
        assert "Registracija z Google računom" in besedilo
        assert "ni mogoče odpreti" not in besedilo

    def test_prijavna_stran_brez_googla_registracije_ne_ponudi(self, aplikacija: FastAPI) -> None:
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            assert registracija.POT not in odjemalec.get(prijava.POT_PRIJAVE).text

    def test_gumb_brez_csrf_zetona(self, obiskovalec: PrijavljenOdjemalec) -> None:
        obiskovalec.get(registracija.POT)

        odgovor = obiskovalec.post(
            google.POT_PRIJAVE, data={"csrf": "napacen", "namen": "registracija"}
        )

        assert odgovor.status_code == 403
        assert "Registracija" in odgovor.text

    def test_prijavljen_stars_gre_na_pregled(
        self, aplikacija_g: FastAPI, motor: Engine, stars: str
    ) -> None:
        with _odjemalec_za(aplikacija_g, motor, stars) as odjemalec:
            odgovor = odjemalec.get(registracija.POT)

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == prijava.PRIVZETI_CILJ


class TestPovratniKlic:
    """Kriterij: „Povratni klic sam ne ustvari ničesar."""

    def test_neznan_sub_ne_ustvari_nicesar_in_dobi_obrazec(
        self, obiskovalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        prej = _stetje(motor)

        stran = _do_obrazca(obiskovalec)

        assert _stetje(motor) == prej
        with Session(motor) as seja:
            # Tudi sledi v `login_attempts` ne: v dnevno mejo šteje šele oddaja.
            assert not list(seja.scalars(select(LoginAttempt.id)))
        assert not obiskovalec.cookies.get(prijava.PISKOTEK_SEJE)
        assert "Še en korak" in stran.text
        assert EMAIL in stran.text
        # Ime iz Googla je predlog v polju, e-naslov in `sub` pa v obrazcu nista.
        assert 'value="Ana Kovač"' in stran.text
        assert SUB not in stran.text
        assert 'name="soglasje"' in stran.text
        assert sistem.BESEDILO_ZASEBNOST_JAVNO[:40] in stran.text

    def test_obrazec_kaze_zacetnici_imena(self, obiskovalec: PrijavljenOdjemalec) -> None:
        """Posnetek 04: krožec ob računu nosi začetnici („AK")."""
        stran = _do_obrazca(obiskovalec)

        assert '<span class="krozec velik" aria-hidden="true">AK</span>' in stran.text
        assert registracija.zacetnici("ana") == "A"
        assert registracija.zacetnici("  ") == ""

    def test_ime_iz_samih_presledkov_da_zacetnico_enaslova(
        self, obiskovalec: PrijavljenOdjemalec, ponaredek: PonarejenGoogle
    ) -> None:
        ponaredek.racun_za_vrniti = RacunGoogla(
            sub=SUB, email=EMAIL, email_verified=True, name="   "
        )

        stran = _do_obrazca(obiskovalec)

        assert f'aria-hidden="true">{EMAIL[0].upper()}</span>' in stran.text

    def test_nov_zacetek_toka_zavrze_prejsnjo_istovetnost(
        self, obiskovalec: PrijavljenOdjemalec
    ) -> None:
        """`ADR-062` G: „Drug račun" je nov začetek; stari piškotek ne sme preživeti."""
        stran = _do_obrazca(obiskovalec)
        assert obiskovalec.cookies.get(registracija.PISKOTEK)

        odgovor = obiskovalec.post(
            google.POT_PRIJAVE,
            data={"csrf": zeton_obrazca(stran.text), "namen": "registracija"},
        )

        assert odgovor.status_code == 303
        assert not obiskovalec.cookies.get(registracija.PISKOTEK)
        assert "Nadaljuj z Googlom" in obiskovalec.get(registracija.POT).text

    def test_piskotek_istovetnosti_ima_zastavice(self, obiskovalec: PrijavljenOdjemalec) -> None:
        povratek = _povratek(obiskovalec, _zacni_registracijo(obiskovalec))

        glava = next(
            g for g in povratek.headers.get_list("set-cookie") if g.startswith("registracija=")
        )
        assert "HttpOnly" in glava
        assert "Secure" in glava
        assert "samesite=lax" in glava.lower()
        assert SUB not in glava, "sub ne sme biti berljiv iz piškotka na pogled"

    def test_neznan_sub_s_prijavne_strani_dobi_isti_obrazec(
        self, obiskovalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """`ADR-062` H: dva vstopa, en izid."""
        povratek = _povratek(obiskovalec, _zacni_prijavo(obiskovalec))

        assert povratek.headers["location"] == registracija.POT
        assert "Še en korak" in obiskovalec.get(registracija.POT).text

    def test_enaslov_z_geslom_se_ne_registrira(
        self, obiskovalec: PrijavljenOdjemalec, motor: Engine, ponaredek: PonarejenGoogle
    ) -> None:
        """Kriterij: računa se ne združi; sporočilo pove, kaj narediti (posnetek 05)."""
        ustvari_starsa(motor)  # stars@primer.test z geslom
        ponaredek.racun_za_vrniti = RacunGoogla(
            sub=SUB, email=STARS_IDENTIFIKATOR.upper(), email_verified=True, name="Ana"
        )
        prej = _stetje(motor)

        povratek = _povratek(obiskovalec, _zacni_registracijo(obiskovalec))

        assert povratek.headers["location"] == f"{registracija.POT}?napaka=geslo"
        assert not obiskovalec.cookies.get(registracija.PISKOTEK)
        stran = obiskovalec.get(povratek.headers["location"])
        assert registracija.SPOROCILO_GESLO_OBSTAJA in stran.text
        assert "Še en korak" not in stran.text
        assert _stetje(motor) == prej

    def test_nepotrjen_enaslov_se_ne_registrira(
        self, obiskovalec: PrijavljenOdjemalec, motor: Engine, ponaredek: PonarejenGoogle
    ) -> None:
        ponaredek.racun_za_vrniti = RacunGoogla(sub=SUB, email=EMAIL, email_verified=False)

        povratek = _povratek(obiskovalec, _zacni_registracijo(obiskovalec))

        assert povratek.headers["location"] == f"{registracija.POT}?napaka=nepotrjen"
        assert not obiskovalec.cookies.get(registracija.PISKOTEK)

    def test_neznana_oznaka_napake_ne_narise_nicesar(
        self, obiskovalec: PrijavljenOdjemalec
    ) -> None:
        stran = obiskovalec.get(f"{registracija.POT}?napaka=Vpiši+geslo+na+zlobna.test")

        assert "zlobna.test" not in stran.text
        assert 'class="obvestilo' not in stran.text

    def test_zavrnjena_privolitev_pove_v_oknu_registracije(
        self, obiskovalec: PrijavljenOdjemalec
    ) -> None:
        stanje = _zacni_registracijo(obiskovalec)

        odgovor = obiskovalec.get(
            google.POT_POVRATNA, params={"error": "access_denied", "state": stanje}
        )

        assert odgovor.headers["location"] == f"{registracija.POT}?napaka=zavrnjeno"

    def test_prijavljen_stars_z_neznanim_googlom_ne_pride_do_obrazca(
        self, aplikacija_g: FastAPI, motor: Engine, stars: str
    ) -> None:
        """Sicer bi obrazec prijavljenemu ustvaril drugo družino in zamenjal sejo."""
        with _odjemalec_za(aplikacija_g, motor, stars) as odjemalec:
            ponarejeno = google.novo_stanje(google.Namen.REGISTRACIJA)
            odjemalec.cookies.set(google.PISKOTEK_STANJA, ponarejeno.zapis())

            odgovor = _povratek(odjemalec, ponarejeno.nakljucje)

            assert google.OZNAKA_NEPOVEZAN in odgovor.headers["location"]
            assert not odjemalec.cookies.get(registracija.PISKOTEK)


# --- Oddaja obrazca -----------------------------------------------------------


class TestOddaja:
    """Kriterij: šele oddan obrazec ustvari družino `čaka`, starša, poverilnico in sejo."""

    def test_srecna_pot(self, obiskovalec: PrijavljenOdjemalec, motor: Engine) -> None:
        prej = _stetje(motor)
        pred = datetime.now(UTC) - timedelta(seconds=1)

        odgovor = _registriraj(obiskovalec, ime_druzine="  Kovačevi ", ime=" Ana K. ")

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == POT_RACUNA
        assert _stetje(motor) == tuple(n + 1 for n in prej)
        druzina = _edina_nova(motor)
        assert druzina.name == "Kovačevi"
        assert druzina.status == STANJE_CAKA
        assert druzina.is_active is True
        assert druzina.decided_at is None
        assert druzina.consent_at is not None, "čas potrditve soglasja se zapiše"
        assert druzina.consent_at.replace(tzinfo=UTC) >= pred
        with Session(motor) as seja:
            stars = seja.scalars(select(User).where(User.family_id == druzina.id)).one()
            poverilnica = seja.scalars(
                select(Credential).where(Credential.user_id == stars.id)
            ).one()
        assert (stars.role, stars.display_name) == (VLOGA_STARS, "Ana K.")
        assert stars.is_system_owner is False
        assert stars.is_active is True
        assert (poverilnica.kind, poverilnica.identifier) == (POVERILNICA_GOOGLE, SUB)
        assert poverilnica.label == EMAIL
        assert poverilnica.secret_hash is None
        # Seja je postavljena, istovetnost je porabljena.
        assert obiskovalec.cookies.get(prijava.PISKOTEK_SEJE)
        assert not obiskovalec.cookies.get(registracija.PISKOTEK)
        assert "Zahtevek je oddan" in obiskovalec.get(POT_RACUNA).text

    def test_brez_soglasja_nic_ne_nastane(
        self, obiskovalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        prej = _stetje(motor)

        odgovor = _registriraj(obiskovalec, soglasje=False)

        assert odgovor.status_code == 400
        assert registracija.SPOROCILO_BREZ_SOGLASJA in odgovor.text
        assert _stetje(motor) == prej
        assert not obiskovalec.cookies.get(prijava.PISKOTEK_SEJE)
        # Vnos se vrne, obrazec je še vedno obrazec.
        assert 'value="Kovačevi"' in odgovor.text
        assert "Še en korak" in odgovor.text

    @pytest.mark.parametrize(
        ("vnos", "sporocilo"),
        [
            ({"ime_druzine": "   "}, registracija.SPOROCILO_PRAZNO_IME_DRUZINE),
            ({"ime": ""}, clani.SPOROCILO_PRAZNO_IME),
            (
                {"ime_druzine": "K" * (sistem.NAJDALJSE_IME_DRUZINE + 1)},
                sistem.SPOROCILO_PREDOLGO_IME_DRUZINE,
            ),
            ({"ime": "A" * (clani.NAJDALJSE_IME + 1)}, clani.SPOROCILO_PREDOLGO_IME),
            # Postgres znaka NUL ne sprejme; javni obrazec nanj ne sme dati 500.
            ({"ime": "Ana\x00"}, registracija.SPOROCILO_NEVELJAVEN_ZNAK),
            ({"ime_druzine": "\x00Kovačevi"}, registracija.SPOROCILO_NEVELJAVEN_ZNAK),
        ],
    )
    def test_neveljaven_vnos_nic_ne_ustvari(
        self,
        obiskovalec: PrijavljenOdjemalec,
        motor: Engine,
        vnos: dict[str, str],
        sporocilo: str,
    ) -> None:
        prej = _stetje(motor)

        odgovor = _registriraj(obiskovalec, **vnos)

        assert odgovor.status_code == 400
        assert sporocilo in odgovor.text
        assert _stetje(motor) == prej

    def test_brez_csrf_zetona(self, obiskovalec: PrijavljenOdjemalec, motor: Engine) -> None:
        _do_obrazca(obiskovalec)
        prej = _stetje(motor)

        odgovor = obiskovalec.post(
            registracija.POT,
            data={"csrf": "ni-pravi", "ime_druzine": "K", "ime": "A", "soglasje": "da"},
        )

        assert odgovor.status_code == 403
        assert _stetje(motor) == prej

    def test_brez_piskotka_istovetnosti(
        self, obiskovalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Obrazec, oddan mimo Googla, nima koga registrirati."""
        stran = obiskovalec.get(registracija.POT)
        prej = _stetje(motor)

        odgovor = _oddaj(obiskovalec, stran)

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == f"{registracija.POT}?napaka=poteklo"
        assert _stetje(motor) == prej

    def test_ponarejen_piskotek(self, obiskovalec: PrijavljenOdjemalec, motor: Engine) -> None:
        """Napadalec si podpiše tuj `sub` s svojim ključem."""
        stran = _do_obrazca(obiskovalec)
        zrtev = registracija.Istovetnost(sub="sub-zrtve", email="zrtev@primer.test", name="Ž")
        _podtakni_istovetnost(
            obiskovalec, registracija.zapisi_istovetnost(zrtev, b"n" * 32, datetime.now(UTC))
        )
        prej = _stetje(motor)

        odgovor = _oddaj(obiskovalec, stran)

        assert odgovor.headers["location"] == f"{registracija.POT}?napaka=poteklo"
        assert _stetje(motor) == prej

    def test_potekel_piskotek(
        self, obiskovalec: PrijavljenOdjemalec, motor: Engine, aplikacija_g: FastAPI
    ) -> None:
        stran = _do_obrazca(obiskovalec)
        kdo = registracija.Istovetnost(sub=SUB, email=EMAIL, name="Ana")
        nekoc = datetime.now(UTC) - registracija.VELJAVNOST - timedelta(seconds=1)
        _podtakni_istovetnost(
            obiskovalec,
            registracija.zapisi_istovetnost(kdo, aplikacija_g.state.kljuc_registracije, nekoc),
        )
        prej = _stetje(motor)

        odgovor = _oddaj(obiskovalec, stran)

        assert odgovor.headers["location"] == f"{registracija.POT}?napaka=poteklo"
        assert _stetje(motor) == prej
        assert registracija.SPOROCILO_POTEKLO in obiskovalec.get(odgovor.headers["location"]).text

    def test_sub_in_enaslov_iz_telesa_se_ne_upostevata(
        self, obiskovalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        odgovor = _registriraj(
            obiskovalec, sub="tuj-sub", email="tuj@primer.test", identifier="tuj-sub"
        )

        assert odgovor.status_code == 303
        with Session(motor) as seja:
            poverilnica = seja.scalars(
                select(Credential).where(Credential.kind == POVERILNICA_GOOGLE)
            ).one()
        assert (poverilnica.identifier, poverilnica.label) == (SUB, EMAIL)

    def test_dvojna_oddaja_ne_naredi_dveh_druzin(
        self, aplikacija_g: FastAPI, obiskovalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Isti Google račun v dveh oknih: druga oddaja pade na enoličnosti `sub`."""
        with PrijavljenOdjemalec(
            aplikacija_g, base_url="https://testserver", follow_redirects=False
        ) as drugo_okno:
            druga_stran = _do_obrazca(drugo_okno)
            assert _registriraj(obiskovalec).status_code == 303
            po_prvi = _stetje(motor)

            odgovor = _oddaj(drugo_okno, druga_stran, ime_druzine="Dvojniki")

            assert odgovor.headers["location"] == f"{registracija.POT}?napaka=obstaja"
            assert _stetje(motor) == po_prvi
            assert not drugo_okno.cookies.get(prijava.PISKOTEK_SEJE)

    def test_geslo_nastane_med_googlom_in_oddajo(
        self, obiskovalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """E-naslov se proti geselnim poverilnicam preveri tudi ob oddaji."""
        stran = _do_obrazca(obiskovalec)
        ustvari_starsa(motor, identifikator=EMAIL)
        prej = _stetje(motor)

        odgovor = _oddaj(obiskovalec, stran)

        assert odgovor.headers["location"] == f"{registracija.POT}?napaka=geslo"
        assert _stetje(motor) == prej

    def test_ze_registriran_se_iz_okna_registracije_prijavi(
        self, aplikacija_g: FastAPI, obiskovalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """`ADR-062` H: znan `sub` se prijavi, druga družina ne nastane."""
        assert _registriraj(obiskovalec).status_code == 303
        po_prvi = _stetje(motor)

        with PrijavljenOdjemalec(
            aplikacija_g, base_url="https://testserver", follow_redirects=False
        ) as drug_brskalnik:
            povratek = _povratek(drug_brskalnik, _zacni_registracijo(drug_brskalnik))

            assert povratek.headers["location"] == prijava.PRIVZETI_CILJ
            assert drug_brskalnik.cookies.get(prijava.PISKOTEK_SEJE)
            assert not drug_brskalnik.cookies.get(registracija.PISKOTEK)
            # Družina še čaka, zato pregled pelje na „Moj račun".
            assert drug_brskalnik.get("/admin").headers["location"] == POT_RACUNA
        druzin, uporabnikov, poverilnic, _ = _stetje(motor)
        assert (druzin, uporabnikov, poverilnic) == po_prvi[:3]

    def test_prijavljen_stars_ne_odda_obrazca(
        self, aplikacija_g: FastAPI, motor: Engine, stars: str
    ) -> None:
        with _odjemalec_za(aplikacija_g, motor, stars) as odjemalec:
            kdo = registracija.Istovetnost(sub=SUB, email=EMAIL, name="Ana")
            odjemalec.cookies.set(
                registracija.PISKOTEK,
                registracija.zapisi_istovetnost(
                    kdo, aplikacija_g.state.kljuc_registracije, datetime.now(UTC)
                ),
            )
            odjemalec.cookies.set(prijava.PISKOTEK_CSRF_PRIJAVE, "zeton")
            prej = _stetje(motor)

            odgovor = odjemalec.post(
                registracija.POT,
                data={"csrf": "zeton", "ime_druzine": "Druga", "ime": "Ana", "soglasje": "da"},
            )

            assert odgovor.headers["location"] == prijava.PRIVZETI_CILJ
            assert _stetje(motor) == prej


# --- Meji javnega obrazca -----------------------------------------------------


def _napolni_cakajoce(motor: Engine, koliko: int) -> None:
    for i in range(koliko):
        ustvari_registrirano(motor, STANJE_CAKA, ime_druzine=f"Čakajoči {i}")


def _zabelezi_registracije(motor: Engine, koliko: int, ko: datetime) -> None:
    with Session(motor) as seja:
        for _ in range(koliko):
            seja.add(
                LoginAttempt(
                    id=str(uuid4()),
                    identifier=registracija.OZNAKA_POSKUSOV,
                    ip_address="172.18.0.1",
                    created_at=ko,
                )
            )
        seja.commit()


class TestMeji:
    """Kriterij: zgornja meja čakajočih in dnevna meja; obrazec pove „poskusi pozneje"."""

    def test_obrazec_ob_polni_vrsti_pove_in_ne_sprejme(
        self, obiskovalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        _napolni_cakajoce(motor, registracija.NAJVEC_CAKAJOCIH)

        stran = _do_obrazca(obiskovalec)
        prej = _stetje(motor)
        odgovor = _oddaj(obiskovalec, stran)

        assert registracija.SPOROCILO_PREVEC in stran.text
        assert re.search(r'type="submit"\s+disabled', stran.text)
        assert odgovor.status_code == 429
        assert registracija.SPOROCILO_PREVEC in odgovor.text
        assert _stetje(motor) == prej

    def test_tik_pod_mejo_sprejme(self, obiskovalec: PrijavljenOdjemalec, motor: Engine) -> None:
        _napolni_cakajoce(motor, registracija.NAJVEC_CAKAJOCIH - 1)

        stran = _do_obrazca(obiskovalec)

        assert registracija.SPOROCILO_PREVEC not in stran.text
        assert _oddaj(obiskovalec, stran).status_code == 303

    def test_zavrnjene_in_odobrene_ne_stejejo(
        self, obiskovalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        for i in range(registracija.NAJVEC_CAKAJOCIH):
            ustvari_registrirano(motor, STANJE_ZAVRNJENA, ime_druzine=f"Z{i}")
            ustvari_registrirano(motor, STANJE_ODOBRENA, ime_druzine=f"O{i}")

        assert _registriraj(obiskovalec).status_code == 303

    def test_dnevna_meja(self, obiskovalec: PrijavljenOdjemalec, motor: Engine) -> None:
        _zabelezi_registracije(
            motor, registracija.NAJVEC_NA_OKNO, datetime.now(UTC) - timedelta(hours=1)
        )
        prej = _stetje(motor)

        odgovor = _registriraj(obiskovalec)

        assert odgovor.status_code == 429
        assert registracija.SPOROCILO_PREVEC in odgovor.text
        assert _stetje(motor) == prej

    def test_dnevna_meja_pozabi_po_enem_dnevu(
        self, obiskovalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        _zabelezi_registracije(
            motor, registracija.NAJVEC_NA_OKNO, datetime.now(UTC) - timedelta(hours=25)
        )

        assert _registriraj(obiskovalec).status_code == 303

    def test_vsaka_registracija_steje_v_dnevno_mejo(
        self, obiskovalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        assert _registriraj(obiskovalec).status_code == 303

        with Session(motor) as seja:
            zapisi = list(
                seja.scalars(
                    select(LoginAttempt).where(
                        LoginAttempt.identifier == registracija.OZNAKA_POSKUSOV
                    )
                )
            )
        assert len(zapisi) == 1

    def test_neuspela_oddaja_ne_steje(
        self, obiskovalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        assert _registriraj(obiskovalec, soglasje=False).status_code == 400

        with Session(motor) as seja:
            assert not list(seja.scalars(select(LoginAttempt.id)))


# --- Zapora neodobrene družine ------------------------------------------------

#: Poti pod `/admin`, ki jih neodobrena družina **sme** (`ADR-062` J). Zapisane
#: na roko: vsaka nova odprta pot je odločitev in mora ta test podreti.
ODPRTE_NEODOBRENIM = frozenset(
    {
        ("GET", "/admin/login"),
        ("POST", "/admin/login"),
        ("GET", "/admin/register"),
        ("POST", "/admin/register"),
        ("POST", "/admin/logout"),
        ("GET", "/admin/racun"),
        ("GET", "/admin/racun/izbrisi"),
        ("POST", "/admin/racun/izbrisi"),
    }
)


def _poti_pod_adminom(aplikacija: FastAPI) -> list[tuple[str, str]]:
    return sorted(
        (metoda.upper(), pot)
        for pot, metode in aplikacija.openapi()["paths"].items()
        for metoda in metode
        if pot == "/admin" or pot.startswith("/admin/")
    )


class TestZapora:
    """Kriterij: vsaka pot pod `/admin` razen „Moj račun" in odjave preusmeri nanj.

    Seznam poti pride iz aplikacije, ne iz tega testa: pot, dodana jutri, je
    v njem sama od sebe, in usmerjevalnik, priklopljen mimo
    `main.USMERJEVALNIKI_ZA_ODOBRENE`, ga podre.
    """

    @pytest.mark.parametrize("stanje", [STANJE_CAKA, STANJE_ZAVRNJENA, "neznano-stanje"])
    def test_vsaka_pot_pelje_na_moj_racun(
        self, aplikacija: FastAPI, motor: Engine, stanje: str
    ) -> None:
        _, user_id = ustvari_registrirano(motor, stanje)
        poti = [p for p in _poti_pod_adminom(aplikacija) if p not in ODPRTE_NEODOBRENIM]
        assert len(poti) >= 60, "seznam poti je sumljivo kratek"

        with _odjemalec_za(aplikacija, motor, user_id) as odjemalec:
            prej = _stetje(motor)
            for metoda, pot in poti:
                if metoda == "POST":
                    odgovor = odjemalec.post(naslov(pot))
                else:
                    odgovor = odjemalec.request(metoda, naslov(pot))

                assert odgovor.status_code == 303, f"{metoda} {pot} → {odgovor.status_code}"
                assert odgovor.headers["location"] == POT_RACUNA, f"{metoda} {pot}"

        assert _stetje(motor) == prej

    def test_odprte_poti_so_res_pod_adminom(self, aplikacija: FastAPI) -> None:
        """Varovalo seznama zgoraj: v njem ni poti, ki je aplikacija nima."""
        assert set(_poti_pod_adminom(aplikacija)) >= ODPRTE_NEODOBRENIM

    def test_vsak_usmerjevalnik_pod_adminom_je_razporejen(self) -> None:
        """Nov usmerjevalnik mora biti ali zaprt ali izrecno odprt."""
        vsi = {
            modul.name: importlib.import_module(f"app.routers.{modul.name}").router
            for modul in pkgutil.iter_modules(app.routers.__path__)
        }
        pod_adminom = {
            ime
            for ime, usmerjevalnik in vsi.items()
            if any(pot.path.startswith("/admin") for pot in usmerjevalnik.routes)
        }
        zaprti = {
            ime for ime, u in vsi.items() if u in main.USMERJEVALNIKI_ZA_ODOBRENE
        }

        assert len(vsi) >= 12, "seznam usmerjevalnikov je sumljivo kratek"
        assert zaprti <= pod_adminom
        assert pod_adminom - zaprti == {"racun", "vstop"}

    def test_odobrena_druzina_ni_zaprta(
        self, aplikacija: FastAPI, motor: Engine
    ) -> None:
        _, user_id = ustvari_registrirano(motor, STANJE_ODOBRENA)

        with _odjemalec_za(aplikacija, motor, user_id) as odjemalec:
            for pot in ("/admin", "/admin/family", "/admin/days", "/admin/quizzes"):
                assert odjemalec.get(pot).status_code == 200, pot

    def test_stran_z_napako_neodobrenim_ne_kaze_menija(
        self, cakajoci: PrijavljenOdjemalec
    ) -> None:
        odgovor = cakajoci.get("/admin/te-strani-ni")

        assert odgovor.status_code == 404
        assert '<nav class="meni' not in odgovor.text

    def test_odjava_dela(self, cakajoci: PrijavljenOdjemalec) -> None:
        odgovor = cakajoci.post(prijava.POT_ODJAVE)

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == prijava.POT_PRIJAVE


# --- Moj račun ----------------------------------------------------------------


class TestMojRacun:
    def test_caka(self, cakajoci: PrijavljenOdjemalec) -> None:
        """Kriterij: stran pove, da mora račun odobriti administrator (skrbnik)."""
        stran = cakajoci.get(POT_RACUNA)

        assert stran.status_code == 200
        for kos in (
            "Zahtevek je oddan",
            "Račun mora odobriti skrbnik sistema",
            "Ana Kovač",
            "ana.kovac@primer.test",
            "Kovačevi",
            "E-pošte ne pošiljamo",
            "Zahtevek ne poteče",
            "1. 10. 2026",
        ):
            assert kos in stran.text, kos
        assert '<nav class="meni' not in stran.text
        assert "Izbriši moj račun" not in stran.text
        assert POT_IZBRISA not in stran.text
        assert f'action="{prijava.POT_ODJAVE}"' in stran.text

    def test_zavrnjena(self, zavrnjeni: PrijavljenOdjemalec) -> None:
        """Kriterij: samo, da je bil zahtevek zavrnjen, in „Izbriši moj račun"."""
        stran = zavrnjeni.get(POT_RACUNA)

        assert stran.status_code == 200
        assert "Zahtevek ni bil sprejet" in stran.text
        assert "3. 10. 2026" in stran.text, "datum zavrnitve"
        assert f'href="{POT_IZBRISA}"' in stran.text
        assert "Račun mora odobriti" not in stran.text
        assert '<nav class="meni' not in stran.text

    def test_izrise_se_tudi_brez_googla(self, cakajoci: PrijavljenOdjemalec) -> None:
        """`ADR-062` J: fixture `aplikacija` Googla nima; kdor čaka, stran vseeno vidi."""
        assert cakajoci.app.state.nastavitve.google_je_nastavljen is False  # type: ignore[attr-defined]
        assert cakajoci.get(POT_RACUNA).status_code == 200

    def test_googlovi_dejanji_sta_zaprti(
        self, aplikacija_g: FastAPI, motor: Engine
    ) -> None:
        _, user_id = ustvari_registrirano(motor, STANJE_CAKA)

        with _odjemalec_za(aplikacija_g, motor, user_id) as odjemalec:
            for pot in (google.POT_POVEZAVE, google.POT_ODSTRANITVE):
                odgovor = odjemalec.post(pot)
                assert odgovor.headers["location"] == POT_RACUNA, pot
        with Session(motor) as seja:
            assert seja.scalar(select(func.count(Credential.id))) == 1

    def test_odobrena_vidi_obicajno_stran(self, aplikacija_g: FastAPI, motor: Engine) -> None:
        _, user_id = ustvari_registrirano(motor, STANJE_ODOBRENA)

        with _odjemalec_za(aplikacija_g, motor, user_id) as odjemalec:
            stran = odjemalec.get(POT_RACUNA)

        assert "Načini prijave" in stran.text
        assert "Zahtevek" not in stran.text


# --- Izbris zavrnjenega računa ------------------------------------------------


class TestIzbris:
    def test_vmesna_stran_nic_ne_izbrise(
        self, zavrnjeni: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        prej = _stetje(motor)

        stran = zavrnjeni.get(POT_IZBRISA)

        assert stran.status_code == 200
        assert "Izbrisati račun?" in stran.text
        assert "registriraš znova" in stran.text
        assert _stetje(motor) == prej

    def test_izbris_odstrani_druzino_starsa_poverilnice_in_seje(
        self, aplikacija: FastAPI, motor: Engine
    ) -> None:
        family_id, user_id = ustvari_registrirano(motor, STANJE_ZAVRNJENA, sub=SUB)
        ostali, _ = ustvari_registrirano(motor, STANJE_ZAVRNJENA, ime_druzine="Drugi")
        prej = _stetje(motor)

        with _odjemalec_za(aplikacija, motor, user_id) as odjemalec:
            with _odjemalec_za(aplikacija, motor, user_id):  # druga seja istega starša
                odgovor = odjemalec.post(POT_IZBRISA)

            assert odgovor.status_code == 303
            assert odgovor.headers["location"] == f"{prijava.POT_PRIJAVE}?napaka=izbrisan"
            # Piškotek seje je preklican (testni odjemalec ga je dobil brez
            # domene, zato se preverja glava in ne posoda).
            piskotek = next(
                g for g in odgovor.headers.get_list("set-cookie") if g.startswith("seja=")
            )
            assert "Max-Age=0" in piskotek
            assert google.SPOROCILO_IZBRISAN in odjemalec.get(odgovor.headers["location"]).text

        assert _druzina(motor, family_id) is None
        with Session(motor) as seja:
            assert seja.get(User, user_id) is None
            assert not list(seja.scalars(select(Credential).where(Credential.identifier == SUB)))
            assert not list(seja.scalars(select(UserSession).where(UserSession.user_id == user_id)))
        # Natanko ena družina, en starš, ena poverilnica in obe seji manj.
        assert _stetje(motor) == (prej[0] - 1, prej[1] - 1, prej[2] - 1, prej[3])
        assert _druzina(motor, ostali) is not None, "tuja zavrnjena družina ostane"
        assert _druzina(motor, CVEK_ID) is not None

    def test_po_izbrisu_se_isti_google_registrira_znova(
        self, aplikacija_g: FastAPI, obiskovalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        assert _registriraj(obiskovalec).status_code == 303
        prva = _edina_nova(motor)
        with Session(motor) as seja:
            seja.get(Family, prva.id).status = STANJE_ZAVRNJENA  # type: ignore[union-attr]
            seja.commit()
        obiskovalec.csrf = zeton_obrazca(obiskovalec.get(POT_IZBRISA).text)
        assert obiskovalec.post(POT_IZBRISA).status_code == 303

        odgovor = _registriraj(obiskovalec, ime_druzine="Kovačevi znova")

        assert odgovor.status_code == 303
        nova = _edina_nova(motor)
        assert (nova.name, nova.status) == ("Kovačevi znova", STANJE_CAKA)
        assert nova.id != prva.id

    def test_cakajoci_ne_more_izbrisati(
        self, cakajoci: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        prej = _stetje(motor)

        assert cakajoci.get(POT_IZBRISA).status_code == 403
        odgovor = cakajoci.post(POT_IZBRISA)

        assert odgovor.status_code == 403
        assert _stetje(motor) == prej

    def test_odobreni_ne_more_izbrisati(self, aplikacija: FastAPI, motor: Engine) -> None:
        family_id, user_id = ustvari_registrirano(motor, STANJE_ODOBRENA)

        with _odjemalec_za(aplikacija, motor, user_id) as odjemalec:
            assert odjemalec.get(POT_IZBRISA).status_code == 403
            assert odjemalec.post(POT_IZBRISA).status_code == 403

        assert _druzina(motor, family_id) is not None

    @pytest.mark.parametrize("stanje", [STANJE_CAKA, STANJE_ODOBRENA])
    def test_repozitorij_izbrise_samo_zavrnjeno(self, motor: Engine, stanje: str) -> None:
        """Pogoj je v stavku, ne le v usmerjevalniku: odobritev, ki pride vmes, zmaga."""
        family_id, _ = ustvari_registrirano(motor, stanje)
        prej = _stetje(motor)

        with Session(motor) as seja:
            assert ClaniRepository(seja, family_id).izbrisi_zavrnjeno_druzino() is False

        assert _stetje(motor) == prej

    def test_brez_csrf_zetona(self, zavrnjeni: PrijavljenOdjemalec, motor: Engine) -> None:
        prej = _stetje(motor)

        odgovor = zavrnjeni.post(POT_IZBRISA, data={"csrf": "napacen"})

        assert odgovor.status_code == 403
        assert _stetje(motor) == prej


# --- Lastnik sistema ----------------------------------------------------------


class TestLastnik:
    def test_seznam_cakajocih(self, lastnikov: PrijavljenOdjemalec, motor: Engine) -> None:
        """Kriterij: ime družine, ime starša, Googlov e-naslov, datum."""
        family_id, _ = ustvari_registrirano(motor, STANJE_CAKA)

        stran = lastnikov.get("/admin/system").text

        assert "Čaka na odobritev" in stran
        for kos in ("Kovačevi", "Ana Kovač", "ana.kovac@primer.test", "1. 10. 2026"):
            assert kos in stran, kos
        assert f'href="/admin/system/families/{family_id}/approve"' in stran
        assert f'href="/admin/system/families/{family_id}/reject"' in stran

    def test_brez_cakajocih_razdelka_ni(self, lastnikov: PrijavljenOdjemalec) -> None:
        assert "Čaka na odobritev" not in lastnikov.get("/admin/system").text

    @pytest.mark.parametrize("dejanje", ["approve", "reject"])
    def test_vmesna_stran_nic_ne_spremeni(
        self, lastnikov: PrijavljenOdjemalec, motor: Engine, dejanje: str
    ) -> None:
        family_id, _ = ustvari_registrirano(motor, STANJE_CAKA)

        stran = lastnikov.get(f"/admin/system/families/{family_id}/{dejanje}")

        assert stran.status_code == 200
        assert "Kovačevi" in stran.text
        assert f'action="/admin/system/families/{family_id}/{dejanje}"' in stran.text
        druzina = _druzina(motor, family_id)
        assert druzina is not None
        assert (druzina.status, druzina.decided_at) == (STANJE_CAKA, None)

    def test_odobri(
        self, aplikacija: FastAPI, lastnikov: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        family_id, user_id = ustvari_registrirano(motor, STANJE_CAKA)

        odgovor = lastnikov.post(f"/admin/system/families/{family_id}/approve")

        assert odgovor.status_code == 303
        druzina = _druzina(motor, family_id)
        assert druzina is not None
        assert druzina.status == STANJE_ODOBRENA
        assert druzina.decided_at is not None
        # Staršu se ob naslednji zahtevi odpre vse; seja ostane ista.
        with _odjemalec_za(aplikacija, motor, user_id) as stars:
            assert stars.get("/admin").status_code == 200
            assert stars.get("/admin/family").status_code == 200

    def test_zavrni(self, lastnikov: PrijavljenOdjemalec, motor: Engine) -> None:
        family_id, user_id = ustvari_registrirano(motor, STANJE_CAKA)
        with Session(motor) as seja:
            sej_prej = seja.scalar(select(func.count(UserSession.id)))

        odgovor = lastnikov.post(f"/admin/system/families/{family_id}/reject")

        assert odgovor.status_code == 303
        druzina = _druzina(motor, family_id)
        assert druzina is not None
        assert druzina.status == STANJE_ZAVRNJENA
        assert druzina.decided_at is not None
        with Session(motor) as seja:
            assert seja.get(User, user_id) is not None, "zavrnitev ne briše"
            assert seja.scalar(select(func.count(UserSession.id))) == sej_prej

    def test_zavrnjeno_je_mogoce_pozneje_odobriti(
        self, lastnikov: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        family_id, _ = ustvari_registrirano(motor, STANJE_ZAVRNJENA)

        assert f"/admin/system/families/{family_id}/approve" in lastnikov.get("/admin/system").text
        odgovor = lastnikov.post(f"/admin/system/families/{family_id}/approve")

        assert odgovor.status_code == 303
        druzina = _druzina(motor, family_id)
        assert druzina is not None
        assert druzina.status == STANJE_ODOBRENA

    @pytest.mark.parametrize(
        ("stanje", "dejanje"),
        [
            (STANJE_ODOBRENA, "reject"),
            (STANJE_ODOBRENA, "approve"),
            (STANJE_ZAVRNJENA, "reject"),
        ],
    )
    def test_nedovoljen_prehod_je_409(
        self, lastnikov: PrijavljenOdjemalec, motor: Engine, stanje: str, dejanje: str
    ) -> None:
        """`ADR-062` K: odobrene ni mogoče zavrniti — po nobeni poti."""
        family_id, _ = ustvari_registrirano(motor, stanje)
        pot = f"/admin/system/families/{family_id}/{dejanje}"

        assert lastnikov.get(pot).status_code == 409
        assert lastnikov.post(pot).status_code == 409

        druzina = _druzina(motor, family_id)
        assert druzina is not None
        assert druzina.status == stanje

    def test_svoje_druzine_lastnik_ne_more_zavrniti(
        self, lastnikov: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        assert lastnikov.post(f"/admin/system/families/{CVEK_ID}/reject").status_code == 409
        druzina = _druzina(motor, CVEK_ID)
        assert druzina is not None
        assert druzina.status == STANJE_ODOBRENA

    @pytest.mark.parametrize("dejanje", ["approve", "reject"])
    def test_neznana_druzina(self, lastnikov: PrijavljenOdjemalec, dejanje: str) -> None:
        pot = f"/admin/system/families/{uuid4()}/{dejanje}"

        assert lastnikov.get(pot).status_code == 404
        assert lastnikov.post(pot).status_code == 404

    def test_repozitorij_prehoda_ne_izvede_iz_napacnega_stanja(self, motor: Engine) -> None:
        """Dve sočasni odločitvi: druga ne najde vrstice v pričakovanem stanju."""
        family_id, _ = ustvari_registrirano(motor, STANJE_ODOBRENA)

        with Session(motor) as seja:
            uspelo = DruzineRepository(seja).nastavi_stanje(
                family_id,
                iz=sistem.stanja_za_zavrnitev(),
                v=STANJE_ZAVRNJENA,
                ko=datetime.now(UTC),
            )

        assert uspelo is False
        druzina = _druzina(motor, family_id)
        assert druzina is not None
        assert druzina.status == STANJE_ODOBRENA

    @pytest.mark.parametrize("dejanje", ["approve", "reject"])
    def test_za_starsa_poti_ne_obstajata(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, dejanje: str
    ) -> None:
        """`ADR-045`: 404 na vsako metodo, stanje nespremenjeno."""
        family_id, _ = ustvari_registrirano(motor, STANJE_CAKA)
        pot = f"/admin/system/families/{family_id}/{dejanje}"

        assert odjemalec.get(pot).status_code == 404
        assert odjemalec.post(pot, follow_redirects=False).status_code == 404

        druzina = _druzina(motor, family_id)
        assert druzina is not None
        assert druzina.status == STANJE_CAKA

    def test_seznam_druzin_kaze_stanje(
        self, lastnikov: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        ustvari_registrirano(motor, STANJE_CAKA, ime_druzine="Čakajoči")
        ustvari_registrirano(motor, STANJE_ZAVRNJENA, ime_druzine="Zavrnjeni")

        stran = lastnikov.get("/admin/system").text

        for oznaka in ("čaka na odobritev", "odobrena", "zavrnjena"):
            assert f">{oznaka}</span>" in stran, oznaka

    def test_tabela_uporabnikov(self, lastnikov: PrijavljenOdjemalec, motor: Engine) -> None:
        """Kriterij: starši vseh družin; otroci **samo kot število**."""
        family_id, _ = ustvari_registrirano(motor, STANJE_CAKA)
        ustvari_otroka(motor, prikazno_ime="Maša Skrivnostna")
        ustvari_otroka(
            motor,
            user_id=str(uuid4()),
            family_id=family_id,
            identifikator="tuj-otrok",
            prikazno_ime="Tujček Neimenovani",
        )

        stran = lastnikov.get("/admin/system").text
        tabela = stran[stran.index("<h2>Uporabniki</h2>") :]

        for kos in ("Lastnik", "lastnik@primer.test", "Ana Kovač", "ana.kovac@primer.test"):
            assert kos in tabela, kos
        assert ">geslo<" in re.sub(r"\s+", "", tabela)
        assert ">Google<" in re.sub(r"\s+", "", tabela)
        assert "Maša Skrivnostna" not in stran
        assert "Tujček Neimenovani" not in stran
        assert "1 otrok" in stran

    def test_nove_strani_ne_berejo_vsebine(
        self, lastnikov: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """`ADR-044` B: lastnikove strani ne preberejo vsebine nobene družine."""
        family_id, _ = ustvari_registrirano(motor, STANJE_CAKA)
        stavki: list[str] = []

        def zabelezi(_p: object, _k: object, stavek: str, *_ostalo: object) -> None:
            stavki.append(stavek.lower())

        event.listen(motor, "before_cursor_execute", zabelezi)
        try:
            lastnikov.get("/admin/system")
            lastnikov.get(f"/admin/system/families/{family_id}/approve")
            lastnikov.post(f"/admin/system/families/{family_id}/approve")
        finally:
            event.remove(motor, "before_cursor_execute", zabelezi)

        assert len(stavki) > 5
        vsebina = (
            "materials",
            "questions",
            "quizzes",
            "quiz_items",
            "question_attempts",
            "schedules",
            "schedule_entries",
            "preizkusi",
        )
        for stavek in stavki:
            for tabela in vsebina:
                assert tabela not in stavek, stavek

    def test_rocni_obrazec_ustvari_odobreno(
        self, lastnikov: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Kriterij: ročni obrazec ostane in ustvari družino `odobrena`."""
        odgovor = lastnikov.post(
            "/admin/system/families",
            data={
                "ime_druzine": "Ročni",
                "ime": "Bojan",
                "enaslov": "bojan@primer.test",
                "geslo": "dolgo-geslo-12",
                "geslo_znova": "dolgo-geslo-12",
            },
        )

        assert odgovor.status_code == 303
        with Session(motor) as seja:
            druzina = seja.scalars(select(Family).where(Family.name == "Ročni")).one()
        assert druzina.status == STANJE_ODOBRENA
        assert druzina.consent_at is None

    def test_zahtevek_ne_potece(self, lastnikov: PrijavljenOdjemalec, motor: Engine) -> None:
        """Kriterij: zahtevek ne poteče — tudi leto star čaka in ga je mogoče odobriti."""
        family_id, _ = ustvari_registrirano(
            motor, STANJE_CAKA, oddano=datetime.now(UTC) - timedelta(days=400)
        )

        assert "Kovačevi" in lastnikov.get("/admin/system").text
        assert lastnikov.post(f"/admin/system/families/{family_id}/approve").status_code == 303


class TestStevecCakajocih:
    """Kriterij: število čakajočih je vidno v navigaciji lastnika."""

    def test_lastnik_vidi_stevilo_povsod(
        self, lastnikov: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        ustvari_registrirano(motor, STANJE_CAKA, ime_druzine="A")
        ustvari_registrirano(motor, STANJE_CAKA, ime_druzine="B")
        ustvari_registrirano(motor, STANJE_ZAVRNJENA, ime_druzine="C")

        for pot in ("/admin/family", "/admin/system", "/admin/days"):
            assert stevec(lastnikov.get(pot).text, "Sistem") == "2", pot

    def test_brez_cakajocih_stevca_ni(self, lastnikov: PrijavljenOdjemalec) -> None:
        assert stevec(lastnikov.get("/admin/family").text, "Sistem") is None

    def test_stars_ne_vidi_ne_postavke_ne_stevila(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        ustvari_registrirano(motor, STANJE_CAKA)

        meni = meni_strani(odjemalec.get("/admin/family").text)

        assert "Sistem" not in meni
        assert "meni-stevec" not in meni


# --- Prva stran po odobritvi --------------------------------------------------


class TestPoOdobritvi:
    """`ADR-062` E: `/admin` za družino brez otroka (posnetek 08)."""

    def test_registrirana_druzina_brez_otroka(self, aplikacija: FastAPI, motor: Engine) -> None:
        """Starš, ki se je registriral z Googlom in bil odobren: koraki in „Odobreno"."""
        _, user_id = ustvari_registrirano(motor, STANJE_ODOBRENA)

        with _odjemalec_za(aplikacija, motor, user_id) as odjemalec:
            stran = odjemalec.get("/admin").text

        assert "Pozdravljeni, Ana" in stran
        assert "Družina Kovačevi je odobrena" in stran
        assert ">Odobreno</span>" in stran
        assert 'class="koraki"' in stran
        assert '<nav class="meni' not in stran

    def test_lastnik_sistema_brez_otroka_ohrani_pregled_in_meni(
        self, lastnikov: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        """Stran brez menija bi lastniku skrila „Sistem" in število čakajočih."""
        ustvari_registrirano(motor, STANJE_CAKA)

        stran = lastnikov.get("/admin").text

        assert "Pozdravljeni" not in stran
        assert "Matematika" in stran
        assert stevec(stran, "Sistem") == "1"

    def test_stars_z_geslom_in_googlom_ni_registriran(
        self, aplikacija: FastAPI, motor: Engine, stars: str
    ) -> None:
        """Starš ročno odprte družine, ki je Google povezal pozneje, se ni registriral."""
        _povezi_google(motor, stars)

        with _odjemalec_za(aplikacija, motor, stars) as odjemalec:
            stran = odjemalec.get("/admin").text

        assert "Družina Cvek še nima otroka" in stran
        assert 'class="koraki"' not in stran
        assert ">Odobreno</span>" not in stran

    def test_stars_brez_vsake_poverilnice_ni_registriran(
        self, aplikacija: FastAPI, motor: Engine
    ) -> None:
        """Brez gesla še ne pomeni „registriran z Googlom" — Google mora biti."""
        _, user_id = ustvari_registrirano(motor, STANJE_ODOBRENA)
        with Session(motor) as seja:
            for poverilnica in seja.scalars(
                select(Credential).where(Credential.user_id == user_id)
            ):
                seja.delete(poverilnica)
            seja.commit()

        with _odjemalec_za(aplikacija, motor, user_id) as odjemalec:
            stran = odjemalec.get("/admin").text

        assert "Družina Kovačevi še nima otroka" in stran
        assert 'class="koraki"' not in stran

    def test_druzina_brez_otroka(self, odjemalec: PrijavljenOdjemalec) -> None:
        """Družina, ki jo je odprl lastnik: isti koraki naprej, brez zgodbe o registraciji."""
        stran = odjemalec.get("/admin").text

        assert "Pozdravljeni, Dejan" in stran
        # Stran nima menija, zato sama pove, čigava družina je to.
        assert "Družina Cvek še nima otroka" in stran
        assert "je odobrena" not in stran
        assert 'class="koraki"' not in stran
        assert ">Odobreno</span>" not in stran
        assert 'href="/admin/family?dodaj=otrok"' in stran
        assert 'href="/admin/schedule"' in stran
        assert "Namesti aplikacijo na otrokov telefon" in stran
        assert "dobiš od skrbnika" in stran
        assert f'action="{prijava.POT_ODJAVE}"' in stran
        assert '<nav class="meni' not in stran
        assert "Dobrodošla" not in stran, "pozdrav ne ugiba spola (`ADR-062` D)"

    def test_povezava_za_apk_iz_nastavitve(
        self, slike: Path, motor: Engine, stars: str
    ) -> None:
        nastavitve = naredi_testne_nastavitve(slike).model_copy(
            update={"apk_url": "https://primer.test/aplikacija.apk"}
        )
        aplikacija = create_app(nastavitve=nastavitve, motor=motor)
        with _odjemalec_za(aplikacija, motor, stars) as odjemalec:
            stran = odjemalec.get("/admin").text

        assert 'href="https://primer.test/aplikacija.apk"' in stran
        assert "dobiš od skrbnika" not in stran

    def test_z_otrokom_je_obicajen_pregled(
        self, odjemalec: PrijavljenOdjemalec, otrok: str
    ) -> None:
        stran = odjemalec.get("/admin").text

        assert "Pozdravljeni" not in stran
        assert '<nav class="meni' in stran
        assert "Matematika" in stran


# --- Starš brez geselne poverilnice (`ADR-062` O) ------------------------------


class TestStarsBrezGesla:
    def test_starseva_stran_ponastavitve_ne_ponudi_in_jo_zavrne(
        self, aplikacija: FastAPI, motor: Engine
    ) -> None:
        _, user_id = ustvari_registrirano(motor, STANJE_ODOBRENA)
        pot = f"/admin/family/members/{user_id}/password"

        with _odjemalec_za(aplikacija, motor, user_id) as odjemalec:
            seznam = odjemalec.get("/admin/family").text
            stran = odjemalec.get(pot)
            odgovor = odjemalec.post(
                pot, data={"geslo": "novo-geslo-tukaj", "geslo_znova": "novo-geslo-tukaj"}
            )

        assert pot not in seznam
        assert stran.status_code == 403
        assert odgovor.status_code == 403
        assert clani.SPOROCILO_STARS_BREZ_GESLA in odgovor.text

    def test_lastnikova_stran_ponastavitve_ne_ponudi_in_jo_zavrne(
        self, lastnikov: PrijavljenOdjemalec, motor: Engine
    ) -> None:
        family_id, user_id = ustvari_registrirano(motor, STANJE_ODOBRENA)
        pot = f"/admin/system/families/{family_id}/parents/{user_id}/password"

        stran = lastnikov.get(f"/admin/system/families/{family_id}").text
        odgovor = lastnikov.post(
            pot, data={"geslo": "novo-geslo-tukaj", "geslo_znova": "novo-geslo-tukaj"}
        )

        assert pot not in stran
        assert odgovor.status_code == 403
        assert clani.SPOROCILO_STARS_BREZ_GESLA in odgovor.text

    def test_stars_z_geslom_ga_se_vedno_ponastavi(
        self, odjemalec: PrijavljenOdjemalec, stars: str
    ) -> None:
        assert odjemalec.get(f"/admin/family/members/{stars}/password").status_code == 200
