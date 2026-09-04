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

from app.storage import ZACASNA_PODMAPA, koncna_pot, shrani_sliko


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
    pot = shrani_sliko(tmp_path, "abc", io.BytesIO(b"vsebina"))

    assert pot == koncna_pot(tmp_path, "abc")
    assert pot.read_bytes() == b"vsebina"


def test_med_pisanjem_koncne_poti_se_ni(tmp_path: Path) -> None:
    """Bistvo atomarnosti: kdor bere končno pot, je ne vidi na pol zapisane."""
    vir = VirKiOpazuje(b"vsebina", koncna_pot(tmp_path, "abc"))

    shrani_sliko(tmp_path, "abc", vir)

    assert vir.koncna_je_obstajala_med_pisanjem is False
    assert koncna_pot(tmp_path, "abc").read_bytes() == b"vsebina"


def test_ob_napaki_pri_pisanju_ne_ostane_nic(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="na disku ni prostora"):
        shrani_sliko(tmp_path, "abc", VirKiPade(OSError("na disku ni prostora")))

    assert not koncna_pot(tmp_path, "abc").exists()
    assert list((tmp_path / ZACASNA_PODMAPA).iterdir()) == []


def test_ob_prekinitvi_ne_ostane_delna_datoteka(tmp_path: Path) -> None:
    """Prekinjen prenos je lahko izjema, ki ni `Exception` — tudi ta ne sme pustiti sledi."""
    with pytest.raises(KeyboardInterrupt):
        shrani_sliko(tmp_path, "abc", VirKiPade(KeyboardInterrupt()))

    assert not koncna_pot(tmp_path, "abc").exists()
    assert list((tmp_path / ZACASNA_PODMAPA).iterdir()) == []


def test_naredi_mapo_ce_je_se_ni(tmp_path: Path) -> None:
    ciljna = tmp_path / "se-ne-obstaja"

    shrani_sliko(ciljna, "abc", io.BytesIO(b"vsebina"))

    assert koncna_pot(ciljna, "abc").exists()


def test_ponoven_zapis_istega_id_prepise_celoto(tmp_path: Path) -> None:
    """Če se že zapiše drugič, mora biti rezultat cela nova slika, ne mešanica."""
    shrani_sliko(tmp_path, "abc", io.BytesIO(b"dolga-prva-vsebina"))
    shrani_sliko(tmp_path, "abc", io.BytesIO(b"kratka"))

    assert koncna_pot(tmp_path, "abc").read_bytes() == b"kratka"
