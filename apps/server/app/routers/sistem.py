"""Stran lastnika sistema: odpiranje in urejanje družin (V3-R05).

Seznam družin, stran ene družine in vmesne strani za štiri dejanja —
deaktivacijo in aktivacijo družine ter ponastavitev gesla, deaktivacijo in
aktivacijo starša. Odločitve so v `docs/odlocitve/ADR-044`, pravila v
`app/sistem.py` in `app/clani.py`, poizvedbe v `DruzineRepository` in
`ClaniRepository`. Ta modul je prenos: bere obrazec, kliče pravilo, izriše.

**Za vsakogar razen lastnika sistema ta usmerjevalnik ne obstaja.** Zavrnitev
je odvisnost na `APIRouter` in ne `if` v vsaki poti, zato velja tudi za pot,
ki bo dodana jutri (`dependencies.zahtevaj_lastnika_sistema`, `ADR-044` G).

**Vsebine tujih družin tu ni** (`ADR-044` B): nobena pot tega modula ne bere
`materials`, `questions`, `quizzes`, `quiz_items`, `question_attempts`,
`schedules` ali `schedule_entries`. Lastnik vidi ime družine, datum nastanka,
stanje, števila članov in **starše** poimensko — otroke samo kot število, ker
nad njimi nima nobenega dejanja; ureja jih njihov starš (`V3-R06`).

Kode zavrnitve so iste kot na starševi strani, ker so ista pravila:

| Kaj | Koda | Kdaj |
|---|---|---|
| te družine ali starša ni | `404` | neznana družina, neznan `user_id`, otrok pod `parents/` |
| dejanje ni tvoje | `403` | svoja družina, lastnik sistema, zadnji aktivni starš |
| stanje že je tako | `409` | deaktivacija deaktiviranega, aktivacija aktivnega |

**Družina pride iz naslova in gre v konstruktor `ClaniRepository`**
(`daj_repozitorij_clanov_ciljne_druzine`). Dejanja nad člani zato tečejo skozi
isti repozitorij in ista pravila kot `/admin/family`; `ADR-038` je pravilo o
zadnjem aktivnem staršu obdržal prav za tega klicatelja.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse, Response

from app import clani, prijava, sistem
from app.besedilo import CLANI, DRUZINE, OTROCI, STARSI, stevilo_z_besedo
from app.casi import datum
from app.db import (
    ClanDruzine,
    ClaniRepository,
    DruzinaZaPregled,
    DruzineRepository,
    IdentifikatorZaseden,
    SejaUporabnika,
)
from app.dependencies import (
    daj_repozitorij_clanov_ciljne_druzine,
    daj_repozitorij_druzin,
    zahtevaj_lastnika_sistema,
)
from app.models import VLOGA_STARS
from app.strani import daj_predloge, ni_dovoljeno, ni_najdeno, zavrnjeno

#: Predpona poti. Pod `/admin`, torej za sejo in s CSRF žetonom (`ADR-035`).
PREDPONA = "/admin/system"

#: Zavrnitev visi na usmerjevalniku in ne v endpointih (`ADR-044` G).
router = APIRouter(prefix=PREDPONA, dependencies=[Depends(zahtevaj_lastnika_sistema)])

OZNAKA_PRIZGANA = "aktivna"
OZNAKA_UGASNJENA = "deaktivirana"

SPOROCILO_NI_STARSA = (
    "Tega starša v tej družini ni. Morda je bil naslov napačno prepisan; "
    "na strani družine so vsi, ki jih lahko urejaš."
)


@dataclass(frozen=True)
class PogledDruzine:
    """Ena vrstica seznama družin, pripravljena za izris.

    **Tu ni ničesar, česar lastnik ne sme videti**, ker ni ničesar, česar
    `DruzinaZaPregled` ne bi že omejil (`ADR-044` B). Ta tip samo oblikuje:
    datum v slovenski zapis, stanje v besedo, števila v povedi.
    """

    id: str
    ime: str
    stanje: str
    aktivna: bool
    nastala: str
    #: Števila kot povedi in ne kot gola števila: „1 starš · 2 otroka" mora
    #: biti slovnično pravilno tudi pri ena in pri dva (`app/besedilo.py`).
    starsev_opis: str
    otrok_opis: str
    clanov_opis: str
    #: Ali je to družina, v kateri je lastnik sam. Seznam to pove, ker je
    #: edina, ki je ni mogoče deaktivirati (`app/sistem.py`).
    moja: bool
    #: Katero dejanje seznam sploh ponudi. **Odloči isto pravilo, ki dejanje
    #: tudi zavrne** — isti vzorec kot pri članih (`app/routers/clani.py`).
    sme_deaktivacijo: bool
    sme_aktivacijo: bool


def _pogled_druzine(druzina: DruzinaZaPregled, *, seja: SejaUporabnika) -> PogledDruzine:
    zavrnitev = sistem.zakaj_ne_sme_deaktivirati_druzine(
        druzina_id=druzina.id, lastnikova_druzina_id=seja.family_id
    )
    return PogledDruzine(
        id=druzina.id,
        ime=druzina.name,
        stanje=OZNAKA_PRIZGANA if druzina.is_active else OZNAKA_UGASNJENA,
        aktivna=druzina.is_active,
        nastala=datum(druzina.created_at),
        starsev_opis=stevilo_z_besedo(druzina.starsev, STARSI),
        otrok_opis=stevilo_z_besedo(druzina.otrok, OTROCI),
        clanov_opis=stevilo_z_besedo(druzina.clanov, CLANI),
        moja=druzina.id == seja.family_id,
        sme_deaktivacijo=druzina.is_active and zavrnitev is None,
        sme_aktivacijo=not druzina.is_active,
    )


@dataclass(frozen=True)
class PogledStarsa:
    """En starš tuje družine, kot ga vidi lastnik sistema.

    Manj kot `routers.clani.Pogled`: brez vloge (vsi tu so starši) in brez
    opombe „to si ti", ker je lastnik na tej strani obiskovalec, ne član.
    Ponastavitev lastnega gesla ostane posebna in to pove stran sama.
    """

    id: str
    ime: str
    identifikator: str
    stanje: str
    brez_gesla: bool
    lastnik_sistema: bool
    aktiven: bool
    nastal: str
    jaz: bool
    sme_geslo: bool
    sme_deaktivacijo: bool
    sme_aktivacijo: bool


def _pogled_starsa(
    clan: ClanDruzine, *, seja: SejaUporabnika, aktivnih_starsev: int
) -> PogledStarsa:
    return PogledStarsa(
        id=clan.user_id,
        ime=clan.display_name,
        # Poverilnica je po shemi lahko odsotna; stran mora zdržati tudi to.
        identifikator=clan.identifier or "—",
        stanje="aktiven račun" if clan.is_active else "deaktiviran račun",
        brez_gesla=not clan.geslo_nastavljeno,
        lastnik_sistema=clan.is_system_owner,
        aktiven=clan.is_active,
        nastal=datum(clan.created_at),
        jaz=clan.user_id == seja.user_id,
        sme_geslo=_zavrnitev_gesla(clan, seja) is None,
        sme_deaktivacijo=clan.is_active
        and _zavrnitev_deaktivacije(clan, seja, aktivnih_starsev) is None,
        sme_aktivacijo=not clan.is_active,
    )


def _zavrnitev_gesla(clan: ClanDruzine, seja: SejaUporabnika) -> str | None:
    """Ista funkcija kot na starševi strani — pravilo je eno (`ADR-044` E)."""
    return clani.zakaj_ne_sme_ponastaviti_gesla(
        izvajalec_id=seja.user_id,
        clan_id=clan.user_id,
        clan_je_lastnik_sistema=clan.is_system_owner,
    )


def _zavrnitev_deaktivacije(
    clan: ClanDruzine, seja: SejaUporabnika, aktivnih_starsev: int
) -> str | None:
    """Ista funkcija kot na starševi strani.

    Klicatelj je tu **zunaj ciljne družine**, kar je primer, zaradi katerega je
    `ADR-038` pravilo o zadnjem aktivnem staršu obdržal: brez njega bi lastnik
    lahko ugasnil edinega starša družine in pustil otroke brez nikogar, ki bi
    jim ponastavil geslo.
    """
    return clani.zakaj_ne_sme_deaktivirati(
        izvajalec_id=seja.user_id,
        clan_id=clan.user_id,
        clan_vloga=clan.role,
        clan_je_lastnik_sistema=clan.is_system_owner,
        aktivnih_starsev=aktivnih_starsev,
    )


def _nazaj() -> RedirectResponse:
    """303 na seznam družin. Osvežitev strani dejanja ne ponovi."""
    return RedirectResponse(PREDPONA, status_code=303)


def _nazaj_na_druzino(family_id: str) -> RedirectResponse:
    """303 na stran družine, na kateri se je dejanje zgodilo."""
    return RedirectResponse(f"{PREDPONA}/families/{family_id}", status_code=303)


# --- Seznam družin in odpiranje nove ---------------------------------------


def _stran_seznama(
    predloge: Jinja2Templates,
    request: Request,
    repo: DruzineRepository,
    seja: SejaUporabnika,
    *,
    napaka: str | None = None,
    vnos: dict[str, str] | None = None,
    koda: int = 200,
) -> Response:
    """Seznam družin; ob napaki isti seznam z besedilom in vrnjenim vnosom.

    Vnos se vrne, da lastniku ni treba znova tipkati imen — **gesli ne**,
    nikoli (isto pravilo kot pri članih, `ADR-038` F).
    """
    vrstice = [_pogled_druzine(druzina, seja=seja) for druzina in repo.pregled()]
    return predloge.TemplateResponse(
        request,
        "sistem.html",
        {
            "druzine": vrstice,
            "skupaj_opis": stevilo_z_besedo(len(vrstice), DRUZINE),
            "napaka": napaka,
            "vnos": vnos or {},
            "besedilo_zasebnost": sistem.BESEDILO_ZASEBNOST,
            # Nalepka o najkrajšem geslu pride iz istega mesta kot zavrnitev.
            "najmanj_stars": prijava.NAJKRAJSE_GESLO[VLOGA_STARS],
        },
        status_code=koda,
    )


@router.get("")
def seznam(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[DruzineRepository, Depends(daj_repozitorij_druzin)],
    seja: Annotated[SejaUporabnika, Depends(zahtevaj_lastnika_sistema)],
) -> Response:
    """Vse družine s stanjem in števili ter obrazec za novo družino."""
    return _stran_seznama(predloge, request, repo, seja)


@router.get("/families")
def seznam_znova() -> Response:
    """`GET` na pot, ki obstaja samo kot `POST`, pelje nazaj na seznam.

    Ne zaradi udobja: brez te poti bi Starlette ob neujemanju metode odgovoril
    s **405**, in to še preden bi stekla odvisnost `zahtevaj_lastnika_sistema`.
    Navaden starš bi tako iz razlike med `405` in `404` prebral, da pot
    obstaja — kriterij `V3-R05` pa pravi, da zanj ta stran ne obstaja.

    Z registrirano potjo se odvisnost izvede in starš dobi `404`, enak kot za
    katerikoli izmišljen naslov. Lastnik pride na seznam.

    **Velja za to predpono in ne za `/admin` nasploh:** enako se obnašajo vse
    ostale poti samo s `POST` (`/admin/logout`, `/admin/family/parents`, …),
    kjer pa obstoj poti ni skrivnost. Tu je, zato je tu popravljeno.
    """
    return _nazaj()


@router.post("/families")
def odpri_druzino(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[DruzineRepository, Depends(daj_repozitorij_druzin)],
    seja: Annotated[SejaUporabnika, Depends(zahtevaj_lastnika_sistema)],
    ime_druzine: Annotated[str, Form()] = "",
    ime: Annotated[str, Form()] = "",
    enaslov: Annotated[str, Form()] = "",
    geslo: Annotated[str, Form()] = "",
    geslo_znova: Annotated[str, Form()] = "",
) -> Response:
    """Ustvari družino in v njej prvega starša — eno dejanje, ena transakcija.

    Vmesne potrditve ni, iz istega razloga kot pri dodajanju člana: ta bi
    začetno geslo spravila v skrito polje druge strani in v zgodovino
    brskalnika (`ADR-038` F). Oddani obrazec je sam po sebi premišljeno
    dejanje.

    Preverbe imena, e-naslova in gesla so **iste funkcije** kot na
    `/admin/family`; novo je samo ime družine (`app/sistem.py`).
    """
    vnos = {"ime_druzine": ime_druzine, "ime": ime, "enaslov": enaslov}
    normaliziran = prijava.normaliziraj_identifikator(enaslov)

    napaka = (
        sistem.preveri_ime_druzine(ime_druzine)
        or clani.preveri_prikazno_ime(ime)
        or clani.preveri_enaslov(normaliziran)
        or clani.preveri_novo_geslo(VLOGA_STARS, geslo, geslo_znova)
    )
    if napaka is not None:
        return _stran_seznama(
            predloge, request, repo, seja, napaka=napaka, vnos=vnos, koda=400
        )

    try:
        repo.ustvari_z_prvim_starsem(
            ime_druzine=ime_druzine.strip(),
            prikazno_ime=ime.strip(),
            identifier=normaliziran,
            secret_hash=prijava.zgosti_geslo(geslo),
            ko=datetime.now(UTC),
        )
    except IdentifikatorZaseden:
        return _stran_seznama(
            predloge,
            request,
            repo,
            seja,
            napaka=clani.SPOROCILO_IDENTIFIKATOR_ZASEDEN,
            vnos=vnos,
            koda=400,
        )

    return _nazaj()


# --- Ena družina -----------------------------------------------------------


def _stran_druzine(
    predloge: Jinja2Templates,
    request: Request,
    druzina: DruzinaZaPregled,
    clani_repo: ClaniRepository,
    seja: SejaUporabnika,
) -> Response:
    """Ena družina: števila, stanje, starši in dejanja nad njimi.

    Starši pridejo iz `ClaniRepository`, torej iz repozitorija **z družino v
    konstruktorju** (`ADR-025`); `DruzineRepository` imen ne vrača.
    """
    aktivnih = clani_repo.aktivnih_starsev()
    starsi = [
        _pogled_starsa(clan, seja=seja, aktivnih_starsev=aktivnih)
        for clan in clani_repo.clani()
        if clan.role == VLOGA_STARS
    ]
    return predloge.TemplateResponse(
        request,
        "sistem-druzina.html",
        {
            "druzina": _pogled_druzine(druzina, seja=seja),
            "starsi": starsi,
            "predpona": PREDPONA,
        },
    )


@router.get("/families/{family_id}")
def druzina(
    request: Request,
    family_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[DruzineRepository, Depends(daj_repozitorij_druzin)],
    clani_repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov_ciljne_druzine)],
    seja: Annotated[SejaUporabnika, Depends(zahtevaj_lastnika_sistema)],
) -> Response:
    """Ena družina s starši. Otroci so samo število (`ADR-044` B)."""
    najdena = repo.poisci(family_id)
    if najdena is None:
        return ni_najdeno(predloge, request, sistem.SPOROCILO_NI_DRUZINE)
    return _stran_druzine(predloge, request, najdena, clani_repo, seja)


# --- Stanje družine --------------------------------------------------------


def _ovira_stanja_druzine(
    predloge: Jinja2Templates,
    request: Request,
    druzina: DruzinaZaPregled,
    seja: SejaUporabnika,
    *,
    aktiviramo: bool,
) -> Response | None:
    """Odgovor, ki dejanje ustavi, ali `None`, kadar ga nič ne ustavi.

    Vrstni red je isti kot pri članih: najprej stanje (`409`), nato pravilo
    (`403`). Aktivacija pravila nima — prižgati je mogoče vsako ugasnjeno
    družino, tudi svojo, do katere pa se ne da priti, ker je ni mogoče ugasniti.
    """
    if aktiviramo and druzina.is_active:
        return ni_dovoljeno(predloge, request, sistem.SPOROCILO_ZE_PRIZGANA)
    if not aktiviramo and not druzina.is_active:
        return ni_dovoljeno(predloge, request, sistem.SPOROCILO_ZE_UGASNJENA)
    if aktiviramo:
        return None

    zavrnitev = sistem.zakaj_ne_sme_deaktivirati_druzine(
        druzina_id=druzina.id, lastnikova_druzina_id=seja.family_id
    )
    return zavrnjeno(predloge, request, zavrnitev) if zavrnitev is not None else None


def _stran_stanja_druzine(
    predloge: Jinja2Templates,
    request: Request,
    druzina: DruzinaZaPregled,
    seja: SejaUporabnika,
    *,
    aktiviramo: bool,
) -> Response:
    return predloge.TemplateResponse(
        request,
        "sistem-stanje.html",
        {
            "druzina": _pogled_druzine(druzina, seja=seja),
            "aktiviramo": aktiviramo,
            "pot_dejanja": (
                f"{PREDPONA}/families/{druzina.id}/"
                f"{'activate' if aktiviramo else 'deactivate'}"
            ),
            "pot_nazaj": f"{PREDPONA}/families/{druzina.id}",
        },
    )


def _stanje_druzine(
    request: Request,
    family_id: str,
    predloge: Jinja2Templates,
    repo: DruzineRepository,
    seja: SejaUporabnika,
    *,
    aktiviramo: bool,
    izvedi: bool,
) -> Response:
    """Skupno telo štirih poti: vmesni strani in obe dejanji.

    Eno telo in ne štiri: razlikujejo se v dveh zastavicah in v ničemer
    drugem, štiri kopije pa bi se razšle natanko v preverbi, ki dejanje ustavi
    (isti razlog kot pri `routers.clani._dodaj`).
    """
    druzina = repo.poisci(family_id)
    if druzina is None:
        return ni_najdeno(predloge, request, sistem.SPOROCILO_NI_DRUZINE)

    ustavi = _ovira_stanja_druzine(predloge, request, druzina, seja, aktiviramo=aktiviramo)
    if ustavi is not None:
        return ustavi
    if not izvedi:
        return _stran_stanja_druzine(predloge, request, druzina, seja, aktiviramo=aktiviramo)

    if not repo.nastavi_aktivnost(family_id, aktivna=aktiviramo):
        return ni_dovoljeno(predloge, request, sistem.SPOROCILO_NI_SPREMENJENO)
    return _nazaj_na_druzino(family_id)


@router.get("/families/{family_id}/deactivate")
def potrdi_deaktivacijo_druzine(
    request: Request,
    family_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[DruzineRepository, Depends(daj_repozitorij_druzin)],
    seja: Annotated[SejaUporabnika, Depends(zahtevaj_lastnika_sistema)],
) -> Response:
    """Vmesna stran pred deaktivacijo družine."""
    return _stanje_druzine(
        request, family_id, predloge, repo, seja, aktiviramo=False, izvedi=False
    )


@router.post("/families/{family_id}/deactivate")
def deaktiviraj_druzino(
    request: Request,
    family_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[DruzineRepository, Depends(daj_repozitorij_druzin)],
    seja: Annotated[SejaUporabnika, Depends(zahtevaj_lastnika_sistema)],
) -> Response:
    """Ugasne družino in prekliče seje vseh njenih članov. Podatkov ne briše."""
    return _stanje_druzine(
        request, family_id, predloge, repo, seja, aktiviramo=False, izvedi=True
    )


@router.get("/families/{family_id}/activate")
def potrdi_aktivacijo_druzine(
    request: Request,
    family_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[DruzineRepository, Depends(daj_repozitorij_druzin)],
    seja: Annotated[SejaUporabnika, Depends(zahtevaj_lastnika_sistema)],
) -> Response:
    """Vmesna stran pred vrnitvijo družine v uporabo."""
    return _stanje_druzine(
        request, family_id, predloge, repo, seja, aktiviramo=True, izvedi=False
    )


@router.post("/families/{family_id}/activate")
def aktiviraj_druzino(
    request: Request,
    family_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[DruzineRepository, Depends(daj_repozitorij_druzin)],
    seja: Annotated[SejaUporabnika, Depends(zahtevaj_lastnika_sistema)],
) -> Response:
    """Prižge družino. Sej ne obnovi — izbrisana vrstica se ne vrne."""
    return _stanje_druzine(
        request, family_id, predloge, repo, seja, aktiviramo=True, izvedi=True
    )


# --- Starši ene družine ----------------------------------------------------


def _najdi_starsa(repo: ClaniRepository, user_id: str) -> ClanDruzine | None:
    """Starš te družine, ali `None`.

    **Otrok pod potjo staršev je `None`**, torej `404`. Pot pravi `parents` in
    otroka pod njo ni; lastnik nad otroki nima nobenega dejanja (`ADR-044` B),
    zato bi bil vsak drug odgovor obljuba strani, ki je ni.
    """
    clan = repo.clan(user_id)
    return clan if clan is not None and clan.role == VLOGA_STARS else None


def _stran_gesla(
    predloge: Jinja2Templates,
    request: Request,
    family_id: str,
    clan: ClanDruzine,
    seja: SejaUporabnika,
    aktivnih_starsev: int,
    *,
    napaka: str | None = None,
    koda: int = 200,
) -> Response:
    """Vmesna stran za geslo — **ista predloga** kot na `/admin/family`.

    Naslov dejanja in pot nazaj prideta iz konteksta (`ADR-044`); dve kopiji
    iste potrditvene strani bi se razšli natanko v opozorilu o sejah, ki je
    edini razlog, da stran obstaja.
    """
    return predloge.TemplateResponse(
        request,
        "clani-geslo.html",
        {
            "clan": _pogled_starsa(clan, seja=seja, aktivnih_starsev=aktivnih_starsev),
            "pot_dejanja": (
                f"{PREDPONA}/families/{family_id}/parents/{clan.user_id}/password"
            ),
            "pot_nazaj": f"{PREDPONA}/families/{family_id}",
            "napaka": napaka,
            "najmanj": prijava.NAJKRAJSE_GESLO[VLOGA_STARS],
        },
        status_code=koda,
    )


@router.get("/families/{family_id}/parents/{user_id}/password")
def potrdi_geslo(
    request: Request,
    family_id: str,
    user_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[DruzineRepository, Depends(daj_repozitorij_druzin)],
    clani_repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov_ciljne_druzine)],
    seja: Annotated[SejaUporabnika, Depends(zahtevaj_lastnika_sistema)],
) -> Response:
    """Vmesna stran s poljema za novo geslo starša."""
    if repo.poisci(family_id) is None:
        return ni_najdeno(predloge, request, sistem.SPOROCILO_NI_DRUZINE)
    clan = _najdi_starsa(clani_repo, user_id)
    if clan is None:
        return ni_najdeno(predloge, request, SPOROCILO_NI_STARSA)
    zavrnitev = _zavrnitev_gesla(clan, seja)
    if zavrnitev is not None:
        return zavrnjeno(predloge, request, zavrnitev)
    return _stran_gesla(
        predloge, request, family_id, clan, seja, clani_repo.aktivnih_starsev()
    )


@router.post("/families/{family_id}/parents/{user_id}/password")
def ponastavi_geslo(
    request: Request,
    family_id: str,
    user_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[DruzineRepository, Depends(daj_repozitorij_druzin)],
    clani_repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov_ciljne_druzine)],
    seja: Annotated[SejaUporabnika, Depends(zahtevaj_lastnika_sistema)],
    geslo: Annotated[str, Form()] = "",
    geslo_znova: Annotated[str, Form()] = "",
) -> Response:
    """Zapiše novo geslo starša in prekliče **vse** njegove seje.

    Isti repozitorij in ista transakcija kot na starševi strani: ponastavitev,
    po kateri bi kje ostala veljavna seja, ne bi bila ponastavitev
    (`ADR-038` D).
    """
    if repo.poisci(family_id) is None:
        return ni_najdeno(predloge, request, sistem.SPOROCILO_NI_DRUZINE)
    clan = _najdi_starsa(clani_repo, user_id)
    if clan is None:
        return ni_najdeno(predloge, request, SPOROCILO_NI_STARSA)

    zavrnitev = _zavrnitev_gesla(clan, seja)
    if zavrnitev is not None:
        return zavrnjeno(predloge, request, zavrnitev)

    napaka = clani.preveri_novo_geslo(VLOGA_STARS, geslo, geslo_znova)
    if napaka is not None:
        return _stran_gesla(
            predloge,
            request,
            family_id,
            clan,
            seja,
            clani_repo.aktivnih_starsev(),
            napaka=napaka,
            koda=400,
        )

    if not clani_repo.ponastavi_geslo(
        clan.user_id, prijava.zgosti_geslo(geslo), datetime.now(UTC)
    ):
        return ni_dovoljeno(predloge, request, clani.SPOROCILO_NI_SPREMENJENO)
    return _nazaj_na_druzino(family_id)


def _stanje_starsa(
    request: Request,
    family_id: str,
    user_id: str,
    predloge: Jinja2Templates,
    repo: DruzineRepository,
    clani_repo: ClaniRepository,
    seja: SejaUporabnika,
    *,
    aktiviramo: bool,
    izvedi: bool,
) -> Response:
    """Skupno telo štirih poti nad staršem — isti razlog kot `_stanje_druzine`."""
    if repo.poisci(family_id) is None:
        return ni_najdeno(predloge, request, sistem.SPOROCILO_NI_DRUZINE)
    clan = _najdi_starsa(clani_repo, user_id)
    if clan is None:
        return ni_najdeno(predloge, request, SPOROCILO_NI_STARSA)

    if aktiviramo and clan.is_active:
        return ni_dovoljeno(predloge, request, clani.SPOROCILO_ZE_AKTIVEN)
    if not aktiviramo and not clan.is_active:
        return ni_dovoljeno(predloge, request, clani.SPOROCILO_ZE_DEAKTIVIRAN)

    aktivnih = clani_repo.aktivnih_starsev()
    if not aktiviramo:
        zavrnitev = _zavrnitev_deaktivacije(clan, seja, aktivnih)
        if zavrnitev is not None:
            return zavrnjeno(predloge, request, zavrnitev)

    if not izvedi:
        return predloge.TemplateResponse(
            request,
            "clani-stanje.html",
            {
                "clan": _pogled_starsa(clan, seja=seja, aktivnih_starsev=aktivnih),
                "aktiviramo": aktiviramo,
                "pot_dejanja": (
                    f"{PREDPONA}/families/{family_id}/parents/{clan.user_id}/"
                    f"{'activate' if aktiviramo else 'deactivate'}"
                ),
                "pot_nazaj": f"{PREDPONA}/families/{family_id}",
            },
        )

    if not clani_repo.nastavi_aktivnost(clan.user_id, aktiven=aktiviramo):
        return ni_dovoljeno(predloge, request, clani.SPOROCILO_NI_SPREMENJENO)
    return _nazaj_na_druzino(family_id)


@router.get("/families/{family_id}/parents/{user_id}/deactivate")
def potrdi_deaktivacijo_starsa(
    request: Request,
    family_id: str,
    user_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[DruzineRepository, Depends(daj_repozitorij_druzin)],
    clani_repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov_ciljne_druzine)],
    seja: Annotated[SejaUporabnika, Depends(zahtevaj_lastnika_sistema)],
) -> Response:
    """Vmesna stran pred deaktivacijo starša."""
    return _stanje_starsa(
        request,
        family_id,
        user_id,
        predloge,
        repo,
        clani_repo,
        seja,
        aktiviramo=False,
        izvedi=False,
    )


@router.post("/families/{family_id}/parents/{user_id}/deactivate")
def deaktiviraj_starsa(
    request: Request,
    family_id: str,
    user_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[DruzineRepository, Depends(daj_repozitorij_druzin)],
    clani_repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov_ciljne_druzine)],
    seja: Annotated[SejaUporabnika, Depends(zahtevaj_lastnika_sistema)],
) -> Response:
    """Deaktivira starša in prekliče njegove seje. Njegovih podatkov ne briše."""
    return _stanje_starsa(
        request,
        family_id,
        user_id,
        predloge,
        repo,
        clani_repo,
        seja,
        aktiviramo=False,
        izvedi=True,
    )


@router.get("/families/{family_id}/parents/{user_id}/activate")
def potrdi_aktivacijo_starsa(
    request: Request,
    family_id: str,
    user_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[DruzineRepository, Depends(daj_repozitorij_druzin)],
    clani_repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov_ciljne_druzine)],
    seja: Annotated[SejaUporabnika, Depends(zahtevaj_lastnika_sistema)],
) -> Response:
    """Vmesna stran pred vrnitvijo starša v uporabo.

    Brez te poti bi bila družina z enim samim staršem, ki je deaktiviran,
    zaklenjena za vedno: po `V3-R06` ga aktivira drug starš njegove družine, in
    tega tam ni (`ADR-044` F).
    """
    return _stanje_starsa(
        request,
        family_id,
        user_id,
        predloge,
        repo,
        clani_repo,
        seja,
        aktiviramo=True,
        izvedi=False,
    )


@router.post("/families/{family_id}/parents/{user_id}/activate")
def aktiviraj_starsa(
    request: Request,
    family_id: str,
    user_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[DruzineRepository, Depends(daj_repozitorij_druzin)],
    clani_repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov_ciljne_druzine)],
    seja: Annotated[SejaUporabnika, Depends(zahtevaj_lastnika_sistema)],
) -> Response:
    """Vrne starša v uporabo. Sej ne obnovi."""
    return _stanje_starsa(
        request,
        family_id,
        user_id,
        predloge,
        repo,
        clani_repo,
        seja,
        aktiviramo=True,
        izvedi=True,
    )

