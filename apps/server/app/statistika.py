"""Pravila štetja za statistiko čez kvize (V2-R04).

Čiste funkcije brez FastAPI in brez seje, po delitvi `obdelava.py` /
`worker.py`: repozitorij prinese vrstice, tu se odloči, kaj šteje in kako se
razvrsti, usmerjevalnik pa to oblikuje za predlogo. Pravila so zapisana v
`docs/odlocitve/ADR-021`.

**Vse se izračuna ob branju iz dnevnika poskusov** in nič se ne shrani
(`ADR-012`). **Pravilnost se izpelje na enem mestu** — `je_pravilna` — in ne
obstaja nikjer kot podatek (`ADR-014`).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction

from app.casi import mesec, meseci_solskega_leta, solsko_leto, utc
from app.db import PoskusZaStatistiko
from app.models import OCENE

#: Ocena, ki pomeni, da odgovora ni vedela. Vse ostale so pravilne (`ADR-014`).
NEPRAVILNA = "nisem_vedela"

#: Ocene, ki štejejo za „težko" pri razvrščanju (`ADR-021` C).
TEZKE = frozenset({"nisem_vedela", "tezko"})

#: Od koliko poskusov naprej je vprašanje „postavljeno večkrat" (`ADR-021` C).
VECKRAT = 2


def je_pravilna(ocena: str) -> bool:
    """Ali ocena pomeni pravilen odgovor. **Edino mesto te izpeljave.**

    *Težko* je pravilen odgovor, dan s trudom; nepravilen je samo *Nisem
    vedela*. Če se kdaj odločimo drugače, se spremeni ta vrstica in izpeljava
    velja za nazaj — shranjen stolpec bi lagal o vsem, kar je že zapisano.
    """
    return ocena != NEPRAVILNA


def odstotek(del_: int, celota: int) -> int | None:
    """Celo število odstotkov, **polovica navzgor**; `None`, kadar ni celote.

    Ne Pythonov `round`, ki zaokroža bančno — 12,5 bi dal 12, 87,5 pa 88, in
    isti delež bi se zaokrožil v dve smeri glede na to, ali je sodo število
    pred njim. Celoštevilska aritmetika, da plavajoča vejica pri 0,5 ne zdrsne.
    """
    if celota == 0:
        return None
    return (200 * del_ + celota) // (2 * celota)


@dataclass
class Razporeditev:
    """Koliko poskusov je dobilo katero oceno. Vse ostalo se izpelje iz tega."""

    po_oceni: dict[str, int] = field(default_factory=lambda: dict.fromkeys(OCENE, 0))

    def dodaj(self, ocena: str) -> None:
        self.po_oceni[ocena] += 1

    @property
    def poskusov(self) -> int:
        return sum(self.po_oceni.values())

    @property
    def pravilnih(self) -> int:
        return sum(koliko for ocena, koliko in self.po_oceni.items() if je_pravilna(ocena))

    @property
    def tezkih(self) -> int:
        return sum(self.po_oceni[ocena] for ocena in TEZKE)

    @property
    def delez_tezkih(self) -> Fraction:
        """Natančen delež za razvrščanje — zaokrožen bi izenačil, kar ni enako."""
        return Fraction(self.tezkih, self.poskusov) if self.poskusov else Fraction(0)


@dataclass(frozen=True)
class Vnos:
    """Ena ocena v zaporedju pri vprašanju (`ADR-021` B)."""

    answered_at: datetime
    ocena: str
    quiz_id: str
    kviz_ime: str
    kviz_preklican: bool


@dataclass
class StatistikaVprasanja:
    """Vse poskuse na eno vprašanje (en `question_id`)."""

    question_id: str
    vprasanje: str
    odgovor: str
    subject: str | None
    material_id: str | None
    material_taken_at: datetime | None
    upokojeno: bool
    razporeditev: Razporeditev = field(default_factory=Razporeditev)
    zaporedje: list[Vnos] = field(default_factory=list)

    @property
    def zadnji(self) -> datetime:
        return max(utc(vnos.answered_at) for vnos in self.zaporedje)


@dataclass
class StatistikaSnovi:
    """Seštevek ene snovi.

    `material_id` je `None` za dokončno izbrisano snov; takrat jo prepozna
    `material_taken_at` (`ADR-012`).
    """

    material_id: str | None
    subject: str | None
    material_taken_at: datetime | None
    razporeditev: Razporeditev = field(default_factory=Razporeditev)
    vprasanj: set[str] = field(default_factory=set)
    zadnji: datetime | None = None


@dataclass
class Razdeljeno:
    """Poskusi, ki štejejo, in število tistih, ki ne morejo — a ne izpadejo molče."""

    stejejo: list[PoskusZaStatistiko]
    brez_vprasanja: int
    neprepoznanih: int


def razdeli(poskusi: Iterable[PoskusZaStatistiko]) -> Razdeljeno:
    """Loči poskuse, ki gredo v razporeditev, od tistih, ki ne morejo.

    Poskus brez vprašanja (postavka brez `question_id`) in poskus z oceno, ki je
    ni med štirimi (ročno spremenjena baza), nimata kam iti. Oba se štejeta
    posebej, da ju stran lahko omeni — po istem načelu kot skupina „Brez ocene"
    na rezultatu kviza (V2-R03).
    """
    stejejo: list[PoskusZaStatistiko] = []
    brez_vprasanja = 0
    neprepoznanih = 0
    for poskus in poskusi:
        if poskus.question_id is None:
            brez_vprasanja += 1
        elif poskus.rating not in OCENE:
            neprepoznanih += 1
        else:
            stejejo.append(poskus)
    return Razdeljeno(stejejo, brez_vprasanja, neprepoznanih)


def sestej(poskusi: Iterable[PoskusZaStatistiko]) -> Razporeditev:
    """Ena razporeditev čez vse dane poskuse."""
    razporeditev = Razporeditev()
    for poskus in poskusi:
        razporeditev.dodaj(poskus.rating)
    return razporeditev


def po_predmetih(poskusi: Iterable[PoskusZaStatistiko]) -> dict[str, Razporeditev]:
    """Razporeditev po predmetu vprašanja (`questions.subject`).

    Predmet vprašanja in ne kviza: dnevni kviz ima `subject` `NULL`, vprašanje
    pa ve, iz katerega predmeta je, tudi ko snovi ni več.
    """
    predmeti: dict[str, Razporeditev] = {}
    for poskus in poskusi:
        predmeti.setdefault(poskus.subject or "", Razporeditev()).dodaj(poskus.rating)
    return predmeti


def _kljuc(
    razporeditev: Razporeditev, zadnji: datetime | None, id_: str
) -> tuple[Fraction, int, float, str]:
    """Ključ „najtežje zgoraj" (`ADR-021` C), za `sorted` brez `reverse`.

    Delež težkih padajoče, nato število poskusov padajoče, nato zadnji poskus
    novejši prvi, nato `id` — da je vrstni red določen tudi pri popolnem
    izenačenju in se ne spreminja od osvežitve do osvežitve.
    """
    return (
        -razporeditev.delez_tezkih,
        -razporeditev.poskusov,
        -(utc(zadnji).timestamp() if zadnji is not None else 0.0),
        id_,
    )


def po_vprasanjih(poskusi: Iterable[PoskusZaStatistiko]) -> list[StatistikaVprasanja]:
    """Poskusi, združeni po `question_id`, z zaporedjem ocen po času.

    Upokojeno vprašanje je svoja vrstica: nova serija je nova identiteta, in
    povezovanja po besedilu ni (`ADR-021` D). Poskusi pridejo iz repozitorija
    urejeni po `answered_at`, zato je zaporedje že kronološko.
    """
    vprasanja: dict[str, StatistikaVprasanja] = {}
    for poskus in poskusi:
        if poskus.question_id is None:
            continue
        statistika = vprasanja.get(poskus.question_id)
        if statistika is None:
            statistika = StatistikaVprasanja(
                question_id=poskus.question_id,
                vprasanje=poskus.vprasanje or "",
                odgovor=poskus.odgovor or "",
                subject=poskus.subject,
                material_id=poskus.material_id,
                material_taken_at=poskus.material_taken_at,
                upokojeno=poskus.upokojeno,
            )
            vprasanja[poskus.question_id] = statistika
        statistika.razporeditev.dodaj(poskus.rating)
        statistika.zaporedje.append(
            Vnos(
                answered_at=poskus.answered_at,
                ocena=poskus.rating,
                quiz_id=poskus.quiz_id,
                kviz_ime=poskus.kviz_ime,
                kviz_preklican=poskus.kviz_preklican,
            )
        )
    return list(vprasanja.values())


def razvrsti(
    vprasanja: Iterable[StatistikaVprasanja],
) -> tuple[list[StatistikaVprasanja], list[StatistikaVprasanja]]:
    """Dva razdelka, vsak najtežji zgoraj: postavljena večkrat in enkrat.

    En sam poskus je že rezultat kviza (V2-R03) in še ni „vztrajno"; zato je
    tak razdelek pod večkrat postavljenimi, četudi ima 100 % težkih.
    """
    urejena = sorted(
        vprasanja,
        key=lambda v: _kljuc(v.razporeditev, v.zadnji, v.question_id),
    )
    veckrat = [v for v in urejena if v.razporeditev.poskusov >= VECKRAT]
    enkrat = [v for v in urejena if v.razporeditev.poskusov < VECKRAT]
    return veckrat, enkrat


def po_snoveh(vprasanja: Iterable[StatistikaVprasanja]) -> list[StatistikaSnovi]:
    """Seštevek po snovi, najtežja zgoraj (isti ključ kot pri vprašanjih).

    Snov je `material_id`. Vprašanja dokončno izbrisane snovi (`material_id`
    `NULL`) se združijo po predmetu in času posnetka — to je vse, kar o snovi
    še vedo (`ADR-012`).
    """
    snovi: dict[tuple[str | None, str | None, datetime | None], StatistikaSnovi] = {}
    for vprasanje in vprasanja:
        kljuc = (
            (vprasanje.material_id, None, None)
            if vprasanje.material_id is not None
            else (None, vprasanje.subject, vprasanje.material_taken_at)
        )
        snov = snovi.get(kljuc)
        if snov is None:
            snov = StatistikaSnovi(
                material_id=vprasanje.material_id,
                subject=vprasanje.subject,
                material_taken_at=vprasanje.material_taken_at,
            )
            snovi[kljuc] = snov
        for ocena, koliko in vprasanje.razporeditev.po_oceni.items():
            snov.razporeditev.po_oceni[ocena] += koliko
        snov.vprasanj.add(vprasanje.question_id)
        if snov.zadnji is None or vprasanje.zadnji > snov.zadnji:
            snov.zadnji = vprasanje.zadnji

    return sorted(snovi.values(), key=lambda s: _kljuc(s.razporeditev, s.zadnji, _id_snovi(s)))


def _id_snovi(snov: StatistikaSnovi) -> str:
    """Zadnji del ključa razvrstitve: `id` snovi ali, pri izbrisani, čas posnetka."""
    if snov.material_id is not None:
        return snov.material_id
    if snov.material_taken_at is not None:
        return utc(snov.material_taken_at).isoformat()
    return ""


def po_mesecih(
    poskusi: Iterable[PoskusZaStatistiko], leto: int
) -> list[tuple[tuple[int, int], Razporeditev]]:
    """Dvanajst mesecev šolskega leta, od septembra do avgusta, **tudi prazni**.

    Prazen mesec je vrstica z ničlo in ne izpuščen — stran mora pokazati, česa
    ni, kot prazne skupine na rezultatu kviza. Mesec se določi v domačem pasu.
    """
    meseci = {kljuc: Razporeditev() for kljuc in meseci_solskega_leta(leto)}
    for poskus in poskusi:
        razporeditev = meseci.get(mesec(poskus.answered_at))
        if razporeditev is not None:
            razporeditev.dodaj(poskus.rating)
    return list(meseci.items())


def po_letih(poskusi: Iterable[PoskusZaStatistiko]) -> list[tuple[int, Razporeditev]]:
    """Po šolskem letu, najstarejše prvo — za okno „vse"."""
    leta: dict[int, Razporeditev] = {}
    for poskus in poskusi:
        leta.setdefault(solsko_leto(poskus.answered_at), Razporeditev()).dodaj(poskus.rating)
    return sorted(leta.items())


def solska_leta(casi: Sequence[datetime]) -> list[int]:
    """Šolska leta, v katerih je kakšen poskus, najnovejše prvo."""
    return sorted({solsko_leto(cas) for cas in casi}, reverse=True)
