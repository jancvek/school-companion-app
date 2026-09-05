"""Testi klica vision modela.

**Nobeden ne gre na omrežje.** Pravi `OpenAI` odjemalec v tej zbirki nikoli ne
nastane: `naredi_klicalca` sprejme odjemalca kot argument, in tu je to
preprost predmet, ki vrne ali vrže, kar test potrebuje.

Izjeme storitve so prave (`openai.APIStatusError` in sorodne), ker je prav
njihovo lovljenje tisto, kar se preverja. Sestavljene so z `httpx2`, ki ga
`openai` uporablja interno — isti razred izjeme, kot bi ga vrgel pravi klic.
"""

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.settings import Settings
from app.vision import (
    NAJMANJ_VPRASANJ,
    NAJVEC_VPRASANJ,
    PROMPT,
    NapakaObdelave,
    naredi_klicalca,
    razcleni_odgovor,
    sestavi_sporocila,
)
from tests.conftest import KLJUC

SLIKA = b"\xff\xd8\xff\xe0-nekaj-bajtov-slike"

#: Odgovor, kakršnega vrne model za berljivo stran.
VELJAVEN_ODGOVOR: dict[str, Any] = {
    "readable": True,
    "transcript": "Delci snovi se gibljejo.",
    "summary": "Stran govori o zgradbi snovi.",
    "questions": [
        {"question": f"Vprašanje {i}?", "answer": f"Odgovor {i}."}
        for i in range(1, NAJMANJ_VPRASANJ + 1)
    ],
}


def nastavitve_z(model: str = "gpt-4.1", timeout: float = 120.0) -> Settings:
    """Nastavitve, ki jih klicalec potrebuje."""
    return Settings(
        api_key=KLJUC,
        database_url="sqlite://",
        openai_api_key="test-openai-kljuc",
        openai_model=model,
        openai_timeout_seconds=timeout,
    )


class LazenOdjemalec:
    """Kar `naredi_klicalca` potrebuje od odjemalca OpenAI, in nič več.

    Zapomni si argumente klica, da se da preveriti, kaj bi šlo na omrežje.
    """

    def __init__(self, *, odgovor: object = None, izjema: Exception | None = None) -> None:
        self._odgovor = odgovor
        self._izjema = izjema
        self.klici: list[dict[str, Any]] = []

    @property
    def chat(self) -> Any:
        return SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> object:
        self.klici.append(kwargs)
        if self._izjema is not None:
            raise self._izjema
        return self._odgovor


def odgovor_storitve(
    vsebina: str | None,
    *,
    model: str = "gpt-4.1-2025-04-14",
    vhodni: int | None = 1500,
    izhodni: int | None = 2000,
) -> SimpleNamespace:
    """Oblika, ki jo `chat.completions.create` vrne ob uspehu."""
    return SimpleNamespace(
        model=model,
        usage=SimpleNamespace(prompt_tokens=vhodni, completion_tokens=izhodni),
        choices=[SimpleNamespace(message=SimpleNamespace(content=vsebina))],
    )


def zahteva() -> httpx2.Request:
    """Zahteva, ki jo izjeme storitve nosijo s sabo."""
    return httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


@pytest.fixture
def slika(tmp_path: Path) -> Path:
    pot = tmp_path / "snov.jpg"
    pot.write_bytes(SLIKA)
    return pot


class TestSestavaZahteve:
    """Kaj gre modelu."""

    def test_sporocilo_nosi_prompt_in_sliko(self, slika: Path) -> None:
        sporocila = sestavi_sporocila(slika)

        assert len(sporocila) == 1
        vsebina = sporocila[0]["content"]
        assert vsebina[0] == {"type": "text", "text": PROMPT}
        assert vsebina[1]["type"] == "image_url"

    def test_slika_gre_kot_base64_in_ne_kot_naslov(self, slika: Path) -> None:
        """Strežnik je za Tailscale; do naslova slike OpenAI nima dostopa."""
        url = sestavi_sporocila(slika)[0]["content"][1]["image_url"]["url"]

        predpona = "data:image/jpeg;base64,"
        assert url.startswith(predpona)
        assert base64.b64decode(url[len(predpona) :]) == SLIKA

    def test_ime_modela_pride_iz_nastavitev(self, slika: Path) -> None:
        """ADR-008: zamenjava modela je sprememba nastavitve, ne kode."""
        odjemalec = LazenOdjemalec(odgovor=odgovor_storitve(json.dumps(VELJAVEN_ODGOVOR)))

        naredi_klicalca(nastavitve_z(model="nekaj-drugega"), odjemalec)(slika)

        assert odjemalec.klici[0]["model"] == "nekaj-drugega"

    def test_zahteva_strukturiran_izhod_po_shemi(self, slika: Path) -> None:
        """Brez `strict` bi bil neveljaven JSON pogost, ne robni primer."""
        odjemalec = LazenOdjemalec(odgovor=odgovor_storitve(json.dumps(VELJAVEN_ODGOVOR)))

        naredi_klicalca(nastavitve_z(), odjemalec)(slika)

        oblika = odjemalec.klici[0]["response_format"]
        assert oblika["type"] == "json_schema"
        assert oblika["json_schema"]["strict"] is True
        assert set(oblika["json_schema"]["schema"]["required"]) == {
            "readable",
            "transcript",
            "summary",
            "questions",
        }


