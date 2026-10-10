"""Tabele `families`, `materials`, `questions`, `quizzes`, `quiz_items` in
`question_attempts` na strežniku.

**Družina je lastnik vseh podatkov** (`docs/odlocitve/ADR-025`): `family_id`
je obvezen na `materials`, `questions`, `quizzes` in `question_attempts`.
`quiz_items` ga nima — postavka brez kviza ne obstaja (`quiz_id` je
`NOT NULL`), zato je njena družina družina kviza (`ADR-029` C).

Tipi so izbrani tako, da ista shema stoji nad Postgresom (produkcija) in nad
SQLite (testi) — glej odločitev 2 v `docs/plan/V1-R02.md`. Zato `id` ni
`UUID`, ampak `String`: UUID generira telefon in strežnik ga hrani takšnega,
kot ga je dobil.
"""

from datetime import datetime
from typing import Literal, get_args

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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

#: Način odgovarjanja. V V2 je edini samoocena (`docs/odlocitve/ADR-014`);
#: stolpec `mode` je tam zato, da bi bila poznejša uvedba ABC čista migracija.
Nacin = Literal["samoocena"]
NACIN_SAMOOCENA: Nacin = "samoocena"

#: Štiri stopnje samoocene, od najtežje navzdol (`ADR-014`). Prva je hkrati
#: pravilnost, ostale tri težavnost. Pravilnost se **ne** shranjuje — izpelje se
#: iz ocene, da bi drugačna izpeljava veljala tudi za nazaj.
Ocena = Literal["nisem_vedela", "tezko", "srednje", "lahko"]
OCENE: tuple[Ocena, ...] = get_args(Ocena)


class Base(DeclarativeBase):
    """Skupna osnova za modele."""


class Family(Base):
    """Družina: obseg lastništva vseh podatkov (`docs/odlocitve/ADR-025`).

    Ime in nič drugega — ni naslova, ni nastavitev. Uporabniki pridejo v
    `V3-R03`.
    """

    __tablename__ = "families"

    #: UUID, generiran na strežniku. Je tudi ime mape slik družine.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    #: Ime za prikaz, npr. `Cvek`. **Ni enolično** — družina ni identiteta za
    #: prijavo; enoličnost nosi `credentials.identifier` (`ADR-038` E).
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    #: Ugasnjena družina se ne more prijaviti, podatki pa ostanejo (`V3-R05`).
    #: Zastavica in ne `deactivated_at`: družina se lahko vrne, in ponovna
    #: aktivacija mora vrniti stanje pred deaktivacijo, ne novo stanje
    #: (`docs/odlocitve/ADR-044` A). Članov se ne dotaknemo — kdor je bil
    #: deaktiviran prej, ostane deaktiviran.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Material(Base):
    """Ena fotografirana učna snov, prejeta s telefona."""

    __tablename__ = "materials"

    #: UUID, generiran na telefonu. Nosilec idempotentnosti.
    #:
    #: Primarni ključ ostane **globalen** in ne po družini: tuj `id` pri
    #: prevzemu je `409` (`docs/odlocitve/ADR-029` D).
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    #: Družina, ki ji zapis pripada (`docs/odlocitve/ADR-025`). Obvezna in
    #: brez `ondelete`: družina se ne briše, `V3-R05` jo deaktivira.
    family_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("families.id", name="fk_materials_family_id"),
        nullable=False,
        index=True,
    )

    #: Otrok, ki je snov fotografiral (`docs/odlocitve/ADR-039`).
    #:
    #: Obvezen in brez `ondelete`: račun se ne briše, `V3-R06` ga deaktivira.
    #: Pove ga **seja žetona** in nikoli telo zahteve — starš se v mobilno
    #: aplikacijo ne more prijaviti (`ADR-036` D), zato je vsak žeton na
    #: `POST /materials` otrokov in „snov brez otroka" ne nastane.
    child_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", name="fk_materials_child_id"),
        nullable=False,
        index=True,
    )

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

    #: Družina, ki ji zapis pripada (`docs/odlocitve/ADR-025`). Obvezna in
    #: brez `ondelete`: družina se ne briše, `V3-R05` jo deaktivira.
    #:
    #: Stolpec in ne izpeljava iz materiala: vprašanje preživi material
    #: (`ADR-012`) in bi brez njega ostalo brez družine (`ADR-029` C). Isti
    #: razlog kot `subject` in `material_taken_at` spodaj.
    family_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("families.id", name="fk_questions_family_id"),
        nullable=False,
        index=True,
    )

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


