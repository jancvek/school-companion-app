"""Google prijava: pravila toka in klic Googlu (V3-R08).

Modul ne ve za FastAPI in ne za bazo — dobi vrednosti, vrne izid. Isti rez kot
`app/prijava.py`, `app/clani.py` in `app/urnik.py`, in iz istega razloga:
pravila se dajo preizkusiti brez zaganjanja strežnika, kar je pri toku, ki ima
tri korake in pet načinov zavrnitve, razlika med preizkusljivim in ne.

Edino, kar je od HTTP tu, sta `postavi_stanje` in `pobrisi_stanje`. Nista
izjema od tega reza, ampak njegova posledica: piškotek **je** vezivo, in
njegove zastavice — predvsem `SameSite=Lax` — so del pravila, ne način
prenosa. Stojita tu tudi zato, ker ju potrebujeta **oba** usmerjevalnika
(`racun.py` in `vstop.py`), kar po pravilu iz `docs/01-arhitektura.md` pomeni,
da nista last nobenega od njiju. `starlette.Response` ni FastAPI; uvaža ga
tudi `app/security.py`, ki prav tako ni usmerjevalnik.

Odločitve so v `docs/odlocitve/ADR-046`. Tri stvari, ki se iz kode ne vidijo
same:

- **`identifier` je `sub`, ne e-naslov** (`ADR-046` A). E-naslov se sme
  spremeniti in bi ob spremembi odnesel prijavo; `sub` ne. E-naslov gre v
  `credentials.label`, kjer ga nihče ne išče.
- **Podpisa ID žetona namerno ne preverjamo** (`ADR-046` E). Podatke dobimo
  neposredno od Googla prek TLS, ne prek brskalnika — preverba podpisa je
  potrebna takrat, ko žeton pride po nezaupani poti. Tu ne pride. Zato tudi
  ni `pyjwt[crypto]` in ni predpomnilnika JWKS.
- **`state` je vezivo, ne okras** (`ADR-046` D). Povratni klic je navaden
  `GET` iz tujega konteksta; brez veziva bi napadalec svoj Google račun
  prilepil na tuj račun in v tujo družino vstopal, kolikor dolgo bi hotel.
  Zato `Stanje` nosi poleg naključja še namen in — pri povezovanju —
  uporabnika, ki je tok sprožil.
"""

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlencode

import httpx
from starlette.responses import Response

from app.settings import Settings

dnevnik = logging.getLogger(__name__)

# --- Poti ------------------------------------------------------------------

#: Začetek prijave. **Zunaj `/admin`**, ker seje ob njem še ni; CSRF žeton
#: preveri pot sama, z istim dvojno oddanim piškotkom kot prijavni obrazec
#: (`ADR-046` B).
POT_PRIJAVE = "/auth/google/login"

#: Povratna pot. **Ena sama za oba tokova** (`ADR-046` C): kaj se dogaja, pove
#: piškotek stanja, ne naslov. Dva naslova bi pomenila dva vpisa v Googlovi
#: konzoli in dve poti, ki delata skoraj isto.
POT_POVRATNA = "/auth/google/callback"

#: Nastavitve prijavljenega starša. Pod `/admin`, torej pod `SejaMiddleware`
#: brez izjeme: povezovanje sproži nekdo, ki **je** prijavljen (`ADR-046` B).
POT_RACUNA = "/admin/racun"
POT_POVEZAVE = f"{POT_RACUNA}/google"
POT_ODSTRANITVE = f"{POT_RACUNA}/google/odstrani"

# --- Googlove končne točke -------------------------------------------------

NASLOV_PRIVOLITVE = "https://accounts.google.com/o/oauth2/v2/auth"
NASLOV_ZETONA = "https://oauth2.googleapis.com/token"
NASLOV_PODATKOV = "https://openidconnect.googleapis.com/v1/userinfo"

#: Obsegi, ki jih zahtevamo. **Nič čez to** — ne koledar, ne pošta, ne diska.
#: Prijava potrebuje istovetnost in nič drugega, in obseg, ki ga prosimo, je
#: tisto, kar starš na Googlovem zaslonu prebere o nas.
OBSEGI = "openid email profile"

