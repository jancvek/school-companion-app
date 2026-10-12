"""Registracija starša z Googlom: pravila, meje in vezivo obrazca (V6-R02).

Modul ne ve za FastAPI in ne za bazo — dobi vrednosti, vrne izid. Isti rez kot
`app/google.py` in `app/sistem.py`. Od HTTP sta tu samo `postavi_istovetnost`
in `pobrisi_istovetnost`, iz istega razloga kot piškotek stanja v
`app/google.py`: piškotek **je** vezivo in njegove zastavice so del pravila.

Odločitve so v `docs/odlocitve/ADR-057` (kaj) in `ADR-062` (kako). Tri stvari,
ki se iz kode ne vidijo same:

- **Povratni klic ne ustvari ničesar** (`ADR-057` A). Googlova istovetnost
  zato do oddanega obrazca potuje v piškotku — in ta mora biti **podpisan**:
  nepodpisan `sub` bi pomenil, da si kdorkoli registrira tuj Google račun, in
  lastnik tega računa bi se pozneje „prijavil" v napadalčevo družino
  (`ADR-062` G).
- **Ključ podpisa živi v pomnilniku procesa.** Ustvari ga `create_app`; ponovni
  zagon strežnika zato prekine registracije, ki so ravno med Googlom in oddajo.
  Starš klikne „Nadaljuj z Googlom" znova.
- **Meje po IP ni** (`ADR-062` F): v tej postavitvi naslov odjemalca ni
  podatek (`ADR-034` A). Meji sta število čakajočih družin in število
  registracij na dan, obe za celo namestitev.
"""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from starlette.responses import Response

from app import clani, sistem

#: Okno registracije in oddaja obrazca. Pod `/admin`, izvzeto iz seje kot
#: prijavna stran (`ADR-062` I).
POT = "/admin/register"

#: Kam gre starš po oddanem zahtevku in kam zapora pošlje neodobreno družino.
POT_RACUNA = "/admin/racun"

# --- Meji javnega obrazca (`ADR-062` F) -------------------------------------

#: Največ družin, ki hkrati čakajo na odobritev. Zavrnjene ne štejejo.
NAJVEC_CAKAJOCIH = 20

#: Največ oddanih registracij v `OKNO_REGISTRACIJ`, za celo namestitev.
NAJVEC_NA_OKNO = 10
OKNO_REGISTRACIJ = timedelta(hours=24)

#: Oznaka vrstic v `login_attempts`, po katerih se šteje dnevna meja. Velike
#: črke, kot `prijava.OZNAKA_POSKUSOV_POVEZAVE`: identifikator prijave je vedno
#: z malimi, zato se z nobenim ne more ujeti.
OZNAKA_POSKUSOV = "REGISTRACIJA"

# --- Sporočila --------------------------------------------------------------

SPOROCILO_PREVEC = (
    "Trenutno čaka preveč zahtevkov. Registracije zdaj ni mogoče oddati. "
    "Poskusi znova čez nekaj dni."
)
SPOROCILO_PRAZNO_IME_DRUZINE = (
    "Ime družine manjka. Vpiši ga — prikazano bo v meniju in skrbniku ob odobritvi."
)
SPOROCILO_BREZ_SOGLASJA = (
    "Brez soglasja zahtevka ne morem oddati. Preberi besedilo in potrdi polje, "
    "če se strinjaš."
)
SPOROCILO_POTEKLO = (
    "Od prijave z Googlom je minilo preveč časa ali pa je bil strežnik medtem "
    "zagnan znova. Klikni „Nadaljuj z Googlom“ še enkrat."
)
SPOROCILO_GESLO_OBSTAJA = (
    "Za ta e-naslov že obstaja račun z geslom. Prijavi se z e-naslovom in "
    "geslom, nato Google povežeš v nastavitvah svojega računa."
)
SPOROCILO_NEPOTRJEN = (
    "Ta Google račun nima potrjenega e-naslova, zato z njim registracija ni "
    "mogoča. Potrdi naslov pri Googlu in poskusi znova."
)
SPOROCILO_ZE_REGISTRIRAN = (
    "Ta Google račun je že registriran. Prijavi se z njim na prijavni strani."
)

#: Oznake napak, ki jih okno registracije pokaže po preusmeritvi. V naslovu je
#: oznaka in nikoli besedilo — isto pravilo in isti razlog kot v
#: `google.SPOROCILA_PRIJAVE`.
OZNAKA_GESLO = "geslo"
OZNAKA_NEPOTRJEN = "nepotrjen"
OZNAKA_POTEKLO = "poteklo"
OZNAKA_ZE_REGISTRIRAN = "obstaja"

SPOROCILA: dict[str, str] = {
    OZNAKA_GESLO: SPOROCILO_GESLO_OBSTAJA,
    OZNAKA_NEPOTRJEN: SPOROCILO_NEPOTRJEN,
    OZNAKA_POTEKLO: SPOROCILO_POTEKLO,
    OZNAKA_ZE_REGISTRIRAN: SPOROCILO_ZE_REGISTRIRAN,
}

# --- Istovetnost med povratnim klicem in obrazcem (`ADR-062` G) --------------

#: Ime piškotka s podpisano istovetnostjo.
PISKOTEK = "registracija"

#: Kako dolgo piškotek velja. Obrazec ima tri polja; deset minut je zanj obilo.
VELJAVNOST = timedelta(minutes=10)

#: Najdaljše ime, ki ga iz Googla sploh vzamemo v piškotek. Ime je samo predlog
#: za polje obrazca; predolgo se odreže tu, da piškotek ne more zrasti čez mejo
#: brskalnika.
_NAJDALJSE_IME = clani.NAJDALJSE_IME