class Quiz(Base):
    """En objavljen kviz: ime, predmet in čas nastanka.

    **Kviz nima stolpca `status`.** Stanje se izpelje iz `canceled_at` in
    `solved_at`, po istem vzorcu, kot je arhiv svoja os in ne peto stanje v
    `ADR-011`. Objavljen kviz je preprosto kviz, ki obstaja (`ADR-016` C).
    Osi sta neodvisni: preklican kviz je lahko tudi rešen (`ADR-019` C), in
    takrat ima pri prikazu prednost preklic.
    """

    __tablename__ = "quizzes"

    #: UUID, generiran **na strežniku** — kviz nastane tu, ne na telefonu.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    #: Družina, ki ji zapis pripada (`docs/odlocitve/ADR-025`). Obvezna in
    #: brez `ondelete`: družina se ne briše, `V3-R05` jo deaktivira.
    family_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("families.id", name="fk_quizzes_family_id"),
        nullable=False,
        index=True,
    )

    #: Otrok, ki mu je kviz namenjen — **naslovljenec** (`ADR-039` A).
    #:
    #: Obvezen: „kviz za nikogar" ne sme biti veljavno stanje, ki bi ga morala
    #: znati obravnavati vsaka poizvedba za njim. Družina brez aktivnega
    #: otroka zato kviza ne more objaviti; sestavljalnik to pove vnaprej.
    #:
    #: Naslovljenec je natanko eden (kriterij `V3-R07`) in je vedno otrok
    #: **svoje** družine; tuj `id` je `404` in ne `403` (`ADR-038`).
    child_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", name="fk_quizzes_child_id"),
        nullable=False,
        index=True,
    )

    #: Ime za prikaz. Sestavi se samodejno (`MAT — 9. 9. 2026`), operater pa ga
    #: v obrazcu lahko prepiše.
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    #: Koda predmeta ali `NULL` za kviz čez več predmetov.
    #:
    #: `NULL` ni „neznano": pomeni, da je kviz nastal iz vstopa „Kaj smo se
    #: danes učili", ki po `ADR-016` (B) namenoma ne izbira predmeta.
    subject: Mapped[str | None] = mapped_column(String(16), nullable=True)

    #: Kdaj je bil kviz objavljen. Osnutkov ni — predogled ničesar ne shrani
    #: (`ADR-016` C), zato je čas nastanka hkrati čas objave.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Kdaj je bil kviz preklican; `NULL` pomeni veljaven, objavljen kviz.
    #:
    #: Preklic in ne brisanje: zapis, ki ga je telefon morda že prenesel, mora
    #: imeti stanje, ki ga je mogoče sinhronizirati — izbrisane vrstice ni
    #: mogoče sporočiti (`ADR-016` F, isti razlog kot `ADR-011`). Enosmerno:
    #: nazaj na `NULL` ne gre nikoli.
    canceled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Kdaj je bil kviz rešen; `NULL` pomeni, da kakšna postavka še nima poskusa.
    #:
    #: Postavi ga **strežnik sam**, v isti transakciji kot poskus, ki zapolni
    #: zadnjo postavko, in ga ne premakne nikoli več. Čas je strežnikov, ne
    #: telefonov: ura telefona lahko laže, časi poskusov pa so zapisani vsak
    #: pri svojem poskusu. Dodan v V2-R02 (`docs/odlocitve/ADR-017` C).
    solved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Postavke kviza, urejene po zaporedju v kvizu.
    #:
    #: **Edina kaskada brisanja v shemi.** Postavka brez kviza nima pomena, za
    #: razliko od vprašanja brez materiala, ki nosi statistiko in mora preživeti
    #: (`ADR-012`). Kvizov se sicer ne briše — kaskada je tu zato, da shema
    #: pove resnico, ne zato, da bi jo kdo uporabljal.
    postavke: Mapped[list["QuizItem"]] = relationship(
        back_populates="quiz",
        order_by="QuizItem.position",
        cascade="all, delete-orphan",
    )


