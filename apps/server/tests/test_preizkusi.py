"""Sestavljanje preizkusa (V4-R07): pravila, klic modela, poti in stran.

Pokriva tabelo „Test casi" iz `docs/plan/V4-R07.md`. **Nobeden ne gre na
omrežje**: klicalec je v testih poti navadna funkcija, v testih klica pa
`LazenOdjemalec` iz `test_vision.py`.

Obnašanja strani v brskalniku (razveljavi/uveljavi, izris formul, tisk,
merilnik) pytest ne izvede — to je ročni preizkus v fazi 9b
(`docs/odlocitve/ADR-054`). Tu so samo trditve o tem, kaj stran **vsebuje**.
"""

import json
import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
)
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app import preizkus
from app.main import MAPA_STATICNIH, create_app
from app.models import STATUS_PRIPRAVLJEN, Material
from app.routers import preizkusi
from app.routers.admin import MAPA_PREDLOG
from app.settings import Settings
from app.vision import (
    NAJVEC_IZHODA_PREIZKUSA,
    IzidPreizkusa,
    NapakaObdelave,
    naredi_klicalca_preizkusa,
)
from tests.conftest import TUJA_DRUZINA_ID, PrijavljenOdjemalec, prijavi
from tests.test_admin import (
    UUID_DVA,
    UUID_ENA,
    UUID_TRI,
    arhiviraj,
    obdelaj,
    polje_prepisov,
    prepisi,
    zapisi,
)
from tests.test_vision import LazenOdjemalec, odziv_s_kodo, zahteva

KOREN_REPOZITORIJA = Path(__file__).resolve().parents[3]

VELJAVEN: dict[str, str] = {
    "sporocilo": "Sestavil sem test s petimi nalogami.",
    "test_md": "# Preverjanje znanja\n\n## 1. Ulomki (2 točki)\n\n$\\frac{1}{2}$ [odgovor]",
    "resitve_md": "# Rešitve\n\n## 1.\n\n**1/2**",
}


# --- Pravila: navodilo, vhod, odgovor (`app/preizkus.py`) ---


def navodilo_iz_zapisa_poc() -> str:
    """Navodilo, kot stoji v `docs/poc/POC-01.md` *Ugotovitve*.

    Zapis POC-a je izvirnik: koda POC-a je zavržena (`CLAUDE.md` §1d). Blok je
    v dokumentu zamaknjen za dva presledka, ker stoji pod točko seznama.
    """
    besedilo = (KOREN_REPOZITORIJA / "docs" / "poc" / "POC-01.md").read_text(encoding="utf-8")
    naslov = besedilo.index("Navodilo modelu, kakršno je bilo sprejeto")
    zacetek = besedilo.index("```text\n", naslov) + len("```text\n")
    blok = besedilo[zacetek : besedilo.index("\n  ```", zacetek)]
    return "\n".join(
        vrstica[2:] if vrstica.startswith("  ") else vrstica for vrstica in blok.split("\n")
    )


class TestNavodilo:
    def test_navodilo_za_matematiko_je_dobesedno_iz_zapisa_poc(self) -> None:
        # Kriterij: besedilo navodila je iz `POC-01` *Ugotovitve*. Razlika je
        # napaka v enem od obeh — in tisti zapis je izvirnik.
        assert navodilo_iz_zapisa_poc() == preizkus.NAVODILO_MAT

    def test_navodilo_se_poisce_po_predmetu(self) -> None:
        assert preizkus.navodilo_za("MAT") == preizkus.NAVODILO_MAT

    @pytest.mark.parametrize("koda", ["SLJ", "", "mat", "MAT/", "NEZNANO"])
    def test_predmet_brez_navodila(self, koda: str) -> None:
        assert preizkus.navodilo_za(koda) is None


class TestVhod:
    """Oblika vhoda iz `POC-01` *Ugotovitve* (krog 3)."""

    def test_nov_test_ima_snov_in_zeljo(self) -> None:
        vhod = preizkus.sestavi_vhod(
            snov="## MAT — snov\n",
            test_md="",
            resitve_md="",
            dosedanje=[],
            zelja=" Test za 6. razred. ",
        )

        assert vhod == (
            "SNOV (prepisi iz zvezka, najstarejši prvi):\n<<<\n## MAT — snov\n>>>\n\n"
            "ŽELJA STARŠA (sestavi nov test):\nTest za 6. razred."
        )

    def test_popravek_ima_vse_dele_v_dogovorjenem_redu(self) -> None:
        vhod = preizkus.sestavi_vhod(
            snov="SNOV-X",
            test_md="TEST-X",
            resitve_md="RESITVE-X",
            dosedanje=["Test za 6. razred.", "Dodaj besedilno nalogo."],
            zelja="Tretja naj bo lažja.",
        )

        assert vhod == (
            "SNOV (prepisi iz zvezka, najstarejši prvi):\n<<<\nSNOV-X\n>>>\n\n"
            "DOSEDANJE ŽELJE (trenutni test jih že upošteva):\n"
            "1. Test za 6. razred.\n2. Dodaj besedilno nalogo.\n\n"
            "TRENUTNI TEST:\n<<<\nTEST-X\n>>>\n\n"
            "TRENUTNE REŠITVE:\n<<<\nRESITVE-X\n>>>\n\n"
            "NOVA ŽELJA STARŠA (popravi trenutni test):\nTretja naj bo lažja."
        )

    def test_snov_je_prva(self) -> None:
        # Snov se med popravki ne spreminja; prva je zato, da jo storitev
        # lahko vzame iz predpomnilnika.
        vhod = preizkus.sestavi_vhod(
            snov="SNOV-X", test_md="TEST-X", resitve_md="R", dosedanje=["a"], zelja="b"
        )

        assert vhod.startswith("SNOV (")
        assert vhod.index("SNOV-X") < vhod.index("DOSEDANJE") < vhod.index("TEST-X")

    def test_prazne_zelje_v_verigi_izpadejo_in_stevilcenje_nima_lukenj(self) -> None:
        vhod = preizkus.sestavi_vhod(
            snov="S", test_md="T", resitve_md="R", dosedanje=["prva", "  ", "", "druga"], zelja="z"
        )

        assert "1. prva\n2. druga\n" in vhod
        assert "3." not in vhod

    def test_popravek_brez_dosedanjih_zelja_nima_praznega_razdelka(self) -> None:
        vhod = preizkus.sestavi_vhod(snov="S", test_md="T", resitve_md="R", dosedanje=[], zelja="z")

        assert "DOSEDANJE" not in vhod
        assert "NOVA ŽELJA STARŠA (popravi trenutni test):" in vhod

    def test_brez_trenutnega_testa_je_to_nov_test_tudi_z_verigo(self) -> None:
        # Želje brez testa, ki bi jih „že upošteval", nimajo pomena.
        vhod = preizkus.sestavi_vhod(
            snov="S", test_md="  \n", resitve_md="R", dosedanje=["stara"], zelja="z"
        )

        assert "ŽELJA STARŠA (sestavi nov test):" in vhod
        assert "stara" not in vhod
        assert "TRENUTNI" not in vhod


