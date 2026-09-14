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

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.besedilo import SNOVI, VPRASANJA, stevilo_z_besedo
from app.casi import cas, cas_ali_prazno, dan_od_do, datum, trajanje
from app.db import KviziRepository, SnovSVprasanji, SnovZaIzbor
from app.dependencies import daj_nastavitve, daj_repozitorij_kvizov
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
from app.strani import daj_predloge, ni_dovoljeno, ni_najdeno
from app.subjects import OZNAKE_OCEN, oznaka_predmeta

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

#: Naslov izbirnika za vsak vstop. Operater mora na strani videti, od kod je
#: prišel — vsi trije vstopi so sicer videti enako.
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


def _vrstica(snov: SnovZaIzbor, obkljukana: bool, mapa_slik: Path) -> dict[str, Any]:
    """Ena vrstica izbirnika, pripravljena za predlogo.

    Predloga ne sklepa in ne oblikuje — dobi gotove vrednosti, tako kot
    `_pogled` na strani predmetov.
    """
    pot = Path(snov.material.image_path)
    ima_sliko = je_znotraj(mapa_slik, pot) and velikost_slike(pot) is not None
    return {
        "id": snov.material.id,
        "koda": snov.material.subject,
        "cas": cas(snov.material.taken_at),
        "vprasanj": stevilo_z_besedo(snov.veljavnih_vprasanj, VPRASANJA),
        "izbirna": snov.izbirna,
        "razlog": _razlog(snov),
        "obkljukana": obkljukana,
        "ima_sliko": ima_sliko,
    }


