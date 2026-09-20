"""Urnik otroka na operaterski strani (V3-R09).

Tri poti in ena predloga. Odločitve so v `docs/odlocitve/ADR-028` (kaj urnik
je), `ADR-041` (kod vstopi in kdaj se obdela) in `ADR-042` (kdaj se zapiše
slika); pravila so v `app/urnik.py`, poizvedbe v `ScheduleRepository`. Ta modul
je prenos: bere obrazec, kliče pravilo, izriše.

| Pot | Metoda | Kaj |
|---|---|---|
| `/admin/schedule` | GET | mreža s trenutno veljavnim urnikom izbranega otroka |
| `/admin/schedule/proposal` | POST | naloži sliko, pokliče model, izriše **predlagano** mrežo |
| `/admin/schedule` | POST | potrdi mrežo; upokoji prejšnji urnik |

**Mreža je vedno urejljiva, tudi brez nove slike** (`ADR-041` E). Slika je
način, da se mreža napolni, in ne edini vstop — sicer je edini odgovor na
neuspelo obdelavo nova fotografija iste stvari, prav to pa kriterij o neuspeli
obdelavi izrecno predvideva.

**Obdelava teče sinhrono** (`ADR-041` B): starš stoji pred zaslonom in izid je
obrazec, ki ga mora tako ali tako popraviti. Cena je čakanje do
`openai_timeout_seconds`; endpoint je zato `def` in ne `async def`, da ga
Starlette požene v pomožni niti in strežnik medtem streže naprej.

**Nepotrjen predlog ne obstaja kot vrstica.** Predlog živi v izrisani mreži in
v bazo pride šele potrditev, zato kriterija „nepotrjen predlog ne sproži
manjka" ni treba uveljavljati — uveljavlja ga odsotnost vrstice.
"""

import logging
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse, Response

from app.casi import IMENA_DNI
from app.db import ClaniRepository, ScheduleRepository
from app.dependencies import (
    daj_klicalca_urnika,
    daj_nastavitve,
    daj_repozitorij_clanov,
    daj_repozitorij_urnikov,
)
from app.otroci import PARAMETER as PARAMETER_OTROKA
from app.otroci import IzbiraOtroka, izberi_otroka
from app.settings import Settings
from app.storage import BereBajte, mapa_urnikov, pobrisi_sliko, shrani_sliko_urnika
from app.strani import daj_predloge, neveljavna_zahteva, ni_najdeno
from app.subjects import PREDMETI
from app.urnik import DNEVI, Urnik, Vnos
from app.vision import KlicalecUrnika, NapakaObdelave, PredlogUrnika

dnevnik = logging.getLogger(__name__)

#: Predpona te strani. Pod `/admin`, torej za sejo in s CSRF žetonom
#: (`ADR-035`); otrok sem ne pride, ker `prijava.Vrata` `/admin` zapre vsem
#: razen staršem (`ADR-041` D).
PREDPONA = "/admin/schedule"

router = APIRouter(prefix=PREDPONA)

#: Isto besedilo kot drugod za tujega in za neobstoječega otroka: obstoj tujega
#: računa ni podatek za starša (`ADR-038`, `ADR-039` B).
SPOROCILO_NEZNAN_OTROK = "Tega otroka v tvoji družini ni."

SPOROCILO_BREZ_OTROKA = (
    "Urnik je last otroka, v tvoji družini pa otroka še ni. Najprej ga dodaj "
    "na strani Družina."
)

SPOROCILO_BREZ_KLJUCA = (
    "Branje slik trenutno ne deluje, ker ključ za OpenAI ni nastavljen. "
    "Urnik lahko vseeno vneseš in potrdiš v spodnji mreži."
)

SPOROCILO_NEBERLJIVA = (
    "S te slike urnika ni bilo mogoče brati. Poskusi z ostrejšo ali bolj "
    "osvetljeno sliko, ali pa urnik vnesi v spodnjo mrežo."
)

SPOROCILO_PRAZNA_SLIKA = "Slike ni bilo. Izberi datoteko in poskusi znova."

SPOROCILO_NI_SLIKA = (
    "Naložiti je mogoče samo sliko (JPEG ali PNG). Izbrana datoteka to ni."
)

SPOROCILO_PREVELIKA = (
    "Slika je prevelika. Največ je {največ} MB; poskusi s fotografijo v "
    "manjši ločljivosti."
)

