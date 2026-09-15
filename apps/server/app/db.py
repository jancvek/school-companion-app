"""Motor, seja in tanka plast nad tabelama `materials` in `questions`.

Poslovna logika govori z `MaterialsRepository`, ne s SQLAlchemy neposredno —
tako testi tečejo nad SQLite v pomnilniku, produkcija pa nad Postgresom, in
oboje skozi isto kodo.

**Vsak repozitorij podatkov pripada eni družini** (`docs/odlocitve/ADR-025`):
`family_id` je obvezen argument konstruktorja, vsaka poizvedba in vsak
`UPDATE` ima pogoj družine, `Session.get` se nad podatki ne uporablja (gre mimo
vsakega pogoja) in seja je zasebna. `DruzineRepository` bere samo tabelo
`families`, nikoli podatkov družine.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import (
    ColumnElement,
    CursorResult,
    Engine,
    create_engine,
    func,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker
from sqlalchemy.sql import Update

from app.models import (
    NACIN_SAMOOCENA,
    STATUS_NOV,
    STATUS_PRIPRAVLJEN,
    STATUS_V_OBDELAVI,
    Family,
    Material,
    Question,
    QuestionAttempt,
    Quiz,
    QuizItem,
)


@dataclass(frozen=True)
class VprasanjeZaZapis:
    """Eno vprašanje z odgovorom, pripravljeno za zapis."""

    question: str
    answer: str


@dataclass(frozen=True)
class IzidObdelave:
    """Kar se ob koncu obdelave zapiše v vrstico `materials`.

    Ta tip živi tu in ne v `app/vision.py`, ker opisuje **zapis v bazo**, ne
    odgovora modela. Zaradi tega `app/db.py` ne ve za OpenAI in `openai` se
    uvaža na natanko enem mestu (ADR-008, odločitev 1 v `docs/plan/V1-R03.md`).

    Revizijska sled (`prompt`, `raw_response`, `model`, tokena) je del izida
    tudi pri napaki: neuspel klic je bil plačan enako kot uspešen, in surov
    odgovor je takrat pogosto edini dokaz, zakaj je padlo.
    """

    status: str
    readable: bool | None = None
    transcript: str | None = None
    summary: str | None = None
    prompt: str | None = None
    raw_response: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
    vprasanja: tuple[VprasanjeZaZapis, ...] = field(default_factory=tuple)


def naredi_motor(database_url: str) -> Engine:
    """Motor za dano povezavo.

    `pool_pre_ping` zato, ker Postgres v Compose lahko vstane pozneje od API-ja
    in ker povezava čez noč odmre; brez tega bi prva zahteva zjutraj padla.
    """
    return create_engine(database_url, pool_pre_ping=True, future=True)


def naredi_tovarno_sej(motor: Engine) -> sessionmaker[Session]:
    """Tovarna sej za dani motor."""
    return sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)


def _nabor_predmeta(family_id: str, subject: str) -> tuple[ColumnElement[bool], ...]:
    """Pogoji, ki določajo slike enega predmeta: ta družina, ta predmet, brez arhiva.

    Na enem mestu, ker ga bereta `seznam_po_predmetu` in `sosedi_v_predmetu`
    (V2-R08). Povečan prikaz obljublja isti nabor kot stran predmeta, in dva
    ločeno napisana filtra bi se nekoč razšla po tihem.
    """
    return (
        Material.family_id == family_id,
        Material.subject == subject,
        Material.archived_at.is_(None),
    )


#: Vrstni red slik predmeta: najnovejša prva, ob enakem času odloči `id`.
#:
#: Brez drugega ključa je vrstni red dveh slik z istim `taken_at` nedoločen —
#: na strani predmeta je to nevidno, listanje v povečanem prikazu pa bi eno od
#: njiju preskočilo ali se med njima vrtelo (V2-R08).
_VRSTNI_RED_PREDMETA = (Material.taken_at.desc(), Material.id.desc())


class DruzineRepository:
    """Branje tabele `families` — edini repozitorij brez družine.

    Ne bere podatkov nobene družine, zato ni obvoz iz `ADR-025`. Potrebujeta ga
    obdelava v ozadju, ki gre po družinah (`docs/odlocitve/ADR-029` B), in
    začasna izbira družine pred prijavo (`app/dependencies.py`, `ADR-029` A).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def idji(self) -> list[str]:
        """`id` vseh družin, najstarejša prva."""
        return list(
            self._session.scalars(select(Family.id).order_by(Family.created_at, Family.id))
        )

    def edina(self) -> str | None:
        """`id` edine družine, ali `None`, kadar jih ni natanko ena."""
        idji = list(self._session.scalars(select(Family.id).limit(2)))
        return idji[0] if len(idji) == 1 else None


class _RepozitorijDruzine:
    """Seja in družina — skupna osnova vseh repozitorijev podatkov.

    `family_id` je obvezen in brez privzetka (`docs/odlocitve/ADR-025`). Prazen
    niz je napaka že tu: repozitorij, ki bi tiho bral „nobeno" družino, bi bil
    videti kot prazna družina in napaka v izbiri družine bi bila nevidna.

    Seja je zasebna, da je usmerjevalnik ne more vzeti in poizvedovati mimo
    repozitorija.
    """

    def __init__(self, session: Session, family_id: str) -> None:
        if not family_id:
            raise ValueError("Repozitorij brez družine ne obstaja (docs/odlocitve/ADR-025).")
        self._session = session
        self._family_id = family_id

    @property
    def family_id(self) -> str:
        """Družina, katere podatke ta repozitorij bere in piše."""
        return self._family_id


