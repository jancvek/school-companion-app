"""`POST /materials` — prevzem ene fotografije s telefona.

Obdelave tu ni. Zahteva V1-R02 pravi, da strežnik sliko sprejme, zapiše in
takoj odgovori; prepis in vprašanja so V1-R03. Zato zapis nastane s stanjem
`new` in nihče ga v tej zahtevi ne premakne naprej.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from app.db import MaterialsRepository
from app.dependencies import daj_nastavitve, daj_repozitorij
from app.models import STATUS_NOV, Material
from app.schemas import MaterialPrevzet
from app.settings import Settings
from app.storage import pobrisi_sliko, shrani_sliko

router = APIRouter()


def v_utc(trenutek: datetime) -> datetime:
    """Čas brez podatka o pasu razumemo kot UTC.

    Telefon pošilja ISO 8601 v UTC (odločitev 3 v planu V1-R01), a to je vnos
    od zunaj. Zapis brez pasu bi sicer v stolpec s pasom prišel z domnevo
    strežnikovega lokalnega časa, kar bi tiho premaknilo uro posnetka.
    """
    if trenutek.tzinfo is None:
        return trenutek.replace(tzinfo=UTC)
    return trenutek.astimezone(UTC)


@router.post("/materials", status_code=201, response_model=MaterialPrevzet)
def prevzemi_material(
    response: Response,
    material_id: Annotated[UUID, Form(alias="id")],
    subject: Annotated[str, Form(min_length=1, max_length=16)],
    taken_at: Annotated[datetime, Form()],
    file: Annotated[UploadFile, File()],
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> MaterialPrevzet:
    """Prevzame sliko in metapodatke; idempotentno glede na `id`.

    `id` je tipiziran kot `UUID`, ne kot `str`. To ni okras: iz njega nastane
    ime datoteke, in nepreverjen niz bi dovolil pisanje izven `images_dir`.
    Neveljavna oblika je zato 422, ne pot do diska.
    """
    identifikator = str(material_id)

    # Preverba pred pisanjem, ne po njem. Če bi datoteko zapisali najprej, bi
    # ponovni prenos istega `id` povozil sliko, ki je na strežniku že bila —
    # vrstica bi ostala prva, vsebina pa bi bila druga.
    obstojeci = repozitorij.poisci(identifikator)
    if obstojeci is not None:
        response.status_code = 200
        # Status beremo iz zapisa in ga ne vpišemo na trdo: v V1-R02 je vedno
        # `new`, v V1-R03 pa bo obdelan zapis že `ready` ali `failed` in
        # odgovor s trdo vpisanim `new` bi lagal.
        return MaterialPrevzet(id=identifikator, status=obstojeci.status, created=False)

    pot = shrani_sliko(nastavitve.images_dir, identifikator, file.file)

    material = Material(
        id=identifikator,
        subject=subject,
        taken_at=v_utc(taken_at),
        image_path=str(pot),
        status=STATUS_NOV,
        received_at=datetime.now(UTC),
    )

    try:
        nastal = repozitorij.vstavi_ce_ga_ni(material)
    except Exception:
        # Slika brez vrstice je sirota, ki je nihče nikoli ne pogleda.
        pobrisi_sliko(pot)
        raise

    if not nastal:
        # Sem pridemo samo ob tekmovanju dveh hkratnih zahtev z istim `id`.
        # Datoteka na disku je veljavna slika tega zapisa, zato ostane.
        response.status_code = 200
        # Status beremo iz zapisa, ki je zmagal, iz istega razloga kot zgoraj.
        zmagovalec = repozitorij.poisci(identifikator)
        status = zmagovalec.status if zmagovalec is not None else STATUS_NOV
        return MaterialPrevzet(id=identifikator, status=status, created=False)

    return MaterialPrevzet(id=identifikator, status=material.status, created=True)
