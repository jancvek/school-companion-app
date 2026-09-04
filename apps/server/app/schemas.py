"""Oblike odgovorov."""

from pydantic import BaseModel


class MaterialPrevzet(BaseModel):
    """Odgovor na `POST /materials`."""

    #: UUID, kot ga je poslal telefon.
    id: str

    #: Stanje obdelave na strežniku; v V1-R02 vedno `new`.
    status: str

    #: `True`, če je zapis nastal zdaj; `False`, če je isti `id` že bil prejet.
    #: Telefon oboje šteje za uspeh — polje je tu, da se idempotentnost vidi
    #: od zunaj in da jo je mogoče preizkusiti.
    created: bool


class Zivost(BaseModel):
    """Odgovor na `GET /health`."""

    status: str