class MaterialsRepository(_RepozitorijDruzine):
    """Operacije nad tabelo `materials` ene družine (V1-R02, V1-R04, V3-R01)."""

    def _moje(self) -> ColumnElement[bool]:
        """Pogoj družine nad `materials`; na enem mestu, da ga nobena poizvedba ne pozabi."""
        return Material.family_id == self._family_id

    def poisci(self, material_id: str) -> Material | None:
        """Zapis z danim `id` v tej družini ali `None`.

        Poizvedba in ne `Session.get`: ta išče samo po primarnem ključu in bi
        vrnil zapis tuje družine.
        """
        return self._session.scalars(
            select(Material).where(Material.id == material_id, self._moje())
        ).one_or_none()

    def obstaja(self, material_id: str) -> bool:
        """Ali zapis z danim `id` že obstaja."""
        return self.poisci(material_id) is not None

    def vstavi_ce_ga_ni(self, material: Material) -> bool:
        """Vstavi zapis; vrne `True`, če je nastal, in `False`, če ga je že bilo.

        Preverba pred vstavljanjem pokrije običajni primer (telefon pošlje isti
        `id` znova, ker prvega odgovora ni dočakal). `IntegrityError` pokrije
        tekmovanje dveh hkratnih zahtev z istim `id`: takrat je zmagala prva in
        to za klicatelja pomeni isto — zapis obstaja, ni ga ustvaril on.

        **Zapis mora nositi družino tega repozitorija.** Zapis brez družine ali
        s tujo je `ValueError` (plan V3-R01, odločitev 2): klicatelj družino
        vzame iz `family_id` repozitorija, ne iz zahteve.

        `id` je globalen primarni ključ. Zapis z `id`, ki obstaja v **drugi**
        družini, pade na istem `IntegrityError` in vrne `False`; klicatelj ga
        od tekmovanja loči s `poisci`, ki v tej družini ne najde ničesar
        (`docs/odlocitve/ADR-029` D).
        """
        if material.family_id != self._family_id:
            raise ValueError("Zapis mora nositi družino tega repozitorija, ne tuje ali prazne.")

        if self.obstaja(material.id):
            return False

        try:
            self._session.add(material)
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            return False

        return True

    def stej_po_predmetih(self) -> dict[str, int]:
        """Koliko zapisov je pri katerem predmetu.

        Vrne samo predmete, ki v bazi res so. Kateri predmeti se pokažejo tudi
        s številom nič, je odločitev vmesnika, ne baze.
        """
        vrstice = self._session.execute(
            select(Material.subject, func.count())
            .where(self._moje(), Material.archived_at.is_(None))
            .group_by(Material.subject)
        ).all()
        return {subject: koliko for subject, koliko in vrstice}

    def seznam_po_predmetu(self, subject: str) -> list[Material]:
        """Zapisi enega predmeta, od najnovejšega navzdol.

        Vrstni red je enak kot v zgodovini na telefonu (`taken_at DESC`), da
        isti posnetek na obeh straneh stoji na istem mestu.
        """
        return list(
            self._session.scalars(
                select(Material)
                .where(*_nabor_predmeta(self._family_id, subject))
                .order_by(*_VRSTNI_RED_PREDMETA)
            )
        )

    def sosedi_v_predmetu(self, material: Material) -> tuple[str | None, str | None]:
        """`id` slike pred `material` in za njim v `seznam_po_predmetu`.

        Za povečan prikaz (V2-R08). `None` pomeni rob nabora — ovijanja ni.
        Arhivirane snovi v naboru ni, zato zanjo poizvedbe sploh ni.

        Bere samo stolpec `id` in ne cele vrstice: `seznam_po_predmetu` bi za
        dva identifikatorja naložil prepise in revizijsko sled celotnega
        predmeta. Seznam je v Pythonu, ker primerjava para `(taken_at, id)` v
        SQL ni enako zapisljiva nad SQLite (testi) in Postgresom.
        """
        if material.archived_at is not None:
            return None, None

        idji = list(
            self._session.scalars(
                select(Material.id)
                .where(*_nabor_predmeta(self._family_id, material.subject))
                .order_by(*_VRSTNI_RED_PREDMETA)
            )
        )
        if material.id not in idji:
            return None, None

        mesto = idji.index(material.id)
        prejsnji = idji[mesto - 1] if mesto > 0 else None
        naslednji = idji[mesto + 1] if mesto + 1 < len(idji) else None
        return prejsnji, naslednji

    def seznam_po_obdobju(self, od: datetime, do: datetime) -> list[Material]:
        """Nearhivirane slike, posnete v polodprtem intervalu `[od, do)`.

        Čez vse predmete in **naraščajoče** po `taken_at` — obratno kot
        `seznam_po_predmetu`. Zaporedni posnetki so strani iste snovi
        (`docs/odlocitve/ADR-003`), zato jih pregled po dnevih (V2-R07) bere v
        vrstnem redu, v katerem so nastali.

        Meji dobi kot par trenutkov v UTC; o časovnih pasovih in o tem, kateri
        lokalni dan je to, repozitorij ne ve nič. Grupiranje po lokalnem dnevu
        je zato v Pythonu — izraz za lokalni dan v SQL ni prenosljiv med SQLite
        (testi) in Postgresom (produkcija), `docs/odlocitve/ADR-023`.
        """
        return list(
            self._session.scalars(
                select(Material)
                .where(
                    self._moje(),
                    Material.archived_at.is_(None),
                    Material.taken_at >= od,
                    Material.taken_at < do,
                )
                .order_by(Material.taken_at)
            )
        )

    def nazadnje_prejeto(self) -> datetime | None:
        """Kdaj je strežnik nazadnje prevzel sliko; `None`, če še nikoli.

        Šteje **vse** zapise družine, tudi arhivirane: vprašanje je, ali je telefon
        slike prenesel, ne ali so še v pregledu. Brez tega bi bil prazen dan
        videti enako kot dan, ko telefon še ni prenašal (V2-R07,
        `docs/odlocitve/ADR-023`).
        """
        return self._session.scalar(
            select(func.max(Material.received_at)).where(self._moje())
        )

    # --- Obdelava (V1-R03) ---

    def _posodobi(self, stavek: Update) -> int:
        """Izvede `UPDATE` in vrne, koliko vrstic je zadel.

        `Session.execute` je tipiziran kot `Result`, ki `rowcount` ne pozna;
        pri `UPDATE` je izid vedno `CursorResult`. `cast` je zato tu, na enem
        mestu, in ne ob vsakem klicu.

        `synchronize_session=False`: stanje beremo nazaj iz baze, ne iz
        predmetov v seji — te metode se kličejo iz obdelave, ki ima za vsak
        korak svojo sejo.
        """
        izid = cast(
            "CursorResult[Any]",
            self._session.execute(stavek.execution_options(synchronize_session=False)),
        )
        self._session.commit()
        return int(izid.rowcount)

    def _upokoji_vprasanja(self, material: Material) -> None:
        """Upokoji vsa veljavna vprašanja danega materiala. **Nič ne pobriše.**

        Do V2-R05 je ta metoda vprašanja izbrisala. `docs/odlocitve/ADR-015`
        to nadomesti: kviz `V2-R01` kaže na `question_id` in statistika
        `V2-R04` stoji na tem, da vprašanje ohrani identiteto čez ponovne
        obdelave — brisanje bi oboje tiho razbilo.

        Pogoj `retired_at IS NULL` ni okras: brez njega bi druga ponovna
        obdelava premaknila žig prve serije in serije se ne bi več ločile.
        Isti vzorec kot pri `arhiviraj` in `potrdi_brisanje`.

        Vsa vprašanja ene serije dobijo **isti** žig, ker je izračunan enkrat
        pred stavkom in ne v bazi.

        **Brez `commit`.** Klicatelja commitata sama: upokojitev in vstavitev
        nove serije morata biti ena transakcija, sicer obstaja trenutek, ko
        material nima nobenega veljavnega vprašanja — in `V2-R01` bi ga v
        izbirniku tako tudi videl.

        Stavek gre mimo seje, zato za sabo pospravi dvoje:

        - `synchronize_session="fetch"` postavi `retired_at` tudi na predmetih
          `Question`, ki so v tej seji že naloženi. Brez tega bi bralec, ki je
          vprašanja prebral **pred** upokojitvijo in jih v isti seji uporablja
          naprej — natanko to bo delal izbirnik `V2-R01` — na njih še vedno
          videl `retired_at = None`, čeprav ima vrstica v bazi žig. To je isti
          razred napake, ki ga sveža baza ne pokaže, pred katerim svari
          `ADR-015`. Tu je `"fetch"` in ne `False` kot v `_posodobi`, ker ta
          metoda dela v isti seji kot predmet, ki ga je klicatelj že prebral.
        - `expire` razveljavi vse tri zbirke, ker se jim je spremenilo
          članstvo; sicer bi `veljavna_vprasanja` še vedno vračala predmete,
          ki v bazi niso več veljavni.
        """
        self._session.execute(
            update(Question)
            .where(
                Question.family_id == self._family_id,
                Question.material_id == material.id,
                Question.retired_at.is_(None),
            )
            .values(retired_at=datetime.now(UTC))
            .execution_options(synchronize_session="fetch")
        )
        self._session.expire(
            material, ["vsa_vprasanja", "veljavna_vprasanja", "upokojena_vprasanja"]
        )

    def seznam_novih(self) -> list[Material]:
        """Zapisi, ki čakajo na obdelavo, od najstarejšega naprej.

        `taken_at ASC` in ne `DESC` kot v zgodovini: v vrsti naj najstarejša
        slika ne čaka najdlje. Isti razlog kot pri čakalni vrsti na telefonu.
        """
        return list(
            self._session.scalars(
                select(Material)
                .where(
                    self._moje(),
                    Material.status == STATUS_NOV,
                    Material.archived_at.is_(None),
                )
                .order_by(Material.taken_at.asc())
            )
        )

    def prevzemi_za_obdelavo(self, material_id: str) -> bool:
        """Premakne zapis iz `new` v `processing`; vrne, ali je prevzem uspel.

        Pogojni `UPDATE` in ne branje s poznejšim pisanjem: pogoj
        `status = 'new'` opravi bazo, zato dva hkratna prevzemnika ne moreta
        oba dobiti `True`. Danes teče en sam proces `uvicorn` in tekmovanja ni
        — pogoj je tu zato, da ga tudi ne bo, če kdaj kdo doda `--workers`
        (odločitev 4 v `docs/plan/V1-R03.md`).
        """
        return self._posodobi(
            update(Material)
            .where(self._moje(), Material.id == material_id, Material.status == STATUS_NOV)
            .values(status=STATUS_V_OBDELAVI)
        ) == 1

    def zapisi_izid(self, material_id: str, izid: IzidObdelave) -> bool:
        """Zapiše izid obdelave in njegova vprašanja; vrne, ali je zapis obstajal.

        Dosedanja vprašanja se najprej upokojijo in nato vpiše nova serija.
        Material ima s tem ob vsakem trenutku največ en niz **veljavnih**
        vprašanj — pravilo iz `docs/odlocitve/ADR-009`, ki mu je `ADR-015`
        spremenil samo pomen besede „veljaven", ne pa same trditve.

        Upokojitev je tu in ne le v `vrni_v_vrsto` zato, da pravilo drži tudi,
        če ta pot kdaj teče nad zapisom, ki veljavna vprašanja že ima — na
        primer po dvojnem prevzemu ali ob ročnem klicu.
        """
        material = self.poisci(material_id)
        if material is None:
            return False

        material.status = izid.status
        material.readable = izid.readable
        material.transcript = izid.transcript
        material.summary = izid.summary
        material.prompt = izid.prompt
        material.raw_response = izid.raw_response
        material.model = izid.model
        material.input_tokens = izid.input_tokens
        material.output_tokens = izid.output_tokens
        material.error = izid.error

        self._upokoji_vprasanja(material)
        for zaporedje, vprasanje in enumerate(izid.vprasanja, start=1):
            material.vsa_vprasanja.append(
                Question(
                    id=str(uuid4()),
                    position=zaporedje,
                    question=vprasanje.question,
                    answer=vprasanje.answer,
                    # Izvor se prepiše ob nastanku: ko materiala ne bo več,
                    # mora vprašanje še vedno vedeti, iz česa je
                    # (`docs/odlocitve/ADR-012`).
                    subject=material.subject,
                    material_taken_at=material.taken_at,
                    # Družina je stolpec in ne izpeljava: vprašanje preživi
                    # material (`docs/odlocitve/ADR-029` C).
                    family_id=material.family_id,
                )
            )

        self._session.commit()
        return True

    def vrni_v_vrsto(self, material_id: str) -> bool:
        """Vrne zapis v `new` in zavrže prejšnji izid; vrne, ali se je zgodilo.

        Zavrže prepis, povzetek, revizijsko sled in besedilo napake, vprašanja
        pa **upokoji** — ta pot je edino mesto, kjer gumb „Pošlji v obdelavo"
        kaj naredi, in `docs/odlocitve/ADR-015` pravi, da tam vprašanja
        preživijo. Material tako še vedno nikoli ne kaže rezultata, ki ne
        pripada njegovemu trenutnemu stanju (`ADR-009`).

        Upokojitev je tu in ne šele ob zapisu novega izida zato, ker gumb
        hkrati pobriše prepis. Sicer bi snov ves čas klica kazala stara
        vprašanja ob praznem prepisu, `V2-R01` pa bi jih tisti čas ponudil v
        kviz kot veljavna.

        Zapisa v `processing` se ne dotakne — tam pravkar teče klic in njegov
        izid bi po vrnitvi v vrsto prišel čez to, kar bi ta metoda počistila.
        Vrne `False` tudi, kadar zapisa ni; klicatelj oboje loči s `poisci`.
        """
        material = self.poisci(material_id)
        if material is None or material.status == STATUS_V_OBDELAVI:
            return False

        material.status = STATUS_NOV
        material.readable = None
        material.transcript = None
        material.summary = None
        material.prompt = None
        material.raw_response = None
        material.model = None
        material.input_tokens = None
        material.output_tokens = None
        material.error = None
        self._upokoji_vprasanja(material)

        self._session.commit()
        return True

    def sprosti_prevzem(self, material_id: str) -> bool:
        """Vrne en prevzet zapis iz `processing` nazaj v `new`.

        Zasilni izhod za primer, ko obdelava po prevzemu ne more zapisati
        izida (npr. baza med klicem odpove). Brez tega bi zapis ostal v
        `processing` do naslednjega zagona strežnika — kar kriterij izrecno
        prepoveduje („ne obtiči v `processing`").

        Za razliko od `vrni_v_vrsto` **samo** premakne stanje: prejšnjega izida
        ne briše, ker ga v tem primeru ni.
        """
        return self._posodobi(
            update(Material)
            .where(
                self._moje(),
                Material.id == material_id,
                Material.status == STATUS_V_OBDELAVI,
            )
            .values(status=STATUS_NOV)
        ) == 1

    def obnovi_obticale(self) -> int:
        """Vrne zapise iz `processing` v `new`; vrne, koliko jih je bilo.

        Kliče se ob zagonu strežnika, preden se zanka zažene. Zapis, ki je v
        `processing` obtičal zato, ker se je strežnik med klicem ustavil, bi
        sicer tam ostal za vedno — pobral ga ne bi nihče več.

        Da to ni nevarno, poskrbi vrstni red: ob zagonu zanka še ne teče, zato
        noben zapis v `processing` ta trenutek ni v resnični obdelavi.
        """
        return self._posodobi(
            update(Material)
            .where(self._moje(), Material.status == STATUS_V_OBDELAVI)
            .values(status=STATUS_NOV)
        )

    # --- Arhiv (V1-R07) ---

    def arhiviraj(self, material_id: str) -> Material | None:
        """Umakne zapis v arhiv; vrne zapis ali `None`, če ga ni.

        Ponovno arhiviranje že arhiviranega zapisa **ne premakne** časa.
        Čas arhiviranja je podatek, po katerem operater bere, kdaj je sliko
        umaknil; drugi klik na osveženi strani ga ne sme prepisati.
        """
        material = self.poisci(material_id)
        if material is None:
            return None

        if material.archived_at is None:
            material.archived_at = datetime.now(UTC)
            self._session.commit()

        return material

    def stej_arhivirane(self) -> int:
        """Koliko zapisov je v arhivu."""
        return int(
            self._session.scalar(
                select(func.count()).select_from(Material).where(
                    self._moje(), Material.archived_at.is_not(None)
                )
            )
            or 0
        )

    def seznam_arhiviranih(self) -> list[Material]:
        """Arhivirani zapisi, najnovejše arhivirani prvi."""
        return list(
            self._session.scalars(
                select(Material)
                .where(self._moje(), Material.archived_at.is_not(None))
                .order_by(Material.archived_at.desc())
            )
        )

    def seznam_za_brisanje(self) -> list[str]:
        """`id` zapisov, ki jih mora telefon še zbrisati.

        To je celoten delovni seznam, ne odsek za nekim kazalcem: seznam se
        sam krajša, ko telefon potrjuje, zato mu ni treba hraniti ničesar
        (`docs/odlocitve/ADR-011`). Najprej najstarejše arhivirani, iz
        istega razloga kot pri čakalni vrsti prenosa.
        """
        return list(
            self._session.scalars(
                select(Material.id)
                .where(
                    self._moje(),
                    Material.archived_at.is_not(None),
                    Material.device_deleted_at.is_(None),
                )
                .order_by(Material.archived_at.asc())
            )
        )

    def potrdi_brisanje(self, material_ids: Iterable[str]) -> int:
        """Zapiše, da danih zapisov na napravi ni več; vrne, koliko jih je zadel.

        Pogoj `archived_at IS NOT NULL` ni okras: potrditev za **aktiven**
        zapis bi pomenila, da bi ga bilo mogoče dokončno izbrisati, čeprav
        ga telefon ni nikoli dobil navodila zbrisati.

        Pogoj `device_deleted_at IS NULL` poskrbi, da ponovljena potrditev
        časa ne premakne. Prenos s telefona je *at-least-once* in ista
        potrditev bo prišla večkrat; to ni napaka in se tako tudi obnaša.
        """
        seznam = list(material_ids)
        if not seznam:
            return 0

        return self._posodobi(
            update(Material)
            .where(
                self._moje(),
                Material.id.in_(seznam),
                Material.archived_at.is_not(None),
                Material.device_deleted_at.is_(None),
            )
            .values(device_deleted_at=datetime.now(UTC))
        )

    def pobrisi(self, material_id: str) -> Material | None:
        """Dokončno pobriše zapis in vrne, kar je bilo pobrisano, ali `None`.

        Vrne cel zapis, ne le `True`, ker klicatelj potrebuje `image_path` (da
        pobriše datoteko) in `subject` (da ve, kam preusmeriti). Objekt je po
        `commit` še vedno berljiv, ker je `expire_on_commit=False`.

        **Brisanje je dovoljeno šele, ko je telefon potrdil, da zapisa pri
        njem ni več.** Sicer telefon za brisanje nikoli ne izve in slika mu
        ostane za vedno — natanko težava, ki jo je V1-R07 prišla odpravit
        (`docs/odlocitve/ADR-011`). Zavrnitev je tu in ne samo v vmesniku,
        ker gumb, ki ga stran ne izriše, ni varovalka.

        Vprašanja se ob tem **ne** pobrišejo — ostanejo z `material_id`
        `NULL` in svojim izvorom (`docs/odlocitve/ADR-012`). To velja za
        veljavna **in upokojena**: nuliranje opravi ORM prek nefiltrirane
        zveze `Material.vsa_vprasanja`, prav zato, da upokojena vprašanja ne
        obtičijo z visečim `material_id` tam, kjer tuji ključ ni uveljavljen.
        """
        material = self.poisci(material_id)
        if material is None or material.device_deleted_at is None:
            return None

        self._session.delete(material)
        self._session.commit()
        return material


