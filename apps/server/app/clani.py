"""Pravila o članih družine: kaj je veljaven vnos in kdo sme koga.

Modul ne ve za FastAPI in ne za bazo — dobi vrednosti, vrne razlog ali `None`.
Isti razlog kot pri `app/prijava.py` in `app/statistika.py`: pravila se dajo
preizkusiti brez zaganjanja strežnika, usmerjevalnik pa ostane prenos.

Odločitve so v `docs/odlocitve/ADR-038` (izvedba `V3-R06`), `ADR-025` (družina
je meja) in `ADR-027` (poverilnica ni uporabnik).

Dve vrsti zavrnitve, ki ju ta modul namenoma **ne** meša:

- **Vnos ni veljaven** (`preveri_*`) — uporabnica ga lahko popravi in poskusi
  znova; usmerjevalnik odgovori s `400` in isto stranjo.
- **Dejanja ne sme opraviti** (`zakaj_ne_sme_*`) — popravek vnosa ne pomaga;
  usmerjevalnik odgovori s `403`.

Stanje („ta račun je že deaktiviran") ni ne eno ne drugo in ostane v
usmerjevalniku kot `409`, po vzoru `strani.ni_dovoljeno`.
"""

from app.models import VLOGA_OTROK, VLOGA_STARS
from app.prijava import NAJKRAJSE_GESLO, geslo_je_dovolj_dolgo

#: Najdaljše prikazno ime — natanko širina stolpca `users.display_name`.
#:
#: Meja je v kodi in ne prepuščena bazi, iz istega razloga kot pri objavi kviza
#: (V2-R01): testi tečejo nad SQLite, ki dolžine `VARCHAR` ne uveljavlja, na
#: Postgresu pa bi predolg vnos postal `DataError` in angleški „Internal
#: Server Error" sredi slovenske strani.
NAJDALJSE_IME = 200

#: Najdaljši identifikator — natanko širina stolpca `credentials.identifier`.
NAJDALJSI_IDENTIFIKATOR = 320

SPOROCILO_PRAZNO_IME = "Prikazno ime manjka. Vpiši ime, kot naj se kaže na strani."
SPOROCILO_PREDOLGO_IME = f"Prikazno ime je predolgo; največ {NAJDALJSE_IME} znakov."

SPOROCILO_PRAZEN_ENASLOV = "E-naslov manjka. S tem e-naslovom se bo starš prijavil na tej strani."
SPOROCILO_NI_ENASLOV = "E-naslov ni videti kot e-naslov — manjka mu @ ali kaj ob njem."
SPOROCILO_PREDOLG_ENASLOV = f"E-naslov je predolg; največ {NAJDALJSI_IDENTIFIKATOR} znakov."

#: Besedilo za zaseden e-naslov.
#:
#: Enoličnost je čez **celo namestitev** (`credentials.identifier UNIQUE`), zato
#: je nekaj informacije neizogibno. Besedilo ne pove, pri kom je ime zasedeno
#: — to je najmanjši možen izid ob kriteriju, ki hkrati zahteva jasno sporočilo
#: in prepoveduje izdajanje tujih računov (`ADR-038` E).
SPOROCILO_IDENTIFIKATOR_ZASEDEN = "To ime je že zasedeno. Izberi drugo."

#: Velja samo takrat, kadar v družini **je** drug aktiven starš — pravilo o
#: zadnjem staršu ugrizne prej. Nasvet je zato vedno izvedljiv.
SPOROCILO_NE_SEBE = (
    "Sebe ne moreš deaktivirati. Naj to naredi drugi starš v družini, "
    "sicer bi družina ostala brez nekoga, ki jo ureja."
)
SPOROCILO_LASTNIK_SISTEMA = (
    "Lastnika sistema ni mogoče deaktivirati. Ta račun vzdržuje strežnik za vse družine."
)
SPOROCILO_ZADNJI_STARS = (
    "V družini mora ostati vsaj en aktiven starš. Najprej dodaj drugega starša, potem tega."
)
SPOROCILO_TUJE_GESLO_LASTNIKA = "Geslo lastnika sistema lahko ponastavi samo on sam."

SPOROCILO_GESLI_SE_NE_UJEMATA = "Gesli se ne ujemata. Vpiši dvakrat isto."

SPOROCILO_ZE_DEAKTIVIRAN = "Ta račun je že deaktiviran."
SPOROCILO_ZE_AKTIVEN = "Ta račun je že aktiven."

