"""Regresijski test tesnjenja: nobena pot in noben repozitorij ne prestopi družine.

Kriterij V3-R01 in obvezen vhod za vsako nadaljnjo zahtevo V3
(`docs/verzije/v3.md`, `docs/odlocitve/ADR-025`). Dve družini, vsaka s snovjo,
arhivom, kvizi in poskusi. Družina B pošlje identifikatorje družine A:

- na **vsako pot** aplikacije — odgovor ne sme vsebovati nobene sledi A in
  podatki ter slike A morajo ostati nedotaknjeni;
- v **vsako javno metodo** vseh treh repozitorijev — z istim merilom.

**Varovali.** Množica poti v `PRIMERI_POTI` mora biti enaka množici poti
aplikacije in množica metod v `PRIMERI_REPOZITORIJEV` enaka množici javnih
metod. Nova pot ali metoda brez vnosa tu podre zbirko. `V3-R05` zahteva, da je
ta test razširjen na vse poti iz `V3-R03` do `V3-R07` in `V3-R09` — to se zgodi
z vnosom v slovar, ne s prepisom.

Podatki nastanejo skozi prave poti (objava kviza, poskusi s telefona), kjer je
to mogoče, da tesnjenje velja za stanje, kakršno nastane v produkciji.
"""

import inspect
import io
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, Select, event, select
from sqlalchemy.orm import Session

from app import google
from app.db import (
    ClaniRepository,
    DruzineRepository,
    IdentifikatorZaseden,
    IzidObdelave,
    KviziRepository,
    MaterialsRepository,
    PoskusZaZapis,
    ScheduleRepository,
    StatistikaRepository,
)
from app.main import create_app
from app.models import (
    NACIN_SAMOOCENA,
    STATUS_NOV,
    STATUS_PRIPRAVLJEN,
    STATUS_V_OBDELAVI,
    VLOGA_OTROK,
    Base,
    Material,
    Question,
    QuestionAttempt,
    Quiz,
    Schedule,
    User,
)
from app.settings import Settings
from app.urnik import Vnos
from tests.conftest import (
    CVEK_ID,
    OTROK_ID,
    PrijavljenOdjemalec,
    naredi_testne_nastavitve,
    prijavi,
    ustvari_otroka,
    ustvari_sejo,
    ustvari_starsa,
)
from tests.test_danes import PONEDELJEK
from tests.test_danes import kartica as kartica_danes
from tests.test_danes import vrstice as vrstice_danes
from tests.test_druzine import DRUGA_ID, dodaj_druzino
from tests.test_kvizi import objavi
from tests.test_racun import PonarejenGoogle
from tests.test_resevanje import POKAZANO, poskus, poslji
from tests.test_rezultat import postavke

#: Vloge snovi, ki jih ima vsaka družina.
VLOGE = ("akt", "arh", "za_brisanje", "nova", "obticala")


@dataclass(frozen=True)
class Druzina:
    """Vse, kar ima ena družina, in po čem se jo v odgovoru prepozna."""

    family_id: str
    subject: str
    #: Niz v vsakem besedilu družine: prepis, povzetek, vprašanja, ime kviza.
    znak: str
    akt: str
    arh: str
    za_brisanje: str
    nova: str
    obticala: str
    posneto: datetime
    prejeto: datetime
    vprasanja: tuple[str, ...]
    resen_kviz: str
    odprt_kviz: str
    postavke: tuple[str, ...]
    postavka_odprtega: str
    poskusi: tuple[str, ...]
    #: Osebi družine (V3-R06). Tudi njun `id` je sled: seznam članov druge
    #: družine se ne sme pokazati nikjer.
    stars_id: str
    otrok_id: str

    def sledi_vsebine(self) -> tuple[str, ...]:
        """Nizi **vsebine**: snov, kvizi, vprašanja, postavke, poskusi.

        Ločeno od oseb, ker `V3-R05` pozna bralca, ki sme videti imena in `id`
        staršev tuje družine (lastnik sistema), vsebine pa ne sme videti nihče
        (`ADR-044` B). Za vse ostale poti velja `sledi()`, ki oboje združi.
        """
        return (
            self.znak,
            self.akt,
            self.arh,
            self.za_brisanje,
            self.nova,
            self.obticala,
            self.resen_kviz,
            self.odprt_kviz,
            *self.vprasanja,
            *self.postavke,
            *self.poskusi,
        )

    def sledi(self) -> tuple[str, ...]:
        """Nizi, ki v odgovoru druge družine ne smejo nastopiti."""
        return (*self.sledi_vsebine(), self.stars_id, self.otrok_id)


def _zgradi(
    aplikacija: FastAPI,
    odjemalec: PrijavljenOdjemalec,
    motor: Engine,
    slike: Path,
    *,
    family_id: str,
    subject: str,
    znak: str,
    prejeto: datetime,
) -> Druzina:
    idji = {vloga: str(uuid5(NAMESPACE_URL, f"{znak}-{vloga}")) for vloga in VLOGE}
    posneto = datetime.now(UTC)
    vprasanja = tuple(f"q-{znak}-{i}" for i in range(1, 6))

    # Osebi nastaneta **pred** snovjo: od V3-R07 snov nosi otroka, ki jo je
    # poslikal (`ADR-039`), in ta mora biti otrok te družine. Snov s tujim
    # otrokom je stanje, ki na produkciji ne nastane, in bi ta test delala
    # lažje, kot je.
    #
    # `user_id=None` da naključen `id`: obe družini gresta skozi isto pot in
    # stalni privzetek iz `conftest` bi drugo podrl na primarnem ključu.
    stars_id = ustvari_starsa(motor, family_id=family_id, identifikator=znak.lower())
    otrok_id = ustvari_otroka(
        motor,
        user_id=None,
        family_id=family_id,
        identifikator=f"otrok-{znak}".lower(),
    )

    with Session(motor) as seja:
        for vloga, material_id in idji.items():
            pot = slike / family_id / f"{material_id}.jpg"
            pot.parent.mkdir(parents=True, exist_ok=True)
            pot.write_bytes(f"slika {znak} {vloga}".encode())
            material = Material(
                child_id=otrok_id,
                id=material_id,
                family_id=family_id,
                subject=subject,
                taken_at=posneto,
                image_path=str(pot),
                status={"nova": STATUS_NOV, "obticala": STATUS_V_OBDELAVI}.get(
                    vloga, STATUS_PRIPRAVLJEN
                ),
                received_at=prejeto,
                readable=True,
                transcript=f"Prepis {znak}",
                summary=f"Povzetek {znak}",
                archived_at=posneto if vloga in ("arh", "za_brisanje") else None,
                device_deleted_at=posneto if vloga == "arh" else None,
            )
            if vloga == "akt":
                material.vsa_vprasanja = [
                    Question(
                        id=vprasanje_id,
                        family_id=family_id,
                        position=i,
                        question=f"Vprašanje {i} {znak}?",
                        answer=f"Odgovor {i} {znak}.",
                        subject=subject,
                        material_taken_at=posneto,
                    )
                    for i, vprasanje_id in enumerate(vprasanja, start=1)
                ]
            seja.add(material)
        seja.commit()

    # Kvizi in poskusi skozi prave poti, v imenu te družine. **Obe strani
    # povesta družino prek seje** (`ADR-036` F): admin s piškotkom starša,
    # telefon z žetonom otroka v glavi. Do V3-R04 je bila druga polovica
    # začasna odvisnost, ki jo je bilo mogoče podtakniti mimo prijave —
    # tesnjenje telefona je zato šele odslej tesnjenje prave poti.
    prijavi(odjemalec, motor, stars_id)
    telefon = ustvari_sejo(motor, otrok_id)
    odjemalec.headers.update(telefon.glave)
    resen = objavi(
        odjemalec,
        motor,
        [idji["akt"]],
        koliko=3,
        subject=subject,
        vstop="rocna",
        ime=f"Rešen {znak}",
    )
    postavke_resenega = postavke(motor, resen)
    odgovor = poslji(odjemalec, [poskus(p) for p in postavke_resenega])
    assert odgovor.status_code == 200, odgovor.text
    odprt = objavi(
        odjemalec,
        motor,
        [idji["akt"]],
        koliko=3,
        subject=subject,
        vstop="rocna",
        ime=f"Odprt {znak}",
    )
    postavke_odprtega = postavke(motor, odprt)

    with Session(motor) as seja:
        poskusi = tuple(
            seja.scalars(select(QuestionAttempt.id).where(QuestionAttempt.family_id == family_id))
        )

    return Druzina(
        family_id=family_id,
        subject=subject,
        znak=znak,
        posneto=posneto,
        prejeto=prejeto,
        vprasanja=vprasanja,
        resen_kviz=resen,
        odprt_kviz=odprt,
        postavke=(*postavke_resenega, *postavke_odprtega),
        postavka_odprtega=postavke_odprtega[0],
        poskusi=poskusi,
        stars_id=stars_id,
        otrok_id=otrok_id,
        **idji,
    )