@dataclass(frozen=True)
class SnovZaIzbor:
    """Ena vrstica izbirnika slik (V2-R01).

    Repozitorij vrne **dejstva**, ne besedila: ali je snov izbirna, zna povedati
    domena, ime razloga v slovenščini pa je stvar vmesnika.
    """

    material: Material

    #: Koliko **veljavnih** vprašanj snov ima (`retired_at IS NULL`).
    veljavnih_vprasanj: int

    #: Ali je katero od njenih veljavnih vprašanj v nepreklicanem kvizu.
    #:
    #: Upokojena vprašanja se ne štejejo: ponovno obdelana snov se v „Novi
    #: snovi" spet ponudi (`docs/odlocitve/ADR-017` B).
    ze_v_kvizu: bool

    @property
    def izbirna(self) -> bool:
        """Ali je snov mogoče dati v kviz.

        Trije pogoji iz `ADR-016` (G) hkrati: obdelava je uspela, model je s
        slike znal brati in kaj veljavnega je ostalo. Snov, ki tega ne izpolni,
        se v izbirniku vseeno **pokaže** — z razlogom, ne izpuščena.
        """
        return (
            self.material.status == STATUS_PRIPRAVLJEN
            and self.material.readable is True
            and self.veljavnih_vprasanj > 0
        )


