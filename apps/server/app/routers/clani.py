"""Člani družine na operaterski strani (V3-R06, V6-R01).

Ena stran s seznamom in dvema obrazcema za dodajanje ter vmesne strani —
ponastavitev gesla, deaktivacija, aktivacija in, za otroka, preklic prijav.
Odločitve so v `docs/odlocitve/ADR-038`, pravila v `app/clani.py`, poizvedbe v
`ClaniRepository`. Ta modul je prenos: bere obrazec, kliče pravilo, izriše.

**Otrok nima ne uporabniškega imena ne gesla** (V6-R01, `ADR-058`). Starš ga
doda samo s prikaznim imenom in mu telefon poveže s QR kodo
(`POST …/members/{id}/link`); ponastavitev gesla zanj nadomesti „Prekliči
prijave" (`ADR-061`).

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
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse, Response

from app import clani, meni, povezava, prijava
from app.besedilo import CLANI, stevilo_z_besedo
from app.casi import datum
from app.db import ClanDruzine, ClaniRepository, IdentifikatorZaseden, SejaUporabnika
from app.dependencies import daj_prijavo, daj_repozitorij_clanov
from app.models import VLOGA_OTROK, VLOGA_STARS
from app.settings import Settings
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
    #: Kar pokaže kartica člana (V5-R01). `je_otrok` loči skupini; `zacetnica`
    #: je za krožec ob imenu.
    je_otrok: bool = False
    zacetnica: str = ""
    #: „Google in geslo" ali „samo Google"; `None`, kadar Google ni povezan ali
    #: ga ta namestitev nima (`ADR-046` F).
    oznaka_googla: str | None = None
    #: „Nastavi geslo", kadar gesla še ni, sicer „Ponastavi geslo". Pot je ista.
    dejanje_gesla: str = "Ponastavi geslo"
    #: Povezava na urnik otroka; `None` pri staršu.
    href_urnika: str | None = None
    #: Ali kartica ponudi „Poveži telefon" in „Prekliči prijave" (V6-R01).
    #: Odločita isti pravili, ki dejanje tudi zavrneta (`app/clani.py`).
    sme_povezavo: bool = False
    sme_preklic: bool = False


OZNAKA_GOOGLE_IN_GESLO = "Google in geslo"
OZNAKA_SAMO_GOOGLE = "samo Google"


def _pogled(
    clan: ClanDruzine,
    *,
    seja: SejaUporabnika,
    aktivnih_starsev: int,
    google_na_voljo: bool = False,
    vec_otrok: bool = False,
) -> Pogled:
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
        je_otrok=clan.role == VLOGA_OTROK,
        zacetnica=meni.zacetnica(clan.display_name),
        oznaka_googla=(
            (OZNAKA_GOOGLE_IN_GESLO if clan.geslo_nastavljeno else OZNAKA_SAMO_GOOGLE)
            if google_na_voljo and clan.google_povezan
            else None
        ),
        dejanje_gesla="Ponastavi geslo" if clan.geslo_nastavljeno else "Nastavi geslo",
        # `?otrok=` samo pri več kot enem otroku, kot povsod (`ADR-039` B).
        href_urnika=(
            ("/admin/schedule" + (f"?otrok={quote(clan.user_id, safe='')}" if vec_otrok else ""))
            if clan.role == VLOGA_OTROK
            else None
        ),
        sme_povezavo=clani.zakaj_ne_sme_povezati_telefona(
            clan_vloga=clan.role, clan_aktiven=clan.is_active
        )
        is None,
        # Deaktiviran otrok sej nima — padle so ob deaktivaciji —, zato mu
        # kartica preklica ne ponuja; pot sama ga ne zavrne.
        sme_preklic=clan.is_active
        and clani.zakaj_ne_sme_preklicati_prijav(clan_vloga=clan.role) is None,
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
    polje_napake: str | None = None,
    dodaj: str | None = None,
) -> Response:
    """Seznam članov; ob napaki isti seznam z besedilom in vrnjenim vnosom.

    `polje_napake` pove, ob katerem polju se napaka izpiše (V5-R01): `ime`,
    `identifikator` ali `geslo`. `dodaj` (`otrok` ali `stars`) odpre obrazec
    za dodajanje — z gumbom na vrhu strani, brez skripte.

    Vnos se vrne, da uporabnici ni treba znova tipkati imena — **geslo ne**,
    nikoli. `obrazec` pove, kateremu od obeh obrazcev napaka pripada; brez tega
    bi se sporočilo o otroku pokazalo nad obrazcem za starša.
    """
    aktivnih = repo.aktivnih_starsev()
    vsi = repo.clani()
    nastavitve: Settings = request.app.state.nastavitve
    vec_otrok = sum(clan.role == VLOGA_OTROK for clan in vsi) > 1
    vrstice = [
        _pogled(
            clan,
            seja=seja,
            aktivnih_starsev=aktivnih,
            google_na_voljo=nastavitve.google_je_nastavljen,
            vec_otrok=vec_otrok,
        )
        for clan in vsi
    ]
    return predloge.TemplateResponse(
        request,
        "clani.html",
        {
            "otroci": [clan for clan in vrstice if clan.je_otrok],
            "starsi": [clan for clan in vrstice if not clan.je_otrok],
            "skupaj_opis": stevilo_z_besedo(len(vrstice), CLANI),
            "napaka": napaka,
            "polje_napake": polje_napake,
            # Kateri obrazec je odprt: tisti z napako, sicer tisti iz naslova.
            "odprt_obrazec": obrazec or (dodaj if dodaj in ("otrok", "stars") else None),
            "obrazec": obrazec,
            "vnos": vnos or {},
            # Nalepka o najkrajšem geslu pride iz istega mesta kot zavrnitev
            # (`prijava.NAJKRAJSE_GESLO`). Vtipkana v predlogo bi se z njo
            # razšla in nihče ne bi opazil: zavrnitev bi govorila resnico,
            # obrazec pa bi lagal.
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
    dodaj: str | None = None,
) -> Response:
    """Člani družine z vlogo in stanjem ter obrazca za dodajanje.

    `?dodaj=otrok` ali `?dodaj=stars` izriše isto stran z odprtim obrazcem
    (V5-R01); vsaka druga vrednost se prezre.
    """
    return _stran_seznama(predloge, request, repo, seja, dodaj=dodaj)


@router.post("/children")
def dodaj_otroka(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
    ime: Annotated[str, Form()] = "",
) -> Response:
    """Doda otroka **samo s prikaznim imenom** (V6-R01, `ADR-058` A).

    Uporabniškega imena in gesla ni; polji s tema imenoma, če ju kdo pošlje,
    se prezreta. Telefon otroku poveže starš s QR kodo.
    """
    napaka = clani.preveri_prikazno_ime(ime)
    if napaka is not None:
        return _stran_seznama(
            predloge,
            request,
            repo,
            seja,
            napaka=napaka,
            obrazec="otrok",
            vnos={"ime": ime},
            koda=400,
            polje_napake="ime",
        )
    repo.ustvari_otroka(display_name=ime.strip(), ko=datetime.now(UTC))
    return _nazaj()


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
    vnos = {"ime": ime, "identifikator": enaslov}

    # Prva napaka po vrsti polj; ob polju, ki jo je povzročilo, se tudi izpiše.
    napaka, polje = next(
        (
            (besedilo, kje)
            for besedilo, kje in (
                (clani.preveri_prikazno_ime(ime), "ime"),
                (clani.preveri_enaslov(normaliziran), "identifikator"),
                (clani.preveri_novo_geslo(VLOGA_STARS, geslo, geslo_znova), "geslo"),
            )
            if besedilo is not None
        ),
        (None, None),
    )
    if napaka is not None:
        return _stran_seznama(
            predloge,
            request,
            repo,
            seja,
            napaka=napaka,
            obrazec="stars",
            vnos=vnos,
            koda=400,
            polje_napake=polje,
        )

    try:
        repo.ustvari_clana(
            role=VLOGA_STARS,
            display_name=ime.strip(),
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
            obrazec="stars",
            vnos=vnos,
            koda=400,
            polje_napake="identifikator",
        )

    return _nazaj()


# --- Povezava telefona in preklic prijav (V6-R01) ---------------------------


@router.get("/members/{user_id}/link")
def povezava_ni_zaznamek() -> Response:
    """303 na seznam: stran s kodo nastane samo iz obrazca (`ADR-061` D).

    Brez te poti bi osvežen ali ročno vtipkan naslov vrnil `405` — in koda, ki
    jo je starš ravnokar gledal, bi bila videti kot napaka strežnika.
    """
    return _nazaj()


@router.post("/members/{user_id}/link")
def povezi_telefon(
    request: Request,
    user_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
) -> Response:
    """Ustvari povezovalni žeton in izriše QR kodo z gumbom za isti telefon.

    Žeton nastane tu, v čitljivi obliki, in **ne zapusti te zahteve drugače
    kot v izrisu**: v bazi je samo njegova zgostitev (`ADR-061` B). Stran zato
    ni zaznamek in se ne sme shraniti v predpomnilnik (`no-store`).

    Vmesne potrditve ni (`ADR-061` D): posledica je samo, da prejšnja,
    neporabljena koda neha veljati.
    """
    clan = repo.clan(user_id)
    if clan is None:
        return ni_najdeno(predloge, request, SPOROCILO_NI_CLANA)
    zavrnitev = clani.zakaj_ne_sme_povezati_telefona(
        clan_vloga=clan.role, clan_aktiven=clan.is_active
    )
    if zavrnitev is not None:
        return zavrnjeno(predloge, request, zavrnitev)

    zdaj = datetime.now(UTC)
    zeton = prijava.nov_zeton()
    if not repo.ustvari_povezavo(
        clan.user_id,
        token_hash=prijava.zgostitev_zetona(zeton),
        ko=zdaj,
        potece=zdaj + prijava.TRAJANJE_POVEZAVE,
    ):
        return ni_dovoljeno(predloge, request, clani.SPOROCILO_NI_SPREMENJENO)

    naslov = povezava.naslov(zeton)
    odgovor = predloge.TemplateResponse(
        request,
        "clani-povezava.html",
        {
            "clan_ime": clan.display_name,
            "zacetnica": meni.zacetnica(clan.display_name),
            "povezava": naslov,
            "qr": povezava.qr_svg(naslov),
            "minut": int(prijava.TRAJANJE_POVEZAVE.total_seconds() // 60),
            "pot_dejanja": f"{PREDPONA}/members/{clan.user_id}/link",
            "pot_nazaj": PREDPONA,
        },
    )
    odgovor.headers["Cache-Control"] = "no-store"
    return odgovor


@router.get("/members/{user_id}/revoke")
def potrdi_preklic_prijav(
    request: Request,
    user_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
) -> Response:
    """Vmesna stran pred preklicem prijav (`ADR-038` F: potrditev je za posledice)."""
    clan = repo.clan(user_id)
    if clan is None:
        return ni_najdeno(predloge, request, SPOROCILO_NI_CLANA)
    zavrnitev = clani.zakaj_ne_sme_preklicati_prijav(clan_vloga=clan.role)
    if zavrnitev is not None:
        return zavrnjeno(predloge, request, zavrnitev)
    return predloge.TemplateResponse(
        request,
        "clani-preklic.html",
        {
            "clan_ime": clan.display_name,
            "zacetnica": meni.zacetnica(clan.display_name),
            "pot_dejanja": f"{PREDPONA}/members/{clan.user_id}/revoke",
            "pot_nazaj": PREDPONA,
        },
    )


@router.post("/members/{user_id}/revoke")
def preklici_prijave(
    request: Request,
    user_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repo: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
) -> Response:
    """Izbriše vse otrokove seje in neporabljeno kodo (`ADR-061` G).

    Posnetkov na telefonu in na strežniku se ne dotakne; otrok je odjavljen,
    dokler mu starš telefona ne poveže znova.
    """
    clan = repo.clan(user_id)
    if clan is None:
        return ni_najdeno(predloge, request, SPOROCILO_NI_CLANA)
    zavrnitev = clani.zakaj_ne_sme_preklicati_prijav(clan_vloga=clan.role)
    if zavrnitev is not None:
        return zavrnjeno(predloge, request, zavrnitev)
    if not repo.preklici_prijave(clan.user_id):
        return ni_dovoljeno(predloge, request, clani.SPOROCILO_NI_SPREMENJENO)
    return _nazaj()


# --- Ponastavitev gesla ----------------------------------------------------


def _zavrnitev_gesla(clan: ClanDruzine, seja: SejaUporabnika) -> str | None:
    return clani.zakaj_ne_sme_ponastaviti_gesla(
        izvajalec_id=seja.user_id,
        clan_id=clan.user_id,
        clan_vloga=clan.role,
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
            "najmanj": prijava.NAJKRAJSE_GESLO[VLOGA_STARS],
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
