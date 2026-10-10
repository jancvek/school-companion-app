"""Sestavljanje preizkusa v klepetu z modelom (V4-R07) in shranjeni
preizkusi (V4-R08).

Poti pod `/admin/assessments` — angleško kot vse ostale in brez besede
`test`, ki je rezervirana za avtomatske teste (`docs/odlocitve/ADR-053` A):

- `POST /compose` izriše urejevalnik iz izbora na strani predmeta — isti
  obrazec in isti izbor kot „Prepisi izbranih", le drugi gumb (`formaction`).
- `GET /compose` pelje na pregled, kot `GET /admin/transcripts`: urejevalnik
  je trenutno delo in ne stanje, zato ga ni mogoče osvežiti ali dati med
  zaznamke.
- `POST /generate` je en klic modela. Kliče ga skripta urejevalnika, odgovor
  je JSON (`docs/odlocitve/ADR-054`, meja 4).

- `GET ""` je pregled shranjenih preizkusov, `GET /{id}` ogled enega in
  `GET /{id}/compose` urejevalnik z izhodiščem v njem (V4-R08).
- `POST ""` shrani končan preizkus. Kliče ga skripta, odgovor je JSON
  (`docs/odlocitve/ADR-055` G).

**Strežnik je za model brez stanja** (`ADR-053` E): delo v teku živi samo v
brskalniku. Zapis nastane šele ob „Shrani" in se potem ne spremeni več
(`ADR-053` F).

**Brskalnik pošlje identifikatorje snovi, ne besedila.** Snov za vsak klic
sestavi strežnik znova, iz seznama predmeta te družine — z isto funkcijo kot
„Prepisi izbranih" (`admin.prepisi_izbora`). Besedilo iz brskalnika bi bilo
trditev o tem, kaj je v zvezku, in meja družine bi bila s tem stvar zaupanja.
Pri preizkusu **na osnovi** shranjenega pošlje samo identifikator izhodišča:
snov, predmet in naslovljenca strežnik prebere iz zapisa (`ADR-055` H).
"""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData
from starlette.responses import Response

from app import preizkus
from app.casi import cas, datum
from app.db import (
    ClaniRepository,
    MaterialsRepository,
    PreizkusiRepository,
    SejaUporabnika,
)
from app.dependencies import (
    daj_klicalca_preizkusa,
    daj_nastavitve,
    daj_prijavo,
    daj_repozitorij,
    daj_repozitorij_clanov,
    daj_repozitorij_preizkusov,
)
from app.models import Material, Preizkus
from app.routers import admin
from app.settings import Settings
from app.storage import je_znotraj, mapa_druzine, velikost_slike
from app.strani import daj_predloge, ni_najdeno
from app.subjects import oznaka_predmeta, poisci_predmet
from app.vision import KlicalecPreizkusa, NapakaObdelave

#: Dnevnik porabe: ena vrstica na klic modela (kriterij `V4-R07`). Da vrstica
#: ravni `INFO` res pride v izpis strežnika, poskrbi `app/main.py`.
dnevnik = logging.getLogger(__name__)

PREDPONA = f"{admin.PREDPONA}/assessments"

router = APIRouter(prefix=PREDPONA)

#: Naslov, ki ga kliče skripta urejevalnika. Izriše ga strežnik (`data-pot`),
#: da ga skripta ne sestavlja sama.
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

#: Isto besedilo za tuj in za neobstoječ preizkus: obstoj tujega zapisa ni
#: podatek za starša (kriterij `V4-R08`, `ADR-038`).
SPOROCILO_NI_PREIZKUSA = (
    "Tega testa ni med shranjenimi testi tvoje družine. Odpri pregled testov "
    "in izberi enega s seznama."
)

SPOROCILO_ZASTARELA_STRAN = (
    "Te strani ni več mogoče shraniti. Test, ki ga vidiš, natisni ali si ga "
    "prepiši, nato urejevalnik odpri znova s strani predmeta."
)

SPOROCILO_PRAZEN_TEST = "Testa še ni. Najprej ga sestavi, nato pritisni „Shrani“."

SPOROCILO_IZBERI_OTROKA = (
    "Izberi otroka, za katerega je test: izbrana snov je od več otrok. Nato "
    "znova pritisni „Shrani“."
)

SPOROCILO_BREZ_SPREMEMBE = (
    "Test je enak shranjenemu, iz katerega si začel. Najprej ga z željo "
    "spremeni, nato pritisni „Shrani“."
)

SPOROCILO_SNOV_IZGINILA = (
    "Izbrane snovi ni več na strani predmeta (arhivirana ali premaknjena), "
    "zato testa ni mogoče shraniti z njo. Test natisni, nato izberi snov znova."
)


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


