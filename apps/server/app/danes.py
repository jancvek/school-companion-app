"""Kartica „danes" na domači strani admina (V3-R13).

Odgovarja na eno vprašanje: ali je otrok danes že kaj poslikal in pri katerem
predmetu koliko slik (`docs/odlocitve/ADR-050`). Podroben odgovor je na
`/admin/days`; kartica je njegov povzetek in vanj pelje.

Svoj modul in ne del `routers/admin.py` ali `routers/dnevi.py`: kliče jo
domača stran, grupiranje po predmetu pa je sorodno pregledu po dnevih. Uvoz iz
enega usmerjevalnika v drugega bi bil prav vzorec, ki ga `dnevi.py` v glavi
zavrača. Ime je javno, brez podčrtaja, kot `app/casi.py` in `app/otroci.py`.

Brez FastAPI in brez seje, po delitvi `obdelava.py` / `worker.py`: sestava je
čista funkcija, ki dobi **dan** kot argument in ure stroja ne bere.

**Nabor ni tu.** Slike izbere klicatelj z istim klicem kot `/admin/days` —
`MaterialsRepository.seznam_po_obdobju` z mejama `dnevi_od_do(dan, dan)` —, da
se številki na obeh straneh ne moreta razići (`ADR-050` A1). Ta modul jih samo
prešteje in razvrsti.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from urllib.parse import quote

from app.db import ClanDruzine
from app.models import Material
from app.otroci import PARAMETER as PARAMETER_OTROKA
from app.subjects import PREDMETI

#: Pot pregleda po dnevih. Statičen niz in ne uvoz iz `routers/dnevi.py`, iz
#: razloga v glavi modula.
POT_DNEVI = "/admin/days"

#: `date.weekday()` sobote; sobota in nedelja sta vikend (`ADR-050` D1).
SOBOTA = 5


@dataclass(frozen=True)
class VrsticaOtroka:
    """Ena vrstica kartice: en aktiven otrok in njegove današnje slike."""

    #: Prikazno ime, ali `None` pri družini z enim otrokom. Pravilo „ime samo
    #: pri več kot enem otroku" (`ADR-039` F3, `ADR-051`) uveljavi tip in ne
    #: predloga, po vzorcu `IzbiraOtroka.ime_za_prikaz`.
    ime: str | None

    #: Predmeti s slikami in števila, v vrstnem redu `PREDMETI`, nato neznane
    #: kode po abecedi. Prazno, kadar otrok danes še ni ničesar poslikal.
    predmeti: tuple[tuple[str, int], ...]

    #: Gotov naslov na `/admin/days` za ta dan in tega otroka. Predloga
    #: naslovov ne sestavlja.
    href: str

    @property
    def ima_slike(self) -> bool:
        """Ali je otrok danes poslikal vsaj eno sliko."""
        return bool(self.predmeti)

    @property
    def stanje(self) -> str:
        """Besedilo vrstice, brez glagola s spolom (`ADR-050` E1).

        Ime je vrednost polja pred ločilom in ne del povedi (`ADR-039` F3).
        """
        stanje = "danes že poslikano" if self.ima_slike else "danes še ni slik"
        if self.ime is None:
            return stanje[0].upper() + stanje[1:]
        return f"{self.ime} — {stanje}"

    @property
    def predmeti_opis(self) -> str:
        """Predmeti za prikaz: `MAT 3 · SLJ 2`; prazno, kadar slik ni."""
        return " · ".join(f"{koda} {koliko}" for koda, koliko in self.predmeti)


@dataclass(frozen=True)
class KarticaDanes:
    """Vsebina kartice. Med vikendom brez vrstic (`ADR-050` D1)."""

    je_vikend: bool
    vrstice: tuple[VrsticaOtroka, ...]


def je_vikend(dan: date) -> bool:
    """Ali je dan sobota ali nedelja. Praznikov in počitnic ni (`ADR-050` D1)."""
    return dan.weekday() >= SOBOTA


def razvrsti_predmete(slike: Sequence[Material]) -> tuple[tuple[str, int], ...]:
    """Števila slik po predmetu, v vrstnem redu urnika.

    Isto pravilo kot `razvrsti_po_dnevih`: najprej `PREDMETI`, nato neznane
    kode po abecedi — te se **nikoli** ne izpustijo (odločitev 3 v
    `docs/plan/V1-R04.md`).
    """
    steviloma = Counter(slika.subject for slika in slike)
    znane = [predmet.koda for predmet in PREDMETI]
    neznane = sorted(koda for koda in steviloma if koda not in znane)
    return tuple(
        (koda, steviloma[koda])
        for koda in [koda for koda in znane if koda in steviloma] + neznane
    )


def povezava(dan: date, otrok: ClanDruzine, *, vec_otrok: bool) -> str:
    """Naslov pregleda po dnevih za ta dan in tega otroka.

    Datum je v naslovu, da polnoč med izrisom in klikom ne prestavi dneva.
    `?otrok=` samo, kadar ima družina več kot enega otroka (`ADR-039` B) —
    šteti se morajo **vsi** otroci, tudi deaktivirani, ker tako šteje izbirnik
    na `/admin/days`.
    """
    naslov = f"{POT_DNEVI}?dan={dan.isoformat()}"
    if vec_otrok:
        naslov += f"&{PARAMETER_OTROKA}={quote(otrok.user_id, safe='')}"
    return naslov


def sestavi_kartico(
    dan: date,
    otroci: Sequence[ClanDruzine],
    slike: Mapping[str, Sequence[Material]],
    *,
    vec_otrok: bool,
) -> KarticaDanes | None:
    """Kartica za dan `dan`; `None`, kadar družina nima aktivnega otroka.

    `otroci` so **aktivni** otroci v vrstnem redu `ClaniRepository.otroci`
    (`ADR-050` B1). `vec_otrok` šteje vse otroke družine, tudi deaktivirane,
    in odloči o `?otrok=` in o imenu v vrstici — oboje po istem pravilu kot
    izbirnik (`ADR-039` B, F3). `slike` preslika `id` otroka v njegove slike tega dne,
    kakor jih vrne `seznam_po_obdobju`; manjkajoč ključ pomeni „brez slik".
    Med vikendom se `slike` ne bere — vrstic tedaj ni, tudi če so slike.
    """
    if not otroci:
        return None
    if je_vikend(dan):
        return KarticaDanes(je_vikend=True, vrstice=())
    return KarticaDanes(
        je_vikend=False,
        vrstice=tuple(
            VrsticaOtroka(
                ime=otrok.display_name if vec_otrok else None,
                predmeti=razvrsti_predmete(slike.get(otrok.user_id, ())),
                href=povezava(dan, otrok, vec_otrok=vec_otrok),
            )
            for otrok in otroci
        ),
    )
