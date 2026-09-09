"""Motor, seja in tanka plast nad tabelama `materials` in `questions`.

Poslovna logika govori z `MaterialsRepository`, ne s SQLAlchemy neposredno —
tako testi tečejo nad SQLite v pomnilniku, produkcija pa nad Postgresom, in
oboje skozi isto kodo.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import (
    CursorResult,
    Engine,
    create_engine,
    func,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import Update

from app.models import (
    STATUS_NOV,
    STATUS_V_OBDELAVI,
    Material,
    Question,
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


class MaterialsRepository:
    """Operacije nad tabelo `materials`, ki jih potrebujeta V1-R02 in V1-R04."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def poisci(self, material_id: str) -> Material | None:
        """Zapis z danim `id` ali `None`."""
        return self.session.get(Material, material_id)

    def obstaja(self, material_id: str) -> bool:
        """Ali zapis z danim `id` že obstaja."""
        return self.poisci(material_id) is not None

    def vstavi_ce_ga_ni(self, material: Material) -> bool:
        """Vstavi zapis; vrne `True`, če je nastal, in `False`, če ga je že bilo.

        Preverba pred vstavljanjem pokrije običajni primer (telefon pošlje isti
        `id` znova, ker prvega odgovora ni dočakal). `IntegrityError` pokrije
        tekmovanje dveh hkratnih zahtev z istim `id`: takrat je zmagala prva in
        to za klicatelja pomeni isto — zapis obstaja, ni ga ustvaril on.
        """
        if self.obstaja(material.id):
            return False

        try:
            self.session.add(material)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            return False

        return True

    def stej_po_predmetih(self) -> dict[str, int]:
        """Koliko zapisov je pri katerem predmetu.

        Vrne samo predmete, ki v bazi res so. Kateri predmeti se pokažejo tudi
        s številom nič, je odločitev vmesnika, ne baze.
        """
        vrstice = self.session.execute(
            select(Material.subject, func.count())
            .where(Material.archived_at.is_(None))
            .group_by(Material.subject)
        ).all()
        return {subject: koliko for subject, koliko in vrstice}

    def seznam_po_predmetu(self, subject: str) -> list[Material]:
        """Zapisi enega predmeta, od najnovejšega navzdol.

        Vrstni red je enak kot v zgodovini na telefonu (`taken_at DESC`), da
        isti posnetek na obeh straneh stoji na istem mestu.
        """
        return list(
            self.session.scalars(
                select(Material)
                .where(Material.subject == subject, Material.archived_at.is_(None))
                .order_by(Material.taken_at.desc())
            )
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
            self.session.execute(stavek.execution_options(synchronize_session=False)),
        )
        self.session.commit()
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
        self.session.execute(
            update(Question)
            .where(
                Question.material_id == material.id,
                Question.retired_at.is_(None),
            )
            .values(retired_at=datetime.now(UTC))
            .execution_options(synchronize_session="fetch")
        )
        self.session.expire(
            material, ["vsa_vprasanja", "veljavna_vprasanja", "upokojena_vprasanja"]
        )

    def seznam_novih(self) -> list[Material]:
        """Zapisi, ki čakajo na obdelavo, od najstarejšega naprej.

        `taken_at ASC` in ne `DESC` kot v zgodovini: v vrsti naj najstarejša
        slika ne čaka najdlje. Isti razlog kot pri čakalni vrsti na telefonu.
        """
        return list(
            self.session.scalars(
                select(Material)
                .where(Material.status == STATUS_NOV, Material.archived_at.is_(None))
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
            .where(Material.id == material_id, Material.status == STATUS_NOV)
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
                )
            )

        self.session.commit()
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

        self.session.commit()
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
            .where(Material.id == material_id, Material.status == STATUS_V_OBDELAVI)
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
            update(Material).where(Material.status == STATUS_V_OBDELAVI).values(status=STATUS_NOV)
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
            self.session.commit()

        return material

    def stej_arhivirane(self) -> int:
        """Koliko zapisov je v arhivu."""
        return int(
            self.session.scalar(
                select(func.count()).select_from(Material).where(
                    Material.archived_at.is_not(None)
                )
            )
            or 0
        )

    def seznam_arhiviranih(self) -> list[Material]:
        """Arhivirani zapisi, najnovejše arhivirani prvi."""
        return list(
            self.session.scalars(
                select(Material)
                .where(Material.archived_at.is_not(None))
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
            self.session.scalars(
                select(Material.id)
                .where(
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

        self.session.delete(material)
        self.session.commit()
        return material
