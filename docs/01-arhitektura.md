# Arhitektura — trenutno stanje

> Ta dokument opisuje, kako je **zdaj**, ne kako naj bo.
> Model ga posodobi ob vsaki spremembi, ki ga naredi neaktualnega.

## Stack

| Plast | Tehnologija | Zakaj |
|---|---|---|
| Mobilna aplikacija | Expo (React Native, TypeScript) | EAS Build da APK brez Play Store-a in Android Studia; `expo-camera` / `expo-sqlite` / `expo-file-system` pokrijejo vse brez native kode |
| Lokalna baza (telefon) | SQLite (`expo-sqlite`) | Čakalna vrsta za offline-first delovanje |
| Strežnik | FastAPI (Python) | Naraven za AI/vision klice, lahek |
| Podatkovna baza (strežnik) | PostgreSQL + pgvector | Ena baza za metapodatke in (kasneje) vektorje, brez ločene vektorske baze |
| Povezljivost telefon ↔ strežnik | Tailscale | Dostop do domačega strežnika brez port-forwardinga |
| Vision / OCR | OpenAI `gpt-4.1` prek uradnega paketa `openai` (od V1-R03) | Klasični OCR (Tesseract) ne obvlada slovenskega rokopisa; izbira in njena začasnost sta v `docs/odlocitve/ADR-008` |
| Obdelava v ozadju | `asyncio` opravilo v procesu `api` | Pri 5–25 slikah na teden Celery in Redis ne rešita nobene težave tega projekta; „kar bi lahko bila mikrostoritev, naj bo funkcija" |
| Orkestracija strežnika | Docker Compose (`api` + `db`) | Brez Celery/Redis — obseg (5–25 slik/teden) tega ne potrebuje |

## Moduli

| Modul | Odgovornost | Datoteke |
|---|---|---|
| `apps/mobile` | Kamera, izbira predmeta, lokalna baza, zgodovina, upload worker, brisanje arhiviranih snovi, reševanje kvizov | `apps/mobile/` (od V1-R01; upload worker od V1-R02; brisanje od V1-R07; kvizi od V2-R02) |
| `apps/server` | Prevzem slik (`POST /materials`), preverba ključa, shramba, operaterska stran `/admin`, vision obdelava v ozadju, arhiv, sestavljalnik kvizov, poskusi reševanja | `apps/server/` (od V1-R02; `/admin` od V1-R04; obdelava od V1-R03; arhiv od V1-R07; kvizi od V2-R01; poskusi od V2-R02) |

Ločena mapi namenoma ne delita orodij za monorepo (npr. Turborepo) — gre za
dva jezika (TypeScript / Python) brez skupne kode, zato vsaka živi s svojim
običajnim orodjem (`npm`/`package.json` v `apps/mobile`,
`pip`/`pyproject.toml` v `apps/server`).

### Notranja delitev `apps/mobile`

| Mapa | Odgovornost |
|---|---|
| `app/` | zasloni; usmerjanje je datotečno (`expo-router`) |
| `src/constants/` | seznam desetih predmetov (`{ value, label }`); od V2-R02 še štiri ocene samoocene (`ocene.ts`) |
| `src/config/` | kar pride v aplikacijo ob gradnji: naslov strežnika, API ključ in oznaka gradnje |
| `src/db/` | verzionirana shema (migracije) in poizvedbe nad tabelo `materials`; od V2-R02 še nad tabelami kvizov (`kvizi.ts`) |
| `src/sync/` | prenos na strežnik: en prenos, čakalna vrsta, priklop na življenjski cikel; od V1-R07 tudi brisanje snovi, ki so na strežniku arhivirane; od V2-R02 usklajevanje kvizov in poskusov (`kvizi.ts`, `use-kvizi.tsx`) in skupni klic s časovno omejitvijo (`http.ts`). **Edina mapa v aplikaciji z omrežnim klicem.** |
| `src/photos/` | stiskanje slike in zapis v `documentDirectory/photos/` |
| `src/materials/` | shranjevanje posnetka: najprej datoteka, nato vrstica |
| `src/capture/` | stanje zaslona s kamero (kamera ↔ predogled) |
| `src/ui/` | skupni gradniki in barve |
| `src/types.ts` | tip `Material` (ena vrstica tabele `materials`); od V2-R02 še kviz, postavka, poskus in ocena |
| `plugins/` | Expo config plugini — koda, ki teče **ob gradnji**, ne v aplikaciji |
| `__tests__/` | enotski in komponentni testi |

**React Compiler je izklopljen.** Expo predloga ga vklopi
(`experiments.reactCompiler`), vendar ga `jest` ne uporablja — zastavica pride
iz Babelovega `caller`, ki ga testni prevod ne nastavi, in je z nastavitvijo
preseta ni mogoče vsiliti. Testi bi torej preverjali drugače preveden kod, kot
se namesti na telefon. Ker aplikacija ni zahtevna in je varnostna mreža tega
projekta prav v testih, je skladnost pomembnejša od memoizacije. Če ga bomo
kdaj vklopili, mora zraven priti način, da isto velja tudi v testih.

Android riše *edge-to-edge* (privzeto od Expo SDK 54), zato vsak zaslon z
vsebino ali gumbi ob spodnjem robu prišteje `useSafeAreaInsets().bottom` —
sicer konča pod sistemsko navigacijsko vrstico. `SafeAreaProvider` postavi
`expo-router` sam, zato ga v `app/_layout.tsx` ni.

Dostop do baze teče skozi tanek vmesnik `MaterialsDatabase`
(`src/db/materials.ts`), ki ga funkcije dobijo kot argument. `expo-sqlite` se
pojavi samo v `src/db/open.ts` in v korenski postavitvi, zato je poslovna
logika testljiva brez naprave.

### Notranja delitev `apps/server`

| Datoteka | Odgovornost |
|---|---|
| `app/main.py` | tovarna aplikacije, življenjski cikel (zagon in ustavitev obdelave) |
| `app/routers/materials.py` | `POST /materials` — prevzem slike s telefona |
| `app/routers/admin.py` | operaterska stran: predmeti, snov, arhiv, brisanje |
| `app/routers/kvizi.py` | sestavljalnik kvizov pod `/admin/quizzes` (V2-R01) |
| `app/routers/resevanje.py` | poti telefona za kvize: `GET /quizzes/pending`, `POST /quiz-attempts` (V2-R02) |
| `app/db.py` | motor, seje ter `MaterialsRepository` in `KviziRepository` — edina pot do baze |
| `app/models.py` | tabele `materials`, `questions`, `quizzes`, `quiz_items` in `question_attempts` |
| `app/storage.py` | zapis, meja mape in brisanje slik na disku |
| `app/vision.py` | **edini modul, ki uvaža `openai`**: prompt, shema odgovora, klic |
| `app/obdelava.py` | kaj se zgodi z enim zapisom: prevzem, klic, zapis izida. Sinhron |
| `app/worker.py` | časovnik: obhodi v presledkih, zagon in ustavitev. Brez poslovne logike |
| `app/settings.py` | nastavitve iz okolja |
| `app/subjects.py` | predmeti in slovenske oznake stanj |
| `app/casi.py` | domači časovni pas, ure za prikaz, meji koledarskega dne (V2-R01); `utc` za čase v odgovorih telefonu (V2-R02) |
| `app/strani.py` | izrisovalnik predlog in strani 404/409 (V2-R01) |
| `app/besedilo.py` | slovenske oblike števil (dvojina) |

`app/casi.py`, `app/strani.py` in `app/besedilo.py` niso nove plasti, ampak
**izvlečki** iz usmerjevalnikov. Prva dva sta nastala v V2-R01 zaradi krožnega
uvoza: `kvizi` potrebuje `daj_predloge` in obe strani z napako, `admin` pa
seznam kvizov — če bi oboje ostalo v `admin.py`, bi krog `admin → kvizi →
admin` padel ob uvozu. Tretji je prišel s popravkom dvojine, ko je isto
jezikovno pravilo potreboval še `admin`.

Odslej velja: **kar potrebujeta oba usmerjevalnika, ni last nobenega od njiju**
in ima javno ime, brez podčrtaja. Podčrtaj pomeni „ne uvažaj tega od zunaj",
in uvoz od zunaj je prav razlog, da tak modul obstaja.

Delitev med `obdelava.py` in `worker.py` je namenska: poslovna logika ne ve za
`asyncio`, zato je testljiva brez zaganjanja zanke. Delitev med `vision.py` in
vsem ostalim zahteva ADR-008 — menjava modela ali ponudnika mora biti sprememba
ene datoteke in ene spremenljivke okolja.

## Podatkovni model

### Telefon — SQLite (`school-companion.db`)

