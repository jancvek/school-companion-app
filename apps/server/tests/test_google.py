"""Pravila Google prijave brez strežnika in brez omrežja (V3-R08).

Modul `app/google.py` je namenoma brez FastAPI in brez baze, zato ga je mogoče
preizkusiti tu — in prav zato je vezivo povratnega klica (`ADR-046` D)
preizkušeno kot pravilo, ne šele skozi pet preusmeritev.

Odjemalec je preizkušen prek `httpx.MockTransport`: omrežja se ne dotaknemo,
a prava koda odjemalca (sestava zahtev, razčlenitev odgovora, prevod napak v
slovenščino) teče v celoti.
"""

import httpx
import pytest

from app import google
from app.google import Namen, NapakaGoogla, RacunGoogla, Stanje
from app.settings import Settings

# --- Stanje: vezivo povratnega klica (`ADR-046` D) -------------------------


class TestStanje:
    """Kar loči „ta povratek je moj" od „ta povratek je nekoga drugega"."""

    def test_zapis_in_branje_se_ujameta(self) -> None:
        stanje = google.novo_stanje(Namen.POVEZAVA, "uporabnik-1")
        assert Stanje.iz_zapisa(stanje.zapis()) == stanje

    def test_prijava_nima_uporabnika(self) -> None:
        stanje = google.novo_stanje(Namen.PRIJAVA)
        assert stanje.user_id is None
        assert Stanje.iz_zapisa(stanje.zapis()) == stanje

    def test_nakljucje_je_vsakic_drugo(self) -> None:
        """Dve zaporedni vrednosti se ne smeta ujeti — sicer vezivo ne veže."""
        prvo = google.novo_stanje(Namen.PRIJAVA)
        drugo = google.novo_stanje(Namen.PRIJAVA)
        assert prvo.nakljucje != drugo.nakljucje

    @pytest.mark.parametrize(
        "zapis",
        [
            None,
            "",
            "povezava",
            "povezava.abc",
            "povezava.abc.def.ghi",
            "izmisljen.abc.def",
            "prijava..uporabnik",
            # Povezava **mora** nositi uporabnika; brez njega je pol veziva.
            "povezava.abc.",
        ],
        ids=[
            "brez",
            "prazen",
            "en-del",
            "dva-dela",
            "stirje-deli",
            "neznan-namen",
            "prazno-nakljucje",
            "povezava-brez-uporabnika",
        ],
    )
    def test_pokvarjen_zapis_ne_da_stanja(self, zapis: str | None) -> None:
        """Molk je zavrnitev: piškotek je poljuben vnos od zunaj."""
        assert Stanje.iz_zapisa(zapis) is None

    def test_ujemanje_stanja(self) -> None:
        stanje = google.novo_stanje(Namen.PRIJAVA)
        assert google.stanje_se_ujema(stanje, stanje.nakljucje)

    @pytest.mark.parametrize("iz_googla", [None, "", "drugo-nakljucje"])
    def test_neujemanje_stanja(self, iz_googla: str | None) -> None:
        stanje = google.novo_stanje(Namen.PRIJAVA)
        assert not google.stanje_se_ujema(stanje, iz_googla)

    def test_brez_piskotka_se_ne_ujame_nic(self) -> None:
        """Manjkajoč piškotek ne sme biti „ujema se", tudi ob pravem `state`."""
        assert not google.stanje_se_ujema(None, "karkoli")


class TestPovezavaPripadaSeji:
    """Drugi del veziva: povezovanje se mora vrniti pod isto sejo.

    Brez tega bi tok, začet pod eno sejo in vrnjen pod drugo, pripisal Google
    račun napačnemu staršu — napad, ki izgleda kot povsem običajno delovanje
    (`ADR-046` D).
    """

    def test_ista_seja_je_v_redu(self) -> None:
        stanje = google.novo_stanje(Namen.POVEZAVA, "uporabnik-1")
        assert google.povezava_pripada_seji(stanje, "uporabnik-1")

    def test_druga_seja_ne(self) -> None:
        stanje = google.novo_stanje(Namen.POVEZAVA, "uporabnik-1")
        assert not google.povezava_pripada_seji(stanje, "uporabnik-2")

    def test_brez_seje_ne(self) -> None:
        stanje = google.novo_stanje(Namen.POVEZAVA, "uporabnik-1")
        assert not google.povezava_pripada_seji(stanje, None)

    def test_prijava_seje_ne_potrebuje(self) -> None:
        """Pri prijavi uporabnika še ne poznamo; pravilo zato ne velja."""
        assert google.povezava_pripada_seji(google.novo_stanje(Namen.PRIJAVA), None)


# --- Naslovi ---------------------------------------------------------------