@dataclass(frozen=True)
class Istovetnost:
    """Kar je o računu povedal Google in kar obrazec potrebuje."""

    #: Stabilen Googlov identifikator; postane `credentials.identifier`.
    sub: str
    #: Potrjen e-naslov; postane `credentials.label` (samo za izris).
    email: str
    #: Ime iz Googla — predlog za polje „Tvoje ime", nič več.
    name: str


def nov_kljuc() -> bytes:
    """Ključ podpisa za en zagon strežnika. 256 bitov."""
    return secrets.token_bytes(32)


def _b64(podatki: bytes) -> str:
    return base64.urlsafe_b64encode(podatki).decode("ascii").rstrip("=")


def _iz_b64(zapis: str) -> bytes:
    return base64.urlsafe_b64decode(zapis + "=" * (-len(zapis) % 4))


def _podpis(kljuc: bytes, vsebina: str) -> str:
    return _b64(hmac.new(kljuc, vsebina.encode("ascii"), hashlib.sha256).digest())


def zapisi_istovetnost(istovetnost: Istovetnost, kljuc: bytes, ko: datetime) -> str:
    """Vrednost piškotka: vsebina in njen HMAC-SHA256, ločena s piko."""
    vsebina = _b64(
        json.dumps(
            {
                "sub": istovetnost.sub,
                "email": istovetnost.email,
                "name": istovetnost.name[:_NAJDALJSE_IME],
                "exp": int((ko + VELJAVNOST).timestamp()),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
    )
    return f"{vsebina}.{_podpis(kljuc, vsebina)}"


def preberi_istovetnost(zapis: str | None, kljuc: bytes, ko: datetime) -> Istovetnost | None:
    """Istovetnost iz piškotka, ali `None`.

    Molk je zavrnitev, ne izjema: piškotek je poljuben vnos od zunaj. `None`
    pomeni katerokoli od: piškotka ni, podpis se ne ujema (ponarejen ali
    podpisan s ključem prejšnjega zagona), rok je mimo, oblika ni naša.

    **Podpis se preveri, preden se vsebina razčleni** — vsebini, ki je nismo
    podpisali mi, ne verjamemo niti toliko, da bi jo brali.
    """
    if not zapis or zapis.count(".") != 1:
        return None
    vsebina, podpis = zapis.split(".")
    try:
        pricakovan = _podpis(kljuc, vsebina)
    except UnicodeEncodeError:
        return None
    if not hmac.compare_digest(pricakovan.encode("ascii"), podpis.encode("utf-8", "replace")):
        return None
    try:
        polja = json.loads(_iz_b64(vsebina))
    except (ValueError, binascii.Error):
        return None
    if not isinstance(polja, dict):
        return None
    sub, email, name, exp = (polja.get(k) for k in ("sub", "email", "name", "exp"))
    if not (isinstance(sub, str) and sub and isinstance(email, str) and email):
        return None
    if not isinstance(name, str) or not isinstance(exp, int):
        return None
    if ko.timestamp() >= exp:
        return None
    return Istovetnost(sub=sub, email=email, name=name)


def postavi_istovetnost(odgovor: Response, zapis: str) -> None:
    """Postavi piškotek z istovetnostjo. Zastavice kot pri piškotku stanja.

    `SameSite=Lax`: obrazec oddaja naša stran, a do nje starš pride s
    preusmeritvijo z Googlovega povratnega klica — vrhnja navigacija.
    """
    odgovor.set_cookie(
        PISKOTEK,
        zapis,
        max_age=int(VELJAVNOST.total_seconds()),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def pobrisi_istovetnost(odgovor: Response) -> None:
    """Pobriše piškotek — ob oddaji in ob vsakem novem začetku toka."""
    odgovor.delete_cookie(PISKOTEK, path="/")


# --- Razsodbe ---------------------------------------------------------------


def je_prek_meje(*, cakajocih: int, v_oknu: int) -> bool:
    """Ali je javni obrazec ta trenutek zaprt (`ADR-062` F).

    Ena razsodba za obe meji: obrazec ne pove, katera je ugriznila.
    """
    return cakajocih >= NAJVEC_CAKAJOCIH or v_oknu >= NAJVEC_NA_OKNO


def zakaj_ne_sme_zaceti(
    *, email: str | None, email_verified: bool, enaslov_ima_geslo: bool
) -> str | None:
    """Oznaka razloga, zakaj neznan Google račun ne pride do obrazca, ali `None`.

    Nepotrjen ali manjkajoč e-naslov ni dokaz o ničemer (`ADR-046` D). E-naslov
    z obstoječo geselno poverilnico se ne registrira in se ne združi sam od
    sebe (`ADR-057` A).
    """
    if not email or not email_verified:
        return OZNAKA_NEPOTRJEN
    if enaslov_ima_geslo:
        return OZNAKA_GESLO
    return None


def preveri_obrazec(*, ime_druzine: str, ime: str, soglasje: bool) -> str | None:
    """Razlog, zakaj oddani obrazec ni veljaven, ali `None`.

    Imeni preverjata isti funkciji kot na lastnikovi in starševi strani; tu je
    novo samo soglasje, brez katerega registracija ne nastane (`ADR-057` D).
    """
    if not ime_druzine.strip():
        # Svoje besedilo: lastnikovo („po katerem boš družino prepoznal na
        # seznamu") nagovarja nekoga, ki seznam družin vidi.
        return SPOROCILO_PRAZNO_IME_DRUZINE
    return (
        sistem.preveri_ime_druzine(ime_druzine)
        or clani.preveri_prikazno_ime(ime)
        or (None if soglasje else SPOROCILO_BREZ_SOGLASJA)
    )
