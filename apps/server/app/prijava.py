"""Gesla, žetoni sej, CSRF in omejevanje ugibanja.

Modul ne ve za FastAPI in ne za HTTP: dobi repozitorij in čas, vrne izid. Isti
razlog kot pri `app/obdelava.py` in `app/statistika.py` — pravila se dajo
preizkusiti brez zaganjanja strežnika, in kar strežnik doda, je samo prenos
(piškotek ali glava).

Odločitve so v `docs/odlocitve/ADR-027` (model identitete) in `ADR-035`
(izvedba). Trije poudarki, ki se iz kode ne vidijo sami:

- **Geslo je argon2id, žeton seje pa SHA-256.** To ni nedoslednost: geslo je
  kratko in ugibljivo, zato mora biti zgoščevanje počasno; žeton je 256
  naključnih bitov, kjer počasnost ne kupi ničesar, plača pa se ob vsaki
  zahtevi.
- **Neznan identifikator stane enako kot znan.** Brez lažne preverbe bi
  odzivni čas povedal, kateri e-naslov v sistemu obstaja.
- **Omejevanje upočasni, ne zaklene.** Zaklep bi pomenil, da lahko kdorkoli z
  znanim e-naslovom starša tega izklopi iz njegovega strežnika (`ADR-034` A).
"""

import hashlib
import secrets
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.db import PoverilnicaZaPrijavo, PrijavaRepository, SejaUporabnika
from app.models import VLOGA_OTROK, VLOGA_STARS

#: Poti prijave in odjave v brskalniku. Pod `/admin` sta zato, ker sta del
#: operaterske strani in ker njuna izvzetja iz `SejaMiddleware` ni treba
#: iskati drugje kot pri ostalih poteh te strani.
POT_PRIJAVE = "/admin/login"
POT_ODJAVE = "/admin/logout"

#: Poti prijave in odjave telefona (V3-R04). **Zunaj `/admin`**: tam govori
#: brskalnik s piškotkom in CSRF žetonom, tu pa telefon z JSON in glavo
#: `Authorization: Bearer` (`docs/odlocitve/ADR-036` G).
POT_PRIJAVE_TELEFONA = "/auth/login"
POT_ODJAVE_TELEFONA = "/auth/logout"

#: Shema, v kateri telefon pošlje žeton.
SHEMA_ZETONA = "bearer"

#: Ime piškotka s sejo.
PISKOTEK_SEJE = "seja"

#: Ime piškotka z CSRF žetonom prijavnega obrazca. Prijava seje še nima, zato
#: se žeton oddá dvakrat: v piškotku in v skritem polju (`ADR-035` D).
PISKOTEK_CSRF_PRIJAVE = "csrf_prijava"

#: Ime skritega polja s CSRF žetonom v vseh obrazcih pod `/admin`.
POLJE_CSRF = "csrf"

#: Kako dolgo velja seja od zadnje uporabe. Rok je drseči.
TRAJANJE_SEJE = timedelta(days=30)

#: Najmanjši razmik med dvema osvežitvama `last_used_at`. Brez tega bi bila
#: vsaka zahteva `UPDATE`.
RAZMIK_OSVEZITVE = timedelta(hours=1)

#: Koliko neuspelih poskusov na isti identifikator je še brez posledic.
PRAG_POSKUSOV = 5

#: V kako dolgem oknu se poskusi štejejo.
OKNO_POSKUSOV = timedelta(minutes=15)

#: Koliko časa čaka poskus, ko je prag presežen. Upočasnitev, ne zaklep.
ZAMIK_SEKUND = 2.0

#: Kako dolgo se neuspeli poskusi sploh hranijo. Starejši gredo ob prijavi ven.
HRAMBA_POSKUSOV = timedelta(days=30)

