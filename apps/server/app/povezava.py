"""Povezava, ki odpre aplikacijo, in njena QR koda (V6-R01).

Modul ne ve za FastAPI in ne za bazo: dobi žeton, vrne naslov in sliko. Je
**edini modul, ki uvaža `segno`** — menjava knjižnice za izris je sprememba
ene datoteke, isti rez kot pri `app/vision.py` in `openai`.

Odločitve so v `docs/odlocitve/ADR-058` C in `ADR-061` A in C.
"""

import io
from urllib.parse import urlencode

import segno

#: Shema aplikacije iz `apps/mobile/app.json`. Sprememba tam brez spremembe tu
#: bi dala kodo, ki je telefon ne odpre; ujemanje varuje test nad `app.json`.
SHEMA = "school-companion"

#: Pot v aplikaciji; `expo-router` jo razreši v zaslon `app/povezi.tsx`.
POT = "povezi"

#: Ime parametra z žetonom. Kratko, ker vsak znak poveča kodo.
PARAMETER = "z"


def naslov(zeton: str) -> str:
    """Povezava, ki jo nosita QR koda in gumb „Odpri na tem telefonu".

    **Nosi samo žeton** (`ADR-061` C). Naslov strežnika ima aplikacija iz
    gradnje; povezava, ki bi ga nosila, bi bila način, kako telefon poslati k
    tujemu strežniku.
    """
    return f"{SHEMA}://{POT}?{urlencode({PARAMETER: zeton})}"


def qr_svg(vsebina: str) -> str:
    """QR koda kot SVG, ki gre naravnost v predlogo.

    Brez glave XML in brez velikosti: velikost določi slog strani, slika pa se
    razteza z `viewBox`. Barvi sta črna na belem ne glede na temo — bralniki
    obrnjene kode berejo slabše, zato ima koda svoje belo polje tudi v temni
    temi.

    Raven popravljanja napak `M`: koda se bere z drugega zaslona, ne s papirja,
    zato višja raven kupi malo in plača z gostejšo kodo.
    """
    izhod = io.BytesIO()
    segno.make(vsebina, error="m").save(
        izhod,
        kind="svg",
        xmldecl=False,
        svgns=True,
        nl=False,
        omitsize=True,
        scale=6,
        border=4,
        dark="#000",
        light="#fff",
        svgclass="qr-koda",
        lineclass=None,
    )
    return izhod.getvalue().decode("utf-8")