#: Račun smo našli, stavek pa ni spremenil ničesar. V praksi pomeni, da
#: oseba nima poverilnice za geslo (`ClanDruzine.identifier` je `None`) —
#: shema to dopušča, poti `V3-R06` pa takega računa ne ustvarijo. Tiha
#: preusmeritev bi tu pomenila, da stran pove „opravljeno" za nič.
SPOROCILO_NI_SPREMENJENO = (
    "Dejanja nisem izvedel — ta račun se je medtem spremenil ali nima gesla, "
    "ki bi ga bilo mogoče ponastaviti. Osveži stran in poglej, v kakšnem stanju je."
)


#: Otrok gesla nima (`V6-R01`, `docs/odlocitve/ADR-058` E). Sporočilo pove,
#: kaj je namesto ponastavitve.
SPOROCILO_OTROK_NIMA_GESLA = (
    "Otrok gesla nima, zato ga ni mogoče ponastaviti. Na seznamu družine mu "
    "poveži telefon s QR kodo ali prekliči prijave."
)

SPOROCILO_TELEFON_SAMO_OTROKU = (
    "Telefon se poveže samo otroku. Starš se prijavi na tej spletni strani."
)
SPOROCILO_POVEZAVA_DEAKTIVIRANEMU = (
    "Ta račun je deaktiviran, zato telefona ni mogoče povezati. Najprej ga "
    "aktiviraj na seznamu družine."
)
SPOROCILO_PREKLIC_SAMO_OTROKU = (
    "Prijave je mogoče preklicati samo otroku. Staršu ponastavi geslo — tudi to "
    "ga odjavi z vseh naprav."
)


def _sporocilo_prekratko_geslo(vloga: str) -> str:
    najmanj = NAJKRAJSE_GESLO.get(vloga, NAJKRAJSE_GESLO[VLOGA_STARS])
    return f"Geslo za starša je prekratko; imeti mora vsaj {najmanj} znakov."


# --- Veljaven vnos ---------------------------------------------------------


def preveri_prikazno_ime(ime: str) -> str | None:
    """Razlog, zakaj prikazno ime ni veljavno, ali `None`."""
    if not ime.strip():
        return SPOROCILO_PRAZNO_IME
    if len(ime.strip()) > NAJDALJSE_IME:
        return SPOROCILO_PREDOLGO_IME
    return None


def preveri_enaslov(naslov: str) -> str | None:
    """Razlog, zakaj e-naslov starša ni veljaven, ali `None`.

    Preverba je namenoma **groba**: en znak `@` in nekaj na obeh straneh, brez
    presledkov. Popolnega vzorca za e-naslov ni, edini pravi preizkus je
    poslano sporočilo — in SMTP-ja ta verzija nima (`ADR-027`). Vse, kar mora
    ta preverba ujeti, je zatipkana vrstica, ki e-naslov sploh ni.
    """
    if not naslov:
        return SPOROCILO_PRAZEN_ENASLOV
    if any(znak.isspace() for znak in naslov):
        return SPOROCILO_NI_ENASLOV
    pred, znak, za = naslov.partition("@")
    if not znak or not pred or not za or "@" in za:
        return SPOROCILO_NI_ENASLOV
    if len(naslov) > NAJDALJSI_IDENTIFIKATOR:
        return SPOROCILO_PREDOLG_ENASLOV
    return None


def preveri_novo_geslo(vloga: str, geslo: str, ponovitev: str) -> str | None:
    """Razlog, zakaj novo geslo ni veljavno, ali `None`.

    Meja je ista in na istem mestu kot pri ukazu `nastavi-geslo`
    (`prijava.NAJKRAJSE_GESLO`): 12 znakov. Dve meji na dveh mestih bi se
    razšli. Geslo ima samo starš; otrok ga od `V6-R01` nima.

    Geslo se vpiše **dvakrat**, tako kot pri ukazu `nastavi-geslo`: zatipkano
    geslo se nikjer ne pokaže, posledica pa je račun, v katerega se ne da
    prijaviti.
    """
    if not geslo_je_dovolj_dolgo(vloga, geslo):
        return _sporocilo_prekratko_geslo(vloga)
    if geslo != ponovitev:
        return SPOROCILO_GESLI_SE_NE_UJEMATA
    return None


# --- Kdo sme koga ----------------------------------------------------------


