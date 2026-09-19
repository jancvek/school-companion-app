"""Prijava in odjava — v brskalniku (V3-R03) in na telefonu (V3-R04).

Oboje je tu in ne v dveh usmerjevalnikih, ker je pod obojim ista preverba
(`prijava.preveri_prijavo`), ista tabela `sessions` in isto omejevanje
ugibanja. Razlikuje se prenosnik in oblika odgovora:

| | brskalnik | telefon |
|---|---|---|
| poti | `/admin/login`, `/admin/logout` | `/auth/login`, `/auth/logout` |
| žeton potuje v | piškotku `seja` | glavi `Authorization: Bearer` |
| vsebina | obrazec in HTML | JSON |
| CSRF | da (dvojno oddan piškotek) | **ne** — brez piškotka ga ni treba |
| vloga, ki sme skozi | starš | otrok |

Poti brskalnika sta pod `/admin`, ker sta del operaterske strani; poti telefona
sta zunaj nje, ker bi ju `SejaMiddleware` sicer zahteval s piškotkom in CSRF
žetonom (`docs/odlocitve/ADR-036` G).

Nobena od odjav ni izvzeta iz svoje plasti: obe zahtevata veljavno sejo.
Odjava prek `GET` bi pomenila, da te lahko tuja stran s sliko odjavi.
"""

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, RedirectResponse, Response

from app import prijava
from app.db import PrijavaRepository, SejaUporabnika
from app.dependencies import daj_prijavo, daj_repozitorij_prijave
from app.prijava import Izid, Vrata
from app.schemas import OdjavaOpravljena, PrijavaTelefona, ZetonPrijave
from app.strani import daj_predloge

router = APIRouter(tags=["prijava"])

#: Koliko časa velja piškotek v brskalniku. Enako kot seja v bazi — krajši bi
#: pomenil, da se uporabnica odjavi sama od sebe, daljši pa piškotek, ki nima
#: več seje.
PISKOTEK_SEKUND = int(prijava.TRAJANJE_SEJE.total_seconds())

SPOROCILO_CSRF = (
    "Prijavni obrazec je potekel ali ni prišel s te strani. Osveži stran in poskusi znova."
)


