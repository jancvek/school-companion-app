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
from typing import Annotated, Any, cast
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
from app.db import ClaniRepository, StatistikaRepository
from app.dependencies import daj_repozitorij_clanov, daj_repozitorij_statistike
from app.models import OCENE, Material, Ocena
from app.otroci import PARAMETER, IzbiraOtroka, izberi_otroka
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

#: Ime parametra za izbiro otroka; isto na obeh straneh in v `/admin/days`.
PARAMETER_OTROK = PARAMETER

#: Besedilo, kadar naslov imenuje otroka, ki ga v tej družini ni. Isto za
#: tujega in za neobstoječega (`docs/odlocitve/ADR-039` B).
SPOROCILO_NEZNAN_OTROK = "Tega otroka v tvoji družini ni."

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
    def vrednost(self) -> str:
        """Vrednost parametra `leto`, kot gre v naslov."""
        return VSE if self.leto is None else str(self.leto)


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


def poizvedba(okno: Okno, izbira: IzbiraOtroka, leto: str | None = None) -> str:
    """Naslovni parameter, ki ohrani **obe** izbiri hkrati.

    Brez otroka v povezavah bi menjava šolskega leta tiho vrnila privzetega
    otroka, in obratno — dve izbiri, od katerih vsaka pobriše drugo, sta
    najhitrejši način, da stran postane neuporabna pri dveh otrocih.

    Otrok se zapiše samo, kadar je izbirnik viden: pri enem otroku parameter
    ne pove ničesar in bi se pojavil v vsaki povezavi družine, ki ga ne
    potrebuje (`docs/odlocitve/ADR-039` B).
    """
    deli = [f"leto={leto if leto is not None else okno.vrednost}"]
    if izbira.je_izbirnik and izbira.izbrani is not None:
        deli.append(f"{PARAMETER_OTROK}={quote(izbira.izbrani.user_id, safe='')}")
    return "?" + "&".join(deli)


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


def _izbira_let(
    okno: Okno, tekoce: int, leta: list[int], izbira: IzbiraOtroka
) -> list[dict[str, Any]]:
    """Povezave za izbiro okna: vsa leta s poskusi, tekoče leto in „vse"."""
    moznosti = [
        {
            "oznaka": oznaka_solskega_leta(leto),
            "url": poizvedba(okno, izbira, str(leto)),
            "izbrano": okno.leto == leto,
        }
        for leto in sorted({*leta, tekoce}, reverse=True)
    ]
    moznosti.append(
        {
            "oznaka": "vse",
            "url": poizvedba(okno, izbira, VSE),
            "izbrano": okno.leto is None,
        }
    )
    return moznosti


