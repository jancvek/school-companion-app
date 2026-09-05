"""Motor, seja in tanka plast nad tabelama `materials` in `questions`.

Poslovna logika govori z `MaterialsRepository`, ne s SQLAlchemy neposredno —
tako testi tečejo nad SQLite v pomnilniku, produkcija pa nad Postgresom, in
oboje skozi isto kodo.
"""

from dataclasses import dataclass, field
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import CursorResult, Engine, create_engine, func, select, update
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
            select(Material.subject, func.count()).group_by(Material.subject)
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
                .where(Material.subject == subject)
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

    def seznam_novih(self) -> list[Material]:
        """Zapisi, ki čakajo na obdelavo, od najstarejšega naprej.

        `taken_at ASC` in ne `DESC` kot v zgodovini: v vrsti naj najstarejša
        slika ne čaka najdlje. Isti razlog kot pri čakalni vrsti na telefonu.
        """
        return list(
            self.session.scalars(
                select(Material)
                .where(Material.status == STATUS_NOV)
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

        Vprašanja se najprej pobrišejo in nato vpišejo na novo. Material ima s
        tem ob vsakem trenutku največ en niz vprašanj — pravilo iz
        `docs/odlocitve/ADR-009`, ki mora veljati tudi, če ta pot kdaj teče nad
        zapisom, ki vprašanja že ima.
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

        material.questions.clear()
        for zaporedje, vprasanje in enumerate(izid.vprasanja, start=1):
            material.questions.append(
                Question(
                    id=str(uuid4()),
                    position=zaporedje,
                    question=vprasanje.question,
                    answer=vprasanje.answer,
                )
            )

        self.session.commit()
        return True

    def vrni_v_vrsto(self, material_id: str) -> bool:
        """Vrne zapis v `new` in zavrže prejšnji izid; vrne, ali se je zgodilo.

        Zavrže **vse**: prepis, povzetek, revizijsko sled, besedilo napake in
        vsa vprašanja. Material tako nikoli ne kaže rezultata, ki ne pripada
        njegovemu trenutnemu stanju (`docs/odlocitve/ADR-009`).

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
        material.questions.clear()

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

    def pobrisi(self, material_id: str) -> Material | None:
        """Pobriše zapis in vrne, kar je bilo pobrisano, ali `None`.

        Vrne cel zapis, ne le `True`, ker klicatelj potrebuje `image_path` (da
        pobriše datoteko) in `subject` (da ve, kam preusmeriti). Objekt je po
        `commit` še vedno berljiv, ker je `expire_on_commit=False`.
        """
        material = self.poisci(material_id)
        if material is None:
            return None

        self.session.delete(material)
        self.session.commit()
        return material
