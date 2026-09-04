"""Nastavitve strežnika, brane iz okolja.

Vrednosti pridejo iz spremenljivk okolja (v Docker Compose iz `.env`).
Privzetka za `API_KEY` namenoma ni: strežnik brez ključa ne sme steči, ker bi
tiho sprejemal vse. Manjkajoč ključ je napaka ob zagonu, ne ob prvi zahtevi.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Najkrajši sprejemljiv ključ.
#:
#: Meja ni okrasna. `secrets.compare_digest(b"", b"")` vrne `True`, zato bi
#: prazen `API_KEY` pomenil strežnik, ki spusti skozi vsakogar, ki pošlje
#: prazno glavo — in to tiho, brez ene same napake v dnevniku. Docker Compose
#: prazno vrednost sicer ujame (`${API_KEY:?}`), zagon `uvicorn` mimo njega
#: pa ne. Zato meja živi tu, kjer velja vedno.
API_KEY_NAJMANJ_ZNAKOV = 16


class Settings(BaseSettings):
    """Nastavitve ene instance strežnika."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    #: Statični ključ, ki ga telefon pošlje v glavi `X-API-Key`.
    #: Prekratek ali prazen ključ je napaka ob zagonu, ne šele ob prvi zahtevi.
    api_key: str = Field(min_length=API_KEY_NAJMANJ_ZNAKOV)

    #: Povezava do Postgresa (SQLAlchemy oblika).
    database_url: str = "postgresql+psycopg://solski:solski@db:5432/solski"

    #: Mapa, v katero se zapisujejo prejete slike.
    images_dir: Path = Path("/data/images")