def _izbira_otrok(okno: Okno, izbira: IzbiraOtroka) -> list[dict[str, Any]]:
    """Povezave za izbiro otroka; prazne, kadar se izbirnik ne izriše."""
    if not izbira.je_izbirnik:
        return []
    return [
        {
            "oznaka": kdo.display_name,
            "url": (
                f"?leto={okno.vrednost}"
                f"&{PARAMETER_OTROK}={quote(kdo.user_id, safe='')}"
            ),
            "izbrano": izbira.izbrani is not None and kdo.user_id == izbira.izbrani.user_id,
        }
        for kdo in izbira.vsi
    ]


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
    okno: Okno,
    tekoce: int,
    repozitorij: StatistikaRepository,
    razdeljeno: Razdeljeno,
    izbira: IzbiraOtroka,
) -> dict[str, Any]:
    """Kar imata obe strani: okno, izbiri, seštevek in opombe."""
    casi = (
        repozitorij.casi_poskusov(izbira.izbrani.user_id)
        if izbira.izbrani is not None
        else []
    )
    return {
        "okno": okno.opis,
        "neprebrano": okno.neprebrano,
        "leta": _izbira_let(okno, tekoce, solska_leta(casi), izbira),
        "otroci": _izbira_otrok(okno, izbira),
        "otrok_ime": izbira.izbrani.display_name if izbira.izbrani is not None else None,
        "brez_otroka": izbira.izbrani is None,
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
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    leto: str | None = None,
    otrok: str | None = None,
) -> Response:
    """Vsi predmeti z razporeditvijo ocen enega otroka v izbranem oknu.

    Vseh deset predmetov po urniku, tudi brez ocen, in za njimi kode iz
    podatkov, ki jih na seznamu ni — po vzorcu `/admin`: sicer bi se ocene
    predmeta s preimenovano kodo tiho izgubile iz pregleda.
    """
    izbira = izberi_otroka(clani.otroci(), otrok)
    if izbira is None:
        return ni_najdeno(predloge, request, SPOROCILO_NEZNAN_OTROK)

    tekoce = _tekoce()
    okno = preberi_okno(leto, tekoce)
    poskusi = (
        repozitorij.poskusi(izbira.izbrani.user_id, *okno.meje)
        if izbira.izbrani is not None
        else []
    )
    razdeljeno = razdeli(poskusi)
    predmeti = po_predmetih(razdeljeno.stejejo)

    def vrstica(koda: str, oznaka: str) -> dict[str, Any]:
        return {
            "koda": koda or "?",
            "oznaka": oznaka,
            # Vprašanje brez predmeta nima kam voditi.
            "url": (
                f"{PREDPONA}/subjects/{quote(koda, safe='')}{poizvedba(okno, izbira)}"
                if koda
                else None
            ),
            **_stevila(predmeti.get(koda, Razporeditev())),
        }

    vrstice = [vrstica(predmet.koda, predmet.oznaka) for predmet in PREDMETI]
    znane = {predmet.koda for predmet in PREDMETI}
    for koda in sorted(predmeti.keys() - znane):
        vrstice.append(vrstica(koda, "predmet ni na seznamu" if koda else "predmet ni znan"))

    return predloge.TemplateResponse(
        request,
        "statistika.html",
        {"predmeti": vrstice, **_skupno(okno, tekoce, repozitorij, razdeljeno, izbira)},
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
                # `cast` in ne nadomestna vrednost: `razdeli` je neprepoznane
                # ocene že izločil, zato je tu vedno ena od štirih.
                "oznaka": OZNAKE_OCEN[cast(Ocena, vnos.ocena)],
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
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    leto: str | None = None,
    otrok: str | None = None,
) -> Response:
    """En predmet, en otrok: seštevek, tabela po mesecih, snovi in vprašanja.

    Koda, ki je na seznamu desetih, ima stran vedno, tudi brez ocen. Koda, ki
    je ni, jo ima samo, če ima kakšen poskus v kateremkoli oknu — sicer bi
    bila stran za poljubno vtipkano kodo 200.

    Stalno število poizvedb ne glede na dolžino: poskusi, snovi, časi za izbiro
    let (in pri neznani kodi še preverba poskusov).
    """
    izbira = izberi_otroka(clani.otroci(), otrok)
    if izbira is None:
        return ni_najdeno(predloge, request, SPOROCILO_NEZNAN_OTROK)

    # Obstoj strani je vezan na **izbranega otroka**: koda zunaj seznama
    # desetih ima stran samo, kadar ima ta otrok pri njej kakšno oceno. Sicer
    # bi menjava otroka pustila odprto stran predmeta, ki zanj ne obstaja.
    ima_poskuse = izbira.izbrani is not None and repozitorij.ima_poskuse(
        koda, izbira.izbrani.user_id
    )
    if poisci_predmet(koda) is None and not ima_poskuse:
        return ni_najdeno(predloge, request, "Predmeta s to kodo ni in nima nobene ocene.")

    tekoce = _tekoce()
    okno = preberi_okno(leto, tekoce)
    poskusi = (
        repozitorij.poskusi(izbira.izbrani.user_id, *okno.meje, subject=koda)
        if izbira.izbrani is not None
        else []
    )
    razdeljeno = razdeli(poskusi)

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
            "nazaj": f"{PREDPONA}{poizvedba(okno, izbira)}",
            "po_mesecih": okno.leto is not None,
            "casovnica": casovnica,
            "snovi": [_snov(snov, snovi) for snov in statistika_snovi],
            "veckrat": [_vprasanje(v, snovi) for v in veckrat],
            "veckrat_opis": stevilo_z_besedo(len(veckrat), VPRASANJA),
            "enkrat": [_vprasanje(v, snovi) for v in enkrat],
            "enkrat_opis": stevilo_z_besedo(len(enkrat), VPRASANJA),
            **_skupno(okno, tekoce, repozitorij, razdeljeno, izbira),
        },
    )
