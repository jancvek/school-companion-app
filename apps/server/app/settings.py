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

    # Nastavitve pridejo **samo** iz okolja, ne iz `.env`.
    #
    # V Docker Compose jih poda `environment:`; datoteko `apps/server/.env`
    # prebere Compose sam, da razreši `${API_KEY}` in podobno. Branje `.env`
    # še tu ne bi dodalo ničesar, prineslo pa bi odvisnost od trenutne delovne
    # mape — `env_file` je relativen nanjo, ne na paket. Isti ukaz bi se torej
    # obnašal različno glede na to, od kod je pognan; to velja za strežnik in
    # za teste.
    model_config = SettingsConfigDict(extra="ignore")

    #: Statični ključ, ki ga telefon pošlje v glavi `X-API-Key`.
    #: Prekratek ali prazen ključ je napaka ob zagonu, ne šele ob prvi zahtevi.
    api_key: str = Field(min_length=API_KEY_NAJMANJ_ZNAKOV)

    #: Povezava do Postgresa (SQLAlchemy oblika).
    database_url: str = "postgresql+psycopg://solski:solski@db:5432/solski"

    #: Mapa, v katero se zapisujejo prejete slike.
    images_dir: Path = Path("/data/images")

    #: Ključ za OpenAI. **Privzetek je prazen niz in to je namerno.**
    #:
    #: Za razliko od `api_key` odsotnost tega ključa strežnika ne ustavi:
    #: prevzem slik, admin stran in `GET /health` delujejo brez njega. Ustavi
    #: samo obdelavo — worker se ne zažene in slike ostanejo `new`, dokler
    #: ključa ni. Glej `docs/odlocitve/ADR-009` za to razliko in za razlog,
    #: zakaj manjkajoč ključ ne pomeni `status='failed'`.
    openai_api_key: str = ""

    #: Ime vision modela. **Nastavitev, ne konstanta v kodi** (ADR-008):
    #: zamenjava z novejšim modelom mora biti sprememba spremenljivke okolja
    #: in ponovni zagon, ne predelava.
    openai_model: str = "gpt-4.1"

    #: Časovna omejitev enega klica modela, v sekundah.
    #:
    #: Meja ni okras. Klic brez nje bi lahko visel neomejeno; worker obdeluje
    #: zaporedno, zato bi en tak klic ustavil vrsto za vse ostale slike.
    openai_timeout_seconds: float = 120.0

    #: Razmik med obhodi worker zanke, v sekundah (kriterij pravi ~30).
    worker_interval_seconds: float = 30.0