Tabela `materials`:

| Stolpec | Tip | Opomba |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | UUID, generiran na telefonu (`expo-crypto`) |
| `subject` | `TEXT NOT NULL` | koda predmeta, npr. `MAT` |
| `taken_at` | `TEXT NOT NULL` | ISO 8601 v UTC; **trenutek posnetka**, ne shranjevanja |
| `file_uri` | `TEXT NOT NULL` | `documentDirectory/photos/<id>.jpg` |
| `sync_status` | `TEXT NOT NULL` | `pending` → `synced`, ali `failed` |
| `sync_attempts` | `INTEGER NOT NULL DEFAULT 0` | neuspeli poskusi; zapis za vmesnik in diagnostiko (V1-R02) |
| `last_attempt_at` | `TEXT` | ISO 8601 v UTC; `NULL`, dokler poskusa ni bilo (V1-R02) |
| `sync_error` | `TEXT` | zakaj zadnji poskus ni uspel (V1-R02) |

V1-R07 lokalne sheme **ni** spremenila: telefon o arhivu ne hrani ničesar,
ker delovni seznam pride vsakič v celoti s strežnika. `SHEMA_VERZIJA` je takrat
ostala 1; na 2 jo je dvignila V2-R02 s tabelami kvizov (spodaj).

Indeks `materials_subject_taken_at (subject, taken_at DESC)` — zgodovina bere
po predmetu in po času navzdol. Čakalna vrsta bere obratno (`taken_at ASC`),
da najstarejši posnetek ne čaka najdlje.

Meja med `pending` in `failed` ni število poskusov, ampak ali se stanje more
spremeniti samo od sebe: 4xx razen 408 in 429 je sodba o vsebini zahteve in
gre v `failed`, omrežna napaka in 5xx ostaneta `pending`. Iz `failed` zapis
vrne samo gumb „Poskusi znova". Glej `docs/odlocitve/ADR-004`.

#### Migracije lokalne sheme

Shema je verzionirana prek `PRAGMA user_version` (`src/db/migrations.ts`);
trenutna verzija je **2**. `CREATE TABLE IF NOT EXISTS` obstoječi tabeli
novega stolpca ne doda in tega ne javi, zato bi se brez migracij telefon z
zapisi iz V1-R01 tiho pokvaril, testi nad svežo bazo pa bi bili zeleni.

Dve pravili, ki veljata odslej:

- **Sveža namestitev gre skozi isto zaporedje migracij kot nadgradnja.** Dve
  poti bi pomenili dve shemi, od katerih bi bila testirana samo ena.
- **Stare migracije se ne popravljajo.** Telefon, ki je migracijo že prestal,
  je nikoli več ne požene; kar je narobe, popravi nova migracija.

`CREATE_MATERIALS_TABLE_SQL` v `src/db/materials.ts` je zamrznjena shema
V1-R01 in se ne dopolnjuje. Test migracije teče nad njeno dobesedno kopijo v
`__tests__/test-database.ts`, ne nad shemo iz kode — sicer bi migracijo
preverjal nad tem, kar sam ustvari.

Isto velja za migracijo 2: `CREATE_KVIZI_TABLES_SQL` v `src/db/kvizi.ts` je
zamrznjena, test pa teče nad `SHEMA_VERZIJE_1` — dobesedno kopijo baze po
migraciji 1, z vrsticami, kakršna je na Mašinem telefonu pred V2-R02.

#### Tabele kvizov (migracija 2, V2-R02)

| Tabela | Stolpci | Opomba |
|---|---|---|
| `quizzes` | `id`, `name`, `created_at` | kviz s strežnika; vsebina je zamrznjena in se ne prepisuje |
| `quiz_items` | `id`, `quiz_id`, `position`, `question_text`, `answer_text`, `answered_on_server` | indeks `(quiz_id, position)`; `answered_on_server` je 1, kadar je postavka odgovorjena že na strežniku (`ADR-019` E) |
| `attempts` | `id`, `quiz_id`, `quiz_item_id` (`UNIQUE`), `mode`, `rating`, `shown_at`, `revealed_at`, `answered_at`, `uploaded_at` | poskus = dogodek; `uploaded_at` je `NULL`, dokler ni prenesen |

**Stanje kviza se ne shranjuje, izpelje se.** Postavka je odgovorjena, če ima
lokalni poskus ali `answered_on_server = 1`; kviz čaka, dokler ima vsaj eno
neodgovorjeno postavko. To pravilo živi v eni poizvedbi (`cakajociKvizi`), ki
jo bereta števec na domači strani in seznam kvizov.

`attempts` **nima tujega ključa** na `quizzes`: kviz se lahko pobriše
(preklic, `ADR-019` C), preden so njegovi poskusi preneseni. Prenesen poskus
dobi `uploaded_at` in se ne pobriše takoj — dokazuje, da je postavka
odgovorjena, dokler strežnik kviza ne neha vračati. Pobriše se skupaj s svojim
kvizom; če je kviz šel že pred prenosom (preklic), pa v istem obhodu, v katerem
je prenesen — `oznaciPrenesene` teče pred `pobrisiKvizeRazen`.
**Neprenesen poskus se ne pobriše nikoli.**

### Strežnik — PostgreSQL

Tabela `materials` (nastane v V1-R02, razširi jo V1-R03):

| Stolpec | Tip | Opomba |
|---|---|---|
| `id` | `VARCHAR(36) PRIMARY KEY` | UUID s telefona; nosilec idempotentnosti |
| `subject` | `VARCHAR(16) NOT NULL` | koda predmeta |
| `taken_at` | `TIMESTAMPTZ NOT NULL` | trenutek posnetka, normaliziran v UTC |
| `image_path` | `VARCHAR(1024) NOT NULL` | pot do slike na disku strežnika |
| `status` | `VARCHAR(16) NOT NULL` | `new` → `processing` → `ready` \| `failed` |
| `received_at` | `TIMESTAMPTZ NOT NULL` | kdaj je strežnik zapis prevzel |
| `archived_at` | `TIMESTAMPTZ` | kdaj je bil umaknjen v arhiv; `NULL` = aktiven (V1-R07) |
| `device_deleted_at` | `TIMESTAMPTZ` | kdaj je telefon potrdil, da ga pri njem ni več (V1-R07) |
| `readable` | `BOOLEAN` | ali je model s slike znal brati (V1-R03) |
| `transcript` | `TEXT` | prepis (V1-R03) |
| `summary` | `TEXT` | povzetek (V1-R03) |
| `prompt` | `TEXT` | poslani prompt, v celoti (V1-R03) |
| `raw_response` | `TEXT` | odgovor modela pred razčlenjevanjem (V1-R03) |
| `model` | `VARCHAR(128)` | ime modela, kot ga je vrnila storitev (V1-R03) |
| `input_tokens`, `output_tokens` | `INTEGER` | poraba (V1-R03) |
| `error` | `TEXT` | zakaj obdelava ni uspela (V1-R03) |

Vsi stolpci V1-R03 so `NULL`-abilni — vrstice iz V1-R02 so morale migracijo
prestati nedotaknjene in jih worker pobere kot vsako drugo.

Tabela `questions` (V1-R03):

| Stolpec | Tip | Opomba |
|---|---|---|
| `id` | `VARCHAR(36) PRIMARY KEY` | UUID, generiran **na strežniku** |
| `material_id` | `VARCHAR(36)` | tuji ključ na `materials.id`, `ON DELETE SET NULL`, indeksiran; `NULL`, ko je material dokončno izbrisan (V1-R07) |
| `subject` | `VARCHAR(16)` | predmet materiala, prepisan ob nastanku (V1-R07) |
| `material_taken_at` | `TIMESTAMPTZ` | čas posnetka materiala, prepisan ob nastanku (V1-R07) |
| `position` | `INTEGER NOT NULL` | zaporedje znotraj **serije**, od 1 |
| `question` | `TEXT NOT NULL` | besedilo vprašanja |
| `answer` | `TEXT NOT NULL` | pričakovan odgovor |
| `retired_at` | `TIMESTAMPTZ` | kdaj je bilo vprašanje upokojeno; `NULL` = veljavno (V2-R05) |

Vprašanja imajo svojo tabelo in ne polja JSON, ker bo `V2-R02` ocene težavnosti
vezala na `question_id`.

**Vprašanje je trajno.** Do V2-R05 ni bilo: ponovna obdelava je prejšnji izid
zavrgla skupaj z vsemi vprašanji materiala. `docs/odlocitve/ADR-015` to
nadomesti — dosedanja vprašanja dobijo `retired_at` in nova serija nastane
poleg. **Brisanja vprašanj v strežniku ni nikjer več.** Ostali del prejšnjega
izida (prepis, povzetek, revizijska sled) se še naprej prepiše, kot pravi
`ADR-009`.

