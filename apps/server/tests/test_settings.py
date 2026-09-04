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


def test_privzetki_ne_zahtevajo_okolja() -> None:
    """Ključ je edino polje brez privzetka; ostalo mora imeti smiselno vrednost."""
    nastavitve = Settings(api_key=VELJAVEN)

    assert nastavitve.database_url.startswith("postgresql+psycopg://")
    assert nastavitve.images_dir.name == "images"
