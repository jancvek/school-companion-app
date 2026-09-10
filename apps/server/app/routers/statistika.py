"""Statistika čez kvize na operaterski strani (V2-R04).

Dve strani: pregled po predmetih in stran predmeta s tabelo po mesecih,
seznamom snovi in seznamom vprašanj. Snov svoje strani nima — vrstica snovi
na strani predmeta vodi na obstoječo stran snovi (`docs/plan/V2-R04.md`,
odločitev 1).

Pravila štetja so v `app/statistika.py` in v `docs/odlocitve/ADR-021`. Ta
modul jih samo pokliče in oblikuje: predloga ne računa in ne sklanja.

Poti so pod `/admin` in ključa ne zahtevajo (`ADR-006`). **To je ves pomen
kriterija „vidna samo lastniku"** (`ADR-021` F): statistike ni v aplikaciji in
nobena pot s ključem je ne vrača.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.besedilo import POSKUSI, VPRASANJA, stevilo_z_besedo
from app.casi import (
    cas,
    datum,
    oznaka_meseca,
    oznaka_solskega_leta,
    solsko_leto,
    solsko_leto_od_do,
)
from app.db import StatistikaRepository
from app.dependencies import daj_repozitorij_statistike
from app.models import OCENE, Material
from app.statistika import (
    Razdeljeno,
    Razporeditev,
    StatistikaSnovi,
    StatistikaVprasanja,
    odstotek,
    po_letih,
    po_mesecih,
    po_predmetih,
    po_snoveh,
    po_vprasanjih,
    razdeli,
    razvrsti,
    sestej,
    solska_leta,
)
from app.strani import daj_predloge, ni_najdeno
from app.subjects import OZNAKE_OCEN, PREDMETI, oznaka_predmeta, poisci_predmet

#: Predpona poti statistike. Pod `/admin`, torej brez ključa (`ADR-006`).
PREDPONA = "/admin/statistics"

router = APIRouter(prefix=PREDPONA)

#: Vrednost parametra `leto` za okno čez vsa šolska leta.
VSE = "vse"

#: Meji sprejemljivega leta. Ne okras: `datetime(10000, …)` vrže izjemo, in
#: ročno vtipkan `?leto=99999` bi bil sicer 500 namesto privzetka.
NAJMANJ_LETO = 2000
NAJVEC_LETO = 2100


@dataclass(frozen=True)
class Okno:
    """Izbrano časovno okno: šolsko leto ali `None` za vsa leta."""

    leto: int | None

    #: Vrednost parametra, ki je ni bilo mogoče prebrati — stran jo omeni.
    neprebrano: str | None = None

    @property
    def meje(self) -> tuple[datetime | None, datetime | None]:
        if self.leto is None:
            return None, None
        return solsko_leto_od_do(self.leto)

    @property
    def opis(self) -> str:
        if self.leto is None:
            return "Vsa šolska leta"
        return f"Šolsko leto {oznaka_solskega_leta(self.leto)}"

    @property
    def poizvedba(self) -> str:
        """Parameter za povezave, ki morajo okno ohraniti."""
        return f"?leto={VSE if self.leto is None else self.leto}"


def preberi_okno(vrednost: str | None, tekoce: int) -> Okno:
    """Okno iz parametra `leto`. Bere se kot **niz**, nikoli kot `int`.

    `int` bi ob nerazberljivi vrednosti dal surov angleški 422 pod predpono,
    kjer je vse ostalo slovensko — isti razlog kot `_prebrano_stevilo` v
    sestavljalniku kvizov. Nerazberljiva vrednost pade na tekoče šolsko leto
    in stran to pove.
    """
    if vrednost is None or vrednost == "":
        return Okno(tekoce)
    if vrednost == VSE:
        return Okno(None)
    if vrednost.isascii() and vrednost.isdigit() and NAJMANJ_LETO <= int(vrednost) <= NAJVEC_LETO:
        return Okno(int(vrednost))
    return Okno(tekoce, neprebrano=vrednost)


def _odstotek_opis(vrednost: int | None) -> str:
    return "—" if vrednost is None else f"{vrednost} %"


def _stevila(razporeditev: Razporeditev) -> dict[str, Any]:
    """Razporeditev, pripravljena za predlogo: števila, pas in deleža."""
    poskusov = razporeditev.poskusov
    return {
        "poskusov": poskusov,
        "poskusov_opis": stevilo_z_besedo(poskusov, POSKUSI),
        "ocene": [
            {
                "oznaka": OZNAKE_OCEN[ocena],
                "koliko": razporeditev.po_oceni[ocena],
                # Širina dela pasu v odstotkih. Zaokrožena, zato se deli lahko
                # seštejejo v 99 ali 101 — pas je slika, števila so podatek.
                "sirina": odstotek(razporeditev.po_oceni[ocena], poskusov) or 0,
            }
            for ocena in OCENE
        ],
        "pravilnih": _odstotek_opis(odstotek(razporeditev.pravilnih, poskusov)),
        "tezkih": _odstotek_opis(odstotek(razporeditev.tezkih, poskusov)),
    }


def _izbira_let(okno: Okno, tekoce: int, leta: list[int]) -> list[dict[str, Any]]:
    """Povezave za izbiro okna: vsa leta s poskusi, tekoče leto in „vse"."""
    moznosti = [
        {
            "oznaka": oznaka_solskega_leta(leto),
            "url": f"?leto={leto}",
            "izbrano": okno.leto == leto,
        }
        for leto in sorted({*leta, tekoce}, reverse=True)
    ]
    moznosti.append({"oznaka": "vse", "url": f"?leto={VSE}", "izbrano": okno.leto is None})
    return moznosti


