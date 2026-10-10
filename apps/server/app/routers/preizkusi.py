"""Sestavljanje preizkusa v klepetu z modelom (V4-R07).

Tri poti pod `/admin/assessments` — angleško kot vse ostale in brez besede
`test`, ki je rezervirana za avtomatske teste (`docs/odlocitve/ADR-053` A):

- `POST /compose` izriše urejevalnik iz izbora na strani predmeta — isti
  obrazec in isti izbor kot „Prepisi izbranih", le drugi gumb (`formaction`).
- `GET /compose` pelje na pregled, kot `GET /admin/transcripts`: urejevalnik
  je trenutno delo in ne stanje, zato ga ni mogoče osvežiti ali dati med
  zaznamke.
- `POST /generate` je en klic modela. Kliče ga skripta urejevalnika, odgovor
  je JSON (`docs/odlocitve/ADR-054`, meja 4).

**Strežnik je za model brez stanja in ne shrani ničesar** (`ADR-053` E): delo
v teku živi samo v brskalniku, shranjevanje je `V4-R08`.

**Brskalnik pošlje identifikatorje snovi, ne besedila.** Snov za vsak klic
sestavi strežnik znova, iz seznama predmeta te družine — z isto funkcijo kot
„Prepisi izbranih" (`admin.prepisi_izbora`). Besedilo iz brskalnika bi bilo
trditev o tem, kaj je v zvezku, in meja družine bi bila s tem stvar zaupanja.
"""

import asyncio
import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData
from starlette.responses import Response

from app import preizkus
from app.casi import cas
from app.db import ClaniRepository, MaterialsRepository
from app.dependencies import (
    daj_klicalca_preizkusa,
    daj_nastavitve,
    daj_repozitorij,
    daj_repozitorij_clanov,
)
from app.models import Material
from app.routers import admin
from app.settings import Settings
from app.storage import je_znotraj, mapa_druzine, velikost_slike
from app.strani import daj_predloge
from app.subjects import poisci_predmet
from app.vision import KlicalecPreizkusa, NapakaObdelave

#: Dnevnik porabe: ena vrstica na klic modela (kriterij `V4-R07`). Da vrstica
#: ravni `INFO` res pride v izpis strežnika, poskrbi `app/main.py`.
dnevnik = logging.getLogger(__name__)

PREDPONA = f"{admin.PREDPONA}/assessments"

router = APIRouter(prefix=PREDPONA)

#: Poti, ki ju izriše predloga: obrazec strani predmeta in skripta urejevalnika.
POT_SESTAVLJANJA = f"{PREDPONA}/compose"
POT_GENERIRANJA = f"{PREDPONA}/generate"

SPOROCILO_SAMO_MATEMATIKA = (
    "Testi se za zdaj sestavljajo samo pri matematiki. Vrni se na stran "
    "predmeta MAT, izberi slike in pritisni „Kreiraj test“."
)

SPOROCILO_PRAZEN_IZBOR = (
    "Izberi vsaj eno sliko. Na strani predmeta obkljukaj slike snovi, iz "
    "katere naj nastane test, in znova pritisni „Kreiraj test“."
)

SPOROCILO_BREZ_KLJUCA = (
    "Sestavljanje testov ni nastavljeno: ključ OPENAI_API_KEY_PREIZKUSI manjka. "
    "Vpiši ga v apps/server/.env in zaženi strežnik znova."
)

SPOROCILO_BREZ_ZELJE = "Napiši, kakšen test želiš, in poskusi znova."

SPOROCILO_BREZ_SNOVI = (
    "Izbrane snovi ni več na strani predmeta (arhivirana ali premaknjena), "
    "zato testa ni iz česa sestaviti. Vrni se na stran predmeta in izberi znova."
)

#: Kaj naj starš naredi po neuspelem klicu; doda se vsakemu sporočilu modela.
IZHOD_OB_NEUSPEHU = "Test je ostal nespremenjen. Poskusi znova."


def _polje(obrazec: FormData, ime: str) -> str:
    """Eno besedilno polje obrazca; karkoli drugega velja za neposlano."""
    vrednost = obrazec.get(ime)
    return vrednost if isinstance(vrednost, str) else ""


def _seznam(obrazec: FormData, ime: str) -> list[str]:
    """Vse vrednosti ponovljenega polja, v poslanem vrstnem redu."""
    return [vrednost for vrednost in obrazec.getlist(ime) if isinstance(vrednost, str)]


def _slicica(material: Material, mapa_slik: Path) -> dict[str, Any]:
    """Ena izbrana snov, kot jo pokaže urejevalnik: sličica in čas.

    Za datoteko izven `mapa_slik` velja isto kot za manjkajočo — isti razlog
    kot v `admin._pogled`: pot `/image` bi jo zavrnila in stran bi kazala
    pokvarjeno sliko.
    """
    pot = Path(material.image_path)
    return {
        "id": material.id,
        "cas": cas(material.taken_at),
        "ima_sliko": je_znotraj(mapa_slik, pot) and velikost_slike(pot) is not None,
    }


def _napaka(sporocilo: str, koda: int) -> JSONResponse:
    """Napaka kot JSON: bere jo skripta in jo pokaže v klepetu."""
    return JSONResponse({"napaka": sporocilo}, status_code=koda)


@router.get("/compose")
def sestavi_nazaj() -> RedirectResponse:
    """Urejevalnik nastane samo iz obrazca; `GET` pelje na pregled.

    Isti prijem kot `GET /admin/transcripts`: kdor stran osveži z naslovom v
    vrstici, pristane na pregledu in ne na 405.
    """
    return RedirectResponse(admin.PREDPONA, status_code=303)


