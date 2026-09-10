"""Oblike odgovorov."""

from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from app.models import Nacin, Ocena

#: Največ poskusov v enem paketu. Kviz ima po `PREDOLG_KVIZ` okoli trideset
#: postavk; meja je tu, da en zahtevek ne more zahtevati neomejenega dela.
NAJVEC_POSKUSOV = 1000


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


class PostavkaZaTelefon(BaseModel):
    """Ena postavka kviza, kot jo dobi telefon."""

    id: str

    #: Zaporedje čez cel kviz, od 1.
    position: int

    #: Zamrznjeno besedilo vprašanja in odgovora (`ADR-016` E).
    question: str
    answer: str

    #: Ali postavka na strežniku že ima poskus (`docs/odlocitve/ADR-019` E).
    answered: bool


class KvizZaTelefonOblika(BaseModel):
    """En kviz s celotno vsebino."""

    id: str
    name: str

    #: Čas objave, vedno z izrecnim pasom UTC.
    created_at: datetime

    items: list[PostavkaZaTelefon]


class CakajociKvizi(BaseModel):
    """Odgovor na `GET /quizzes/pending`: celoten delovni seznam."""

    quizzes: list[KvizZaTelefonOblika]


class PoskusTelefona(BaseModel):
    """En odgovor na eno postavko, kot ga pošlje telefon.

    Preverba je tu in ne v repozitoriju: `id` in `quiz_item_id` sta `UUID` iz
    istega razloga kot `id` pri `POST /materials` — nepreverjen niz od zunaj ne
    sme priti do baze. Časi morajo nositi pas; čas brez pasu bi strežnik moral
    ugibati, in ugibanje premakne uro.
    """

    id: UUID
    quiz_item_id: UUID
    mode: Nacin
    rating: Ocena
    shown_at: AwareDatetime
    revealed_at: AwareDatetime
    answered_at: AwareDatetime


class PaketPoskusov(BaseModel):
    """Telo zahteve `POST /quiz-attempts`.

    Paket in ne posamezno sporočilo, iz istega razloga kot pri potrditvi
    brisanja: en cikel na telefonu naj bo ena zahteva.
    """

    attempts: list[PoskusTelefona] = Field(max_length=NAJVEC_POSKUSOV)


class PoskusiZapisani(BaseModel):
    """Odgovor na `POST /quiz-attempts`."""

    #: Koliko poskusov je ta zahteva dejansko zapisala. Ponovljen paket vrne
    #: `0` in to ni napaka.
    recorded: int


class Zivost(BaseModel):
    """Odgovor na `GET /health`."""

    status: str
