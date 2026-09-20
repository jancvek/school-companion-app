"""Družina kot lastnik podatkov (V3-R01): izbira, repozitoriji, prevzem, obdelava.

Test tesnjenja čez vse poti je v `test_tesnjenje.py`. Tu je vedenje, ki ga
prinese družina sama: kako se izbere in koliko to stane, kaj se zgodi, ko ni
natanko ene, in kako prevzem in obdelava ravnata z dvema družinama
(`docs/odlocitve/ADR-025`, `ADR-029`).
"""

import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import (
    ClaniRepository,
    DruzineRepository,
    KviziRepository,
    MaterialsRepository,
    StatistikaRepository,
)
from app.models import (
    STATUS_NAPAKA,
    STATUS_NOV,
    STATUS_PRIPRAVLJEN,
    STATUS_V_OBDELAVI,
    Family,
    Material,
    Question,
)
from app.obdelava import obdelaj_cakajoce
from app.routers.materials import SPOROCILO_TUJ_ID
from app.worker import obnovi_obticale
from tests.conftest import CVEK_ID, SejaTesta
from tests.test_kvizi import objavi
from tests.test_obdelava import klicalec_vrne, uspesen_izid
from tests.test_resevanje import poskus, poslji
from tests.test_rezultat import postavke

#: Druga družina. Kanoničen UUID, ker iz njega nastane mapa slik.
DRUGA_ID = "9d4c2b1a-7e6f-4d5c-8b3a-1f2e3d4c5b6a"

UUID_ENA = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
UUID_DVA = "a1b2c3d4-e5f6-4789-abcd-ef0123456789"


REPOZITORIJI = (MaterialsRepository, KviziRepository, StatistikaRepository, ClaniRepository)


def dodaj_druzino(
    motor: Engine,
    family_id: str = DRUGA_ID,
    created_at: datetime = datetime(2026, 9, 2, tzinfo=UTC),
) -> None:
    """Še ena družina poleg Cvek, ki jo ima vsaka testna baza."""
    with Session(motor) as seja:
        seja.add(Family(id=family_id, name="Druga", created_at=created_at))
        seja.commit()


def snov_druzine(
    motor: Engine,
    slike: Path,
    family_id: str,
    material_id: str,
    *,
    status: str = STATUS_NOV,
) -> Path:
    """Snov dane družine s sliko v mapi te družine; vrne pot do slike."""
    pot = slike / family_id / f"{material_id}.jpg"
    pot.parent.mkdir(parents=True, exist_ok=True)
    pot.write_bytes(f"slika-{family_id[:4]}".encode())
    with Session(motor) as seja:
        seja.add(
            Material(
                id=material_id,
                family_id=family_id,
                subject="MAT",
                taken_at=datetime(2026, 9, 4, 7, 30, tzinfo=UTC),
                image_path=str(pot),
                status=status,
                received_at=datetime(2026, 9, 4, 8, 0, tzinfo=UTC),
            )
        )
        seja.commit()
    return pot


def stavki_med(motor: Engine, klic: Callable[[], object]) -> list[str]:
    """Stavki SQL, ki jih je proti bazi opravil dani klic."""
    stavki: list[str] = []

    def zabelezi(_povezava: Any, _kazalec: Any, stavek: str, *_ostalo: Any) -> None:
        stavki.append(stavek)

    event.listen(motor, "before_cursor_execute", zabelezi)
    try:
        klic()
    finally:
        event.remove(motor, "before_cursor_execute", zabelezi)
    return stavki