def _opombe(razdeljeno: Razdeljeno) -> list[str]:
    """Poskusi, ki ne morejo v razporeditev — a ne smejo izpasti molče."""
    opombe: list[str] = []
    if razdeljeno.brez_vprasanja:
        opombe.append(
            f"{stevilo_z_besedo(razdeljeno.brez_vprasanja, POSKUSI)} brez vprašanja — "
            "postavka kviza ne kaže na nobeno vprašanje, zato ni šteto po predmetih."
        )
    if razdeljeno.neprepoznanih:
        opombe.append(
            f"{stevilo_z_besedo(razdeljeno.neprepoznanih, POSKUSI)} z neprepoznano oceno — "
            "ni šteto v razporeditev."
        )
    return opombe


def _skupno(
    okno: Okno, tekoce: int, repozitorij: StatistikaRepository, razdeljeno: Razdeljeno
) -> dict[str, Any]:
    """Kar imata obe strani: okno, izbiro let, seštevek in opombe."""
    return {
        "okno": okno.opis,
        "neprebrano": okno.neprebrano,
        "leta": _izbira_let(okno, tekoce, solska_leta(repozitorij.casi_poskusov())),
        "skupaj": _stevila(sestej(razdeljeno.stejejo)),
        "opombe": _opombe(razdeljeno),
    }


def _tekoce() -> int:
    return solsko_leto(datetime.now(UTC))


@router.get("")
def pregled(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repozitorij: Annotated[StatistikaRepository, Depends(daj_repozitorij_statistike)],
    leto: str | None = None,
) -> Response:
    """Vsi predmeti z razporeditvijo ocen v izbranem oknu.

    Vseh deset predmetov po urniku, tudi brez ocen, in za njimi kode iz
    podatkov, ki jih na seznamu ni — po vzorcu `/admin`: sicer bi se ocene
    predmeta s preimenovano kodo tiho izgubile iz pregleda.
    """
    tekoce = _tekoce()
    okno = preberi_okno(leto, tekoce)
    razdeljeno = razdeli(repozitorij.poskusi(*okno.meje))
    predmeti = po_predmetih(razdeljeno.stejejo)

    def vrstica(koda: str, oznaka: str) -> dict[str, Any]:
        return {
            "koda": koda or "?",
            "oznaka": oznaka,
            # Vprašanje brez predmeta nima kam voditi.
            "url": f"{PREDPONA}/subjects/{quote(koda, safe='')}{okno.poizvedba}" if koda else None,
            **_stevila(predmeti.get(koda, Razporeditev())),
        }

    vrstice = [vrstica(predmet.koda, predmet.oznaka) for predmet in PREDMETI]
    znane = {predmet.koda for predmet in PREDMETI}
    for koda in sorted(predmeti.keys() - znane):
        vrstice.append(vrstica(koda, "predmet ni na seznamu" if koda else "predmet ni znan"))

    return predloge.TemplateResponse(
        request,
        "statistika.html",
        {"predmeti": vrstice, **_skupno(okno, tekoce, repozitorij, razdeljeno)},
    )


def _izvor(taken_at: datetime | None) -> str:
    """Snov na strani predmeta: predmet je znan, ostane čas posnetka."""
    return f"posnetek {cas(taken_at)}" if taken_at is not None else "čas posnetka ni znan"


