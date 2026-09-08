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

    #: `True`, kadar je zapis arhiviran. Spremlja odgovor `410 Gone` in je
    #: namenjeno branju s strani človeka: telefon se odloči po statusni
    #: kodi, ker mu nalagalec datotek telesa odgovora ne izpostavi
    #: zanesljivo (`docs/odlocitve/ADR-011`).
    archived: bool = False


class ZaBrisanjeNaNapravi(BaseModel):
    """Odgovor na `GET /materials/pending-deletion`."""

    #: `id` materialov, ki so arhivirani in jih naprava še ni potrdila.
    ids: list[str]


class PotrditevBrisanja(BaseModel):
    """Telo zahteve `POST /materials/deleted-on-device`."""

    #: `id`, ki jih na napravi ni več. Paket in ne posamezno sporočilo:
    #: en cikel na telefonu naj bo ena zahteva.
    ids: list[str]


class BrisanjePotrjeno(BaseModel):
    """Odgovor na `POST /materials/deleted-on-device`."""

    #: Koliko zapisov je ta zahteva dejansko premaknila. Ponovljena
    #: potrditev vrne `0` in to ni napaka.
    confirmed: int


class Zivost(BaseModel):
    """Odgovor na `GET /health`."""

    status: str