#: Najkrajše geslo po vlogi. Ključ je `str` in ne `Vloga`: vloga pride iz baze
#: kot navaden niz in vrednost, ki je v tabeli ne bi smelo biti, mora pasti na
#: privzetek za starša (strožjega), ne na `KeyError`.
#:
#: Otrokovih 8 in ne 4: `ADR-035` G je kratko geslo dovolil z utemeljitvijo,
#: da otrokov račun služi mobilni prijavi in do `/admin` ne pride — mobilne
#: prijave takrat ni bilo. Z `V3-R04` nastane in je dosegljiva z javnega
#: interneta, `ADR-035` E pa priznava, da upočasnitev ne velja za napadalca z
#: vzporednimi povezavami (`docs/odlocitve/ADR-036` E).
NAJKRAJSE_GESLO: dict[str, int] = {VLOGA_STARS: 12, VLOGA_OTROK: 8}

#: Eno samo sporočilo za vse neuspehe, ki bi sicer izdali, ali račun obstaja.
SPOROCILO_NEUSPELA_PRIJAVA = (
    "E-naslov ali geslo ni pravo. Poskusi znova; po več zaporednih poskusih bo prijava počasnejša."
)

#: Izjema od enotnega sporočila (`ADR-035` F): Maša mora razumeti, zakaj ne gre.
SPOROCILO_OTROK = "Ta račun je otrokov in se prijavi v mobilni aplikaciji, ne na tej strani."

#: Zrcalna izjema na telefonu (`ADR-036` D). Cena je ista in se prizna enako:
#: sporočilo izda vlogo računa, čigar geslo tisti, ki ga vidi, že pozna.
SPOROCILO_STARS = "Ta račun je starševski in se prijavi na spletni strani, ne v aplikaciji."

_ZGOSCEVALNIK = PasswordHasher()

#: Zgostitev, ob katero se preveri geslo za neobstoječ račun.
#:
#: Izračuna se ob uvozu in ne zapiše kot konstanta v kodi: ročno prepisana
#: zgostitev se lahko razide s parametri `PasswordHasher` — in preverba proti
#: zgostitvi z drugačnimi parametri traja drugače dolgo, kar je natanko tisto,
#: kar naj lažna preverba skrije. Gesla, ki ga zgostitev nosi, ne pozna nihče.
_LAZNA_ZGOSTITEV_GESLA = _ZGOSCEVALNIK.hash(secrets.token_urlsafe(32))


class Vrata(Enum):
    """Kje se kdo prijavlja.

    Vsaka vloga ima svoja vrata (`docs/00-namen.md`): starš dela izključno v
    spletnem adminu, otrok izključno v mobilni aplikaciji. Pravilo je **eno**
    in ne dve zrcalni veji — `ADR-035` F ga je zapisal za admin, `ADR-036` D
    za telefon, in odkar obstajata oboja vrata, je ena tabela cenejša od dveh
    posebnih primerov, ki se lahko razideta.
    """

    ADMIN = "admin"
    TELEFON = "telefon"


#: Katera vloga sodi na katera vrata, in kaj dobi tista, ki pride na napačna.
_VLOGA_ZA_VRATA: dict[Vrata, str] = {
    Vrata.ADMIN: VLOGA_STARS,
    Vrata.TELEFON: VLOGA_OTROK,
}

_SPOROCILO_NAPACNA_VRATA: dict[Vrata, str] = {
    Vrata.ADMIN: SPOROCILO_OTROK,
    Vrata.TELEFON: SPOROCILO_STARS,
}


def vloga_sodi(vloga: str, vrata: Vrata) -> bool:
    """Ali ta vloga sme skozi ta vrata.

    Preverja se ob **prijavi in ob vsaki uporabi seje**, ne samo ob prijavi.
    Razlog je nastal prav z `V3-R04`: do takrat otrokove seje ni bilo mogoče
    ustvariti (admin ga je zavrnil), zato je preverba ob prijavi zadoščala.
    Odkar telefon seje ustvarja, je žeton otroka resničen niz — in isti niz,
    prilepljen v piškotek `seja`, bi brez te preverbe odprl celoten `/admin`.
    Žeton je en pojem z dvema prenosnikoma (`ADR-027`); vrata pa dvoje.
    """
    return vloga == _VLOGA_ZA_VRATA[vrata]


