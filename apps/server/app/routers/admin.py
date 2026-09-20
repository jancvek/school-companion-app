"""Operaterska stran: pregled prejetih slik in brisanje.

Stran je namenjena lastniku sistema, ne učenki (`docs/00-namen.md`, vloga
„spremlja delovanje"). Ključa ne zahteva. Do V3-R03 jo varuje začasen
`basic_auth` v Caddyju (`docs/odlocitve/ADR-026`); pred V3-R02 je bila meja
Tailscale (`docs/odlocitve/ADR-006`).

Stran s podrobnostmi od V1-R03 pokaže tudi izid obdelave — prepis, povzetek,
vprašanja z odgovori — in celotno revizijsko sled klica: poslani prompt, surov
odgovor modela, ime modela in porabo tokenov. Gumb „Pošlji v obdelavo" zapis
vrne v vrsto; ker to zavrže prejšnji rezultat, je `POST` in ne povezava
(`docs/odlocitve/ADR-009`).
"""

import re
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.besedilo import SLIKE, stevilo_z_besedo
from app.casi import cas, cas_ali_prazno, v_domacem
from app.db import ClaniRepository, KviziRepository, MaterialsRepository
from app.dependencies import (
    daj_nastavitve,
    daj_repozitorij,
    daj_repozitorij_clanov,
    daj_repozitorij_kvizov,
)
from app.models import STATUS_V_OBDELAVI, Material
from app.routers.kvizi import seznam_kvizov
from app.settings import Settings
from app.storage import je_znotraj, mapa_druzine, pobrisi_sliko, velikost_slike
from app.strani import daj_predloge, ni_dovoljeno, ni_najdeno
from app.subjects import PREDMETI, oznaka_predmeta, oznaka_statusa, poisci_predmet

#: Predpona vseh poti operaterske strani.
PREDPONA = "/admin"

router = APIRouter(prefix=PREDPONA)

#: Mapa s predlogami. Izpelje se iz mesta te datoteke, ne iz trenutne mape.
#:
#: Isti razlog kot pri `mypy.ini` in `env_file` v V1-R02: pot, relativna na
#: delovno mapo, bi pomenila, da se strežnik obnaša različno glede na to, od
#: kod je pognan (odločitev 2 v `docs/plan/V1-R04.md`).
MAPA_PREDLOG = Path(__file__).resolve().parent.parent / "templates"


def _velikost_opis(bajti: int | None) -> str:
    """Velikost datoteke v berljivi obliki."""
    if bajti is None:
        return "datoteke na disku ni"
    if bajti < 1024:
        return f"{bajti} B"
    if bajti < 1024 * 1024:
        return f"{bajti / 1024:.0f} kB"
    return f"{bajti / (1024 * 1024):.1f} MB"


def imena_otrok(clani: ClaniRepository) -> dict[str, str]:
    """Preslikava `id` → prikazno ime, za oznako „čigava snov" (V3-R07).

    **Prazna pri družini z enim otrokom**: oznaka, ki ne loči ničesar, bi bila
    na vsaki vrstici samo šum, in kriterij `V3-R07` pravi, da se vmesnik
    družine z enim otrokom ne spremeni (`ADR-039` F).

    Vključuje tudi **deaktivirane** otroke: njihova snov ostane (`V3-R06`) in
    mora imeti ime — brez tega bi vrstice po deaktivaciji tiho izgubile oznako.
    """
    otroci = clani.otroci()
    if len(otroci) < 2:
        return {}
    return {otrok.user_id: otrok.display_name for otrok in otroci}