`retired_at` je svoja os in ne novo stanje, po istem vzorcu kot
`materials.archived_at` (`ADR-011`). „Vprašanja materiala" odslej povsod
pomeni `retired_at IS NULL`; `position` je enolična znotraj serije in ne
znotraj materiala, ker se z vsako obdelavo začne znova. Serija se prepozna po
skupnem `retired_at` — dodatnega stolpca za oznako serije ni.

**Vprašanje material preživi.** Do V1-R07 je bila kaskada nastavljena dvakrat
(`ondelete="CASCADE"` v shemi in `cascade="all, delete-orphan"` v ORM);
`docs/odlocitve/ADR-012` je obe odstranil, ker vprašanje nosi statistiko, ki
jo bo V2 vezala nanj. Ob brisanju materiala ORM otrokom postavi
`material_id = NULL` — tudi na SQLite, kjer tuji ključi privzeto niso
uveljavljeni, zato testi še naprej dokazujejo isto kot produkcija.

Zaradi obojega ima `Material` **tri** zveze na `questions` in nobene z imenom
`questions`:

| Zveza | Kaj vrne | Zakaj obstaja |
|---|---|---|
| `vsa_vprasanja` | veljavna in upokojena | Edina pisljiva. Nosi vstavljanje nove serije **in** ORM-jevo nuliranje `material_id` ob brisanju materiala — filtrirana zveza upokojenih ne bi videla in ta bi ostala z visečim ključem tam, kjer tuji ključ ni uveljavljen |
| `veljavna_vprasanja` | `retired_at IS NULL` | To, kar `ADR-015` misli z „vprašanja materiala". Edina, ki jo bere vmesnik |
| `upokojena_vprasanja` | `retired_at IS NOT NULL` | Števec na strani s podrobnostmi |

Filtrirani sta `viewonly=True`; brez tega bi SQLAlchemy tri zveze nad istim
tujim ključem razumel kot tri poti, ki si lastijo `material_id`. Zveza
`questions` je bila **preimenovana in ne le filtrirana** namenoma: nevtralno
zveneče ime je past, ker pozabljen filter nad svežo bazo ni viden — material
ima takrat natanko eno serijo. Preimenovanje pomete čez bralce s `mypy`.

Upokojitev opravi `MaterialsRepository._upokoji_vprasanja`: en `UPDATE ...
WHERE material_id = ? AND retired_at IS NULL`, brez `commit` (klicatelj
commita, da sta upokojitev in nova serija ena transakcija) in s
`synchronize_session="fetch"`, da dobijo žig tudi predmeti, naloženi v isti
seji pred stavkom.

Denormalizirana `subject` in `material_taken_at` sta tam zato, da vprašanje
brez materiala še vedno pove, iz katere snovi in katerega dne je.

`id` je `VARCHAR` in ne `UUID`, čas pa `DateTime(timezone=True)`, ker mora ista
shema stati nad Postgresom (produkcija) in nad SQLite (testi).

Tabela `quizzes` (V2-R01):

| Stolpec | Tip | Opomba |
|---|---|---|
| `id` | `VARCHAR(36) PRIMARY KEY` | UUID, generiran **na strežniku** |
| `name` | `VARCHAR(200) NOT NULL` | sestavi se samodejno (`MAT — 9. 9. 2026`), operater ga sme prepisati |
| `subject` | `VARCHAR(16)` | koda predmeta; `NULL` = kviz čez več predmetov |
| `created_at` | `TIMESTAMPTZ NOT NULL` | čas objave — osnutkov ni, zato je to hkrati čas nastanka |
| `canceled_at` | `TIMESTAMPTZ` | kdaj je bil preklican; `NULL` = objavljen |
| `solved_at` | `TIMESTAMPTZ` | kdaj je bil rešen; `NULL` = kakšna postavka še nima poskusa (V2-R02) |

Tabela `quiz_items` (V2-R01):

| Stolpec | Tip | Opomba |
|---|---|---|
| `id` | `VARCHAR(36) PRIMARY KEY` | UUID, generiran na strežniku |
| `quiz_id` | `VARCHAR(36) NOT NULL` | tuji ključ na `quizzes.id`, `ON DELETE CASCADE`, indeksiran |
| `question_id` | `VARCHAR(36)` | tuji ključ na `questions.id`, `ON DELETE SET NULL`, indeksiran |
| `position` | `INTEGER NOT NULL` | zaporedje **čez cel kviz**, od 1 |
| `question_text` | `TEXT NOT NULL` | kopija besedila vprašanja ob objavi |
| `answer_text` | `TEXT NOT NULL` | kopija odgovora ob objavi |

**Kviz nima stolpca `status`.** Stanje se izpelje iz `canceled_at` in
`solved_at`, po istem vzorcu, kot sta arhiv (`ADR-011`) in upokojitev
(`ADR-015`) svoji osi in ne novo stanje. Objavljen kviz je preprosto kviz, ki
obstaja.

**Osi sta neodvisni.** Preklican kviz je lahko tudi rešen — telefon je poskuse
zanj morda dal, preden je izvedel za preklic, in strežnik jih sprejme
(`ADR-019` C). Pri prikazu ima **preklic prednost**: seznam na `/admin` in stran
kviza takrat kažeta „preklican".

`solved_at` je prišel z V2-R02 in ne z V2-R01, ker ga je edina znala napolniti
(`ADR-017` C). Postavi ga **strežnik sam**, v isti transakciji kot poskus, ki
zapolni zadnjo postavko, in ga ne premakne nikoli več. Čas je strežnikov:
časi s telefona so zapisani pri vsakem poskusu posebej.

**Postavka zamrzne dvoje.** `question_id` nosi identiteto, ki jo bo
potrebovala `V2-R04`; `question_text` in `answer_text` nosita berljivost, ko
bo izvorna snov dokončno izbrisana in bo `questions.material_id` `NULL`
(`ADR-016` E). Ponovna obdelava ali brisanje snovi objavljenega kviza zato ne
spremenita.

**`quiz_items` nima stolpca `material_id`.** Pot do snovi gre prek
`question_id → questions.material_id`, kar vzdrži, ker se vprašanja nikoli ne
brišejo, po brisanju materiala pa je snov razpoznavna iz denormaliziranih
`questions.subject` in `questions.material_taken_at` (`ADR-017` B). Isti par
stolpcev odgovori na vprašanje „iz katere snovi je to vprašanje", ko materiala
ni več.

**Tuji ključ `quiz_items → quizzes` je edina kaskada brisanja v shemi.**
Postavka brez kviza nima pomena, za razliko od vprašanja brez materiala, ki
nosi statistiko in mora preživeti (`ADR-012`). Kvizov se sicer ne briše —
kaskada je tam zato, da shema pove resnico, ne zato, da bi jo kdo uporabljal.

Zveza `QuizItem.question` je **enosmerna**: `Question` povratne nima. Povratna
bi ORM-ju dala pot, po kateri bi ob brisanju vprašanja nulil `question_id` —
vprašanja pa se ne brišejo, zato bi bila to mrtva pot z živimi posledicami.

Tabela `question_attempts` (V2-R02):

| Stolpec | Tip | Opomba |
|---|---|---|
| `id` | `VARCHAR(36) PRIMARY KEY` | UUID, generiran **na telefonu**; nosilec idempotentnosti |
| `quiz_item_id` | `VARCHAR(36) NOT NULL` | tuji ključ na `quiz_items.id`, **brez `ondelete`**; `UNIQUE` |
| `mode` | `VARCHAR(16) NOT NULL` | način odgovarjanja; zaenkrat vedno `samoocena` (`ADR-014`) |
| `rating` | `VARCHAR(16) NOT NULL` | `nisem_vedela`, `tezko`, `srednje` ali `lahko` |
| `shown_at`, `revealed_at`, `answered_at` | `TIMESTAMPTZ NOT NULL` | pokazano, razkrit odgovor, ocenjeno — s telefona (`ADR-019` D) |
| `received_at` | `TIMESTAMPTZ NOT NULL` | kdaj je strežnik poskus prevzel |

**Poskus je dogodek, ne števec** (`ADR-012`): ena vrstica na odgovor, ponovljen
prenos istega `id` ne naredi nič. **Pravilnost se ne shranjuje** — izpelje se iz
ocene, da bi drugačna izpeljava veljala tudi za nazaj (`ADR-014`).

**Postavka ima največ en poskus** (`ADR-019` E). Enoličnost je v shemi in ne le
v repozitoriju; drugi poskus za isto postavko strežnik sprejme kot uspeh, a ga
ne zapiše. `question_id` tu ni, ker je izpeljiv prek `quiz_items.question_id`.

