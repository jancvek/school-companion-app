"""Nastavitve prijavljenega starša (V3-R08).

Ena stran s pregledom načinov prijave in dvema dejanjema: poveži Google in
odstrani Google. Odločitve so v `docs/odlocitve/ADR-046`, pravila v
`app/google.py`, poizvedbe v `PrijavaRepository`. Ta modul je prenos.

**Vse tri poti so pod `/admin` in nimajo nobene izjeme** (`ADR-046` B). To ni
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

from app import google
from app.db import NaciniPrijave, PrijavaRepository, SejaUporabnika
from app.dependencies import daj_nastavitve, daj_prijavo, daj_repozitorij_prijave
from app.settings import Settings
from app.strani import daj_predloge, ni_najdeno, zavrnjeno

router = APIRouter(prefix=google.POT_RACUNA)


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
    """Kako se ta starš lahko prijavi, in kaj lahko s tem naredi."""
    if not nastavitve.google_je_nastavljen:
        return _brez_googla(predloge, request)
    nacini = repo.nacini_prijave(seja.user_id)
    return predloge.TemplateResponse(
        request,
        "racun.html",
        {"pogled": _pogled(seja, nacini, google.SPOROCILA_IZIDOV.get(izid or ""))},
    )


@router.post("/google")
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


@router.post("/google/odstrani")
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
