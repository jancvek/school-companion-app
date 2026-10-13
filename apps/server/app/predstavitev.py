"""Javna predstavitvena stran: pot, sidra in podatki prikazov (V6-R03).

Brez FastAPI, brez baze in brez seje — stran je za vsakogar ista
(`docs/odlocitve/ADR-059` A, `ADR-063` A). Kar stran navaja z imenom iz
vmesnika, pride od tam, kjer vmesnik to ime hrani, da se ob preimenovanju ne
razideta po tihem.
"""

from typing import NamedTuple

from app.subjects import OZNAKE_OCEN

#: Točna pot strani. Edina pot zunaj `/admin`, ki vrne HTML.
POT = "/"

#: Sidra razdelkov; meni v glavi in povezave z drugih strani kažejo nanje.
SIDRO_TESTI = "testi"
SIDRO_KVIZI = "kvizi"
SIDRO_KAKO = "kako-deluje"
SIDRO_DRUZINA = "druzina"
SIDRO_ZASEBNOST = "zasebnost"
SIDRO_RACUN = "racun"

#: Kam vodi „pravila zasebnosti" ob soglasju (`ADR-063` C).
POT_ZASEBNOSTI = f"{POT}#{SIDRO_ZASEBNOST}"

#: Slog strani. Pod `/admin/static`, a dosegljiv brez seje kot **točna pot**
#: (`main.JAVNE_DATOTEKE`, `ADR-063` B).
POT_SLOGA = "/admin/static/javno/slog.css"

#: Meni v glavi, v vrstnem redu razdelkov (`docs/poc/POC-03.md`, *Dogovorjeno*).
MENI: tuple[tuple[str, str], ...] = (
    (SIDRO_TESTI, "Testi"),
    (SIDRO_KVIZI, "Kvizi"),
    (SIDRO_KAKO, "Kako deluje"),
    (SIDRO_DRUZINA, "Za otroka in starše"),
    (SIDRO_ZASEBNOST, "Zasebnost"),
)

#: Štiri ocene samoocene, od najtežje navzdol — kot na telefonu.
OCENE: tuple[str, ...] = tuple(OZNAKE_OCEN.values())


class VrsticaStatistike(NamedTuple):
    """En pas v prikazu statistike. Podatki so izmišljeni (`ADR-059` D)."""

    koda: str
    #: Deleži štirih ocen v odstotkih, v vrstnem redu `OCENE`.
    delezi: tuple[int, int, int, int]
    odgovorov: int


STATISTIKA: tuple[VrsticaStatistike, ...] = (
    VrsticaStatistike("MAT", (22, 28, 25, 25), 48),
    VrsticaStatistike("NAR", (8, 14, 30, 48), 36),
    VrsticaStatistike("SLJ", (12, 20, 34, 34), 41),
    VrsticaStatistike("GEO", (5, 10, 25, 60), 20),
)