class TestRazclenitevOdgovora:
    """Kaj sprejmemo nazaj."""

    def test_srecna_pot(self) -> None:
        vsebina = razcleni_odgovor(json.dumps(VELJAVEN_ODGOVOR))

        assert vsebina.readable is True
        assert vsebina.transcript == "Delci snovi se gibljejo."
        assert vsebina.summary == "Stran govori o zgradbi snovi."
        assert len(vsebina.questions) == NAJMANJ_VPRASANJ
        assert vsebina.questions[0].question == "Vprašanje 1?"
        assert vsebina.questions[0].answer == "Odgovor 1."

    def test_neveljaven_json_je_napaka(self) -> None:
        with pytest.raises(NapakaObdelave) as napaka:
            razcleni_odgovor("{to ni json")

        assert "veljavnega JSON" in napaka.value.sporocilo

    def test_manjkajoce_polje_je_napaka(self) -> None:
        brez_povzetka = {k: v for k, v in VELJAVEN_ODGOVOR.items() if k != "summary"}

        with pytest.raises(NapakaObdelave) as napaka:
            razcleni_odgovor(json.dumps(brez_povzetka))

        assert "summary" in napaka.value.sporocilo

    def test_prazno_vprasanje_je_napaka(self) -> None:
        """Vprašanje brez besedila je za kviz neuporabno."""
        pokvarjen = {**VELJAVEN_ODGOVOR, "questions": [{"question": "", "answer": "x"}] * 5}

        with pytest.raises(NapakaObdelave):
            razcleni_odgovor(json.dumps(pokvarjen))

    @pytest.mark.parametrize("koliko", [0, 1, NAJMANJ_VPRASANJ - 1, NAJVEC_VPRASANJ + 1])
    def test_stevilo_vprasanj_izven_meja_je_napaka(self, koliko: int) -> None:
        """Kriterij pravi 5-10. Odgovor s tremi vprašanji ni tiho sprejet.

        Meja ni v shemi, ki gre storitvi (`strict` ne pozna `minItems`), zato
        je prav ta test edino, kar jo drži.
        """
        odgovor = {
            **VELJAVEN_ODGOVOR,
            "questions": [{"question": f"V{i}?", "answer": f"O{i}."} for i in range(koliko)],
        }

        with pytest.raises(NapakaObdelave) as napaka:
            razcleni_odgovor(json.dumps(odgovor))

        assert str(koliko) in napaka.value.sporocilo

    @pytest.mark.parametrize("koliko", [NAJMANJ_VPRASANJ, 7, NAJVEC_VPRASANJ])
    def test_stevilo_vprasanj_znotraj_meja_je_sprejeto(self, koliko: int) -> None:
        odgovor = {
            **VELJAVEN_ODGOVOR,
            "questions": [{"question": f"V{i}?", "answer": f"O{i}."} for i in range(koliko)],
        }

        assert len(razcleni_odgovor(json.dumps(odgovor)).questions) == koliko

    def test_neberljiva_slika_brez_vprasanj_je_veljaven_odgovor(self) -> None:
        odgovor = {"readable": False, "transcript": "", "summary": "", "questions": []}

        vsebina = razcleni_odgovor(json.dumps(odgovor))

        assert vsebina.readable is False
        assert vsebina.questions == ()

    def test_neberljiva_slika_z_vprasanji_si_nasprotuje(self) -> None:
        """Model trdi, da ni znal brati, in hkrati sprašuje o vsebini.

        Tega ne popravljamo tiho, ker ne vemo, kateri polovici verjeti.
        """
        odgovor = {**VELJAVEN_ODGOVOR, "readable": False}

        with pytest.raises(NapakaObdelave) as napaka:
            razcleni_odgovor(json.dumps(odgovor))

        assert "neberljivo" in napaka.value.sporocilo

    def test_dodatno_polje_je_napaka(self) -> None:
        """`additionalProperties: false` velja tudi pri sprejemu."""
        with pytest.raises(NapakaObdelave):
            razcleni_odgovor(json.dumps({**VELJAVEN_ODGOVOR, "cena": 3}))


