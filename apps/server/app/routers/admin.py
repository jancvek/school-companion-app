"""Operaterska stran: pregled prejetih slik in brisanje.

Stran je namenjena lastniku sistema, ne učenki (`docs/00-namen.md`, vloga
„spremlja delovanje"). Ključa ne zahteva — meja je Tailscale; glej
`docs/odlocitve/ADR-006` za to izbiro in njene posledice.

Prikaza rezultatov obdelave tu ni. Prompt, odgovor modela, prepis, vprašanja
in gumb „Pošlji v obdelavo" pridejo z V1-R03; ta zahteva pokaže samo tisto,
kar v bazi res obstaja.
"""

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.db import MaterialsRepository
from app.dependencies import daj_nastavitve, daj_repozitorij
from app.models import Material
from app.settings import Settings
from app.storage import je_znotraj, pobrisi_sliko, velikost_slike
from app.subjects import PREDMETI, oznaka_predmeta, oznaka_statusa, poisci_predmet

#: Predpona vseh poti operaterske strani.
PREDPONA = "/admin"

router = APIRouter(prefix=PREDPONA)

#: Mapa s predlogami. Izpelje se iz mesta te datoteke, ne iz trenutne mape.
#:
#: Isti razlog kot pri `mypy.ini` in `env_file` v V1-R02: pot, relativna na
#: delovno mapo, bi pomenila, da se strežnik obnaša različno glede na to, od
#: kod je pognan (odločitev 2 v `docs/plan/V1-R04.md`).
MAPA_PREDLOG = Path(__file__).resolve().parent.parent / "templates"

#: Ime časovnega pasu, v katerem operater bere ure.
#:
#: V bazi je vse v UTC. Stran, ki bi kazala UTC, bi ob vsakem posnetku
#: zahtevala računanje na pamet — in prav ura posnetka je podatek, po katerem
#: operater sliko prepozna.
#:
#: Pas je imenski in ne odmik, ker se odmik dvakrat na leto spremeni. Bazo
#: pasov prinese sistem: v vsebniku `python:3.12-slim` je v `/usr/share/
#: zoneinfo`, na Windows pa paket `tzdata`, ki ga zahteva že `psycopg`.
#: Zato tu ni nove odvisnosti.
DOMACI_PAS = "Europe/Ljubljana"


@lru_cache(maxsize=1)
def _pas() -> ZoneInfo:
    """Časovni pas, poiskan ob prvi uporabi in nato zapomnjen.

    Namenoma **ni** modulska konstanta: `ZoneInfo` brez baze pasov vrže
    izjemo, in ta bi ob uvozu modula podrla celo aplikacijo — tudi
    `GET /health` in `POST /materials`. Udobje pri prikazu ure ne sme biti
    pogoj za življenje strežnika.
    """
    return ZoneInfo(DOMACI_PAS)


def daj_predloge(request: Request) -> Jinja2Templates:
    """Izrisovalnik predlog te aplikacije.

    Iz `app.state` in ne iz modulske globale, iz istega razloga kot vse
    ostalo v `app/dependencies.py`: vsak test dobi svojo, popolnoma ločeno
    aplikacijo (odločitev iz plana, „`Jinja2Templates` v `app.state`").
    """
    predloge: Jinja2Templates = request.app.state.predloge
    return predloge


def _cas(trenutek: datetime) -> str:
    """Trenutek iz baze v berljiv lokalni zapis.

    Oblika je sestavljena ročno in ne s `strftime`: oznaki `%-d` in `%-m` (dan
    in mesec brez vodilne ničle) na Windows ne obstajata, testi pa tečejo tam.

    Čas brez podatka o pasu razumemo kot UTC. To ni teoretični robni primer:
    Postgres v stolpcu `TIMESTAMPTZ` pas vrne, **SQLite pa ne** — vrne naiven
    `datetime`. Brez te vrstice bi `astimezone` naiven čas razumel kot čas
    strežnikovega pasu in ura bi bila v testih drugačna kot v produkciji.
    Vsebinsko isto počne `v_utc` ob sprejemu, a iz drugega razloga: tam gre za
    normalizacijo vnosa od zunaj, tu za razliko med gonilnikoma.
    """
    if trenutek.tzinfo is None:
        trenutek = trenutek.replace(tzinfo=UTC)
    lokalni = trenutek.astimezone(_pas())
    return f"{lokalni.day}. {lokalni.month}. {lokalni.year} ob {lokalni:%H:%M}"


