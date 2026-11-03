"""Predaja shranjenega preizkusa otroku (V4-R10, `ADR-068`).

Pokriva tabelo „Test casi" iz `docs/plan/V4-R10.md`. Tesnjenje med družinama
(pot in repozitorij) je v `test_tesnjenje.py`, migracija v
`test_migracija.py`. Kako gumbi izgledajo in da se ne natisnejo, pokaže ročni
preizkus v fazi 9b; tu so trditve o tem, kaj strežnik zapiše in kaj stran
**vsebuje**.
"""

import re
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db import PREHODI_PREDAJE, PreizkusiRepository
from app.models import DEJANJA_PREDAJE, STANJA_PREIZKUSA, Preizkus
from tests.conftest import BRAT_ID, CVEK_ID, PrijavljenOdjemalec, ustvari_otroka
from tests.test_shranjeni_preizkusi import DRUG_ID, NEZNAN_ID, NOV_ID, OSNOVA_ID, STOLPCI, v_bazo

pytestmark = pytest.mark.usefixtures("otrok")

PRIMEREN_CAS = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)

#: Stolpci, ki jih predaja ne sme premakniti (`ADR-068` B).
VSEBINA = tuple(stolpec for stolpec in STOLPCI if stolpec not in ("given_at", "solved_at"))


def pot(preizkus_id: str = OSNOVA_ID) -> str:
    return f"/admin/assessments/{preizkus_id}/handover"


def predaj(
    odjemalec: PrijavljenOdjemalec, dejanje: str, iz: str, preizkus_id: str = OSNOVA_ID
) -> Any:
    """Klik na gumb ogleda: obrazec z dejanjem in videnim stanjem."""
    return odjemalec.post(
        pot(preizkus_id), data={"dejanje": dejanje, "iz": iz}, follow_redirects=False
    )


def zapis(motor: Engine, preizkus_id: str = OSNOVA_ID) -> Preizkus:
    with Session(motor) as seja:
        najden = seja.get(Preizkus, preizkus_id)
        assert najden is not None
        seja.expunge(najden)
        return najden


def nastavi(
    motor: Engine,
    preizkus_id: str = OSNOVA_ID,
    *,
    given_at: datetime | None = None,
    solved_at: datetime | None = None,
) -> None:
    """Stanje predaje neposredno v bazo — stanje, ne pot do njega."""
    with Session(motor) as seja:
        najden = seja.get(Preizkus, preizkus_id)
        assert najden is not None
        najden.given_at = given_at
        najden.solved_at = solved_at
        seja.commit()


def vsebina(motor: Engine, preizkus_id: str = OSNOVA_ID) -> dict[str, Any]:
    z = zapis(motor, preizkus_id)
    return {stolpec: getattr(z, stolpec) for stolpec in VSEBINA}


# --- Prehodi (`ADR-068` C) ---


