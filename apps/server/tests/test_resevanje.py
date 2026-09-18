"""Testi poti za telefon: `GET /quizzes/pending` in `POST /quiz-attempts` (V2-R02).

Pokrivajo razdelek „Strežnik" v tabeli „Test casi" iz `docs/plan/V2-R02.md`.

Kvizi nastanejo neposredno v bazi, kjer test zanima samo reševanje; prek
sestavljalnika samo tam, kjer je pomembno, da je besedilo res zamrznjeno.
"""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models import OCENE, Question, QuestionAttempt, Quiz
from app.models import QuizItem as Postavka
from app.schemas import NAJVEC_POSKUSOV
from tests.conftest import CVEK_ID, SejaTesta
from tests.test_kvizi import UUID_ENA, objavi, snov

#: Trenutek, ko je bilo prvo vprašanje pokazano. Razmiki do razkritja in ocene
#: so različni, da test loči tri žige med sabo.
POKAZANO = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)
RAZKRITO = POKAZANO + timedelta(seconds=7)
OCENJENO = POKAZANO + timedelta(seconds=9)


def kviz(
    motor: Engine,
    *,
    postavk: int = 3,
    preklican: bool = False,
    ustvarjen: datetime | None = None,
) -> tuple[str, list[str]]:
    """Objavljen kviz z danim številom postavk; vrne `id` kviza in postavk."""
    quiz_id = str(uuid4())
    idji = [str(uuid4()) for _ in range(postavk)]
    with Session(motor) as seja:
        nov = Quiz(
            family_id=CVEK_ID,
            id=quiz_id,
            name="MAT — 10. 9. 2026",
            subject="MAT",
            created_at=ustvarjen or datetime(2026, 9, 10, 8, 0, tzinfo=UTC),
            canceled_at=datetime(2026, 9, 10, 9, 0, tzinfo=UTC) if preklican else None,
        )
        nov.postavke = [
            Postavka(
                id=postavka_id,
                position=zaporedje,
                question_text=f"Vprašanje {zaporedje}?",
                answer_text=f"Odgovor {zaporedje}.",
            )
            for zaporedje, postavka_id in enumerate(idji, start=1)
        ]
        seja.add(nov)
        seja.commit()
    return quiz_id, idji


def poskus(quiz_item_id: str, **polja: Any) -> dict[str, Any]:
    """En veljaven poskus v obliki, kot ga pošlje telefon."""
    return {
        "id": str(uuid4()),
        "quiz_item_id": quiz_item_id,
        "mode": "samoocena",
        "rating": "srednje",
        "shown_at": POKAZANO.isoformat(),
        "revealed_at": RAZKRITO.isoformat(),
        "answered_at": OCENJENO.isoformat(),
        **polja,
    }


def poslji(
    odjemalec: TestClient,
    poskusi: list[dict[str, Any]],
    telefon: SejaTesta | None = None,
) -> Any:
    """Pošlje paket poskusov z veljavnim žetonom telefona.

    `telefon` je neobvezen, ker ga nekateri klicatelji nosijo v privzetih
    glavah odjemalca (`test_tesnjenje.py`); podati ga je treba tam, kjer
    odjemalec pripada brskalniku.

    Vrne `Any` in ne `httpx.Response`: `TestClient` vrne odgovor paketa
    `httpx2`, kadar je nameščen, sicer `httpx`. Uvoz katerega koli bi zbirko
    vezal na to, kaj je slučajno v okolju (`CLAUDE.md`, ponovljivost).
    """
    return odjemalec.post(
        "/quiz-attempts",
        json={"attempts": poskusi},
        headers=telefon.glave if telefon else None,
    )


def cakajoci(odjemalec: TestClient, telefon: SejaTesta) -> list[dict[str, Any]]:
    odgovor = odjemalec.get("/quizzes/pending", headers=telefon.glave)
    assert odgovor.status_code == 200, odgovor.text
    kvizi: list[dict[str, Any]] = odgovor.json()["quizzes"]
    return kvizi


def poskusi_v_bazi(motor: Engine) -> list[QuestionAttempt]:
    with Session(motor) as seja:
        return list(seja.scalars(select(QuestionAttempt)))


def resen_ob(motor: Engine, quiz_id: str) -> datetime | None:
    with Session(motor) as seja:
        najden = seja.get(Quiz, quiz_id)
        assert najden is not None
        return najden.solved_at


def v_utc(trenutek: datetime) -> datetime:
    """SQLite vrne naiven čas; primerjamo v UTC."""
    return trenutek.replace(tzinfo=UTC) if trenutek.tzinfo is None else trenutek