def _velikost_opis(bajti: int | None) -> str:
    """Velikost datoteke v berljivi obliki."""
    if bajti is None:
        return "datoteke na disku ni"
    if bajti < 1024:
        return f"{bajti} B"
    if bajti < 1024 * 1024:
        return f"{bajti / 1024:.0f} kB"
    return f"{bajti / (1024 * 1024):.1f} MB"


def _pogled(material: Material, images_dir: Path) -> dict[str, Any]:
    """Zapis, pripravljen za predlogo.

    Predloga ne računa in ne oblikuje — dobi gotove nize. Tako je oblikovanje
    testljivo brez izrisa in predloga ostane brana kot postavitev.

    Za datoteko izven `images_dir` velja isto kot za manjkajočo. Sicer bi
    predloga narisala `<img>`, pot `/image` pa bi ga zavrnila — stran bi
    kazala pokvarjeno sliko namesto povedati, kaj je narobe.
    """
    pot = Path(material.image_path)
    velikost = velikost_slike(pot) if je_znotraj(images_dir, pot) else None
    return {
        "id": material.id,
        "koda": material.subject,
        "oznaka": oznaka_predmeta(material.subject),
        "cas": _cas(material.taken_at),
        "prejeto": _cas(material.received_at),
        "stanje": oznaka_statusa(material.status),
        "pot": material.image_path,
        "velikost": velikost,
        "velikost_opis": _velikost_opis(velikost),
    }


def _ni_najdeno(predloge: Jinja2Templates, request: Request, sporocilo: str) -> Response:
    """404 kot stran, ne kot JSON.

    Globalnega prestreznika za `HTTPException` namenoma ni: ta bi spremenil
    tudi odgovore `POST /materials` iz JSON v HTML in podrl telefon
    (odločitev 7 v `docs/plan/V1-R04.md`).
    """
    return predloge.TemplateResponse(
        request, "najdena-ni.html", {"sporocilo": sporocilo}, status_code=404
    )


@router.get("")
def pregled(
    request: Request,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
) -> Response:
    """Vsi predmeti s številom slik."""
    steviloma = repozitorij.stej_po_predmetih()

    vrstice = [
        {"koda": predmet.koda, "oznaka": predmet.oznaka, "koliko": steviloma.get(predmet.koda, 0)}
        for predmet in PREDMETI
    ]

    # Predmet, ki je v bazi, a ga na seznamu desetih ni, se pokaže pod svojo
    # kodo. Sicer bi se ob preimenovanju kode na telefonu slike tiho izgubile
    # iz pregleda — odločitev 3 v `docs/plan/V1-R04.md`.
    znane = {predmet.koda for predmet in PREDMETI}
    for koda in sorted(steviloma.keys() - znane):
        vrstice.append({"koda": koda, "oznaka": "predmet ni na seznamu", "koliko": steviloma[koda]})

    return predloge.TemplateResponse(
        request,
        "predmeti.html",
        {"predmeti": vrstice, "skupaj": sum(steviloma.values())},
    )


