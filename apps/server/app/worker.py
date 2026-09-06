"""Zanka, ki v presledkih poganja obdelavo.

Tanka lupina okoli `app/obdelava.py`: tu so časovnik, zagon in ustavitev, tam
je vse, kar se z zapisom v resnici zgodi. Poslovne logike v tej datoteki ni.

Opravilo teče v procesu `api` in ne v svojem vsebniku — `docs/00-namen.md`:
*„Kar bi lahko bila mikrostoritev, naj bo funkcija."* Pri obsegu 5-25 slik na
teden Celery in Redis ne rešita nobene težave, ki bi jo ta projekt imel.

Samo delo teče v niti (`asyncio.to_thread`), ker sta SQLAlchemy in odjemalec
OpenAI sinhrona; brez tega bi en klic za sto sekund ustavil celoten strežnik.
"""

import asyncio
import contextlib
import logging
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.db import MaterialsRepository
from app.obdelava import obdelaj_cakajoce
from app.vision import Klicalec

dnevnik = logging.getLogger(__name__)


def obnovi_obticale(tovarna_sej: sessionmaker[Session]) -> int:
    """Zapise, ki so obtičali v `processing`, vrne v `new`; vrne, koliko.

    Kliče se **ob zagonu, preden zanka steče**. Takrat noben zapis ni v
    resnični obdelavi, zato je vsak `processing` ostanek strežnika, ki se je
    ustavil sredi klica. Brez tega ga ne bi pobral nihče več.

    **Znana omejitev:** ta sklep drži, dokler teče en sam proces `api`. Če bi
    kdo dodal `uvicorn --workers`, bi zagon drugega procesa vrnil v `new` prav
    tiste zapise, ki jih prvi ta hip obdeluje, in slika bi bila plačana
    dvakrat. Pogojni prevzem (`prevzemi_za_obdelavo`) tega ne prepreči, ker
    gre za dva zaporedna, vsak zase veljavna prehoda. Zato je obdelava v
    ozadju vezana na en proces; glej `docs/01-arhitektura.md`.
    """
    with tovarna_sej() as seja:
        koliko = MaterialsRepository(seja).obnovi_obticale()

    if koliko:
        dnevnik.warning(
            "Ob zagonu je bilo %d zapisov v obdelavi; vrnjeni so v vrsto. "
            "Strežnik se je verjetno ustavil med klicem modela.",
            koliko,
        )
    return koliko


class Obdelovalec:
    """Opravilo v ozadju, ki v presledkih obdela, kar čaka.

    Ustavitev teče prek dogodka in ne prek preklica: preklic med `to_thread`
    ne prekine niti, ki že teče, dogodek pa poskrbi, da se zanka po koncu
    trenutnega obhoda ne uspava znova. Isti dogodek gre v `obdelaj_cakajoce`,
    ki ga pogleda med zapisi — zaustavitev zato ne čaka ne celega razmika ne
    cele serije, ampak kvečjemu en klic modela, ki je že v teku.
    """

    def __init__(
        self,
        tovarna_sej: sessionmaker[Session],
        klicalec: Klicalec,
        images_dir: Path,
        interval: float,
    ) -> None:
        self._tovarna_sej = tovarna_sej
        self._klicalec = klicalec
        self._images_dir = images_dir
        self._interval = interval
        self._ustavi = asyncio.Event()
        self._opravilo: asyncio.Task[None] | None = None

    def zazeni(self) -> None:
        """Zažene zanko. Pred njo obnovi zapise, ki so obtičali."""
        obnovi_obticale(self._tovarna_sej)
        self._ustavi.clear()
        self._opravilo = asyncio.create_task(self._zanka(), name="obdelava")
        # `%g` in ne `%.0f`: razmik pod sekundo (v testih) bi se sicer izpisal
        # kot „0 s" in dnevnik bi trdil nekaj, kar ni res.
        dnevnik.info("Obdelava slik teče; razmik med obhodi je %g s.", self._interval)

    async def ustavi(self) -> None:
        """Počaka, da se tekoči obhod izteče, in ustavi zanko."""
        if self._opravilo is None:
            return

        self._ustavi.set()
        with contextlib.suppress(asyncio.CancelledError):
            await self._opravilo
        self._opravilo = None
        dnevnik.info("Obdelava slik je ustavljena.")

    async def en_obhod(self) -> int:
        """En obhod obdelave. Ločen zato, da se da preizkusiti brez časovnika.

        Obdelavi podamo dogodek ustavitve: obhod ga preveri med zapisi in se
        ustavi, namesto da bi zaustavitev strežnika čakala celo serijo.
        """
        return await asyncio.to_thread(
            obdelaj_cakajoce,
            self._tovarna_sej,
            self._klicalec,
            self._images_dir,
            self._ustavi.is_set,
        )

    async def _zanka(self) -> None:
        while not self._ustavi.is_set():
            try:
                await self.en_obhod()
            except Exception:
                # `obdelaj_cakajoce` napake posameznih zapisov lovi sam; sem
                # pride le kaj hujšega (npr. nedosegljiva baza). Tudi takrat
                # zanka ne sme umreti — sicer bi obdelava tiho zamrla do
                # ponovnega zagona strežnika, in tega nihče ne bi opazil.
                dnevnik.exception("Obhod obdelave je odpovedal; zanka teče naprej.")

            # Uspavanje, ki ga ustavitev prekine takoj.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._ustavi.wait(), timeout=self._interval)
