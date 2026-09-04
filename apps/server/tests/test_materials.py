"""Testi za `POST /materials`.

Pokrivajo tabelo „Strežnik" iz `docs/plan/V1-R02.md`.
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models import Material
from app.storage import ZACASNA_PODMAPA
from tests.conftest import KLJUC

UUID_ENA = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
UUID_DVA = "a1b2c3d4-e5f6-4789-abcd-ef0123456789"


def polja(material_id: str = UUID_ENA, subject: str = "MAT") -> dict[str, str]:
    """Metapodatki, kot jih pošlje telefon."""
    return {
        "id": material_id,
        "subject": subject,
        "taken_at": "2026-09-04T07:30:00Z",
    }


def datoteka(vsebina: bytes = b"slika-ena") -> dict[str, Any]:
    """Del zahtevka z datoteko."""
    return {"file": ("posnetek.jpg", vsebina, "image/jpeg")}


def stevilo_vrstic(motor: Engine) -> int:
    """Koliko zapisov je v tabeli."""
    with Session(motor) as seja:
        return seja.scalar(select(func.count()).select_from(Material)) or 0


def slike_na_disku(mapa: Path) -> list[Path]:
    """Končane slike; začasna podmapa ni med njimi."""
    return sorted(p for p in mapa.iterdir() if p.is_file())


class TestUspesenPrenos:
    """Srečna pot."""

    def test_vrne_201_in_zapise_vrstico_ter_datoteko(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        odgovor = odjemalec.post(
            "/materials",
            data=polja(),
            files=datoteka(),
            headers={"X-API-Key": KLJUC},
        )

        assert odgovor.status_code == 201
        assert odgovor.json() == {"id": UUID_ENA, "status": "new", "created": True}

        with Session(motor) as seja:
            zapis = seja.get(Material, UUID_ENA)
            assert zapis is not None
            assert zapis.subject == "MAT"
            assert zapis.status == "new"

        assert (slike / f"{UUID_ENA}.jpg").read_bytes() == b"slika-ena"

    def test_taken_at_se_shrani_kot_trenutek_v_utc(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        odjemalec.post(
            "/materials",
            data=polja() | {"taken_at": "2026-09-04T09:30:00+02:00"},
            files=datoteka(),
            headers={"X-API-Key": KLJUC},
        )

        with Session(motor) as seja:
            zapis = seja.get(Material, UUID_ENA)
            assert zapis is not None
            # 09:30 v pasu +02:00 je 07:30 UTC. SQLite pas zavrže, zato
            # primerjamo samo uro — bistveno je, da ni ostala 09:30.
            assert zapis.taken_at.hour == 7
            assert zapis.taken_at.minute == 30


class TestIdempotentnost:
    """Isti `id` dvakrat ne sme dati dveh zapisov."""

    def test_drugi_prenos_vrne_200_in_ne_podvoji(
        self, odjemalec: TestClient, motor: Engine
    ) -> None:
        prvi = odjemalec.post(
            "/materials", data=polja(), files=datoteka(b"prva"), headers={"X-API-Key": KLJUC}
        )
        drugi = odjemalec.post(
            "/materials", data=polja(), files=datoteka(b"druga"), headers={"X-API-Key": KLJUC}
        )

        assert prvi.status_code == 201
        assert prvi.json()["created"] is True
        assert drugi.status_code == 200
        assert drugi.json()["created"] is False
        assert stevilo_vrstic(motor) == 1

    def test_drugi_prenos_ne_povozi_prve_slike(
        self, odjemalec: TestClient, slike: Path
    ) -> None:
        odjemalec.post(
            "/materials", data=polja(), files=datoteka(b"prva"), headers={"X-API-Key": KLJUC}
        )
        odjemalec.post(
            "/materials", data=polja(), files=datoteka(b"druga"), headers={"X-API-Key": KLJUC}
        )

        assert (slike / f"{UUID_ENA}.jpg").read_bytes() == b"prva"

    def test_razlicna_id_dasta_dve_vrstici(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        odjemalec.post(
            "/materials", data=polja(UUID_ENA), files=datoteka(), headers={"X-API-Key": KLJUC}
        )
        odjemalec.post(
            "/materials", data=polja(UUID_DVA), files=datoteka(), headers={"X-API-Key": KLJUC}
        )

        assert stevilo_vrstic(motor) == 2
        assert len(slike_na_disku(slike)) == 2


class TestKljuc:
    """Brez veljavnega ključa ne sme nastati nič."""

    @pytest.mark.parametrize(
        ("opis", "glave"),
        [
            ("brez glave", {}),
            ("napacen kljuc", {"X-API-Key": "tuj-kljuc"}),
            ("prazen kljuc", {"X-API-Key": ""}),
        ],
    )
    def test_vrne_401_brez_vrstice_in_brez_datoteke(
        self,
        odjemalec: TestClient,
        motor: Engine,
        slike: Path,
        opis: str,
        glave: dict[str, str],
    ) -> None:
        odgovor = odjemalec.post("/materials", data=polja(), files=datoteka(), headers=glave)

        assert odgovor.status_code == 401, opis
        assert stevilo_vrstic(motor) == 0
        assert slike_na_disku(slike) == []

    def test_kljuc_z_ne_ascii_znaki_ne_sesuje_streznika(self, odjemalec: TestClient) -> None:
        # Starlette glave dekodira kot latin-1, zato je lahko ključ, ki pride
        # z omrežja, ne-ASCII niz. `compare_digest` nad takim nizom vrže
        # TypeError; brez primerjave bajtov bi bila to 500, ne 401.
        #
        # Glava je podana kot bajti, ker odjemalec ne-ASCII niza sploh ne bi
        # poslal — omejitev je na njegovi strani, ne na strežnikovi.
        odgovor = odjemalec.post(
            "/materials",
            data=polja(),
            files=datoteka(),
            headers={"X-API-Key": b"\xc4-tuj-kljuc"},
        )

        assert odgovor.status_code == 401

    def test_kljuc_se_preveri_pred_branjem_telesa(self, odjemalec: TestClient) -> None:
        # Zahtevek je brez obveznih polj: če bi se telo bralo prej, bi bil
        # odgovor 422. Ker je 401, je ključ res prva stvar na poti.
        odgovor = odjemalec.post("/materials", headers={"X-API-Key": "tuj-kljuc"})

        assert odgovor.status_code == 401


class TestNeveljavenZahtevek:
    """Manjkajoča ali pokvarjena polja."""

    def test_manjkajoc_subject_da_422(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        vhod = polja()
        del vhod["subject"]

        odgovor = odjemalec.post(
            "/materials", data=vhod, files=datoteka(), headers={"X-API-Key": KLJUC}
        )

        assert odgovor.status_code == 422
        assert stevilo_vrstic(motor) == 0
        assert slike_na_disku(slike) == []

    def test_manjkajoca_datoteka_da_422(self, odjemalec: TestClient, motor: Engine) -> None:
        odgovor = odjemalec.post("/materials", data=polja(), headers={"X-API-Key": KLJUC})

        assert odgovor.status_code == 422
        assert stevilo_vrstic(motor) == 0

    def test_neveljaven_taken_at_da_422(self, odjemalec: TestClient, motor: Engine) -> None:
        odgovor = odjemalec.post(
            "/materials",
            data=polja() | {"taken_at": "jutri popoldne"},
            files=datoteka(),
            headers={"X-API-Key": KLJUC},
        )

        assert odgovor.status_code == 422
        assert stevilo_vrstic(motor) == 0

    @pytest.mark.parametrize("nakazen_id", ["../pobegni", "ni-uuid", "", "a" * 40])
    def test_id_ki_ni_uuid_da_422_in_ne_zapise_nicesar(
        self, odjemalec: TestClient, motor: Engine, slike: Path, nakazen_id: str
    ) -> None:
        # Iz `id` nastane ime datoteke. Nepreverjen niz bi dovolil pisanje
        # izven mape s slikami, zato je oblika UUID pogoj, ne okras.
        odgovor = odjemalec.post(
            "/materials",
            data=polja(nakazen_id),
            files=datoteka(),
            headers={"X-API-Key": KLJUC},
        )

        assert odgovor.status_code == 422
        assert stevilo_vrstic(motor) == 0
        assert slike_na_disku(slike) == []


class TestNapakaPriZapisu:
    """Datoteke ni bilo mogoče zapisati."""

    def test_ne_ostane_vrstica_v_bazi(
        self,
        odjemalec: TestClient,
        motor: Engine,
        slike: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def pade(*_args: object, **_kwargs: object) -> Path:
            raise OSError("na disku ni prostora")

        monkeypatch.setattr("app.routers.materials.shrani_sliko", pade)

        with pytest.raises(OSError, match="na disku ni prostora"):
            odjemalec.post(
                "/materials", data=polja(), files=datoteka(), headers={"X-API-Key": KLJUC}
            )

        assert stevilo_vrstic(motor) == 0
        assert slike_na_disku(slike) == []

    def test_ob_padcu_vstavljanja_slika_ne_ostane(
        self,
        odjemalec: TestClient,
        motor: Engine,
        slike: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def pade(*_args: object, **_kwargs: object) -> bool:
            raise RuntimeError("baza je odpovedala")

        monkeypatch.setattr(
            "app.db.MaterialsRepository.vstavi_ce_ga_ni", pade, raising=True
        )

        with pytest.raises(RuntimeError, match="baza je odpovedala"):
            odjemalec.post(
                "/materials", data=polja(), files=datoteka(), headers={"X-API-Key": KLJUC}
            )

        # Slika brez vrstice je sirota, ki je nihče nikoli ne pogleda.
        assert stevilo_vrstic(motor) == 0
        assert slike_na_disku(slike) == []


class TestAtomarnost:
    """Na končni poti nikoli ni polovične datoteke."""

    def test_po_uspehu_v_zacasni_podmapi_ni_ostankov(
        self, odjemalec: TestClient, slike: Path
    ) -> None:
        odjemalec.post(
            "/materials", data=polja(), files=datoteka(), headers={"X-API-Key": KLJUC}
        )

        zacasna = slike / ZACASNA_PODMAPA
        assert list(zacasna.iterdir()) == []


class TestZivost:
    """`GET /health` mora delovati brez ključa."""

    def test_vrne_200_brez_kljuca(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.get("/health")

        assert odgovor.status_code == 200
        assert odgovor.json() == {"status": "ok"}
