"""Sestavljanje aplikacije.

`create_app` je tovarna, ne modulska spremenljivka. Razloga sta dva: strežnik
ob uvozu modula ne sme zahtevati `API_KEY` (sicer se ne da uvoziti niti za
test), vsak test pa dobi svojo aplikacijo s svojo bazo in svojim ključem.
Uvicorn jo zato zažene z zastavico `--factory`.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db import naredi_motor, naredi_tovarno_sej
from app.routers import admin, materials
from app.schemas import Zivost
from app.security import ApiKeyMiddleware
from app.settings import Settings
from app.vision import Klicalec, naredi_klicalca
from app.worker import Obdelovalec

dnevnik = logging.getLogger(__name__)

#: Poti, ki ključa ne zahtevajo. `GET /health` mora odgovoriti tudi brez njega,
#: sicer preverba živosti ne loči „strežnik ne teče" od „ključ ni pravi".
IZVZETE_POTI = frozenset({"/health"})

#: Predpone, ki ključa ne zahtevajo.
#:
#: Operaterska stran teče v brskalniku, ta pa glave `X-API-Key` ne zna
#: poslati. Meja pred njo je Tailscale in vezava strežnika na tisti naslov —
#: glej `docs/odlocitve/ADR-006`, ki to izbiro in njene posledice zapiše.
#:
#: **Tu ne dodajaj ničesar brez ADR.** Vsaka predpona na tem seznamu je pot,
#: ki jo lahko odpre kdorkoli v omrežju.
IZVZETE_PREDPONE = frozenset({"/admin"})


@asynccontextmanager
async def _zivljenjski_cikel(app: FastAPI) -> AsyncIterator[None]:
    """Zažene in ustavi obdelavo v ozadju.

    **Brez ključa za OpenAI se obdelava ne zažene** (`docs/odlocitve/ADR-009`).
    Slike takrat ostanejo `new` in se obdelajo same, ko je ključ nastavljen in
    strežnik zagnan znova. Dobesedno branje robnega primera („manjkajoč ključ →
    `failed`") bi vsako prispelo sliko v nekaj sekundah poslalo v `failed` in
    zanjo zahtevalo ročno vrnitev v vrsto — napaka v nastavitvi bi tako
    proizvedla delo, sorazmerno s številom slik.

    Prevzem slik, admin stran in `GET /health` tečejo naprej v vsakem primeru.
    """
    klicalec: Klicalec | None = app.state.klicalec

    if klicalec is None:
        dnevnik.warning(
            "OPENAI_API_KEY ni nastavljen, zato obdelava slik ne teče. "
            "Slike se sprejemajo in ostanejo v stanju „čaka na obdelavo“. "
            "Vpiši ključ v apps/server/.env in zaženi strežnik znova."
        )
        app.state.obdelovalec = None
        yield
        return

    obdelovalec = Obdelovalec(
        tovarna_sej=app.state.tovarna_sej,
        klicalec=klicalec,
        images_dir=app.state.nastavitve.images_dir,
        interval=app.state.nastavitve.worker_interval_seconds,
    )
    app.state.obdelovalec = obdelovalec
    obdelovalec.zazeni()
    try:
        yield
    finally:
        await obdelovalec.ustavi()


def create_app(
    nastavitve: Settings | None = None,
    motor: Engine | None = None,
    klicalec: Klicalec | None = None,
) -> FastAPI:
    """Sestavi aplikacijo. Brez argumentov prebere nastavitve iz okolja.

    `klicalec` se poda in ne uvozi, iz istega razloga kot vse drugo v
    `app/dependencies.py`: testi dobijo svojo funkcijo in nikoli ne pridejo do
    omrežja. Brez njega si ga aplikacija zgradi sama — a le, če ključ je.
    """
    if nastavitve is None:
        nastavitve = Settings()  # type: ignore[call-arg]  # polja pridejo iz okolja
    if motor is None:
        motor = naredi_motor(nastavitve.database_url)
    if klicalec is None and nastavitve.openai_api_key:
        klicalec = naredi_klicalca(nastavitve)

    app = FastAPI(
        title="Šolski pomočnik — strežnik",
        version="1.0.0",
        lifespan=_zivljenjski_cikel,
    )
    app.state.nastavitve = nastavitve
    app.state.motor = motor
    app.state.tovarna_sej = naredi_tovarno_sej(motor)
    app.state.predloge = Jinja2Templates(directory=str(admin.MAPA_PREDLOG))
    app.state.klicalec = klicalec
    app.state.obdelovalec = None

    app.add_middleware(
        ApiKeyMiddleware,
        api_key=nastavitve.api_key,
        izvzete_poti=IZVZETE_POTI,
        izvzete_predpone=IZVZETE_PREDPONE,
    )

    app.include_router(materials.router)
    app.include_router(admin.router)

    # Napake pod `/admin` naj bodo stran, ne JSON. Prestreznik se za vse
    # ostale poti umakne privzetemu — glej `admin.prestrezi_napako`.
    app.add_exception_handler(StarletteHTTPException, admin.prestrezi_napako)

    @app.get("/health", response_model=Zivost)
    def zivost() -> Zivost:
        """Preverba živosti. Ne dotakne se ne baze ne diska."""
        return Zivost(status="ok")

    return app
