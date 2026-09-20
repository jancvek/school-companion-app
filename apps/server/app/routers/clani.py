"""Člani družine na operaterski strani (V3-R06).

Ena stran s seznamom in dvema obrazcema za dodajanje ter tri vmesne strani —
ponastavitev gesla, deaktivacija, aktivacija. Odločitve so v
`docs/odlocitve/ADR-038`, pravila v `app/clani.py`, poizvedbe v
`ClaniRepository`. Ta modul je prenos: bere obrazec, kliče pravilo, izriše.

Tri vrste zavrnitve in vsaka ima svojo kodo, ker vsaka pomeni drugo pot naprej:

| Kaj | Koda | Kdaj |
|---|---|---|
| tega člana ni | `404` | tuj ali neobstoječ `user_id` — obstoj tujega računa ni podatek za starša |
| dejanje ni tvoje | `403` | sebe, lastnika sistema, zadnjega aktivnega starša |
| stanje že je tako | `409` | deaktivacija deaktiviranega, aktivacija aktivnega |

**Tuj in neznan `user_id` se ne ločita.** Oboje pride iz `ClaniRepository.clan`
kot `None` in oboje dobi isto stran s `404`; razlika v besedilu bi povedala,
da tuj račun obstaja (kriterij `V3-R06`).

Geslo se z obrazca **nikoli ne vrne v izris** — ne ob napaki, ne v skritem
polju. Prav zato dodajanje vmesne strani nima (`ADR-038` F): ta bi geslo
spravila v HTML in v zgodovino brskalnika.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse, Response

from app import clani, prijava
from app.besedilo import CLANI, stevilo_z_besedo
from app.casi import datum
from app.db import ClanDruzine, ClaniRepository, IdentifikatorZaseden, SejaUporabnika
from app.dependencies import daj_prijavo, daj_repozitorij_clanov
from app.models import VLOGA_OTROK, VLOGA_STARS
from app.strani import daj_predloge, ni_dovoljeno, ni_najdeno, zavrnjeno

#: Predpona poti. Pod `/admin`, torej za sejo in s CSRF žetonom (`ADR-035`).
PREDPONA = "/admin/family"

router = APIRouter(prefix=PREDPONA)

SPOROCILO_NI_CLANA = (
    "Tega člana ni v tvoji družini. Morda je bil naslov napačno prepisan; "
    "na seznamu družine so vsi, ki jih lahko urejaš."
)

#: Slovenski oznaki vlog. Preslikava in ne `if` v predlogi: predloga ne
#: oblikuje (isto pravilo kot pri sklanjanju, `app/besedilo.py`).
#:
#: Ključ je `str` in ne `Vloga`, iz istega razloga kot pri
#: `prijava.NAJKRAJSE_GESLO`: vloga pride iz baze kot navaden niz in
#: vrednost, ki je v tabeli ne bi smelo biti, mora pasti na svoj zapis in
#: ne na `KeyError` sredi izrisa.
OZNAKE_VLOG: dict[str, str] = {VLOGA_STARS: "starš", VLOGA_OTROK: "otrok"}

#: Oznaka stanja računa. Samostalniška in ne pridevniška oblika („aktiven"),
#: da besedilo ne določa spola osebe, ki ji račun pripada.
OZNAKA_AKTIVEN = "aktiven račun"
OZNAKA_DEAKTIVIRAN = "deaktiviran račun"
OZNAKA_BREZ_GESLA = "geslo ni nastavljeno"


@dataclass(frozen=True)
class Pogled:
    """Ena vrstica seznama članov, pripravljena za izris."""

    id: str
    ime: str
    vloga: str
    identifikator: str
    stanje: str
    brez_gesla: bool
    lastnik_sistema: bool
    aktiven: bool
    nastal: str
    #: Ali je to član, ki je prav zdaj prijavljen. Seznam to pove, ker je
    #: ponastavitev lastnega gesla posebna: odjavi te.
    jaz: bool
    #: Katera dejanja seznam sploh ponudi. **Odloči isto pravilo, ki dejanje
    #: tudi zavrne** (`app/clani.py`): ponujen klik, ki se konča s `403`, in
    #: skrit klik, ki bi uspel, sta obe napaki, in dve pravili bi se razšli.
    sme_geslo: bool
    sme_deaktivacijo: bool
    sme_aktivacijo: bool


def _pogled(clan: ClanDruzine, *, seja: SejaUporabnika, aktivnih_starsev: int) -> Pogled:
    sme_deaktivacijo = clan.is_active and (
        clani.zakaj_ne_sme_deaktivirati(
            izvajalec_id=seja.user_id,
            clan_id=clan.user_id,
            clan_vloga=clan.role,
            clan_je_lastnik_sistema=clan.is_system_owner,
            aktivnih_starsev=aktivnih_starsev,
        )
        is None
    )
    return Pogled(
        id=clan.user_id,
        ime=clan.display_name,
        vloga=OZNAKE_VLOG.get(clan.role, clan.role),
        # Poverilnica je po shemi lahko odsotna; stran mora zdržati tudi to.
        identifikator=clan.identifier or "—",
        stanje=OZNAKA_AKTIVEN if clan.is_active else OZNAKA_DEAKTIVIRAN,
        brez_gesla=not clan.geslo_nastavljeno,
        lastnik_sistema=clan.is_system_owner,
        aktiven=clan.is_active,
        nastal=datum(clan.created_at),
        jaz=clan.user_id == seja.user_id,
        sme_geslo=_zavrnitev_gesla(clan, seja) is None,
        sme_deaktivacijo=sme_deaktivacijo,
        sme_aktivacijo=not clan.is_active,
    )


def _stran_seznama(
    predloge: Jinja2Templates,
    request: Request,
    repo: ClaniRepository,
    seja: SejaUporabnika,
    *,
    napaka: str | None = None,
    obrazec: str | None = None,
    vnos: dict[str, str] | None = None,
    koda: int = 200,
) -> Response:
    """Seznam članov; ob napaki isti seznam z besedilom in vrnjenim vnosom.

    Vnos se vrne, da uporabnici ni treba znova tipkati imena — **geslo ne**,
    nikoli. `obrazec` pove, kateremu od obeh obrazcev napaka pripada; brez tega
    bi se sporočilo o otroku pokazalo nad obrazcem za starša.
    """
    aktivnih = repo.aktivnih_starsev()
    vrstice = [
        _pogled(clan, seja=seja, aktivnih_starsev=aktivnih) for clan in repo.clani()
    ]
    return predloge.TemplateResponse(
        request,
        "clani.html",
        {
            "clani": vrstice,
            "skupaj_opis": stevilo_z_besedo(len(vrstice), CLANI),
            "napaka": napaka,
            "obrazec": obrazec,
            "vnos": vnos or {},
            # Nalepka o najkrajšem geslu pride iz istega mesta kot zavrnitev
            # (`prijava.NAJKRAJSE_GESLO`). Vtipkana v predlogo bi se z njo
            # razšla in nihče ne bi opazil: zavrnitev bi govorila resnico,
            # obrazec pa bi lagal.
            "najmanj_otrok": prijava.NAJKRAJSE_GESLO[VLOGA_OTROK],
            "najmanj_stars": prijava.NAJKRAJSE_GESLO[VLOGA_STARS],
        },
        status_code=koda,
    )


def _nazaj() -> RedirectResponse:
    """303 na seznam. Osvežitev strani dejanja ne ponovi."""
    return RedirectResponse(PREDPONA, status_code=303)


@router.get("")
def seznam(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
) -> Response:
    """Člani družine z vlogo in stanjem ter obrazca za dodajanje."""
    return _stran_seznama(predloge, request, repo, seja)


def _dodaj(
    request: Request,
    predloge: Jinja2Templates,
    repo: ClaniRepository,
    seja: SejaUporabnika,
    *,
    vloga: str,
    obrazec: str,
    ime: str,
    identifikator: str,
    napaka_identifikatorja: str | None,
    geslo: str,
    geslo_znova: str,
) -> Response:
    """Skupno telo obeh dodajanj: preveri, ustvari, vrni se na seznam.

    Otrok in starš se ločita v treh rečeh — vlogi, preverbi identifikatorja in
    najkrajšem geslu — in v ničemer drugem. Dve ločeni telesi bi se razšli
    natanko v tistem, kar je skupno (`docs/odlocitve/ADR-038` E).
    """
    vnos = {"ime": ime, "identifikator": identifikator}

    napaka = (
        clani.preveri_prikazno_ime(ime)
        or napaka_identifikatorja
        or clani.preveri_novo_geslo(vloga, geslo, geslo_znova)
    )
    if napaka is not None:
        return _stran_seznama(
            predloge, request, repo, seja, napaka=napaka, obrazec=obrazec, vnos=vnos, koda=400
        )

    try:
        repo.ustvari_clana(
            role=vloga,
            display_name=ime.strip(),
            identifier=prijava.normaliziraj_identifikator(identifikator),
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
            obrazec=obrazec,
            vnos=vnos,
            koda=400,
        )

    return _nazaj()


@router.post("/children")
def dodaj_otroka(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
    ime: Annotated[str, Form()] = "",
    uporabnisko_ime: Annotated[str, Form()] = "",
    geslo: Annotated[str, Form()] = "",
    geslo_znova: Annotated[str, Form()] = "",
) -> Response:
    """Doda otroka: prikazno ime, uporabniško ime, začetno geslo. Brez e-naslova."""
    normalizirano = prijava.normaliziraj_identifikator(uporabnisko_ime)
    return _dodaj(
        request,
        predloge,
        repo,
        seja,
        vloga=VLOGA_OTROK,
        obrazec="otrok",
        ime=ime,
        identifikator=uporabnisko_ime,
        napaka_identifikatorja=clani.preveri_uporabnisko_ime(normalizirano),
        geslo=geslo,
        geslo_znova=geslo_znova,
    )


@router.post("/parents")
def dodaj_starsa(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
    ime: Annotated[str, Form()] = "",
    enaslov: Annotated[str, Form()] = "",
    geslo: Annotated[str, Form()] = "",
    geslo_znova: Annotated[str, Form()] = "",
) -> Response:
    """Doda starša: prikazno ime, e-naslov, začetno geslo.

    Novi starš **ni** lastnik sistema: to zastavico podeli samo migracija in
    pozneje `V3-R05`. Starš, ki bi lahko ustvaril lastnika sistema, bi si ga
    lahko ustvaril tudi sam (`ADR-038` G).
    """
    normaliziran = prijava.normaliziraj_identifikator(enaslov)
    return _dodaj(
        request,
        predloge,
        repo,
        seja,
        vloga=VLOGA_STARS,
        obrazec="stars",
        ime=ime,
        identifikator=enaslov,
        napaka_identifikatorja=clani.preveri_enaslov(normaliziran),
        geslo=geslo,
        geslo_znova=geslo_znova,
    )


# --- Ponastavitev gesla ----------------------------------------------------


def _zavrnitev_gesla(clan: ClanDruzine, seja: SejaUporabnika) -> str | None:
    return clani.zakaj_ne_sme_ponastaviti_gesla(
        izvajalec_id=seja.user_id,
        clan_id=clan.user_id,
        clan_je_lastnik_sistema=clan.is_system_owner,
    )


def _stran_gesla(
    predloge: Jinja2Templates,
    request: Request,
    repo: ClaniRepository,
    clan: ClanDruzine,
    seja: SejaUporabnika,
    *,
    napaka: str | None = None,
    koda: int = 200,
) -> Response:
    return predloge.TemplateResponse(
        request,
        "clani-geslo.html",
        {
            "clan": _pogled(clan, seja=seja, aktivnih_starsev=repo.aktivnih_starsev()),
            # Predlogo od V3-R05 deli z lastnikovo stranjo, zato naslov dejanja
            # ni vpisan vanjo (`docs/odlocitve/ADR-044`).
            "pot_dejanja": f"{PREDPONA}/members/{clan.user_id}/password",
            "pot_nazaj": PREDPONA,
            "napaka": napaka,
            "najmanj": prijava.NAJKRAJSE_GESLO.get(
                clan.role, prijava.NAJKRAJSE_GESLO[VLOGA_STARS]
            ),
        },
        status_code=koda,
    )


@router.get("/members/{user_id}/password")
def potrdi_geslo(
    request: Request,
    user_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
) -> Response:
    """Vmesna stran: čigavo geslo, kaj bo s sejami, in polji za novo geslo.

    Pravilo se preveri **že tu** in ne šele ob oddaji: potrditvena stran za
    dejanje, ki bo zavrnjeno, je obljuba, ki je stran ne more izpolniti.
    """
    clan = repo.clan(user_id)
    if clan is None:
        return ni_najdeno(predloge, request, SPOROCILO_NI_CLANA)
    zavrnitev = _zavrnitev_gesla(clan, seja)
    if zavrnitev is not None:
        return zavrnjeno(predloge, request, zavrnitev)
    return _stran_gesla(predloge, request, repo, clan, seja)


@router.post("/members/{user_id}/password")
def ponastavi_geslo(
    request: Request,
    user_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
    geslo: Annotated[str, Form()] = "",
    geslo_znova: Annotated[str, Form()] = "",
) -> Response:
    """Zapiše novo geslo in prekliče **vse** seje člana, tudi na drugih napravah.

    Kadar starš ponastavi geslo sebi, pade tudi seja, v kateri ravno kliče
    (`ADR-038` D). Preusmeritev na seznam je zato pravilna tudi takrat:
    `SejaMiddleware` ob naslednji zahtevi ne najde seje in pelje na prijavo.
    Posebnega primera tu ni — pravilo je eno.
    """
    clan = repo.clan(user_id)
    if clan is None:
        return ni_najdeno(predloge, request, SPOROCILO_NI_CLANA)

    zavrnitev = _zavrnitev_gesla(clan, seja)
    if zavrnitev is not None:
        return zavrnjeno(predloge, request, zavrnitev)

    napaka = clani.preveri_novo_geslo(clan.role, geslo, geslo_znova)
    if napaka is not None:
        return _stran_gesla(predloge, request, repo, clan, seja, napaka=napaka, koda=400)

    if not repo.ponastavi_geslo(clan.user_id, prijava.zgosti_geslo(geslo), datetime.now(UTC)):
        return ni_dovoljeno(predloge, request, clani.SPOROCILO_NI_SPREMENJENO)
    return _nazaj()


# --- Deaktivacija in aktivacija --------------------------------------------


def _zavrnitev_deaktivacije(
    repo: ClaniRepository, clan: ClanDruzine, seja: SejaUporabnika
) -> str | None:
    return clani.zakaj_ne_sme_deaktivirati(
        izvajalec_id=seja.user_id,
        clan_id=clan.user_id,
        clan_vloga=clan.role,
        clan_je_lastnik_sistema=clan.is_system_owner,
        aktivnih_starsev=repo.aktivnih_starsev(),
    )


def _preveri_stanje(
    clan: ClanDruzine, predloge: Jinja2Templates, request: Request, *, aktiviramo: bool
) -> Response | None:
    """409, kadar je račun že v stanju, v katerega ga peljemo."""
    if aktiviramo and clan.is_active:
        return ni_dovoljeno(predloge, request, clani.SPOROCILO_ZE_AKTIVEN)
    if not aktiviramo and not clan.is_active:
        return ni_dovoljeno(predloge, request, clani.SPOROCILO_ZE_DEAKTIVIRAN)
    return None


def _ovira_stanja(
    predloge: Jinja2Templates,
    request: Request,
    repo: ClaniRepository,
    clan: ClanDruzine,
    seja: SejaUporabnika,
    *,
    aktiviramo: bool,
) -> Response | None:
    """Odgovor, ki dejanje ustavi, ali `None`, kadar ga nič ne ustavi.

    Vrstni red ni poljuben: najprej stanje (`409`), nato pravilo (`403`).
    Član sam je preverjen že pred tem — zavrnitev nad tujim članom bi povedala,
    da tuj član obstaja.
    """
    ze = _preveri_stanje(clan, predloge, request, aktiviramo=aktiviramo)
    if ze is not None:
        return ze

    if aktiviramo:
        return None

    zavrnitev = _zavrnitev_deaktivacije(repo, clan, seja)
    return zavrnjeno(predloge, request, zavrnitev) if zavrnitev is not None else None


def _stran_stanja(
    predloge: Jinja2Templates,
    request: Request,
    repo: ClaniRepository,
    clan: ClanDruzine,
    seja: SejaUporabnika,
    *,
    aktiviramo: bool,
) -> Response:
    return predloge.TemplateResponse(
        request,
        "clani-stanje.html",
        {
            "clan": _pogled(clan, seja=seja, aktivnih_starsev=repo.aktivnih_starsev()),
            "pot_dejanja": (
                f"{PREDPONA}/members/{clan.user_id}/"
                f"{'activate' if aktiviramo else 'deactivate'}"
            ),
            "pot_nazaj": PREDPONA,
            "aktiviramo": aktiviramo,
        },
    )


@router.get("/members/{user_id}/deactivate")
def potrdi_deaktivacijo(
    request: Request,
    user_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
) -> Response:
    """Vmesna stran pred deaktivacijo."""
    clan = repo.clan(user_id)
    if clan is None:
        return ni_najdeno(predloge, request, SPOROCILO_NI_CLANA)
    ustavi = _ovira_stanja(predloge, request, repo, clan, seja, aktiviramo=False)
    return ustavi or _stran_stanja(predloge, request, repo, clan, seja, aktiviramo=False)


@router.post("/members/{user_id}/deactivate")
def deaktiviraj(
    request: Request,
    user_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
) -> Response:
    """Deaktivira člana in prekliče njegove seje. Njegovih podatkov ne briše."""
    clan = repo.clan(user_id)
    if clan is None:
        return ni_najdeno(predloge, request, SPOROCILO_NI_CLANA)
    ustavi = _ovira_stanja(predloge, request, repo, clan, seja, aktiviramo=False)
    if ustavi is not None:
        return ustavi
    if not repo.nastavi_aktivnost(clan.user_id, aktiven=False):
        return ni_dovoljeno(predloge, request, clani.SPOROCILO_NI_SPREMENJENO)
    return _nazaj()


@router.get("/members/{user_id}/activate")
def potrdi_aktivacijo(
    request: Request,
    user_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
) -> Response:
    """Vmesna stran pred vrnitvijo računa v uporabo."""
    clan = repo.clan(user_id)
    if clan is None:
        return ni_najdeno(predloge, request, SPOROCILO_NI_CLANA)
    ustavi = _ovira_stanja(predloge, request, repo, clan, seja, aktiviramo=True)
    return ustavi or _stran_stanja(predloge, request, repo, clan, seja, aktiviramo=True)


@router.post("/members/{user_id}/activate")
def aktiviraj(
    request: Request,
    user_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
) -> Response:
    """Vrne račun v uporabo. Sej ne obnovi — izbrisana vrstica se ne vrne."""
    clan = repo.clan(user_id)
    if clan is None:
        return ni_najdeno(predloge, request, SPOROCILO_NI_CLANA)
    ustavi = _ovira_stanja(predloge, request, repo, clan, seja, aktiviramo=True)
    if ustavi is not None:
        return ustavi
    if not repo.nastavi_aktivnost(clan.user_id, aktiven=True):
        return ni_dovoljeno(predloge, request, clani.SPOROCILO_NI_SPREMENJENO)
    return _nazaj()