class TestIzidKlica:
    """Kaj klicalec vrne ob uspehu."""

    def test_vsebina_in_sled(self, slika: Path) -> None:
        surovo = json.dumps(VELJAVEN_ODGOVOR)
        odjemalec = LazenOdjemalec(odgovor=odgovor_storitve(surovo))

        izid = naredi_klicalca(nastavitve_z(), odjemalec)(slika)

        assert izid.vsebina.readable is True
        assert izid.raw_response == surovo
        assert izid.prompt == PROMPT
        assert izid.input_tokens == 1500
        assert izid.output_tokens == 2000

    def test_ime_modela_je_iz_odgovora_in_ne_iz_nastavitve(self, slika: Path) -> None:
        """Storitev vzdevek `gpt-4.1` razreši v konkretno različico.

        Za primerjavo med modeli je merodajno prav to, kar je res odgovorilo —
        sicer bi po zamenjavi modela stara sled kazala novo ime.
        """
        odjemalec = LazenOdjemalec(
            odgovor=odgovor_storitve(json.dumps(VELJAVEN_ODGOVOR), model="gpt-4.1-2025-04-14")
        )

        izid = naredi_klicalca(nastavitve_z(model="gpt-4.1"), odjemalec)(slika)

        assert izid.model == "gpt-4.1-2025-04-14"

    def test_manjkajoca_poraba_ne_podre_klica(self, slika: Path) -> None:
        """Storitev `usage` sme izpustiti; sled je takrat nepopolna, ne pa napačna."""
        odjemalec = LazenOdjemalec(
            odgovor=odgovor_storitve(json.dumps(VELJAVEN_ODGOVOR), vhodni=None, izhodni=None)
        )

        izid = naredi_klicalca(nastavitve_z(), odjemalec)(slika)

        assert izid.input_tokens is None
        assert izid.output_tokens is None


class TestNapakeStoritve:
    """Vsaka napaka mora povedati, kaj naj operater naredi."""

    def test_potekla_casovna_omejitev(self, slika: Path) -> None:
        odjemalec = LazenOdjemalec(izjema=APITimeoutError(request=zahteva()))

        with pytest.raises(NapakaObdelave) as napaka:
            naredi_klicalca(nastavitve_z(timeout=90.0), odjemalec)(slika)

        assert "90 sekundah" in napaka.value.sporocilo

    def test_nedosegljiva_storitev(self, slika: Path) -> None:
        odjemalec = LazenOdjemalec(izjema=APIConnectionError(request=zahteva()))

        with pytest.raises(NapakaObdelave) as napaka:
            naredi_klicalca(nastavitve_z(), odjemalec)(slika)

        assert "omrežno povezavo" in napaka.value.sporocilo

    @pytest.mark.parametrize("koda", [401, 403])
    def test_zavrnjen_kljuc_pove_katero_spremenljivko_popraviti(
        self, slika: Path, koda: int
    ) -> None:
        """Robni primer iz `v1.md`: napačen ključ je `failed`, ne mirujoč worker."""
        odjemalec = LazenOdjemalec(
            izjema=APIStatusError(
                "nope", response=httpx2.Response(koda, request=zahteva()), body=None
            )
        )

        with pytest.raises(NapakaObdelave) as napaka:
            naredi_klicalca(nastavitve_z(), odjemalec)(slika)

        assert "OPENAI_API_KEY" in napaka.value.sporocilo
        assert str(koda) in napaka.value.sporocilo

    def test_porabljena_kvota(self, slika: Path) -> None:
        odjemalec = LazenOdjemalec(
            izjema=APIStatusError(
                "nope", response=httpx2.Response(429, request=zahteva()), body=None
            )
        )

        with pytest.raises(NapakaObdelave) as napaka:
            naredi_klicalca(nastavitve_z(), odjemalec)(slika)

        assert "kvote" in napaka.value.sporocilo

    def test_napaka_na_strani_storitve(self, slika: Path) -> None:
        odjemalec = LazenOdjemalec(
            izjema=APIStatusError(
                "nope", response=httpx2.Response(503, request=zahteva()), body=None
            )
        )

        with pytest.raises(NapakaObdelave) as napaka:
            naredi_klicalca(nastavitve_z(), odjemalec)(slika)

        assert "strani storitve OpenAI" in napaka.value.sporocilo

    def test_prazen_odgovor(self, slika: Path) -> None:
        odjemalec = LazenOdjemalec(odgovor=odgovor_storitve(None))

        with pytest.raises(NapakaObdelave) as napaka:
            naredi_klicalca(nastavitve_z(), odjemalec)(slika)

        assert "prazen odgovor" in napaka.value.sporocilo

    def test_neveljaven_odgovor_ohrani_sled(self, slika: Path) -> None:
        """Brez surovega odgovora bi bil `failed` zapis brez dokaza.

        Poraba tokenov gre zraven: neuspel klic je bil plačan enako kot uspešen.
        """
        odjemalec = LazenOdjemalec(odgovor=odgovor_storitve("{to ni json"))

        with pytest.raises(NapakaObdelave) as napaka:
            naredi_klicalca(nastavitve_z(), odjemalec)(slika)

        assert napaka.value.raw_response == "{to ni json"
        assert napaka.value.model == "gpt-4.1-2025-04-14"
        assert napaka.value.input_tokens == 1500
        assert napaka.value.output_tokens == 2000

    def test_napaka_pred_odgovorom_sledi_nima(self, slika: Path) -> None:
        """Kadar storitev ni odgovorila, ni česa shraniti — in tudi ne izmisliti."""
        odjemalec = LazenOdjemalec(izjema=APITimeoutError(request=zahteva()))

        with pytest.raises(NapakaObdelave) as napaka:
            naredi_klicalca(nastavitve_z(), odjemalec)(slika)

        assert napaka.value.raw_response is None
        assert napaka.value.model is None