@dataclass(frozen=True)
class SnovSVprasanji:
    """Snov in vprašanja, ki bi šla iz nje v kviz. Za predogled."""

    material: Material
    vprasanja: tuple[Question, ...]


@dataclass(frozen=True)
class KvizZaTelefon:
    """Kviz, ki čaka na telefonu, in postavke, ki so že odgovorjene (V2-R02).

    `odgovorjene` nosi `docs/odlocitve/ADR-019` (E): telefon po ponovni
    namestitvi ve, katere postavke naj preskoči, in jih ne rešuje znova.
    """

    kviz: Quiz
    odgovorjene: frozenset[str]


@dataclass(frozen=True)
class PoskusZaStatistiko:
    """En poskus z vsem, kar statistika potrebuje o njem (V2-R04).

    Zamrznjena vrstica in ne predmeti ORM: statistika bere na tisoče poskusov,
    in vsak dostop do `poskus.postavka.vprasanje` bi bil lena poizvedba.

    Polja vprašanja so `None`, kadar postavka vprašanja nima — v praksi se to
    ne zgodi (`ADR-012`, `ADR-015`), a poskus zato ne sme izpasti molče.
    """

    rating: str
    answered_at: datetime
    quiz_id: str
    kviz_ime: str
    kviz_preklican: bool
    question_id: str | None
    vprasanje: str | None
    odgovor: str | None
    subject: str | None
    material_id: str | None
    material_taken_at: datetime | None
    upokojeno: bool


