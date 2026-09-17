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

#: Poti prijave in odjave. Pod `/admin` sta zato, ker bi ju `ApiKeyMiddleware`
#: sicer zahteval z glavo `X-API-Key`, ki je brskalnik ne zna poslati.
POT_PRIJAVE = "/admin/login"
POT_ODJAVE = "/admin/logout"

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

#: Najkrajše geslo po vlogi (`ADR-035` G). Staršev račun je admin družine na
#: javnem internetu; otrokov je za mobilno prijavo in do `/admin` ne pride.
#: Ključ je `str` in ne `Vloga`: vloga pride iz baze kot navaden niz in
#: vrednost, ki je v tabeli ne bi smelo biti, mora pasti na privzetek za
#: starša (strožjega), ne na `KeyError`.
NAJKRAJSE_GESLO: dict[str, int] = {VLOGA_STARS: 12, VLOGA_OTROK: 4}

#: Eno samo sporočilo za vse neuspehe, ki bi sicer izdali, ali račun obstaja.
SPOROCILO_NEUSPELA_PRIJAVA = (
    "E-naslov ali geslo ni pravo. Poskusi znova; po več zaporednih poskusih "
    "bo prijava počasnejša."
)

#: Izjema od enotnega sporočila (`ADR-035` F): Maša mora razumeti, zakaj ne gre.
SPOROCILO_OTROK = (
    "Ta račun je otrokov in se prijavi v mobilni aplikaciji, ne na tej strani."
)

_ZGOSCEVALNIK = PasswordHasher()

#: Zgostitev, ob katero se preveri geslo za neobstoječ račun.
#:
#: Izračuna se ob uvozu in ne zapiše kot konstanta v kodi: ročno prepisana
#: zgostitev se lahko razide s parametri `PasswordHasher` — in preverba proti
#: zgostitvi z drugačnimi parametri traja drugače dolgo, kar je natanko tisto,
#: kar naj lažna preverba skrije. Gesla, ki ga zgostitev nosi, ne pozna nihče.
_LAZNA_ZGOSTITEV_GESLA = _ZGOSCEVALNIK.hash(secrets.token_urlsafe(32))


class Izid(Enum):
    """Kaj se je zgodilo ob poskusu prijave."""

    USPEH = "uspeh"
    ZAVRNJENO = "zavrnjeno"
    OTROK = "otrok"


@dataclass(frozen=True)
class IzidPrijave:
    """Izid z vsem, kar klicatelj potrebuje za odgovor."""

    izid: Izid
    sporocilo: str | None = None
    poverilnica: PoverilnicaZaPrijavo | None = None


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
    """Primerja žetona v konstantnem času; manjkajoč žeton ne velja nikoli."""
    if not prvi or not drugi:
        return False
    return secrets.compare_digest(prvi, drugi)


# --- Omejevanje ugibanja ---------------------------------------------------


def zamik_pred_preverbo(neuspelih: int) -> float:
    """Koliko sekund čaka poskus, preden se geslo sploh preveri."""
    return ZAMIK_SEKUND if neuspelih >= PRAG_POSKUSOV else 0.0


def koliko_cakati(repo: PrijavaRepository, identifikator: str, ko: datetime) -> float:
    """Zamik za ta identifikator ob času `ko`."""
    neuspelih = repo.neuspelih_poskusov(identifikator, ko - OKNO_POSKUSOV)
    return zamik_pred_preverbo(neuspelih)


# --- Prijava ---------------------------------------------------------------


def preveri_prijavo(
    repo: PrijavaRepository,
    identifikator: str,
    geslo: str,
    *,
    ip: str | None,
    ko: datetime,
) -> IzidPrijave:
    """Preveri poverilnico in zabeleži neuspeh.

    Seje **ne** ustvari — to je ločen korak (`ustvari_sejo`), da je vidno, kje
    seja nastane. Neuspeh zapiše v `login_attempts`; uspeh števce pobriše in
    počisti potekle seje ter stare poskuse (`ADR-035` C).
    """
    poverilnica = repo.poverilnica(identifikator)

    if poverilnica is None:
        _preveri_lazno(geslo)
        repo.zabelezi_neuspeh(identifikator, ip, ko)
        return IzidPrijave(Izid.ZAVRNJENO, SPOROCILO_NEUSPELA_PRIJAVA)

    if not geslo_se_ujema(poverilnica.secret_hash, geslo) or not poverilnica.is_active:
        repo.zabelezi_neuspeh(identifikator, ip, ko)
        return IzidPrijave(Izid.ZAVRNJENO, SPOROCILO_NEUSPELA_PRIJAVA)

    if poverilnica.role == VLOGA_OTROK:
        # Geslo je pravo, zato to ni neuspel poskus in se ne šteje.
        return IzidPrijave(Izid.OTROK, SPOROCILO_OTROK)

    repo.pozabi_poskuse(identifikator)
    repo.pocisti_potekle_seje(ko)
    repo.pocisti_stare_poskuse(ko - HRAMBA_POSKUSOV)
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
    """
    if not zeton:
        return None
    seja = repo.seja(zgostitev_zetona(zeton))
    if seja is None:
        return None
    if seja.expires_at <= ko or not seja.is_active:
        repo.izbrisi_sejo(seja.session_id)
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
