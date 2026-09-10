"""Slovenske oblike števil za operatersko stran.

Do V2-R01 je vmesnik sklanjal na dva načina hkrati: novi strani sestavljalnika
sta pisali „2 vprašanji", starejše pa „2 slik". Drugo je napačno —
slovenščina je pri števnikih **štirioblična** in ima dvojino.

Ta modul je tretji po `app/casi.py` in `app/strani.py` in stoji na istem
načelu: kar potrebujeta oba usmerjevalnika, ni last nobenega od njiju in ima
javno ime, brez podčrtaja.

Oblike so **podatek in ne koda**. Vsak samostalnik je četverica na enem mestu,
da se pri naslednji uporabi ne ugiba znova in da ni treba iskati, kje že je
bilo isto enkrat rešeno.
"""

#: Četverica oblik: za 1, za 2, za 3 in 4, ter za 5 in naprej.
Oblike = tuple[str, str, str, str]

SLIKE: Oblike = ("slika", "sliki", "slike", "slik")
VPRASANJA: Oblike = ("vprašanje", "vprašanji", "vprašanja", "vprašanj")
SNOVI: Oblike = ("snov", "snovi", "snovi", "snovi")


def stevilo_z_besedo(koliko: int, oblike: Oblike) -> str:
    """Število z ustrezno sklonsko obliko samostalnika.

    *1 slika, 2 sliki, 3 slike, 5 slik.* Ločnica teče po **ostanku pri
    deljenju s sto** in ne po samem številu — *101 slika* in *102 sliki* sta
    pravilna, *111 slik* pa tudi, ker je ostanek 11 in ne 1.

    Funkcija pozna število, ne sklona. Kjer besedilo zahteva rodilnik („iz N
    snovi"), je oblika pri vsakem številu ista in se zapiše kot konstanta v
    predlogi — glej `kvizi-predogled.html`.
    """
    ostanek = koliko % 100
    if ostanek == 1:
        return f"{koliko} {oblike[0]}"
    if ostanek == 2:
        return f"{koliko} {oblike[1]}"
    if ostanek in (3, 4):
        return f"{koliko} {oblike[2]}"
    return f"{koliko} {oblike[3]}"
