"""Razvrstitev slik po tednih in dneh (V5-R01).

Stran predmeta in izbor snovi za kviz kažeta slike po tednih: teden je blok,
v njem dnevi od ponedeljka naprej (`docs/poc/POC-02.md`, `ADR-060` D in E).
Tu je samo **razvrstitev in poimenovanje** — brez FastAPI, brez baze in brez
urnika; zakaj je dan prazen, pove `app/urnik.py`.

Razvršča se po **lokalnem** koledarskem dnevu, ki ga poda klicatelj
(`casi.v_domacem(...).date()`): izraz za lokalni dan v SQL ni prenosljiv med
SQLite in Postgresom, isti razlog kot na pregledu po dnevih.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from app.casi import MESECI

#: Kratka imena dni po `date.weekday()`, za glavo stolpca.
KRATKA_IMENA_DNI = ("Pon", "Tor", "Sre", "Čet", "Pet", "Sob", "Ned")

#: Zadnji dan, ki ga teden pokaže vedno; sobota in nedelja samo s slikami
#: (`ADR-060` D) — urnik pozna ponedeljek do petka (`ADR-041` F).
PETEK = 4

#: Pomišljaj v razponu dni. Kot ubežni znak, ker ga `ruff` v nizu šteje za
#: zamenljivega z vezajem.
POMISLJAJ = "\u2013"


def ponedeljek_tedna(dan: date) -> date:
    """Ponedeljek tedna, v katerem je `dan`."""
    return dan - timedelta(days=dan.weekday())


@dataclass(frozen=True)
class Dan[T]:
    """En dan tedna in njegove slike, **od najstarejše naprej**.

    Zaporedni posnetki istega dne so strani iste snovi (`ADR-003`), zato se
    znotraj dneva berejo v vrstnem redu nastanka — kot na pregledu po dnevih.
    """

    datum: date
    snovi: tuple[T, ...]

    @property
    def ime(self) -> str:
        return KRATKA_IMENA_DNI[self.datum.weekday()]

    @property
    def datum_kratko(self) -> str:
        """Dan in mesec brez leta (`5. 10.`); leto pove glava tedna."""
        return f"{self.datum.day}. {self.datum.month}."

    @property
    def je_vikend(self) -> bool:
        return self.datum.weekday() > PETEK


@dataclass(frozen=True)
class Teden[T]:
    """En teden z vsaj eno sliko: pet dni, vikend dan samo s slikami."""

    ponedeljek: date
    dnevi: tuple[Dan[T], ...]

    @property
    def stevilo(self) -> int:
        return sum(len(dan.snovi) for dan in self.dnevi)

    @property
    def razpon(self) -> str:
        """Prvi in zadnji prikazani dan s stičnim pomišljajem: od 5. do 9. oktobra.

        Čez mejo meseca nosita mesec oba dneva, pomišljaj pa je nestičen.
        Imena mesecev so v imenovalniku, kot povsod (`casi.cas_z_mesecem`).
        """
        prvi, zadnji = self.dnevi[0].datum, self.dnevi[-1].datum
        if prvi.month == zadnji.month:
            return f"{prvi.day}.{POMISLJAJ}{zadnji.day}. {MESECI[zadnji.month - 1]}"
        return (
            f"{prvi.day}. {MESECI[prvi.month - 1]} {POMISLJAJ} "
            f"{zadnji.day}. {MESECI[zadnji.month - 1]}"
        )

    def oznaka(self, danes: date) -> str | None:
        """„Ta teden" ali „Prejšnji teden"; starejši tedni oznake nimajo."""
        razlika = (ponedeljek_tedna(danes) - self.ponedeljek).days
        return {0: "Ta teden", 7: "Prejšnji teden"}.get(razlika)


def razvrsti_po_tednih[T](snovi: Iterable[tuple[date, T]]) -> list[Teden[T]]:
    """Slike v tednih, **najnovejši teden prvi**; teden brez slik ne nastane.

    `snovi` so pari (lokalni dan, slika) v vrstnem redu **od najnovejše
    navzdol**, kot jih vrne `seznam_po_predmetu`. Znotraj dneva se vrstni red
    obrne — glej `Dan`.

    Teden brez ene same slike se ne izriše (`ADR-060` E): počitnice bi sicer
    dale vrsto praznih blokov. Dan brez slik znotraj prikazanega tedna pa
    ostane, če je delavnik — prav odsotnost slik je tam podatek.
    """
    po_dneh: dict[date, list[T]] = {}
    for dan, snov in snovi:
        po_dneh.setdefault(dan, []).append(snov)

    tedni = []
    for ponedeljek in sorted({ponedeljek_tedna(dan) for dan in po_dneh}, reverse=True):
        dnevi = []
        for odmik in range(7):
            datum = ponedeljek + timedelta(days=odmik)
            slike_dne = po_dneh.get(datum, [])
            if odmik <= PETEK or slike_dne:
                dnevi.append(Dan(datum=datum, snovi=tuple(reversed(slike_dne))))
        tedni.append(Teden(ponedeljek=ponedeljek, dnevi=tuple(dnevi)))
    return tedni


def oznaka_tedna(ponedeljek: date, danes: date) -> str:
    """Naslov skupine v seznamu po tednih: „Ta teden", „Prejšnji teden" ali razpon.

    Za izbor snovi za kviz, kjer teden ni blok z dnevi, ampak naslov nad
    vrsticami. Razpon je vedno od ponedeljka do petka.
    """
    teden: Teden[object] = Teden(
        ponedeljek=ponedeljek,
        dnevi=tuple(
            Dan(datum=ponedeljek + timedelta(days=odmik), snovi=()) for odmik in range(PETEK + 1)
        ),
    )
    return teden.oznaka(danes) or teden.razpon[0].upper() + teden.razpon[1:]


def v_tednih(koliko: int) -> str:
    """Število tednov v mestniku, za „24 slik v 4 tednih".

    Mestnik ima dve obliki: *v 1 tednu*, sicer *v 2, 3, 5, 21 tednih*. Ločnica
    je ostanek pri deljenju s sto, kot v `besedilo.stevilo_z_besedo` — *v 101
    tednu*, a *v 111 tednih*.
    """
    return f"{koliko} tednu" if koliko % 100 == 1 else f"{koliko} tednih"
