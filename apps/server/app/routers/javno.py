"""Javna predstavitvena stran na `GET /` (V6-R03).

Edini usmerjevalnik, ki streže HTML zunaj `/admin`. **Nima odvisnosti s sejo,
družino ali bazo** in jih ne sme dobiti (`docs/odlocitve/ADR-059` A): stran je
za vsakogar ista, tudi za prijavljenega starša (`ADR-063` A). Piškotkov ne
bere in ne postavlja, zato gumbi registracije niso obrazci, ampak povezave
(`ADR-063` E).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app import predstavitev, prijava, registracija, sistem
from app.strani import daj_predloge
from app.subjects import PREDMETI

router = APIRouter(tags=["javno"])


@router.get(predstavitev.POT, include_in_schema=False)
def stran(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
) -> Response:
    """Predstavitvena stran. Ali so gumbi registracije, pove `google_na_voljo`
    iz obdelovalca konteksta — brez Googla okno registracije ne more ničesar."""
    barve = {predmet.koda: predmet.barva for predmet in PREDMETI}
    return predloge.TemplateResponse(
        request,
        "predstavitev.html",
        {
            "meni_strani": predstavitev.MENI,
            "sidro": {
                "testi": predstavitev.SIDRO_TESTI,
                "kvizi": predstavitev.SIDRO_KVIZI,
                "kako": predstavitev.SIDRO_KAKO,
                "druzina": predstavitev.SIDRO_DRUZINA,
                "zasebnost": predstavitev.SIDRO_ZASEBNOST,
                "racun": predstavitev.SIDRO_RACUN,
            },
            "ocene": predstavitev.OCENE,
            "statistika": predstavitev.STATISTIKA,
            "barve": barve,
            "besedilo_zasebnost": sistem.BESEDILO_ZASEBNOST_JAVNO,
            "pot_sloga": predstavitev.POT_SLOGA,
            "pot_prijave": prijava.POT_PRIJAVE,
            "pot_registracije": registracija.POT,
        },
    )
