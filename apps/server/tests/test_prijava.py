"""Prijava, seje in CSRF na admin strani (V3-R03).

Pokrivajo tabelo „Test casi" iz `docs/plan/V3-R03.md`; odločitve so v
`docs/odlocitve/ADR-027` in `ADR-035`.

Dva testa sta **generirana** in ne napisana na roko:

- dosegljivost: vsaka pot pod `/admin` iz `app.openapi()` mora brez seje
  peljati na prijavo;
- CSRF: vsak `POST` pod `/admin` mora brez žetona vrniti 403, in vsak obrazec
  v predlogah mora skrito polje imeti.

Ročni seznam bi novo pot spustil skozi tiho, in prav to je razlog, da kriterij
zahteva generiranje.
"""

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app import main, prijava
from app.models import VLOGA_OTROK, LoginAttempt, Material, UserSession
from app.routers import admin, clani, dnevi, kvizi, racun, sistem, statistika, urnik, vstop
from app.routers.admin import MAPA_PREDLOG
from app.security import SPOROCILO_BREZ_CSRF, SPOROCILO_NEVELJAVEN_ZETON
from tests.conftest import (
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

#: Vrednost, s katero se v generiranem testu zapolni `{parameter}` v poti.
VZOREC = "vzorec"


def poti_pod_adminom(aplikacija: FastAPI) -> list[tuple[str, str]]:
    """(metoda, pot) za vsako pot pod `/admin` razen prijave.

    Bere se iz `app.openapi()`, ker je to edini popoln seznam poti aplikacije —
    ročno vzdrževan seznam bi novo pot spustil mimo.
    """
    return sorted(
        (metoda.upper(), pot)
        for pot, metode in aplikacija.openapi()["paths"].items()
        for metoda in metode
        if pot.startswith("/admin") and pot != prijava.POT_PRIJAVE
    )


def naslov(pot: str) -> str:
    """Pot z zapolnjenimi parametri: `/admin/materials/{id}` → `/admin/materials/vzorec`."""
    return re.sub(r"\{[^}]+\}", VZOREC, pot)


def brez_pretvornika(pot: str) -> str:
    """`/admin/subjects/{koda:path}` → `/admin/subjects/{koda}`.

    Usmerjevalnik pretvornik zapiše, OpenAPI pa ne; brez te poenotitve bi
    se seznama razlikovala v poteh, ki sta v resnici isti.
    """
    return re.sub(r"\{([^}:]+):[^}]+\}", lambda u: "{" + u.group(1) + "}", pot)


def zeton_obrazca(besedilo: str) -> str:
    """CSRF žeton iz izrisane strani."""
    najdeno = re.search(r'name="csrf" value="([^"]+)"', besedilo)
    assert najdeno is not None, besedilo[:500]
    return najdeno.group(1)


def prijavi_se(
    odjemalec: TestClient,
    identifikator: str = STARS_IDENTIFIKATOR,
    geslo: str = GESLO_STARSA,
    *,
    cilj: str | None = None,
) -> Any:
    """Prijava skozi obrazec, kot jo opravi brskalnik."""
    stran = odjemalec.get(
        prijava.POT_PRIJAVE if cilj is None else f"{prijava.POT_PRIJAVE}?next={cilj}"
    )
    podatki = {
        "identifikator": identifikator,
        "geslo": geslo,
        "csrf": zeton_obrazca(stran.text),
    }
    if cilj is not None:
        podatki["cilj"] = zeton_cilja(stran.text)
    return odjemalec.post(prijava.POT_PRIJAVE, data=podatki, follow_redirects=False)


def zeton_cilja(besedilo: str) -> str:
    """Vrednost skritega polja `cilj`, kot jo iz obrazca pošlje brskalnik.

    `unescape` ni kozmetika: Jinja `&` v vrednosti zapiše kot `&amp;`, brskalnik
    pa v `POST` pošlje odubežano vrednost. Brez tega bi test cilj z dvema
    parametroma poslal drugače od brskalnika.
    """
    najdeno = re.search(r'name="cilj" value="([^"]*)"', besedilo)
    assert najdeno is not None, besedilo[:500]
    return unescape(najdeno.group(1))


def sej_v_bazi(motor: Engine) -> int:
    with Session(motor) as seja:
        return len(list(seja.scalars(select(UserSession.id))))


@pytest.fixture
def brez_prijave(aplikacija: FastAPI, motor: Engine) -> Iterator[PrijavljenOdjemalec]:
    """Odjemalec brez seje, z ustvarjenim staršem v bazi."""
    ustvari_starsa(motor)
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
        yield odjemalec


class TestDosegljivost:
    """Kriterij: brez seje ni dosegljivo nič pod `/admin`."""

    def test_vsaka_pot_pod_adminom_brez_seje_pelje_na_prijavo(
        self, aplikacija: FastAPI, brez_prijave: TestClient
    ) -> None:
        poti = poti_pod_adminom(aplikacija)
        assert len(poti) >= 20, "seznam poti je sumljivo kratek"

        for metoda, pot in poti:
            odgovor = brez_prijave.request(metoda, naslov(pot), follow_redirects=False)

            assert odgovor.status_code == 303, f"{metoda} {pot} → {odgovor.status_code}"
            assert odgovor.headers["location"].startswith(prijava.POT_PRIJAVE), (
                f"{metoda} {pot} pelje na {odgovor.headers['location']}"
            )

    def test_seznam_poti_iz_openapi_je_popoln(self, aplikacija: FastAPI) -> None:
        """Varovalo za generirani test zgoraj: `openapi()` mora videti vse poti.

        Seznam se bere iz `app.openapi()`, ker `app.routes` poti vključenih
        usmerjevalnikov ne razgrne (`docs/02-izkusnje.md`). Pot z
        `include_in_schema=False` pa v OpenAPI ne pride — in bi generiranemu
        testu ušla. Zato jo tu iščemo pri viru: v usmerjevalnikih samih.
        """
        iz_usmerjevalnikov = {
            (metoda, brez_pretvornika(pot.path))
            for modul in (
                admin,
                clani,
                dnevi,
                kvizi,
                racun,
                sistem,
                statistika,
                urnik,
                vstop,
            )
            for pot in modul.router.routes
            for metoda in getattr(pot, "methods", set())
            if pot.path.startswith("/admin")
        }
        iz_openapi = {
            (metoda.upper(), pot)
            for pot, metode in aplikacija.openapi()["paths"].items()
            for metoda in metode
            if pot.startswith("/admin")
        }

        assert iz_usmerjevalnikov == iz_openapi

    def test_vsak_post_pod_adminom_prenese_ne_ascii_zeton(
        self, odjemalec: PrijavljenOdjemalec, aplikacija: FastAPI
    ) -> None:
        """Ne-ASCII CSRF žeton je **zavrnitev**, ne 500 (popravljeno v V3-R08).

        `secrets.compare_digest` nad `str` zahteva čiste ASCII znake in sicer
        vrže `TypeError`. Žeton pride iz obrazca, torej od zunaj, zato je bila
        taka izjema 500 z golim angleškim besedilom na **vsakem** `POST` pod
        `/admin` — kar `CLAUDE.md` §1b izrecno prepoveduje.

        Test se generira iz `openapi()` in ne našteva poti ročno: pot, ki bo
        dodana jutri, mora biti pokrita brez posega v ta test — isto sklepanje
        kot pri generiranem testu dosegljivosti zgoraj.
        """
        posti = [
            (metoda, pot)
            for pot, metode in aplikacija.openapi()["paths"].items()
            for metoda in metode
            if pot.startswith("/admin") and metoda.upper() == "POST"
        ]
        assert len(posti) >= 7, "seznam POST poti je sumljivo kratek"

        for _, pot in posti:
            odgovor = odjemalec.post(
                brez_pretvornika(pot).replace("{", "").replace("}", ""),
                data={"csrf": "\u017e"},
                follow_redirects=False,
            )
            assert odgovor.status_code != 500, f"POST {pot} → 500"
            assert "Internal Server Error" not in odgovor.text, pot

    def test_izvzete_predpone_ostanejo_enoclanske(self) -> None:
        """`/admin` je edina predpona, ki je `ZetonMiddleware` ne varuje.

        Varovalo in ne komentar (`docs/odlocitve/ADR-046` B): vsaka predpona na
        tem seznamu je cela veja poti brez te plasti, in `V3-R08` je pokazal,
        da je nove Googlove poti mogoče izvzeti **poimensko**. Naslednja
        zahteva naj predpone ne doda tiho. Isti vzorec kot pri
        `POTI_S_SVOJIM_CSRF` v `test_urnik.py`.
        """
        assert frozenset({"/admin"}) == main.IZVZETE_PREDPONE

    def test_poti_brez_seje_ostane_samo_prijava(self) -> None:
        """`SejaMiddleware` pod `/admin` nima druge izjeme kot prijavno stran.

        `V3-R08` je povezovanje Googla namenoma pustil pod `/admin` prav zato,
        da te izjeme ne bi potreboval (`ADR-046` B).
        """
        assert frozenset({prijava.POT_PRIJAVE}) == main.POTI_BREZ_SEJE

    def test_prijavna_stran_je_dosegljiva_brez_seje(self, brez_prijave: TestClient) -> None:
        odgovor = brez_prijave.get(prijava.POT_PRIJAVE)

        assert odgovor.status_code == 200
        assert "Prijava" in odgovor.text

    def test_zivost_ostane_brez_seje(self, brez_prijave: TestClient) -> None:
        """`GET /health` ne sme zahtevati ne ključa ne seje."""
        assert brez_prijave.get("/health").status_code == 200

    def test_pot_telefona_seje_brskalnika_ne_zahteva(
        self, brez_prijave: TestClient, telefon: SejaTesta
    ) -> None:
        """Telefon se izkaže z žetonom v glavi, ne s piškotkom (V3-R04)."""
        odgovor = brez_prijave.get("/quizzes/pending", headers=telefon.glave)

        assert odgovor.status_code == 200

    def test_pot_telefona_brez_zetona_ostane_401(self, brez_prijave: TestClient) -> None:
        """Regresija iz `ADR-006`, prepisana po `ADR-027`.

        Besedilo se je spremenilo iz „brez ključa" v „brez veljavnega žetona",
        namen pa ne: dokazati, da izvzetje `/admin` ni izvzelo telefona.
        """
        odgovor = brez_prijave.post(
            "/materials",
            data={"id": UUID_ENA, "subject": "MAT", "taken_at": "2026-09-04T07:30:00Z"},
            files={"file": ("posnetek.jpg", b"slika", "image/jpeg")},
        )

        assert odgovor.status_code == 401


class TestUspesnaPrijava:
    def test_prijava_postavi_sejo_in_piskotek_s_tremi_zastavicami(
        self, brez_prijave: TestClient, motor: Engine
    ) -> None:
        odgovor = prijavi_se(brez_prijave)

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == "/admin"
        piskotek = odgovor.headers["set-cookie"]
        assert piskotek.startswith(f"{prijava.PISKOTEK_SEJE}=")
        assert "HttpOnly" in piskotek
        assert "Secure" in piskotek
        assert "SameSite=lax" in piskotek.replace("samesite", "SameSite")
        assert sej_v_bazi(motor) == 1

    def test_po_prijavi_je_admin_dosegljiv(self, brez_prijave: TestClient) -> None:
        prijavi_se(brez_prijave)

        assert brez_prijave.get("/admin").status_code == 200

    def test_zeton_v_bazi_ni_zeton_iz_piskotka(
        self, brez_prijave: TestClient, motor: Engine
    ) -> None:
        odgovor = prijavi_se(brez_prijave)
        zeton = odgovor.cookies[prijava.PISKOTEK_SEJE]

        with Session(motor) as seja:
            zgostitve = list(seja.scalars(select(UserSession.token_hash)))

        assert zeton not in zgostitve
        assert zgostitve == [prijava.zgostitev_zetona(zeton)]

    @pytest.mark.parametrize(
        "zahtevana",
        [
            "/admin/days?obdobje=teden",
            # Dva parametra: tega naslova ne proizvaja test, ampak obrazec v
            # `predmeti.html`. Z neubeženim `&` se je cilj odrezal pri prvem
            # parametru in `vstop` je padel na privzetek — uporabnica je po
            # prijavi pristala na **drugem zaslonu**, ne le brez parametra.
            "/admin/quizzes/new?subject=MAT&vstop=rocna",
            "/admin/days?dan=2026-09-04&obdobje=dan",
        ],
    )
    def test_vrne_se_na_zahtevano_pot(self, brez_prijave: TestClient, zahtevana: str) -> None:
        preusmeritev = brez_prijave.get(zahtevana, follow_redirects=False)
        assert preusmeritev.status_code == 303

        na_prijavo = preusmeritev.headers["location"]
        stran = brez_prijave.get(na_prijavo)
        odgovor = brez_prijave.post(
            prijava.POT_PRIJAVE,
            data={
                "identifikator": STARS_IDENTIFIKATOR,
                "geslo": GESLO_STARSA,
                "csrf": zeton_obrazca(stran.text),
                "cilj": zeton_cilja(stran.text),
            },
            follow_redirects=False,
        )

        assert odgovor.headers["location"] == zahtevana

    @pytest.mark.parametrize(
        "tuj",
        ["https://zlo.example/", "//zlo.example/", "/materials", "/admin-drugo"],
    )
    def test_tuj_cilj_pelje_na_admin(self, brez_prijave: TestClient, tuj: str) -> None:
        """`next` sme biti samo relativna pot pod `/admin` (`ADR-035`)."""
        odgovor = prijavi_se(brez_prijave, cilj=tuj)

        assert odgovor.headers["location"] == "/admin"

    def test_post_brez_seje_cilja_ne_dobi(self, brez_prijave: TestClient) -> None:
        """Pot, ki obstaja samo kot `POST`, po prijavi z `GET` vrne 404.

        Vsebine obrazca vrnitev tako ali tako ne obnovi, zato je stran „ni
        najdeno" slabši izid od predmetov (`ADR-035` A).
        """
        odgovor = brez_prijave.post(
            "/admin/quizzes/preview", data={"csrf": ""}, follow_redirects=False
        )

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == prijava.POT_PRIJAVE


class TestNeuspesnaPrijava:
    """Sporočilo ne sme povedati, ali račun obstaja (`ADR-035` F)."""

    def test_napacno_geslo(self, brez_prijave: TestClient, motor: Engine) -> None:
        odgovor = prijavi_se(brez_prijave, geslo="to-ni-pravo-geslo")

        assert odgovor.status_code == 401
        assert prijava.SPOROCILO_NEUSPELA_PRIJAVA in odgovor.text
        assert prijava.PISKOTEK_SEJE not in odgovor.cookies
        assert sej_v_bazi(motor) == 0

    def test_neznan_identifikator_da_isto_sporocilo(self, brez_prijave: TestClient) -> None:
        odgovor = prijavi_se(brez_prijave, identifikator="ni-ga@primer.test")

        assert odgovor.status_code == 401
        assert prijava.SPOROCILO_NEUSPELA_PRIJAVA in odgovor.text

    def test_geslo_ni_nastavljeno(self, aplikacija: FastAPI, motor: Engine) -> None:
        """Tako stanje pusti migracija `0008_uporabniki` (`ADR-035` G)."""
        ustvari_starsa(motor, identifikator="brez-gesla@primer.test", geslo=None)

        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            odgovor = prijavi_se(
                odjemalec, identifikator="brez-gesla@primer.test", geslo="karkoli-12345"
            )

        assert odgovor.status_code == 401
        assert prijava.SPOROCILO_NEUSPELA_PRIJAVA in odgovor.text
        assert sej_v_bazi(motor) == 0

    def test_deaktiviran_racun(self, aplikacija: FastAPI, motor: Engine) -> None:
        ustvari_starsa(motor, identifikator="ugasnjen@primer.test", aktiven=False)

        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            odgovor = prijavi_se(odjemalec, identifikator="ugasnjen@primer.test")

        assert odgovor.status_code == 401
        assert prijava.SPOROCILO_NEUSPELA_PRIJAVA in odgovor.text
        assert sej_v_bazi(motor) == 0

    def test_otrok_dobi_razlago_in_ne_seje(self, aplikacija: FastAPI, motor: Engine) -> None:
        """Edina izjema od enotnega sporočila (`ADR-035` F)."""
        ustvari_starsa(
            motor,
            identifikator=OTROK_IDENTIFIKATOR,
            geslo=GESLO_OTROKA,
            vloga=VLOGA_OTROK,
            prikazno_ime="Maša",
        )

        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            odgovor = prijavi_se(odjemalec, identifikator=OTROK_IDENTIFIKATOR, geslo=GESLO_OTROKA)

        assert odgovor.status_code == 401
        assert prijava.SPOROCILO_OTROK in odgovor.text
        assert sej_v_bazi(motor) == 0

    def test_pravo_geslo_otroka_ne_steje_kot_neuspeh(
        self, aplikacija: FastAPI, motor: Engine
    ) -> None:
        ustvari_starsa(
            motor,
            identifikator=OTROK_IDENTIFIKATOR,
            geslo=GESLO_OTROKA,
            vloga=VLOGA_OTROK,
        )

        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            prijavi_se(odjemalec, identifikator=OTROK_IDENTIFIKATOR, geslo=GESLO_OTROKA)

        with Session(motor) as seja:
            assert list(seja.scalars(select(LoginAttempt.id))) == []


class TestCsrfNaPrijavi:
    """Brez tega bi te tuja stran lahko prijavila v **svoj** račun."""

    def test_brez_zetona_je_403(self, brez_prijave: TestClient, motor: Engine) -> None:
        odgovor = brez_prijave.post(
            prijava.POT_PRIJAVE,
            data={"identifikator": STARS_IDENTIFIKATOR, "geslo": GESLO_STARSA},
            follow_redirects=False,
        )

        assert odgovor.status_code == 403
        assert sej_v_bazi(motor) == 0

    def test_zeton_brez_piskotka_je_403(self, brez_prijave: TestClient) -> None:
        stran = brez_prijave.get(prijava.POT_PRIJAVE)
        zeton = zeton_obrazca(stran.text)
        brez_prijave.cookies.delete(prijava.PISKOTEK_CSRF_PRIJAVE)

        odgovor = brez_prijave.post(
            prijava.POT_PRIJAVE,
            data={
                "identifikator": STARS_IDENTIFIKATOR,
                "geslo": GESLO_STARSA,
                "csrf": zeton,
            },
            follow_redirects=False,
        )

        assert odgovor.status_code == 403


class TestOmejevanjeUgibanja:
    """5 neuspehov v 15 minutah → vsak nadaljnji poskus čaka (`ADR-035` E)."""

    def test_zamika_ni_pod_pragom(self) -> None:
        assert prijava.zamik_pred_preverbo(prijava.PRAG_POSKUSOV - 1) == 0.0

    def test_zamik_nad_pragom(self) -> None:
        assert prijava.zamik_pred_preverbo(prijava.PRAG_POSKUSOV) == prijava.ZAMIK_SEKUND

    def test_sesti_poskus_caka(
        self, brez_prijave: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cakanja: list[float] = []

        async def zabelezi(sekund: float) -> None:
            cakanja.append(sekund)

        monkeypatch.setattr("app.routers.vstop.asyncio.sleep", zabelezi)
        for _ in range(prijava.PRAG_POSKUSOV):
            prijavi_se(brez_prijave, geslo="to-ni-pravo-geslo")
        assert cakanja == []

        odgovor = prijavi_se(brez_prijave, geslo="to-ni-pravo-geslo")

        assert cakanja == [prijava.ZAMIK_SEKUND]
        # Sporočilo je isto: zaklep ni podatek, ki bi ga napadalec smel dobiti.
        assert prijava.SPOROCILO_NEUSPELA_PRIJAVA in odgovor.text

    def test_pravo_geslo_v_upocasnitvi_se_vedno_uspe(
        self, brez_prijave: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Upočasnitev, ne zaklep — sicer te lahko kdorkoli izklopi iz admina."""

        async def brez_cakanja(_sekund: float) -> None:
            return None

        monkeypatch.setattr("app.routers.vstop.asyncio.sleep", brez_cakanja)
        for _ in range(prijava.PRAG_POSKUSOV):
            prijavi_se(brez_prijave, geslo="to-ni-pravo-geslo")

        odgovor = prijavi_se(brez_prijave)

        assert odgovor.status_code == 303

    def test_uspesna_prijava_izbrise_stevce(
        self, brez_prijave: TestClient, motor: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def brez_cakanja(_sekund: float) -> None:
            return None

        monkeypatch.setattr("app.routers.vstop.asyncio.sleep", brez_cakanja)
        for _ in range(prijava.PRAG_POSKUSOV):
            prijavi_se(brez_prijave, geslo="to-ni-pravo-geslo")

        prijavi_se(brez_prijave)

        with Session(motor) as seja:
            assert list(seja.scalars(select(LoginAttempt.id))) == []

    def test_stari_poskusi_se_ne_stejejo(
        self, brez_prijave: TestClient, motor: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cakanja: list[float] = []

        async def zabelezi(sekund: float) -> None:
            cakanja.append(sekund)

        monkeypatch.setattr("app.routers.vstop.asyncio.sleep", zabelezi)
        for _ in range(prijava.PRAG_POSKUSOV):
            prijavi_se(brez_prijave, geslo="to-ni-pravo-geslo")
        with Session(motor) as seja:
            seja.execute(
                update(LoginAttempt).values(
                    created_at=datetime.now(UTC) - prijava.OKNO_POSKUSOV - timedelta(minutes=1)
                )
            )
            seja.commit()

        prijavi_se(brez_prijave, geslo="to-ni-pravo-geslo")

        assert cakanja == []


class TestEnakStrosekNeuspeha:
    """Odzivni čas ne sme povedati, ali račun obstaja (`ADR-035` F).

    Ure ne merimo — merjenje časa v testu je odvisno od stroja. Namesto tega
    štejemo klice zgoščevalnika: če jih pri neznanem identifikatorju ni, je
    odgovor hitrejši in razlika je merljiva od zunaj.
    """

    @staticmethod
    def _stej_preverbe(monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """Zamenja cel zgoščevalnik, ker je `verify` na njem samo za branje."""
        klici: list[str] = []
        pravi = prijava._ZGOSCEVALNIK

        class Stevec:
            def hash(self, geslo: str) -> str:
                return str(pravi.hash(geslo))

            def verify(self, zgostitev: str, geslo: str) -> bool:
                klici.append(zgostitev)
                return bool(pravi.verify(zgostitev, geslo))

        monkeypatch.setattr(prijava, "_ZGOSCEVALNIK", Stevec())
        return klici

    def test_neznan_identifikator_vseeno_preveri_zgostitev(
        self, brez_prijave: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        klici = self._stej_preverbe(monkeypatch)

        prijavi_se(brez_prijave, identifikator="ni-ga@primer.test")

        assert len(klici) == 1

    def test_racun_brez_gesla_vseeno_preveri_zgostitev(
        self, aplikacija: FastAPI, motor: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ustvari_starsa(motor, identifikator="brez-gesla@primer.test", geslo=None)
        klici = self._stej_preverbe(monkeypatch)

        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            prijavi_se(odjemalec, identifikator="brez-gesla@primer.test", geslo="karkoli-12345")

        assert len(klici) == 1


class TestSeja:
    def test_potekla_seja_pelje_na_prijavo_in_izgine(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        with Session(motor) as seja:
            seja.execute(
                update(UserSession).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            seja.commit()

        odgovor = odjemalec.get("/admin", follow_redirects=False)

        assert odgovor.status_code == 303
        assert sej_v_bazi(motor) == 0

    def test_neznan_zeton_pelje_na_prijavo(self, odjemalec: TestClient) -> None:
        odjemalec.cookies.set(prijava.PISKOTEK_SEJE, "tega-zetona-ni")

        odgovor = odjemalec.get("/admin", follow_redirects=False)

        assert odgovor.status_code == 303

    def test_drseci_rok_se_odmakne_po_uri(self, odjemalec: TestClient, motor: Engine) -> None:
        staro = datetime.now(UTC) - timedelta(hours=2)
        with Session(motor) as seja:
            seja.execute(update(UserSession).values(last_used_at=staro))
            seja.commit()

        odjemalec.get("/admin")

        with Session(motor) as seja:
            vrstica = seja.scalars(select(UserSession)).one()
            assert vrstica.last_used_at.replace(tzinfo=UTC) > staro
            assert vrstica.expires_at.replace(tzinfo=UTC) > datetime.now(UTC) + timedelta(days=29)

    def test_v_isti_uri_se_ne_osvezuje(self, odjemalec: TestClient, motor: Engine) -> None:
        """Sicer bi bila vsaka zahteva `UPDATE` (`ADR-035` B)."""
        odjemalec.get("/admin")
        with Session(motor) as seja:
            prej = seja.scalars(select(UserSession.last_used_at)).one()

        odjemalec.get("/admin")

        with Session(motor) as seja:
            assert seja.scalars(select(UserSession.last_used_at)).one() == prej

    def test_odjava_izbrise_sejo_in_piskotek(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        odgovor = odjemalec.post(prijava.POT_ODJAVE, follow_redirects=False)

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == prijava.POT_PRIJAVE
        assert sej_v_bazi(motor) == 0
        assert odjemalec.get("/admin", follow_redirects=False).status_code == 303

    def test_odjava_brez_zetona_ne_odjavi(self, odjemalec: TestClient, motor: Engine) -> None:
        odgovor = odjemalec.post(prijava.POT_ODJAVE, data={"csrf": "napacen"})

        assert odgovor.status_code == 403
        assert sej_v_bazi(motor) == 1

    def test_potekel_piskotek_pocisti_tudi_druge_potekle_seje(
        self, odjemalec: TestClient, motor: Engine, aplikacija: FastAPI
    ) -> None:
        """`ADR-035` C: čiščenje teče tudi na tej poti, ne le ob prijavi."""
        tuj = ustvari_starsa(motor, identifikator="druga@primer.test")
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as drug:
            prijavi(drug, motor, tuj)
        with Session(motor) as seja:
            seja.execute(
                update(UserSession).values(expires_at=datetime.now(UTC) - timedelta(days=1))
            )
            seja.commit()
        assert sej_v_bazi(motor) == 2

        odjemalec.get("/admin", follow_redirects=False)

        assert sej_v_bazi(motor) == 0

    def test_neuspela_prijava_pocisti_stare_poskuse(
        self, brez_prijave: TestClient, motor: Engine
    ) -> None:
        """Brez tega bi tabela rasla prav v stanju, ki ga pusti migracija.

        Dokler geslo ni nastavljeno, uspešne prijave ni — in če bi čiščenje
        viselo samo na njej, vrstic ne bi pobrisal nihče (`ADR-035` C).
        """
        with Session(motor) as seja:
            seja.add(
                LoginAttempt(
                    id="star",
                    identifier="nekdo@primer.test",
                    ip_address=None,
                    created_at=datetime.now(UTC) - prijava.HRAMBA_POSKUSOV - timedelta(days=1),
                )
            )
            seja.commit()

        prijavi_se(brez_prijave, geslo="to-ni-pravo-geslo")

        with Session(motor) as seja:
            assert "star" not in list(seja.scalars(select(LoginAttempt.id)))

    def test_prijava_pocisti_potekle_seje(
        self, brez_prijave: TestClient, motor: Engine, aplikacija: FastAPI
    ) -> None:
        """Čiščenje ob prijavi in ne v workerju — ta brez ključa OpenAI ne teče."""
        tuj = ustvari_starsa(motor, identifikator="druga@primer.test")
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as drug:
            prijavi(drug, motor, tuj)
        with Session(motor) as seja:
            seja.execute(
                update(UserSession).values(expires_at=datetime.now(UTC) - timedelta(days=1))
            )
            seja.commit()
        assert sej_v_bazi(motor) == 1

        prijavi_se(brez_prijave)

        # Ostane samo sveža seja te prijave.
        assert sej_v_bazi(motor) == 1
        with Session(motor) as seja:
            assert seja.scalars(select(UserSession.user_id)).one() != tuj


class TestCsrfPodAdminom:
    """Kriterij: `POST` brez žetona vrne 403 — na **vsaki** poti pod `/admin`."""

    def test_vsak_post_brez_zetona_je_403(self, aplikacija: FastAPI, odjemalec: TestClient) -> None:
        posti = [(m, p) for m, p in poti_pod_adminom(aplikacija) if m == "POST"]
        assert len(posti) >= 7, "seznam POST poti je sumljivo kratek"

        for _, pot in posti:
            odgovor = odjemalec.post(naslov(pot), data={"csrf": ""}, follow_redirects=False)

            assert odgovor.status_code == 403, f"POST {pot} → {odgovor.status_code}"
            assert SPOROCILO_BREZ_CSRF in odgovor.text

    def test_tuj_zeton_ne_velja(
        self, aplikacija: FastAPI, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)
        drug_stars = ustvari_starsa(motor, identifikator="druga@primer.test")
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as drug:
            prijavi(drug, motor, drug_stars)
            tuj_zeton = drug.csrf

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/archive",
            data={"csrf": tuj_zeton},
            follow_redirects=False,
        )

        assert odgovor.status_code == 403
        with Session(motor) as seja:
            assert seja.scalars(select(Material.archived_at)).one() is None

    def test_z_zetonom_dejanje_uspe(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Test zgoraj ni prazen: z žetonom ista pot deluje."""
        snov(motor, slike, UUID_ENA)

        odgovor = odjemalec.post(f"/admin/materials/{UUID_ENA}/archive", follow_redirects=False)

        assert odgovor.status_code == 303
        with Session(motor) as seja:
            assert seja.scalars(select(Material.archived_at)).one() is not None

    @pytest.mark.parametrize("metoda", ["DELETE", "PUT", "PATCH"])
    def test_nevarna_metoda_brez_zetona_je_403(self, odjemalec: TestClient, metoda: str) -> None:
        """Pravilo je „vse razen `GET`/`HEAD`", ne „samo `POST`".

        Takih poti pod `/admin` danes ni; `V3-R06` jih bo dodajal in plast, ki
        bi naštevala metode, bi novo spustila brez žetona.
        """
        odgovor = odjemalec.request(metoda, "/admin", follow_redirects=False)

        assert odgovor.status_code == 403
        assert SPOROCILO_BREZ_CSRF in odgovor.text

    def test_vsak_obrazec_v_predlogah_nosi_skrito_polje(self) -> None:
        """403 na poti ne pomaga, če obrazec žetona ne pošlje."""
        obrazci = 0
        for pot in sorted(MAPA_PREDLOG.glob("*.html")):
            vrstice = pot.read_text(encoding="utf-8").split("\n")
            for stevilka, vrstica in enumerate(vrstice):
                if 'method="post"' not in vrstica:
                    continue
                obrazci += 1
                naslednja = vrstice[stevilka + 1]
                assert 'name="csrf"' in naslednja, f"{pot.name}, vrstica {stevilka + 1}"

        assert obrazci >= 9, "obrazcev je manj, kot jih je stran imela"


class TestGlavaStrani:
    """Kriterij (dodan v fazi 1): glava pove, čigavo družino gledaš in kdo si."""

    def test_glava_pokaze_druzino_uporabnika_in_odjavo(self, odjemalec: TestClient) -> None:
        besedilo = odjemalec.get("/admin").text

        assert "Cvek" in besedilo
        assert "Dejan" in besedilo
        assert "Odjava" in besedilo
        assert f'action="{prijava.POT_ODJAVE}"' in besedilo

    def test_prijavna_stran_glave_nima(self, brez_prijave: TestClient) -> None:
        besedilo = brez_prijave.get(prijava.POT_PRIJAVE).text

        # Ne išče besede „Odjava": ta stoji tudi v komentarju sloga v ogrodju.
        assert f'action="{prijava.POT_ODJAVE}"' not in besedilo
        assert '<span class="druzina">' not in besedilo
        assert "Cvek" not in besedilo


class TestPrijavaTelefona:
    """`POST /auth/login` in `POST /auth/logout` (V3-R04, `ADR-036` G).

    Ista preverba kot v brskalniku, drug prenosnik: JSON namesto obrazca,
    žeton v odgovoru namesto piškotka, in brez CSRF — brez piškotka ga ni
    treba. Kar tu ni podvojeno iz razredov zgoraj, je to, kar je za obe poti
    isto (omejevanje, enak strošek neuspeha, čiščenje poteklih sej): tega ne
    določa prenosnik, ampak `app/prijava.py`.
    """

    def prijavi(
        self,
        odjemalec: TestClient,
        identifikator: str = OTROK_IDENTIFIKATOR,
        geslo: str = GESLO_OTROKA,
    ) -> Any:
        return odjemalec.post(
            prijava.POT_PRIJAVE_TELEFONA,
            json={"identifier": identifikator, "password": geslo},
        )

    def test_otrok_dobi_zeton_in_svoje_ime(self, brez_prijave: TestClient, motor: Engine) -> None:
        user_id = ustvari_otroka(motor)

        odgovor = self.prijavi(brez_prijave)

        assert odgovor.status_code == 200
        telo = odgovor.json()
        assert telo["user_id"] == user_id
        assert telo["display_name"] == "Maša"
        assert len(telo["token"]) >= 32
        assert sej_v_bazi(motor) == 1

    def test_zeton_v_odgovoru_odpre_poti_telefona(
        self, brez_prijave: TestClient, motor: Engine
    ) -> None:
        ustvari_otroka(motor)
        zeton = self.prijavi(brez_prijave).json()["token"]

        odgovor = brez_prijave.get("/quizzes/pending", headers={"Authorization": f"Bearer {zeton}"})

        assert odgovor.status_code == 200

    def test_v_bazi_je_samo_zgostitev_zetona(self, brez_prijave: TestClient, motor: Engine) -> None:
        """Kdor prebere bazo, se z njeno vsebino ne more prijaviti (`ADR-035` B)."""
        ustvari_otroka(motor)
        zeton = self.prijavi(brez_prijave).json()["token"]

        with Session(motor) as seja:
            zgostitve = list(seja.scalars(select(UserSession.token_hash)))

        assert zgostitve == [prijava.zgostitev_zetona(zeton)]
        assert zeton not in zgostitve

    def test_piskotka_ne_postavi(self, brez_prijave: TestClient, motor: Engine) -> None:
        """Telefon piškotkov nima; postavljen piškotek bi bil tiha druga pot."""
        ustvari_otroka(motor)

        odgovor = self.prijavi(brez_prijave)

        assert odgovor.cookies.get(prijava.PISKOTEK_SEJE) is None

    def test_stars_je_zavrnjen_z_razlago_in_brez_seje(
        self, brez_prijave: TestClient, motor: Engine
    ) -> None:
        """Zrcalno `ADR-035` F: vsaka vloga ima svoja vrata (`ADR-036` D)."""
        odgovor = self.prijavi(brez_prijave, identifikator=STARS_IDENTIFIKATOR, geslo=GESLO_STARSA)

        assert odgovor.status_code == 401
        assert odgovor.json()["detail"] == prijava.SPOROCILO_STARS
        assert sej_v_bazi(motor) == 0

    def test_pravo_geslo_starsa_ne_steje_kot_neuspeh(
        self, brez_prijave: TestClient, motor: Engine
    ) -> None:
        """Geslo je pravo, le vrata so napačna — to ni ugibanje."""
        self.prijavi(brez_prijave, identifikator=STARS_IDENTIFIKATOR, geslo=GESLO_STARSA)

        with Session(motor) as seja:
            assert list(seja.scalars(select(LoginAttempt.id))) == []

    @pytest.mark.parametrize(
        ("identifikator", "geslo"),
        [
            (OTROK_IDENTIFIKATOR, "to-geslo-ni-pravo"),
            ("otrok-ki-ga-ni", GESLO_OTROKA),
        ],
    )
    def test_napacno_geslo_in_neznano_ime_dasta_isto_sporocilo(
        self, brez_prijave: TestClient, motor: Engine, identifikator: str, geslo: str
    ) -> None:
        ustvari_otroka(motor)

        odgovor = self.prijavi(brez_prijave, identifikator=identifikator, geslo=geslo)

        assert odgovor.status_code == 401
        assert odgovor.json()["detail"] == prijava.SPOROCILO_NEUSPELA_PRIJAVA
        assert sej_v_bazi(motor) == 0

    def test_deaktiviran_otrok_se_ne_prijavi(self, brez_prijave: TestClient, motor: Engine) -> None:
        """Deaktivacija pride z `V3-R06`; zastavica obstaja že od `V3-R03`."""
        ustvari_otroka(motor, aktiven=False)

        odgovor = self.prijavi(brez_prijave)

        assert odgovor.status_code == 401
        assert odgovor.json()["detail"] == prijava.SPOROCILO_NEUSPELA_PRIJAVA
        assert sej_v_bazi(motor) == 0

    def test_otrok_brez_nastavljenega_gesla_se_ne_prijavi(
        self, brez_prijave: TestClient, motor: Engine
    ) -> None:
        """Stanje, v katerem uporabnika pusti migracija (`ADR-035` G)."""
        ustvari_otroka(motor, geslo=None)

        odgovor = self.prijavi(brez_prijave, geslo="karkoli-pac")

        assert odgovor.status_code == 401
        assert sej_v_bazi(motor) == 0

    def test_neuspeh_se_steje_v_omejevanje(self, brez_prijave: TestClient, motor: Engine) -> None:
        """Ugibanje na telefonu gre v isto tabelo kot ugibanje v brskalniku."""
        ustvari_otroka(motor)

        self.prijavi(brez_prijave, geslo="to-geslo-ni-pravo")

        with Session(motor) as seja:
            identifikatorji = list(seja.scalars(select(LoginAttempt.identifier)))
        assert identifikatorji == [OTROK_IDENTIFIKATOR]

    def test_odjava_pobrise_sejo_in_zeton_neha_veljati(
        self, brez_prijave: TestClient, motor: Engine
    ) -> None:
        ustvari_otroka(motor)
        zeton = self.prijavi(brez_prijave).json()["token"]
        glave = {"Authorization": f"Bearer {zeton}"}

        odgovor = brez_prijave.post(prijava.POT_ODJAVE_TELEFONA, headers=glave)

        assert odgovor.status_code == 200
        assert odgovor.json() == {"logged_out": True}
        assert sej_v_bazi(motor) == 0
        assert brez_prijave.get("/quizzes/pending", headers=glave).status_code == 401

    def test_odjava_brez_zetona_je_401(self, brez_prijave: TestClient) -> None:
        """Brez seje ni ničesar za odjaviti; telefon žeton preprosto zavrže."""
        assert brez_prijave.post(prijava.POT_ODJAVE_TELEFONA).status_code == 401

    def test_odjava_pusti_seje_drugih_naprav(self, brez_prijave: TestClient, motor: Engine) -> None:
        """Ena naprava, ena seja. Odjava telefona ni odjava vseh naprav."""
        ustvari_otroka(motor)
        prva = self.prijavi(brez_prijave).json()["token"]
        self.prijavi(brez_prijave)

        brez_prijave.post(prijava.POT_ODJAVE_TELEFONA, headers={"Authorization": f"Bearer {prva}"})

        assert sej_v_bazi(motor) == 1


class TestVrataVeljajoTudiZaZeNastaloSejo:
    """Vloga se preveri ob **vsaki uporabi** seje, ne samo ob prijavi.

    Ta razred varuje luknjo, ki jo je odprla prav `V3-R04`: do nje otrokove
    seje ni bilo mogoče ustvariti, ker jo je admin zavrnil, zato je preverba ob
    prijavi zadoščala. Odkar telefon seje ustvarja, je isti neprozoren niz
    uporaben v obeh prenosnikih (`ADR-027`) — in brez te preverbe bi otrok s
    svojim žetonom v piškotku odprl celoten `/admin`.
    """

    def test_otrokov_zeton_v_piskotku_ne_odpre_admina(
        self, brez_prijave: TestClient, motor: Engine
    ) -> None:
        telefon = ustvari_sejo(motor, ustvari_otroka(motor))
        brez_prijave.cookies.set(prijava.PISKOTEK_SEJE, telefon.zeton)

        odgovor = brez_prijave.get("/admin", follow_redirects=False)

        assert odgovor.status_code == 303
        assert odgovor.headers["location"].startswith(prijava.POT_PRIJAVE)

    def test_starsev_zeton_v_glavi_ne_odpre_poti_telefona(
        self, brez_prijave: TestClient, motor: Engine
    ) -> None:
        brskalnik = ustvari_sejo(motor, ustvari_starsa(motor, identifikator="drug@primer.test"))

        odgovor = brez_prijave.get("/quizzes/pending", headers=brskalnik.glave)

        assert odgovor.status_code == 401
        assert odgovor.json()["detail"] == SPOROCILO_NEVELJAVEN_ZETON