@router.get("/subjects/{koda:path}")
def predmet(
    request: Request,
    koda: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> Response:
    """Slike enega predmeta, najnovejša prva."""
    # Pretvornik `:path` požre tudi končno poševnico, zato `MAT/` ne bi bil
    # `MAT`. Starlette bi to sicer preusmeril sam, a pri `:path` pot obstaja
    # in preusmeritve ni. Koda predmeta se na poševnico nikoli ne konča.
    koda = koda.rstrip("/")
    snovi = repozitorij.seznam_po_predmetu(koda)

    # Neznana koda brez ene same slike je tipkarska napaka v naslovu, ne prazen
    # predmet. Koda, ki slike ima, je veljavna, tudi če ni na seznamu.
    if not snovi and poisci_predmet(koda) is None:
        return _ni_najdeno(
            predloge, request, f"Predmeta s kodo „{koda}“ ni ne na seznamu ne v bazi."
        )

    return predloge.TemplateResponse(
        request,
        "predmet.html",
        {
            "koda": koda,
            "oznaka": oznaka_predmeta(koda),
            "snovi": [_pogled(snov, nastavitve.images_dir) for snov in snovi],
        },
    )


@router.get("/materials/{material_id}")
def snov(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> Response:
    """Podrobnosti ene slike."""
    material = repozitorij.poisci(material_id)
    if material is None:
        return _ni_najdeno(predloge, request, "Zapisa s tem identifikatorjem na strežniku ni.")

    return predloge.TemplateResponse(
        request, "snov.html", {"snov": _pogled(material, nastavitve.images_dir)}
    )


@router.get("/materials/{material_id}/image")
def slika(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> Response:
    """Sama datoteka slike."""
    material = repozitorij.poisci(material_id)
    if material is None:
        return _ni_najdeno(predloge, request, "Zapisa s tem identifikatorjem na strežniku ni.")

    pot = Path(material.image_path)

    # Pot je zapisala naša koda in bi ji smeli zaupati. Ne zaupamo ji, ker je
    # cena preverbe ena vrstica, cena napačne predpostavke pa branje poljubne
    # datoteke s strežnika (odločitev 8 v `docs/plan/V1-R04.md`).
    if not je_znotraj(nastavitve.images_dir, pot) or not pot.is_file():
        return _ni_najdeno(predloge, request, "Slike tega zapisa na disku ni.")

    return FileResponse(pot, media_type="image/jpeg")


@router.get("/materials/{material_id}/delete")
def potrdi_brisanje(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> Response:
    """Vmesni korak pred brisanjem. Sam ne spremeni ničesar."""
    material = repozitorij.poisci(material_id)
    if material is None:
        return _ni_najdeno(predloge, request, "Zapisa s tem identifikatorjem na strežniku ni.")

    return predloge.TemplateResponse(
        request, "brisanje.html", {"snov": _pogled(material, nastavitve.images_dir)}
    )


@router.post("/materials/{material_id}/delete")
def izbrisi(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
) -> Response:
    """Izbriše zapis in njegovo datoteko."""
    # Najprej vrstica, nato datoteka — obratno kot pri sprejemu, in namenoma.
    # Vrstica brez datoteke je pokvarjen vnos, ki ga operater vidi; datoteka
    # brez vrstice je nevidna sirota, ki stane samo prostor. Če odpove drugi
    # korak, hočemo drugo napako (odločitev 5 v `docs/plan/V1-R04.md`).
    material = repozitorij.pobrisi(material_id)
    if material is None:
        return _ni_najdeno(predloge, request, "Zapisa s tem identifikatorjem na strežniku ni.")

    pobrisi_sliko(Path(material.image_path))

    # 303 in ne 302: po `POST` mora brskalnik naslednjo zahtevo poslati kot
    # `GET`, sicer osvežitev strani ponovi brisanje.
    return RedirectResponse(f"/admin/subjects/{material.subject}", status_code=303)



def je_admin_pot(pot: str) -> bool:
    """Ali zahtevek pripada operaterski strani.

    Isto ujemanje kot pri izvzetju iz preverbe ključa: `/admin` in
    `/admin/...`, nikoli `/administration`.
    """
    return pot == PREDPONA or pot.startswith(f"{PREDPONA}/")


async def prestrezi_napako(request: Request, izjema: Exception) -> Response:
    """Napake pod `/admin` izriše kot stran, drugod pusti JSON.

    Prvi poskus je bil pot `/{ostanek:path}` na koncu usmerjevalnika. Bila je
    napačna: prekrila je Starlettejevo preusmeritev ob končni poševnici, zato
    je `GET /admin/` — naslov, ki ga brskalnik ponudi sam — vrnil 404 s
    trditvijo, da strani ni. Prestreznik se sproži šele, ko poti res ni, in se
    preusmeritve ne dotakne. Pokrije tudi 405, ki ga lovilec ni.

    Prestreznik je globalen, ker drugačnega FastAPI ne pozna, a se za vse
    izven `/admin` umakne privzetemu — odgovori `POST /materials` morajo
    ostati JSON, sicer telefon dobi HTML tam, kjer pričakuje sporočilo o
    napaki (odločitev 7 v `docs/plan/V1-R04.md`).
    """
    if isinstance(izjema, StarletteHTTPException) and je_admin_pot(request.url.path):
        sporocilo = (
            "Te strani na strežniku ni."
            if izjema.status_code == 404
            else "Ta stran tega dejanja ne podpira."
        )
        predloge: Jinja2Templates = request.app.state.predloge
        return predloge.TemplateResponse(
            request, "najdena-ni.html", {"sporocilo": sporocilo}, status_code=izjema.status_code
        )

    return await http_exception_handler(request, izjema)  # type: ignore[arg-type]
