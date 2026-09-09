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
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app import db
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
        # Vse tri zbirke vprašanj se preberejo, dokler je seja odprta.
        len(material.vsa_vprasanja)
        len(material.veljavna_vprasanja)
        len(material.upokojena_vprasanja)
        return material


def stevilo_vprasanj(motor: Engine) -> int:
    """Koliko vrstic je v tabeli `questions` — veljavnih in upokojenih skupaj."""
    with Session(motor) as seja:
        return seja.scalar(select(func.count()).select_from(Question)) or 0


def stevilo_upokojenih(motor: Engine) -> int:
    """Koliko vrstic ima postavljen `retired_at`.

    Ločeno od `stevilo_vprasanj` zato, ker je od V2-R05 razlika med „vrstice
    ni" in „vrstica je, a ni veljavna" celotna vsebina zahteve
    (`docs/odlocitve/ADR-015`).
    """
    with Session(motor) as seja:
        return (
            seja.scalar(
                select(func.count())
                .select_from(Question)
                .where(Question.retired_at.is_not(None))
            )
            or 0
        )


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
        veljavna = material.veljavna_vprasanja
        assert [v.position for v in veljavna] == [1, 2, 3, 4, 5, 6, 7]
        assert veljavna[0].question == "Vprašanje 1?"
        assert veljavna[0].answer == "Odgovor 1."
        assert len({v.id for v in veljavna}) == 7

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
        assert material.veljavna_vprasanja == []
        # Snov brez zgodovine: ni ne veljavnih ne upokojenih vprašanj. Prazen
        # seznam sam po sebi ne pove, katero od obojega je (`ADR-015`).
        assert material.upokojena_vprasanja == []
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
                prompt="POSLANI PROMPT",
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
        assert material.model == "gpt-4.1"
        assert material.input_tokens == 10
        assert material.output_tokens == 0
        # Kriterij zahteva sled ob **vsakem** izidu. Prav pri „model je vrnil
        # neveljaven JSON" je vprašanje „kaj smo mu poslali" glavno.
        assert material.prompt == "POSLANI PROMPT"

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

    def test_zavrze_ves_prejsnji_izid_vprasanja_pa_upokoji(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """ADR-009 velja naprej za izid; za vprašanja ga nadomesti ADR-015.

        Do V2-R05 je ta test zahteval, da vprašanja iz tabele **izginejo**. To
        ni oslabitev testa, ampak sprememba pogodbe: `docs/odlocitve/ADR-015`
        nadomesti odločitev A1 iz `ADR-009`, ker bo kviz `V2-R01` kazal na
        `question_id` in bi ga gumb sicer tiho razbil.

        Preostali del izida (prepis, povzetek, sled) se še naprej zavrže — in
        prav to je razlog, da se vprašanja upokojijo že tu in ne šele ob novem
        izidu: snov sicer ne bi smela kazati starih vprašanj ob praznem
        prepisu.
        """
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
        # Nobena vrstica ne izgine; vseh pet je samo še upokojenih.
        assert stevilo_vprasanj(motor) == 5
        assert stevilo_upokojenih(motor) == 5
        assert material.veljavna_vprasanja == []
        assert len(material.upokojena_vprasanja) == 5

    def test_vsa_vprasanja_ene_serije_dobijo_isti_zig(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Serija se prepozna po skupnem `retired_at` in po ničemer drugem.

        Dodatnega stolpca za oznako serije `ADR-015` namenoma nima, zato je ta
        enakost edino, kar serijo drži skupaj. Upokojitev, ki bi tekla vrstico
        za vrstico in vsakič vprašala za čas znova, bi eno serijo razbila na
        pet enočlanskih in `V2-R04` bi jih štela kot pet obdelav.
        """
        zapisi(motor, slike)
        klicalec, _ = klicalec_vrne(uspesen_izid())
        obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)

        with tovarna_sej() as seja:
            MaterialsRepository(seja).vrni_v_vrsto(UUID_ENA)

        zigi = {v.retired_at for v in preberi(motor).upokojena_vprasanja}
        assert len(zigi) == 1
        assert zigi.pop() is not None

    def test_druga_upokojitev_ne_premakne_ziga_prve(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Vsaka serija ima svoj čas upokojitve; prejšnji se ne prepiše.

        Pogoj `retired_at IS NULL` v `_upokoji_vprasanja` je edino, kar to
        drži. Brez njega bi druga ponovna obdelava vse dosedanje serije zlepila
        v eno in zgodovina obdelav te snovi bi izginila — isti razred napake
        kot pri `arhiviraj`, ki časa arhiviranja tudi ne premakne.
        """
        zapisi(motor, slike)
        prvi, _ = klicalec_vrne(uspesen_izid(koliko_vprasanj=5))
        obdelaj_zapis(tovarna_sej, prvi, slike, UUID_ENA)
        with tovarna_sej() as seja:
            MaterialsRepository(seja).vrni_v_vrsto(UUID_ENA)
        prva_serija = {v.id: v.retired_at for v in preberi(motor).upokojena_vprasanja}
        assert len(prva_serija) == 5

        drugi, _ = klicalec_vrne(uspesen_izid(koliko_vprasanj=3))
        assert obdelaj_cakajoce(tovarna_sej, drugi, slike) == 1
        with tovarna_sej() as seja:
            MaterialsRepository(seja).vrni_v_vrsto(UUID_ENA)

        assert stevilo_vprasanj(motor) == 8
        assert stevilo_upokojenih(motor) == 8
        po_drugi = {v.id: v.retired_at for v in preberi(motor).upokojena_vprasanja}
        # Prva serija ima še vedno natanko svoj žig.
        for id_vprasanja, zig in prva_serija.items():
            assert po_drugi[id_vprasanja] == zig
        # In serij je res dvoje, ne ena zlepljena.
        assert len(set(po_drugi.values())) == 2

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
        """Regresijski test iz kriterija V2-R05 — cel krog čez dve obdelavi.

        Do V2-R05 je ta test zahteval, da je v tabeli po drugi obdelavi devet
        vrstic. Zdaj jih je štirinajst in devet je veljavnih: `ADR-015` pravi,
        da se stara serija upokoji in ne izbriše.

        `ADR-015` ta test označi za obveznega in ne priporočenega. Je edini, ki
        pozabljen filter `retired_at IS NULL` sploh lahko ujame — nad svežo
        bazo ima material natanko eno serijo in tam je taka napaka nevidna.
        """
        zapisi(motor, slike)
        klicalec, klicane = klicalec_vrne(uspesen_izid(koliko_vprasanj=5))
        obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)
        stara = {v.id for v in preberi(motor).veljavna_vprasanja}

        with tovarna_sej() as seja:
            MaterialsRepository(seja).vrni_v_vrsto(UUID_ENA)

        drugi, _ = klicalec_vrne(uspesen_izid(koliko_vprasanj=9))
        assert obdelaj_cakajoce(tovarna_sej, drugi, slike) == 1

        material = preberi(motor)
        assert material.status == STATUS_PRIPRAVLJEN
        # Vrne se samo nova serija, oštevilčena od 1 naprej.
        veljavna = material.veljavna_vprasanja
        assert len(veljavna) == 9
        assert [v.position for v in veljavna] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
        assert stara.isdisjoint({v.id for v in veljavna})
        # Stara serija je še v bazi, z `retired_at`.
        assert stevilo_vprasanj(motor) == 14
        assert stevilo_upokojenih(motor) == 5
        assert {v.id for v in material.upokojena_vprasanja} == stara
        assert len(klicane) == 1

    def test_neuspesna_ponovna_obdelava_vprasanj_ne_vrne(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Po neuspelem drugem klicu ostane snov brez veljavnih vprašanj.

        Upokojitev se ne razveljavi. Tako je bilo tudi prej — brisanje je bilo
        prav tako nepovratno — le da je zdaj prejšnja serija še vedno v bazi in
        s tem kviz, ki nanjo kaže, nedotaknjen (`ADR-015`).
        """
        zapisi(motor, slike)
        prvi, _ = klicalec_vrne(uspesen_izid(koliko_vprasanj=5))
        obdelaj_zapis(tovarna_sej, prvi, slike, UUID_ENA)

        with tovarna_sej() as seja:
            MaterialsRepository(seja).vrni_v_vrsto(UUID_ENA)

        def pade(pot: Path) -> IzidKlica:
            raise NapakaObdelave("Storitev OpenAI ni odgovorila.")

        assert obdelaj_cakajoce(tovarna_sej, pade, slike) == 1

        material = preberi(motor)
        assert material.status == STATUS_NAPAKA
        assert material.veljavna_vprasanja == []
        assert len(material.upokojena_vprasanja) == 5
        assert stevilo_vprasanj(motor) == 5

    def test_neberljiva_ponovna_obdelava_vprasanj_ne_vrne(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Enako, kadar je drugi klic uspel, a slika ni bila berljiva.

        Zapis je `ready` in brez veljavnih vprašanj. Brez števca upokojenih bi
        bila ta snov na admin strani videti enako kot snov, ki vprašanj ni
        imela nikoli.
        """
        zapisi(motor, slike)
        prvi, _ = klicalec_vrne(uspesen_izid(koliko_vprasanj=5))
        obdelaj_zapis(tovarna_sej, prvi, slike, UUID_ENA)

        with tovarna_sej() as seja:
            MaterialsRepository(seja).vrni_v_vrsto(UUID_ENA)

        drugi, _ = klicalec_vrne(uspesen_izid(readable=False))
        assert obdelaj_cakajoce(tovarna_sej, drugi, slike) == 1

        material = preberi(motor)
        assert material.status == STATUS_PRIPRAVLJEN
        assert material.readable is False
        assert material.veljavna_vprasanja == []
        assert len(material.upokojena_vprasanja) == 5


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

    def test_ponoven_zapis_ne_podvoji_veljavnih_vprasanj(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Material ima ob vsakem trenutku največ en niz **veljavnih** vprašanj.

        Trditev iz `ADR-009` velja naprej; `ADR-015` ji je spremenil samo pomen
        besede „veljaven". Do V2-R05 je ta test zahteval eno samo vrstico v
        tabeli — zdaj sta dve in veljavna je ena.

        Zapis izida upokoji tudi mimo gumba: ta pot lahko teče nad zapisom, ki
        veljavna vprašanja že ima, in takrat mora pravilo držati enako.
        """
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

        assert len(preberi(motor).veljavna_vprasanja) == 1
        assert stevilo_vprasanj(motor) == 2
        assert stevilo_upokojenih(motor) == 1

    def test_upokojitev_in_nova_serija_sta_ena_transakcija(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Če vstavljanje nove serije pade, se upokojitev ne obdrži.

        Sicer bi obstajalo okno, v katerem ima material upokojena vprašanja in
        nobenega veljavnega — in izbirnik `V2-R01` bi tako snov videl kot
        „obdelana, a brez vprašanj" za vedno, brez načina, da se to popravi.
        Zato `_upokoji_vprasanja` ne commita sam.

        Napaka se vrine med upokojitev in vstavljanje tako, da drugi `uuid4`
        vrže izjemo. Če bi bila upokojitev svoja transakcija, bi jo zapiranje
        seje pustilo pri miru in vprašanje bi ostalo upokojeno.
        """
        zapisi(motor, slike)
        prvi = IzidObdelave(
            status=STATUS_PRIPRAVLJEN,
            readable=True,
            vprasanja=(VprasanjeZaZapis(question="V1?", answer="O1."),),
        )
        with tovarna_sej() as seja:
            MaterialsRepository(seja).zapisi_izid(UUID_ENA, prvi)

        pravi_uuid4 = db.uuid4
        preostali = [1]

        def pade_pri_drugem() -> Any:
            if preostali:
                preostali.pop()
                return pravi_uuid4()
            raise RuntimeError("Baza je med vstavljanjem odpovedala.")

        monkeypatch.setattr(db, "uuid4", pade_pri_drugem)

        drugi = IzidObdelave(
            status=STATUS_PRIPRAVLJEN,
            readable=True,
            vprasanja=(
                VprasanjeZaZapis(question="V2?", answer="O2."),
                VprasanjeZaZapis(question="V3?", answer="O3."),
            ),
        )
        with pytest.raises(RuntimeError):  # noqa: SIM117
            with tovarna_sej() as seja:
                MaterialsRepository(seja).zapisi_izid(UUID_ENA, drugi)

        # Nič se ni premaknilo: prvo vprašanje je še vedno veljavno in samo.
        material = preberi(motor)
        assert len(material.veljavna_vprasanja) == 1
        assert material.veljavna_vprasanja[0].question == "V1?"
        assert stevilo_vprasanj(motor) == 1
        assert stevilo_upokojenih(motor) == 0

    def test_upokojitev_osvezi_ze_naloziene_predmete(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Bralec, ki vprašanja prebere pred upokojitvijo, ne sme videti starega stanja.

        `UPDATE` gre mimo seje, zato bi predmeti `Question`, naloženi prej v
        isti seji, brez sinhronizacije še vedno kazali `retired_at = None`.
        Nad svežo bazo se to nikoli ne pokaže — material ima takrat eno samo
        serijo in nihče je ne bere dvakrat. Prav tak razred napake `ADR-015`
        našteva kot ceno te odločitve.
        """
        zapisi(motor, slike)
        izid = IzidObdelave(
            status=STATUS_PRIPRAVLJEN,
            readable=True,
            vprasanja=(VprasanjeZaZapis(question="V?", answer="O."),),
        )
        with tovarna_sej() as seja:
            MaterialsRepository(seja).zapisi_izid(UUID_ENA, izid)

        with tovarna_sej() as seja:
            repozitorij = MaterialsRepository(seja)
            material = repozitorij.poisci(UUID_ENA)
            assert material is not None
            # Bralec vprašanja prebere **pred** upokojitvijo in jih obdrži.
            prebrana = list(material.veljavna_vprasanja)
            assert [v.retired_at for v in prebrana] == [None]

            repozitorij.vrni_v_vrsto(UUID_ENA)

            assert prebrana[0].retired_at is not None

    def test_vprasanje_dobi_izvor_svojega_materiala(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Predmet in čas posnetka se prepišeta v vprašanje ob nastanku.

        Denormalizirano namenoma: material se sme dokončno izbrisati, vprašanje
        pa mora tudi potem povedati, iz katere snovi in katerega dne je
        (`docs/odlocitve/ADR-012`). Brez tega testa bi bili obe polji lahko
        tiho `NULL` in nihče tega ne bi opazil do dneva, ko bi bilo prepozno.
        """
        zapisi(motor, slike, taken_at="2026-09-04T07:30:00+00:00")

        with tovarna_sej() as seja:
            MaterialsRepository(seja).zapisi_izid(
                UUID_ENA,
                IzidObdelave(
                    status=STATUS_PRIPRAVLJEN,
                    readable=True,
                    vprasanja=(VprasanjeZaZapis(question="V?", answer="O."),),
                ),
            )

        with Session(motor) as seja:
            vprasanje = seja.scalars(select(Question)).one()
            assert vprasanje.subject == "MAT"
            assert vprasanje.material_taken_at is not None
            # SQLite pasu ne vrne, Postgres ga — primerjamo, kar je skupno.
            assert vprasanje.material_taken_at.replace(tzinfo=None) == datetime(
                2026, 9, 4, 7, 30
            )

    def test_izvor_prezivi_brisanje_materiala(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Po dokončnem brisanju materiala vprašanje še vedno ve, od kod je."""
        zapisi(motor, slike)

        with tovarna_sej() as seja:
            repozitorij = MaterialsRepository(seja)
            repozitorij.zapisi_izid(
                UUID_ENA,
                IzidObdelave(
                    status=STATUS_PRIPRAVLJEN,
                    readable=True,
                    vprasanja=(VprasanjeZaZapis(question="V?", answer="O."),),
                ),
            )

        with Session(motor) as seja:
            material = seja.get(Material, UUID_ENA)
            assert material is not None
            seja.delete(material)
            seja.commit()

        with Session(motor) as seja:
            vprasanje = seja.scalars(select(Question)).one()
            assert vprasanje.material_id is None
            assert vprasanje.subject == "MAT"
            assert vprasanje.material_taken_at is not None


class TestSledJeCelaObVsakemIzidu:
    """Kriterij: prompt, surov odgovor, ime modela in oba števca — vedno.

    Ločen razred, ker gre za trditev o **vseh** poteh izida hkrati; posamezen
    test zgoraj vsakič preveri le svojo.
    """

    def test_uspeh_zapise_vseh_pet_polj(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        zapisi(motor, slike)
        klicalec, _ = klicalec_vrne(uspesen_izid())

        obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)

        material = preberi(motor)
        assert material.prompt == "POSLANI PROMPT"
        assert material.raw_response is not None
        assert material.model is not None
        assert material.input_tokens is not None
        assert material.output_tokens is not None

    def test_napaka_po_klicu_zapise_vseh_pet_polj(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Napaka, do katere pride po poslani zahtevi. Klic je bil plačan."""
        zapisi(motor, slike)

        def klicalec(pot: Path) -> IzidKlica:
            raise NapakaObdelave(
                "Model ni vrnil veljavnega JSON.",
                prompt="POSLANI PROMPT",
                raw_response="{to ni json",
                model="gpt-4.1-2025-04-14",
                input_tokens=1500,
                output_tokens=12,
            )

        obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)

        material = preberi(motor)
        assert material.prompt == "POSLANI PROMPT"
        assert material.raw_response == "{to ni json"
        assert material.model == "gpt-4.1-2025-04-14"
        assert material.input_tokens == 1500
        assert material.output_tokens == 12

    def test_brez_klica_sledi_ni_in_se_ne_izmislja(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Manjkajoča slika pomeni, da zahteva ni bila poslana.

        Prazna sled je tu resnica, ne pomanjkljivost — prompt, ki ni bil nikoli
        poslan, v reviziji nima kaj iskati.
        """
        zapisi(motor, slike, vsebina=None)
        klicalec, klicane = klicalec_vrne(uspesen_izid())

        obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)

        material = preberi(motor)
        assert klicane == []
        assert material.prompt is None
        assert material.raw_response is None
        assert material.model is None

    def test_izjema_pri_dostopu_do_diska_ne_pusti_zapisa_v_obdelavi(
        self,
        motor: Engine,
        slike: Path,
        tovarna_sej: sessionmaker[Session],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Zapis je prevzet, nato pade nekaj, kar ni klic modela.

        `Path.is_file` pri zavrnjenem dostopu do mape vrže `PermissionError` in
        ta ni napaka klicalca, ki bi jo `_izid_za` pretvoril v `failed`. Če je
        ne bi ujel klicatelj, bi zapis ostal v `processing` — kriterij pa
        pravi, da tam ne obtiči.
        """
        zapisi(motor, slike)
        klicalec, klicane = klicalec_vrne(uspesen_izid())

        def pokvarjen_dostop(mapa: Path, pot: Path) -> bool:
            raise PermissionError("dostop do mape zavrnjen")

        monkeypatch.setattr("app.obdelava.je_znotraj", pokvarjen_dostop)

        with pytest.raises(PermissionError):
            obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)

        assert klicane == []
        # Zapis je spet v vrsti, ne obtičal.
        assert preberi(motor).status == STATUS_NOV

    def test_zanka_prezivi_izjemo_pri_dostopu_do_diska(
        self,
        motor: Engine,
        slike: Path,
        tovarna_sej: sessionmaker[Session],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Ista izjema skozi `obdelaj_cakajoce`: obhod se konča, zanka ne pade."""
        zapisi(motor, slike)
        klicalec, _ = klicalec_vrne(uspesen_izid())

        def pokvarjen_dostop(mapa: Path, pot: Path) -> bool:
            raise PermissionError("dostop do mape zavrnjen")

        monkeypatch.setattr("app.obdelava.je_znotraj", pokvarjen_dostop)

        assert obdelaj_cakajoce(tovarna_sej, klicalec, slike) == 0
        assert preberi(motor).status == STATUS_NOV


class TestUstavljanjeMedSerijo:
    """Zaustavitev strežnika ne sme čakati cele serije čakajočih slik."""

    def test_obhod_se_ustavi_med_zapisi(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Po prvem zapisu se obhod ozre na zastavico in neha.

        Brez tega bi `ustavi()` pri dvajsetih čakajočih slikah in časovni
        omejitvi 120 s blokiral zaustavitev do štirideset minut.
        """
        zapisi(motor, slike, UUID_ENA, taken_at="2026-09-04T07:00:00+00:00")
        zapisi(motor, slike, UUID_DVA, taken_at="2026-09-04T09:00:00+00:00")
        izid = uspesen_izid()
        obdelanih = 0

        def klicalec(pot: Path) -> IzidKlica:
            nonlocal obdelanih
            obdelanih += 1
            return izid

        # Zastavica je postavljena od začetka drugega kroga naprej.
        assert obdelaj_cakajoce(tovarna_sej, klicalec, slike, lambda: obdelanih >= 1) == 1

        assert obdelanih == 1
        assert preberi(motor, UUID_ENA).status == STATUS_PRIPRAVLJEN
        # Drugi ostane v vrsti in ga pobere naslednji zagon.
        assert preberi(motor, UUID_DVA).status == STATUS_NOV

    def test_zapis_ki_je_ze_v_teku_se_dokonca(
        self, motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
    ) -> None:
        """Prekinjen klic bi bil plačan in zavržen, zato se ne prekinja."""
        zapisi(motor, slike)
        izid = uspesen_izid()

        def klicalec(pot: Path) -> IzidKlica:
            return izid

        # Zastavica je postavljena že pred prvim zapisom in obhod ne naredi nič.
        assert obdelaj_cakajoce(tovarna_sej, klicalec, slike, lambda: True) == 0
        assert preberi(motor).status == STATUS_NOV

        # Brez zastavice gre isti zapis normalno skozi.
        assert obdelaj_cakajoce(tovarna_sej, klicalec, slike) == 1
        assert preberi(motor).status == STATUS_PRIPRAVLJEN

    def test_izjema_pri_branju_po_prevzemu_sprosti_zapis(
        self,
        motor: Engine,
        slike: Path,
        tovarna_sej: sessionmaker[Session],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Od prevzema naprej mora zapis vsaka pot spraviti iz `processing`.

        Tu odpove branje zapisa **takoj po** prevzemu — okno med dvema sejama,
        ki je bilo prej zunaj `try`.
        """
        zapisi(motor, slike)
        klicalec, klicane = klicalec_vrne(uspesen_izid())
        izvirni = MaterialsRepository.poisci

        def pokvarjeno_branje(self: MaterialsRepository, material_id: str) -> Material | None:
            raise RuntimeError("baza je med prevzemom in branjem odpovedala")

        monkeypatch.setattr(MaterialsRepository, "poisci", pokvarjeno_branje)

        with pytest.raises(RuntimeError):
            obdelaj_zapis(tovarna_sej, klicalec, slike, UUID_ENA)

        monkeypatch.setattr(MaterialsRepository, "poisci", izvirni)
        assert klicane == []
        assert preberi(motor).status == STATUS_NOV