class Izid(Enum):
    """Kaj se je zgodilo ob poskusu prijave."""

    USPEH = "uspeh"
    ZAVRNJENO = "zavrnjeno"
    #: Poverilnica je prava, a vloga na ta vrata ne sodi. Do V3-R04 se je ta
    #: izid imenoval `OTROK` in je obstajal samo za admin stran.
    NAPACNA_VRATA = "napacna-vrata"


@dataclass(frozen=True)
class IzidPrijave:
    """Izid z vsem, kar klicatelj potrebuje za odgovor."""

    izid: Izid
    sporocilo: str | None = None
    poverilnica: PoverilnicaZaPrijavo | None = None


# --- Identifikator ---------------------------------------------------------


def normaliziraj_identifikator(identifikator: str) -> str:
    """Identifikator v obliki, v kakršni stoji v bazi: brez robov, male črke.

    Normalizira se **ob nastanku računa in ob vsaki prijavi**, na obeh vratih
    (`docs/odlocitve/ADR-038` E). Brez tega enoličnost stolpca
    `credentials.identifier` ne pomeni tega, kar zahteva `V3-R06`:
    `Ana@primer.si` in `ana@primer.si` bi bila dva računa, torej natanko
    dvoumnost, ki naj bi jo enoličnost preprečila.

    Stranski učinek je dobrodošel: omejevanje ugibanja (`ADR-035` E) šteje po
    normaliziranem identifikatorju, zato se mu z menjavo velikih črk ni mogoče
    izogniti.

    `lower` in ne `casefold`: ta bi `ß` preslikal v `ss` in s tem dva različna
    zapisa zlil v enega — pri identifikatorju, ki je ime računa, je to več, kot
    je bilo mišljeno.
    """
    return identifikator.strip().lower()


# --- Gesla -----------------------------------------------------------------


def zgosti_geslo(geslo: str) -> str:
    """Zgostitev gesla (argon2id, privzeti parametri paketa)."""
    return _ZGOSCEVALNIK.hash(geslo)


def geslo_se_ujema(zgostitev: str | None, geslo: str) -> bool:
    """Ali se geslo ujema z zgostitvijo.

    `zgostitev is None` pomeni „geslo ni nastavljeno" (`ADR-035` G). Tudi
    takrat se preverba **izvede** — proti lažni zgostitvi — da račun brez gesla
    ni prepoznaven po hitrejšem odgovoru.
    """
    if zgostitev is None:
        _preveri_lazno(geslo)
        return False
    try:
        return _ZGOSCEVALNIK.verify(zgostitev, geslo)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _preveri_lazno(geslo: str) -> None:
    """Porabi toliko časa kot prava preverba. Izid se zavrže."""
    with suppress(VerifyMismatchError, VerificationError, InvalidHashError):
        _ZGOSCEVALNIK.verify(_LAZNA_ZGOSTITEV_GESLA, geslo)


def geslo_je_dovolj_dolgo(vloga: str, geslo: str) -> bool:
    """Ali geslo ustreza najmanjši dolžini za to vlogo."""
    return len(geslo) >= NAJKRAJSE_GESLO.get(vloga, NAJKRAJSE_GESLO[VLOGA_STARS])


# --- Žetoni ----------------------------------------------------------------


def nov_zeton() -> str:
    """Neprozoren naključni žeton (`ADR-027` B2)."""
    return secrets.token_urlsafe(32)


def zgostitev_zetona(zeton: str) -> str:
    """SHA-256 žetona, šestnajstiško. V bazi je samo to, nikoli žeton sam."""
    return hashlib.sha256(zeton.encode("utf-8")).hexdigest()


