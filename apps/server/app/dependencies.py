"""Odvisnosti, ki jih endpointi dobijo od aplikacije.

Vse berejo iz `app.state`, ki ga napolni `create_app`. Tako ni globalnega
stanja na ravni modula in vsak test dobi svojo, popolnoma ločeno aplikacijo.
"""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from app.db import MaterialsRepository
from app.settings import Settings


def daj_nastavitve(request: Request) -> Settings:
    """Nastavitve te instance strežnika."""
    nastavitve: Settings = request.app.state.nastavitve
    return nastavitve


def daj_repozitorij(request: Request) -> Iterator[MaterialsRepository]:
    """Ena seja na zahtevo; zapre se tudi, če je zahteva padla."""
    tovarna: sessionmaker[Session] = request.app.state.tovarna_sej
    with tovarna() as seja:
        yield MaterialsRepository(seja)
