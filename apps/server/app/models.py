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

    # --- Arhiv (V1-R07). Oboje je `NULL`, dokler se ni zgodilo. ---

    #: Kdaj je bil zapis arhiviran; `NULL` pomeni aktiven.
    #:
    #: Ločen stolpec in **ne** peto stanje `status`: `status` je avtomat
    #: obdelave, arhiv pa je druga os — arhiviran zapis je lahko hkrati
    #: `ready`. Isti razlog kot pri `readable` (`docs/odlocitve/ADR-011`).
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Kdaj je telefon potrdil, da tega materiala pri njem ni več.
    #:
    #: Potrditev pomeni „na tej napravi ga ni več", ne „pravkar sem ga
    #: izbrisal" — zapis, ki ga aplikacija sploh nima (sveža namestitev), se
    #: potrdi enako. Dokler je `NULL`, dokončno brisanje ni dovoljeno.
    device_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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

    # --- Vprašanja: tri zveze, ker „vprašanja materiala" ni eno samo ---
    #
    # Zveze `questions` namenoma **ni več** (bila je do V2-R05). Odkar
    # `docs/odlocitve/ADR-015` pozna upokojena vprašanja, je nevtralno zveneče
    # ime past: bralec, ki ga vzame brez razmisleka, dobi tudi upokojena in
    # tega mu sveža baza nikoli ne pokaže — tam ima material natanko eno
    # serijo. Zato ima vsaka od treh vlog svoje ime.

    #: **Vsa** vprašanja, veljavna in upokojena. Ni za prikaz.
    #:
    #: Edina pisljiva zveza od treh. Nosi dvoje:
    #:
    #: 1. vstavljanje nove serije ob zapisu izida obdelave;
    #: 2. ORM-jevo postavljanje `material_id = NULL` ob brisanju materiala.
    #:
    #: Točka 2 je razlog, da ta zveza sploh ostaja nefiltrirana. Filtrirana
    #: zveza upokojenih vprašanj ob brisanju ne bi videla in ta bi ostala z
    #: visečim `material_id`; na SQLite, kjer tuji ključi privzeto niso
    #: uveljavljeni, bi bila taka napaka v testih zelena in bi se pokazala
    #: šele na Postgresu (`docs/odlocitve/ADR-012`).
    #:
    #: **Brez kaskade brisanja.** Do V1-R07 sta tu stali dve mreži, ki sta
    #: vprašanja pobrisali skupaj z materialom; `ADR-012` ju je odstranil, ker
    #: mora vprašanje material preživeti. Posledica, ki se ne vidi sama od
    #: sebe: `clear()` odslej vprašanj ne pobriše, ampak jih osiroti.
    vsa_vprasanja: Mapped[list["Question"]] = relationship(
        back_populates="material",
        order_by="Question.position",
    )

    #: Veljavna vprašanja materiala — to, kar `ADR-015` misli z „vprašanja
    #: materiala". Zadnja serija, ki jo je vrnil model.
    #:
    #: `viewonly=True` ni okras: brez njega bi SQLAlchemy tri zveze nad istim
    #: tujim ključem razumel kot tri poti, ki si lastijo `material_id`, in
    #: opozoril na prekrivanje. Pisanje teče izključno skozi `vsa_vprasanja`
    #: in skozi `MaterialsRepository`.
    veljavna_vprasanja: Mapped[list["Question"]] = relationship(
        primaryjoin=(
            "and_(Material.id == Question.material_id, Question.retired_at.is_(None))"
        ),
        order_by="Question.position",
        viewonly=True,
    )

    #: Upokojena vprašanja: serije prejšnjih obdelav te snovi.
    #:
    #: Urejena po `retired_at` in šele nato po `position`, ker je `position`
    #: enolična znotraj **serije** in ne znotraj materiala (`ADR-015`) —
    #: skupen `retired_at` je edino, po čemer se serija prepozna.
    upokojena_vprasanja: Mapped[list["Question"]] = relationship(
        primaryjoin=(
            "and_(Material.id == Question.material_id,"
            " Question.retired_at.is_not(None))"
        ),
        order_by="Question.retired_at, Question.position",
        viewonly=True,
    )