@pytest.fixture
def druzini(
    aplikacija: FastAPI, odjemalec: PrijavljenOdjemalec, motor: Engine, slike: Path
) -> tuple[Druzina, Druzina]:
    """Družini A (Cvek) in B; aplikacija je po vrnitvi v imenu **B**.

    Predmeta sta različna, da je tudi štetje po predmetu razločljivo; B je
    sliko prejela prej kot A, da `nazadnje_prejeto` ne more slučajno vrniti
    pravega časa iz napačne družine.
    """
    # Brez otroka: `_zgradi` ga ustvari sam, za obe družini po isti poti.
    dodaj_druzino(motor, z_otrokom=False)
    zdaj = datetime.now(UTC)
    a = _zgradi(
        aplikacija,
        odjemalec,
        motor,
        slike,
        family_id=CVEK_ID,
        subject="ZGO",
        znak="SKRIVNOST-A",
        prejeto=zdaj,
    )
    b = _zgradi(
        aplikacija,
        odjemalec,
        motor,
        slike,
        family_id=DRUGA_ID,
        subject="MAT",
        znak="SKRIVNOST-B",
        prejeto=zdaj - timedelta(hours=2),
    )
    # `_zgradi` je odjemalca nazadnje prijavil kot starša B in mu v glavo dal
    # žeton otroka B; to je stanje, v katerem testi tečejo. Odjemalec torej v
    # isti zahtevi nosi oboje, kar je za ta test prav: dokazuje, da pot vzame
    # tisto identiteto, ki ji pripada, in ne tiste, ki je pri roki.
    assert odjemalec.get("/quizzes/pending").status_code == 200
    return a, b


def posnetek_druzine(
    motor: Engine, slike: Path, family_id: str
) -> tuple[list[tuple[str, ...]], dict[str, bytes]]:
    """Vse vrstice in vse slike ene družine, za primerjavo pred in po.

    Tabela, za katero pravilo družine tu ni zapisano, je napaka: nova tabela
    (`V3-R03` in naprej) bi sicer ostala zunaj primerjave in test bi bil zelen
    ne glede na to, kaj se v njej zgodi.
    """
    kvizi = Quiz.__table__
    urniki = Schedule.__table__
    uporabniki = User.__table__
    vrstice: list[tuple[str, ...]] = []
    with Session(motor) as seja:
        for tabela in Base.metadata.sorted_tables:
            poizvedba: Select[Any]
            if "family_id" in tabela.c:
                poizvedba = select(tabela).where(tabela.c.family_id == family_id)
            elif tabela.name == "families":
                poizvedba = select(tabela).where(tabela.c.id == family_id)
            elif tabela.name == "quiz_items":
                poizvedba = (
                    select(tabela)
                    .join(kvizi, kvizi.c.id == tabela.c.quiz_id)
                    .where(kvizi.c.family_id == family_id)
                )
            elif tabela.name == "schedule_entries":
                # Urnik (V3-R09): vnos brez urnika ne obstaja, zato je njegova
                # družina družina urnika — ista izpeljava kot pri `quiz_items`
                # (`ADR-029` C). `schedules` stolpec ima in pade v prvo vejo.
                poizvedba = (
                    select(tabela)
                    .join(urniki, urniki.c.id == tabela.c.schedule_id)
                    .where(urniki.c.family_id == family_id)
                )
            elif tabela.name in ("credentials", "sessions"):
                # Identiteta (V3-R03): družina je od uporabnika, ki mu vrstica
                # pripada. Seja druge družine ne sme ne nastati ne izginiti,
                # ko po njenih poteh hodi kdo drug.
                poizvedba = (
                    select(tabela)
                    .join(uporabniki, uporabniki.c.id == tabela.c.user_id)
                    .where(uporabniki.c.family_id == family_id)
                )
            elif tabela.name == "login_attempts":
                # Edina tabela brez družine, in to po `ADR-035` E: neuspel
                # poskus se zabeleži tudi za identifikator, ki ne obstaja, zato
                # družine nima na kaj vezati. V posnetek ne sodi.
                continue
            else:
                raise AssertionError(f"Za tabelo {tabela.name} ni zapisano, čigava je.")
            vrstice.extend((tabela.name, *map(str, vrstica)) for vrstica in seja.execute(poizvedba))

    mapa = slike / family_id
    datoteke = {
        str(pot.relative_to(mapa)): pot.read_bytes()
        for pot in sorted(mapa.rglob("*"))
        if pot.is_file()
    }
    return sorted(vrstice), datoteke


def brez_sledi(besedilo: str, tuja: Druzina, poslano: tuple[str, ...]) -> None:
    """Odgovor ne vsebuje ničesar od tuje družine, razen tega, kar je poslal sam."""
    for sled in tuja.sledi():
        if sled not in poslano:
            assert sled not in besedilo, f"odgovor vsebuje sled tuje družine: {sled}"


# --- Aplikacija tesnjenja ---

#: Aplikacija tega testa ima **Google prizgan** (V3-R08), za razliko od
#: privzete iz `conftest.py`.
#:
#: Brez tega bi Googlove poti vrnile 404, ker Google v tej namestitvi ni
#: nastavljen (`docs/odlocitve/ADR-046` F) — in njihovi primeri spodaj bi bili
#: zeleni, ne da bi karkoli dokazali. Varovalo `test_vsaka_pot_aplikacije_ima_primer`
#: bi bilo zadovoljeno, tesnjenje pa nepreverjeno. To je natanko oblika testa,
#: ki jo merilo dokoncanosti prepoveduje (`CLAUDE.md` §1b: „test, ki ostane
#: zelen ob pokvarjeni implementaciji, ne steje").


@pytest.fixture
def aplikacija(slike: Path, motor: Engine) -> FastAPI:
    """Prepise fixture iz `conftest.py`: vse zmoznosti so prizgane.

    Odjemalec Googla je ponaredek in do omreza ne pride (`ADR-046` F).
    """
    nastavitve: Settings = naredi_testne_nastavitve(slike).model_copy(
        update={
            "google_client_id": "odjemalec-tesnjenja",
            "google_client_secret": "skrivnost-tesnjenja",
            "domena": "tesnjenje.test",
        }
    )
    return create_app(
        nastavitve=nastavitve, motor=motor, odjemalec_googla=PonarejenGoogle()
    )


# --- Poti ---

OK = frozenset({200})
NI = frozenset({404})
PREUSMERITEV = frozenset({303})

#: (odgovor, dovoljeni statusi, poslani identifikatorji tuje družine)
Klic = Callable[[PrijavljenOdjemalec, Druzina], tuple[Any, frozenset[int], tuple[str, ...]]]

