"""Nastavitve morajo napačno konfiguracijo ujeti ob zagonu, ne ob prvi zahtevi."""

import pytest
from pydantic import ValidationError

from app.settings import API_KEY_NAJMANJ_ZNAKOV, Settings


def test_veljaven_kljuc_je_sprejet() -> None:
    nastavitve = Settings(api_key="a" * API_KEY_NAJMANJ_ZNAKOV)

    assert nastavitve.api_key == "a" * API_KEY_NAJMANJ_ZNAKOV


@pytest.mark.parametrize("kljuc", ["", "prekratek", "a" * (API_KEY_NAJMANJ_ZNAKOV - 1)])
def test_prazen_ali_prekratek_kljuc_prepreci_zagon(kljuc: str) -> None:
    # Strežnik s praznim ključem bi tiho spustil skozi vsakogar. Napaka ob
    # zagonu je edina, ki se je ne da spregledati.
    with pytest.raises(ValidationError):
        Settings(api_key=kljuc)


def test_manjkajoc_kljuc_prepreci_zagon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]  # polja bi prišla iz okolja