class Question(Base):
    """Eno vprašanje, ki ga je model sestavil iz ene snovi.

    Lastna tabela in ne polje JSON na `materials`, ker bo `V2-R02` ocene
    težavnosti vezala na `question_id` — vprašanje mora imeti obstojen
    identifikator.

    **Vprašanje je trajno.** Do V2-R05 ni bilo: ponovna obdelava je prejšnji
    rezultat zavrgla skupaj z vsemi vprašanji materiala (`ADR-009`, odločitev
    A1). `docs/odlocitve/ADR-015` to nadomesti — brisanja ni več, staro
    vprašanje dobi `retired_at`. Brez tega bi gumb „Pošlji v obdelavo" tiho
    razbil objavljen kviz, ki na `question_id` kaže (`V2-R01`), in statistiko
    čez leta, ki stoji na tem, da vprašanje ohrani identiteto (`V2-R04`).
    """

    __tablename__ = "questions"

    #: UUID, generiran na strežniku (za razliko od `materials.id`, ki pride
    #: s telefona) — vprašanje nastane tu in nikjer drugje.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    #: Material, iz katerega je vprašanje nastalo, ali `NULL`, kadar je bil
    #: material dokončno izbrisan.
    #:
    #: `SET NULL` in ne `CASCADE`: vprašanje nosi statistiko, ki jo bo V2
    #: vezala nanj, in te ne sme vzeti brisanje slike
    #: (`docs/odlocitve/ADR-012`).
    material_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("materials.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    #: Predmet materiala, prepisan ob nastanku vprašanja.
    #:
    #: Denormalizirano namenoma: ko materiala ni več, mora vprašanje še vedno
    #: povedati, iz katere snovi je. Isti vzorec kot račun, ki prepiše naslov
    #: kupca, namesto da ga referencira.
    subject: Mapped[str | None] = mapped_column(String(16), nullable=True)

    #: Čas posnetka materiala, prepisan ob nastanku vprašanja.
    material_taken_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Zaporedna številka znotraj **serije** (od 1). Vrstni red, v katerem jih
    #: je vrnil model, je vrstni red, v katerem se pokažejo.
    #:
    #: Znotraj materiala enolična ni: druga obdelava iste snovi začne spet pri
    #: 1. Enoličnost znotraj serije je dovolj, ker se serije nikoli ne
    #: prikazujejo pomešane (`docs/odlocitve/ADR-015`).
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Besedilo vprašanja.
    question: Mapped[str] = mapped_column(Text, nullable=False)

    #: Pričakovan odgovor. `docs/00-namen.md` kviz definira kot „vprašanj **in
    #: odgovorov**"; brez shranjenega odgovora bi ga `V1-R05` moral kupiti z
    #: novim klicem modela.
    answer: Mapped[str] = mapped_column(Text, nullable=False)

    #: Kdaj je bilo vprašanje upokojeno; `NULL` pomeni **veljavno** vprašanje.
    #:
    #: Svoja os in ne novo stanje, po istem vzorcu kot `Material.archived_at`
    #: (`docs/odlocitve/ADR-011`): upokojeno vprašanje je še vedno vprašanje,
    #: le v novo serijo se ne uvršča.
    #:
    #: Vsa vprašanja ene serije dobijo **isti** žig — po njem se serija
    #: prepozna in zato dodatnega stolpca za oznako serije ni. Upokojitev je
    #: enosmerna: nazaj na `NULL` ne gre nikoli, in ročnega gumba zanjo ni,
    #: ker je posledica ponovne obdelave in ne samostojno dejanje
    #: (`docs/odlocitve/ADR-015`).
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    material: Mapped[Material | None] = relationship(back_populates="vsa_vprasanja")