class TestRepozitorijBrezDruzine:
    """Kriterij V3-R01: brez privzetka in brez metode, ki bi družino obšla."""

    @pytest.mark.parametrize("razred", REPOZITORIJI)
    def test_druzina_je_obvezen_argument_brez_privzetka(self, razred: type) -> None:
        parametri = inspect.signature(razred).parameters

        assert list(parametri) == ["session", "family_id"]
        assert parametri["family_id"].default is inspect.Parameter.empty

    @pytest.mark.parametrize("razred", REPOZITORIJI)
    def test_prazna_druzina_je_napaka_ze_ob_nastanku(self, razred: type, motor: Engine) -> None:
        with Session(motor) as seja, pytest.raises(ValueError, match="brez družine"):
            razred(seja, "")

    @pytest.mark.parametrize("razred", REPOZITORIJI)
    def test_seja_ni_javna(self, razred: type, motor: Engine) -> None:
        """Javna seja bi usmerjevalniku dala pot do baze mimo pogoja družine."""
        with Session(motor) as seja:
            repozitorij = razred(seja, CVEK_ID)

            assert not hasattr(repozitorij, "session")
            assert repozitorij.family_id == CVEK_ID

    @pytest.mark.parametrize("druzina", [DRUGA_ID, None], ids=["tuja", "brez"])
    def test_vstavljanje_zapisa_s_tujo_ali_brez_druzine_se_zavrne(
        self, motor: Engine, druzina: str | None
    ) -> None:
        """Zapis mora nositi družino repozitorija (plan V3-R01, odločitev 2)."""
        dodaj_druzino(motor)
        with Session(motor) as seja, pytest.raises(ValueError, match="družino tega repozitorija"):
            MaterialsRepository(seja, CVEK_ID).vstavi_ce_ga_ni(
                Material(
                    # Brez družine: polja sploh ni, kot pri poti, ki bi ga pozabila.
                    **({} if druzina is None else {"family_id": druzina}),
                    id=UUID_ENA,
                    subject="MAT",
                    taken_at=datetime(2026, 9, 4, 7, 30, tzinfo=UTC),
                    image_path="/nikamor.jpg",
                    status=STATUS_NOV,
                    received_at=datetime(2026, 9, 4, 8, 0, tzinfo=UTC),
                )
            )


class TestDruzineRepository:
    def test_idji_so_najstarejsa_druzina_prva(self, motor: Engine) -> None:
        dodaj_druzino(motor, created_at=datetime(2026, 8, 1, tzinfo=UTC))

        with Session(motor) as seja:
            assert DruzineRepository(seja).idji() == [DRUGA_ID, CVEK_ID]

    def test_edina_samo_pri_natanko_eni(self, motor: Engine) -> None:
        with Session(motor) as seja:
            assert DruzineRepository(seja).edina() == CVEK_ID

        dodaj_druzino(motor)
        with Session(motor) as seja:
            assert DruzineRepository(seja).edina() is None
            seja.execute(delete(Family))
            seja.commit()
            assert DruzineRepository(seja).edina() is None


