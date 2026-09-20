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
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.settings import Settings
from app.subjects import PREDMETI
from app.urnik import DNEVI

dnevnik = logging.getLogger(__name__)

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


#: Oznake dni, kot jih vrne model. Kratke in brez sumnikov: model naj izbira
#: med petimi nizi in ne piše prostega besedila, ki bi ga bilo treba ugibati.
#:
#: Sobote in nedelje na seznamu ni (`docs/odlocitve/ADR-041` F), zato model
#: šestega stolpca urnika, če bi ga slika imela, sploh ne more vrniti.
DNEVI_MODELA: tuple[str, ...] = ("pon", "tor", "sre", "cet", "pet")

#: Oznaka dneva → `date.weekday()`.
_DAN_PO_OZNAKI = dict(zip(DNEVI_MODELA, DNEVI, strict=True))

#: Kode predmetov v promptu, da model preslika sam in ne ugiba naša koda.
_SEZNAM_PREDMETOV = "\n".join(
    f"- {predmet.koda} = {predmet.oznaka}" for predmet in PREDMETI
)

#: Prompt za sliko urnika (V3-R09).
#:
#: Model **preslika sam**, ker ime na šolskem urniku in koda nista isto
#: (`Slovenščina` proti `SLJ`), seznam pa je kratek in ga zna prebrati. Naša
#: koda preslikave ne ugiba: kar ni ena od desetih kod, je nepreslikana celica,
#: ki jo vidi starš (`ADR-028` A2).
#:
#: **Ure se preberejo, a se ne vrnejo.** Urnik je množica predmetov na dan;
#: dve uri istega predmeta zahtevata vsaj eno sliko in sta zato ista reč.
PROMPT_URNIK = f"""\
Na sliki je šolski urnik osnovnošolke. Preberi, kateri predmeti so kateri dan
v tednu.

Vrni eno postavko za vsako celico urnika, ki nosi predmet. Če je isti predmet
v istem dnevu večkrat, ga vseeno vrni večkrat — ure nas ne zanimajo, podvojitve
odstranimo sami.

Za vsako celico vrni:
- day: dan v tednu (pon, tor, sre, cet ali pet),
- text: besedilo, kakršno na tistem mestu res piše, dobesedno,
- subject: koda predmeta s tega seznama, ali prazen niz, če se celica ne ujema
  z nobeno kodo.

Kode predmetov:
{_SEZNAM_PREDMETOV}

Kode si ne izmišljuj in celice ne vrzi stran: če ne veš, katera koda je prava,
pusti subject prazen in v text napiši, kar piše na sliki. Prazne celice, ure,
odmore, kosilo in dneve brez pouka izpusti.

Če urnika s slike ni mogoče brati (prazna stran, zamegljenost, na sliki ni
urnika), nastavi readable na false in vrni prazen seznam celic. V tem primeru
si vsebine ne izmišljuj.\
"""