@router.post("/compose")
async def sestavi(
    request: Request,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    klicalec: Annotated[KlicalecPreizkusa | None, Depends(daj_klicalca_preizkusa)],
) -> Response:
    """Urejevalnik preizkusa za izbor s strani predmeta. Ničesar ne zapiše.

    V stran gredo **samo snovi, ki so preživele presejanje** skozi seznam
    predmeta te družine: tuj, arhiviran ali neobstoječ identifikator se v
    izrisu ne pojavi in ga skripta zato tudi ne pošlje naprej.

    Obrazec je prebran sam, brez `Form()` parametrov, iz istega razloga kot
    pri `POST /admin/transcripts`: izbor je eno polje na sliko in edina meja
    je velikost telesa (`admin.BREZ_MEJE_POLJ`).
    """
    obrazec = await request.form(max_fields=admin.BREZ_MEJE_POLJ)
    koda = _polje(obrazec, "subject").rstrip("/")

    def stran(**kontekst: Any) -> Response:
        return predloge.TemplateResponse(
            request,
            "preizkus.html",
            {
                "koda": koda,
                # Pot nazaj gre na pregled, kadar bi bila stran predmeta 404.
                "pot_nazaj": (
                    admin.pot_predmeta(koda)
                    if poisci_predmet(koda) is not None
                    else admin.PREDPONA
                ),
                "snovi": [],
                **kontekst,
            },
        )

    if preizkus.navodilo_za(koda) is None:
        return stran(opozorilo=SPOROCILO_SAMO_MATEMATIKA)

    nabor = repozitorij.seznam_po_predmetu(koda)
    _, izbrane = admin.prepisi_izbora(
        repozitorij, admin.imena_otrok(clani), nabor, _seznam(obrazec, "snov")
    )
    if not izbrane:
        return stran(opozorilo=SPOROCILO_PRAZEN_IZBOR)

    mapa_slik = mapa_druzine(nastavitve.images_dir, repozitorij.family_id)
    return stran(
        snovi=[_slicica(material, mapa_slik) for material in izbrane],
        pot_generiranja=POT_GENERIRANJA,
        # Brez ključa urejevalnik dela, le generiranje pove, da ni nastavljeno
        # (kriterij `V4-R07`). Ista drža kot pri urniku brez ključa.
        brez_kljuca=SPOROCILO_BREZ_KLJUCA if klicalec is None else None,
    )


@router.post("/generate")
async def generiraj(
    request: Request,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    klicalec: Annotated[KlicalecPreizkusa | None, Depends(daj_klicalca_preizkusa)],
) -> JSONResponse:
    """En klic modela: nov test ali popravek trenutnega. Ničesar ne zapiše.

    Telo je obrazec in ne JSON, da CSRF žeton preveri ista plast kot povsod
    pod `/admin` (`ADR-054`, meja 4; `ADR-035` D). Odgovor je JSON; vsaka
    napaka nosi slovensko sporočilo, ki ga skripta pokaže v klepetu.

    Klic modela teče v pomožni niti, kot pri urniku: odjemalec je sinhron in
    klic traja do `openai_timeout_seconds`. Zahteva nanj čaka — pretakanja in
    opravil v ozadju ni (`POC-01`: čakanje 15 do 30 s je sprejemljivo).
    """
    obrazec = await request.form(max_fields=admin.BREZ_MEJE_POLJ)
    koda = _polje(obrazec, "subject").rstrip("/")

    navodilo = preizkus.navodilo_za(koda)
    if navodilo is None:
        return _napaka(SPOROCILO_SAMO_MATEMATIKA, 400)
    if klicalec is None:
        return _napaka(SPOROCILO_BREZ_KLJUCA, 503)

    zelja = _polje(obrazec, "zelja").strip()
    if not zelja:
        return _napaka(SPOROCILO_BREZ_ZELJE, 400)

    nabor = repozitorij.seznam_po_predmetu(koda)
    prepisi, _ = admin.prepisi_izbora(
        repozitorij, admin.imena_otrok(clani), nabor, _seznam(obrazec, "snov")
    )
    if not prepisi.slik:
        return _napaka(SPOROCILO_BREZ_SNOVI, 400)

    vhod = preizkus.sestavi_vhod(
        snov=prepisi.besedilo,
        test_md=_polje(obrazec, "test_md"),
        resitve_md=_polje(obrazec, "resitve_md"),
        dosedanje=_seznam(obrazec, "dosedanje"),
        zelja=zelja,
    )

    try:
        izid = await asyncio.to_thread(klicalec, navodilo, vhod)
    except NapakaObdelave as napaka:
        # Sporočilo je naše in vsebine ne citira (`preizkus.razcleni_odgovor`,
        # `vision._poslji`); snov in želja v dnevnik ne gresta.
        dnevnik.warning("Preizkus %s: klic modela ni uspel: %s", koda, napaka.sporocilo)
        return _napaka(f"{napaka.sporocilo} {IZHOD_OB_NEUSPEHU}", 502)

    dnevnik.info(
        "Preizkus %s: model %s, %.1f s, žetoni vhod %s (predpomnjeni %s), "
        "izhod %s (razmišljanje %s).",
        koda,
        izid.model,
        izid.trajanje,
        izid.vhodni,
        izid.predpomnjeni,
        izid.izhodni,
        izid.razmisljanje,
    )

    # Prazen `test_md` ni napaka klica: model pove, zakaj testa ni, in to gre
    # staršu dobesedno. Da test ob tem ostane nespremenjen, poskrbi skripta.
    return JSONResponse(
        {
            "sporocilo": izid.odgovor.sporocilo,
            "test_md": izid.odgovor.test_md,
            "resitve_md": izid.odgovor.resitve_md,
        }
    )
