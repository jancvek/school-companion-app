"""Klic vision modela. **Edini modul, ki uvaža `openai`.**

ADR-008 to zahteva izrecno: menjava modela ali ponudnika mora biti sprememba
ene datoteke in ene spremenljivke okolja, ne predelava. Zato tu ni
abstrakcijskih slojev in vtičnikov — `docs/00-namen.md`: *„Kar bi lahko bila
mikrostoritev, naj bo funkcija."*

Modul je razrezan na tri dele, ki se dajo preizkusiti ločeno in brez omrežja:

- `sestavi_sporocila` — kaj pošljemo (čista funkcija nad potjo do slike),
- `razcleni_odgovor` — kaj sprejmemo (čista funkcija nad nizom),
- `naredi_klicalca` — ovoj, ki oboje poveže z odjemalcem OpenAI.

Zunanjemu svetu ta modul ponuja `Klicalec`: `Path → IzidKlica`. Kdo ga je
naredil, obdelava ne ve — v testih je to preprosta funkcija.
"""

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.settings import Settings

#: Najmanj in največ vprašanj, ki jih sme vrniti model (kriterij: 5-10).
#:
#: Meja **ni** v shemi, ki jo pošljemo storitvi: strukturiran izhod z
#: `strict: true` ne podpira `minItems`/`maxItems`. Zato jo uveljavimo tu, ob
#: sprejemu. Odgovor s tremi vprašanji je napaka in ne tiho sprejet rezultat.
NAJMANJ_VPRASANJ = 5
NAJVEC_VPRASANJ = 10

#: Prompt, kakršen gre modelu. Shrani se v celoti ob vsakem zapisu — oznaka
#: različice bi po spremembi te konstante kazala napačno vsebino.
PROMPT = """\
Si pomočnik za osnovnošolsko učenko. Na sliki je stran iz njenega zvezka,
učbenika ali fotografija šolske table. Snov je v slovenščini.

Naredi troje:

1. PREPIS: prepiši vse besedilo s slike dobesedno, vključno z rokopisom.
   Ohrani vrstni red in razdelitev na odstavke. Formul in računov ne
   razlagaj — samo prepiši jih. Če česa ne moreš razbrati, na tistem mestu
   napiši [neberljivo].

2. POVZETEK: v dveh do štirih stavkih povej, kaj je vsebina te strani, tako
   da učenka že po povzetku ve, katera snov je to.

3. VPRAŠANJA: sestavi med 5 in 10 vprašanj za ponavljanje te snovi, s
   pričakovanimi odgovori. Vprašanja naj izhajajo izključno iz te strani in
   naj ne zahtevajo znanja, ki ga na njej ni. Prilagodi jih osnovnošolki.

Vse odgovarjaj v slovenščini.

Če slika ni berljiva ali na njej ni učne snovi (prazna stran, prst čez
objektiv, popolna zamegljenost), nastavi readable na false, transcript in
summary pusti prazna in vrni prazen seznam vprašanj. V tem primeru si
vsebine ne izmišljuj.\
"""

#: Shema odgovora. `strict: true` pomeni, da storitev jamči obliko — polja so
#: vedno vsa prisotna, tudi pri neberljivi sliki (takrat prazna).
SHEMA_ODGOVORA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["readable", "transcript", "summary", "questions"],
    "properties": {
        "readable": {
            "type": "boolean",
            "description": "Ali je s slike mogoče brati učno snov.",
        },
        "transcript": {"type": "string", "description": "Dobesedni prepis besedila."},
        "summary": {"type": "string", "description": "Povzetek v dveh do štirih stavkih."},
        "questions": {
            "type": "array",
            "description": "Med 5 in 10 vprašanj; prazno, kadar readable ni true.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["question", "answer"],
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                },
            },
        },
    },
}


