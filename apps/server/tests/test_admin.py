"""Testi operaterske strani pod `/admin`.

Pokrivajo tabelo „Test casi" iz `docs/plan/V1-R04.md`.

Zapisi nastanejo neposredno v bazi in ne prek `POST /materials`: ta stran bere
stanje, ne poti, po kateri je stanje nastalo. Vsak test, ki gre skozi prenos,
bi ob spremembi prenosa padel iz razloga, ki s to zahtevo nima zveze.
"""

import html
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.db import MaterialsRepository
from app.models import (
    STATUS_NAPAKA,
    STATUS_NOV,
    STATUS_PRIPRAVLJEN,
    STATUS_V_OBDELAVI,
    Material,
    Question,
    Quiz,
)
from app.subjects import PREDMETI
from tests.conftest import CVEK_ID, OTROK_ID, TUJA_DRUZINA_ID, SejaTesta

# V3-R10 preverja, da premik potegne za sabo statistiko, izbirnik in sosede.
# Pomagala za to stanje že obstajajo v testih tistih zahtev; podvojena tu bi
# se razšla od njih — isti razlog kot v `test_tesnjenje.py` in
# `test_statistika.py`, ki jih uvažata enako.
from tests.test_kvizi import izbirnik, je_izbirna, je_obkljukana, objavi, upokoji
from tests.test_kvizi import snov as snov_z_vprasanji
from tests.test_resevanje import poskus, poslji
from tests.test_rezultat import postavke

UUID_ENA = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
UUID_DVA = "a1b2c3d4-e5f6-4789-abcd-ef0123456789"


def zapisi(
    motor: Engine,
    slike: Path,
    material_id: str = UUID_ENA,
    subject: str = "MAT",
    taken_at: str = "2026-09-04T07:30:00+00:00",
    vsebina: bytes | None = b"slika-ena",
) -> Path:
    """Ustvari zapis in (privzeto) njegovo datoteko; vrne pot do slike.

    `vsebina=None` pomeni vrstico brez datoteke — stanje, ki na tej strani ne
    sme povzročiti izjeme.
    """
    pot = slike / CVEK_ID / f"{material_id}.jpg"
    if vsebina is not None:
        pot.write_bytes(vsebina)

    with Session(motor) as seja:
        seja.add(
            Material(
                child_id=OTROK_ID,
                family_id=CVEK_ID,
                id=material_id,
                subject=subject,
                taken_at=datetime.fromisoformat(taken_at),
                image_path=str(pot),
                status=STATUS_NOV,
                received_at=datetime(2026, 9, 4, 8, 0, tzinfo=UTC),
            )
        )
        seja.commit()

    return pot


def obdelaj(
    motor: Engine,
    material_id: str = UUID_ENA,
    *,
    status: str = STATUS_PRIPRAVLJEN,
    readable: bool | None = True,
    koliko_vprasanj: int = 5,
    error: str | None = None,
) -> None:
    """Zapisu doda izid obdelave, kot bi ga zapisal worker (V1-R03).

    Neposredno v bazo in ne skozi obdelavo: ta stran bere stanje, ne poti, po
    kateri je stanje nastalo — isti razlog kot pri `zapisi`.
    """
    with Session(motor) as seja:
        material = seja.get(Material, material_id)
        assert material is not None
        material.status = status
        material.readable = readable
        material.transcript = "Delci snovi se gibljejo." if readable else None
        material.summary = "Zgradba snovi." if readable else None
        material.prompt = "POSLANI PROMPT ZA MODEL"
        material.raw_response = '{"readable": true}'
        material.model = "gpt-4.1-2025-04-14"
        material.input_tokens = 1500
        material.output_tokens = 2000
        material.error = error
        # `vsa_vprasanja` in ne `veljavna_vprasanja`: druga je `viewonly` in
        # skoznjo se ne piše (`docs/odlocitve/ADR-015`). Nova vprašanja imajo
        # `retired_at` prazen, torej so veljavna.
        material.vsa_vprasanja = [
            Question(
                family_id=CVEK_ID,
                id=f"{material_id}-v{i}",
                position=i,
                question=f"Vprašanje {i}?",
                answer=f"Odgovor {i}.",
            )
            for i in range(1, koliko_vprasanj + 1)
        ]
        seja.commit()


def arhiviraj(
    motor: Engine,
    material_id: str = UUID_ENA,
    *,
    potrjeno: bool = False,
    arhivirano: str = "2026-09-05T10:00:00+00:00",
) -> None:
    """Postavi zapis v arhiv, po potrebi s potrditvijo s telefona.

    Neposredno v bazo in ne skozi pot: te strani berejo stanje, ne poti, po
    kateri je stanje nastalo — isti razlog kot pri `zapisi` in `obdelaj`.
    """
    with Session(motor) as seja:
        material = seja.get(Material, material_id)
        assert material is not None
        material.archived_at = datetime.fromisoformat(arhivirano)
        material.device_deleted_at = (
            datetime(2026, 9, 5, 12, 0, tzinfo=UTC) if potrjeno else None
        )
        seja.commit()


def cas_arhiviranja(motor: Engine, material_id: str = UUID_ENA) -> datetime | None:
    """Kdaj je bil zapis arhiviran."""
    with Session(motor) as seja:
        material = seja.get(Material, material_id)
        assert material is not None
        return material.archived_at


def dodaj_serijo(
    motor: Engine,
    material_id: str = UUID_ENA,
    *,
    koliko: int = 3,
    oznaka: str = "b",
) -> None:
    """Doda zapisu novo serijo veljavnih vprašanj, oštevilčeno spet od 1.

    Ločeno od `obdelaj`, ki zbirko **zamenja** in bi s tem prejšnjo serijo
    osirotel. `position` se z vsako serijo začne znova — enolična je znotraj
    serije in ne znotraj materiala (`docs/odlocitve/ADR-015`) — zato `oznaka`
    loči `id` vrstic, ki bi si sicer bile enake.
    """
    with Session(motor) as seja:
        material = seja.get(Material, material_id)
        assert material is not None
        for i in range(1, koliko + 1):
            material.vsa_vprasanja.append(
                Question(
                    family_id=CVEK_ID,
                    id=f"{material_id}-{oznaka}{i}",
                    position=i,
                    question=f"Vprašanje {oznaka}{i}?",
                    answer=f"Odgovor {oznaka}{i}.",
                )
            )
        seja.commit()


def upokoji_vprasanja(
    motor: Engine,
    material_id: str = UUID_ENA,
    *,
    ob_casu: str = "2026-09-06T09:00:00+00:00",
) -> None:
    """Upokoji vsa veljavna vprašanja zapisa, kot bi to storila ponovna obdelava.

    Neposredno v bazo in ne skozi `vrni_v_vrsto`: te strani berejo stanje, ne
    poti, po kateri je stanje nastalo — isti razlog kot pri `zapisi` in
    `obdelaj`.
    """
    with Session(motor) as seja:
        material = seja.get(Material, material_id)
        assert material is not None
        for vprasanje in material.veljavna_vprasanja:
            vprasanje.retired_at = datetime.fromisoformat(ob_casu)
        seja.commit()


def stevilo_vprasanj(motor: Engine) -> int:
    """Koliko vrstic je v tabeli `questions` — veljavnih in upokojenih skupaj."""
    with Session(motor) as seja:
        return seja.scalar(select(func.count()).select_from(Question)) or 0


def stevilo_veljavnih(motor: Engine) -> int:
    """Koliko vrstic nima postavljenega `retired_at`.

    Ločeno od `stevilo_vprasanj` zato, ker je od V2-R05 razlika med „vrstice
    ni" in „vrstica je, a ni veljavna" celotna vsebina zahteve
    (`docs/odlocitve/ADR-015`).
    """
    with Session(motor) as seja:
        return (
            seja.scalar(
                select(func.count())
                .select_from(Question)
                .where(Question.retired_at.is_(None))
            )
            or 0
        )


def stevilo_vrstic(motor: Engine) -> int:
    """Koliko zapisov je v tabeli."""
    with Session(motor) as seja:
        return seja.scalar(select(func.count()).select_from(Material)) or 0


def vrstica_predmeta(besedilo: str, koda: str) -> str:
    """Del strani, ki pripada enemu predmetu.

    Iskanje po celi strani ne bi dokazalo ničesar: številka `2` je na strani
    tudi v skupnem številu in v drugih vrsticah. Števec se mora ujemati prav
    v vrstici svojega predmeta.
    """
    for blok in besedilo.split("<li>"):
        if f">{koda}</span>" in blok:
            return blok
    raise AssertionError(f"predmeta {koda} ni na seznamu")