def _postavi_piskotek(odgovor: Response, ime: str, vrednost: str, sekund: int) -> None:
    """Piškotek s tremi zastavicami iz kriterija `V3-R03`.

    `secure=True` velja tudi v razvoju: strežnik je od `V3-R02` za Caddyjem in
    govori izključno `https`. Testi zato tečejo na `https://testserver`.
    """
    odgovor.set_cookie(
        ime,
        vrednost,
        max_age=sekund,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _stran_prijave(
    predloge: Jinja2Templates,
    request: Request,
    *,
    cilj: str,
    sporocilo: str | None = None,
    koda: int = 200,
) -> Response:
    """Izriše prijavno stran in postavi CSRF piškotek obrazca.

    Žeton je nov ob vsakem izrisu; stari piškotek se prepiše. Dvojno oddan
    žeton (piškotek + skrito polje) je edina možnost, dokler seje še ni
    (`docs/odlocitve/ADR-035` D).
    """
    zeton = prijava.nov_zeton()
    odgovor = predloge.TemplateResponse(
        request,
        "prijava.html",
        {"cilj": cilj, "sporocilo": sporocilo, "csrf": zeton},
        status_code=koda,
    )
    _postavi_piskotek(odgovor, prijava.PISKOTEK_CSRF_PRIJAVE, zeton, PISKOTEK_SEKUND)
    return odgovor


@router.get(prijava.POT_PRIJAVE)
def stran_prijave(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    # V naslovu je `next`, v kodi `cilj`: ime parametra v Pythonu bi sicer
    # zasenčilo vgrajeno funkcijo `next`.
    cilj: Annotated[str | None, Query(alias="next")] = None,
) -> Response:
    """Prijavni obrazec. Cilj `next` se sanira že tu, ne šele po prijavi."""
    return _stran_prijave(predloge, request, cilj=prijava.varen_cilj(cilj))


@router.post(prijava.POT_PRIJAVE)
async def prijavi(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[PrijavaRepository, Depends(daj_repozitorij_prijave)],
    identifikator: Annotated[str, Form()] = "",
    geslo: Annotated[str, Form()] = "",
    csrf: Annotated[str, Form()] = "",
    cilj: Annotated[str, Form()] = prijava.PRIVZETI_CILJ,
) -> Response:
    """Preveri poverilnico in ob uspehu postavi sejo.

    Vrstni red korakov ni poljuben: najprej CSRF (zahteva, ki ni prišla s te
    strani, se ne šteje v omejevanje), nato zamik, šele nato geslo. Zamik pred
    preverbo in ne po njej — po njej bi bila razlika v času še vedno merljiva.
    """
    varen = prijava.varen_cilj(cilj)

    if not prijava.zetona_se_ujemata(csrf, request.cookies.get(prijava.PISKOTEK_CSRF_PRIJAVE)):
        return _stran_prijave(predloge, request, cilj=varen, sporocilo=SPOROCILO_CSRF, koda=403)

    zdaj = datetime.now(UTC)
    zamik = prijava.koliko_cakati(repo, identifikator, zdaj)
    if zamik:
        await asyncio.sleep(zamik)

    # V nit in ne v zanko dogodkov: argon2 je namenoma počasen (~60 ms) in
    # sinhron. Na zanki bi vsak poskus prijave za toliko časa ustavil **vse**
    # ostale zahteve strežnika, tudi prenos slike s telefona.
    izid = await run_in_threadpool(
        prijava.preveri_prijavo,
        repo,
        identifikator,
        geslo,
        vrata=Vrata.ADMIN,
        ip=request.client.host if request.client else None,
        ko=datetime.now(UTC),
    )

    if izid.izid is not Izid.USPEH or izid.poverilnica is None:
        return _stran_prijave(predloge, request, cilj=varen, sporocilo=izid.sporocilo, koda=401)

    zeton = prijava.ustvari_sejo(
        repo,
        izid.poverilnica,
        ko=datetime.now(UTC),
        oznaka_naprave=request.headers.get("user-agent", "")[:200] or None,
    )
    odgovor = RedirectResponse(varen, status_code=303)
    _postavi_piskotek(odgovor, prijava.PISKOTEK_SEJE, zeton, PISKOTEK_SEKUND)
    odgovor.delete_cookie(prijava.PISKOTEK_CSRF_PRIJAVE, path="/")
    return odgovor


@router.post(prijava.POT_ODJAVE)
def odjavi(
    repo: Annotated[PrijavaRepository, Depends(daj_repozitorij_prijave)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
) -> Response:
    """Izbriše sejo te naprave. Seje na drugih napravah ostanejo."""
    repo.izbrisi_sejo(seja.session_id)
    odgovor = RedirectResponse(prijava.POT_PRIJAVE, status_code=303)
    odgovor.delete_cookie(prijava.PISKOTEK_SEJE, path="/")
    return odgovor


# --- Telefon (V3-R04) ------------------------------------------------------


@router.post(
    prijava.POT_PRIJAVE_TELEFONA,
    response_model=ZetonPrijave,
    responses={401: {"description": "Poverilnica ni prava"}},
    tags=["telefon"],
)
async def prijavi_telefon(
    request: Request,
    telo: PrijavaTelefona,
    repo: Annotated[PrijavaRepository, Depends(daj_repozitorij_prijave)],
) -> Response:
    """Preveri poverilnico otroka in vrne žeton za glavo `Authorization`.

    Isto zaporedje kot v brskalniku, brez koraka s CSRF: zamik pred preverbo
    gesla, ne po njej, in zgoščevanje v niti, ker je argon2 sinhronih ~60 ms
    in bi na zanki dogodkov ustavil vse ostale zahteve — tudi prenos slike.

    Zavrnitev je vedno `401`, tudi za starša (`ADR-036` D). Koda ne loči
    primerov; loči jih sporočilo, in to samo tam, kjer je bilo to zavestno
    dovoljeno.
    """
    zamik = prijava.koliko_cakati(repo, telo.identifier, datetime.now(UTC))
    if zamik:
        await asyncio.sleep(zamik)

    izid = await run_in_threadpool(
        prijava.preveri_prijavo,
        repo,
        telo.identifier,
        telo.password,
        vrata=Vrata.TELEFON,
        ip=request.client.host if request.client else None,
        ko=datetime.now(UTC),
    )

    if izid.izid is not Izid.USPEH or izid.poverilnica is None:
        return JSONResponse({"detail": izid.sporocilo}, status_code=401)

    zdaj = datetime.now(UTC)
    zeton = prijava.ustvari_sejo(
        repo,
        izid.poverilnica,
        ko=zdaj,
        oznaka_naprave=request.headers.get("user-agent", "")[:200] or None,
    )
    return JSONResponse(
        ZetonPrijave(
            token=zeton,
            user_id=izid.poverilnica.user_id,
            display_name=izid.poverilnica.display_name,
            expires_at=zdaj + prijava.TRAJANJE_SEJE,
        ).model_dump(mode="json")
    )


@router.post(prijava.POT_ODJAVE_TELEFONA, response_model=OdjavaOpravljena, tags=["telefon"])
def odjavi_telefon(
    repo: Annotated[PrijavaRepository, Depends(daj_repozitorij_prijave)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
) -> OdjavaOpravljena:
    """Izbriše sejo te naprave. Lokalnih slik na telefonu se ne dotakne.

    Pot **ni** izvzeta iz `ZetonMiddleware`: brez veljavnega žetona ni seje,
    ki bi jo bilo mogoče izbrisati. Telefon zato ob `401` svoj žeton preprosto
    zavrže — odjava je najprej lokalna (`ADR-036` G).
    """
    repo.izbrisi_sejo(seja.session_id)
    return OdjavaOpravljena()
