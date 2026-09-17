"""Prijava in odjava na operaterski strani (V3-R03).

Poti sta pod `/admin`, ker brskalnik glave `X-API-Key` ne zna poslati in bi ju
`ApiKeyMiddleware` sicer zavrnil (`app/security.py`). `GET/POST /admin/login`
sta edini izvzeti iz `SejaMiddleware` — vse ostalo pod `/admin` brez seje
konča tu.

Odjava je izvzeta **ni**: zahteva sejo in CSRF žeton kot vsak drug `POST`.
Odjava prek `GET` bi pomenila, da te lahko tuja stran s sliko odjavi.
"""

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response

from app import prijava
from app.db import PrijavaRepository, SejaUporabnika
from app.dependencies import daj_prijavo, daj_repozitorij_prijave
from app.prijava import Izid
from app.strani import daj_predloge

router = APIRouter(tags=["prijava"])

#: Koliko časa velja piškotek v brskalniku. Enako kot seja v bazi — krajši bi
#: pomenil, da se uporabnica odjavi sama od sebe, daljši pa piškotek, ki nima
#: več seje.
PISKOTEK_SEKUND = int(prijava.TRAJANJE_SEJE.total_seconds())

SPOROCILO_CSRF = (
    "Prijavni obrazec je potekel ali ni prišel s te strani. Osveži stran in "
    "poskusi znova."
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

    if not prijava.zetona_se_ujemata(
        csrf, request.cookies.get(prijava.PISKOTEK_CSRF_PRIJAVE)
    ):
        return _stran_prijave(
            predloge, request, cilj=varen, sporocilo=SPOROCILO_CSRF, koda=403
        )

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
        ip=request.client.host if request.client else None,
        ko=datetime.now(UTC),
    )

    if izid.izid is not Izid.USPEH or izid.poverilnica is None:
        return _stran_prijave(
            predloge, request, cilj=varen, sporocilo=izid.sporocilo, koda=401
        )

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