class TestPrehodi:
    def test_dan_otroku(self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str) -> None:
        v_bazo(motor, stars)

        odgovor = predaj(odjemalec, "dan", "shranjen")

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == f"/admin/assessments/{OSNOVA_ID}"
        z = zapis(motor)
        assert z.stanje == "v-resevanju"
        assert z.given_at is not None and z.solved_at is None

    def test_resen_iz_shranjenega_nastavi_oba_casa(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)

        predaj(odjemalec, "resen", "shranjen")

        z = zapis(motor)
        assert z.stanje == "resen"
        assert z.given_at is not None and z.solved_at is not None

    def test_resen_iz_resevanja_ohrani_cas_predaje(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)
        nastavi(motor, given_at=PRIMEREN_CAS)

        predaj(odjemalec, "resen", "v-resevanju")

        z = zapis(motor)
        assert z.stanje == "resen"
        # SQLite vrne čas brez pasu; primerja se trenutek, ne zapis pasu.
        assert z.given_at is not None
        assert z.given_at.replace(tzinfo=None) == PRIMEREN_CAS.replace(tzinfo=None)

    def test_vrni_iz_resenega_v_resevanje(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)
        nastavi(motor, given_at=PRIMEREN_CAS, solved_at=PRIMEREN_CAS)

        predaj(odjemalec, "vrni", "resen")

        z = zapis(motor)
        assert z.stanje == "v-resevanju"
        assert z.given_at is not None and z.solved_at is None

    def test_vrni_iz_resevanja_med_shranjene(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)
        nastavi(motor, given_at=PRIMEREN_CAS)

        predaj(odjemalec, "vrni", "v-resevanju")

        z = zapis(motor)
        assert z.stanje == "shranjen"
        assert z.given_at is None and z.solved_at is None

    def test_vrnitev_ne_izbrise_zapisa(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        # `ADR-068` E, `ADR-011`: pobriše se vrednost v stolpcu, ne vrstica.
        v_bazo(motor, stars)
        nastavi(motor, given_at=PRIMEREN_CAS, solved_at=PRIMEREN_CAS)

        predaj(odjemalec, "vrni", "resen")
        predaj(odjemalec, "vrni", "v-resevanju")

        with Session(motor) as seja:
            assert seja.scalars(select(Preizkus.id)).all() == [OSNOVA_ID]

    @pytest.mark.parametrize(("dejanje", "iz"), sorted(PREHODI_PREDAJE))
    def test_prehod_ne_premakne_vsebine(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        stars: str,
        dejanje: str,
        iz: str,
    ) -> None:
        v_bazo(motor, stars)
        if iz == "v-resevanju":
            nastavi(motor, given_at=PRIMEREN_CAS)
        if iz == "resen":
            nastavi(motor, given_at=PRIMEREN_CAS, solved_at=PRIMEREN_CAS)
        prej = vsebina(motor)

        assert predaj(odjemalec, dejanje, iz).status_code == 303

        assert vsebina(motor) == prej


# --- Videno stanje (`ADR-068` D) ---


class TestVidenoStanje:
    def test_zastarelo_videno_stanje_ne_spremeni_nicesar(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        # Drugi starš je test medtem označil kot rešen; ta je videl „v reševanju".
        v_bazo(motor, stars)
        nastavi(motor, given_at=PRIMEREN_CAS, solved_at=PRIMEREN_CAS)

        prej = zapis(motor)

        odgovor = predaj(odjemalec, "vrni", "v-resevanju")

        assert odgovor.status_code == 303
        po = zapis(motor)
        assert po.stanje == "resen"
        # Oba časa, ne samo izpeljano stanje: brez pogoja bi „Vrni" pobrisal
        # `given_at` in pustil rešen test brez časa predaje.
        assert (po.given_at, po.solved_at) == (prej.given_at, prej.solved_at)

    def test_dvojni_vrni_gre_samo_en_korak_nazaj(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)
        nastavi(motor, given_at=PRIMEREN_CAS, solved_at=PRIMEREN_CAS)

        predaj(odjemalec, "vrni", "resen")
        predaj(odjemalec, "vrni", "resen")

        assert zapis(motor).stanje == "v-resevanju"

    def test_dvojni_dan_otroku_ohrani_prvi_cas(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)

        predaj(odjemalec, "dan", "shranjen")
        prvi = zapis(motor).given_at
        predaj(odjemalec, "dan", "shranjen")

        assert zapis(motor).given_at == prvi


# --- Neveljaven vhod ---


class TestNeveljavno:
    @pytest.mark.parametrize(
        ("dejanje", "iz"),
        [
            ("vrni", "shranjen"),
            ("dan", "v-resevanju"),
            ("dan", "resen"),
            ("resen", "resen"),
            ("x", "shranjen"),
            ("dan", "x"),
            ("", ""),
        ],
    )
    def test_neznan_prehod_je_400_in_nic_se_ne_spremeni(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        stars: str,
        dejanje: str,
        iz: str,
    ) -> None:
        v_bazo(motor, stars)
        nastavi(motor, given_at=PRIMEREN_CAS)
        prej = zapis(motor)

        odgovor = predaj(odjemalec, dejanje, iz)

        assert odgovor.status_code == 400
        assert "Tega gumba ne poznam" in odgovor.text
        po = zapis(motor)
        assert (po.given_at, po.solved_at) == (prej.given_at, prej.solved_at)

    def test_neznan_test_je_404(self, odjemalec: PrijavljenOdjemalec) -> None:
        odgovor = predaj(odjemalec, "dan", "shranjen", NEZNAN_ID)

        assert odgovor.status_code == 404

    def test_brez_csrf_zetona_se_ne_zgodi_nic(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)

        odgovor = odjemalec.post(
            pot(), data={"dejanje": "dan", "iz": "shranjen", "csrf": "napacen"}
        )

        assert odgovor.status_code == 403
        assert zapis(motor).stanje == "shranjen"

    def test_brez_seje_pelje_na_prijavo(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)
        odjemalec.cookies.clear()

        odgovor = odjemalec.post(
            pot(), data={"dejanje": "dan", "iz": "shranjen"}, follow_redirects=False
        )

        assert odgovor.status_code == 303
        assert odgovor.headers["location"].startswith("/admin/login")
        assert zapis(motor).stanje == "shranjen"


# --- Ogled (`ADR-068` F, G) ---


def gumbi(besedilo: str) -> list[tuple[str, str]]:
    """(vrednost, napis) gumbov predaje na ogledu."""
    return re.findall(
        r'<button class="gumb gumb-obdelava" type="submit" name="dejanje" value="([^"]+)">'
        r"([^<]+)</button>",
        besedilo,
    )


class TestOgled:
    def test_gumbi_po_stanju(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)
        stran = lambda: odjemalec.get(f"/admin/assessments/{OSNOVA_ID}").text  # noqa: E731

        assert gumbi(stran()) == [("dan", "Dan otroku"), ("resen", "Rešen")]
        nastavi(motor, given_at=PRIMEREN_CAS)
        assert gumbi(stran()) == [("resen", "Rešen"), ("vrni", "Vrni med shranjene")]
        nastavi(motor, given_at=PRIMEREN_CAS, solved_at=PRIMEREN_CAS)
        assert gumbi(stran()) == [("vrni", "Vrni v reševanje")]

    @pytest.mark.parametrize("stanje", STANJA_PREIZKUSA)
    def test_obrazec_nosi_videno_stanje_in_csrf(
        self,
        odjemalec: PrijavljenOdjemalec,
        motor: Engine,
        stars: str,
        stanje: str,
    ) -> None:
        v_bazo(motor, stars)
        if stanje != "shranjen":
            nastavi(motor, given_at=PRIMEREN_CAS)
        if stanje == "resen":
            nastavi(motor, given_at=PRIMEREN_CAS, solved_at=PRIMEREN_CAS)

        besedilo = odjemalec.get(f"/admin/assessments/{OSNOVA_ID}").text

        obrazci = re.findall(
            rf'<form method="post" action="{re.escape(pot())}">\s*'
            r'<input type="hidden" name="csrf" value="([^"]+)">\s*'
            r'<input type="hidden" name="iz" value="([^"]+)">',
            besedilo,
        )
        assert obrazci and all(iz == stanje for _, iz in obrazci)
        assert all(zeton == odjemalec.csrf for zeton, _ in obrazci)

    def test_predaja_se_ne_natisne(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        v_bazo(motor, stars)

        besedilo = odjemalec.get(f"/admin/assessments/{OSNOVA_ID}").text

        assert '<div class="vrstica-gumbov ne-tiskaj predaja">' in besedilo

    def test_datuma_predaje_ni_na_strani(
        self, odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
    ) -> None:
        # 20. 10. je samo v časih predaje; shranjen je bil 1. 10.
        v_bazo(motor, stars)
        nastavi(motor, given_at=PRIMEREN_CAS, solved_at=PRIMEREN_CAS)

        for naslov in (f"/admin/assessments/{OSNOVA_ID}", "/admin/assessments"):
            besedilo = odjemalec.get(naslov).text
            assert "20. 10." not in besedilo, naslov
            assert "rešen" in besedilo, naslov


# --- Pregled (`ADR-068` G) ---


def vrstice(besedilo: str) -> list[str]:
    """Naslovi testov v vrsticah pregleda, v vrstnem redu."""
    return re.findall(r'<td><a href="/admin/assessments/[^"]+">([^<]+)</a></td>', besedilo)


@pytest.fixture
def trije(motor: Engine, stars: str) -> None:
    """Trije testi v treh stanjih; SLJ je rešen."""
    v_bazo(
        motor, stars, OSNOVA_ID, title="Shranjen MAT", saved_at=datetime(2026, 10, 1, tzinfo=UTC)
    )
    v_bazo(motor, stars, NOV_ID, title="Pri otroku MAT", saved_at=datetime(2026, 10, 2, tzinfo=UTC))
    v_bazo(
        motor,
        stars,
        DRUG_ID,
        title="Rešen SLJ",
        subject="SLJ",
        saved_at=datetime(2026, 10, 3, tzinfo=UTC),
    )
    nastavi(motor, NOV_ID, given_at=PRIMEREN_CAS)
    nastavi(motor, DRUG_ID, given_at=PRIMEREN_CAS, solved_at=PRIMEREN_CAS)


@pytest.mark.usefixtures("trije")
class TestPregled:
    def test_filter_stanja(self, odjemalec: PrijavljenOdjemalec) -> None:
        def naslovi(poizvedba: str) -> list[str]:
            return vrstice(odjemalec.get(f"/admin/assessments{poizvedba}").text)

        assert naslovi("") == ["Rešen SLJ", "Pri otroku MAT", "Shranjen MAT"]
        assert naslovi("?stanje=v-resevanju") == ["Pri otroku MAT"]
        assert naslovi("?stanje=resen") == ["Rešen SLJ"]

    def test_stanje_in_predmet_se_sestavljata(self, odjemalec: PrijavljenOdjemalec) -> None:
        besedilo = odjemalec.get("/admin/assessments?predmet=MAT&stanje=resen").text

        assert vrstice(besedilo) == []
        assert "Ni testa, ki bi ustrezal izbranemu filtru." in besedilo
        assert vrstice(odjemalec.get("/admin/assessments?predmet=SLJ&stanje=resen").text) == [
            "Rešen SLJ"
        ]

    @pytest.mark.parametrize("stanje", ["x", "shranjen", "RESEN"])
    def test_neznano_stanje_da_prazen_seznam(
        self, odjemalec: PrijavljenOdjemalec, stanje: str
    ) -> None:
        # „Še ni dan" ni filter (`B-02`), zato je `shranjen` tu neznano stanje.
        odgovor = odjemalec.get(f"/admin/assessments?stanje={stanje}")

        assert odgovor.status_code == 200
        assert vrstice(odgovor.text) == []

    def test_oznaka_v_vrstici(self, odjemalec: PrijavljenOdjemalec) -> None:
        besedilo = odjemalec.get("/admin/assessments").text

        oznake = re.findall(r"</a></td>\s*(?:\{#[^#]*#\}\s*)?<td>(.*?)</td>", besedilo, flags=re.S)
        assert oznake == [
            '<span class="oznaka ok">rešen</span>',
            '<span class="oznaka caka">v reševanju</span>',
            "",
        ]

    def test_povezave_filtrov_ohranijo_drugi_filter(self, odjemalec: PrijavljenOdjemalec) -> None:
        besedilo = odjemalec.get("/admin/assessments?predmet=MAT").text

        assert 'href="/admin/assessments?predmet=MAT&amp;stanje=v-resevanju"' in besedilo
        assert 'href="/admin/assessments?predmet=MAT&amp;stanje=resen"' in besedilo
        besedilo = odjemalec.get("/admin/assessments?stanje=resen").text
        assert 'href="/admin/assessments?predmet=SLJ&amp;stanje=resen"' in besedilo
        # „vsi" pri stanju ohrani predmet, „vsi" pri predmetu ohrani stanje.
        besedilo = odjemalec.get("/admin/assessments?predmet=MAT&stanje=resen").text
        assert '<a href="/admin/assessments?predmet=MAT">vsi</a>' in besedilo
        assert '<a href="/admin/assessments?stanje=resen">vsi</a>' in besedilo

    def test_pregled_ostane_brez_skripte_in_brez_obrazca_za_pisanje(
        self, odjemalec: PrijavljenOdjemalec
    ) -> None:
        besedilo = odjemalec.get("/admin/assessments").text

        assert "<script" not in besedilo
        assert re.findall(r'<form method="post" action="([^"]+)"', besedilo) == ["/admin/logout"]


def test_brez_testov_ni_filtra_stanja(odjemalec: PrijavljenOdjemalec) -> None:
    besedilo = odjemalec.get("/admin/assessments").text

    assert 'aria-label="Stanje"' not in besedilo


# --- Robni primeri (`ADR-068` H) ---


def test_deaktiviran_otrok_test_se_da_oznaciti(
    odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
) -> None:
    ustvari_otroka(motor, user_id=BRAT_ID, identifikator="nejc", prikazno_ime="Nejc", aktiven=False)
    v_bazo(motor, stars, child_id=BRAT_ID)

    predaj(odjemalec, "resen", "shranjen")

    assert zapis(motor).stanje == "resen"


def test_nov_test_na_osnovi_resenega_je_shranjen(motor: Engine, stars: str) -> None:
    v_bazo(motor, stars)
    nastavi(motor, given_at=PRIMEREN_CAS, solved_at=PRIMEREN_CAS)
    with Session(motor) as seja:
        nov = PreizkusiRepository(seja, CVEK_ID).shrani(
            preizkus_id=NOV_ID,
            child_id=zapis(motor).child_id,
            saved_by=stars,
            subject="MAT",
            title="Na osnovi",
            test_md="# Na osnovi",
            solutions_md="",
            source_md="snov",
            model="m",
            base_id=OSNOVA_ID,
        )
        assert nov is not None
        assert nov.stanje == "shranjen"


# --- Varovalo: samo ena pot piše (`ADR-068` B) ---


#: Pisanje v obstoječ zapis `preizkusi` v kakršnikoli obliki: stavek `update`
#: (tudi prelomljen), surov SQL ali ORM prirejanje vsebinskega stolpca.
PISANJE_V_PREIZKUSE = re.compile(
    r"update\(\s*Preizkus\b|UPDATE\s+preizkusi\b|\.(?:test_md|solutions_md|source_md)\s*=(?!=)",
    re.IGNORECASE,
)


def test_update_na_preizkusih_je_samo_v_zapisi_predajo() -> None:
    """Edino pisanje v obstoječ zapis `preizkusi` je v `zapisi_predajo`.

    Pregled besedila in ne vedenja, zato **delno** varovalo: ujame stavek
    `update`, surov SQL in prirejanje vsebine testa, ne pa npr. `setattr` ali
    prirejanja naslova. Drugo pisanje bi bilo nova pot do urejanja vsebine, ki
    jo `ADR-053` F zapira; vedenje varuje `test_prehod_ne_premakne_vsebine`.
    """
    from pathlib import Path

    koda = Path(__file__).resolve().parents[1] / "app"
    najdbe = [
        (datoteka.name, ujemanje.group(0))
        for datoteka in sorted(koda.rglob("*.py"))
        for ujemanje in PISANJE_V_PREIZKUSE.finditer(datoteka.read_text(encoding="utf-8"))
    ]
    assert najdbe == [("db.py", "update(Preizkus")], najdbe
    besedilo = (koda / "db.py").read_text(encoding="utf-8")
    zacetek = besedilo.index("def zapisi_predajo(")
    # Konec metode: naslednja metoda ali konec datoteke (metoda je lahko zadnja).
    konec = besedilo.find("\n    def ", zacetek + 1)
    konec = len(besedilo) if konec == -1 else konec
    assert zacetek < besedilo.index("update(Preizkus)") < konec


def test_dejanja_in_prehodi_se_ujemata() -> None:
    """Vsako dejanje ima vsaj en prehod; vsak prehod gre iz znanega stanja."""
    assert {dejanje for dejanje, _ in PREHODI_PREDAJE} == set(DEJANJA_PREDAJE)
    assert {iz for _, iz in PREHODI_PREDAJE} <= set(STANJA_PREIZKUSA)
