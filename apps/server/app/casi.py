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

from datetime import UTC, date, datetime, time, timedelta
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


def datum_dneva(dan: date) -> str:
    """Koledarski dan v berljivem zapisu (`9. 9. 2026`).

    Oblika je sestavljena ročno in ne s `strftime`: oznaki `%-d` in `%-m` (dan
    in mesec brez vodilne ničle) na Windows ne obstajata, testi pa tečejo tam.

    Sprejme `date` in ne `datetime`, ker pregled po dnevih (V2-R07) izpiše tudi
    dan, ki nobenega posnetka nima — takrat trenutka, ki bi ga bilo mogoče
    pretvoriti, ni.
    """
    return f"{dan.day}. {dan.month}. {dan.year}"


def datum(trenutek: datetime) -> str:
    """Samo datum trenutka iz baze, v berljivem lokalnem zapisu."""
    return datum_dneva(v_domacem(trenutek).date())


def cas(trenutek: datetime) -> str:
    """Trenutek iz baze v berljiv lokalni zapis, z uro."""
    lokalni = v_domacem(trenutek)
    return f"{datum(trenutek)} ob {lokalni:%H:%M}"


def ura(trenutek: datetime) -> str:
    """Samo ura in minuta v domačem pasu (`08:05`).

    Za pregled po dnevih (V2-R07): datum nosi naslov skupine, ob sliki stoji
    samo ura in ponovljen datum bi bil šum.
    """
    return f"{v_domacem(trenutek):%H:%M}"


def cas_ali_prazno(trenutek: datetime | None) -> str | None:
    """Kot `cas`, a prenese tudi „se še ni zgodilo"."""
    return None if trenutek is None else cas(trenutek)


def trajanje(od: datetime, do: datetime) -> str:
    """Čas med dvema trenutkoma, za prikaz: `14 s`, `2 min 5 s`, `1 h 3 min`.

    Za trajanje odgovora na rezultatu kviza (V2-R03). Oba konca prideta s
    telefona (`docs/odlocitve/ADR-019` D); razlika med njima je zanesljivejša od
    absolutnih vrednosti, ne pa nezmotljiva — premik ure telefona med
    prikazom in oceno da **negativno** razliko. Ta ni podatek, ampak znak, da
    podatka ni, zato je izpis „—" in ne „-3 s".

    Naiven čas (SQLite) se razume kot UTC, kot v `v_domacem`. Brez tega bi
    odštevanje naivnega in pasovnega trenutka vrglo `TypeError` — v testih
    drugače kot v produkciji, kjer Postgres vrne oba s pasom.

    Sekunde se režejo navzdol: 59,9 s je še „59 s", ne „1 min 0 s".
    """
    razlika = utc(do) - utc(od)
    if razlika < timedelta(0):
        return "—"

    sekunde = int(razlika.total_seconds())
    ure, ostanek = divmod(sekunde, 3600)
    minute, sekunde = divmod(ostanek, 60)
    if ure:
        return f"{ure} h {minute} min"
    if minute:
        return f"{minute} min {sekunde} s"
    return f"{sekunde} s"


#: Imena mesecev v imenovalniku, od januarja. Za tabelo po mesecih (V2-R04).
MESECI = (
    "januar",
    "februar",
    "marec",
    "april",
    "maj",
    "junij",
    "julij",
    "avgust",
    "september",
    "oktober",
    "november",
    "december",
)

#: Mesec, s katerim se začne šolsko leto (`docs/odlocitve/ADR-021` B).
ZACETNI_MESEC = 9


def solsko_leto(trenutek: datetime) -> int:
    """Šolsko leto, ki mu trenutek pripada, kot leto začetka: 2026 je 2026/27.

    Meja je 1. september ob **lokalni** polnoči, iz istega razloga kot pri
    `dan_od_do`: poleti je to 31. avgusta ob 22:00 UTC, in ocena ob 23:30 po
    domačem času 31. avgusta sodi v staro leto, ocena ob 00:30 1. septembra pa
    v novo.
    """
    lokalni = v_domacem(trenutek)
    return lokalni.year if lokalni.month >= ZACETNI_MESEC else lokalni.year - 1


def solsko_leto_od_do(leto: int) -> tuple[datetime, datetime]:
    """Meji šolskega leta `leto` v UTC, polodprto: `[1. 9. leto, 1. 9. leto+1)`.

    Kot `dan_od_do` vrne par UTC trenutkov, ker repozitorij za časovne pasove ne
    ve. `datetime` s `ZoneInfo` sam izbere pravi odmik za tisti dan, zato
    poletnega časa ni treba obravnavati posebej.
    """
    zacetek = datetime(leto, ZACETNI_MESEC, 1, tzinfo=pas())
    konec = datetime(leto + 1, ZACETNI_MESEC, 1, tzinfo=pas())
    return zacetek.astimezone(UTC), konec.astimezone(UTC)


def oznaka_solskega_leta(leto: int) -> str:
    """Šolsko leto za prikaz: `2026/27`."""
    return f"{leto}/{(leto + 1) % 100:02d}"


def mesec(trenutek: datetime) -> tuple[int, int]:
    """Koledarsko leto in mesec trenutka v domačem pasu."""
    lokalni = v_domacem(trenutek)
    return lokalni.year, lokalni.month


def meseci_solskega_leta(leto: int) -> list[tuple[int, int]]:
    """Dvanajst mesecev šolskega leta po vrsti, od septembra do avgusta."""
    return [
        (leto if st >= ZACETNI_MESEC else leto + 1, st)
        for st in [*range(ZACETNI_MESEC, 13), *range(1, ZACETNI_MESEC)]
    ]


def oznaka_meseca(leto: int, st: int) -> str:
    """Mesec za prikaz: `september 2026`."""
    return f"{MESECI[st - 1]} {leto}"


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


def danes() -> date:
    """Današnji koledarski dan v domačem pasu.

    Ne `date.today()`: ta vrne dan po uri **stroja**, in stroj je v vsebniku
    nastavljen na UTC. Med lokalno polnočjo in dvema bi bil to še prejšnji dan
    in gumb „Danes" bi kazal včerajšnjo snov (V2-R07).
    """
    return datetime.now(pas()).date()


def dnevi_od_do(prvi: date, zadnji: date) -> tuple[datetime, datetime]:
    """Meji obdobja od dneva `prvi` do **vključno** dneva `zadnji`, v UTC.

    Polodprto `[od, do)` in lokalno, iz istih dveh razlogov kot `dan_od_do`:
    zaprt interval bi posnetek točno ob polnoči štel dvakrat, meja v UTC pa bi
    poleti posnetek med 22:00 in 24:00 UTC pripisala prejšnjemu dnevu.

    `dan_od_do` ostaja svoja funkcija in ne ovoj nad to: tam je vhod trenutek
    posnetka (sestavljalnik kvizov ne ve, katerega dne je), tu pa koledarski
    dan, ki ga je izbral operater in ki nobenega posnetka ni nujno imel.
    """
    zacetek = datetime.combine(prvi, time.min, tzinfo=pas())
    konec = datetime.combine(zadnji + timedelta(days=1), time.min, tzinfo=pas())
    return zacetek.astimezone(UTC), konec.astimezone(UTC)
