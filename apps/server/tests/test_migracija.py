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
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.models import Base

KOREN = Path(__file__).resolve().parent.parent

#: Stalen `id` družine Cvek iz `0007_druzine`.
CVEK_ID = "5b0f6c2e-8d3a-4c7e-9a1b-2f4d6e8c0a13"

#: Stalen `id` otroka (Maša) iz `0008_uporabniki`. Edini otrok družine Cvek,
#: zato je pripis v `0009_otrok_na_zapisu` enoumen.
MASA_ID = "3e7b9a05-4c12-4f6d-9b83-1d5f8c0a2e47"


def alembic_nastavitve(database_url: str) -> Config:
    config = Config(str(KOREN / "alembic.ini"))
    config.set_main_option("script_location", str(KOREN / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture
def baza(tmp_path: Path, slike: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    # `DATABASE_URL` gre stran, čeprav ima izrecna nastavitev v `env.py` že
    # prednost. Ta test dela `downgrade base`; če bi se kdaj povezal na živo
    # bazo, bi v njej spustil tabelo `materials`. Dve ograji sta tu poceni,
    # posledica ene same napake pa ni.
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # `0007_druzine` premika slike in brez mape nad polno bazo pade. Mapa je
    # testna, kot baza; test, ki preverja prav odsotnost, jo odstrani sam.
    monkeypatch.setenv("IMAGES_DIR", str(slike))

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


@pytest.mark.parametrize("tabela", sorted(Base.metadata.tables))
def test_migrirana_shema_se_ujema_z_modeli(baza: str, tabela: str) -> None:
    """Če se model in migracija razideta, mora to javiti test, ne namestitev.

    Primerja se **vsaka** tabela iz modelov, ne samo `materials`: nova tabela,
    ki bi jo kdo dodal samo v modele, bi sicer testom ušla in bi jo opazil
    šele vsebnik ob zagonu.

    Seznam tabel je do V3-R03 stal na roko napisan v parametrih in ni bil
    razširjen — štiri tabele identitete so tako ostale brez primerjave po
    stolpcih, čeprav je varovalo spodaj imena preverilo. Odslej pride iz
    `Base.metadata`, kjer zaostati ne more.
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
        # Po stolpcu in ne „edini ključ": od `0007_druzine` ima tabela še
        # ključ na `families`, ki ga preverja `test_druzina_je_obvezen_tuji_kljuc`.
        kljuci = [
            k
            for k in inspect(motor).get_foreign_keys("questions")
            if k["constrained_columns"] == ["material_id"]
        ]
        assert len(kljuci) == 1
        assert kljuci[0]["referred_table"] == "materials"
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


def _vstavi_kviz(
    povezava: Any, family_id: str | None = None, child_id: str | None = None
) -> None:
    """Kviz z eno postavko, kot ga je pustila `0005_kvizi`.

    Z `family_id` kot po `0007_druzine` in s `child_id` kot po
    `0009_otrok_na_zapisu`, kjer sta stolpca obvezna.
    """
    if family_id is None:
        povezava.execute(
            text(
                "INSERT INTO quizzes (id, name, subject, created_at) "
                "VALUES ('k1', 'MAT — 9. 9. 2026', 'MAT', '2026-09-09 08:00:00')"
            )
        )
    elif child_id is None:
        povezava.execute(
            text(
                "INSERT INTO quizzes (id, name, subject, created_at, family_id) "
                "VALUES ('k1', 'MAT — 9. 9. 2026', 'MAT', '2026-09-09 08:00:00', :druzina)"
            ),
            {"druzina": family_id},
        )
    else:
        povezava.execute(
            text(
                "INSERT INTO quizzes (id, name, subject, created_at, family_id, child_id) "
                "VALUES ('k1', 'MAT — 9. 9. 2026', 'MAT', '2026-09-09 08:00:00', "
                ":druzina, :otrok)"
            ),
            {"druzina": family_id, "otrok": child_id},
        )
    povezava.execute(
        text(
            "INSERT INTO quiz_items (id, quiz_id, question_id, position, "
            "question_text, answer_text) "
            "VALUES ('p1', 'k1', NULL, 1, 'Kdaj?', 'Leta 1991.')"
        )
    )


def test_obstojeci_kviz_prezivi_migracijo_poskusov(baza: str) -> None:
    """Kviz iz V2-R01 mora migracijo `0006` prestati kot **nerešen**.

    To je smisel tega, da je `solved_at` `NULL`-abilen brez privzetka: kviz,
    ki ga nihče ni rešil, ne sme po namestitvi veljati za rešenega — sicer ga
    telefon nikoli ne bi dobil.
    """
    config = alembic_nastavitve(baza)
    command.upgrade(config, "0005_kvizi")

    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            _vstavi_kviz(povezava)

        command.upgrade(config, "head")

        with motor.connect() as povezava:
            kviz = povezava.execute(
                text("SELECT name, solved_at, canceled_at FROM quizzes WHERE id = 'k1'")
            ).one()
            postavka = povezava.execute(
                text("SELECT question_text FROM quiz_items WHERE id = 'p1'")
            ).one()

        assert kviz.name == "MAT — 9. 9. 2026"
        assert kviz.solved_at is None
        assert kviz.canceled_at is None
        assert postavka.question_text == "Kdaj?"
        assert "question_attempts" in inspect(motor).get_table_names()
    finally:
        motor.dispose()


def test_poskus_je_enolicen_na_postavko_in_brez_kaskade(baza: str) -> None:
    """`ADR-019` E v shemi, ne le v repozitoriju; tuji ključ brez `ondelete`.

    Poskus nosi statistiko (`ADR-012`), zato baza brisanja kviza s poskusi ne
    sme tiho izvesti. Kot pri `test_vprasanja_kazejo_na_material` se tu bere
    shema, ker SQLite brez `PRAGMA foreign_keys=ON` ključev ne uveljavlja.
    """
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        pregled = inspect(motor)
        # Po stolpcu, iz istega razloga kot v `test_vprasanja_kazejo_na_material`.
        [kljuc] = [
            k
            for k in pregled.get_foreign_keys("question_attempts")
            if k["constrained_columns"] == ["quiz_item_id"]
        ]
        assert kljuc["referred_table"] == "quiz_items"
        assert not kljuc["options"].get("ondelete")

        enolicni = [u["column_names"] for u in pregled.get_unique_constraints("question_attempts")]
        assert ["quiz_item_id"] in enolicni
    finally:
        motor.dispose()


def test_razveljavitev_poskusov_ohrani_kvize(baza: str) -> None:
    """`downgrade` čez `0006` nad bazo s poskusom: kvizi ostanejo, poskusov ni."""
    config = alembic_nastavitve(baza)
    command.upgrade(config, "head")

    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            _vstavi_kviz(povezava, CVEK_ID, MASA_ID)
            povezava.execute(
                text(
                    "INSERT INTO question_attempts (id, quiz_item_id, mode, rating, "
                    "shown_at, revealed_at, answered_at, received_at, family_id, child_id) "
                    "VALUES ('a1', 'p1', 'samoocena', 'lahko', '2026-09-10 15:00:00', "
                    "'2026-09-10 15:00:07', '2026-09-10 15:00:09', '2026-09-10 15:05:00', "
                    ":druzina, :otrok)"
                ),
                {"druzina": CVEK_ID, "otrok": MASA_ID},
            )
            povezava.execute(
                text("UPDATE quizzes SET solved_at = '2026-09-10 15:05:00' WHERE id = 'k1'")
            )

        command.downgrade(config, "0005_kvizi")

        pregled = inspect(motor)
        assert "question_attempts" not in pregled.get_table_names()
        assert "solved_at" not in {s["name"] for s in pregled.get_columns("quizzes")}
        with motor.connect() as povezava:
            assert povezava.execute(text("SELECT id FROM quizzes")).scalars().all() == ["k1"]
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
            # `family_id` je od `0007_druzine` obvezen in `child_id` od
            # `0009_otrok_na_zapisu`; Cvek in Mašo ustvarita migraciji sami.
            druzina = {"druzina": CVEK_ID}
            povezava.execute(
                text(
                    "INSERT INTO materials (id, subject, taken_at, image_path, status, "
                    "received_at, family_id, child_id) "
                    "VALUES ('star', 'MAT', '2026-09-01 08:00:00', "
                    "'/data/images/star.jpg', 'ready', '2026-09-01 08:05:00', "
                    ":druzina, :otrok)"
                ),
                {**druzina, "otrok": MASA_ID},
            )
            povezava.execute(
                text(
                    "INSERT INTO questions "
                    "(id, material_id, position, question, answer, subject, family_id) "
                    "VALUES ('v1', 'star', 1, 'Kdaj?', 'Leta 1991.', 'MAT', :druzina)"
                ),
                druzina,
            )
            # Sirota, ki je shema pred to migracijo ne zna zapisati.
            povezava.execute(
                text(
                    "INSERT INTO questions "
                    "(id, material_id, position, question, answer, subject, family_id) "
                    "VALUES ('v2', NULL, 1, 'Brez materiala?', 'Da.', 'MAT', :druzina)"
                ),
                druzina,
            )
            # Upokojeno vprašanje, da gre `downgrade` migracije `0004` res
            # čez vrstico, ki ima stolpec napolnjen. Brez nje bi `DROP COLUMN`
            # tekel nad samimi praznimi vrednostmi in ne bi dokazal ničesar.
            povezava.execute(
                text(
                    "INSERT INTO questions (id, material_id, position, question, "
                    "answer, subject, retired_at, family_id) "
                    "VALUES ('v3', 'star', 1, 'Stara serija?', 'Da.', 'MAT', "
                    "'2026-09-06 09:00:00', :druzina)"
                ),
                druzina,
            )

        command.downgrade(config, "0002_obdelava")

        with motor.connect() as povezava:
            preostala = povezava.execute(text("SELECT id FROM questions")).scalars().all()

        # Vprašanje z materialom ostane — tudi upokojeno, ki po `DROP COLUMN`
        # od veljavnega ni več ločljivo. Sirota gre; tako je zapisano v
        # docstringu migracije `0003_arhiv` in nikjer drugje to ni preverjeno.
        assert preostala == ["v1", "v3"]
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


# --- Družine (V3-R01, `0007_druzine`) ---


def _polna_baza_pred_druzinami(baza: str, slike: Path) -> None:
    """Baza v stanju `0006_poskusi`, kakršna je na strežniku pred V3-R01.

    Material s sliko, arhiviran material brez slike (počiščena slika), vprašanje,
    osirotelo vprašanje, kviz s postavko in poskus. Na disku še datoteka brez
    vrstice in ostanek v `.tmp/` — oboje mora migracija pustiti pri miru.
    """
    command.upgrade(alembic_nastavitve(baza), "0006_poskusi")

    (slike / "m1.jpg").write_bytes(b"slika-m1")
    (slike / "sirota.jpg").write_bytes(b"sirota")
    (slike / ".tmp").mkdir()
    (slike / ".tmp" / "napol.jpg").write_bytes(b"napol")

    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            for material_id, arhiviran in (("m1", None), ("m2", "2026-09-05 10:00:00")):
                povezava.execute(
                    text(
                        "INSERT INTO materials (id, subject, taken_at, image_path, status, "
                        "received_at, archived_at) VALUES (:id, 'MAT', '2026-09-01 08:00:00', "
                        ":pot, 'ready', '2026-09-01 08:05:00', :arhiv)"
                    ),
                    {
                        "id": material_id,
                        "pot": str(slike / f"{material_id}.jpg"),
                        "arhiv": arhiviran,
                    },
                )
            povezava.execute(
                text(
                    "INSERT INTO questions (id, material_id, position, question, answer, subject) "
                    "VALUES ('v1', 'm1', 1, 'Kdaj?', 'Leta 1991.', 'MAT'), "
                    "('v2', NULL, 1, 'Brez materiala?', 'Da.', 'MAT')"
                )
            )
            _vstavi_kviz(povezava)
            povezava.execute(text("UPDATE quiz_items SET question_id = 'v1' WHERE id = 'p1'"))
            povezava.execute(
                text(
                    "INSERT INTO question_attempts (id, quiz_item_id, mode, rating, "
                    "shown_at, revealed_at, answered_at, received_at) "
                    "VALUES ('a1', 'p1', 'samoocena', 'lahko', '2026-09-10 15:00:00', "
                    "'2026-09-10 15:00:07', '2026-09-10 15:00:09', '2026-09-10 15:05:00')"
                )
            )
    finally:
        motor.dispose()


#: Tabele, ki po `0007_druzine` nosijo družino, in koliko vrstic ima vsaka v
#: `_polna_baza_pred_druzinami`.
VRSTIC = {"materials": 2, "questions": 2, "quizzes": 1, "question_attempts": 1}


def _stej(motor: Any) -> dict[str, int]:
    with motor.connect() as povezava:
        return {
            tabela: povezava.execute(text(f"SELECT count(*) FROM {tabela}")).scalar_one()
            for tabela in [*VRSTIC, "quiz_items"]
        }


def test_druzina_cvek_prevzame_vse_vrstice_in_slike(baza: str, slike: Path) -> None:
    """Kriterij V3-R01: vse vrstice dobijo Cvek, vse slike gredo v njeno mapo."""
    _polna_baza_pred_druzinami(baza, slike)

    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        with motor.connect() as povezava:
            druzine = povezava.execute(text("SELECT id, name FROM families")).tuples().all()
            assert druzine == [(CVEK_ID, "Cvek")]
            for tabela in VRSTIC:
                v_tabeli = povezava.execute(text(f"SELECT DISTINCT family_id FROM {tabela}"))
                assert v_tabeli.scalars().all() == [CVEK_ID], tabela
            poti = dict(
                povezava.execute(text("SELECT id, image_path FROM materials")).tuples().all()
            )

        assert _stej(motor) == {**VRSTIC, "quiz_items": 1}
    finally:
        motor.dispose()

    mapa = slike / CVEK_ID
    # Slika je premaknjena z vsebino vred, pot v bazi kaže nanjo.
    assert poti["m1"] == str(mapa / "m1.jpg")
    assert (mapa / "m1.jpg").read_bytes() == b"slika-m1"
    assert not (slike / "m1.jpg").exists()
    # Počiščena slika: pot prepisana, datoteke ni in je tudi prej ni bilo.
    assert poti["m2"] == str(mapa / "m2.jpg")
    assert not (mapa / "m2.jpg").exists()
    # Sirota in ostanek v `.tmp/` ostaneta, kjer sta bila.
    assert (slike / "sirota.jpg").read_bytes() == b"sirota"
    assert (slike / ".tmp" / "napol.jpg").read_bytes() == b"napol"
    assert not (mapa / "sirota.jpg").exists()


def test_migracija_brez_mape_slik_nad_polno_bazo_pade(
    baza: str, slike: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tih privzetek bi prepisal poti, datotek pa ne bi premaknil."""
    _polna_baza_pred_druzinami(baza, slike)
    monkeypatch.delenv("IMAGES_DIR")

    with pytest.raises(RuntimeError, match="IMAGES_DIR"):
        command.upgrade(alembic_nastavitve(baza), "head")

    # Preverba je pred vsakim DDL: shema in slika sta nedotaknjeni.
    motor = create_engine(baza)
    try:
        assert "families" not in inspect(motor).get_table_names()
    finally:
        motor.dispose()
    assert (slike / "m1.jpg").read_bytes() == b"slika-m1"


def test_migracija_prazne_baze_ne_potrebuje_mape_slik(
    baza: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("IMAGES_DIR")

    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        with motor.connect() as povezava:
            assert povezava.execute(text("SELECT id FROM families")).scalars().all() == [CVEK_ID]
    finally:
        motor.dispose()


def test_ponovni_zagon_po_prekinjenem_premiku(baza: str, slike: Path) -> None:
    """Premik ni v transakciji baze: baza je stara, slika pa že v mapi Cvek.

    Točno to stanje pusti migracija, ki pade po premiku datotek in se ji baza
    vrne. Ponovni zagon mora priti do istega izida kot neprekinjen.
    """
    _polna_baza_pred_druzinami(baza, slike)
    # `exist_ok`: mapo Cvek fixture `slike` že ustvari (`conftest.py`).
    (slike / CVEK_ID).mkdir(exist_ok=True)
    (slike / "m1.jpg").replace(slike / CVEK_ID / "m1.jpg")

    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        with motor.connect() as povezava:
            pot = povezava.execute(
                text("SELECT image_path FROM materials WHERE id = 'm1'")
            ).scalar_one()
    finally:
        motor.dispose()
    assert pot == str(slike / CVEK_ID / "m1.jpg")
    assert (slike / CVEK_ID / "m1.jpg").read_bytes() == b"slika-m1"


def test_razveljavitev_druzin_vrne_slike_poti_in_vrstice(baza: str, slike: Path) -> None:
    """`downgrade` nad polno bazo: nobena vrstica ne izgine, slike nazaj v koren."""
    _polna_baza_pred_druzinami(baza, slike)
    config = alembic_nastavitve(baza)
    command.upgrade(config, "head")

    command.downgrade(config, "0006_poskusi")

    motor = create_engine(baza)
    try:
        pregled = inspect(motor)
        assert "families" not in pregled.get_table_names()
        for tabela in VRSTIC:
            assert "family_id" not in {s["name"] for s in pregled.get_columns(tabela)}, tabela
        assert _stej(motor) == {**VRSTIC, "quiz_items": 1}
        with motor.connect() as povezava:
            poti = dict(
                povezava.execute(text("SELECT id, image_path FROM materials")).tuples().all()
            )
    finally:
        motor.dispose()

    assert poti == {"m1": str(slike / "m1.jpg"), "m2": str(slike / "m2.jpg")}
    assert (slike / "m1.jpg").read_bytes() == b"slika-m1"
    assert not (slike / CVEK_ID / "m1.jpg").exists()


def test_razveljavitev_z_dvema_druzinama_se_ne_izvede(baza: str) -> None:
    config = alembic_nastavitve(baza)
    command.upgrade(config, "head")
    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            povezava.execute(
                text(
                    "INSERT INTO families (id, name, created_at) "
                    "VALUES ('druga', 'Druga', '2026-09-14 10:00:00')"
                )
            )

        with pytest.raises(RuntimeError, match="2 družin"):
            command.downgrade(config, "0006_poskusi")

        assert "families" in inspect(motor).get_table_names()
    finally:
        motor.dispose()


@pytest.mark.parametrize("tabela", list(VRSTIC))
def test_druzina_je_obvezen_tuji_kljuc(baza: str, tabela: str) -> None:
    """`family_id` kaže na `families`, brez `ondelete` — družina se ne briše."""
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        pregled = inspect(motor)
        [kljuc] = [
            k
            for k in pregled.get_foreign_keys(tabela)
            if k["constrained_columns"] == ["family_id"]
        ]
        assert kljuc["referred_table"] == "families"
        assert kljuc["referred_columns"] == ["id"]
        assert not kljuc["options"].get("ondelete")
        [stolpec] = [s for s in pregled.get_columns(tabela) if s["name"] == "family_id"]
        assert stolpec["nullable"] is False
    finally:
        motor.dispose()


def test_postavka_kviza_nima_druzine(baza: str) -> None:
    """Družina postavke je družina kviza (`ADR-029` C)."""
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        assert "family_id" not in {s["name"] for s in inspect(motor).get_columns("quiz_items")}
    finally:
        motor.dispose()


# --- Uporabniki, poverilnice in seje (V3-R03, `0008_uporabniki`) ------------


def _vrstice(motor: Any, stavek: str) -> list[tuple[Any, ...]]:
    with motor.connect() as povezava:
        return [tuple(v) for v in povezava.execute(text(stavek))]


def test_migracija_ustvari_lastnika_in_otroka(baza: str) -> None:
    """Kriterij V3-R03: migracija posadi starša (lastnika) in otroka Mašo.

    Test je natančen glede **identifikatorjev**, ne le glede števila vrstic:
    napačen e-naslov bi pomenil, da ukaz `nastavi-geslo` računa ne najde in da
    admina po namestitvi ni mogoče odkleniti brez ročnega posega v bazo.
    """
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        uporabniki = _vrstice(
            motor,
            "SELECT u.role, u.display_name, u.is_system_owner, u.is_active, "
            "u.family_id, c.kind, c.identifier, c.secret_hash "
            "FROM users u JOIN credentials c ON c.user_id = u.id "
            "ORDER BY u.role",
        )

        assert uporabniki == [
            ("child", "Maša", 0, 1, CVEK_ID, "password", "masa", None),
            (
                "parent",
                "Dejan",
                1,
                1,
                CVEK_ID,
                "password",
                "dejan.ambrus@gmail.com",
                None,
            ),
        ]
    finally:
        motor.dispose()


def test_gesla_v_migraciji_ni(baza: str) -> None:
    """`secret_hash` je `NULL`: privzeto geslo v repozitoriju bi bilo javno geslo."""
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        assert _vrstice(motor, "SELECT secret_hash FROM credentials") == [(None,), (None,)]
        besedilo = (KOREN / "alembic" / "versions" / "0008_uporabniki.py").read_text(
            encoding="utf-8"
        )
        assert "argon2" not in besedilo
        assert "secret_hash, created_at, updated_at" in besedilo
    finally:
        motor.dispose()


def test_identifikator_je_enolicen_cez_namestitev(baza: str) -> None:
    """Dva enaka identifikatorja bi pomenila prijavo, ki ne ve, kdo se prijavlja."""
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        enolicni = inspect(motor).get_unique_constraints("credentials")
        assert ["identifier"] in [u["column_names"] for u in enolicni]
        assert ["token_hash"] in [
            u["column_names"] for u in inspect(motor).get_unique_constraints("sessions")
        ]
    finally:
        motor.dispose()


@pytest.mark.parametrize("tabela", ["users", "credentials", "sessions"])
def test_tabele_identitete_kazejo_na_lastnika(baza: str, tabela: str) -> None:
    """`users` na družino, `credentials` in `sessions` na uporabnika."""
    command.upgrade(alembic_nastavitve(baza), "head")

    cilj = {"users": ("family_id", "families"), "credentials": ("user_id", "users")}.get(
        tabela, ("user_id", "users")
    )
    motor = create_engine(baza)
    try:
        [kljuc] = [
            k
            for k in inspect(motor).get_foreign_keys(tabela)
            if k["constrained_columns"] == [cilj[0]]
        ]
        assert kljuc["referred_table"] == cilj[1]
    finally:
        motor.dispose()


def test_poskusi_prijave_druzine_nimajo(baza: str) -> None:
    """Poskus se zabeleži tudi za identifikator, ki ne obstaja (`ADR-035` E)."""
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        stolpci = {s["name"] for s in inspect(motor).get_columns("login_attempts")}
        assert stolpci == {"id", "identifier", "ip_address", "created_at"}
        assert inspect(motor).get_foreign_keys("login_attempts") == []
    finally:
        motor.dispose()


def test_razveljavitev_0008_pusti_podatke_druzine(baza: str) -> None:
    """`downgrade` spusti tabele identitete in se snovi ne dotakne."""
    command.upgrade(alembic_nastavitve(baza), "head")
    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            povezava.execute(
                text(
                    "INSERT INTO materials (id, family_id, child_id, subject, taken_at, "
                    "image_path, status, received_at) VALUES ('m1', :druzina, :otrok, "
                    "'MAT', '2026-09-04 07:30:00', '/x.jpg', 'new', '2026-09-04 08:00:00')"
                ),
                {"druzina": CVEK_ID, "otrok": MASA_ID},
            )
    finally:
        motor.dispose()

    command.downgrade(alembic_nastavitve(baza), "0007_druzine")

    motor = create_engine(baza)
    try:
        tabele = set(inspect(motor).get_table_names())
        assert not tabele & {"users", "credentials", "sessions", "login_attempts"}
        assert _vrstice(motor, "SELECT id FROM materials") == [("m1",)]
    finally:
        motor.dispose()


# --- Otrok na zapisu (V3-R07, `0009_otrok_na_zapisu`) ---


def _baza_pred_otrokom(baza: str, slike: Path) -> None:
    """Baza v stanju `0008_uporabniki`: snov, kviz in poskus, vse v Cveku.

    Po migraciji mora vse troje nositi Mašo — edinega otroka te družine.
    """
    _polna_baza_pred_druzinami(baza, slike)
    command.upgrade(alembic_nastavitve(baza), "0008_uporabniki")


def _dodaj_otroka(baza: str, user_id: str, ime: str, family_id: str = CVEK_ID) -> None:
    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            povezava.execute(
                text(
                    "INSERT INTO users (id, family_id, role, display_name, "
                    "is_system_owner, is_active, created_at) VALUES (:id, :druzina, "
                    "'child', :ime, 0, 1, '2026-09-20 10:00:00')"
                ),
                {"id": user_id, "druzina": family_id, "ime": ime},
            )
    finally:
        motor.dispose()


def _dodaj_druzino(baza: str, family_id: str, ime: str) -> None:
    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            povezava.execute(
                text(
                    "INSERT INTO families (id, name, created_at) "
                    "VALUES (:id, :ime, '2026-09-20 10:00:00')"
                ),
                {"id": family_id, "ime": ime},
            )
    finally:
        motor.dispose()


def test_migracija_pripise_edinega_otroka_druzine(baza: str, slike: Path) -> None:
    """Kriterij V3-R07: obstoječi zapisi dobijo otroka; tu snov, kviz in poskus."""
    _baza_pred_otrokom(baza, slike)

    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        for tabela in ("materials", "quizzes", "question_attempts"):
            assert _vrstice(motor, f"SELECT DISTINCT child_id FROM {tabela}") == [
                (MASA_ID,)
            ], tabela
        # Vprašanja ostanejo last družine in otroka ne dobijo (`ADR-039` G);
        # postavka ga izpelje iz kviza, kot družino (`ADR-029` C).
        for brez in ("questions", "quiz_items"):
            assert "child_id" not in {s["name"] for s in inspect(motor).get_columns(brez)}
    finally:
        motor.dispose()


def test_migracija_otroka_ohrani_vse_vrstice(baza: str, slike: Path) -> None:
    """Pripis otroka ne sme ne izgubiti ne podvojiti nobene vrstice."""
    _baza_pred_otrokom(baza, slike)
    motor = create_engine(baza)
    try:
        prej = _stej(motor)
    finally:
        motor.dispose()

    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        assert _stej(motor) == prej
    finally:
        motor.dispose()


@pytest.mark.parametrize("tabela", ["materials", "quizzes", "question_attempts"])
def test_otrok_je_obvezen_tuji_kljuc(baza: str, tabela: str) -> None:
    """`NOT NULL` in tuji ključ na `users` — „kviz za nikogar" ne sme obstajati."""
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        stolpec = next(
            s for s in inspect(motor).get_columns(tabela) if s["name"] == "child_id"
        )
        assert stolpec["nullable"] is False

        kljuci = [
            k
            for k in inspect(motor).get_foreign_keys(tabela)
            if k["constrained_columns"] == ["child_id"]
        ]
        assert len(kljuci) == 1
        assert kljuci[0]["referred_table"] == "users"
        # Brez kaskade: račun se ne briše, deaktivira se (`V3-R06`).
        assert not kljuci[0]["options"].get("ondelete")

        indeksi = [
            i for i in inspect(motor).get_indexes(tabela) if i["column_names"] == ["child_id"]
        ]
        assert len(indeksi) == 1
    finally:
        motor.dispose()


def test_migracija_z_dvema_otrokoma_se_ne_izvede(baza: str, slike: Path) -> None:
    """Dvoumnost se ne ugane: migracija se ustavi in ničesar ne spremeni."""
    _baza_pred_otrokom(baza, slike)
    _dodaj_otroka(baza, "drugi-otrok", "Nejc")

    with pytest.raises(RuntimeError, match="ne zna ugibati"):
        command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        # Nič ni spremenjeno: stolpca ni na nobeni od treh tabel.
        for tabela in ("materials", "quizzes", "question_attempts"):
            assert "child_id" not in {
                s["name"] for s in inspect(motor).get_columns(tabela)
            }, tabela
        assert _vrstice(motor, "SELECT id FROM materials ORDER BY id") == [("m1",), ("m2",)]
    finally:
        motor.dispose()


def test_migracija_brez_otroka_se_ne_izvede(baza: str, slike: Path) -> None:
    """Družina brez otroka je ista dvoumnost z druge strani."""
    _baza_pred_otrokom(baza, slike)
    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            povezava.execute(
                text("DELETE FROM credentials WHERE user_id = :id"), {"id": MASA_ID}
            )
            povezava.execute(text("DELETE FROM users WHERE id = :id"), {"id": MASA_ID})
    finally:
        motor.dispose()

    with pytest.raises(RuntimeError, match="ima 0 otrok"):
        command.upgrade(alembic_nastavitve(baza), "head")


def test_migracija_zavrne_tudi_druzino_brez_podatkov(baza: str, slike: Path) -> None:
    """Družina brez vrstic v teh tabelah ni izjema.

    Molk o njej bi pomenil, da se migracija ustavi šele ob njeni prvi sliki —
    torej takrat, ko je na to vprašanje najtežje odgovoriti.
    """
    _baza_pred_otrokom(baza, slike)
    _dodaj_druzino(baza, "druzina-b", "Brez otrok")

    with pytest.raises(RuntimeError, match="'Brez otrok' ima 0 otrok"):
        command.upgrade(alembic_nastavitve(baza), "head")


def test_migracija_nasteje_vse_tezave_hkrati(baza: str, slike: Path) -> None:
    """Lastnik dobi cel seznam, ne prve napake od petih."""
    _baza_pred_otrokom(baza, slike)
    _dodaj_otroka(baza, "drugi-otrok", "Nejc")
    _dodaj_druzino(baza, "druzina-b", "Brez otrok")

    with pytest.raises(RuntimeError) as napaka:
        command.upgrade(alembic_nastavitve(baza), "head")

    # Dvojina: „2 otroka", ne „2 otrok". Sporočilo bere človek, ki bazo
    # popravlja (`CLAUDE.md` §1b).
    assert "'Cvek' ima 2 otroka" in str(napaka.value)
    assert "'Brez otrok' ima 0 otrok" in str(napaka.value)


def test_razveljavitev_otroka_ohrani_vrstice(baza: str, slike: Path) -> None:
    """`downgrade` spusti stolpce in ne izgubi nobene vrstice."""
    _baza_pred_otrokom(baza, slike)
    command.upgrade(alembic_nastavitve(baza), "head")

    command.downgrade(alembic_nastavitve(baza), "0008_uporabniki")

    motor = create_engine(baza)
    try:
        for tabela in ("materials", "quizzes", "question_attempts"):
            assert "child_id" not in {s["name"] for s in inspect(motor).get_columns(tabela)}
        assert _vrstice(motor, "SELECT id FROM materials ORDER BY id") == [("m1",), ("m2",)]
        assert _vrstice(motor, "SELECT id FROM question_attempts") == [("a1",)]
    finally:
        motor.dispose()


def test_deaktiviran_otrok_se_steje(baza: str, slike: Path) -> None:
    """Deaktiviran otrok je še vedno otrok — in njegovi zapisi so njegovi.

    `_otrok_na_druzino` `is_active` namenoma ne gleda: deaktivacija ne izbriše
    ničesar (`V3-R06`), zato družina z enim aktivnim in enim deaktiviranim
    otrokom **ni** enoumna in se migracija ustavi. Pred zagonom na produkciji
    to pomeni: preveri, da je v Cveku natanko en zapis z `role='child'`, tudi
    med neaktivnimi.
    """
    _baza_pred_otrokom(baza, slike)
    _dodaj_otroka(baza, "neaktivni-otrok", "Nejc")
    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            povezava.execute(
                text("UPDATE users SET is_active = 0 WHERE id = 'neaktivni-otrok'")
            )
    finally:
        motor.dispose()

    with pytest.raises(RuntimeError, match="ima 2 otroka"):
        command.upgrade(alembic_nastavitve(baza), "head")


def test_vrnitev_in_ponoven_zagon_prideta_do_istega_stanja(baza: str, slike: Path) -> None:
    """`downgrade` → `upgrade` mora dati isto, kar je bilo prej.

    Nad bazo z enim otrokom je pripis izpeljiv nazaj, zato je pot obnovljiva.
    Brez tega testa bi bila trditev iz docstringa migracije samo trditev.
    """
    _baza_pred_otrokom(baza, slike)
    command.upgrade(alembic_nastavitve(baza), "head")
    motor = create_engine(baza)
    try:
        prej = _stej(motor)
    finally:
        motor.dispose()

    command.downgrade(alembic_nastavitve(baza), "0008_uporabniki")
    command.upgrade(alembic_nastavitve(baza), "head")

    motor = create_engine(baza)
    try:
        assert _stej(motor) == prej
        for tabela in ("materials", "quizzes", "question_attempts"):
            assert _vrstice(motor, f"SELECT DISTINCT child_id FROM {tabela}") == [
                (MASA_ID,)
            ], tabela
    finally:
        motor.dispose()


def test_obstojeci_zapisi_prezivijo_urnik(baza: str, slike: Path) -> None:
    """`0010_urnik` je gol `CREATE TABLE` in se obstoječih vrstic ne dotakne.

    Preverja se prav to, kar migracija **trdi** o sebi: da ni prepisa
    podatkov. Test zato bazo napolni že pred njo in preverí, da je po njej
    vsebina enaka — ne le, da novi tabeli obstajata (to pove že varovalo
    `test_migracija_pokrije_vse_tabele_iz_modelov`).
    """
    config = alembic_nastavitve(baza)
    _polna_baza_pred_druzinami(baza, slike)
    command.upgrade(config, "0009_otrok_na_zapisu")

    motor = create_engine(baza)
    try:
        prej = _stej(motor)
        assert prej["materials"] >= 1, "test mora teči nad polno bazo"

        command.upgrade(config, "0010_urnik")

        tabele = set(inspect(motor).get_table_names())
        assert {"schedules", "schedule_entries"} <= tabele
        assert _stej(motor) == prej, "urnik ne sme premakniti nobene obstoječe vrstice"
    finally:
        motor.dispose()


def test_razveljavitev_urnika_ohrani_ostalo(baza: str, slike: Path) -> None:
    """`downgrade` spusti obe tabeli in nič drugega.

    Urniki se pri tem izgubijo dokončno — isti razred kot `0005_kvizi` —,
    vse ostalo pa mora ostati nedotaknjeno. Vrnitev čezenj je s tem varna za
    bazo, ki urnika še ni dobila, in nepovratna za tisto, ki ga je.
    """
    config = alembic_nastavitve(baza)
    _polna_baza_pred_druzinami(baza, slike)
    command.upgrade(config, "head")

    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            povezava.execute(
                text(
                    "INSERT INTO schedules "
                    "(id, family_id, child_id, confirmed_at, replaced_at, image_path) "
                    "VALUES ('u1', :druzina, :otrok, '2026-09-07 08:00:00', NULL, NULL)"
                ),
                {"druzina": CVEK_ID, "otrok": MASA_ID},
            )
            povezava.execute(
                text(
                    "INSERT INTO schedule_entries "
                    "(id, schedule_id, weekday, subject, skip_photo) "
                    "VALUES ('v1', 'u1', 0, 'MAT', 0)"
                )
            )

        prej = _stej(motor)

        command.downgrade(config, "0009_otrok_na_zapisu")

        tabele = set(inspect(motor).get_table_names())
        assert "schedules" not in tabele
        assert "schedule_entries" not in tabele
        assert _stej(motor) == prej, "razveljavitev urnika ne sme vzeti ničesar s sabo"
    finally:
        motor.dispose()


# --- Stanje družine (V3-R05, `0011_stanje_druzine`) ---


def test_obstojece_druzine_ostanejo_aktivne(baza: str, slike: Path) -> None:
    """`0011_stanje_druzine` doda stolpec in nobene vrstice ne premakne.

    Preverja prav to, kar migracija **trdi** o sebi: obstoječe družine so po
    njej aktivne in vsebina baze je enaka. Zgolj obstoj stolpca pove že
    varovalo `test_migrirana_shema_se_ujema_z_modeli`.
    """
    config = alembic_nastavitve(baza)
    _polna_baza_pred_druzinami(baza, slike)
    command.upgrade(config, "0010_urnik")

    motor = create_engine(baza)
    try:
        prej = _stej(motor)
        assert prej["materials"] >= 1, "test mora teči nad polno bazo"

        command.upgrade(config, "0011_stanje_druzine")

        assert _vrstice(motor, "SELECT DISTINCT is_active FROM families") == [(1,)]
        assert _stej(motor) == prej, "stanje družine ne sme premakniti nobene vrstice"
    finally:
        motor.dispose()


def test_razveljavitev_stanja_druzine_ohrani_podatke(baza: str, slike: Path) -> None:
    """`downgrade` spusti stolpec in nič drugega.

    Podatek o tem, katera družina je bila ugasnjena, se pri tem izgubi
    dokončno — isti razred kot `0004_upokojena_vprasanja` —, vse ostalo pa
    mora ostati nedotaknjeno. Test ugasne družino prav zato, da bi ga
    razveljavitev, ki bi vrstico vzela s sabo, ne odnesla neopaženo.
    """
    config = alembic_nastavitve(baza)
    _polna_baza_pred_druzinami(baza, slike)
    command.upgrade(config, "head")

    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            povezava.execute(
                text("UPDATE families SET is_active = 0 WHERE id = :druzina"),
                {"druzina": CVEK_ID},
            )
        prej = _stej(motor)

        command.downgrade(config, "0010_urnik")

        stolpci = {stolpec["name"] for stolpec in inspect(motor).get_columns("families")}
        assert "is_active" not in stolpci
        assert _stej(motor) == prej, "razveljavitev ne sme vzeti nobene vrstice s sabo"
    finally:
        motor.dispose()


# --- Google poverilnica (V3-R08, `0012_google_poverilnica`) ---


def test_obstojece_poverilnice_prezivijo_google(baza: str, slike: Path) -> None:
    """`0012_google_poverilnica` doda stolpec in nobene vrstice ne premakne.

    Kriterij `V3-R08` zahteva več kot to: **`users` in `sessions` se ne smeta
    dotakniti.** Če bi se, bi bil `ADR-027` („Google je nova vrstica, ne nova
    shema") ovržen in zahteva bi se ustavila. Zato test primerja shemi obeh
    tabel pred migracijo in po njej, ne le števila vrstic.
    """
    config = alembic_nastavitve(baza)
    _polna_baza_pred_druzinami(baza, slike)
    command.upgrade(config, "0011_stanje_druzine")

    motor = create_engine(baza)
    try:
        prej = _stej(motor)
        poverilnic = _vrstice(motor, "SELECT count(*) FROM credentials")[0][0]
        assert poverilnic >= 1, "test mora teči nad bazo s poverilnicami"
        uporabniki_prej = {s["name"] for s in inspect(motor).get_columns("users")}
        seje_prej = {s["name"] for s in inspect(motor).get_columns("sessions")}

        command.upgrade(config, "0012_google_poverilnica")

        pregled = inspect(motor)
        assert {s["name"] for s in pregled.get_columns("users")} == uporabniki_prej
        assert {s["name"] for s in pregled.get_columns("sessions")} == seje_prej
        assert "label" in {s["name"] for s in pregled.get_columns("credentials")}
        assert _stej(motor) == prej, "google poverilnica ne sme premakniti nobene vrstice"
        assert _vrstice(motor, "SELECT count(*) FROM credentials")[0][0] == poverilnic
        # Geselne poverilnice oznake nimajo in je ne potrebujejo.
        assert _vrstice(motor, "SELECT DISTINCT label FROM credentials") == [(None,)]
    finally:
        motor.dispose()


def test_razveljavitev_google_ohrani_prijavo(baza: str, slike: Path) -> None:
    """`downgrade` spusti `label` in **nobene poverilnice ne odnese**.

    To je najblažja razveljavitev v tem projektu: `identifier` (Googlov `sub`),
    po katerem prijava dejansko teče, je v drugem stolpcu in ostane. Izgubi se
    samo berljiv izpis v nastavitvah.
    """
    config = alembic_nastavitve(baza)
    _polna_baza_pred_druzinami(baza, slike)
    command.upgrade(config, "head")

    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            uporabnik = povezava.execute(text("SELECT id FROM users LIMIT 1")).scalar_one()
            povezava.execute(
                text(
                    "INSERT INTO credentials "
                    "(id, user_id, kind, identifier, secret_hash, label, created_at, updated_at) "
                    "VALUES ('g1', :u, 'google', 'sub-104829', NULL, 'ana@primer.test', "
                    "'2026-09-21 10:00:00', '2026-09-21 10:00:00')"
                ),
                {"u": uporabnik},
            )
        prej = _stej(motor)
        poverilnic = _vrstice(motor, "SELECT count(*) FROM credentials")[0][0]

        command.downgrade(config, "0011_stanje_druzine")

        stolpci = {stolpec["name"] for stolpec in inspect(motor).get_columns("credentials")}
        assert "label" not in stolpci
        assert _stej(motor) == prej
        assert _vrstice(motor, "SELECT count(*) FROM credentials")[0][0] == poverilnic, (
            "razveljavitev ne sme vzeti nobene poverilnice s sabo"
        )
        assert _vrstice(motor, "SELECT identifier FROM credentials WHERE id = 'g1'") == [
            ("sub-104829",)
        ]
    finally:
        motor.dispose()


# --- Shranjeni preizkusi (V4-R08, `0013_preizkusi`) ---


def test_obstojeci_zapisi_prezivijo_preizkuse(baza: str, slike: Path) -> None:
    """`0013_preizkusi` je gol `CREATE TABLE` in se obstoječih vrstic ne dotakne.

    Preverja prav to, kar migracija **trdi** o sebi (kriterij `V4-R08`:
    „migracija samo doda tabelo"). Baza je polna že pred njo.
    """
    config = alembic_nastavitve(baza)
    _polna_baza_pred_druzinami(baza, slike)
    command.upgrade(config, "0012_google_poverilnica")

    motor = create_engine(baza)
    try:
        prej = _stej(motor)
        tabele_prej = set(inspect(motor).get_table_names())
        assert prej["materials"] >= 1, "test mora teči nad polno bazo"

        command.upgrade(config, "0013_preizkusi")

        assert set(inspect(motor).get_table_names()) - tabele_prej == {"preizkusi"}
        assert _stej(motor) == prej, "preizkusi ne smejo premakniti nobene obstoječe vrstice"
    finally:
        motor.dispose()


def test_razveljavitev_preizkusov_ohrani_ostalo(baza: str, slike: Path) -> None:
    """`downgrade` spusti tabelo in nič drugega.

    Shranjeni preizkusi se pri tem izgubijo dokončno — isti razred kot
    `0005_kvizi` in `0010_urnik` —, vse ostalo ostane nedotaknjeno.
    """
    config = alembic_nastavitve(baza)
    _polna_baza_pred_druzinami(baza, slike)
    command.upgrade(config, "head")

    motor = create_engine(baza)
    try:
        with motor.begin() as povezava:
            povezava.execute(
                text(
                    "INSERT INTO preizkusi "
                    "(id, family_id, child_id, subject, title, test_md, solutions_md, "
                    "source_md, model, saved_at, saved_by, base_id) "
                    "VALUES ('p1', :druzina, :otrok, 'MAT', 'T', '# T', '', 'snov', 'm', "
                    "'2026-10-10 08:00:00', :otrok, NULL)"
                ),
                {"druzina": CVEK_ID, "otrok": MASA_ID},
            )
        prej = _stej(motor)

        command.downgrade(config, "0012_google_poverilnica")

        assert "preizkusi" not in set(inspect(motor).get_table_names())
        assert _stej(motor) == prej, "razveljavitev preizkusov ne sme vzeti ničesar s sabo"
    finally:
        motor.dispose()
