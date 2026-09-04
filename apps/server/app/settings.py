"""Nastavitve strežnika, brane iz okolja.

Vrednosti pridejo iz spremenljivk okolja (v Docker Compose iz `.env`).
Privzetka za `API_KEY` namenoma ni: strežnik brez ključa ne sme steči, ker bi
tiho sprejemal vse. Manjkajoč ključ je napaka ob zagonu, ne ob prvi zahtevi.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Nastavitve ene instance strežnika."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    #: Statični ključ, ki ga telefon pošlje v glavi `X-API-Key`.
    api_key: str

    #: Povezava do Postgresa (SQLAlchemy oblika).
    database_url: str = "postgresql+psycopg://solski:solski@db:5432/solski"

    #: Mapa, v katero se zapisujejo prejete slike.
    images_dir: Path = Path("/data/images")
