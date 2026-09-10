"""Predmeti in prevodi, ki jih potrebuje operaterska stran.

Seznam desetih predmetov je **podvojen** iz
`apps/mobile/src/constants/subjects.ts`. To je zavestno: projekt namenoma
nima skupne kode med TypeScriptom in Pythonom (`docs/01-arhitektura.md`), in
mehanizem za deljenje desetih nizov bi stal več, kot prihrani.

Varovalo pred razhajanjem ni test nad tujo datoteko, ampak vedenje strani:
predmet, ki je v bazi in ga na tem seznamu ni, se **vseeno pokaže**, pod svojo
kodo (odločitev 3 v `docs/plan/V1-R04.md`). Preimenovana koda na telefonu zato
slik ne skrije.
"""

from typing import NamedTuple

from app.models import Ocena


class Predmet(NamedTuple):
    """Šolski predmet, kot ga pozna vmesnik."""

    #: Koda, kakršna pride s telefona in je zapisana v bazi.
    koda: str

    #: Ime za prikaz.
    oznaka: str


#: Cel urnik v vrstnem redu, ki ni abeceden in se ne preurejaj (V1-R01).
PREDMETI: tuple[Predmet, ...] = (
    Predmet("NAR", "Naravoslovje"),
    Predmet("MAT", "Matematika"),
    Predmet("TJA", "Tuji jezik angleščina"),
    Predmet("GEO", "Geografija"),
    Predmet("SLJ", "Slovenščina"),
    Predmet("LUM", "Likovna umetnost"),
    Predmet("ZGO", "Zgodovina"),
    Predmet("TIT", "Tehnika in tehnologija"),
    Predmet("DKE", "Domovinska in državljanska kultura in etika"),
    Predmet("GUM", "Glasbena umetnost"),
)

_PO_KODI = {predmet.koda: predmet for predmet in PREDMETI}


def poisci_predmet(koda: str) -> Predmet | None:
    """Predmet z dano kodo ali `None`, če ga na seznamu ni."""
    return _PO_KODI.get(koda)


def oznaka_predmeta(koda: str) -> str:
    """Ime za prikaz; za neznano kodo vrne kodo samo.

    Neznana koda ni napaka. Pomeni, da je v bazi zapis iz gradnje aplikacije z
    drugačnim seznamom — in tak zapis mora ostati viden.
    """
    predmet = _PO_KODI.get(koda)
    return predmet.oznaka if predmet is not None else koda


#: Stanje obdelave v slovenščini.
#:
#: V V1-R04 je zapis vedno `new`; preostali trije so tu zato, da jih V1-R03 ne
#: bo dodajala v predloge (odločitev 10 v `docs/plan/V1-R04.md`).
STATUSI: dict[str, str] = {
    "new": "čaka na obdelavo",
    "processing": "v obdelavi",
    "ready": "obdelano",
    "failed": "napaka",
}

#: Oznaka za obdelan zapis, s katerega model ni znal brati.
#:
#: Petega statusa namenoma ni: klic je uspel in bil plačan, torej to ni napaka
#: obdelave. Razliko nosi polje `readable`, oznaka pa mora povedati oboje —
#: „obdelano" samo bi bilo v tem primeru zavajajoče (`docs/plan/V1-R03.md`).
STATUS_NEBERLJIVO = "obdelano — slika ni berljiva"


#: Oznake štirih stopenj samoocene, kot jih vidi Maša na telefonu (`ADR-014`).
#:
#: Do V2-R04 so živele v `app/routers/kvizi.py`, ker jih je potreboval samo
#: rezultat kviza. Odkar jih potrebuje še statistika, niso last nobenega od
#: obeh usmerjevalnikov (`docs/01-arhitektura.md`). Vrstni red prikaza ni ta
#: slovar, ampak `OCENE` iz `app/models.py` — od najtežje navzdol.
OZNAKE_OCEN: dict[Ocena, str] = {
    "nisem_vedela": "Nisem vedela",
    "tezko": "Težko",
    "srednje": "Srednje",
    "lahko": "Lahko",
}


def oznaka_statusa(status: str, readable: bool | None = None) -> str:
    """Stanje obdelave za prikaz; neznano stanje pokaže dobesedno.

    `readable` je pomemben samo pri `ready`; pri ostalih stanjih je `None`,
    ker obdelave, ki bi to lahko povedala, še ni bilo.
    """
    if status == "ready" and readable is False:
        return STATUS_NEBERLJIVO
    return STATUSI.get(status, status)
