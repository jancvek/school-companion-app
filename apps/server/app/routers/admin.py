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

import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app import sistem
from app.besedilo import SLIKE, ZNAKI, stevilo_z_besedo
from app.casi import cas, cas_ali_prazno, v_domacem
from app.db import ClaniRepository, KviziRepository, MaterialsRepository
from app.dependencies import (
    daj_nastavitve,
    daj_repozitorij,
    daj_repozitorij_clanov,
    daj_repozitorij_kvizov,
)
from app.models import STATUS_V_OBDELAVI, Material, Question
from app.prepisi import SnovZaPrepis, VprasanjeZaPrepis, izbrane, sestavi
from app.routers.kvizi import seznam_kvizov
from app.settings import Settings
from app.storage import je_znotraj, mapa_druzine, pobrisi_sliko, velikost_slike
from app.strani import daj_predloge, neveljavna_zahteva, ni_dovoljeno, ni_najdeno
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
            # Ali je trenutna koda med desetimi. Snov s kodo iz starejše
            # gradnje telefona v izbiri ne more biti označena kot trenutna,
            # in brez tega bi brskalnik sam pokazal prvo možnost (`NAR`) —
            # neprevidna potrditev obrazca bi jo vložila pod Naravoslovje.
            "koda_znana": poisci_predmet(material.subject) is not None,
            # Ista dva pogoja kot pri ponovni obdelavi, a svoja zastavica:
            # razloga sta različna in se lahko kdaj razideta. Snov v obdelavi
            # se ne premika (`ADR-040` C1), arhivirana pa se ne ureja
            # (`ADR-011`). Obrazec, ki ga stran izriše zaman, bi lagal —
            # in gumb, ki ga ne izriše, ni varovalka, zato ista dva pogoja
            # nosi tudi `premakni_v_predmet`.
            "premik_mozen": (
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
    vse: str | None = None,
) -> Response:
    """Slike enega predmeta, najnovejša prva.

    `?vse=1` izriše isto stran z vsemi kljukicami (V3-R11). Povezava in ne
    skripta: „Izberi vse" mora delati tudi brez nje (`docs/odlocitve/ADR-048`
    G). Parameter se primerja točno z `1` — vrednost, ki je ne izriše nobena
    naša povezava, ne sme po tihem obkljukati celega predmeta.
    """
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
            # Pot je tu in ne v predlogi, ker mora skozi `quote`: koda s
            # poševnico ali vprašajem bi sicer povezavo razbila (isti razlog
            # kot pri `_po_umiku`).
            "pot_predmeta": _pot_predmeta(koda),
            "vse_obkljukano": vse == "1",
        },
    )


def _pot_predmeta(koda: str) -> str:
    """Naslov strani predmeta, ubežan za URL."""
    return f"{PREDPONA}/subjects/{quote(koda, safe='')}"


#: „Koliko polj sme imeti obrazec" — odgovor je: koliko jih gre v 1 MiB telesa.
#:
#: Neskončnost in ne veliko število, ker bi **vsaka končna meja vrnila prav
#: tisto stran, zaradi katere je ta konstanta nastala**: ob preseženi
#: `max_fields` vrže Starlette `MultiPartException`, ta postane `400`, in
#: uporabnica dobi golo angleško besedilo kot edino vsebino. Druga meja tu bi
#: torej problem samo premaknila navzgor, ne odpravila.
#:
#: **Cena je izmerjena, ne predpostavljena** (Python 3.12, `FormParser`):
#:
#: | telo | polj | čas razčlenjevanja |
#: |---|---|---|
#: | pošten izbor 1200 slik (50 KiB) | 1 200 | 0,012 s |
#: | 1 MiB samih praznih polj (`a=&`) | 349 525 | 3,4 s |
#:
#: Zgornja vrstica je to, kar zna poslati „Izberi vse"; spodnja je najslabše,
#: kar gre v telo, ki ga `SejaMiddleware` še sprejme (`NAJVECJE_TELO_OBRAZCA`).
#: Pomnilnik je s tem omejen (vrh ~85 MiB), **ni pa zastonj**: uvicorn teče brez
#: `--workers`, zato tak zahtevek za tri sekunde zadrži tudi prevzem slik s
#: telefona. Poslati ga zna samo prijavljen starš z veljavnim CSRF žetonom —
#: v modelu groženj te namestitve (`ADR-025`, `ADR-026`) torej lastnik sam, na
#: svojem strežniku. To je sprejeto zavestno; če se krog uporabnikov kdaj
#: razširi čez znance, je to ena od stvari, ki jih je treba premisliti znova.
BREZ_MEJE_POLJ = math.inf


def _polje_obrazca(obrazec: FormData, ime: str) -> str:
    """Eno besedilno polje obrazca; karkoli drugega velja za neposlano."""
    vrednost = obrazec.get(ime)
    return vrednost if isinstance(vrednost, str) else ""