def _prijava_s_tujim_racunom(odjemalec: PrijavljenOdjemalec, tuja: Druzina) -> Any:
    """Poskus prijave z identifikatorjem starša tuje družine in napačnim geslom.

    Gre skozi prijavni obrazec, ker CSRF žeton prijave pride iz piškotka, ki ga
    postavi šele `GET` (`docs/odlocitve/ADR-035` D).
    """
    stran = odjemalec.get("/admin/login")
    zeton = re.search(r'name="csrf" value="([^"]+)"', stran.text)
    assert zeton is not None, stran.text
    return odjemalec.post(
        "/admin/login",
        data={
            "identifikator": tuja.znak,
            "geslo": "to-geslo-ni-pravo",
            "csrf": zeton.group(1),
        },
        follow_redirects=False,
    )


def _google_zeton_prijave(odjemalec: PrijavljenOdjemalec) -> str:
    """CSRF zeton prijavnega obrazca; Googlov gumb nosi istega (`ADR-035` D)."""
    stran = odjemalec.get("/admin/login")
    zeton = re.search(r'name="csrf" value="([^"]+)"', stran.text)
    assert zeton is not None, stran.text
    return zeton.group(1)


def _povratek_s_tujim_stanjem(odjemalec: PrijavljenOdjemalec, tuja: Druzina) -> Any:
    """Povratni klic s piskotkom stanja, ki nosi **tujega** starsa.

    To je oblika napada, ki ji je namenjen `ADR-046` D, prevedena v jezik tega
    testa: identifikator druzine A, poslan v imenu druzine B. Ce bi pot
    piskotku verjela, bi se Google racun druzine B pripisal starsu druzine A —
    in ta bi od takrat vstopal v tujo druzino, kadar bi hotel.
    """
    stanje = google.novo_stanje(google.Namen.POVEZAVA, tuja.stars_id)
    odjemalec.cookies.set(google.PISKOTEK_STANJA, stanje.zapis())
    odgovor = odjemalec.get(
        google.POT_POVRATNA,
        params={"code": "koda-tesnjenja", "state": stanje.nakljucje},
        follow_redirects=False,
    )
    odjemalec.cookies.delete(google.PISKOTEK_STANJA)
    return odgovor