class TestIzbiraDruzine:
    """Od kod pot izve družino: iz seje, na obeh straneh.

    `ADR-029` A je izbiro „edina družina v bazi" uvedel kot **začasno** za obe
    strani in napovedal, da jo `V3-R03` za admin zamenja s sejo, `V3-R04` pa za
    telefon z žetonom. Oba koraka sta narejena, zato je `daj_druzino_telefona`
    odpadel in z njim izid `500`, ki ga je znal proizvesti (`ADR-036` F).
    """

    def test_admin_druzine_ne_isce_v_bazi_ampak_v_seji(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        """`/admin` uporablja `MaterialsRepository` in `KviziRepository` hkrati.

        Družino obema pove seja, ki jo je prebrala vmesna plast — natanko
        enkrat na zahtevo. Poizvedbe po tabeli `families` na tej poti ni več;
        če se kdaj vrne, je to tiha vrnitev začasnega pravila `ADR-029` A.
        """
        odgovori = []
        stavki = stavki_med(motor, lambda: odgovori.append(odjemalec.get("/admin")))

        assert odgovori[0].status_code == 200
        assert [stavek for stavek in stavki if "FROM families" in stavek] == []
        assert sum("FROM sessions" in stavek for stavek in stavki) == 1

    def test_druga_druzina_v_bazi_ne_ustavi_admin_strani(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        """Pred V3-R03 je bil to `500`; odkar odloča seja, druga družina ne moti."""
        dodaj_druzino(motor)

        odgovor = odjemalec.get("/admin")

        assert odgovor.status_code == 200

    def test_telefon_druzine_ne_isce_v_bazi_ampak_v_seji(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        """Zrcalno adminu: družino pove žeton, poizvedbe po `families` ni.

        Če se `FROM families` na tej poti kdaj vrne, je to tiha vrnitev
        začasnega pravila `ADR-029` A, ki ga je `ADR-036` F razveljavil.
        """
        odgovori = []
        stavki = stavki_med(
            motor,
            lambda: odgovori.append(odjemalec.get("/quizzes/pending", headers=telefon.glave)),
        )

        assert odgovori[0].status_code == 200
        assert [stavek for stavek in stavki if "FROM families" in stavek] == []
        assert sum("FROM sessions" in stavek for stavek in stavki) == 1

    def test_druga_druzina_v_bazi_ne_ustavi_telefona(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        """Pred V3-R04 je bil to `500`; odkar odloča žeton, druga družina ne moti.

        To je pogoj, ki ga je `V3-R05` postavil pred prvo tujo družino: dokler
        je druga vrstica v `families` ustavljala telefon, večdružinskosti ni
        bilo mogoče niti preizkusiti v resnici.
        """
        dodaj_druzino(motor)

        odgovor = odjemalec.get("/quizzes/pending", headers=telefon.glave)

        assert odgovor.status_code == 200

    def test_telefon_brez_zetona_ne_pride_do_druzine(self, odjemalec: TestClient) -> None:
        """Brez seje ni družine — in tudi ne poti do podatkov."""
        odgovor = odjemalec.get("/quizzes/pending")

        assert odgovor.status_code == 401


class TestPrevzemTujegaId:
    """`POST /materials` z `id`, ki pripada drugi družini (`ADR-029` D)."""

    def test_vrne_409_in_ne_zapise_ne_vrstice_ne_datoteke(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        dodaj_druzino(motor)
        tuja_slika = snov_druzine(motor, slike, DRUGA_ID, UUID_ENA)

        odgovor = odjemalec.post(
            "/materials",
            data={"id": UUID_ENA, "subject": "MAT", "taken_at": "2026-09-04T07:30:00Z"},
            files={"file": ("posnetek.jpg", b"ponaredek", "image/jpeg")},
            headers=telefon.glave,
        )

        assert odgovor.status_code == 409
        assert odgovor.json() == {"detail": SPOROCILO_TUJ_ID}
        with Session(motor) as seja:
            druzine = seja.scalars(select(Material.family_id).where(Material.id == UUID_ENA))
            assert druzine.all() == [DRUGA_ID]
        # Tuja slika nedotaknjena, v mapi Cvek ne ostane nič — ne slika ne ostanek.
        assert tuja_slika.read_bytes() == b"slika-9d4c"
        mapa_cvek = slike / CVEK_ID
        assert [p for p in mapa_cvek.rglob("*") if p.is_file()] == []


class TestObdelavaPoDruzinah:
    """Obdelava in obnova obtičalih gresta po družinah (`ADR-029` B)."""

    def test_obdela_obe_druzini_vsako_iz_svoje_mape(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        dodaj_druzino(motor)
        slika_cvek = snov_druzine(motor, slike, CVEK_ID, UUID_ENA)
        slika_druge = snov_druzine(motor, slike, DRUGA_ID, UUID_DVA)
        klicalec, klicane = klicalec_vrne(uspesen_izid(koliko_vprasanj=5))

        assert obdelaj_cakajoce(tovarna_sej, klicalec, slike) == 2

        assert sorted(klicane) == sorted([slika_cvek, slika_druge])
        with Session(motor) as seja:
            for material_id, family_id in ((UUID_ENA, CVEK_ID), (UUID_DVA, DRUGA_ID)):
                druzine = seja.scalars(
                    select(Question.family_id).where(Question.material_id == material_id)
                ).all()
                # Vprašanja dobijo družino svojega materiala, ne katerekoli.
                assert druzine == [family_id] * 5, material_id

    def test_slika_v_mapi_tuje_druzine_ne_gre_v_klic(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Meja slike je mapa družine, ne koren: tuja slika je „ni na disku"."""
        dodaj_druzino(motor)
        tuja = slike / DRUGA_ID / "tuja.jpg"
        tuja.parent.mkdir()
        tuja.write_bytes(b"tuja")
        with Session(motor) as seja:
            seja.add(
                Material(
                    id=UUID_ENA,
                    family_id=CVEK_ID,
                    subject="MAT",
                    taken_at=datetime(2026, 9, 4, 7, 30, tzinfo=UTC),
                    image_path=str(tuja),
                    status=STATUS_NOV,
                    received_at=datetime(2026, 9, 4, 8, 0, tzinfo=UTC),
                )
            )
            seja.commit()
        klicalec, klicane = klicalec_vrne(uspesen_izid())

        obdelaj_cakajoce(tovarna_sej, klicalec, slike)

        assert klicane == []
        with Session(motor) as seja:
            assert seja.scalar(select(Material.status).where(Material.id == UUID_ENA)) == (
                STATUS_NAPAKA
            )

    def test_obnova_obticalih_zajame_vse_druzine(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        dodaj_druzino(motor)
        snov_druzine(motor, slike, CVEK_ID, UUID_ENA, status=STATUS_V_OBDELAVI)
        snov_druzine(motor, slike, DRUGA_ID, UUID_DVA, status=STATUS_V_OBDELAVI)

        assert obnovi_obticale(tovarna_sej) == 2

        with Session(motor) as seja:
            assert set(seja.scalars(select(Material.status))) == {STATUS_NOV}


class TestMejaMapeVUsmerjevalnikih:
    """Meja mape v usmerjevalnikih je mapa družine, ne koren (kriterij V3-R01).

    Vrstica družine kaže na **obstoječo** datoteko: v mapi družine (kontrola), v
    korenu ali v mapi druge družine. Slika je samo prva. Obstoječi testi meje
    postavijo datoteko v `tmp_path`, zunaj korena, zato meje družine ne ločijo od
    meje korena; to je našel pregledovalec v fazi 7.

    Vsak primer je **eno mesto** v usmerjevalniku, kjer se računa, ali je slika na
    disku — mutacija kateregakoli od njih mora podreti natanko svoj primer.
    """

    KJE = ("lastna_mapa", "koren", "tuja_mapa")

    SLIKA = f'src="/admin/materials/{UUID_ENA}/image"'

    #: ime → (stanje snovi, zahteva, ki stran izriše)
    PRIMERI_STRANI: ClassVar[dict[str, tuple[dict[str, Any], Callable[[TestClient], Any]]]] = {
        "admin.predmet": ({}, lambda o: o.get("/admin/subjects/MAT")),
        "admin.arhiv": ({"arhivirana": True}, lambda o: o.get("/admin/archive")),
        "admin.snov": ({}, lambda o: o.get(f"/admin/materials/{UUID_ENA}")),
        "admin.arhiviranje": ({}, lambda o: o.get(f"/admin/materials/{UUID_ENA}/archive")),
        "admin.brisanje": (
            {"arhivirana": True, "potrjena": True},
            lambda o: o.get(f"/admin/materials/{UUID_ENA}/delete"),
        ),
        "dnevi": ({}, lambda o: o.get("/admin/days")),
        "kvizi.izbirnik": ({}, lambda o: o.get("/admin/quizzes/new?vstop=danes")),
        "kvizi.izbirnik_z_izborom": (
            {},
            lambda o: o.post("/admin/quizzes/new", data={"vstop": "danes"}),
        ),
        "kvizi.predogled_brez_vprasanj": (
            {"vprasanj": 0},
            lambda o: o.post("/admin/quizzes/preview", data={"vstop": "danes", "snov": [UUID_ENA]}),
        ),
    }

    @staticmethod
    def _slika(slike: Path, kje: str) -> Path:
        """Obstoječa datoteka na dani legi."""
        mapa = {"lastna_mapa": slike / CVEK_ID, "koren": slike, "tuja_mapa": slike / DRUGA_ID}[kje]
        mapa.mkdir(parents=True, exist_ok=True)
        pot = mapa / f"{UUID_ENA}.jpg"
        pot.write_bytes(b"slika")
        return pot

    @staticmethod
    def _snov(
        motor: Engine,
        pot: Path,
        *,
        arhivirana: bool = False,
        potrjena: bool = False,
        vprasanj: int = 5,
    ) -> None:
        """Današnja obdelana snov družine Cvek, katere `image_path` je `pot`."""
        zdaj = datetime.now(UTC)
        with Session(motor) as seja:
            material = Material(
                id=UUID_ENA,
                family_id=CVEK_ID,
                subject="MAT",
                taken_at=zdaj,
                image_path=str(pot),
                status=STATUS_PRIPRAVLJEN,
                received_at=zdaj,
                readable=True,
                transcript="Prepis.",
                summary="Povzetek.",
                archived_at=zdaj if arhivirana else None,
                device_deleted_at=zdaj if potrjena else None,
            )
            material.vsa_vprasanja = [
                Question(
                    id=f"meja-v{i}",
                    family_id=CVEK_ID,
                    position=i,
                    question=f"Vprašanje {i}?",
                    answer=f"Odgovor {i}.",
                    subject="MAT",
                    material_taken_at=zdaj,
                )
                for i in range(1, vprasanj + 1)
            ]
            seja.add(material)
            seja.commit()

    @pytest.mark.parametrize("kje", KJE)
    @pytest.mark.parametrize("primer", sorted(PRIMERI_STRANI))
    def test_stran_pokaze_sliko_samo_iz_mape_druzine(
        self, odjemalec: TestClient, motor: Engine, slike: Path, primer: str, kje: str
    ) -> None:
        stanje, zahteva = self.PRIMERI_STRANI[primer]
        self._snov(motor, self._slika(slike, kje), **stanje)

        odgovor = zahteva(odjemalec)

        assert odgovor.status_code == 200, odgovor.text[:300]
        assert (self.SLIKA in odgovor.text) is (kje == "lastna_mapa")

    @pytest.mark.parametrize("kje", KJE)
    def test_rezultat_kviza_pozna_sliko_samo_iz_mape_druzine(
        self, odjemalec: TestClient, motor: Engine, slike: Path, kje: str, telefon: SejaTesta
    ) -> None:
        self._snov(motor, self._slika(slike, kje))
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=3, subject="MAT", vstop="rocna")
        oddano = poslji(odjemalec, [poskus(p) for p in postavke(motor, quiz_id)], telefon)
        assert oddano.status_code == 200, oddano.text

        besedilo = odjemalec.get(f"/admin/quizzes/{quiz_id}").text

        assert ("slike ni na disku" in besedilo) is (kje != "lastna_mapa")

    @pytest.mark.parametrize("kje", KJE)
    def test_strezenje_slike_samo_iz_mape_druzine(
        self, odjemalec: TestClient, motor: Engine, slike: Path, kje: str
    ) -> None:
        self._snov(motor, self._slika(slike, kje))

        odgovor = odjemalec.get(f"/admin/materials/{UUID_ENA}/image")

        assert odgovor.status_code == (200 if kje == "lastna_mapa" else 404)

    @pytest.mark.parametrize("kje", KJE)
    def test_ciscenje_slike_brise_samo_v_mapi_druzine(
        self, odjemalec: TestClient, motor: Engine, slike: Path, kje: str
    ) -> None:
        pot = self._slika(slike, kje)
        self._snov(motor, pot, arhivirana=True)

        odgovor = odjemalec.post(f"/admin/materials/{UUID_ENA}/purge-image", follow_redirects=False)

        assert odgovor.status_code == 303
        assert pot.exists() is (kje != "lastna_mapa")

    @pytest.mark.parametrize("kje", KJE)
    def test_dokoncno_brisanje_brise_datoteko_samo_v_mapi_druzine(
        self, odjemalec: TestClient, motor: Engine, slike: Path, kje: str
    ) -> None:
        pot = self._slika(slike, kje)
        self._snov(motor, pot, arhivirana=True, potrjena=True)

        odgovor = odjemalec.post(f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False)

        assert odgovor.status_code == 303
        assert pot.exists() is (kje != "lastna_mapa")