def zetona_se_ujemata(prvi: str | None, drugi: str | None) -> bool:
    """Primerja žetona v konstantnem času; manjkajoč žeton ne velja nikoli.

    **Primerjata se bajta, ne niza**, in to ni podrobnost (popravljeno v
    `V3-R08`, drugi pregled). `secrets.compare_digest` nad `str` zahteva čiste
    ASCII znake in ob vsakem drugem vrže `TypeError`. Vsaj en vhod vsakega
    klicatelja pride od zunaj — CSRF žeton iz obrazca, piškotek `csrf_prijava`
    (Starlette glavo `Cookie` dekodira v latin-1) —, zato je bila taka izjema
    **500 z golim angleškim besedilom** na štirih poteh naenkrat:
    `POST /admin/login`, `POST /auth/google/login`, vsak `POST` pod `/admin`
    prek `SejaMiddleware` in nalaganje slike urnika.

    Z `encode` je vsak vhod veljaven bajtni niz, zato je neujemanje
    neujemanje in ne izjema. Pogodba se s tem **ne spremeni**: žeton z
    ne-ASCII znakom ni bil veljaven nikoli, le namesto `403` je dal `500`.

    Velja za vsako primerjavo skrivnosti, ki pride iz zahteve
    (`docs/02-izkusnje.md`).
    """
    if not prvi or not drugi:
        return False
    return secrets.compare_digest(prvi.encode("utf-8"), drugi.encode("utf-8"))


# --- Omejevanje ugibanja ---------------------------------------------------


def zamik_pred_preverbo(neuspelih: int) -> float:
    """Koliko sekund čaka poskus, preden se geslo sploh preveri."""
    return ZAMIK_SEKUND if neuspelih >= PRAG_POSKUSOV else 0.0


def koliko_cakati(repo: PrijavaRepository, identifikator: str, ko: datetime) -> float:
    """Zamik za ta identifikator ob času `ko`.

    Identifikator se normalizira tudi tu in ne samo ob preverbi: števec bi
    sicer za `Masa` in `masa` tekel ločeno in ugibanje bi se mu izognilo z
    menjavo velikih črk (`docs/odlocitve/ADR-038` E).
    """
    neuspelih = repo.neuspelih_poskusov(
        normaliziraj_identifikator(identifikator), ko - OKNO_POSKUSOV
    )
    return zamik_pred_preverbo(neuspelih)


# --- Prijava ---------------------------------------------------------------


def preveri_prijavo(
    repo: PrijavaRepository,
    identifikator: str,
    geslo: str,
    *,
    vrata: Vrata,
    ip: str | None,
    ko: datetime,
) -> IzidPrijave:
    """Preveri poverilnico in zabeleži neuspeh.

    Seje **ne** ustvari — to je ločen korak (`ustvari_sejo`), da je vidno, kje
    seja nastane. Neuspeh zapiše v `login_attempts`, uspeh števce tega
    identifikatorja pobriše.

    **Čiščenje teče ob vsakem poskusu, ne samo ob uspešnem** (`ADR-035` C).
    Sicer bi v natanko tistem stanju, ki ga pusti migracija — račun brez
    gesla, torej brez uspešne prijave — tabela poskusov rasla brez meje.

    `vrata` povedo, od kod prijava prihaja. Vloga, ki tja ne sodi, dobi
    `NAPACNA_VRATA` z razlago namesto enotnega sporočila — glej `Vrata`.

    **Identifikator se normalizira tu in ne v usmerjevalniku** (`ADR-038` E):
    pravilo mora veljati za obe vrati in za vsak zapis v `login_attempts`, in
    pravilo, ki bi ga moral vsak klicatelj ponoviti, je pravilo, ki ga bo kdo
    kdaj pozabil.

    **Ugasnjena družina je isto kot ugasnjen račun** (`V3-R05`, `ADR-044` A):
    ista zavrnitev, isto besedilo, isti zapis v `login_attempts`. Stoji v
    istem pogoju kot `is_active` in ne v svojem, ker bi ločen `if` z lastnim
    sporočilom povedal, da družina obstaja in je ugasnjena — in to je podatek
    o tuji družini.
    """
    identifikator = normaliziraj_identifikator(identifikator)

    repo.pocisti_stare_poskuse(ko - HRAMBA_POSKUSOV)
    repo.pocisti_potekle_seje(ko)

    poverilnica = repo.poverilnica(identifikator)

    if poverilnica is None:
        _preveri_lazno(geslo)
        repo.zabelezi_neuspeh(identifikator, ip, ko)
        return IzidPrijave(Izid.ZAVRNJENO, SPOROCILO_NEUSPELA_PRIJAVA)

    if (
        not geslo_se_ujema(poverilnica.secret_hash, geslo)
        or not poverilnica.is_active
        or not poverilnica.family_is_active
    ):
        repo.zabelezi_neuspeh(identifikator, ip, ko)
        return IzidPrijave(Izid.ZAVRNJENO, SPOROCILO_NEUSPELA_PRIJAVA)

    if not vloga_sodi(poverilnica.role, vrata):
        # Geslo je pravo, zato to ni neuspel poskus in se ne šteje.
        return IzidPrijave(Izid.NAPACNA_VRATA, _SPOROCILO_NAPACNA_VRATA[vrata])

    repo.pozabi_poskuse(identifikator)
    return IzidPrijave(Izid.USPEH, poverilnica=poverilnica)