class TestSeznamPredmetov:
    """`GET /admin`."""

    def test_pokaze_vseh_deset_predmetov_s_stevci(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA, subject="MAT")
        zapisi(motor, slike, UUID_DVA, subject="SLJ")

        odgovor = odjemalec.get("/admin")

        assert odgovor.status_code == 200
        for koda in ("NAR", "MAT", "TJA", "GEO", "SLJ", "LUM", "ZGO", "TIT", "DKE", "GUM"):
            # Prek `vrstica_predmeta`, ne z `koda in besedilo`: „MAT" se ujame
            # tudi znotraj „Matematika" in trditev ne bi dokazovala ničesar.
            vrstica_predmeta(odgovor.text, koda)
        assert "Matematika" in odgovor.text

    def test_stevci_so_pravi(self, odjemalec: TestClient, motor: Engine, slike: Path) -> None:
        zapisi(motor, slike, UUID_ENA, subject="MAT")
        zapisi(motor, slike, UUID_DVA, subject="MAT")

        besedilo = odjemalec.get("/admin").text

        assert ">2</span>" in vrstica_predmeta(besedilo, "MAT")
        assert ">0</span>" in vrstica_predmeta(besedilo, "GEO")
        assert ">1</span>" not in vrstica_predmeta(besedilo, "MAT")

    def test_predmet_brez_slik_je_viden_in_dosegljiv(self, odjemalec: TestClient) -> None:
        # Povezava mora biti tudi pri praznem predmetu, sicer je stran s
        # sporočilom „še ni nobene slike" dosegljiva samo z ročno vtipkanim
        # naslovom.
        besedilo = odjemalec.get("/admin").text

        assert "GEO" in besedilo
        assert 'href="/admin/subjects/GEO"' in besedilo

    def test_predmet_ki_ni_na_seznamu_je_vseeno_viden(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Preimenovana koda na telefonu ne sme skriti slik iz pregleda.
        zapisi(motor, slike, UUID_ENA, subject="XXX")

        besedilo = odjemalec.get("/admin").text

        assert "XXX" in besedilo
        assert 'href="/admin/subjects/XXX"' in besedilo

    def test_vrstni_red_predmetov_je_urnik_in_ne_abeceda(self, odjemalec: TestClient) -> None:
        besedilo = odjemalec.get("/admin").text

        assert besedilo.index("NAR") < besedilo.index("MAT") < besedilo.index("TJA")
        # Abecedni vrstni red bi DKE postavil predenj; urnik ga postavi za TIT.
        assert besedilo.index("TIT") < besedilo.index("DKE")


class TestSeznamPredmeta:
    """`GET /admin/subjects/{koda}`."""

    def test_najnovejsa_slika_je_prva(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA, taken_at="2026-09-01T07:00:00+00:00")
        zapisi(motor, slike, UUID_DVA, taken_at="2026-09-04T07:00:00+00:00")

        besedilo = odjemalec.get("/admin/subjects/MAT").text

        # Dva zapisa z različnim `taken_at`: obrnjen `ORDER BY` ta test podre.
        assert besedilo.index(UUID_DVA) < besedilo.index(UUID_ENA)

    def test_slika_v_seznamu_vodi_na_podrobnosti(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Brez te trditve bi bilo mogoče povezavo odstraniti ali preusmeriti
        # drugam, ne da bi kaj padlo: UUID je na strani tudi v `src` slike.
        zapisi(motor, slike)

        besedilo = odjemalec.get("/admin/subjects/MAT").text

        assert f'href="/admin/materials/{UUID_ENA}"' in besedilo

    def test_slike_se_nalagajo_leno(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        besedilo = odjemalec.get("/admin/subjects/MAT").text

        assert 'loading="lazy"' in besedilo

    def test_manjkajoca_datoteka_v_seznamu_pove_kaj_je_narobe(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Brez tega bi brskalnik narisal ikono pokvarjene slike — kar je videti
        # kot napaka strani, ne kot podatek. Najdeno ob ogledu strani, ne s
        # testom; test je nastal za tem.
        zapisi(motor, slike, vsebina=None)

        besedilo = odjemalec.get("/admin/subjects/MAT").text

        assert "slike na disku ni" in besedilo
        assert f'src="/admin/materials/{UUID_ENA}/image"' not in besedilo

    def test_prikaze_cas_v_domacem_pasu(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # 7:30 UTC je poleti v Ljubljani 9:30. Stran, ki bi kazala UTC, bi
        # operaterju vsakič nalagala računanje na pamet.
        zapisi(motor, slike, taken_at="2026-09-04T07:30:00+00:00")

        besedilo = odjemalec.get("/admin/subjects/MAT").text

        assert "4. 9. 2026 ob 09:30" in besedilo
        # Kriterij zahteva pod vsako sliko čas **in** stanje obdelave.
        assert "čaka na obdelavo" in besedilo

    def test_prazen_predmet_da_sporocilo_in_ne_napako(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get("/admin/subjects/GEO")

        assert odgovor.status_code == 200
        assert "še ni nobene slike" in odgovor.text

    def test_neznana_koda_brez_slik_da_404(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get("/admin/subjects/XXX")

        assert odgovor.status_code == 404
        assert "text/html" in odgovor.headers["content-type"]

    def test_neznana_koda_s_slikami_je_dosegljiva(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, subject="XXX")

        odgovor = odjemalec.get("/admin/subjects/XXX")

        assert odgovor.status_code == 200
        assert UUID_ENA in odgovor.text


class TestPodrobnosti:
    """`GET /admin/materials/{id}`."""

    def test_pokaze_vse_metapodatke(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        pot = zapisi(motor, slike, vsebina=b"x" * 2048)

        odgovor = odjemalec.get(f"/admin/materials/{UUID_ENA}")

        assert odgovor.status_code == 200
        # Trditve so vezane na izpisano polje, ne na golo pojavitev v besedilu.
        # `UUID_ENA in besedilo` je bilo izpolnjeno že z naslovom slike, „MAT"
        # pa s povratno povezavo — stran brez teh polj bi ostala zelena.
        assert f"<dd>{UUID_ENA}</dd>" in odgovor.text
        assert "Matematika" in odgovor.text
        assert "<dd>4. 9. 2026 ob 09:30</dd>" in odgovor.text  # čas posnetka
        assert "<dd>4. 9. 2026 ob 10:00</dd>" in odgovor.text  # čas prejema
        assert "<dd>2 kB</dd>" in odgovor.text
        assert "čaka na obdelavo" in odgovor.text
        # Brez te trditve bi kriterij „s sliko v polni velikosti" ostal
        # nedokazan: odstranitev <img> s strani ni podrla nobenega testa.
        assert f'src="/admin/materials/{UUID_ENA}/image"' in odgovor.text
        # Cela pot, ne le ime datoteke: kriterij pravi „pot do datoteke".
        assert f"<dd>{pot}</dd>" in odgovor.text
        assert "čaka na obdelavo" in odgovor.text

    def test_ima_gumb_za_arhiviranje(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Kriterij pravi „gumb na strani s podrobnostmi odpre potrditveno
        # stran". Vsi testi arhiviranja hodijo naravnost na URL, zato bi brez
        # te trditve gumb lahko izginil in dejanje bi ostalo dosegljivo samo
        # z ročno vtipkanim naslovom.
        #
        # Do V1-R07 je tu stalo brisanje; `docs/odlocitve/ADR-011` ga je
        # zamenjalo z arhiviranjem.
        zapisi(motor, slike)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert f'href="/admin/materials/{UUID_ENA}/archive"' in besedilo
        assert f'href="/admin/materials/{UUID_ENA}/delete"' not in besedilo

    def test_povratna_povezava_je_ubezana_za_url(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, subject="A?B")

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert 'href="/admin/subjects/A%3FB"' in besedilo

    def test_manjkajoca_datoteka_ne_podre_strani(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, vsebina=None)

        odgovor = odjemalec.get(f"/admin/materials/{UUID_ENA}")

        assert odgovor.status_code == 200
        assert "slike na disku pa ni" in odgovor.text
        assert "<dd>datoteke na disku ni</dd>" in odgovor.text

    def test_neznan_id_da_404_kot_html(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get(f"/admin/materials/{UUID_ENA}")

        assert odgovor.status_code == 404
        assert "text/html" in odgovor.headers["content-type"]
        # Ne sme biti JSON s `detail`, kot ga vrne privzeti FastAPI.
        assert '"detail"' not in odgovor.text


class TestSlika:
    """`GET /admin/materials/{id}/image`."""

    def test_vrne_vsebino_datoteke(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, vsebina=b"prava-vsebina")

        odgovor = odjemalec.get(f"/admin/materials/{UUID_ENA}/image")

        assert odgovor.status_code == 200
        assert odgovor.headers["content-type"] == "image/jpeg"
        assert odgovor.content == b"prava-vsebina"

    def test_manjkajoca_datoteka_da_404(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, vsebina=None)

        assert odjemalec.get(f"/admin/materials/{UUID_ENA}/image").status_code == 404

    def test_obstojeca_datoteka_izven_mape_se_ne_pokaze(
        self, odjemalec: TestClient, motor: Engine, slike: Path, tmp_path: Path
    ) -> None:
        # Datoteka izven `images_dir`, ki res obstaja: brez preverbe v `_pogled`
        # bi predloga narisala `<img>`, pot `/image` pa bi ga zavrnila — stran
        # bi kazala pokvarjeno sliko namesto povedati, kaj je narobe.
        zunaj = tmp_path / "zunaj.jpg"
        zunaj.write_bytes(b"slika-zunaj-mape")
        zapisi(motor, slike, vsebina=None)
        with Session(motor) as seja:
            material = seja.get(Material, UUID_ENA)
            assert material is not None
            material.image_path = str(zunaj)
            seja.commit()

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "slike na disku pa ni" in besedilo
        assert f'src="/admin/materials/{UUID_ENA}/image"' not in besedilo

    def test_pot_izven_mape_s_slikami_se_ne_prebere(
        self, odjemalec: TestClient, motor: Engine, slike: Path, tmp_path: Path
    ) -> None:
        # Pot je zapisala naša koda, a pokvarjena vrstica ne sme pomeniti
        # branja poljubne datoteke s strežnika.
        skrivnost = tmp_path / "skrivnost.txt"
        skrivnost.write_bytes(b"tega-nihce-ne-sme-videti")
        zapisi(motor, slike, vsebina=None)
        with Session(motor) as seja:
            material = seja.get(Material, UUID_ENA)
            assert material is not None
            material.image_path = str(skrivnost)
            seja.commit()

        odgovor = odjemalec.get(f"/admin/materials/{UUID_ENA}/image")

        assert odgovor.status_code == 404
        assert b"tega-nihce-ne-sme-videti" not in odgovor.content


class TestArhiviranje:
    """`GET` in `POST /admin/materials/{id}/archive` ter `GET /admin/archive`."""

    def test_potrditvena_stran_nicesar_ne_spremeni(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        pot = zapisi(motor, slike)

        odgovor = odjemalec.get(f"/admin/materials/{UUID_ENA}/archive")

        assert odgovor.status_code == 200
        assert cas_arhiviranja(motor) is None
        assert pot.exists()

    def test_potrditvena_stran_pokaze_kaj_bo_arhivirano(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Isto pravilo kot pri brisanju v V1-R04: potrditvena stran mora
        # povedati, kaj potrjuješ — slika, predmet, datum.
        zapisi(motor, slike)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}/archive").text

        assert f'src="/admin/materials/{UUID_ENA}/image"' in besedilo
        assert "MAT" in besedilo
        assert "4. 9. 2026 ob 09:30" in besedilo

    def test_arhivira_z_obrazcem_in_ne_s_povezavo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}/archive").text

        assert 'method="post"' in besedilo
        assert f'href="/admin/materials/{UUID_ENA}/archive"' not in besedilo

    def test_post_arhivira_in_pusti_vrstico_ter_datoteko(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Bistvo `ADR-011`: arhiviranje ni brisanje. Vrstica in datoteka
        # ostaneta, gre samo iz pregleda.
        pot = zapisi(motor, slike)

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/archive", follow_redirects=False
        )

        # 303 in ne 302: osvežitev strani po arhiviranju ne sme dejanja ponoviti.
        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == "/admin/subjects/MAT"
        assert stevilo_vrstic(motor) == 1
        assert pot.exists()
        assert cas_arhiviranja(motor) is not None

    def test_arhivirana_slika_izgine_s_seznama_predmeta(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Pozabljen filter je tiha napaka: arhiv bi obstajal, a ne bi ničesar
        # skril. Zato ima vsaka od treh poizvedb svoj test.
        zapisi(motor, slike, UUID_ENA)
        zapisi(motor, slike, UUID_DVA)
        arhiviraj(motor, UUID_ENA)

        besedilo = odjemalec.get("/admin/subjects/MAT").text

        assert UUID_ENA not in besedilo
        assert UUID_DVA in besedilo

    def test_arhivirana_slika_ne_steje_v_pregledu(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA)
        zapisi(motor, slike, UUID_DVA)
        arhiviraj(motor, UUID_ENA)

        besedilo = odjemalec.get("/admin").text

        assert ">1<" in vrstica_predmeta(besedilo, "MAT")
        assert "V arhivu 1." in besedilo

    def test_ponovno_arhiviranje_ne_premakne_casa(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Čas arhiviranja je podatek, po katerem operater bere, kdaj je sliko
        # umaknil. Drugi klik na osveženi strani ga ne sme prepisati.
        zapisi(motor, slike)
        arhiviraj(motor)
        prvi = cas_arhiviranja(motor)

        odjemalec.post(f"/admin/materials/{UUID_ENA}/archive", follow_redirects=False)

        assert cas_arhiviranja(motor) == prvi

    def test_preusmeritev_po_arhiviranju_je_ubezana(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # `?` bi glavo `Location` prerezal na poizvedbo in operater bi pristal
        # na predmetu „A", ne na „A?B". Zapisa sta dva, da predmet po umiku
        # še obstaja — sicer preusmeritev po pravilu pelje na pregled.
        zapisi(motor, slike, UUID_ENA, subject="A?B")
        zapisi(motor, slike, UUID_DVA, subject="A?B")

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/archive", follow_redirects=False
        )

        assert odgovor.headers["location"] == "/admin/subjects/A%3FB"

    def test_umik_zadnje_slike_neznanega_predmeta_pelje_na_pregled(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Predmet, ki ni med desetimi, obstaja samo, dokler ima aktivno sliko.
        # Brez tega bi preusmeritev pristala na strani „Tega ni".
        zapisi(motor, slike, subject="XXX")

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/archive", follow_redirects=False
        )

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == "/admin"
        assert odjemalec.get(odgovor.headers["location"]).status_code == 200

    def test_umik_zadnje_slike_znanega_predmeta_pelje_na_predmet(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, subject="MAT")

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/archive", follow_redirects=False
        )

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == "/admin/subjects/MAT"
        assert odjemalec.get(odgovor.headers["location"]).status_code == 200

    def test_potrditvena_stran_neobstojecega_da_404(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get(f"/admin/materials/{UUID_ENA}/archive")

        assert odgovor.status_code == 404
        assert "text/html" in odgovor.headers["content-type"]

    def test_arhiviranje_neobstojecega_preusmeri_na_pregled(
        self, odjemalec: TestClient
    ) -> None:
        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/archive", follow_redirects=False
        )

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == "/admin"

    def test_arhivirani_zapis_ni_vec_v_vrsti_za_obdelavo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Tretja poizvedba, ki mora arhiv izločiti. Brez tega bi plačali klic
        # modela za sliko, ki je bila umaknjena.
        from app.db import MaterialsRepository

        zapisi(motor, slike)
        arhiviraj(motor)

        with Session(motor) as seja:
            assert MaterialsRepository(seja, CVEK_ID).seznam_novih() == []

    def test_arhivirani_zapis_nima_gumba_za_ponovno_obdelavo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        arhiviraj(motor)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "reprocess" not in besedilo

    def test_arhiv_pokaze_zapis_in_da_telefon_se_ni_potrdil(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        arhiviraj(motor)

        besedilo = odjemalec.get("/admin/archive").text

        assert UUID_ENA in besedilo
        assert "5. 9. 2026 ob 12:00" in besedilo
        assert "čaka na telefon" in besedilo

    def test_arhiviran_zapis_ne_trdi_da_je_v_obdelavi(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # `ponovna_obdelava_mozna` je `false` iz dveh razlogov. Brez ločene veje
        # v predlogi bi arhivirana snov trdila, da je pravkar v obdelavi, in
        # operaterju naročila, naj osvežuje stran, ki se ne bo spremenila nikoli.
        zapisi(motor, slike)
        obdelaj(motor)
        arhiviraj(motor)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "pravkar v obdelavi" not in besedilo
        assert "Arhivirana snov se ne obdeluje" in besedilo

    def test_arhiv_pokaze_predmet_in_cas_posnetka(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        arhiviraj(motor)

        besedilo = odjemalec.get("/admin/archive").text

        # Skupaj in ne vsak zase: „MAT" se na strani lahko pojavi tudi kje
        # drugje, ta trditev pa govori o kartici te snovi.
        assert "MAT — 4. 9. 2026 ob 09:30" in besedilo

    def test_arhiv_ureja_po_casu_arhiviranja_navzdol(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Kriterij pravi „najnovejše arhivirana prva". Z enim samim zapisom bi
        # obrat vrstnega reda ostal neopazen.
        zapisi(motor, slike, UUID_ENA)
        zapisi(motor, slike, UUID_DVA)
        arhiviraj(motor, UUID_ENA, arhivirano="2026-09-05T10:00:00+00:00")
        arhiviraj(motor, UUID_DVA, arhivirano="2026-09-06T10:00:00+00:00")

        besedilo = odjemalec.get("/admin/archive").text

        assert besedilo.index(UUID_DVA) < besedilo.index(UUID_ENA)

    def test_arhiv_pokaze_kljukico_ko_je_telefon_potrdil(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        arhiviraj(motor, potrjeno=True)

        besedilo = odjemalec.get("/admin/archive").text

        assert "izbrisano na telefonu" in besedilo

    def test_prazen_arhiv_da_sporocilo_in_ne_napako(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get("/admin/archive")

        assert odgovor.status_code == 200
        assert "Arhiv je prazen" in odgovor.text


class TestPociscenjeSlike:
    """`POST /admin/materials/{id}/purge-image`."""

    def test_pobrise_datoteko_in_pusti_vrstico(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Vsakdanji način sproščanja prostora: velike so datoteke, ne vrstice.
        pot = zapisi(motor, slike)
        obdelaj(motor)
        arhiviraj(motor)

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/purge-image", follow_redirects=False
        )

        assert odgovor.status_code == 303
        assert not pot.exists()
        assert stevilo_vrstic(motor) == 1
        assert stevilo_vprasanj(motor) == 5

    def test_ni_dovoljeno_dokler_zapis_ni_v_arhivu(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        pot = zapisi(motor, slike)

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/purge-image", follow_redirects=False
        )

        assert odgovor.status_code == 409
        assert pot.exists()

    def test_neobstojec_zapis_da_404(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.post(f"/admin/materials/{UUID_ENA}/purge-image")

        assert odgovor.status_code == 404


class TestDokoncnoBrisanje:
    """`GET` in `POST /admin/materials/{id}/delete` po `ADR-011`.

    Brisanje je odslej zadnja stopnja in ne prva: dovoljeno je šele, ko je
    telefon potrdil, da te slike pri njem ni več. Sicer telefon za brisanje
    nikoli ne izve in slika mu ostane za vedno — natanko težava, ki jo je
    V1-R07 prišla odpravit.
    """

    def test_potrditvena_stran_pred_potrditvijo_telefona_da_409(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        arhiviraj(motor)

        odgovor = odjemalec.get(f"/admin/materials/{UUID_ENA}/delete")

        assert odgovor.status_code == 409
        assert "text/html" in odgovor.headers["content-type"]

    def test_gumb_se_ne_pokaze_dokler_telefon_ni_potrdil(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        arhiviraj(motor)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert f'href="/admin/materials/{UUID_ENA}/delete"' not in besedilo

    def test_gumb_se_pokaze_po_potrditvi(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        arhiviraj(motor, potrjeno=True)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert f'href="/admin/materials/{UUID_ENA}/delete"' in besedilo

    def test_post_pred_potrditvijo_telefona_ne_izbrise(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Gumb, ki ga stran ne izriše, ni varovalka. Ročno vtipkan `POST` mora
        # naleteti na isto pravilo.
        pot = zapisi(motor, slike)
        arhiviraj(motor)

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False
        )

        assert odgovor.status_code == 409
        assert stevilo_vrstic(motor) == 1
        assert pot.exists()

    def test_potrditvena_stran_pove_koliko_vprasanj_ostane(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Brez tega bi bilo brisanje videti nevarnejše, kot je — in po V2 bi
        # operater mislil, da z njim briše tudi statistiko.
        zapisi(motor, slike)
        obdelaj(motor)
        arhiviraj(motor, potrjeno=True)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}/delete").text

        assert "veljavnih: 5" in besedilo

    def test_potrditvena_stran_steje_tudi_upokojena(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Poved je o tem, kaj brisanje **pusti**, in po `ADR-012` ostane oboje.

        Samo veljavna bi bila tu podcenjena številka: operater bi mislil, da
        briše več, kot briše, in prav to zmoto naj bi ta stavek odpravil.
        """
        zapisi(motor, slike)
        obdelaj(motor)
        upokoji_vprasanja(motor)
        dodaj_serijo(motor, koliko=3)
        arhiviraj(motor, potrjeno=True)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}/delete").text

        assert "veljavnih: 3" in besedilo
        assert "upokojenih: 5" in besedilo

    def test_post_izbrise_vrstico_in_datoteko_ter_pelje_v_arhiv(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        pot = zapisi(motor, slike)
        arhiviraj(motor, potrjeno=True)

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False
        )

        # Nazaj v arhiv in ne na predmet: s seznama predmeta je bila slika
        # umaknjena že ob arhiviranju.
        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == "/admin/archive"
        assert stevilo_vrstic(motor) == 0
        assert not pot.exists()

    def test_brisanje_ne_pobrise_sosedov(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        pot_ena = zapisi(motor, slike, UUID_ENA)
        pot_dva = zapisi(motor, slike, UUID_DVA)
        arhiviraj(motor, UUID_ENA, potrjeno=True)

        odjemalec.post(f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False)

        assert not pot_ena.exists()
        assert pot_dva.exists()
        assert stevilo_vrstic(motor) == 1

    def test_potrditvena_stran_neobstojecega_da_404(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get(f"/admin/materials/{UUID_ENA}/delete")

        assert odgovor.status_code == 404
        assert "text/html" in odgovor.headers["content-type"]

    def test_brisanje_ze_izbrisanega_pelje_v_arhiv(self, odjemalec: TestClient) -> None:
        # Zahteva V1-R04: „brez sesutja, preusmeritev na seznam". To se zgodi,
        # ko je operater isto sliko izbrisal v drugem zavihku — rezultat je
        # tak, kot ga je hotel.
        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False
        )

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == "/admin/archive"

    def test_brisanje_zapisa_brez_datoteke_uspe(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, vsebina=None)
        arhiviraj(motor, potrjeno=True)

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False
        )

        assert odgovor.status_code == 303
        assert stevilo_vrstic(motor) == 0


class TestPrijavaOstajaZahtevanaDrugod:
    """Regresija iz `ADR-006`, prepisana po `ADR-027`: izvzetje `/admin` ne
    sme odpreti ničesar drugega.

    Ta razred je razlog, da izvzetje predpone sploh sme obstajati. Če pade,
    je strežnik odprt — ne glede na to, ali admin stran deluje.

    Besedilo se je z V3-R04 spremenilo iz „brez ključa“ v
    „brez veljavnega žetona“, namen pa ne. Test s **starim ključem** je
    pri tem pridobil nov pomen: dokazuje, da prehod ni postopen in da stara
    skrivnost ne odpre več ničesar (`ADR-036`).
    """

    def test_admin_je_dosegljiv_brez_zetona(self, odjemalec: TestClient) -> None:
        assert odjemalec.get("/admin").status_code == 200

    def test_materials_brez_zetona_ostaja_401(self, odjemalec: TestClient, motor: Engine) -> None:
        odgovor = odjemalec.post(
            "/materials",
            data={"id": UUID_ENA, "subject": "MAT", "taken_at": "2026-09-04T07:30:00Z"},
            files={"file": ("posnetek.jpg", b"slika", "image/jpeg")},
        )

        assert odgovor.status_code == 401
        assert stevilo_vrstic(motor) == 0

    def test_materials_s_starim_kljucem_ostaja_401(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        # Glava, s katero je telefon govoril do V3-R04. Prehod je oster:
        # ključ ne velja nikjer več in ne sme biti nadomestna pot.
        odgovor = odjemalec.post(
            "/materials",
            headers={"X-API-Key": "star-kljuc-a-dovolj-dolg"},
            data={"id": UUID_ENA, "subject": "MAT", "taken_at": "2026-09-04T07:30:00Z"},
            files={"file": ("posnetek.jpg", b"slika", "image/jpeg")},
        )

        assert odgovor.status_code == 401
        assert stevilo_vrstic(motor) == 0

    def test_materials_z_veljavnim_zetonom_se_vedno_dela(
        self, odjemalec: TestClient, motor: Engine, telefon: SejaTesta
    ) -> None:
        # Brez tega bi prejšnja dva testa ostala zelena tudi, če bi bila pot
        # pokvarjena in bi vračala 401 vsem.
        odgovor = odjemalec.post(
            "/materials",
            headers=telefon.glave,
            data={"id": UUID_ENA, "subject": "MAT", "taken_at": "2026-09-04T07:30:00Z"},
            files={"file": ("posnetek.jpg", b"slika", "image/jpeg")},
        )

        assert odgovor.status_code == 201
        assert stevilo_vrstic(motor) == 1

    def test_pot_ki_se_le_zacne_kot_admin_ni_izvzeta(self, odjemalec: TestClient) -> None:
        # Golo `startswith("/admin")` bi to pot spustilo skozi preverbo žetona.
        for pot in ("/administration", "/admin-nekaj", "/adminmaterials"):
            assert odjemalec.get(pot).status_code == 401, pot

    def test_health_ostaja_dosegljiv_brez_zetona(self, odjemalec: TestClient) -> None:
        assert odjemalec.get("/health").status_code == 200


class TestUbezanje:
    """Vsebina iz baze ne sme priti v HTML nespremenjena.

    `subject` je na `POST /materials` omejen samo na dolžino (`min_length=1,
    max_length=16`), ne na nabor znakov — poljubnih šestnajst znakov gre skozi
    in konča v izpisu. Ubežanje je bil edini razlog, da je bila izbrana Jinja2
    namesto sestavljanja HTML iz nizov (odločitev 1 v `docs/plan/V1-R04.md`);
    brez tega razreda tega razloga ni dokazoval noben test.
    """

    #: Napad **brez poševnice**. To ni podrobnost: prva različica teh testov je
    #: uporabljala `<script>x</script>`, in poševnica v njem je pomenila, da
    #: zahtevek do `predmet.html` in do sporočila s kodo sploh ni prišel —
    #: testa sta preverjala odsotnost napada, ki ga tja nihče ni poslal, in
    #: ostala zelena tudi z izklopljenim ubežanjem.
    NAPAD = "<img src=x onerror=alert(1)>"

    def test_predmet_na_seznamu_je_ubezan(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, subject=self.NAPAD)

        besedilo = odjemalec.get("/admin").text

        assert self.NAPAD not in besedilo
        assert "&lt;img" in besedilo

    def test_predmet_v_naslovu_strani_je_ubezan(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, subject=self.NAPAD)

        besedilo = odjemalec.get(f"/admin/subjects/{self.NAPAD}").text

        assert self.NAPAD not in besedilo

    def test_predmet_v_podrobnostih_je_ubezan(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, subject=self.NAPAD)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert self.NAPAD not in besedilo

    def test_pot_do_datoteke_je_ubezana(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, vsebina=None)
        with Session(motor) as seja:
            material = seja.get(Material, UUID_ENA)
            assert material is not None
            material.image_path = f"/data/images/{self.NAPAD}.jpg"
            seja.commit()

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert self.NAPAD not in besedilo

    def test_predmet_na_potrditveni_strani_je_ubezan(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, subject=self.NAPAD)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}/archive").text

        assert self.NAPAD not in besedilo

    def test_sporocilo_na_strani_404_je_ubezano(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get(f"/admin/subjects/{self.NAPAD}")

        assert odgovor.status_code == 404
        assert self.NAPAD not in odgovor.text


class TestNeznanePoti:
    """Karkoli pod `/admin`, česar ni, mora biti slovenska stran."""

    def test_neznana_pod_pot_da_slovensko_stran(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get("/admin/nekaj/cesar/ni")

        assert odgovor.status_code == 404
        assert "text/html" in odgovor.headers["content-type"]
        assert '"detail"' not in odgovor.text

    def test_koda_s_posevnico_je_dosegljiva(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # `subject` sme vsebovati poševnico (`POST /materials` ga omejuje samo
        # po dolžini). Brez pretvornika `:path` bi bila povezava s strani
        # `/admin` slepa ulica in slike takega predmeta nedosegljive.
        zapisi(motor, slike, subject="A/B")

        odgovor = odjemalec.get("/admin/subjects/A/B")

        assert odgovor.status_code == 200
        assert UUID_ENA in odgovor.text

    def test_koda_z_vprasajem_je_dosegljiva_s_povezave(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # `?` in `#` bi povezavo prerezala; predloga kodo zato ubeži za URL.
        zapisi(motor, slike, subject="A?B")

        seznam = odjemalec.get("/admin").text
        assert "/admin/subjects/A%3FB" in seznam

        odgovor = odjemalec.get("/admin/subjects/A%3FB")
        assert odgovor.status_code == 200
        assert UUID_ENA in odgovor.text

    def test_prestreznik_ne_prekrije_pravih_poti(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        assert odjemalec.get("/admin").status_code == 200
        assert odjemalec.get("/admin/subjects/MAT").status_code == 200
        assert odjemalec.get(f"/admin/materials/{UUID_ENA}").status_code == 200
        assert odjemalec.get(f"/admin/materials/{UUID_ENA}/image").status_code == 200
        assert odjemalec.get(f"/admin/materials/{UUID_ENA}/archive").status_code == 200
        assert odjemalec.get("/admin/archive").status_code == 200

    def test_koncna_posevnica_preusmeri_in_ne_pade(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # `/admin/` je naslov, ki ga brskalnik ponudi sam. Prva različica te
        # zahteve je imela pot `/{ostanek:path}`, ki je Starlettejevo
        # preusmeritev prekrila in vrnila 404 s trditvijo, da strani ni.
        zapisi(motor, slike)

        assert odjemalec.get("/admin/", follow_redirects=True).status_code == 200
        assert odjemalec.get("/admin/subjects/MAT/", follow_redirects=True).status_code == 200

    def test_neznana_pot_s_postom_da_slovensko_stran(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.post("/admin/nekaj/cesar/ni")

        assert odgovor.status_code == 404
        assert "text/html" in odgovor.headers["content-type"]
        assert '"detail"' not in odgovor.text

    def test_napacna_metoda_pod_admin_da_slovensko_stran(self, odjemalec: TestClient) -> None:
        # `/admin` obstaja, a samo kot GET. Lovilec `/{ostanek:path}` tega
        # primera ni pokril; prestreznik ga.
        odgovor = odjemalec.post("/admin")

        assert odgovor.status_code == 405
        # Privzeti ročnik pošlje `Allow`; prestreznik je ne sme zavreči.
        assert odgovor.headers["allow"] == "GET"
        assert "text/html" in odgovor.headers["content-type"]
        assert '"detail"' not in odgovor.text

    def test_napake_izven_admin_ostanejo_json(
        self, odjemalec: TestClient, telefon: SejaTesta
    ) -> None:
        # Prestreznik je globalen; za telefon se mora umakniti privzetemu.
        odgovor = odjemalec.get("/materials", headers=telefon.glave)

        assert odgovor.status_code == 405
        assert "application/json" in odgovor.headers["content-type"]


class TestPakiranje:
    """Predloge morajo biti v nameščenem paketu, ne le v izvorni mapi."""

    def test_predloge_so_navedene_kot_podatki_paketa(self) -> None:
        # Gradnje kolesa v enotskem testu ne poganjamo — predolgo traja in
        # zahteva omrežje. Ta test varuje prav vrstico, brez katere predloge
        # iz kolesa izpadejo, testi pa ostanejo zeleni (odločitev 9 v
        # `docs/plan/V1-R04.md`).
        besedilo = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(
            encoding="utf-8"
        )

        assert "[tool.setuptools.package-data]" in besedilo
        assert 'app = ["templates/*.html"]' in besedilo

    def test_vse_predloge_so_v_mapi_paketa(self) -> None:
        from app.routers.admin import MAPA_PREDLOG

        imena = {pot.name for pot in MAPA_PREDLOG.glob("*.html")}

        assert imena == {
            "osnova.html",
            "predmeti.html",
            "predmet.html",
            "snov.html",
            "arhiv.html",
            "arhiviranje.html",
            "brisanje.html",
            "najdena-ni.html",
            # V2-R01. Seznam je napisan na roko namenoma: nova predloga mora
            # test podreti, da se nekdo vpraša, ali je res zajeta v paket.
            "kvizi-izbirnik.html",
            "kvizi-predogled.html",
            "kviz.html",
            # V2-R03.
            "kviz-tisk.html",
            # V2-R04.
            "statistika.html",
            "statistika-predmet.html",
            "_statistika.html",
            # V2-R07.
            "dnevi.html",
            # V3-R03.
            "prijava.html",
            # V3-R06.
            "clani.html",
            "clani-geslo.html",
            "clani-stanje.html",
            # V3-R09.
            "urnik.html",
            # V3-R05.
            "sistem.html",
            "sistem-druzina.html",
            "sistem-stanje.html",
            # V3-R08.
            "racun.html",
            # V3-R11.
            "prepisi.html",
        }


class TestBrezJavaScripta:
    """Stran ne sme uporabljati JavaScripta — razen kjer ga zahteva izrecno uvede.

    Kriterij iz `docs/verzije/v1.md` in odločitev 1 v planu: vsa dinamika so
    obrazci. Brez tega testa bi bila zahteva izpolnjena samo, dokler se je
    nekdo spomni — dodan `<script>` ne bi podrl ničesar.

    `ADR-024` skripto dovoljuje kot nadgradnjo in `V2-R08` jo uvede na strani s
    podrobnostmi snovi. Test je zato **zožen, ne izbrisan**: izvzeta je samo
    `snov.html` (in s tem njena izrisana stran), za katero meje `ADR-024`
    preverja `TestPovecava`. Vsaka druga predloga ostane pod polnim testom.
    """

    #: Vzorci, ki pomenijo, da se na strani izvaja koda.
    VZORCI = ("<script", "javascript:", "onclick=", "onload=", "onerror=", "onsubmit=")

    #: Predloge, ki skripto smejo imeti. `snov.html`: povečan prikaz, V2-R08.
    #: `prepisi.html`: gumb „Kopiraj v odložišče", V3-R11 (`ADR-048` C).
    IZVZETE = ("snov.html", "prepisi.html")

    def test_v_predlogah_ni_javascripta(self) -> None:
        from app.routers.admin import MAPA_PREDLOG

        najdeno = [
            f"{pot.name}: {vzorec}"
            for pot in sorted(MAPA_PREDLOG.glob("*.html"))
            if pot.name not in self.IZVZETE
            for vzorec in self.VZORCI
            if vzorec in pot.read_text(encoding="utf-8").lower()
        ]

        assert najdeno == []

    def test_v_izrisani_strani_ni_javascripta(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Predloge so eno, izris drugo: skript bi lahko prišel tudi iz vsebine.
        # Podrobnosti snovi tu ni več — izvzete so z `IZVZETE`.
        zapisi(motor, slike)

        for pot in (
            "/admin",
            "/admin/subjects/MAT",
            f"/admin/materials/{UUID_ENA}/delete",
        ):
            besedilo = odjemalec.get(pot).text.lower()
            for vzorec in self.VZORCI:
                assert vzorec not in besedilo, f"{pot} vsebuje {vzorec}"


#: Tretji identifikator za listanje; po abecedi je za `UUID_ENA` in `UUID_DVA`.
UUID_TRI = "c0ffee00-1234-4abc-8def-001122334455"


def del_povecave(besedilo: str) -> str:
    """Del strani s povečanim prikazom, brez skripte za njim.

    Trditve o puščicah in prenosu morajo veljati prav v prikazu: ista pot do
    slike je na strani tudi ob sliki v podrobnostih.
    """
    zacetek = besedilo.index('<div class="prekritje" id="prekritje"')
    return besedilo[zacetek : besedilo.index("<script>", zacetek)]


def skripta(besedilo: str) -> str:
    """Telo edine skripte na strani."""
    zacetek = besedilo.index("<script>")
    return besedilo[zacetek : besedilo.index("</script>", zacetek)]


class TestPovecava:
    """Povečan prikaz slike na `GET /admin/materials/{id}` (V2-R08).

    Testi dokazujejo samo, kar je v izrisu. **Kako se prikaz obnaša** — da se
    odpre, zapre z `Esc` in klikom zunaj, da stran ne drsi, da tipki listata —
    pytest ne izvede in se preveri ročno v fazi 9b (`docs/odlocitve/ADR-024`,
    „Posledice").
    """

    @staticmethod
    def stran(odjemalec: TestClient, material_id: str) -> str:
        odgovor = odjemalec.get(f"/admin/materials/{material_id}")
        assert odgovor.status_code == 200
        return odgovor.text

    @staticmethod
    def tri_zaporedne(motor: Engine, slike: Path, subject: str = "MAT") -> None:
        """Tri slike istega predmeta; najnovejša je `UUID_TRI`, najstarejša `UUID_ENA`."""
        zapisi(motor, slike, UUID_ENA, subject, "2026-09-04T07:30:00+00:00")
        zapisi(motor, slike, UUID_DVA, subject, "2026-09-04T08:30:00+00:00")
        zapisi(motor, slike, UUID_TRI, subject, "2026-09-04T09:30:00+00:00")

    # --- Povečan prikaz ---

    def test_slika_je_povezava_na_izvirnik(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Meja 3 `ADR-024`: brez skripte klik odpre izvirnik.
        zapisi(motor, slike)

        besedilo = self.stran(odjemalec, UUID_ENA)

        assert re.search(
            rf'<a class="povecaj" href="/admin/materials/{UUID_ENA}/image" data-povecava>'
            rf'\s*<img src="/admin/materials/{UUID_ENA}/image"',
            besedilo,
        )

    def test_prikaz_je_v_izrisu_skrit(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Brez skripte ga ne sme biti videti. `display: grid` bi atribut
        # `hidden` prevladal, zato je pravilo, ki ga vrne, del dokaza.
        zapisi(motor, slike)

        besedilo = self.stran(odjemalec, UUID_ENA)

        assert '<div class="prekritje" id="prekritje" hidden>' in besedilo
        assert ".prekritje[hidden] { display: none; }" in besedilo

    def test_prikaz_kaze_isto_datoteko_brez_omejitve_visine(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        besedilo = self.stran(odjemalec, UUID_ENA)
        prikaz = del_povecave(besedilo)

        assert re.findall(r'src="([^"]*)"', prikaz) == [f"/admin/materials/{UUID_ENA}/image"]
        # `max-height: 78vh` velja za `.snov img`. Prikaz stoji za zadnjim
        # elementom `.snov` (povezava nazaj), torej zunaj njega.
        assert besedilo.index('<div class="prekritje"') > besedilo.index('class="nazaj"')

    def test_prikaz_ima_gumb_za_zapiranje(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        prikaz = del_povecave(self.stran(odjemalec, UUID_ENA))

        assert '<button class="prekritje-gumb" type="button" id="prekritje-zapri">' in prikaz

    @pytest.mark.parametrize(
        ("taken_at", "ime"),
        [
            ("2026-09-04T07:30:00+00:00", "MAT_2026-09-04_09-30.jpg"),  # poletni čas
            ("2026-12-01T23:15:00+00:00", "MAT_2026-12-02_00-15.jpg"),  # zimski, čez polnoč
        ],
    )
    def test_prenos_nosi_predmet_in_lokalni_cas(
        self, odjemalec: TestClient, motor: Engine, slike: Path, taken_at: str, ime: str
    ) -> None:
        zapisi(motor, slike, taken_at=taken_at)

        prikaz = del_povecave(self.stran(odjemalec, UUID_ENA))

        prenos = re.search(
            rf'<a class="prekritje-gumb" href="/admin/materials/{UUID_ENA}/image"'
            r'\s+download="([^"]*)">',
            prikaz,
        )
        assert prenos is not None
        assert prenos.group(1) == ime

    def test_ime_prenosa_nadomesti_nevarne_znake(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, subject="A/B? č")

        prikaz = del_povecave(self.stran(odjemalec, UUID_ENA))

        assert 'download="A_B____2026-09-04_09-30.jpg"' in prikaz

    def test_brez_datoteke_ni_prikaza(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, vsebina=None)

        besedilo = self.stran(odjemalec, UUID_ENA)

        assert "data-povecava" not in besedilo
        assert 'id="prekritje"' not in besedilo
        assert "<script" not in besedilo
        assert f'href="/admin/materials/{UUID_ENA}/image"' not in besedilo
        # Obstoječe sporočilo ostane dobesedno.
        assert "Zapis v bazi obstaja, slike na disku pa ni." in besedilo

    # --- Listanje ---

    def test_sosedi_v_sredini(self, odjemalec: TestClient, motor: Engine, slike: Path) -> None:
        # Smer mreže na strani predmeta: levo novejša, desno starejša.
        self.tri_zaporedne(motor, slike)

        prikaz = del_povecave(self.stran(odjemalec, UUID_DVA))

        assert f'id="prekritje-prejsnja" href="/admin/materials/{UUID_TRI}#povecano"' in prikaz
        assert f'id="prekritje-naslednja" href="/admin/materials/{UUID_ENA}#povecano"' in prikaz
        assert "neaktivna" not in prikaz

    def test_prva_slika_ima_neaktivno_prejsnjo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        self.tri_zaporedne(motor, slike)

        prikaz = del_povecave(self.stran(odjemalec, UUID_TRI))

        assert '<span class="puscica neaktivna" aria-disabled="true">←</span>' in prikaz
        assert 'id="prekritje-prejsnja"' not in prikaz
        assert f'id="prekritje-naslednja" href="/admin/materials/{UUID_DVA}#povecano"' in prikaz

    def test_zadnja_slika_ima_neaktivno_naslednjo_in_ne_ovije(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        self.tri_zaporedne(motor, slike)

        prikaz = del_povecave(self.stran(odjemalec, UUID_ENA))

        assert '<span class="puscica neaktivna" aria-disabled="true">→</span>' in prikaz
        assert 'id="prekritje-naslednja"' not in prikaz
        assert f"/admin/materials/{UUID_TRI}#povecano" not in prikaz
        assert f'id="prekritje-prejsnja" href="/admin/materials/{UUID_DVA}#povecano"' in prikaz

    def test_edina_slika_ima_obe_puscici_neaktivni(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        prikaz = del_povecave(self.stran(odjemalec, UUID_ENA))

        assert prikaz.count('class="puscica neaktivna" aria-disabled="true"') == 2
        assert "#povecano" not in prikaz

    def test_drug_predmet_ni_sosed(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA, "MAT", "2026-09-04T07:30:00+00:00")
        zapisi(motor, slike, UUID_DVA, "SLO", "2026-09-04T08:30:00+00:00")
        zapisi(motor, slike, UUID_TRI, "MAT", "2026-09-04T09:30:00+00:00")

        prikaz = del_povecave(self.stran(odjemalec, UUID_TRI))

        assert f'id="prekritje-naslednja" href="/admin/materials/{UUID_ENA}#povecano"' in prikaz
        assert UUID_DVA not in prikaz

    def test_arhiviran_sosed_izpade(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        self.tri_zaporedne(motor, slike)
        arhiviraj(motor, UUID_DVA)

        prikaz = del_povecave(self.stran(odjemalec, UUID_TRI))

        assert f'id="prekritje-naslednja" href="/admin/materials/{UUID_ENA}#povecano"' in prikaz
        assert UUID_DVA not in prikaz

    def test_arhivirana_snov_ima_prikaz_brez_puscic(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        self.tri_zaporedne(motor, slike)
        arhiviraj(motor, UUID_DVA)

        besedilo = self.stran(odjemalec, UUID_DVA)
        prikaz = del_povecave(besedilo)

        assert "data-povecava" in besedilo
        assert f'src="/admin/materials/{UUID_DVA}/image"' in prikaz
        assert "puscica" not in prikaz
        assert "#povecano" not in prikaz

    def test_neznana_koda_ima_puscici(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Popravljen kriterij V2-R08: neznana koda s slikami ima svojo stran
        # predmeta in je v naboru.
        zapisi(motor, slike, UUID_ENA, "XYZ", "2026-09-04T07:30:00+00:00")
        zapisi(motor, slike, UUID_DVA, "XYZ", "2026-09-04T08:30:00+00:00")

        prikaz = del_povecave(self.stran(odjemalec, UUID_DVA))

        assert f'id="prekritje-naslednja" href="/admin/materials/{UUID_ENA}#povecano"' in prikaz
        assert '<span class="puscica neaktivna" aria-disabled="true">←</span>' in prikaz

    def test_enak_cas_obisce_obe_sliki(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # `UUID_ENA` je vstavljen prvi, da vrstni red vstavljanja ne more
        # nadomestiti razvrščanja po `id` (`id DESC`: `UUID_DVA` je prvi).
        zapisi(motor, slike, UUID_ENA, "MAT", "2026-09-04T07:30:00+00:00")
        zapisi(motor, slike, UUID_DVA, "MAT", "2026-09-04T07:30:00+00:00")

        prva = del_povecave(self.stran(odjemalec, UUID_DVA))
        druga = del_povecave(self.stran(odjemalec, UUID_ENA))
        predmet = odjemalec.get("/admin/subjects/MAT").text

        assert f'id="prekritje-naslednja" href="/admin/materials/{UUID_ENA}#povecano"' in prva
        assert f'id="prekritje-prejsnja" href="/admin/materials/{UUID_DVA}#povecano"' in druga
        assert predmet.index(UUID_DVA) < predmet.index(UUID_ENA)

    # --- Meje `ADR-024` ---

    def test_skripta_ostane_v_mejah(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Meje 1 in 2: vgrajena, brez zunanjega vira. Meja 4: ne pošilja in ne
        # sproža obrazcev. Kaj skripta *počne*, test ne dokaže — samo, česa v
        # njej ni.
        from app.routers.admin import MAPA_PREDLOG

        zapisi(motor, slike)
        besedilo = self.stran(odjemalec, UUID_ENA)
        predloga = (MAPA_PREDLOG / "snov.html").read_text(encoding="utf-8")

        for vir in (besedilo, predloga):
            male = vir.lower()
            assert male.count("<script") == 1
            assert "<script>" in male  # brez atributov, torej brez `src`
            assert "javascript:" not in male
            # Vsak `on…=` in ne le štirje iz `TestBrezJavaScripta.VZORCI`:
            # izvzetje od tistega testa ne sme odpreti `onkeydown=` ali
            # `onfocus=`, ki ju ta stran s skripto prav lahko skuša uporabiti.
            # Odkril pregled v fazi 7.
            assert re.search(r"\son[a-z]+\s*=", male) is None
            telo = skripta(male)
            for prepovedano in ("fetch(", "xmlhttprequest", "sendbeacon", ".submit(", "<form"):
                assert prepovedano not in telo

    def test_skripta_bere_isto_oznako_kot_povezave(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        besedilo = self.stran(odjemalec, UUID_ENA)

        assert 'var OZNAKA = "#povecano";' in skripta(besedilo)


class TestSosediVPredmetu:
    """`MaterialsRepository.sosedi_v_predmetu` (V2-R08).

    Obljuba je „isti nabor in isti vrstni red kot stran predmeta", zato se
    sosedi primerjajo neposredno s `seznam_po_predmetu` nad stanjem, ki vsebuje
    vse, kar bi ju lahko razdružilo: drug predmet, arhiv in enak čas.
    """

    ARHIVIRANA = "d0d0d0d0-0000-4000-8000-000000000001"
    DRUG_PREDMET = "e0e0e0e0-0000-4000-8000-000000000002"

    def test_sosedi_so_sosedi_na_seznamu_predmeta(self, motor: Engine, slike: Path) -> None:
        zapisi(motor, slike, UUID_ENA, "MAT", "2026-09-04T07:30:00+00:00")
        zapisi(motor, slike, UUID_DVA, "MAT", "2026-09-04T07:30:00+00:00")
        zapisi(motor, slike, UUID_TRI, "MAT", "2026-09-04T09:30:00+00:00")
        zapisi(motor, slike, self.ARHIVIRANA, "MAT", "2026-09-04T08:00:00+00:00")
        zapisi(motor, slike, self.DRUG_PREDMET, "SLO", "2026-09-04T08:15:00+00:00")
        arhiviraj(motor, self.ARHIVIRANA)

        with Session(motor) as seja:
            repozitorij = MaterialsRepository(seja, CVEK_ID)
            seznam = [snov.id for snov in repozitorij.seznam_po_predmetu("MAT")]
            sosedi = [
                repozitorij.sosedi_v_predmetu(snov)
                for snov in repozitorij.seznam_po_predmetu("MAT")
            ]

        assert seznam == [UUID_TRI, UUID_DVA, UUID_ENA]
        assert sosedi == [(None, UUID_DVA), (UUID_TRI, UUID_ENA), (UUID_DVA, None)]

    def test_arhivirana_snov_nima_sosedov(self, motor: Engine, slike: Path) -> None:
        zapisi(motor, slike, UUID_ENA, "MAT", "2026-09-04T07:30:00+00:00")
        zapisi(motor, slike, UUID_DVA, "MAT", "2026-09-04T08:30:00+00:00")
        arhiviraj(motor, UUID_ENA)

        with Session(motor) as seja:
            repozitorij = MaterialsRepository(seja, CVEK_ID)
            snov = repozitorij.poisci(UUID_ENA)
            assert snov is not None

            assert repozitorij.sosedi_v_predmetu(snov) == (None, None)


class TestOblikovanje:
    """Enotski testi za pretvorbe, ki jih strani samo izpišejo.

    Prek HTTP je pokrita samo veja, ki jo ustvari testni zapis; ostale vejé
    bi ostale nedokazane, čeprav sta obe v produkciji dosegljivi — posnetek
    zvezka pri 1600 px zna preseči megabajt.
    """

    def test_velikost_v_bajtih(self) -> None:
        from app.routers.admin import _velikost_opis

        assert _velikost_opis(500) == "500 B"

    def test_velikost_v_kilobajtih(self) -> None:
        from app.routers.admin import _velikost_opis

        assert _velikost_opis(2048) == "2 kB"

    def test_velikost_v_megabajtih(self) -> None:
        from app.routers.admin import _velikost_opis

        assert _velikost_opis(2_500_000) == "2.4 MB"

    def test_velikost_manjkajoce_datoteke(self) -> None:
        from app.routers.admin import _velikost_opis

        assert _velikost_opis(None) == "datoteke na disku ni"

    def test_neznano_stanje_se_pokaze_dobesedno(self) -> None:
        # V1-R03 doda stanja; dokler jih ni, se neznano stanje ne sme skriti
        # za besedo „neznano" — operater mora videti, kaj je v bazi.
        from app.subjects import oznaka_statusa

        assert oznaka_statusa("nekaj-cisto-drugega") == "nekaj-cisto-drugega"
        assert oznaka_statusa("ready") == "obdelano"


class TestPrikazUpokojenih:
    """Kriterij V2-R05: razlika med „ni vprašanj" in „vsa so upokojena".

    Brez tega razdelka je razlika nevidna — stran v obeh primerih kaže prazen
    seznam, operater pa iz tega sklepa, da vprašanj ni bilo nikoli. Razdelek
    zato ne visi v veji `ready`, ampak zunaj vseh vej po statusu: snov, ki je
    bila pravkar poslana v ponovno obdelavo, je `new` in prav takrat je to
    edino, kar o njenih vprašanjih sploh piše.
    """

    def test_stran_izrise_samo_veljavna_vprasanja(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Besedila upokojenih vprašanj na strani ni.

        Pomešana med veljavna bi bila neopazna, ker se `position` z vsako
        serijo začne znova (`docs/odlocitve/ADR-015`).
        """
        zapisi(motor, slike)
        obdelaj(motor)
        upokoji_vprasanja(motor)
        dodaj_serijo(motor, koliko=9)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "Vprašanje b9?" in besedilo
        assert "Odgovor b9." in besedilo
        # Prva serija je upokojena; njeno besedilo ne sme priti na stran.
        assert "Vprašanje 1?" not in besedilo
        assert "Odgovor 1." not in besedilo

    def test_stran_pove_koliko_vprasanj_je_upokojenih(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        obdelaj(motor)
        upokoji_vprasanja(motor)
        dodaj_serijo(motor, koliko=9)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "Upokojena vprašanja: 5" in besedilo

    def test_snov_brez_zgodovine_razdelka_nima(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """„Ni vprašanj" — prva stran razlike."""
        zapisi(motor, slike)
        obdelaj(motor, readable=False, koliko_vprasanj=0)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "Upokojena vprašanja" not in besedilo

    def test_snov_po_ponovni_obdelavi_razdelek_ima(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """„Vsa so upokojena" — druga stran razlike.

        Zapis je po gumbu spet `new` in nima nobenega veljavnega vprašanja.
        Prav ta primer je razlog, da razdelek stoji zunaj vej po statusu.
        """
        zapisi(motor, slike)
        obdelaj(motor)

        odjemalec.post(f"/admin/materials/{UUID_ENA}/reprocess")
        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "Upokojena vprašanja: 5" in besedilo


class TestPrikazObdelave:
    """Stran s podrobnostmi mora pokazati izid obdelave (V1-R03)."""

    def test_obdelan_zapis_pokaze_prepis_povzetek_in_vprasanja(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        obdelaj(motor, koliko_vprasanj=6)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "Delci snovi se gibljejo." in besedilo
        assert "Zgradba snovi." in besedilo
        for i in range(1, 7):
            assert f"Vprašanje {i}?" in besedilo
            assert f"Odgovor {i}." in besedilo

    def test_obdelan_zapis_pokaze_model_in_tokene(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Kriterij zahteva ime modela in porabo tokenov.

        Iz tega se dela primerjava med modeli (ADR-008), zato mora biti vidno
        brez brskanja po bazi.
        """
        zapisi(motor, slike)
        obdelaj(motor)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "gpt-4.1-2025-04-14" in besedilo
        assert "1500" in besedilo
        assert "2000" in besedilo

    def test_obdelan_zapis_pokaze_poslani_prompt_in_surov_odgovor(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        obdelaj(motor)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "POSLANI PROMPT ZA MODEL" in besedilo
        assert "Surov odgovor modela" in besedilo

    def test_neobdelan_zapis_sledi_ne_kaze(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Prazni razdelki so šum. Dokler obdelave ni bilo, ni česa pokazati."""
        zapisi(motor, slike)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "Poslani prompt" not in besedilo
        assert "Vprašanja" not in besedilo
        assert "čaka na obdelavo" in besedilo

    def test_neuspela_obdelava_pokaze_napako_in_surov_odgovor(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Kriterij: stran pokaže besedilo napake, kadar je `status='failed'`."""
        zapisi(motor, slike)
        obdelaj(
            motor,
            status=STATUS_NAPAKA,
            readable=None,
            koliko_vprasanj=0,
            error="Storitev OpenAI je zavrnila ključ (HTTP 401).",
        )

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "Obdelava ni uspela" in besedilo
        assert "zavrnila ključ (HTTP 401)" in besedilo
        # Surov odgovor je pri napaki pogosto edini dokaz, zakaj je padlo.
        assert "Surov odgovor modela" in besedilo

    def test_neberljiva_slika_je_oznacena_in_nima_vprasanj(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Petega statusa ni; „obdelano" samo bi bilo tu zavajajoče."""
        zapisi(motor, slike)
        obdelaj(motor, readable=False, koliko_vprasanj=0)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "obdelano — slika ni berljiva" in besedilo
        assert "Slika ni berljiva" in besedilo
        assert "Vprašanja" not in besedilo

    def test_stanje_je_vidno_tudi_v_seznamu_predmeta(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        obdelaj(motor, readable=False, koliko_vprasanj=0)

        besedilo = odjemalec.get("/admin/subjects/MAT").text

        assert "obdelano — slika ni berljiva" in besedilo


class TestPonovnaObdelava:
    """Gumb „Pošlji v obdelavo"."""

    def test_vrne_zapis_v_vrsto_in_preusmeri_na_podrobnosti(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        obdelaj(motor)

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/reprocess", follow_redirects=False
        )

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == f"/admin/materials/{UUID_ENA}"
        with Session(motor) as seja:
            material = seja.get(Material, UUID_ENA)
            assert material is not None
            assert material.status == STATUS_NOV

    def test_zavrze_prejsnji_rezultat_vprasanja_pa_upokoji(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """ADR-009 velja naprej za izid; za vprašanja ga nadomesti ADR-015.

        Do V2-R05 je ta test zahteval prazno tabelo. Sprememba ni oslabitev,
        ampak nova pogodba: gumb, ki vprašanje pobriše, bi razbil kviz, ki
        nanj kaže (`V2-R01`), in statistiko čez leta (`V2-R04`).
        """
        zapisi(motor, slike)
        obdelaj(motor)
        assert stevilo_vprasanj(motor) == 5

        odjemalec.post(f"/admin/materials/{UUID_ENA}/reprocess")

        # Vseh pet vrstic ostane; nobena ni več veljavna.
        assert stevilo_vprasanj(motor) == 5
        assert stevilo_veljavnih(motor) == 0
        with Session(motor) as seja:
            material = seja.get(Material, UUID_ENA)
            assert material is not None
            assert material.transcript is None
            assert material.model is None
            assert material.input_tokens is None

    def test_dela_tudi_iz_stanja_napake(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        obdelaj(motor, status=STATUS_NAPAKA, readable=None, koliko_vprasanj=0, error="padlo")

        odjemalec.post(f"/admin/materials/{UUID_ENA}/reprocess")

        with Session(motor) as seja:
            material = seja.get(Material, UUID_ENA)
            assert material is not None
            assert material.status == STATUS_NOV
            assert material.error is None

    def test_gumb_ni_navadna_povezava(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """`GET` na to pot ne sme ničesar spremeniti.

        Isto pravilo kot pri brisanju (ADR-006): dejanje je nepovratno in
        stane plačan klic, zato ga predpomnilnik ali predogled povezave ne
        smeta sprožiti.
        """
        zapisi(motor, slike)
        obdelaj(motor)

        odgovor = odjemalec.get(f"/admin/materials/{UUID_ENA}/reprocess")

        assert odgovor.status_code == 405
        assert "Ta stran tega dejanja ne podpira." in odgovor.text
        with Session(motor) as seja:
            material = seja.get(Material, UUID_ENA)
            assert material is not None
            assert material.status == STATUS_PRIPRAVLJEN
        assert stevilo_vprasanj(motor) == 5

    def test_neznan_zapis_vrne_stran_in_ne_sled_izjeme(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.post(f"/admin/materials/{UUID_DVA}/reprocess")

        assert odgovor.status_code == 404
        assert "Zapisa s tem identifikatorjem na strežniku ni." in odgovor.text

    def test_zapisa_v_obdelavi_ne_spremeni(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Tam pravkar teče klic; njegov izid bi prišel čez to, kar bi počistili."""
        zapisi(motor, slike)
        obdelaj(motor, status=STATUS_V_OBDELAVI, readable=None, koliko_vprasanj=3)

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/reprocess", follow_redirects=False
        )

        assert odgovor.status_code == 303
        with Session(motor) as seja:
            material = seja.get(Material, UUID_ENA)
            assert material is not None
            assert material.status == STATUS_V_OBDELAVI
        assert stevilo_vprasanj(motor) == 3

    def test_med_obdelavo_gumba_ni(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Gumb, ki ne naredi ničesar, laže."""
        zapisi(motor, slike)
        obdelaj(motor, status=STATUS_V_OBDELAVI, readable=None, koliko_vprasanj=0)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "Pošlji v obdelavo" not in besedilo
        assert "pravkar v obdelavi" in besedilo

    def test_gumb_je_na_strani_obdelanega_zapisa(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        obdelaj(motor)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "Pošlji v obdelavo" in besedilo
        assert f'action="/admin/materials/{UUID_ENA}/reprocess"' in besedilo
        assert 'method="post"' in besedilo


class TestPremikVDrugPredmet:
    """`POST /admin/materials/{id}/subject` (V3-R10, `docs/odlocitve/ADR-040`).

    Otrok ob slikanju včasih izbere napačen predmet. Premik popravi
    `materials.subject` in `questions.subject` **vseh** vprašanj te snovi,
    telefona in objavljenih kvizov pa se ne dotakne.

    Snovi so iz `test_kvizi.snov`, ne iz `zapisi`/`obdelaj` tega modula:
    vprašanja potrebujejo denormaliziran `subject`, ki ga tam zapiše
    `zapisi_izid` — brez njega bi testi premika merili prazno polje.
    """

    POT = f"/admin/materials/{UUID_ENA}/subject"

    @staticmethod
    def predmet(motor: Engine, material_id: str = UUID_ENA) -> str:
        with Session(motor) as seja:
            material = seja.get(Material, material_id)
            assert material is not None
            return material.subject

    @staticmethod
    def predmeti_vprasanj(motor: Engine, material_id: str = UUID_ENA) -> set[str | None]:
        """Predmeti **vseh** vprašanj snovi — veljavnih in upokojenih."""
        with Session(motor) as seja:
            return set(
                seja.scalars(
                    select(Question.subject).where(Question.material_id == material_id)
                )
            )

    @staticmethod
    def premakni(odjemalec: TestClient, koda: str = "SLJ", **kwargs: Any) -> Any:
        return odjemalec.post(
            TestPremikVDrugPredmet.POT, data={"subject": koda}, **kwargs
        )

    # --- Srečna pot ---

    def test_premakne_snov_in_preusmeri_na_njeno_stran(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov_z_vprasanji(motor, slike)

        odgovor = self.premakni(odjemalec, follow_redirects=False)

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == f"/admin/materials/{UUID_ENA}"
        assert self.predmet(motor) == "SLJ"

    def test_slika_je_na_seznamu_novega_predmeta_in_ne_vec_na_starem(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov_z_vprasanji(motor, slike)

        self.premakni(odjemalec)

        assert UUID_ENA in odjemalec.get("/admin/subjects/SLJ").text
        assert UUID_ENA not in odjemalec.get("/admin/subjects/MAT").text

    def test_vprasanja_gredo_zraven_tudi_upokojena(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """`ADR-040` B1: sicer bi bila ista snov v statistiki razcepljena.

        Pade, če `UPDATE questions` dobi pogoj `retired_at IS NULL`: pet
        upokojenih vprašanj bi ostalo pod `MAT`.
        """
        snov_z_vprasanji(motor, slike)
        upokoji(motor)
        # Druga serija na **isti** snovi, kot jo pusti ponovna obdelava.
        with Session(motor) as seja:
            for zaporedje in (1, 2):
                seja.add(
                    Question(
                        family_id=CVEK_ID,
                        id=f"{UUID_ENA}-nova{zaporedje}",
                        material_id=UUID_ENA,
                        position=zaporedje,
                        question=f"Novo vprašanje {zaporedje}?",
                        answer="Nov odgovor.",
                        subject="MAT",
                    )
                )
            seja.commit()
        assert self.predmeti_vprasanj(motor) == {"MAT"}
        assert stevilo_vprasanj(motor) == 7
        assert stevilo_veljavnih(motor) == 2

        self.premakni(odjemalec)

        assert self.predmeti_vprasanj(motor) == {"SLJ"}
        # Premik ni upokojitev in ni brisanje: serije ostanejo take, kot so.
        assert stevilo_vprasanj(motor) == 7
        assert stevilo_veljavnih(motor) == 2

    def test_oba_stavka_sta_ena_transakcija(
        self, motor: Engine, slike: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Kriterij V3-R10: vmesnega stanja med stavkoma ni.

        Če bi `premakni_v_predmet` prvi `UPDATE` commitala sama, bi snov po
        odpovedi baze ostala pod novim predmetom, njena vprašanja pa pod
        starim — in statistika bi bila razcepljena prav na način, ki ga
        `ADR-040` B1 prepoveduje. Test pusti drugi stavek pasti in zahteva,
        da se ne spremeni nič.
        """
        snov_z_vprasanji(motor, slike)

        with Session(motor) as seja:
            pravi = seja.execute

            def pade(stavek: Any, *args: Any, **kwargs: Any) -> Any:
                if "UPDATE questions" in str(stavek):
                    raise RuntimeError("baza je odpovedala med drugim stavkom")
                return pravi(stavek, *args, **kwargs)

            monkeypatch.setattr(seja, "execute", pade)
            with pytest.raises(RuntimeError):
                MaterialsRepository(seja, CVEK_ID).premakni_v_predmet(UUID_ENA, "SLJ")

        assert self.predmet(motor) == "MAT"
        assert self.predmeti_vprasanj(motor) == {"MAT"}

    def test_vprasanja_druge_snovi_ostanejo_pri_starem_predmetu(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Pogoj `material_id` ni okras: brez njega bi šel s sabo cel predmet."""
        snov_z_vprasanji(motor, slike)
        snov_z_vprasanji(motor, slike, UUID_DVA)

        self.premakni(odjemalec)

        assert self.predmet(motor, UUID_DVA) == "MAT"
        assert self.predmeti_vprasanj(motor, UUID_DVA) == {"MAT"}

    def test_vprasanje_tuje_druzine_na_isti_snovi_se_ne_premakne(
        self, odjemalec: TestClient, motor: Engine, slike: Path, tuj_otrok: str
    ) -> None:
        """Pogoj družine nosi **vsak** od obeh stavkov (`ADR-025`).

        Vrstica je podtaknjena: vprašanje tuje družine, ki kaže na snov te.
        Na produkciji tako stanje ne nastane — prav zato ga tu naredimo sami,
        sicer bi bil pogoj družine na `UPDATE questions` nepreverljiv in bi
        ga smel kdo odstraniti kot odvečnega. Prvi stavek ga ne pokrije: ta
        ščiti **snov**, ne vprašanj, ki nanjo kažejo.
        """
        snov_z_vprasanji(motor, slike)
        with Session(motor) as seja:
            seja.add(
                Question(
                    family_id=TUJA_DRUZINA_ID,
                    id="tuje-vprasanje",
                    material_id=UUID_ENA,
                    position=1,
                    question="Tuje vprašanje?",
                    answer="Tuj odgovor.",
                    subject="MAT",
                )
            )
            seja.commit()

        self.premakni(odjemalec)

        with Session(motor) as seja:
            tuje = seja.get(Question, "tuje-vprasanje")
            assert tuje is not None
            assert tuje.subject == "MAT"

    def test_snov_z_neznano_kodo_se_da_vrniti_med_deset(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Koda iz starejše gradnje telefona ni ovira — premik je izhod iz nje."""
        snov_z_vprasanji(motor, slike, subject="FIZ")

        self.premakni(odjemalec, "MAT")

        assert self.predmet(motor) == "MAT"
        assert self.predmeti_vprasanj(motor) == {"MAT"}

    @pytest.mark.parametrize("status", [STATUS_NOV, STATUS_NAPAKA])
    def test_neobdelana_in_padla_snov_se_premakneta(
        self, odjemalec: TestClient, motor: Engine, slike: Path, status: str
    ) -> None:
        """Premik ni vezan na izid obdelave; vprašanja bodo nastala pod novim predmetom."""
        snov_z_vprasanji(motor, slike, status=status, readable=None, vprasanj=0)

        self.premakni(odjemalec)

        assert self.predmet(motor) == "SLJ"

    def test_premik_v_isti_predmet_je_brez_ucinka_in_brez_napake(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov_z_vprasanji(motor, slike)

        odgovor = self.premakni(odjemalec, "MAT", follow_redirects=False)

        assert odgovor.status_code == 303
        assert self.predmet(motor) == "MAT"
        assert self.predmeti_vprasanj(motor) == {"MAT"}

    # --- Kaj gre s premikom in kaj ne ---

    def test_statistika_steje_poskuse_pod_novim_predmetom(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        """Kriterij V3-R10 nad `V2-R04`: statistika predmeta se za nazaj spremeni.

        To je namen premika, ne stranski učinek (`ADR-040` B1).
        """
        snov_z_vprasanji(motor, slike)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=1)
        odgovor = poslji(odjemalec, [poskus(postavke(motor, quiz_id)[0])], telefon)
        assert odgovor.status_code == 200, odgovor.text
        vprasanje = f"Vprašanje 1 iz {UUID_ENA[:4]}?"
        assert vprasanje in odjemalec.get("/admin/statistics/subjects/MAT?leto=vse").text

        self.premakni(odjemalec)

        assert vprasanje in odjemalec.get("/admin/statistics/subjects/SLJ?leto=vse").text
        assert (
            vprasanje not in odjemalec.get("/admin/statistics/subjects/MAT?leto=vse").text
        )

    def test_objavljen_kviz_se_ne_spremeni(
        self, odjemalec: TestClient, motor: Engine, slike: Path, otrok: str
    ) -> None:
        """`ADR-016` E in `ADR-040` D1: ime „MAT — …" je že natisnjeno."""
        snov_z_vprasanji(motor, slike)
        quiz_id = objavi(odjemalec, motor, [UUID_ENA], koliko=3)
        with Session(motor) as seja:
            kviz = seja.get(Quiz, quiz_id)
            assert kviz is not None
            prej = (kviz.subject, kviz.name)
        assert prej[0] == "MAT"
        postavke_prej = postavke(motor, quiz_id)

        self.premakni(odjemalec)

        with Session(motor) as seja:
            kviz = seja.get(Quiz, quiz_id)
            assert kviz is not None
            assert (kviz.subject, kviz.name) == prej
        assert postavke(motor, quiz_id) == postavke_prej

    def test_sosedi_v_povecanem_prikazu_pridejo_iz_novega_predmeta(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Kriterij V3-R10 nad `V2-R08`: nabor sosedov je nabor predmeta."""
        snov_z_vprasanji(motor, slike, taken_at=datetime(2026, 9, 4, 7, 30, tzinfo=UTC))
        snov_z_vprasanji(
            motor,
            slike,
            UUID_DVA,
            subject="SLJ",
            taken_at=datetime(2026, 9, 3, 7, 30, tzinfo=UTC),
        )
        stran = odjemalec.get(f"/admin/materials/{UUID_ENA}").text
        assert UUID_DVA not in del_povecave(stran)

        self.premakni(odjemalec)

        stran = odjemalec.get(f"/admin/materials/{UUID_ENA}").text
        assert UUID_DVA in del_povecave(stran)

    def test_pregled_po_dnevih_kaze_sliko_pod_novim_predmetom(
        self, odjemalec: TestClient, motor: Engine, slike: Path, otrok: str
    ) -> None:
        """Kriterij V3-R10 nad `V2-R07`: dan grupira po `materials.subject`."""
        snov_z_vprasanji(motor, slike, taken_at=datetime(2026, 9, 4, 7, 30, tzinfo=UTC))

        self.premakni(odjemalec)

        besedilo = odjemalec.get("/admin/days?dan=2026-09-04").text
        assert "SLJ — Slovenščina" in besedilo
        assert "MAT — Matematika" not in besedilo

    def test_izbirnik_kvizov_ponudi_sliko_pod_novim_predmetom(
        self, odjemalec: TestClient, motor: Engine, slike: Path, otrok: str
    ) -> None:
        """Kriterij V3-R10 nad `V2-R01`: izbirnik bere `materials.subject`."""
        snov_z_vprasanji(motor, slike)
        assert not je_izbirna(izbirnik(odjemalec, "rocna", "SLJ"), UUID_ENA)

        self.premakni(odjemalec)

        assert je_izbirna(izbirnik(odjemalec, "rocna", "SLJ"), UUID_ENA)

    def test_snov_iz_kviza_v_novem_predmetu_ni_nova(
        self, odjemalec: TestClient, motor: Engine, slike: Path, otrok: str
    ) -> None:
        """„Nova snov" šteje prek vprašanj, ne prek predmeta (`ADR-017` B).

        Snov, ki je bila v kvizu pod `MAT`, v `SLJ` ni nova — kar je pravilno:
        vprašanja so ista in otrok jih je že dobil.
        """
        snov_z_vprasanji(motor, slike)
        objavi(odjemalec, motor, [UUID_ENA], koliko=3)

        self.premakni(odjemalec)

        besedilo = izbirnik(odjemalec, "nova", "SLJ")
        assert je_izbirna(besedilo, UUID_ENA)
        assert not je_obkljukana(besedilo, UUID_ENA)

    def test_ponovni_prenos_iste_slike_popravka_ne_povozi(
        self, odjemalec: TestClient, motor: Engine, slike: Path, telefon: SejaTesta
    ) -> None:
        """Znana omejitev `ADR-040` A1 ima ostro stran: telefon ne sme povoziti.

        Telefon prvotnega predmeta pri sebi ne popravi in prenos ponavlja,
        dokler ne dobi odgovora. Ponovni prenos iste slike zato pride s
        **starim** predmetom — in prenos mora ostati idempotenten glede na
        `id`, sicer bi popravek izginil ob naslednji sinhronizaciji.
        """
        snov_z_vprasanji(motor, slike)
        self.premakni(odjemalec)

        odgovor = odjemalec.post(
            "/materials",
            data={"id": UUID_ENA, "subject": "MAT", "taken_at": "2026-09-04T07:30:00Z"},
            files={"file": ("posnetek.jpg", b"slika", "image/jpeg")},
            headers=telefon.glave,
        )

        assert odgovor.status_code == 200
        assert odgovor.json()["created"] is False
        assert self.predmet(motor) == "SLJ"

    # --- Zavrnitve ---

    def test_neznana_koda_vrne_400_in_nic_ne_spremeni(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov_z_vprasanji(motor, slike)

        odgovor = self.premakni(odjemalec, "XYZ")

        assert odgovor.status_code == 400
        assert "ni na seznamu desetih predmetov" in odgovor.text
        assert self.predmet(motor) == "MAT"
        assert self.predmeti_vprasanj(motor) == {"MAT"}

    def test_prazna_koda_vrne_400_in_ne_422(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Manjkajoče polje mora dobiti slovensko stran, ne FastAPIjevega JSON-a."""
        snov_z_vprasanji(motor, slike)

        odgovor = odjemalec.post(self.POT)

        assert odgovor.status_code == 400
        assert "ni na seznamu desetih predmetov" in odgovor.text
        assert self.predmet(motor) == "MAT"

    def test_arhivirane_snovi_ne_premakne(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """`ADR-011`: arhiv je umik, ne urejanje.

        Pade, če iz `UPDATE` odstranim pogoj `archived_at IS NULL`.
        """
        snov_z_vprasanji(motor, slike, arhivirana=True)

        odgovor = self.premakni(odjemalec, follow_redirects=False)

        assert odgovor.status_code == 303
        assert self.predmet(motor) == "MAT"
        assert self.predmeti_vprasanj(motor) == {"MAT"}

    def test_snovi_v_obdelavi_ne_premakne(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """`ADR-040` C1: tam pravkar teče worker in piše vprašanja.

        Pade, če iz `UPDATE` odstranim pogoj `status <> 'processing'`.
        """
        snov_z_vprasanji(motor, slike, status=STATUS_V_OBDELAVI, readable=None)

        odgovor = self.premakni(odjemalec, follow_redirects=False)

        assert odgovor.status_code == 303
        assert self.predmet(motor) == "MAT"
        assert self.predmeti_vprasanj(motor) == {"MAT"}

    def test_neznan_zapis_vrne_stran_in_ne_sled_izjeme(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_DVA}/subject", data={"subject": "SLJ"}
        )

        assert odgovor.status_code == 404
        assert "Zapisa s tem identifikatorjem na strežniku ni." in odgovor.text

    def test_brez_csrf_zetona_je_zavrnjen(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Ista plast kot pri vsakem drugem `POST` pod `/admin` (`ADR-035`)."""
        snov_z_vprasanji(motor, slike)

        odgovor = odjemalec.post(self.POT, data={"subject": "SLJ", "csrf": ""})

        assert odgovor.status_code == 403
        assert self.predmet(motor) == "MAT"

    def test_pot_ni_navadna_povezava(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """`GET` na to pot ne sme ničesar spremeniti."""
        snov_z_vprasanji(motor, slike)

        odgovor = odjemalec.get(f"{self.POT}?subject=SLJ")

        assert odgovor.status_code == 405
        assert self.predmet(motor) == "MAT"

    # --- Obrazec ---

    def test_obrazec_ponudi_deset_predmetov_v_vrstnem_redu_urnika(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov_z_vprasanji(motor, slike)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert re.findall(r'<option value="([A-Z]+)"', besedilo) == [
            predmet.koda for predmet in PREDMETI
        ]
        assert f'action="/admin/materials/{UUID_ENA}/subject"' in besedilo

    def test_obrazec_ima_vnaprej_izbran_trenutni_predmet(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        snov_z_vprasanji(motor, slike)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert '<option value="MAT" selected>' in besedilo
        assert besedilo.count(" selected>") == 1

    def test_obrazec_snovi_z_neznano_kodo_nima_tihega_privzetka(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Snov s kodo zunaj desetih ne sme dobiti prve možnosti za privzetek.

        Brez vodilne možnosti bi brskalnik pokazal `NAR` in klik na „Premakni"
        bi snov tiho vložil pod Naravoslovje.
        """
        snov_z_vprasanji(motor, slike, subject="FIZ")

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert re.findall(r'<option value="([A-Z]*)" selected', besedilo) == [""]
        assert "FIZ — ni na seznamu" in besedilo

    def test_obrazca_ni_na_arhivirani_snovi_in_na_snovi_v_obdelavi(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Gumb, ki ne bi naredil ničesar, laže — pogoj pa je tudi v poti."""
        snov_z_vprasanji(motor, slike, arhivirana=True)
        snov_z_vprasanji(motor, slike, UUID_DVA, status=STATUS_V_OBDELAVI, readable=None)

        for material_id in (UUID_ENA, UUID_DVA):
            besedilo = odjemalec.get(f"/admin/materials/{material_id}").text
            assert 'name="subject"' not in besedilo, material_id
            assert "Premakni" not in besedilo, material_id

    def test_obrazec_ne_prinese_nove_skripte(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """`ADR-024`: edina skripta te strani ostane povečan prikaz (V2-R08)."""
        snov_z_vprasanji(motor, slike)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert besedilo.count("<script") == 1


class TestBrisanjeZVprasanji:
    """Regresija V1-R07: dokončno brisanje mora vprašanja **pustiti**.

    Do V1-R07 sta tu stali dve kaskadi, ki sta vprašanja pobrisali skupaj z
    materialom, in ta razred je to zahteval. `docs/odlocitve/ADR-012` obrne
    pravilo: vprašanje nosi statistiko, ki jo bo V2 vezala nanj, in te ne sme
    vzeti brisanje slike. Test ni oslabljen, ampak obrnjen skupaj s pogodbo.
    """

    def test_brisanje_pusti_vprasanja_in_jim_vzame_material(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        pot = zapisi(motor, slike)
        obdelaj(motor)
        arhiviraj(motor, potrjeno=True)
        assert stevilo_vprasanj(motor) == 5

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False
        )

        assert odgovor.status_code == 303
        assert stevilo_vrstic(motor) == 0
        assert stevilo_vprasanj(motor) == 5
        assert not pot.exists()

        with Session(motor) as seja:
            for vprasanje in seja.scalars(select(Question)):
                assert vprasanje.material_id is None

    def test_brisanje_pusti_tudi_upokojena_vprasanja(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """`ADR-012` ne pozna razlike med veljavnim in upokojenim vprašanjem.

        Ta test je razlog, da zveza `Material.vsa_vprasanja` sploh obstaja:
        nuliranje `material_id` ob brisanju opravi ORM prek nje, in filtrirana
        zveza upokojenih vprašanj ne bi videla. Na SQLite tuji ključi privzeto
        niso uveljavljeni, zato bi ta vrsta napake ostala zelena tu in se
        pokazala šele na Postgresu.
        """
        pot = zapisi(motor, slike)
        obdelaj(motor)
        upokoji_vprasanja(motor)
        dodaj_serijo(motor, koliko=9)
        arhiviraj(motor, potrjeno=True)
        assert stevilo_vprasanj(motor) == 14

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False
        )

        assert odgovor.status_code == 303
        assert stevilo_vrstic(motor) == 0
        assert not pot.exists()
        # Vseh štirinajst ostane, veljavnih in upokojenih enako.
        assert stevilo_vprasanj(motor) == 14
        assert stevilo_veljavnih(motor) == 9
        with Session(motor) as seja:
            for vprasanje in seja.scalars(select(Question)):
                assert vprasanje.material_id is None

    def test_brisanje_ne_zamaje_vprasanj_drugega_materiala(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Sosedov material mora ostati pripet svojim vprašanjem."""
        zapisi(motor, slike, UUID_ENA)
        zapisi(motor, slike, UUID_DVA)
        obdelaj(motor, UUID_ENA, koliko_vprasanj=5)
        obdelaj(motor, UUID_DVA, koliko_vprasanj=4)
        arhiviraj(motor, UUID_ENA, potrjeno=True)

        odjemalec.post(f"/admin/materials/{UUID_ENA}/delete")

        assert stevilo_vprasanj(motor) == 9
        with Session(motor) as seja:
            sosedova = seja.scalars(
                select(Question).where(Question.material_id == UUID_DVA)
            ).all()
            assert len(sosedova) == 4

    def test_ponovna_obdelava_vprasanja_upokoji_in_jim_pusti_material(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Upokojitev ni osirotenje: material ostane, `retired_at` se postavi.

        Do V2-R05 je ta test zahteval, da ponovna obdelava vprašanja pobriše —
        varovalo, da odstranitev `delete-orphan` iz modela (`ADR-012`) brisanja
        tiho ne spremeni v osirotenje. `ADR-015` brisanje odpravi, varovalo pa
        ostane potrebno in se le obrne: vprašanje mora obdržati `material_id`,
        sicer bi bila v bazi kopica vprašanj brez izvora, ki jih ni več mogoče
        povezati s snovjo, iz katere so nastala.
        """
        zapisi(motor, slike)
        obdelaj(motor)

        odjemalec.post(f"/admin/materials/{UUID_ENA}/reprocess")

        assert stevilo_vprasanj(motor) == 5
        assert stevilo_veljavnih(motor) == 0
        with Session(motor) as seja:
            for vprasanje in seja.scalars(select(Question)):
                assert vprasanje.material_id == UUID_ENA
                assert vprasanje.retired_at is not None


class TestSledJeVidnaTudiPriNapaki:
    """Kriterij: stran pokaže vsa polja sledi, vključno pri `status='failed'`.

    Ločeno od `TestPrikazObdelave`, ker gre za regresijo: prompt se pri napaki
    prej ni shranil in blok „Poslani prompt" se na strani sploh ni izrisal.
    """

    def test_neuspel_zapis_pokaze_poslani_prompt(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        obdelaj(
            motor,
            status=STATUS_NAPAKA,
            readable=None,
            koliko_vprasanj=0,
            error="Model ni vrnil veljavnega JSON.",
        )

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert "Poslani prompt" in besedilo
        assert "POSLANI PROMPT ZA MODEL" in besedilo
        assert "Surov odgovor modela" in besedilo
        assert "gpt-4.1-2025-04-14" in besedilo
        assert "1500" in besedilo


class TestSlovenskaStevila:
    """Strani izpisujejo števila slik slovensko, z dvojino.

    Do tega popravka so vse tri pisale „2 slik". Napaka je bila vidna vsak dan
    in je ni ujel noben test — nobena trditev se besedila ni dotaknila.
    """

    def test_pregled_sesteje_cez_predmete(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA, subject="MAT")
        zapisi(motor, slike, UUID_DVA, subject="SLJ")

        besedilo = odjemalec.get("/admin").text

        assert "Skupaj 2 sliki v uporabi" in besedilo
        assert "2 slik " not in besedilo

    def test_pregled_pri_eni_sliki(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA)

        assert "Skupaj 1 slika v uporabi" in odjemalec.get("/admin").text

    @pytest.mark.parametrize(
        ("koliko", "pricakovano"),
        [(1, "1 slika,"), (2, "2 sliki,"), (3, "3 slike,"), (5, "5 slik,")],
    )
    def test_seznam_predmeta_sklanja(
        self,
        odjemalec: TestClient,
        motor: Engine,
        slike: Path,
        koliko: int,
        pricakovano: str,
    ) -> None:
        # Dvojina (2) in mala mnozina (3) sta obliki, ki ju je stara koda
        # pisala napacno; 1 in 5 sta bili pravilni ze prej.
        for i in range(koliko):
            zapisi(motor, slike, f"slika-{i:02d}", subject="MAT")

        besedilo = odjemalec.get("/admin/subjects/MAT").text

        assert f"{pricakovano} najnovejša prva." in besedilo

    def test_arhiv_sklanja(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA)
        zapisi(motor, slike, UUID_DVA)
        arhiviraj(motor, UUID_ENA)
        arhiviraj(motor, UUID_DVA, arhivirano="2026-09-06T10:00:00+00:00")

        besedilo = odjemalec.get("/admin/archive").text

        assert "2 sliki, najnovejše arhivirana prva" in besedilo

    def test_v_predlogah_ni_vec_dvooblicnega_sklanjanja(self) -> None:
        """Vzorec `{{ "x" if n == 1 else "y" }}` je bil sam vir napake.

        Test je nad datotekami in ne nad izrisom: nova predloga bi ga sicer
        lahko prinesla nazaj in nihce ne bi opazil, dokler ne bi kdo prebral
        „2 slik" na zaslonu.
        """
        from app.routers.admin import MAPA_PREDLOG

        najdeno = [
            pot.name
            # `rglob` in ne `glob`: mapa je danes ravna, ob prvi podmapi
            # predlog pa bi varovalka tiho nehala varovati.
            for pot in sorted(MAPA_PREDLOG.rglob("*.html"))
            if "== 1 else" in pot.read_text(encoding="utf-8")
        ]

        assert najdeno == []


# --- Prepisi izbranih slik (V3-R11) ---


def blok_povezave(besedilo: str, material_id: str) -> str:
    """Del strani med `<a href="/admin/materials/{id}">` in koncem te povezave.

    Kriterij zahteva, da je kljukica **zunaj** povezave na snov: klik nanjo ne
    sme odpreti podrobnosti. To je trditev o ugnezdenosti in ne o vrstnem redu
    nizov, zato test gleda natanko v ta blok.
    """
    zacetek = besedilo.index(f'<a href="/admin/materials/{material_id}">')
    return besedilo[zacetek : besedilo.index("</a>", zacetek)]


def obrazec_izbora(besedilo: str) -> str:
    """Obrazec za izbor slik na strani predmeta, brez ostanka strani.

    Glava strani ima svoj obrazec za odjavo (V3-R03), zato trditve o „enem
    obrazcu" tečejo nad tem izrezom in ne nad celo stranjo.
    """
    zacetek = besedilo.index('<form method="post" action="/admin/transcripts">')
    return besedilo[zacetek : besedilo.index("</form>", zacetek)]


def polje_prepisov(besedilo: str) -> str:
    """Vsebina polja `<textarea>`, **neubežana** — kot jo vidi uporabnica.

    Brez `unescape` bi bile trditve o dolžini in o vsebini odvisne od tega, ali
    prepis vsebuje `&`, `<` ali `>`: strežnik šteje neubežano besedilo,
    predloga pa v HTML zapiše ubežanega. Odkril pregled v fazi 7.
    """
    zacetek = besedilo.index("<textarea")
    return html.unescape(
        besedilo[besedilo.index(">", zacetek) + 1 : besedilo.index("</textarea>")]
    )


def prepisi(odjemalec: TestClient, koda: str = "MAT", *snovi: str) -> Any:
    """`POST /admin/transcripts` z izborom, kot bi ga poslal obrazec."""
    return odjemalec.post("/admin/transcripts", data={"subject": koda, "snov": list(snovi)})


class TestKljukiceNaStraniPredmeta:
    """Izbor slik na `/admin/subjects/{koda}` (V3-R11).

    Brez JavaScripta: celoten seznam je en obrazec s ponovljenim poljem `snov`,
    „Izberi vse" pa je povezava (`docs/odlocitve/ADR-048` B in G).
    """

    def test_vsaka_slika_ima_kljukico(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA)
        zapisi(motor, slike, UUID_DVA)

        besedilo = odjemalec.get("/admin/subjects/MAT").text

        for material_id in (UUID_ENA, UUID_DVA):
            assert f'type="checkbox" name="snov" value="{material_id}"' in besedilo

    def test_privzeto_ni_obkljukana_nobena(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        assert "checked" not in odjemalec.get("/admin/subjects/MAT").text

    def test_kljukica_je_zunaj_povezave_na_snov(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Sicer bi klik nanjo odprl podrobnosti namesto izbral sliko.
        zapisi(motor, slike)

        besedilo = odjemalec.get("/admin/subjects/MAT").text

        assert "checkbox" not in blok_povezave(besedilo, UUID_ENA)

    def test_seznam_je_en_obrazec_s_csrf_zetonom_in_predmetom(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        besedilo = odjemalec.get("/admin/subjects/MAT").text

        # Natanko en tak obrazec. Trditev o `<form` nasploh ne bi šla: glava
        # strani ima svojega za odjavo (V3-R03).
        assert besedilo.count('action="/admin/transcripts"') == 1
        assert '<form method="post" action="/admin/transcripts">' in besedilo
        assert 'name="csrf"' in obrazec_izbora(besedilo)
        assert '<input type="hidden" name="subject" value="MAT">' in besedilo

    def test_gumb_stoji_nad_seznamom_in_pod_njim(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Predmet nosi čez leto nekaj sto slik; en sam gumb na dnu bi pomenil
        # drsenje čez cel predmet po vsakem izboru na vrhu.
        zapisi(motor, slike)

        besedilo = odjemalec.get("/admin/subjects/MAT").text

        assert besedilo.count("Prepisi izbranih") == 2
        # Oba **v istem obrazcu**: gumb zunaj njega ne bi poslal ničesar.
        assert obrazec_izbora(besedilo).count("Prepisi izbranih") == 2

    def test_izberi_vse_obkljuka_vse(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA)
        zapisi(motor, slike, UUID_DVA)

        besedilo = odjemalec.get("/admin/subjects/MAT?vse=1").text

        assert besedilo.count("checked") == 2

    def test_povezavi_za_izbor_in_ciscenje(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        besedilo = odjemalec.get("/admin/subjects/MAT").text

        assert 'href="/admin/subjects/MAT?vse=1">Izberi vse' in besedilo
        assert 'href="/admin/subjects/MAT">Počisti izbor' in besedilo

    def test_druga_vrednost_parametra_ne_obkljuka(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Vrednost, ki je ne izriše nobena naša povezava, ne sme po tihem
        # obkljukati celega predmeta.
        zapisi(motor, slike)

        assert "checked" not in odjemalec.get("/admin/subjects/MAT?vse=0").text
        assert "checked" not in odjemalec.get("/admin/subjects/MAT?vse=da").text

    def test_prazen_predmet_obrazca_nima(self, odjemalec: TestClient) -> None:
        besedilo = odjemalec.get("/admin/subjects/MAT").text

        assert 'action="/admin/transcripts"' not in besedilo
        assert "Prepisi izbranih" not in besedilo
        assert "Izberi vse" not in besedilo


class TestPrepisiIzbranih:
    """Stran `POST /admin/transcripts` (V3-R11).

    Stran je **trenutni izpis in ne stanje** (`docs/odlocitve/ADR-048` B): v
    bazo se ne zapiše nič, zato je ponovljen `POST` neškodljiv.
    """

    def test_prepis_izbrane_slike_je_v_polju(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        obdelaj(motor)

        odgovor = prepisi(odjemalec, "MAT", UUID_ENA)

        assert odgovor.status_code == 200
        assert "Delci snovi se gibljejo." in polje_prepisov(odgovor.text)

    def test_glava_nosi_kodo_datum_in_uro(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Posneto 07:30 UTC, torej 09:30 doma. Ime meseca in ne `9.`:
        # besedilo se bere zunaj admina (`ADR-048` D).
        zapisi(motor, slike, taken_at="2026-09-04T07:30:00+00:00")
        obdelaj(motor)

        polje = polje_prepisov(prepisi(odjemalec, "MAT", UUID_ENA).text)

        assert polje.startswith("## MAT — 4. september 2026, 09:30")

    def test_ime_otroka_je_v_glavi_pri_vec_otrocih(
        self, odjemalec: TestClient, motor: Engine, slike: Path, otrok: str, brat: str
    ) -> None:
        # Oba otroka: `imena_otrok` je pri enem prazna (`ADR-039` F), zato bi
        # test brez `brat` dokazoval nasprotje od tega, kar pravi ime.
        zapisi(motor, slike)
        obdelaj(motor)

        polje = polje_prepisov(prepisi(odjemalec, "MAT", UUID_ENA).text)

        assert "· Maša" in polje

    def test_druzina_z_enim_otrokom_imena_nima(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        obdelaj(motor)

        assert "·" not in polje_prepisov(prepisi(odjemalec, "MAT", UUID_ENA).text)

    def test_vrstni_red_je_od_najstarejse(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Stran predmeta kaže najnovejše prve; besedilo teče obratno.
        zapisi(motor, slike, UUID_ENA, taken_at="2026-09-01T07:00:00+00:00")
        zapisi(motor, slike, UUID_DVA, taken_at="2026-09-04T07:00:00+00:00")
        obdelaj(motor, UUID_ENA)
        obdelaj(motor, UUID_DVA)

        polje = polje_prepisov(prepisi(odjemalec, "MAT", UUID_ENA, UUID_DVA).text)

        assert polje.index("1. september") < polje.index("4. september")

    def test_slika_brez_prepisa_prispeva_samo_glavo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Neberljiva snov je obdelana, a brez prepisa (`ADR-011`). Kljukica je
        # navadna in v besedilu ostane glava kot sled (`ADR-048` E).
        zapisi(motor, slike)
        obdelaj(motor, readable=False)

        polje = polje_prepisov(prepisi(odjemalec, "MAT", UUID_ENA).text)

        assert polje == "## MAT — 4. september 2026, 09:30\n"

    def test_slika_v_obdelavi_prispeva_samo_glavo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        polje = polje_prepisov(prepisi(odjemalec, "MAT", UUID_ENA).text)

        assert polje == "## MAT — 4. september 2026, 09:30\n"

    def test_stevca_stojita_nad_poljem_in_nista_v_njem(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA)
        zapisi(motor, slike, UUID_DVA)
        obdelaj(motor, UUID_ENA)
        obdelaj(motor, UUID_DVA)

        besedilo = prepisi(odjemalec, "MAT", UUID_ENA, UUID_DVA).text
        polje = polje_prepisov(besedilo)

        assert "2 sliki" in besedilo
        assert f"{len(polje)} znakov" in besedilo
        # Števca sta podatek o besedilu, ne del besedila (`ADR-048` A).
        assert "2 sliki" not in polje
        assert besedilo.index("2 sliki") < besedilo.index("<textarea")

    def test_stevca_sklanjata(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        besedilo = prepisi(odjemalec, "MAT", UUID_ENA).text

        assert "1 slika" in besedilo

    def test_polje_je_samo_za_branje(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Meja 3 iz `ADR-024`: Ctrl+A in Ctrl+C delata tudi brez skripte.
        zapisi(motor, slike)

        besedilo = prepisi(odjemalec, "MAT", UUID_ENA).text

        assert '<textarea id="besedilo" class="prepisi" readonly' in besedilo

    def test_brez_izbora_pove_kaj_narediti_in_polja_nima(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        odgovor = prepisi(odjemalec, "MAT")

        assert odgovor.status_code == 200
        assert "Izberi vsaj eno sliko" in odgovor.text
        assert "<textarea" not in odgovor.text
        assert 'href="/admin/subjects/MAT"' in odgovor.text

    def test_brez_izbora_pri_neznanem_predmetu_pelje_na_pregled(
        self, odjemalec: TestClient
    ) -> None:
        # Stran predmeta, ki nima slik in ni na seznamu desetih, je 404;
        # povezava nanjo bi peljala na „Tega ni" (isto pravilo kot `_po_umiku`).
        odgovor = prepisi(odjemalec, "XYZ")

        assert odgovor.status_code == 200
        assert "Izberi vsaj eno sliko" in odgovor.text
        assert 'class="nazaj" href="/admin"' in odgovor.text

    def test_prazen_predmet_s_seznama_pelje_nazaj_nanj(self, odjemalec: TestClient) -> None:
        # Znan predmet ostane dosegljiv tudi prazen.
        odgovor = prepisi(odjemalec, "MAT")

        assert 'class="nazaj" href="/admin/subjects/MAT"' in odgovor.text


class TestNaborPredmetaOmejujeIzbor:
    """Šteje samo identifikator iz nabora strani predmeta (`ADR-048` F).

    Vsak tak identifikator se **tiho izpusti**: iz izrisanega obrazca ne more
    nastati, zato ni napaka uporabnice, ki bi jo bilo treba razložiti, in
    odgovor z njim ne sme izdati, da tuja snov obstaja.
    """

    def test_arhivirana_snov_se_izpusti(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA)
        zapisi(motor, slike, UUID_DVA)
        obdelaj(motor, UUID_ENA)
        obdelaj(motor, UUID_DVA)
        arhiviraj(motor, UUID_ENA)

        odgovor = prepisi(odjemalec, "MAT", UUID_ENA, UUID_DVA)

        assert "1 slika" in odgovor.text

    def test_snov_drugega_predmeta_se_izpusti(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA, subject="MAT")
        zapisi(motor, slike, UUID_DVA, subject="SLO")
        obdelaj(motor, UUID_ENA)
        obdelaj(motor, UUID_DVA)

        odgovor = prepisi(odjemalec, "MAT", UUID_ENA, UUID_DVA)

        assert "1 slika" in odgovor.text
        assert "SLO" not in polje_prepisov(odgovor.text)

    def test_neobstojec_identifikator_se_izpusti(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        obdelaj(motor)

        odgovor = prepisi(
            odjemalec, "MAT", UUID_ENA, "00000000-0000-4000-8000-000000000000"
        )

        assert "1 slika" in odgovor.text

    def test_sam_tuj_identifikator_da_prazno_stran(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        odgovor = prepisi(odjemalec, "MAT", "00000000-0000-4000-8000-000000000000")

        assert "Izberi vsaj eno sliko" in odgovor.text


class TestPrepisiNicesarNeZapisejo:
    """`ADR-048` F: sestavljanje je čista funkcija, nič se ne shrani."""

    def test_baza_se_ne_spremeni(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        obdelaj(motor)
        with Session(motor) as seja:
            prej = seja.get(Material, UUID_ENA)
            assert prej is not None
            stanje = (prej.status, prej.transcript, prej.subject, prej.archived_at)

        prepisi(odjemalec, "MAT", UUID_ENA)
        prepisi(odjemalec, "MAT", UUID_ENA)

        assert stevilo_vrstic(motor) == 1
        with Session(motor) as seja:
            potem = seja.get(Material, UUID_ENA)
            assert potem is not None
            assert (
                potem.status,
                potem.transcript,
                potem.subject,
                potem.archived_at,
            ) == stanje

    def test_get_pelje_na_pregled_in_ne_na_405(self, odjemalec: TestClient) -> None:
        # Stran ni zaznamek in je ni mogoče osvežiti; kdor to poskusi, naj
        # pristane na pregledu in ne na strani z napako.
        odgovor = odjemalec.get("/admin/transcripts", follow_redirects=False)

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == "/admin"


class TestSkriptaPrepisov:
    """Meje skripte na strani s prepisi (`ADR-024` 1-4, `ADR-048` C 1-3).

    Pytest skripte **ne izvede**; dokazljivo je samo, kaj je v izrisu. Kako se
    gumb res obnaša, dokaže ročni preizkus v fazi 9b — enako kot pri povečanem
    prikazu (`ADR-024`, „Posledice").

    **Trditve so vezane na obliko skripte, ne na njeno vedenje**: na imeni
    `neuspeh` in `napaka` ter na zapis `.then(fn, fn)`. Drugače ne gre, dokler
    skripte ne izvedemo. Kdor skripto preoblikuje, naj popravi te trditve
    skupaj z njo — niso pokvarjene, le berejo izvorno obliko. Odkril pregled
    v fazi 7.
    """

    def stran(self, odjemalec: TestClient, motor: Engine, slike: Path) -> str:
        zapisi(motor, slike)
        obdelaj(motor)
        return prepisi(odjemalec, "MAT", UUID_ENA).text

    def test_skripta_je_vgrajena_in_brez_zunanje_knjiznice(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        besedilo = self.stran(odjemalec, motor, slike)

        assert "<script>" in besedilo
        # Nobenega `src`: niti CDN niti datoteke iz repozitorija (meji 1 in 2).
        assert "<script src" not in besedilo

    def test_skripta_ne_klice_streznika_in_ne_poslja_obrazca(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        telo = skripta(self.stran(odjemalec, motor, slike)).lower()

        for prepovedano in ("fetch(", "xmlhttprequest", "sendbeacon", ".submit(", "<form"):
            assert prepovedano not in telo

    def test_ta_stran_obrazca_sploh_nima(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Stran je izpis in ne dejanje; edini obrazec je odjava v glavi.
        besedilo = self.stran(odjemalec, motor, slike)

        assert besedilo.count("<form") == 1
        assert 'action="/admin/logout"' in besedilo

    def test_na_strani_ni_nobenega_atributa_on(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Vsak `on…=` in ne le štirje iz `TestBrezJavaScripta.VZORCI`:
        # izvzetje od tistega testa ne sme odpreti `onkeydown=` ali `onfocus=`.
        besedilo = self.stran(odjemalec, motor, slike).lower()

        assert re.search(r"\son[a-z]+\s*=", besedilo) is None

    def test_skripta_bere_isto_polje_kot_ga_izrise_stran(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Meja 1 iz `ADR-048` C: kar je v odložišču, je natanko to, kar je v
        # polju. Skripta bere `value` in ne sestavlja svojega besedila.
        besedilo = self.stran(odjemalec, motor, slike)
        telo = skripta(besedilo)

        assert 'id="besedilo"' in besedilo
        assert 'document.getElementById("besedilo")' in telo
        assert "navigator.clipboard.writeText(polje.value)" in telo

    def test_ob_neuspehu_oznaci_in_pove_za_ctrl_c(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Meja 3: tiho neuspešen gumb je huje kot gumba nič.
        telo = skripta(self.stran(odjemalec, motor, slike))

        assert "polje.select()" in telo
        assert "Ctrl+C" in telo
        # Trditev o **klicu** in ne le o definiciji: `polje.select()` stoji v
        # `oznaci()`, in če bi zavrnitvena veja tega ne klicala, bi bil test
        # zelen ob gumbu, ki ob neuspehu ne označi ničesar. Odkril pregled.
        assert "}, neuspeh);" in telo
        assert re.search(r"catch \(napaka\) \{\s*neuspeh\(\);", telo) is not None

    def test_gumb_je_skrit_dokler_ga_skripta_ne_odkrije(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Brez skripte gumba ni — izrisan in mrtev bi bil ravno tisto, kar
        # meja 3 prepoveduje. Namesto njega je navodilo za Ctrl+A in Ctrl+C.
        besedilo = self.stran(odjemalec, motor, slike)

        assert 'id="kopiraj" class="gumb gumb-obdelava" type="button" hidden' in besedilo
        assert "gumb.hidden = false;" in skripta(besedilo)
        assert "Ctrl+A" in besedilo

    def test_stran_brez_izbora_skripte_nima(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Polja ni, zato tudi brati ni česa; skripta bi tam padla na `null`.
        odgovor = prepisi(odjemalec, "MAT")

        assert "<script" not in odgovor.text


class TestVelikIzborNePade:
    """„Izberi vse" na velikem predmetu ne sme odpovedati (odkril pregled v fazi 7).

    Starlettejev `FormParser` ima privzeto `max_fields=1000` — meja ni v
    `parse`, ampak v povratnem klicu `on_field_end` — in ta izbor je eno polje
    na sliko. Brez popravka je `POST` s tisoč in eno sliko vrnil `400` z
    besedilom „Too many fields. Maximum number of fields is 1000." kot edino
    vsebino strani. To je odpoved pri največjem izboru, zaradi katere je
    `ADR-048` B izbral `POST` namesto `GET`, in hkrati kršitev merila
    dokončanosti (`CLAUDE.md` §1b: brez surovega besedila sistemske napake).

    Odslej velja ena sama meja — velikost telesa (`NAJVECJE_TELO_OBRAZCA`),
    ki ima slovensko sporočilo in jo postavi `SejaMiddleware`.
    """

    #: Čez Starlettejev privzetek, a še krepko pod 1 MiB telesa.
    KOLIKO = 1200

    def test_izbor_cez_tisoc_polj_uspe(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        obdelaj(motor)
        # Ena resnična slika, ostalo izmišljeni identifikatorji: dokazuje se
        # število polj, ne nabor. Tuji se tiho izpustijo kot vedno.
        izbor = [UUID_ENA] + [f"{i:08d}-0000-4000-8000-000000000000" for i in range(self.KOLIKO)]

        odgovor = prepisi(odjemalec, "MAT", *izbor)

        assert odgovor.status_code == 200
        assert "Too many fields" not in odgovor.text
        assert "1 slika" in odgovor.text
        assert "Delci snovi se gibljejo." in polje_prepisov(odgovor.text)

    def test_prevelik_obrazec_pove_slovensko(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Meja, ki ostane, je ena sama in govori slovensko. Prag je 1 MiB
        # telesa; polje je tu eno samo in dovolj veliko, da ga preseže.
        #
        # Ta trditev je o `SejaMiddleware` in ne o tej poti — 413 pade, preden
        # zahteva sem sploh pride. Stoji tu zato, ker je to **edina** meja, ki
        # temu obrazcu ostane, in ker mora biti ob testu zgoraj vidno, da ni
        # ostala brez sporočila. Odkril pregled v fazi 7.
        zapisi(motor, slike)

        odgovor = odjemalec.post(
            "/admin/transcripts",
            data={"subject": "MAT", "snov": "x" * (1024 * 1024 + 1)},
        )

        assert odgovor.status_code == 413
        assert "Poslani obrazec je prevelik" in odgovor.text


class TestKodaPredmetaSPosebnimiZnaki:
    """Koda predmeta sme vsebovati karkoli (odkril pregled v fazi 7).

    `POST /materials` jo omejuje samo po dolžini, `oznaka_predmeta` pa neznano
    kodo izrecno dopušča — zapis s `/` ali `?` v `subject` torej lahko nastane.
    Zato gre koda v povezave skozi `quote` in se na poševnico ne konča. Obe
    vrstici sta imeli komentar z utemeljitvijo, nista pa imeli testa.
    """

    KODA = "MAT/2?a"

    def test_povezavi_za_izbor_sta_ubezani(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, subject=self.KODA)

        besedilo = odjemalec.get(f"/admin/subjects/{quote(self.KODA, safe='')}").text

        # Brez `quote` bi `?` povezavo prerezal na poizvedbo in „Izberi vse"
        # bi peljal na drug predmet.
        assert 'href="/admin/subjects/MAT%2F2%3Fa?vse=1"' in besedilo
        assert 'href="/admin/subjects/MAT%2F2%3Fa"' in besedilo

    def test_izbor_v_takem_predmetu_dela(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, subject=self.KODA)
        obdelaj(motor)

        odgovor = prepisi(odjemalec, self.KODA, UUID_ENA)

        assert odgovor.status_code == 200
        assert "Delci snovi se gibljejo." in polje_prepisov(odgovor.text)

    def test_koncna_posevnica_zadene_isti_nabor(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Pretvornik `:path` požre končno poševnico, zato jo odreže tudi ta
        # pot — sicer bi obrazec s strani `MAT/` pokazal prazen izbor.
        zapisi(motor, slike, subject="MAT")
        obdelaj(motor)

        odgovor = prepisi(odjemalec, "MAT/", UUID_ENA)

        assert "1 slika" in odgovor.text


class TestPrepisNeRazbijeStrani:
    """Prepis je besedilo z zunanjega modela in gre v HTML kot podatek.

    Prepis, ki bi vseboval `</textarea>`, bi brez ubežanja polje zaprl sredi
    besedila in ostanek zlil v stran. Odkril pregled v fazi 7.
    """

    NAGAJIV = "Zapis: a < b & c > d </textarea><script>alert(1)</script>"

    def prepis(self, motor: Engine, besedilo: str) -> None:
        with Session(motor) as seja:
            material = seja.get(Material, UUID_ENA)
            assert material is not None
            material.status = STATUS_PRIPRAVLJEN
            material.readable = True
            material.transcript = besedilo
            seja.commit()

    def test_znaki_html_ostanejo_v_polju_in_ne_v_strani(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)
        self.prepis(motor, self.NAGAJIV)

        odgovor = prepisi(odjemalec, "MAT", UUID_ENA)

        # Vsebina polja je natanko prepis — to je obljuba `ADR-048` C1.
        assert polje_prepisov(odgovor.text).endswith(self.NAGAJIV + "\n")
        # Polje se konča tam, kjer ga konča predloga, in ne sredi prepisa.
        assert odgovor.text.count("</textarea>") == 1
        # Zunaj izvzete skripte te strani ni nobene druge (`ADR-024`).
        assert odgovor.text.count("<script") == 1

    def test_stevec_znakov_steje_neubezano_besedilo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Uporabnica prilepi neubežano besedilo, zato mora tudi števec govoriti
        # o njem. Ubežani zapis je daljši in bi lagal.
        zapisi(motor, slike)
        self.prepis(motor, self.NAGAJIV)

        odgovor = prepisi(odjemalec, "MAT", UUID_ENA)

        assert f"{len(polje_prepisov(odgovor.text))} znakov" in odgovor.text