def _pogled(
    material: Material, mapa_slik: Path, imena: dict[str, str] | None = None
) -> dict[str, Any]:
    """Zapis, pripravljen za predlogo.

    Predloga ne računa in ne oblikuje — dobi gotove nize. Tako je oblikovanje
    testljivo brez izrisa in predloga ostane brana kot postavitev.

    Za datoteko izven `mapa_slik` velja isto kot za manjkajočo. Sicer bi
    predloga narisala `<img>`, pot `/image` pa bi ga zavrnila — stran bi
    kazala pokvarjeno sliko namesto povedati, kaj je narobe.

    Vprašanj in revizijske sledi tu **ni**: ta pogled se izriše tudi za vsako
    sliko v seznamu predmeta, in branje vprašanj bi tam pomenilo eno poizvedbo
    na sliko. Za stran s podrobnostmi je `_pogled_podrobno`.
    """
    pot = Path(material.image_path)
    velikost = velikost_slike(pot) if je_znotraj(mapa_slik, pot) else None
    return {
        "id": material.id,
        # Čigava snov je (V3-R07). `None` pri družini z enim otrokom: ime, ki
        # ne loči ničesar, je na vsaki vrstici samo šum (`ADR-039` F).
        # Izbirnika tu ni — te strani so zgodovina družine, ne pogled po
        # otroku; ta je na `/admin/days` in v statistiki.
        "otrok": (imena or {}).get(material.child_id),
        "koda": material.subject,
        "oznaka": oznaka_predmeta(material.subject),
        "cas": cas(material.taken_at),
        "prejeto": cas(material.received_at),
        "stanje": oznaka_statusa(material.status, material.readable),
        "pot": material.image_path,
        "velikost": velikost,
        "velikost_opis": _velikost_opis(velikost),
        "arhiviran": material.archived_at is not None,
        "arhivirano_ob": cas_ali_prazno(material.archived_at),
        # „Potrjeno" pomeni, da je telefon sporočil, da tega materiala pri
        # njem ni več. Dokler ni, dokončno brisanje ni dovoljeno.
        "potrjeno": material.device_deleted_at is not None,
        "potrjeno_ob": cas_ali_prazno(material.device_deleted_at),
    }


def _stevilo(koliko: int | None) -> str:
    """Število tokenov za prikaz; manjkajoč podatek ni nič in ni ničla."""
    return "—" if koliko is None else f"{koliko}"


def _pogled_podrobno(
    material: Material, mapa_slik: Path, imena: dict[str, str] | None = None
) -> dict[str, Any]:
    """Kot `_pogled`, plus izid obdelave in revizijska sled (V1-R03).

    Vse, kar je posebej za to stran, je zbrano tu: predloga potem samo
    razporeja. Zastavice (`je_ready`, `ima_sled`, …) so izračunane, ker bi
    predloga sicer sklepala o pomenu statusov — in bi se sklepanje podvojilo
    ob vsakem novem stanju.
    """
    pogled = _pogled(material, mapa_slik, imena)
    pogled.update(
        {
            "status": material.status,
            "berljivo": material.readable,
            "prepis": material.transcript,
            "povzetek": material.summary,
            "napaka": material.error,
            "model": material.model,
            "prompt": material.prompt,
            "surov_odgovor": material.raw_response,
            "vhodni_tokeni": _stevilo(material.input_tokens),
            "izhodni_tokeni": _stevilo(material.output_tokens),
            # Samo veljavna. Upokojena imajo svoje število in svoj razdelek —
            # pomešana med veljavna bi bila neopazna, ker se `position` z
            # vsako serijo začne znova (`docs/odlocitve/ADR-015`).
            "vprasanja": [
                {"stevilka": vprasanje.position, "vprasanje": vprasanje.question,
                 "odgovor": vprasanje.answer}
                for vprasanje in material.veljavna_vprasanja
            ],
            # Sled se pokaže, kadar je karkoli od nje nastalo — tudi pri
            # `failed`, kjer je surov odgovor pogosto edino, kar pojasni zakaj.
            "ima_sled": any(
                (
                    material.prompt,
                    material.raw_response,
                    material.model,
                    material.input_tokens is not None,
                    material.output_tokens is not None,
                )
            ),
            # Zapisa, ki ga pravkar obdeluje worker, ne ponujamo v ponovno
            # obdelavo: gumb bi ne naredil ničesar in bi lagal. Arhiviranega
            # tudi ne — worker ga ne pobira več, gumb bi torej samo pobrisal
            # dosedanji izid in ne bi naredil novega.
            "ponovna_obdelava_mozna": (
                material.status != STATUS_V_OBDELAVI and material.archived_at is None
            ),
            "stevilo_vprasanj": len(material.veljavna_vprasanja),
            # Brez tega števila je razlika med „ta snov nima vprašanj" in „vsa
            # njena vprašanja so upokojena" nevidna — stran bi v obeh primerih
            # kazala prazen seznam. To je kriterij V2-R05, ne stvar okusa.
            "stevilo_upokojenih": len(material.upokojena_vprasanja),
        }
    )
    return pogled