def ustvari_sejo(
    repo: PrijavaRepository,
    poverilnica: PoverilnicaZaPrijavo,
    *,
    ko: datetime,
    oznaka_naprave: str | None,
) -> str:
    """Ustvari sejo in vrne žeton, ki gre v piškotek. V bazi ostane zgostitev."""
    zeton = nov_zeton()
    repo.ustvari_sejo(
        user_id=poverilnica.user_id,
        token_hash=zgostitev_zetona(zeton),
        csrf_token=nov_zeton(),
        ko=ko,
        potece=ko + TRAJANJE_SEJE,
        device_label=oznaka_naprave,
    )
    return zeton


def seja_za_zeton(
    repo: PrijavaRepository, zeton: str | None, ko: datetime
) -> SejaUporabnika | None:
    """Seja za žeton iz piškotka, ali `None`.

    Potekla seja se tu **izbriše** — vrstica, ki je nihče ne pobriše, bi v bazi
    ostala za vedno (`ADR-035` C). Veljavni seji se drseči rok odmakne naprej,
    a največ enkrat na `RAZMIK_OSVEZITVE`.

    Seja neha veljati tudi, kadar je **račun** deaktiviran (`V3-R06`) ali
    kadar je ugasnjena **družina** (`V3-R05`). Obe dejanji seje že izbrišeta v
    svoji transakciji; ta preverba je druga plast in ujame sejo, ki je
    nastala v isti sapi kot deaktivacija (`ADR-044` A).
    """
    if not zeton:
        return None
    seja = repo.seja(zgostitev_zetona(zeton))
    if seja is None:
        return None
    if seja.expires_at <= ko or not seja.is_active or not seja.family_is_active:
        # Ne samo ta vrstica: potekla seja je znak, da jih je verjetno več
        # (ista naprava, ista ura poteka), in čiščenje je ena poizvedba.
        repo.izbrisi_sejo(seja.session_id)
        repo.pocisti_potekle_seje(ko)
        return None
    if ko - seja.last_used_at >= RAZMIK_OSVEZITVE:
        repo.osvezi_sejo(seja.session_id, ko, ko + TRAJANJE_SEJE)
    return seja


# --- Vrnitev na zahtevano pot ----------------------------------------------

#: Kam pelje prijava, kadar cilja ni ali ni sprejemljiv.
PRIVZETI_CILJ = "/admin"


def varen_cilj(cilj: str | None) -> str:
    """Pot, na katero se uporabnica po prijavi vrne.

    Sprejme **izključno** relativno pot pod `/admin`. Vse ostalo pelje na
    `/admin`: `next=https://zlo.example/` bi sicer prijavo spremenil v
    preusmerjevalnik na tujo stran, `next=/materials` pa bi peljal na pot
    telefona, ki v brskalniku vrne 401.
    """
    if not cilj or not cilj.startswith("/") or cilj.startswith("//"):
        return PRIVZETI_CILJ
    razbito = urlsplit(cilj)
    if razbito.scheme or razbito.netloc:
        return PRIVZETI_CILJ
    pot = razbito.path
    if pot != "/admin" and not pot.startswith("/admin/"):
        return PRIVZETI_CILJ
    return cilj