class QuizItem(Base):
    """Eno vprašanje, zamrznjeno v kviz.

    **Dve ravni obrambe** za kriterij „objavljen kviz zamrzne svoje postavke"
    (`ADR-016` E):

    1. `question_id` nosi **identiteto** — `V2-R04` bo ocene čez leta vezala
       nanjo, kar je mogoče šele, odkar vprašanje ob ponovni obdelavi ne izgine
       (`ADR-015`).
    2. `question_text` in `answer_text` nosita **berljivost** — kviz izpred let
       mora biti berljiv tudi, ko je bila izvorna snov dokončno izbrisana in je
       `questions.material_id` `NULL` (`ADR-012`).

    Stolpca `material_id` tu namenoma ni: pot do snovi gre prek vprašanja, ki
    denormalizirana `subject` in `material_taken_at` nosi s sabo že od V1-R07
    (`docs/odlocitve/ADR-017` B).
    """

    __tablename__ = "quiz_items"

    #: UUID, generiran na strežniku.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    quiz_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: Vprašanje, iz katerega je postavka nastala.
    #:
    #: `NULL`-abilen zaradi `ON DELETE SET NULL`. V praksi se to ne zgodi —
    #: vprašanja se od `ADR-012` in `ADR-015` ne brišejo nikjer več — a shema
    #: mora povedati isto kot tuji ključ. Če bi se kdaj zgodilo, kviz izgubi
    #: ključ in ne postavke: besedilo je zamrznjeno v njej.
    question_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("questions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    #: Zaporedna številka **čez cel kviz**, od 1.
    #:
    #: Za razliko od `Question.position`, ki je enolična znotraj serije enega
    #: materiala. Kviz je en dokument in ga bo `V2-R03` tako tudi natisnil.
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Kopija besedila vprašanja ob objavi.
    question_text: Mapped[str] = mapped_column(Text, nullable=False)

    #: Kopija pričakovanega odgovora ob objavi.
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)

    quiz: Mapped[Quiz] = relationship(back_populates="postavke")

    #: Zveza je **enosmerna**: `Question` povratne nima.
    #:
    #: Povratna zveza bi ORM-ju dala pot, po kateri bi ob brisanju vprašanja
    #: nulil `question_id` — vprašanja pa se ne brišejo (`ADR-012`). To bi bila
    #: mrtva pot z živimi posledicami; `Question` po V2-R05 ostane nedotaknjen.
    question: Mapped[Question | None] = relationship()


class QuestionAttempt(Base):
    """En odgovor na eno postavko kviza — dogodek, ne števec (`ADR-012`).

    `id` generira **telefon**. Prenos s telefona je *at-least-once*: ponovljen
    `INSERT` z istim `id` ne naredi nič, ponovljen `UPDATE stevec + 1` pa bi
    podatke tiho pokvaril.

    **Postavka ima največ en poskus** (`docs/odlocitve/ADR-019` E): drugi poskus
    za isto postavko strežnik sprejme kot uspeh, a ga ne zapiše. Enoličnost je
    v shemi in ne le v repozitoriju, da je ne more obiti nobena pot do baze.

    Stolpca `question_id` tu **ni**: vprašanje je izpeljivo prek postavke
    (`quiz_items.question_id`), podvojen ključ pa bi se lahko razšel.
    """

    __tablename__ = "question_attempts"
    __table_args__ = (
        UniqueConstraint("quiz_item_id", name="question_attempts_quiz_item_id_key"),
    )

    #: UUID, generiran na telefonu. Nosilec idempotentnosti.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    #: Družina, ki ji zapis pripada (`docs/odlocitve/ADR-025`). Obvezna in
    #: brez `ondelete`: družina se ne briše, `V3-R05` jo deaktivira.
    family_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("families.id", name="fk_question_attempts_family_id"),
        nullable=False,
        index=True,
    )

    #: Postavka, na katero je to odgovor.
    #:
    #: **Brez `ondelete`.** Poskus nosi statistiko, zato naj baza brisanje
    #: kviza s poskusi raje zavrne, kot da jih vzame s sabo. Kvizov se sicer
    #: ne briše (`ADR-016` F).
    quiz_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("quiz_items.id"), nullable=False
    )

    #: Otrok, ki je odgovoril (`ADR-039`).
    #:
    #: Pove ga seja žetona, ne telo paketa. Ni nujno naslovljenec kviza:
    #: poskus za kviz **drugega** otroka strežnik sprejme kot uspeh, a ga ne
    #: zapiše (`ADR-039` D), zato v tabeli tak par ne nastane — pravilo je v
    #: repozitoriju, ne v tuji omejitvi, ker gre za tih sprejem in ne za
    #: napako.
    child_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", name="fk_question_attempts_child_id"),
        nullable=False,
        index=True,
    )

    #: Način odgovarjanja; zaenkrat vedno `samoocena` (`ADR-014`).
    mode: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Ena od `OCENE`. Surova ocena; pravilnost se izpelje, ne shrani.
    rating: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Kdaj je bilo vprašanje pokazano, kdaj razkrit odgovor in kdaj ocenjeno —
    #: vse tri s telefona (`ADR-019` D). Razlike med njimi so zanesljivejše od
    #: absolutnih vrednosti, ker se ura telefona lahko premakne.
    shown_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Kdaj je strežnik poskus prevzel.
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# --- Identiteta (V3-R03) ---------------------------------------------------
#
# Model je iz `docs/odlocitve/ADR-027`: **poverilnica ni uporabnik**. Oseba
# živi v `users`, način prijave v `credentials`, in Google (`V3-R08`) je zato
# pozneje nova vrstica, ne nova shema. Izvedbene odločitve so v `ADR-035`.

