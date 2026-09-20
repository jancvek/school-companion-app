"""Izbira otroka v pogledih, ki so od `V3-R07` ločeni po otroku.

Potrebujeta jo **statistika** (`/admin/statistics`, `/admin/statistics/subjects/{koda}`)
in **pregled po dnevih** (`/admin/days`), zato ni last nobenega od njiju in
ima javno ime, brez podčrtaja — isto pravilo kot `app/casi.py` in
`app/besedilo.py` (`docs/01-arhitektura.md`, „Notranja delitev `apps/server`").

Brez FastAPI in brez seje, po delitvi `obdelava.py` / `worker.py`: pravilo
izbire je čista funkcija, ki jo je mogoče preizkusiti brez zahteve.

Pravila so iz `docs/odlocitve/ADR-039` B:

- **En otrok naenkrat, brez možnosti „vsi otroci".** Delež *Nisem vedela* čez
  dva otroka ni podatek o nobenem od njiju, statistika pa je pripomoček za
  pogovor z enim otrokom (`ADR-021` A).
- **Privzeto prvi po prikaznem imenu**; razvrstitev pride iz
  `ClaniRepository.otroci`, ki ima drugi ključ `id`, da se privzetek ob dveh
  enakih imenih ne premika.
- **Neznan ali tuj `id` je `404`**, z istim besedilom kot neobstoječ — obstoj
  tujega računa ni podatek za starša (`V3-R06`, `ADR-038`). To se namenoma
  razhaja z `?leto=` (tih padec na privzetek) in z `?dan=` (`400`,
  `ADR-023`): otrok ni okno nad istimi podatki, ampak identiteta podatkov.
- **Izbirnika, ki nima česa izbirati, ni**: pri enem otroku se ne izriše.
"""

from dataclasses import dataclass

from app.db import ClanDruzine

#: Ime parametra v naslovu. Slovensko, kot vidno besedilo — poti so angleške,
#: parametri vmesnika pa ne (`?leto=`, `?dan=`, `?obdobje=` so že takšni).
PARAMETER = "otrok"


@dataclass(frozen=True)
class IzbiraOtroka:
    """Kateri otrok je izbran in kaj naj pokaže izbirnik."""

    #: Izbrani otrok, ali `None`, kadar družina nima nobenega otroka. `None`
    #: ni napaka: družina, ki otroka še ni dobila, ima prazno statistiko in
    #: prazen pregled po dnevih, ne strani z napako.
    izbrani: ClanDruzine | None

    #: Vsi otroci družine, po prikaznem imenu — vsebina izbirnika.
    vsi: tuple[ClanDruzine, ...]

    @property
    def je_izbirnik(self) -> bool:
        """Ali se izbirnik sploh izriše.

        Pri enem otroku se ne: kriterij `V3-R07` pravi, da se vmesnik družine z
        enim otrokom ne spremeni. Pri nobenem prav tako ne — izbirati ni česa.
        """
        return len(self.vsi) > 1

    @property
    def ime_za_prikaz(self) -> str | None:
        """Prikazno ime izbranega otroka, ali `None`, kadar se ne izriše.

        Dvojček `kvizi.Naslovljenec.ime_za_prikaz` in iz istega razloga:
        pravilo „ime samo pri več kot enem otroku" (`ADR-039` F3) mora
        uveljaviti **tip**, ne klicno mesto. Prvi zapis te zahteve ga je
        uveljavljal na klicnih mestih in je zato v sestavljalniku odpadel.

        `V3-R09` bo po `ADR-039` B podedoval ta vzorec za tretji pogled po
        otroku; tam naj ne bo česa posnemati narobe.
        """
        if not self.je_izbirnik or self.izbrani is None:
            return None
        return self.izbrani.display_name


def izberi_otroka(
    otroci: list[ClanDruzine], zahtevani: str | None
) -> IzbiraOtroka | None:
    """Izbira iz parametra, ali privzetek; `None`, kadar zahtevanega ni.

    `None` pomeni **404** in ne tihega padca na privzetek: naslov, ki imenuje
    otroka, ki ga v tej družini ni, ne sme pokazati številk nekoga drugega.
    Prav to bi bila najtišja možna napaka te zahteve.
    """
    # Prazen niz šteje enako kot manjkajoč parameter: isti parameter ne sme
    # imeti dveh pomenov, in `?otrok=` iz počiščenega obrazca ne sme biti 404.
    if zahtevani:
        izbrani = next((otrok for otrok in otroci if otrok.user_id == zahtevani), None)
        if izbrani is None:
            return None
        return IzbiraOtroka(izbrani=izbrani, vsi=tuple(otroci))

    return IzbiraOtroka(izbrani=otroci[0] if otroci else None, vsi=tuple(otroci))