#: Časovna omejitev enega klica Googlu, v sekundah.
#:
#: Meja ni okras, iz istega razloga kot pri vision klicu: klic brez nje bi
#: lahko visel, dokler ne odneha brskalnik — uporabnica bi ves ta čas gledala
#: prazno stran in ne bi vedela, ali se kaj dogaja.
OMEJITEV_SEKUND = 15.0

# --- Sporočila -------------------------------------------------------------

#: Eno samo sporočilo za vsak neuspeh, ki bi sicer izdal, ali račun obstaja.
#:
#: Isto načelo kot `prijava.SPOROCILO_NEUSPELA_PRIJAVA`: neznan Google račun,
#: deaktiviran račun in ugasnjena družina dajo isto besedilo. Pove, kaj naj
#: uporabnica naredi (prijavi se z geslom in poveži), ne da bi povedala, v
#: katerem od teh stanj je.
SPOROCILO_NEPOVEZAN = (
    "S tem Google računom prijava ni mogoča. Google račun poveže starš sam, "
    "v nastavitvah svojega računa, potem ko se prijavi z geslom."
)

SPOROCILO_STANJE = (
    "Prijava z Googlom se ni končala tam, kjer se je začela, zato je nisem "
    "dokončal. Poskusi znova v istem oknu brskalnika."
)

SPOROCILO_NEDOSEGLJIV = (
    "Googla trenutno ne morem doseči, zato prijave nisem dokončal. "
    "Poskusi čez nekaj minut ali se prijavi z geslom."
)

SPOROCILO_NEPOTRJEN = (
    "Ta Google račun nima potrjenega e-naslova, zato ga nisem povezal. "
    "Potrdi naslov pri Googlu in poskusi znova."
)

#: Ta račun Google **že** ima. Ločeno od `SPOROCILO_ZASEDEN`, ker je pot naprej
#: druga: tam je račun pri nekom drugem in ni kaj narediti, tu je tvoj in ga
#: lahko najprej odstraniš.
SPOROCILO_ZE_POVEZAN = (
    "Ta račun ima Google račun že povezan. Če želiš povezati drugega, najprej "
    "odstrani obstoječega."
)

SPOROCILO_ZASEDEN = (
    "Ta Google račun je že povezan z drugim računom v tej namestitvi. "
    "Eden Google račun pripada enemu uporabniku."
)

SPOROCILO_ZAVRNJENO = (
    "Prijave z Googlom nisi dokončala — Google je sporočil, da je bila "
    "zavrnjena ali preklicana. Lahko poskusiš znova ali se prijaviš z geslom."
)

SPOROCILO_POVEZANO = "Google račun je povezan."
SPOROCILO_ODSTRANJENO = "Google račun ni več povezan."

#: Besedilo, ko Google v tej namestitvi sploh ni nastavljen (`ADR-046` F).
#: Enako kot za vsako resnično neobstoječo pot — namestitev brez Googla teh
#: strani nima in obiskovalcu ne pove, da bi jih lahko imela.
SPOROCILO_NI_STRANI = (
    "Te strani ni. Morda je bil naslov napačno prepisan; na začetni strani so "
    "vse, ki so na voljo."
)

#: Oznake izidov, ki jih stran računa pokaže po preusmeritvi. V naslovu je
#: **oznaka**, ne besedilo: besedilo v naslovu bi pomenilo, da lahko kdorkoli s
#: povezavo nariše poljubno sporočilo na našo stran.
IZID_POVEZANO = "povezano"
IZID_ODSTRANJENO = "odstranjeno"

SPOROCILA_IZIDOV: dict[str, str] = {
    IZID_POVEZANO: SPOROCILO_POVEZANO,
    IZID_ODSTRANJENO: SPOROCILO_ODSTRANJENO,
}

