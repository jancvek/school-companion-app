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
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.db import IzidObdelave, MaterialsRepository, VprasanjeZaZapis
from app.models import STATUS_NAPAKA, STATUS_PRIPRAVLJEN
from app.storage import je_znotraj
from app.vision import Klicalec, NapakaObdelave

dnevnik = logging.getLogger(__name__)


def obdelaj_cakajoce(
    tovarna_sej: sessionmaker[Session], klicalec: Klicalec, images_dir: Path
) -> int:
    """Obdela vse zapise, ki čakajo; vrne, koliko jih je obdelala.

    Zaporedno, enega za drugim — pri obsegu 5-25 slik na teden vzporednost ne
    prinese ničesar, prinese pa več načinov, kako se lahko kaj zalomi.

    **Napaka pri enem zapisu ne sme ustaviti ostalih.** Zato je vsak zapis v
    svojem `try`; zanka nad njimi teče naprej tudi ob nepričakovani izjemi.
    """
    with tovarna_sej() as seja:
        cakajoci = [material.id for material in MaterialsRepository(seja).seznam_novih()]

    obdelanih = 0
    for material_id in cakajoci:
        try:
            if obdelaj_zapis(tovarna_sej, klicalec, images_dir, material_id):
                obdelanih += 1
        except Exception:
            # Sem pridemo samo, če je odpovedalo že samo zapisovanje izida.
            # Zapis smo takrat že poskusili sprostiti; tu ostane še to, da
            # obdelava teče naprej za naslednje slike.
            dnevnik.exception("Obdelava zapisa %s je nepričakovano odpovedala.", material_id)

    return obdelanih


def obdelaj_zapis(
    tovarna_sej: sessionmaker[Session],
    klicalec: Klicalec,
    images_dir: Path,
    material_id: str,
) -> bool:
    """Obdela en zapis; vrne, ali ga je ta klic res prevzel in dokončal.

    `False` pomeni, da zapis ni bil na voljo — bodisi ga je medtem prevzel kdo
    drug, bodisi ni več v stanju `new`. To ni napaka.
    """
    with tovarna_sej() as seja:
        repozitorij = MaterialsRepository(seja)
        if not repozitorij.prevzemi_za_obdelavo(material_id):
            return False

        material = repozitorij.poisci(material_id)
        if material is None:
            # Zapis je nekdo izbrisal med prevzemom in branjem. Brisati ni
            # česa in pisati ni kam.
            return False

        pot = Path(material.image_path)

    izid = _izid_za(klicalec, images_dir, pot, material_id)

    try:
        with tovarna_sej() as seja:
            MaterialsRepository(seja).zapisi_izid(material_id, izid)
    except Exception:
        # Zapis je prevzet, izida pa ni kam zapisati. Brez tega bi ostal v
        # `processing` do naslednjega zagona strežnika.
        _sprosti(tovarna_sej, material_id)
        raise

    return True


def _izid_za(
    klicalec: Klicalec, images_dir: Path, pot: Path, material_id: str
) -> IzidObdelave:
    """Kaj se zapiše za ta zapis — uspeh ali napaka. Sam nikoli ne vrže."""
    # Preverba pred klicem: za sliko, ki je ni, ne plačamo. Meja `images_dir`
    # je ista kot pri streženju slike na admin strani — pot je zapisala naša
    # koda, a je cena preverbe ena vrstica (`app/storage.py`).
    if not je_znotraj(images_dir, pot) or not pot.is_file():
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
            # Prompt je konstanta in ne pride iz odgovora, zato ga ob napaki
            # ni od kod vzeti; ostalo sled napaka nosi s sabo, kolikor je je
            # do takrat nastalo.
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


def _sprosti(tovarna_sej: sessionmaker[Session], material_id: str) -> None:
    """Zasilna vrnitev prevzetega zapisa v vrsto. Napake požre.

    Pospravljanje za drugo napako je ne sme prekriti — isto pravilo kot pri
    `pobrisi_sliko` v `app/storage.py`.
    """
    try:
        with tovarna_sej() as seja:
            MaterialsRepository(seja).sprosti_prevzem(material_id)
    except Exception:
        dnevnik.exception(
            "Zapisa %s ni bilo mogoče vrniti v vrsto; ostal bo v obdelavi do "
            "ponovnega zagona strežnika.",
            material_id,
        )
