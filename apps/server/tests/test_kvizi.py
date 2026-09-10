"""Testi sestavljalnika kvizov pod `/admin/quizzes`.

Pokrivajo tabelo „Test casi" iz `docs/plan/V2-R01.md`.

Zapisi nastanejo neposredno v bazi in ne prek `POST /materials` ali prek
obdelave: te strani berejo stanje, ne poti, po kateri je stanje nastalo — isti
razlog kot v `test_admin.py`.
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

from app.casi import dan_od_do, datum
from app.models import (
    STATUS_NAPAKA,
    STATUS_NOV,
    STATUS_PRIPRAVLJEN,
    STATUS_V_OBDELAVI,
    Material,
    Question,
    Quiz,
    QuizItem,
)
from app.routers.kvizi import (
    NAJVEC_IME,
    NAJVEC_KODA,
    PRIVZETO_STEVILO,
    VPRASANJA,
    _stevilo_z_besedo,
)
from tests.conftest import KLJUC

#: Trije stabilni identifikatorji; testi jih berejo iz izrisane strani.
UUID_ENA = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
UUID_DVA = "a1b2c3d4-e5f6-4789-abcd-ef0123456789"
UUID_TRI = "b2c3d4e5-f6a7-4890-bcde-f01234567890"


def snov(
    motor: Engine,
    slike: Path,
    material_id: str = UUID_ENA,
    *,
    subject: str = "MAT",
    taken_at: datetime | None = None,
    status: str = STATUS_PRIPRAVLJEN,
    readable: bool | None = True,
    vprasanj: int = 5,
    arhivirana: bool = False,
) -> None:
    """Ena obdelana snov s svojimi veljavnimi vprašanji.

    Privzeto je to snov, ki **gre** v kviz: `ready`, berljiva, s petimi
    veljavnimi vprašanji. Vsak test pokvari samo tisto, kar preizkuša.

    Vprašanja dobijo denormaliziran izvor (`subject`, `material_taken_at`),
    kot ga zapiše `zapisi_izid` — brez tega bi kviz po brisanju snovi ne vedel
    povedati, iz česa je vprašanje (`docs/odlocitve/ADR-012`).
    """
    kdaj = taken_at or datetime(2026, 9, 4, 7, 30, tzinfo=UTC)
    pot = slike / f"{material_id}.jpg"
    pot.write_bytes(b"slika")

    with Session(motor) as seja:
        material = Material(
            id=material_id,
            subject=subject,
            taken_at=kdaj,
            image_path=str(pot),
            status=status,
            received_at=kdaj,
            readable=readable,
            archived_at=datetime(2026, 9, 5, tzinfo=UTC) if arhivirana else None,
        )
        material.vsa_vprasanja = [
            Question(
                id=f"{material_id}-v{i}",
                position=i,
                question=f"Vprašanje {i} iz {material_id[:4]}?",
                answer=f"Odgovor {i}.",
                subject=subject,
                material_taken_at=kdaj,
            )
            for i in range(1, vprasanj + 1)
        ]
        seja.add(material)
        seja.commit()


def upokoji(motor: Engine, material_id: str = UUID_ENA) -> None:
    """Upokoji vsa veljavna vprašanja snovi, kot to naredi „Pošlji v obdelavo"."""
    with Session(motor) as seja:
        for vprasanje in seja.scalars(
            select(Question).where(
                Question.material_id == material_id, Question.retired_at.is_(None)
            )
        ):
            vprasanje.retired_at = datetime.now(UTC)
        seja.commit()


def objavi(
    odjemalec: TestClient,
    motor: Engine,
    material_ids: list[str],
    *,
    koliko: int = 3,
    subject: str | None = "MAT",
    vstop: str = "nova",
    ime: str = "",
) -> str:
    """Objavi kviz iz danih snovi in vrne `id` nastalega kviza.

    Gre skozi **oba** koraka, predogled in objavo, in ne mimo predogleda.
    To ni okrasje: vrstni red postavk nastane prav v predogledu, ki snovi
    razvrsti po `taken_at DESC`; objava potem zaporedje samo ohrani. Pomožna
    funkcija, ki bi identifikatorje pobrala iz baze in jih poslala naravnost v
    objavo, bi kviz sestavila v vrstnem redu, ki ga v vmesniku ni.
    """
    predogled = odjemalec.post(
        "/admin/quizzes/preview",
        data={
            "vstop": vstop,
            "stevilo": str(koliko),
            "snov": material_ids,
            **({"subject": subject} if subject is not None else {}),
        },
    )
    assert predogled.status_code == 200, predogled.text
    idji = re.findall(r'name="vprasanje" value="([^"]+)"', predogled.text)
    assert idji, predogled.text

    podatki: dict[str, str | list[str]] = {
        "vstop": vstop,
        "ime": ime,
        "vprasanje": idji,
    }
    if subject is not None:
        podatki["subject"] = subject

    odgovor = odjemalec.post("/admin/quizzes", data=podatki, follow_redirects=False)
    assert odgovor.status_code == 303, odgovor.text
    return odgovor.headers["location"].rsplit("/", 1)[-1]


def izbirnik(odjemalec: TestClient, vstop: str = "nova", subject: str | None = "MAT") -> str:
    """Besedilo izbirnika za dani vstop."""
    poizvedba = {"vstop": vstop}
    if subject is not None:
        poizvedba["subject"] = subject
    odgovor = odjemalec.get("/admin/quizzes/new", params=poizvedba)
    assert odgovor.status_code == 200, odgovor.text
    return odgovor.text


def je_obkljukana(besedilo: str, material_id: str) -> bool:
    """Ali je v izrisanem izbirniku okence te snovi obkljukano.

    Bere se cel element `<input>`, ne le prisotnost `checked` kjerkoli na
    strani: `checked` pri sosedu bi sicer veljal za tega.
    """
    zacetek = besedilo.index(f'value="{material_id}"')
    element = besedilo[besedilo.rindex("<input", 0, zacetek) : besedilo.index(">", zacetek)]
    return "checked" in element


def je_izbirna(besedilo: str, material_id: str) -> bool:
    """Ali ima snov v izbirniku okence (torej jo je mogoče izbrati)."""
    return f'name="snov" value="{material_id}"' in besedilo