#: Oznake napak, ki jih pokaže **prijavna** stran po preusmeritvi.
#:
#: Skozi naslov potuje oznaka in nikoli besedilo. Prosto besedilo v naslovu bi
#: pomenilo, da lahko kdorkoli s pripravljeno povezavo nariše poljubno
#: sporočilo na našo prijavno stran — „vpiši geslo še enkrat na …" je napad,
#: ne napaka. Neznana oznaka ne pokaže ničesar.
OZNAKA_STANJE = "stanje"
OZNAKA_NEDOSEGLJIV = "nedosegljiv"
OZNAKA_NEPOVEZAN = "nepovezan"
OZNAKA_ZAVRNJENO = "zavrnjeno"

SPOROCILA_PRIJAVE: dict[str, str] = {
    OZNAKA_STANJE: SPOROCILO_STANJE,
    OZNAKA_NEDOSEGLJIV: SPOROCILO_NEDOSEGLJIV,
    OZNAKA_NEPOVEZAN: SPOROCILO_NEPOVEZAN,
    OZNAKA_ZAVRNJENO: SPOROCILO_ZAVRNJENO,
}

SPOROCILO_ZADNJA_POVERILNICA = (
    "Najprej nastavi geslo, sicer se ne boš mogel več prijaviti. Ko je geslo "
    "nastavljeno, lahko Google račun odstraniš."
)


class NapakaGoogla(Exception):
    """Klic Googlu ni uspel; sporočilo je v slovenščini in za bralca.

    Nosi **berljivo** besedilo, ne surove napake storitve (merilo dokončanosti
    v `CLAUDE.md` §1b). Kaj se je v resnici zgodilo, gre v dnevnik.
    """


# --- Vezivo povratnega klica (`ADR-046` D) ---------------------------------


class Namen(Enum):
    """Zakaj je bil tok sprožen. Povratna pot je ena, tokova sta dva."""

    PRIJAVA = "prijava"
    POVEZAVA = "povezava"


#: Ime piškotka, v katerem živi stanje med odhodom h Googlu in povratkom.
PISKOTEK_STANJA = "google_state"

#: Kako dolgo piškotek stanja velja. Privolitveni zaslon je nekaj klikov;
#: deset minut je zanj obilo, za ukradeno vrednost pa malo.
STANJE_SEKUND = 600

#: Ločilo v zapisu stanja. Ne `-` in ne `_`: oba se pojavita v
#: `secrets.token_urlsafe` in v UUID-ju, zato bi razčlenitev postala odvisna
#: od tega, kje se prvi pojavi.
_LOCILO = "."


@dataclass(frozen=True)
class Stanje:
    """Kar mora povratni klic dokazati, da je isti tok kot odhod.

    `user_id` je `None` pri prijavi (takrat uporabnika še ne poznamo) in
    obvezen pri povezovanju. Prav ta razlika je bistvo `ADR-046` D: pri
    povezovanju se mora ujemati **tudi** z dejavno sejo, sicer bi se
    poverilnica pripisala napačnemu staršu.
    """

    namen: Namen
    nakljucje: str
    user_id: str | None = None

    def zapis(self) -> str:
        """Vrednost, ki gre v piškotek.

        Brez podpisa: piškotek je naš in `HttpOnly`, primerja pa se sam s
        seboj — nikoli se mu ne zaupa kot trditvi o svetu. Podpis bi varoval
        pred ponarejanjem vsebine, kar je tu brez pomena: ponarejena vrednost
        se preprosto ne bo ujela s `state`, ki ga vrne Google.
        """
        return _LOCILO.join((self.namen.value, self.nakljucje, self.user_id or ""))

    @staticmethod
    def iz_zapisa(zapis: str | None) -> "Stanje | None":
        """Stanje iz piškotka, ali `None`, kadar ga ni ali je pokvarjen.

        Molk je zavrnitev, ne izjema: piškotek je poljuben vnos od zunaj in
        vsaka oblika, ki je ne prepoznamo, pomeni „tega toka nisem začel jaz".
        """
        if not zapis:
            return None
        deli = zapis.split(_LOCILO)
        if len(deli) != 3:
            return None
        namen_zapis, nakljucje, user_id = deli
        if not nakljucje:
            return None
        try:
            namen = Namen(namen_zapis)
        except ValueError:
            return None
        if namen is Namen.POVEZAVA and not user_id:
            return None
        return Stanje(namen=namen, nakljucje=nakljucje, user_id=user_id or None)


