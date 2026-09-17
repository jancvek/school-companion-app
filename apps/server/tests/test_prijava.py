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
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app import prijava
from app.models import VLOGA_OTROK, LoginAttempt, Material, UserSession
from app.routers.admin import MAPA_PREDLOG
from app.security import SPOROCILO_BREZ_CSRF
from tests.conftest import (
    GESLO_OTROKA,
    GESLO_STARSA,
    OTROK_IDENTIFIKATOR,
    STARS_IDENTIFIKATOR,
    PrijavljenOdjemalec,
    prijavi,
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
    """Vrednost skritega polja `cilj` na prijavni strani."""
    najdeno = re.search(r'name="cilj" value="([^"]*)"', besedilo)
    assert najdeno is not None, besedilo[:500]
    return najdeno.group(1)


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

    def test_prijavna_stran_je_dosegljiva_brez_seje(self, brez_prijave: TestClient) -> None:
        odgovor = brez_prijave.get(prijava.POT_PRIJAVE)

        assert odgovor.status_code == 200
        assert "Prijava" in odgovor.text

    def test_zivost_ostane_brez_seje(self, brez_prijave: TestClient) -> None:
        """`GET /health` ne sme zahtevati ne ključa ne seje."""
        assert brez_prijave.get("/health").status_code == 200

    def test_pot_telefona_seje_ne_zahteva(self, brez_prijave: TestClient) -> None:
        """Pogodba s telefonom se v tej zahtevi ne spremeni (V3-R04 jo bo)."""
        from tests.conftest import KLJUC

        odgovor = brez_prijave.get("/quizzes/pending", headers={"X-API-Key": KLJUC})

        assert odgovor.status_code == 200

    def test_pot_telefona_brez_kljuca_ostane_401(self, brez_prijave: TestClient) -> None:
        """Regresija iz `ADR-006`: izvzetje `/admin` ni izvzelo telefona."""
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

    def test_vrne_se_na_zahtevano_pot(self, brez_prijave: TestClient) -> None:
        zahtevana = "/admin/days?obdobje=teden"
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

    def test_geslo_ni_nastavljeno(
        self, aplikacija: FastAPI, motor: Engine
    ) -> None:
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

    def test_otrok_dobi_razlago_in_ne_seje(
        self, aplikacija: FastAPI, motor: Engine
    ) -> None:
        """Edina izjema od enotnega sporočila (`ADR-035` F)."""
        ustvari_starsa(
            motor,
            identifikator=OTROK_IDENTIFIKATOR,
            geslo=GESLO_OTROKA,
            vloga=VLOGA_OTROK,
            prikazno_ime="Maša",
        )

        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
            odgovor = prijavi_se(
                odjemalec, identifikator=OTROK_IDENTIFIKATOR, geslo=GESLO_OTROKA
            )

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

    def test_odjava_brez_zetona_ne_odjavi(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        odgovor = odjemalec.post(prijava.POT_ODJAVE, data={"csrf": "napacen"})

        assert odgovor.status_code == 403
        assert sej_v_bazi(motor) == 1

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

    def test_vsak_post_brez_zetona_je_403(
        self, aplikacija: FastAPI, odjemalec: TestClient
    ) -> None:
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

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/archive", follow_redirects=False
        )

        assert odgovor.status_code == 303
        with Session(motor) as seja:
            assert seja.scalars(select(Material.archived_at)).one() is not None

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
