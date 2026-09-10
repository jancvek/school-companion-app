"""Čas za prikaz in meje dneva v domačem pasu.

Do V2-R01 je vse to živelo v `app/routers/admin.py` kot zasebne funkcije. Ko
je isto potreboval še usmerjevalnik kvizov, je bila izbira med uvozom iz enega
usmerjevalnika v drugega in svojim modulom. Uvoz med usmerjevalnikoma bi
pomenil, da `kvizi` ne moreta obstajati brez `admin`, čeprav gre za štiri
funkcije, ki o usmerjanju ne vedo nič.

Imena so odslej **javna in brez podčrtaja**: podčrtaj pomeni „ne uvažaj tega
od zunaj", uvoz od zunaj pa je prav razlog, da ta modul obstaja.

V bazi je vse v UTC. Stran, ki bi kazala UTC, bi ob vsakem posnetku zahtevala
računanje na pamet — in prav ura posnetka je podatek, po katerem operater
sliko prepozna.
"""

from datetime import UTC, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

#: Ime časovnega pasu, v katerem operater bere ure.
#:
#: Pas je imenski in ne odmik, ker se odmik dvakrat na leto spremeni. Bazo
#: pasov prinese sistem: v vsebniku `python:3.12-slim` je v
#: `/usr/share/zoneinfo`, na Windows pa paket `tzdata`, ki ga zahteva že
#: `psycopg`. Zato tu ni nove odvisnosti.
DOMACI_PAS = "Europe/Ljubljana"


@lru_cache(maxsize=1)
def pas() -> ZoneInfo:
    """Časovni pas, poiskan ob prvi uporabi in nato zapomnjen.

    Namenoma **ni** modulska konstanta: `ZoneInfo` brez baze pasov vrže
    izjemo, in ta bi ob uvozu modula podrla celo aplikacijo — tudi
    `GET /health` in `POST /materials`. Udobje pri prikazu ure ne sme biti
    pogoj za življenje strežnika.
    """
    return ZoneInfo(DOMACI_PAS)


def utc(trenutek: datetime) -> datetime:
    """Trenutek iz baze z izrecnim pasom UTC.

    Za odgovore telefonu (V2-R02): naiven čas, kakršnega vrne SQLite, bi se v
    JSON zapisal brez pasu, telefon pa bi ga prebral kot svoj lokalni čas.
    """
    if trenutek.tzinfo is None:
        return trenutek.replace(tzinfo=UTC)
    return trenutek.astimezone(UTC)


def v_domacem(trenutek: datetime) -> datetime:
    """Trenutek iz baze, pretvorjen v domači pas.

    Čas brez podatka o pasu razumemo kot UTC. To ni teoretični robni primer:
    Postgres v stolpcu `TIMESTAMPTZ` pas vrne, **SQLite pa ne** — vrne naiven
    `datetime`. Brez te vrstice bi `astimezone` naiven čas razumel kot čas
    strežnikovega pasu in ura bi bila v testih drugačna kot v produkciji.
    """
    if trenutek.tzinfo is None:
        trenutek = trenutek.replace(tzinfo=UTC)
    return trenutek.astimezone(pas())


def datum(trenutek: datetime) -> str:
    """Samo datum, v berljivem lokalnem zapisu (`9. 9. 2026`).

    Oblika je sestavljena ročno in ne s `strftime`: oznaki `%-d` in `%-m` (dan
    in mesec brez vodilne ničle) na Windows ne obstajata, testi pa tečejo tam.
    """
    lokalni = v_domacem(trenutek)
    return f"{lokalni.day}. {lokalni.month}. {lokalni.year}"


def cas(trenutek: datetime) -> str:
    """Trenutek iz baze v berljiv lokalni zapis, z uro."""
    lokalni = v_domacem(trenutek)
    return f"{datum(trenutek)} ob {lokalni:%H:%M}"


def cas_ali_prazno(trenutek: datetime | None) -> str | None:
    """Kot `cas`, a prenese tudi „se še ni zgodilo"."""
    return None if trenutek is None else cas(trenutek)


def dan_od_do(trenutek: datetime) -> tuple[datetime, datetime]:
    """Meji koledarskega dne, ki mu trenutek pripada, v UTC.

    Vrne **polodprt** interval `[od, do)`: od lokalne polnoči do naslednje
    lokalne polnoči. Polodprt zato, ker bi zaprt pri posnetku točno ob polnoči
    dan štel dvakrat.

    Meja je lokalna in ne UTC — `ADR-016` (B) pravi „od polnoči do polnoči" v
    pasu `Europe/Ljubljana`. Razlika se pokaže poleti pri posnetku med 22:00 in
    24:00 UTC, ki lokalno pripada že naslednjemu dnevu; takrat je pravilna prav
    lokalna meja.

    Poletnega časa ni treba posebej obravnavati: v tem pasu se ura premakne ob
    02:00 oziroma 03:00, zato lokalna polnoč vedno obstaja in je enolična.
    """
    dan = v_domacem(trenutek).date()
    zacetek = datetime.combine(dan, time.min, tzinfo=pas())
    return zacetek.astimezone(UTC), (zacetek + timedelta(days=1)).astimezone(UTC)