def _prazen_urejevalnik() -> dict[str, Any]:
    """Privzetki konteksta `preizkus.html`; pot jih prepiše s svojimi."""
    return {"urejevalnik": False, "snovi": [], "otroci_snovi": [], "osnova": None}


def _poti_urejevalnika() -> dict[str, Any]:
    """Naslova, ki ju kliče skripta, in identifikator novega zapisa.

    Vse troje izriše strežnik (`data-` atributi), da skripta naslovov ne
    sestavlja (`ADR-054`, meja 4). Identifikator nastane **tu** in ne ob
    shranjevanju: ponovljen `POST` z istim zato ne naredi drugega zapisa
    (`ADR-055` G).
    """
    return {
        "pot_generiranja": POT_GENERIRANJA,
        "pot_shranjevanja": PREDPONA,
        "nov_id": str(uuid4()),
    }


def _otroci_snovi(clani: ClaniRepository, izbrane: list[Material]) -> list[dict[str, str]]:
    """Otroci izbrane snovi za izbirnik naslovljenca; prazno, kadar je en sam.

    Vključuje deaktivirane: test je na papirju in prijave ne potrebuje
    (`ADR-055` H), za razliko od kviza (`ADR-039` A).
    """
    lastniki = {material.child_id for material in izbrane}
    if len(lastniki) < 2:
        return []
    return [
        {"id": otrok.user_id, "ime": otrok.display_name}
        for otrok in clani.otroci()
        if otrok.user_id in lastniki
    ]


def pot_preizkusa(preizkus_id: str) -> str:
    """Naslov ogleda shranjenega preizkusa."""
    return f"{PREDPONA}/{quote(preizkus_id, safe='')}"


def _je_uuid(vrednost: str) -> bool:
    """Ali je niz kanonično zapisan UUID — tak, kot ga izriše `uuid4`."""
    try:
        return str(UUID(vrednost)) == vrednost
    except ValueError:
        return False


def _vrstica(zapis: Preizkus, imena: dict[str, str]) -> dict[str, Any]:
    """Shranjen preizkus, kot ga pokažeta pregled in glava ogleda.

    Ime otroka gre skozi `admin.imena_otrok`, ki je pri družini z enim
    otrokom prazna (`ADR-039` F3, `ADR-051`).
    """
    return {
        "pot": pot_preizkusa(zapis.id),
        "cas": cas(zapis.saved_at),
        "koda": zapis.subject,
        "naslov": zapis.title,
        "otrok": imena.get(zapis.child_id),
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
                **_prazen_urejevalnik(),
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
        urejevalnik=True,
        snovi=[_slicica(material, mapa_slik) for material in izbrane],
        # Izbirnik naslovljenca samo, kadar je izbrana snov od več otrok
        # (kriterij `V4-R08`); sicer je naslovljenec znan in ga določi strežnik.
        otroci_snovi=_otroci_snovi(clani, izbrane),
        **_poti_urejevalnika(),
        # Brez ključa urejevalnik dela, le generiranje pove, da ni nastavljeno
        # (kriterij `V4-R07`). Ista drža kot pri urniku brez ključa.
        brez_kljuca=SPOROCILO_BREZ_KLJUCA if klicalec is None else None,
    )


@router.post("/generate")
async def generiraj(
    request: Request,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    shranjeni: Annotated[PreizkusiRepository, Depends(daj_repozitorij_preizkusov)],
    klicalec: Annotated[KlicalecPreizkusa | None, Depends(daj_klicalca_preizkusa)],
) -> JSONResponse:
    """En klic modela: nov test ali popravek trenutnega. Ničesar ne zapiše.

    Polje `osnova` pomeni preizkus na osnovi shranjenega (V4-R08): snov in
    predmet takrat prideta **iz zapisa**, ne iz obrazca in ne iz trenutne
    snovi predmeta. Tuja ali neobstoječa osnova je `404`.

    Telo je obrazec in ne JSON, da CSRF žeton preveri ista plast kot povsod
    pod `/admin` (`ADR-054`, meja 4; `ADR-035` D). Odgovor je JSON; vsaka
    napaka nosi slovensko sporočilo, ki ga skripta pokaže v klepetu.

    Klic modela teče v pomožni niti, kot pri urniku: odjemalec je sinhron in
    klic traja do `openai_timeout_seconds`. Zahteva nanj čaka — pretakanja in
    opravil v ozadju ni (`POC-01`: čakanje 15 do 30 s je sprejemljivo).
    """
    obrazec = await request.form(max_fields=admin.BREZ_MEJE_POLJ)
    koda = _polje(obrazec, "subject").rstrip("/")

    osnova: Preizkus | None = None
    osnova_id = _polje(obrazec, "osnova")
    if osnova_id:
        osnova = shranjeni.najdi(osnova_id)
        if osnova is None:
            return _napaka(SPOROCILO_NI_PREIZKUSA, 404)
        koda = osnova.subject

    navodilo = preizkus.navodilo_za(koda)
    if navodilo is None:
        return _napaka(SPOROCILO_SAMO_MATEMATIKA, 400)
    if klicalec is None:
        return _napaka(SPOROCILO_BREZ_KLJUCA, 503)

    zelja = _polje(obrazec, "zelja").strip()
    if not zelja:
        return _napaka(SPOROCILO_BREZ_ZELJE, 400)

    if osnova is not None:
        snov = osnova.source_md
    else:
        nabor = repozitorij.seznam_po_predmetu(koda)
        prepisi, _ = admin.prepisi_izbora(
            repozitorij, admin.imena_otrok(clani), nabor, _seznam(obrazec, "snov")
        )
        if not prepisi.slik:
            return _napaka(SPOROCILO_BREZ_SNOVI, 400)
        snov = prepisi.besedilo

    vhod = preizkus.sestavi_vhod(
        snov=snov,
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
            # Ime, kot ga je vrnila storitev; skripta ga hrani pri koraku in
            # pošlje ob shranjevanju (`ADR-055` C).
            "model": izid.model,
        }
    )


