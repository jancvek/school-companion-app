"""Predmeti kot podatek: barve (V5-R01, `docs/odlocitve/ADR-056` E)."""

import re

from app.subjects import BARVA_NEZNANEGA, PREDMETI, barva_predmeta

#: Barve iz `docs/poc/POC-02.md`, *Ugotovitve → Barvni žetoni*. Prepisane sem
#: in ne prebrane iz modula: test, ki bi bral isti slovar kot koda, bi ostal
#: zelen ob vsaki zamenjavi barve.
BARVE_IZ_POC = {
    "NAR": "#3d7856",
    "MAT": "#2d5a8e",
    "TJA": "#8a3a5b",
    "GEO": "#8b5a26",
    "SLJ": "#a63f3b",
    "LUM": "#6f55a0",
    "ZGO": "#6a5843",
    "TIT": "#44636e",
    "DKE": "#5a7530",
    "GUM": "#2b7a80",
}


class TestBarvePredmetov:
    def test_vsak_predmet_ima_barvo_iz_dogovora(self) -> None:
        assert {predmet.koda: predmet.barva for predmet in PREDMETI} == BARVE_IZ_POC

    def test_barva_je_sestmestna_sestnajstiska_vrednost(self) -> None:
        # Vrednost gre v atribut `style`; karkoli drugega kot `#rrggbb` bi bilo
        # tam besedilo, ki ga nihče ne preverja.
        for predmet in PREDMETI:
            assert re.fullmatch(r"#[0-9a-f]{6}", predmet.barva), predmet.koda

    def test_barva_po_kodi(self) -> None:
        assert barva_predmeta("MAT") == "#2d5a8e"

    def test_neznana_koda_dobi_nevtralno_barvo(self) -> None:
        # Predmet zunaj seznama ostane viden (`subjects.py`), svoje barve pa
        # nima — in ne sme podedovati barve kakega od desetih.
        assert barva_predmeta("XYZ") == BARVA_NEZNANEGA
        assert barva_predmeta('"><b>') == BARVA_NEZNANEGA
        assert BARVA_NEZNANEGA not in BARVE_IZ_POC.values()
