"""Testi za arhiv in za brisanje na telefonu (V1-R07).

Pokrivajo tisto, kar `tests/test_admin.py` ne more: pot, ki jo uporablja
telefon, in pravila repozitorija, na katerih ta pot stoji. Vse gre skozi
`TestClient` in SQLite v pomnilniku — Docker ni pogoj za zeleno zbirko.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models import STATUS_NOV, Material
from tests.conftest import KLJUC

UUID_ENA = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
UUID_DVA = "a1b2c3d4-e5f6-4789-abcd-ef0123456789"
UUID_TRI = "b7c8d9e0-f1a2-4b3c-8d4e-5f60718293a4"


def zapisi(
    motor: Engine,
    slike: Path,
    material_id: str = UUID_ENA,
    *,
    subject: str = "MAT",
    arhivirano: datetime | None = None,
    potrjeno: datetime | None = None,
) -> Path:
    """Ustvari zapis z datoteko in mu po potrebi postavi stanje arhiva."""
    pot = slike / f"{material_id}.jpg"
    pot.write_bytes(b"slika")

    with Session(motor) as seja:
        seja.add(
            Material(
                id=material_id,
                subject=subject,
                taken_at=datetime(2026, 9, 4, 7, 30, tzinfo=UTC),
                image_path=str(pot),
                status=STATUS_NOV,
                received_at=datetime(2026, 9, 4, 8, 0, tzinfo=UTC),
                archived_at=arhivirano,
                device_deleted_at=potrjeno,
            )
        )
        seja.commit()

    return pot


def potrjeno_ob(motor: Engine, material_id: str = UUID_ENA) -> datetime | None:
    """Kdaj je telefon potrdil brisanje tega zapisa, v UTC.

    Normalizacija ni okras: Postgres v `TIMESTAMPTZ` pas vrne, SQLite pa ne.
    Brez nje bi primerjava z zapisanim časom padla samo v testih.
    """
    with Session(motor) as seja:
        material = seja.get(Material, material_id)
        assert material is not None
        if material.device_deleted_at is None:
            return None
        return material.device_deleted_at.replace(
            tzinfo=material.device_deleted_at.tzinfo or UTC
        ).astimezone(UTC)


def stevilo_vrstic(motor: Engine) -> int:
    """Koliko zapisov je v tabeli."""
    with Session(motor) as seja:
        return seja.scalar(select(func.count()).select_from(Material)) or 0


def polja(material_id: str = UUID_ENA) -> dict[str, str]:
    """Metapodatki, kot jih pošlje telefon."""
    return {"id": material_id, "subject": "MAT", "taken_at": "2026-09-04T07:30:00Z"}


def datoteka(vsebina: bytes = b"nova-vsebina") -> dict[str, Any]:
    """Del zahtevka z datoteko."""
    return {"file": ("posnetek.jpg", vsebina, "image/jpeg")}


ARHIVIRANO = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
POTRJENO = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


class TestSeznamZaBrisanje:
    """`GET /materials/pending-deletion`."""

    def test_vrne_arhivirane_ki_se_niso_potrjeni(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA, arhivirano=ARHIVIRANO)
        zapisi(motor, slike, UUID_DVA)
        zapisi(motor, slike, UUID_TRI, arhivirano=ARHIVIRANO, potrjeno=POTRJENO)

        odgovor = odjemalec.get("/materials/pending-deletion", headers={"X-API-Key": KLJUC})

        assert odgovor.status_code == 200
        assert odgovor.json() == {"ids": [UUID_ENA]}

    def test_prazen_seznam_ni_napaka(self, odjemalec: TestClient) -> None:
        # Običajno stanje: nič ni arhiviranega. Telefon mora dobiti prazen
        # seznam in ne 404.
        odgovor = odjemalec.get("/materials/pending-deletion", headers={"X-API-Key": KLJUC})

        assert odgovor.status_code == 200
        assert odgovor.json() == {"ids": []}

    def test_brez_kljuca_je_401(self, odjemalec: TestClient) -> None:
        # Nova pot ne sme priti mimo vmesne plasti s ključem. Izvzetje velja
        # samo za `/admin` in `GET /health`.
        assert odjemalec.get("/materials/pending-deletion").status_code == 401

    def test_najstarejse_arhivirani_prvi(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA, arhivirano=datetime(2026, 9, 6, tzinfo=UTC))
        zapisi(motor, slike, UUID_DVA, arhivirano=datetime(2026, 9, 5, tzinfo=UTC))

        odgovor = odjemalec.get("/materials/pending-deletion", headers={"X-API-Key": KLJUC})

        assert odgovor.json()["ids"] == [UUID_DVA, UUID_ENA]


class TestPotrditevBrisanja:
    """`POST /materials/deleted-on-device`."""

    def test_zapise_potrditev_in_skrci_seznam(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA, arhivirano=ARHIVIRANO)

        odgovor = odjemalec.post(
            "/materials/deleted-on-device",
            json={"ids": [UUID_ENA]},
            headers={"X-API-Key": KLJUC},
        )

        assert odgovor.status_code == 200
        assert odgovor.json() == {"confirmed": 1}
        assert potrjeno_ob(motor) is not None

        seznam = odjemalec.get(
            "/materials/pending-deletion", headers={"X-API-Key": KLJUC}
        ).json()
        assert seznam == {"ids": []}

    def test_ponovljena_potrditev_ne_premakne_casa(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Prenos s telefona je *at-least-once*: ista potrditev bo prišla
        # večkrat in to ni napaka.
        zapisi(motor, slike, UUID_ENA, arhivirano=ARHIVIRANO, potrjeno=POTRJENO)

        odgovor = odjemalec.post(
            "/materials/deleted-on-device",
            json={"ids": [UUID_ENA]},
            headers={"X-API-Key": KLJUC},
        )

        assert odgovor.status_code == 200
        assert odgovor.json() == {"confirmed": 0}
        assert potrjeno_ob(motor) == POTRJENO

    def test_neznan_id_ni_napaka(self, odjemalec: TestClient) -> None:
        # Zapis je bil medtem že dokončno izbrisan. Izid je tak, kot ga je
        # telefon hotel, zato 404 tu ne bi bil resničen.
        odgovor = odjemalec.post(
            "/materials/deleted-on-device",
            json={"ids": [UUID_ENA]},
            headers={"X-API-Key": KLJUC},
        )

        assert odgovor.status_code == 200
        assert odgovor.json() == {"confirmed": 0}

    def test_aktiven_zapis_se_ne_potrdi(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Potrditev za nearhiviran zapis bi odprla pot dokončnemu brisanju
        # slike, ki je telefon ni nikoli dobil navodila zbrisati.
        zapisi(motor, slike, UUID_ENA)

        odgovor = odjemalec.post(
            "/materials/deleted-on-device",
            json={"ids": [UUID_ENA]},
            headers={"X-API-Key": KLJUC},
        )

        assert odgovor.json() == {"confirmed": 0}
        assert potrjeno_ob(motor) is None

    def test_paket_potrdi_vec_naenkrat(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        zapisi(motor, slike, UUID_ENA, arhivirano=ARHIVIRANO)
        zapisi(motor, slike, UUID_DVA, arhivirano=ARHIVIRANO)

        odgovor = odjemalec.post(
            "/materials/deleted-on-device",
            json={"ids": [UUID_ENA, UUID_DVA]},
            headers={"X-API-Key": KLJUC},
        )

        assert odgovor.json() == {"confirmed": 2}

    def test_prazen_paket_ni_napaka(self, odjemalec: TestClient) -> None:
        odgovor = odjemalec.post(
            "/materials/deleted-on-device", json={"ids": []}, headers={"X-API-Key": KLJUC}
        )

        assert odgovor.status_code == 200
        assert odgovor.json() == {"confirmed": 0}

    def test_brez_kljuca_je_401(self, odjemalec: TestClient) -> None:
        assert (
            odjemalec.post("/materials/deleted-on-device", json={"ids": []}).status_code
            == 401
        )


class TestPrenosArhiviranega:
    """`POST /materials` za zapis, ki je medtem šel v arhiv."""

    def test_vrne_410_in_nicesar_ne_spremeni(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Brez tega bi posnetek, ki je na telefonu obtičal v `pending`, tam
        # ostal za vedno: z delovnega seznama je lahko že padel, ker je bilo
        # brisanje na napravi že potrjeno (`docs/odlocitve/ADR-010`).
        pot = zapisi(motor, slike, UUID_ENA, arhivirano=ARHIVIRANO, potrjeno=POTRJENO)

        odgovor = odjemalec.post(
            "/materials",
            data=polja(),
            files=datoteka(),
            headers={"X-API-Key": KLJUC},
        )

        assert odgovor.status_code == 410
        assert odgovor.json()["archived"] is True
        assert odgovor.json()["created"] is False
        assert stevilo_vrstic(motor) == 1
        # Vsebina se ne sme povoziti: na strežniku je slika, ki jo je operater
        # videl, ko se je odločil za arhiv.
        assert pot.read_bytes() == b"slika"

    def test_nearhiviran_zapis_se_vedno_vrne_200(
        self, odjemalec: TestClient, motor: Engine, slike: Path
    ) -> None:
        # Idempotentnost iz V1-R02 se ne sme spremeniti.
        zapisi(motor, slike, UUID_ENA)

        odgovor = odjemalec.post(
            "/materials",
            data=polja(),
            files=datoteka(),
            headers={"X-API-Key": KLJUC},
        )

        assert odgovor.status_code == 200
        assert odgovor.json()["archived"] is False