def novo_stanje(namen: Namen, user_id: str | None = None) -> Stanje:
    """Stanje z novim naključjem. 256 bitov, kot žeton seje (`ADR-027` B2)."""
    return Stanje(namen=namen, nakljucje=secrets.token_urlsafe(32), user_id=user_id)


def stanje_se_ujema(iz_piskotka: Stanje | None, iz_googla: str | None) -> bool:
    """Ali povratek pripada odhodu.

    Primerjava je `compare_digest` in ne `==`: vrednost je skrivnost za
    trajanje enega toka, in primerjava, ki odneha pri prvem različnem znaku,
    o njej pove več, kot je treba.
    """
    if iz_piskotka is None or not iz_googla:
        return False
    return secrets.compare_digest(iz_piskotka.nakljucje, iz_googla)


def povezava_pripada_seji(stanje: Stanje, user_id_seje: str | None) -> bool:
    """Ali je povezovanje začel isti uporabnik, ki je zdaj prijavljen.

    Velja **samo** za `Namen.POVEZAVA` in je drugi del veziva iz `ADR-046` D.
    Brez njega bi tok, začet pod eno sejo in vrnjen pod drugo, pripisal Google
    račun napačnemu staršu — in to je natanko oblika napada, ki izgleda kot
    povsem običajno delovanje.
    """
    if stanje.namen is not Namen.POVEZAVA:
        return True
    if stanje.user_id is None or user_id_seje is None:
        return False
    return secrets.compare_digest(stanje.user_id, user_id_seje)


# --- Naslovi ---------------------------------------------------------------


def povratni_naslov(domena: str) -> str:
    """Povratni naslov, kakršen mora biti vpisan v Googlovi konzoli.

    Sestavi se iz **nastavitve**, ne iz `request.url`: za Caddyjem je gostitelj
    v zahtevi lahko notranje ime vsebnika, in naslov, ki bi se razlikoval od
    vpisanega, bi Google zavrnil — z napako, ki je za uporabnico neberljiva.

    Vedno `https` (`ADR-026`): aplikacija drugega ne govori.
    """
    return f"https://{domena}{POT_POVRATNA}"


def naslov_privolitve(*, client_id: str, domena: str, stanje: Stanje) -> str:
    """Naslov Googlovega privolitvenega zaslona, na katerega preusmerimo.

    `prompt=select_account`, da starš z več Google računi lahko izbere pravega.
    Brez tega bi Google tiho vzel tistega, s katerim je pravkar prijavljen — in
    povezal bi se napačen račun, ne da bi kdo opazil, dokler prijava z drugim
    ne bi nehala delovati.
    """
    parametri = {
        "client_id": client_id,
        "redirect_uri": povratni_naslov(domena),
        "response_type": "code",
        "scope": OBSEGI,
        "state": stanje.nakljucje,
        "prompt": "select_account",
    }
    return f"{NASLOV_PRIVOLITVE}?{urlencode(parametri)}"


# --- Račun, ki ga vrne Google ----------------------------------------------


@dataclass(frozen=True)
class RacunGoogla:
    """Kar o računu potrebujemo, in nič več.

    Ime, slika in vse ostalo, kar `userinfo` vrne, se zavrže: podatek, ki ga
    ne potrebujemo, je podatek, ki ga ne hranimo.
    """

    #: Stabilen Googlov identifikator. Gre v `credentials.identifier`.
    sub: str
    #: E-naslov. Gre v `credentials.label` — **samo za izris** (`ADR-046` A).
    email: str | None
    #: Ali je Google naslov potrdil. Nepotrjen naslov ni dokaz o ničemer.
    email_verified: bool