def zakaj_ne_sme_deaktivirati(
    *,
    izvajalec_id: str,
    clan_id: str,
    clan_vloga: str,
    clan_je_lastnik_sistema: bool,
    aktivnih_starsev: int,
) -> str | None:
    """Razlog, zakaj ta starš tega člana ne sme deaktivirati, ali `None`.

    Pravila so tri in vsako ima svojo posledico, če ga ni:

    - **lastnika sistema ne** (`ADR-038` G) — sicer drugi starš v isti družini
      izklopi račun, na katerem stoji `V3-R05`;
    - **zadnjega aktivnega starša ne** (kriterij `V3-R06`) — sicer družina
      ostane brez nekoga, ki jo ureja, in otrok brez nekoga, ki mu ponastavi
      geslo;
    - **sebe ne** (kriterij `V3-R06`) — sicer se starš izklopi iz lastnega
      admina z enim klikom.

    `aktivnih_starsev` je število aktivnih staršev družine **vključno s
    članom**, ki ga deaktiviramo; prav zato je meja `<= 1` in ne `< 1`.

    **Vrstni red ni okras, ampak izbira sporočila.** Vsa tri pravila vodijo v
    isti `403`; razlikujejo se po tem, kaj povedo, naj uporabnica naredi
    (`CLAUDE.md` §1b). Dokler je bilo „sebe ne" prvo, je starš, ki je v
    družini sam, dobil nasvet „naj to naredi drugi starš v družini" — nasvet,
    ki mu v enostarševski družini ni mogel slediti, in enostarševska družina
    je privzeto stanje vsake nove družine (migracija `0008`, pozneje `V3-R05`).
    Odkar je pravilo o zadnjem staršu pred njim, tak starš dobi „najprej dodaj
    drugega starša, potem tega", kar je izvedljiv naslednji korak. Najdeno v
    drugem pregledu `V3-R06`.

    Stranski izid iste zamenjave: pravilo o zadnjem staršu je odslej dosegljivo
    čez HTTP. Prej ni bilo — klicatelj je vedno aktiven starš te družine
    (`prijava.seja_za_zeton` neaktivnemu sejo izbriše, `vloga_sodi` otroka ne
    spusti), zato tuj **aktiven** starš pomeni, da sta aktivna vsaj dva, ob
    cilju „jaz" pa je prej ugriznilo „sebe ne". Priklop na pravo število je
    zato zdaj pribit z navadnim testom čez pot, ne z uvozom privatnega imena.
    """
    if clan_je_lastnik_sistema:
        return SPOROCILO_LASTNIK_SISTEMA
    if clan_vloga == VLOGA_STARS and aktivnih_starsev <= 1:
        return SPOROCILO_ZADNJI_STARS
    if clan_id == izvajalec_id:
        return SPOROCILO_NE_SEBE
    return None


def zakaj_ne_sme_ponastaviti_gesla(
    *, izvajalec_id: str, clan_id: str, clan_vloga: str, clan_je_lastnik_sistema: bool
) -> str | None:
    """Razlog, zakaj ta starš temu članu ne sme ponastaviti gesla, ali `None`.

    Omejitvi sta dve:

    - **otrok gesla nima** (`V6-R01`, `ADR-058` E) — namesto ponastavitve sta
      „Poveži telefon" in „Prekliči prijave";
    - **lastnik sistema** (`ADR-038` G): geslo mu sme ponastaviti samo on sam.

    Sebi ga sme ponastaviti vsak starš — in takrat mu pade tudi seja, v kateri
    ravno kliče (`ADR-038` D).
    """
    if clan_vloga == VLOGA_OTROK:
        return SPOROCILO_OTROK_NIMA_GESLA
    if clan_je_lastnik_sistema and clan_id != izvajalec_id:
        return SPOROCILO_TUJE_GESLO_LASTNIKA
    return None


def zakaj_ne_sme_povezati_telefona(*, clan_vloga: str, clan_aktiven: bool) -> str | None:
    """Razlog, zakaj temu članu telefona ni mogoče povezati, ali `None` (V6-R01).

    Poveže se samo **aktiven otrok**: starš se na telefon ne prijavi
    (`ADR-036` D), deaktiviran račun pa se ne more prijaviti nikjer
    (`ADR-038` A). Isto pravilo odloči, ali kartica dejanje sploh ponudi.
    """
    if clan_vloga != VLOGA_OTROK:
        return SPOROCILO_TELEFON_SAMO_OTROKU
    if not clan_aktiven:
        return SPOROCILO_POVEZAVA_DEAKTIVIRANEMU
    return None


def zakaj_ne_sme_preklicati_prijav(*, clan_vloga: str) -> str | None:
    """Razlog, zakaj temu članu prijav ni mogoče preklicati, ali `None` (V6-R01).

    Dejanje je otrokov nadomestek za ponastavitev gesla (`ADR-058` E). Starš
    ga nima: njegova pot do istega izida je ponastavitev gesla, in dve poti z
    različnimi pravili (sebe, lastnik sistema) bi se razšli.
    """
    if clan_vloga != VLOGA_OTROK:
        return SPOROCILO_PREKLIC_SAMO_OTROKU
    return None