#: Vlogi uporabnika. Starš dela izključno v adminu, otrok izključno v mobilni
#: aplikaciji (`docs/00-namen.md`); prijava otroka v admin se zavrne
#: (`ADR-035` F).
Vloga = Literal["parent", "child"]
VLOGA_STARS: Vloga = "parent"
VLOGA_OTROK: Vloga = "child"

#: Vrste poverilnic. Obe nastaneta v V3: `password` v `V3-R03`, `google` v
#: `V3-R08` — kot nova vrstica iste tabele, natanko kot je napovedal `ADR-027`.
VrstaPoverilnice = Literal["password", "google"]
POVERILNICA_GESLO: VrstaPoverilnice = "password"
POVERILNICA_GOOGLE: VrstaPoverilnice = "google"


class User(Base):
    """Oseba v družini: starš ali otrok.

    Nima ne gesla ne uporabniškega imena — oboje je v `credentials`. Brisanja
    ni: račun se deaktivira (`is_active`), ker načelo „nič se ne briše, vse se
    upokoji" velja tudi za osebe (`V3-R06`).
    """

    __tablename__ = "users"

    #: UUID, generiran na strežniku.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    #: Družina, ki ji oseba pripada. Obvezna in brez `ondelete`, kot povsod
    #: (`docs/odlocitve/ADR-025`).
    family_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("families.id", name="fk_users_family_id"),
        nullable=False,
        index=True,
    )

    #: Ena od `Vloga`.
    role: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Ime, kot ga stran pokaže, npr. `Dejan`.
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)

    #: Lastnik sistema. **Zaenkrat samo zastavica**: pogledi, ki jo berejo,
    #: nastanejo v `V3-R05` (`docs/verzije/v3.md`). Do takrat je lastnik
    #: navaden starš svoje družine.
    is_system_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: Deaktiviran račun se ne more prijaviti, podatki pa ostanejo. Stolpec
    #: pride že v V3-R03, čeprav ga poti uporabijo šele v `V3-R06`: ista tabela
    #: naj ne gre v drugo migracijo čez dva tedna.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Credential(Base):
    """Način, s katerim se oseba izkaže. Ena oseba jih ima lahko več."""

    __tablename__ = "credentials"

    __table_args__ = (
        UniqueConstraint("identifier", name="credentials_identifier_key"),
    )

    #: UUID, generiran na strežniku.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", name="fk_credentials_user_id"),
        nullable=False,
        index=True,
    )

    #: Ena od `VrstaPoverilnice`.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)

    #: E-naslov starša ali uporabniško ime otroka; pri `google` Googlov `sub`.
    #:
    #: **Enolično čez celotno namestitev**, ne po družini: prijava pozna samo
    #: identifikator in geslo, zato bi dvoje enakih imen pomenilo, da strežnik
    #: ne ve, kdo se prijavlja (`docs/verzije/v3.md`, `V3-R06`).
    #:
    #: Pri Googlu tu **ne** stoji e-naslov (`docs/odlocitve/ADR-046` A): starš,
    #: ki ima geslo in Google na istem naslovu, bi s tem podrl prav to
    #: enoličnost — torej stanje, ki ga `V3-R08` zahteva kot običajno. `sub` je
    #: hkrati edina vrednost, za katero Google jamči, da se ne spremeni.
    identifier: Mapped[str] = mapped_column(String(320), nullable=False)

    #: E-naslov Google računa, **samo za izris** (`ADR-046` A, `V3-R08`).
    #:
    #: Po njem se nikoli ne išče in nikoli ne prijavlja — sicer bi bil drugi
    #: identifikator in bi terjal svojo enoličnost. Pri geselnih poverilnicah
    #: ostane `NULL`; `identifier` je tam že berljiv in oznake ne rabi.
    #:
    #: Vrednost je lahko zastarela do naslednje prijave z Googlom, ki jo
    #: osveži. Zastarel **prikaz** je cenejši od poizvedbe pri Googlu brez
    #: razloga; pravice iz te vrednosti ne izhajajo nobene.
    label: Mapped[str | None] = mapped_column(String(320), nullable=True)

    #: Zgostitev gesla (argon2id). **`NULL` pomeni, da geslo ni nastavljeno** —
    #: tak račun obstaja, prijava z njim pa ne uspe nikoli (`ADR-035` G). Tako
    #: nastaneta uporabnika v migraciji `0008_uporabniki`, brez gesla v
    #: repozitoriju.
    secret_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserSession(Base):
    """Ena prijavljena naprava.

    Razred se ne imenuje `Session`: to ime v tem projektu pomeni sejo
    SQLAlchemy in bi ga v vsaki datoteki zasenčilo. Tabela je `sessions`, kot
    pravi `ADR-027`.

    Žetona v bazi ni — je samo njegova zgostitev SHA-256. Kdor prebere bazo,
    se z njo ne more prijaviti (`ADR-035` B).
    """

    __tablename__ = "sessions"

    __table_args__ = (UniqueConstraint("token_hash", name="sessions_token_hash_key"),)

    #: UUID, generiran na strežniku.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", name="fk_sessions_user_id"),
        nullable=False,
        index=True,
    )

    #: SHA-256 žetona iz piškotka, zapisana šestnajstiško.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    #: CSRF žeton te seje. Živi tu in ne v skrivnosti iz okolja: s sejo nastane
    #: in z njo pade, zato ni nastavitve, ki bi bila lahko napačna
    #: (`ADR-035` D).
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Kdaj seja poteče. Rok je drseči: ob uporabi se odmakne naprej.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Kdaj je bila seja nazadnje uporabljena. Osveži se največ enkrat na uro,
    #: sicer bi bila vsaka zahteva `UPDATE` (`ADR-035` B).
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Groba oznaka naprave (`User-Agent`, skrajšan). Ni identiteta in se ne
    #: preverja.
    #:
    #: **Seznama sej ne kaže nobena stran.** `V3-R06` ga ni naredila, ker ga
    #: njeni kriteriji ne zahtevajo (`docs/odlocitve/ADR-038` H); stolpec se
    #: piše ob vsaki prijavi in bo seznam nosil, ko in če bo.
    device_label: Mapped[str | None] = mapped_column(String(200), nullable=True)