class TestRazclenitevOdgovora:
    def test_srecna_pot(self) -> None:
        odgovor = preizkus.razcleni_odgovor(json.dumps(VELJAVEN))

        assert odgovor.sporocilo == VELJAVEN["sporocilo"]
        assert odgovor.test_md == VELJAVEN["test_md"]
        assert odgovor.resitve_md == VELJAVEN["resitve_md"]
        assert odgovor.ima_test

    def test_prazen_test_je_veljaven_odgovor_brez_testa(self) -> None:
        # Model pove, zakaj testa ni; to ni napaka klica (`POC-01`).
        odgovor = preizkus.razcleni_odgovor(
            json.dumps({"sporocilo": "Snovi ni dovolj.", "test_md": " \n", "resitve_md": ""})
        )

        assert not odgovor.ima_test
        assert odgovor.sporocilo == "Snovi ni dovolj."

    def test_neveljaven_json(self) -> None:
        with pytest.raises(preizkus.NeveljavenOdgovor) as napaka:
            preizkus.razcleni_odgovor('{"sporocilo": "odrezano')

        assert "veljavnega JSON" in napaka.value.sporocilo

    @pytest.mark.parametrize("polje", ["sporocilo", "test_md", "resitve_md"])
    def test_manjkajoce_polje(self, polje: str) -> None:
        podatki = {k: v for k, v in VELJAVEN.items() if k != polje}

        with pytest.raises(preizkus.NeveljavenOdgovor) as napaka:
            preizkus.razcleni_odgovor(json.dumps(podatki))

        assert polje in napaka.value.sporocilo

    def test_polje_ki_ni_besedilo(self) -> None:
        with pytest.raises(preizkus.NeveljavenOdgovor):
            preizkus.razcleni_odgovor(json.dumps({**VELJAVEN, "test_md": 7}))

    def test_dodatno_polje(self) -> None:
        with pytest.raises(preizkus.NeveljavenOdgovor):
            preizkus.razcleni_odgovor(json.dumps({**VELJAVEN, "se_nekaj": "x"}))

    def test_odgovor_ki_ni_predmet(self) -> None:
        with pytest.raises(preizkus.NeveljavenOdgovor):
            preizkus.razcleni_odgovor('["seznam"]')

    def test_sporocilo_napake_ne_citira_vsebine(self) -> None:
        # Sporočilo gre v dnevnik, ta pa testa in snovi ne sme nositi.
        with pytest.raises(preizkus.NeveljavenOdgovor) as napaka:
            preizkus.razcleni_odgovor(json.dumps({**VELJAVEN, "test_md": ["SKRIVNA-VSEBINA"]}))

        assert "SKRIVNA-VSEBINA" not in napaka.value.sporocilo


# --- Klic modela (`vision.naredi_klicalca_preizkusa`) ---


def nastavitve_preizkusa(timeout: float = 120.0) -> Settings:
    return Settings(
        database_url="sqlite://",
        openai_api_key="kljuc-za-vision",
        openai_model="model-za-vision",
        openai_api_key_preizkusi="kljuc-za-preizkuse",
        openai_model_preizkusi="model-za-preizkuse",
        openai_timeout_seconds=timeout,
    )


def odgovor_storitve(vsebina: str | None, **uporaba: Any) -> SimpleNamespace:
    """Oblika, ki jo `chat.completions.create` vrne ob uspehu, s porabo."""
    return SimpleNamespace(
        model="model-za-preizkuse-2026-10-01",
        usage=SimpleNamespace(
            prompt_tokens=5300,
            completion_tokens=2100,
            prompt_tokens_details=SimpleNamespace(cached_tokens=1300),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=300),
            **uporaba,
        ),
        choices=[SimpleNamespace(message=SimpleNamespace(content=vsebina))],
    )