class TestNaslovi:
    def test_povratni_naslov_je_https_na_domeni(self) -> None:
        assert (
            google.povratni_naslov("solski.test")
            == "https://solski.test/auth/google/callback"
        )

    def test_naslov_privolitve_nosi_vse_potrebno(self) -> None:
        stanje = google.novo_stanje(Namen.PRIJAVA)
        naslov = google.naslov_privolitve(
            client_id="odjemalec-1", domena="solski.test", stanje=stanje
        )
        zahteva = httpx.URL(naslov)
        assert str(zahteva.copy_with(query=None)) == google.NASLOV_PRIVOLITVE
        parametri = dict(zahteva.params)
        assert parametri["client_id"] == "odjemalec-1"
        assert parametri["redirect_uri"] == google.povratni_naslov("solski.test")
        assert parametri["response_type"] == "code"
        assert parametri["state"] == stanje.nakljucje
        assert parametri["prompt"] == "select_account"

    def test_naslov_ne_prosi_za_vec_kot_istovetnost(self) -> None:
        """Obseg je tisto, kar starš na Googlovem zaslonu prebere o nas."""
        assert set(google.OBSEGI.split()) == {"openid", "email", "profile"}

    def test_v_naslovu_ni_uporabnika(self) -> None:
        """`user_id` ostane v piškotku in ne gre skozi Google.

        Naslov vidi brskalnik in ga zapiše v zgodovino; `state` je naključje,
        ki samo po sebi ne pove nič. Uporabnik v naslovu bi bil podatek o tem,
        kdo se prijavlja, poslan tretji strani brez potrebe.
        """
        stanje = google.novo_stanje(Namen.POVEZAVA, "uporabnik-1")
        naslov = google.naslov_privolitve(
            client_id="odjemalec-1", domena="solski.test", stanje=stanje
        )
        assert "uporabnik-1" not in naslov


# --- Razsodbe --------------------------------------------------------------


class TestRazsodbe:
    def test_potrjen_naslov_se_poveze(self) -> None:
        racun = RacunGoogla(sub="123", email="ana@primer.test", email_verified=True)
        assert google.zakaj_ne_sme_povezati(racun, ze_povezan=False) is None

    def test_nepotrjen_naslov_se_ne_poveze(self) -> None:
        racun = RacunGoogla(sub="123", email="ana@primer.test", email_verified=False)
        assert (
            google.zakaj_ne_sme_povezati(racun, ze_povezan=False)
            == google.SPOROCILO_NEPOTRJEN
        )

    def test_drugi_google_na_istem_racunu_ne_gre(self) -> None:
        """Sicer bi nastala druga vrstica, ki je vmesnik ne bi znal odstraniti."""
        racun = RacunGoogla(sub="456", email="ana@primer.test", email_verified=True)
        assert (
            google.zakaj_ne_sme_povezati(racun, ze_povezan=True)
            == google.SPOROCILO_ZE_POVEZAN
        )

    def test_odstranitev_z_geslom_gre(self) -> None:
        assert google.zakaj_ne_sme_odstraniti(ima_geslo=True) is None

    def test_odstranitev_brez_gesla_ne_gre(self) -> None:
        """Račun, ki bi se s tem zaklenil sam iz sebe (`ADR-046` G)."""
        assert (
            google.zakaj_ne_sme_odstraniti(ima_geslo=False)
            == google.SPOROCILO_ZADNJA_POVERILNICA
        )


# --- Odjemalec -------------------------------------------------------------


def _nastavitve() -> Settings:
    return Settings(
        database_url="sqlite://",
        google_client_id="odjemalec-1",
        google_client_secret="skrivnost-1",
        domena="solski.test",
    )


def _odjemalec(obdelovalec: object) -> google.OdjemalecGoogla:
    prenos = httpx.Client(transport=httpx.MockTransport(obdelovalec))  # type: ignore[arg-type]
    return google.naredi_odjemalca(_nastavitve(), prenos=prenos)