def _predlagano_ime(subject: str | None, zdaj: datetime) -> str:
    """Samodejno ime kviza, npr. `MAT — 9. 9. 2026`.

    Datum je datum **nastanka kviza** in ne datum snovi: kviz iz zaostanka
    zajame več dni in en sam datum snovi bi bil laž. Koda predmeta in ne
    njegovo dolgo ime, ker je to zapis, ki ga operater bere v seznamu.
    """
    return f"{subject or VSI_PREDMETI} — {datum(zdaj)}"


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
    izbrane: set[str] | None = None,
    sporocilo: str | None = None,
) -> Response:
    """Izriše izbirnik. Ena pot za vse tri vstope in za vrnitev iz predogleda.

    `izbrane` je `None` ob prvem prihodu (obkljuka pravilo vstopa) in množica
    identifikatorjev ob vrnitvi iz predogleda — takrat velja, kar je operater
    izbral, in ne več pravilo. Brez tega bi „Nazaj na izbor" izbor zavrgel,
    kriterij pa zahteva, da je „izbor tak, kot je bil".
    """
    zdaj = datetime.now(UTC)
    predmet, od, do = _obseg(vstop, subject, zdaj)
    snovi = repozitorij.snovi_za_izbor(subject=predmet, od=od, do=do)

    vrstice = [
        _vrstica(
            snov,
            obkljukana=(
                _je_obkljukana(vstop, snov)
                if izbrane is None
                else snov.material.id in izbrane
            ),
            mapa_slik=mapa_slik,
        )
        for snov in snovi
    ]

    return predloge.TemplateResponse(
        request,
        "kvizi-izbirnik.html",
        {
            "vstop": vstop,
            "naslov": NASLOVI[vstop],
            "subject": subject,
            "oznaka": oznaka_predmeta(subject) if subject else VSI_PREDMETI,
            "cez_vse_predmete": vstop == VSTOP_DANES,
            "stevilo": stevilo,
            "najmanj": NAJMANJ_VPRASANJ,
            "najvec": NAJVEC_VPRASANJ,
            "snovi": vrstice,
            "izbirnih": sum(1 for vrstica in vrstice if vrstica["izbirna"]),
            "sporocilo": sporocilo,
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
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    vstop: str = VSTOP_NOVA,
    subject: str | None = None,
    stevilo: str = str(PRIVZETO_STEVILO),
) -> Response:
    """Izbirnik slik ob prihodu z enega od treh vstopov.

    Registriran je **pred** `/{quiz_id}`: FastAPI ujema po vrstnem redu in
    obratni vrstni red bi „new" prebral kot identifikator kviza.
    """
    napaka = _preveri_vstop(predloge, request, vstop, subject)
    if napaka is not None:
        return napaka

    return _izrisi_izbirnik(
        request,
        predloge,
        repozitorij,
        mapa_druzine(nastavitve.images_dir, repozitorij.family_id),
        vstop=vstop,
        subject=subject,
        stevilo=_prebrano_stevilo(stevilo),
    )


@router.post("/new")
def izbirnik_z_izborom(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repozitorij: Annotated[KviziRepository, Depends(daj_repozitorij_kvizov)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    vstop: Annotated[str, Form()] = VSTOP_NOVA,
    subject: Annotated[str | None, Form()] = None,
    stevilo: Annotated[str, Form()] = str(PRIVZETO_STEVILO),
    snov: Annotated[list[str] | None, Form()] = None,
) -> Response:
    """Izbirnik ob vrnitvi iz predogleda („Nazaj na izbor").

    Ista stran kot `GET /new`, le da obkljuka to, kar je operater izbral.
    `POST` zato, ker izbor potuje kot seznam identifikatorjev in ne kot naslov.
    """
    napaka = _preveri_vstop(predloge, request, vstop, subject)
    if napaka is not None:
        return napaka

    return _izrisi_izbirnik(
        request,
        predloge,
        repozitorij,
        mapa_druzine(nastavitve.images_dir, repozitorij.family_id),
        vstop=vstop,
        subject=subject,
        stevilo=_prebrano_stevilo(stevilo),
        izbrane=set(snov or []),
    )


@router.post("/preview")
def predogled(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repozitorij: Annotated[KviziRepository, Depends(daj_repozitorij_kvizov)],
    nastavitve: Annotated[Settings, Depends(daj_nastavitve)],
    vstop: Annotated[str, Form()] = VSTOP_NOVA,
    subject: Annotated[str | None, Form()] = None,
    stevilo: Annotated[str, Form()] = str(PRIVZETO_STEVILO),
    snov: Annotated[list[str] | None, Form()] = None,
) -> Response:
    """Predogled izbranih vprašanj. **Ničesar ne shrani** (`ADR-016` C).

    `POST` in ne `GET`: izbor je lahko sto identifikatorjev in v naslovu bi bil
    predolg. Osvežitev strani dejanje ponovi in prav nič ne naredi — prav zato,
    ker se nič ne shrani.
    """
    napaka = _preveri_vstop(predloge, request, vstop, subject)
    if napaka is not None:
        return napaka

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
        1 for vrstica in repozitorij.snovi_za_izbor(predmet, od, do) if not vrstica.izbirna
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
            "skupine": [_skupina_pogled(skupina) for skupina in skupine],
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


def _skupina_pogled(skupina: SnovSVprasanji) -> dict[str, Any]:
    """Ena snov s svojimi vprašanji, pripravljena za predogled."""
    return {
        "id": skupina.material.id,
        "koda": skupina.material.subject,
        "cas": cas(skupina.material.taken_at),
        "vprasanja": [
            {"vprasanje": vprasanje.question, "odgovor": vprasanje.answer}
            for vprasanje in skupina.vprasanja
        ],
    }


@router.post("")
def objavi(
    request: Request,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repozitorij: Annotated[KviziRepository, Depends(daj_repozitorij_kvizov)],
    ime: Annotated[str, Form()] = "",
    vstop: Annotated[str, Form()] = VSTOP_NOVA,
    subject: Annotated[str | None, Form()] = None,
    vprasanje: Annotated[list[str] | None, Form()] = None,
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
    )

    # 303 iz istega razloga kot pri brisanju in ponovni obdelavi: osvežitev
    # strani ne sme dejanja ponoviti — tu bi to pomenilo drugi enak kviz.
    return RedirectResponse(f"{PREDPONA}/{quote(kviz.id, safe='')}", status_code=303)


def _pogled_kviza(kviz: Quiz, postavk: int) -> dict[str, Any]:
    """Kviz brez postavk — za seznam na `/admin`."""
    return {
        "id": kviz.id,
        "ime": kviz.name,
        "koda": kviz.subject or VSI_PREDMETI,
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


def seznam_kvizov(repozitorij: KviziRepository) -> list[dict[str, Any]]:
    """Kvizi za razdelek na `/admin`, najnovejši prvi.

    Živi tu in ne v `admin.py`, ker je oblika kviza stvar tega modula; `admin`
    jo samo pokliče in preda predlogi.
    """
    return [_pogled_kviza(kviz, postavk) for kviz, postavk in repozitorij.seznam()]


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
    """Skupine rezultata za predlogo, vsaka z oznako in sklanjanim številom."""
    return [
        {
            "oznaka": OZNAKE_OCEN[ocena] if ocena is not None else BREZ_OCENE,
            "stevilo_opis": stevilo_z_besedo(len(clani), VPRASANJA),
            "postavke": [
                _postavka_rezultata(postavka, poskus, snovi, mapa_slik)
                for postavka, poskus in clani
            ],
        }
        for ocena, clani in _skupine(kviz.postavke, poskusi)
    ]


@router.get("/{quiz_id}")
def kviz(
    request: Request,
    quiz_id: str,
    predloge: Annotated[Jinja2Templates, Depends(daj_predloge)],
    repozitorij: Annotated[KviziRepository, Depends(daj_repozitorij_kvizov)],
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

    if najden.solved_at is not None:
        return predloge.TemplateResponse(
            request,
            "kviz.html",
            {
                "kviz": _pogled_kviza(najden, len(najden.postavke)),
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
            "kviz": _pogled_kviza(najden, len(postavke)),
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
            "mogoč, ko Maša na telefonu oceni vsa vprašanja.",
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
            "kviz": _pogled_kviza(najden, len(najden.postavke)),
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
