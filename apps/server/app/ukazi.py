"""Ukazi za vzdrževanje strežnika. Zaenkrat eden: nastavitev gesla.

Zakaj ukaz in ne spremenljivka okolja: geslo v okolju ostane v `.env`, v
zgodovini lupine in v izpisu `docker inspect`, ukaz pa ga prebere s tipkovnice
in ga nikamor ne zapiše. Kriterij `V3-R03` je dopuščal oboje; izbrano je to
(`docs/odlocitve/ADR-035` G).

Zagon v produkciji:

    docker compose exec api python -m app.ukazi nastavi-geslo dejan.ambrus@gmail.com

Geslo se v argumentu **ne sprejme**. Argument bi pristal v zgodovini ukazov in
v seznamu procesov, kar je natanko tisto, čemur se ukaz izogiba.
"""

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from getpass import getpass

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db import PrijavaRepository, naredi_motor
from app.models import VLOGA_OTROK
from app.prijava import (
    NAJKRAJSE_GESLO,
    geslo_je_dovolj_dolgo,
    normaliziraj_identifikator,
    zgosti_geslo,
)
from app.settings import Settings

#: Izhodna koda ob napaki, ki je uporabnikova (napačen vnos, neznan račun).
NAPAKA = 1

SPOROCILO_GESLO_V_ARGUMENTU = (
    "Gesla ne sprejmem kot argument — ostalo bi v zgodovini lupine in v seznamu "
    "procesov. Zaženi ukaz brez gesla; vprašal te bom zanj."
)

SPOROCILO_NI_RACUNA = (
    "Računa s tem identifikatorjem ni. Preveri, ali je migracija 0008_uporabniki "
    "tekla (alembic upgrade head), in ali si e-naslov oziroma uporabniško ime "
    "vpisal natanko tako, kot je v bazi."
)

SPOROCILO_NEUJEMANJE = "Gesli se ne ujemata. Nič ni spremenjeno; poskusi znova."

SPOROCILO_PRAZNO = "Geslo je prazno. Nič ni spremenjeno."


def _sporocilo_prekratko(vloga: str) -> str:
    najmanj = NAJKRAJSE_GESLO[vloga]
    kdo = "otrokovo geslo" if vloga == VLOGA_OTROK else "staršev račun"
    return (
        f"Geslo je prekratko: za {kdo} jih mora biti vsaj {najmanj}. "
        "Nič ni spremenjeno."
    )


def nastavi_geslo(
    identifikator: str,
    *,
    vprasaj: Callable[[str], str] = getpass,
    izpisi: Callable[[str], None] = print,
    nastavitve: Settings | None = None,
    motor: Engine | None = None,
) -> int:
    """Nastavi geslo računu z danim identifikatorjem. Vrne izhodno kodo.

    `vprasaj`, `izpisi` in `motor` so argumenti, da test ne potrebuje ne
    tipkovnice ne ujetega izpisa ne prave baze — isti razlog kot pri `klicalec`
    v `app/main.py`.
    """
    if motor is None:
        if nastavitve is None:
            nastavitve = Settings()  # vsa polja imajo privzetek; okolje jih le prepiše
        motor = naredi_motor(nastavitve.database_url)

    # Ista normalizacija kot ob prijavi (`docs/odlocitve/ADR-038` E), sicer
    # `Masa` v ukazu ne bi našla računa `masa`, ki se s tem imenom prijavlja.
    identifikator = normaliziraj_identifikator(identifikator)

    with Session(motor) as seja:
        repo = PrijavaRepository(seja)
        poverilnica = repo.poverilnica(identifikator)
        if poverilnica is None:
            izpisi(SPOROCILO_NI_RACUNA)
            return NAPAKA

        geslo = vprasaj(f"Novo geslo za {poverilnica.display_name} ({identifikator}): ")
        if not geslo:
            izpisi(SPOROCILO_PRAZNO)
            return NAPAKA
        if not geslo_je_dovolj_dolgo(poverilnica.role, geslo):
            izpisi(_sporocilo_prekratko(poverilnica.role))
            return NAPAKA
        if vprasaj("Še enkrat isto geslo: ") != geslo:
            izpisi(SPOROCILO_NEUJEMANJE)
            return NAPAKA

        repo.ponastavi_geslo(
            poverilnica.credential_id,
            poverilnica.user_id,
            zgosti_geslo(geslo),
            datetime.now(UTC),
        )

    izpisi(
        f"Geslo za {poverilnica.display_name} je nastavljeno. "
        "Vse dosedanje seje tega računa so preklicane; prijaviti se je treba znova."
    )
    return 0


def glavni(argumenti: list[str] | None = None) -> int:
    """Razbere ukazno vrstico in požene ukaz."""
    razclenjevalnik = argparse.ArgumentParser(
        prog="python -m app.ukazi",
        description="Vzdrževalni ukazi strežnika Šolskega pomočnika.",
    )
    podukazi = razclenjevalnik.add_subparsers(dest="ukaz", required=True)

    geslo = podukazi.add_parser(
        "nastavi-geslo",
        help="Nastavi geslo računu (e-naslov starša ali uporabniško ime otroka).",
    )
    geslo.add_argument("identifikator", help="E-naslov ali uporabniško ime.")
    # Dovoljen samo zato, da lahko ukaz pojasni, zakaj ga ne sprejme. Brez tega
    # bi `argparse` odgovoril s suhim „unrecognized arguments".
    geslo.add_argument("odvecno", nargs="*", help=argparse.SUPPRESS)

    razclenjeno = razclenjevalnik.parse_args(argumenti)

    if razclenjeno.odvecno:
        print(SPOROCILO_GESLO_V_ARGUMENTU)
        return NAPAKA
    return nastavi_geslo(razclenjeno.identifikator)


if __name__ == "__main__":  # pragma: no cover — vhodna točka
    sys.exit(glavni())
