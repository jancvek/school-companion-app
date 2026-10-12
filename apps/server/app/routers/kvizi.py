"""Sestavljalnik kvizov na operaterski strani (V2-R01).

Trije vstopi vodijo v **isti** izbirnik slik in se razlikujejo po obsegu
seznama in po tem, kaj je vnaprej obkljukano (`docs/odlocitve/ADR-016` A,
popravljeno z `ADR-017` A). „Sestavi" pokaže predogled, ki **ničesar ne
shrani**; zapis v bazi nastane šele ob „Objavi", v eni transakciji
(`ADR-016` C).

Ključa te poti ne zahtevajo — so pod predpono `/admin` in zanje velja
`docs/odlocitve/ADR-006` v celoti, vključno z izpostavljenostjo prek tuje
strani (CSRF). Novih posledic ni: preklic kviza ničesar ne uniči, objava pa
ustvari zapis, ki ga je mogoče preklicati.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.besedilo import SNOVI, VPRASANJA, stevilo_z_besedo
from app.casi import (
    cas,
    cas_ali_prazno,
    dan_in_ura,
    dan_od_do,
    danes,
    datum,
    kratek_datum,
    mesec,
    oznaka_meseca,
    trajanje,
    v_domacem,
)
from app.db import (
    ClanDruzine,
    ClaniRepository,
    KviziRepository,
    MaterialsRepository,
    SnovSVprasanji,
    SnovZaIzbor,
)
from app.dependencies import (
    daj_nastavitve,
    daj_repozitorij,
    daj_repozitorij_clanov,
    daj_repozitorij_kvizov,
)
from app.models import (
    OCENE,
    STATUS_NAPAKA,
    STATUS_NOV,
    STATUS_V_OBDELAVI,
    Material,
    Ocena,
    QuestionAttempt,
    Quiz,
    QuizItem,
)
from app.settings import Settings
from app.storage import je_znotraj, mapa_druzine, velikost_slike
from app.strani import daj_predloge, neveljavna_zahteva, ni_dovoljeno, ni_najdeno
from app.subjects import (
    BARVA_NEZNANEGA,
    OZNAKE_OCEN,
    PREDMETI,
    barva_predmeta,
    oznaka_predmeta,
)
from app.tedni import oznaka_tedna, ponedeljek_tedna

#: Predpona poti sestavljalnika. Pod `/admin`, torej brez ključa (`ADR-006`).
PREDPONA = "/admin/quizzes"

router = APIRouter(prefix=PREDPONA)

#: Vstop „Nova snov": izbereš predmet, obkljukana je snov, ki še ni bila v kvizu.
VSTOP_NOVA = "nova"

#: Vstop „Kaj smo se danes učili": čez vse predmete, obkljukana današnja snov.
VSTOP_DANES = "danes"

#: Vstop „Ročna izbira": izbereš predmet, obkljukano ni nič.
VSTOP_ROCNA = "rocna"

VSTOPI = frozenset({VSTOP_NOVA, VSTOP_DANES, VSTOP_ROCNA})

#: Kviz mora imeti naslovljenca (`docs/odlocitve/ADR-039` A), zato družina
#: brez aktivnega otroka kviza ne more objaviti. Sporočilo pove, kaj naj starš
#: naredi, in ne le, česa ne gre.
SPOROCILO_BREZ_OTROKA = (
    "Kviz je vedno namenjen enemu otroku, tvoja družina pa nima nobenega "
    "aktivnega otroka. Najprej dodaj otroka v razdelku Družina."
)

#: Isto besedilo za tujega in za neobstoječega otroka (`ADR-038`).
SPOROCILO_NEZNAN_OTROK = "Tega otroka v tvoji družini ni."

#: Tri stanja kviza, v vrstnem redu zavihkov na `/admin/quizzes` (V5-R01).
#: Vrednosti so hkrati vrednosti parametra `?stanje=`.
STANJE_CAKA = "cakajo"
STANJE_RESEN = "reseni"
STANJE_PREKLICAN = "preklicani"
STANJA = (STANJE_CAKA, STANJE_RESEN, STANJE_PREKLICAN)
OZNAKE_STANJ = {
    STANJE_CAKA: "Čakajo",
    STANJE_RESEN: "Rešeni",
    STANJE_PREKLICAN: "Preklicani",
}
SPOROCILO_NEZNANO_STANJE = (
    "Tega stanja kvizov ne poznam. Izberi enega od zavihkov na strani Kvizi: "
    "Vsi, Čakajo, Rešeni ali Preklicani."
)

#: Objava brez naslovljenca. Kviz je vedno nekomu namenjen, zato je tih
#: privzetek tu napačen: kviz bi nastal za otroka, ki ga ni nihče izbral.
SPOROCILO_BREZ_NASLOVLJENCA = (
    "Kviza ni bilo mogoče objaviti, ker ni bilo izbrano, kateremu otroku je "
    "namenjen. Vrni se na izbor snovi, izberi otroka in klikni „Sestavi“."
)


def _imena(otroci: list[ClanDruzine]) -> dict[str, str]:
    """Preslikava `id` → prikazno ime, za oznako pri vrstici snovi.

    Prazna pri družini z enim otrokom: oznaka, ki ne loči ničesar, je na
    vsaki vrstici samo šum (`ADR-039` F). Vključuje tudi **deaktivirane**
    otroke — njihova snov ostane in mora imeti ime.
    """
    if len(otroci) < 2:
        return {}
    return {otrok.user_id: otrok.display_name for otrok in otroci}


def _ime_otroka(otroci: list[ClanDruzine], user_id: str) -> str | None:
    """Prikazno ime naslovljenca, ali `None` pri družini z enim otrokom.

    Isto pravilo kot `_imena` in kot izbirnik (`ADR-039` F3): vmesnik družine
    z enim otrokom se ne spremeni. Prvi zapis te funkcije je ime vračal vedno,
    z utemeljitvijo, da ga stavek o samooceni potrebuje — stavek je odtlej
    preoblikovan tako, da ga ne (`ADR-014` je zadoščeno, ker je v družini z
    enim otrokom jasno, čigava trditev je).
    """
    if len(otroci) < 2:
        return None
    return next((o.display_name for o in otroci if o.user_id == user_id), None)

#: Naslov izbirnika za vsak vstop. Operater mora na strani videti, od kod je
#: prišel — vsi trije vstopi so sicer videti enako.
#: Vrednosti parametra `?izbor=` na izbirniku (V5-R01).
IZBOR_VSE = "vse"
IZBOR_NIC = "nic"

NASLOVI = {
    VSTOP_NOVA: "Nova snov",
    VSTOP_DANES: "Kaj smo se danes učili",
    VSTOP_ROCNA: "Ročna izbira",
}

#: Koliko vprašanj na sliko, kadar operater polja ne spremeni (`ADR-016` D).
PRIVZETO_STEVILO = 3

#: Meji polja „vprašanj na sliko".
#:
#: Zgornja je 10, ker model vrne največ 10 vprašanj na sliko in višja številka ne
#: more prinesti ničesar. Meja je v obrazcu **in** tu: polje, ki ga stran
#: omeji, ni varovalka.
NAJMANJ_VPRASANJ = 1
NAJVEC_VPRASANJ = 10

#: Nad koliko vprašanji predogled opozori, da je kviz predolg.
PREDOLG_KVIZ = 30

#: Ime, pod katerim nastopa kviz čez več predmetov.
VSI_PREDMETI = "Vsi predmeti"

#: Meji dolžine, ki morata biti **enaki širini stolpcev** v `app/models.py`
#: (`Quiz.name` je `String(200)`, `Quiz.subject` `String(16)`).
#:
#: Preverba je tu in ne v `Form(max_length=…)` iz dveh razlogov: `Form` bi ob
#: predolgem vnosu vrnil surov angleški 422 (isti razlog kot pri
#: `_prebrano_stevilo`), predvsem pa tega ne sme ujeti šele baza. Testi tečejo
#: nad SQLite, ki dolžine `VARCHAR` **ne uveljavlja**; na Postgresu bi bil
#: predolg vnos `DataError` in operater bi dobil angleški „Internal Server
#: Error". To je razred napake, ki ga zelena zbirka ne pokaže.
NAJVEC_IME = 200
NAJVEC_KODA = 16

#: Ime skupine za postavko, ki v rešenem kvizu nima prepoznavne ocene.
#:
#: Ne bi smelo nastati — kviz je rešen šele, ko ima vsaka postavka poskus, in
#: strežnik sprejme samo štiri kode. Skupina je tu zato, da postavka v takem
#: primeru ne izpade **molče** iz rezultata.
BREZ_OCENE = "Brez ocene"

#: Kaj je za tisk obkljukano ob prvem prihodu. Namen zahteve: „natisniti samo
#: tista, ki so bila težka".
PRIVZETO_ZA_TISK: tuple[Ocena, ...] = ("nisem_vedela", "tezko")


def _stevilo_v_mejah(stevilo: int) -> int:
    """Vprašanj na sliko, omejeno na smiselno območje."""
    return max(NAJMANJ_VPRASANJ, min(stevilo, NAJVEC_VPRASANJ))


def _prebrano_stevilo(vrednost: str) -> int:
    """Polje „vprašanj na sliko" iz obrazca ali naslova.

    Bere se kot niz in ne kot `int`, ker bi FastAPI ob nerazberljivi vrednosti
    sam vrnil **422 s surovim angleškim JSON** (`Input should be a valid
    integer`) — pod predpono `/admin`, kjer je vse ostalo slovensko in kjer
    `CLAUDE.md` v merilu dokončanosti surovo sistemsko besedilo kot edino
    vsebino prepoveduje. Prestreznik v `create_app` lovi samo
    `StarletteHTTPException` in te napake ne pokrije.

    Nerazberljiva vrednost pade nazaj na privzetek; polje na strani takoj
    pokaže, kaj velja. Do tega pride le z ročno vtipkanim naslovom — polje v
    obrazcu je `type="number"`.
    """
    try:
        return _stevilo_v_mejah(int(vrednost))
    except ValueError:
        return PRIVZETO_STEVILO


def _razlog(snov: SnovZaIzbor) -> str | None:
    """Zakaj snovi ni mogoče dati v kviz, ali `None`, kadar je mogoče.

    Snov brez veljavnih vprašanj je **vidna, a neizbirna, z razlogom**; molčeč
    izpust bi pomenil kviz iz polovice dneva brez sledi, da manjka pol
    (`ADR-016` G).

    Četrti razlog („obdelano, a brez veljavnih vprašanj") ga kriterij ne
    našteje, stanje pa ga dopušča: snov, ki je bila poslana v ponovno obdelavo,
    ima vsa vprašanja upokojena (`ADR-015`). Brez te veje bi taka snov padla v
    „slika ni berljiva" in bi razlog lagal.
    """
    if snov.izbirna:
        return None
    if snov.material.status in (STATUS_NOV, STATUS_V_OBDELAVI):
        return "še v obdelavi"
    if snov.material.status == STATUS_NAPAKA:
        return "obdelava ni uspela"
    if snov.material.readable is False:
        return "slika ni berljiva"
    return "obdelano, a brez veljavnih vprašanj"


def _vrstica(
    snov: SnovZaIzbor,
    obkljukana: bool,
    mapa_slik: Path,
    ime_otroka: str | None = None,
) -> dict[str, Any]:
    """Ena vrstica izbirnika, pripravljena za predlogo.

    Predloga ne sklepa in ne oblikuje — dobi gotove vrednosti, tako kot
    `_pogled` na strani predmetov.
    """
    pot = Path(snov.material.image_path)
    ima_sliko = je_znotraj(mapa_slik, pot) and velikost_slike(pot) is not None
    return {
        "id": snov.material.id,
        "koda": snov.material.subject,
        "barva": barva_predmeta(snov.material.subject),
        "cas": cas(snov.material.taken_at),
        # Vrstica seznama po tednih (V5-R01): dan z imenom in ura.
        "dan_in_ura": dan_in_ura(snov.material.taken_at),
        "ponedeljek": ponedeljek_tedna(v_domacem(snov.material.taken_at).date()),
        # Izbirna snov, ki je že bila v kvizu za tega otroka, to pove —
        # sicer ni videti, zakaj je „Nova snov" ni obkljukala.
        "ze_v_kvizu": snov.ze_v_kvizu,
        "vprasanj": stevilo_z_besedo(snov.veljavnih_vprasanj, VPRASANJA),
        "izbirna": snov.izbirna,
        "razlog": _razlog(snov),
        "obkljukana": obkljukana,
        "ima_sliko": ima_sliko,
        # `None` pri družini z enim otrokom: ime, ki ne loči ničesar, je na
        # vsaki vrstici samo šum (`docs/odlocitve/ADR-039` F).
        "otrok": ime_otroka,
    }


def _predlagano_ime(subject: str | None, zdaj: datetime) -> str:
    """Samodejno ime kviza, npr. `MAT — 9. 9. 2026`.

    Datum je datum **nastanka kviza** in ne datum snovi: kviz iz zaostanka
    zajame več dni in en sam datum snovi bi bil laž. Koda predmeta in ne
    njegovo dolgo ime, ker je to zapis, ki ga operater bere v seznamu.
    """
    return f"{subject or VSI_PREDMETI} — {datum(zdaj)}"


@dataclass(frozen=True)
class Naslovljenec:
    """Otrok, ki mu bo kviz namenjen, in kaj naj ponudi izbirnik (`ADR-039` A)."""

    izbrani: ClanDruzine

    #: Vsi **aktivni** otroci družine, po prikaznem imenu. Deaktiviran otrok
    #: se ne more prijaviti, zato kviza zanj ni mogoče rešiti in se ne ponudi.
    vsi: tuple[ClanDruzine, ...]

    @property
    def je_izbirnik(self) -> bool:
        """Pri enem otroku se polje ne izriše — izbirati ni česa."""
        return len(self.vsi) > 1

    @property
    def ime_za_prikaz(self) -> str | None:
        """Prikazno ime, ali `None` pri družini z enim otrokom.

        **Edina pot do imena v izrisu.** `izbrani.display_name` se v
        usmerjevalniku ne bere neposredno: prvi zapis te zahteve je to počel in
        pravilo „ime samo pri več kot enem otroku" (`ADR-039` F3) je zato v
        sestavljalniku odpadlo, medtem ko je na sedmih drugih straneh veljalo.
        Pravilo, ki ga mora vsako klicno mesto uveljaviti samo, je pravilo, ki
        bo enkrat pozabljeno — zato stoji tu.
        """
        return self.izbrani.display_name if self.je_izbirnik else None


def _naslovljenec(
    predloge: Jinja2Templates,
    request: Request,
    otroci: list[ClanDruzine],
    zahtevani: str | None,
    *,
    obvezen: bool = False,
) -> Naslovljenec | Response:
    """Naslovljenec iz obrazca, ali privzetek; ob težavi vrne stran z napako.

    Dve zavrnitvi in vsaka pomeni drugo pot naprej (vzorec `ADR-038`):

    - **409**, kadar družina nima nobenega aktivnega otroka. Stanje družine
      tega dejanja ne dopušča; pove, kaj naj starš naredi. Isto pravilo na
      `/admin` vstopov sploh ne ponudi — gumb, ki ga stran ne izriše, ni
      varovalka.
    - **404**, kadar naslovljenec ni otrok te družine. Isto besedilo za
      tujega in za neobstoječega: obstoj tujega računa ni podatek za starša.

    Privzetek je **prvi po prikaznem imenu**, isti kot na statistiki
    (`ADR-039` B), in velja samo pri **branju** — ob prvem prihodu v izbirnik
    mora biti seznam že preračunan za nekoga. Ob objavi privzetka ni, zato
    imena tudi ni treba zapisati v gumbe: `ADR-039` G je ime tam zahteval prav
    zato, da privzetek ne bi bil tiha izbira, in te nevarnosti po `obvezen`
    ni več (`ADR-039` F3).

    **`obvezen=True` privzetka nima**, in to je kriterij `V3-R07`
    („sestavljalnik ga **zahteva** ob objavi"): objava brez polja je `409` in
    ne tih kviz za prvega otroka po abecedi. Utemeljitev „obrazec ga vedno
    pošlje" ne vzdrži — osvežena ali zaznamovana stran predogleda izpred te
    spremembe, ponovno pošiljanje iz zgodovine brskalnika in vsak prihodnji
    izris, ki bi skrito polje izgubil, dajo natanko tak zahtevek. Skrito polje
    ni varovalka, po istem pravilu kot gumb, ki ga stran ne izriše.

    Prazen niz šteje enako kot manjkajoče polje — tu in v `app/otroci.py`,
    da isti parameter nima dveh pomenov.
    """
    aktivni = [otrok for otrok in otroci if otrok.is_active]
    if not aktivni:
        return ni_dovoljeno(predloge, request, SPOROCILO_BREZ_OTROKA)

    if not zahtevani:
        if obvezen:
            return ni_dovoljeno(predloge, request, SPOROCILO_BREZ_NASLOVLJENCA)
        return Naslovljenec(izbrani=aktivni[0], vsi=tuple(aktivni))

    izbrani = next((otrok for otrok in aktivni if otrok.user_id == zahtevani), None)
    if izbrani is None:
        return ni_najdeno(predloge, request, SPOROCILO_NEZNAN_OTROK)
    return Naslovljenec(izbrani=izbrani, vsi=tuple(aktivni))


def _obseg(
    vstop: str, subject: str | None, zdaj: datetime
) -> tuple[str | None, datetime | None, datetime | None]:
    """Kaj naj izbirnik našteje pri danem vstopu (`ADR-017` A).

    Predmetna vstopa vso nearhivirano snov predmeta, dnevni samo današnjo čez
    vse predmete. To je razlika, ki je `ADR-016` (A) ni predvidel: brez nje bi
    dnevni vstop naštel celotno zgodovino vseh predmetov, da bi obkljukal tri
    današnje slike.
    """
    if vstop == VSTOP_DANES:
        od, do = dan_od_do(zdaj)
        return None, od, do
    return subject, None, None


def _je_obkljukana(vstop: str, snov: SnovZaIzbor) -> bool:
    """Ali je snov ob vstopu vnaprej obkljukana.

    Neizbirne snovi ne obkljuka noben vstop — obkljukati je mogoče samo tisto,
    kar gre lahko v kviz.
    """
    if not snov.izbirna:
        return False
    if vstop == VSTOP_NOVA:
        return not snov.ze_v_kvizu
    return vstop == VSTOP_DANES


def _izrisi_izbirnik(
    request: Request,
    predloge: Jinja2Templates,
    repozitorij: KviziRepository,
    mapa_slik: Path,
    vstop: str,
    subject: str | None,
    stevilo: int,
    naslovljenec: Naslovljenec,
    imena_otrok: dict[str, str],
    izbrane: set[str] | None = None,
    sporocilo: str | None = None,
    obkljukaj: str | None = None,
) -> Response:
    """Izriše izbirnik. Ena pot za vse tri vstope in za vrnitev iz predogleda.

    `obkljukaj` (`IZBOR_VSE` ali `IZBOR_NIC`) preglasi pravilo vstopa: starš je
    kliknil „Izberi vse" oziroma „Počisti izbor" (V5-R01).

    `izbrane` je `None` ob prvem prihodu (obkljuka pravilo vstopa) in množica
    identifikatorjev ob vrnitvi iz predogleda — takrat velja, kar je operater
    izbral, in ne več pravilo. Brez tega bi „Nazaj na izbor" izbor zavrgel,
    kriterij pa zahteva, da je „izbor tak, kot je bil".
    """
    zdaj = datetime.now(UTC)
    predmet, od, do = _obseg(vstop, subject, zdaj)
    # Seznam ni omejen na snov naslovljenca — vprašanja so last družine in
    # starš sme iz snovi enega otroka sestaviti kviz za drugega (kriterij
    # `V3-R07`). Naslovljenec odloča samo, kaj šteje kot „že v kvizu".
    snovi = repozitorij.snovi_za_izbor(
        naslovljenec.izbrani.user_id, subject=predmet, od=od, do=do
    )

    vrstice = [
        _vrstica(
            snov,
            obkljukana=(
                obkljukaj == IZBOR_VSE
                if obkljukaj is not None
                else _je_obkljukana(vstop, snov)
                if izbrane is None
                else snov.material.id in izbrane
            ),
            mapa_slik=mapa_slik,
            ime_otroka=imena_otrok.get(snov.material.child_id),
        )
        for snov in snovi
    ]

    # Seznam po tednih (V5-R01): vrstni red ostane od najnovejše navzdol,
    # nova skupina je vsaka menjava tedna.
    danasnji = danes()
    tedni: list[dict[str, Any]] = []
    for vrstica in vrstice:
        oznaka = oznaka_tedna(vrstica["ponedeljek"], danasnji)
        if not tedni or tedni[-1]["oznaka"] != oznaka:
            tedni.append({"oznaka": oznaka, "snovi": []})
        tedni[-1]["snovi"].append(vrstica)

    # Naslov iste strani z drugim otrokom ali drugim izborom: vse, kar ni
    # predmet menjave, potuje naprej.
    def naslov_izbirnika(**spremembe: str) -> str:
        polja = {
            "vstop": vstop,
            **({"subject": subject} if subject else {}),
            "stevilo": str(stevilo),
            "otrok": naslovljenec.izbrani.user_id,
            **spremembe,
        }
        return f"{PREDPONA}/new?" + "&".join(
            f"{kljuc}={quote(vrednost, safe='')}" for kljuc, vrednost in polja.items()
        )

    return predloge.TemplateResponse(
        request,
        "kvizi-izbirnik.html",
        {
            "tedni": tedni,
            # „Izberi vse / Počisti izbor" sta povezavi na isto stran, kot
            # `?vse=1` na strani predmeta (`ADR-048` G) — brez skripte.
            "href_izberi_vse": naslov_izbirnika(izbor=IZBOR_VSE),
            "href_pocisti": naslov_izbirnika(izbor=IZBOR_NIC),
            # Zavihki „Kviz za": menjava otroka gre skozi `GET`, ker se morajo
            # kljukice preračunati po pravilu vstopa (`ADR-039` G).
            "zavihki_otrok": [
                {
                    "oznaka": kdo.display_name,
                    "href": naslov_izbirnika(otrok=kdo.user_id),
                    "izbran": kdo.user_id == naslovljenec.izbrani.user_id,
                }
                for kdo in naslovljenec.vsi
            ]
            if naslovljenec.je_izbirnik
            else [],
            "vstop": vstop,
            "naslov": NASLOVI[vstop],
            "subject": subject,
            "oznaka": oznaka_predmeta(subject) if subject else VSI_PREDMETI,
            "cez_vse_predmete": vstop == VSTOP_DANES,
            "stevilo": stevilo,
            "najmanj": NAJMANJ_VPRASANJ,
            "najvec": NAJVEC_VPRASANJ,
            "izbirnih": sum(1 for vrstica in vrstice if vrstica["izbirna"]),
            "sporocilo": sporocilo,
            "naslovljenec": naslovljenec.izbrani.user_id,
        },
    )


def _preveri_vstop(
    predloge: Jinja2Templates, request: Request, vstop: str, subject: str | None
) -> Response | None:
    """Zavrne nesmiseln vstop; `None` pomeni, da je vstop v redu.

    Do tega ne pride s klikom — oba predmetna vstopa pošljeta izbrani predmet.
    Pride pa z ročno vtipkanim naslovom, in takrat je pojasnilo boljše od
    praznega izbirnika, ki bi trdil, da za ta predmet ni nič.
    """
    if vstop not in VSTOPI:
        return ni_najdeno(predloge, request, "Takega vstopa v sestavljalnik ni.")
    if vstop != VSTOP_DANES and not subject:
        return ni_najdeno(
            predloge,
            request,
            "Za ta vstop je treba izbrati predmet. Izberi ga v razdelku "
            "Kvizi na pregledni strani.",
        )
    return None


@router.get("/new")
def izbirnik(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repozitorij: Annotated[KviziRepository, Depends(daj_repozitorij_kvizov)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    vstop: str = VSTOP_NOVA,
    subject: str | None = None,
    stevilo: str = str(PRIVZETO_STEVILO),
    otrok: str | None = None,
    izbor: str | None = None,
) -> Response:
    """Izbirnik slik ob prihodu z enega od treh vstopov.

    `?izbor=vse` obkljuka vso izbirno snov in `?izbor=nic` nobene (V5-R01);
    brez parametra ali z drugo vrednostjo velja pravilo vstopa.

    Registriran je **pred** `/{quiz_id}`: FastAPI ujema po vrstnem redu in
    obratni vrstni red bi „new" prebral kot identifikator kviza.
    """
    napaka = _preveri_vstop(predloge, request, vstop, subject)
    if napaka is not None:
        return napaka

    otroci = clani.otroci()
    naslovljenec = _naslovljenec(predloge, request, otroci, otrok)
    if isinstance(naslovljenec, Response):
        return naslovljenec

    return _izrisi_izbirnik(
        request,
        predloge,
        repozitorij,
        mapa_druzine(nastavitve.images_dir, repozitorij.family_id),
        vstop=vstop,
        subject=subject,
        stevilo=_prebrano_stevilo(stevilo),
        naslovljenec=naslovljenec,
        imena_otrok=_imena(otroci),
        obkljukaj=izbor if izbor in (IZBOR_VSE, IZBOR_NIC) else None,
    )


@router.post("/new")
def izbirnik_z_izborom(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repozitorij: Annotated[KviziRepository, Depends(daj_repozitorij_kvizov)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    vstop: Annotated[str, Form()] = VSTOP_NOVA,
    subject: Annotated[str | None, Form()] = None,
    stevilo: Annotated[str, Form()] = str(PRIVZETO_STEVILO),
    snov: Annotated[list[str] | None, Form()] = None,
    otrok: Annotated[str | None, Form()] = None,
) -> Response:
    """Izbirnik ob vrnitvi iz predogleda („Nazaj na izbor").

    Ista stran kot `GET /new`, le da obkljuka to, kar je operater izbral.
    `POST` zato, ker izbor potuje kot seznam identifikatorjev in ne kot naslov.

    Naslovljenec pride v skritem polju in se tu **ne menja**: menjava gre skozi
    `GET /new`, ker mora kljukice preračunati po pravilu vstopa za novega
    otroka (`ADR-039` G), tega pa vrnitev iz predogleda ne sme — tam velja
    izbor, ki ga je operater naredil.
    """
    napaka = _preveri_vstop(predloge, request, vstop, subject)
    if napaka is not None:
        return napaka

    otroci = clani.otroci()
    naslovljenec = _naslovljenec(predloge, request, otroci, otrok)
    if isinstance(naslovljenec, Response):
        return naslovljenec

    return _izrisi_izbirnik(
        request,
        predloge,
        repozitorij,
        mapa_druzine(nastavitve.images_dir, repozitorij.family_id),
        vstop=vstop,
        subject=subject,
        stevilo=_prebrano_stevilo(stevilo),
        naslovljenec=naslovljenec,
        imena_otrok=_imena(otroci),
        izbrane=set(snov or []),
    )


@router.post("/preview")
def predogled(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repozitorij: Annotated[KviziRepository, Depends(daj_repozitorij_kvizov)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    vstop: Annotated[str, Form()] = VSTOP_NOVA,
    subject: Annotated[str | None, Form()] = None,
    stevilo: Annotated[str, Form()] = str(PRIVZETO_STEVILO),
    snov: Annotated[list[str] | None, Form()] = None,
    otrok: Annotated[str | None, Form()] = None,
) -> Response:
    """Predogled izbranih vprašanj. **Ničesar ne shrani** (`ADR-016` C).

    `POST` in ne `GET`: izbor je lahko sto identifikatorjev in v naslovu bi bil
    predolg. Osvežitev strani dejanje ponovi in prav nič ne naredi — prav zato,
    ker se nič ne shrani.
    """
    napaka = _preveri_vstop(predloge, request, vstop, subject)
    if napaka is not None:
        return napaka

    otroci = clani.otroci()
    naslovljenec = _naslovljenec(predloge, request, otroci, otrok)
    if isinstance(naslovljenec, Response):
        return naslovljenec

    koliko = _prebrano_stevilo(stevilo)
    izbrane = list(snov or [])

    skupine = [
        skupina
        for skupina in repozitorij.snovi_z_vprasanji(izbrane, koliko)
        # Snov brez vprašanj v predogled ne pride: v izbirniku je neizbirna in
        # tu bi bila prazen naslov. Zgodi se ob spremenjenem obrazcu ali ob
        # ponovni obdelavi, ki je stekla med izborom in „Sestavi".
        if skupina.vprasanja
    ]
    if not skupine:
        return _izrisi_izbirnik(
            request,
            predloge,
            repozitorij,
            mapa_druzine(nastavitve.images_dir, repozitorij.family_id),
            vstop=vstop,
            subject=subject,
            stevilo=koliko,
            naslovljenec=naslovljenec,
            imena_otrok=_imena(otroci),
            izbrane=set(izbrane),
            sporocilo=(
                "Izberi vsaj eno snov, ki ima vprašanja. Praznega kviza ni "
                "mogoče sestaviti."
            ),
        )

    zdaj = datetime.now(UTC)
    predmet, od, do = _obseg(vstop, subject, zdaj)
    # Izpuščene se štejejo nad **celotnim obsegom vstopa**, ne nad izborom:
    # vprašanje, na katero predogled odgovarja, je „koliko snovi tega predmeta
    # oziroma dneva danes ne more v kviz", in ne „koliko sem jih odkljukal".
    izpusceno = sum(
        1
        for vrstica in repozitorij.snovi_za_izbor(
            naslovljenec.izbrani.user_id, predmet, od, do
        )
        if not vrstica.izbirna
    )

    skupaj = sum(len(skupina.vprasanja) for skupina in skupine)
    return predloge.TemplateResponse(
        request,
        "kvizi-predogled.html",
        {
            "vstop": vstop,
            "subject": subject,
            "stevilo": koliko,
            "izbrane": izbrane,
            # Naslovljenec potuje skozi predogled v skritem polju, kot ves
            # ostali izbor: predogled ničesar ne shrani (`ADR-016` C). Ime je
            # vrednost polja v vrstici pod naslovom in ga pri enem otroku ni —
            # v gumbih ga ni več, ker objava privzetka nima (`ADR-039` F3).
            "naslovljenec": naslovljenec.izbrani.user_id,
            "naslovljenec_ime": naslovljenec.ime_za_prikaz,
            "skupine": _skupine_predogleda(skupine),
            "vprasanja_idji": [
                vprasanje.id for skupina in skupine for vprasanje in skupina.vprasanja
            ],
            "skupaj": skupaj,
            "skupaj_opis": stevilo_z_besedo(skupaj, VPRASANJA),
            "snovi": len(skupine),
            # Izpuščene se štejejo čez **cel obseg vstopa**, zato mora
            # besedilo imenovati ta obseg in ne izbora.
            "izpusceno_opis": (
                f"{stevilo_z_besedo(izpusceno, SNOVI)} "
                f'{"tega dne" if vstop == VSTOP_DANES else "tega predmeta"}'
            ),
            "predolg": skupaj > PREDOLG_KVIZ,
            "meja": PREDOLG_KVIZ,
            "izpusceno": izpusceno,
            "predlagano_ime": _predlagano_ime(
                None if vstop == VSTOP_DANES else subject, zdaj
            ),
        },
    )


def _skupina_pogled(skupina: SnovSVprasanji, prva_stevilka: int = 1) -> dict[str, Any]:
    """Ena snov s svojimi vprašanji, pripravljena za predogled.

    `prva_stevilka` je številka prvega vprašanja te snovi **v kvizu**: predogled
    šteje zvezno čez vse snovi (V5-R01), ker je to številka, pod katero bo
    vprašanje otrok videl na telefonu.
    """
    return {
        "id": skupina.material.id,
        "koda": skupina.material.subject,
        "barva": barva_predmeta(skupina.material.subject),
        "cas": cas(skupina.material.taken_at),
        "dan_in_ura": dan_in_ura(skupina.material.taken_at),
        "vprasanj_opis": stevilo_z_besedo(len(skupina.vprasanja), VPRASANJA),
        "vprasanja": [
            {"stevilka": stevilka, "vprasanje": vprasanje.question, "odgovor": vprasanje.answer}
            for stevilka, vprasanje in enumerate(skupina.vprasanja, start=prva_stevilka)
        ],
    }


def _skupine_predogleda(skupine: Sequence[SnovSVprasanji]) -> list[dict[str, Any]]:
    """Snovi predogleda z zvezno številko vprašanja čez cel kviz."""
    pogledi: list[dict[str, Any]] = []
    naslednja = 1
    for skupina in skupine:
        pogledi.append(_skupina_pogled(skupina, naslednja))
        naslednja += len(skupina.vprasanja)
    return pogledi


@router.post("")
def objavi(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repozitorij: Annotated[KviziRepository, Depends(daj_repozitorij_kvizov)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    ime: Annotated[str, Form()] = "",
    vstop: Annotated[str, Form()] = VSTOP_NOVA,
    subject: Annotated[str | None, Form()] = None,
    vprasanje: Annotated[list[str] | None, Form()] = None,
    otrok: Annotated[str | None, Form()] = None,
) -> Response:
    """Ustvari kviz iz predogledanih vprašanj, v eni transakciji.

    Obrazec pove, **katera** vprašanja; kaj v njih piše, se prebere iz baze.
    Neznan identifikator pomeni zavrnitev in ne krajši kviz — polovičen kviz,
    ki tega ne pove, je slabši od zavrnitve, ki jo operater vidi.

    Ta pot je edina, ki v bazo **piše**, zato vsakemu polju pogleda pod prste:
    vstop, dolžino imena in dolžino kode predmeta. Prej tega ni delala, ker
    vse troje pride iz skritih polj, ki jih je izrisal predogled — a skrito
    polje ni varovalka, po istem pravilu kot gumb, ki ga stran ne izriše.
    """
    napaka = _preveri_vstop(predloge, request, vstop, subject)
    if napaka is not None:
        return napaka

    # Naslovljenec je preverjen **pred** vsem ostalim in tu **nima
    # privzetka**: kriterij pravi, da ga sestavljalnik ob objavi zahteva.
    # Manjkajoč je 409, tuj 404, družina brez otroka 409 (`ADR-039` A).
    naslovljenec = _naslovljenec(predloge, request, clani.otroci(), otrok, obvezen=True)
    if isinstance(naslovljenec, Response):
        return naslovljenec

    ime = ime.strip()
    if len(ime) > NAJVEC_IME:
        return ni_dovoljeno(
            predloge,
            request,
            f"Ime kviza je predolgo: {len(ime)} znakov, največ jih sme biti "
            f"{NAJVEC_IME}. Skrajšaj ga in poskusi znova.",
        )

    if subject is not None and len(subject) > NAJVEC_KODA:
        return ni_dovoljeno(
            predloge,
            request,
            "Koda predmeta je predolga. Kviz sestavi znova prek razdelka "
            "Kvizi na pregledni strani.",
        )

    idji = list(vprasanje or [])
    if not idji:
        return ni_dovoljeno(
            predloge,
            request,
            "Kviza ni bilo mogoče objaviti, ker ni bilo izbrano nobeno "
            "vprašanje. Vrni se na izbor snovi in klikni „Sestavi“.",
        )

    vprasanja = repozitorij.vprasanja_po_idjih(idji)
    if vprasanja is None:
        return ni_dovoljeno(
            predloge,
            request,
            "Kviza ni bilo mogoče objaviti: izbor vprašanj ni veljaven — "
            "kakšnega vprašanja ni več ali pa se je katero ponovilo. Vrni se "
            "in sestavi izbor znova.",
        )

    predmet = None if vstop == VSTOP_DANES else (subject or None)
    kviz = repozitorij.objavi(
        ime=ime or _predlagano_ime(predmet, datetime.now(UTC)),
        subject=predmet,
        vprasanja=vprasanja,
        naslovljenec=naslovljenec.izbrani.user_id,
    )

    # 303 iz istega razloga kot pri brisanju in ponovni obdelavi: osvežitev
    # strani ne sme dejanja ponoviti — tu bi to pomenilo drugi enak kviz.
    return RedirectResponse(f"{PREDPONA}/{quote(kviz.id, safe='')}", status_code=303)


def _pogled_kviza(kviz: Quiz, postavk: int, imena: dict[str, str]) -> dict[str, Any]:
    """Kviz brez postavk — za seznam na `/admin` in za glavo strani kviza.

    `imena` je prazen pri družini z enim otrokom: naslovljenec, ki je lahko
    samo eden, na vsaki vrstici ne pove ničesar (`docs/odlocitve/ADR-039` F).
    Ime je tudi tam, kjer otroka ni v preslikavi (podatek iz ročno spremenjene
    baze), `None` — in stran ga takrat izpusti, ne pa pokaže surov `id`.
    """
    return {
        "id": kviz.id,
        "ime": kviz.name,
        "otrok": imena.get(kviz.child_id),
        "koda": kviz.subject or VSI_PREDMETI,
        # Barva čipa; kviz čez več predmetov svoje nima (V5-R01).
        "barva": barva_predmeta(kviz.subject) if kviz.subject else BARVA_NEZNANEGA,
        "stanje": stanje_kviza(kviz),
        "nastal_kratko": kratek_datum(kviz.created_at),
        "resen_kratko": kratek_datum(kviz.solved_at) if kviz.solved_at is not None else None,
        "nastal": cas(kviz.created_at),
        # Sam datum za seznam: tam je ura odveč, predmet in datum pa sta
        # kriterij — ime je prepisljivo in ju ob prepisu ne nosi več.
        "nastal_datum": datum(kviz.created_at),
        "vprasanj": postavk,
        "vprasanj_opis": stevilo_z_besedo(postavk, VPRASANJA),
        "preklican": kviz.canceled_at is not None,
        "preklican_ob": cas_ali_prazno(kviz.canceled_at),
        # Rešenost je svoja os (V2-R02). Preklican kviz je lahko tudi rešen
        # (`ADR-019` C); katera ima prednost, odloči predloga.
        "resen": kviz.solved_at is not None,
        "resen_ob": cas_ali_prazno(kviz.solved_at),
        "resen_datum": datum(kviz.solved_at) if kviz.solved_at is not None else None,
    }


def stanje_kviza(kviz: Quiz) -> str:
    """V katerem od treh stanj je kviz; vsak pade v natanko eno.

    Preklic ima prednost pred rešenostjo (`ADR-019` C): preklican kviz, ki ga
    je telefon vseeno rešil, je preklican. To pravilo je bilo do V5-R01 v
    predlogi; odkar po stanju filtrira tudi stran `/admin/quizzes`, je tu.
    """
    if kviz.canceled_at is not None:
        return STANJE_PREKLICAN
    if kviz.solved_at is not None:
        return STANJE_RESEN
    return STANJE_CAKA


def seznam_kvizov(
    repozitorij: KviziRepository, otroci: list[ClanDruzine], *, najvec: int | None = None
) -> list[dict[str, Any]]:
    """Kvizi za razdelek na `/admin`, najnovejši prvi.

    Živi tu in ne v `admin.py`, ker je oblika kviza stvar tega modula; `admin`
    jo samo pokliče in preda predlogi. `najvec` je za Predmete, ki pokažejo
    zadnje štiri in povezavo na vse (`ADR-056` G).
    """
    imena = _imena(otroci)
    vsi = repozitorij.seznam()
    if najvec is not None:
        vsi = vsi[:najvec]
    return [_pogled_kviza(kviz, postavk, imena) for kviz, postavk in vsi]


def predmeti_za_izbiro(kode_s_slikami: Iterable[str]) -> list[dict[str, str]]:
    """Predmeti za izbirnik v obrazcu „Nov kviz".

    Deset predmetov v vrstnem redu urnika, nato kode, ki so v bazi in jih na
    seznamu ni — predmet zunaj seznama ostane povsod viden (`subjects.py`),
    in kviz iz njega je bilo mogoče sestaviti že na `/admin`.
    """
    znane = {predmet.koda for predmet in PREDMETI}
    return [
        *({"koda": predmet.koda, "oznaka": predmet.oznaka} for predmet in PREDMETI),
        *(
            {"koda": koda, "oznaka": "predmet ni na seznamu"}
            for koda in sorted(set(kode_s_slikami) - znane)
        ),
    ]


def _po_mesecih(izbrani: list[tuple[Quiz, int]], imena: dict[str, str]) -> list[dict[str, Any]]:
    """Kvizi v skupinah po mesecu objave, v domačem pasu; vrstni red ostane.

    Seznam je že urejen od najnovejšega, zato je nova skupina vsaka menjava
    meseca. Razvrščanje je v Pythonu iz istega razloga kot pri statistiki:
    izraz za lokalni mesec v SQL ni prenosljiv med SQLite in Postgresom.
    """
    skupine: list[dict[str, Any]] = []
    zadnji: tuple[int, int] | None = None
    for kviz, postavk in izbrani:
        kljuc = mesec(kviz.created_at)
        if kljuc != zadnji:
            oznaka = oznaka_meseca(*kljuc)
            skupine.append({"oznaka": oznaka[0].upper() + oznaka[1:], "kvizi": []})
            zadnji = kljuc
        skupine[-1]["kvizi"].append(_pogled_kviza(kviz, postavk, imena))
    return skupine


def _naslov_seznama(stanje: str | None, otrok: str | None) -> str:
    """Naslov strani z izbranima filtroma; oba potujeta skupaj.

    Zavihek stanja mora nositi izbranega otroka in obratno, sicer bi menjava
    enega tiho ponastavila drugega (isto pravilo kot `?leto=` in `?otrok=` na
    statistiki).
    """
    deli = []
    if stanje:
        deli.append(f"stanje={quote(stanje, safe='')}")
    if otrok:
        deli.append(f"otrok={quote(otrok, safe='')}")
    return PREDPONA + ("?" + "&".join(deli) if deli else "")


@router.get("")
def vsi_kvizi(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repozitorij: Annotated[KviziRepository, Depends(daj_repozitorij_kvizov)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    snovi: Annotated[MaterialsRepository, Depends(daj_repozitorij)],
    stanje: str | None = None,
    otrok: str | None = None,
) -> Response:
    """Vsi kvizi družine s filtroma po stanju in otroku (V5-R01, `ADR-056` G).

    Brez parametrov pokaže vse. **Neznano stanje je 400** in ne tih padec na
    „vsi": filter, ki ne filtrira, bi bil videti, kot da filtrira. **Tuj ali
    neznan otrok je 404** z istim besedilom kot povsod (`ADR-039` B).
    Prazen niz šteje pri obeh kot „brez filtra".
    """
    stanje = stanje or None
    otrok = otrok or None
    if stanje is not None and stanje not in STANJA:
        return neveljavna_zahteva(predloge, request, SPOROCILO_NEZNANO_STANJE)

    otroci = clani.otroci()
    # Tudi deaktivirani: njihovi kvizi ostanejo (`ADR-039` F2).
    if otrok is not None and otrok not in {clan.user_id for clan in otroci}:
        return ni_najdeno(predloge, request, SPOROCILO_NEZNAN_OTROK)

    vsi = [
        (kviz, postavk)
        for kviz, postavk in repozitorij.seznam()
        if otrok is None or kviz.child_id == otrok
    ]
    # Števila v zavihkih stanja veljajo za izbranega otroka.
    koliko = dict.fromkeys(STANJA, 0)
    for kviz, _postavk in vsi:
        koliko[stanje_kviza(kviz)] += 1
    izbrani = [
        (kviz, postavk)
        for kviz, postavk in vsi
        if stanje is None or stanje_kviza(kviz) == stanje
    ]

    zavihki_stanja = [
        {
            "oznaka": "Vsi",
            "stevilo": len(vsi),
            "href": _naslov_seznama(None, otrok),
            "izbran": stanje is None,
        },
        *(
            {
                "oznaka": OZNAKE_STANJ[kljuc],
                "stevilo": koliko[kljuc],
                "href": _naslov_seznama(kljuc, otrok),
                "izbran": stanje == kljuc,
            }
            for kljuc in STANJA
        ),
    ]
    # Zavihki otrok samo pri več kot enem otroku (`ADR-039` B).
    zavihki_otrok: list[dict[str, Any]] = []
    if len(otroci) > 1:
        zavihki_otrok = [
            {
                "oznaka": "Oba" if len(otroci) == 2 else "Vsi",
                "href": _naslov_seznama(stanje, None),
                "izbran": otrok is None,
            },
            *(
                {
                    "oznaka": clan.display_name,
                    "href": _naslov_seznama(stanje, clan.user_id),
                    "izbran": otrok == clan.user_id,
                }
                for clan in otroci
            ),
        ]

    imena = _imena(otroci)
    return predloge.TemplateResponse(
        request,
        "kvizi.html",
        {
            "meseci": _po_mesecih(izbrani, imena),
            "zavihki_stanja": zavihki_stanja,
            "zavihki_otrok": zavihki_otrok,
            "je_filter": stanje is not None or otrok is not None,
            "je_stolpec_otrok": bool(imena),
            "predmeti_za_kviz": predmeti_za_izbiro(snovi.stej_po_predmetih()),
            # Kviz mora imeti naslovljenca (`ADR-039` A): brez aktivnega
            # otroka obrazca ni, isto pravilo kot na Predmetih.
            "ima_otroka": any(clan.is_active for clan in otroci),
        },
    )


def _skupine(
    postavke: list[QuizItem], poskusi: dict[str, QuestionAttempt]
) -> list[tuple[Ocena | None, list[tuple[QuizItem, QuestionAttempt | None]]]]:
    """Postavke po oceni, od najtežje navzdol; znotraj skupine po `position`.

    Vse štiri skupine so vedno tu, tudi prazne — kriterij zahteva „število v
    vsaki skupini", in skupina, ki manjka, števila nima. Peta (`None`, „brez
    ocene") je samo, kadar ni prazna; glej `BREZ_OCENE`.

    Postavke pridejo iz `Quiz.postavke`, ki je že urejena po `position`, zato
    je vrstni red znotraj skupine le ohranjen.
    """
    # Ključ je `str` in ne `Ocena`: `rating` je v bazi niz, in slovar mora znati
    # povedati, da neke kode v njem ni.
    po_oceni: dict[str, list[tuple[QuizItem, QuestionAttempt | None]]] = {
        ocena: [] for ocena in OCENE
    }
    brez: list[tuple[QuizItem, QuestionAttempt | None]] = []
    for postavka in postavke:
        poskus = poskusi.get(postavka.id)
        if poskus is not None and poskus.rating in po_oceni:
            po_oceni[poskus.rating].append((postavka, poskus))
        else:
            brez.append((postavka, poskus))

    skupine: list[tuple[Ocena | None, list[tuple[QuizItem, QuestionAttempt | None]]]] = [
        (ocena, po_oceni[ocena]) for ocena in OCENE
    ]
    if brez:
        skupine.append((None, brez))
    return skupine


def _opombe_izvora(postavka: QuizItem, snov: Material, mapa_slik: Path) -> list[str]:
    """Kaj mora operater vedeti o izvorni snovi, preden klikne povezavo.

    Samo v rezultatu (`docs/plan/V2-R03.md`, odločitev 3): stran nerešenega
    kviza ostane, kakršna je bila, ker test iz `V2-R01` dokazuje, da je ponovna
    obdelava ne spremeni.

    Slika „na disku" pomeni isto kot v izbirniku — znotraj `mapa_slik` in
    berljive velikosti.
    """
    opombe: list[str] = []
    pot = Path(snov.image_path)
    ima_sliko = je_znotraj(mapa_slik, pot) and velikost_slike(pot) is not None
    if snov.archived_at is not None:
        opombe.append(
            "v arhivu" if ima_sliko else "v arhivu, slika počiščena — prepis je na strani snovi"
        )
    elif not ima_sliko:
        opombe.append("slike ni na disku")

    # Upokojeno vprašanje pomeni, da je bila snov po objavi ponovno obdelana:
    # prepis na strani snovi je iz novejše obdelave in ni tisti, iz katerega je
    # to vprašanje nastalo (`ADR-015`).
    if postavka.question is not None and postavka.question.retired_at is not None:
        opombe.append(
            "snov je bila medtem ponovno obdelana — prepis na strani snovi je "
            "novejši od tega vprašanja"
        )
    return opombe


def _postavka_rezultata(
    postavka: QuizItem,
    poskus: QuestionAttempt | None,
    snovi: dict[str, Material],
    mapa_slik: Path,
) -> dict[str, Any]:
    """Ena postavka rešenega kviza, pripravljena za predlogo.

    Besedilo je **zamrznjeno** iz postavke (`ADR-016` E). Številka je številka
    v kvizu in ne mesto v skupini: po njej se da stran primerjati s telefonom.
    """
    vprasanje = postavka.question
    snov = (
        snovi.get(vprasanje.material_id)
        if vprasanje is not None and vprasanje.material_id is not None
        else None
    )
    return {
        "stevilka": postavka.position,
        "vprasanje": postavka.question_text,
        "odgovor": postavka.answer_text,
        # Snov, ki je v slovarju ni, je dokončno izbrisana — isto kot `NULL`.
        "snov_id": snov.id if snov is not None else None,
        "izvor": (
            _izvor(vprasanje.subject, vprasanje.material_taken_at)
            if vprasanje is not None
            else None
        ),
        "opombe": _opombe_izvora(postavka, snov, mapa_slik) if snov is not None else [],
        # Dve trajanji in ne eno (`ADR-019` D): razmislek pove, kako dolgo je
        # iskala odgovor, ocena pa je mehki signal iz `ADR-014` — „Lahko"
        # dve sekundi po razkritju.
        "razmislek": trajanje(poskus.shown_at, poskus.revealed_at) if poskus else None,
        "cas_ocene": trajanje(poskus.revealed_at, poskus.answered_at) if poskus else None,
    }


def _rezultat(
    kviz: Quiz,
    poskusi: dict[str, QuestionAttempt],
    snovi: dict[str, Material],
    mapa_slik: Path,
) -> list[dict[str, Any]]:
    """Skupine rezultata za predlogo, vsaka z oznako in sklanjanim številom.

    `mesto` (0 do 3, po `OCENE` od najtežje navzdol) da skupini barvo ocene;
    skupina „brez ocene" ga nima. `delez` je širina skupine v pasu
    razporeditve, v odstotkih vseh postavk (V5-R01).
    """
    skupine = _skupine(kviz.postavke, poskusi)
    vseh = sum(len(clani) for _, clani in skupine) or 1
    return [
        {
            "oznaka": OZNAKE_OCEN[ocena] if ocena is not None else BREZ_OCENE,
            "mesto": OCENE.index(ocena) if ocena is not None else None,
            "stevilo": len(clani),
            "delez": round(100 * len(clani) / vseh, 2),
            "stevilo_opis": stevilo_z_besedo(len(clani), VPRASANJA),
            "postavke": [
                _postavka_rezultata(postavka, poskus, snovi, mapa_slik)
                for postavka, poskus in clani
            ],
        }
        for ocena, clani in skupine
    ]


@router.get("/{quiz_id}")
def kviz(
    request: Request,
    quiz_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repozitorij: Annotated[KviziRepository, Depends(daj_repozitorij_kvizov)],
    clani: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
) -> Response:
    """En kviz z vsemi postavkami; rešen kviz kot rezultat (V2-R03).

    Postavka pokaže svoje **zamrznjeno** besedilo in ne besedila vprašanja iz
    baze: prav v tem je pomen `ADR-016` (E). Povezava na izvorno snov je tam,
    kjer snov še obstaja; kadar je bila dokončno izbrisana, ostane vprašanje
    brez `material_id` in kviz to pove namesto da bi ponudil mrtvo povezavo.

    **Rezultat ima samo rešen kviz** (`solved_at`), tudi preklican — preklic
    ima prednost pri stanju, ne pri tem, ali se poskusi pokažejo
    (`docs/plan/V2-R03.md`, odločitev 1). Nerešen kviz se izriše kot pred
    V2-R03 in ne plača nobene poizvedbe več.
    """
    najden = repozitorij.poisci(quiz_id)
    if najden is None:
        return ni_najdeno(predloge, request, "Kviza s tem identifikatorjem ni.")

    # Izbirnika tu ni: kviz ima natanko enega naslovljenca (`ADR-039` F).
    # Ime pa je — povedati mora, čigav rezultat bereš.
    otroci = clani.otroci()
    imena = _imena(otroci)
    ime_otroka = _ime_otroka(otroci, najden.child_id)

    if najden.solved_at is not None:
        return predloge.TemplateResponse(
            request,
            "kviz.html",
            {
                "otrok_ime": ime_otroka,
                "kviz": _pogled_kviza(najden, len(najden.postavke), imena),
                "rezultat": _rezultat(
                    najden,
                    repozitorij.poskusi_kviza(quiz_id),
                    repozitorij.snovi_postavk(najden),
                    mapa_druzine(nastavitve.images_dir, repozitorij.family_id),
                ),
            },
        )

    postavke = [
        {
            "stevilka": postavka.position,
            "vprasanje": postavka.question_text,
            "odgovor": postavka.answer_text,
            "snov_id": (
                postavka.question.material_id if postavka.question is not None else None
            ),
            "izvor": _izvor(postavka.question.subject, postavka.question.material_taken_at)
            if postavka.question is not None
            else None,
        }
        for postavka in najden.postavke
    ]

    return predloge.TemplateResponse(
        request,
        "kviz.html",
        {
            "otrok_ime": ime_otroka,
            "kviz": _pogled_kviza(najden, len(postavke), imena),
            "postavke": postavke,
        },
    )


def _izvor(subject: str | None, taken_at: datetime | None) -> str | None:
    """Iz katere snovi je vprašanje — tudi ko te snovi ni več.

    Bere denormalizirana `questions.subject` in `material_taken_at`, ki ju je
    V1-R07 zapisala prav za ta primer (`ADR-012`).
    """
    if subject is None and taken_at is None:
        return None
    if taken_at is None:
        return subject
    return f"{subject or '?'} — {cas(taken_at)}"


@router.get("/{quiz_id}/print")
def tisk(
    request: Request,
    quiz_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repozitorij: Annotated[KviziRepository, Depends(daj_repozitorij_kvizov)],
    clani_druzine: Annotated[ClaniRepository, Depends(daj_repozitorij_clanov)],
    izbor: str | None = None,
    ocena: Annotated[list[str] | None, Query()] = None,
) -> Response:
    """Stran za tisk: vprašanja brez odgovorov, prelom, ključ (V2-R03).

    Tisk je tudi za **reševanje na papir**, zato del z vprašanji nima ne
    odgovorov ne naslovov skupin po oceni — naslov „Nisem vedela" nad
    vprašanjem bi Maši povedal, kaj je o njem mislila prvič. Vrstni red je vseeno
    od najtežje navzdol, oštevilčenje pa znova od 1; ključ nosi iste številke.

    `GET`, ker nič ne spremeni. Parameter `izbor` loči prvi prihod (velja
    `PRIVZETO_ZA_TISK`) od obrazca, v katerem je vse odkljukano: obrazec brez
    obkljukanega okenca ne pošlje nobene `ocena`, in brez `izbor` bi se tak
    obrazec tiho vrnil v privzetek. Neznane kode se prezrejo.

    Gumba „Natisni" ni: brez JavaScripta ga ni mogoče narediti (`ADR-006`).
    """
    najden = repozitorij.poisci(quiz_id)
    if najden is None:
        return ni_najdeno(predloge, request, "Kviza s tem identifikatorjem ni.")
    if najden.solved_at is None:
        return ni_dovoljeno(
            predloge,
            request,
            "Kviz še ni rešen, zato vprašanj ni mogoče izbrati po oceni. Tisk bo "
            "mogoč, ko otrok na telefonu oceni vsa vprašanja.",
        )

    zahtevane = set(ocena or [])
    izbrane = (
        [koda for koda in OCENE if koda in zahtevane]
        if izbor is not None
        else list(PRIVZETO_ZA_TISK)
    )

    skupine = _skupine(najden.postavke, repozitorij.poskusi_kviza(quiz_id))
    za_tisk = [
        postavka
        for koda, clani in skupine
        if koda in izbrane
        for postavka, _poskus in clani
    ]

    return predloge.TemplateResponse(
        request,
        "kviz-tisk.html",
        {
            # Natisnjen list gre iz zaslona na mizo, zato mora povedati,
            # čigav je — pri dveh otrocih je to edina razlika med listoma.
            "kviz": _pogled_kviza(najden, len(najden.postavke), _imena(clani_druzine.otroci())),
            "ocene": [
                {
                    "koda": koda,
                    "oznaka": OZNAKE_OCEN[koda],
                    "stevilo_opis": stevilo_z_besedo(len(clani), VPRASANJA),
                    "izbrana": koda in izbrane,
                }
                for koda, clani in skupine
                if koda is not None
            ],
            "stevilo_opis": stevilo_z_besedo(len(za_tisk), VPRASANJA),
            "vprasanja": [
                {"stevilka": stevilka, "vprasanje": postavka.question_text,
                 "odgovor": postavka.answer_text}
                for stevilka, postavka in enumerate(za_tisk, start=1)
            ],
        },
    )


@router.post("/{quiz_id}/cancel")
def preklici(
    request: Request,
    quiz_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repozitorij: Annotated[KviziRepository, Depends(daj_repozitorij_kvizov)],
) -> Response:
    """Prekliče kviz. **Ne izbriše ga** (`ADR-016` F).

    Brez vmesne potrditvene strani, po vzorcu gumba „Pošlji v obdelavo":
    dejanje je nepovratno, a ničesar ne uniči — postavke in besedilo ostanejo.
    Vmesni korak ima brisanje, ki podatke res vzame.
    """
    if repozitorij.preklici(quiz_id) is None:
        return ni_najdeno(predloge, request, "Kviza s tem identifikatorjem ni.")

    return RedirectResponse(f"{PREDPONA}/{quote(quiz_id, safe='')}", status_code=303)
