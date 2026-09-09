"""Alembic migracija mora dati isto shemo kot modeli.

Zakaj to sploh potrebuje test: migracija je na kritični poti zagona — servis
`api` požene `alembic upgrade head` pred `uvicorn` (`docker-compose.yml`).
Napaka v njej pomeni, da vsebnik sploh ne vstane. Testi sicer shemo postavijo
z `Base.metadata.create_all`, zato bi se migracija in modeli lahko tiho
razšla, migracije pa nihče ne bi pognal do prve namestitve.

Test teče nad SQLite, ker Docker ni pogoj za zeleno zbirko (odločitev 2 v
`docs/plan/V1-R02.md`). Migracija je dialekt-varna: `CREATE EXTENSION vector`
se izvede samo nad Postgresom. Prav zato ostane `CREATE EXTENSION` **edino**,
česar ta test ne pokrije.
"""

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.models import Base

KOREN = Path(__file__).resolve().parent.parent


def alembic_nastavitve(database_url: str) -> Config:
    config = Config(str(KOREN / "alembic.ini"))
    config.set_main_option("script_location", str(KOREN / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture
def baza(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    # `DATABASE_URL` gre stran, čeprav ima izrecna nastavitev v `env.py` že
    # prednost. Ta test dela `downgrade base`; če bi se kdaj povezal na živo
    # bazo, bi v njej spustil tabelo `materials`. Dve ograji sta tu poceni,
    # posledica ene same napake pa ni.
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # Datoteka in ne `:memory:`: Alembic si odpre svojo povezavo, baza v
    # pomnilniku pa z njo ne bi bila ista.
    return f"sqlite:///{tmp_path / 'test.db'}"


def test_migracija_ustvari_tabelo_materials(baza: str) -> None:
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        assert "materials" in inspect(motor).get_table_names()
    finally:
        motor.dispose()


@pytest.mark.parametrize("tabela", ["materials", "questions"])
def test_migrirana_shema_se_ujema_z_modeli(baza: str, tabela: str) -> None:
    """Če se model in migracija razideta, mora to javiti test, ne namestitev.

    Primerja se **vsaka** tabela iz modelov, ne samo `materials`: nova tabela,
    ki bi jo kdo dodal samo v modele, bi sicer testom ušla in bi jo opazil
    šele vsebnik ob zagonu.
    """
    command.upgrade(alembic_nastavitve(baza), "head")

    iz_migracije = create_engine(baza)
    iz_modelov = create_engine("sqlite://")
    try:
        Base.metadata.create_all(iz_modelov)

        stolpci_migracije = {
            (s["name"], type(s["type"]).__name__, s["nullable"])
            for s in inspect(iz_migracije).get_columns(tabela)
        }
        stolpci_modelov = {
            (s["name"], type(s["type"]).__name__, s["nullable"])
            for s in inspect(iz_modelov).get_columns(tabela)
        }

        assert stolpci_migracije == stolpci_modelov
    finally:
        iz_migracije.dispose()
        iz_modelov.dispose()


def test_migracija_pokrije_vse_tabele_iz_modelov(baza: str) -> None:
    """Varovalo za test zgoraj: ta ima seznam tabel zapisan na roko.

    Brez te trditve bi bila enajsta tabela v modelih neopažena — parametri
    testa bi je preprosto ne omenjali in vse bi ostalo zeleno.
    """
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        iz_migracije = set(inspect(motor).get_table_names()) - {"alembic_version"}
        assert iz_migracije == set(Base.metadata.tables)
    finally:
        motor.dispose()


def test_vprasanja_kazejo_na_material(baza: str) -> None:
    """Tuji ključ mora biti `SET NULL`, ne `CASCADE`.

    Do V1-R07 je bil `CASCADE` in ta test je to tudi zahteval. Zamenjava ni
    oslabitev testa, ampak sprememba pogodbe: `docs/odlocitve/ADR-012` pravi,
    da mora vprašanje material preživeti, ker nosi statistiko, ki jo bo V2
    vezala nanj. `CASCADE` v shemi bi to odločitev tiho izničil povsod, kjer
    gre brisanje mimo ORM.

    Na SQLite je tuji ključ brez `PRAGMA foreign_keys=ON` neaktiven, zato ga
    tu ne preverjamo z brisanjem, ampak v shemi — na Postgresu je prav on
    tisti, ki odloča pri brisanju mimo ORM.
    """
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        kljuci = inspect(motor).get_foreign_keys("questions")
        assert len(kljuci) == 1
        assert kljuci[0]["referred_table"] == "materials"
        assert kljuci[0]["constrained_columns"] == ["material_id"]
        assert kljuci[0]["referred_columns"] == ["id"]
        assert kljuci[0]["options"]["ondelete"].upper() == "SET NULL"
    finally:
        motor.dispose()


def test_obstojeci_zapis_prezivi_migracijo(baza: str) -> None:
    """Vrstica iz V1-R02 mora migracijo prestati nedotaknjena.

    To je smisel tega, da so novi stolpci `NULL`-abilni. Če bi kdaj kdo enemu
    dodal `nullable=False` brez privzetka, bi `upgrade` nad polno bazo padel —
    in vsebnik se ne bi zagnal.
    """
    config = alembic_nastavitve(baza)
    command.upgrade(config, "0001_materials")

    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            povezava.execute(
                text(
                    "INSERT INTO materials "
                    "(id, subject, taken_at, image_path, status, received_at) "
                    "VALUES ('star', 'MAT', '2026-09-01 08:00:00', "
                    "'/data/images/star.jpg', 'new', '2026-09-01 08:05:00')"
                )
            )

        command.upgrade(config, "head")

        with motor.connect() as povezava:
            vrstica = povezava.execute(
                text("SELECT status, transcript, readable FROM materials WHERE id = 'star'")
            ).one()

        # Status ostane `new`, torej ga worker pobere kot vsako drugo sliko;
        # novi stolpci so prazni, ne izmišljeni.
        assert vrstica.status == "new"
        assert vrstica.transcript is None
        assert vrstica.readable is None
    finally:
        motor.dispose()


def test_obstojeca_vprasanja_prezivijo_prepis_tabele(baza: str) -> None:
    """Vrstice iz V1-R03 morajo prestati prepis tabele `questions`.

    Migracija `0003_arhiv` na SQLite tabelo **prepiše na novo**
    (`batch_alter_table` s `copy_from`), ker `ALTER` tujega ključa tam ne
    obstaja. Brez tega testa se prepis nikoli ne izvede nad nobeno vrstico in
    nič ne dokazuje, da podatki pri tem ne izginejo.

    Hkrati je to edini test, ki požene zapolnitev denormaliziranega izvora.
    Brez nje bi vprašanje po dokončnem brisanju materiala ne vedelo več, iz
    katere snovi je (`docs/odlocitve/ADR-012`).
    """
    config = alembic_nastavitve(baza)
    command.upgrade(config, "0002_obdelava")

    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            povezava.execute(
                text(
                    "INSERT INTO materials "
                    "(id, subject, taken_at, image_path, status, received_at) "
                    "VALUES ('star', 'ZGO', '2026-09-01 08:00:00', "
                    "'/data/images/star.jpg', 'ready', '2026-09-01 08:05:00')"
                )
            )
            povezava.execute(
                text(
                    "INSERT INTO questions (id, material_id, position, question, answer) "
                    "VALUES ('v1', 'star', 1, 'Kdaj?', 'Leta 1991.')"
                )
            )

        command.upgrade(config, "head")

        with motor.connect() as povezava:
            vrstica = povezava.execute(
                text(
                    "SELECT material_id, question, answer, subject, material_taken_at "
                    "FROM questions WHERE id = 'v1'"
                )
            ).one()

        assert vrstica.material_id == "star"
        assert vrstica.question == "Kdaj?"
        assert vrstica.answer == "Leta 1991."
        # Izvor se napolni iz materiala, ne pusti prazen.
        assert vrstica.subject == "ZGO"
        assert str(vrstica.material_taken_at).startswith("2026-09-01 08:00:00")
    finally:
        motor.dispose()


def test_obstojece_vprasanje_je_po_migraciji_veljavno(baza: str) -> None:
    """Vrstica iz V1-R03 mora migracijo `0004` prestati kot **veljavno** vprašanje.

    To je smisel tega, da je `retired_at` `NULL`-abilen brez privzetka:
    `NULL` pomeni veljavno vprašanje (`docs/odlocitve/ADR-015`), zato obstoječih
    vrstic ni treba nikamor prepisati. Če bi kdo stolpcu kdaj dal `NOT NULL` s
    privzetkom „zdaj", bi migracija vsa dosedanja vprašanja tiho upokojila —
    kviz `V2-R01` bi po namestitvi ostal brez vsebine in nihče ne bi vedel zakaj.
    """
    config = alembic_nastavitve(baza)
    command.upgrade(config, "0003_arhiv")

    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            povezava.execute(
                text(
                    "INSERT INTO materials "
                    "(id, subject, taken_at, image_path, status, received_at) "
                    "VALUES ('star', 'ZGO', '2026-09-01 08:00:00', "
                    "'/data/images/star.jpg', 'ready', '2026-09-01 08:05:00')"
                )
            )
            povezava.execute(
                text(
                    "INSERT INTO questions "
                    "(id, material_id, position, question, answer, subject) "
                    "VALUES ('v1', 'star', 1, 'Kdaj?', 'Leta 1991.', 'ZGO')"
                )
            )

        command.upgrade(config, "head")

        with motor.connect() as povezava:
            vrstica = povezava.execute(
                text("SELECT question, answer, retired_at FROM questions WHERE id = 'v1'")
            ).one()

        # Vsebina nedotaknjena, stolpec prazen — ne izmišljen.
        assert vrstica.question == "Kdaj?"
        assert vrstica.answer == "Leta 1991."
        assert vrstica.retired_at is None
    finally:
        motor.dispose()


def test_razveljavitev_prezivi_podatke(baza: str) -> None:
    """`downgrade` nad polno bazo, ne le nad prazno.

    Prepis tabele v obratno smer in vrnitev `NOT NULL` na `material_id` sta
    poteza, ki nad prazno bazo uspe vedno. Test brez podatkov torej ne bi
    dokazal ničesar o njej.
    """
    config = alembic_nastavitve(baza)
    command.upgrade(config, "head")

    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            povezava.execute(
                text(
                    "INSERT INTO materials "
                    "(id, subject, taken_at, image_path, status, received_at) "
                    "VALUES ('star', 'MAT', '2026-09-01 08:00:00', "
                    "'/data/images/star.jpg', 'ready', '2026-09-01 08:05:00')"
                )
            )
            povezava.execute(
                text(
                    "INSERT INTO questions "
                    "(id, material_id, position, question, answer, subject) "
                    "VALUES ('v1', 'star', 1, 'Kdaj?', 'Leta 1991.', 'MAT')"
                )
            )
            # Sirota, ki je shema pred to migracijo ne zna zapisati.
            povezava.execute(
                text(
                    "INSERT INTO questions "
                    "(id, material_id, position, question, answer, subject) "
                    "VALUES ('v2', NULL, 1, 'Brez materiala?', 'Da.', 'MAT')"
                )
            )

        command.downgrade(config, "0002_obdelava")

        with motor.connect() as povezava:
            preostala = povezava.execute(text("SELECT id FROM questions")).scalars().all()

        # Vprašanje z materialom ostane, sirota gre — tako je zapisano v
        # docstringu migracije in nikjer drugje to ni preverjeno.
        assert preostala == ["v1"]
    finally:
        motor.dispose()


def test_primarni_kljuc_je_id(baza: str) -> None:
    """Idempotentnost stoji na tem, da je `id` primarni ključ."""
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        assert inspect(motor).get_pk_constraint("materials")["constrained_columns"] == ["id"]
    finally:
        motor.dispose()


def test_migracija_se_da_razveljaviti(baza: str) -> None:
    config = alembic_nastavitve(baza)
    command.upgrade(config, "head")

    motor = create_engine(baza)
    try:
        # Najprej se prepričamo, da je migracija res tekla **nad to** bazo.
        # Brez tega bi bila zaključna trditev izpolnjena tudi, če bi Alembic
        # delal nad neko drugo bazo, ta pa bi bila ves čas prazna — in test bi
        # bil zelen prav takrat, ko bi bilo najbolj narobe.
        assert "materials" in inspect(motor).get_table_names()

        command.downgrade(config, "base")

        assert "materials" not in inspect(motor).get_table_names()
    finally:
        motor.dispose()


def test_izrecna_nastavitev_ima_prednost_pred_okoljem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regresija: `DATABASE_URL` ne sme preusmeriti migracije drugam.

    Če bi okolje premagalo izrecno nastavitev, bi `pytest` v lupini z
    izvoženim `DATABASE_URL` migriral živo bazo — in `downgrade base` bi v njej
    spustil tabelo `materials`.
    """
    ciljna = tmp_path / "ciljna.db"
    tuja = tmp_path / "tuja.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tuja}")

    command.upgrade(alembic_nastavitve(f"sqlite:///{ciljna}"), "head")

    assert ciljna.exists()
    # Tuje baze se migracija ne sme niti dotakniti.
    assert not tuja.exists()