def _za_prepis(
    material: Material, imena: dict[str, str], vprasanja: Sequence[Question] = ()
) -> SnovZaPrepis:
    """`Material` → vhod za sestavljanje besedila (V3-R11, V3-R12).

    Tu in ne v `app/prepisi.py`: ta pretvorba je edino mesto, kjer se odloči,
    katera polja snovi sploh smejo v besedilo, in modul za sestavljanje zato
    ostane brez sheme baze. Vprašanja poda klicalec, prebrana z eno poizvedbo
    (`docs/odlocitve/ADR-049` E) — `material.veljavna_vprasanja` se tu ne bere.
    """
    return SnovZaPrepis(
        id=material.id,
        koda=material.subject,
        taken_at=material.taken_at,
        otrok=imena.get(material.child_id),
        prepis=material.transcript,
        povzetek=material.summary,
        vprasanja=tuple(
            VprasanjeZaPrepis(vprasanje=v.question, odgovor=v.answer) for v in vprasanja
        ),
    )


@router.get("/transcripts")
def prepisi_nazaj() -> RedirectResponse:
    """Stran s prepisi nastane samo iz obrazca; `GET` pelje na pregled.

    Obstaja zato, da pot ni videti kot 405 (isti prijem kot
    `GET /admin/system/families` v V3-R05). Stran je trenutni izpis in ne
    stanje (`docs/odlocitve/ADR-048` B), zato je ni mogoče osvežiti ali dati
    med zaznamke — kdor to poskusi, pristane na pregledu in ne na napaki.
    """
    return RedirectResponse(PREDPONA, status_code=303)