Tuji ključ na postavko je **brez kaskade in brez `SET NULL`**: poskus nosi
statistiko, zato naj baza brisanje kviza s poskusi raje zavrne, kot da jih
vzame s sabo. `quiz_items → quizzes` ostaja edina kaskada v shemi.


Migracija `0003_arhiv` prevesi tuji ključ `questions.material_id` s `CASCADE`
na `SET NULL`. Na SQLite gre to skozi `op.batch_alter_table` s `copy_from`
(tabela se prepiše na novo, ker `ALTER` tujega ključa tam ne obstaja), na
Postgresu z navadnim `ALTER`. Ime starega ključa je dialektni privzetek
(`questions_material_id_fkey`), novi je poimenovan.

Migracija `0004_upokojena_vprasanja` doda `questions.retired_at`. Gol
`ADD COLUMN`, `NULL`-abilen in brez privzetka: obstoječe vrstice ostanejo
`NULL`, torej veljavne, in prepisa podatkov ni. Njen `downgrade` stolpec
spusti — nobene vrstice ne izgubi, pač pa **dokončno izgubi podatek o
upokojitvi**, zato je vrnitev čezenj smiselna samo nad bazo, v kateri se
ponovna obdelava še ni zgodila.

Migracija `0005_kvizi` ustvari `quizzes` in `quiz_items` ter oba indeksa.
Nobenega obstoječega stolpca se ne dotakne, zato obstoječih vrstic ni treba
ne prepisovati ne polniti. Njen `downgrade` obe tabeli spusti — in s tem
**dokončno izgubi vse kvize**, za razliko od `downgrade` v `0004`, ki
izgubi le podatek o upokojitvi. Vrstni red je obrnjen (najprej otrok),
sicer bi tuji ključ na Postgresu brisanje `quizzes` zavrnil.

Migracija `0006_poskusi` doda `quizzes.solved_at` (gol `ADD COLUMN`,
`NULL`-abilen) in ustvari `question_attempts`. Obstoječi kvizi ostanejo
nerešeni, kar je res. Njen `downgrade` tabelo in stolpec spusti in s tem
**dokončno izgubi vse poskuse in podatek o rešenosti**; kvizi ostanejo, a bi
jih ponoven `upgrade` naredil nerešene in telefon bi jih prenesel znova.

Migracije vodi **Alembic** (`apps/server/alembic/`). Prva migracija ustvari
razširitev `vector` — vektorskih stolpcev še ni, iskanje po pomenu je V2.
`alembic/env.py` povezavo bere iz `DATABASE_URL`, vendar **samo, kadar url ni
že izrecno nastavljen**; obratna prednost bi pomenila, da se testi migracije
povežejo na živo bazo.

Isti `env.py` kliče `fileConfig(..., disable_existing_loggers=False)`. Privzeti
`True` utiša vse že ustvarjene zapisovalnike: v produkciji je to nevidno, ker
`alembic upgrade head` teče kot svoj proces pred `uvicorn`, v testih pa Alembic
teče v istem procesu in bi migracija tiho ugasnila dnevnik aplikacije za vse
teste za sabo. Odkrito v V1-R03, ko je test dnevniškega zapisa ob manjkajočem
`OPENAI_API_KEY` padel samo v celotni zbirki, ne pa sam.

Slike živijo v `/data/images/<id>.jpg`. Zapis gre najprej v
`/data/images/.tmp/` pod enoličnim imenom in se na končno mesto premakne
atomarno; vrstica v bazi nastane šele za datoteko. Prekinjen prenos zato ne
pusti polovične slike na mestu, kjer jo bo V1-R03 iskal kot celo.

## Prenos telefon → strežnik

`POST /materials` sprejme multipart z `id`, `subject`, `taken_at` in `file`.
Prvi prenos vrne **201**, ponoven prenos istega `id` **200** in polje
`created: false` — telefon oboje šteje za uspeh. Obstoječi zapis se ne prepiše
in slika se ne povozi.

Od V1-R07 obstaja tretji izid: **410** za zapis, ki je medtem šel v arhiv.
Telefon ga zbriše pri sebi in ne šteje za neuspeh. Brez tega bi posnetek, ki
je na telefonu obtičal v `pending`, tam ostal za vedno — z delovnega seznama
je lahko že padel, ker je bilo brisanje na napravi že potrjeno.

Ključ preverja **ASGI vmesna plast**, ne odvisnost endpointa: FastAPI telo
zahteve prebere pred razreševanjem odvisnosti, zato bi strežnik večmegabajtno
sliko najprej prebral in šele nato ugotovil, da ključ ne velja. Izvzeta sta
`GET /health` in celotna predpona `/admin`.

Izvzetje predpone je **varnostna meja, ne priročnost**: ujame se na `/admin`
in na `/admin/...`, nikoli na pot, ki se le začne enako (`/administration`).
Da izvzetje ne odpre ničesar drugega, dokazuje razred
`TestKljucOstajaZahtevanDrugod` v `tests/test_admin.py` — brez njega bi bila
sprememba te vrstice nevidna do dneva, ko bi bilo prepozno.

Na telefonu prenos teče prek `File.upload` iz `expo-file-system` (nativni
multipart naravnost z diska, brez nalaganja v pomnilnik JS), s časovno
omejitvijo 60 s. Omejitev ni okras: cikel, ki se ne konča, pusti zaporo
workerja postavljeno in worker je do ponovnega zagona aplikacije mrtev.

Worker teče **samo, dokler je aplikacija v ospredju**: poskusi ob zagonu, po
vsakem uspešnem *Shrani* in nato vsakih 30 s, po neuspehu s podvojevanjem
zamika do 5 minut. Prenaša zaporedno, enega za drugim. Po *Shrani* se prenos
samo sproži — nanj se **ne čaka**, sicer bi zaporedno slikanje ob nedosegljivem
strežniku obtičalo in ADR-003 bi padel.

## Vision obdelava (V1-R03)

Zanka teče kot `asyncio` opravilo v procesu `api`, priklopljeno na `lifespan`.
Vsakih 30 s (`WORKER_INTERVAL_SECONDS`) pobere zapise s `status='new'`,
najstarejši posnetek prvi, in jih obdela **zaporedno**. Samo delo teče v niti
(`asyncio.to_thread`), ker sta SQLAlchemy in odjemalec OpenAI sinhrona; brez
tega bi en klic za sto sekund ustavil celoten strežnik.

Zapis se prevzame s **pogojnim** `UPDATE ... WHERE status='new'` in delo se
nadaljuje samo, če je bila spremenjena natanko ena vrstica. Danes teče en sam
proces `uvicorn` in tekmovanja ni; pogoj je tu zato, da ga tudi ne bo, če kdaj
kdo doda `--workers`. Prevzem in zapis izida sta ločeni transakciji, ker med
njima teče klic, ki traja sekunde.

Prehodi stanj:

| Iz | V | Kdaj |
|---|---|---|
| `new` | `processing` | prevzem v obhodu zanke |
| `processing` | `ready` | klic je uspel (tudi kadar je slika neberljiva) |
| `processing` | `failed` | napaka klica, neveljaven odgovor ali manjkajoča slika |
| `processing` | `new` | ob zagonu strežnika (obtičal zapis) ali če izida ni kam zapisati |
| `ready` \| `failed` \| `new` | `new` | gumb „Pošlji v obdelavo" na admin strani |

Gumb „Pošlji v obdelavo" zavrže prepis, povzetek in revizijsko sled, dosedanja
vprašanja pa **upokoji** (`ADR-015`) — že takrat in ne šele ob novem izidu, ker
bi snov sicer ves čas klica kazala stara vprašanja ob praznem prepisu. Stran s
podrobnostmi zato pove, koliko upokojenih vprašanj snov ima; brez tega števila
je razlika med „ni vprašanj" in „vsa so upokojena" nevidna.

**Neberljiva slika ni peti status.** Klic je uspel in bil plačan, torej to ni
napaka obdelave: zapis je `ready` s `readable=false`, brez prepisa in brez
vprašanj. Razliko pokaže oznaka „obdelano — slika ni berljiva".

**Vrstica brez datoteke na disku gre v `failed` brez klica** — za sliko, ki je
ni, ne plačamo. Meja `images_dir` je ista kot pri streženju slike na admin
strani.

