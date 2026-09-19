"""Dve preverbi ob vhodu: žeton telefona in seja s CSRF (admin stran).

Obe stojita na isti tabeli `sessions` in na istem neprozornem žetonu
(`docs/odlocitve/ADR-027`); razlikujeta se po prenosniku — telefon nosi žeton v
glavi `Authorization: Bearer`, brskalnik v piškotku — in po tem, kaj naredita,
ko seje ni: telefon dobi `401` kot JSON, brskalnik `303` na prijavo.

Zakaj vmesni plasti (ASGI middleware) in ne odvisnosti na endpointu:

- **Žeton:** FastAPI telo zahteve prebere, *preden* razreši odvisnosti.
  Preverba kot odvisnost bi torej pomenila, da strežnik celo večmegabajtno
  sliko najprej prebere in šele nato ugotovi, da žeton ne velja. Vmesna plast
  zavrne zahtevo, preden se telo sploh začne brati — kar je tudi edini način,
  da drži zahteva „401, brez zapisa v bazo in brez datoteke".
- **Seja:** odvisnost je mogoče pozabiti pri novem usmerjevalniku, predpone pa
  ne. Pot pod `/admin`, ki je nihče ni dodal na noben seznam, je varovana po
  privzetku (`docs/odlocitve/ADR-035` A). Generirani test dosegljivosti
  pozabljeno pot sicer ujame, a koda, ki napake ne dopusti, je boljša od testa,
  ki jo prijavi.

Do V3-R04 je bila prva plast `ApiKeyMiddleware` z enim vgrajenim ključem za
vse družine. Odpadel je ostro, ne postopno (`ADR-027` C2): strežnik ne sprejema
obojega, ker bi obdobje, ko veljata oba načina, trajalo dlje od same zamenjave.
"""

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode

from sqlalchemy.orm import Session, sessionmaker
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import prijava
from app.db import PrijavaRepository, SejaUporabnika

#: Glava, v kateri telefon pošlje žeton.
GLAVA_ZETONA = "authorization"

SPOROCILO_NEVELJAVEN_ZETON = (
    "Prijava je potekla ali ni veljavna. Prijavi se v aplikaciji znova; "
    "posnetki na telefonu ostanejo in se prenesejo po prijavi."
)


def zeton_iz_glave(glava: str | None) -> str | None:
    """Žeton iz glave `Authorization: Bearer <žeton>`, ali `None`.

    Shema se primerja brez ozira na velikost črk, kot zahteva RFC 7235. Vse
    ostalo (druga shema, glava brez presledka, prazen žeton) je `None` —
    molk je zavrnitev, ne izjema: glava je poljuben vnos od zunaj.
    """
    if not glava:
        return None
    shema, _, vrednost = glava.partition(" ")
    if shema.lower() != prijava.SHEMA_ZETONA:
        return None
    zeton = vrednost.strip()
    return zeton or None


def je_izvzeta(pot: str, poti: frozenset[str], predpone: frozenset[str]) -> bool:
    """Ali je pot izvzeta iz preverbe žetona.

    Predpona se ujame samo na sami sebi in na tem, kar ji sledi za poševnico:
    `/admin` in `/admin/karkoli`, **ne** pa `/administration`. Golo
    `startswith("/admin")` bi izvzelo vsako pot, ki se slučajno začne enako —
    in tako izvzetje bi bilo videti pravilno vse do dneva, ko nastane pot s
    podobnim imenom (odločitev 6 v `docs/plan/V1-R04.md`).
    """
    if pot in poti:
        return True
    return any(pot == predpona or pot.startswith(f"{predpona}/") for predpona in predpone)


def _razresi_sejo(scope: Scope, zeton: str | None) -> SejaUporabnika | None:
    """Seja za dani žeton, z lastno sejo baze. Skupno obema plastema."""
    tovarna: sessionmaker[Session] = scope["app"].state.tovarna_sej
    with tovarna() as seja_baze:
        return prijava.seja_za_zeton(PrijavaRepository(seja_baze), zeton, datetime.now(UTC))