#: Znaki kode predmeta, ki v imenu prenesene datoteke ostanejo; vse drugo je `_`.
#:
#: Koda sme vsebovati karkoli (`POST /materials` jo omejuje samo po dolžini),
#: poševnica ali dvopičje v imenu datoteke pa bi brskalnik ime zavrgel ali
#: prerezal.
_NEVARNO_V_IMENU = re.compile(r"[^A-Za-z0-9-]")

#: Sidro, ki na strani s podrobnostmi ob prihodu odpre povečan prikaz (V2-R08).
OZNAKA_POVECAVE = "#povecano"


def _ime_prenosa(material: Material) -> str:
    """Predlagano ime prenesene slike: `MAT_2026-09-04_09-30.jpg`.

    Koda in čas posnetka v domačem pasu, na minuto — to operater na posnetku
    prepozna. Identifikatorja ni: dvoumnost med dvema posnetkoma iste minute
    je manjša škoda kot neberljivo ime. Sestavi ga strežnik in ne skripta
    (`docs/odlocitve/ADR-024`, meja 4).
    """
    koda = _NEVARNO_V_IMENU.sub("_", material.subject)
    return f"{koda}_{v_domacem(material.taken_at):%Y-%m-%d_%H-%M}.jpg"


def _povezava_povecave(material_id: str | None) -> str | None:
    """Pot na podrobnosti soseda, ki tam spet odpre povečan prikaz."""
    if material_id is None:
        return None
    return f"{PREDPONA}/materials/{material_id}{OZNAKA_POVECAVE}"


def _pogled_povecave(
    material: Material, repozitorij: MaterialsRepository
) -> dict[str, Any]:
    """Kar potrebuje povečan prikaz na strani s podrobnostmi (V2-R08).

    Puščic arhivirana snov nima, ker je v naboru predmeta ni; `listanje` to
    pove predlogi, da ji ni treba sklepati iz dveh praznih sosedov — tudi
    edina slika predmeta ima oba prazna, a puščici ima, le neaktivni.
    """
    prejsnji, naslednji = repozitorij.sosedi_v_predmetu(material)
    return {
        # Isto sidro kot v povezavah na soseda. Iz ene konstante, sicer bi se
        # skripta in povezave razšli po tihem in prikaz ob prihodu ne bi odprl.
        "oznaka": OZNAKA_POVECAVE,
        "ime_prenosa": _ime_prenosa(material),
        "listanje": material.archived_at is None,
        "prejsnja": _povezava_povecave(prejsnji),
        "naslednja": _povezava_povecave(naslednji),
    }


#: Pojasnilo, zakaj dokončnega brisanja (še) ni.
ZADRZANO = (
    "Dokončno brisanje je mogoče šele, ko telefon potrdi, da te slike pri njem "
    "ni več. Dokler potrditve ni, bi slika na telefonu ostala za vedno. "
    "Sliko lahko medtem počistiš z diska — zapis, prepis in vprašanja ostanejo."
)


