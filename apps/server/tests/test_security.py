"""Testi za razbiranje žetona iz glave in za izvzetost poti.

Ločeni od HTTP testov, ker odjemalec nekaterih vnosov sploh ne pusti do
strežnika — ne-ASCII niz v glavi zavrne že sam. Skozi HTTP torej ni mogoče
dokazati, da funkcija tak vnos prenese; tu je.

Do V3-R04 je bil tu ključ (`kljuc_se_ujema`) in z njim vprašanje primerjave v
konstantnem času. Žeton tega vprašanja nima: ne primerja se tu, ampak v bazi,
in to prek SHA-256 zgostitve (`app/prijava.py`). Ostane razbiranje glave, ki
je vnos od zunaj in mora prenesti karkoli.
"""

import pytest

from app.security import je_izvzeta, zeton_iz_glave


def test_pravilna_glava_da_zeton() -> None:
    assert zeton_iz_glave("Bearer abc123") == "abc123"


@pytest.mark.parametrize(
    "glava",
    [
        "bearer abc123",
        "BEARER abc123",
        "BeArEr abc123",
    ],
)
def test_shema_se_bere_brez_ozira_na_velikost_crk(glava: str) -> None:
    """RFC 7235: shema ni občutljiva na velikost črk."""
    assert zeton_iz_glave(glava) == "abc123"


@pytest.mark.parametrize(
    "glava",
    [
        None,
        "",
        "abc123",  # brez sheme
        "Basic abc123",  # druga shema
        "Bearer",  # brez presledka in brez žetona
        "Bearer ",  # prazen žeton
        "Bearer    ",  # sami presledki
        "Token abc123",
        "Bearerabc123",  # shema, zlepljena z žetonom
    ],
)
def test_neveljavna_glava_ne_da_zetona(glava: str | None) -> None:
    assert zeton_iz_glave(glava) is None


@pytest.mark.parametrize("glava", ["Bearer žeton-š-č-ž", "Bearer 日本語", "Bearer Ä"])
def test_ne_ascii_zeton_ne_vrze_izjeme(glava: str) -> None:
    """Glava je vnos od zunaj in ne sme sesuti strežnika.

    Tak žeton ne bo ustrezal nobeni seji — zgostitev se ne bo ujela —, a to
    mora ugotoviti baza, ne izjema pri razbiranju.
    """
    assert zeton_iz_glave(glava) is not None


def test_odvecni_presledki_okoli_zetona_ne_stejejo() -> None:
    assert zeton_iz_glave("Bearer   abc123   ") == "abc123"


@pytest.mark.parametrize(
    ("pot", "pricakovano"),
    [
        ("/health", True),
        ("/auth/login", True),
        ("/admin", True),
        ("/admin/", True),
        ("/admin/subjects/MAT", True),
        ("/materials", False),
        ("/quizzes/pending", False),
        # Odjava telefona **ni** izvzeta: brez veljavnega žetona ni seje, ki bi
        # jo bilo mogoče izbrisati (`docs/odlocitve/ADR-036` G).
        ("/auth/logout", False),
        ("/", False),
        # Predpona se ne sme ujeti na pot, ki se le začne enako. Golo
        # `startswith("/admin")` bi vse tri odprlo brez žetona.
        ("/administration", False),
        ("/admin-nekaj", False),
        ("/adminmaterials", False),
        # Predpona velja od začetka poti, ne kjerkoli v njej.
        ("/materials/admin", False),
    ],
)
def test_izvzetost_poti(pot: str, pricakovano: bool) -> None:
    assert (
        je_izvzeta(pot, frozenset({"/health", "/auth/login"}), frozenset({"/admin"})) is pricakovano
    )