SPOROCILO_NEZNANA_KODA = (
    "Predmeta „{koda}“ ne poznam, zato urnik ni bil spremenjen. Izbrati je "
    "mogoče samo predmete iz mreže."
)

SPOROCILO_NEZNAN_DAN = (
    "Dneva „{dan}“ ne poznam, zato urnik ni bil spremenjen. Urnik pozna "
    "ponedeljek do petek."
)

#: Največja slika urnika, v bajtih.
#:
#: Omejitev je **svoja** in ne podedovana iz `POST /materials`: tam vhod
#: nastavi naša aplikacija na telefonu, tu pa brskalnik, ki mu pot ne piše
#: ničesar. Deset megabajtov je z veliko rezerve nad fotografijo urnika in
#: krepko pod tem, kar bi strežniku škodilo.
NAJVECJA_SLIKA = 10 * 1024 * 1024

#: Vrste, ki jih sprejmemo. Fotografija urnika je JPEG, posnetek zaslona PNG.
VRSTE_SLIK = frozenset({"image/jpeg", "image/png"})

#: Vrednosti izbirnika v eni celici mreže. Tri stanja in ne dve zastavici:
#: „ni na urniku", „se slika" in „se ne slika" so izključujoči, in dve
#: potrditveni polji bi dopustili četrto, nesmiselno kombinacijo.
CELICA_NI = ""
CELICA_SLIKA = "da"
CELICA_BREZ_SLIKE = "brez"
CELICE = (CELICA_NI, CELICA_SLIKA, CELICA_BREZ_SLIKE)


class NeveljavenObrazec(Exception):
    """Vrednost iz obrazca, ki je ni mogoče sprejeti.

    Nosi slovensko sporočilo. Izjema in ne vrnjena vrednost, ker branje mreže
    teče v dveh gnezdenih zankah in vsaka napaka zaključi obravnavo celote —
    urnik se spremeni v celoti ali nič (`ScheduleRepository.potrdi`).
    """

    def __init__(self, sporocilo: str) -> None:
        super().__init__(sporocilo)
        self.sporocilo = sporocilo


