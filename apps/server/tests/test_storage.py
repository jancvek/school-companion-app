"""Testi za zapis slike na disk.

Ločeni od endpointa, ker gre za lastnost, ki je skozi HTTP ni mogoče videti:
da na končni poti nikoli ni polovične datoteke.

Testi ne krpajo `os` ali `shutil`. Namesto tega podtaknejo vir, ki med branjem
sam pogleda, kaj je takrat na disku — kar dokaže isto, brez globalnih
stranskih učinkov.
"""

import io
from pathlib import Path

import pytest

from app.storage import ZACASNA_PODMAPA, koncna_pot, mapa_druzine, shrani_sliko

#: Družina, v katere mapo pišejo testi.
DRUZINA = "5b0f6c2e-8d3a-4c7e-9a1b-2f4d6e8c0a13"


class VirKiOpazuje:
    """Vir, ki ob prvem branju zabeleži, ali končna pot že obstaja."""

    def __init__(self, vsebina: bytes, koncna: Path) -> None:
        self._vsebina = vsebina
        self._koncna = koncna
        self.koncna_je_obstajala_med_pisanjem: bool | None = None

    def read(self, size: int = -1, /) -> bytes:
        if self.koncna_je_obstajala_med_pisanjem is None:
            self.koncna_je_obstajala_med_pisanjem = self._koncna.exists()
        vrni, self._vsebina = self._vsebina, b""
        return vrni


class VirKiPade:
    """Vir, ki med branjem odpove — prekinjen prenos."""

    def __init__(self, napaka: BaseException) -> None:
        self._napaka = napaka

    def read(self, size: int = -1, /) -> bytes:
        raise self._napaka


def test_zapise_vsebino_na_koncno_pot(tmp_path: Path) -> None:
    pot = shrani_sliko(tmp_path, DRUZINA, "abc", io.BytesIO(b"vsebina"))

    assert pot == koncna_pot(tmp_path, DRUZINA, "abc")
    assert pot.read_bytes() == b"vsebina"


def test_med_pisanjem_koncne_poti_se_ni(tmp_path: Path) -> None:
    """Bistvo atomarnosti: kdor bere končno pot, je ne vidi na pol zapisane."""
    vir = VirKiOpazuje(b"vsebina", koncna_pot(tmp_path, DRUZINA, "abc"))

    shrani_sliko(tmp_path, DRUZINA, "abc", vir)

    assert vir.koncna_je_obstajala_med_pisanjem is False
    assert koncna_pot(tmp_path, DRUZINA, "abc").read_bytes() == b"vsebina"


def test_ob_napaki_pri_pisanju_ne_ostane_nic(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="na disku ni prostora"):
        shrani_sliko(tmp_path, DRUZINA, "abc", VirKiPade(OSError("na disku ni prostora")))

    assert not koncna_pot(tmp_path, DRUZINA, "abc").exists()
    assert list((mapa_druzine(tmp_path, DRUZINA) / ZACASNA_PODMAPA).iterdir()) == []


def test_ob_prekinitvi_ne_ostane_delna_datoteka(tmp_path: Path) -> None:
    """Prekinjen prenos je lahko izjema, ki ni `Exception` — tudi ta ne sme pustiti sledi."""
    with pytest.raises(KeyboardInterrupt):
        shrani_sliko(tmp_path, DRUZINA, "abc", VirKiPade(KeyboardInterrupt()))

    assert not koncna_pot(tmp_path, DRUZINA, "abc").exists()
    assert list((mapa_druzine(tmp_path, DRUZINA) / ZACASNA_PODMAPA).iterdir()) == []


def test_naredi_mapo_ce_je_se_ni(tmp_path: Path) -> None:
    ciljna = tmp_path / "se-ne-obstaja"

    shrani_sliko(ciljna, DRUZINA, "abc", io.BytesIO(b"vsebina"))

    assert koncna_pot(ciljna, DRUZINA, "abc").exists()


def test_ponoven_zapis_istega_id_prepise_celoto(tmp_path: Path) -> None:
    """Če se že zapiše drugič, mora biti rezultat cela nova slika, ne mešanica."""
    shrani_sliko(tmp_path, DRUZINA, "abc", io.BytesIO(b"dolga-prva-vsebina"))
    shrani_sliko(tmp_path, DRUZINA, "abc", io.BytesIO(b"kratka"))

    assert koncna_pot(tmp_path, DRUZINA, "abc").read_bytes() == b"kratka"


# --- Mapa družine (V3-R01) ---


def test_mapa_druzine_je_podmapa_korena(tmp_path: Path) -> None:
    assert mapa_druzine(tmp_path, DRUZINA) == tmp_path / DRUZINA


@pytest.mark.parametrize(
    "neveljaven",
    [
        "",
        "..",
        f"../{DRUZINA}",
        DRUZINA.upper(),
        DRUZINA.replace("-", ""),
        f"{{{DRUZINA}}}",
        f"urn:uuid:{DRUZINA}",
    ],
)
def test_mapa_druzine_sprejme_samo_kanonicen_uuid(tmp_path: Path, neveljaven: str) -> None:
    """Iz `family_id` nastane pot; vse razen kanonične oblike ostane zunaj diska."""
    with pytest.raises(ValueError, match="ni UUID"):
        mapa_druzine(tmp_path, neveljaven)


def test_slika_in_zacasna_mapa_sta_v_mapi_druzine(tmp_path: Path) -> None:
    """`.tmp/` je v mapi družine: isti datotečni sistem kot končno mesto."""
    pot = shrani_sliko(tmp_path, DRUZINA, "abc", io.BytesIO(b"vsebina"))

    assert pot.parent == tmp_path / DRUZINA
    assert (tmp_path / DRUZINA / ZACASNA_PODMAPA).is_dir()
    assert not (tmp_path / ZACASNA_PODMAPA).exists()


def test_isti_id_v_dveh_druzinah_sta_dve_sliki(tmp_path: Path) -> None:
    druga = "9d4c2b1a-7e6f-4d5c-8b3a-1f2e3d4c5b6a"

    shrani_sliko(tmp_path, DRUZINA, "abc", io.BytesIO(b"prva"))
    shrani_sliko(tmp_path, druga, "abc", io.BytesIO(b"druga"))

    assert koncna_pot(tmp_path, DRUZINA, "abc").read_bytes() == b"prva"
    assert koncna_pot(tmp_path, druga, "abc").read_bytes() == b"druga"
