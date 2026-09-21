"""Skupna plomba operaterskih strani: izrisovalnik in tri strani z napako.

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

from app.settings import Settings


def daj_predloge(request: Request) -> Jinja2Templates:
    """Izrisovalnik predlog te aplikacije.

    Iz `app.state` in ne iz modulske globale, iz istega razloga kot vse ostalo
    v `app/dependencies.py`: vsak test dobi svojo, popolnoma ločeno aplikacijo.
    """
    predloge: Jinja2Templates = request.app.state.predloge
    return predloge


def kontekst_prijave(request: Request) -> dict[str, object]:
    """Kdo je prijavljen, kakšen CSRF žeton nosijo obrazci te strani in ali je
    v tej namestitvi na voljo Google.

    Vpisan je kot `context_processors` izrisovalnika (`app/main.py`), zato
    velja za **vsako** predlogo — glava z imenom družine in skrito polje v
    obrazcu tako ne potrebujeta dopolnila v 27 klicih `TemplateResponse`
    (`docs/odlocitve/ADR-035` D).

    Brez seje se vrne **samo** `prijava: None` in `google_na_voljo`, brez
    ključa `csrf`. Razlog je v Starlette: obdelovalci konteksta tečejo za
    klicateljem in njegove vrednosti prepišejo. Prazen `csrf` bi torej
    pobrisal žeton, ki ga prijavna stran poda sama — in prijavni obrazec bi
    ostal brez žetona, pri vsakem poskusu 403.

    `google_na_voljo` je tu in ne v posamezni poti prav zaradi iste pasti
    (V3-R08): vrednost potrebujeta glava (povezava na `/admin/racun`) in
    prijavna stran (gumb), in ključ, ki bi ga obdelovalec vračal *poleg* tega,
    kar poda pot, bi se s tisto vrednostjo boril. Zato je lastnik en sam.
    """
    nastavitve: Settings = request.app.state.nastavitve
    skupno: dict[str, object] = {"google_na_voljo": nastavitve.google_je_nastavljen}
    seja = getattr(request.state, "prijava", None)
    if seja is None:
        return {**skupno, "prijava": None}
    return {**skupno, "prijava": seja, "csrf": seja.csrf_token}


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


def zavrnjeno(predloge: Jinja2Templates, request: Request, sporocilo: str) -> Response:
    """403 kot stran (V3-R06).

    Ni 404: član je v tvoji družini in ga vidiš, zato skrivanje nima česa
    skriti — skriva se samo obstoj **tujih** članov, in to počne `ni_najdeno`.
    Ni 409: stanje je v redu, dejanje pa ni tvoje (deaktivacija sebe, lastnika
    sistema ali zadnjega starša). Razlika med „še ne gre" in „ti ne smeš" je
    edino, kar zavrnjenemu pove, ali naj poskusi drugače ali sploh ne.
    """
    return predloge.TemplateResponse(
        request,
        "najdena-ni.html",
        {"naslov": "Tega ne smeš", "sporocilo": sporocilo},
        status_code=403,
    )


def ni_izvedeno(predloge: Jinja2Templates, request: Request, sporocilo: str) -> Response:
    """403 za dejanje, ki ga nismo izvedli, ker mu ni bilo mogoče zaupati.

    Dvojček strani, ki jo ob manjkajočem CSRF žetonu izriše `SejaMiddleware`.
    Obstaja zato, ker ena pot žeton preverja **sama** (`docs/odlocitve/ADR-043`)
    in mora ob zavrnitvi izgledati enako kot vse ostale — različno besedilo za
    isto stvar bi bralcu povedalo, da se je zgodilo nekaj drugega.

    Ni `zavrnjeno`: tam gre za „ti tega ne smeš" (deaktivacija sebe,
    `V3-R06`), tu pa za „temu obrazcu ne zaupam".
    """
    return predloge.TemplateResponse(
        request,
        "najdena-ni.html",
        {"naslov": "Tega nisem izvedel", "sporocilo": sporocilo},
        status_code=403,
    )


def neveljavna_zahteva(predloge: Jinja2Templates, request: Request, sporocilo: str) -> Response:
    """400 kot stran, ne kot JSON.

    Ni 404: pot obstaja, narobe je vrednost v naslovu. In ni tih padec na
    privzetek, kot ga pri `?leto=` naredi statistika: pri pregledu po dnevih je
    datum celoten pomen strani, zato bi tiha zamenjava z današnjim dnem
    pomenila, da operater gleda današnje slike in misli, da gleda torkove
    (`docs/odlocitve/ADR-023`).
    """
    return predloge.TemplateResponse(
        request,
        "najdena-ni.html",
        {"naslov": "Tega naslova ne razumem", "sporocilo": sporocilo},
        status_code=400,
    )