# --- Shranjeni preizkusi (V4-R08) ---


@router.post("")
async def shrani(
    request: Request,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    shranjeni: Annotated[PreizkusiRepository, Depends(daj_repozitorij_preizkusov)],
    prijava: Annotated[SejaUporabnika, Depends(daj_prijavo)],
) -> JSONResponse:
    """Shrani končan preizkus; odgovor je JSON z naslovom ogleda.

    Od brskalnika pridejo **test, rešitve, model in identifikatorji** — nikoli
    besedilo snovi, naslov ali (pri preizkusu na osnovi) predmet in otrok.
    Vse to določi strežnik (`ADR-055` B, H).

    Ponovljen klic z istim `id` vrne isti naslov in ne zapiše ničesar
    (`ADR-055` G); zato je ta preverba **pred** vsemi ostalimi — snov je
    lahko med prvim in drugim klikom že arhivirana.
    """
    obrazec = await request.form(max_fields=admin.BREZ_MEJE_POLJ)

    preizkus_id = _polje(obrazec, "id")
    if not _je_uuid(preizkus_id):
        return _napaka(SPOROCILO_ZASTARELA_STRAN, 400)
    obstojeci = shranjeni.najdi(preizkus_id)
    if obstojeci is not None:
        return JSONResponse({"pot": pot_preizkusa(obstojeci.id)})

    test_md = _polje(obrazec, "test_md")
    resitve_md = _polje(obrazec, "resitve_md")
    if not test_md.strip():
        return _napaka(SPOROCILO_PRAZEN_TEST, 400)
    model = _polje(obrazec, "model").strip()[: preizkus.NAJDALJSI_MODEL]
    if not model:
        return _napaka(SPOROCILO_ZASTARELA_STRAN, 400)

    osnova_id = _polje(obrazec, "osnova")
    naslovljenec: str | None
    if osnova_id:
        osnova = shranjeni.najdi(osnova_id)
        if osnova is None:
            return _napaka(SPOROCILO_NI_PREIZKUSA, 404)
        if preizkus.je_enak_izhodiscu(test_md, resitve_md, osnova.test_md, osnova.solutions_md):
            return _napaka(SPOROCILO_BREZ_SPREMEMBE, 400)
        koda = osnova.subject
        snov = osnova.source_md
        naslovljenec = osnova.child_id
    else:
        koda = _polje(obrazec, "subject").rstrip("/")
        if preizkus.navodilo_za(koda) is None:
            return _napaka(SPOROCILO_SAMO_MATEMATIKA, 400)
        nabor = repozitorij.seznam_po_predmetu(koda)
        prepisi, izbrane = admin.prepisi_izbora(
            repozitorij, admin.imena_otrok(clani), nabor, _seznam(obrazec, "snov")
        )
        if not izbrane:
            return _napaka(SPOROCILO_SNOV_IZGINILA, 400)
        snov = prepisi.besedilo
        naslovljenec = preizkus.izberi_naslovljenca(
            [material.child_id for material in izbrane], _polje(obrazec, "otrok")
        )
        if naslovljenec is None:
            return _napaka(SPOROCILO_IZBERI_OTROKA, 400)

    zapis = shranjeni.shrani(
        preizkus_id=preizkus_id,
        child_id=naslovljenec,
        saved_by=prijava.user_id,
        subject=koda,
        title=preizkus.naslov_iz_testa(test_md, f"Test — {koda} — {datum(datetime.now(UTC))}"),
        test_md=test_md,
        solutions_md=resitve_md,
        source_md=snov,
        model=model,
        base_id=osnova_id or None,
    )
    if zapis is None:
        # `id` obstaja v drugi družini. Iz izrisane strani to ne nastane.
        return _napaka(SPOROCILO_ZASTARELA_STRAN, 409)
    return JSONResponse({"pot": pot_preizkusa(zapis.id)})


