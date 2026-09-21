"""Nastavitve morajo napačno konfiguracijo ujeti ob zagonu, ne ob prvi zahtevi.

Od V3-R04 tu ni več nobenega polja brez privzetka: `API_KEY` je odpadel
(`docs/odlocitve/ADR-036`), dostop pa odloča seja v bazi. Testi zato dokazujejo
dvoje — da se strežnik zažene brez vsakega okolja in da nobena nastavitev ne
pride iz datoteke, ki je odvisna od trenutne delovne mape.
"""

from pathlib import Path

import pytest

from app.settings import Settings


def test_streznik_se_zazene_brez_vsakega_okolja(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nobeno polje ni obvezno.

    Ključ je bil edino tako polje in ga ni več. Če kdaj spet nastane
    nastavitev brez privzetka, mora to biti zavestna odločitev z ADR — ta test
    tedaj pade in vpraša.
    """
    for ime in ("DATABASE_URL", "IMAGES_DIR", "OPENAI_API_KEY", "OPENAI_MODEL"):
        monkeypatch.delenv(ime, raising=False)

    nastavitve = Settings()

    assert nastavitve.database_url.startswith("postgresql+psycopg://")
    assert nastavitve.images_dir.name == "images"


def test_api_kljuca_ni_vec(monkeypatch: pytest.MonkeyPatch) -> None:
    """`API_KEY` v okolju ne sme oživeti nobene poti.

    `model_config` ima `extra="ignore"`, zato star `.env` z vrstico `API_KEY=`
    strežnika ne ustavi — in tudi ne naredi ničesar. To je namen: nadgradnja
    ne zahteva, da lastnik `.env` počisti prej kot ob priložnosti.
    """
    monkeypatch.setenv("API_KEY", "star-kljuc-ki-ne-velja-vec")

    nastavitve = Settings()

    assert not hasattr(nastavitve, "api_key")


def test_nastavitve_ne_berejo_datoteke_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Izid ne sme biti odvisen od tega, od kod je ukaz pognan.

    `env_file` je relativen na trenutno delovno mapo, ne na paket. Če bi ga
    `Settings` brala, bi bil ta test zelen ali rdeč glede na to, ali je lastnik
    že naredil `apps/server/.env` po `okolje.primer` — in `pytest` iz korena bi
    se obnašal drugače kot `pytest` iz `apps/server`.

    Test dela v začasni mapi, da ne more povoziti prave `.env`.
    """
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENAI_MODEL=iz-datoteke\n", encoding="utf-8")

    assert Settings().openai_model == "gpt-4.1"


def test_openai_kljuc_ni_pogoj_za_zagon() -> None:
    """Odsotnost tega ključa strežnika ne ustavi.

    Ustavi samo obdelavo — slike ostanejo `new`, dokler ključa ni
    (`docs/odlocitve/ADR-009`). Če bi kdo temu polju dal `min_length`, bi se
    strežnik nehal zaganjati brez ključa za OpenAI, in prevzem slik s telefona
    bi padel skupaj z obdelavo.
    """
    assert Settings().openai_api_key == ""


def test_privzetki_obdelave() -> None:
    """ADR-008: ime modela je nastavitev, ne konstanta v kodi."""
    nastavitve = Settings()

    assert nastavitve.openai_model == "gpt-4.1"
    assert nastavitve.openai_timeout_seconds == 120.0
    assert nastavitve.worker_interval_seconds == 30.0


def test_ime_modela_pride_iz_okolja(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zamenjava modela mora biti sprememba spremenljivke okolja (ADR-008)."""
    monkeypatch.setenv("OPENAI_MODEL", "nekaj-novejsega")

    assert Settings().openai_model == "nekaj-novejsega"


# --- Google (V3-R08) -------------------------------------------------------


def test_google_pride_iz_okolja(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skrivnost odjemalca pride iz okolja in nikoli iz repozitorija."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "odjemalec-1")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "skrivnost-1")
    monkeypatch.setenv("DOMENA", "solski.test")

    nastavitve = Settings()

    assert nastavitve.google_je_nastavljen
    assert nastavitve.google_client_secret == "skrivnost-1"


def test_brez_googla_se_streznik_vseeno_zazene() -> None:
    """Manjkajoča nastavitev ustavi eno zmožnost, ne strežnika (`ADR-046` F).

    Ista drža kot pri `OPENAI_API_KEY` (`ADR-009`): namestitev, ki Googla ne
    omenja, ga nima — brez posebnega koraka in brez napake ob zagonu.
    """
    nastavitve = Settings(database_url="sqlite://")

    assert nastavitve.google_client_id == ""
    assert nastavitve.google_client_secret == ""
    assert not nastavitve.google_je_nastavljen


def test_skrivnosti_odjemalca_ni_v_repozitoriju() -> None:
    """`okolje.primer` nosi imeni brez vrednosti, kot vse druge skrivnosti.

    Isti razred varovala kot pri zgostitvi gesla v `test_postavitev.py`: da
    skrivnosti v repozitoriju ni, mora biti preverjeno, ne le dogovorjeno
    (`CLAUDE.md`, trdi rob 6).
    """
    predloga = Path(__file__).resolve().parents[1] / "okolje.primer"
    besedilo = predloga.read_text(encoding="utf-8")

    assert "GOOGLE_CLIENT_SECRET=\n" in besedilo
    assert "GOOGLE_CLIENT_ID=\n" in besedilo
