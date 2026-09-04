"""Preverba API ključa.

Zakaj vmesna plast (ASGI middleware) in ne odvisnost na endpointu: FastAPI
telo zahteve prebere, *preden* razreši odvisnosti. Preverba ključa kot
odvisnost bi torej pomenila, da strežnik celo večmegabajtno sliko najprej
prebere in šele nato ugotovi, da ključ ne velja. Vmesna plast zavrne zahtevo,
preden se telo sploh začne brati — kar je tudi edini način, da drži zahteva
„401, brez zapisa v bazo in brez datoteke".
"""

import secrets

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

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
    """
    if ponujeni is None:
        return False
    return secrets.compare_digest(ponujeni.encode("utf-8"), pricakovani.encode("utf-8"))


class ApiKeyMiddleware:
    """Zavrne vsako zahtevo brez veljavnega ključa, razen na izvzetih poteh."""

    def __init__(self, app: ASGIApp, api_key: str, izvzete_poti: frozenset[str]) -> None:
        self.app = app
        self.api_key = api_key
        self.izvzete_poti = izvzete_poti

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.izvzete_poti:
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
