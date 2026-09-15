"""Odvisnosti, ki jih endpointi dobijo od aplikacije.

Vse berejo iz `app.state`, ki ga napolni `create_app`. Tako ni globalnega
stanja na ravni modula in vsak test dobi svojo, popolnoma ločeno aplikacijo.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from app.db import (
    DruzineRepository,
    KviziRepository,
    MaterialsRepository,
    StatistikaRepository,
)
from app.settings import Settings

#: Sporočilo, kadar družine ni mogoče izbrati. Nastane samo ob napaki v
#: namestitvi — po `0007_druzine` je družina natanko ena.
SPOROCILO_NI_ENE_DRUZINE = (
    "V bazi ni natanko ene družine, zato strežnik ne ve, čigave podatke naj pokaže. "
    "Preveri, ali je migracija 0007_druzine tekla (alembic upgrade head), in ali v "
    "tabeli families ni kdo dodal druge družine pred prijavo uporabnikov (V3-R03)."
)


def daj_nastavitve(request: Request) -> Settings:
    """Nastavitve te instance strežnika."""
    nastavitve: Settings = request.app.state.nastavitve
    return nastavitve


def daj_druzino(request: Request) -> str:
    """`id` družine, katere podatke ta zahteva bere in piše.

    **Začasno** (`docs/odlocitve/ADR-029` A): dokler ni prijave, je to edina
    družina v bazi. `V3-R03` jo za admin stran zamenja z družino seje, `V3-R04`
    za telefon z družino žetona. Pri nič ali več družinah zahteva pade s `500`
    in ne ugiba — druga družina pred prijavo je napaka v namestitvi.

    Preverba je tu in ne ob zagonu strežnika: test tesnjenja potrebuje dve
    družini v isti aplikaciji in to odvisnost zamenja.
    """
    tovarna: sessionmaker[Session] = request.app.state.tovarna_sej
    with tovarna() as seja:
        druzina = DruzineRepository(seja).edina()
    if druzina is None:
        raise HTTPException(status_code=500, detail=SPOROCILO_NI_ENE_DRUZINE)
    return druzina


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


def daj_repozitorij_statistike(
    request: Request, family_id: Annotated[str, Depends(daj_druzino)]
) -> Iterator[StatistikaRepository]:
    """Kot `daj_repozitorij`, a za statistiko čez kvize (V2-R04). Samo bere."""
    tovarna: sessionmaker[Session] = request.app.state.tovarna_sej
    with tovarna() as seja:
        yield StatistikaRepository(seja, family_id)
