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
    PrijavaRepository,
    SejaUporabnika,
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


def daj_prijavo(request: Request) -> SejaUporabnika:
    """Seja, ki jo je za to zahtevo razrešila `SejaMiddleware`.

    Dosegljiva je izključno pod `/admin`: drugod plasti ni in je tudi seje ne.
    Klic zunaj `/admin` je napaka v kodi, ne stanje, ki bi ga smel povzročiti
    uporabnik — zato `RuntimeError` in ne HTTP odgovor.
    """
    seja: SejaUporabnika | None = getattr(request.state, "prijava", None)
    if seja is None:
        raise RuntimeError(
            "Ta pot je zunaj SejaMiddleware in seje nima. Odvisnost daj_prijavo "
            "sodi samo na poti pod /admin (docs/odlocitve/ADR-035 A)."
        )
    return seja


def daj_repozitorij_prijave(request: Request) -> Iterator[PrijavaRepository]:
    """Repozitorij uporabnikov, poverilnic in sej. Ena seja na zahtevo."""
    tovarna: sessionmaker[Session] = request.app.state.tovarna_sej
    with tovarna() as seja:
        yield PrijavaRepository(seja)


def daj_druzino(request: Request) -> str:
    """`id` družine, katere podatke bere in piše zahteva **pod `/admin`**.

    Odloči seja: `SejaMiddleware` jo je razrešila že pred usmerjevalnikom, zato
    tu ni nobene dodatne poizvedbe. S tem odpade začasna izbira „edina družina
    v bazi" (`docs/odlocitve/ADR-029` A) — za admin, ne za telefon; ta ima
    `daj_druzino_telefona`, dokler je `V3-R04` ne zamenja z žetonom.
    """
    return daj_prijavo(request).family_id


def daj_druzino_telefona(request: Request) -> str:
    """`id` družine za poti telefona — **začasno** edina družina v bazi.

    `ADR-029` A: dokler telefon nima žetona (`V3-R04`), družine ne pove nihče.
    Pri nič ali več družinah zahteva pade s `500` in ne ugiba; druga družina
    pred `V3-R04` je zato stanje, ki telefonske poti ustavi — namenoma.

    Preverba je tu in ne ob zagonu strežnika: test tesnjenja potrebuje dve
    družini v isti aplikaciji.
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


def daj_repozitorij_telefona(
    request: Request, family_id: Annotated[str, Depends(daj_druzino_telefona)]
) -> Iterator[MaterialsRepository]:
    """Kot `daj_repozitorij`, a za poti telefona (`POST /materials` in sorodne).

    Ločena odvisnost in ne zastavica: pot telefona in pot brskalnika družino
    izvesta na dva različna načina, in prav to razliko `V3-R04` odstrani.
    """
    tovarna: sessionmaker[Session] = request.app.state.tovarna_sej
    with tovarna() as seja:
        yield MaterialsRepository(seja, family_id)


def daj_repozitorij_kvizov_telefona(
    request: Request, family_id: Annotated[str, Depends(daj_druzino_telefona)]
) -> Iterator[KviziRepository]:
    """Kot `daj_repozitorij_kvizov`, a za poti telefona (V2-R02)."""
    tovarna: sessionmaker[Session] = request.app.state.tovarna_sej
    with tovarna() as seja:
        yield KviziRepository(seja, family_id)


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