def _oznake_snovi(material_id: str | None, snovi: dict[str, Material]) -> list[str]:
    """Arhiv in izbris. Snov, ki je v slovarju ni, je bila dokončno izbrisana."""
    snov = snovi.get(material_id) if material_id is not None else None
    if snov is None:
        return ["snov izbrisana"]
    if snov.archived_at is not None:
        return ["v arhivu"]
    return []


def _snov(statistika: StatistikaSnovi, snovi: dict[str, Material]) -> dict[str, Any]:
    obstaja = statistika.material_id is not None and statistika.material_id in snovi
    return {
        "id": statistika.material_id if obstaja else None,
        "izvor": _izvor(statistika.material_taken_at),
        "oznake": _oznake_snovi(statistika.material_id, snovi),
        "vprasanj_opis": stevilo_z_besedo(len(statistika.vprasanj), VPRASANJA),
        **_stevila(statistika.razporeditev),
    }


def _vprasanje(statistika: StatistikaVprasanja, snovi: dict[str, Material]) -> dict[str, Any]:
    obstaja = statistika.material_id is not None and statistika.material_id in snovi
    oznake = _oznake_snovi(statistika.material_id, snovi)
    if statistika.upokojeno:
        # Upokojeno vprašanje je iz starejše serije snovi (`ADR-021` D).
        oznake.insert(0, "upokojeno")
    return {
        "vprasanje": statistika.vprasanje,
        "odgovor": statistika.odgovor,
        "snov_id": statistika.material_id if obstaja else None,
        "izvor": _izvor(statistika.material_taken_at),
        "oznake": oznake,
        "zaporedje": [
            {
                "datum": datum(vnos.answered_at),
                "oznaka": OZNAKE_OCEN.get(vnos.ocena, vnos.ocena),  # type: ignore[call-overload]
                "quiz_id": vnos.quiz_id,
                "kviz_ime": vnos.kviz_ime,
                "preklican": vnos.kviz_preklican,
            }
            for vnos in statistika.zaporedje
        ],
        **_stevila(statistika.razporeditev),
    }


@router.get("/subjects/{koda:path}")
def predmet(
    request: Request,
    koda: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repozitorij: Annotated[StatistikaRepository, Depends(daj_repozitorij_statistike)],
    leto: str | None = None,
) -> Response:
    """En predmet: seštevek, tabela po mesecih, snovi in vprašanja.

    Koda, ki je na seznamu desetih, ima stran vedno, tudi brez ocen. Koda, ki
    je ni, jo ima samo, če ima kakšen poskus v kateremkoli oknu — sicer bi
    bila stran za poljubno vtipkano kodo 200.

    Stalno število poizvedb ne glede na dolžino: poskusi, snovi, časi za izbiro
    let (in pri neznani kodi še preverba poskusov).
    """
    if poisci_predmet(koda) is None and not repozitorij.ima_poskuse(koda):
        return ni_najdeno(predloge, request, "Predmeta s to kodo ni in nima nobene ocene.")

    tekoce = _tekoce()
    okno = preberi_okno(leto, tekoce)
    razdeljeno = razdeli(repozitorij.poskusi(*okno.meje, subject=koda))

    vprasanja = po_vprasanjih(razdeljeno.stejejo)
    veckrat, enkrat = razvrsti(vprasanja)
    statistika_snovi = po_snoveh(vprasanja)
    snovi = repozitorij.snovi(
        snov.material_id for snov in statistika_snovi if snov.material_id is not None
    )

    if okno.leto is not None:
        casovnica = [
            {"oznaka": oznaka_meseca(leto_meseca, st), **_stevila(razporeditev)}
            for (leto_meseca, st), razporeditev in po_mesecih(razdeljeno.stejejo, okno.leto)
        ]
    else:
        casovnica = [
            {"oznaka": oznaka_solskega_leta(solsko), **_stevila(razporeditev)}
            for solsko, razporeditev in po_letih(razdeljeno.stejejo)
        ]

    return predloge.TemplateResponse(
        request,
        "statistika-predmet.html",
        {
            "koda": koda,
            "oznaka": oznaka_predmeta(koda),
            "nazaj": f"{PREDPONA}{okno.poizvedba}",
            "po_mesecih": okno.leto is not None,
            "casovnica": casovnica,
            "snovi": [_snov(snov, snovi) for snov in statistika_snovi],
            "veckrat": [_vprasanje(v, snovi) for v in veckrat],
            "veckrat_opis": stevilo_z_besedo(len(veckrat), VPRASANJA),
            "enkrat": [_vprasanje(v, snovi) for v in enkrat],
            "enkrat_opis": stevilo_z_besedo(len(enkrat), VPRASANJA),
            **_skupno(okno, tekoce, repozitorij, razdeljeno),
        },
    )