class LoginAttempt(Base):
    """Neuspel poskus prijave. Uspešni se ne zapisujejo.

    Šteje se **samo identifikator**, ne naslov odjemalca: Docker Desktop
    naslova ne ohrani (`docs/odlocitve/ADR-034` A), zato bi štetje po naslovu
    upočasnilo vse hkrati. Naslov se vseeno zapiše — za pogled nazaj, ne za
    odločitev (`ADR-035` E).
    """

    __tablename__ = "login_attempts"

    #: UUID, generiran na strežniku.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    #: Identifikator, kakršen je bil poslan — tudi tak, ki ga ni v bazi.
    identifier: Mapped[str] = mapped_column(String(320), nullable=False, index=True)

    #: Naslov, s katerega je poskus prišel, ali `NULL`, kadar ga ni mogoče
    #: ugotoviti.
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class Schedule(Base):
    """Urnik enega otroka: kateri predmeti so kateri dan (`ADR-028`).

    **Urnik je pričakovanje, ne dejstvo** — prvo tako mesto v tej bazi. Vse
    ostalo tu je zapis o tem, kaj se je zgodilo; urnik pove, kaj naj bi se
    zgodilo, in prav zato mora skozi potrditev starša (`ADR-028` A2).

    **Veljaven je vedno en sam na otroka.** Nov prejšnjega ne izbriše, ampak
    upokoji: `replaced_at` je svoja os po istem vzorcu kot `archived_at`
    (`ADR-011`) in `retired_at` (`ADR-015`). Enoličnost uveljavlja **ena pot
    pisanja v eni transakciji** (`ScheduleRepository.potrdi`) in ne delni
    indeks — tega bi bilo treba zapisati dvakrat, za SQLite in za Postgres.

    Vrstice brez potrditve ni: nepotrjen predlog živi v obrazcu in nikoli v
    bazi. Zato `confirmed_at` ni `NULL`-abilen in stanja `draft` ni.
    """

    __tablename__ = "schedules"

    #: UUID, generiran **na strežniku** — urnik nastane tu.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    #: Družina, ki ji zapis pripada (`docs/odlocitve/ADR-025`). Obvezna in
    #: brez `ondelete`, kot povsod.
    family_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("families.id", name="fk_schedules_family_id"),
        nullable=False,
        index=True,
    )

    #: Otrok, čigar urnik je to. Obvezen: „urnik nikogar" ni stanje, ki bi ga
    #: morala znati obravnavati vsaka poizvedba za njim (isto kot pri
    #: `Quiz.child_id`, `ADR-039` A). Urnik je last otroka in ne namestitve —
    #: prav zato je ta zahteva v V3 in ne prej (`ADR-028` B2).
    child_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", name="fk_schedules_child_id"),
        nullable=False,
        index=True,
    )

    #: Kdaj je starš ta urnik potrdil. Hkrati čas nastanka — osnutkov ni.
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    #: Kdaj ga je nadomestil novejši; `NULL` pomeni **veljaven** urnik.
    #:
    #: Enosmerno: nazaj na `NULL` ne gre nikoli. Upokojenega urnika ne bere
    #: nihče in vmesnika zanj ni — ostane, ker načelo „nič se ne briše, vse se
    #: upokoji" velja povsod (`docs/00-namen.md`), ne ker ga kdo potrebuje.
    replaced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Pot do slike urnika na disku, ali `NULL`.
    #:
    #: `NULL` ni manjkajoč podatek, ampak resnica o nastanku: ta urnik je
    #: starš **natipkal** in ne prebral s slike (`ADR-041` E). Slika se zapiše
    #: ob nalaganju in ne ob potrditvi (`ADR-042`), zato jo ta stolpec samo
    #: poveže z vrstico.
    #:
    #: Slika urnika **ni snov**: živi v `<family_id>/urniki/` in nikoli v
    #: `materials` (`ADR-028`). Sicer bi se pojavila v izbirniku kvizov, v
    #: statistiki in na strani predmeta, iz ponedeljkove mreže pa bi nastalo
    #: pet vprašanj o urniku.
    image_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    #: Vnosi tega urnika, urejeni po dnevu in nato po kodi predmeta.
    #:
    #: Kaskada brisanja: vnos brez urnika nima pomena, enako kot postavka brez
    #: kviza. Urnikov se sicer ne briše — kaskada je tu zato, da shema pove
    #: resnico.
    vnosi: Mapped[list["ScheduleEntry"]] = relationship(
        back_populates="urnik",
        order_by="ScheduleEntry.weekday, ScheduleEntry.subject",
        cascade="all, delete-orphan",
    )