Klic gre skozi `app/vision.py` in nikjer drugje (ADR-008). Slika potuje kot
base64 v `data:` URL, ker je strežnik za Tailscale in OpenAI do njegovih
naslovov nima dostopa. Odgovor je strukturiran po shemi (`json_schema`,
`strict: true`), a gre vseeno skozi preverbo s Pydantic: `strict` je obljuba
storitve, ne naša invarianta, in ne zna povedati „med 5 in 10 vprašanj" —
`minItems` v strogem načinu ni podprt, zato to mejo uveljavimo ob sprejemu.

**Revizijska sled se zapiše ob vsakem izidu, tudi neuspešnem:** poslani prompt
(v celoti, ne kot oznaka različice), surov odgovor, ime modela in poraba
tokenov. Brez tega primerjave med modeli, ki jo ADR-008 predvideva, ne bo
mogoče narediti z dejanskimi podatki. Cene v evre ne računamo — cenik v
nastavitvah bi se staral neopazno.

Zaustavitev strežnika ne čaka ne celega razmika ne cele serije: dogodek
ustavitve gre tudi v obhod, ki ga pogleda **med** zapisi. Zapis, ki je takrat
že v teku, se dokonča — prekinjen klic bi bil plačan in zavržen.

**Znana omejitev: obdelava je vezana na en proces `api`.** Obnovitev obtičalih
ob zagonu stoji na sklepu „ta hip ni v obdelavi nič", ki drži samo pri enem
procesu. Če bi kdo dodal `uvicorn --workers`, bi zagon drugega procesa vrnil v
`new` prav tiste zapise, ki jih prvi obdeluje, in slika bi bila plačana
dvakrat. Pogojni prevzem tega ne prepreči, ker gre za dva zaporedna, vsak zase
veljavna prehoda. Prava rešitev, če bo kdaj potrebna, je zaklep na ravni baze,
ne več procesov.

**Brez `OPENAI_API_KEY` se zanka sploh ne zažene.** Slike ostanejo `new` in se
obdelajo same, ko je ključ nastavljen in strežnik zagnan znova; razlog gre v
dnevnik ob zagonu. Prevzem slik, admin stran in `GET /health` tečejo naprej.
Napačen (od storitve zavrnjen) ključ pa je `failed` kot vsaka druga napaka
klica. Glej `docs/odlocitve/ADR-009`.

## Operaterska stran (`/admin`)

Strežniško izrisan HTML za lastnika sistema (`docs/00-namen.md`, vloga
„spremlja delovanje"). Brez JavaScripta, brez gradnje frontenda, brez `npm` v
`apps/server`. Nastala v V1-R04; V1-R03 jo je razširila s prikazom obdelave.

| Pot | Metoda | Kaj |
|---|---|---|
| `/admin` | GET | vseh deset predmetov s števci; predmet iz baze, ki ga na seznamu ni, je viden pod svojo kodo |
| `/admin/subjects/{koda}` | GET | slike predmeta, najnovejša prva, lena naložitev |
| `/admin/materials/{id}` | GET | podrobnosti ene slike |
| `/admin/materials/{id}/image` | GET | datoteka slike |
| `/admin/archive` | GET | arhivirane snovi, najnovejše arhivirane prve (V1-R07) |
| `/admin/materials/{id}/archive` | GET | potrditvena stran za arhiviranje (V1-R07) |
| `/admin/materials/{id}/archive` | POST | umakne v arhiv in preusmeri (303) (V1-R07) |
| `/admin/materials/{id}/purge-image` | POST | pobriše samo datoteko (V1-R07) |
| `/admin/materials/{id}/delete` | GET | potrditvena stran za dokončno brisanje |
| `/admin/materials/{id}/delete` | POST | dokončno izbriše in preusmeri (303) |
| `/admin/materials/{id}/reprocess` | POST | vrne v vrsto, vprašanja upokoji, preusmeri (303) |
| `/admin/quizzes/new` | GET | izbirnik slik za enega od treh vstopov (V2-R01) |
| `/admin/quizzes/new` | POST | isti izbirnik ob vrnitvi iz predogleda, z ohranjenim izborom (V2-R01) |
| `/admin/quizzes/preview` | POST | predogled izbranih vprašanj; **ničesar ne shrani** (V2-R01) |
| `/admin/quizzes` | POST | objavi kviz in vse postavke v eni transakciji, preusmeri (303) (V2-R01) |
| `/admin/quizzes/{id}` | GET | kviz s postavkami (V2-R01) |
| `/admin/quizzes/{id}/cancel` | POST | prekliče kviz, preusmeri (303) (V2-R01) |

Poti so angleške kot obstoječi API, vidno besedilo slovensko. **Prijave ni** —
meja je Tailscale; posledice, vključno s CSRF, so v `docs/odlocitve/ADR-006`.

Napake pod `/admin` (404, 405) izriše prestreznik `StarletteHTTPException`,
registriran v `create_app`. Izven te predpone se umakne privzetemu, ker morajo
odgovori `POST /materials` ostati JSON — telefon tam pričakuje sporočilo o
napaki, ne strani. Prvi poskus je bila pot `/{ostanek:path}` na koncu
usmerjevalnika; ta je prekrila Starlettejevo preusmeritev ob končni poševnici,
zato je `GET /admin/` vrnil 404 s trditvijo, da strani ni. Prestreznik se
sproži šele, ko poti res ni.

Koda predmeta sme vsebovati karkoli (`POST /materials` jo omejuje samo po
dolžini), zato je pot `subjects/{koda:path}` in povezava nanjo ubežana za URL.
Brez obojega bi bile slike predmeta s poševnico ali vprašajem iz vmesnika
nedosegljive.

Predloge so v `app/templates/`, pot do njih se izpelje iz `__file__` in ne iz
trenutne mape. `[tool.setuptools.package-data]` v `pyproject.toml` jih vključi
v nameščeni paket; brez te vrstice so testi zeleni, vsebnik pa pade ob prvi
zahtevi. Izrisovalnik živi v `app.state.predloge`, kot vse drugo stanje
aplikacije.

Po brisanju stran pelje na predmet, iz katerega je bila slika — razen kadar
je bila to zadnja slika predmeta, ki ni na seznamu desetih. Tak predmet
obstaja samo, dokler ima kakšno sliko, zato bi bila njegova stran po brisanju
404; v tem edinem primeru pelje na pregled. Kriterij pravi „preusmeri na
seznam predmeta", drug kriterij pa za neznano kodo zahteva 404 — v tem kotu
si nasprotujeta in izbrana je bila stran, ki obstaja.

**Brisanje gre v obratnem vrstnem redu kot sprejem: najprej vrstica, nato
datoteka.** Vrstica brez datoteke je pokvarjen vnos, ki ga operater vidi;
datoteka brez vrstice je nevidna sirota, ki stane samo prostor. Isto pravilo
velja na telefonu.

## Sestavljalnik kvizov (V2-R01)

Trije vstopi v razdelku „Kvizi" na `/admin` vodijo v **isti** izbirnik slik
(`ADR-016` A). Razlikujejo se po dvojem — po obsegu seznama in po tem, kaj je
vnaprej obkljukano; `ADR-016` je predvidel samo drugo, `ADR-017` (A) je prvo
dodal, ker bi dnevni vstop sicer naštel celotno zgodovino vseh predmetov, da
bi obkljukal tri današnje slike.

| Vstop | Kaj seznam našteje | Kaj je obkljukano |
|---|---|---|
| *Nova snov* | vsa nearhivirana snov izbranega predmeta | tista, ki še ni bila v kvizu |
| *Ročna izbira* | vsa nearhivirana snov izbranega predmeta | nič |
| *Kaj smo se danes učili* | današnja nearhivirana snov, čez vse predmete | vsa našteta |

„Danes" pomeni `taken_at` (trenutek posnetka, ne prejema) v pasu
`Europe/Ljubljana`, od polnoči do polnoči, polodprto. Meja se izračuna v
usmerjevalniku (`app/casi.py:dan_od_do`) in se repozitoriju poda kot par UTC
trenutkov — ta za časovne pasove ne ve.

**„Bila v kvizu" pomeni: kakšno njeno veljavno vprašanje je v nepreklicanem
kvizu.** Oba pogoja štejeta (`ADR-017` B): preklican kviz ni bil pravi, zato
se njegova snov spet ponudi, ponovno obdelana snov pa ima novo serijo, ki v
kvizu še ni bila. Poizvedba gre prek `quiz_items → questions.material_id`;
tabele `quiz_sources` ni in po `ADR-016` (D) ne bo, dokler ne bo naključnega
izbora.

Izbirnik so **tri poizvedbe** ne glede na dolžino seznama: ena za snovi, ena
za števila veljavnih vprašanj (`GROUP BY material_id`), ena za množico snovi,
ki so že v kvizu. Sličice se nalagajo z `loading="lazy"`, kot na strani
predmeta. Seznam predmeta bo čez šolsko leto dolg nekaj sto vrstic; če to
kdaj postane neuporabno, je pravi popravek ostranjevanje in ne tiho krajšanje
(`ADR-017` A).

**Snov brez veljavnih vprašanj je vidna, a neizbirna, z razlogom** — molčeč
izpust bi pomenil kviz iz polovice dneva brez sledi, da manjka pol
(`ADR-016` G). Razlogov je **pet**, ne štirje: kriterij našteje „še v
obdelavi", „obdelava ni uspela" in „slika ni berljiva", stanje pa dopušča še
„obdelano, a brez veljavnih vprašanj" — to je snov, ki je bila poslana v
ponovno obdelavo in ima vsa vprašanja upokojena.

**Predogled ničesar ne shrani** (`ADR-016` C). Izbor potuje skozi skrita polja
obrazca, zapis v bazi nastane šele ob „Objavi", v eni transakciji. Osnutkov
zato ni in seznam kvizov kaže samo kvize. Cena je, da zaprt zavihek med
predogledom pomeni izgubljen izbor.

Predogled nosi **dva** obrazca: „Objavi" nosi identifikatorje vprašanj (objavi
se natanko to, kar je bilo videno), „Nazaj na izbor" pa izbor snovi in število
vprašanj na sliko, da je ob vrnitvi izbor tak, kot je bil.