@dataclass(frozen=True)
class PoskusZaZapis:
    """En poskus s telefona, preverjen in pripravljen za zapis."""

    id: str
    quiz_item_id: str
    mode: str
    rating: str
    shown_at: datetime
    revealed_at: datetime
    answered_at: datetime


class KviziRepository(_RepozitorijDruzine):
    """Operacije nad `quizzes` in `quiz_items` (V2-R01).

    Svoj razred in ne metode na `MaterialsRepository`: poizvedba izbirnika sicer
    bere `materials` in `questions`, a obstaja zaradi kvizov.
    `MaterialsRepository` ostane to, kar je bil, in ne postane predal za vse.

    Družina kviza je `quizzes.family_id`, družina postavke je družina njenega
    kviza (`docs/odlocitve/ADR-029` C).
    """

    # --- Izbirnik ---

    def snovi_za_izbor(
        self,
        subject: str | None = None,
        od: datetime | None = None,
        do: datetime | None = None,
    ) -> list[SnovZaIzbor]:
        """Snovi za izbirnik, najnovejša prva.

        `subject` omeji na en predmet (predmetna vstopa), `od`/`do` na en dan
        (dnevni vstop, polodprt interval). Vstopi se razlikujejo tudi po obsegu
        seznama in ne le po obkljukanju — `docs/odlocitve/ADR-017` (A).

        **Arhivirana snov se ne vrne nikoli.** Arhiv pomeni pospravljeno;
        vprašanja arhiv preživijo zaradi statistike, ne zato, da bi jih še
        kvizirali (`ADR-016` G).

        Vrstni red je `taken_at DESC`, kot povsod v `/admin` — in ker kriterij
        pravi „po snovi (kot v izbirniku)", je to hkrati vrstni red postavk
        objavljenega kviza.

        **Tri poizvedbe, nikoli N+1.** Branje števila vprašanj na vsako sliko
        posebej bi pri seznamu celega predmeta pomenilo sto poizvedb na stran;
        `ADR-017` (A) pove, zakaj je ta seznam dolg.
        """
        # Izrecna oznaka tipa: brez nje mypy tip seznama sklepa iz prvega
        # elementa (`BinaryExpression`) in zavrne `==`, ki vrne širši
        # `ColumnElement`.
        pogoji: list[ColumnElement[bool]] = [
            Material.family_id == self._family_id,
            Material.archived_at.is_(None),
        ]
        if subject is not None:
            pogoji.append(Material.subject == subject)
        if od is not None:
            pogoji.append(Material.taken_at >= od)
        if do is not None:
            pogoji.append(Material.taken_at < do)

        snovi = list(
            self._session.scalars(
                select(Material).where(*pogoji).order_by(Material.taken_at.desc())
            )
        )
        if not snovi:
            return []

        idji = [snov.id for snov in snovi]
        steviloma = self._stej_veljavna(idji)
        v_kvizu = self._ze_v_kvizu(idji)

        return [
            SnovZaIzbor(
                material=snov,
                veljavnih_vprasanj=steviloma.get(snov.id, 0),
                ze_v_kvizu=snov.id in v_kvizu,
            )
            for snov in snovi
        ]

    def _stej_veljavna(self, material_ids: Sequence[str]) -> dict[str, int]:
        """Koliko veljavnih vprašanj ima katera snov. Ena poizvedba za vse."""
        vrstice = self._session.execute(
            select(Question.material_id, func.count())
            .where(
                Question.family_id == self._family_id,
                Question.material_id.in_(material_ids),
                Question.retired_at.is_(None),
            )
            .group_by(Question.material_id)
        ).all()
        return {material_id: koliko for material_id, koliko in vrstice if material_id}

    def _ze_v_kvizu(self, material_ids: Sequence[str]) -> set[str]:
        """Katere od danih snovi so že bile v kvizu.

        „Bila v kvizu" pomeni dvoje hkrati (`docs/odlocitve/ADR-017` B):

        - kviz **ni preklican** — preklican kviz ni bil pravi, zato se njegova
          snov spet ponudi (`ADR-016` B);
        - vprašanje je **veljavno** — po ponovni obdelavi so stara vprašanja
          upokojena in snov ima novo serijo, ki v kvizu še ni bila.

        Pot do snovi gre prek vprašanja in ne prek stolpca na postavki:
        `quiz_items` svojega `material_id` nima in ga po `ADR-017` (B) tudi ne
        potrebuje.
        """
        return set(
            self._session.scalars(
                select(Question.material_id)
                .join(QuizItem, QuizItem.question_id == Question.id)
                .join(Quiz, Quiz.id == QuizItem.quiz_id)
                .where(
                    Question.family_id == self._family_id,
                    Quiz.family_id == self._family_id,
                    Question.material_id.in_(material_ids),
                    Question.retired_at.is_(None),
                    Quiz.canceled_at.is_(None),
                )
                .distinct()
            )
        )

    # --- Predogled ---

    def snovi_z_vprasanji(
        self, material_ids: Iterable[str], koliko: int
    ) -> list[SnovSVprasanji]:
        """Izbrane snovi s prvimi `koliko` veljavnimi vprašanji vsake.

        **Prvih N po `position`, brez naključja** (`ADR-016` D). Če jih je manj
        od `koliko`, se vzame, kar je — snov s tremi vprašanji ni napaka.

        Vrstni red snovi je `taken_at DESC` in se **ne** povzame po vrstnem redu
        v obrazcu: brskalniku verjamemo, katere snovi so izbrane, ne pa, v
        katerem vrstnem redu naj bodo. Snov, ki je medtem šla v arhiv, izpade.

        Dve poizvedbi, ne ena na snov.
        """
        idji = list(material_ids)
        if not idji:
            return []

        snovi = list(
            self._session.scalars(
                select(Material)
                .where(
                    Material.family_id == self._family_id,
                    Material.id.in_(idji),
                    Material.archived_at.is_(None),
                )
                .order_by(Material.taken_at.desc())
            )
        )
        if not snovi:
            return []

        po_snovi: dict[str, list[Question]] = {snov.id: [] for snov in snovi}
        vprasanja = self._session.scalars(
            select(Question)
            .where(
                Question.family_id == self._family_id,
                Question.material_id.in_(po_snovi.keys()),
                Question.retired_at.is_(None),
            )
            .order_by(Question.material_id, Question.position)
        )
        for vprasanje in vprasanja:
            if vprasanje.material_id is not None:
                po_snovi[vprasanje.material_id].append(vprasanje)

        return [
            SnovSVprasanji(material=snov, vprasanja=tuple(po_snovi[snov.id][:koliko]))
            for snov in snovi
        ]

    def vprasanja_po_idjih(self, question_ids: Sequence[str]) -> list[Question] | None:
        """Vprašanja v **danem** vrstnem redu, ali `None`, če katerega ni.

        Vrstni red je tu vrstni red iz obrazca in ne iz baze: predogled je
        tisti, ki je zaporedje določil, in objavi se, kar je bilo videno.

        `None` in ne krajši seznam: polovičen kviz je slabši od zavrnitve, ki jo
        operater vidi. Da se to sploh zgodi, mora nekdo spremeniti skrito polje
        — vprašanja se ne brišejo (`ADR-012`).

        **Podvojen identifikator je prav tako `None`.** Predogled ga ne more
        proizvesti, spremenjen obrazec pa: brez zavrnitve bi kviz dobil dve
        enaki postavki in bi `V2-R04` isti odgovor štela dvakrat.

        Oboje ujame **ena sama** primerjava. `najdena` je slovar, ključan po
        `id`: manjkajoče vprašanje ga skrajša, podvojeno pa ga ne podaljša —
        v obeh primerih je krajši od seznama, ki je prišel. Tu je stala še
        ločena preverba s `set()`; bila je mrtva veja in je šla ven.

        **Vprašanje tuje družine šteje kot neobstoječe** — isti izid kot
        spremenjen obrazec (`docs/odlocitve/ADR-029`).
        """
        if not question_ids:
            return None

        najdena = {
            vprasanje.id: vprasanje
            for vprasanje in self._session.scalars(
                select(Question).where(
                    Question.family_id == self._family_id, Question.id.in_(question_ids)
                )
            )
        }
        if len(najdena) != len(question_ids):
            return None

        return [najdena[question_id] for question_id in question_ids]

    # --- Objava in življenje kviza ---

    def objavi(
        self, ime: str, subject: str | None, vprasanja: Sequence[Question]
    ) -> Quiz:
        """Ustvari kviz in vse njegove postavke **v eni transakciji**.

        En `commit` na koncu in ne eden na postavko: kriterij zahteva, da
        delnega kviza ni. Ob napaki med potjo se ne zapiše nič.

        Besedilo se prepiše **iz vprašanj v bazi**, nikoli iz obrazca — obrazec
        pove, katera vprašanja, ne kaj v njih piše. Od tega trenutka je postavka
        neodvisna od vprašanja: ponovna obdelava ali dokončno brisanje snovi je
        ne spremenita (`ADR-016` E).
        """
        # Druga ograja za `vprasanja_po_idjih`: kviz ne sme nikoli prestopiti
        # meje družine, tudi če bi vprašanja prišla od drugod.
        if any(vprasanje.family_id != self._family_id for vprasanje in vprasanja):
            raise ValueError("Kviz ne sme vsebovati vprašanja tuje družine (ADR-025).")

        kviz = Quiz(
            id=str(uuid4()),
            family_id=self._family_id,
            name=ime,
            subject=subject,
            created_at=datetime.now(UTC),
        )
        for zaporedje, vprasanje in enumerate(vprasanja, start=1):
            kviz.postavke.append(
                QuizItem(
                    id=str(uuid4()),
                    question_id=vprasanje.id,
                    position=zaporedje,
                    question_text=vprasanje.question,
                    answer_text=vprasanje.answer,
                )
            )

        self._session.add(kviz)
        self._session.commit()
        return kviz

    def seznam(self) -> list[tuple[Quiz, int]]:
        """Vsi kvizi s številom postavk, najnovejši prvi.

        `outerjoin` in ne `join`: kviza brez postavk ni mogoče objaviti, a če bi
        kdaj nastal, naj ga seznam pokaže z ničlo in ne skrije.

        Štetje v isti poizvedbi in ne prek `len(kviz.postavke)` — sicer bi
        seznam desetih kvizov prebral vse njihove postavke, da bi izpisal deset
        številk. `GROUP BY` po primarnem ključu je dovolj tudi na Postgresu.
        """
        vrstice = self._session.execute(
            select(Quiz, func.count(QuizItem.id))
            .outerjoin(QuizItem, QuizItem.quiz_id == Quiz.id)
            .where(Quiz.family_id == self._family_id)
            .group_by(Quiz.id)
            .order_by(Quiz.created_at.desc())
        ).all()
        return [(kviz, koliko) for kviz, koliko in vrstice]

    def poisci(self, quiz_id: str) -> Quiz | None:
        """Kviz z danim `id` ali `None`, s postavkami in njihovimi vprašanji.

        `selectinload` in ne lena naložitev: stran kviza za vsako postavko
        prebere še njeno vprašanje (izvor, povezava na snov). Pri kvizu s
        tridesetimi postavkami — kar je po `PREDOLG_KVIZ` pričakovana zgornja
        velikost — bi to pomenilo dvaintrideset poizvedb namesto treh.
        """
        return self._session.scalars(
            select(Quiz)
            .where(Quiz.family_id == self._family_id, Quiz.id == quiz_id)
            .options(selectinload(Quiz.postavke).selectinload(QuizItem.question))
        ).one_or_none()

    # --- Rezultat (V2-R03) ---

    def snovi_postavk(self, kviz: Quiz) -> dict[str, Material]:
        """Snovi, iz katerih so vprašanja kviza, ključane po `id`. Ena poizvedba.

        Rezultat pri vsaki postavki pove, ali je snov v arhivu in ali ima še
        sliko — za to potrebuje vrstico `materials`. Branje prek
        `postavka.question.material` bi bilo leno nalaganje na vsako postavko.

        Ločeno od `poisci` in ne privzeto v njem: stran **nerešenega** kviza
        snovi ne potrebuje in naj ne plača poizvedbe, ki je ne uporabi
        (`docs/plan/V2-R03.md`, odločitev 5). Dokončno izbrisane snovi v slovarju
        ni — vprašanje ima takrat `material_id` `NULL` (`ADR-012`).
        """
        idji = {
            postavka.question.material_id
            for postavka in kviz.postavke
            if postavka.question is not None and postavka.question.material_id is not None
        }
        if not idji:
            return {}

        return {
            snov.id: snov
            for snov in self._session.scalars(
                select(Material).where(
                    Material.family_id == self._family_id, Material.id.in_(idji)
                )
            )
        }

    def poskusi_kviza(self, quiz_id: str) -> dict[str, QuestionAttempt]:
        """Poskusi kviza, ključani po postavki. Ena poizvedba.

        Ključ je `quiz_item_id`, ker ima postavka največ en poskus — v shemi
        (`UNIQUE`) in ne le po dogovoru (`docs/odlocitve/ADR-019` E). Rezultat
        zato ne potrebuje pravila, kateri od dveh poskusov velja.
        """
        return {
            poskus.quiz_item_id: poskus
            for poskus in self._session.scalars(
                select(QuestionAttempt)
                .join(QuizItem, QuizItem.id == QuestionAttempt.quiz_item_id)
                .where(
                    QuestionAttempt.family_id == self._family_id,
                    QuizItem.quiz_id == quiz_id,
                )
            )
        }

    def preklici(self, quiz_id: str) -> Quiz | None:
        """Prekliče kviz; vrne kviz ali `None`, če ga ni.

        **Nič se ne pobriše** (`ADR-016` F): postavke ostanejo, kviz ostane,
        samo `canceled_at` dobi žig. Na telefon se preklican kviz preprosto
        neha pošiljati (`seznam_za_telefon`).

        Ponoven preklic časa **ne premakne**, iz istega razloga kot pri
        `arhiviraj` in `_upokoji_vprasanja`: čas je podatek o tem, kdaj se je
        odločitev zgodila, in drugi klik na osveženi strani ga ne sme prepisati.
        """
        kviz = self.poisci(quiz_id)
        if kviz is None:
            return None

        if kviz.canceled_at is None:
            kviz.canceled_at = datetime.now(UTC)
            self._session.commit()

        return kviz

    # --- Reševanje na telefonu (V2-R02) ---

    def seznam_za_telefon(self) -> list[KvizZaTelefon]:
        """Kvizi, ki čakajo na telefonu: nepreklicani in nerešeni, najstarejši prvi.

        **Delovni seznam, ne odsek za kazalcem** — isti vzorec kot
        `seznam_za_brisanje` (`docs/odlocitve/ADR-011`, `ADR-016` F). Seznam se
        krajša sam, ko je kviz rešen ali preklican, zato telefonu ni treba
        hraniti časa zadnje sinhronizacije.

        Vsebina je **zamrznjeno besedilo postavk** in ne besedilo iz
        `questions`: ponovna obdelava snovi objavljenega kviza ne spremeni
        (`ADR-016` E).

        Dve poizvedbi za postavke (`selectinload`) in ena za odgovorjene, ne
        ena na kviz.
        """
        kvizi = list(
            self._session.scalars(
                select(Quiz)
                .where(
                    Quiz.family_id == self._family_id,
                    Quiz.canceled_at.is_(None),
                    Quiz.solved_at.is_(None),
                )
                .order_by(Quiz.created_at)
                .options(selectinload(Quiz.postavke))
            )
        )
        if not kvizi:
            return []

        odgovorjene = set(
            self._session.scalars(
                select(QuestionAttempt.quiz_item_id)
                .join(QuizItem, QuizItem.id == QuestionAttempt.quiz_item_id)
                .where(
                    QuestionAttempt.family_id == self._family_id,
                    QuizItem.quiz_id.in_([kviz.id for kviz in kvizi]),
                )
            )
        )

        return [
            KvizZaTelefon(
                kviz=kviz,
                odgovorjene=frozenset(
                    postavka.id for postavka in kviz.postavke if postavka.id in odgovorjene
                ),
            )
            for kviz in kvizi
        ]

    def zapisi_poskuse(
        self, poskusi: Sequence[PoskusZaZapis], _ponovitev: bool = False
    ) -> int | None:
        """Zapiše paket poskusov; vrne, koliko jih je bilo res zapisanih.

        `None`, kadar se kateri poskus nanaša na postavko, ki je ni — takrat se
        **ne zapiše nič** od paketa. Paket je vse ali nič: pol zapisanega
        paketa bi telefon ob ponovitvi poslal še enkrat in to bi bilo sicer
        neškodljivo, a nihče ne bi znal povedati, kaj je od prvega poskusa
        ostalo.

        Pravila za posamezen poskus:

        - obstoječ `id` → preskoči (idempotentnost, `ADR-012`);
        - postavka že ima poskus, tudi iz istega paketa → preskoči. **Prvi
          zmaga** (`docs/odlocitve/ADR-019` E);
        - sicer vstavi.

        Poskusi preklicanega kviza se sprejmejo kot vsi drugi: dogodek je
        dejstvo, zavrnjen poskus pa bi na telefonu obtičal za vedno
        (`ADR-019` C).

        Rešenost prizadetih kvizov se preveri **v isti transakciji** kot
        vstavljanje, da paket, ki zapolni zadnjo postavko, kviz tudi reši.
        Meja te trditve: dva **hkratna** paketa za različni zadnji postavki
        istega kviza drug drugega na Postgresu (READ COMMITTED) ne vidita, in
        `solved_at` bi ostal prazen, dokler ne pride naslednji paket. Pri enem
        telefonu z zaporo v ponavljalniku se to ne zgodi; zapisano je kot znana
        omejitev v `docs/01-arhitektura.md`.

        Dva hkratna paketa za isto postavko bi se srečala na enoličnosti v
        shemi. Takrat se transakcija ponovi enkrat: druga ponovitev vidi zapis
        tekmeca in poskus preskoči, kot pravi „prvi zmaga".

        **Postavka tuje družine šteje kot neobstoječa** in paket vrne `None`
        (`docs/odlocitve/ADR-029`). Poskus dobi družino od repozitorija. Znana
        meja: poskus, katerega `id` (UUID s telefona) že obstaja v drugi
        družini, pade dvakrat na primarnem ključu in izjema gre naprej — brez
        ponarejanja se to ne zgodi, obvoz s poizvedbo brez družine pa ni dovoljen.
        """
        if not poskusi:
            return 0

        postavke_idji = {poskus.quiz_item_id for poskus in poskusi}
        kvizi_postavk = dict(
            self._session.execute(
                select(QuizItem.id, QuizItem.quiz_id)
                .join(Quiz, Quiz.id == QuizItem.quiz_id)
                .where(Quiz.family_id == self._family_id, QuizItem.id.in_(postavke_idji))
            )
            .tuples()
            .all()
        )
        if len(kvizi_postavk) != len(postavke_idji):
            return None

        znani_idji = set(
            self._session.scalars(
                select(QuestionAttempt.id).where(
                    QuestionAttempt.family_id == self._family_id,
                    QuestionAttempt.id.in_([poskus.id for poskus in poskusi]),
                )
            )
        )
        zasedene = set(
            self._session.scalars(
                select(QuestionAttempt.quiz_item_id).where(
                    QuestionAttempt.family_id == self._family_id,
                    QuestionAttempt.quiz_item_id.in_(postavke_idji),
                )
            )
        )

        zdaj = datetime.now(UTC)
        zapisani = 0
        for poskus in poskusi:
            if poskus.id in znani_idji or poskus.quiz_item_id in zasedene:
                continue
            self._session.add(
                QuestionAttempt(
                    id=poskus.id,
                    family_id=self._family_id,
                    quiz_item_id=poskus.quiz_item_id,
                    mode=poskus.mode,
                    rating=poskus.rating,
                    shown_at=poskus.shown_at,
                    revealed_at=poskus.revealed_at,
                    answered_at=poskus.answered_at,
                    received_at=zdaj,
                )
            )
            znani_idji.add(poskus.id)
            zasedene.add(poskus.quiz_item_id)
            zapisani += 1

        try:
            # Seja ima `autoflush=False`; štetje spodaj mora vstavljeno videti.
            self._session.flush()
            self._oznaci_resene(set(kvizi_postavk.values()), zdaj)
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if _ponovitev:
                raise
            return self.zapisi_poskuse(poskusi, _ponovitev=True)

        return zapisani

    def _oznaci_resene(self, quiz_ids: set[str], zdaj: datetime) -> None:
        """Postavi `solved_at` kvizom, pri katerih ima vsaka postavka poskus.

        Brez `commit` — klicatelj commita, da sta poskus in rešenost ena
        transakcija. `WHERE solved_at IS NULL`, da ponovljen paket žiga ne
        premakne: čas je podatek o tem, kdaj se je rešitev zgodila. Isti vzorec
        kot `preklici` in `_upokoji_vprasanja`.

        Rešenost se izpelje **neodvisno od preklica** (`ADR-019` C); katera os
        ima prednost pri prikazu, je stvar prikaza.
        """
        vrstice = self._session.execute(
            select(QuizItem.quiz_id, func.count(QuizItem.id), func.count(QuestionAttempt.id))
            .join(Quiz, Quiz.id == QuizItem.quiz_id)
            .outerjoin(QuestionAttempt, QuestionAttempt.quiz_item_id == QuizItem.id)
            .where(Quiz.family_id == self._family_id, QuizItem.quiz_id.in_(quiz_ids))
            .group_by(QuizItem.quiz_id)
        ).tuples()
        reseni = [quiz_id for quiz_id, postavk, poskusov in vrstice if postavk == poskusov]
        if not reseni:
            return

        self._session.execute(
            update(Quiz)
            .where(
                Quiz.family_id == self._family_id,
                Quiz.id.in_(reseni),
                Quiz.solved_at.is_(None),
            )
            .values(solved_at=zdaj)
            .execution_options(synchronize_session="fetch")
        )