#: Kaj naredi odjemalec: iz kode dobi račun. Vse ostalo (naslovi, stanje,
#: razsodbe) je zgoraj in ne potrebuje omrežja.
#:
#: Protokol in ne razred, iz istega razloga kot `vision.Klicalec`: v testih je
#: to navadna funkcija in zbirka nikoli ne pride do omrežja (`ADR-046` F).
class OdjemalecGoogla:
    """Vmesnik odjemalca. Izvedba je `naredi_odjemalca`, v testih ponaredek."""

    def racun(self, koda: str) -> RacunGoogla:  # pragma: no cover - vmesnik
        raise NotImplementedError


def naredi_odjemalca(
    nastavitve: Settings, prenos: httpx.Client | None = None
) -> OdjemalecGoogla:
    """Odjemalec, ki kodo zamenja za račun. Dva klica, oba prek HTTPS.

    `prenos` se poda samo v testih prenosa samega; redni testi podajo ponaredek
    celotnega odjemalca in do te funkcije sploh ne pridejo.
    """

    class _Odjemalec(OdjemalecGoogla):
        def racun(self, koda: str) -> RacunGoogla:
            if prenos is not None:
                # Podan prenos je last klicatelja in se tu ne zapira.
                return self._oboje(prenos, koda)
            with httpx.Client(timeout=OMEJITEV_SEKUND) as odjemalec:
                return self._oboje(odjemalec, koda)

        def _oboje(self, odjemalec: httpx.Client, koda: str) -> RacunGoogla:
            return self._podatki(odjemalec, self._zeton(odjemalec, koda))

        def _zeton(self, odjemalec: httpx.Client, koda: str) -> str:
            odgovor = self._poklici(
                lambda: odjemalec.post(
                    NASLOV_ZETONA,
                    data={
                        "code": koda,
                        "client_id": nastavitve.google_client_id,
                        "client_secret": nastavitve.google_client_secret,
                        "redirect_uri": povratni_naslov(nastavitve.domena),
                        "grant_type": "authorization_code",
                    },
                )
            )
            zeton = odgovor.get("access_token")
            if not isinstance(zeton, str) or not zeton:
                dnevnik.warning("Google ni vrnil access_token: %s", sorted(odgovor))
                raise NapakaGoogla(SPOROCILO_NEDOSEGLJIV)
            return zeton

        def _podatki(self, odjemalec: httpx.Client, zeton: str) -> RacunGoogla:
            odgovor = self._poklici(
                lambda: odjemalec.get(
                    NASLOV_PODATKOV, headers={"Authorization": f"Bearer {zeton}"}
                )
            )
            sub = odgovor.get("sub")
            if not isinstance(sub, str) or not sub:
                dnevnik.warning("Google ni vrnil sub: %s", sorted(odgovor))
                raise NapakaGoogla(SPOROCILO_NEDOSEGLJIV)
            email = odgovor.get("email")
            return RacunGoogla(
                sub=sub,
                email=email if isinstance(email, str) and email else None,
                # Privzetek je `False` in ne `True`: manjkajoče polje je
                # odsotnost potrdila, ne potrdilo.
                email_verified=odgovor.get("email_verified") is True,
            )

        @staticmethod
        def _poklici(klic: Callable[[], httpx.Response]) -> dict[str, object]:
            """Izvede klic in vrne JSON, ali vrže slovensko napako.

            Vsak neuspeh — omrežje, časovna omejitev, koda ≥ 400, odgovor, ki
            ni JSON — konča isto: v dnevnik podrobnost, uporabnici berljiv
            stavek. Surovo besedilo Googlove napake kot edina vsebina je po
            merilu dokončanosti (`CLAUDE.md` §1b) napaka.
            """
            try:
                odgovor = klic()
                odgovor.raise_for_status()
                telo = odgovor.json()
            except (httpx.HTTPError, ValueError) as napaka:
                dnevnik.warning("Klic Googlu ni uspel: %s", napaka)
                raise NapakaGoogla(SPOROCILO_NEDOSEGLJIV) from napaka
            if not isinstance(telo, dict):
                dnevnik.warning("Google je vrnil, kar ni predmet: %r", telo)
                raise NapakaGoogla(SPOROCILO_NEDOSEGLJIV)
            return telo

    return _Odjemalec()


