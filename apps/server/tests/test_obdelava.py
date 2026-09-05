"""Testi obdelave enega zapisa in vrste čakajočih.

Klicalec je vedno lažen: obdelava ga sprejme kot argument in ne ve, ali za njim
stoji OpenAI ali funkcija iz tega modula. Prav to je razlog, da je klic v
`app/vision.py` in ne tu (odločitev 2 v `docs/plan/V1-R03.md`).

Testi repozitorija (prevzem, zapis izida, vrnitev v vrsto) so tu in ne v
svoji datoteki, ker so to koraki iste poti in se berejo skupaj.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import IzidObdelave, MaterialsRepository, VprasanjeZaZapis
from app.models import (
    STATUS_NAPAKA,
    STATUS_NOV,
    STATUS_PRIPRAVLJEN,
    STATUS_V_OBDELAVI,
    Material,
    Question,
)
from app.obdelava import obdelaj_cakajoce, obdelaj_zapis
from app.vision import (
    IzidKlica,
    Klicalec,
    NapakaObdelave,
    VprasanjeModela,
    VsebinaOdgovora,
)

UUID_ENA = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
UUID_DVA = "a1b2c3d4-e5f6-4789-abcd-ef0123456789"


def zapisi(
    motor: Engine,
    slike: Path,
    material_id: str = UUID_ENA,
    *,
    status: str = STATUS_NOV,
    taken_at: str = "2026-09-04T07:30:00+00:00",
    vsebina: bytes | None = b"slika",
) -> Path:
    """Ustvari zapis in (privzeto) njegovo datoteko; vrne pot do slike."""
    pot = slike / f"{material_id}.jpg"
    if vsebina is not None:
        pot.write_bytes(vsebina)

    with Session(motor) as seja:
        seja.add(
            Material(
                id=material_id,
                subject="MAT",
                taken_at=datetime.fromisoformat(taken_at),
                image_path=str(pot),
                status=status,
                received_at=datetime(2026, 9, 4, 8, 0, tzinfo=UTC),
            )
        )
        seja.commit()

    return pot


def preberi(motor: Engine, material_id: str = UUID_ENA) -> Material:
    """Zapis iz baze, s tem, kar je v njej res."""
    with Session(motor) as seja:
        material = seja.get(Material, material_id)
        assert material is not None
        # Vprašanja se preberejo, dokler je seja odprta.
        len(material.questions)
        return material


def stevilo_vprasanj(motor: Engine) -> int:
    with Session(motor) as seja:
        return seja.scalar(select(func.count()).select_from(Question)) or 0


def uspesen_izid(*, readable: bool = True, koliko_vprasanj: int = 5) -> IzidKlica:
    """Kar bi vrnil model za berljivo stran."""
    vprasanja = tuple(
        VprasanjeModela(question=f"Vprašanje {i}?", answer=f"Odgovor {i}.")
        for i in range(1, koliko_vprasanj + 1)
    )
    return IzidKlica(
        vsebina=VsebinaOdgovora(
            readable=readable,
            transcript="Delci snovi se gibljejo." if readable else "",
            summary="Zgradba snovi." if readable else "",
            questions=vprasanja if readable else (),
        ),
        prompt="POSLANI PROMPT",
        raw_response=json.dumps({"readable": readable}),
        model="gpt-4.1-2025-04-14",
        input_tokens=1500,
        output_tokens=2000,
    )


def klicalec_vrne(izid: IzidKlica) -> tuple[Klicalec, list[Path]]:
    """Klicalec, ki vedno uspe, in seznam poti, s katerimi je bil klican."""
    klicane: list[Path] = []

    def klicalec(pot: Path) -> IzidKlica:
        klicane.append(pot)
        return izid

    return klicalec, klicane


class TestPrevzem:
    """`prevzemi_za_obdelavo` — pogojni `UPDATE`."""

    def test_zapis_v_new_se_prevzame(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        zapisi(motor, slike)

        with tovarna_sej() as seja:
            assert MaterialsRepository(seja).prevzemi_za_obdelavo(UUID_ENA) is True

        assert preberi(motor).status == STATUS_V_OBDELAVI

    def test_drugi_prevzem_istega_zapisa_ne_uspe(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Jedro varovala pred dvojno obdelavo: zmaga natanko en prevzemnik.

        Če bi bil prevzem branje s poznejšim pisanjem, bi bila oba `True` in
        ista slika bi bila plačana dvakrat.
        """
        zapisi(motor, slike)

        with tovarna_sej() as prva, tovarna_sej() as druga:
            assert MaterialsRepository(prva).prevzemi_za_obdelavo(UUID_ENA) is True
            assert MaterialsRepository(druga).prevzemi_za_obdelavo(UUID_ENA) is False

    @pytest.mark.parametrize("status", [STATUS_V_OBDELAVI, STATUS_PRIPRAVLJEN, STATUS_NAPAKA])
    def test_zapis_izven_new_se_ne_prevzame(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session], status: str
    ) -> None:
        zapisi(motor, slike, status=status)

        with tovarna_sej() as seja:
            assert MaterialsRepository(seja).prevzemi_za_obdelavo(UUID_ENA) is False

    def test_neznan_zapis_se_ne_prevzame(self, tovarna_sej: sessionmaker[Session]) -> None:
        with tovarna_sej() as seja:
            assert MaterialsRepository(seja).prevzemi_za_obdelavo("ni-ga") is False


