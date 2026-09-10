"""Skupna plomba operaterskih strani: izrisovalnik in dve strani z napako.

Do V2-R01 je vse to živelo v `app/routers/admin.py`. Ko je isto potreboval še
usmerjevalnik kvizov, je bila izbira med krožnim uvozom in svojim modulom —
`kvizi` bi uvažal `daj_predloge` iz `admin`, `admin` pa seznam kvizov iz
`kvizi`. Krog bi pri uvozu padel.

Isti razlog kot pri `app/casi.py`: kar potrebujeta oba usmerjevalnika, ni last
nobenega od njiju. Imena so zato javna in brez podčrtaja.
"""

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response


def daj_predloge(request: Request) -> Jinja2Templates:
    """Izrisovalnik predlog te aplikacije.

    Iz `app.state` in ne iz modulske globale, iz istega razloga kot vse ostalo
    v `app/dependencies.py`: vsak test dobi svojo, popolnoma ločeno aplikacijo.
    """
    predloge: Jinja2Templates = request.app.state.predloge
    return predloge


def ni_najdeno(predloge: Jinja2Templates, request: Request, sporocilo: str) -> Response:
    """404 kot stran, ne kot JSON.

    Globalnega prestreznika za `HTTPException` namenoma ni: ta bi spremenil
    tudi odgovore `POST /materials` iz JSON v HTML in podrl telefon
    (odločitev 7 v `docs/plan/V1-R04.md`).
    """
    return predloge.TemplateResponse(
        request, "najdena-ni.html", {"sporocilo": sporocilo}, status_code=404
    )


def ni_dovoljeno(predloge: Jinja2Templates, request: Request, sporocilo: str) -> Response:
    """409 kot stran, ne kot JSON.

    Ni 404: zapis obstaja in operater ga vidi. Ni tiha preusmeritev: klik, ki
    ne naredi ničesar in tega ne pove, je slabši od zavrnitve.
    """
    return predloge.TemplateResponse(
        request,
        "najdena-ni.html",
        {"naslov": "Tega še ne gre", "sporocilo": sporocilo},
        status_code=409,
    )
