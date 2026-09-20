"""Pravila urnika in manjkajočih slik (V3-R09).

Brez FastAPI, brez seje in brez baze — po isti delitvi kot `app/statistika.py`,
`app/clani.py` in `app/otroci.py`: pravilo je čista funkcija, ki jo je mogoče
preizkusiti brez zahteve in brez izrisa. Potrebujeta ga **dva** usmerjevalnika
(`urnik` ga piše, `dnevi` ga bere), zato ni last nobenega od njiju in ima javno
ime, brez podčrtaja (`docs/01-arhitektura.md`).

Vse odločitve so v `docs/odlocitve/ADR-028`, izvedbene v `ADR-041`:

- **Urnik je množica predmetov na dan**, brez ur in brez zaporedja. Dve uri
  istega predmeta zahtevata vsaj eno sliko in sta zato ista reč.
- **Ponedeljek do petek** (`ADR-041` F). Sobote in nedelje ni na mreži, zato
  manjko tam ne nastane po sami zgradbi in ne po posebnem pravilu.
- **Manjki štejejo samo nearhivirane slike**; stanje obdelave in berljivost
  nanje ne vplivata — slika je slika, tudi če je model z nje ni znal prebrati.
- **Dan brez ene same slike manjkov nima** (`ADR-028` E2). Sicer bi bil vsak
  praznik vrstica s petimi manjki in stran bi postala šum.
- **Predmet, ki je poslikan, a ga tistega dne na urniku ni, ni napaka.** Urnik
  je pričakovanje, ne pravilo.
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass

from app.subjects import PREDMETI

#: Dnevi, ki jih urnik pozna, po `date.weekday()`: 0 = ponedeljek … 4 = petek.
#:
#: Izmeničnih (sodih/lihih) tednov urnik ne pozna — to bi bila nova dimenzija
#: zapisa in nova zahteva, ne popravek te (`ADR-028`).
DNEVI: tuple[int, ...] = (0, 1, 2, 3, 4)

#: Mesto predmeta v `PREDMETI`, za razvrščanje manjkov.
#:
#: Manjki se naštejejo v vrstnem redu urnika in ne po abecedi ne po vrstnem
#: redu vnosa — isto pravilo kot povsod drugod na `/admin`.
_MESTO = {predmet.koda: mesto for mesto, predmet in enumerate(PREDMETI)}

#: Kam pade koda, ki je na seznamu desetih ni.
#:
#: Potrjen urnik takih kod ne vsebuje — pot potrditve jih zavrne —, a
#: razvrščanje, ki bi ob njej vrglo `ValueError` sredi izrisa, bi bilo past za
#: vsako prihodnjo spremembo seznama predmetov.
_ZADNJI = len(PREDMETI)


@dataclass(frozen=True)
class Vnos:
    """En vnos urnika: ta predmet je ta dan pričakovan."""

    #: `date.weekday()`: 0 = ponedeljek … 4 = petek.
    dan: int

    #: Koda predmeta iz `PREDMETI`.
    predmet: str

    #: Ali se ta predmet **ta dan** ne slika (`ADR-028` F2). Tak vnos manjka
    #: ne javlja nikoli.
    se_ne_slika: bool = False


@dataclass(frozen=True)
class Urnik:
    """Potrjen urnik enega otroka kot množica vnosov.

    Vrednostni tip in ne vrstica iz baze: manjke računa nad njim tudi test, ki
    baze ne odpre. Pot iz baze je `ScheduleRepository.veljaven`.
    """

    vnosi: tuple[Vnos, ...]

    @classmethod
    def iz_vnosov(cls, vnosi: Iterable[Vnos]) -> "Urnik":
        """Urnik iz poljubnega zaporedja vnosov, brez podvojenih parov.

        Množica in ne seznam: dva vnosa za isti par *dan + predmet* sta ista
        reč. Shema to uveljavi z enoličnostjo, tu pa velja tudi za vnose, ki
        še niso bili zapisani — torej za predlog modela, kjer se ista koda v
        istem dnevu pojavi ob dveh urah.

        Ob podvojitvi obvelja **označeni** vnos: „ta dan se ta predmet ne
        slika" je izjema, ki jo je starš postavil namenoma, in tiho je ne
        preglasi neoznačena polovica istega para.
        """
        po_paru: dict[tuple[int, str], Vnos] = {}
        for vnos in vnosi:
            kljuc = (vnos.dan, vnos.predmet)
            prejsnji = po_paru.get(kljuc)
            if prejsnji is None or vnos.se_ne_slika:
                po_paru[kljuc] = vnos
        return cls(vnosi=tuple(sorted(po_paru.values(), key=_kljuc_vnosa)))

    def predmeti_dneva(self, dan: int) -> tuple[str, ...]:
        """Kode, ki so ta dan **pričakovane na sliki**, v vrstnem redu `PREDMETI`.

        Vnos z `se_ne_slika` tu ni: predmet, za katerega slike nikoli ni
        (LUM, GUM, TIT), bi sicer javljal manjko vsak teden in stran bi se
        nehala brati (`ADR-028` F).
        """
        return tuple(
            vnos.predmet
            for vnos in self.vnosi
            if vnos.dan == dan and not vnos.se_ne_slika
        )

def _kljuc_vnosa(vnos: Vnos) -> tuple[int, int, str]:
    """Razvrstitev vnosov: po dnevu, znotraj dneva po vrstnem redu `PREDMETI`."""
    return (vnos.dan, _MESTO.get(vnos.predmet, _ZADNJI), vnos.predmet)


def manjkajoci_predmeti(
    urnik: Urnik | None, dan: int, poslikani: Collection[str]
) -> tuple[str, ...]:
    """Predmeti z urnika tega dne, za katere ni nobene slike.

    `poslikani` so kode **nearhiviranih** slik tega otroka tistega lokalnega
    koledarskega dne — katerega koli stanja obdelave in katere koli
    berljivosti. Filtriranje arhiva je stvar klicatelja, ker je to isti nabor,
    ki ga stran že izriše; dva ločeno napisana filtra bi se nekoč razšla.

    Trije primeri vrnejo prazno:

    - **urnika ni** — otrok brez potrjenega urnika vidi stran natanko tako kot
      pred to zahtevo (kriterij `V3-R09`);
    - **dan nima nobene slike** — manjki se naštejejo samo tam, kjer je podatek
      nov, torej pri **delno** poslikanem dnevu (`ADR-028` E2). Brez tega bi
      bil vsak praznik in vsak dan počitnic vrstica s petimi manjki;
    - **vse pričakovano je poslikano** — kar je tudi ves smisel.

    Poslikan predmet, ki ga tistega dne na urniku ni, se ne javlja in tudi
    manjka ne zapre: urnik je pričakovanje, ne pravilo.
    """
    if urnik is None or not poslikani:
        return ()

    imamo = set(poslikani)
    return tuple(koda for koda in urnik.predmeti_dneva(dan) if koda not in imamo)
