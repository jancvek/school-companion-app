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
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, Select, select
from sqlalchemy.orm import Session

from app.db import (
    IzidObdelave,
    KviziRepository,
    MaterialsRepository,
    PoskusZaZapis,
    StatistikaRepository,
)
from app.dependencies import daj_druzino_telefona
from app.models import (
    NACIN_SAMOOCENA,
    STATUS_NOV,
    STATUS_PRIPRAVLJEN,
    STATUS_V_OBDELAVI,
    Base,
    Material,
    Question,
    QuestionAttempt,
    Quiz,
    User,
)
from tests.conftest import CVEK_ID, KLJUC, PrijavljenOdjemalec, prijavi, ustvari_starsa
from tests.test_druzine import DRUGA_ID, dodaj_druzino
from tests.test_kvizi import objavi
from tests.test_resevanje import POKAZANO, poskus, poslji
from tests.test_rezultat import postavke

GLAVE = {"X-API-Key": KLJUC}

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

    def sledi(self) -> tuple[str, ...]:
        """Nizi, ki v odgovoru druge družine ne smejo nastopiti."""
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

    with Session(motor) as seja:
        for vloga, material_id in idji.items():
            pot = slike / family_id / f"{material_id}.jpg"
            pot.parent.mkdir(parents=True, exist_ok=True)
            pot.write_bytes(f"slika {znak} {vloga}".encode())
            material = Material(
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

    # Kvizi in poskusi skozi prave poti, v imenu te družine. Admin pot pove
    # družino prek **seje** (V3-R03), pot telefona prek začasne odvisnosti, ki
    # jo bo `V3-R04` zamenjal z žetonom — zato tu oboje.
    prijavi(odjemalec, motor, ustvari_starsa(motor, family_id=family_id, identifikator=znak))
    aplikacija.dependency_overrides[daj_druzino_telefona] = lambda: family_id
    resen = objavi(
        odjemalec, motor, [idji["akt"]], koliko=3, subject=subject, vstop="rocna",
        ime=f"Rešen {znak}",
    )
    postavke_resenega = postavke(motor, resen)
    odgovor = poslji(odjemalec, [poskus(p) for p in postavke_resenega])
    assert odgovor.status_code == 200, odgovor.text
    odprt = objavi(
        odjemalec, motor, [idji["akt"]], koliko=3, subject=subject, vstop="rocna",
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
    dodaj_druzino(motor)
    zdaj = datetime.now(UTC)
    a = _zgradi(
        aplikacija, odjemalec, motor, slike,
        family_id=CVEK_ID, subject="ZGO", znak="SKRIVNOST-A", prejeto=zdaj,
    )
    b = _zgradi(
        aplikacija, odjemalec, motor, slike,
        family_id=DRUGA_ID, subject="MAT", znak="SKRIVNOST-B", prejeto=zdaj - timedelta(hours=2),
    )
    # `_zgradi` je odjemalca nazadnje prijavil kot starša B in začasno družino
    # telefona nastavil na B; to je stanje, v katerem testi tečejo.
    assert aplikacija.dependency_overrides[daj_druzino_telefona]() == b.family_id
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


# --- Poti ---

OK = frozenset({200})
NI = frozenset({404})
PREUSMERITEV = frozenset({303})

#: (odgovor, dovoljeni statusi, poslani identifikatorji tuje družine)
Klic = Callable[[TestClient, Druzina], tuple[Any, frozenset[int], tuple[str, ...]]]

def _prijava_s_tujim_racunom(odjemalec: TestClient, tuja: Druzina) -> Any:
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


PRIMERI_POTI: dict[tuple[str, str], Klic] = {
    ("GET", "/health"): lambda o, a: (o.get("/health"), OK, ()),
    ("GET", "/admin"): lambda o, a: (o.get("/admin"), OK, ()),
    ("GET", "/admin/archive"): lambda o, a: (o.get("/admin/archive"), OK, ()),
    ("GET", "/admin/days"): lambda o, a: (o.get("/admin/days?obdobje=teden"), OK, ()),
    ("GET", "/admin/subjects/{koda}"): lambda o, a: (
        o.get(f"/admin/subjects/{a.subject}"), OK, (),
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
        o.get(f"/admin/quizzes/{a.resen_kviz}"), NI, (a.resen_kviz,),
    ),
    ("GET", "/admin/quizzes/{quiz_id}/print"): lambda o, a: (
        o.get(f"/admin/quizzes/{a.resen_kviz}/print"), NI, (a.resen_kviz,),
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
        _prijava_s_tujim_racunom(o, a), frozenset({401}), (a.znak,),
    ),
    ("POST", "/admin/logout"): lambda o, a: (
        o.post("/admin/logout", follow_redirects=False), PREUSMERITEV, (),
    ),
    ("GET", "/admin/statistics"): lambda o, a: (o.get("/admin/statistics?leto=vse"), OK, ()),
    ("GET", "/admin/statistics/subjects/{koda}"): lambda o, a: (
        o.get(f"/admin/statistics/subjects/{a.subject}?leto=vse"), OK, (),
    ),
    ("POST", "/materials"): lambda o, a: (
        o.post(
            "/materials",
            data={"id": a.akt, "subject": a.subject, "taken_at": "2026-09-04T07:30:00Z"},
            files={"file": ("posnetek.jpg", b"ponaredek", "image/jpeg")},
            headers=GLAVE,
        ),
        frozenset({409}),
        (a.akt,),
    ),
    ("GET", "/materials/pending-deletion"): lambda o, a: (
        o.get("/materials/pending-deletion", headers=GLAVE), OK, (),
    ),
    ("POST", "/materials/deleted-on-device"): lambda o, a: (
        o.post(
            "/materials/deleted-on-device", json={"ids": [a.za_brisanje]}, headers=GLAVE
        ),
        OK,
        (a.za_brisanje,),
    ),
    ("GET", "/quizzes/pending"): lambda o, a: (o.get("/quizzes/pending", headers=GLAVE), OK, ()),
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
    odjemalec: TestClient,
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
    odjemalec: TestClient, druzini: tuple[Druzina, Druzina]
) -> None:
    """Test zgoraj ni prazen: iste poti družini B njene podatke pokažejo."""
    _, b = druzini

    assert b.akt in odjemalec.get(f"/admin/subjects/{b.subject}").text
    assert b.arh in odjemalec.get("/admin/archive").text
    assert b.znak in odjemalec.get(f"/admin/statistics/subjects/{b.subject}?leto=vse").text
    assert b.odprt_kviz in odjemalec.get("/quizzes/pending", headers=GLAVE).text
    assert b.za_brisanje in odjemalec.get("/materials/pending-deletion", headers=GLAVE).text


# --- Repozitoriji ---


def _m(seja: Session, druzina: Druzina) -> MaterialsRepository:
    return MaterialsRepository(seja, druzina.family_id)


def _k(seja: Session, druzina: Druzina) -> KviziRepository:
    return KviziRepository(seja, druzina.family_id)


def _s(seja: Session, druzina: Druzina) -> StatistikaRepository:
    return StatistikaRepository(seja, druzina.family_id)


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
                b.posneto - timedelta(days=1), b.posneto + timedelta(days=1)
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
    ("MaterialsRepository", "vrni_v_vrsto"): lambda s, a, b: (
        _m(s, b).vrni_v_vrsto(a.akt) is False
    ),
    ("MaterialsRepository", "vstavi_ce_ga_ni"): lambda s, a, b: (
        _m(s, b).vstavi_ce_ga_ni(
            Material(
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
    ("KviziRepository", "objavi"): lambda s, a, b: _vrze(
        ValueError,
        lambda: _k(s, b).objavi("Vdor", a.subject, [_nalozi(s, Question, a.vprasanja[0])]),
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
        [c.kviz.id for c in _k(s, b).seznam_za_telefon()] == [b.odprt_kviz]
    ),
    ("KviziRepository", "snovi_postavk"): lambda s, a, b: (
        _k(s, b).snovi_postavk(_nalozi(s, Quiz, a.resen_kviz)) == {}
    ),
    ("KviziRepository", "snovi_z_vprasanji"): lambda s, a, b: (
        _k(s, b).snovi_z_vprasanji([a.akt], 3) == []
    ),
    ("KviziRepository", "snovi_za_izbor"): lambda s, a, b: (
        {x.material.id for x in _k(s, b).snovi_za_izbor()} == {b.akt, b.nova, b.obticala}
    ),
    ("KviziRepository", "vprasanja_po_idjih"): lambda s, a, b: (
        _k(s, b).vprasanja_po_idjih([a.vprasanja[0]]) is None
    ),
    ("KviziRepository", "zapisi_poskuse"): lambda s, a, b: (
        _k(s, b).zapisi_poskuse([_poskus(a.postavka_odprtega)]) is None
    ),
    # StatistikaRepository
    ("StatistikaRepository", "casi_poskusov"): lambda s, a, b: (
        len(_s(s, b).casi_poskusov()) == len(b.poskusi)
    ),
    ("StatistikaRepository", "ima_poskuse"): lambda s, a, b: (
        _s(s, b).ima_poskuse(a.subject) is False
    ),
    ("StatistikaRepository", "poskusi"): lambda s, a, b: (
        {p.quiz_id for p in _s(s, b).poskusi()} == {b.resen_kviz}
    ),
    ("StatistikaRepository", "snovi"): lambda s, a, b: _s(s, b).snovi([a.akt]) == {},
}


def test_vsaka_javna_metoda_repozitorija_ima_primer() -> None:
    """Varovalo: nova javna metoda brez primera tu podre zbirko."""
    javne = {
        (razred.__name__, ime)
        for razred in (MaterialsRepository, KviziRepository, StatistikaRepository)
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