class ZetonMiddleware:
    """Zahteva veljavno sejo otroka za vsako pot telefona.

    Poleg veljavnosti seje preverja tudi **vrata**: skozi to plast sme le
    vloga, ki na telefon sodi (`prijava.vloga_sodi`). Brez te vrstice bi
    starš, ki bi vrednost svojega piškotka prilepil v glavo, prišel na poti
    telefona — in, kar je huje, zrcalna preverba v `SejaMiddleware` bi
    manjkala tudi v drugo smer. Glej `docs/odlocitve/ADR-036` D.
    """

    def __init__(
        self,
        app: ASGIApp,
        izvzete_poti: frozenset[str],
        izvzete_predpone: frozenset[str] = frozenset(),
    ) -> None:
        self.app = app
        self.izvzete_poti = izvzete_poti
        self.izvzete_predpone = izvzete_predpone

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or je_izvzeta(
            scope["path"], self.izvzete_poti, self.izvzete_predpone
        ):
            await self.app(scope, receive, send)
            return

        zeton = zeton_iz_glave(Headers(scope=scope).get(GLAVA_ZETONA))
        seja = _razresi_sejo(scope, zeton)

        if seja is None or not prijava.vloga_sodi(seja.role, prijava.Vrata.TELEFON):
            odgovor = JSONResponse(
                {"detail": SPOROCILO_NEVELJAVEN_ZETON},
                status_code=401,
            )
            await odgovor(scope, receive, send)
            return

        # Družino odslej pove seja, ne „edina družina v bazi" (`ADR-029` A je
        # s tem razveljavljen, `ADR-036` F). Odvisnosti je ne berejo znova.
        scope.setdefault("state", {})["prijava"] = seja

        await self.app(scope, receive, send)


#: Največje telo, ki ga plast prebere, da najde CSRF žeton (1 MiB).
#:
#: Obrazci pod `/admin` so kratki; nalaganja datotek tam ni (slike prihajajo s
#: telefona na `POST /materials`, ki je zunaj te plasti). Meja je tu zato, da
#: plast ne zadrži poljubno velikega telesa v pomnilniku.
NAJVECJE_TELO_OBRAZCA = 1024 * 1024

#: Vrsta vsebine, v kateri obrazci pod `/admin` pošiljajo podatke.
OBRAZEC = "application/x-www-form-urlencoded"

SPOROCILO_BREZ_CSRF = (
    "Obrazec je potekel ali ni prišel s te strani, zato dejanja nisem izvedel. "
    "Osveži stran in poskusi znova."
)

SPOROCILO_PREVELIKO_TELO = (
    "Poslani obrazec je prevelik, zato ga nisem sprejel. Če se to ponovi, "
    "povej lastniku sistema."
)


#: Metodi, ki ne spreminjata stanja in zato CSRF žetona ne potrebujeta.
VARNE_METODE = frozenset({"GET", "HEAD"})


def _naslov_prijave(scope: Scope) -> str:
    """Naslov prijavne strani s ciljem, na katerega se uporabnica vrne.

    Cilj gre skozi `urlencode` in ne skozi `quote` s širokim `safe`: pot z
    **dvema** parametroma (`/admin/quizzes/new?subject=MAT&vstop=rocna`) bi se
    ob neubeženem `&` pri razčlenitvi prijavne strani odrezala pri prvem od
    njiju in uporabnica bi pristala na drugem zaslonu, ne le brez parametra.

    **Cilj dobi samo varna metoda.** Pot, ki obstaja le kot `POST`, po prijavi
    z `GET` vrne 404, vsebine obrazca pa vrnitev tako ali tako ne obnovi; zato
    gre `POST` brez seje na `/admin`.
    """
    if scope["method"] not in VARNE_METODE:
        return prijava.POT_PRIJAVE
    pot = scope["path"]
    poizvedba = scope.get("query_string", b"").decode("latin-1")
    cilj = f"{pot}?{poizvedba}" if poizvedba else pot
    return f"{prijava.POT_PRIJAVE}?{urlencode({'next': cilj})}"


