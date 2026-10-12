"""Stalni meni spletnega pregleda (V5-R01).

Nadomesti razdelke-povezave na dnu `/admin` (`docs/odlocitve/ADR-056` G).
Tu so **pravila**: katere postavke so, katera je izbrana in kje števcev ni.
Štetje samo je v `app/strani.py`, ki te funkcije kliče — modul je brez
FastAPI in brez baze, po delitvi `app/danes.py` in `app/urnik.py`.
"""

from dataclasses import dataclass

#: Predpona strani lastnika sistema. Pod njo meni **nima števcev**: te strani
#: ne berejo vsebine nobene družine in to trdi test s prestrezanjem SQL
#: (`docs/odlocitve/ADR-044` B, `ADR-060` F).
PREDPONA_SISTEMA = "/admin/system"


@dataclass(frozen=True)
class Stevci:
    """Kar meni šteje, za eno družino."""

    slik: int = 0
    cakajocih_kvizov: int = 0
    testov: int = 0
    arhiviranih: int = 0


@dataclass(frozen=True)
class Postavka:
    """Ena vrstica menija."""

    oznaka: str
    href: str
    #: Ali stran, ki se izrisuje, sodi pod to postavko.
    izbrana: bool
    #: Število ob postavki; `None`, kadar ga ni ali je nič.
    stevec: int | None = None


@dataclass(frozen=True)
class Meni:
    """Dve skupini postavk z ločilom med njima, kot na posnetkih `POC-02`."""

    vsebina: tuple[Postavka, ...]
    uprava: tuple[Postavka, ...]


#: (oznaka, naslov, predpone poti, ki sodijo pod postavko, ključ števca).
#:
#: Vrstni red je iz `ADR-056` G in se ne preurejaj. Podrobnosti slike, prepisi
#: in stran predmeta so del „Predmetov": tja se pride s police.
_VSEBINA: tuple[tuple[str, str, tuple[str, ...], str | None], ...] = (
    (
        "Predmeti",
        "/admin",
        ("/admin/subjects", "/admin/materials", "/admin/transcripts"),
        "slik",
    ),
    ("Po dnevih", "/admin/days", ("/admin/days",), None),
    ("Kvizi", "/admin/quizzes", ("/admin/quizzes",), "cakajocih_kvizov"),
    ("Testi", "/admin/assessments", ("/admin/assessments",), "testov"),
    ("Urnik", "/admin/schedule", ("/admin/schedule",), None),
    ("Statistika", "/admin/statistics", ("/admin/statistics",), None),
)
_UPRAVA: tuple[tuple[str, str, tuple[str, ...], str | None], ...] = (
    ("Družina", "/admin/family", ("/admin/family",), None),
    ("Arhiv", "/admin/archive", ("/admin/archive",), "arhiviranih"),
)
_SISTEM = ("Sistem", PREDPONA_SISTEMA, (PREDPONA_SISTEMA,), None)


def _je_pod(pot: str, predpona: str) -> bool:
    """Predpona se ujame na sebi in na tem, kar ji sledi za poševnico.

    Isto pravilo kot `security.je_izvzeta`: `/admin/system` in
    `/admin/system/…`, **ne** pa `/admin/systematic`.
    """
    return pot == predpona or pot.startswith(f"{predpona}/")


def je_brez_stevcev(pot: str) -> bool:
    """Ali se za to pot števci ne smejo šteti (`ADR-060` F)."""
    return _je_pod(pot, PREDPONA_SISTEMA)


def sestavi_meni(
    pot: str, *, lastnik_sistema: bool, stevci: Stevci | None, cakajocih: int = 0
) -> Meni:
    """Meni za stran na dani poti.

    `stevci` je `None` pod `/admin/system`; ostale strani ga podajo vedno.
    Števec z vrednostjo nič se ne izriše — „Arhiv 0" ne pove ničesar.

    `cakajocih` je število družin, ki čakajo na odobritev (V6-R02); stoji ob
    postavki „Sistem" in ga zato vidi samo lastnik. **Ni števec vsebine**:
    bere samo `families`, zato je viden tudi pod `/admin/system`, kjer
    števcev vsebine ni (`ADR-062` Q).
    """

    def postavka(vnos: tuple[str, str, tuple[str, ...], str | None]) -> Postavka:
        oznaka, href, predpone, kljuc = vnos
        # `/admin` je predpona vsega; kot izbrana šteje samo natanko ta pot.
        izbrana = pot == href or any(_je_pod(pot, predpona) for predpona in predpone)
        koliko = getattr(stevci, kljuc) if stevci is not None and kljuc else None
        return Postavka(oznaka=oznaka, href=href, izbrana=izbrana, stevec=koliko or None)

    uprava = tuple(postavka(vnos) for vnos in _UPRAVA)
    if lastnik_sistema:
        sistem = postavka(_SISTEM)
        uprava += (
            Postavka(
                oznaka=sistem.oznaka,
                href=sistem.href,
                izbrana=sistem.izbrana,
                stevec=cakajocih or None,
            ),
        )
    return Meni(vsebina=tuple(postavka(vnos) for vnos in _VSEBINA), uprava=uprava)


def ime_druzine(ime: str) -> str:
    """Ime družine za glavo menija: „Družina Novak".

    Ime vpiše lastnik sistema in sme biti že „Družina Novak"; takrat se beseda
    ne podvoji. Ime stoji za samostalnikom v imenovalniku, zato sklanjanja ni.
    """
    cisto = ime.strip()
    if cisto.lower().startswith("družina"):
        return cisto
    return f"Družina {cisto}"


def zacetnica(ime: str) -> str:
    """Prva črka imena za krožec ob imenu; prazno ime da prazen krožec."""
    cisto = ime.strip()
    return cisto[:1].upper()