class NapakaObdelave(Exception):
    """Klic ni uspel ali odgovor ni bil uporaben.

    Nosi tudi tisti del revizijske sledi, ki je do napake že nastal. Brez tega
    bi bil `status='failed'` zapis brez dokaza: prav surov odgovor je takrat
    edino, iz česar se da videti, kaj je model v resnici vrnil.

    Sporočilo je v slovenščini in pove, kaj se je zgodilo — ne gola sled
    izjeme (`docs/CLAUDE.md`, merilo dokončanosti).
    """

    def __init__(
        self,
        sporocilo: str,
        *,
        raw_response: str | None = None,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        super().__init__(sporocilo)
        self.sporocilo = sporocilo
        self.raw_response = raw_response
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


@dataclass(frozen=True)
class VprasanjeModela:
    """Eno vprašanje s pričakovanim odgovorom, kot ga je vrnil model."""

    question: str
    answer: str


@dataclass(frozen=True)
class VsebinaOdgovora:
    """Razčlenjena vsebina odgovora."""

    readable: bool
    transcript: str
    summary: str
    questions: tuple[VprasanjeModela, ...]


@dataclass(frozen=True)
class IzidKlica:
    """Vse, kar en klic modela prinese nazaj — vsebina in revizijska sled."""

    vsebina: VsebinaOdgovora
    prompt: str
    raw_response: str
    model: str
    input_tokens: int | None
    output_tokens: int | None


#: Kar obdelava potrebuje od tega modula: iz poti do slike naredi izid.
#:
#: Tip in ne razred: v testih je to navadna funkcija, ki ne ve za OpenAI.
Klicalec = Callable[[Path], IzidKlica]


class _Vprasanje(BaseModel):
    """Preverba enega vprašanja iz odgovora."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class _Odgovor(BaseModel):
    """Preverba celotnega odgovora.

    `strict: true` v shemi je obljuba storitve, ne naša invarianta. Odgovor gre
    zato vseeno skozi to preverbo — tudi zato, ker `strict` ne zna povedati
    „med 5 in 10" (odločitev 8 v `docs/plan/V1-R03.md`).
    """

    model_config = ConfigDict(extra="forbid")

    readable: bool
    transcript: str
    summary: str
    questions: list[_Vprasanje]

    @model_validator(mode="after")
    def _preveri_stevilo_vprasanj(self) -> "_Odgovor":
        koliko = len(self.questions)

        if not self.readable:
            # Neberljiva slika z vprašanji si nasprotuje: model trdi, da ni
            # znal brati, in hkrati sprašuje o vsebini. Tega ne popravljamo
            # tiho, ker ne vemo, kateri polovici verjeti.
            if koliko:
                raise ValueError(
                    f"model je sliko označil kot neberljivo, a vrnil {koliko} vprašanj"
                )
            return self

        if not NAJMANJ_VPRASANJ <= koliko <= NAJVEC_VPRASANJ:
            raise ValueError(
                f"model je vrnil {koliko} vprašanj, pričakovanih je "
                f"{NAJMANJ_VPRASANJ}-{NAJVEC_VPRASANJ}"
            )
        return self


def _slika_kot_podatkovni_url(pot: Path) -> str:
    """Slika z diska kot `data:` URL, kot ga zahteva vsebina sporočila."""
    return "data:image/jpeg;base64," + base64.b64encode(pot.read_bytes()).decode("ascii")


def sestavi_sporocila(pot: Path) -> list[dict[str, Any]]:
    """Sporočila enega klica: prompt in slika.

    Slika gre kot base64 in ne kot naslov: strežnik je za Tailscale in OpenAI
    do njega nima dostopa.
    """
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": _slika_kot_podatkovni_url(pot)}},
            ],
        }
    ]


def razcleni_odgovor(surovo: str) -> VsebinaOdgovora:
    """Niz iz odgovora v preverjeno vsebino; ob neskladju vrže `NapakaObdelave`.

    Klicatelj mora surov niz shraniti **pred** to funkcijo, ne za njo — kadar
    razčlenitev pade, je prav ta niz edino, kar pojasni zakaj.
    """
    try:
        podatki = json.loads(surovo)
    except json.JSONDecodeError as napaka:
        raise NapakaObdelave(f"Model ni vrnil veljavnega JSON: {napaka.msg}.") from napaka

    try:
        odgovor = _Odgovor.model_validate(podatki)
    except ValidationError as napaka:
        prva = napaka.errors()[0]
        kje = ".".join(str(del_) for del_ in prva["loc"]) or "odgovor"
        raise NapakaObdelave(
            f"Odgovor modela ni po pričakovani obliki ({kje}: {prva['msg']})."
        ) from napaka

    return VsebinaOdgovora(
        readable=odgovor.readable,
        transcript=odgovor.transcript,
        summary=odgovor.summary,
        questions=tuple(
            VprasanjeModela(question=v.question, answer=v.answer) for v in odgovor.questions
        ),
    )


class _OdjemalecKlepeta(Protocol):
    """Kar `naredi_klicalca` potrebuje od odjemalca OpenAI.

    Ožji tip od `OpenAI` zato, da se v testih podtakne preprost predmet in ne
    cel lažni odjemalec — isti razlog kot pri `BereBajte` v `app/storage.py`.
    """

    @property
    def chat(self) -> Any: ...


def naredi_klicalca(nastavitve: Settings, odjemalec: _OdjemalecKlepeta | None = None) -> Klicalec:
    """Sestavi funkcijo `slika → izid` nad enim odjemalcem OpenAI.

    Odjemalec nastane enkrat in ne ob vsakem klicu: nosi bazen povezav in
    nastavljeno časovno omejitev.
    """
    klepet: _OdjemalecKlepeta = odjemalec or OpenAI(
        api_key=nastavitve.openai_api_key,
        timeout=nastavitve.openai_timeout_seconds,
    )

    def poklici(pot: Path) -> IzidKlica:
        try:
            odgovor = klepet.chat.completions.create(
                model=nastavitve.openai_model,
                messages=sestavi_sporocila(pot),
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "ucna_snov",
                        "strict": True,
                        "schema": SHEMA_ODGOVORA,
                    },
                },
            )
        except APITimeoutError as napaka:
            raise NapakaObdelave(
                f"Model se ni odzval v {nastavitve.openai_timeout_seconds:.0f} sekundah."
            ) from napaka
        except APIConnectionError as napaka:
            raise NapakaObdelave(
                "Do storitve OpenAI ni bilo mogoče priti. Preveri omrežno povezavo strežnika."
            ) from napaka
        except APIStatusError as napaka:
            raise NapakaObdelave(_opis_statusa(napaka)) from napaka

        uporaba = getattr(odgovor, "usage", None)
        vhodni = getattr(uporaba, "prompt_tokens", None)
        izhodni = getattr(uporaba, "completion_tokens", None)
        # Ime beremo iz odgovora in ne iz nastavitve: storitev zna vzdevek
        # (`gpt-4.1`) razrešiti v konkretno različico, in za primerjavo med
        # modeli je merodajno prav to, kar je res odgovorilo.
        ime_modela = getattr(odgovor, "model", None) or nastavitve.openai_model

        surovo = odgovor.choices[0].message.content if odgovor.choices else None
        if not surovo:
            raise NapakaObdelave(
                "Model je vrnil prazen odgovor.",
                raw_response=surovo,
                model=ime_modela,
                input_tokens=vhodni,
                output_tokens=izhodni,
            )

        try:
            vsebina = razcleni_odgovor(surovo)
        except NapakaObdelave as napaka:
            # Sled dopolnimo tu, ker je `razcleni_odgovor` čista funkcija nad
            # nizom in za tokene ne ve.
            raise NapakaObdelave(
                napaka.sporocilo,
                raw_response=surovo,
                model=ime_modela,
                input_tokens=vhodni,
                output_tokens=izhodni,
            ) from napaka

        return IzidKlica(
            vsebina=vsebina,
            prompt=PROMPT,
            raw_response=surovo,
            model=ime_modela,
            input_tokens=vhodni,
            output_tokens=izhodni,
        )

    return poklici


def _opis_statusa(napaka: APIStatusError) -> str:
    """Napaka storitve v stavku, ki operaterju pove, kaj naj naredi."""
    if napaka.status_code in (401, 403):
        return (
            "Storitev OpenAI je zavrnila ključ (HTTP "
            f"{napaka.status_code}). Preveri OPENAI_API_KEY v apps/server/.env."
        )
    if napaka.status_code == 429:
        return (
            "Storitev OpenAI je zavrnila zahtevo zaradi omejitve pogostosti ali "
            "porabljene kvote (HTTP 429). Poskusi znova pozneje."
        )
    if napaka.status_code >= 500:
        return (
            f"Napaka na strani storitve OpenAI (HTTP {napaka.status_code}). "
            "Poskusi znova pozneje."
        )
    return f"Storitev OpenAI je zahtevo zavrnila (HTTP {napaka.status_code})."