#: Shema odgovora za urnik. `enum` pri dnevu je namenski: `strict: true` ga
#: uveljavi na strani storitve, zato šesti dan sploh ne pride do nas.
SHEMA_URNIKA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["readable", "cells"],
    "properties": {
        "readable": {
            "type": "boolean",
            "description": "Ali je s slike mogoče brati urnik.",
        },
        "cells": {
            "type": "array",
            "description": "Ena postavka na celico s predmetom; prazno, kadar readable ni true.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["day", "text", "subject"],
                "properties": {
                    "day": {"type": "string", "enum": list(DNEVI_MODELA)},
                    "text": {"type": "string"},
                    "subject": {
                        "type": "string",
                        "description": "Koda predmeta, ali prazen niz, če je ni mogoče določiti.",
                    },
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
        prompt: str | None = None,
        raw_response: str | None = None,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        super().__init__(sporocilo)
        self.sporocilo = sporocilo
        #: Prompt, ki je bil poslan. Nastavljen povsod, kjer je do klica prišlo
        #: — tudi ob časovni omejitvi in ob zavrnitvi. Klic je bil takrat
        #: opravljen in plačan, in kriterij V1-R03 zahteva sled ob **vsakem**
        #: izidu. `None` pomeni, da zahteva ni bila poslana.
        self.prompt = prompt
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


@dataclass(frozen=True)
class CelicaUrnika:
    """Ena prebrana celica urnika.

    `koda` je `None`, kadar celice ni mogoče preslikati na predmet. Taka
    celica se staršu **pokaže** in ne izpade molče (kriterij `V3-R09`):
    napačno prebran urnik bi sicer lagal vsak teden, dokler ga nihče ne
    popravi, in prav zato potrditev ni prijaznost, ampak varovalka.
    """

    #: `date.weekday()`: 0 = ponedeljek … 4 = petek.
    dan: int

    #: Besedilo, kakršno je model prebral. Edino, kar staršu pove, katero
    #: celico naj pogleda.
    besedilo: str

    #: Koda iz `PREDMETI`, ali `None`.
    koda: str | None


@dataclass(frozen=True)
class PredlogUrnika:
    """Kar model prebere z ene slike urnika.

    **Predlog in ne urnik**: v bazo ne gre nikoli, v bazo gre šele to, kar
    starš potrdi (`ADR-028` A2). Revizijske sledi ne nosi (`ADR-042`).
    """

    readable: bool
    celice: tuple[CelicaUrnika, ...]

    @property
    def nepreslikane(self) -> tuple[CelicaUrnika, ...]:
        """Celice, ki jih ni bilo mogoče preslikati na predmet."""
        return tuple(celica for celica in self.celice if celica.koda is None)


#: Kar pot urnika potrebuje od tega modula: iz slike naredi predlog.
KlicalecUrnika = Callable[[Path], PredlogUrnika]


class _Celica(BaseModel):
    """Preverba ene celice iz odgovora."""

    model_config = ConfigDict(extra="forbid")

    day: str
    text: str
    subject: str

    @model_validator(mode="after")
    def _preveri_dan(self) -> "_Celica":
        if self.day not in _DAN_PO_OZNAKI:
            raise ValueError(f"dan „{self.day}“ ni eden od {', '.join(DNEVI_MODELA)}")
        return self


class _Urnik(BaseModel):
    """Preverba celotnega odgovora o urniku.

    `strict: true` je obljuba storitve in ne naša invarianta — isti razlog kot
    pri `_Odgovor`. Tu ta razlika največ pomeni pri `readable`: shema ne zna
    povedati, da neberljiva slika ne sme imeti celic.
    """

    model_config = ConfigDict(extra="forbid")

    readable: bool
    cells: list[_Celica]

    @model_validator(mode="after")
    def _preveri_celice(self) -> "_Urnik":
        if not self.readable and self.cells:
            # Isto sklepanje kot pri vprašanjih: model trdi, da ni znal brati,
            # in hkrati navaja, kaj je prebral. Tega ne popravljamo tiho, ker
            # ne vemo, kateri polovici verjeti.
            raise ValueError(
                f"model je urnik označil kot neberljiv, a vrnil {len(self.cells)} celic"
            )
        return self


def razcleni_urnik(surovo: str) -> PredlogUrnika:
    """Niz iz odgovora v predlog urnika; ob neskladju vrže `NapakaObdelave`.

    Čista funkcija nad nizom, kot `razcleni_odgovor`, in preizkusljiva brez
    omrežja. Preslikava kode je tu in ne v `app/urnik.py`, ker je to razumevanje
    **odgovora modela** in ne pravilo urnika: kar model vrne kot `subject`, je
    trditev, ki jo je treba preveriti proti `PREDMETI`.

    Koda se pred primerjavo očisti presledkov in zapiše z velikimi črkami —
    `mat` in `MAT` sta ista koda, `Šport` pa ni nobena.
    """
    try:
        podatki = json.loads(surovo)
    except json.JSONDecodeError as napaka:
        raise NapakaObdelave(f"Model ni vrnil veljavnega JSON: {napaka.msg}.") from napaka

    try:
        odgovor = _Urnik.model_validate(podatki)
    except ValidationError as napaka:
        prva = napaka.errors()[0]
        kje = ".".join(str(del_) for del_ in prva["loc"]) or "odgovor"
        raise NapakaObdelave(
            f"Odgovor modela ni po pričakovani obliki ({kje}: {prva['msg']})."
        ) from napaka

    znane = {predmet.koda for predmet in PREDMETI}
    celice = []
    for celica in odgovor.cells:
        koda = celica.subject.strip().upper()
        celice.append(
            CelicaUrnika(
                dan=_DAN_PO_OZNAKI[celica.day],
                besedilo=celica.text.strip(),
                koda=koda if koda in znane else None,
            )
        )

    return PredlogUrnika(readable=odgovor.readable, celice=tuple(celice))


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


def sestavi_sporocila(pot: Path, prompt: str = PROMPT) -> list[dict[str, Any]]:
    """Sporočila enega klica: prompt in slika.

    Slika gre kot base64 in ne kot naslov: strežnik slike streže samo pod
    `/admin`, za geslom, zato OpenAI do njih nima dostopa.

    `prompt` je argument od V3-R09, ko je sliko dobil še urnik. Privzetek je
    prompt za snov, da klicna mesta V1-R03 ostanejo, kakršna so.
    """
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
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


@dataclass(frozen=True)
class _SurovOdgovor:
    """Kar en klic prinese nazaj, preden se odgovor razčleni."""

    raw: str
    model: str
    input_tokens: int | None
    output_tokens: int | None


def _izvedi_klic(
    klepet: _OdjemalecKlepeta,
    nastavitve: Settings,
    pot: Path,
    prompt: str,
    ime_sheme: str,
    shema: dict[str, Any],
) -> _SurovOdgovor:
    """En klic modela nad eno sliko; napake pretvori v `NapakaObdelave`.

    Skupen obema klicalcema — snovi (V1-R03) in urniku (V3-R09). Obravnava
    napak storitve je pri obeh ista; podvojena bi se sčasoma razsla prav v
    tistem delu, ki se izvede najredkeje.
    """
    try:
        odgovor = klepet.chat.completions.create(
            model=nastavitve.openai_model,
            messages=sestavi_sporocila(pot, prompt),
            response_format={
                "type": "json_schema",
                "json_schema": {"name": ime_sheme, "strict": True, "schema": shema},
            },
        )
    except APITimeoutError as napaka:
        # `prompt` tudi tu: zahteva je bila poslana, model se ni odzval. Sled
        # brez tega ne bi povedala, kaj je dobil.
        raise NapakaObdelave(
            f"Model se ni odzval v {nastavitve.openai_timeout_seconds:.0f} sekundah.",
            prompt=prompt,
        ) from napaka
    except APIConnectionError as napaka:
        raise NapakaObdelave(
            "Do storitve OpenAI ni bilo mogoče priti. Preveri omrežno povezavo strežnika.",
            prompt=prompt,
        ) from napaka
    except APIStatusError as napaka:
        raise NapakaObdelave(_opis_statusa(napaka), prompt=prompt) from napaka
    except APIError as napaka:
        # Vse ostalo, kar zna vreči `openai` — npr.
        # `APIResponseValidationError`, ki ni podrazred nobene od zgornjih
        # treh. Brez te veje bi taka napaka ušla do splošnega lovilca v
        # `app/obdelava.py` in zapis bi končal v `failed` **brez sledi**,
        # čeprav je bila zahteva poslana in plačana. Prav to je primer,
        # kjer kriterij „shrani se poslani prompt" največ pomeni.
        dnevnik.exception("Klic modela je odpovedal z napako knjižnice openai.")
        raise NapakaObdelave(
            f"Klic modela ni uspel ({type(napaka).__name__}). "
            "Podrobnosti so v dnevniku strežnika.",
            prompt=prompt,
        ) from napaka

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
            prompt=prompt,
            raw_response=surovo,
            model=ime_modela,
            input_tokens=vhodni,
            output_tokens=izhodni,
        )

    return _SurovOdgovor(
        raw=surovo, model=ime_modela, input_tokens=vhodni, output_tokens=izhodni
    )


def _s_sledjo(napaka: NapakaObdelave, prompt: str, surov: _SurovOdgovor) -> NapakaObdelave:
    """Napaki razčlenjevanja doda sled klica.

    `razcleni_odgovor` in `razcleni_urnik` sta čisti funkciji nad nizom in za
    tokene ne vesta; sled zato dopolnimo tu.
    """
    return NapakaObdelave(
        napaka.sporocilo,
        prompt=prompt,
        raw_response=surov.raw,
        model=surov.model,
        input_tokens=surov.input_tokens,
        output_tokens=surov.output_tokens,
    )


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
        surov = _izvedi_klic(klepet, nastavitve, pot, PROMPT, "ucna_snov", SHEMA_ODGOVORA)

        try:
            vsebina = razcleni_odgovor(surov.raw)
        except NapakaObdelave as napaka:
            raise _s_sledjo(napaka, PROMPT, surov) from napaka

        return IzidKlica(
            vsebina=vsebina,
            prompt=PROMPT,
            raw_response=surov.raw,
            model=surov.model,
            input_tokens=surov.input_tokens,
            output_tokens=surov.output_tokens,
        )

    return poklici


def naredi_klicalca_urnika(
    nastavitve: Settings, odjemalec: _OdjemalecKlepeta | None = None
) -> KlicalecUrnika:
    """Sestavi funkcijo `slika urnika → predlog` (V3-R09).

    Svoj klicalec in ne zastavica na obstoječem: prompt, shema in izid so
    drugi; skupen je samo klic, in prav ta je izvlečen v `_izvedi_klic`.

    **Revizijske sledi izid ne nosi** (`docs/odlocitve/ADR-042`): potrjen urnik
    ni odgovor modela, ker ga starš vmes popravi, zato bi sled ob njem
    opisovala nekaj, česar vrstica ne vsebuje. Neuspeh gre v dnevnik.
    """
    klepet: _OdjemalecKlepeta = odjemalec or OpenAI(
        api_key=nastavitve.openai_api_key,
        timeout=nastavitve.openai_timeout_seconds,
    )

    def poklici(pot: Path) -> PredlogUrnika:
        surov = _izvedi_klic(klepet, nastavitve, pot, PROMPT_URNIK, "urnik", SHEMA_URNIKA)

        try:
            return razcleni_urnik(surov.raw)
        except NapakaObdelave as napaka:
            raise _s_sledjo(napaka, PROMPT_URNIK, surov) from napaka

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
