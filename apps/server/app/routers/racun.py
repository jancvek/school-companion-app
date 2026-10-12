"""Nastavitve prijavljenega starša (V3-R08).

Ena stran s pregledom načinov prijave in dvema dejanjema: poveži Google in
odstrani Google. Odločitve so v `docs/odlocitve/ADR-046`, pravila v
`app/google.py`, poizvedbe v `PrijavaRepository`. Ta modul je prenos.

Od `V6-R02` je to tudi **„Moj račun" neodobrene družine**: edina stran, ki jo
vidi starš, čigar zahtevek čaka ali je bil zavrnjen, in pot, po kateri zavrnjeni
svoj račun izbriše (`ADR-057` C in G, `ADR-062` J in L). Googlovi dejanji sta
zanj zaprti; odvisnost `zahtevaj_odobreno_druzino` nosita sami, ker ta
usmerjevalnik kot celota ne sme biti zaprt.

**Vse poti so pod `/admin` in nimajo nobene izjeme** (`ADR-046` B). To ni
podrobnost: povezovanje sproži starš, ki **je** prijavljen, in sejo ter CSRF
žeton mu zato preveri `SejaMiddleware` — ista plast kot vsaki drugi strani.
Pot zunaj `/admin` bi morala oboje ponoviti sama, kar je natanko tisto, čemur
se `app/security.py` izogiba: *„odvisnost je mogoče pozabiti pri novem
usmerjevalniku, predpone pa ne."*

Zunaj `/admin` sta samo tisti dve poti, ki ju sproži nekdo brez seje — začetek
prijave in Googlov povratni klic. Živita v `app/routers/vstop.py`, ob ostalih
poteh prijave.

Stran je **samo starševa**: pod `/admin` otrok ne pride (`prijava.Vrata`), in
`user_id` za vsako poizvedbo pride iz seje, nikoli iz naslova. Zato tu ni
nobene poti z `{user_id}` — lastnik sistema tujih povezav ne ureja
(kriterij 4).
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse, Response

from app import google, prijava
from app.casi import cas, datum
from app.db import ClaniRepository, NaciniPrijave, PrijavaRepository, SejaUporabnika, Zahtevek
from app.dependencies import (
    daj_nastavitve,
    daj_prijavo,
    daj_repozitorij_clanov,
    daj_repozitorij_prijave,
    zahtevaj_odobreno_druzino,
)
from app.meni import ime_druzine
from app.models import STANJE_ODOBRENA, STANJE_ZAVRNJENA
from app.settings import Settings
from app.strani import daj_predloge, ni_dovoljeno, ni_najdeno, zavrnjeno

router = APIRouter(prefix=google.POT_RACUNA)

#: Vmesna stran in izbris zavrnjenega računa (V6-R02, `ADR-062` L).
POT_IZBRISA = f"{google.POT_RACUNA}/izbrisi"

SPOROCILO_NI_ZA_IZBRIS = (
    "Računa ni mogoče izbrisati: izbriše se lahko samo račun, katerega zahtevek "
    "je bil zavrnjen."
)
SPOROCILO_IZBRIS_NI_USPEL = (
    "Računa nisem izbrisal — stanje zahtevka se je medtem spremenilo. Odpri "
    "stran „Moj račun“ in poglej, v kakšnem stanju je."
)


@dataclass(frozen=True)
class Pogled:
    """Stran, pripravljena za izris."""

    ime: str
    identifikator: str
    geslo_nastavljeno: bool
    google_povezan: bool
    google_oznaka: str | None
    #: Ali stran gumb za odstranitev sploh ponudi. **Odloči isto pravilo, ki
    #: odstranitev tudi zavrne** (`app/google.py`) — ponujen klik, ki se konča
    #: z zavrnitvijo, in skrit klik, ki bi uspel, sta obe napaki, dve pravili
    #: pa bi se slej ko prej razšli. Isti vzorec kot pri članih (`V3-R06`).
    sme_odstraniti: bool
    #: Zakaj odstranitve ni — da stran pove razlog, ne samo skrije gumb.
    zakaj_ne_sme: str | None
    sporocilo: str | None


def _pogled(seja: SejaUporabnika, nacini: NaciniPrijave, sporocilo: str | None) -> Pogled:
    zakaj_ne_sme = google.zakaj_ne_sme_odstraniti(ima_geslo=nacini.geslo_nastavljeno)
    return Pogled(
        ime=seja.display_name,
        # Poverilnica je po shemi lahko odsotna; stran mora zdržati tudi to,
        # enako kot seznam članov (`V3-R06`).
        identifikator=nacini.identifikator or "—",
        geslo_nastavljeno=nacini.geslo_nastavljeno,
        google_povezan=nacini.google_povezan,
        google_oznaka=nacini.google_oznaka,
        sme_odstraniti=nacini.google_povezan and zakaj_ne_sme is None,
        zakaj_ne_sme=zakaj_ne_sme if nacini.google_povezan else None,
        sporocilo=sporocilo,
    )


def _brez_googla(predloge: Jinja2Templates, request: Request) -> Response:
    """404 za namestitev, v kateri Google ni nastavljen (`ADR-046` F).

    Ni 503: pot, ki je ta namestitev nima, za obiskovalca ne obstaja, in
    „storitev trenutno ni na voljo" bi obljubljalo, da bo.
    """
    return ni_najdeno(predloge, request, google.SPOROCILO_NI_STRANI)


@router.get("")
def stran(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    repo: Annotated[PrijavaRepository, Depends(daj_repozitorij_prijave)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
    izid: Annotated[str | None, Query()] = None,
) -> Response:
    """Kako se ta starš lahko prijavi, in kaj lahko s tem naredi.

    Za družino, ki **ni odobrena**, je to edina stran pod `/admin` (V6-R02,
    `ADR-057` C): pove, v kakšnem stanju je zahtevek, in nič drugega. Izriše se
    tudi v namestitvi, kjer je bil Google medtem izklopljen — kdor čaka, mora
    svojo stran videti (`ADR-062` J).
    """
    if seja.family_status != STANJE_ODOBRENA:
        return _stran_zahtevka(predloge, request, repo, seja)
    if not nastavitve.google_je_nastavljen:
        return _brez_googla(predloge, request)
    nacini = repo.nacini_prijave(seja.user_id)
    return predloge.TemplateResponse(
        request,
        "racun.html",
        {"pogled": _pogled(seja, nacini, google.SPOROCILA_IZIDOV.get(izid or ""))},
    )


def _stran_zahtevka(
    predloge: Jinja2Templates,
    request: Request,
    repo: PrijavaRepository,
    seja: SejaUporabnika,
) -> Response:
    """„Moj račun" neodobrene družine: čaka (posnetek 07) ali zavrnjena (09).

    Stanje, ki ga ta koda ne pozna, se izriše kot „čaka": zaprto je tako ali
    tako (`zahtevaj_odobreno_druzino`), izbrisa pa ne ponudimo nikomur, ki ni
    izrecno zavrnjen.
    """
    zahtevek = repo.zahtevek(seja.user_id) or Zahtevek(
        enaslov=None, oddan=seja.last_used_at, odlocen=None
    )
    zavrnjena = seja.family_status == STANJE_ZAVRNJENA
    return predloge.TemplateResponse(
        request,
        "racun-zahtevek.html",
        {
            "zavrnjena": zavrnjena,
            "ime": seja.display_name,
            "enaslov": zahtevek.enaslov or "—",
            "druzina": seja.family_name,
            "oddan": cas(zahtevek.oddan),
            "odlocen": datum(zahtevek.odlocen) if zahtevek.odlocen is not None else None,
            "pot_izbrisa": POT_IZBRISA,
            "pot_odjave": prijava.POT_ODJAVE,
        },
    )


def _ovira_izbrisa(seja: SejaUporabnika) -> str | None:
    """Zakaj ta seja računa ne sme izbrisati, ali `None`.

    Samo zavrnjena družina (`ADR-057` G). Čakajoča zahtevka ne more umakniti,
    odobrena družine ne more izbrisati (`ADR-062` K, L).
    """
    return None if seja.family_status == STANJE_ZAVRNJENA else SPOROCILO_NI_ZA_IZBRIS


@router.get("/izbrisi")
def potrdi_izbris(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
) -> Response:
    """Vmesna stran pred izbrisom zavrnjenega računa. Sama ne spremeni ničesar."""
    ovira = _ovira_izbrisa(seja)
    if ovira is not None:
        return zavrnjeno(predloge, request, ovira)
    return predloge.TemplateResponse(
        request,
        "racun-izbris.html",
        {
            "ime": seja.display_name,
            "druzina": ime_druzine(seja.family_name),
            "pot_izbrisa": POT_IZBRISA,
            "pot_nazaj": google.POT_RACUNA,
        },
    )


@router.post("/izbrisi")
def izbrisi(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
) -> Response:
    """Izbriše zavrnjeno družino, starša, poverilnice in seje (`ADR-057` G).

    Družina pride **iz seje**, nikoli iz naslova: starš izbriše samo svojo.
    Pogoj na stanju preveri repozitorij še enkrat, v isti transakciji kot
    izbris — stanje v seji je bilo prebrano na začetku zahteve in je lahko že
    staro (`ADR-062` L).

    Po izbrisu se isti Google račun lahko registrira znova.
    """
    ovira = _ovira_izbrisa(seja)
    if ovira is not None:
        return zavrnjeno(predloge, request, ovira)
    if not clani.izbrisi_zavrnjeno_druzino():
        return ni_dovoljeno(predloge, request, SPOROCILO_IZBRIS_NI_USPEL)
    odgovor = RedirectResponse(f"{prijava.POT_PRIJAVE}?napaka={google.OZNAKA_IZBRISAN}", 303)
    odgovor.delete_cookie(prijava.PISKOTEK_SEJE, path="/")
    return odgovor


@router.post("/google", dependencies=[Depends(zahtevaj_odobreno_druzino)])
def povezi(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
) -> Response:
    """Začne povezovanje: postavi stanje in pelje na Googlov zaslon.

    Stanje nosi **`user_id` iz seje** (`ADR-046` D). Brez tega bi bil tok,
    začet pod eno sejo in vrnjen pod drugo, pripisan napačnemu staršu — in to
    ne bi bilo videti kot napaka, ampak kot uspešna povezava.

    CSRF žeton je preveril `SejaMiddleware`, preden je zahteva prišla sem.
    """
    if not nastavitve.google_je_nastavljen:
        return _brez_googla(predloge, request)
    stanje = google.novo_stanje(google.Namen.POVEZAVA, seja.user_id)
    odgovor = RedirectResponse(
        google.naslov_privolitve(
            client_id=nastavitve.google_client_id,
            domena=nastavitve.domena,
            stanje=stanje,
        ),
        status_code=303,
    )
    google.postavi_stanje(odgovor, stanje)
    return odgovor


@router.post("/google/odstrani", dependencies=[Depends(zahtevaj_odobreno_druzino)])
def odstrani(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    repo: Annotated[PrijavaRepository, Depends(daj_repozitorij_prijave)],
    seja: Annotated[SejaUporabnika, Depends(daj_prijavo)],
) -> Response:
    """Odstrani Google povezavo tega starša.

    **Uporabnika in gesla se ne dotakne** (kriterij 6) in sej ne prekliče:
    starš se ni odjavil, samo enega načina prijave nima več.

    Odstranitev, po kateri na računu ne bi ostala nobena poverilnica za
    prijavo, se zavrne (`ADR-046` G) — s `403` in razlago, kot vsako drugo
    „tega ne smeš" pod `/admin`.
    """
    if not nastavitve.google_je_nastavljen:
        return _brez_googla(predloge, request)

    nacini = repo.nacini_prijave(seja.user_id)
    if nacini.google_credential_id is None:
        # Povezave ni: gumba ni bilo, torej je to podvojena oddaja ali ročen
        # klic. Tiha preusmeritev je tu prava — stanje je že tako, kot naj bi
        # bilo po dejanju.
        return RedirectResponse(google.POT_RACUNA, status_code=303)

    zakaj_ne = google.zakaj_ne_sme_odstraniti(ima_geslo=nacini.geslo_nastavljeno)
    if zakaj_ne is not None:
        return zavrnjeno(predloge, request, zakaj_ne)

    repo.odstrani_google(nacini.google_credential_id, seja.user_id)
    return RedirectResponse(f"{google.POT_RACUNA}?izid={google.IZID_ODSTRANJENO}", status_code=303)
