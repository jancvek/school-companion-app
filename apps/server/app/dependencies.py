"""Odvisnosti, ki jih endpointi dobijo od aplikacije.

Vse berejo iz `app.state`, ki ga napolni `create_app`. Tako ni globalnega
stanja na ravni modula in vsak test dobi svojo, popolnoma ločeno aplikacijo.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.db import (
    ClaniRepository,
    KviziRepository,
    MaterialsRepository,
    PrijavaRepository,
    ScheduleRepository,
    SejaUporabnika,
    StatistikaRepository,
)
from app.settings import Settings
from app.vision import KlicalecUrnika


def daj_nastavitve(request: Request) -> Settings:
    """Nastavitve te instance strežnika."""
    nastavitve: Settings = request.app.state.nastavitve
    return nastavitve


def daj_prijavo(request: Request) -> SejaUporabnika:
    """Seja, ki jo je za to zahtevo razrešila vmesna plast.

    Razreši jo `SejaMiddleware` pod `/admin` (brskalnik) ali `ZetonMiddleware`
    na poteh telefona; obe pišeta v isto mesto, ker je seja ista stvar z dvema
    prenosnikoma (`ADR-027`). Poti, ki ne gre skozi nobeno od njiju, seje ni —
    in to je napaka v kodi, ne stanje, ki bi ga smel povzročiti uporabnik,
    zato `RuntimeError` in ne HTTP odgovor.
    """
    seja: SejaUporabnika | None = getattr(request.state, "prijava", None)
    if seja is None:
        raise RuntimeError(
            "Ta pot je zunaj obeh plasti in seje nima. Odvisnost daj_prijavo "
            "sodi na poti pod /admin ali na poti telefona "
            "(docs/odlocitve/ADR-035 A, ADR-036 F)."
        )
    return seja


def daj_repozitorij_prijave(request: Request) -> Iterator[PrijavaRepository]:
    """Repozitorij uporabnikov, poverilnic in sej. Ena seja na zahtevo."""
    tovarna: sessionmaker[Session] = request.app.state.tovarna_sej
    with tovarna() as seja:
        yield PrijavaRepository(seja)


def daj_druzino(request: Request) -> str:
    """`id` družine, katere podatke bere in piše ta zahteva.

    Odloči seja — brskalnikova ali telefonova; vmesna plast jo je razrešila že
    pred usmerjevalnikom, zato tu ni nobene dodatne poizvedbe.

    Od `V3-R04` je to **edina** pot do družine. Začasna izbira „edina družina
    v bazi" (`daj_druzino_telefona`, `ADR-029` A) je odpadla skupaj z API
    ključem: družino zdaj pove žeton (`ADR-036` F). S tem druga družina v bazi
    ne ustavi več ničesar — kar je bil pogoj za `V3-R05`.
    """
    return daj_prijavo(request).family_id


def daj_otroka(request: Request) -> str:
    """`id` otroka, ki je prijavljen na tej poti telefona (`ADR-039`).

    Otroka na snovi in na poskusu pove **seja**, nikoli telo zahteve: podatek,
    ki ga pošlje odjemalec, bi bil trditev o tem, kdo je, in tako trditev je
    prijava že preverila.

    Velja samo na poteh telefona. Tam je vsak žeton otrokov — starš se v
    mobilno aplikacijo ne more prijaviti (`ADR-036` D), kar `prijava.Vrata`
    uveljavi ob vsaki uporabi seje. Prav zato `V3-R07` ne potrebuje posebnega
    primera „zapis brez otroka".
    """
    return daj_prijavo(request).user_id


def daj_repozitorij(
    request: Request, family_id: Annotated[str, Depends(daj_druzino)]
) -> Iterator[MaterialsRepository]:
    """Ena seja na zahtevo; zapre se tudi, če je zahteva padla."""
    tovarna: sessionmaker[Session] = request.app.state.tovarna_sej
    with tovarna() as seja:
        yield MaterialsRepository(seja, family_id)


def daj_repozitorij_kvizov(
    request: Request, family_id: Annotated[str, Depends(daj_druzino)]
) -> Iterator[KviziRepository]:
    """Kot `daj_repozitorij`, a za `quizzes` in `quiz_items` (V2-R01).

    Svoja seja in ne deljena z `MaterialsRepository`: strani, ki potrebujeta
    oboje (`/admin` in izbira predmeta), s tem odpreta dve **bralni** seji na
    zahtevo. To ni težava pravilnosti — pisanje teče izključno skozi ta
    repozitorij in je zato ena seja in ena transakcija.
    """
    tovarna: sessionmaker[Session] = request.app.state.tovarna_sej
    with tovarna() as seja:
        yield KviziRepository(seja, family_id)


def daj_repozitorij_clanov(
    request: Request, family_id: Annotated[str, Depends(daj_druzino)]
) -> Iterator[ClaniRepository]:
    """Kot `daj_repozitorij`, a za osebe, poverilnice in seje družine (V3-R06).

    Svoja seja in ne deljena s `PrijavaRepository`: ta je brez družine in ga
    dobi vmesna plast, ta pa je vezan na družino iz seje. Da sta ločena, je
    vidno v tipu in ne le v dogovoru (`docs/odlocitve/ADR-025`).
    """
    tovarna: sessionmaker[Session] = request.app.state.tovarna_sej
    with tovarna() as seja:
        yield ClaniRepository(seja, family_id)


def daj_repozitorij_statistike(
    request: Request, family_id: Annotated[str, Depends(daj_druzino)]
) -> Iterator[StatistikaRepository]:
    """Kot `daj_repozitorij`, a za statistiko čez kvize (V2-R04). Samo bere."""
    tovarna: sessionmaker[Session] = request.app.state.tovarna_sej
    with tovarna() as seja:
        yield StatistikaRepository(seja, family_id)


def daj_repozitorij_urnikov(
    request: Request, family_id: Annotated[str, Depends(daj_druzino)]
) -> Iterator[ScheduleRepository]:
    """Kot `daj_repozitorij`, a za urnike otrok družine (V3-R09).

    Svoja seja in ne deljena z `MaterialsRepository`: pregled po dnevih
    potrebuje oboje in s tem odpre dve **bralni** seji na zahtevo. To ni
    težava pravilnosti — pisanje teče izključno skozi pot potrditve in je
    zato ena seja in ena transakcija (isti razlog kot pri
    `daj_repozitorij_kvizov`).
    """
    tovarna: sessionmaker[Session] = request.app.state.tovarna_sej
    with tovarna() as seja:
        yield ScheduleRepository(seja, family_id)


def daj_klicalca_urnika(request: Request) -> KlicalecUrnika | None:
    """Klicalec za sliko urnika, ali `None`, kadar ključa za OpenAI ni.

    `None` in ne izjema: brez ključa mora stran z urnikom še vedno delati —
    mreža je urejljiva tudi brez slike (`ADR-041` E), zato je odsotnost
    ključa stanje, ki ga pot pove v slovenščini, in ne napaka strežnika.
    Isto sklepanje kot pri mirujočem workerju (`ADR-009` B2).
    """
    klicalec: KlicalecUrnika | None = request.app.state.klicalec_urnika
    return klicalec