class TestKlicalecPreizkusa:
    def test_zahteva_nosi_navodilo_vhod_in_svoj_model(self) -> None:
        odjemalec = LazenOdjemalec(odgovor=odgovor_storitve(json.dumps(VELJAVEN)))

        naredi_klicalca_preizkusa(nastavitve_preizkusa(), odjemalec)("NAVODILO", "VHOD")

        (klic,) = odjemalec.klici
        # Model preizkusov, ne vision model (`ADR-054`).
        assert klic["model"] == "model-za-preizkuse"
        assert klic["messages"] == [
            {"role": "system", "content": "NAVODILO"},
            {"role": "user", "content": "VHOD"},
        ]
        assert klic["reasoning_effort"] == "medium"
        assert klic["max_completion_tokens"] == NAJVEC_IZHODA_PREIZKUSA

    def test_zahteva_strukturiran_izhod_po_shemi(self) -> None:
        odjemalec = LazenOdjemalec(odgovor=odgovor_storitve(json.dumps(VELJAVEN)))

        naredi_klicalca_preizkusa(nastavitve_preizkusa(), odjemalec)("N", "V")

        oblika = odjemalec.klici[0]["response_format"]
        assert oblika["type"] == "json_schema"
        assert oblika["json_schema"]["strict"] is True
        assert oblika["json_schema"]["schema"] == preizkus.SHEMA
        assert preizkus.SHEMA["required"] == ["sporocilo", "test_md", "resitve_md"]

    def test_izid_nosi_odgovor_model_in_porabo(self) -> None:
        odjemalec = LazenOdjemalec(odgovor=odgovor_storitve(json.dumps(VELJAVEN)))

        izid = naredi_klicalca_preizkusa(nastavitve_preizkusa(), odjemalec)("N", "V")

        assert izid.odgovor.test_md == VELJAVEN["test_md"]
        assert izid.model == "model-za-preizkuse-2026-10-01"
        assert (izid.vhodni, izid.predpomnjeni, izid.izhodni, izid.razmisljanje) == (
            5300,
            1300,
            2100,
            300,
        )
        assert izid.trajanje >= 0

    def test_manjkajoca_poraba_ne_podre_klica(self) -> None:
        surov = SimpleNamespace(
            model=None,
            usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(VELJAVEN)))],
        )

        izid = naredi_klicalca_preizkusa(nastavitve_preizkusa(), LazenOdjemalec(odgovor=surov))(
            "N", "V"
        )

        assert izid.model == "model-za-preizkuse"
        assert (izid.vhodni, izid.predpomnjeni, izid.izhodni, izid.razmisljanje) == (
            None,
            None,
            None,
            None,
        )

    def test_potekla_casovna_omejitev(self) -> None:
        odjemalec = LazenOdjemalec(izjema=APITimeoutError(request=zahteva()))

        with pytest.raises(NapakaObdelave) as napaka:
            naredi_klicalca_preizkusa(nastavitve_preizkusa(timeout=90.0), odjemalec)("N", "V")

        assert "90 sekundah" in napaka.value.sporocilo

    def test_nedosegljiva_storitev(self) -> None:
        odjemalec = LazenOdjemalec(izjema=APIConnectionError(request=zahteva()))

        with pytest.raises(NapakaObdelave) as napaka:
            naredi_klicalca_preizkusa(nastavitve_preizkusa(), odjemalec)("N", "V")

        assert "omrežno povezavo" in napaka.value.sporocilo

    def test_zavrnjen_kljuc_pokaze_na_kljuc_preizkusov(self) -> None:
        # Preizkus ima svoj ključ; sporočilo, ki bi pokazalo na vision ključ,
        # bi poslalo popravljat pravo spremenljivko.
        odjemalec = LazenOdjemalec(
            izjema=APIStatusError("nope", response=odziv_s_kodo(401), body=None)
        )

        with pytest.raises(NapakaObdelave) as napaka:
            naredi_klicalca_preizkusa(nastavitve_preizkusa(), odjemalec)("N", "V")

        assert "OPENAI_API_KEY_PREIZKUSI" in napaka.value.sporocilo

    @pytest.mark.parametrize("koda", [429, 500])
    def test_napaka_storitve(self, koda: int) -> None:
        odjemalec = LazenOdjemalec(
            izjema=APIStatusError("nope", response=odziv_s_kodo(koda), body=None)
        )

        with pytest.raises(NapakaObdelave) as napaka:
            naredi_klicalca_preizkusa(nastavitve_preizkusa(), odjemalec)("N", "V")

        assert str(koda) in napaka.value.sporocilo

    def test_prazen_odgovor(self) -> None:
        odjemalec = LazenOdjemalec(odgovor=odgovor_storitve(None))

        with pytest.raises(NapakaObdelave) as napaka:
            naredi_klicalca_preizkusa(nastavitve_preizkusa(), odjemalec)("N", "V")

        assert "prazen odgovor" in napaka.value.sporocilo

    @pytest.mark.parametrize(
        "vsebina",
        ['{"sporocilo": "odrezano', json.dumps({"sporocilo": "x", "test_md": "y"})],
        ids=["neveljaven-json", "manjkajoce-polje"],
    )
    def test_neuporaben_odgovor_je_napaka(self, vsebina: str) -> None:
        odjemalec = LazenOdjemalec(odgovor=odgovor_storitve(vsebina))

        with pytest.raises(NapakaObdelave):
            naredi_klicalca_preizkusa(nastavitve_preizkusa(), odjemalec)("N", "V")

    def test_napaka_ne_nosi_vhoda_in_ga_ne_zapise_v_dnevnik(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Vhod je snov družine: ne v sled napake ne v dnevnik.
        odjemalec = LazenOdjemalec(
            izjema=APIResponseValidationError(response=odziv_s_kodo(200), body="SKRIVNA-SNOV")
        )

        with caplog.at_level(logging.DEBUG), pytest.raises(NapakaObdelave) as napaka:
            naredi_klicalca_preizkusa(nastavitve_preizkusa(), odjemalec)("N", "SKRIVNA-SNOV")

        assert napaka.value.prompt is None
        assert "APIResponseValidationError" in napaka.value.sporocilo
        assert "SKRIVNA-SNOV" not in caplog.text
        assert "APIResponseValidationError" in caplog.text


# --- Poti ---


class LazenKlicalec:
    """Klicalec preizkusa, ki si zapomni, kaj je dobil."""

    def __init__(
        self, odgovor: dict[str, str] | None = None, napaka: NapakaObdelave | None = None
    ) -> None:
        self._odgovor = VELJAVEN if odgovor is None else odgovor
        self._napaka = napaka
        self.klici: list[tuple[str, str]] = []

    def __call__(self, navodilo: str, vhod: str) -> IzidPreizkusa:
        self.klici.append((navodilo, vhod))
        if self._napaka is not None:
            raise self._napaka
        return IzidPreizkusa(
            odgovor=preizkus.Odgovor(**self._odgovor),
            model="model-iz-odgovora",
            trajanje=17.25,
            vhodni=5300,
            predpomnjeni=1300,
            izhodni=2100,
            razmisljanje=300,
        )

    @property
    def vhod(self) -> str:
        """Vhod edinega klica."""
        ((_, vhod),) = self.klici
        return vhod


@pytest.fixture
def klicalec() -> LazenKlicalec:
    return LazenKlicalec()


@pytest.fixture
def aplikacija(nastavitve: Settings, motor: Engine, klicalec: LazenKlicalec) -> FastAPI:
    """Prepiše fixture iz `conftest.py`: aplikacija ima klicalca preizkusa."""
    return create_app(nastavitve=nastavitve, motor=motor, klicalec_preizkusa=klicalec)


@pytest.fixture
def brez_kljuca(
    nastavitve: Settings, motor: Engine, stars: str
) -> Iterator[PrijavljenOdjemalec]:
    """Odjemalec nad aplikacijo **brez** ključa za preizkuse."""
    aplikacija = create_app(nastavitve=nastavitve, motor=motor)
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
        prijavi(odjemalec, motor, stars)
        yield odjemalec


def snov_s_prepisom(
    motor: Engine,
    slike: Path,
    material_id: str,
    prepis: str,
    *,
    subject: str = "MAT",
    taken_at: str = "2026-09-04T07:30:00+00:00",
) -> None:
    """Obdelana snov z razločljivim prepisom."""
    zapisi(motor, slike, material_id, subject=subject, taken_at=taken_at)
    obdelaj(motor, material_id)
    with Session(motor) as seja:
        material = seja.get(Material, material_id)
        assert material is not None
        material.transcript = prepis
        seja.commit()


def sestavi(odjemalec: PrijavljenOdjemalec, koda: str = "MAT", *snovi: str) -> Any:
    """`POST /admin/assessments/compose`, kot ga pošlje gumb „Kreiraj test"."""
    return odjemalec.post(
        "/admin/assessments/compose", data={"subject": koda, "snov": list(snovi)}
    )


def generiraj(odjemalec: PrijavljenOdjemalec, **polja: Any) -> Any:
    """`POST /admin/assessments/generate`, kot ga pošlje skripta urejevalnika."""
    podatki: dict[str, Any] = {
        "subject": "MAT",
        "snov": [UUID_ENA],
        "test_md": "",
        "resitve_md": "",
        "zelja": "Test za 6. razred.",
    }
    podatki.update(polja)
    return odjemalec.post("/admin/assessments/generate", data=podatki)


def izbor_urejevalnika(besedilo: str) -> list[str]:
    """Identifikatorji snovi, ki jih urejevalnik nosi v svojem obrazcu."""
    zacetek = besedilo.index('<form method="post" action="/admin/transcripts" target="_blank"')
    obrazec = besedilo[zacetek : besedilo.index("</form>", zacetek)]
    return re.findall(r'name="snov" value="([^"]+)"', obrazec)


class TestGumbNaStraniPredmeta:
    def test_matematika_ima_gumb_ki_poslje_isti_obrazec_drugam(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        besedilo = odjemalec.get("/admin/subjects/MAT").text
        zacetek = besedilo.index('<form method="post" action="/admin/transcripts">')
        obrazec = besedilo[zacetek : besedilo.index("</form>", zacetek)]

        # Nad seznamom in pod njim, kot „Prepisi izbranih"; oba v obrazcu
        # izbora, da pošljeta iste kljukice in isti CSRF žeton.
        assert obrazec.count('formaction="/admin/assessments/compose">Kreiraj test') == 2
        assert besedilo.count("Kreiraj test") == 2

    def test_drug_predmet_gumba_nima(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, subject="SLJ")

        besedilo = odjemalec.get("/admin/subjects/SLJ").text

        assert "Prepisi izbranih" in besedilo
        assert "Kreiraj test" not in besedilo
        assert "/admin/assessments" not in besedilo

    def test_prepisi_izbranih_ostanejo_privzeto_dejanje_obrazca(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        # Regresija `V3-R11`: prvi gumb nima `formaction`, obrazec še vedno
        # pelje na prepise in ti so isti kot pred to zahtevo.
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        besedilo = odjemalec.get("/admin/subjects/MAT").text

        assert besedilo.count('action="/admin/transcripts"') == 1
        gumb = '<button class="gumb gumb-obdelava" type="submit">Prepisi izbranih</button>'
        assert gumb in besedilo
        polje = polje_prepisov(prepisi(odjemalec, "MAT", UUID_ENA).text)
        assert polje.startswith("## MAT — 4. september 2026, 09:30\n\n### Povzetek\n")
        assert "### Prepis\nUlomke seštevamo.\n" in polje


class TestUrejevalnik:
    """`POST /admin/assessments/compose`."""

    def test_prazen_izbor_pove_kaj_naj_stars_naredi(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        odgovor = sestavi(odjemalec, "MAT")

        assert odgovor.status_code == 200
        assert "Izberi vsaj eno sliko" in odgovor.text
        assert 'href="/admin/subjects/MAT"' in odgovor.text
        assert "<script" not in odgovor.text

    def test_urejevalnik_nosi_natanko_izbrane_snovi(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA, taken_at="2026-09-04T07:30:00+00:00")
        zapisi(motor, slike, UUID_DVA, taken_at="2026-09-05T07:30:00+00:00")
        zapisi(motor, slike, UUID_TRI, taken_at="2026-09-06T07:30:00+00:00")

        odgovor = sestavi(odjemalec, "MAT", UUID_TRI, UUID_ENA)

        assert odgovor.status_code == 200
        # Od najstarejše, kot v besedilu prepisov (`ADR-048` D).
        assert izbor_urejevalnika(odgovor.text) == [UUID_ENA, UUID_TRI]
        assert f'<a class="slicica" href="/admin/materials/{UUID_ENA}/image"' in odgovor.text
        assert f'<a class="slicica" href="/admin/materials/{UUID_TRI}/image"' in odgovor.text
        assert UUID_DVA not in odgovor.text

    def test_urejevalnik_ima_csrf_predmet_in_naslov_generiranja(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        besedilo = sestavi(odjemalec, "MAT", UUID_ENA).text

        assert f'<input type="hidden" name="csrf" value="{odjemalec.csrf}">' in besedilo
        assert '<input type="hidden" name="subject" value="MAT">' in besedilo
        assert 'data-pot="/admin/assessments/generate"' in besedilo
        assert "Kreiraj test</button>" in besedilo
        assert "disabled data-brez-kljuca" not in besedilo

    def test_tuj_arhiviran_in_neobstojec_identifikator_tiho_izpadejo(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        slike: Path,
        tuj_otrok: str,
    ) -> None:
        zapisi(motor, slike, UUID_ENA)
        zapisi(motor, slike, UUID_DVA)
        arhiviraj(motor, UUID_DVA)
        tuja = "0f0f0f0f-1111-4222-8333-444455556666"
        with Session(motor) as seja:
            seja.add(
                Material(
                    id=tuja,
                    family_id=TUJA_DRUZINA_ID,
                    child_id=tuj_otrok,
                    subject="MAT",
                    taken_at=datetime(2026, 9, 4, 7, 30, tzinfo=UTC),
                    image_path=str(slike / TUJA_DRUZINA_ID / f"{tuja}.jpg"),
                    status=STATUS_PRIPRAVLJEN,
                    received_at=datetime(2026, 9, 4, 8, 0, tzinfo=UTC),
                )
            )
            seja.commit()

        odgovor = sestavi(odjemalec, "MAT", tuja, UUID_DVA, "ni-taksnega", UUID_ENA)

        assert izbor_urejevalnika(odgovor.text) == [UUID_ENA]
        assert tuja not in odgovor.text
        assert UUID_DVA not in odgovor.text

    def test_snov_brez_datoteke_nima_povezave_na_sliko(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, vsebina=None)

        besedilo = sestavi(odjemalec, "MAT", UUID_ENA).text

        assert "slike na disku ni" in besedilo
        assert 'class="slicica"' not in besedilo
        assert izbor_urejevalnika(besedilo) == [UUID_ENA]

    def test_drug_predmet_urejevalnika_nima(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, subject="SLJ")

        odgovor = sestavi(odjemalec, "SLJ", UUID_ENA)

        assert odgovor.status_code == 200
        assert "samo pri matematiki" in odgovor.text
        assert "<script" not in odgovor.text
        assert UUID_ENA not in odgovor.text

    def test_get_pelje_na_pregled_in_ne_na_405(self, odjemalec: PrijavljenOdjemalec) -> None:
        odgovor = odjemalec.get("/admin/assessments/compose", follow_redirects=False)

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == "/admin"

    def test_brez_kljuca_urejevalnik_pove_da_generiranje_ni_nastavljeno(
        self, brez_kljuca: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        besedilo = sestavi(brez_kljuca, "MAT", UUID_ENA).text

        assert "Sestavljanje testov ni nastavljeno" in besedilo
        assert "OPENAI_API_KEY_PREIZKUSI" in besedilo
        # Urejevalnik je kljub temu izrisan; gumb je onemogočen.
        assert izbor_urejevalnika(besedilo) == [UUID_ENA]
        assert "disabled data-brez-kljuca>Kreiraj test</button>" in besedilo

    def test_nicesar_ne_zapise(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")
        with Session(motor) as seja:
            prej = [(m.id, m.status, m.transcript, m.archived_at) for m in seja.query(Material)]

        sestavi(odjemalec, "MAT", UUID_ENA)
        generiraj(odjemalec)

        with Session(motor) as seja:
            assert [
                (m.id, m.status, m.transcript, m.archived_at) for m in seja.query(Material)
            ] == prej


class TestDostop:
    def test_brez_seje_vse_tri_poti_peljejo_na_prijavo(
        self, aplikacija: FastAPI, stars: str
    ) -> None:
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brez_seje:
            for metoda, pot in (
                ("GET", "/admin/assessments/compose"),
                ("POST", "/admin/assessments/compose"),
                ("POST", "/admin/assessments/generate"),
            ):
                odgovor = brez_seje.request(metoda, pot, follow_redirects=False)

                assert odgovor.status_code == 303, pot
                assert odgovor.headers["location"].startswith("/admin/login"), pot

    @pytest.mark.parametrize("pot", ["/admin/assessments/compose", "/admin/assessments/generate"])
    def test_brez_csrf_zetona_je_zavrnitev_in_model_se_ne_klice(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        slike: Path,
        klicalec: LazenKlicalec,
        pot: str,
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        odgovor = odjemalec.post(
            pot,
            data={"csrf": "napacen", "subject": "MAT", "snov": [UUID_ENA], "zelja": "Test."},
        )

        assert odgovor.status_code == 403
        assert klicalec.klici == []

    def test_json_telo_csrf_plasti_ne_obide(
        self, odjemalec: PrijavljenOdjemalec, klicalec: LazenKlicalec
    ) -> None:
        # `ADR-054` meja 4: telo je obrazec prav zato, da plast ostane ista.
        # `request` in ne `post`: ta bi žeton sam dodal kot obrazec.
        odgovor = odjemalec.request(
            "POST",
            "/admin/assessments/generate",
            json={"csrf": odjemalec.csrf, "subject": "MAT", "snov": [UUID_ENA], "zelja": "Test."},
        )

        assert odgovor.status_code == 403
        assert klicalec.klici == []


class TestGeneriranje:
    """`POST /admin/assessments/generate`."""

    def test_odgovor_modela_gre_nazaj_kot_json(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        odgovor = generiraj(odjemalec)

        assert odgovor.status_code == 200
        assert odgovor.headers["content-type"].startswith("application/json")
        assert odgovor.json() == VELJAVEN

    def test_nov_test_dobi_navodilo_za_matematiko_snov_in_zeljo(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path, klicalec: LazenKlicalec
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        generiraj(odjemalec, zelja="  Test za 6. razred.  ")

        ((navodilo, vhod),) = klicalec.klici
        assert navodilo == preizkus.NAVODILO_MAT
        assert vhod.startswith("SNOV (prepisi iz zvezka, najstarejši prvi):\n<<<\n## MAT — ")
        assert vhod.endswith("ŽELJA STARŠA (sestavi nov test):\nTest za 6. razred.")
        assert "TRENUTNI TEST" not in vhod

    def test_snov_v_vhodu_je_isto_besedilo_kot_prepisi_izbranih(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path, klicalec: LazenKlicalec
    ) -> None:
        # Kriterij: ista funkcija kot „Prepisi izbranih" (`ADR-048` F) — s
        # povzetki in vprašanji vred, od najstarejše.
        snov_s_prepisom(
            motor, slike, UUID_ENA, "Prvi prepis.", taken_at="2026-09-04T07:30:00+00:00"
        )
        snov_s_prepisom(
            motor, slike, UUID_DVA, "Drugi prepis.", taken_at="2026-09-05T07:30:00+00:00"
        )
        polje = polje_prepisov(prepisi(odjemalec, "MAT", UUID_DVA, UUID_ENA).text)

        generiraj(odjemalec, snov=[UUID_DVA, UUID_ENA])

        assert "### Vprašanja\n1. V: Vprašanje 1?" in polje
        assert f"<<<\n{polje.strip()}\n>>>" in klicalec.vhod

    def test_popravek_dobi_test_resitve_verigo_zelja_in_novo_zeljo(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path, klicalec: LazenKlicalec
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        generiraj(
            odjemalec,
            test_md="# TRENUTNI-TEST",
            resitve_md="# TRENUTNE-RESITVE",
            dosedanje=["Test za 6. razred.", "Dodaj besedilno nalogo."],
            zelja="Tretja naj bo lažja.",
        )

        vhod = klicalec.vhod
        assert (
            "DOSEDANJE ŽELJE (trenutni test jih že upošteva):\n"
            "1. Test za 6. razred.\n2. Dodaj besedilno nalogo.\n\n"
            "TRENUTNI TEST:\n<<<\n# TRENUTNI-TEST\n>>>\n\n"
            "TRENUTNE REŠITVE:\n<<<\n# TRENUTNE-RESITVE\n>>>\n\n"
            "NOVA ŽELJA STARŠA (popravi trenutni test):\nTretja naj bo lažja."
        ) in vhod
        assert vhod.index("Ulomke seštevamo.") < vhod.index("DOSEDANJE ŽELJE")

    def test_besedila_snovi_od_brskalnika_ne_sprejme(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path, klicalec: LazenKlicalec
    ) -> None:
        # Polja, ki bi jih podtaknil brskalnik, v vhod ne pridejo: snov je
        # samo to, kar strežnik sestavi iz identifikatorjev.
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        generiraj(odjemalec, snov_md="PODTAKNJENA-SNOV", prepisi="PODTAKNJENA-SNOV")

        assert "PODTAKNJENA-SNOV" not in klicalec.vhod
        assert "Ulomke seštevamo." in klicalec.vhod

    def test_arhivirana_tujepredmetna_in_neobstojeca_snov_ne_pride_v_vhod(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path, klicalec: LazenKlicalec
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")
        snov_s_prepisom(motor, slike, UUID_DVA, "ARHIVIRAN-PREPIS")
        arhiviraj(motor, UUID_DVA)
        snov_s_prepisom(motor, slike, UUID_TRI, "PREPIS-SLOVENSCINE", subject="SLJ")

        generiraj(odjemalec, snov=[UUID_DVA, UUID_TRI, "ni-taksnega", UUID_ENA])

        assert "Ulomke seštevamo." in klicalec.vhod
        assert "ARHIVIRAN-PREPIS" not in klicalec.vhod
        assert "PREPIS-SLOVENSCINE" not in klicalec.vhod

    def test_izbor_brez_veljavne_snovi_modela_ne_klice(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path, klicalec: LazenKlicalec
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")
        arhiviraj(motor, UUID_ENA)

        odgovor = generiraj(odjemalec)

        assert odgovor.status_code == 400
        assert "izberi znova" in odgovor.json()["napaka"]
        assert klicalec.klici == []

    @pytest.mark.parametrize("zelja", ["", "   \n "])
    def test_prazna_zelja_modela_ne_klice(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        slike: Path,
        klicalec: LazenKlicalec,
        zelja: str,
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        odgovor = generiraj(odjemalec, zelja=zelja)

        assert odgovor.status_code == 400
        assert "Napiši, kakšen test želiš" in odgovor.json()["napaka"]
        assert klicalec.klici == []

    def test_drug_predmet_modela_ne_klice(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path, klicalec: LazenKlicalec
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Prepis.", subject="SLJ")

        odgovor = generiraj(odjemalec, subject="SLJ")

        assert odgovor.status_code == 400
        assert "samo pri matematiki" in odgovor.json()["napaka"]
        assert klicalec.klici == []

    def test_brez_kljuca_je_slovenska_napaka_v_json(
        self, brez_kljuca: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        odgovor = generiraj(brez_kljuca)

        assert odgovor.status_code == 503
        assert odgovor.headers["content-type"].startswith("application/json")
        assert "Sestavljanje testov ni nastavljeno" in odgovor.json()["napaka"]


class TestNapakeModela:
    @pytest.fixture
    def klicalec(self) -> LazenKlicalec:
        return LazenKlicalec(napaka=NapakaObdelave("Model se ni odzval v 120 sekundah."))

    def test_napaka_modela_je_502_s_slovenskim_sporocilom(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        odgovor = generiraj(odjemalec)

        assert odgovor.status_code == 502
        assert odgovor.json() == {
            "napaka": (
                "Model se ni odzval v 120 sekundah. Test je ostal nespremenjen. Poskusi znova."
            )
        }

    def test_napaka_modela_gre_v_dnevnik_brez_snovi_in_zelje(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        slike: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "SKRIVNA-SNOV")

        with caplog.at_level(logging.DEBUG):
            generiraj(odjemalec, zelja="SKRIVNA-ZELJA")

        assert "Preizkus MAT: klic modela ni uspel: Model se ni odzval" in caplog.text
        assert "SKRIVNA-SNOV" not in caplog.text
        assert "SKRIVNA-ZELJA" not in caplog.text


class TestPrazenTest:
    @pytest.fixture
    def klicalec(self) -> LazenKlicalec:
        return LazenKlicalec(
            odgovor={"sporocilo": "Snovi ni dovolj za test.", "test_md": "", "resitve_md": ""}
        )

    def test_prazen_test_je_odgovor_s_sporocilom_modela(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        # Ni napaka klica: model pove, zakaj testa ni. Da test ob tem ostane,
        # kakršen je bil, poskrbi skripta (ročni preizkus).
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        odgovor = generiraj(odjemalec)

        assert odgovor.status_code == 200
        assert odgovor.json() == {
            "sporocilo": "Snovi ni dovolj za test.",
            "test_md": "",
            "resitve_md": "",
        }


class TestDnevnikPorabe:
    def test_uspesen_klic_zapise_model_trajanje_in_zetone(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        slike: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "Ulomke seštevamo.")

        with caplog.at_level(logging.DEBUG):
            generiraj(odjemalec)

        (vrstica,) = [z.getMessage() for z in caplog.records if z.name == preizkusi.dnevnik.name]
        assert vrstica == (
            "Preizkus MAT: model model-iz-odgovora, 17.2 s, žetoni vhod 5300 "
            "(predpomnjeni 1300), izhod 2100 (razmišljanje 300)."
        )

    def test_dnevnik_ne_vsebuje_snovi_zelje_ne_testa(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        slike: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        snov_s_prepisom(motor, slike, UUID_ENA, "SKRIVNA-SNOV")

        with caplog.at_level(logging.DEBUG):
            generiraj(
                odjemalec,
                zelja="SKRIVNA-ZELJA",
                test_md="SKRIVEN-TEST",
                dosedanje=["SKRIVNA-STARA-ZELJA"],
            )

        for sled in ("SKRIVNA-SNOV", "SKRIVNA-ZELJA", "SKRIVEN-TEST", "SKRIVNA-STARA-ZELJA"):
            assert sled not in caplog.text
        assert VELJAVEN["test_md"] not in caplog.text

    def test_vrstica_ravni_info_pride_v_izpis_streznika(
        self, aplikacija: FastAPI
    ) -> None:
        # Uvicorn korenskega dnevnika ne nastavi, zato bi vrstica `INFO` brez
        # lastnega izpisa ne prišla nikamor — kriterij pa zahteva dnevnik
        # strežnika. `create_app` je bil v tej zbirki klican večkrat; izpis
        # mora biti kljub temu en sam.
        assert preizkusi.dnevnik.isEnabledFor(logging.INFO)
        assert len(preizkusi.dnevnik.handlers) == 1


# --- Statične datoteke in meje `ADR-054` ---

KNJIZNICE = ("katex-0.16.22", "marked-15.0.12")


class TestStaticneDatoteke:
    @pytest.mark.parametrize(
        "pot",
        [
            "/admin/static/vendor/katex-0.16.22/katex.min.js",
            "/admin/static/vendor/katex-0.16.22/katex.min.css",
            "/admin/static/vendor/katex-0.16.22/contrib/auto-render.min.js",
            "/admin/static/vendor/katex-0.16.22/fonts/KaTeX_Main-Regular.woff2",
            "/admin/static/vendor/marked-15.0.12/marked.min.js",
        ],
    )
    def test_s_sejo_je_datoteka_postrezena(self, odjemalec: PrijavljenOdjemalec, pot: str) -> None:
        odgovor = odjemalec.get(pot)

        assert odgovor.status_code == 200
        assert len(odgovor.content) > 1000

    def test_brez_seje_pelje_na_prijavo(self, aplikacija: FastAPI, stars: str) -> None:
        # Statične datoteke so pod `/admin` prav zato, da jih varuje ista
        # plast kot vse ostalo (`ADR-054`, meja 2).
        with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brez_seje:
            odgovor = brez_seje.get(
                "/admin/static/vendor/katex-0.16.22/katex.min.js", follow_redirects=False
            )

        assert odgovor.status_code == 303
        assert odgovor.headers["location"].startswith("/admin/login")

    def test_neobstojeca_datoteka_je_404(self, odjemalec: PrijavljenOdjemalec) -> None:
        assert odjemalec.get("/admin/static/vendor/ni-je.js").status_code == 404

    def test_pot_iz_mape_ne_uide(self, odjemalec: PrijavljenOdjemalec) -> None:
        odgovor = odjemalec.get("/admin/static/%2e%2e/main.py")

        assert odgovor.status_code == 404

    def test_knjiznici_sta_natanko_dve_z_razlicico_v_imenu_mape(self) -> None:
        mape = sorted(pot.name for pot in (MAPA_STATICNIH / "vendor").iterdir())

        assert mape == list(KNJIZNICE)

    @pytest.mark.parametrize("knjiznica", KNJIZNICE)
    def test_ob_vsaki_knjiznici_je_licenca(self, knjiznica: str) -> None:
        licenca = MAPA_STATICNIH / "vendor" / knjiznica / "LICENSE"

        assert "MIT" in licenca.read_text(encoding="utf-8")

    def test_samo_pomanjsane_datoteke_in_pisave_woff2(self) -> None:
        # `ADR-054`, meja 2. Datoteka, ki je stran ne naloži, je ostanek.
        koncnice = {
            pot.name if pot.name == "LICENSE" else "".join(pot.suffixes[-2:])
            for pot in (MAPA_STATICNIH / "vendor").rglob("*")
            if pot.is_file()
        }

        assert koncnice == {"LICENSE", ".min.js", ".min.css", ".woff2"}

    def test_staticne_datoteke_so_navedene_kot_podatki_paketa(self) -> None:
        # Brez te vrstice so testi zeleni (tečejo iz izvorne mape), vsebnik pa
        # urejevalnika ne izriše — isti razred napake kot pri predlogah.
        besedilo = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(
            encoding="utf-8"
        )

        assert '"*" = ["static/**/*"]' in besedilo


class TestBrezCdn:
    """Nobene povezave na tuj strežnik v nobeni predlogi (`ADR-054`, meja 2)."""

    #: Oznake, ki ob izrisu same naložijo vir.
    VIRI = re.compile(
        r"""<(?:script|link|img|iframe|source|video|audio|embed|object)\b[^>]*?
            \b(?:src|href|data)\s*=\s*["']?\s*(?:https?:)?//""",
        re.IGNORECASE | re.VERBOSE,
    )
    UVOZI = re.compile(r"""(?:@import|url\()\s*["']?\s*(?:https?:)?//""", re.IGNORECASE)

    def test_vzorec_ujame_cdn(self) -> None:
        # Varovalka testa: vzorec, ki ne ujame ničesar, je zelen vedno.
        assert self.VIRI.search('<script src="https://cdn.jsdelivr.net/npm/katex"></script>')
        assert self.VIRI.search("<link rel=stylesheet href=//cdn.primer.test/a.css>")
        assert self.UVOZI.search('@import url("https://fonts.googleapis.com/css")')
        assert not self.VIRI.search('<script src="/admin/static/vendor/x.min.js"></script>')

    def test_predloge_ne_nalagajo_nicesar_od_drugod(self) -> None:
        najdeno = [
            pot.name
            for pot in sorted(MAPA_PREDLOG.rglob("*.html"))
            if self.VIRI.search(pot.read_text(encoding="utf-8"))
            or self.UVOZI.search(pot.read_text(encoding="utf-8"))
        ]

        assert najdeno == []

    def test_slog_knjiznice_ne_nalaga_nicesar_od_drugod(self) -> None:
        slog = (MAPA_STATICNIH / "vendor" / "katex-0.16.22" / "katex.min.css").read_text(
            encoding="utf-8"
        )

        assert not self.UVOZI.search(slog)
        # Pisave so relativne na slog, torej z našega strežnika.
        assert "url(fonts/KaTeX_Main-Regular.woff2)" in slog


class TestSkriptaUrejevalnika:
    """Meje `ADR-054` za `preizkus.html` — kar se da preveriti brez brskalnika."""

    @pytest.fixture
    def stran(self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path) -> str:
        zapisi(motor, slike)
        besedilo: str = sestavi(odjemalec, "MAT", UUID_ENA).text
        return besedilo

    def test_zunanje_skripte_so_natanko_tri_in_vse_nase(self, stran: str) -> None:
        assert re.findall(r'<script src="([^"]+)"', stran) == [
            "/admin/static/vendor/marked-15.0.12/marked.min.js",
            "/admin/static/vendor/katex-0.16.22/katex.min.js",
            "/admin/static/vendor/katex-0.16.22/contrib/auto-render.min.js",
        ]
        assert re.findall(r'<link[^>]+href="([^"]+)"', stran) == [
            "/admin/static/vendor/katex-0.16.22/katex.min.css"
        ]

    def test_brez_skripte_stran_pove_da_je_ne_more_izrisati(self, stran: str) -> None:
        zacetek = stran.index("<noscript>")
        sporocilo = stran[zacetek : stran.index("</noscript>", zacetek)]

        assert "potrebuje JavaScript" in sporocilo

    def test_skripta_klice_streznik_na_enem_mestu_in_z_obrazcem(self, stran: str) -> None:
        skripta = stran[stran.rindex("<script>") : stran.rindex("</script>")]

        assert skripta.count("fetch(") == 1
        assert 'fetch(koren.getAttribute("data-pot")' in skripta
        assert "new URLSearchParams()" in skripta
        for prepovedano in ("XMLHttpRequest", "sendBeacon", "localStorage", "sessionStorage"):
            assert prepovedano not in skripta
        assert "JSON.stringify" not in skripta

    def test_skripta_ne_zaupa_besedilu_modela(self, stran: str) -> None:
        # Surov HTML se ubeži pred `marked`, povezave in slike iz markdowna se
        # odstranijo. Trditev je o prisotnosti varovalk; da delujejo, pokaže
        # ročni preizkus.
        skripta = stran[stran.rindex("<script>") : stran.rindex("</script>")]

        assert 'vir.replace(/&/g, "&amp;").replace(/</g, "&lt;")' in skripta
        assert 'querySelectorAll("a")' in skripta
        assert 'querySelectorAll("img")' in skripta
        assert "trust" not in skripta

    def test_tisk_ima_rob_strani_in_naloga_se_ne_razdeli(self, stran: str) -> None:
        assert "@page { size: A4; margin: 15mm 18mm; }" in stran
        assert ".list .naloga { break-inside: avoid; page-break-inside: avoid; }" in stran
        assert "body:not(.z-resitvami) #list-resitve { display: none; }" in stran

    def test_stran_predmeta_ostane_brez_skripte(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        assert "<script" not in odjemalec.get("/admin/subjects/MAT").text.lower()


# --- Nastavitve ---


class TestNastavitve:
    def test_kljuc_preizkusov_je_locen_in_privzeto_prazen(self) -> None:
        nastavitve = Settings(database_url="sqlite://", openai_api_key="kljuc-za-vision")

        assert nastavitve.openai_api_key_preizkusi == ""
        assert nastavitve.openai_model_preizkusi == "gpt-5.6-luna"

    def test_kljuc_in_model_prideta_iz_okolja(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY_PREIZKUSI", "kljuc-iz-okolja")
        monkeypatch.setenv("OPENAI_MODEL_PREIZKUSI", "model-iz-okolja")

        nastavitve = Settings()

        assert nastavitve.openai_api_key_preizkusi == "kljuc-iz-okolja"
        assert nastavitve.openai_model_preizkusi == "model-iz-okolja"

    def test_vision_kljuc_ne_prizge_preizkusov(
        self, nastavitve: Settings, motor: Engine
    ) -> None:
        # Ločena ključa (`ADR-054`): eden brez drugega ne prižge ničesar.
        samo_vision = nastavitve.model_copy(update={"worker_interval_seconds": 3600.0})
        aplikacija = create_app(
            nastavitve=samo_vision, motor=motor, klicalec=lambda pot: pytest.fail("ne kliči")
        )

        assert aplikacija.state.klicalec_preizkusa is None

    def test_predloga_okolja_nosi_imeni_brez_kljuca(self) -> None:
        besedilo = (Path(__file__).resolve().parent.parent / "okolje.primer").read_text(
            encoding="utf-8"
        )

        assert "OPENAI_API_KEY_PREIZKUSI=\n" in besedilo
        assert "OPENAI_MODEL_PREIZKUSI=gpt-5.6-luna\n" in besedilo

    def test_compose_poda_obe_spremenljivki_vsebniku(self) -> None:
        # Compose vsebniku poda samo naštete spremenljivke; brez teh dveh
        # vrstic bi ključ v `.env` ostal brez učinka.
        besedilo = (Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text(
            encoding="utf-8"
        )

        assert "OPENAI_API_KEY_PREIZKUSI: ${OPENAI_API_KEY_PREIZKUSI:-}" in besedilo
        assert "OPENAI_MODEL_PREIZKUSI: ${OPENAI_MODEL_PREIZKUSI:-gpt-5.6-luna}" in besedilo
