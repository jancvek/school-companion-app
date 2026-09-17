"""Dve preverbi ob vhodu: API ključ (telefon) in seja s CSRF (admin stran).

Zakaj vmesni plasti (ASGI middleware) in ne odvisnosti na endpointu:

- **Ključ:** FastAPI telo zahteve prebere, *preden* razreši odvisnosti.
  Preverba ključa kot odvisnost bi torej pomenila, da strežnik celo
  večmegabajtno sliko najprej prebere in šele nato ugotovi, da ključ ne velja.
  Vmesna plast zavrne zahtevo, preden se telo sploh začne brati — kar je tudi
  edini način, da drži zahteva „401, brez zapisa v bazo in brez datoteke".
- **Seja:** odvisnost je mogoče pozabiti pri novem usmerjevalniku, predpone pa
  ne. Pot pod `/admin`, ki je nihče ni dodal na noben seznam, je varovana po
  privzetku (`docs/odlocitve/ADR-035` A). Generirani test dosegljivosti
  pozabljeno pot sicer ujame, a koda, ki napake ne dopusti, je boljša od testa,
  ki jo prijavi.
"""

import secrets
from datetime import UTC, datetime
from urllib.parse import parse_qs, quote

from sqlalchemy.orm import Session, sessionmaker
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import prijava
from app.db import PrijavaRepository

#: Glava, v kateri telefon pošlje ključ.
API_KEY_HEADER = "x-api-key"

SPOROCILO_NEVELJAVEN_KLJUC = (
    "Neveljaven ali manjkajoč API ključ. Preveri nastavitev SERVER_API_KEY v aplikaciji."
)


def kljuc_se_ujema(ponujeni: str | None, pricakovani: str) -> bool:
    """Primerja ključa v konstantnem času.

    `compare_digest` nad nizom zahteva same znake ASCII in ob drugačnem vnosu
    vrže `TypeError`, zato primerjamo bajte — ključ iz glave je poljuben vnos
    od zunaj in ne sme sesuti strežnika.

    Prazen pričakovani ključ ne velja nikoli. `compare_digest(b"", b"")` sicer
    vrne `True`, kar bi pomenilo strežnik, odprt vsakomur, ki pošlje prazno
    glavo. `Settings` tak ključ zavrne že ob zagonu; ta vrstica je druga
    ograja, za primer, ko bi kdo plast nastavitev obšel.
    """
    if ponujeni is None or not pricakovani:
        return False
    return secrets.compare_digest(ponujeni.encode("utf-8"), pricakovani.encode("utf-8"))


def je_izvzeta(pot: str, poti: frozenset[str], predpone: frozenset[str]) -> bool:
    """Ali je pot izvzeta iz preverbe ključa.

    Predpona se ujame samo na sami sebi in na tem, kar ji sledi za poševnico:
    `/admin` in `/admin/karkoli`, **ne** pa `/administration`. Golo
    `startswith("/admin")` bi izvzelo vsako pot, ki se slučajno začne enako —
    in tako izvzetje bi bilo videti pravilno vse do dneva, ko nastane pot s
    podobnim imenom (odločitev 6 v `docs/plan/V1-R04.md`).
    """
    if pot in poti:
        return True
    return any(pot == predpona or pot.startswith(f"{predpona}/") for predpona in predpone)


class ApiKeyMiddleware:
    """Zavrne vsako zahtevo brez veljavnega ključa, razen na izvzetih poteh."""

    def __init__(
        self,
        app: ASGIApp,
        api_key: str,
        izvzete_poti: frozenset[str],
        izvzete_predpone: frozenset[str] = frozenset(),
    ) -> None:
        self.app = app
        self.api_key = api_key
        self.izvzete_poti = izvzete_poti
        self.izvzete_predpone = izvzete_predpone

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or je_izvzeta(
            scope["path"], self.izvzete_poti, self.izvzete_predpone
        ):
            await self.app(scope, receive, send)
            return

        ponujeni = Headers(scope=scope).get(API_KEY_HEADER)
        if not kljuc_se_ujema(ponujeni, self.api_key):
            odgovor = JSONResponse(
                {"detail": SPOROCILO_NEVELJAVEN_KLJUC},
                status_code=401,
            )
            await odgovor(scope, receive, send)
            return

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


def _cilj_po_prijavi(scope: Scope) -> str:
    """Pot z nizom poizvedbe, na katero se uporabnica po prijavi vrne."""
    pot = scope["path"]
    poizvedba = scope.get("query_string", b"").decode("latin-1")
    return f"{pot}?{poizvedba}" if poizvedba else pot


class SejaMiddleware:
    """Zahteva veljavno sejo za vsako pot pod `/admin` in CSRF žeton za `POST`.

    Kaj plast naredi, po vrsti:

    1. Poti zunaj `/admin` spusti nedotaknjene — telefon te plasti ne sreča.
    2. Brez veljavne seje odgovori s `303` na prijavo in `next`. Ne `401`:
       odgovor gleda človek v brskalniku, ne program.
    3. Z veljavno sejo jo poda naprej v `scope["state"]["prijava"]`, da je
       usmerjevalniki ne berejo še enkrat.
    4. Pri `POST` prebere telo, primerja CSRF žeton s tistim iz vrstice seje in
       telo **vrne nazaj** v tok, da ga endpoint prebere kot običajno. Zato ta
       plast telo bere — drugače CSRF brez odvisnosti v vsakem endpointu ne gre
       (`docs/odlocitve/ADR-035` D).
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
        tovarna: sessionmaker[Session] = scope["app"].state.tovarna_sej
        with tovarna() as seja_baze:
            seja = prijava.seja_za_zeton(
                PrijavaRepository(seja_baze),
                zahteva.cookies.get(prijava.PISKOTEK_SEJE),
                datetime.now(UTC),
            )

        if seja is None:
            odgovor = RedirectResponse(
                f"{prijava.POT_PRIJAVE}?next={quote(_cilj_po_prijavi(scope), safe='/?=&')}",
                status_code=303,
            )
            await self._odgovori(odgovor, scope, receive, send)
            return

        scope.setdefault("state", {})["prijava"] = seja

        if scope["method"] != "POST":
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