@router.get("")
def pregled(
    request: Request,
    shranjeni: Annotated[PreizkusiRepository, Depends(daj_repozitorij_preizkusov)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    predmet: str | None = None,
) -> Response:
    """Shranjeni preizkusi družine, najnovejši prvi; `?predmet=` filtrira.

    Filter ponudi predmete, pri katerih družina preizkus ima. Neznana koda ni
    napaka: da prazen seznam, ker je predmet tu okno nad istimi podatki in ne
    identiteta (`ADR-055` A). Prazen niz šteje kot brez filtra.
    """
    izbran = predmet or None
    stevila = shranjeni.stej_po_predmetih()
    imena = admin.imena_otrok(clani)
    return predloge.TemplateResponse(
        request,
        "preizkusi.html",
        {
            "vrstice": [_vrstica(zapis, imena) for zapis in shranjeni.seznam(izbran)],
            "izbran": izbran,
            "filtri": [
                {
                    "koda": koda,
                    "oznaka": oznaka_predmeta(koda),
                    "pot": f"{PREDPONA}?predmet={quote(koda, safe='')}",
                }
                for koda in sorted(stevila)
            ],
            "pot_vseh": PREDPONA,
            "ima_imena": bool(imena),
        },
    )


@router.get("/{preizkus_id}/compose")
def sestavi_na_osnovi(
    request: Request,
    preizkus_id: str,
    shranjeni: Annotated[PreizkusiRepository, Depends(daj_repozitorij_preizkusov)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    klicalec: Annotated[KlicalecPreizkusa | None, Depends(daj_klicalca_preizkusa)],
) -> Response:
    """Urejevalnik z izhodiščem v shranjenem preizkusu. Ničesar ne zapiše.

    Izhodišče je korak nič: pod njega se ne da razveljaviti. Snov je besedilo
    iz zapisa in ne trenutna snov predmeta; sličic zato ni (`ADR-055` E).
    Izvirnik ostane, kakršen je — shranjevanje naredi novo vrstico.
    """
    zapis = shranjeni.najdi(preizkus_id)
    if zapis is None:
        return ni_najdeno(predloge, request, SPOROCILO_NI_PREIZKUSA)

    kontekst: dict[str, Any] = {
        "koda": zapis.subject,
        "pot_nazaj": pot_preizkusa(zapis.id),
        **_prazen_urejevalnik(),
    }
    if preizkus.navodilo_za(zapis.subject) is None:
        kontekst["opozorilo"] = SPOROCILO_SAMO_MATEMATIKA
    else:
        kontekst.update(
            urejevalnik=True,
            osnova={
                "id": zapis.id,
                "test_md": zapis.test_md,
                "resitve_md": zapis.solutions_md,
                "snov": zapis.source_md,
                **_vrstica(zapis, admin.imena_otrok(clani)),
            },
            **_poti_urejevalnika(),
            brez_kljuca=SPOROCILO_BREZ_KLJUCA if klicalec is None else None,
        )
    return predloge.TemplateResponse(request, "preizkus.html", kontekst)


@router.get("/{preizkus_id}")
def ogled(
    request: Request,
    preizkus_id: str,
    shranjeni: Annotated[PreizkusiRepository, Depends(daj_repozitorij_preizkusov)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
) -> Response:
    """Shranjen preizkus za branje in tisk. Urejanja ni (`ADR-053` F)."""
    zapis = shranjeni.najdi(preizkus_id)
    if zapis is None:
        return ni_najdeno(predloge, request, SPOROCILO_NI_PREIZKUSA)

    osnova = shranjeni.najdi(zapis.base_id) if zapis.base_id else None
    return predloge.TemplateResponse(
        request,
        "preizkus-ogled.html",
        {
            **_vrstica(zapis, admin.imena_otrok(clani)),
            "test_md": zapis.test_md,
            "resitve_md": zapis.solutions_md,
            "snov": zapis.source_md,
            "model": zapis.model,
            "pot_osnove": f"{pot_preizkusa(zapis.id)}/compose",
            "pot_pregleda": PREDPONA,
            # Iz katerega shranjenega testa je nastal (`ADR-055` E).
            "izhodisce": (
                {"pot": pot_preizkusa(osnova.id), "naslov": osnova.title}
                if osnova is not None
                else None
            ),
        },
    )