class ScheduleEntry(Base):
    """En vnos urnika: ta predmet je ta dan na urniku.

    **Brez ure in brez zaporedja** (`ADR-028`). Dve uri istega predmeta v istem
    dnevu sta za manjke ista reč — zahteva se vsaj ena slika —, zato je urnik
    množica in ne seznam. Enoličnost para *dan + predmet* to pove v shemi in ne
    le v dogovoru.
    """

    __tablename__ = "schedule_entries"

    #: UUID, generiran na strežniku.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    #: Urnik, ki mu vnos pripada. Družine **nima**: izpelje se iz urnika, po
    #: isti logiki kot pri `quiz_items` (`ADR-029` C).
    schedule_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("schedules.id", name="fk_schedule_entries_schedule_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: Dan v tednu, kot ga šteje `date.weekday()`: 0 = ponedeljek … 4 = petek.
    #:
    #: Sobote in nedelje urnik ne pozna (`ADR-041` F), zato manjko tam ne more
    #: nastati po sami zgradbi in ne po posebnem pravilu. Izmeničnih tednov
    #: prav tako ne — to bi bila nova dimenzija zapisa in nova zahteva
    #: (`ADR-028`).
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Koda predmeta. Vedno ena od `app.subjects.PREDMETI` — to uveljavi pot
    #: potrditve, ker je urnik pričakovanje, ki ga vpiše človek, in ne koda, ki
    #: pride s telefona iz druge gradnje.
    subject: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Ali se ta predmet **ta dan** ne slika (`ADR-028` F2).
    #:
    #: Lastnost vnosa in ne predmeta: seznam predmetov je trdo zapisan in
    #: podvojen v TypeScriptu in Pythonu, veljal bi za vse družine, pričakovanje
    #: pa je last ene. Isti predmet je zato lahko v ponedeljek označen in v
    #: sredo ne.
    skip_photo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    urnik: Mapped["Schedule"] = relationship(back_populates="vnosi")

    __table_args__ = (
        UniqueConstraint("schedule_id", "weekday", "subject", name="uq_schedule_entries_dan"),
    )


class Preizkus(Base):
    """Shranjen preizkus — v vmesniku „test" (V4-R08, `ADR-053` F).

    **Vrstica obstaja samo za končan preizkus.** Delo v teku živi v brskalniku
    (`ADR-053` E), zato tu ni stanja, osnutka in ne zgodovine različic. Zapis
    se po nastanku **ne spremeni nikoli** in se ne briše (`ADR-011`): nov
    preizkus iz njega je nova vrstica z `base_id`.

    Ime razreda in tabele je slovensko, ker je `test` rezerviran za avtomatske
    teste (`ADR-053` A); stolpci so angleški kot povsod drugod.
    """

    __tablename__ = "preizkusi"

    #: UUID, ki ga strežnik izriše v urejevalnik in ga brskalnik pošlje ob
    #: shranjevanju: ponovljen `POST` zato ne naredi drugega zapisa
    #: (`ADR-055` G).
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    #: Družina, ki ji zapis pripada (`ADR-025`). Obvezna in brez `ondelete`.
    family_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("families.id", name="fk_preizkusi_family_id"),
        nullable=False,
        index=True,
    )

    #: Naslovljenec. Obvezen, kot pri kvizu (`ADR-053` G, `ADR-039` A).
    child_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", name="fk_preizkusi_child_id"),
        nullable=False,
        index=True,
    )

    #: Koda predmeta snovi, iz katere je nastal.
    subject: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Naslov za pregled; strežnik ga prebere iz prve vrstice testa
    #: (`ADR-055` B).
    title: Mapped[str] = mapped_column(String(200), nullable=False)

    #: Test in rešitve v markdownu z LaTeX-om, kot ju je vrnil model.
    test_md: Mapped[str] = mapped_column(Text, nullable=False)
    solutions_md: Mapped[str] = mapped_column(Text, nullable=False)

    #: Snov: besedilo prepisov, iz katerih je preizkus nastal, zamrznjeno ob
    #: shranjevanju. Identifikatorjev slik tu ni — slike se arhivirajo in
    #: brišejo, besedilo ostane (`ADR-055` E).
    source_md: Mapped[str] = mapped_column(Text, nullable=False)

    #: Ime modela, kot ga je vrnila storitev pri zadnjem koraku. Pošlje ga
    #: brskalnik in je zato podatek za primerjavo, ne dokaz (`ADR-055` C).
    model: Mapped[str] = mapped_column(String(128), nullable=False)

    #: Kdaj je bil shranjen (strežnikov čas) in kateri starš ga je shranil.
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    saved_by: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", name="fk_preizkusi_saved_by"),
        nullable=False,
    )

    #: Shranjen preizkus, ki je bil izhodišče tega; `NULL` pri preizkusu iz
    #: snovi (`ADR-055` E).
    base_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("preizkusi.id", name="fk_preizkusi_base_id"),
        nullable=True,
    )
