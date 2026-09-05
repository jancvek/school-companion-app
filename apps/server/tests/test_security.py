"""Testi za primerjavo API ključa.

Ločeni od HTTP testov, ker odjemalec nekaterih vnosov sploh ne pusti do
strežnika — ne-ASCII niz v glavi zavrne že sam. Skozi HTTP torej ni mogoče
dokazati, da funkcija tak vnos prenese; tu je.
"""

import pytest

from app.security import je_izvzeta, kljuc_se_ujema

PRAVI = "kljuc-za-teste"


def test_enak_kljuc_se_ujema() -> None:
    assert kljuc_se_ujema(PRAVI, PRAVI) is True


@pytest.mark.parametrize(
    "ponujeni",
    [
        None,
        "",
        "tuj-kljuc",
        "kljuc-za-test",  # za en znak krajši
        "kljuc-za-testee",
        " kljuc-za-teste",
        "KLJUC-ZA-TESTE",
    ],
)
def test_drugacen_kljuc_se_ne_ujema(ponujeni: str | None) -> None:
    assert kljuc_se_ujema(ponujeni, PRAVI) is False


@pytest.mark.parametrize("ponujeni", ["ključ-š-č-ž", "Ä-tuj-kljuc", "日本語"])
def test_ne_ascii_kljuc_vrne_false_in_ne_vrze_izjeme(ponujeni: str) -> None:
    # `secrets.compare_digest` nad nizom z ne-ASCII znaki vrže TypeError.
    # Ključ pride od zunaj, zato tega ne sme povzročiti.
    assert kljuc_se_ujema(ponujeni, PRAVI) is False


def test_ne_ascii_kljuc_se_lahko_tudi_ujema() -> None:
    """Primerjava bajtov ne sme pokvariti ključa, ki je sam ne-ASCII."""
    assert kljuc_se_ujema("ključ-š-č-ž", "ključ-š-č-ž") is True


def test_prazen_pricakovani_kljuc_ne_odpre_streznika() -> None:
    # `secrets.compare_digest(b"", b"")` vrne True. Brez izrecne obrambe bi
    # prazen API_KEY pomenil strežnik, odprt vsakomur, ki pošlje prazno glavo.
    assert kljuc_se_ujema("", "") is False
    assert kljuc_se_ujema(None, "") is False
    assert kljuc_se_ujema("karkoli", "") is False


@pytest.mark.parametrize(
    ("pot", "pricakovano"),
    [
        ("/health", True),
        ("/admin", True),
        ("/admin/", True),
        ("/admin/subjects/MAT", True),
        ("/materials", False),
        ("/", False),
        # Predpona se ne sme ujeti na pot, ki se le začne enako. Golo
        # `startswith("/admin")` bi vse tri odprlo brez ključa.
        ("/administration", False),
        ("/admin-nekaj", False),
        ("/adminmaterials", False),
        # Predpona velja od začetka poti, ne kjerkoli v njej.
        ("/materials/admin", False),
    ],
)
def test_izvzetost_poti(pot: str, pricakovano: bool) -> None:
    assert (
        je_izvzeta(pot, frozenset({"/health"}), frozenset({"/admin"})) is pricakovano
    )
