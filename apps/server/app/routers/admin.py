"""Operaterska stran: pregled prejetih slik in brisanje.

Stran je namenjena lastniku sistema, ne učenki (`docs/00-namen.md`, vloga
„spremlja delovanje"). Ključa ne zahteva — meja je Tailscale; glej
`docs/odlocitve/ADR-006` za to izbiro in njene posledice.

Prikaza rezultatov obdelave tu ni. Prompt, odgovor modela, prepis, vprašanja
in gumb „Pošlji v obdelavo" pridejo z V1-R03; ta zahteva pokaže samo tisto,
kar v bazi res obstaja.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.db import MaterialsRepository
from app.dependencies import daj_nastavitve, daj_repozitorij
from app.models import Material
from app.settings import Settings
from app.storage import je_znotraj, pobrisi_sliko, velikost_slike
from app.subjects import PREDMETI, oznaka_predmeta, oznaka_statusa, poisci_predmet

router = APIRouter(prefix="/admin")

#: Pot do predlog se izpelje iz mesta te datoteke, ne iz trenutne mape.
#:
#: Isti razlog kot pri `mypy.ini` in `env_file` v V1-R02: pot, relativna na
#: delovno mapo, bi pomenila, da se strežnik obnaša različno glede na to, od
#: kod je pognan (odločitev 2 v `docs/plan/V1-R04.md`).
PREDLOGE = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

#: Časovni pas, v katerem operater bere ure.
#:
#: V bazi je vse v UTC. Stran, ki bi kazala UTC, bi ob vsakem posnetku
#: zahtevala računanje na pamet — in prav ura posnetka je podatek, po katerem
#: operater sliko prepozna.
#:
#: Pas je zapisan imensko in ne kot odmik, ker se odmik dvakrat na leto
#: spremeni. Imenski pas zahteva bazo časovnih pasov: na Windows jo prinese
#: paket `tzdata` (v `pyproject.toml`), v Linux vsebniku pa je brez njega ni.
DOMACI_PAS = ZoneInfo("Europe/Ljubljana")


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
    lokalni = trenutek.astimezone(DOMACI_PAS)
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


def _pogled(material: Material) -> dict[str, Any]:
    """Zapis, pripravljen za predlogo.

    Predloga ne računa in ne oblikuje — dobi gotove nize. Tako je oblikovanje
    testljivo brez izrisa in predloga ostane brana kot postavitev.
    """
    pot = Path(material.image_path)
    velikost = velikost_slike(pot)
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


def _ni_najdeno(request: Request, sporocilo: str) -> Response:
    """404 kot stran, ne kot JSON.

    Globalnega prestreznika za `HTTPException` namenoma ni: ta bi spremenil
    tudi odgovore `POST /materials` iz JSON v HTML in podrl telefon
    (odločitev 7 v `docs/plan/V1-R04.md`).
    """
    return PREDLOGE.TemplateResponse(
        request, "najdena-ni.html", {"sporocilo": sporocilo}, status_code=404
    )


@router.get("")
def pregled(
    request: Request,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
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

    return PREDLOGE.TemplateResponse(
        request,
        "predmeti.html",
        {"predmeti": vrstice, "skupaj": sum(steviloma.values())},
    )


@router.get("/subjects/{koda}")
def predmet(
    request: Request,
    koda: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
) -> Response:
    """Slike enega predmeta, najnovejša prva."""
    snovi = repozitorij.seznam_po_predmetu(koda)

    # Neznana koda brez ene same slike je tipkarska napaka v naslovu, ne prazen
    # predmet. Koda, ki slike ima, je veljavna, tudi če ni na seznamu.
    if not snovi and poisci_predmet(koda) is None:
        return _ni_najdeno(request, f"Predmeta s kodo „{koda}“ ni ne na seznamu ne v bazi.")

    return PREDLOGE.TemplateResponse(
        request,
        "predmet.html",
        {
            "koda": koda,
            "oznaka": oznaka_predmeta(koda),
            "snovi": [_pogled(snov) for snov in snovi],
        },
    )


@router.get("/materials/{material_id}")
def snov(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
) -> Response:
    """Podrobnosti ene slike."""
    material = repozitorij.poisci(material_id)
    if material is None:
        return _ni_najdeno(request, "Zapisa s tem identifikatorjem na strežniku ni.")

    return PREDLOGE.TemplateResponse(request, "snov.html", {"snov": _pogled(material)})


@router.get("/materials/{material_id}/image")
def slika(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> Response:
    """Sama datoteka slike."""
    material = repozitorij.poisci(material_id)
    if material is None:
        return _ni_najdeno(request, "Zapisa s tem identifikatorjem na strežniku ni.")

    pot = Path(material.image_path)

    # Pot je zapisala naša koda in bi ji smeli zaupati. Ne zaupamo ji, ker je
    # cena preverbe ena vrstica, cena napačne predpostavke pa branje poljubne
    # datoteke s strežnika (odločitev 8 v `docs/plan/V1-R04.md`).
    if not je_znotraj(nastavitve.images_dir, pot) or not pot.is_file():
        return _ni_najdeno(request, "Slike tega zapisa na disku ni.")

    return FileResponse(pot, media_type="image/jpeg")


@router.get("/materials/{material_id}/delete")
def potrdi_brisanje(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
) -> Response:
    """Vmesni korak pred brisanjem. Sam ne spremeni ničesar."""
    material = repozitorij.poisci(material_id)
    if material is None:
        return _ni_najdeno(request, "Zapisa s tem identifikatorjem na strežniku ni.")

    return PREDLOGE.TemplateResponse(request, "brisanje.html", {"snov": _pogled(material)})


@router.post("/materials/{material_id}/delete")
def izbrisi(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
) -> Response:
    """Izbriše zapis in njegovo datoteko."""
    # Najprej vrstica, nato datoteka — obratno kot pri sprejemu, in namenoma.
    # Vrstica brez datoteke je pokvarjen vnos, ki ga operater vidi; datoteka
    # brez vrstice je nevidna sirota, ki stane samo prostor. Če odpove drugi
    # korak, hočemo drugo napako (odločitev 5 v `docs/plan/V1-R04.md`).
    material = repozitorij.pobrisi(material_id)
    if material is None:
        return _ni_najdeno(request, "Zapisa s tem identifikatorjem na strežniku ni.")

    pobrisi_sliko(Path(material.image_path))

    # 303 in ne 302: po `POST` mora brskalnik naslednjo zahtevo poslati kot
    # `GET`, sicer osvežitev strani ponovi brisanje.
    return RedirectResponse(f"/admin/subjects/{material.subject}", status_code=303)
