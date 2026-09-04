"""Zapis prejete slike na disk.

Vrstni red je enak kot na telefonu (odločitev 4 v planu V1-R01, odločitev 5 v
planu V1-R02): najprej cela datoteka, šele nato vrstica v bazi.

Zapis gre v `<images_dir>/.tmp/<id>.jpg` in se na končno mesto premakne z
`os.replace`, ki je na istem datotečnem sistemu atomaren. Prekinjen prenos
zato pusti kvečjemu ostanek v `.tmp/`, nikoli pa polovične slike na mestu, kjer
jo bo V1-R03 iskal kot celo.
"""

import contextlib
import shutil
from pathlib import Path
from typing import Protocol

#: Podmapa za nedokončane zapise.
ZACASNA_PODMAPA = ".tmp"


class BereBajte(Protocol):
    """Karkoli, iz česar se da brati bajte.

    Namenoma ni `BinaryIO`: ta zahteva ves nabor metod datoteke, mi pa
    potrebujemo samo `read`. Ožji tip pomeni, da se da v testu podtakniti
    preprost predmet in ne cele lažne datoteke.
    """

    def read(self, size: int = -1, /) -> bytes: ...


def koncna_pot(images_dir: Path, material_id: str) -> Path:
    """Mesto, kjer slika živi, ko je zapis končan."""
    return images_dir / f"{material_id}.jpg"


def shrani_sliko(images_dir: Path, material_id: str, vir: BereBajte) -> Path:
    """Zapiše `vir` v `<images_dir>/<id>.jpg` in vrne končno pot.

    Ob kakršnikoli napaki počisti začasno datoteko in napako prenese naprej —
    klicatelj mora poskrbeti, da v tem primeru ne nastane vrstica v bazi.
    """
    zacasna_mapa = images_dir / ZACASNA_PODMAPA
    zacasna_mapa.mkdir(parents=True, exist_ok=True)

    zacasna = zacasna_mapa / f"{material_id}.jpg"
    koncna = koncna_pot(images_dir, material_id)

    try:
        with zacasna.open("wb") as cilj:
            shutil.copyfileobj(vir, cilj)
        # `Path.replace` je na istem datotečnem sistemu atomaren in prepiše
        # obstoječo datoteko brez vmesnega stanja, ko cilja ne bi bilo.
        zacasna.replace(koncna)
    except BaseException:
        zacasna.unlink(missing_ok=True)
        raise

    return koncna


def pobrisi_sliko(pot: Path) -> None:
    """Pobriše sliko, za katero se je izkazalo, da vrstice v bazi ne bo.

    Napake namenoma požre — brisanje je pospravljanje za drugo napako in je ne
    sme prekriti.
    """
    # Sirota na disku je manjše zlo kot napaka, ki povozi prvotno.
    with contextlib.suppress(OSError):
        pot.unlink(missing_ok=True)
