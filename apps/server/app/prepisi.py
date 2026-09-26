"""Sestavljanje besedila s prepisi izbranih slik (V3-R11, V3-R12).

Čista funkcija: izbor snovi → besedilo. Brez FastAPI, brez baze in brez
predloge, po istem načelu kot `app/urnik.py` in `app/clani.py`. Javno ime,
brez podčrtaja, ker ga sme uvoziti kdorkoli — `docs/odlocitve/ADR-048` F
predvideva, da ga bo pozneje uporabil tudi generator delovnih listov
(`V4-R04`). To je možnost, ne obljuba.

Modul ne ve, katere snovi sme brati. Nabor določi klicalec — pri strani
predmeta je to `MaterialsRepository.seznam_po_predmetu`, ki že nosi mejo
družine, predmeta in arhiva. `izbrane` iz tega nabora obdrži samo označene in
jih uredi; identifikator, ki ga v naboru ni, tiho izpusti (`ADR-048` F).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.casi import cas_z_mesecem

#: Ločilo med imenom otroka in ostankom glave. Isti znak kot v seznamih na
#: strani predmeta in v arhivu, da glava ni videti kot druga vrsta podatka.
LOCILO_OTROKA = "·"


#: Zamik nadaljevalnih vrstic pod točko seznama vprašanj: poravnan z `O:`,
#: da markdown točke ne prekine (`ADR-049` C).
ZAMIK_TOCKE = "   "


@dataclass(frozen=True)
class VprasanjeZaPrepis:
    """Eno veljavno vprašanje z odgovorom, kakor ga vidi sestavljanje (V3-R12).

    Namenoma **ni** `Question`, iz istega razloga kot `SnovZaPrepis`.
    """

    vprasanje: str
    odgovor: str


@dataclass(frozen=True)
class SnovZaPrepis:
    """Ena snov, kakor jo vidi sestavljanje besedila.

    Namenoma **ni** `Material`: ta modul ne sme poznati sheme baze, sicer je
    „brez baze" samo trditev v docstringu. Pretvorbo naredi klicalec, kar je
    hkrati edino mesto, kjer se odloči, katera polja sploh smejo v besedilo.
    """

    id: str
    koda: str
    taken_at: datetime
    #: Ime otroka ali `None` pri družini z enim otrokom (`V3-R07`, `ADR-039` F).
    otrok: str | None
    #: Prepis ali `None`, kadar ga ni — v obdelavi, neuspela, neberljiva.
    prepis: str | None
    #: Povzetek ali `None`, kadar ga ni (V3-R12).
    povzetek: str | None = None
    #: Veljavna vprašanja v vrstnem redu izpisa (`ADR-015`, `ADR-049` C).
    #: Kateri so veljavni in kako so urejeni, odloči klicalec.
    vprasanja: tuple[VprasanjeZaPrepis, ...] = ()


@dataclass(frozen=True)
class Prepisi:
    """Besedilo in oba števca, ki stojita nad njim.

    Števca sta del izida in ne izračun v predlogi: obljuba iz kriterija je
    „število slik in znakov **tega** besedila", in dve ločeni poti do števila
    bi se nekoč razšli. Znakov je dobesedno `len(besedilo)`; strežnik besedila
    ne reže in praga ne pozna (`ADR-048` A).
    """

    besedilo: str
    slik: int
    znakov: int


def izbrane(
    nabor: Sequence[SnovZaPrepis], izbrani: Iterable[str]
) -> list[SnovZaPrepis]:
    """Iz nabora obdrži označene, urejene od najstarejše.

    Šteje samo identifikator, ki je v naboru. Tuja družina, drug predmet,
    arhiv in neobstoječ zapis se **tiho izpustijo**: tak identifikator ne
    more nastati iz izrisanega obrazca, zato ni napaka uporabnika, ki bi jo
    bilo treba razložiti, in odgovor z njim ne sme izdati, da tuja snov
    obstaja (`ADR-048` F).

    Vrstni red je obraten od strani predmeta — besedilo se bere kot snov v
    zaporedju, kot je nastajala (`ADR-048` D). Ob enakem `taken_at` odloči
    `id`, da je zaporedje določeno in ponovljivo; brez drugega ključa bi dva
    posnetka iz iste minute lahko vsakič zamenjala mesti.

    Ponovljen identifikator v izboru snov prispeva enkrat: obrazec ga tako ne
    pošlje, a podvojena glava bi bila tihi nesmisel v besedilu.
    """
    hoceni = set(izbrani)
    return sorted(
        (snov for snov in nabor if snov.id in hoceni),
        key=lambda snov: (snov.taken_at, snov.id),
    )


def _tocka(predpona: str, besedilo: str) -> list[str]:
    """Vrstice ene polovice točke; nadaljevalne dobijo zamik `ZAMIK_TOCKE`.

    `splitlines` in ne deljenje po `LF`, da `CRLF` iz modela ne pusti `CR` na
    koncu vrstice.
    """
    prva, *ostale = besedilo.strip().splitlines() or [""]
    return [f"{predpona}{prva}", *(f"{ZAMIK_TOCKE}{vrstica}" for vrstica in ostale)]


def _vprasanja(vprasanja: Sequence[VprasanjeZaPrepis]) -> str:
    """Oštevilčen seznam `N. V: …` / `   O: …` (`ADR-049` C).

    Številka je zaporedje izpisa in ne `position`, da luknja ne more nastati.
    Nadaljevalne vrstice večvrstičnega vprašanja ali odgovora so zamaknjene,
    sicer bi markdown točko prekinil.
    """
    vrstice = []
    for stevilka, vprasanje in enumerate(vprasanja, start=1):
        vrstice += _tocka(f"{stevilka}. V: ", vprasanje.vprasanje)
        vrstice += _tocka(f"{ZAMIK_TOCKE}O: ", vprasanje.odgovor)
    return "\n".join(vrstice)


def sestavi(snovi: Sequence[SnovZaPrepis]) -> Prepisi:
    """Besedilo s povzetki, prepisi in vprašanji danih snovi, v danem vrstnem redu.

    Vsaka snov prispeva markdown glavo, pod njo do tri dele s podnaslovi
    `### Povzetek`, `### Prepis` in `### Vprašanja`, vedno v tem redu
    (`ADR-049` A). Markdown in ne golo besedilo, ker ChatGPT glave razume kot
    mejo med kosi snovi, v navadnem urejevalniku pa ostanejo berljive
    (`ADR-048` D).

    Del, ki ga ni ali je iz samih presledkov, se izpusti skupaj s
    podnaslovom (`ADR-049` D). Snov brez vseh treh prispeva **samo glavo**
    (`ADR-048` E): glava je sled, da je bila snov tisti dan, in ta sled se ne
    sme izgubiti. To je zavestno drugače kot pri izbirniku kvizov, kjer
    neizbirna snov ostane brez kljukice.

    Vrstnega reda ta funkcija ne popravlja: uredi ga `izbrane`. Kdor sestavi
    zaporedje sam, dobi natanko svoje zaporedje.
    """
    kosi = []
    for snov in snovi:
        glava = f"## {snov.koda} — {cas_z_mesecem(snov.taken_at)}"
        if snov.otrok:
            glava = f"{glava} {LOCILO_OTROKA} {snov.otrok}"

        deli = [glava]
        for podnaslov, vsebina in (
            ("Povzetek", (snov.povzetek or "").strip()),
            ("Prepis", (snov.prepis or "").strip()),
            ("Vprašanja", _vprasanja(snov.vprasanja)),
        ):
            if vsebina:
                deli.append(f"### {podnaslov}\n{vsebina}")
        kosi.append("\n\n".join(deli))

    # Prazen izbor da prazno besedilo in ne vrstice s samim `\n`: stran ob
    # praznem izboru polja sploh ne izriše, `znakov` pa mora biti 0 in ne 1.
    besedilo = "\n\n".join(kosi) + "\n" if kosi else ""
    return Prepisi(besedilo=besedilo, slik=len(kosi), znakov=len(besedilo))
