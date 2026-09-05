"""Tabeli `materials` in `questions` na strežniku.

Tipi so izbrani tako, da ista shema stoji nad Postgresom (produkcija) in nad
SQLite (testi) — glej odločitev 2 v `docs/plan/V1-R02.md`. Zato `id` ni
`UUID`, ampak `String`: UUID generira telefon in strežnik ga hrani takšnega,
kot ga je dobil.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

#: Stanje ob prevzemu: slika je na disku, obdelave še ni bilo.
STATUS_NOV = "new"

#: Zapis je prevzel worker in klic modela teče. Prehodno stanje: zapis, ki v
#: njem ostane čez ponovni zagon strežnika, se vrne v `new` (V1-R03).
STATUS_V_OBDELAVI = "processing"

#: Klic je uspel. Pove, da je odgovor modela zapisan — **ne** pa, da je slika
#: berljiva; za to je polje `readable`.
STATUS_PRIPRAVLJEN = "ready"

#: Klic ni uspel ali odgovor ni bil po shemi. Razlog je v `error`. Iz tega
#: stanja zapis vrne samo gumb „Pošlji v obdelavo".
STATUS_NAPAKA = "failed"


class Base(DeclarativeBase):
    """Skupna osnova za modele."""


class Material(Base):
    """Ena fotografirana učna snov, prejeta s telefona."""

    __tablename__ = "materials"

    #: UUID, generiran na telefonu. Nosilec idempotentnosti.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    #: Koda predmeta, npr. `MAT`.
    subject: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Trenutek posnetka (ne prejema), s časovnim pasom.
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Pot do slike na disku strežnika.
    image_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    #: Stanje obdelave: `new` → `processing` → `ready` | `failed`.
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Trenutek, ko je strežnik zapis prevzel.
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # --- Izid obdelave (V1-R03). Vse je `NULL`, dokler obdelave ni bilo. ---

    #: Ali je model s slike sploh znal brati.
    #:
    #: Ločeno od `status` in ne peti status: klic je uspel in bil plačan, torej
    #: to ni napaka obdelave. Neberljiva slika je `ready` z `readable=False` in
    #: brez vprašanj (odločitev iz faze 1, `docs/plan/V1-R03.md`).
    readable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    #: Dobesedno besedilo, ki ga je model prebral s slike.
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Kratek povzetek vsebine, za hitro prepoznavanje v pregledu.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Revizijska sled klica. Zapiše se ob **vsakem** izidu. ---
    #
    # Brez nje primerjave med modeli ne bo mogoče narediti z dejanskimi
    # podatki, ampak spet le na papirju (ADR-008). Zato tudi pri `failed`:
    # takrat je surov odgovor pogosto edini dokaz, zakaj je padlo.

    #: Prompt, kakršen je bil poslan. V celoti, ne kot oznaka različice —
    #: sicer bi sled po spremembi prompta v kodi kazala napačno vsebino.
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Odgovor modela, kakršen je prišel, pred razčlenjevanjem.
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Ime modela, kot ga je vrnila storitev (ne kot je bilo naročeno) —
    #: storitev zna razrešiti vzdevek v konkretno različico.
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    #: Poraba tokenov. Shrani se tudi pri `failed`, kadar jo odgovor nosi:
    #: neuspel klic je bil plačan enako kot uspešen.
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Zakaj obdelava ni uspela. Slovensko, berljivo — ne gola sled izjeme.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Vprašanja tega materiala, po zaporedju.
    #:
    #: `cascade="all, delete-orphan"` **brez** `passive_deletes`: otroke pobriše
    #: ORM sam, torej tudi na SQLite, ki tujih ključev privzeto ne uveljavlja.
    #: `ondelete="CASCADE"` v shemi je druga, neodvisna mreža na Postgresu.
    #: Obe sta tu zato, da testi ne dokazujejo manj kot produkcija
    #: (odločitev 6 v `docs/plan/V1-R03.md`).
    questions: Mapped[list["Question"]] = relationship(
        back_populates="material",
        cascade="all, delete-orphan",
        order_by="Question.position",
    )


class Question(Base):
    """Eno vprašanje, ki ga je model sestavil iz ene snovi.

    Lastna tabela in ne polje JSON na `materials`, ker bo `V1-R05` ocene
    težavnosti vezala na `question_id` — vprašanje mora imeti obstojen
    identifikator.

    Vprašanje **ni trajno:** ponovna obdelava zavrže prejšnji rezultat skupaj
    z vsemi vprašanji materiala. Glej `docs/odlocitve/ADR-009`, ki to zapiše
    prav zato, da `V1-R05` tega ne odkrije naknadno v kodi.
    """

    __tablename__ = "questions"

    #: UUID, generiran na strežniku (za razliko od `materials.id`, ki pride
    #: s telefona) — vprašanje nastane tu in nikjer drugje.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    #: Material, iz katerega je vprašanje nastalo.
    material_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("materials.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: Zaporedna številka znotraj materiala (od 1). Vrstni red, v katerem jih
    #: je vrnil model, je vrstni red, v katerem se pokažejo.
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Besedilo vprašanja.
    question: Mapped[str] = mapped_column(Text, nullable=False)

    #: Pričakovan odgovor. `docs/00-namen.md` kviz definira kot „vprašanj **in
    #: odgovorov**"; brez shranjenega odgovora bi ga `V1-R05` moral kupiti z
    #: novim klicem modela.
    answer: Mapped[str] = mapped_column(Text, nullable=False)

    material: Mapped[Material] = relationship(back_populates="questions")