@router.post("/transcripts")
async def prepisi_izbranih(
    request: Request,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
) -> Response:
    """Prepisi izbranih slik enega predmeta v enem polju (V3-R11).

    `POST` in ne `GET`: predmet bo čez šolsko leto nosil nekaj sto slik in
    ponovljen parameter z UUID bi dal naslov, ki bi odpovedal prav pri
    največjem izboru (`docs/odlocitve/ADR-048` B).

    **Ničesar ne zapiše** — ne v bazo in ne na disk. Nabor je isti seznam, ki
    ga izriše stran predmeta, zato tuj, arhiviran, tujepredmetni in
    neobstoječ identifikator iz njega preprosto izpadejo (`ADR-048` F).

    **`async def` in obrazec prebran sam**, namesto `Form()` parametrov (isti
    prijem kot `POST /admin/schedule`): ta izbor je eno polje na sliko, FastAPI
    pa telo prebere s Starlettejevim privzetkom `max_fields=1000`. Meja ni v
    `FormParser.parse`, ampak v povratnem klicu `on_field_end`, in ob preseženi
    vrže `MultiPartException` — stran s prepisi bi bila `400` z golim angleškim
    besedilom kot edino vsebino, in to bi „Izberi vse" na dovolj velikem
    predmetu dosegel z enim klikom. To je natanko odpoved pri največjem izboru,
    zaradi katere je `ADR-048` B izbral `POST` namesto `GET`, le pri drugem
    številu.

    Zato velja **ena sama meja: velikost telesa.** Tisto postavi
    `SejaMiddleware` (`NAJVECJE_TELO_OBRAZCA`, 1 MiB) in nanjo odgovori
    slovensko, preden zahteva sploh pride sem. Druga, skrita meja na številu
    polj bi pomenila dve različni odpovedi za isto dejanje — in ena od njiju
    ne bi znala povedati, kaj naj uporabnica naredi. Kaj to stane, je
    izmerjeno pri `BREZ_MEJE_POLJ`.
    """
    obrazec = await request.form(max_fields=BREZ_MEJE_POLJ)
    # Vrsta vsebine je `application/x-www-form-urlencoded`, zato so vse
    # vrednosti nizi; `isinstance` je tu zato, da tega ne trdi samo komentar.
    koda = _polje_obrazca(obrazec, "subject").rstrip("/")
    snov = [vrednost for vrednost in obrazec.getlist("snov") if isinstance(vrednost, str)]
    nabor = repozitorij.seznam_po_predmetu(koda) if koda else []
    imena = imena_otrok(clani)

    # Najprej izbor nad naborom, šele nato vprašanja — samo za izbrane, ne za
    # celoten predmet (`ADR-049` E).
    po_id = {material.id: material for material in nabor}
    izbor = izbrane([_za_prepis(material, imena) for material in nabor], snov)
    vprasanja = repozitorij.veljavna_vprasanja_snovi(s.id for s in izbor)
    izid = sestavi(
        [_za_prepis(po_id[s.id], imena, vprasanja.get(s.id, ())) for s in izbor]
    )

    return predloge.TemplateResponse(
        request,
        "prepisi.html",
        {
            "koda": koda,
            "besedilo": izid.besedilo if izid.slik else None,
            "slik_opis": stevilo_z_besedo(izid.slik, SLIKE),
            "znakov_opis": stevilo_z_besedo(izid.znakov, ZNAKI),
            # Prazen izbor ni napaka strežnika, ampak nedokončano dejanje;
            # sporočilo pove, kaj naj uporabnica naredi. Pot nazaj gre na
            # pregled, kadar bi bila stran predmeta 404 — enako kot `_po_umiku`.
            "pot_nazaj": (
                _pot_predmeta(koda)
                if nabor or poisci_predmet(koda) is not None
                else PREDPONA
            ),
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
        request,
        "snov.html",
        # `PREDMETI` in ne kode iz baze: premik je mogoč samo v enega od
        # desetih predmetov urnika (`ADR-040`), in prav premik je edino, kar
        # snov z neznano kodo spravi nazaj med deset. Da taka snov v izbiri
        # nima tihega privzetka, poskrbi `koda_znana` in vodilna možnost v
        # predlogi.
        {"snov": pogled, "povecava": povecava, "predmeti": PREDMETI},
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


@router.post("/materials/{material_id}/subject")
def premakni_v_predmet(
    request: Request,
    material_id: str,
    repozitorij: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    subject: Annotated[str, Form()] = "",
) -> Response:
    """Premakne sliko pod drug predmet, skupaj z vsemi njenimi vprašanji.

    Otrok ob slikanju včasih izbere napačen predmet; dotlej je bilo to
    mogoče popraviti samo na telefonu pred prenosom, kar v praksi pomeni
    nikoli (`docs/odlocitve/ADR-040`).

    `POST` in ne povezava, ker spremeni stanje. Vmesne potrditvene strani
    vseeno ni: za razliko od brisanja je premik povraten — snov se lahko
    premakne nazaj.

    Privzetek `""` in ne obvezno polje: brez njega bi manjkajoče polje
    obrodilo 422 s FastAPIjevim JSON-om, tu pa mora tudi napačna vrednost
    dobiti slovensko stran (merilo dokončanosti v `CLAUDE.md`).

    Izid premika namenoma ne vpliva na odgovor. `False` pomeni, da je snov
    arhivirana ali pravkar v obdelavi; takrat je stran, na katero peljemo,
    prav tista, ki to pove.
    """
    material = repozitorij.poisci(material_id)
    if material is None:
        return ni_najdeno(predloge, request, "Zapisa s tem identifikatorjem na strežniku ni.")

    # Preverba družine je prva: tuja snov ne sme z ničimer izdati, ali
    # obstaja — tudi ne z razliko med 400 in 404 (`ADR-025`).
    if poisci_predmet(subject) is None:
        return neveljavna_zahteva(
            predloge,
            request,
            "Predmet ni izbran ali pa ga ni na seznamu desetih predmetov "
            "urnika. Izberi enega od njih in poskusi znova.",
        )

    repozitorij.premakni_v_predmet(material_id, subject)

    # 303 iz istega razloga kot povsod pod `/admin`: osvežitev strani dejanja
    # ne sme ponoviti. Nazaj na snov in ne na predmet — po premiku je prav
    # stran snovi tista, ki pokaže, da je predmet zdaj drug.
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
        koda = izjema.status_code
        glave = izjema.headers
        if koda == 405 and sistem.je_skrita_pot(request.url.path):
            # Pod predpono lastnika sistema je **napačna metoda podatek**:
            # `405` pove, da pot obstaja, in kriterij `V3-R05` zahteva, da za
            # vse razen lastnika ne obstaja. Zato tu in ne v usmerjevalniku —
            # pravilo velja za vsako pot te predpone, tudi za tisto, ki bo
            # dodana jutri, in za vsako metodo, ki je ta pot nima
            # (`docs/odlocitve/ADR-044` G).
            #
            # **Glava `Allow` mora odpasti z njim:** ta našteje metode, ki jih
            # pot sprejema, in bi povedala natanko to, kar 404 skriva.
            #
            # Brez razlike po vlogi: lastnik tu izgubi le točnejše sporočilo ob
            # ročno vtipkanem naslovu, pravilo, ki bi se ravnalo po tem, kdo
            # sprašuje, pa bi imelo dve obnašanji in dve priložnosti za zmoto.
            koda = 404
            glave = None
        if koda == 404:
            sporocilo = "Te strani na strežniku ni."
        elif koda == 405:
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
            status_code=koda,
            # Privzeti ročnik pri 405 pošlje glavo `Allow`; brskalniku je vseeno,
            # orodjem ni, in zavreči jo brez razloga ni prav. Razlog je en sam:
            # skrita predpona zgoraj, kjer bi glava izdala, kaj pot sprejema.
            headers=glave,
        )

    return await http_exception_handler(request, izjema)  # type: ignore[arg-type]
