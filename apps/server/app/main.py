"""Sestavljanje aplikacije.

`create_app` je tovarna, ne modulska spremenljivka: vsak test dobi svojo
aplikacijo s svojo bazo, svojo mapo slik in svojim klicalcem, brez globalnega
stanja na ravni modula. Uvicorn jo zato zažene z zastavico `--factory`.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import prijava, strani
from app.db import naredi_motor, naredi_tovarno_sej
from app.routers import (
    admin,
    clani,
    dnevi,
    kvizi,
    materials,
    resevanje,
    sistem,
    statistika,
    urnik,
    vstop,
)
from app.schemas import Zivost
from app.security import SejaMiddleware, ZetonMiddleware
from app.settings import Settings
from app.vision import Klicalec, KlicalecUrnika, naredi_klicalca, naredi_klicalca_urnika
from app.worker import Obdelovalec

dnevnik = logging.getLogger(__name__)

#: Poti, ki žetona ne zahtevajo.
#:
#: `GET /health` mora odgovoriti tudi brez njega, sicer preverba živosti ne
#: loči „strežnik ne teče" od „prijava ni veljavna". `POST /auth/login` je
#: pot, na kateri žeton šele nastane; **odjave tu ni** — ta zahteva žeton kot
#: vsaka druga pot telefona (`docs/odlocitve/ADR-036` G).
IZVZETE_POTI = frozenset({"/health", prijava.POT_PRIJAVE_TELEFONA})

#: Predpone, ki žetona ne zahtevajo.
#:
#: Operaterska stran teče v brskalniku, ki žetona ne nosi v glavi, ampak v
#: piškotku. **Izvzetje iz žetona ne pomeni, da je stran odprta:** varuje jo
#: `SejaMiddleware` — seja za vsako pot, CSRF žeton za vsako nevarno metodo
#: (`docs/odlocitve/ADR-035`). Pred V3-R03 je bil tu začasen `basic_auth` v
#: Caddyju (`ADR-026`), pred V3-R02 pa Tailscale (`ADR-006`).
#:
#: **Tu ne dodajaj ničesar brez ADR.** Vsaka predpona na tem seznamu je pot,
#: ki je `ZetonMiddleware` ne varuje.
IZVZETE_PREDPONE = frozenset({"/admin"})

#: Poti pod `/admin`, ki seje ne zahtevajo. Sicer se ne bi bilo mogoče
#: prijaviti. **Odjave tu ni**: ta sejo zahteva kot vsak drug `POST`.
POTI_BREZ_SEJE = frozenset({prijava.POT_PRIJAVE})

#: Poti, ki CSRF žeton preverijo **same** (`docs/odlocitve/ADR-043`).
#:
#: Sejo zahtevajo kot vsaka druga pot pod `/admin`; izpade samo branje telesa v
#: plasti, ker telo nosi datoteko. Nabor je **enočlanski** in to varuje test:
#: druga taka pot naj ne zaide sem tiho, ampak naj pretehta možnost A iz
#: `ADR-043` — da se `multipart` nauči plast sama.
POTI_S_SVOJIM_CSRF = frozenset({urnik.POT_PREDLOGA})


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
    klicalec_urnika: KlicalecUrnika | None = None,
) -> FastAPI:
    """Sestavi aplikacijo. Brez argumentov prebere nastavitve iz okolja.

    `klicalec` se poda in ne uvozi, iz istega razloga kot vse drugo v
    `app/dependencies.py`: testi dobijo svojo funkcijo in nikoli ne pridejo do
    omrežja. Brez njega si ga aplikacija zgradi sama — a le, če ključ je.
    """
    if nastavitve is None:
        nastavitve = Settings()  # vsa polja imajo privzetek; okolje jih le prepiše
    if motor is None:
        motor = naredi_motor(nastavitve.database_url)
    if klicalec is None and nastavitve.openai_api_key:
        klicalec = naredi_klicalca(nastavitve)
    # Svoj klicalec za urnik (V3-R09): drug prompt, druga shema, drug izid.
    # Brez ključa ostane `None` in stran z urnikom to pove v slovenščini —
    # mreža je urejljiva tudi brez slike (`ADR-041` E).
    if klicalec_urnika is None and nastavitve.openai_api_key:
        klicalec_urnika = naredi_klicalca_urnika(nastavitve)

    app = FastAPI(
        title="Šolski pomočnik — strežnik",
        version="1.0.0",
        lifespan=_zivljenjski_cikel,
    )
    app.state.nastavitve = nastavitve
    app.state.motor = motor
    app.state.tovarna_sej = naredi_tovarno_sej(motor)
    # `context_processors`: glava z družino in CSRF žeton morata biti v **vsaki**
    # predlogi, ne v 27 klicih `TemplateResponse` (`docs/odlocitve/ADR-035` D).
    app.state.predloge = Jinja2Templates(
        directory=str(admin.MAPA_PREDLOG),
        context_processors=[strani.kontekst_prijave],
    )
    app.state.klicalec = klicalec
    app.state.klicalec_urnika = klicalec_urnika
    app.state.obdelovalec = None

    # Vrstni red plasti: zadnja dodana je zunanja. Žeton je torej pred sejo.
    # Vsaka od obeh plasti obdela svoje poti in tuje spusti naprej nedotaknjene
    # (`ZetonMiddleware` izvzame predpono `/admin`, `SejaMiddleware` se ujame
    # samo nanjo), zato se ne prekrivata in nobena zahteva ne prebere seje
    # dvakrat.
    app.add_middleware(
        SejaMiddleware,
        izvzete_poti=POTI_BREZ_SEJE,
        poti_s_svojim_csrf=POTI_S_SVOJIM_CSRF,
    )
    app.add_middleware(
        ZetonMiddleware,
        izvzete_poti=IZVZETE_POTI,
        izvzete_predpone=IZVZETE_PREDPONE,
    )

    # Prijava in odjava brskalnika (V3-R03) ter telefona (V3-R04). Prvi med
    # usmerjevalniki pod `/admin`, ker `/admin/login` ne sme zaiti v ujemalnik
    # `/admin/materials/{id}`.
    app.include_router(vstop.router)
    app.include_router(materials.router)
    # Poti telefona za kvize (V2-R02). Niso pod `/admin`, zato zahtevajo žeton.
    app.include_router(resevanje.router)
    app.include_router(admin.router)
    # Za `admin.router` in ne pred njim: `kvizi` doda poti pod isto
    # predpono `/admin`, zato je vrstni red registracije viden navzven.
    # `/admin/quizzes/...` se z nobeno obstoječo potjo ne prekriva —
    # `admin` ima `/admin/materials/...` in `/admin/subjects/...`.
    app.include_router(kvizi.router)
    # Statistika čez kvize (V2-R04), pod `/admin/statistics/...` — z nobeno
    # obstoječo potjo se ne prekriva. Pod `/admin` in torej brez ključa:
    # vidna je samo na operaterski strani (`docs/odlocitve/ADR-021` F).
    app.include_router(statistika.router)
    # Pregled slik po obdobju in predmetih (V2-R07), pod `/admin/days`. Z
    # nobeno obstoječo potjo se ne prekriva in samo bere; varuje jo isto kot
    # ves `/admin` (`docs/odlocitve/ADR-026`).
    app.include_router(dnevi.router)
    # Člani družine (V3-R06), pod `/admin/family`. Z nobeno obstoječo potjo se
    # ne prekriva in je varovana z isto plastjo kot ves `/admin` (`ADR-035` A);
    # pravila o tem, kdo sme koga, so v `app/clani.py`.
    app.include_router(clani.router)
    # Urnik otroka (V3-R09), pod `/admin/schedule`. Z nobeno obstoječo potjo se
    # ne prekriva. Edina pot pod `/admin`, ki sprejme datoteko; varuje jo ista
    # plast kot ves `/admin`, pravila urnika pa so v `app/urnik.py`.
    app.include_router(urnik.router)
    # Stran lastnika sistema (V3-R05), pod `/admin/system`. Z nobeno obstoječo
    # potjo se ne prekriva. Poleg seje jo varuje še `zahtevaj_lastnika_sistema`
    # na samem usmerjevalniku: za starša ta predpona ne obstaja (404, ne 403;
    # `docs/odlocitve/ADR-044` G).
    app.include_router(sistem.router)

    # Napake pod `/admin` naj bodo stran, ne JSON. Prestreznik se za vse
    # ostale poti umakne privzetemu — glej `admin.prestrezi_napako`.
    app.add_exception_handler(StarletteHTTPException, admin.prestrezi_napako)

    @app.get("/health", response_model=Zivost)
    def zivost() -> Zivost:
        """Preverba živosti. Ne dotakne se ne baze ne diska."""
        return Zivost(status="ok")

    return app
