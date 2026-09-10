"""Slovenske oblike števil (`app/besedilo.py`).

Enotski testi funkcije stojijo tu in ne v `test_kvizi.py`, kjer so nastali:
funkcija je v tem popravku dobila svoj modul, ker jo potrebujeta oba
usmerjevalnika, in test naj bo tam, kjer ga bo naslednji bralec iskal.
Sestavljalnik obdrži svoje **integracijske** trditve — da je niz res prišel na
stran.
"""

import pytest

from app.besedilo import SLIKE, SNOVI, VPRASANJA, Oblike, stevilo_z_besedo


@pytest.mark.parametrize(
    ("koliko", "pricakovano"),
    [
        (1, "1 slika"),
        (2, "2 sliki"),
        (3, "3 slike"),
        (4, "4 slike"),
        (5, "5 slik"),
        (0, "0 slik"),
        (11, "11 slik"),
        # 21 in 101 se obe končata z 1, a se ne obnašata enako, in prav v tem
        # je razlog za ostanek pri **sto** namesto zadnje števke: *enaindvajset*
        # se konča z „dvajset" in zahteva rodilnik množine, *sto ena* pa z
        # „ena" in zahteva ednino — kot v „101 dalmatinec".
        (21, "21 slik"),
        (22, "22 slik"),
        (101, "101 slika"),
        (102, "102 sliki"),
        (103, "103 slike"),
        (111, "111 slik"),
        (112, "112 slik"),
    ],
)
def test_slike(koliko: int, pricakovano: str) -> None:
    assert stevilo_z_besedo(koliko, SLIKE) == pricakovano


@pytest.mark.parametrize(
    ("koliko", "pricakovano"),
    [
        (1, "1 vprašanje"),
        (2, "2 vprašanji"),
        (3, "3 vprašanja"),
        (5, "5 vprašanj"),
    ],
)
def test_vprasanja(koliko: int, pricakovano: str) -> None:
    assert stevilo_z_besedo(koliko, VPRASANJA) == pricakovano


@pytest.mark.parametrize(
    ("koliko", "pricakovano"),
    [(1, "1 snov"), (2, "2 snovi"), (3, "3 snovi"), (5, "5 snovi")],
)
def test_snovi(koliko: int, pricakovano: str) -> None:
    """Pri tem samostalniku so tri oblike od štirih enake — in to je pravilno.

    Test obstaja zato, da se ob morebitnem „poenostavljanju" četverice vidi,
    da enakost ni pomota.
    """
    assert stevilo_z_besedo(koliko, SNOVI) == pricakovano


@pytest.mark.parametrize("oblike", [SLIKE, VPRASANJA, SNOVI])
def test_vsaka_cetverica_je_res_cetverica(oblike: Oblike) -> None:
    """Varovalka pred trojico, ki bi tiho izpustila dvojino.

    Prav dvojina je oblika, ki v drugih jezikih ne obstaja in jo je najlažje
    pozabiti — natanko to se je zgodilo starim stranem, ki so pisale „2 slik".
    """
    assert len(oblike) == 4