class StatistikaRepository(_RepozitorijDruzine):
    """Branje dnevnika poskusov za statistiko čez kvize (V2-R04).

    Svoj razred in ne metode na `KviziRepository`, iz istega razloga, kot je
    `KviziRepository` ločen od `MaterialsRepository`: bere iste tabele, a
    obstaja zaradi nečesa drugega. **Samo bere** — statistika nima števcev
    (`docs/odlocitve/ADR-012`).

    **Vsaka poizvedba šteje samo način `samoocena`.** Statistiki dveh načinov
    se nikoli ne povprečita (`ADR-014`); danes drugega načina ni, zato bi bil
    pozabljen pogoj neviden do dneva, ko bi prišel ABC. Isti skupni pogoji
    nosijo tudi družino poskusa.
    """

    def _pogoji(self, od: datetime | None, do: datetime | None) -> list[ColumnElement[bool]]:
        """Družina, način in okno po `answered_at`, polodprto `[od, do)`, meje v UTC.

        `answered_at` je v bazi v UTC — `routers/resevanje.py` ga pred zapisom
        pretvori —, zato primerjava drži tudi nad SQLite, ki pasu ne hrani.
        """
        pogoji: list[ColumnElement[bool]] = [
            QuestionAttempt.family_id == self._family_id,
            QuestionAttempt.mode == NACIN_SAMOOCENA,
        ]
        if od is not None:
            pogoji.append(QuestionAttempt.answered_at >= od)
        if do is not None:
            pogoji.append(QuestionAttempt.answered_at < do)
        return pogoji

    def poskusi(
        self,
        od: datetime | None = None,
        do: datetime | None = None,
        subject: str | None = None,
    ) -> list[PoskusZaStatistiko]:
        """Poskusi v oknu, najstarejši prvi. **Ena poizvedba.**

        `LEFT JOIN questions`, da poskus na postavki brez vprašanja ne izpade;
        z `subject` pa takega poskusa ni, ker brez vprašanja predmeta ne pozna.

        Preklican kviz ni izločen: ocena je dejstvo, preklic pove le, da je bil
        kviz napačno sestavljen (`docs/odlocitve/ADR-021` E). Upokojeno
        vprašanje ni izločeno: poskus nanj je Mašin odgovor (`ADR-021` D).
        """
        pogoji = self._pogoji(od, do)
        if subject is not None:
            pogoji.append(Question.subject == subject)

        vrstice = self._session.execute(
            select(
                QuestionAttempt.rating,
                QuestionAttempt.answered_at,
                Quiz.id,
                Quiz.name,
                Quiz.canceled_at,
                Question.id,
                Question.question,
                Question.answer,
                Question.subject,
                Question.material_id,
                Question.material_taken_at,
                Question.retired_at,
            )
            .select_from(QuestionAttempt)
            .join(QuizItem, QuizItem.id == QuestionAttempt.quiz_item_id)
            .join(Quiz, Quiz.id == QuizItem.quiz_id)
            .outerjoin(Question, Question.id == QuizItem.question_id)
            .where(*pogoji)
            .order_by(QuestionAttempt.answered_at, QuestionAttempt.id)
        ).tuples()

        return [
            PoskusZaStatistiko(
                rating=rating,
                answered_at=answered_at,
                quiz_id=quiz_id,
                kviz_ime=kviz_ime,
                kviz_preklican=canceled_at is not None,
                question_id=question_id,
                vprasanje=vprasanje,
                odgovor=odgovor,
                subject=subject_vprasanja,
                material_id=material_id,
                material_taken_at=material_taken_at,
                upokojeno=retired_at is not None,
            )
            for (
                rating,
                answered_at,
                quiz_id,
                kviz_ime,
                canceled_at,
                question_id,
                vprasanje,
                odgovor,
                subject_vprasanja,
                material_id,
                material_taken_at,
                retired_at,
            ) in vrstice
        ]

    def casi_poskusov(self) -> list[datetime]:
        """`answered_at` vseh poskusov, za izbiro šolskih let. Ena poizvedba.

        Časi in ne leta: šolsko leto se določi v domačem pasu, tega pa baza ne
        pozna (`app/casi.py`). En stolpec čez vse poskuse je pri tem obsegu
        nekaj tisoč vrednosti na leto.
        """
        return list(
            self._session.scalars(
                select(QuestionAttempt.answered_at).where(*self._pogoji(None, None))
            )
        )

    def snovi(self, material_ids: Iterable[str]) -> dict[str, Material]:
        """Snovi po `id`, za oznako arhiva. Ena poizvedba, kot `snovi_postavk`.

        Dokončno izbrisane snovi v slovarju ni — njena vprašanja imajo takrat
        `material_id` `NULL` (`ADR-012`).
        """
        idji = set(material_ids)
        if not idji:
            return {}
        return {
            snov.id: snov
            for snov in self._session.scalars(
                select(Material).where(
                    Material.family_id == self._family_id, Material.id.in_(idji)
                )
            )
        }

    def ima_poskuse(self, subject: str) -> bool:
        """Ali ima predmet kakšen poskus, v kateremkoli oknu.

        Za kodo, ki je ni na seznamu desetih: brez poskusov je stran 404, s
        poskusi pa mora obstajati — sicer bi se ocene predmeta s preimenovano
        kodo tiho izgubile (isto pravilo kot `/admin`).
        """
        return (
            self._session.scalars(
                select(QuestionAttempt.id)
                .join(QuizItem, QuizItem.id == QuestionAttempt.quiz_item_id)
                .join(Question, Question.id == QuizItem.question_id)
                .where(*self._pogoji(None, None), Question.subject == subject)
                .limit(1)
            ).first()
            is not None
        )
