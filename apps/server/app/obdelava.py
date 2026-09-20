"""Kaj se zgodi z eno sliko: prevzem, klic modela, zapis izida.

Ta modul je **sinhron in ne ve za `asyncio`**. Zanka, ki ga poganja, je v
`app/worker.py`; tam ni poslovne logike, tu ni časovnikov. Razlog je isti kot
pri `MaterialsDatabase` na telefonu: logika mora biti testljiva brez zaganjanja
zanke in brez omrežja (odločitev 2 v `docs/plan/V1-R03.md`).

Vsak zapis dobi svojo sejo in svojo transakcijo. Prevzem in zapis izida sta
zato ločena — med njima teče klic, ki traja sekunde, in odprta transakcija čez
ta čas bi po nepotrebnem držala povezavo in zaklenjeno vrstico.
"""

import logging
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.db import DruzineRepository, IzidObdelave, MaterialsRepository, VprasanjeZaZapis
from app.models import STATUS_NAPAKA, STATUS_PRIPRAVLJEN
from app.storage import je_znotraj, mapa_druzine
from app.vision import Klicalec, NapakaObdelave

dnevnik = logging.getLogger(__name__)


def obdelaj_cakajoce(
    tovarna_sej: sessionmaker[Session],
    klicalec: Klicalec,
    images_dir: Path,
    naj_se_ustavi: Callable[[], bool] | None = None,
) -> int:
    """Obdela vse zapise, ki čakajo; vrne, koliko jih je obdelala.

    Zaporedno, enega za drugim — pri obsegu 5-25 slik na teden vzporednost ne
    prinese ničesar, prinese pa več načinov, kako se lahko kaj zalomi.

    **Napaka pri enem zapisu ne sme ustaviti ostalih.** Zato je vsak zapis v
    svojem `try`; zanka nad njimi teče naprej tudi ob nepričakovani izjemi.

    `naj_se_ustavi` se vpraša **med** zapisi. Brez tega bi zaustavitev
    strežnika čakala celo serijo: pri dvajsetih čakajočih slikah in časovni
    omejitvi 120 s je to do štirideset minut. Zapis, ki je takrat že v teku, se
    dokonča — prekinjen klic bi bil plačan in zavržen.

    **Po družinah** (`docs/odlocitve/ADR-029` B): repozitorija brez družine
    ni, zato obhod vzame družine eno za drugo. „Najstarejši posnetek prvi"
    velja znotraj družine.

    **Ugasnjene družine obhod preskoči** (`ADR-044` D). Njene slike ostanejo
    `new` in se obdelajo, ko je družina spet prižgana; klic v OpenAI za
    družino, v katero se nihče ne more prijaviti, bi bil plačan za nič. Isti
    vzorec kot mirujoči worker brez ključa (`ADR-009` B2): odsotnost pogoja za
    delo ni napaka in ne sme proizvesti ne dela ne zapisov `failed`.
    """
    with tovarna_sej() as seja:
        druzine = DruzineRepository(seja).idji_aktivnih()

    obdelanih = 0
    for family_id in druzine:
        with tovarna_sej() as seja:
            cakajoci = [
                material.id for material in MaterialsRepository(seja, family_id).seznam_novih()
            ]

        for zaporedje, material_id in enumerate(cakajoci):
            if naj_se_ustavi is not None and naj_se_ustavi():
                dnevnik.info(
                    "Obdelava se ustavlja; %d zapisov družine %s ostaja v vrsti "
                    "za naslednji zagon.",
                    len(cakajoci) - zaporedje,
                    family_id,
                )
                return obdelanih

            try:
                if obdelaj_zapis(tovarna_sej, klicalec, images_dir, family_id, material_id):
                    obdelanih += 1
            except Exception:
                dnevnik.exception(
                    "Obdelava zapisa %s je nepričakovano odpovedala.", material_id
                )

    return obdelanih


def obdelaj_zapis(
    tovarna_sej: sessionmaker[Session],
    klicalec: Klicalec,
    images_dir: Path,
    family_id: str,
    material_id: str,
) -> bool:
    """Obdela en zapis družine; vrne, ali ga je ta klic res prevzel in dokončal.

    `images_dir` je koren; meja slike je mapa družine (`mapa_druzine`).

    `False` pomeni, da zapis ni bil na voljo — bodisi ga je medtem prevzel kdo
    drug, bodisi ni več v stanju `new`. To ni napaka.
    """
    with tovarna_sej() as seja:
        if not MaterialsRepository(seja, family_id).prevzemi_za_obdelavo(material_id):
            return False

    # **Vse od prevzema naprej je v enem `try`.** Od trenutka, ko je zapis
    # `processing`, ga mora vsaka pot izvedbe od tam tudi spraviti — sicer bi
    # obtičal do naslednjega zagona strežnika, kriterij pa pravi, da tam ne
    # obtiči. `_izid_za` je pisan tako, da napak klicalca ne spusti naprej, a
    # „pisan tako" ni jamstvo: `Path.is_file` pri zavrnjenem dostopu do mape
    # vrže `PermissionError`, odpoved baze pa lahko podre tudi branje zapisa
    # ali zapis izida.
    try:
        with tovarna_sej() as seja:
            material = MaterialsRepository(seja, family_id).poisci(material_id)
            if material is None:
                # Zapis je nekdo izbrisal med prevzemom in branjem. Sprostiti
                # ni česa in pisati ni kam.
                return False
            pot = Path(material.image_path)

        izid = _izid_za(klicalec, mapa_druzine(images_dir, family_id), pot, material_id)

        with tovarna_sej() as seja:
            MaterialsRepository(seja, family_id).zapisi_izid(material_id, izid)
    except Exception:
        _sprosti(tovarna_sej, family_id, material_id)
        raise

    return True