**Objava je edina pot, ki v bazo piše, zato vsakemu polju pogleda pod prste:**
vstop mora biti eden od treh, ime sme meriti 200 znakov in koda predmeta 16
(natanko širina stolpcev), identifikatorji morajo obstajati in se ne smejo
ponoviti. Besedilo se prepiše **iz baze** in nikoli iz obrazca. Preverbi
dolžine sta v kodi in ne prepuščeni bazi, ker testi tečejo nad SQLite, ki
dolžine `VARCHAR` ne uveljavlja — na Postgresu bi bil predolg vnos `DataError`
in operater bi dobil angleški „Internal Server Error".

Upokojitve objava **ne** preverja: vprašanje, ki je bilo upokojeno med
predogledom in klikom na „Objavi", se vseeno objavi. Razlogi so v `ADR-018`.

Polje „vprašanj na sliko" (privzeto 3, meji 1 in 10) se bere kot **niz** in ne
kot `int`: `int` bi ob nerazberljivi vrednosti dal surov angleški 422, pod
predpono, kjer je vse ostalo slovensko. Nerazberljiva vrednost pade na
privzetek in polje to takoj pokaže.

**Vrstni red registracije poti je viden navzven:** `GET /admin/quizzes/new`
mora biti registriran pred `GET /admin/quizzes/{quiz_id}`, sicer FastAPI „new"
prebere kot identifikator kviza.

