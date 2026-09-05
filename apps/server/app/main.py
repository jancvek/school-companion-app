"""Sestavljanje aplikacije.

`create_app` je tovarna, ne modulska spremenljivka. Razloga sta dva: strežnik
ob uvozu modula ne sme zahtevati `API_KEY` (sicer se ne da uvoziti niti za
test), vsak test pa dobi svojo aplikacijo s svojo bazo in svojim ključem.
Uvicorn jo zato zažene z zastavico `--factory`.
"""

from fastapi import FastAPI
from sqlalchemy import Engine

from app.db import naredi_motor, naredi_tovarno_sej
from app.routers import materials
from app.schemas import Zivost
from app.security import ApiKeyMiddleware
from app.settings import Settings

#: Poti, ki ključa ne zahtevajo. `GET /health` mora odgovoriti tudi brez njega,
#: sicer preverba živosti ne loči „strežnik ne teče" od „ključ ni pravi".
IZVZETE_POTI = frozenset({"/health"})


def create_app(nastavitve: Settings | None = None, motor: Engine | None = None) -> FastAPI:
    """Sestavi aplikacijo. Brez argumentov prebere nastavitve iz okolja."""
    if nastavitve is None:
        nastavitve = Settings()  # type: ignore[call-arg]  # polja pridejo iz okolja
    if motor is None:
        motor = naredi_motor(nastavitve.database_url)

    app = FastAPI(title="Šolski pomočnik — strežnik", version="1.0.0")
    app.state.nastavitve = nastavitve
    app.state.motor = motor
    app.state.tovarna_sej = naredi_tovarno_sej(motor)

    app.add_middleware(
        ApiKeyMiddleware,
        api_key=nastavitve.api_key,
        izvzete_poti=IZVZETE_POTI,
    )

    app.include_router(materials.router)

    @app.get("/health", response_model=Zivost)
    def zivost() -> Zivost:
        """Preverba živosti. Ne dotakne se ne baze ne diska."""
        return Zivost(status="ok")

    return app
