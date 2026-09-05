"""Nastavitve morajo napačno konfiguracijo ujeti ob zagonu, ne ob prvi zahtevi."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.settings import API_KEY_NAJMANJ_ZNAKOV, Settings

VELJAVEN = "a" * API_KEY_NAJMANJ_ZNAKOV


def test_veljaven_kljuc_je_sprejet() -> None:
    nastavitve = Settings(api_key=VELJAVEN)

    assert nastavitve.api_key == VELJAVEN


@pytest.mark.parametrize("kljuc", ["", "prekratek", "a" * (API_KEY_NAJMANJ_ZNAKOV - 1)])
def test_prazen_ali_prekratek_kljuc_prepreci_zagon(kljuc: str) -> None:
    # Strežnik s praznim ključem bi tiho spustil skozi vsakogar, ker
    # `compare_digest(b"", b"")` vrne True. Napaka ob zagonu je edina, ki se je
    # ne da spregledati.
    with pytest.raises(ValidationError):
        Settings(api_key=kljuc)


def test_manjkajoc_kljuc_prepreci_zagon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]  # polje bi prišlo iz okolja


def test_nastavitve_ne_berejo_datoteke_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Izid ne sme biti odvisen od tega, od kod je ukaz pognan.

    `env_file` je relativen na trenutno delovno mapo, ne na paket. Če bi ga
    `Settings` brala, bi bil ta test zelen ali rdeč glede na to, ali je lastnik
    že naredil `apps/server/.env` po `okolje.primer` — in `pytest` iz korena bi
    se obnašal drugače kot `pytest` iz `apps/server`.

    Test dela v začasni mapi, da ne more povoziti prave `.env`.
    """
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"API_KEY={VELJAVEN}\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_privzetki_ne_zahtevajo_okolja(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ključ je edino polje brez privzetka; ostalo mora imeti smiselno vrednost.

    Spremenljivke se izbrišejo, sicer bi bil ta test — ki naj neodvisnost od
    okolja prav dokazuje — sam odvisen od tega, kaj je v lupini izvoženo.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("IMAGES_DIR", raising=False)

    nastavitve = Settings(api_key=VELJAVEN)

    assert nastavitve.database_url.startswith("postgresql+psycopg://")
    assert nastavitve.images_dir.name == "images"


def test_openai_kljuc_ni_pogoj_za_zagon() -> None:
    """Za razliko od `API_KEY` odsotnost tega ključa strežnika ne ustavi.

    Ustavi samo obdelavo — slike ostanejo `new`, dokler ključa ni
    (`docs/odlocitve/ADR-009`). Če bi kdo temu polju dal `min_length`, bi se
    strežnik nehal zaganjati brez ključa za OpenAI, in prevzem slik s telefona
    bi padel skupaj z obdelavo.
    """
    nastavitve = Settings(api_key=VELJAVEN)

    assert nastavitve.openai_api_key == ""


def test_privzetki_obdelave() -> None:
    """ADR-008: ime modela je nastavitev, ne konstanta v kodi."""
    nastavitve = Settings(api_key=VELJAVEN)

    assert nastavitve.openai_model == "gpt-4.1"
    assert nastavitve.openai_timeout_seconds == 120.0
    assert nastavitve.worker_interval_seconds == 30.0


def test_ime_modela_pride_iz_okolja(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zamenjava modela mora biti sprememba spremenljivke okolja (ADR-008)."""
    monkeypatch.setenv("OPENAI_MODEL", "nekaj-novejsega")

    assert Settings(api_key=VELJAVEN).openai_model == "nekaj-novejsega"