Razdelek s kvizi na `/admin` stoji **pod** seznamom predmetov. Ime kviza
vsebuje kodo predmeta („MAT — 9. 9. 2026"), zgoraj pa bi ta koda postala prva
pojavitev na strani in podrla test, ki po vrstnem redu pojavitev dokazuje, da
so predmeti našteti po urniku in ne po abecedi.

Števila v besedilu so zapisana s slovensko **dvojino** („2 vprašanji", ne
„2 vprašanj"). To zna `stevilo_z_besedo` iz `app/besedilo.py`; velja za vse
strani, tudi starejše. Glej razdelek „Slovenske oblike števil" spodaj.

## Slovenske oblike števil

Slovenščina je pri števnikih **štirioblična** in ima dvojino: *1 slika,
2 sliki, 3 slike, 5 slik*. `stevilo_z_besedo` (`app/besedilo.py`) to zna;
oblike so **podatek in ne koda** — vsak samostalnik je četverica na enem mestu
(`SLIKE`, `VPRASANJA`, `SNOVI`).

**Ločnica teče po ostanku pri deljenju s sto, ne po zadnji števki.** To ni
mikrooptimizacija, ampak edini način, da sta 21 in 101 obravnavana različno,
čeprav se obe končata z 1: *enaindvajset* se konča z „dvajset" in zahteva
rodilnik množine („21 slik"), *sto ena* pa z „ena" in zahteva ednino
(„101 slika", kot v „101 dalmatinec"). Zato tudi „111 slik" — ostanek je 11.

**Sklanja usmerjevalnik, ne predloga.** Predloga dobi gotov niz, isto pravilo
kot pri `_pogled`: „predloga ne računa in ne oblikuje".

Funkcija pozna število, ne sklona. Kjer besedilo zahteva rodilnik („iz N
snovi"), je oblika pri vsakem številu ista in se zapiše kot konstanta v
predlogi.

Dve mesti sklanjatve **namenoma ne uporabljata**: `snov.html` („Upokojena
vprašanja: 3") in `brisanje.html` („veljavnih: 3, upokojenih: 5"). Oblika z
dvopičjem je pravilna pri vsakem številu; menjava bi bila okus in ne popravek.

Da se dvoobličnost ne prikrade nazaj, jo lovi test nad **datotekami** predlog
in ne nad izrisom: vzorec `{{ "…" if … == 1 else "…" }}` v nobeni predlogi ne
sme obstajati. Prav ta vzorec je bil vir napake, ki je bila vsak dan vidna in
je noben test ni ujel.

## Kvizi na telefonu (V2-R02)

Telefon dobi kviz kot **zaprt objekt s celotno vsebino** in ga reši brez
omrežja. Splošne sinhronizacije vprašanj ni (`ADR-016`, posledice).

### Pogodba

| Pot | Kaj |
|---|---|
| `GET /quizzes/pending` | **celoten delovni seznam** nepreklicanih in nerešenih kvizov, najstarejši prvi, s postavkami; besedilo je zamrznjeno iz `quiz_items`, ne iz `questions`; pri vsaki postavki `answered` |
| `POST /quiz-attempts` | paket do 1000 poskusov; odgovor `200` z `recorded` = koliko jih je bilo res zapisanih |

Obe poti zahtevata API ključ — nista pod `/admin` in izvzetje (`ADR-006`) se ni
razširilo. Vzorec je isti kot pri arhivu: brez kazalca in brez časa zadnje
sinhronizacije (`ADR-011`). Kviz, ki ga na seznamu ni več, je rešen ali
preklican.

**Paket je vse ali nič.** Neveljavna ocena ali način, čas brez pasu,
identifikator, ki ni UUID, ali postavka, ki je ni, dajo `422` in v bazi ne
nastane nič. Ponovljen paket in drugi poskus za isto postavko pa **nista**
napaka: `200` z `recorded: 0`. Telefon ju šteje za uspeh, sicer bi po `ADR-004`
obtičal.

Časi v odgovoru nosijo izrecen pas UTC (`casi.utc`): SQLite vrne naiven čas,
ki bi ga telefon sicer prebral kot svoj lokalni.

### Usklajevanje na telefonu

En obhod (`src/sync/kvizi.ts`): **najprej poskusi gor, nato seznam dol.** Ker
strežnik kviz reši v isti transakciji kot zadnji poskus, je seznam, prebran
po prenosu, že brez pravkar rešenega kviza. Nato se novi kvizi shranijo, pri
obstoječih se posodobi samo `answered_on_server`, lokalni kvizi, ki jih na
seznamu ni, pa se pobrišejo — **razen kviza, ki je ta hip odprt** (`ADR-019` C).

Nerazberljiv odgovor s seznamom kot celota **vrže** in ne vrne praznega
seznama: prazen seznam bi obhod razumel kot „nič več ne čaka" in bi pobrisal
tudi napol rešene kvize.

Ritem ima svoj ponudnik `KviziProvider` (`src/sync/use-kvizi.tsx`) in ne
`SyncProvider`: ob zagonu, ob vrnitvi v ospredje, vsakih 5 minut (ponavljalnik
iz `izbrisi.ts`) in takoj po zadnji oceni kviza. Samo v ospredju.

### Zasloni

Domača stran ima tretji gumb **„Kvizi"**, ki je vedno viden; kadar kaj čaka,
nosi število („Kvizi · 2") in poudarjen rob. Seznam (`app/kvizi/index.tsx`)
kaže čakajoče kvize, najstarejše prve. Reševanje (`app/kvizi/[id].tsx`):
vprašanje → *Pokaži odgovor* → ena od štirih ocen, ki je hkrati „naprej".
Zapuščen kviz se nadaljuje pri prvi neocenjeni postavki. Po zadnji oceni
„Kviz je končan", **brez številk ocen** — rezultat je lastnikov (`ADR-019` B).

### Znane omejitve

- **Trajno zavrnjen paket ustavi tudi dostavo novih kvizov.** Obhod se ob
  neuspešnem prenosu poskusov konča, preden prebere seznam. Pri `422` se to
  ponavlja vsakih 5 minut, poskusi ostanejo na telefonu, novi kvizi pa ne
  pridejo — brez vidne sledi. Nastane lahko samo ob napaki v kodi ali ob
  obnovitvi strežniške baze iz starejše kopije. Odkril pregled V2-R02; odprto
  za odločitev lastnika.
- **Hkratna paketa na strežniku.** Dva hkratna paketa za različni zadnji
  postavki istega kviza drug drugega na Postgresu ne vidita, in `solved_at`
  ostane prazen do naslednjega paketa. Pri enem telefonu z zaporo v
  ponavljalniku se to ne zgodi. Ponovitev ob `IntegrityError` (tekma za isto
  postavko) s testom ni pokrita.
- **`sprozi` med tekočim obhodom ne naredi nič.** Če zadnja ocena pade med
  obhod, gredo poskusi gor v naslednjem obhodu, ne takoj. Podatek se ne izgubi.
- **Odprti kviz se prebere ob začetku obhoda.** Kviz, odprt med obhodom, ki je
  že v teku, se lahko lokalno pobriše, če ga strežnik ne vrača več (preklic).
  Zaslon dela naprej iz pomnilnika, poskusi se zapišejo in prenesejo.
- **`shraniKviz` ni ena transakcija.** Prekinitev sredi shranjevanja pusti kviz
  z manj postavkami; naslednji obhod doda manjkajoče in kviz spet čaka.

## Arhiv in brisanje na telefonu (V1-R07)

Gumb na strani s podrobnostmi **arhivira** in ne briše. Arhiviran zapis izgine
iz števcev na `/admin`, s seznama predmeta in iz vrste za obdelavo, na
strežniku pa ostane s prepisom, povzetkom in vprašanji. Vrnitve iz arhiva ni;
razlogi so v `docs/odlocitve/ADR-011`.

Arhiv je **svoja os in ne peto stanje** `status`: `status` je avtomat obdelave
in arhiviran zapis je lahko hkrati `ready`. Isti razlog kot pri `readable`.

Telefon vsakih 5 minut (in ob zagonu, dokler je aplikacija v ospredju) vpraša
`GET /materials/pending-deletion`. Odgovor je **celoten delovni seznam** —
arhivirano, česar naprava še ni potrdila — in ne odsek za nekim kazalcem.
Seznam se krajša sam, ko telefon potrjuje, zato telefonu ni treba hraniti
ničesar in lokalna shema se ne spremeni. Časovni žig zadnje sinhronizacije je
bil zavrnjen: pade na razliki ur in na transakciji, ki se potrdi šele potem,
ko je telefon kazalec že premaknil čezenj.

Za vsak `id` telefon pobriše **najprej vrstico, nato datoteko**, in šele nato
pošlje `POST /materials/deleted-on-device`. Potrditev pred dejanskim brisanjem
bi pomenila zapis, ki ga strežnik šteje za pospravljenega, na telefonu pa
ostane. Zapis, ki ga naprava nima (sveža namestitev), se potrdi takoj —
potrditev pomeni „tega tu ni več", ne „pravkar sem ga izbrisal". Ponovljena
potrditev ničesar ne premakne; prenos je *at-least-once*.

V mobilnem vmesniku se ob tem ne zgodi nič: slika iz Zgodovine samo izgine.

**Dokončno brisanje ima dve stopnji.** „Počisti sliko" pobriše samo datoteko
in je dovoljeno kadarkoli po arhiviranju. „Izbriši dokončno" pobriše tudi
vrstico in je dovoljeno **šele, ko je `device_deleted_at` postavljen** —
sicer telefon za brisanje nikoli ne izve. Pravilo velja v vmesniku, v poti in
v repozitoriju: gumb, ki ga stran ne izriše, ni varovalka. Vprašanja ob tem
ostanejo.

Ure so v pasu `Europe/Ljubljana`, ker jih operater primerja s tem, kar kaže
telefon. Bazo pasov prinese sistem (v vsebniku `/usr/share/zoneinfo`, na
Windows paket `tzdata`, ki ga zahteva že `psycopg`), zato tu ni nove
odvisnosti. `ZoneInfo` se ustvari ob prvi uporabi in ne ob uvozu modula —
sicer bi manjkajoča baza pasov podrla tudi `GET /health` in `POST /materials`.

Čas iz baze je lahko brez podatka o pasu: Postgres ga v `TIMESTAMPTZ` vrne,
**SQLite pa ne**. Prikaz ga zato normalizira v UTC, preden ga pretvori.

## Zunanje odvisnosti

| Odvisnost | Namen | Kdaj dodana |
|---|---|---|
| Expo SDK 57 (`expo`, `expo-router`, `expo-status-bar`, `expo-splash-screen`) | ogrodje in datotečno usmerjanje | V1-R01 |
| `expo-camera` | zajem fotografije in dovoljenje za kamero | V1-R01 |
| `expo-sqlite` | lokalna baza na telefonu | V1-R01 |
| `expo-file-system` | `documentDirectory/photos/`, premik in brisanje datotek | V1-R01 |
| `expo-image-manipulator` | pomanjšanje na 1600 px in JPEG 0.8 | V1-R01 |
| `expo-crypto` | UUID, generiran na telefonu | V1-R01 |
| `react-native`, `react`, `react-dom` | osnova | V1-R01 |
| `react-native-safe-area-context` | odmiki varnega območja; koda ga uvaža neposredno (`useSafeAreaInsets`) | V1-R01 |
| `expo-constants`, `expo-linking`, `react-native-screens`, `react-native-gesture-handler`, `react-native-reanimated`, `react-native-worklets` | `peerDependencies` paketa `expo-router`; koda jih ne uvaža neposredno | V1-R01 |
| razvojno: `jest`, `jest-expo`, `@testing-library/react-native`, `react-test-renderer`, `eslint`, `eslint-config-expo`, `typescript`, `babel-preset-expo`, `@types/node`, `@types/jest`, `@types/react` | preverbe | V1-R01 |

V1-R02 telefonu ni dodala nobene odvisnosti — prenos teče prek
`expo-file-system`, nastavitve pa prek `expo-constants`, oba že iz V1-R01.
Tudi V2-R02 ni dodala nobene, ne telefonu ne strežniku: UUID poskusa pride iz
`expo-crypto`, ki je v projektu od V1-R01.

### `apps/server` (Python 3.12)

| Odvisnost | Namen | Kdaj dodana |
|---|---|---|
| `fastapi`, `uvicorn[standard]` | HTTP strežnik | V1-R02 |
| `python-multipart` | brez njega FastAPI multiparta ne prebere | V1-R02 |
| `sqlalchemy`, `psycopg[binary]` | dostop do baze; `binary` zato, ker na Windows ni prevajalnika | V1-R02 |
| `alembic` | migracije sheme | V1-R02 |
| `pydantic-settings` | nastavitve iz okolja | V1-R02 |
| `jinja2` | predloge operaterske strani | V1-R04 |
| `openai` | klic vision modela; izbran zaradi strukturiranega izhoda po shemi | V1-R03 |
| razvojno: `ruff`, `mypy`, `pytest`, `httpx` | preverbe; `httpx` rabi `TestClient` | V1-R02 |

## Kako se poganja in testira

### `apps/mobile`

```powershell
npm --prefix apps/mobile install
npm --prefix apps/mobile start          # razvoj (Expo Go / dev build)
npm --prefix apps/mobile run lint
npm --prefix apps/mobile run typecheck
npm --prefix apps/mobile test
```

Kamera, dovoljenja in pisanje datotek se v enotskih testih ne dajo preveriti —
ta del preveri lastnik ročno na napravi. Testi pokrivajo logiko okoli njih;
testi baze tečejo nad pravo SQLite bazo v pomnilniku prek `node:sqlite`, ki je
del Node.js in ne nova odvisnost.

Da se aplikacija res prevede (ne samo tipno preveri), pomaga
`npx expo export -p android`.

**Tipizirane poti** (`experiments.typedRoutes` v `app.json`) pridejo iz
`.expo/types/router.d.ts`, ki je git-ignoriran in ga ustvari Metro. Zastarela
lokalna datoteka podre `typecheck` ob vsakem novem zaslonu, čeprav je koda
pravilna — svež klon je nima in je čist. Znova jo ustvari
`npx expo customize tsconfig.json` (ali `npm start`); nobene sledene datoteke
ob tem ne spremeni. Odkrito v V2-R02.

Naslov strežnika in API ključ prideta v aplikacijo **ob gradnji**, iz
spremenljivk okolja `SERVER_BASE_URL` in `SERVER_API_KEY` (Expo naloži `.env`
sam, `app.config.ts` ju prepiše v `extra`). Brez njiju se worker ne zažene,
aplikacija pa deluje kot v V1-R01 in to tudi pove. Ključ s tem konča vgrajen v
APK — to je zavestno, ker gre za en družinski ključ na omrežju, ki je že
zaprto s Tailscale; cena je, da zamenjava ključa zahteva novo gradnjo.

Po isti poti pride tudi **oznaka gradnje** (V1-R06): `app.config.ts` prepiše
`EAS_BUILD_ID` v `extra.buildId`, domača stran pa jo izpiše kot
`1.0.0 · gradnja 317bdcd1`. Brez tega izpisa dveh APK na telefonu ni bilo
mogoče ločiti — verzija je bila pri obeh `1.0.0` in `versionCode` pri obeh 1;
`versionCode` odtlej šteje EAS sam (glej spodaj). Razvojna
gradnja spremenljivke nima in vrstica takrat pove `razvojna gradnja`; prazna
vrednost šteje enako kot odsotna.

#### Gradnja APK in nešifriran promet

Distribucija je EAS Build, profil `preview` v `apps/mobile/eas.json` (Android
APK, interna distribucija, okolje `preview`). Naslov in ključ tam nista v
`.env`, ampak med spremenljivkami okolja EAS za to okolje; `app.json` nosi
`owner` in `extra.eas.projectId`.

**Verzijo gradnje hrani EAS, ne repozitorij** (`appVersionSource: "remote"`,
`autoIncrement` v profilu `preview`). `versionCode` zato zraste sam ob vsaki
gradnji in dveh APK ne loči le izpis na domači strani, ampak tudi Android. V
`app.json` `android.versionCode` namenoma ni — številka, ki bi jo bilo treba
ročno povečevati, se pozabi natanko takrat, ko je potrebna. Cena je, da je
števec pri EAS in ga svež klon sam ne pozna.

Promet do strežnika je **nešifriran** (`http://` na Tailscale naslov). Android
ga v release gradnji privzeto blokira, zato ga izrecno dovoli lokalni config
plugin `apps/mobile/plugins/with-cleartext-traffic.js`, ki v glavno
`<application>` zapiše `android:usesCleartextTraffic="true"`. Dovoljenje velja
za celo aplikacijo; utemeljitev, zavrnjene možnosti in odprta pot k HTTPS so v
`docs/odlocitve/ADR-010`.

**To je razred napake, ki ga zeleni testi ne ujamejo.** Plugin teče ob gradnji,
enotski testi pa vidijo samo njegovo funkcijo in registracijo v `app.json`.
Dve preverbi, ki gresta dlje:

```powershell
npx expo config --type introspect      # razreši plugine in izpiše manifest
unzip -o app.apk AndroidManifest.xml   # kaj je v resnici v zgrajeni APK
```

Prva pokaže v nekaj sekundah in brez gradnje, ali je plugin registriran in ali
učinkuje. **Njen izpis vsebuje `extra.apiKey` in naslov strežnika v čisti
obliki** — ne lepi ga v prijave napak in ne shranjuj v dnevnik; kadar gre le za
manifest, ga poženi s praznima `SERVER_API_KEY` in `SERVER_BASE_URL`.

Druga pove, kaj je v zgrajeni APK. `AndroidManifest.xml` je tam **binarni
AXML**: ime atributa je v nizovnem bazenu in ga `grep -a` najde, vrednost
`true` pa je shranjena kot tipiziran boolean in kot besedilo ni vidna. Prisotno
ime atributa je zato dokaz, da je plugin učinkoval (prej ga v manifestu sploh
ni bilo), za odčitano vrednost pa je potreben `aapt2 dump xmltree` ali
`apktool d` — nobeden od njiju ni na tem stroju na `PATH`.

Zadnja beseda ostane preizkus na telefonu: slika mora priti do stanja
„Preneseno".

### `apps/server`

Postopek postavitve (enkrat na klon) — glej `docs/odlocitve/ADR-005`:

```powershell
python -m venv apps\server\.venv
apps\server\.venv\Scripts\python.exe -m pip install -e "apps\server[dev]"
```

Nato mapo `apps\server\.venv\Scripts` dodaj na **začetek** uporabniškega
`PATH`. `scripts/verify.ps1` orodja kliče kot gole ukaze iz korena
repozitorija in venv-a ne aktivira, zato se morajo razrešiti sama.

**Posledica, ki preseneti:** na tem računu `python` in `pip` odslej kažeta v
venv tega projekta.

```powershell
ruff check apps/server
mypy apps/server
pytest apps/server
```

`mypy.ini` je v korenu repozitorija in ne v `apps/server`, ker mypy nastavitve
bere iz trenutne mape, ne iz ciljne — `verify.ps1` pa ga kliče iz korena.
`ruff` in `pytest` te težave nimata in imata nastavitve v
`apps/server/pyproject.toml`.

Testi strežnika **ne potrebujejo Postgresa ne Dockerja**: tečejo nad SQLite v
pomnilniku skozi plast repozitorija (`app/db.py`). Cena te izbire je, da
pgvector in Postgres-specifično vedenje s testi nista pokrita.

Zagon:

```powershell
copy apps\server\okolje.primer apps\server\.env   # nato izpolni
docker compose -f apps\server\docker-compose.yml up -d --build
```

`.env` prebere **Docker Compose**, da razreši `${API_KEY}` in poda vrednosti
vsebniku; strežnik sam `.env` ne bere, ker bi bil `env_file` relativen na
trenutno delovno mapo. `BIND_ADDRESS` naj bo Tailscale naslov tega stroja
(`tailscale ip -4`) — privzetek `127.0.0.1` je namenoma neuporaben od zunaj.
`API_KEY` mora imeti vsaj 16 znakov, sicer se strežnik ne zažene.

`OPENAI_API_KEY` se obnaša drugače od `API_KEY`: brez njega strežnik **normalno
steče** in slike sprejema, ne teče pa obdelava. `OPENAI_MODEL` (privzeto
`gpt-4.1`), `OPENAI_TIMEOUT_SECONDS` (120) in `WORKER_INTERVAL_SECONDS` (30) so
neobvezni.

#### Odprto: strežnik po nenadzorovanem ponovnem zagonu

**Docker Desktop se zaganja ob prijavi uporabnika, ne ob zagonu sistema**
(vnos v `HKCU\...\CurrentVersion\Run`). Vsebnika imata
`restart: unless-stopped` in se po zagonu Dockerja vrneta sama — a le, če je
seja sploh vzpostavljena.

Praktična posledica: če se stroj ponoči znova zažene in se nihče ne prijavi,
strežnik ostane dol. **Podatki se ne izgubijo** — slike ostanejo na telefonu
s stanjem `pending` in domača stran kaže števec čakajočih. Cena ni izguba,
ampak da lahko mine teden, preden kdo opazi.

Stanje stroja ob tem zapisu: BitLocker ni vklopljen (ni TPM), račun je
lokalen, samodejni vpis ni nastavljen.

Pretehtane možnosti, **odločitev je odložena na kasnejšo fazo**:

| Možnost | Za | Proti |
|---|---|---|
| Samodejni vpis + takojšen zaklep seje (Sysinternals Autologon, geslo kot LSA skrivnost) | ohrani preverjeno postavitev in vezavo na Tailscale; malo dela | geslo mora biti shranjeno na stroju |
| Nadzorno opravilo, ki na ~15 min preveri `/health` in po potrebi požene `docker compose up -d` | pokrije tudi sesut Docker in zamrznjen WSL; ne zahteva gesla | sam po sebi ne reši odsotne seje |
| Docker Engine v WSL distribuciji namesto Docker Desktopa, zagnan kot opravilo ob zagonu | ne potrebuje prijave; odpravi tudi pripetost na staro 4.26.1 | **WSL2 objavlja vrata prek NAT na `localhost`**, zato `BIND_ADDRESS` preneha delovati; omrežno mejo bi nadomestil požarni zid ali `portproxy` — pravilo, ki ga je lahko narobe nastaviti in ki ga nihče ne testira (nasprotuje odločitvi 8 v planu V1-R02) |
| Ne narediti nič | nič dela; podatki so varni | zamik pri opazitvi izpada |

Če strežnik kdaj preraste ta stroj, je pravi odgovor ločena Linux naprava, ne
prepletanje WSL-a.

### Celotna preverba

```powershell
pwsh -File scripts/verify.ps1
```

Šest korakov: lint, typecheck in testi za `apps/mobile` in za `apps/server`.
Od V1-R02 se ne preskoči noben — koraki za `apps/server` so se preskakovali
samo, dokler ta mapa ni obstajala.