class TestOdjemalec:
    """Prava koda odjemalca nad ponarejenim prenosom. Omrežja se ne dotakne."""

    def test_srecna_pot(self) -> None:
        videno: list[httpx.Request] = []

        def obdelaj(zahteva: httpx.Request) -> httpx.Response:
            videno.append(zahteva)
            if str(zahteva.url) == google.NASLOV_ZETONA:
                return httpx.Response(200, json={"access_token": "zeton-1"})
            return httpx.Response(
                200,
                json={
                    "sub": "104829",
                    "email": "ana@primer.test",
                    "email_verified": True,
                    "name": "Ana",
                },
            )

        racun = _odjemalec(obdelaj).racun("koda-1")

        assert racun == RacunGoogla(
            sub="104829", email="ana@primer.test", email_verified=True
        )
        # Skrivnost gre v **telo** zahteve, nikoli v naslov: naslovi se
        # beležijo v posredniških strežnikih, telesa ne.
        assert "skrivnost-1" not in str(videno[0].url)
        assert b"skrivnost-1" in videno[0].content
        assert b"grant_type=authorization_code" in videno[0].content
        assert videno[1].headers["authorization"] == "Bearer zeton-1"

    def test_ime_in_slika_se_zavrzeta(self) -> None:
        """Podatek, ki ga ne potrebujemo, je podatek, ki ga ne hranimo."""

        def obdelaj(zahteva: httpx.Request) -> httpx.Response:
            if str(zahteva.url) == google.NASLOV_ZETONA:
                return httpx.Response(200, json={"access_token": "z"})
            return httpx.Response(
                200,
                json={
                    "sub": "1",
                    "email": "a@b.test",
                    "email_verified": True,
                    "name": "Ana",
                    "picture": "https://primer.test/a.jpg",
                },
            )

        racun = _odjemalec(obdelaj).racun("koda-1")
        assert not hasattr(racun, "picture")
        assert racun.sub == "1"

    def test_manjkajoc_email_verified_pomeni_nepotrjen(self) -> None:
        """Odsotnost potrdila ni potrdilo."""

        def obdelaj(zahteva: httpx.Request) -> httpx.Response:
            if str(zahteva.url) == google.NASLOV_ZETONA:
                return httpx.Response(200, json={"access_token": "z"})
            return httpx.Response(200, json={"sub": "1", "email": "a@b.test"})

        assert _odjemalec(obdelaj).racun("koda-1").email_verified is False

    def test_email_verified_kot_niz_ne_velja(self) -> None:
        """`"true"` ni `True`; primerjava je `is True` prav zaradi tega."""

        def obdelaj(zahteva: httpx.Request) -> httpx.Response:
            if str(zahteva.url) == google.NASLOV_ZETONA:
                return httpx.Response(200, json={"access_token": "z"})
            return httpx.Response(
                200, json={"sub": "1", "email": "a@b.test", "email_verified": "true"}
            )

        assert _odjemalec(obdelaj).racun("koda-1").email_verified is False

    @pytest.mark.parametrize(
        "odgovor",
        [
            httpx.Response(400, json={"error": "invalid_grant"}),
            httpx.Response(500, text="Internal Server Error"),
            httpx.Response(200, text="to ni JSON"),
            httpx.Response(200, json={"brez": "zetona"}),
            httpx.Response(200, json=["to ni predmet"]),
        ],
        ids=["400", "500", "ni-json", "brez-zetona", "ni-predmet"],
    )
    def test_neuspeh_pri_zetonu_da_slovensko_sporocilo(self, odgovor: httpx.Response) -> None:
        with pytest.raises(NapakaGoogla) as napaka:
            _odjemalec(lambda _: odgovor).racun("koda-1")
        assert str(napaka.value) == google.SPOROCILO_NEDOSEGLJIV

    def test_odgovor_brez_sub_ne_velja(self) -> None:
        """Brez `sub` ni ključa, po katerem bi poverilnica sploh obstajala."""

        def obdelaj(zahteva: httpx.Request) -> httpx.Response:
            if str(zahteva.url) == google.NASLOV_ZETONA:
                return httpx.Response(200, json={"access_token": "z"})
            return httpx.Response(200, json={"email": "a@b.test", "email_verified": True})

        with pytest.raises(NapakaGoogla) as napaka:
            _odjemalec(obdelaj).racun("koda-1")
        assert str(napaka.value) == google.SPOROCILO_NEDOSEGLJIV

    def test_nedosegljivo_omrezje_da_slovensko_sporocilo(self) -> None:
        """Surovo besedilo napake kot edina vsebina je napaka (`CLAUDE.md` §1b)."""

        def obdelaj(zahteva: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("ne gre", request=zahteva)

        with pytest.raises(NapakaGoogla) as napaka:
            _odjemalec(obdelaj).racun("koda-1")
        assert str(napaka.value) == google.SPOROCILO_NEDOSEGLJIV
        assert "ne gre" not in str(napaka.value)

    def test_casovna_omejitev_da_slovensko_sporocilo(self) -> None:
        def obdelaj(zahteva: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("predolgo", request=zahteva)

        with pytest.raises(NapakaGoogla) as napaka:
            _odjemalec(obdelaj).racun("koda-1")
        assert str(napaka.value) == google.SPOROCILO_NEDOSEGLJIV


# --- Nastavitve ------------------------------------------------------------


class TestNastavljenost:
    """Brez katerekoli od treh vrednosti Google v tej namestitvi ni na voljo."""

    def test_vse_tri_pomenijo_nastavljeno(self) -> None:
        assert _nastavitve().google_je_nastavljen

    @pytest.mark.parametrize(
        "polje", ["google_client_id", "google_client_secret", "domena"]
    )
    def test_brez_ene_ni_nastavljeno(self, polje: str) -> None:
        nastavitve = _nastavitve().model_copy(update={polje: ""})
        assert not nastavitve.google_je_nastavljen

    def test_privzetek_je_nenastavljeno(self) -> None:
        """Namestitev, ki Googla ne omenja, ga nima — brez posebnega koraka."""
        assert not Settings(database_url="sqlite://").google_je_nastavljen
