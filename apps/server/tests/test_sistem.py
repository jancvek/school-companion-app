"""Lastnik sistema odpira in ureja družine (V3-R05).

Pokriva tabelo „Test casi" iz `docs/plan/V3-R05.md`; odločitve so v
`docs/odlocitve/ADR-044`, pravila v `app/sistem.py` in `app/clani.py`.

Kaj je **drugje** in se tu ne ponavlja:

- da za starša te strani ni, dokaže `test_dostop_starsa_ni_mogoc` tu (ker se
  generira iz poti aplikacije), **in** `tests/test_tesnjenje.py` z dvema
  resničnima družinama in s posnetkom stanja pred in po;
- da lastnik ne vidi vsebine tujih družin, dokaže `test_tesnjenje.py` s
  sledmi snovi, kvizov in vprašanj;
- da obstoječe družine po migraciji ostanejo aktivne, dokaže
  `tests/test_migracija.py`.

Vsak test, ki pravi „prijava deluje" ali „prijava ne deluje", gre skozi
**pravo prijavno pot** — v brskalniku ali na telefonu. Zgostitev, ki se ujema
sama s sabo, in zastavica, ki jo prebere test, ne dokažeta ničesar o tem, ali
se da priti v aplikacijo.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from app import clani, prijava, sistem
from app.models import (
    STATUS_NOV,
    STATUS_V_OBDELAVI,
    Base,
    Family,
    Material,
    User,
    UserSession,
)
from app.obdelava import obdelaj_cakajoce
from app.routers.sistem import SPOROCILO_NI_STARSA
from app.worker import obnovi_obticale
from tests.conftest import (
    CVEK_ID,
    GESLO_STARSA,
    STARS_IDENTIFIKATOR,
    PrijavljenOdjemalec,
    prijavi,
    ustvari_otroka,
    ustvari_sejo,
    ustvari_starsa,
)
from tests.test_druzine import DRUGA_ID, dodaj_druzino, snov_druzine
from tests.test_obdelava import klicalec_vrne, uspesen_izid
from tests.test_prijava import prijavi_se

POT = "/admin/system"

#: Snov tuje družine, s katero se preverja, da deaktivacija ne izgubi ničesar
#: in da obdelava miruje. Kanoničen UUID, ker iz njega nastane ime slike.
UUID_SNOVI = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"

LASTNIK_IDENTIFIKATOR = "lastnik@primer.test"
GESLO_LASTNIKA = "geslo-lastnika-12"

#: Vnos, ki ga obrazec sprejme, kadar test ne preizkuša prav vnosa.
NOVA_DRUZINA = {
    "ime_druzine": "Novak",
    "ime": "Ana Novak",
    "enaslov": "ana@novak.test",
    "geslo": "anino-geslo-12",
    "geslo_znova": "anino-geslo-12",
}


@pytest.fixture
def lastnik(motor: Engine) -> str:
    """Lastnik sistema — starš družine Cvek z zastavico `is_system_owner`.

    Svoj račun in ne `stars`: privzeti starš je navaden starš in prav ta
    razlika je tu ves čas na preizkusu.
    """
    return ustvari_starsa(
        motor,
        identifikator=LASTNIK_IDENTIFIKATOR,
        geslo=GESLO_LASTNIKA,
        prikazno_ime="Lastnik",
        lastnik_sistema=True,
    )


@pytest.fixture
def lastnikov_odjemalec(
    aplikacija: FastAPI, motor: Engine, lastnik: str
) -> Iterator[PrijavljenOdjemalec]:
    """Odjemalec s sejo lastnika sistema."""
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
        prijavi(odjemalec, motor, lastnik)
        yield odjemalec


def druzine(motor: Engine) -> list[Family]:
    """Vse družine, prebrane mimo repozitorija."""
    with Session(motor) as seja:
        return list(seja.scalars(select(Family).order_by(Family.name)))


def sej_uporabnika(motor: Engine, user_id: str) -> int:
    with Session(motor) as seja:
        return len(list(seja.scalars(select(UserSession).where(UserSession.user_id == user_id))))


# --- Kdo sploh pride do strani ---------------------------------------------


@pytest.mark.parametrize(
    ("pot", "skrita"),
    [
        ("/admin/system", True),
        ("/admin/system/", True),
        ("/admin/system/families", True),
        ("/admin/system/families/abc/parents/def/password", True),
        # Pot s podobnim imenom ni pod predpono. Golo `startswith` bi jo zajelo
        # in bi bilo videti pravilno do dneva, ko taka pot nastane — ista past
        # kot pri `security.je_izvzeta` (odločitev 6 v `docs/plan/V1-R04.md`).
        ("/admin/systematic", False),
        ("/admin/system-x", False),
        ("/admin", False),
        ("/admin/family", False),
        ("/system", False),
    ],
)
def test_je_skrita_pot(pot: str, skrita: bool) -> None:
    """Ujemanje predpone: sama pot in to, kar ji sledi za poševnico.

    Test enote in ne čez HTTP: `/admin/systematic` ne obstaja, zato se razlika
    med pravilnim ujemanjem in golim `startswith` v odgovoru strežnika ne vidi
    — pokazala bi se šele, ko bi taka pot nastala, in takrat bi bila skrita po
    nesreči.
    """
    assert sistem.je_skrita_pot(pot) is skrita


def _primeri_poti(aplikacija: FastAPI) -> list[tuple[str, str]]:
    """Vsaka pot pod `/admin/system`, z izmišljenimi, a veljavnimi vrednostmi.

    Generira se **iz poti aplikacije** in ne našteva ročno: nova pot, ki bi jo
    kdo dodal brez zavrnitve, mora pasti tu, ne v produkciji (`ADR-044` G).
    """
    return [
        (
            metoda.upper(),
            pot.replace("{family_id}", DRUGA_ID).replace("{user_id}", "kdorkoli"),
        )
        for pot, metode in aplikacija.openapi()["paths"].items()
        for metoda in metode
        if pot.startswith(POT)
    ]


def test_pod_predpono_je_vec_poti(aplikacija: FastAPI) -> None:
    """Varovalo: če se predpona kdaj preimenuje, test spodaj ne sme biti prazen."""
    assert len(_primeri_poti(aplikacija)) >= 8


def test_dostop_starsa_ni_mogoc(
    aplikacija: FastAPI, odjemalec: PrijavljenOdjemalec, motor: Engine
) -> None:
    """Za navadnega starša nobena pot te strani ne obstaja: **404, ne 403**.

    403 bi povedal, da stran obstaja in da ni zanj; kriterij `V3-R05` zahteva,
    da zanj ne obstaja. Besedilo mora biti isto kot za resnično neobstoječo
    pot, sicer je razlika sama podatek.
    """
    dodaj_druzino(motor)

    for metoda, pot in _primeri_poti(aplikacija):
        odgovor = (
            odjemalec.get(pot) if metoda == "GET" else odjemalec.post(pot, data={})
        )
        assert odgovor.status_code == 404, f"{metoda} {pot}"
        assert "Te strani na strežniku ni." in odgovor.text, f"{metoda} {pot}"


def _napacne_metode(aplikacija: FastAPI) -> list[tuple[str, str]]:
    """Vsaka pot pod predpono in **metoda, ki je ta pot nima**.

    Generira se iz `openapi()`, enako kot `_primeri_poti`, ker gre za isto
    vprašanje z druge strani: tam „ali obstoječa kombinacija izda stran",
    tu „ali jo izda neobstoječa kombinacija". Naštet seznam bi zastaral pri
    prvi novi poti.
    """
    return [
        (metoda, pot.replace("{family_id}", DRUGA_ID).replace("{user_id}", "kdorkoli"))
        for pot, metode in aplikacija.openapi()["paths"].items()
        for metoda in ("GET", "POST")
        if pot.startswith(POT) and metoda.lower() not in metode
    ]


def test_obstajajo_poti_z_eno_samo_metodo(aplikacija: FastAPI) -> None:
    """Varovalo: če bi vsaka pot imela obe metodi, bi bil test spodaj prazen.

    Danes sta taki dve: `/admin/system` in stran ene družine, obe samo `GET`.
    """
    assert len(_napacne_metode(aplikacija)) >= 2


def test_starsu_je_napacna_metoda_videti_kot_neobstojeca_pot(
    aplikacija: FastAPI, odjemalec: PrijavljenOdjemalec
) -> None:
    """Napačna metoda ne sme izdati, da pot obstaja — **404, ne 405**.

    Starlette ob ujemanju poti in neujemanju metode odgovori `405`, še preden
    steče odvisnost `zahtevaj_lastnika_sistema`; razlika med `405` in `404` je
    sama po sebi podatek, da pot obstaja. Kriterij `V3-R05` pravi, da za
    starša ta stran ne obstaja, zato mora biti odgovor **enak** kot za
    izmišljen naslov — koda, telo in glave.

    Test pomete čez vse kombinacije in ne čez eno pot: prvi popravek je zaprl
    samo smer `GET` na pot, ki obstaja kot `POST`, medtem ko sta `POST` na
    `/admin/system` in na stran družine še vedno vrnila `405` (drugi pregled).
    """
    izmisljena = odjemalec.get(f"{POT}/izmisljena-pot", follow_redirects=False)
    assert izmisljena.status_code == 404

    for metoda, pot in _napacne_metode(aplikacija):
        # Žeton mora biti veljaven: brez njega bi `SejaMiddleware` odgovoril s
        # `403` še pred usmerjanjem in test bi bil zelen, ne da bi karkoli
        # povedal o tem, kaj pot razkrije.
        telo = {"csrf": odjemalec.csrf} if metoda == "POST" else None
        odgovor = odjemalec.request(metoda, pot, data=telo, follow_redirects=False)

        assert odgovor.status_code == 404, f"{metoda} {pot}"
        assert odgovor.text == izmisljena.text, f"{metoda} {pot}"
        assert "allow" not in odgovor.headers, (
            f"{metoda} {pot}: glava Allow pove, katere metode pot sprejema"
        )


def test_zunaj_predpone_napacna_metoda_ostane_405(
    odjemalec: PrijavljenOdjemalec,
) -> None:
    """Drugod pod `/admin` ostane `405`, ker tam obstoj poti ni skrivnost.

    Trditev je o meji popravka: skrivanje velja za eno predpono in ni tiho
    spremenilo vedenja vseh poti pod `/admin` (`ADR-044` G).
    """
    odgovor = odjemalec.get("/admin/logout", follow_redirects=False)

    assert odgovor.status_code == 405


def test_starsu_je_pot_samo_s_postom_videti_kot_neobstojeca(
    odjemalec: PrijavljenOdjemalec,
) -> None:
    """Ista trditev za `GET` na pot, ki obstaja samo kot `POST`.

    Posebej in ne samo v generiranem testu zgoraj: `/admin/system/families`
    ima **registriran** `GET`, ki lastnika pelje na seznam, zato je v
    generiranem seznamu ni — in prav ta pot je bila prvi najdeni uhajalec.
    """
    obstojeca = odjemalec.get(f"{POT}/families", follow_redirects=False)
    izmisljena = odjemalec.get(f"{POT}/izmisljena-pot", follow_redirects=False)

    assert obstojeca.status_code == izmisljena.status_code == 404
    assert obstojeca.text == izmisljena.text


def test_lastniku_get_na_families_pelje_na_seznam(
    lastnikov_odjemalec: PrijavljenOdjemalec,
) -> None:
    """Za lastnika ista pot ni slepa ulica — pelje na seznam družin."""
    odgovor = lastnikov_odjemalec.get(f"{POT}/families", follow_redirects=False)

    assert odgovor.status_code == 303
    assert odgovor.headers["location"] == POT


def test_lastnik_pride_na_stran(lastnikov_odjemalec: PrijavljenOdjemalec) -> None:
    """Test zgoraj ni prazen: ista pot je za lastnika sistema 200."""
    odgovor = lastnikov_odjemalec.get(POT)

    assert odgovor.status_code == 200
    assert "Družine" in odgovor.text


def test_povezave_na_sistem_stars_ne_vidi(
    odjemalec: PrijavljenOdjemalec, lastnikov_odjemalec: PrijavljenOdjemalec
) -> None:
    """Povezava na `/admin` je samo za lastnika — povabilo v 404 ni vljudno."""
    assert POT not in odjemalec.get("/admin").text
    assert POT in lastnikov_odjemalec.get("/admin").text


# --- Seznam družin ---------------------------------------------------------


def test_seznam_pokaze_druzine_s_stevili(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine
) -> None:
    """Ime, števila članov, datum in stanje — in nič drugega (`ADR-044` B)."""
    dodaj_druzino(motor)

    besedilo = lastnikov_odjemalec.get(POT).text

    assert "Cvek" in besedilo
    assert "Druga" in besedilo
    assert "1 starš" in besedilo
    assert "1 otrok" in besedilo
    assert "aktivna" in besedilo


def test_besedilo_o_vision_api_ju_je_ob_obrazcu(
    lastnikov_odjemalec: PrijavljenOdjemalec,
) -> None:
    """Kriterij 7: lastnik ima besedilo pripravljeno tam, kjer ga potrebuje.

    Trditev velja o konstanti in ne o zapisu HTML — prav zato besedilo živi v
    `app/sistem.py` (`ADR-044` C).
    """
    besedilo = lastnikov_odjemalec.get(POT).text

    assert "OpenAI" in sistem.BESEDILO_ZASEBNOST
    for vrstica in sistem.BESEDILO_ZASEBNOST.split("\n\n"):
        assert vrstica.strip()[:40] in besedilo


# --- Odpiranje nove družine ------------------------------------------------


def test_odpre_druzino_in_prvega_starsa(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine, aplikacija: FastAPI
) -> None:
    """Družina in starš nastaneta; starš se **prijavi skozi pravo pot**."""
    odgovor = lastnikov_odjemalec.post(
        POT + "/families", data=NOVA_DRUZINA, follow_redirects=False
    )

    assert odgovor.status_code == 303
    imena = [druzina.name for druzina in druzine(motor)]
    assert imena == ["Cvek", "Novak"]

    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brskalnik:
        prijava_starsa = prijavi_se(brskalnik, "ana@novak.test", "anino-geslo-12")
    assert prijava_starsa.status_code == 303


def test_novi_stars_ni_lastnik_sistema(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine
) -> None:
    """Zastavice ne podeli nobena pot, niti ta (`ADR-038` G)."""
    lastnikov_odjemalec.post(POT + "/families", data=NOVA_DRUZINA)

    with Session(motor) as seja:
        novi = seja.scalars(select(User).where(User.display_name == "Ana Novak")).one()
        assert novi.is_system_owner is False
        assert novi.is_active is True
        assert novi.role == "parent"


def test_nova_druzina_je_prizgana(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine
) -> None:
    """Družina, ki bi nastala ugasnjena, bi bila past za lastnika in za starša."""
    lastnikov_odjemalec.post(POT + "/families", data=NOVA_DRUZINA)

    nova = next(druzina for druzina in druzine(motor) if druzina.name == "Novak")
    assert nova.is_active is True


def test_enaslov_normaliziran(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine, aplikacija: FastAPI
) -> None:
    """Velike črke in robovi se poravnajo, kot povsod (`ADR-038` E)."""
    lastnikov_odjemalec.post(
        POT + "/families", data={**NOVA_DRUZINA, "enaslov": "  Ana@Novak.TEST  "}
    )

    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brskalnik:
        assert prijavi_se(brskalnik, "ana@novak.test", "anino-geslo-12").status_code == 303


@pytest.mark.parametrize(
    ("polje", "vrednost", "del_sporocila"),
    [
        ("ime_druzine", "   ", "Ime družine manjka"),
        ("ime_druzine", "x" * 201, "predolgo"),
        ("ime", "", "Prikazno ime manjka"),
        ("enaslov", "ni-enaslov", "ni videti kot e-naslov"),
        ("geslo", "kratko", "prekratko"),
    ],
)
def test_neveljaven_vnos_ne_ustvari_nicesar(
    lastnikov_odjemalec: PrijavljenOdjemalec,
    motor: Engine,
    polje: str,
    vrednost: str,
    del_sporocila: str,
) -> None:
    """400 s slovenskim sporočilom in **brez** polovične družine.

    Prekratko geslo je tu s praznim `geslo_znova` neujemanje ne bi dokazalo:
    zavrniti ga mora dolžina, sicer bi pravilo lahko izginilo neopazno.
    """
    podatki = {**NOVA_DRUZINA, polje: vrednost}
    if polje == "geslo":
        podatki["geslo_znova"] = vrednost

    odgovor = lastnikov_odjemalec.post(POT + "/families", data=podatki)

    assert odgovor.status_code == 400
    assert del_sporocila in odgovor.text
    assert [druzina.name for druzina in druzine(motor)] == ["Cvek"]


def test_gesli_se_ne_ujemata(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine
) -> None:
    odgovor = lastnikov_odjemalec.post(
        POT + "/families", data={**NOVA_DRUZINA, "geslo_znova": "drugo-geslo-12"}
    )

    assert odgovor.status_code == 400
    assert clani.SPOROCILO_GESLI_SE_NE_UJEMATA in odgovor.text
    assert [druzina.name for druzina in druzine(motor)] == ["Cvek"]


def test_zaseden_enaslov_ne_pusti_prazne_druzine(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
) -> None:
    """Enoličnost razsodi baza, družina pa ne sme ostati za sabo.

    To je edini razlog, da sta družina in starš **ena transakcija**: brez nje
    bi zaseden e-naslov pustil prazno družino, ki bi jo moral nekdo pospraviti.
    """
    odgovor = lastnikov_odjemalec.post(
        POT + "/families", data={**NOVA_DRUZINA, "enaslov": STARS_IDENTIFIKATOR}
    )

    assert odgovor.status_code == 400
    assert clani.SPOROCILO_IDENTIFIKATOR_ZASEDEN in odgovor.text
    assert [druzina.name for druzina in druzine(motor)] == ["Cvek"]


def test_geslo_se_ob_napaki_ne_vrne_v_izris(
    lastnikov_odjemalec: PrijavljenOdjemalec,
) -> None:
    """Ime se vrne, geslo nikoli — ne v polju in ne v skritem polju."""
    odgovor = lastnikov_odjemalec.post(
        POT + "/families", data={**NOVA_DRUZINA, "ime_druzine": ""}
    )

    assert "Ana Novak" in odgovor.text
    assert "anino-geslo-12" not in odgovor.text


# --- Stanje družine --------------------------------------------------------


def test_deaktivacija_ustavi_prijavo_starsa_in_otroka(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine, aplikacija: FastAPI
) -> None:
    """Nihče iz ugasnjene družine ne pride noter — ne v brskalnik, ne na telefon.

    Sporočilo je isto kot pri vsaki drugi neuspeli prijavi: da je družina
    ugasnjena, ni podatek, ki bi ga smel dobiti kdorkoli, ki ugiba
    (`ADR-044` A).
    """
    dodaj_druzino(motor, z_otrokom=False)
    ustvari_starsa(
        motor, family_id=DRUGA_ID, identifikator="drugi@primer.test", prikazno_ime="Drugi"
    )
    ustvari_otroka(motor, user_id=None, family_id=DRUGA_ID, identifikator="drugiotrok")

    lastnikov_odjemalec.post(f"{POT}/families/{DRUGA_ID}/deactivate")

    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brskalnik:
        zavrnjen = prijavi_se(brskalnik, "drugi@primer.test", GESLO_STARSA)
    assert zavrnjen.status_code == 401
    assert prijava.SPOROCILO_NEUSPELA_PRIJAVA in zavrnjen.text

    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as telefon:
        na_telefonu = telefon.post(
            "/auth/login", json={"identifier": "drugiotrok", "password": "geslo-otroka"}
        )
    assert na_telefonu.status_code == 401


def test_deaktivacija_pobrise_seje_clanov(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine
) -> None:
    """Seje padejo takoj, na vseh napravah — kot pri deaktivaciji osebe."""
    dodaj_druzino(motor, z_otrokom=False)
    drugi = ustvari_starsa(
        motor, family_id=DRUGA_ID, identifikator="drugi@primer.test", prikazno_ime="Drugi"
    )
    ustvari_sejo(motor, drugi)
    assert sej_uporabnika(motor, drugi) == 1

    lastnikov_odjemalec.post(f"{POT}/families/{DRUGA_ID}/deactivate")

    assert sej_uporabnika(motor, drugi) == 0


def test_seja_pade_tudi_sredi_dela(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine, aplikacija: FastAPI
) -> None:
    """Starš, ki je bil prijavljen, ob naslednji zahtevi pristane na prijavi.

    Prva plast je izbris sej, ta test pa je o drugi: tudi seja, ki bi izbris
    kako preživela, ne sme več veljati (`prijava.seja_za_zeton`).
    """
    dodaj_druzino(motor, z_otrokom=False)
    drugi = ustvari_starsa(
        motor, family_id=DRUGA_ID, identifikator="drugi@primer.test", prikazno_ime="Drugi"
    )

    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brskalnik:
        prijavi(brskalnik, motor, drugi)
        assert brskalnik.get("/admin").status_code == 200

        lastnikov_odjemalec.post(f"{POT}/families/{DRUGA_ID}/deactivate")

        odgovor = brskalnik.get("/admin", follow_redirects=False)
        assert odgovor.status_code == 303
        assert prijava.POT_PRIJAVE in odgovor.headers["location"]


def test_seja_nastala_po_ugasnitvi_ne_velja(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine, aplikacija: FastAPI
) -> None:
    """Druga plast: seja, ki izbrisu uide, vseeno ne velja.

    Izbris sej ob deaktivaciji je **prva** plast in test zgoraj preverja njo.
    Ta test naredi sejo **po** ugasnitvi — kar je stanje, ki v resnici nastane
    ob tekmi med deaktivacijo in prijavo, ki teče isti hip — in trdi, da je
    tudi taka seja brez veljave (`prijava.seja_za_zeton`, `ADR-044` A).

    Brez te trditve bi preverbo v `seja_za_zeton` lahko kdo odstranil in
    nobenemu testu ne bi bilo nič: prva plast bi vse pokrila.
    """
    dodaj_druzino(motor, z_otrokom=False)
    drugi = ustvari_starsa(
        motor, family_id=DRUGA_ID, identifikator="drugi@primer.test", prikazno_ime="Drugi"
    )
    lastnikov_odjemalec.post(f"{POT}/families/{DRUGA_ID}/deactivate")

    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brskalnik:
        prijavi(brskalnik, motor, drugi)
        assert sej_uporabnika(motor, drugi) == 1

        odgovor = brskalnik.get("/admin", follow_redirects=False)

        assert odgovor.status_code == 303
        assert prijava.POT_PRIJAVE in odgovor.headers["location"]
    assert sej_uporabnika(motor, drugi) == 0, "neveljavna seja se ob naletu pobriše"


def test_deaktivacija_ne_izgubi_podatkov(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
) -> None:
    """„Deaktivirana družina ne izgubi podatkov" (kriterij 3).

    Šteje se **vse**, ne le tabela, na katero bi se spomnili: vsaka tabela
    modelov razen sej, ki so edina stvar, ki sme pasti.
    """
    dodaj_druzino(motor)
    snov_druzine(motor, slike, DRUGA_ID, UUID_SNOVI)
    prej = _posnetek(motor)

    lastnikov_odjemalec.post(f"{POT}/families/{DRUGA_ID}/deactivate")

    assert _posnetek(motor) == prej


def _posnetek(motor: Engine) -> dict[str, int]:
    """Število vrstic po tabelah, razen sej."""
    with Session(motor) as seja:
        return {
            ime: len(list(seja.execute(select(tabela))))
            for ime, tabela in Base.metadata.tables.items()
            if ime != "sessions"
        }


def test_aktivacija_vrne_stanje_pred_deaktivacijo(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine, aplikacija: FastAPI
) -> None:
    """Kdor je bil deaktiviran že prej, ostane deaktiviran (`ADR-044` A).

    To je razlika med zastavico na družini in prelivanjem na člane, in edini
    test, ki jo vidi. Brez njega bi obe izvedbi izgledali enako.
    """
    dodaj_druzino(motor, z_otrokom=False)
    aktivni = ustvari_starsa(
        motor, family_id=DRUGA_ID, identifikator="aktivni@primer.test", prikazno_ime="Aktivni"
    )
    ustvari_starsa(
        motor,
        family_id=DRUGA_ID,
        identifikator="ugasnjeni@primer.test",
        prikazno_ime="Ugasnjeni",
        aktiven=False,
    )
    assert aktivni

    lastnikov_odjemalec.post(f"{POT}/families/{DRUGA_ID}/deactivate")
    lastnikov_odjemalec.post(f"{POT}/families/{DRUGA_ID}/activate")

    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brskalnik:
        assert prijavi_se(brskalnik, "aktivni@primer.test", GESLO_STARSA).status_code == 303
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brskalnik:
        assert prijavi_se(brskalnik, "ugasnjeni@primer.test", GESLO_STARSA).status_code == 401


def test_svoje_druzine_ni_mogoce_deaktivirati(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine
) -> None:
    """403 in razlaga; družina ostane prižgana (`app/sistem.py`)."""
    odgovor = lastnikov_odjemalec.post(f"{POT}/families/{CVEK_ID}/deactivate")

    assert odgovor.status_code == 403
    assert sistem.SPOROCILO_SVOJE_DRUZINE in odgovor.text
    assert [d.is_active for d in druzine(motor) if d.id == CVEK_ID] == [True]


def test_svoje_druzine_seznam_sploh_ne_ponudi(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine
) -> None:
    """Odloči isto pravilo, ki dejanje tudi zavrne — dve bi se razšli."""
    dodaj_druzino(motor)

    besedilo = lastnikov_odjemalec.get(POT).text

    assert f"/families/{CVEK_ID}/deactivate" not in besedilo
    assert f"/families/{DRUGA_ID}/deactivate" in besedilo


def test_vmesna_stran_pred_deaktivacijo(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine
) -> None:
    """Klik na povezavo ne spremeni ničesar; spremeni šele `POST` s te strani."""
    dodaj_druzino(motor)

    odgovor = lastnikov_odjemalec.get(f"{POT}/families/{DRUGA_ID}/deactivate")

    assert odgovor.status_code == 200
    assert "Deaktivirati družino" in odgovor.text
    assert [d.is_active for d in druzine(motor) if d.id == DRUGA_ID] == [True]


def test_ze_deaktivirana_druzina(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine
) -> None:
    """409: stanje že je tako. Ni 403 — dejanje bi bilo tvoje, le odveč je."""
    dodaj_druzino(motor)
    lastnikov_odjemalec.post(f"{POT}/families/{DRUGA_ID}/deactivate")

    odgovor = lastnikov_odjemalec.post(f"{POT}/families/{DRUGA_ID}/deactivate")

    assert odgovor.status_code == 409
    assert sistem.SPOROCILO_ZE_UGASNJENA in odgovor.text


def test_ze_aktivna_druzina(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine
) -> None:
    dodaj_druzino(motor)

    odgovor = lastnikov_odjemalec.post(f"{POT}/families/{DRUGA_ID}/activate")

    assert odgovor.status_code == 409
    assert sistem.SPOROCILO_ZE_PRIZGANA in odgovor.text


@pytest.mark.parametrize(
    "pot",
    ["", "/deactivate", "/activate", "/parents/kdorkoli/password"],
)
def test_neznana_druzina_je_404(
    lastnikov_odjemalec: PrijavljenOdjemalec, pot: str
) -> None:
    """Tudi za lastnika: družine, ki je ni, ni."""
    odgovor = lastnikov_odjemalec.get(f"{POT}/families/00000000-0000-4000-8000-000000000000{pot}")

    assert odgovor.status_code == 404
    assert sistem.SPOROCILO_NI_DRUZINE in odgovor.text


# --- Starši tuje družine ---------------------------------------------------


def _druzina_z_dvema_starsema(motor: Engine) -> tuple[str, str]:
    """Tuja družina z dvema aktivnima staršema; vrne njuna `id`."""
    dodaj_druzino(motor, z_otrokom=False)
    prvi = ustvari_starsa(
        motor, family_id=DRUGA_ID, identifikator="prvi@primer.test", prikazno_ime="Prvi"
    )
    drugi = ustvari_starsa(
        motor, family_id=DRUGA_ID, identifikator="drugi@primer.test", prikazno_ime="Drugi"
    )
    return prvi, drugi


def test_stran_druzine_pokaze_starse_in_ne_otrok(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine
) -> None:
    """Starši poimensko, otroci samo kot število (`ADR-044` B)."""
    dodaj_druzino(motor, z_otrokom=False)
    ustvari_starsa(
        motor, family_id=DRUGA_ID, identifikator="prvi@primer.test", prikazno_ime="Prvi"
    )
    ustvari_otroka(
        motor,
        user_id=None,
        family_id=DRUGA_ID,
        identifikator="skritaotrok",
        prikazno_ime="Skriti otrok",
    )

    besedilo = lastnikov_odjemalec.get(f"{POT}/families/{DRUGA_ID}").text

    assert "Prvi" in besedilo
    assert "prvi@primer.test" in besedilo
    assert "Skriti otrok" not in besedilo
    assert "skritaotrok" not in besedilo
    assert "1 otrok" in besedilo


def test_ponastavitev_gesla_starsu(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine, aplikacija: FastAPI
) -> None:
    """Novo geslo dela, staro ne — oboje skozi pravo prijavno pot."""
    prvi, _ = _druzina_z_dvema_starsema(motor)
    ustvari_sejo(motor, prvi)

    odgovor = lastnikov_odjemalec.post(
        f"{POT}/families/{DRUGA_ID}/parents/{prvi}/password",
        data={"geslo": "novo-geslo-12", "geslo_znova": "novo-geslo-12"},
        follow_redirects=False,
    )

    assert odgovor.status_code == 303
    assert sej_uporabnika(motor, prvi) == 0
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brskalnik:
        assert prijavi_se(brskalnik, "prvi@primer.test", "novo-geslo-12").status_code == 303
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brskalnik:
        assert prijavi_se(brskalnik, "prvi@primer.test", GESLO_STARSA).status_code == 401


def test_prekratko_novo_geslo_starsa(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine, aplikacija: FastAPI
) -> None:
    """400, in staro geslo dela naprej — pol opravljene ponastavitve ni."""
    prvi, _ = _druzina_z_dvema_starsema(motor)

    odgovor = lastnikov_odjemalec.post(
        f"{POT}/families/{DRUGA_ID}/parents/{prvi}/password",
        data={"geslo": "kratko", "geslo_znova": "kratko"},
    )

    assert odgovor.status_code == 400
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brskalnik:
        assert prijavi_se(brskalnik, "prvi@primer.test", GESLO_STARSA).status_code == 303


def test_deaktivacija_starsa_tuje_druzine(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine, aplikacija: FastAPI
) -> None:
    """Starš se ne more več prijaviti; njegove seje padejo, drugi starš ostane."""
    prvi, drugi = _druzina_z_dvema_starsema(motor)
    ustvari_sejo(motor, prvi)

    odgovor = lastnikov_odjemalec.post(
        f"{POT}/families/{DRUGA_ID}/parents/{prvi}/deactivate", follow_redirects=False
    )

    assert odgovor.status_code == 303
    assert sej_uporabnika(motor, prvi) == 0
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brskalnik:
        assert prijavi_se(brskalnik, "prvi@primer.test", GESLO_STARSA).status_code == 401
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brskalnik:
        assert prijavi_se(brskalnik, "drugi@primer.test", GESLO_STARSA).status_code == 303
    assert drugi


def test_zadnjega_aktivnega_starsa_ni_mogoce_deaktivirati(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine
) -> None:
    """Pravilo iz `V3-R06`, ki je prav za tega klicatelja ostalo (`ADR-038`).

    Brez njega bi lastnik ugasnil edinega starša družine in pustil njene
    otroke brez nikogar, ki bi jim ponastavil geslo.
    """
    dodaj_druzino(motor, z_otrokom=False)
    sam = ustvari_starsa(
        motor, family_id=DRUGA_ID, identifikator="sam@primer.test", prikazno_ime="Sam"
    )

    odgovor = lastnikov_odjemalec.post(
        f"{POT}/families/{DRUGA_ID}/parents/{sam}/deactivate"
    )

    assert odgovor.status_code == 403
    assert clani.SPOROCILO_ZADNJI_STARS in odgovor.text
    with Session(motor) as seja:
        assert seja.get(User, sam).is_active is True  # type: ignore[union-attr]


def test_lastnika_sistema_ni_mogoce_deaktivirati(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine, lastnik: str, stars: str
) -> None:
    """Tudi on sam sebe ne — sicer se izklopi iz lastnega strežnika.

    V družini sta dva aktivna starša, zato pravilo o zadnjem staršu ne ugrizne
    in zadetek je res pravilo o lastniku sistema (`ADR-038` G).
    """
    assert stars

    odgovor = lastnikov_odjemalec.post(
        f"{POT}/families/{CVEK_ID}/parents/{lastnik}/deactivate"
    )

    assert odgovor.status_code == 403
    assert clani.SPOROCILO_LASTNIK_SISTEMA in odgovor.text


def test_aktivacija_starsa_odklene_druzino(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine, aplikacija: FastAPI
) -> None:
    """Edini starš družine je deaktiviran — brez lastnika ga ne vrne nihče.

    To je razlog, da aktivacija starša na tej strani obstaja (`ADR-044` F):
    po `V3-R06` ga aktivira drug starš njegove družine, in tega tu ni.
    """
    dodaj_druzino(motor, z_otrokom=False)
    sam = ustvari_starsa(
        motor,
        family_id=DRUGA_ID,
        identifikator="sam@primer.test",
        prikazno_ime="Sam",
        aktiven=False,
    )

    odgovor = lastnikov_odjemalec.post(
        f"{POT}/families/{DRUGA_ID}/parents/{sam}/activate", follow_redirects=False
    )

    assert odgovor.status_code == 303
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as brskalnik:
        assert prijavi_se(brskalnik, "sam@primer.test", GESLO_STARSA).status_code == 303


def test_otroka_pod_potjo_starsev_ni(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine
) -> None:
    """Otrok ni starš, zato ga pod `parents/` ni — 404, ne 403.

    Lastnik nad otroki nima nobenega dejanja (`ADR-044` B); pot, ki bi jih
    sprejela, bi bila obljuba strani, ki je ni.
    """
    otrok = dodaj_druzino(motor)

    odgovor = lastnikov_odjemalec.get(
        f"{POT}/families/{DRUGA_ID}/parents/{otrok}/password"
    )

    assert odgovor.status_code == 404


def test_stars_pod_napacno_druzino_ni(
    lastnikov_odjemalec: PrijavljenOdjemalec, motor: Engine, stars: str
) -> None:
    """`user_id` iz družine X pod `family_id` Y je 404.

    Repozitorij članov je vezan na družino **iz naslova** (`ADR-025`), zato
    tujega starša ne najde — brez posebnega primera in brez druge poizvedbe.
    """
    dodaj_druzino(motor)

    odgovor = lastnikov_odjemalec.get(
        f"{POT}/families/{DRUGA_ID}/parents/{stars}/password"
    )

    assert odgovor.status_code == 404
    assert SPOROCILO_NI_STARSA in odgovor.text


# --- Obdelava ugasnjene družine --------------------------------------------


def _ugasni(motor: Engine, family_id: str) -> None:
    """Ugasne družino mimo poti — ta ima svoje teste zgoraj."""
    with Session(motor) as seja:
        seja.execute(update(Family).where(Family.id == family_id).values(is_active=False))
        seja.commit()


def test_ugasnjena_druzina_se_ne_obdela(
    motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
) -> None:
    """Slika ugasnjene družine ostane `new` in klicalec je ne dobi.

    Klic se plača, zato ga družina, v katero se nihče ne more prijaviti, ne
    sme sprožiti (`ADR-044` D). Trdi se oboje — da klica ni **in** da zapis
    ni pristal v `failed`: mirujoča obdelava ne sme proizvesti dela za nazaj
    (`ADR-009` B2).
    """
    dodaj_druzino(motor)
    snov_druzine(motor, slike, DRUGA_ID, UUID_SNOVI)
    _ugasni(motor, DRUGA_ID)
    klicalec, klicane = klicalec_vrne(uspesen_izid())

    obdelanih = obdelaj_cakajoce(tovarna_sej, klicalec, slike)

    assert obdelanih == 0
    assert klicane == []
    with Session(motor) as seja:
        snov = seja.get(Material, UUID_SNOVI)
        assert snov is not None
        assert snov.status == STATUS_NOV


def test_po_aktivaciji_se_ista_snov_obdela(
    lastnikov_odjemalec: PrijavljenOdjemalec,
    motor: Engine,
    slike: Path,
    tovarna_sej: sessionmaker[Session],
) -> None:
    """Test zgoraj ni prazen: ista snov gre v obdelavo, ko je družina prižgana.

    Gre skozi **pravo pot aktivacije**, ne mimo nje: da slika po vrnitvi
    družine ne obtiči, je prav tisto, kar mirujoča obdelava obljublja.
    """
    dodaj_druzino(motor)
    snov_druzine(motor, slike, DRUGA_ID, UUID_SNOVI)
    _ugasni(motor, DRUGA_ID)
    klicalec, klicane = klicalec_vrne(uspesen_izid())

    lastnikov_odjemalec.post(f"{POT}/families/{DRUGA_ID}/activate")
    obdelanih = obdelaj_cakajoce(tovarna_sej, klicalec, slike)

    assert obdelanih == 1
    assert len(klicane) == 1


def test_obnovi_obticale_gre_tudi_cez_ugasnjene(
    motor: Engine, slike: Path, tovarna_sej: sessionmaker[Session]
) -> None:
    """Zapis, ki je obtičal v `processing`, se vrne v vrsto tudi tam.

    Ta pot ne kliče ničesar zunanjega in ne stane nič; vrstica, ki bi v
    ugasnjeni družini ostala `processing` za vedno, bi bila po ponovni
    aktivaciji tiha izguba (`ADR-044` D). Prav zato ima `DruzineRepository`
    dve metodi in ne ene.
    """
    dodaj_druzino(motor)
    snov_druzine(motor, slike, DRUGA_ID, UUID_SNOVI, status=STATUS_V_OBDELAVI)
    _ugasni(motor, DRUGA_ID)

    assert obnovi_obticale(tovarna_sej) == 1

    with Session(motor) as seja:
        snov = seja.get(Material, UUID_SNOVI)
        assert snov is not None
        assert snov.status == STATUS_NOV