class TestObsegSeznama:
    """Kaj izbirnik našteje pri katerem vstopu (`ADR-017` A)."""

    def test_predmetni_vstop_nasteje_vso_snov_predmeta(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Tudi tisto izpred tednov: „Nova snov" pobira zaostanek, ne dneva.
        snov(motor, slike, UUID_ENA, taken_at=datetime(2026, 8, 1, 7, tzinfo=UTC))
        snov(motor, slike, UUID_DVA, taken_at=datetime(2026, 9, 4, 7, tzinfo=UTC))

        besedilo = izbirnik(odjemalec)

        assert UUID_ENA in besedilo
        assert UUID_DVA in besedilo

    def test_predmetni_vstop_ne_nasteje_tujega_predmeta(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, subject="MAT")
        snov(motor, slike, UUID_DVA, subject="SLJ")

        besedilo = izbirnik(odjemalec, subject="MAT")

        assert UUID_ENA in besedilo
        assert UUID_DVA not in besedilo

    def test_dnevni_vstop_je_cez_vse_predmete(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zdaj = datetime.now(UTC)
        snov(motor, slike, UUID_ENA, subject="MAT", taken_at=zdaj)
        snov(motor, slike, UUID_DVA, subject="SLJ", taken_at=zdaj)
        snov(motor, slike, UUID_TRI, subject="MAT", taken_at=zdaj - timedelta(days=2))

        besedilo = izbirnik(odjemalec, vstop="danes", subject=None)

        assert UUID_ENA in besedilo
        assert UUID_DVA in besedilo
        # Predvčerajšnja snov v dnevni vstop ne sodi, čeprav je istega predmeta.
        assert UUID_TRI not in besedilo

    def test_arhivirana_snov_se_ne_pojavi(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # `ADR-016` (G): arhiv pomeni pospravljeno. Vprašanja arhiv preživijo
        # zaradi statistike, ne zato, da bi jih še kvizirali.
        snov(motor, slike, UUID_ENA, arhivirana=True)
        snov(motor, slike, UUID_DVA)

        besedilo = izbirnik(odjemalec)

        assert UUID_ENA not in besedilo
        assert UUID_DVA in besedilo

    def test_prazen_dan_odpre_izbirnik_in_pove(self, odjemalec: TestClient) -> None:
        # Ne 404 in ne preusmeritev: vstop se odpre in pove, da danes ni nič.
        odgovor = odjemalec.get("/admin/quizzes/new", params={"vstop": "danes"})

        assert odgovor.status_code == 200
        assert "Danes ni nobene posnete snovi" in odgovor.text

    def test_vstop_brez_predmeta_pove_kaj_manjka(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get("/admin/quizzes/new", params={"vstop": "nova"})

        assert odgovor.status_code == 404
        assert "izbrati predmet" in odgovor.text

    def test_neznan_vstop_da_404(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get(
            "/admin/quizzes/new", params={"vstop": "izmisljen", "subject": "MAT"}
        )

        assert odgovor.status_code == 404


class TestObkljukanje:
    """Kaj je vnaprej obkljukano."""

    def test_nova_snov_obkljuka_samo_se_neuporabljeno(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)
        snov(motor, slike, UUID_DVA)
        snov(motor, slike, UUID_TRI)
        objavi(odjemalec, motor, [UUID_ENA])

        besedilo = izbirnik(odjemalec, vstop="nova")

        # Vse tri so naštete — obseg seznama je ves predmet (`ADR-017` A).
        assert je_izbirna(besedilo, UUID_ENA)
        assert not je_obkljukana(besedilo, UUID_ENA)
        assert je_obkljukana(besedilo, UUID_DVA)
        assert je_obkljukana(besedilo, UUID_TRI)

    def test_rocna_izbira_ne_obkljuka_nicesar(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)
        snov(motor, slike, UUID_DVA)

        besedilo = izbirnik(odjemalec, vstop="rocna")

        assert je_izbirna(besedilo, UUID_ENA)
        assert not je_obkljukana(besedilo, UUID_ENA)
        assert not je_obkljukana(besedilo, UUID_DVA)

    def test_dnevni_vstop_obkljuka_vse_danasnje(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zdaj = datetime.now(UTC)
        snov(motor, slike, UUID_ENA, taken_at=zdaj)
        snov(motor, slike, UUID_DVA, subject="SLJ", taken_at=zdaj)

        besedilo = izbirnik(odjemalec, vstop="danes", subject=None)

        assert je_obkljukana(besedilo, UUID_ENA)
        assert je_obkljukana(besedilo, UUID_DVA)

    def test_preklican_kviz_vrne_snov_v_izbor(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # `ADR-016` (B): kviz je bil preklican prav zato, ker ni bil pravi.
        snov(motor, slike, UUID_ENA)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA])
        assert not je_obkljukana(izbirnik(odjemalec), UUID_ENA)

        odjemalec.post(f"/admin/quizzes/{quiz_id}/cancel", follow_redirects=False)

        assert je_obkljukana(izbirnik(odjemalec), UUID_ENA)

    def test_upokojeno_vprasanje_ne_steje_za_bilo_v_kvizu(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Ponovno obdelana snov se v „Novi snovi" spet ponudi (`ADR-017` B).

        Brez pogoja `retired_at IS NULL` v `_ze_v_kvizu` bi popravljena snov v
        privzeti izbor ne prišla nikoli in bi jo bilo treba loviti z „Ročno
        izbiro" — gumb „Pošlji v obdelavo" in kvizi bi bili uporabna vsak
        zase, skupaj pa ne.
        """
        snov(motor, slike, UUID_ENA)
        objavi(odjemalec, motor, [UUID_ENA])
        assert not je_obkljukana(izbirnik(odjemalec), UUID_ENA)

        # Ponovna obdelava: stara serija se upokoji, nastane nova.
        upokoji(motor, UUID_ENA)
        with Session(motor) as seja:
            material = seja.get(Material, UUID_ENA)
            assert material is not None
            material.vsa_vprasanja.append(
                Question(
                    id=f"{UUID_ENA}-nov1",
                    position=1,
                    question="Novo vprašanje?",
                    answer="Nov odgovor.",
                    subject="MAT",
                    material_taken_at=material.taken_at,
                )
            )
            seja.commit()

        assert je_obkljukana(izbirnik(odjemalec), UUID_ENA)


class TestNeizbirnaSnov:
    """Snov brez veljavnih vprašanj je vidna, a neizbirna, z razlogom."""

    @pytest.mark.parametrize(
        ("status", "readable", "razlog"),
        [
            (STATUS_NOV, None, "še v obdelavi"),
            (STATUS_V_OBDELAVI, None, "še v obdelavi"),
            (STATUS_NAPAKA, None, "obdelava ni uspela"),
            (STATUS_PRIPRAVLJEN, False, "slika ni berljiva"),
        ],
    )
    def test_vsak_razlog_je_zapisan(
        self,
        odjemalec: TestClient,
        motor: Engine,
        slike: Path,
        status: str,
        readable: bool | None,
        razlog: str,
    ) -> None:
        # Molčeč izpust bi pomenil kviz iz polovice dneva brez sledi, da manjka
        # pol (`ADR-016` G).
        snov(motor, slike, UUID_ENA, status=status, readable=readable, vprasanj=0)

        besedilo = izbirnik(odjemalec)

        assert UUID_ENA in besedilo
        assert not je_izbirna(besedilo, UUID_ENA)
        assert razlog in besedilo

    def test_obdelana_snov_brez_veljavnih_vprasanj(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Peti primer, ki ga kriterij ne našteje, stanje pa ga dopušča.

        Snov po „Pošlji v obdelavo" ima vsa vprašanja upokojena. Brez svoje veje
        bi padla v „slika ni berljiva" in bi razlog lagal.
        """
        snov(motor, slike, UUID_ENA)
        upokoji(motor, UUID_ENA)

        besedilo = izbirnik(odjemalec)

        assert not je_izbirna(besedilo, UUID_ENA)
        assert "brez veljavnih vprašanj" in besedilo

    def test_izbirnik_pokaze_slicico_cas_predmet_in_stevilo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=5)

        besedilo = izbirnik(odjemalec)

        assert f'src="/admin/materials/{UUID_ENA}/image"' in besedilo
        assert 'loading="lazy"' in besedilo
        assert "MAT" in besedilo
        assert "4. 9. 2026 ob" in besedilo
        assert "5\n                    vprašanj" in besedilo or "5 vprašanj" in besedilo


class TestPredogled:
    """„Sestavi" pokaže, kaj bo objavljeno, in ničesar ne shrani."""

    def test_privzeto_so_tri_vprasanja_na_sliko(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=5)

        # Polje `stevilo` se namenoma **ne** poslje: prav privzetek je tu
        # kriterij, in test, ki vrednost poslje, ga ne dokazuje.
        odgovor = odjemalec.post(
            "/admin/quizzes/preview",
            data={"vstop": "nova", "subject": "MAT", "snov": [UUID_ENA]},
        )

        assert odgovor.text.count('name="vprasanje"') == PRIVZETO_STEVILO == 3

    def test_vzame_prvih_n_po_position(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Brez naključja (`ADR-016` D): prvi dve po `position`, ne poljubni dve.
        snov(motor, slike, UUID_ENA, vprasanj=5)

        odgovor = odjemalec.post(
            "/admin/quizzes/preview",
            data={"vstop": "nova", "subject": "MAT", "stevilo": "2", "snov": [UUID_ENA]},
        )

        assert f'value="{UUID_ENA}-v1"' in odgovor.text
        assert f'value="{UUID_ENA}-v2"' in odgovor.text
        assert f'value="{UUID_ENA}-v3"' not in odgovor.text

    def test_manj_vprasanj_od_zahtevanih_ni_napaka(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=2)

        odgovor = odjemalec.post(
            "/admin/quizzes/preview",
            data={"vstop": "nova", "subject": "MAT", "stevilo": "5", "snov": [UUID_ENA]},
        )

        assert odgovor.status_code == 200
        assert odgovor.text.count('name="vprasanje"') == 2

    def test_pokaze_vprasanja_z_odgovori_in_povezavo_na_snov(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=3)

        odgovor = odjemalec.post(
            "/admin/quizzes/preview",
            data={"vstop": "nova", "subject": "MAT", "stevilo": "3", "snov": [UUID_ENA]},
        )

        assert "Vprašanje 1 iz 3f2b?" in odgovor.text
        assert "Odgovor 1." in odgovor.text
        assert f'href="/admin/materials/{UUID_ENA}"' in odgovor.text

    def test_nicesar_ne_shrani(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # `ADR-016` (C): v bazi ne nastajajo mrtvi osnutki.
        snov(motor, slike, UUID_ENA)

        odjemalec.post(
            "/admin/quizzes/preview",
            data={"vstop": "nova", "subject": "MAT", "stevilo": "3", "snov": [UUID_ENA]},
        )

        with Session(motor) as seja:
            assert seja.scalar(select(func.count()).select_from(Quiz)) == 0
            assert seja.scalar(select(func.count()).select_from(QuizItem)) == 0

    def test_pove_skupno_stevilo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)
        snov(motor, slike, UUID_DVA)

        odgovor = odjemalec.post(
            "/admin/quizzes/preview",
            data={
                "vstop": "nova",
                "subject": "MAT",
                "stevilo": "3",
                "snov": [UUID_ENA, UUID_DVA],
            },
        )

        assert "Skupaj 6" in odgovor.text

    def test_opozori_nad_tridesetimi(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        idji = [f"snov-{i:02d}" for i in range(3)]
        for material_id in idji:
            snov(motor, slike, material_id, vprasanj=10)
        # Enaintrideseto vprašanje in ne desetih: meja se preizkusi tik ob
        # sebi, sicer bi `> PREDOLG_KVIZ + 5` preživel.
        snov(motor, slike, "snov-ena", vprasanj=1)

        pod = odjemalec.post(
            "/admin/quizzes/preview",
            data={"vstop": "nova", "subject": "MAT", "stevilo": "10", "snov": idji},
        )
        cez = odjemalec.post(
            "/admin/quizzes/preview",
            data={
                "vstop": "nova",
                "subject": "MAT",
                "stevilo": "10",
                "snov": [*idji, "snov-ena"],
            },
        )

        assert "Skupaj 30 " in pod.text
        assert "Skupaj 31 " in cez.text
        # Pri točno 30 opozorila ni, pri 31 je: meja je „več kot 30".
        assert "več kot 30" not in pod.text
        assert "več kot 30" in cez.text

    def test_pove_koliko_je_bilo_izpuscenih(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)
        snov(motor, slike, UUID_DVA, status=STATUS_NOV, readable=None, vprasanj=0)
        snov(motor, slike, UUID_TRI, status=STATUS_NAPAKA, readable=None, vprasanj=0)

        odgovor = odjemalec.post(
            "/admin/quizzes/preview",
            data={"vstop": "nova", "subject": "MAT", "stevilo": "3", "snov": [UUID_ENA]},
        )

        assert "2 snovi" in odgovor.text

    def test_prazen_izbor_vrne_v_izbirnik_s_sporocilom(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)

        odgovor = odjemalec.post(
            "/admin/quizzes/preview",
            data={"vstop": "nova", "subject": "MAT", "stevilo": "3"},
        )

        assert odgovor.status_code == 200
        assert "Izberi vsaj eno snov" in odgovor.text
        with Session(motor) as seja:
            assert seja.scalar(select(func.count()).select_from(Quiz)) == 0

    def test_nazaj_na_izbor_ohrani_izbor(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)
        snov(motor, slike, UUID_DVA)
        snov(motor, slike, UUID_TRI)

        odgovor = odjemalec.post(
            "/admin/quizzes/new",
            data={
                "vstop": "nova",
                "subject": "MAT",
                "stevilo": "4",
                "snov": [UUID_ENA, UUID_TRI],
            },
        )

        assert je_obkljukana(odgovor.text, UUID_ENA)
        assert not je_obkljukana(odgovor.text, UUID_DVA)
        assert je_obkljukana(odgovor.text, UUID_TRI)
        assert 'value="4"' in odgovor.text


class TestObjava:
    """„Objavi" ustvari kviz in postavke v eni transakciji."""

    def test_ustvari_kviz_in_vse_postavke(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)
        snov(motor, slike, UUID_DVA)

        quiz_id = objavi(odjemalec, motor, [UUID_ENA, UUID_DVA])

        with Session(motor) as seja:
            kviz = seja.get(Quiz, quiz_id)
            assert kviz is not None
            assert [postavka.position for postavka in kviz.postavke] == [1, 2, 3, 4, 5, 6]

    def test_zapise_kopijo_besedila(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)

        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=1)

        with Session(motor) as seja:
            kviz = seja.get(Quiz, quiz_id)
            assert kviz is not None
            postavka = kviz.postavke[0]
            assert postavka.question_text == "Vprašanje 1 iz 3f2b?"
            assert postavka.answer_text == "Odgovor 1."
            assert postavka.question_id == f"{UUID_ENA}-v1"

    def test_vrstni_red_je_po_snovi_in_znotraj_nje_po_position(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        starejsa = datetime(2026, 9, 1, 7, tzinfo=UTC)
        novejsa = datetime(2026, 9, 4, 7, tzinfo=UTC)
        snov(motor, slike, UUID_ENA, taken_at=starejsa)
        snov(motor, slike, UUID_DVA, taken_at=novejsa)

        # Namenoma v „napačnem" vrstnem redu: vrstni red določi `taken_at DESC`
        # in ne zaporedje polj v obrazcu.
        quiz_id = objavi(odjemalec, motor, [UUID_ENA, UUID_DVA], koliko=2)

        with Session(motor) as seja:
            kviz = seja.get(Quiz, quiz_id)
            assert kviz is not None
            izvori = [postavka.question_id for postavka in kviz.postavke]
        assert izvori == [
            f"{UUID_DVA}-v1",
            f"{UUID_DVA}-v2",
            f"{UUID_ENA}-v1",
            f"{UUID_ENA}-v2",
        ]

    def test_neznano_vprasanje_zavrne_objavo_v_celoti(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Polovičen kviz je slabši od zavrnitve, ki jo operater vidi.
        snov(motor, slike, UUID_ENA)

        odgovor = odjemalec.post(
            "/admin/quizzes",
            data={
                "vstop": "nova",
                "subject": "MAT",
                "ime": "",
                "vprasanje": [f"{UUID_ENA}-v1", "tega-vprasanja-ni"],
            },
        )

        assert odgovor.status_code == 409
        with Session(motor) as seja:
            assert seja.scalar(select(func.count()).select_from(Quiz)) == 0
            assert seja.scalar(select(func.count()).select_from(QuizItem)) == 0

    def test_samodejno_ime_pri_predmetnem_vstopu(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)

        quiz_id = objavi(odjemalec, motor, [UUID_ENA])

        with Session(motor) as seja:
            kviz = seja.get(Quiz, quiz_id)
            assert kviz is not None
            assert kviz.name == f"MAT — {datum(datetime.now(UTC))}"
            assert kviz.subject == "MAT"

    def test_samodejno_ime_pri_dnevnem_vstopu(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Dnevni vstop gre čez vse predmete, zato `subject` ostane `NULL`.
        snov(motor, slike, UUID_ENA, taken_at=datetime.now(UTC))

        quiz_id = objavi(odjemalec, motor, [UUID_ENA], subject=None, vstop="danes")

        with Session(motor) as seja:
            kviz = seja.get(Quiz, quiz_id)
            assert kviz is not None
            assert kviz.name == f"Vsi predmeti — {datum(datetime.now(UTC))}"
            assert kviz.subject is None

    def test_ime_je_prepisljivo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)

        quiz_id = objavi(odjemalec, motor, [UUID_ENA], ime="Ponavljanje pred testom")

        with Session(motor) as seja:
            kviz = seja.get(Quiz, quiz_id)
            assert kviz is not None
            assert kviz.name == "Ponavljanje pred testom"


class TestZamrznitev:
    """Objavljen kviz svojih postavk ne spremeni več (`ADR-016` E)."""

    def test_stran_kviza_bere_kopijo_in_ne_zivega_vprasanja(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Dokaže, da stran bere `question_text` in ne `question.question`.

        Ta test je nastal zato, ker ga prej ni bilo: mutacija, ki je stran
        preusmerila na živo besedilo vprašanja, je celotno zbirko pustila
        zeleno. Ponovna obdelava tega ne ujame — ta staro vprašanje samo
        upokoji, njegovega besedila pa ne spremeni, zato sta kopija in izvirnik
        še vedno enaka. Razliko je treba narediti izrecno.

        Vrstice `questions` se v produkciji ne popravljajo; trditev, ki jo test
        dokazuje, ni „to se zgodi", ampak „kviz je od tega neodvisen" — in prav
        to je prva od dveh ravni obrambe iz `ADR-016` (E).
        """
        snov(motor, slike, UUID_ENA, vprasanj=1)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=1)

        with Session(motor) as seja:
            vprasanje = seja.get(Question, f"{UUID_ENA}-v1")
            assert vprasanje is not None
            vprasanje.question = "PODTAKNJENO VPRAŠANJE"
            vprasanje.answer = "PODTAKNJEN ODGOVOR"
            seja.commit()

        besedilo = odjemalec.get(f"/admin/quizzes/{quiz_id}").text

        assert "Vprašanje 1 iz 3f2b?" in besedilo
        assert "Odgovor 1." in besedilo
        assert "PODTAKNJENO" not in besedilo

    def test_postavka_brez_vprasanja_je_se_vedno_berljiva(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Druga raven obrambe: kviz brez `question_id` še vedno nekaj pove.

        `ON DELETE SET NULL` na `quiz_items.question_id` se v produkciji ne
        sproži — vprašanja se ne brišejo (`ADR-012`) — a shema to pot dopušča
        in stran ob njej ne sme pasti. Brez kopije besedila bi bila postavka
        takrat prazna vrstica.
        """
        snov(motor, slike, UUID_ENA, vprasanj=1)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=1)

        with Session(motor) as seja:
            postavka = seja.scalars(select(QuizItem)).one()
            postavka.question_id = None
            seja.commit()

        odgovor = odjemalec.get(f"/admin/quizzes/{quiz_id}")

        assert odgovor.status_code == 200
        assert "Vprašanje 1 iz 3f2b?" in odgovor.text
        assert "Odgovor 1." in odgovor.text
        assert "izvor ni znan" in odgovor.text

    def test_ponovna_obdelava_ne_spremeni_kviza(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """**Regresijski test zahteve.**

        Pade, če postavka izgubi kopijo besedila ali če bi kviz besedilo bral
        iz vprašanja. Prav zaradi tega testa je `V2-R05` obstajala.
        """
        snov(motor, slike, UUID_ENA, vprasanj=3)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=3)
        prej = odjemalec.get(f"/admin/quizzes/{quiz_id}").text

        upokoji(motor, UUID_ENA)
        with Session(motor) as seja:
            material = seja.get(Material, UUID_ENA)
            assert material is not None
            material.vsa_vprasanja.append(
                Question(
                    id=f"{UUID_ENA}-nov1",
                    position=1,
                    question="Popolnoma drugačno vprašanje?",
                    answer="Drugačen odgovor.",
                    subject="MAT",
                    material_taken_at=material.taken_at,
                )
            )
            seja.commit()

        potem = odjemalec.get(f"/admin/quizzes/{quiz_id}").text

        assert "Vprašanje 1 iz 3f2b?" in potem
        assert "Popolnoma drugačno vprašanje?" not in potem
        with Session(motor) as seja:
            kviz = seja.get(Quiz, quiz_id)
            assert kviz is not None
            assert len(kviz.postavke) == 3
            assert kviz.postavke[0].question_id == f"{UUID_ENA}-v1"
        assert prej == potem

    def test_kviz_prezivi_dokoncno_brisanje_snovi(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=3)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=3)

        with Session(motor) as seja:
            material = seja.get(Material, UUID_ENA)
            assert material is not None
            seja.delete(material)
            seja.commit()

        odgovor = odjemalec.get(f"/admin/quizzes/{quiz_id}")

        assert odgovor.status_code == 200
        assert "Vprašanje 1 iz 3f2b?" in odgovor.text
        assert "Odgovor 1." in odgovor.text
        # Povezave na snov ni več, izvor pa vprašanje še vedno nosi (`ADR-012`).
        assert f'href="/admin/materials/{UUID_ENA}"' not in odgovor.text
        assert "izvorne slike ni več" in odgovor.text
        with Session(motor) as seja:
            postavke = seja.scalars(select(QuizItem)).all()
            assert len(postavke) == 3
            assert all(postavka.question_id is not None for postavka in postavke)


class TestStranKviza:
    """`GET /admin/quizzes/{id}` in preklic."""

    def test_pot_new_ni_prebrana_kot_identifikator(self, odjemalec: TestClient) -> None:
        # Vrstni red registracije poti: `/new` mora biti pred `/{quiz_id}`.
        odgovor = odjemalec.get("/admin/quizzes/new", params={"vstop": "danes"})

        assert odgovor.status_code == 200
        assert "Kviza s tem identifikatorjem ni" not in odgovor.text

    def test_neznan_kviz_da_404_kot_html(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get("/admin/quizzes/tega-ni")

        assert odgovor.status_code == 404
        assert "text/html" in odgovor.headers["content-type"]

    def test_preklic_ne_izbrise_nicesar(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=3)

        odgovor = odjemalec.post(
            f"/admin/quizzes/{quiz_id}/cancel", follow_redirects=False
        )

        assert odgovor.status_code == 303
        with Session(motor) as seja:
            kviz = seja.get(Quiz, quiz_id)
            assert kviz is not None
            assert kviz.canceled_at is not None
            assert len(kviz.postavke) == 3
        assert "preklican" in odjemalec.get(f"/admin/quizzes/{quiz_id}").text

    def test_ponoven_preklic_ne_premakne_casa(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA])

        odjemalec.post(f"/admin/quizzes/{quiz_id}/cancel", follow_redirects=False)
        with Session(motor) as seja:
            kviz = seja.get(Quiz, quiz_id)
            assert kviz is not None
            prvi = kviz.canceled_at

        odjemalec.post(f"/admin/quizzes/{quiz_id}/cancel", follow_redirects=False)
        with Session(motor) as seja:
            kviz = seja.get(Quiz, quiz_id)
            assert kviz is not None
            assert kviz.canceled_at == prvi

    def test_preklicanega_kviza_ni_mogoce_preklicati_nazaj(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Enosmerno, po vzorcu `archived_at` in `retired_at`. Gumba ni.
        snov(motor, slike, UUID_ENA)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA])
        odjemalec.post(f"/admin/quizzes/{quiz_id}/cancel", follow_redirects=False)

        besedilo = odjemalec.get(f"/admin/quizzes/{quiz_id}").text

        assert "Prekliči kviz" not in besedilo


class TestSeznamNaPregledu:
    """Razdelek s kvizi na `/admin`."""

    def test_najnovejsi_prvi_s_podatki(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)
        snov(motor, slike, UUID_DVA)
        prvi = objavi(odjemalec, motor, [UUID_ENA], ime="Starejši kviz")
        drugi = objavi(odjemalec, motor, [UUID_DVA], ime="Novejši kviz")

        besedilo = odjemalec.get("/admin").text

        assert besedilo.index("Novejši kviz") < besedilo.index("Starejši kviz")
        assert f'href="/admin/quizzes/{prvi}"' in besedilo
        assert f'href="/admin/quizzes/{drugi}"' in besedilo
        assert "objavljen" in besedilo

    def test_preklican_kviz_je_oznacen(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA])
        odjemalec.post(f"/admin/quizzes/{quiz_id}/cancel", follow_redirects=False)

        assert "preklican" in odjemalec.get("/admin").text

    def test_prazen_seznam_pove_da_kviza_se_ni(self, odjemalec: TestClient) -> None:
        besedilo = odjemalec.get("/admin").text
        razdelek = besedilo[besedilo.index("<h2>Kvizi</h2>") :]

        assert "Objavljenega kviza še ni." in razdelek

    def test_kviz_na_pregledu_ne_podre_vrstnega_reda_predmetov(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Regresija za `test_admin.py::test_vrstni_red_predmetov_je_urnik_...`.

        Tisti test sodi po vrstnem redu **prvih** pojavitev kod predmetov na
        strani. Ime kviza vsebuje kodo (`MAT — 9. 9. 2026`), zato bi razdelek
        s kvizi nad seznamom predmetov ta test podrl iz razloga, ki z vrstnim
        redom predmetov nima zveze. Ta test to past drzi zaprto z druge strani:
        kviz v bazi je in vrstni red mora vseeno stati.
        """
        snov(motor, slike, UUID_ENA, subject="DKE")
        objavi(odjemalec, motor, [UUID_ENA], subject="DKE")

        besedilo = odjemalec.get("/admin").text

        assert besedilo.index("NAR") < besedilo.index("MAT") < besedilo.index("TJA")
        assert besedilo.index("TIT") < besedilo.index("DKE")

    def test_vstopi_so_na_pregledu(self, odjemalec: TestClient) -> None:
        besedilo = odjemalec.get("/admin").text

        assert 'value="nova"' in besedilo
        assert 'value="rocna"' in besedilo
        assert "/admin/quizzes/new?vstop=danes" in besedilo


class TestMejaDneva:
    """„Danes" je lokalni dan, ne UTC dan (`ADR-016` B)."""

    def test_meja_je_lokalna_polnoc(self) -> None:
        # 8. 9. ob 22:30 UTC je v Ljubljani (CEST, UTC+2) že 9. 9. ob 00:30.
        trenutek = datetime(2026, 9, 8, 22, 30, tzinfo=UTC)

        od, do = dan_od_do(trenutek)

        assert od == datetime(2026, 9, 8, 22, 0, tzinfo=UTC)
        assert do == datetime(2026, 9, 9, 22, 0, tzinfo=UTC)
        assert od <= trenutek < do

    def test_interval_je_polodprt(self) -> None:
        # Posnetek točno ob polnoči sodi v nov dan in ne v oba.
        od, do = dan_od_do(datetime(2026, 9, 8, 22, 0, tzinfo=UTC))

        assert od == datetime(2026, 9, 8, 22, 0, tzinfo=UTC)
        assert do - od == timedelta(days=1)

    def test_prehod_na_zimski_cas_da_petindvajset_ur(self) -> None:
        # Zadnjo nedeljo v oktobru 2026 (25. 10.) ima lokalni dan 25 ur.
        od, do = dan_od_do(datetime(2026, 10, 25, 12, 0, tzinfo=UTC))

        assert do - od == timedelta(hours=25)


class TestBrezKljuca:
    """Nove poti so pod `/admin`, torej brez ključa — in nič drugega ni odprto."""

    def test_sestavljalnik_je_dosegljiv_brez_kljuca(self, odjemalec: TestClient) -> None:
        assert odjemalec.get("/admin/quizzes/new", params={"vstop": "danes"}).status_code == 200

    def test_materials_brez_kljuca_ostaja_401(self, odjemalec: TestClient) -> None:
        # Isti regresijski razlog kot v `test_admin.py`: izvzetje predpone
        # `/admin` ne sme odpreti ničesar drugega (`ADR-006`).
        odgovor = odjemalec.post("/materials", files={"file": ("a.jpg", b"x", "image/jpeg")})

        assert odgovor.status_code == 401

    def test_materials_s_pravim_kljucem_se_vedno_dela(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.post(
            "/materials",
            headers={"X-API-Key": KLJUC},
            data={
                "id": UUID_TRI,
                "subject": "MAT",
                "taken_at": "2026-09-04T07:30:00+00:00",
            },
            files={"file": ("a.jpg", b"x", "image/jpeg")},
        )

        assert odgovor.status_code == 201


class TestSlovenscina:
    """Števila v vmesniku so zapisana slovensko, z dvojino."""

    @pytest.mark.parametrize(
        ("koliko", "pricakovano"),
        [
            (1, "1 vprašanje"),
            (2, "2 vprašanji"),
            (3, "3 vprašanja"),
            (4, "4 vprašanja"),
            (5, "5 vprašanj"),
            (0, "0 vprašanj"),
            # Ločnica teče po ostanku pri sto in ne po samem številu.
            (101, "101 vprašanje"),
            (102, "102 vprašanji"),
            (111, "111 vprašanj"),
        ],
    )
    def test_dvojina_in_mnozina(self, koliko: int, pricakovano: str) -> None:
        assert _stevilo_z_besedo(koliko, VPRASANJA) == pricakovano

    def test_izbirnik_pravilno_sklanja(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA, vprasanj=2)
        snov(motor, slike, UUID_DVA, vprasanj=1)

        besedilo = izbirnik(odjemalec)

        assert "2 vprašanji" in besedilo
        assert "1 vprašanje" in besedilo

    def test_predogled_imenuje_obseg_in_ne_izbora(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Izpuščene se štejejo čez cel predmet oziroma dan, ne čez izbor.

        Besedilo mora imenovati prav to: „tega predmeta" pri predmetnem vstopu
        in „tega dne" pri dnevnem.
        """
        snov(motor, slike, UUID_ENA)
        snov(motor, slike, UUID_DVA, status=STATUS_NOV, readable=None, vprasanj=0)

        odgovor = odjemalec.post(
            "/admin/quizzes/preview",
            data={"vstop": "nova", "subject": "MAT", "stevilo": "3", "snov": [UUID_ENA]},
        )

        assert "1 snov tega predmeta" in odgovor.text
        assert "izbora" not in odgovor.text

    def test_predogled_uporabi_rodilnik_za_snovi(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Za predlogom *iz* gre rodilnik: „iz 1 snovi", nikoli „iz 1 snov".
        snov(motor, slike, UUID_ENA, vprasanj=2)

        odgovor = odjemalec.post(
            "/admin/quizzes/preview",
            data={"vstop": "nova", "subject": "MAT", "stevilo": "3", "snov": [UUID_ENA]},
        )

        assert "Skupaj 2 vprašanji iz 1 snovi." in odgovor.text


class TestPoizvedbe:
    """Strani ne smejo delati poizvedbe na vrstico (N+1)."""

    @staticmethod
    def _stej(motor: Engine, klic: Callable[[], object]) -> int:
        """Koliko stavkov je proti bazi opravil dani klic."""
        stevec = 0

        def zabelezi(*_args: object, **_kwargs: object) -> None:
            nonlocal stevec
            stevec += 1

        event.listen(motor, "before_cursor_execute", zabelezi)
        try:
            klic()
        finally:
            event.remove(motor, "before_cursor_execute", zabelezi)
        return stevec

    def test_izbirnik_je_tri_poizvedbe_ne_glede_na_stevilo_snovi(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        for i in range(12):
            snov(motor, slike, f"veliko-{i:02d}", vprasanj=5)

        koliko = self._stej(motor, lambda: izbirnik(odjemalec))

        # Ena za snovi, ena za stevila vprasanj, ena za "ze v kvizu".
        assert koliko == 3

    def test_stran_kviza_ne_bere_vprasanja_na_postavko(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Brez `selectinload` bi bilo poizvedb toliko kot postavk plus nekaj.
        snov(motor, slike, UUID_ENA, vprasanj=10)
        snov(motor, slike, UUID_DVA, vprasanj=10)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA, UUID_DVA], koliko=10)

        koliko = self._stej(motor, lambda: odjemalec.get(f"/admin/quizzes/{quiz_id}"))

        assert koliko <= 5, f"stran kviza je opravila {koliko} poizvedb"


class TestPopravkiPoPregledu:
    """Kar je nasel pregledovalec v fazi 7 in prej ni bilo dokazano."""

    def test_danes_se_meri_po_taken_at_in_ne_po_received_at(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """`ADR-016` (B): danes je trenutek **posnetka**, ne prejema.

        Prej tega ni dokazoval noben test: pomozna funkcija je `received_at`
        nastavljala enako kot `taken_at`, zato je zamenjava stolpca v poizvedbi
        pustila celo zbirko zeleno. Razlika se v resnici pokaze natanko pri
        posnetku pozno zvecer, ki se prenese naslednji dan.
        """
        zdaj = datetime.now(UTC)
        snov(motor, slike, UUID_ENA, taken_at=zdaj)
        snov(motor, slike, UUID_DVA, taken_at=zdaj - timedelta(days=3))

        # Starejsi posnetek je streznik prejel sele danes, danasnjega pa ze
        # pred dnevi: stolpca sta zdaj v nasprotju in poizvedba mora izbrati
        # pravega.
        with Session(motor) as seja:
            stara = seja.get(Material, UUID_DVA)
            nova = seja.get(Material, UUID_ENA)
            assert stara is not None
            assert nova is not None
            stara.received_at = zdaj
            nova.received_at = zdaj - timedelta(days=3)
            seja.commit()

        besedilo = izbirnik(odjemalec, vstop="danes", subject=None)

        assert UUID_ENA in besedilo
        assert UUID_DVA not in besedilo

    def test_predogled_nosi_izbor_nazaj_v_izbirnik(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Kriterij: ob vrnitvi je izbor tak, kot je bil.

        Prej je bil pokrit samo `POST /new`, ki ga je test sestavil sam. Ce bi
        predogled skrita polja izgubil, bi gumb v brskalniku poslal prazen
        obrazec in izbor zavrgel, zbirka pa bi ostala zelena. Zato ta test
        **prebere obrazec iz izrisanega predogleda** in ga poslje naprej
        takega, kot bi ga poslal brskalnik.
        """
        snov(motor, slike, UUID_ENA)
        snov(motor, slike, UUID_DVA)
        snov(motor, slike, UUID_TRI)

        predogled = odjemalec.post(
            "/admin/quizzes/preview",
            data={
                "vstop": "nova",
                "subject": "MAT",
                "stevilo": "4",
                "snov": [UUID_ENA, UUID_TRI],
            },
        )

        obrazec = predogled.text[predogled.text.index('action="/admin/quizzes/new"') :]
        izbrane = re.findall(r'name="snov" value="([^"]+)"', obrazec)
        stevilo = re.search(r'name="stevilo" value="([^"]+)"', obrazec)
        assert stevilo is not None
        assert set(izbrane) == {UUID_ENA, UUID_TRI}

        nazaj = odjemalec.post(
            "/admin/quizzes/new",
            data={
                "vstop": "nova",
                "subject": "MAT",
                "stevilo": stevilo.group(1),
                "snov": izbrane,
            },
        )

        assert je_obkljukana(nazaj.text, UUID_ENA)
        assert not je_obkljukana(nazaj.text, UUID_DVA)
        assert je_obkljukana(nazaj.text, UUID_TRI)
        assert 'value="4"' in nazaj.text

    def test_seznam_pove_predmet_in_datum_tudi_ob_prepisanem_imenu(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Kriterij: seznam kvizov s predmetom, datumom, stevilom in stanjem.

        Ime je prepisljivo, zato predmeta in datuma ne nosi. Prej ju vrstica ni
        izpisala nikjer.
        """
        snov(motor, slike, UUID_ENA, subject="GEO")
        objavi(
            odjemalec, motor, [UUID_ENA], subject="GEO", ime="Ponavljanje pred testom"
        )

        besedilo = odjemalec.get("/admin").text
        vrstica = besedilo[besedilo.index("Ponavljanje pred testom") :][:400]

        assert "GEO" in vrstica
        assert datum(datetime.now(UTC)) in vrstica
        assert "objavljen" in vrstica

    def test_izbirnik_pove_kodo_predmeta_v_vsaki_vrstici(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Pri dnevnem vstopu cez vse predmete je koda v vrstici edini nacin,
        # da se snovi locijo med sabo.
        zdaj = datetime.now(UTC)
        snov(motor, slike, UUID_ENA, subject="MAT", taken_at=zdaj)
        snov(motor, slike, UUID_DVA, subject="GEO", taken_at=zdaj)

        besedilo = izbirnik(odjemalec, vstop="danes", subject=None)

        assert '<span class="cas">MAT ' in besedilo
        assert '<span class="cas">GEO ' in besedilo

    def test_podvojeno_vprasanje_zavrne_objavo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Sicer bi kviz dobil dve enaki postavki in bi `V2-R04` isti odgovor
        # stela dvakrat.
        snov(motor, slike, UUID_ENA)

        odgovor = odjemalec.post(
            "/admin/quizzes",
            data={
                "vstop": "nova",
                "subject": "MAT",
                "ime": "",
                "vprasanje": [f"{UUID_ENA}-v1", f"{UUID_ENA}-v1"],
            },
        )

        assert odgovor.status_code == 409
        with Session(motor) as seja:
            assert seja.scalar(select(func.count()).select_from(QuizItem)) == 0

    def test_objava_brez_vprasanj_pove_kaj_je_narobe(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.post(
            "/admin/quizzes", data={"vstop": "nova", "subject": "MAT", "ime": ""}
        )

        assert odgovor.status_code == 409
        assert "ni bilo izbrano nobeno" in odgovor.text

    def test_nerazberljivo_stevilo_ne_vrne_surove_napake(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Merilo dokoncanosti: pod `/admin` ni surovega sistemskega besedila.

        FastAPI bi ob polju tipa `int` vrnil 422 z angleskim JSON
        (`Input should be a valid integer`). Do tega pride le z rocno vtipkanim
        naslovom, a stran mora ostati stran.
        """
        snov(motor, slike, UUID_ENA)

        odgovor = odjemalec.get(
            "/admin/quizzes/new",
            params={"vstop": "nova", "subject": "MAT", "stevilo": "abc"},
        )

        assert odgovor.status_code == 200
        assert "text/html" in odgovor.headers["content-type"]
        assert "Input should be" not in odgovor.text
        # Pade nazaj na privzetek in to takoj pokaze v polju.
        assert 'name="stevilo" value="3"' in odgovor.text


class TestPredogledJeZadnjaBeseda:
    """Predogled je poizvedba, ki doloci, kaj bo zamrznjeno v kviz.

    Prej so bili njegovi filtri nepokriti: `retired_at IS NULL` in
    `archived_at IS NULL` v `KviziRepository.snovi_z_vprasanji` sta se dala
    odstraniti, ne da bi kateri koli test padel. Testi izbirnika tega ne
    ujamejo — izbirnik in predogled sta dve razlicni poizvedbi.
    """

    def test_predogled_ponudi_novo_serijo_in_ne_upokojene(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Po ponovni obdelavi predogled ponudi **novo** serijo.

        Stara in nova serija imata obe `position` 1..n, zato ju ne loci
        vrstni red, ampak samo `retired_at`. Brez tega filtra bi operater
        potrdil staro vprasanje in objava bi ga po `ADR-018` brez ugovora
        zamrznila v kviz.
        """
        snov(motor, slike, UUID_ENA, vprasanj=3)
        upokoji(motor, UUID_ENA)
        with Session(motor) as seja:
            material = seja.get(Material, UUID_ENA)
            assert material is not None
            material.vsa_vprasanja.append(
                Question(
                    id=f"{UUID_ENA}-nov1",
                    position=1,
                    question="Vprasanje iz nove serije?",
                    answer="Odgovor iz nove serije.",
                    subject="MAT",
                    material_taken_at=material.taken_at,
                )
            )
            seja.commit()

        odgovor = odjemalec.post(
            "/admin/quizzes/preview",
            data={"vstop": "nova", "subject": "MAT", "stevilo": "3", "snov": [UUID_ENA]},
        )

        assert "Vprasanje iz nove serije?" in odgovor.text
        assert "Vprašanje 1 iz 3f2b?" not in odgovor.text
        assert odgovor.text.count('name="vprasanje"') == 1

    def test_snov_arhivirana_med_izborom_in_sestavi_izpade(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Arhiv velja tudi za pot predogleda, ne le za izbirnik.

        Med izborom in klikom „Sestavi" mine nekaj sekund; v drugem zavihku
        je snov lahko medtem sla v arhiv. Docstring metode to obljublja, prej
        pa tega ni drzalo nic.
        """
        snov(motor, slike, UUID_ENA)
        snov(motor, slike, UUID_DVA)
        with Session(motor) as seja:
            material = seja.get(Material, UUID_DVA)
            assert material is not None
            material.archived_at = datetime.now(UTC)
            seja.commit()

        odgovor = odjemalec.post(
            "/admin/quizzes/preview",
            data={
                "vstop": "nova",
                "subject": "MAT",
                "stevilo": "3",
                "snov": [UUID_ENA, UUID_DVA],
            },
        )

        assert f'href="/admin/materials/{UUID_ENA}"' in odgovor.text
        assert f'href="/admin/materials/{UUID_DVA}"' not in odgovor.text
        assert odgovor.text.count('name="vprasanje"') == 3


class TestObjavaPreverjaVhod:
    """Objava je edina pot, ki pise v bazo, zato vsakemu polju pogleda pod prste."""

    def test_predolgo_ime_ne_pride_do_baze(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """`Quiz.name` je `String(200)`.

        SQLite dolzine `VARCHAR` ne uveljavlja, zato bi bil predolg vnos v
        testih zelen in bi na Postgresu postal `DataError` -> angleski
        „Internal Server Error". Preverba mora biti v kodi, ne v bazi.
        """
        snov(motor, slike, UUID_ENA)

        odgovor = odjemalec.post(
            "/admin/quizzes",
            data={
                "vstop": "nova",
                "subject": "MAT",
                "ime": "x" * 201,
                "vprasanje": [f"{UUID_ENA}-v1"],
            },
        )

        assert odgovor.status_code == 409
        assert "predolgo" in odgovor.text
        with Session(motor) as seja:
            assert seja.scalar(select(func.count()).select_from(Quiz)) == 0

    def test_ime_na_meji_je_se_sprejeto(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov(motor, slike, UUID_ENA)

        odgovor = odjemalec.post(
            "/admin/quizzes",
            data={
                "vstop": "nova",
                "subject": "MAT",
                "ime": "x" * 200,
                "vprasanje": [f"{UUID_ENA}-v1"],
            },
            follow_redirects=False,
        )

        assert odgovor.status_code == 303

    def test_predolga_koda_predmeta_ne_pride_do_baze(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # `Quiz.subject` je `String(16)`; isti razlog kot pri imenu.
        snov(motor, slike, UUID_ENA)

        odgovor = odjemalec.post(
            "/admin/quizzes",
            data={
                "vstop": "nova",
                "subject": "P" * 17,
                "ime": "",
                "vprasanje": [f"{UUID_ENA}-v1"],
            },
        )

        assert odgovor.status_code == 409
        with Session(motor) as seja:
            assert seja.scalar(select(func.count()).select_from(Quiz)) == 0

    def test_neznan_vstop_ne_ustvari_kviza(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Edina pot v modulu, ki vhodu iz obrazca prej ni pogledala pod prste.
        snov(motor, slike, UUID_ENA)

        odgovor = odjemalec.post(
            "/admin/quizzes",
            data={
                "vstop": "izmisljen",
                "subject": "MAT",
                "ime": "",
                "vprasanje": [f"{UUID_ENA}-v1"],
            },
        )

        assert odgovor.status_code == 404
        with Session(motor) as seja:
            assert seja.scalar(select(func.count()).select_from(Quiz)) == 0


class TestVarovalkeBrezKlika:
    """Varovalke na poteh, ki jih s klikom ni mogoce doseci.

    Vse tri stojijo na skritih poljih obrazca. Do njih se pride z rocno
    vtipkanim naslovom — in prav zato morajo imeti test: napacen popravek jih
    odstrani, vmesnik pa razlike ne pokaze.
    """

    def test_dnevni_vstop_da_kviz_cez_vse_predmete_tudi_s_podtaknjenim_predmetom(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """`quizzes.subject` mora ostati `NULL`, ceprav obrazec nosi predmet.

        Rocno vtipkan naslov `?vstop=danes&subject=MAT` da izbirnik, ki predmet
        prenese naprej skozi skrita polja vse do objave. Brez varovalke
        `None if vstop == VSTOP_DANES` bi nastal kviz z imenom „MAT — ..." in
        `subject='MAT'`, ceprav vsebuje snov vseh predmetov (`ADR-016` B).
        """
        zdaj = datetime.now(UTC)
        snov(motor, slike, UUID_ENA, subject="MAT", taken_at=zdaj)
        snov(motor, slike, UUID_DVA, subject="GEO", taken_at=zdaj)

        odgovor = odjemalec.post(
            "/admin/quizzes",
            data={
                "vstop": "danes",
                "subject": "MAT",
                "ime": "",
                "vprasanje": [f"{UUID_ENA}-v1", f"{UUID_DVA}-v1"],
            },
            follow_redirects=False,
        )

        assert odgovor.status_code == 303
        quiz_id = odgovor.headers["location"].rsplit("/", 1)[-1]
        with Session(motor) as seja:
            kviz = seja.get(Quiz, quiz_id)
            assert kviz is not None
            assert kviz.subject is None
            assert kviz.name == f"Vsi predmeti — {datum(zdaj)}"

    def test_meji_dolzine_se_ujemata_s_sirino_stolpcev(self) -> None:
        """Konstanti podvajata `String(...)` iz `app/models.py`.

        Podvojena vrednost, ki je ne uveljavlja nic, tiho zdrsne narazen ob
        prvi spremembi stolpca — in preverba, ki naj bi lovila razred napake,
        ki ga zelena zbirka ne pokaze, bi bila sama izpostavljena istemu.
        """
        assert Quiz.name.type.length == NAJVEC_IME
        assert Quiz.subject.type.length == NAJVEC_KODA