class TestVrstaCakajocih:
    """`seznam_novih` — kaj čaka in v kakšnem vrstnem redu."""

    def test_pobere_samo_new(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        zapisi(motor, slike, UUID_ENA, status=STATUS_NOV)
        zapisi(motor, slike, UUID_DVA, status=STATUS_PRIPRAVLJEN)

        with tovarna_sej() as seja:
            cakajoci = [m.id for m in MaterialsRepository(seja).seznam_novih()]

        assert cakajoci == [UUID_ENA]

    def test_najstarejsa_slika_je_prva(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Obratno kot zgodovina: v vrsti naj najstarejši posnetek ne čaka najdlje."""
        zapisi(motor, slike, UUID_ENA, taken_at="2026-09-04T10:00:00+00:00")
        zapisi(motor, slike, UUID_DVA, taken_at="2026-09-04T07:00:00+00:00")

        with tovarna_sej() as seja:
            cakajoci = [m.id for m in MaterialsRepository(seja).seznam_novih()]

        assert cakajoci == [UUID_DVA, UUID_ENA]


class TestSrecnaPot:
    """Obdelava, ki uspe."""

    def test_zapise_izid_in_sled(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        pot = zapisi(motor, slike)
        klicalec, klicane = klicalec_vrne(uspesen_izid())

        assert obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA) is True

        material = preberi(motor)
        assert material.status == STATUS_PRIPRAVLJEN
        assert material.readable is True
        assert material.transcript == "Delci snovi se gibljejo."
        assert material.summary == "Zgradba snovi."
        assert material.prompt == "POSLANI PROMPT"
        assert material.raw_response is not None
        assert material.model == "gpt-4.1-2025-04-14"
        assert material.input_tokens == 1500
        assert material.output_tokens == 2000
        assert material.error is None
        assert klicane == [pot]

    def test_vprasanja_dobijo_svoje_vrstice_in_zaporedje(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """`V1-R05` veže ocene na `question_id`, zato ima vprašanje svojo vrstico."""
        zapisi(motor, slike)
        klicalec, _ = klicalec_vrne(uspesen_izid(koliko_vprasanj=7))

        obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)

        material = preberi(motor)
        assert [v.position for v in material.questions] == [1, 2, 3, 4, 5, 6, 7]
        assert material.questions[0].question == "Vprašanje 1?"
        assert material.questions[0].answer == "Odgovor 1."
        assert len({v.id for v in material.questions}) == 7

    def test_neberljiva_slika_je_ready_brez_vprasanj(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Klic je uspel in bil plačan — to ni napaka obdelave."""
        zapisi(motor, slike)
        klicalec, _ = klicalec_vrne(uspesen_izid(readable=False))

        obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)

        material = preberi(motor)
        assert material.status == STATUS_PRIPRAVLJEN
        assert material.readable is False
        assert material.questions == []
        # Sled se shrani tudi tu; brez nje ne bi vedeli, kaj je model vrnil.
        assert material.model == "gpt-4.1-2025-04-14"
        assert material.input_tokens == 1500


class TestNapake:
    """Obdelava, ki ne uspe. Zapis mora vedno končati v `failed`, nikoli v `processing`."""

    def test_napaka_klica_gre_v_failed_s_sledjo(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        zapisi(motor, slike)

        def klicalec(pot: Path) -> IzidKlica:
            raise NapakaObdelave(
                "Storitev OpenAI je zavrnila ključ (HTTP 401).",
                raw_response="{}",
                model="gpt-4.1",
                input_tokens=10,
                output_tokens=0,
            )

        obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)

        material = preberi(motor)
        assert material.status == STATUS_NAPAKA
        assert material.error is not None
        assert "401" in material.error
        assert material.raw_response == "{}"
        assert material.input_tokens == 10

    def test_nepricakovana_izjema_gre_v_failed_z_berljivim_sporocilom(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Surova sled izjeme ni vsebina za operaterja (merilo dokončanosti)."""
        zapisi(motor, slike)

        def klicalec(pot: Path) -> IzidKlica:
            raise ZeroDivisionError("delitev z nic")

        obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)

        material = preberi(motor)
        assert material.status == STATUS_NAPAKA
        assert material.error is not None
        assert "nepričakovane napake" in material.error
        assert "delitev z nic" not in material.error

    def test_manjkajoca_datoteka_ne_sprozi_klica(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Za sliko, ki je ni, ne plačamo."""
        zapisi(motor, slike, vsebina=None)
        klicalec, klicane = klicalec_vrne(uspesen_izid())

        obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)

        assert klicane == []
        material = preberi(motor)
        assert material.status == STATUS_NAPAKA
        assert material.error is not None
        assert "ni na disku" in material.error

    def test_datoteka_izven_mape_slik_ne_sprozi_klica(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session], tmp_path: Path
    ) -> None:
        """Ista meja kot pri streženju slike na admin strani."""
        tujec = tmp_path / "tujec.jpg"
        tujec.write_bytes(b"nekaj")
        with Session(motor) as seja:
            seja.add(
                Material(
                    id=UUID_ENA,
                    subject="MAT",
                    taken_at=datetime(2026, 9, 4, 7, 30, tzinfo=UTC),
                    image_path=str(tujec),
                    status=STATUS_NOV,
                    received_at=datetime(2026, 9, 4, 8, 0, tzinfo=UTC),
                )
            )
            seja.commit()
        klicalec, klicane = klicalec_vrne(uspesen_izid())

        obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)

        assert klicane == []
        assert preberi(motor).status == STATUS_NAPAKA

    def test_zapis_nikoli_ne_ostane_v_processing(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Mutacijski test: če bi obdelava napako požrla brez zapisa izida,
        bi zapis obtičal v `processing` in ga ne bi pobral nihče več."""
        zapisi(motor, slike)

        def klicalec(pot: Path) -> IzidKlica:
            raise NapakaObdelave("karkoli")

        obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)

        assert preberi(motor).status != STATUS_V_OBDELAVI


class TestVrstaSePremika:
    """`obdelaj_cakajoce` — več zapisov v enem obhodu."""

    def test_obdela_vse_cakajoce(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        zapisi(motor, slike, UUID_ENA)
        zapisi(motor, slike, UUID_DVA)
        klicalec, klicane = klicalec_vrne(uspesen_izid())

        assert obdelaj_cakajoce(tovarna_sej, klicalec, slike) == 2

        assert len(klicane) == 2
        assert preberi(motor, UUID_ENA).status == STATUS_PRIPRAVLJEN
        assert preberi(motor, UUID_DVA).status == STATUS_PRIPRAVLJEN

    def test_napaka_pri_prvem_zapisu_ne_ustavi_drugega(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Robni primer iz `v1.md`: worker se ne ustavi.

        Prvi zapis je starejši, torej gre v vrsti prvi.
        """
        zapisi(motor, slike, UUID_ENA, taken_at="2026-09-04T07:00:00+00:00")
        zapisi(motor, slike, UUID_DVA, taken_at="2026-09-04T09:00:00+00:00")
        uspeh = uspesen_izid()

        def klicalec(pot: Path) -> IzidKlica:
            if pot.name.startswith(UUID_ENA):
                raise NapakaObdelave("prvi je padel")
            return uspeh

        obdelaj_cakajoce(tovarna_sej, klicalec, slike)

        assert preberi(motor, UUID_ENA).status == STATUS_NAPAKA
        assert preberi(motor, UUID_DVA).status == STATUS_PRIPRAVLJEN

    def test_zapisov_izven_new_se_ne_dotakne(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        zapisi(motor, slike, UUID_ENA, status=STATUS_PRIPRAVLJEN)
        klicalec, klicane = klicalec_vrne(uspesen_izid())

        assert obdelaj_cakajoce(tovarna_sej, klicalec, slike) == 0
        assert klicane == []


class TestVrnitevVVrsto:
    """`vrni_v_vrsto` — kar stoji za gumbom „Pošlji v obdelavo"."""

    def test_zavrze_ves_prejsnji_izid(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """ADR-009: material ima največ en niz vprašanj in nikoli tujega rezultata."""
        zapisi(motor, slike)
        klicalec, _ = klicalec_vrne(uspesen_izid())
        obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)
        assert stevilo_vprasanj(motor) == 5

        with tovarna_sej() as seja:
            assert MaterialsRepository(seja).vrni_v_vrsto(UUID_ENA) is True

        material = preberi(motor)
        assert material.status == STATUS_NOV
        assert material.transcript is None
        assert material.summary is None
        assert material.readable is None
        assert material.prompt is None
        assert material.raw_response is None
        assert material.model is None
        assert material.input_tokens is None
        assert material.output_tokens is None
        assert material.error is None
        # Vprašanja izginejo iz tabele, ne le iz zveze.
        assert stevilo_vprasanj(motor) == 0

    def test_dela_tudi_iz_failed(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        zapisi(motor, slike, status=STATUS_NAPAKA)
        with tovarna_sej() as seja:
            MaterialsRepository(seja).zapisi_izid(
                UUID_ENA, IzidObdelave(status=STATUS_NAPAKA, error="prej je padlo")
            )

        with tovarna_sej() as seja:
            assert MaterialsRepository(seja).vrni_v_vrsto(UUID_ENA) is True

        material = preberi(motor)
        assert material.status == STATUS_NOV
        assert material.error is None

    def test_zapisa_v_obdelavi_se_ne_dotakne(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Tam pravkar teče klic; njegov izid bi prišel čez to, kar bi počistili."""
        zapisi(motor, slike, status=STATUS_V_OBDELAVI)

        with tovarna_sej() as seja:
            assert MaterialsRepository(seja).vrni_v_vrsto(UUID_ENA) is False

        assert preberi(motor).status == STATUS_V_OBDELAVI

    def test_neznanega_zapisa_ni(self, tovarna_sej: sessionmaker[Session]) -> None:
        with tovarna_sej() as seja:
            assert MaterialsRepository(seja).vrni_v_vrsto("ni-ga") is False

    def test_po_vrnitvi_gre_zapis_znova_skozi_obdelavo(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Cel krog: obdelan zapis se po gumbu obdela znova in dobi nova vprašanja."""
        zapisi(motor, slike)
        klicalec, klicane = klicalec_vrne(uspesen_izid(koliko_vprasanj=5))
        obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)

        with tovarna_sej() as seja:
            MaterialsRepository(seja).vrni_v_vrsto(UUID_ENA)

        drugi, _ = klicalec_vrne(uspesen_izid(koliko_vprasanj=9))
        assert obdelaj_cakajoce(tovarna_sej, drugi, slike) == 1

        material = preberi(motor)
        assert material.status == STATUS_PRIPRAVLJEN
        assert len(material.questions) == 9
        # Stara vprašanja niso ostala poleg novih.
        assert stevilo_vprasanj(motor) == 9
        assert len(klicane) == 1


class TestObnovitevObticalih:
    """`obnovi_obticale` — zapis, ki ga je prekinil ponovni zagon strežnika."""

    def test_processing_gre_nazaj_v_new(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        zapisi(motor, slike, status=STATUS_V_OBDELAVI)

        with tovarna_sej() as seja:
            assert MaterialsRepository(seja).obnovi_obticale() == 1

        assert preberi(motor).status == STATUS_NOV

    def test_drugih_stanj_se_ne_dotakne(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        zapisi(motor, slike, UUID_ENA, status=STATUS_PRIPRAVLJEN)
        zapisi(motor, slike, UUID_DVA, status=STATUS_NAPAKA)

        with tovarna_sej() as seja:
            assert MaterialsRepository(seja).obnovi_obticale() == 0

        assert preberi(motor, UUID_ENA).status == STATUS_PRIPRAVLJEN
        assert preberi(motor, UUID_DVA).status == STATUS_NAPAKA

    def test_obnovljeni_zapis_gre_v_obdelavo(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Smisel obnovitve: zapis mora spet biti dosegljiv vrsti."""
        zapisi(motor, slike, status=STATUS_V_OBDELAVI)
        klicalec, _ = klicalec_vrne(uspesen_izid())

        with tovarna_sej() as seja:
            MaterialsRepository(seja).obnovi_obticale()

        assert obdelaj_cakajoce(tovarna_sej, klicalec, slike) == 1
        assert preberi(motor).status == STATUS_PRIPRAVLJEN


class TestZapisIzida:
    """`zapisi_izid` — podrobnosti, ki jih poti zgoraj ne pokažejo."""

    def test_neznan_zapis_vrne_false(self, tovarna_sej: sessionmaker[Session]) -> None:
        with tovarna_sej() as seja:
            assert (
                MaterialsRepository(seja).zapisi_izid(
                    "ni-ga", IzidObdelave(status=STATUS_NAPAKA)
                )
                is False
            )

    def test_ponoven_zapis_ne_podvoji_vprasanj(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Material ima ob vsakem trenutku največ en niz vprašanj (ADR-009)."""
        zapisi(motor, slike)
        izid = IzidObdelave(
            status=STATUS_PRIPRAVLJEN,
            readable=True,
            vprasanja=(VprasanjeZaZapis(question="V?", answer="O."),),
        )

        with tovarna_sej() as seja:
            MaterialsRepository(seja).zapisi_izid(UUID_ENA, izid)
        with tovarna_sej() as seja:
            MaterialsRepository(seja).zapisi_izid(UUID_ENA, izid)

        assert stevilo_vprasanj(motor) == 1