PRIMERI_POTI: dict[tuple[str, str], Klic] = {
    ("GET", "/health"): lambda o, a: (o.get("/health"), OK, ()),
    ("GET", "/admin"): lambda o, a: (o.get("/admin"), OK, ()),
    ("GET", "/admin/archive"): lambda o, a: (o.get("/admin/archive"), OK, ()),
    ("GET", "/admin/days"): lambda o, a: (o.get("/admin/days?obdobje=teden"), OK, ()),
    ("GET", "/admin/subjects/{koda}"): lambda o, a: (
        o.get(f"/admin/subjects/{a.subject}"), OK, (),
    ),
    # V3-R11. Prepis tuje snovi ne sme priti v besedilo: nabor je stran
    # predmeta te družine, zato tuj identifikator iz njega izpade (`ADR-048`
    # F). Močnejši primer — izbor v **svojem** predmetu, pomešan s tujim
    # identifikatorjem — je spodaj v svojem testu.
    ("GET", "/admin/transcripts"): lambda o, a: (
        o.get("/admin/transcripts", follow_redirects=False), PREUSMERITEV, (),
    ),
    ("POST", "/admin/transcripts"): lambda o, a: (
        o.post("/admin/transcripts", data={"subject": a.subject, "snov": [a.akt]}),
        OK,
        (a.akt,),
    ),
    ("GET", "/admin/materials/{material_id}"): lambda o, a: (
        o.get(f"/admin/materials/{a.akt}"), NI, (a.akt,),
    ),
    ("GET", "/admin/materials/{material_id}/image"): lambda o, a: (
        o.get(f"/admin/materials/{a.akt}/image"), NI, (a.akt,),
    ),
    ("GET", "/admin/materials/{material_id}/archive"): lambda o, a: (
        o.get(f"/admin/materials/{a.akt}/archive"), NI, (a.akt,),
    ),
    ("POST", "/admin/materials/{material_id}/archive"): lambda o, a: (
        o.post(f"/admin/materials/{a.akt}/archive", follow_redirects=False),
        PREUSMERITEV,
        (a.akt,),
    ),
    ("POST", "/admin/materials/{material_id}/purge-image"): lambda o, a: (
        o.post(f"/admin/materials/{a.arh}/purge-image", follow_redirects=False), NI, (a.arh,),
    ),
    ("GET", "/admin/materials/{material_id}/delete"): lambda o, a: (
        o.get(f"/admin/materials/{a.arh}/delete"), NI, (a.arh,),
    ),
    ("POST", "/admin/materials/{material_id}/delete"): lambda o, a: (
        o.post(f"/admin/materials/{a.arh}/delete", follow_redirects=False),
        PREUSMERITEV,
        (a.arh,),
    ),
    ("POST", "/admin/materials/{material_id}/reprocess"): lambda o, a: (
        o.post(f"/admin/materials/{a.akt}/reprocess", follow_redirects=False), NI, (a.akt,),
    ),
    # Veljavna koda predmeta, ne neznana: 404 mora priti iz meje družine in
    # ne iz zavrnitve vrednosti (V3-R10, `ADR-040`).
    ("POST", "/admin/materials/{material_id}/subject"): lambda o, a: (
        o.post(
            f"/admin/materials/{a.akt}/subject",
            data={"subject": "SLJ"},
            follow_redirects=False,
        ),
        NI,
        (a.akt,),
    ),
    ("GET", "/admin/quizzes/new"): lambda o, a: (
        o.get("/admin/quizzes/new?vstop=danes"), OK, (),
    ),
    ("POST", "/admin/quizzes/new"): lambda o, a: (
        o.post(
            "/admin/quizzes/new",
            data={"vstop": "rocna", "subject": a.subject, "stevilo": "3", "snov": [a.akt]},
        ),
        OK,
        (a.akt,),
    ),
    ("POST", "/admin/quizzes/preview"): lambda o, a: (
        o.post(
            "/admin/quizzes/preview",
            data={"vstop": "rocna", "subject": a.subject, "stevilo": "3", "snov": [a.akt]},
        ),
        OK,
        (a.akt,),
    ),
    ("POST", "/admin/quizzes"): lambda o, a: (
        o.post(
            "/admin/quizzes",
            data={
                "vstop": "rocna",
                "subject": a.subject,
                "ime": "Vdor",
                "vprasanje": list(a.vprasanja[:3]),
            },
            follow_redirects=False,
        ),
        frozenset({409}),
        a.vprasanja[:3],
    ),
    ("GET", "/admin/quizzes/{quiz_id}"): lambda o, a: (
        o.get(f"/admin/quizzes/{a.resen_kviz}"),
        NI,
        (a.resen_kviz,),
    ),
    ("GET", "/admin/quizzes/{quiz_id}/print"): lambda o, a: (
        o.get(f"/admin/quizzes/{a.resen_kviz}/print"),
        NI,
        (a.resen_kviz,),
    ),
    ("POST", "/admin/quizzes/{quiz_id}/cancel"): lambda o, a: (
        o.post(f"/admin/quizzes/{a.odprt_kviz}/cancel", follow_redirects=False),
        NI,
        (a.odprt_kviz,),
    ),
    # Identiteta (V3-R03). Prijava je edina pot, na kateri gre identifikator
    # tuje družine skozi obrazec; njen odgovor ne sme povedati, ali ta račun
    # obstaja, in tuje seje ne sme ne ustvariti ne pobrisati.
    ("GET", "/admin/login"): lambda o, a: (o.get("/admin/login"), OK, ()),
    ("POST", "/admin/login"): lambda o, a: (
        _prijava_s_tujim_racunom(o, a),
        frozenset({401}),
        (a.znak,),
    ),
    ("POST", "/admin/logout"): lambda o, a: (
        o.post("/admin/logout", follow_redirects=False),
        PREUSMERITEV,
        (),
    ),
    # Identiteta na telefonu (V3-R04). Isti dve vprašanji kot pri prijavi v
    # brskalniku, z drugim prenosnikom: ali odgovor izda obstoj tujega računa
    # in ali se da z njim doseči tujo sejo.
    ("POST", "/auth/login"): lambda o, a: (
        o.post(
            "/auth/login",
            json={"identifier": f"otrok-{a.znak}", "password": "to-geslo-ni-pravo"},
        ),
        frozenset({401}),
        (a.znak,),
    ),
    ("POST", "/auth/logout"): lambda o, a: (
        o.post("/auth/logout"),
        OK,
        (),
    ),
    # Člani družine (V3-R06). Tuj `user_id` je 404 in ne 403: `403` bi povedal,
    # da tak uporabnik obstaja. Zato so tu **vse** poti člana, obe metodi, in
    # v obeh vlogah — starš in otrok tuje družine.
    ("GET", "/admin/family"): lambda o, a: (o.get("/admin/family"), OK, ()),
    ("POST", "/admin/family/children"): lambda o, a: (
        o.post(
            "/admin/family/children",
            data={
                "ime": "Vrinjen otrok",
                # Uporabniško ime tuje družine: če bi ga ta pot sprejela, bi
                # nastal drugi račun z istim imenom — ali pa bi sporočilo o
                # zasedenosti izdalo, čigav je.
                "uporabnisko_ime": f"otrok-{a.znak}".lower(),
                "geslo": "geslo-otroka-8",
                "geslo_znova": "geslo-otroka-8",
            },
        ),
        frozenset({400}),
        (a.znak,),
    ),
    ("POST", "/admin/family/parents"): lambda o, a: (
        o.post(
            "/admin/family/parents",
            data={
                "ime": "Vrinjen starš",
                "enaslov": f"{a.znak}@primer.test".lower(),
                "geslo": "geslo-starsa-12",
                "geslo_znova": "geslo-starsa-12",
            },
            follow_redirects=False,
        ),
        PREUSMERITEV,
        (a.znak,),
    ),
    ("GET", "/admin/family/members/{user_id}/password"): lambda o, a: (
        o.get(f"/admin/family/members/{a.stars_id}/password"), NI, (a.stars_id,),
    ),
    ("POST", "/admin/family/members/{user_id}/password"): lambda o, a: (
        o.post(
            f"/admin/family/members/{a.otrok_id}/password",
            data={"geslo": "vlomljeno-geslo", "geslo_znova": "vlomljeno-geslo"},
            follow_redirects=False,
        ),
        NI,
        (a.otrok_id,),
    ),
    ("GET", "/admin/family/members/{user_id}/deactivate"): lambda o, a: (
        o.get(f"/admin/family/members/{a.stars_id}/deactivate"), NI, (a.stars_id,),
    ),
    ("POST", "/admin/family/members/{user_id}/deactivate"): lambda o, a: (
        o.post(f"/admin/family/members/{a.otrok_id}/deactivate", follow_redirects=False),
        NI,
        (a.otrok_id,),
    ),
    ("GET", "/admin/family/members/{user_id}/activate"): lambda o, a: (
        o.get(f"/admin/family/members/{a.stars_id}/activate"), NI, (a.stars_id,),
    ),
    ("POST", "/admin/family/members/{user_id}/activate"): lambda o, a: (
        o.post(f"/admin/family/members/{a.otrok_id}/activate", follow_redirects=False),
        NI,
        (a.otrok_id,),
    ),
    # Stran lastnika sistema (V3-R05). Odjemalec je **navaden starš**, zato je
    # vsaka od teh poti 404 — ne 403 in ne 200 z obrezano vsebino: za starša ta
    # stran ne obstaja (`ADR-044` G). Da je za lastnika 200, dokazuje
    # `tests/test_sistem.py`; tu je pomembno, da za vse ostale ni.
    ("GET", "/admin/system"): lambda o, a: (o.get("/admin/system"), NI, ()),
    ("GET", "/admin/system/families"): lambda o, a: (
        o.get("/admin/system/families", follow_redirects=False), NI, ()
    ),
    ("POST", "/admin/system/families"): lambda o, a: (
        o.post(
            "/admin/system/families",
            data={
                "ime_druzine": "Vdor",
                "ime": "Vlomilec",
                "enaslov": "vlom@primer.test",
                "geslo": "vlomljeno-geslo-12",
                "geslo_znova": "vlomljeno-geslo-12",
            },
            follow_redirects=False,
        ),
        NI,
        (),
    ),
    ("GET", "/admin/system/families/{family_id}"): lambda o, a: (
        o.get(f"/admin/system/families/{a.family_id}"), NI, (a.family_id,),
    ),
    ("GET", "/admin/system/families/{family_id}/deactivate"): lambda o, a: (
        o.get(f"/admin/system/families/{a.family_id}/deactivate"), NI, (a.family_id,),
    ),
    ("POST", "/admin/system/families/{family_id}/deactivate"): lambda o, a: (
        o.post(
            f"/admin/system/families/{a.family_id}/deactivate", follow_redirects=False
        ),
        NI,
        (a.family_id,),
    ),
    ("GET", "/admin/system/families/{family_id}/activate"): lambda o, a: (
        o.get(f"/admin/system/families/{a.family_id}/activate"), NI, (a.family_id,),
    ),
    ("POST", "/admin/system/families/{family_id}/activate"): lambda o, a: (
        o.post(f"/admin/system/families/{a.family_id}/activate", follow_redirects=False),
        NI,
        (a.family_id,),
    ),
    ("GET", "/admin/system/families/{family_id}/parents/{user_id}/password"): lambda o, a: (
        o.get(f"/admin/system/families/{a.family_id}/parents/{a.stars_id}/password"),
        NI,
        (a.family_id, a.stars_id),
    ),
    ("POST", "/admin/system/families/{family_id}/parents/{user_id}/password"): lambda o, a: (
        o.post(
            f"/admin/system/families/{a.family_id}/parents/{a.stars_id}/password",
            data={"geslo": "vlomljeno-geslo-12", "geslo_znova": "vlomljeno-geslo-12"},
            follow_redirects=False,
        ),
        NI,
        (a.family_id, a.stars_id),
    ),
    ("GET", "/admin/system/families/{family_id}/parents/{user_id}/deactivate"): lambda o, a: (
        o.get(f"/admin/system/families/{a.family_id}/parents/{a.stars_id}/deactivate"),
        NI,
        (a.family_id, a.stars_id),
    ),
    ("POST", "/admin/system/families/{family_id}/parents/{user_id}/deactivate"): lambda o, a: (
        o.post(
            f"/admin/system/families/{a.family_id}/parents/{a.stars_id}/deactivate",
            follow_redirects=False,
        ),
        NI,
        (a.family_id, a.stars_id),
    ),
    ("GET", "/admin/system/families/{family_id}/parents/{user_id}/activate"): lambda o, a: (
        o.get(f"/admin/system/families/{a.family_id}/parents/{a.stars_id}/activate"),
        NI,
        (a.family_id, a.stars_id),
    ),
    ("POST", "/admin/system/families/{family_id}/parents/{user_id}/activate"): lambda o, a: (
        o.post(
            f"/admin/system/families/{a.family_id}/parents/{a.stars_id}/activate",
            follow_redirects=False,
        ),
        NI,
        (a.family_id, a.stars_id),
    ),
    # Urnik (V3-R09). Vse tri poti imenujejo **tujega** otroka: urnik je last
    # otroka, zato je to tu ista vrsta sledi kot tuj `material_id` drugje.
    ("GET", "/admin/schedule"): lambda o, a: (
        o.get(f"/admin/schedule?otrok={a.otrok_id}"), NI, (a.otrok_id,),
    ),
    ("POST", "/admin/schedule"): lambda o, a: (
        o.post(
            "/admin/schedule",
            data={"otrok": a.otrok_id, "c0_MAT": "da"},
            follow_redirects=False,
        ),
        NI,
        (a.otrok_id,),
    ),
    # Edina pot pod `/admin`, ki pošilja `multipart` in CSRF preveri sama
    # (`ADR-043`). Žeton gre zato v `data` in ne prek `PrijavljenOdjemalec`,
    # ki ga doda samo običajnim obrazcem.
    ("POST", "/admin/schedule/proposal"): lambda o, a: (
        o.post(
            "/admin/schedule/proposal",
            data={"csrf": o.csrf, "otrok": a.otrok_id},
            files={"slika": ("urnik.png", io.BytesIO(b"PNG"), "image/png")},
        ),
        NI,
        (a.otrok_id,),
    ),
    ("GET", "/admin/statistics"): lambda o, a: (o.get("/admin/statistics?leto=vse"), OK, ()),
    ("GET", "/admin/statistics/subjects/{koda}"): lambda o, a: (
        o.get(f"/admin/statistics/subjects/{a.subject}?leto=vse"),
        OK,
        (),
    ),
    ("POST", "/materials"): lambda o, a: (
        o.post(
            "/materials",
            data={"id": a.akt, "subject": a.subject, "taken_at": "2026-09-04T07:30:00Z"},
            files={"file": ("posnetek.jpg", b"ponaredek", "image/jpeg")},
        ),
        frozenset({409}),
        (a.akt,),
    ),
    ("GET", "/materials/pending-deletion"): lambda o, a: (
        o.get("/materials/pending-deletion"),
        OK,
        (),
    ),
    ("POST", "/materials/deleted-on-device"): lambda o, a: (
        o.post("/materials/deleted-on-device", json={"ids": [a.za_brisanje]}),
        OK,
        (a.za_brisanje,),
    ),
    # --- Google (V3-R08) ---
    #
    # Nobena od teh poti tujega identifikatorja ne sprejme kot vhod: vse
    # delajo nad `user_id` iz seje. Primeri zato dokazujejo drugo plat istega
    # pravila — da pot, ki je o **meni**, ne pokaze in ne spremeni nicesar
    # tujega, tudi kadar ji tujega starsa vrinemo v piskotek.
    ("GET", google.POT_RACUNA): lambda o, a: (o.get(google.POT_RACUNA), OK, ()),
    ("POST", google.POT_POVEZAVE): lambda o, a: (
        o.post(google.POT_POVEZAVE, follow_redirects=False),
        PREUSMERITEV,
        (),
    ),
    ("POST", google.POT_ODSTRANITVE): lambda o, a: (
        o.post(google.POT_ODSTRANITVE, follow_redirects=False),
        PREUSMERITEV,
        (),
    ),
    ("POST", google.POT_PRIJAVE): lambda o, a: (
        o.post(
            google.POT_PRIJAVE,
            data={"csrf": _google_zeton_prijave(o)},
            follow_redirects=False,
        ),
        PREUSMERITEV,
        (),
    ),
    ("GET", google.POT_POVRATNA): lambda o, a: (
        _povratek_s_tujim_stanjem(o, a),
        frozenset({409}),
        (a.stars_id,),
    ),
    ("GET", "/quizzes/pending"): lambda o, a: (
        o.get("/quizzes/pending"),
        OK,
        (),
    ),
    ("POST", "/quiz-attempts"): lambda o, a: (
        poslji(o, [poskus(a.postavka_odprtega)]),
        frozenset({422}),
        (a.postavka_odprtega,),
    ),
}