class _OmejenoBranje:
    """Ovoj nad naloženo datoteko, ki neha brati pri `najvec` bajtih.

    Preverba velikosti **med branjem** in ne iz glave `Content-Length`: to je
    trditev odjemalca, zapis na disk pa je dejanje. Brez tega bi `shrani_sliko`
    sprejel, kolikor bi kdo poslal.
    """

    def __init__(self, vir: BereBajte, najvec: int) -> None:
        self._vir = vir
        self._ostanek = najvec

    def read(self, size: int = -1, /) -> bytes:
        kos = self._vir.read(size)
        self._ostanek -= len(kos)
        if self._ostanek < 0:
            raise NeveljavenObrazec(
                SPOROCILO_PREVELIKA.format(največ=NAJVECJA_SLIKA // (1024 * 1024))
            )
        return kos


@dataclass(frozen=True)
class Celica:
    """Ena celica mreže, pripravljena za izris."""

    #: Ime polja v obrazcu, npr. `c0_MAT`.
    polje: str

    #: Izbrana vrednost: ena od `CELICE`.
    vrednost: str


@dataclass(frozen=True)
class Vrstica:
    """En predmet čez vseh pet dni."""

    koda: str
    oznaka: str
    celice: tuple[Celica, ...]


def ime_polja(dan: int, koda: str) -> str:
    """Ime polja ene celice v obrazcu.

    Dan je številka in ne ime, koda pa je iz `PREDMETI` — oboje je iz zaprtega
    nabora, zato ime polja ne more nositi ničesar, česar branje ne pričakuje.
    """
    return f"c{dan}_{koda}"


def mreza(urnik: Urnik | None) -> list[Vrstica]:
    """Mreža desetih predmetov čez pet dni, z izbranimi vrednostmi.

    **Cela mreža in ne le zasedene celice**: potrditev je celotna zamenjava in
    ne krpanje (`ScheduleRepository.potrdi`), zato mora obrazec pokazati tudi
    to, česar na urniku ni — sicer starš ne more ničesar odstraniti.

    Predmeti so v vrstnem redu `PREDMETI` in ne po abecedi, kot povsod drugod
    na `/admin`.
    """
    izbrano: dict[tuple[int, str], str] = {}
    if urnik is not None:
        for vnos in urnik.vnosi:
            izbrano[(vnos.dan, vnos.predmet)] = (
                CELICA_BREZ_SLIKE if vnos.se_ne_slika else CELICA_SLIKA
            )

    return [
        Vrstica(
            koda=predmet.koda,
            oznaka=predmet.oznaka,
            celice=tuple(
                Celica(
                    polje=ime_polja(dan, predmet.koda),
                    vrednost=izbrano.get((dan, predmet.koda), CELICA_NI),
                )
                for dan in DNEVI
            ),
        )
        for predmet in PREDMETI
    ]


def mreza_iz_predloga(predlog: PredlogUrnika) -> list[Vrstica]:
    """Mreža, napolnjena s tem, kar je model prebral.

    Nepreslikane celice v mrežo **ne** pridejo — v njej zanje ni stolpca, ker
    mreža pozna samo deset kod. Izpišejo se nad njo (`nepreslikane`), da ne
    izpadejo molče (kriterij `V3-R09`).

    Vse prebrane celice so `se slika`: `se_ne_slika` je pričakovanje starša o
    tem, ali iz predmeta slika sploh nastane, in tega s slike urnika ni mogoče
    prebrati (`ADR-028` F2).
    """
    return mreza(
        Urnik.iz_vnosov(
            Vnos(dan=celica.dan, predmet=celica.koda)
            for celica in predlog.celice
            if celica.koda is not None
        )
    )


def preberi_mrezo(obrazec: Any) -> list[Vnos]:
    """Vnosi iz oddane mreže; ob neveljavni vrednosti vrže `NeveljavenObrazec`.

    **Neznana koda ali dan sta 400 in ne tiho izpuščena celica** (kriterij
    `V3-R09`): obrazec sestavi naša predloga, zato je vsaka druga vrednost
    bodisi napaka v kodi bodisi ročno sestavljena zahteva, in v obeh primerih
    je tiho sprejeti del urnika slabši od zavrnitve celote.

    Manjkajoče polje pa ni napaka, ampak `CELICA_NI`: brskalniki naj smejo
    izpustiti prazno vrednost, in stara odprta stran po spremembi seznama
    predmetov naj ne pade na `KeyError`.
    """
    znane = {predmet.koda for predmet in PREDMETI}
    vnosi: list[Vnos] = []

    for kljuc, vrednost in obrazec.multi_items():
        if not kljuc.startswith("c") or "_" not in kljuc:
            continue
        oznaka_dneva, _, koda = kljuc[1:].partition("_")

        if not oznaka_dneva.isdigit() or int(oznaka_dneva) not in DNEVI:
            raise NeveljavenObrazec(SPOROCILO_NEZNAN_DAN.format(dan=oznaka_dneva))
        if koda not in znane:
            raise NeveljavenObrazec(SPOROCILO_NEZNANA_KODA.format(koda=koda))

        izbrano = str(vrednost)
        if izbrano not in CELICE:
            raise NeveljavenObrazec(SPOROCILO_NEZNANA_KODA.format(koda=koda))
        if izbrano == CELICA_NI:
            continue

        vnosi.append(
            Vnos(
                dan=int(oznaka_dneva),
                predmet=koda,
                se_ne_slika=izbrano == CELICA_BREZ_SLIKE,
            )
        )

    return vnosi


def _parameter_otroka(izbira: IzbiraOtroka) -> str:
    """`?otrok=…`, ali prazno, kadar se izbirnik ne izriše.

    Pri enem otroku parameter ne pove ničesar in bi se pojavil v vsaki
    povezavi družine, ki ga ne potrebuje (`ADR-039` B). Dvojček istoimenske
    funkcije v `app/routers/dnevi.py`.
    """
    if not izbira.je_izbirnik or izbira.izbrani is None:
        return ""
    return f"?{PARAMETER_OTROKA}={quote(izbira.izbrani.user_id, safe='')}"


def _kontekst(
    izbira: IzbiraOtroka,
    vrstice: list[Vrstica],
    *,
    ima_urnik: bool,
    slika_id: str | None = None,
    sporocilo: str | None = None,
    napaka: str | None = None,
    nepreslikane: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    """Kontekst predloge. Predloga ne računa in ne sestavlja naslovov."""
    return {
        "dnevi": [{"stevilka": dan, "ime": IMENA_DNI[dan]} for dan in DNEVI],
        "vrstice": vrstice,
        "ima_urnik": ima_urnik,
        # Gotov niz za vsako celico: predloga primerja vrednosti, ne pozna pa
        # njihovega pomena.
        "celica_ni": CELICA_NI,
        "celica_slika": CELICA_SLIKA,
        "celica_brez_slike": CELICA_BREZ_SLIKE,
        "slika_id": slika_id,
        "sporocilo": sporocilo,
        "napaka": napaka,
        "nepreslikane": nepreslikane,
        "je_izbirnik_otrok": izbira.je_izbirnik,
        "otrok_prvi": _parameter_otroka(izbira),
        "otroci": [{"id": kdo.user_id, "ime": kdo.display_name} for kdo in izbira.vsi],
        "izbrani_otrok": izbira.izbrani.user_id if izbira.izbrani is not None else None,
        "najvecja_slika_mb": NAJVECJA_SLIKA // (1024 * 1024),
        "ima_klicalca": True,
    }


def _izberi(
    clani: ClaniRepository, otrok: str | None
) -> IzbiraOtroka | None:
    """Izbrani otrok, ali `None` za 404.

    Tudi deaktivirani otroci: njihovi podatki ostanejo (`V3-R06`) in seznam,
    ki bi jih izpustil, bi njihov urnik naredil nedosegljiv.
    """
    return izberi_otroka(clani.otroci(), otrok)


@router.get("")
def stran_urnika(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    urniki: Annotated[ScheduleRepository, Depends(daj_repozitorij_urnikov)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    klicalec: Annotated[KlicalecUrnika | None, Depends(daj_klicalca_urnika)],
    otrok: str | None = None,
) -> Response:
    """Mreža s trenutno veljavnim urnikom izbranega otroka."""
    izbira = _izberi(clani, otrok)
    if izbira is None:
        return ni_najdeno(predloge, request, SPOROCILO_NEZNAN_OTROK)

    veljaven = (
        urniki.urnik(izbira.izbrani.user_id) if izbira.izbrani is not None else None
    )
    kontekst = _kontekst(izbira, mreza(veljaven), ima_urnik=veljaven is not None)
    kontekst["ima_klicalca"] = klicalec is not None
    if izbira.izbrani is None:
        kontekst["napaka"] = SPOROCILO_BREZ_OTROKA
    elif klicalec is None:
        kontekst["napaka"] = SPOROCILO_BREZ_KLJUCA

    return predloge.TemplateResponse(request, "urnik.html", kontekst)


@router.post("/proposal")
def predlagaj_urnik(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    urniki: Annotated[ScheduleRepository, Depends(daj_repozitorij_urnikov)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    klicalec: Annotated[KlicalecUrnika | None, Depends(daj_klicalca_urnika)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    slika: Annotated[UploadFile, File()],
    otrok: Annotated[str | None, Form()] = None,
) -> Response:
    """Prebere sliko urnika in izriše **predlagano** mrežo. V bazo ne piše nič.

    Vrstni red je namenski: slika se zapiše na disk **pred** klicem modela
    (`ADR-042`), ker klicalec bere s poti. Ob neuspelem klicu se pobriše —
    datoteka, na katero ne bo kazala nobena vrstica in je nihče ne bo potrdil,
    je sirota, ki jo tu še znamo pospraviti.
    """
    izbira = _izberi(clani, otrok)
    if izbira is None:
        return ni_najdeno(predloge, request, SPOROCILO_NEZNAN_OTROK)
    if izbira.izbrani is None:
        return neveljavna_zahteva(predloge, request, SPOROCILO_BREZ_OTROKA)

    veljaven = urniki.urnik(izbira.izbrani.user_id)

    def s_sporocilom(napaka: str) -> Response:
        """Mreža, kakršna je bila, z razlago. Urnik ostane nedotaknjen."""
        kontekst = _kontekst(izbira, mreza(veljaven), ima_urnik=veljaven is not None)
        kontekst["napaka"] = napaka
        kontekst["ima_klicalca"] = klicalec is not None
        return predloge.TemplateResponse(request, "urnik.html", kontekst)

    if klicalec is None:
        return s_sporocilom(SPOROCILO_BREZ_KLJUCA)
    if not slika.filename:
        return s_sporocilom(SPOROCILO_PRAZNA_SLIKA)
    if slika.content_type not in VRSTE_SLIK:
        return s_sporocilom(SPOROCILO_NI_SLIKA)

    slika_id = str(uuid4())
    try:
        pot = shrani_sliko_urnika(
            nastavitve.images_dir,
            urniki.family_id,
            slika_id,
            _OmejenoBranje(slika.file, NAJVECJA_SLIKA),
        )
    except NeveljavenObrazec as prevelika:
        return s_sporocilom(prevelika.sporocilo)

    try:
        predlog = klicalec(pot)
    except NapakaObdelave as napaka:
        # Sled gre v dnevnik in ne v bazo (`ADR-042`); staršu povemo, kaj naj
        # naredi, in ne surovega besedila napake.
        dnevnik.warning("Branje urnika ni uspelo: %s", napaka.sporocilo)
        pobrisi_sliko(pot)
        return s_sporocilom(napaka.sporocilo)

    if not predlog.readable:
        pobrisi_sliko(pot)
        return s_sporocilom(SPOROCILO_NEBERLJIVA)

    kontekst = _kontekst(
        izbira,
        mreza_iz_predloga(predlog),
        ima_urnik=veljaven is not None,
        slika_id=slika_id,
        sporocilo=(
            "Urnik je prebran. Preveri mrežo, popravi, kar je narobe, in potrdi."
        ),
        nepreslikane=tuple(
            (IMENA_DNI[celica.dan], celica.besedilo) for celica in predlog.nepreslikane
        ),
    )
    return predloge.TemplateResponse(request, "urnik.html", kontekst)


@router.post("")
async def potrdi_urnik(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    urniki: Annotated[ScheduleRepository, Depends(daj_repozitorij_urnikov)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> Response:
    """Potrdi mrežo: upokoji prejšnji urnik in vstavi novega.

    Obrazec se bere iz zahteve in ne skozi deklarirane parametre: polj je
    petdeset in njihova imena so izpeljana iz `PREDMETI`, zato bi jih bilo
    treba našteti dvakrat — enkrat v `PREDMETI` in enkrat tu. Deklarirani
    parametri bi seznam predmetov podvojili prav tam, kjer se mora ujemati.

    `async def` in ne `def`: tu ni klica modela, brati pa je treba telo
    zahteve. Pri predlogu je obratno — tam klic traja in mora v pomožno nit.
    """
    obrazec = await request.form()

    izbira = _izberi(clani, _polje(obrazec, PARAMETER_OTROKA))
    if izbira is None:
        return ni_najdeno(predloge, request, SPOROCILO_NEZNAN_OTROK)
    if izbira.izbrani is None:
        return neveljavna_zahteva(predloge, request, SPOROCILO_BREZ_OTROKA)

    try:
        vnosi = preberi_mrezo(obrazec)
    except NeveljavenObrazec as neveljaven:
        return neveljavna_zahteva(predloge, request, neveljaven.sporocilo)

    image_path = _pot_slike(nastavitve, urniki.family_id, _polje(obrazec, "slika_id"))

    if urniki.potrdi(izbira.izbrani.user_id, vnosi, image_path) is None:
        # Otrok je bil med izrisom in oddajo odstranjen iz družine. Isto
        # besedilo kot za tujega (`ADR-038`).
        return ni_najdeno(predloge, request, SPOROCILO_NEZNAN_OTROK)

    # 303 in ne izris: po `POST` mora osvežitev strani pomeniti branje in ne
    # ponovne potrditve.
    return RedirectResponse(f"{PREDPONA}{_parameter_otroka(izbira)}", status_code=303)


def _polje(obrazec: Any, ime: str) -> str | None:
    """Ena vrednost obrazca kot niz, ali `None`, kadar je prazna ali je ni."""
    vrednost = obrazec.get(ime)
    if vrednost is None:
        return None
    besedilo = str(vrednost).strip()
    return besedilo or None


def _pot_slike(nastavitve: Settings, family_id: str, slika_id: str | None) -> str | None:
    """Pot do naložene slike urnika, ali `None`, kadar slike ni bilo.

    Sestavi se **iz `slika_id`** in nikoli iz poti v skritem polju: pot je
    stvar strežnika, in vrednost iz obrazca bi pomenila, da vrstica lahko
    kaže kamorkoli po disku. `slika_id` mora biti UUID v kanonični obliki —
    ista preverba kot pri `storage.mapa_druzine` in iz istega razloga.

    `None` ni manjkajoč podatek, ampak resnica o nastanku: ta urnik je starš
    natipkal in ne prebral s slike (`ADR-041` E).
    """
    if slika_id is None:
        return None
    try:
        if str(UUID(slika_id)) != slika_id:
            return None
    except ValueError:
        return None

    return str(mapa_urnikov(nastavitve.images_dir, family_id) / f"{slika_id}.jpg")