# --- Razsodbe --------------------------------------------------------------


def zakaj_ne_sme_odstraniti(*, ima_geslo: bool) -> str | None:
    """Zakaj odstranitve Google povezave ne izvedemo, ali `None`.

    Kriterij 6 pravi, da odstranitev ne izbriše uporabnika in ne odstrani
    gesla. Kaj se zgodi, ko gesla **ni**, ne pove — in tako stanje ni
    izmišljeno: migracija `0008_uporabniki` ustvari račune prav brez gesla
    (`ADR-035` G).

    Odstranitev, po kateri na računu ne bi ostala nobena poverilnica, s katero
    se je mogoče prijaviti, bi bila zaklep samega sebe. Zato zavrnitev
    (`ADR-046` G) — in isto pravilo, ki jo zavrne, tudi gumba ne ponudi,
    natanko kot pri članih družine (`V3-R06`).
    """
    if not ima_geslo:
        return SPOROCILO_ZADNJA_POVERILNICA
    return None


def zakaj_ne_sme_povezati(racun: RacunGoogla, *, ze_povezan: bool) -> str | None:
    """Zakaj Google računa ne povežemo, ali `None`.

    `ze_povezan` je tu in ne samo v izrisu: stran gumba za povezovanje res ne
    pokaže, kadar je Google že povezan, a `POST` na pot je mogoč tudi brez
    gumba. Brez te preverbe bi starš dobil **dve** vrstici `kind='google'` —
    druga bi bila v nastavitvah nevidna (`nacini_prijave` vrne prvo) in prek
    vmesnika neodstranljiva, oba `sub` pa bi odpirala prijavo. Napaka, ki je
    ne bi opazil nihče, dokler ne bi bilo treba enega od njiju odvzeti.

    Enoličnost `sub` **čez uporabnike** tu ni preverjena: to razsodi baza
    (`credentials.identifier UNIQUE`), ker je poizvedba pred vstavljanjem
    tekma, ne preverba — isti razlog in isti vzorec kot pri zasedenem
    identifikatorju v `V3-R06` (`ADR-038` E). Tu gre za drugo vprašanje: ne
    „je ta `sub` zaseden", ampak „ima ta račun Google že".
    """
    if ze_povezan:
        return SPOROCILO_ZE_POVEZAN
    if not racun.email_verified:
        return SPOROCILO_NEPOTRJEN
    return None


def postavi_stanje(odgovor: Response, stanje: Stanje) -> None:
    """Postavi piškotek z vezivom povratnega klica (`ADR-046` D).

    Kliče ga **vsak** začetek toka — povezovanje (`routers/racun.py`) in
    prijava (`routers/vstop.py`). Ena funkcija zato, da se zastavice obeh
    mest ne moreta razideti; razhajanje bi bilo tiho in bi se videlo šele kot
    tok, ki nenadoma ne deluje ali ne varuje.

    `SameSite=Lax` je tu **pravi in ne ohlapni**: Googlova preusmeritev nazaj
    k nam je vrhnja navigacija, zato piškotek pride s seboj. `Strict` bi tok
    pokvaril (piškotka ob prihodu s tuje strani ne bi bilo), `None` pa bi
    vezivo izničil, ker bi piškotek potoval tudi ob zahtevah, ki jih sproži
    tuja stran.

    `secure=True` velja tudi v razvoju: strežnik od `V3-R02` govori izključno
    `https` (isti razlog kot pri piškotku seje).
    """
    odgovor.set_cookie(
        PISKOTEK_STANJA,
        stanje.zapis(),
        max_age=STANJE_SEKUND,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def pobrisi_stanje(odgovor: Response) -> None:
    """Pobriše piškotek stanja. Kliče se ob **vsakem** izidu povratnega klica.

    Enkratna raba je del veziva, ne pospravljanje: piškotek, ki po povratku
    ostane, je vrednost, ki jo je mogoče uporabiti še enkrat.
    """
    odgovor.delete_cookie(PISKOTEK_STANJA, path="/")