def test_vsaka_pot_aplikacije_ima_primer(aplikacija: FastAPI) -> None:
    """Varovalo: nova pot brez primera tu podre zbirko."""
    poti = {
        (metoda.upper(), pot)
        for pot, metode in aplikacija.openapi()["paths"].items()
        for metoda in metode
    }

    assert poti == set(PRIMERI_POTI)


@pytest.mark.parametrize("primer", sorted(PRIMERI_POTI), ids=" ".join)
def test_pot_ne_pokaze_in_ne_spremeni_tuje_druzine(
    primer: tuple[str, str],
    odjemalec: PrijavljenOdjemalec,
    motor: Engine,
    slike: Path,
    druzini: tuple[Druzina, Druzina],
) -> None:
    a, _ = druzini
    prej = posnetek_druzine(motor, slike, a.family_id)

    odgovor, statusi, poslano = PRIMERI_POTI[primer](odjemalec, a)

    assert odgovor.status_code in statusi, odgovor.text[:500]
    brez_sledi(odgovor.text, a, poslano)
    assert posnetek_druzine(motor, slike, a.family_id) == prej


def test_druzina_b_na_istih_poteh_vidi_svoje(
    odjemalec: PrijavljenOdjemalec, druzini: tuple[Druzina, Druzina]
) -> None:
    """Test zgoraj ni prazen: iste poti družini B njene podatke pokažejo."""
    _, b = druzini

    assert b.akt in odjemalec.get(f"/admin/subjects/{b.subject}").text
    assert b.arh in odjemalec.get("/admin/archive").text
    assert b.znak in odjemalec.get(f"/admin/statistics/subjects/{b.subject}?leto=vse").text
    assert b.odprt_kviz in odjemalec.get("/quizzes/pending").text
    assert b.za_brisanje in odjemalec.get("/materials/pending-deletion").text
    assert b.otrok_id in odjemalec.get("/admin/family").text