def _izid_za(
    klicalec: Klicalec, mapa_slik: Path, pot: Path, material_id: str
) -> IzidObdelave:
    """Kaj se zapiše za ta zapis — uspeh ali napaka.

    Napake klicalca ujame vse in jih pretvori v izid. Ne jamči pa, da ne vrže
    nikoli: dostop do datotečnega sistema (`is_file`) zna vreči `PermissionError`
    in ta gre naprej. Zato je klic te funkcije pri klicatelju v `try`, ki
    prevzem sprosti.
    """
    # Preverba pred klicem: za sliko, ki je ni, ne plačamo. Meja `images_dir`
    # je ista kot pri streženju slike na admin strani — pot je zapisala naša
    # koda, a je cena preverbe ena vrstica (`app/storage.py`).
    if not je_znotraj(mapa_slik, pot) or not pot.is_file():
        dnevnik.error("Slike zapisa %s ni na disku: %s", material_id, pot)
        return IzidObdelave(
            status=STATUS_NAPAKA,
            error=(
                "Slike ni na disku strežnika, zato obdelava ni bila mogoča. "
                "Zapis je smiselno izbrisati."
            ),
        )

    try:
        klic = klicalec(pot)
    except NapakaObdelave as napaka:
        dnevnik.warning("Obdelava zapisa %s ni uspela: %s", material_id, napaka.sporocilo)
        return IzidObdelave(
            status=STATUS_NAPAKA,
            # Sled se zapiše tudi tu. Kriterij V1-R03 zahteva prompt, surov
            # odgovor, ime modela in porabo ob **vsakem** izidu — in prav pri
            # napaki („model je vrnil neveljaven JSON") je vprašanje „kaj smo
            # mu poslali" glavno. Napaka nosi s sabo toliko sledi, kolikor je
            # je do nje nastalo.
            prompt=napaka.prompt,
            raw_response=napaka.raw_response,
            model=napaka.model,
            input_tokens=napaka.input_tokens,
            output_tokens=napaka.output_tokens,
            error=napaka.sporocilo,
        )
    except Exception as napaka:
        # Nepričakovana izjema iz klicalca. Zapis gre v `failed` z berljivim
        # sporočilom; podrobnosti so v dnevniku, ne na strani.
        dnevnik.exception("Nepričakovana napaka pri obdelavi zapisa %s.", material_id)
        return IzidObdelave(
            status=STATUS_NAPAKA,
            error=(
                "Pri klicu vision modela je prišlo do nepričakovane napake "
                f"({type(napaka).__name__}). Podrobnosti so v dnevniku strežnika."
            ),
        )

    return IzidObdelave(
        # `ready` tudi pri neberljivi sliki: klic je uspel in bil plačan, torej
        # to ni napaka obdelave. Razliko nosi `readable`.
        status=STATUS_PRIPRAVLJEN,
        readable=klic.vsebina.readable,
        transcript=klic.vsebina.transcript,
        summary=klic.vsebina.summary,
        prompt=klic.prompt,
        raw_response=klic.raw_response,
        model=klic.model,
        input_tokens=klic.input_tokens,
        output_tokens=klic.output_tokens,
        vprasanja=tuple(
            VprasanjeZaZapis(question=vprasanje.question, answer=vprasanje.answer)
            for vprasanje in klic.vsebina.questions
        ),
    )


def _sprosti(tovarna_sej: sessionmaker[Session], family_id: str, material_id: str) -> None:
    """Zasilna vrnitev prevzetega zapisa v vrsto. Napake požre.

    Pospravljanje za drugo napako je ne sme prekriti — isto pravilo kot pri
    `pobrisi_sliko` v `app/storage.py`.
    """
    try:
        with tovarna_sej() as seja:
            MaterialsRepository(seja, family_id).sprosti_prevzem(material_id)
    except Exception:
        dnevnik.exception(
            "Zapisa %s ni bilo mogoče vrniti v vrsto; ostal bo v obdelavi do "
            "ponovnega zagona strežnika.",
            material_id,
        )
