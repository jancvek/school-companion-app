"""Pregled slik po obdobju in predmetih (V2-R07).

Ena pot za branje: `GET /admin/days`. Odgovarja na vprašanje „ali je Maša
snov poslikala in kaj je poslikala", ki ga obstoječi strani ne znata — stran
predmeta je en predmet čez vso zgodovino, vstop „Kaj smo se danes učili" pa je
vstop v sestavljalnik kviza in ne pregled (`docs/odlocitve/ADR-023`).

Ključa pot ne zahteva, kot vse pod `/admin` (`ADR-006`). Samo bere in ne
pokaže ničesar, česar ne pokažeta že `/admin/subjects/{koda}` in
`/admin/materials/{id}`.

Svoj usmerjevalnik in ne nova pot v `admin.py`: gre za svojo temo, `admin.py`
pa je že dolg. Uvoza med usmerjevalnikoma ni — povezava z domače strani je
statični `href` v predlogi, zato krožnega uvoza, ki je v V2-R01 rodil
`app/strani.py`, tu ni.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.besedilo import SLIKE, stevilo_z_besedo
from app.casi import cas, danes, datum_dneva, dnevi_od_do, ura, v_domacem
from app.db import MaterialsRepository
from app.dependencies import daj_nastavitve, daj_repozitorij
from app.models import Material
from app.settings import Settings
from app.storage import je_znotraj, velikost_slike
from app.strani import daj_predloge, neveljavna_zahteva
from app.subjects import PREDMETI, oznaka_predmeta

#: Predpona te strani. Pod `/admin`, torej brez ključa (`ADR-006`).
PREDPONA = "/admin/days"

router = APIRouter(prefix=PREDPONA)

#: Vrednosti parametra `obdobje`.
DAN = "dan"
TEDEN = "teden"

#: Koliko dni pokaže „Ta teden": današnji dan in šest pred njim.
#:
#: Sedem in ne osem — kriterij pravi, da je obseg navzgor omejen na en teden.
#: Sidro je **današnji** dan in ne izbrani (`ADR-023`).
DNI_V_TEDNU = 7

#: Meji sprejemljivega leta. Ne okras: `date(1, 1, 1)` je veljaven `date`, a
#: „pregled 1. januarja leta 1" ni vprašanje, ki bi ga kdo postavil — tipkarska
#: napaka pa je. Zgornja meja drži `timedelta` stran od `OverflowError`.
NAJMANJ_LETO = 2000
NAJVEC_LETO = 2100

#: Dolžina datuma v obliki `YYYY-MM-DD`.
_DOLZINA_DATUMA = 10


class NeveljavenVhod(Exception):
    """Vrednost iz naslova, ki je ni mogoče prebrati.

    Nosi slovensko sporočilo za operaterja. Izjema in ne vrnjena vrednost, ker
    branje parametrov ni ena preverba, ampak štiri, in vsaka od njih zaključi
    obravnavo — zaporedje `if ... return` bi pomen skrilo med veje.
    """

    def __init__(self, sporocilo: str) -> None:
        super().__init__(sporocilo)
        self.sporocilo = sporocilo


@dataclass(frozen=True)
class Obdobje:
    """Prebrano obdobje: prvi in **vključno** zadnji koledarski dan."""

    prvi: date
    zadnji: date

    #: Ali je bil izbran teden. Predloga po tem označi aktivni gumb.
    je_teden: bool

    @property
    def dnevi(self) -> list[date]:
        """Vsi dnevi obdobja, najnovejši prvi.

        Vsi in ne le tisti s slikami: prav prazen dan je odgovor na vprašanje,
        ali je Maša tisti dan poslikala (`ADR-023`).
        """
        koliko = (self.zadnji - self.prvi).days
        return [self.zadnji - timedelta(days=zamik) for zamik in range(koliko + 1)]

    @property
    def opis(self) -> str:
        """Obdobje za prikaz v podnaslovu."""
        if self.prvi == self.zadnji:
            return datum_dneva(self.prvi)
        return f"od {datum_dneva(self.prvi)} do {datum_dneva(self.zadnji)}"


def preberi_datum(vrednost: str) -> date:
    """Dan iz parametra `dan`. Samo oblika `YYYY-MM-DD`.

    Preverba dolžine je pred `fromisoformat`, ker ta od Pythona 3.11 sprejme
    tudi `20260912` in cele časovne žige — stran pa naslov, ki ga sama nikoli
    ne sestavi, raje zavrne kot tiho razume po svoje.
    """
    if len(vrednost) != _DOLZINA_DATUMA or vrednost[4] != "-" or vrednost[7] != "-":
        raise NeveljavenVhod(
            f"Datuma „{vrednost}“ ne razumem. Pričakovana oblika je 2026-09-12."
        )

    try:
        dan = date.fromisoformat(vrednost)
    except ValueError:
        raise NeveljavenVhod(
            f"Datuma „{vrednost}“ ni v koledarju. Pričakovana oblika je 2026-09-12."
        ) from None

    if not NAJMANJ_LETO <= dan.year <= NAJVEC_LETO:
        raise NeveljavenVhod(
            f"Leto mora biti med {NAJMANJ_LETO} in {NAJVEC_LETO}, pri tebi pa je {dan.year}."
        )

    return dan


def preberi_obdobje(dan: str | None, obdobje: str | None, zdaj: date) -> Obdobje:
    """Obdobje iz parametrov naslova; brez njiju je to današnji dan.

    Parametra se bereta kot **niz** in nikoli kot `date` ali `int`: FastAPI bi
    ob nerazberljivi vrednosti vrnil surov angleški 422 pod predpono, kjer je
    vse ostalo slovensko (isti razlog kot pri `?leto=` na statistiki). Razlika
    je, kaj se zgodi potem — tu 400 in ne padec na privzetek (`ADR-023`).
    """
    izbrano = (obdobje or DAN).strip()
    if izbrano not in (DAN, TEDEN):
        raise NeveljavenVhod(
            f"Obdobja „{izbrano}“ ne poznam. Izbrati je mogoče dan ali teden."
        )

    if izbrano == TEDEN:
        # Datum ni tiho prezrt: parameter, ki na obseg ne vpliva, ne sme
        # izgledati, kot da nanj vpliva. Iz vmesnika ta kombinacija ne nastane.
        if dan:
            raise NeveljavenVhod(
                "Teden se vedno konča z današnjim dnem, zato ga s poljubnim dnevom "
                "ni mogoče združiti. Odstrani „dan“ iz naslova ali izberi en dan."
            )
        return Obdobje(prvi=zdaj - timedelta(days=DNI_V_TEDNU - 1), zadnji=zdaj, je_teden=True)

    izbrani_dan = preberi_datum(dan) if dan else zdaj
    return Obdobje(prvi=izbrani_dan, zadnji=izbrani_dan, je_teden=False)


def _pogled_slike(material: Material, images_dir: Path) -> dict[str, Any]:
    """Ena sličica: samo ura posnetka in ali datoteka obstaja.

    Stanje obdelave in berljivost tu **nista** — vidna sta na strani
    podrobnosti, kamor sličica pelje. Za datoteko izven `images_dir` velja isto
    kot za manjkajočo, kot v `admin._pogled`: sicer bi predloga narisala `<img>`,
    pot `/image` pa bi ga zavrnila.
    """
    pot = Path(material.image_path)
    ima_sliko = je_znotraj(images_dir, pot) and velikost_slike(pot) is not None
    return {"id": material.id, "ura": ura(material.taken_at), "ima_sliko": ima_sliko}


def razvrsti_po_dnevih(
    dnevi: list[date], snovi: list[Material], images_dir: Path
) -> list[dict[str, Any]]:
    """Slike, razvrščene po dnevu in znotraj dneva po predmetu.

    Čista funkcija: brez seje, brez zahteve, testljiva brez izrisa. Grupiranje
    je v Pythonu in ne v SQL, ker izraz za lokalni koledarski dan v SQL ni
    prenosljiv med SQLite (testi) in Postgresom (produkcija).

    Trije vrstni redi, vsak iz svojega razloga:

    - dnevi padajoče, kot jih poda `Obdobje.dnevi`;
    - predmeti po vrstnem redu `PREDMETI` (urnik) in ne po abecedi, nato
      neznane kode po abecedi — te se **nikoli** ne izpustijo (odločitev 3 v
      `docs/plan/V1-R04.md`);
    - slike naraščajoče po `taken_at`, kar je že vrstni red vhoda
      (`seznam_po_obdobju`), ker so zaporedni posnetki strani iste snovi
      (`docs/odlocitve/ADR-003`).

    Predmet brez slik tistega dne se ne izpiše; dan brez slik se izpiše prazen.
    """
    po_dnevih: dict[date, dict[str, list[Material]]] = {dan: {} for dan in dnevi}
    for snov in snovi:
        # Dan se izračuna iz **lokalnega** časa posnetka. Meja je zato lokalna
        # polnoč, kot zahteva `ADR-016` (B).
        dan = v_domacem(snov.taken_at).date()
        if dan in po_dnevih:
            po_dnevih[dan].setdefault(snov.subject, []).append(snov)

    znane = [predmet.koda for predmet in PREDMETI]

    izpis: list[dict[str, Any]] = []
    for dan in dnevi:
        skupine = po_dnevih[dan]
        neznane = sorted(koda for koda in skupine if koda not in znane)
        vrstni_red = [koda for koda in znane if koda in skupine] + neznane

        predmeti = [
            {
                "koda": koda,
                "oznaka": oznaka_predmeta(koda),
                "koliko_opis": stevilo_z_besedo(len(skupine[koda]), SLIKE),
                "slike": [_pogled_slike(snov, images_dir) for snov in skupine[koda]],
            }
            for koda in vrstni_red
        ]
        koliko = sum(len(skupine[koda]) for koda in vrstni_red)
        izpis.append(
            {
                "datum": datum_dneva(dan),
                "iso": dan.isoformat(),
                "koliko_opis": stevilo_z_besedo(koliko, SLIKE),
                "predmeti": predmeti,
            }
        )

    return izpis


@router.get("")
def pregled_po_dnevih(
    request: Request,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    dan: str | None = None,
    obdobje: str | None = None,
) -> Response:
    """Slike izbranega dne ali tedna, grupirane po dnevu in predmetu."""
    zdaj = danes()
    try:
        izbrano = preberi_obdobje(dan, obdobje, zdaj)
    except NeveljavenVhod as neveljaven:
        return neveljavna_zahteva(predloge, request, neveljaven.sporocilo)

    od, do = dnevi_od_do(izbrano.prvi, izbrano.zadnji)
    snovi = repozitorij.seznam_po_obdobju(od, do)
    prejeto = repozitorij.nazadnje_prejeto()

    return predloge.TemplateResponse(
        request,
        "dnevi.html",
        {
            "obdobje_opis": izbrano.opis,
            "je_teden": izbrano.je_teden,
            "dni_v_tednu": DNI_V_TEDNU,
            "skupaj_opis": stevilo_z_besedo(len(snovi), SLIKE),
            # Gotov niz in ne trenutek: predloga ne računa in ne oblikuje.
            # `None` pomeni, da strežnik ni prejel še nobene slike — to ni
            # ničla in ne prazen niz, ampak svoje besedilo.
            "prejeto_opis": cas(prejeto) if prejeto is not None else None,
            # Vrednost za `<input type="date">`; ta pozna samo obliko ISO.
            "izbrani_dan": izbrano.zadnji.isoformat(),
            "vceraj": (zdaj - timedelta(days=1)).isoformat(),
            "dnevi": razvrsti_po_dnevih(izbrano.dnevi, snovi, nastavitve.images_dir),
        },
    )