def test_kartica_danes_ne_steje_slik_tuje_druzine(
    odjemalec: PrijavljenOdjemalec,
    motor: Engine,
    slike: Path,
    druzini: tuple[Druzina, Druzina],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kartica „danes" (V3-R13) šteje samo slike svoje družine.

    Dan je stalen ponedeljek: slike, ki jih `_zgradi` posname ob uri zagona,
    tako ne štejejo, in izid ni odvisen od dneva v tednu, ko zbirka teče.
    """
    a, b = druzini
    monkeypatch.setattr("app.routers.admin.danes", lambda: PONEDELJEK)
    posneto = datetime(2026, 9, 7, 8, tzinfo=UTC)
    with Session(motor) as seja:
        for druzina, subject, koliko in ((a, "ZGO", 2), (b, "MAT", 1)):
            for i in range(koliko):
                seja.add(
                    Material(
                        id=str(uuid4()),
                        family_id=druzina.family_id,
                        child_id=druzina.otrok_id,
                        subject=subject,
                        taken_at=posneto,
                        image_path=str(slike / druzina.family_id / f"danes-{i}.jpg"),
                        status=STATUS_NOV,
                        received_at=posneto,
                    )
                )
        seja.commit()

    besedilo = odjemalec.get("/admin").text

    assert vrstice_danes(besedilo) == ["✓ Maša — danes že poslikano MAT 1"]
    assert "ZGO" not in kartica_danes(besedilo)


def test_prepis_tuje_druzine_ne_pride_v_besedilo(
    odjemalec: PrijavljenOdjemalec, druzini: tuple[Druzina, Druzina]
) -> None:
    """Kriterij V3-R11: izbor v **svojem** predmetu s tujim identifikatorjem vred.

    Primer v `PRIMERI_POTI` pošlje tuj predmet in tam je nabor prazen že zato,
    ker družina B v predmetu A nima ničesar. Tu je test močnejši: predmet je
    B-jev, njen lastni izbor uspe — in prav med njenimi identifikatorji potuje
    tudi identifikator snovi družine A. Če bi presejanje teklo po izboru
    namesto po naboru, bi se tu videl prepis družine A.
    """
    a, b = druzini

    odgovor = odjemalec.post(
        "/admin/transcripts", data={"subject": b.subject, "snov": [b.akt, a.akt]}
    )

    assert odgovor.status_code == 200
    # Svoje vidi — sicer bi bila trditev spodaj zelena nad prazno stranjo.
    assert b.znak in odgovor.text
    assert a.znak not in odgovor.text
    assert a.akt not in odgovor.text


def test_vprasanja_tuje_druzine_ne_pridejo_v_besedilo(
    odjemalec: PrijavljenOdjemalec, druzini: tuple[Druzina, Druzina]
) -> None:
    """Kriterij V3-R12: isti izbor kot zgoraj, trditev o vprašanjih.

    Obe družini imata pri aktivni snovi vprašanja. B-jeva pridejo v besedilo
    (sicer bi bila trditev o A zelena nad praznim delom), A-jeva ne — ne
    vprašanje ne odgovor. Mejo same poizvedbe, mimo nabora, preverja primer
    `veljavna_vprasanja_snovi` v `PRIMERI_REPOZITORIJEV` (`ADR-049` E).
    """
    a, b = druzini

    odgovor = odjemalec.post(
        "/admin/transcripts", data={"subject": b.subject, "snov": [b.akt, a.akt]}
    )

    assert odgovor.status_code == 200
    assert f"1. V: Vprašanje 1 {b.znak}?" in odgovor.text
    assert f"O: Odgovor 1 {b.znak}." in odgovor.text
    assert f"Vprašanje 1 {a.znak}?" not in odgovor.text
    assert f"Odgovor 1 {a.znak}." not in odgovor.text
    assert f"Povzetek {a.znak}" not in odgovor.text


# --- Lastnik sistema (V3-R05) ---


@pytest.fixture
def lastnikov_odjemalec(
    aplikacija: FastAPI, motor: Engine, druzini: tuple[Druzina, Druzina]
) -> Iterator[PrijavljenOdjemalec]:
    """Odjemalec lastnika sistema, ki je starš družine **B**.

    Lastnik je vedno v neki družini (`ADR-025`), zato je A zanj tuja družina —
    natanko razmerje, ki ga `V3-R05` uvaja in ki ga je treba preizkusiti.
    """
    _, b = druzini
    lastnik = ustvari_starsa(
        motor,
        family_id=b.family_id,
        identifikator="lastnik@primer.test",
        prikazno_ime="Lastnik sistema",
        lastnik_sistema=True,
    )
    with PrijavljenOdjemalec(aplikacija, base_url="https://testserver") as odjemalec:
        prijavi(odjemalec, motor, lastnik)
        yield odjemalec


def test_lastnik_ne_vidi_vsebine_tuje_druzine(
    lastnikov_odjemalec: PrijavljenOdjemalec, druzini: tuple[Druzina, Druzina]
) -> None:
    """Kriterij 4: lastnik vidi imena, števila in stanje — **vsebine pa ne**.

    Imena in `id` staršev tuje družine sme videti, ker jim ponastavlja geslo in
    jih deaktivira; snovi, prepisov, povzetkov, kvizov, vprašanj in poskusov ne
    sme videti nikjer (`ADR-044` B). Zato `sledi_vsebine()` in ne `sledi()`.

    Test pomete čez **vse** strani lastnika, ki kaj kažejo, in ne samo čez
    seznam: nova stran, ki bi kdaj prikazala kaj več, pade tu.
    """
    a, _ = druzini
    strani = (
        "/admin/system",
        f"/admin/system/families/{a.family_id}",
        f"/admin/system/families/{a.family_id}/deactivate",
        f"/admin/system/families/{a.family_id}/parents/{a.stars_id}/password",
        f"/admin/system/families/{a.family_id}/parents/{a.stars_id}/deactivate",
    )

    for pot in strani:
        odgovor = lastnikov_odjemalec.get(pot)
        assert odgovor.status_code == 200, pot
        for sled in a.sledi_vsebine():
            assert sled not in odgovor.text, f"{pot} vsebuje sled vsebine tuje družine: {sled}"


def test_lastnik_tujo_druzino_vseeno_vidi(
    lastnikov_odjemalec: PrijavljenOdjemalec, druzini: tuple[Druzina, Druzina]
) -> None:
    """Test zgoraj ni prazen: ime tuje družine in njen starš sta na strani."""
    a, _ = druzini

    odgovor = lastnikov_odjemalec.get(f"/admin/system/families/{a.family_id}")

    assert "Cvek" in odgovor.text
    assert a.stars_id in odgovor.text


def test_lastnikova_dejanja_ne_spremenijo_vsebine_tuje_druzine(
    lastnikov_odjemalec: PrijavljenOdjemalec,
    motor: Engine,
    slike: Path,
    druzini: tuple[Druzina, Druzina],
) -> None:
    """Deaktivacija družine se dotakne **samo** zastavice in sej.

    Posnetek zajame vse vrstice in vse slike družine, zato bi vsako drugo
    spremembo — pobrisano snov, premaknjeno sliko, spremenjen kviz, ugasnjen
    račun člana — ujel. Izvzeti sta natanko dve stvari, ki se **smeta**
    spremeniti: zastavica družine in seje njenih članov (`ADR-044` A).

    Da seje res padejo, ni stvar tega testa — to trdi `tests/test_sistem.py`.
    Tu je vprašanje obratno: ali se je deaktivacija dotaknila česa drugega.
    """
    a, _ = druzini
    prej = _brez_stanja_in_sej(posnetek_druzine(motor, slike, a.family_id))

    odgovor = lastnikov_odjemalec.post(
        f"/admin/system/families/{a.family_id}/deactivate", follow_redirects=False
    )

    assert odgovor.status_code == 303
    assert _brez_stanja_in_sej(posnetek_druzine(motor, slike, a.family_id)) == prej


#: Tabeli, ki ju deaktivacija družine sme spremeniti: stanje in seje.
SME_SE_SPREMENITI = frozenset({"families", "sessions"})


def _brez_stanja_in_sej(
    posnetek: tuple[list[tuple[str, ...]], dict[str, bytes]],
) -> tuple[list[tuple[str, ...]], dict[str, bytes]]:
    """Posnetek brez tistega, kar deaktivacija sme spremeniti."""
    vrstice, datoteke = posnetek
    return [vrstica for vrstica in vrstice if vrstica[0] not in SME_SE_SPREMENITI], datoteke


#: Javne metode `DruzineRepository`, zapisane na roko.
#:
#: Varovalo `test_vsaka_javna_metoda_repozitorija_ima_primer` našteva pet
#: repozitorijev **z družino** in tega ne gleda — po `ADR-025` je ta edini, ki
#: sme brati čez vse. Prav zato potrebuje svoje: nova metoda tu je odločitev o
#: meji iz `ADR-044` E in ne sme nastati tiho, med pisanjem strani.
JAVNE_METODE_DRUZIN = {
    "edina",
    "idji",
    "idji_aktivnih",
    "nastavi_aktivnost",
    "poisci",
    "pregled",
    "ustvari_z_prvim_starsem",
}


def test_repozitorij_druzin_ima_zapisan_obseg() -> None:
    """Varovalo: nova javna metoda `DruzineRepository` podre zbirko.

    Ta razred je edini, ki bere čez družine, zato je vsaka njegova nova metoda
    vprašanje „sme to brati?" in ne podrobnost izvedbe.
    """
    javne = {
        ime
        for ime, clan in inspect.getmembers(DruzineRepository)
        if not ime.startswith("_") and callable(clan)
    }

    assert javne == JAVNE_METODE_DRUZIN


def test_repozitorij_druzin_ne_bere_podatkov_druzine(motor: Engine) -> None:
    """Meja iz `ADR-044` E: samo `families` in `users`, nikoli podatki.

    Trditev je o **stavkih, ki jih razred res izvede**, in ne o branju kode:
    poslušalec SQLAlchemy prestreže vsako poizvedbo, ki gre na bazo.
    """
    prestrezene: list[str] = []

    @event.listens_for(motor, "before_cursor_execute")
    def zabelezi(  # type: ignore[no-untyped-def]
        conn, cursor, stavek, parameters, context, executemany
    ) -> None:
        prestrezene.append(stavek.lower())

    try:
        with Session(motor) as seja:
            repo = DruzineRepository(seja)
            repo.pregled()
            repo.poisci(CVEK_ID)
            repo.idji()
            repo.idji_aktivnih()
            repo.edina()
            repo.nastavi_aktivnost(CVEK_ID, aktivna=False)
            # Tudi pisalna pot: če bi kdo vanjo dodal branje snovi ali kvizov,
            # bi brez tega klica varovalo ostalo zeleno.
            repo.ustvari_z_prvim_starsem(
                ime_druzine="Nova",
                prikazno_ime="Nov starš",
                identifier="nov@primer.test",
                secret_hash="zgostitev",
                ko=datetime.now(UTC),
            )
    finally:
        event.remove(motor, "before_cursor_execute", zabelezi)

    prepovedane = (
        "materials",
        "questions",
        "quizzes",
        "quiz_items",
        "question_attempts",
        "schedules",
        "schedule_entries",
    )
    for stavek in prestrezene:
        for tabela in prepovedane:
            assert tabela not in stavek, f"{tabela} v stavku: {stavek}"


# --- Repozitoriji ---


def _m(seja: Session, druzina: Druzina) -> MaterialsRepository:
    return MaterialsRepository(seja, druzina.family_id)


def _k(seja: Session, druzina: Druzina) -> KviziRepository:
    return KviziRepository(seja, druzina.family_id)


def _s(seja: Session, druzina: Druzina) -> StatistikaRepository:
    return StatistikaRepository(seja, druzina.family_id)


def _c(seja: Session, druzina: Druzina) -> ClaniRepository:
    return ClaniRepository(seja, druzina.family_id)


def _nalozi[T](seja: Session, model: type[T], identifikator: str) -> T:
    """Vrstica tuje družine, prebrana mimo repozitorija — kot bi jo podtaknil klicatelj."""
    najdeno = seja.get(model, identifikator)
    assert najdeno is not None
    return najdeno


def _vrze(napaka: type[Exception], klic: Callable[[], object]) -> bool:
    try:
        klic()
    except napaka:
        return True
    return False


def _utc(trenutek: datetime | None) -> datetime | None:
    """SQLite vrne naiven čas; primerjamo v UTC."""
    if trenutek is None or trenutek.tzinfo is not None:
        return trenutek
    return trenutek.replace(tzinfo=UTC)


def _poskus(postavka: str) -> PoskusZaZapis:
    return PoskusZaZapis(
        id=str(uuid4()),
        quiz_item_id=postavka,
        mode=NACIN_SAMOOCENA,
        rating="srednje",
        shown_at=POKAZANO,
        revealed_at=POKAZANO,
        answered_at=POKAZANO,
    )


#: Vsak primer v imenu **B** pokliče metodo z identifikatorji **A** in vrne, ali
#: je izid tak, kot mora biti. Kjer metoda vrača seznam, se preveri, da so v
#: njem natanko stvari B — ne le, da ni A.
Preverba = Callable[[Session, Druzina, Druzina], bool]

PRIMERI_REPOZITORIJEV: dict[tuple[str, str], Preverba] = {
    # ScheduleRepository (V3-R09). Urnik je last otroka, zato je tu sled
    # **tuj otrok**: potrditev zanj ne sme zapisati ničesar, branje pa ne sme
    # vrniti ničesar — tudi kadar urnik v resnici obstaja, le v drugi družini.
    ("ScheduleRepository", "potrdi"): lambda s, a, b: (
        ScheduleRepository(s, b.family_id).potrdi(
            a.otrok_id, [Vnos(dan=0, predmet="MAT")], None
        )
        is None
    ),
    ("ScheduleRepository", "urnik"): lambda s, a, b: (
        ScheduleRepository(s, b.family_id).urnik(a.otrok_id) is None
    ),
    ("ScheduleRepository", "veljaven"): lambda s, a, b: (
        ScheduleRepository(s, b.family_id).veljaven(a.otrok_id) is None
    ),
    # MaterialsRepository
    ("MaterialsRepository", "arhiviraj"): lambda s, a, b: _m(s, b).arhiviraj(a.akt) is None,
    ("MaterialsRepository", "nazadnje_prejeto"): lambda s, a, b: (
        _utc(_m(s, b).nazadnje_prejeto()) == b.prejeto
    ),
    ("MaterialsRepository", "obnovi_obticale"): lambda s, a, b: (
        _m(s, b).obnovi_obticale() == 1
    ),
    ("MaterialsRepository", "obstaja"): lambda s, a, b: _m(s, b).obstaja(a.akt) is False,
    ("MaterialsRepository", "pobrisi"): lambda s, a, b: _m(s, b).pobrisi(a.arh) is None,
    ("MaterialsRepository", "poisci"): lambda s, a, b: _m(s, b).poisci(a.akt) is None,
    ("MaterialsRepository", "potrdi_brisanje"): lambda s, a, b: (
        _m(s, b).potrdi_brisanje([a.za_brisanje]) == 0
    ),
    ("MaterialsRepository", "prevzemi_za_obdelavo"): lambda s, a, b: (
        _m(s, b).prevzemi_za_obdelavo(a.nova) is False
    ),
    ("MaterialsRepository", "premakni_v_predmet"): lambda s, a, b: (
        _m(s, b).premakni_v_predmet(a.akt, "SLJ") is False
    ),
    ("MaterialsRepository", "seznam_arhiviranih"): lambda s, a, b: (
        {x.id for x in _m(s, b).seznam_arhiviranih()} == {b.arh, b.za_brisanje}
    ),
    ("MaterialsRepository", "seznam_novih"): lambda s, a, b: (
        [x.id for x in _m(s, b).seznam_novih()] == [b.nova]
    ),
    ("MaterialsRepository", "seznam_po_obdobju"): lambda s, a, b: (
        {
            x.id
            for x in _m(s, b).seznam_po_obdobju(
                b.posneto - timedelta(days=1), b.posneto + timedelta(days=1), b.otrok_id
            )
        }
        == {b.akt, b.nova, b.obticala}
    ),
    ("MaterialsRepository", "seznam_po_predmetu"): lambda s, a, b: (
        _m(s, b).seznam_po_predmetu(a.subject) == []
    ),
    ("MaterialsRepository", "seznam_za_brisanje"): lambda s, a, b: (
        _m(s, b).seznam_za_brisanje() == [b.za_brisanje]
    ),
    ("MaterialsRepository", "sosedi_v_predmetu"): lambda s, a, b: (
        _m(s, b).sosedi_v_predmetu(_nalozi(s, Material, a.akt)) == (None, None)
    ),
    ("MaterialsRepository", "sprosti_prevzem"): lambda s, a, b: (
        _m(s, b).sprosti_prevzem(a.obticala) is False
    ),
    ("MaterialsRepository", "stej_arhivirane"): lambda s, a, b: _m(s, b).stej_arhivirane() == 2,
    ("MaterialsRepository", "stej_po_predmetih"): lambda s, a, b: (
        _m(s, b).stej_po_predmetih() == {b.subject: 3}
    ),
    # V3-R12. Tuj identifikator v vhodu; poizvedba nosi mejo sama (`ADR-049`
    # E). Svoja vprašanja pridejo — sicer bi bila trditev zelena nad praznim.
    ("MaterialsRepository", "veljavna_vprasanja_snovi"): lambda s, a, b: (
        {
            material_id: [v.id for v in vprasanja]
            for material_id, vprasanja in _m(s, b)
            .veljavna_vprasanja_snovi([a.akt, b.akt])
            .items()
        }
        == {b.akt: list(b.vprasanja)}
    ),
    ("MaterialsRepository", "vrni_v_vrsto"): lambda s, a, b: (
        _m(s, b).vrni_v_vrsto(a.akt) is False
    ),
    ("MaterialsRepository", "vstavi_ce_ga_ni"): lambda s, a, b: (
        _m(s, b).vstavi_ce_ga_ni(
            Material(
                child_id=OTROK_ID,
                id=a.akt,
                family_id=b.family_id,
                subject=b.subject,
                taken_at=b.posneto,
                image_path="/nikamor.jpg",
                status=STATUS_NOV,
                received_at=b.prejeto,
            )
        )
        is False
    ),
    ("MaterialsRepository", "zapisi_izid"): lambda s, a, b: (
        _m(s, b).zapisi_izid(a.akt, IzidObdelave(status=STATUS_PRIPRAVLJEN)) is False
    ),
    # KviziRepository
    # Dva vdora na isti poti, zato dva primera v enem: tuje vprašanje **in**
    # tuj naslovljenec. Oba sta `ValueError` (`ADR-039` A); usmerjevalnik
    # drugega prestreže prej in naredi 404.
    ("KviziRepository", "objavi"): lambda s, a, b: _vrze(
        ValueError,
        lambda: _k(s, b).objavi(
            "Vdor", a.subject, [_nalozi(s, Question, a.vprasanja[0])], b.otrok_id
        ),
    )
    and _vrze(
        ValueError,
        lambda: _k(s, b).objavi(
            "Vdor", b.subject, [_nalozi(s, Question, b.vprasanja[0])], a.otrok_id
        ),
    ),
    ("KviziRepository", "poisci"): lambda s, a, b: _k(s, b).poisci(a.resen_kviz) is None,
    ("KviziRepository", "poskusi_kviza"): lambda s, a, b: (
        _k(s, b).poskusi_kviza(a.resen_kviz) == {}
    ),
    ("KviziRepository", "preklici"): lambda s, a, b: _k(s, b).preklici(a.odprt_kviz) is None,
    ("KviziRepository", "seznam"): lambda s, a, b: (
        {kviz.id for kviz, _ in _k(s, b).seznam()} == {b.resen_kviz, b.odprt_kviz}
    ),
    ("KviziRepository", "seznam_za_telefon"): lambda s, a, b: (
        [c.kviz.id for c in _k(s, b).seznam_za_telefon(b.otrok_id)] == [b.odprt_kviz]
    ),
    ("KviziRepository", "snovi_postavk"): lambda s, a, b: (
        _k(s, b).snovi_postavk(_nalozi(s, Quiz, a.resen_kviz)) == {}
    ),
    ("KviziRepository", "snovi_z_vprasanji"): lambda s, a, b: (
        _k(s, b).snovi_z_vprasanji([a.akt], 3) == []
    ),
    ("KviziRepository", "snovi_za_izbor"): lambda s, a, b: (
        {x.material.id for x in _k(s, b).snovi_za_izbor(b.otrok_id)}
        == {b.akt, b.nova, b.obticala}
    ),
    ("KviziRepository", "vprasanja_po_idjih"): lambda s, a, b: (
        _k(s, b).vprasanja_po_idjih([a.vprasanja[0]]) is None
    ),
    ("KviziRepository", "zapisi_poskuse"): lambda s, a, b: (
        _k(s, b).zapisi_poskuse([_poskus(a.postavka_odprtega)], b.otrok_id) is None
    ),
    # StatistikaRepository
    ("StatistikaRepository", "casi_poskusov"): lambda s, a, b: (
        len(_s(s, b).casi_poskusov(b.otrok_id)) == len(b.poskusi)
        and _s(s, b).casi_poskusov(a.otrok_id) == []
    ),
    ("StatistikaRepository", "ima_poskuse"): lambda s, a, b: (
        _s(s, b).ima_poskuse(a.subject, b.otrok_id) is False
        and _s(s, b).ima_poskuse(b.subject, a.otrok_id) is False
    ),
    ("StatistikaRepository", "poskusi"): lambda s, a, b: (
        {p.quiz_id for p in _s(s, b).poskusi(b.otrok_id)} == {b.resen_kviz}
        and _s(s, b).poskusi(a.otrok_id) == []
    ),
    ("StatistikaRepository", "snovi"): lambda s, a, b: _s(s, b).snovi([a.akt]) == {},
    # ClaniRepository (V3-R06)
    ("ClaniRepository", "aktivnih_starsev"): lambda s, a, b: _c(s, b).aktivnih_starsev() == 1,
    ("ClaniRepository", "clan"): lambda s, a, b: _c(s, b).clan(a.stars_id) is None,
    ("ClaniRepository", "clani"): lambda s, a, b: (
        {clan.user_id for clan in _c(s, b).clani()} == {b.stars_id, b.otrok_id}
    ),
    ("ClaniRepository", "nastavi_aktivnost"): lambda s, a, b: (
        _c(s, b).nastavi_aktivnost(a.otrok_id, aktiven=False) is False
    ),
    # Nova v `V3-R07`: vir izbirnika otroka in privzetka. Tuj otrok se v njej
    # ne sme pojaviti — sicer bi ga izbirnik ponudil in `?otrok=` bi ga sprejel.
    ("ClaniRepository", "otroci"): lambda s, a, b: (
        {clan.user_id for clan in _c(s, b).otroci()} == {b.otrok_id}
        and {clan.user_id for clan in _c(s, b).otroci(samo_aktivni=True)} == {b.otrok_id}
    ),
    ("ClaniRepository", "ponastavi_geslo"): lambda s, a, b: (
        _c(s, b).ponastavi_geslo(a.otrok_id, "vlomljena-zgostitev", datetime.now(UTC)) is False
    ),
    # Enoličnost identifikatorja je **globalna** (`ADR-038` E), zato ta klic ne
    # more uspeti — a mora pasti na bazi in ne na poizvedbi čez tujo družino,
    # in ne sme pustiti vrstice ne tu ne tam.
    ("ClaniRepository", "ustvari_clana"): lambda s, a, b: _vrze(
        IdentifikatorZaseden,
        lambda: _c(s, b).ustvari_clana(
            role=VLOGA_OTROK,
            display_name="Vrinjen otrok",
            identifier=f"otrok-{a.znak}".lower(),
            secret_hash="vlomljena-zgostitev",
            ko=datetime.now(UTC),
        ),
    ),
}


def test_vsaka_javna_metoda_repozitorija_ima_primer() -> None:
    """Varovalo: nova javna metoda brez primera tu podre zbirko."""
    javne = {
        (razred.__name__, ime)
        for razred in (
            MaterialsRepository,
            KviziRepository,
            StatistikaRepository,
            ClaniRepository,
            ScheduleRepository,
        )
        for ime, clan in inspect.getmembers(razred)
        if not ime.startswith("_") and callable(clan)
    }

    assert javne == set(PRIMERI_REPOZITORIJEV)


@pytest.mark.parametrize("primer", sorted(PRIMERI_REPOZITORIJEV), ids=".".join)
def test_repozitorij_ne_vidi_in_ne_spremeni_tuje_druzine(
    primer: tuple[str, str],
    motor: Engine,
    slike: Path,
    druzini: tuple[Druzina, Druzina],
) -> None:
    a, b = druzini
    prej = posnetek_druzine(motor, slike, a.family_id)

    with Session(motor) as seja:
        assert PRIMERI_REPOZITORIJEV[primer](seja, a, b)

    assert posnetek_druzine(motor, slike, a.family_id) == prej