class TestSeznam:
    def test_vrne_samo_nepreklicane_in_neresene(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        cakajoc, _ = kviz(motor)
        kviz(motor, preklican=True)
        resen, postavke = kviz(motor, postavk=1)
        assert poslji(odjemalec, [poskus(postavke[0])], telefon).status_code == 200

        assert [k["id"] for k in cakajoci(odjemalec, telefon)] == [cakajoc]
        assert resen_ob(motor, resen) is not None

    def test_najstarejsi_prvi(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        mlajsi, _ = kviz(motor, ustvarjen=datetime(2026, 9, 10, tzinfo=UTC))
        starejsi, _ = kviz(motor, ustvarjen=datetime(2026, 9, 8, tzinfo=UTC))

        assert [k["id"] for k in cakajoci(odjemalec, telefon)] == [starejsi, mlajsi]

    def test_nosi_celotno_vsebino_po_zaporedju(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        quiz_id, postavke = kviz(motor, postavk=3)

        [prenesen] = cakajoci(odjemalec, telefon)

        assert prenesen["id"] == quiz_id
        assert prenesen["name"] == "MAT — 10. 9. 2026"
        assert [p["id"] for p in prenesen["items"]] == postavke
        assert [p["position"] for p in prenesen["items"]] == [1, 2, 3]
        assert prenesen["items"][1]["question"] == "Vprašanje 2?"
        assert prenesen["items"][1]["answer"] == "Odgovor 2."
        assert all(p["answered"] is False for p in prenesen["items"])

    def test_cas_objave_nosi_pas(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        """SQLite vrne naiven čas; brez pasu bi ga telefon bral kot lokalnega."""
        kviz(motor, ustvarjen=datetime(2026, 9, 10, 8, 0, tzinfo=UTC))

        [prenesen] = cakajoci(odjemalec, telefon)

        prebran = datetime.fromisoformat(prenesen["created_at"])
        assert prebran.tzinfo is not None
        assert prebran == datetime(2026, 9, 10, 8, 0, tzinfo=UTC)

    def test_pove_odgovorjene_postavke(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        """`ADR-019` E: po ponovni namestitvi telefon ve, kaj naj preskoči."""
        _, postavke = kviz(motor, postavk=3)
        assert poslji(odjemalec, [poskus(postavke[0])], telefon).status_code == 200

        [prenesen] = cakajoci(odjemalec, telefon)

        assert [p["answered"] for p in prenesen["items"]] == [True, False, False]

    def test_nosi_zamrznjeno_besedilo_in_ne_vprasanja_iz_baze(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        """Vsebina pride iz postavke, ne iz `questions` (`ADR-016` E)."""
        snov(motor, slike)
        objavi(odjemalec, motor, [UUID_ENA], koliko=1)
        with Session(motor) as seja:
            vprasanje = seja.get(Question, f"{UUID_ENA}-v1")
            assert vprasanje is not None
            izvirnik = vprasanje.question
            vprasanje.question = "Spremenjeno po objavi?"
            seja.commit()

        [prenesen] = cakajoci(odjemalec, telefon)

        assert prenesen["items"][0]["question"] == izvirnik
        assert "Spremenjeno" not in str(prenesen)

    def test_prazen_seznam_ni_napaka(self, odjemalec: TestClient, telefon: SejaTesta) -> None:
        assert cakajoci(odjemalec, telefon) == []

    def test_brez_kljuca_je_401(self, odjemalec: TestClient, motor: Engine) -> None:
        kviz(motor)

        assert odjemalec.get("/quizzes/pending").status_code == 401


class TestPoskusi:
    def test_zapise_poskus_z_vsemi_polji(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        _, postavke = kviz(motor)
        poslan = poskus(postavke[0], rating="tezko")

        odgovor = poslji(odjemalec, [poslan], telefon)

        assert odgovor.status_code == 200, odgovor.text
        assert odgovor.json() == {"recorded": 1}
        [zapisan] = poskusi_v_bazi(motor)
        assert zapisan.id == poslan["id"]
        assert zapisan.quiz_item_id == postavke[0]
        assert zapisan.mode == "samoocena"
        assert zapisan.rating == "tezko"
        assert v_utc(zapisan.shown_at) == POKAZANO
        assert v_utc(zapisan.revealed_at) == RAZKRITO
        assert v_utc(zapisan.answered_at) == OCENJENO
        assert zapisan.received_at is not None

    def test_cas_v_drugem_pasu_se_zapise_v_utc(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        _, postavke = kviz(motor)

        poslji(odjemalec, [poskus(postavke[0], shown_at="2026-09-10T17:00:00+02:00")], telefon)

        [zapisan] = poskusi_v_bazi(motor)
        assert v_utc(zapisan.shown_at) == POKAZANO

    @pytest.mark.parametrize("ocena", OCENE)
    def test_sprejme_vse_stiri_ocene(
        self, odjemalec: TestClient, motor: Engine, ocena: str, telefon: SejaTesta
    ) -> None:
        _, postavke = kviz(motor, postavk=1)

        odgovor = poslji(odjemalec, [poskus(postavke[0], rating=ocena)], telefon)

        assert odgovor.status_code == 200, odgovor.text
        assert poskusi_v_bazi(motor)[0].rating == ocena

    def test_ponovljen_paket_ne_podvoji(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        """Prenos s telefona je *at-least-once* (`ADR-012`)."""
        _, postavke = kviz(motor)
        paket = [poskus(postavke[0]), poskus(postavke[1])]

        assert poslji(odjemalec, paket, telefon).json() == {"recorded": 2}
        drugic = poslji(odjemalec, paket, telefon)

        assert drugic.status_code == 200
        assert drugic.json() == {"recorded": 0}
        assert len(poskusi_v_bazi(motor)) == 2

    def test_prvi_poskus_postavke_zmaga(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        """`ADR-019` E: drugi poskus je uspeh brez zapisa, ne napaka."""
        _, postavke = kviz(motor)
        prvi = poskus(postavke[0], rating="lahko")
        drugi = poskus(postavke[0], rating="nisem_vedela")

        poslji(odjemalec, [prvi], telefon)
        odgovor = poslji(odjemalec, [drugi], telefon)

        assert odgovor.status_code == 200
        assert odgovor.json() == {"recorded": 0}
        [zapisan] = poskusi_v_bazi(motor)
        assert zapisan.id == prvi["id"]
        assert zapisan.rating == "lahko"

    def test_dvojnik_v_istem_paketu(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        _, postavke = kviz(motor)
        prvi = poskus(postavke[0])

        odgovor = poslji(odjemalec, [prvi, poskus(postavke[0])], telefon)

        assert odgovor.json() == {"recorded": 1}
        assert [p.id for p in poskusi_v_bazi(motor)] == [prvi["id"]]

    def test_prazen_paket_ni_napaka(self, odjemalec: TestClient, telefon: SejaTesta) -> None:
        odgovor = poslji(odjemalec, [], telefon)

        assert odgovor.status_code == 200
        assert odgovor.json() == {"recorded": 0}

    def test_brez_kljuca_je_401_in_nic_v_bazi(self, odjemalec: TestClient, motor: Engine) -> None:
        _, postavke = kviz(motor)

        odgovor = odjemalec.post("/quiz-attempts", json={"attempts": [poskus(postavke[0])]})

        assert odgovor.status_code == 401
        assert poskusi_v_bazi(motor) == []


class TestResenost:
    def test_delen_kviz_ni_resen(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        quiz_id, postavke = kviz(motor, postavk=3)

        poslji(odjemalec, [poskus(postavke[0]), poskus(postavke[1])], telefon)

        assert resen_ob(motor, quiz_id) is None
        assert [k["id"] for k in cakajoci(odjemalec, telefon)] == [quiz_id]

    def test_zadnja_postavka_kviz_resi(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        """Strežnik rešenost izpelje sam — v isti transakciji kot zadnji poskus."""
        quiz_id, postavke = kviz(motor, postavk=3)
        poslji(odjemalec, [poskus(postavke[0]), poskus(postavke[1])], telefon)

        poslji(odjemalec, [poskus(postavke[2])], telefon)

        resen = resen_ob(motor, quiz_id)
        assert resen is not None
        # Isti žig kot prevzem zadnjega poskusa: oboje je nastalo v eni
        # transakciji, ne v dveh zaporednih.
        zadnji_prevzem = max(v_utc(p.received_at) for p in poskusi_v_bazi(motor))
        assert v_utc(resen) == zadnji_prevzem
        assert cakajoci(odjemalec, telefon) == []

    def test_resenost_se_ne_premakne(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        quiz_id, postavke = kviz(motor, postavk=1)
        paket = [poskus(postavke[0])]
        poslji(odjemalec, paket, telefon)
        prvic = resen_ob(motor, quiz_id)

        poslji(odjemalec, paket, telefon)
        poslji(odjemalec, [poskus(postavke[0])], telefon)

        assert resen_ob(motor, quiz_id) == prvic

    def test_preklican_kviz_sprejme_poskuse(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        """`ADR-019` C: dogodek je dejstvo; zavrnjen bi na telefonu obtičal."""
        quiz_id, postavke = kviz(motor, postavk=2, preklican=True)

        odgovor = poslji(odjemalec, [poskus(postavke[0]), poskus(postavke[1])], telefon)

        assert odgovor.status_code == 200
        assert odgovor.json() == {"recorded": 2}
        # Rešenost se izpelje neodvisno od preklica; prednost je stvar prikaza.
        assert resen_ob(motor, quiz_id) is not None

    def test_poskus_enega_kviza_ne_resi_drugega(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        prvi, postavke_prvega = kviz(motor, postavk=1)
        drugi, _ = kviz(motor, postavk=1)

        poslji(odjemalec, [poskus(postavke_prvega[0])], telefon)

        assert resen_ob(motor, prvi) is not None
        assert resen_ob(motor, drugi) is None


class TestPreverbaVhoda:
    """Paket je vse ali nič: ob neveljavnem poskusu se ne zapiše nobeden."""

    @pytest.mark.parametrize(
        "polja",
        [
            {"rating": "zelo_tezko"},
            {"mode": "abc"},
            {"shown_at": "2026-09-10T08:00:00"},
            {"answered_at": "ni čas"},
            {"id": "ni-uuid"},
        ],
        ids=["ocena", "nacin", "cas-brez-pasu", "nerazberljiv-cas", "id"],
    )
    def test_neveljaven_poskus_zavrne_ves_paket(
        self, odjemalec: TestClient, motor: Engine, polja: dict[str, str], telefon: SejaTesta
    ) -> None:
        _, postavke = kviz(motor)

        odgovor = poslji(odjemalec, [poskus(postavke[0]), poskus(postavke[1], **polja)], telefon)

        assert odgovor.status_code == 422
        assert poskusi_v_bazi(motor) == []

    def test_neznana_postavka_zavrne_ves_paket(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        _, postavke = kviz(motor)

        odgovor = poslji(odjemalec, [poskus(postavke[0]), poskus(str(uuid4()))], telefon)

        assert odgovor.status_code == 422
        assert "ni" in odgovor.json()["detail"]
        assert poskusi_v_bazi(motor) == []

    def test_prevelik_paket(self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta) -> None:
        _, postavke = kviz(motor, postavk=1)

        odgovor = poslji(odjemalec, [poskus(postavke[0])] * (NAJVEC_POSKUSOV + 1), telefon)

        assert odgovor.status_code == 422
        assert poskusi_v_bazi(motor) == []


def stanje_na_pregledu(odjemalec: TestClient) -> str:
    """Besedilo stanja edinega kviza na `/admin`, brez presledkov na robu."""
    besedilo = odjemalec.get("/admin").text
    [stanje] = re.findall(r'<span class="stanje">(.*?)</span>', besedilo, re.DOTALL)
    return " ".join(stanje.split())


class TestAdmin:
    def test_resen_kviz_je_na_pregledu_resen(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        _, postavke = kviz(motor, postavk=1)
        poslji(odjemalec, [poskus(postavke[0])], telefon)

        stanje = stanje_na_pregledu(odjemalec)

        assert "rešen" in stanje
        assert "objavljen" not in stanje
        # Datum rešitve, ne le beseda.
        assert re.search(r"rešen \d{1,2}\. \d{1,2}\. \d{4}", stanje)

    def test_neresen_kviz_ostane_objavljen(self, odjemalec: TestClient, motor: Engine) -> None:
        kviz(motor)

        assert stanje_na_pregledu(odjemalec).endswith("objavljen")

    def test_preklic_prevlada_nad_resenostjo(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        quiz_id, postavke = kviz(motor, postavk=1, preklican=True)
        poslji(odjemalec, [poskus(postavke[0])], telefon)
        assert resen_ob(motor, quiz_id) is not None

        stanje = stanje_na_pregledu(odjemalec)
        stran = odjemalec.get(f"/admin/quizzes/{quiz_id}").text

        assert stanje.endswith("preklican")
        assert "rešen" not in stanje
        assert "Kviz je preklican" in stran
        assert "Kviz je rešen" not in stran

    def test_stran_kviza_pove_resenost(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        quiz_id, postavke = kviz(motor, postavk=1)
        assert "Kviz je rešen" not in odjemalec.get(f"/admin/quizzes/{quiz_id}").text

        poslji(odjemalec, [poskus(postavke[0])], telefon)

        assert "Kviz je rešen" in odjemalec.get(f"/admin/quizzes/{quiz_id}").text


def test_stevilo_kvizov_in_postavk_se_ne_spremeni(
    odjemalec: TestClient, motor: Engine, telefon: SejaTesta
) -> None:
    """Poskusi ničesar ne dodajajo ne kvizom ne postavkam — so svoja tabela."""
    _, postavke = kviz(motor, postavk=2)

    poslji(odjemalec, [poskus(p) for p in postavke], telefon)

    with Session(motor) as seja:
        assert seja.scalar(select(func.count()).select_from(Quiz)) == 1
        assert seja.scalar(select(func.count()).select_from(Postavka)) == 2
