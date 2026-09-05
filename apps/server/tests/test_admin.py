"""Testi operaterske strani pod `/admin`.

Pokrivajo tabelo „Test casi" iz `docs/plan/V1-R04.md`.

Zapisi nastanejo neposredno v bazi in ne prek `POST /materials`: ta stran bere
stanje, ne poti, po kateri je stanje nastalo. Vsak test, ki gre skozi prenos,
bi ob spremembi prenosa padel iz razloga, ki s to zahtevo nima zveze.
"""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models import (
    STATUS_NAPAKA,
    STATUS_NOV,
    STATUS_PRIPRAVLJEN,
    STATUS_V_OBDELAVI,
    Material,
    Question,
)
from tests.conftest import KLJUC

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
    pot = slike / f"{material_id}.jpg"
    if vsebina is not None:
        pot.write_bytes(vsebina)

    with Session(motor) as seja:
        seja.add(
            Material(
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
        material.questions = [
            Question(
                id=f"{material_id}-v{i}",
                position=i,
                question=f"Vprašanje {i}?",
                answer=f"Odgovor {i}.",
            )
            for i in range(1, koliko_vprasanj + 1)
        ]
        seja.commit()


def stevilo_vprasanj(motor: Engine) -> int:
    """Koliko vrstic je v tabeli `questions`."""
    with Session(motor) as seja:
        return seja.scalar(select(func.count()).select_from(Question)) or 0


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

    def test_ima_gumb_za_brisanje(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Kriterij pravi „gumb na strani s podrobnostmi odpre potrditveno
        # stran". Vsi testi brisanja hodijo naravnost na URL, zato bi brez te
        # trditve gumb lahko izginil in brisanje bi ostalo dosegljivo samo z
        # ročno vtipkanim naslovom.
        zapisi(motor, slike)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}").text

        assert f'href="/admin/materials/{UUID_ENA}/delete"' in besedilo

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


class TestBrisanje:
    """`GET` in `POST /admin/materials/{id}/delete`."""

    def test_potrditvena_stran_nicesar_ne_izbrise(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        pot = zapisi(motor, slike)

        odgovor = odjemalec.get(f"/admin/materials/{UUID_ENA}/delete")

        assert odgovor.status_code == 200
        assert stevilo_vrstic(motor) == 1
        assert pot.exists()

    def test_potrditvena_stran_pokaze_kaj_bo_izbrisano(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Kriterij zahteva potrditveno stran „s sliko, predmetom in datumom".
        # Brez teh treh trditev bi test ostal zelen, tudi če bi predloga
        # vprašala „izbrisati?" in ne povedala, kaj.
        zapisi(motor, slike)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}/delete").text

        assert f'src="/admin/materials/{UUID_ENA}/image"' in besedilo
        assert "MAT" in besedilo
        assert "4. 9. 2026 ob 09:30" in besedilo

    def test_potrditvena_stran_brise_z_obrazcem_in_ne_s_povezavo(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike)

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}/delete").text

        assert 'method="post"' in besedilo
        assert f'href="/admin/materials/{UUID_ENA}/delete"' not in besedilo

    def test_post_izbrise_vrstico_in_datoteko_ter_preusmeri(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        pot = zapisi(motor, slike)

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False
        )

        # 303 in ne 302: osvežitev strani po brisanju ne sme brisati znova.
        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == "/admin/subjects/MAT"
        assert stevilo_vrstic(motor) == 0
        assert not pot.exists()

    def test_preusmeritev_po_brisanju_je_ubezana(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # `?` bi glavo `Location` prerezal na poizvedbo in operater bi pristal
        # na predmetu „A", ne na „A?B". Zapisa sta dva, da predmet po brisanju
        # še obstaja — sicer preusmeritev po pravilu pelje na pregled.
        zapisi(motor, slike, UUID_ENA, subject="A?B")
        zapisi(motor, slike, UUID_DVA, subject="A?B")

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False
        )

        assert odgovor.headers["location"] == "/admin/subjects/A%3FB"

    def test_brisanje_zadnje_slike_neznanega_predmeta_pelje_na_pregled(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Predmet, ki ni med desetimi, obstaja samo, dokler ima sliko. Brez
        # tega bi preusmeritev pristala na strani „Tega ni".
        zapisi(motor, slike, subject="XXX")

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False
        )

        # 303 in ne 302: sicer brskalnik ob osvežitvi ponovi POST.
        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == "/admin"
        assert odjemalec.get(odgovor.headers["location"]).status_code == 200

    def test_brisanje_zadnje_slike_znanega_predmeta_pelje_na_predmet(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Znan predmet ostane dosegljiv tudi prazen — tam je sporočilo, da
        # slik ni, in to je pravi konec brisanja.
        zapisi(motor, slike, subject="MAT")

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False
        )

        # 303 in ne 302: sicer brskalnik ob osvežitvi ponovi POST.
        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == "/admin/subjects/MAT"
        assert odjemalec.get(odgovor.headers["location"]).status_code == 200

    def test_brisanje_ne_pobrise_sosedov(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        pot_ena = zapisi(motor, slike, UUID_ENA)
        pot_dva = zapisi(motor, slike, UUID_DVA)

        odjemalec.post(f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False)

        assert not pot_ena.exists()
        assert pot_dva.exists()
        assert stevilo_vrstic(motor) == 1

    def test_potrditvena_stran_neobstojecega_da_404(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get(f"/admin/materials/{UUID_ENA}/delete")

        assert odgovor.status_code == 404
        assert "text/html" in odgovor.headers["content-type"]

    def test_brisanje_ze_izbrisanega_preusmeri_na_pregled(
        self, odjemalec: TestClient
    ) -> None:
        # Zahteva: „brez sesutja, preusmeritev na seznam". To se zgodi, ko je
        # operater isto sliko izbrisal v drugem zavihku — rezultat je tak, kot
        # ga je hotel, zato stran o napaki ni pravi odgovor.
        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False
        )

        assert odgovor.status_code == 303
        assert odgovor.headers["location"] == "/admin"

    def test_brisanje_zapisa_brez_datoteke_uspe(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, vsebina=None)

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False
        )

        assert odgovor.status_code == 303
        assert stevilo_vrstic(motor) == 0


class TestKljucOstajaZahtevanDrugod:
    """Regresija: izvzetje `/admin` ne sme odpreti ničesar drugega.

    Ta razred je razlog, da izvzetje predpone sploh sme obstajati. Če pade,
    je strežnik odprt — ne glede na to, ali admin stran deluje.
    """

    def test_admin_je_dosegljiv_brez_kljuca(self, odjemalec: TestClient) -> None:
        assert odjemalec.get("/admin").status_code == 200

    def test_materials_brez_kljuca_ostaja_401(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        odgovor = odjemalec.post(
            "/materials",
            data={"id": UUID_ENA, "subject": "MAT", "taken_at": "2026-09-04T07:30:00Z"},
            files={"file": ("posnetek.jpg", b"slika", "image/jpeg")},
        )

        assert odgovor.status_code == 401
        assert stevilo_vrstic(motor) == 0

    def test_materials_z_napacnim_kljucem_ostaja_401(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        odgovor = odjemalec.post(
            "/materials",
            headers={"X-API-Key": "napacen-kljuc-a-dovolj-dolg"},
            data={"id": UUID_ENA, "subject": "MAT", "taken_at": "2026-09-04T07:30:00Z"},
            files={"file": ("posnetek.jpg", b"slika", "image/jpeg")},
        )

        assert odgovor.status_code == 401
        assert stevilo_vrstic(motor) == 0

    def test_materials_s_pravim_kljucem_se_vedno_dela(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        # Brez tega bi prejšnja dva testa ostala zelena tudi, če bi bila pot
        # pokvarjena in bi vračala 401 vsem.
        odgovor = odjemalec.post(
            "/materials",
            headers={"X-API-Key": KLJUC},
            data={"id": UUID_ENA, "subject": "MAT", "taken_at": "2026-09-04T07:30:00Z"},
            files={"file": ("posnetek.jpg", b"slika", "image/jpeg")},
        )

        assert odgovor.status_code == 201
        assert stevilo_vrstic(motor) == 1

    def test_pot_ki_se_le_zacne_kot_admin_ni_izvzeta(self, odjemalec: TestClient) -> None:
        # Golo `startswith("/admin")` bi to pot spustilo skozi preverbo ključa.
        for pot in ("/administration", "/admin-nekaj", "/adminmaterials"):
            assert odjemalec.get(pot).status_code == 401, pot

    def test_health_ostaja_dosegljiv_brez_kljuca(self, odjemalec: TestClient) -> None:
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

        besedilo = odjemalec.get(f"/admin/materials/{UUID_ENA}/delete").text

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
        assert odjemalec.get(f"/admin/materials/{UUID_ENA}/delete").status_code == 200

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

    def test_napake_izven_admin_ostanejo_json(self, odjemalec: TestClient) -> None:
        # Prestreznik je globalen; za telefon se mora umakniti privzetemu.
        odgovor = odjemalec.get("/materials", headers={"X-API-Key": KLJUC})

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
            "brisanje.html",
            "najdena-ni.html",
        }


class TestBrezJavaScripta:
    """Stran ne sme uporabljati JavaScripta.

    Kriterij iz `docs/verzije/v1.md` in odločitev 1 v planu: vsa dinamika so
    obrazci. Brez tega testa bi bila zahteva izpolnjena samo, dokler se je
    nekdo spomni — dodan `<script>` ne bi podrl ničesar.
    """

    #: Vzorci, ki pomenijo, da se na strani izvaja koda.
    VZORCI = ("<script", "javascript:", "onclick=", "onload=", "onerror=", "onsubmit=")

    def test_v_predlogah_ni_javascripta(self) -> None:
        from app.routers.admin import MAPA_PREDLOG

        najdeno = [
            f"{pot.name}: {vzorec}"
            for pot in sorted(MAPA_PREDLOG.glob("*.html"))
            for vzorec in self.VZORCI
            if vzorec in pot.read_text(encoding="utf-8").lower()
        ]

        assert najdeno == []

    def test_v_izrisani_strani_ni_javascripta(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Predloge so eno, izris drugo: skript bi lahko prišel tudi iz vsebine.
        zapisi(motor, slike)

        for pot in (
            "/admin",
            "/admin/subjects/MAT",
            f"/admin/materials/{UUID_ENA}",
            f"/admin/materials/{UUID_ENA}/delete",
        ):
            besedilo = odjemalec.get(pot).text.lower()
            for vzorec in self.VZORCI:
                assert vzorec not in besedilo, f"{pot} vsebuje {vzorec}"


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

    def test_zavrze_prejsnji_rezultat_in_vprasanja(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """ADR-009: material ima največ en niz vprašanj."""
        zapisi(motor, slike)
        obdelaj(motor)
        assert stevilo_vprasanj(motor) == 5

        odjemalec.post(f"/admin/materials/{UUID_ENA}/reprocess")

        assert stevilo_vprasanj(motor) == 0
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


class TestBrisanjeZVprasanji:
    """Regresija V1-R04: brisanje mora pobrisati tudi vprašanja.

    Brez kaskade bi bila to na Postgresu kršitev tujega ključa, na SQLite pa
    bi tiho pustila osirotela vprašanja — zbirka bi bila zelena, produkcija
    ne (odločitev 6 v `docs/plan/V1-R03.md`).
    """

    def test_brisanje_pobrise_tudi_vprasanja(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        pot = zapisi(motor, slike)
        obdelaj(motor)
        assert stevilo_vprasanj(motor) == 5

        odgovor = odjemalec.post(
            f"/admin/materials/{UUID_ENA}/delete", follow_redirects=False
        )

        assert odgovor.status_code == 303
        assert stevilo_vrstic(motor) == 0
        assert stevilo_vprasanj(motor) == 0
        assert not pot.exists()

    def test_brisanje_ne_pobrise_vprasanj_drugega_materiala(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        """Kaskada mora seči natanko do otrok tega zapisa in nič dlje."""
        zapisi(motor, slike, UUID_ENA)
        zapisi(motor, slike, UUID_DVA)
        obdelaj(motor, UUID_ENA, koliko_vprasanj=5)
        obdelaj(motor, UUID_DVA, koliko_vprasanj=4)

        odjemalec.post(f"/admin/materials/{UUID_ENA}/delete")

        assert stevilo_vprasanj(motor) == 4