class SejaMiddleware:
    """Zahteva veljavno sejo za vsako pot pod `/admin` in CSRF žeton za vsako
    metodo, ki ni `GET` ali `HEAD`.

    Kaj plast naredi, po vrsti:

    1. Poti zunaj `/admin` spusti nedotaknjene — telefon te plasti ne sreča.
    2. Brez veljavne seje **starša** odgovori s `303` na prijavo in `next`. Ne
       `401`: odgovor gleda človek v brskalniku, ne program. Otrokova seja tu
       velja za odsotno; glej `prijava.vloga_sodi` za razlog, zakaj vrata ne
       zadoščajo samo ob prijavi.
    3. Z veljavno sejo jo poda naprej v `scope["state"]["prijava"]`, da je
       usmerjevalniki ne berejo še enkrat.
    4. Pri nevarni metodi prebere telo, primerja CSRF žeton s tistim iz vrstice
       seje in telo **vrne nazaj** v tok, da ga endpoint prebere kot običajno.
       Zato ta plast telo bere — drugače CSRF brez odvisnosti v vsakem
       endpointu ne gre (`docs/odlocitve/ADR-035` D).

    Danes je edina nevarna metoda pod `/admin` `POST`. Pravilo je kljub temu
    napisano kot „vse razen varnih": `V3-R06` bo dodajal akcije, in plast, ki
    bi naštevala metode, bi novo spustila brez žetona.
    """

    def __init__(
        self,
        app: ASGIApp,
        predpona: str = "/admin",
        izvzete_poti: frozenset[str] = frozenset(),
    ) -> None:
        self.app = app
        self.predpona = predpona
        self.izvzete_poti = izvzete_poti

    def _je_pod_predpono(self, pot: str) -> bool:
        return pot == self.predpona or pot.startswith(f"{self.predpona}/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._je_pod_predpono(scope["path"]):
            await self.app(scope, receive, send)
            return
        if scope["path"] in self.izvzete_poti:
            await self.app(scope, receive, send)
            return

        zahteva = Request(scope)
        seja = _razresi_sejo(scope, zahteva.cookies.get(prijava.PISKOTEK_SEJE))

        # Vrata se preverijo tudi tu, ne le ob prijavi: od V3-R04 otrokove
        # seje obstajajo, in njen žeton, prilepljen v piškotek `seja`, bi brez
        # te vrstice odprl celoten `/admin` (`prijava.vloga_sodi`).
        if seja is not None and not prijava.vloga_sodi(seja.role, prijava.Vrata.ADMIN):
            seja = None

        if seja is None:
            odgovor = RedirectResponse(_naslov_prijave(scope), status_code=303)
            await self._odgovori(odgovor, scope, receive, send)
            return

        scope.setdefault("state", {})["prijava"] = seja

        if scope["method"] in VARNE_METODE:
            await self.app(scope, receive, send)
            return

        telo = await _preberi_telo(receive)
        if telo is None:
            await self._napaka(SPOROCILO_PREVELIKO_TELO, scope, receive, send, 413)
            return
        if not prijava.zetona_se_ujemata(_csrf_iz_telesa(zahteva.headers, telo), seja.csrf_token):
            await self._napaka(SPOROCILO_BREZ_CSRF, scope, receive, send, 403)
            return

        await self.app(scope, _ponovi_telo(telo), send)

    async def _napaka(
        self, sporocilo: str, scope: Scope, receive: Receive, send: Send, koda: int
    ) -> None:
        """Napako izriše kot stran, ne kot JSON — bralec je človek."""
        predloge = scope["app"].state.predloge
        odgovor = predloge.TemplateResponse(
            Request(scope, receive),
            "najdena-ni.html",
            {"naslov": "Tega nisem izvedel", "sporocilo": sporocilo},
            status_code=koda,
        )
        await self._odgovori(odgovor, scope, receive, send)

    async def _odgovori(
        self, odgovor: Response, scope: Scope, receive: Receive, send: Send
    ) -> None:
        await odgovor(scope, receive, send)


async def _preberi_telo(receive: Receive) -> bytes | None:
    """Prebere celo telo zahteve, ali `None`, kadar preseže mejo."""
    deli: list[bytes] = []
    velikost = 0
    while True:
        sporocilo: Message = await receive()
        if sporocilo["type"] != "http.request":
            break
        del_telesa = sporocilo.get("body", b"")
        velikost += len(del_telesa)
        if velikost > NAJVECJE_TELO_OBRAZCA:
            return None
        deli.append(del_telesa)
        if not sporocilo.get("more_body", False):
            break
    return b"".join(deli)


def _ponovi_telo(telo: bytes) -> Receive:
    """Tok, ki prebrano telo poda naprej endpointu."""

    poslano = False

    async def receive() -> Message:
        nonlocal poslano
        if poslano:
            return {"type": "http.disconnect"}
        poslano = True
        return {"type": "http.request", "body": telo, "more_body": False}

    return receive


def _csrf_iz_telesa(glave: Headers, telo: bytes) -> str | None:
    """CSRF žeton iz obrazca, ali `None`.

    Prizna izključno `application/x-www-form-urlencoded`. Vsak `POST` pod
    `/admin` je tak obrazec; karkoli drugega (JSON, `multipart`) tu ne nastane
    in se zato ne poskuša razčleniti — molk je zavrnitev, ne izjema.
    """
    if glave.get("content-type", "").split(";")[0].strip() != OBRAZEC:
        return None
    polja = parse_qs(telo.decode("utf-8", errors="replace"))
    vrednosti = polja.get(prijava.POLJE_CSRF, [])
    return vrednosti[0] if vrednosti else None
