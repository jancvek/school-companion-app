"""Poti za reševanje kviza na telefonu (V2-R02).

Svoj usmerjevalnik in ne del `kvizi.py`: tam je operaterska stran pod `/admin`
(brskalnik, brez ključa, HTML), tu pa drug odjemalec z drugo mejo — telefon,
ki pošlje API ključ in pričakuje JSON. Poti niso pod `/admin`, zato jih vmesna
plast za ključ varuje sama; izvzetje (`ADR-006`) se ne širi.

Vzorec je isti kot pri arhivu (`docs/odlocitve/ADR-011`): telefon dobi
**celoten delovni seznam**, brez kazalca, in pošlje paket dogodkov, ki je
idempotenten po `id`.
"""

from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.casi import utc
from app.db import KviziRepository, PoskusZaZapis
from app.dependencies import daj_repozitorij_kvizov
from app.schemas import (
    CakajociKvizi,
    KvizZaTelefonOblika,
    PaketPoskusov,
    PoskusiZapisani,
    PostavkaZaTelefon,
)

router = APIRouter()

#: Sporočilo ob poskusu za postavko, ki je ni. Nastane lahko samo ob napaki v
#: kodi — postavke se ne brišejo —, zato pove, kaj je narobe, in ne ponuja
#: dejanja, ki ga uporabnica ne more narediti.
SPOROCILO_NEZNANA_POSTAVKA = (
    "Poskus se nanaša na vprašanje kviza, ki ga na strežniku ni. "
    "Nič od paketa ni zapisano; telefon ga obdrži in poskusi znova."
)


@router.get("/quizzes/pending", response_model=CakajociKvizi)
def cakajoci_kvizi(
    repozitorij: Annotated[KviziRepository, Depends(daj_repozitorij_kvizov)],
) -> CakajociKvizi:
    """Kvizi, ki čakajo na reševanje, s celotno zamrznjeno vsebino.

    Samo nepreklicani in nerešeni. Splošne sinhronizacije vprašanj ni: telefon
    dobi kviz kot zaprt objekt (`ADR-016`, posledice).
    """
    return CakajociKvizi(
        quizzes=[
            KvizZaTelefonOblika(
                id=cakajoc.kviz.id,
                name=cakajoc.kviz.name,
                created_at=utc(cakajoc.kviz.created_at),
                items=[
                    PostavkaZaTelefon(
                        id=postavka.id,
                        position=postavka.position,
                        question=postavka.question_text,
                        answer=postavka.answer_text,
                        answered=postavka.id in cakajoc.odgovorjene,
                    )
                    for postavka in cakajoc.kviz.postavke
                ],
            )
            for cakajoc in repozitorij.seznam_za_telefon()
        ]
    )


@router.post("/quiz-attempts", response_model=PoskusiZapisani)
def zapisi_poskuse(
    telo: PaketPoskusov,
    repozitorij: Annotated[KviziRepository, Depends(daj_repozitorij_kvizov)],
) -> PoskusiZapisani:
    """Sprejme paket poskusov; idempotentno po `id`, prvi poskus postavke zmaga.

    Ponovljen paket in drugi poskus za isto postavko nista napaka — odgovor je
    `200` s številom res zapisanih. Telefon oboje šteje za uspeh, sicer bi po
    `ADR-004` obtičal v stanju, iz katerega ga nič ne vrne
    (`docs/odlocitve/ADR-019` E).
    """
    zapisani = repozitorij.zapisi_poskuse(
        [
            PoskusZaZapis(
                id=str(poskus.id),
                quiz_item_id=str(poskus.quiz_item_id),
                mode=poskus.mode,
                rating=poskus.rating,
                shown_at=poskus.shown_at.astimezone(UTC),
                revealed_at=poskus.revealed_at.astimezone(UTC),
                answered_at=poskus.answered_at.astimezone(UTC),
            )
            for poskus in telo.attempts
        ]
    )
    if zapisani is None:
        raise HTTPException(status_code=422, detail=SPOROCILO_NEZNANA_POSTAVKA)

    return PoskusiZapisani(recorded=zapisani)