def _po_umiku(repozitorij: MaterialsRepository, koda: str) -> RedirectResponse:
    """Kam pelje pot, ko slika izgine s seznama predmeta.

    Stran predmeta zna biti po umiku 404: koda, ki ni na seznamu desetih,
    obstaja samo, dokler ima kakšno aktivno sliko. Umik zadnje bi operaterja
    poslal na „Tega ni", zato v tem edinem primeru pelje na pregled. Znan
    predmet ostane dosegljiv tudi prazen.

    303 in ne 302: po `POST` mora brskalnik naslednjo zahtevo poslati kot
    `GET`, sicer osvežitev strani dejanje ponovi. Koda gre skozi `quote`:
    `?` in `#` bi glavo `Location` prerezala na poizvedbo oziroma sidro.
    """
    if not repozitorij.seznam_po_predmetu(koda) and poisci_predmet(koda) is None:
        return RedirectResponse(PREDPONA, status_code=303)

    return RedirectResponse(
        f"{PREDPONA}/subjects/{quote(koda, safe='')}", status_code=303
    )


@router.get("")
def pregled(
    request: Request,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    kvizi: Annotated[KviziRepository, Depends(daj_repozitorij_kvizov)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
) -> Response:
    """Vsi predmeti s številom slik in seznam kvizov (V2-R01)."""
    steviloma = repozitorij.stej_po_predmetih()
    otroci = clani.otroci()

    vrstice = [
        {"koda": predmet.koda, "oznaka": predmet.oznaka, "koliko": steviloma.get(predmet.koda, 0)}
        for predmet in PREDMETI
    ]

    # Predmet, ki je v bazi, a ga na seznamu desetih ni, se pokaže pod svojo
    # kodo. Sicer bi se ob preimenovanju kode na telefonu slike tiho izgubile
    # iz pregleda — odločitev 3 v `docs/plan/V1-R04.md`.
    znane = {predmet.koda for predmet in PREDMETI}
    for koda in sorted(steviloma.keys() - znane):
        vrstice.append({"koda": koda, "oznaka": "predmet ni na seznamu", "koliko": steviloma[koda]})

    return predloge.TemplateResponse(
        request,
        "predmeti.html",
        {
            "predmeti": vrstice,
            # Gotov niz in ne število: predloga ne računa in ne sklanja, isto
            # pravilo kot pri `_pogled`.
            "skupaj_opis": stevilo_z_besedo(sum(steviloma.values()), SLIKE),
            "arhiviranih": repozitorij.stej_arhivirane(),
            # Kviz je svoja os in ne del pregleda predmetov, zato svoj ključ in
            # svoj razdelek. Oblika ene vrstice je last `routers/kvizi.py` —
            # ta stran jo samo pokaže.
            "kvizi": seznam_kvizov(kvizi, otroci),
            # Kviz mora imeti naslovljenca (`docs/odlocitve/ADR-039` A), zato
            # družina brez aktivnega otroka vstopov v sestavljalnik sploh ne
            # dobi. Isto pravilo jih tudi zavrne s `409` — gumb, ki ga stran
            # ne izriše, ni varovalka (vzorec `ADR-038`).
            "ima_otroka": any(otrok.is_active for otrok in otroci),
        },
    )


@router.get("/archive")
def arhiv(
    request: Request,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> Response:
    """Arhivirane slike, najnovejše arhivirane prve.

    Vrstni red je po času arhiviranja in ne po času posnetka: ta stran
    odgovarja na vprašanje „kaj sem umaknil in ali je telefon to pospravil",
    ne „kdaj je bila snov posneta".
    """
    snovi = repozitorij.seznam_arhiviranih()
    imena = imena_otrok(clani)
    return predloge.TemplateResponse(
        request,
        "arhiv.html",
        {
            "koliko_opis": stevilo_z_besedo(len(snovi), SLIKE),
            "snovi": [
                _pogled(
                    snov,
                    mapa_druzine(nastavitve.images_dir, repozitorij.family_id),
                    imena,
                )
                for snov in snovi
            ],
        },
    )


@router.get("/subjects/{koda:path}")
def predmet(
    request: Request,
    koda: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> Response:
    """Slike enega predmeta, najnovejša prva."""
    # Pretvornik `:path` požre tudi končno poševnico, zato `MAT/` ne bi bil
    # `MAT`. Starlette bi to sicer preusmeril sam, a pri `:path` pot obstaja
    # in preusmeritve ni. Koda predmeta se na poševnico nikoli ne konča.
    koda = koda.rstrip("/")
    snovi = repozitorij.seznam_po_predmetu(koda)

    # Neznana koda brez ene same slike je tipkarska napaka v naslovu, ne prazen
    # predmet. Koda, ki slike ima, je veljavna, tudi če ni na seznamu.
    if not snovi and poisci_predmet(koda) is None:
        return ni_najdeno(
            predloge, request, f"Predmeta s kodo „{koda}“ ni ne na seznamu ne v bazi."
        )

    # Imena **pred** zanko in ne v njej: znotraj izpeljanega seznama bi bila
    # to ena poizvedba na sliko, seznam predmeta pa bo čez šolsko leto dolg
    # nekaj sto vrstic (`docs/odlocitve/ADR-017` A). Arhiv ima isto potezo.
    imena = imena_otrok(clani)
    mapa_slik = mapa_druzine(nastavitve.images_dir, repozitorij.family_id)

    return predloge.TemplateResponse(
        request,
        "predmet.html",
        {
            "koda": koda,
            "oznaka": oznaka_predmeta(koda),
            "koliko_opis": stevilo_z_besedo(len(snovi), SLIKE),
            "snovi": [_pogled(snov, mapa_slik, imena) for snov in snovi],
        },
    )


@router.get("/materials/{material_id}")
def snov(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> Response:
    """Podrobnosti ene slike."""
    material = repozitorij.poisci(material_id)
    if material is None:
        return ni_najdeno(predloge, request, "Zapisa s tem identifikatorjem na strežniku ni.")

    mapa_slik = mapa_druzine(nastavitve.images_dir, repozitorij.family_id)
    pogled = _pogled_podrobno(material, mapa_slik, imena_otrok(clani))
    # Snov brez datoteke povečanega prikaza nima, zato tudi poizvedbe po
    # sosedih ne plača.
    povecava = (
        _pogled_povecave(material, repozitorij) if pogled["velikost"] is not None else None
    )

    return predloge.TemplateResponse(
        request, "snov.html", {"snov": pogled, "povecava": povecava}
    )


@router.get("/materials/{material_id}/image")
def slika(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> Response:
    """Sama datoteka slike."""
    material = repozitorij.poisci(material_id)
    if material is None:
        return ni_najdeno(predloge, request, "Zapisa s tem identifikatorjem na strežniku ni.")

    pot = Path(material.image_path)

    # Pot je zapisala naša koda in bi ji smeli zaupati. Ne zaupamo ji, ker je
    # cena preverbe ena vrstica, cena napačne predpostavke pa branje poljubne
    # datoteke s strežnika (odločitev 8 v `docs/plan/V1-R04.md`).
    mapa_slik = mapa_druzine(nastavitve.images_dir, repozitorij.family_id)
    if not je_znotraj(mapa_slik, pot) or not pot.is_file():
        return ni_najdeno(predloge, request, "Slike tega zapisa na disku ni.")

    return FileResponse(pot, media_type="image/jpeg")


@router.get("/materials/{material_id}/archive")
def potrdi_arhiviranje(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> Response:
    """Vmesni korak pred arhiviranjem. Sam ne spremeni ničesar."""
    material = repozitorij.poisci(material_id)
    if material is None:
        return ni_najdeno(predloge, request, "Zapisa s tem identifikatorjem na strežniku ni.")

    return predloge.TemplateResponse(
        request,
        "arhiviranje.html",
        {"snov": _pogled(material, mapa_druzine(nastavitve.images_dir, repozitorij.family_id))},
    )


@router.post("/materials/{material_id}/archive")
def arhiviraj(
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
) -> Response:
    """Umakne sliko v arhiv.

    Nadomešča brisanje, ki je do V1-R07 stalo na tem mestu. Slika izgine iz
    pregleda in jo telefon pri sebi zbriše, na strežniku pa ostane s prepisom
    in vprašanji (`docs/odlocitve/ADR-011`).
    """
    material = repozitorij.arhiviraj(material_id)
    if material is None:
        # Isto ravnanje kot pri brisanju: zapisa ni, izid je tak, kot ga je
        # operater hotel. Predmeta ni od kod prebrati, zato pelje na pregled.
        return RedirectResponse(PREDPONA, status_code=303)

    return _po_umiku(repozitorij, material.subject)


@router.post("/materials/{material_id}/purge-image")
def pocisti_sliko(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> Response:
    """Pobriše samo datoteko; vrstica, prepis in vprašanja ostanejo.

    To je vsakdanji način sproščanja prostora: velike so datoteke, ne vrstice.
    Dovoljen je pri arhiviranem zapisu ne glede na to, ali je telefon brisanje
    že potrdil — datoteka na strežniku s telefonom nima zveze.
    """
    material = repozitorij.poisci(material_id)
    if material is None:
        return ni_najdeno(predloge, request, "Zapisa s tem identifikatorjem na strežniku ni.")

    if material.archived_at is None:
        return ni_dovoljeno(
            predloge,
            request,
            "Sliko je mogoče počistiti šele, ko je zapis v arhivu.",
        )

    pot = Path(material.image_path)
    # Ista meja kot pri streženju slike: pot je zapisala naša koda, a je ne
    # jemljemo za dano — cena preverbe je ena vrstica, cena napačne
    # predpostavke pa brisanje poljubne datoteke s strežnika.
    if je_znotraj(mapa_druzine(nastavitve.images_dir, repozitorij.family_id), pot):
        pobrisi_sliko(pot)

    return RedirectResponse(
        f"{PREDPONA}/materials/{quote(material_id, safe='')}", status_code=303
    )


@router.get("/materials/{material_id}/delete")
def potrdi_brisanje(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> Response:
    """Vmesni korak pred dokončnim brisanjem. Sam ne spremeni ničesar."""
    material = repozitorij.poisci(material_id)
    if material is None:
        return ni_najdeno(predloge, request, "Zapisa s tem identifikatorjem na strežniku ni.")

    if material.device_deleted_at is None:
        return ni_dovoljeno(predloge, request, ZADRZANO)

    return predloge.TemplateResponse(
        request,
        "brisanje.html",
        {
            "snov": _pogled_podrobno(
                material, mapa_druzine(nastavitve.images_dir, repozitorij.family_id)
            )
        },
    )


@router.post("/materials/{material_id}/delete")
def izbrisi(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> Response:
    """Dokončno izbriše zapis in njegovo datoteko.

    Dovoljeno šele, ko je telefon potrdil, da zapisa pri njem ni več
    (`docs/odlocitve/ADR-011`). Preverba je tudi v repozitoriju; ta tu je zato,
    da operater dobi pojasnilo namesto tihe preusmeritve.
    """
    material = repozitorij.poisci(material_id)
    if material is not None and material.device_deleted_at is None:
        return ni_dovoljeno(predloge, request, ZADRZANO)

    # Najprej vrstica, nato datoteka — obratno kot pri sprejemu, in namenoma.
    # Vrstica brez datoteke je pokvarjen vnos, ki ga operater vidi; datoteka
    # brez vrstice je nevidna sirota, ki stane samo prostor. Če odpove drugi
    # korak, hočemo drugo napako (odločitev 5 v `docs/plan/V1-R04.md`).
    #
    # Vprašanja tega materiala ostanejo — z `material_id = NULL` in svojim
    # izvorom (`docs/odlocitve/ADR-012`).
    pobrisani = repozitorij.pobrisi(material_id)
    if pobrisani is None:
        # Zapisa ni; operater ga je izbrisal v drugem zavihku. Izid je tak, kot
        # ga je hotel.
        return RedirectResponse(f"{PREDPONA}/archive", status_code=303)

    # Ista meja kot pri „Počisti sliko" in pri streženju slike. Do V1-R07 je
    # ta klic meje ni imel; zdaj stojita poti druga ob drugi in razlike ne bi
    # pojasnilo nič.
    pot = Path(pobrisani.image_path)
    if je_znotraj(mapa_druzine(nastavitve.images_dir, repozitorij.family_id), pot):
        pobrisi_sliko(pot)

    # Nazaj v arhiv in ne na predmet: s seznama predmeta je bila ta slika
    # umaknjena že ob arhiviranju.
    return RedirectResponse(f"{PREDPONA}/archive", status_code=303)


@router.post("/materials/{material_id}/reprocess")
def ponovno_obdelaj(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
) -> Response:
    """Vrne zapis v vrsto in s tem sproži ponovno obdelavo.

    Samo `POST`, nikoli navadna povezava — enako pravilo kot pri brisanju
    (ADR-006). Dejanje je nepovratno: zavrže prejšnji prepis, povzetek in
    revizijsko sled (`docs/odlocitve/ADR-009`), dosedanja vprašanja pa
    **upokoji in ne izbriše** (`ADR-015`, ki nadomesti odločitev A1 iz
    `ADR-009`). Vmesne potrditvene strani vseeno ni, ker za razliko od
    brisanja slika ostane in se da obdelati znova.
    """
    material = repozitorij.poisci(material_id)
    if material is None:
        return ni_najdeno(predloge, request, "Zapisa s tem identifikatorjem na strežniku ni.")

    # Izid namenoma ne vpliva na odgovor. `False` pomeni, da je zapis že v
    # obdelavi; takrat je stran, na katero peljemo, prav tista, ki to pove.
    repozitorij.vrni_v_vrsto(material_id)

    # 303 iz istega razloga kot pri brisanju: osvežitev strani ne sme dejanja
    # ponoviti — tu bi to pomenilo še en plačan klic modela.
    return RedirectResponse(
        f"{PREDPONA}/materials/{quote(material_id, safe='')}", status_code=303
    )


def je_admin_pot(pot: str) -> bool:
    """Ali zahtevek pripada operaterski strani.

    Isto ujemanje kot pri izvzetju iz preverbe ključa: `/admin` in
    `/admin/...`, nikoli `/administration`.
    """
    return pot == PREDPONA or pot.startswith(f"{PREDPONA}/")


async def prestrezi_napako(request: Request, izjema: Exception) -> Response:
    """Napake pod `/admin` izriše kot stran, drugod pusti JSON.

    Prvi poskus je bil pot `/{ostanek:path}` na koncu usmerjevalnika. Bila je
    napačna: prekrila je Starlettejevo preusmeritev ob končni poševnici, zato
    je `GET /admin/` — naslov, ki ga brskalnik ponudi sam — vrnil 404 s
    trditvijo, da strani ni. Prestreznik se sproži šele, ko poti res ni, in se
    preusmeritve ne dotakne. Pokrije tudi 405, ki ga lovilec ni.

    Prestreznik je globalen, ker drugačnega FastAPI ne pozna, a se za vse
    izven `/admin` umakne privzetemu — odgovori `POST /materials` morajo
    ostati JSON, sicer telefon dobi HTML tam, kjer pričakuje sporočilo o
    napaki (odločitev 7 v `docs/plan/V1-R04.md`).
    """
    if isinstance(izjema, StarletteHTTPException) and je_admin_pot(request.url.path):
        if izjema.status_code == 404:
            sporocilo = "Te strani na strežniku ni."
        elif izjema.status_code == 405:
            sporocilo = "Ta stran tega dejanja ne podpira."
        else:
            # Sporočilo je sestavila naša koda in je slovensko — npr.
            # izbira družine v `app/dependencies.py`.
            sporocilo = str(izjema.detail)
        predloge: Jinja2Templates = request.app.state.predloge
        return predloge.TemplateResponse(
            request,
            "najdena-ni.html",
            {"sporocilo": sporocilo},
            status_code=izjema.status_code,
            # Privzeti ročnik pri 405 pošlje glavo `Allow`; brskalniku je vseeno,
            # orodjem ni, in zavreči jo brez razloga ni prav.
            headers=izjema.headers,
        )

    return await http_exception_handler(request, izjema)  # type: ignore[arg-type]
