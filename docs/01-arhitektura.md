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
| Povezljivost telefon ↔ strežnik | HTTPS na `school-buddy.duckdns.org`, Caddy pred `api` (od V3-R02) | Pošiljanje od koderkoli; certifikat Let's Encrypt; glej „Javni dostop" in `docs/odlocitve/ADR-026` |
| Vision / OCR | OpenAI `gpt-4.1` prek uradnega paketa `openai` (od V1-R03) | Klasični OCR (Tesseract) ne obvlada slovenskega rokopisa; izbira in njena začasnost sta v `docs/odlocitve/ADR-008` |
| Obdelava v ozadju | `asyncio` opravilo v procesu `api` | Pri 5–25 slikah na teden Celery in Redis ne rešita nobene težave tega projekta; „kar bi lahko bila mikrostoritev, naj bo funkcija" |
| Orkestracija strežnika | Docker Compose (`caddy` + `api` + `db`) | Brez Celery/Redis — obseg (5–25 slik/teden) tega ne potrebuje |

## Moduli

| Modul | Odgovornost | Datoteke |
|---|---|---|
| `apps/mobile` | Kamera, izbira predmeta, lokalna baza, zgodovina, upload worker, brisanje arhiviranih snovi, reševanje kvizov (od V3-R07 samo kvizi prijavljenega otroka) | `apps/mobile/` (od V1-R01; upload worker od V1-R02; brisanje od V1-R07; kvizi od V2-R02) |
| `apps/server` | Prevzem slik (`POST /materials`), preverba ključa, shramba, operaterska stran `/admin`, vision obdelava v ozadju, arhiv, sestavljalnik kvizov, poskusi reševanja, rezultat in tisk, statistika čez kvize, pregled slik po dnevih, povečan prikaz slike, naslovljenec kviza in lastnik zapisa | `apps/server/` (od V1-R02; `/admin` od V1-R04; obdelava od V1-R03; arhiv od V1-R07; kvizi od V2-R01; poskusi od V2-R02; rezultat od V2-R03; statistika od V2-R04; pregled po dnevih od V2-R07; povečan prikaz od V2-R08) |

Ločena mapi namenoma ne delita orodij za monorepo (npr. Turborepo) — gre za
dva jezika (TypeScript / Python) brez skupne kode, zato vsaka živi s svojim
običajnim orodjem (`npm`/`package.json` v `apps/mobile`,
`pip`/`pyproject.toml` v `apps/server`).

### Notranja delitev `apps/mobile`

| Mapa | Odgovornost |
|---|---|
| `app/` | zasloni; usmerjanje je datotečno (`expo-router`) |
| `src/constants/` | seznam desetih predmetov (`{ value, label }`); od V2-R02 še štiri ocene samoocene (`ocene.ts`) |
| `src/config/` | kar pride v aplikacijo ob gradnji: naslov strežnika (samo `https`, od V3-R02) in oznaka gradnje; ključa od V3-R04 ni več |
| `src/db/` | verzionirana shema (migracije) in poizvedbe nad tabelo `materials`; od V2-R02 še nad tabelami kvizov (`kvizi.ts`) |
| `src/sync/` | prenos na strežnik: en prenos, čakalna vrsta, priklop na življenjski cikel; od V1-R07 tudi brisanje snovi, ki so na strežniku arhivirane; od V2-R02 usklajevanje kvizov in poskusov (`kvizi.ts`, `use-kvizi.tsx`) in skupni klic s časovno omejitvijo (`http.ts`). **Edina mapa v aplikaciji z omrežnim klicem.** |
| `src/photos/` | stiskanje slike in zapis v `documentDirectory/photos/` |
| `src/materials/` | shranjevanje posnetka: najprej datoteka, nato vrstica |
| `src/capture/` | stanje zaslona s kamero (kamera ↔ predogled) |
| `src/ui/` | skupni gradniki in barve |
| `src/types.ts` | tip `Material` (ena vrstica tabele `materials`); od V2-R02 še kviz, postavka, poskus in ocena |
| `__tests__/` | enotski in komponentni testi |

Mape `plugins/` od V3-R02 ni: edini config plugin (dovoljenje za nešifriran
promet, `ADR-010`) je bil odstranjen.

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
| `app/security.py` | vmesni plasti ob vhodu: `ZetonMiddleware` (telefon, `Authorization: Bearer`, V3-R04) in `SejaMiddleware` (seja in CSRF pod `/admin`, V3-R03; `poti_s_svojim_csrf` od V3-R09) |
| `app/routers/materials.py` | `POST /materials` — prevzem slike s telefona |
| `app/routers/admin.py` | operaterska stran: predmeti, snov, arhiv, brisanje |
| `app/routers/kvizi.py` | sestavljalnik kvizov pod `/admin/quizzes` (V2-R01); rezultat rešenega kviza in stran za tisk (V2-R03) |
| `app/routers/resevanje.py` | poti telefona za kvize: `GET /quizzes/pending`, `POST /quiz-attempts` (V2-R02) |
| `app/routers/statistika.py` | statistika čez kvize pod `/admin/statistics` (V2-R04) |
| `app/routers/dnevi.py` | pregled slik po obdobju in predmetih pod `/admin/days` (V2-R07); vrstica z manjki (V3-R09) |
| `app/routers/urnik.py` | urnik otroka pod `/admin/schedule`: mreža, predlog s slike, potrditev (V3-R09) |
| `app/routers/clani.py` | člani družine pod `/admin/family`: seznam, dodajanje, ponastavitev gesla, deaktivacija in aktivacija (V3-R06) |
| `app/routers/sistem.py` | stran lastnika sistema pod `/admin/system`: družine, odpiranje nove, stanje družine in dejanja nad starši (V3-R05) |
| `app/routers/racun.py` | nastavitve prijavljenega starša pod `/admin/racun`: načini prijave, povezava in odstranitev Googla (V3-R08) |
| `app/google.py` | Google prijava: poti, naslovi, vezivo stanja, razsodbe in **edini modul, ki govori z Googlom** (V3-R08). Brez FastAPI in brez baze |
| `app/db.py` | motor, seje ter `MaterialsRepository`, `KviziRepository`, `StatistikaRepository` (V2-R04, samo bere), `ClaniRepository` (V3-R06) in `ScheduleRepository` (V3-R09) — vsak z obvezno družino (V3-R01) — ter `DruzineRepository` (od V3-R05 tudi pregled čez družine) in `PrijavaRepository` (V3-R03), edina brez družine; edina pot do baze |
| `app/models.py` | tabele `families` (V3-R01), `materials`, `questions`, `quizzes`, `quiz_items`, `question_attempts` ter `users`, `credentials`, `sessions` in `login_attempts` (V3-R03); `child_id` na snovi, kvizu in poskusu (V3-R07); `schedules` in `schedule_entries` (V3-R09); `credentials.label` (V3-R08) |
| `app/storage.py` | zapis, meja mape in brisanje slik na disku; mapa družine (V3-R01); podmapa `urniki/` (V3-R09) |
| `app/vision.py` | **edini modul, ki uvaža `openai`**: prompta, shemi odgovorov, klic. Dva klicalca — snov (V1-R03) in urnik (V3-R09) — nad skupnim `_izvedi_klic` |
| `app/obdelava.py` | kaj se zgodi z enim zapisom: prevzem, klic, zapis izida. Sinhron |
| `app/worker.py` | časovnik: obhodi v presledkih, zagon in ustavitev. Brez poslovne logike |
| `app/statistika.py` | pravila štetja statistike: razporeditev, izpeljava pravilnosti, razvrstitev, meseci (V2-R04). Brez FastAPI in brez seje |
| `app/prijava.py` | gesla (argon2id), žetoni sej, CSRF, omejevanje ugibanja, varen `next` — brez FastAPI (V3-R03); `Vrata` in `vloga_sodi`: katera vloga sme kam (V3-R04); `normaliziraj_identifikator` (V3-R06) |
| `app/ukazi.py` | `python -m app.ukazi nastavi-geslo <identifikator>`; geslo z `getpass`, nikoli iz argumenta (V3-R03); prekliče seje računa (V3-R06) |
| `app/clani.py` | pravila o članih družine: veljaven vnos in kdo sme koga — brez FastAPI in brez baze (V3-R06) |
| `app/sistem.py` | pravila lastnika sistema: ime družine, česa niti on ne sme, besedilo o zunanjem vision API-ju — brez FastAPI in brez baze (V3-R05) |
| `app/routers/vstop.py` | prijava in odjava: `GET/POST /admin/login`, `POST /admin/logout` (V3-R03); `POST /auth/login` in `POST /auth/logout` za telefon (V3-R04); `POST /auth/google/login` in `GET /auth/google/callback` (V3-R08) |
| `app/settings.py` | nastavitve iz okolja |
| `app/dependencies.py` | odvisnosti poti iz `app.state`; družina iz seje — ene same, za obe strani (`daj_druzino`, V3-R04; začasne `daj_druzino_telefona` ni več) |
| `app/urnik.py` | pravila urnika in manjkov: kateri predmeti so kateri dan, česa tisti dan ni na sliki (V3-R09). Brez FastAPI in brez baze |
| `app/otroci.py` | izbira otroka v pogledih, ki so ločeni po otroku: privzetek, 404 za tujega, kdaj se izbirnik izriše (V3-R07). Brez FastAPI in brez seje |
| `app/subjects.py` | predmeti, slovenske oznake stanj in oznake ocen (`OZNAKE_OCEN`, tu od V2-R04) |
| `app/casi.py` | domači časovni pas, ure za prikaz, meji koledarskega dne (V2-R01); `utc` za čase v odgovorih telefonu (V2-R02); `trajanje` za čas odgovora na rezultatu (V2-R03); šolsko leto in meseci (V2-R04); današnji dan, meje poljubnega obdobja in ura brez datuma (V2-R07) |
| `app/strani.py` | izrisovalnik predlog in strani 404/409 (V2-R01), 400 (V2-R07) ter 403 (V3-R06); obdelovalec konteksta z glavo, CSRF žetonom (V3-R03) in `google_na_voljo` (V3-R08) |
| `app/besedilo.py` | slovenske oblike števil (dvojina) |
| `Caddyfile` | Caddy pred `api`: domena, TLS-ALPN, ikona zavihka (V3-R02); `basic_auth` je padel z V3-R03 |
| `varnostna-kopija/` | `kopija.ps1` in `obnova.ps1` (V3-R02) |

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
trenutna verzija je **4**. `CREATE TABLE IF NOT EXISTS` obstoječi tabeli
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
migraciji 1.

#### Lastnik zapisa (migracija 3, V3-R04)

`materials` in `attempts` dobita `user_id TEXT` (indeksiran, `NULL`-abilen).
Test teče nad `SHEMA_VERZIJE_2` — dobesedno kopijo baze po migraciji 2,
kakršna je na Mašinem telefonu pred V3-R04.

**`NULL` pomeni „nastalo, ko ni bil prijavljen nihče“**, ne „brez
lastnika za vedno“: tak zapis posvoji **vsaka razrešena seja**
(`posvojiBrezLastnika`) — prijava in obnovitev žetona z diska enako. Okno, v
katerem tak zapis nastane, se ne odpre le ob zagonu, ampak tudi, kadar branje
ali brisanje iz varne shrambe spodleti; vezanje posvojitve zgolj na prijavo bi
tak zapis pustilo nedosegljiv za vedno (`ADR-036`, popravki po drugem
pregledu). Brez tega bi bila nadgradnja Mašinega telefona
vrsta, ki ne odide nikoli, saj so vse obstoječe vrstice brez lastnika.

Pogoj lastništva je povsod `user_id IS ?` in ne `=`: isti stavek tako
velja za prijavljeno uporabnico in za neprijavljeno aplikacijo. Filtrirajo
vrsta (`listPending`), števci (`countByStatus`), Zgodovina
(`listBySubject`), vrnitev v vrsto (`retryFailed`) in nepreneseni poskusi
(`neprenesenePoskuse`).

**Od V3-R07 kviz nosi lastnika in vse tri poizvedbe filtrirajo.** Do takrat
`cakajociKvizi`, `najdiKviz` in `postavkeKviza` niso filtrirale nič, zato je na
skupnem telefonu otrok B videl kvize otroka A — tiste, ki so ostali, ker na
njih visi neprenesen tuj poskus (`ADR-036` C) — in v njih postavke, ki so bile
zanj videti odgovorjene. Podrobnosti so v razdelku o migraciji 5 spodaj.

`pobrisiKvizeRazen` ne pobriše kviza, na katerem visi **tuj neprenesen
poskus**: seznam s strežnika je seznam prijavljenega otroka, zato bi bil
vsak kviz prejšnjega videti kot preklican (`ADR-036` C).

#### Sled o nedokončani odjavi (migracija 4, V3-R04)

Tabela `naprava` (`id = 1`, `odjava_ob`) — ena sama vrstica, ki jo jamči
`CHECK (id = 1)`. Postavi jo odjava **pred** brisanjem iz varne shrambe in
počisti takoj, ko brisanje uspe; obstaja torej samo takrat, kadar je odjava
ostala nedokončana.

Žeton, ki ga ob zagonu sreča postavljena oznaka, je **ostanek in ne seja**:
zavrže se, brisanje se poskusi znova, aplikacija ostane neprijavljena. Brez
tega bi se po spodleteli odjavi prejšnja seja obnovila in posvojila posnetke,
ki jih je med tem naredil kdo drug (`ADR-037`).

Oznaka je v tej bazi in ne v varni shrambi prav zato, ker obstaja za primer,
ko odpove varna shramba. Prijava jo počisti — nova prijava prekliče vsako
nedokončano odjavo pred njo.

#### Lastnik kviza (migracija 5, V3-R07)

`quizzes` dobi `user_id TEXT` (indeksiran, `NULL`-abilen). Test teče nad
`SHEMA_VERZIJE_4` — dobesedno kopijo baze po migraciji 4, kakršna je na
Mašinem telefonu pred V3-R07.

`NULL` pomeni isto kot pri `materials`: kviz izpred te migracije lastnika
nima. Posvoji ga **`posvojiBrezLastnika`** ob vsaki razrešeni seji — lokalno in
brez omrežja, sicer otrok brez povezave kvizov ne bi videl — in tudi
`shraniKviz` ob obhodu, a samo iz `NULL` (vsebina ostane zamrznjena,
`ADR-016` E).

Filtrirajo tri poizvedbe, vse po pravilu `user_id IS ?`, ki velja tudi za
neprijavljeno aplikacijo:

- `cakajociKvizi` — seznam in števec na domači strani;
- `najdiKviz` — odprtje kviza; tuj kviz je „kviza ni";
- `postavkeKviza` — **dva** pogoja: stik na `quizzes` (postavke *mojega*
  kviza) in filtriran stik na `attempts`. Drugi je nujen: tuj poskus ne sme
  postavke narediti odgovorjene, sicer bi kviz na seznamu visel za vedno.

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

#### Družina kot lastnik podatkov (V3-R01)

Tabela `families`: `id` (`VARCHAR(36)`, UUID s strežnika, hkrati ime mape
slik), `name` (`VARCHAR(200) NOT NULL`, **ni enoličen**), `created_at` in — od
V3-R05 — `is_active` (`BOOLEAN NOT NULL`, privzeto `true`). Nič drugega; ni
naslova in ni nastavitev.

`family_id NOT NULL` imajo `materials`, `questions`, `quizzes` in
`question_attempts`. **Izpeljave:** `quiz_items` stolpca nima — družina
postavke je družina njenega kviza (`quiz_id` je `NOT NULL`). `questions` ga ima
kot stolpec in ne izpeljavo iz materiala, ker vprašanje material preživi in bi
brez njega ostalo brez družine (`ADR-029` C). Primarni ključi ostanejo globalni.

**Izolacija je lastnost kode** (`ADR-025`):

- `MaterialsRepository`, `KviziRepository` in `StatistikaRepository` dobijo
  `family_id` v konstruktorju, brez privzetka; prazen niz je `ValueError`. Seja
  je zasebna, `Session.get` se nad podatki ne uporablja, vsaka poizvedba in
  vsak `UPDATE` ima pogoj družine. Nove vrstice dobijo družino od repozitorija.
- `DruzineRepository` bere `families` in **šteje** člane v `users` (obdelava,
  od V3-R05 pregled lastnika sistema). Podatkov nobene družine ne bere in
  imen članov ne vrača; meja je zapisana v `ADR-044` E in jo varuje test.
- **Družino pove seja, na obeh straneh** (V3-R04): `daj_druzino` vrne
  `family_id` iz seje, ki jo je razrešila vmesna plast — brez poizvedbe.
  Začasna izbira „edina družina v bazi" (`ADR-029` A) je odpadla skupaj z
  API ključem (`ADR-036` F); druga družina v bazi zato ne ustavi več ničesar,
  kar je bil pogoj za `V3-R05`.
- `tests/test_tesnjenje.py` pošlje identifikatorje ene družine v imenu druge
  na vsako pot in v vsako javno metodo repozitorijev. Varovali zahtevata, da
  ima vsaka pot in metoda svoj primer; posnetek družine zavrne tabelo brez
  zapisanega pravila družine.

**Znana omejitev:** `POST /quiz-attempts` s poskusom, katerega `id` (UUID s
telefona) že obstaja v **drugi** družini, vrne `500` (dvakrat `IntegrityError`
na primarnem ključu), ne `4xx`. Brez ponarejanja se to ne zgodi; obvoz s
poizvedbo brez družine ni dovoljen, drugačen izid pa bi bil nova odločitev o
pogodbi s telefonom.

Tabela `materials` (nastane v V1-R02, razširi jo V1-R03):

| Stolpec | Tip | Opomba |
|---|---|---|
| `id` | `VARCHAR(36) PRIMARY KEY` | UUID s telefona; nosilec idempotentnosti |
| `family_id` | `VARCHAR(36) NOT NULL` | tuji ključ na `families.id`, brez `ondelete`, indeksiran (V3-R01) |
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
| `family_id` | `VARCHAR(36) NOT NULL` | tuji ključ na `families.id`, brez `ondelete`, indeksiran (V3-R01) |
| `material_id` | `VARCHAR(36)` | tuji ključ na `materials.id`, `ON DELETE SET NULL`, indeksiran; `NULL`, ko je material dokončno izbrisan (V1-R07) |
| `subject` | `VARCHAR(16)` | predmet materiala, prepisan ob nastanku (V1-R07); popravi ga premik snovi (V3-R10) |
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

**`questions.subject` je kopija ob nastanku, ki pa ni zamrznjena:** premik
snovi v drug predmet jo popravi pri vseh vprašanjih te snovi, veljavnih in
upokojenih (V3-R10, `ADR-040` B1). Statistika predmeta se s tem za nazaj
spremeni — to je namen premika. `material_taken_at` se ne spreminja nikoli.

`id` je `VARCHAR` in ne `UUID`, čas pa `DateTime(timezone=True)`, ker mora ista
shema stati nad Postgresom (produkcija) in nad SQLite (testi).

Tabela `quizzes` (V2-R01):

| Stolpec | Tip | Opomba |
|---|---|---|
| `id` | `VARCHAR(36) PRIMARY KEY` | UUID, generiran **na strežniku** |
| `family_id` | `VARCHAR(36) NOT NULL` | tuji ključ na `families.id`, brez `ondelete`, indeksiran (V3-R01) |
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

**Postavka zamrzne dvoje.** `question_id` nosi identiteto, na kateri stoji
statistika čez kvize (`V2-R04`); `question_text` in `answer_text` nosita berljivost, ko
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
| `family_id` | `VARCHAR(36) NOT NULL` | tuji ključ na `families.id`, brez `ondelete`, indeksiran (V3-R01) |
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

Migracija `0007_druzine` ustvari `families` z družino **Cvek** (stalen `id`
`5b0f6c2e-8d3a-4c7e-9a1b-2f4d6e8c0a13`), `family_id` doda kot `NULL`-abilen,
zapolni s Cvek in nato naredi obvezen. Nato prepiše `image_path` slik, ki
ležijo neposredno v korenu `IMAGES_DIR`, in datoteke premakne v
`<IMAGES_DIR>/<Cvek>/`. Premik ni del transakcije baze, zato je idempotenten
(vir je in cilja ni → premakni; vira ni → pusti) in `id` družine je stalen —
ponovni zagon po prekinitvi pride do istega stanja. Datotek brez vrstice in
`.tmp/` se ne dotakne. **`IMAGES_DIR` je obvezen, kadar baza ni prazna**;
preverba je pred prvim DDL. `downgrade` slike in poti vrne in stolpce spusti;
pri več kot eni družini se ne izvede. Če `downgrade` pade po premiku slik, se
pozdravi s ponovnim `downgrade`, ne z `upgrade`.

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

Slike živijo v `/data/images/<family_id>/<id>.jpg` (V3-R01). **Meja mape je
mapa družine**, ne koren: slika tuje družine ali v korenu je za družino „ni na
disku" (`storage.mapa_druzine`, ki sprejme samo kanoničen UUID). Zapis gre
najprej v `<mapa družine>/.tmp/` pod enoličnim imenom in se na končno mesto premakne
atomarno; vrstica v bazi nastane šele za datoteko. Prekinjen prenos zato ne
pusti polovične slike na mestu, kjer jo bo V1-R03 iskal kot celo.

#### Otrok kot lastnik zapisa (V3-R07)

Družina je meja **lastništva** (`ADR-025`), otrok je meja **pomena**: v družini
z več otroki „kviz" in „statistika" brez njega ne povesta nič.

`child_id VARCHAR(36) NOT NULL` (tuji ključ na `users.id`, brez `ondelete`,
indeksiran) imajo `materials`, `quizzes` in `question_attempts`.

- **`questions` ga nima** — vprašanja ostanejo last družine (`ADR-039` G);
  **`quiz_items` ga izpelje iz kviza**, kot družino (`ADR-029` C).
- Na `quizzes` je to **naslovljenec**, na `materials` in `question_attempts`
  **tisti, ki je posnel oziroma odgovoril**. Ni nujno isti: poskus za kviz
  drugega otroka se sprejme in **ne zapiše** (`ADR-039` D).
- **Otroka pove seja, nikoli telo zahteve** (`dependencies.daj_otroka`).
  Pogodba s telefonom se navzven ne spremeni: novega polja ni.
- **Otrok je argument poizvedbe in ne konstruktorja repozitorija**, za razliko
  od družine: družina je meja izolacije, otrok izbira pogleda znotraj nje.
- **Ime otroka se v vmesniku izriše samo pri več kot enem otroku**, in vedno
  kot vrednost polja (`Maša · MAT · …`), nikoli za predlogom — slovenščina bi
  zahtevala sklanjanje (`ADR-039` F3). Pravilo uveljavljajo **vrata**, ne
  klicna mesta: `_imena`, `_ime_otroka` in `Naslovljenec.ime_za_prikaz` pri
  enem otroku vrnejo `None` oziroma prazno preslikavo. `TestImenaPriEnemOtroku`
  pomete čez vse strani `/admin` in nova stran z imenom pade tam.

Migracija `0009_otrok_na_zapisu` doda stolpce kot `NULL`-abilne, jih zapolni z
**edinim otrokom vsake družine** (šteje tudi deaktiviranega) in nato naredi
obvezne. Družina z nič ali več kot enim otrokom migracijo **ustavi z razlago**
pred prvim DDL in ne spremeni ničesar. `downgrade` stolpce spusti in dokončno
izgubi pripis otroka, vrstic pa ne — isti vzorec kot `0004`.

#### Identiteta: uporabniki, poverilnice in seje (V3-R03)

Model je iz `ADR-027`: **poverilnica ni uporabnik**. `V3-R08` je to preveril in
potrdil — Google je nova vrstica (`kind='google'`) in en `NULL`-abilen stolpec,
ne nova shema; `users` in `sessions` se nista dotaknila.

| Tabela | Stolpci | Opomba |
|---|---|---|
| `users` | `id`, `family_id NOT NULL` (FK, indeks), `role` (`parent`\|`child`), `display_name`, `is_system_owner`, `is_active`, `created_at` | oseba brez gesla; `is_active` pišeta in bereta poti `V3-R06` (glej „Člani družine"), `is_system_owner` odpira `/admin/system` (`V3-R05`) |
| `credentials` | `id`, `user_id NOT NULL` (FK, indeks), `kind` (`password`\|`google`), `identifier` **UNIQUE**, `secret_hash`, `label`, `created_at`, `updated_at` | `identifier` je e-naslov starša, uporabniško ime otroka ali Googlov `sub` (V3-R08), enoličen čez celo namestitev; `secret_hash IS NULL` pomeni „geslo ni nastavljeno" — pri `google` pomeni, da ta vrsta zgostitve nima; `label` je e-naslov Google računa **samo za izris** (V3-R08) |
| `sessions` | `id`, `user_id NOT NULL` (FK, indeks), `token_hash` **UNIQUE**, `csrf_token`, `created_at`, `expires_at`, `last_used_at`, `device_label` | žetona v bazi ni, samo SHA-256 |
| `login_attempts` | `id`, `identifier` (indeks), `ip_address`, `created_at` (indeks) | **edina tabela brez družine**: poskus se zabeleži tudi za identifikator, ki ne obstaja |

Migracija `0008_uporabniki` ustvari starša (lastnika sistema, `is_system_owner`)
in otroka v družini Cvek, **oba brez gesla**. Geslo vpiše lastnik z ukazom;
privzeto geslo v migraciji bi bilo javno geslo (`ADR-035` G).

`PrijavaRepository` je poleg `DruzineRepository` edini repozitorij brez
družine, in to neizogibno: prijava pozna samo identifikator in družino šele
izve. Nobene tabele s podatki družine ne bere.

## Prenos telefon → strežnik

`POST /materials` sprejme multipart z `id`, `subject`, `taken_at` in `file`.
Prvi prenos vrne **201**, ponoven prenos istega `id` **200** in polje
`created: false` — telefon oboje šteje za uspeh. Obstoječi zapis se ne prepiše
in slika se ne povozi.

Od V1-R07 obstaja tretji izid: **410** za zapis, ki je medtem šel v arhiv.
Telefon ga zbriše pri sebi in ne šteje za neuspeh. Brez tega bi posnetek, ki
je na telefonu obtičal v `pending`, tam ostal za vedno — z delovnega seznama
je lahko že padel, ker je bilo brisanje na napravi že potrjeno.

Od V3-R01 obstaja četrti izid: **409** za `id`, ki na strežniku obstaja v
**drugi** družini (`ADR-029` D). Vstavljanje pade na primarnem ključu, v lastni
družini zapisa ni; pravkar zapisana datoteka se pobriše. Pravilno delujoč
telefon tega izida ne vidi.

Od V3-R04 obstaja peti izid: **401** za zahtevo brez veljavnega žetona. Telefon
ga **ne** šteje za sodbo o vsebini: zapis ostane `pending` in prenos počaka na
prijavo (`ADR-036` H). To je izjema od pravila `ADR-004`, ker se to stanje more
spremeniti samo od sebe.

**Žeton** preverja **ASGI vmesna plast** (`ZetonMiddleware`, od V3-R04), ne
odvisnost endpointa: FastAPI telo zahteve prebere pred razreševanjem
odvisnosti, zato bi strežnik večmegabajtno sliko najprej prebral in šele nato
ugotovil, da prijava ne velja. Izvzeti so `GET /health`, `POST /auth/login` in
celotna predpona `/admin`; odjava telefona izvzeta **ni**.

Do V3-R04 je bil tu en sam vgrajen `API_KEY` za vse družine. Odpadel je ostro,
ne postopno (`ADR-027` C2, `ADR-036`): strežnik ne sprejema obojega.

Izvzetje predpone je **varnostna meja, ne priročnost**: ujame se na `/admin`
in na `/admin/...`, nikoli na pot, ki se le začne enako (`/administration`).
Da izvzetje ne odpre ničesar drugega, dokazuje razred
`TestPrijavaOstajaZahtevanaDrugod` v `tests/test_admin.py` — brez njega bi bila
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
Vsakih 30 s (`WORKER_INTERVAL_SECONDS`) pobere zapise s `status='new'`
**po družinah** (od V3-R01, `ADR-029` B), znotraj družine najstarejši posnetek
prvi, in jih obdela **zaporedno**. Obnova obtičalih ob zagonu gre prav tako po
družinah. Samo delo teče v niti
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
ni, ne plačamo. Meja je mapa družine, ista kot pri streženju slike na admin
strani.

Klic gre skozi `app/vision.py` in nikjer drugje (ADR-008). **Od V3-R09 ga
sprožita dve mesti**: ta zanka za snov in pot `/admin/schedule/proposal` za
urnik, ki teče sinhrono ob zahtevi (`ADR-041` B). Modul ostaja edini uvoznik
`openai`; „klic modela teče v ozadju“ pa ne drži več za oboje. Slika potuje kot
base64 v `data:` URL, ker so slike dosegljive samo pod `/admin`, za geslom, in
OpenAI do njih nima dostopa. Odgovor je strukturiran po shemi (`json_schema`,
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
„spremlja delovanje"). Brez gradnje frontenda in brez `npm` v `apps/server`.
Nastala v V1-R04; V1-R03 jo je razširila s prikazom obdelave.

**Skripta je izjema, ne privzetek** (`ADR-024`): edina je na strani s
podrobnostmi snovi (V2-R08), vgrajena v `snov.html`. Vse ostale strani so brez
nje in to preverja `TestBrezJavaScripta`, ki izvzame samo `snov.html`.

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
| `/admin/materials/{id}/subject` | POST | premakne snov in **vsa** njena vprašanja v drug predmet, preusmeri (303) (V3-R10) |
| `/admin/quizzes/new` | GET | izbirnik slik za enega od treh vstopov (V2-R01) |
| `/admin/quizzes/new` | POST | isti izbirnik ob vrnitvi iz predogleda, z ohranjenim izborom (V2-R01) |
| `/admin/quizzes/preview` | POST | predogled izbranih vprašanj; **ničesar ne shrani** (V2-R01) |
| `/admin/quizzes` | POST | objavi kviz in vse postavke v eni transakciji, preusmeri (303) (V2-R01) |
| `/admin/quizzes/{id}` | GET | kviz s postavkami (V2-R01); rešen kviz kot rezultat v skupinah po oceni (V2-R03) |
| `/admin/quizzes/{id}/print` | GET | stran za tisk rešenega kviza: vprašanja brez odgovorov, prelom, ključ; izbor ocen z obrazcem `GET` (V2-R03) |
| `/admin/quizzes/{id}/cancel` | POST | prekliče kviz, preusmeri (303) (V2-R01) |
| `/admin/statistics` | GET | statistika čez kvize po predmetih; okno `?leto=2026` ali `?leto=vse` (V2-R04); otrok `?otrok=<id>` (V3-R07) |
| `/admin/statistics/subjects/{koda}` | GET | statistika predmeta: po mesecih, snovi, vprašanja od najtežjega (V2-R04); `?otrok=` (V3-R07) |
| `/admin/days` | GET | slike **enega otroka** po dnevu in predmetu; `?dan=YYYY-MM-DD`, `?obdobje=dan\|teden` (V2-R07), `?otrok=<id>` (V3-R07) |
| `/admin/schedule` | GET | mreža urnika izbranega otroka; `?otrok=<id>` (V3-R09) |
| `/admin/schedule/proposal` | POST | naloži sliko urnika, pokliče model, izriše **predlagano** mrežo; nič ne zapiše v bazo (V3-R09) |
| `/admin/schedule` | POST | potrdi mrežo; prejšnji urnik upokoji (V3-R09) |
| `/admin/family` | GET | člani družine z vlogo in stanjem, obrazca za dodajanje (V3-R06) |
| `/admin/family/children` | POST | doda otroka: prikazno ime, uporabniško ime, začetno geslo (V3-R06) |
| `/admin/family/parents` | POST | doda starša: prikazno ime, e-naslov, začetno geslo (V3-R06) |
| `/admin/family/members/{id}/password` | GET | vmesna stran s poljema za novo geslo (V3-R06) |
| `/admin/family/members/{id}/password` | POST | zapiše zgostitev in prekliče vse seje člana (V3-R06) |
| `/admin/family/members/{id}/deactivate` | GET | vmesna stran (V3-R06) |
| `/admin/family/members/{id}/deactivate` | POST | deaktivira in prekliče vse seje člana (V3-R06) |
| `/admin/family/members/{id}/activate` | GET | vmesna stran (V3-R06) |
| `/admin/family/members/{id}/activate` | POST | vrne račun v uporabo; sej ne obnovi (V3-R06) |
| `/admin/system` | GET | vse družine s števili članov in stanjem, obrazec za novo družino, besedilo o vision API-ju (V3-R05) |
| `/admin/system/families` | GET | 303 na seznam; obstaja zato, da pot ni videti kot 405 (V3-R05) |
| `/admin/system/families` | POST | ustvari družino in v njej prvega starša v eni transakciji (V3-R05) |
| `/admin/system/families/{id}` | GET | ena družina: starši poimensko, otroci samo kot število (V3-R05) |
| `/admin/system/families/{id}/deactivate` | GET, POST | vmesna stran in ugasnitev družine; seje vseh članov padejo (V3-R05) |
| `/admin/system/families/{id}/activate` | GET, POST | vmesna stran in vrnitev družine v uporabo (V3-R05) |
| `/admin/system/families/{id}/parents/{user_id}/password` | GET, POST | ponastavitev gesla staršu (V3-R05) |
| `/admin/system/families/{id}/parents/{user_id}/deactivate` | GET, POST | vmesna stran in deaktivacija starša (V3-R05) |
| `/admin/system/families/{id}/parents/{user_id}/activate` | GET, POST | vmesna stran in aktivacija starša (V3-R05) |
| `/admin/racun` | GET | načini prijave prijavljenega starša; `user_id` iz seje, nikoli iz naslova (V3-R08) |
| `/admin/racun/google` | POST | začne povezovanje: postavi piškotek stanja in pelje na Googlov zaslon (V3-R08) |
| `/admin/racun/google/odstrani` | POST | odstrani Google povezavo; gesla in sej se ne dotakne (V3-R08) |

Googlovi poti, ki ju sproži nekdo **brez** seje, sta zunaj `/admin` in zato
nista v tej tabeli: `POST /auth/google/login` in `GET /auth/google/callback`
(glej „Google prijava za starša").

Poti so angleške kot obstoječi API, vidno besedilo slovensko. **Vsaka od njih
zahteva sejo** (V3-R03, glej „Prijava, seje in CSRF"); vsak `POST` nosi CSRF
žeton. Poti pod `/admin/system` zahtevajo še lastnika sistema in so za vse
ostale `404` (V3-R05, glej „Lastnik sistema odpira družine"). Strani kažejo podatke družine iz seje, glava pa pove, čigava družina je
to in kdo je prijavljen.

Napake pod `/admin` (404, 405 in 500 izbire družine) izriše prestreznik `StarletteHTTPException`,
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

## Prijava, seje in CSRF (V3-R03)

Admin stran je na javnem internetu, zato jo varuje prijava v aplikaciji sami.
Odločitve so v `ADR-027` (model) in `ADR-035` (izvedba).

| Pot | Metoda | Kaj |
|---|---|---|
| `/admin/login` | GET | prijavni obrazec; postavi piškotek `csrf_prijava` |
| `/admin/login` | POST | preveri poverilnico, ustvari sejo, preusmeri na `next` |
| `/admin/logout` | POST | izbriše sejo te naprave (zahteva sejo in CSRF žeton) |

- **`SejaMiddleware` je plast, ne odvisnost.** Zahteva sejo za vsako pot pod
  `/admin` razen `/admin/login`; brez nje odgovori s `303` na prijavo z
  `?next=<zahtevana pot>`. Pot, ki je nihče ni dodal na noben seznam, je zato
  varovana po privzetku. `next` se sprejme samo kot relativna pot pod `/admin`,
  zapiše se z `urlencode` (sicer se cilj z dvema parametroma odreže pri `&`) in
  ga dobi **samo varna metoda** — `POST` brez seje pelje na `/admin`, ker bi
  vrnitev nanj z `GET` dala 404.
- **Ena pot žeton preveri sama** (`ADR-043`): `POST /admin/schedule/proposal`
  nosi datoteko v `multipart/form-data`, ki ga `_csrf_iz_telesa` ne prizna, in
  telo, večje od `NAJVECJE_TELO_OBRAZCA`. Plast zato zanjo telesa ne bere;
  **sejo zahteva enako kot povsod**. Nabor `poti_s_svojim_csrf` je enočlanski
  in to varuje test — druga taka pot naj vanj ne zaide tiho.
- **Žeton seje** je `secrets.token_urlsafe(32)`; v bazi je samo njegova
  SHA-256. Piškotek `seja` je `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`,
  z veljavnostjo 30 dni. **Rok je drseči** in se osveži največ enkrat na uro.
- **Primerjava žetonov gre skozi `prijava.zetona_se_ujemata` in primerja
  bajte** (popravljeno v `V3-R08`). `compare_digest` nad `str` zahteva čisti
  ASCII in sicer vrže `TypeError`; žeton pride iz obrazca, torej od zunaj, zato
  je bila taka izjema `500` z golim angleškim besedilom na vsakem `POST` pod
  `/admin`. Pogodba je nespremenjena — tak žeton ni bil veljaven nikoli, le
  namesto `403` je dal `500`. Pokritost varuje test, generiran iz `openapi()`.
- **CSRF žeton živi v vrstici seje** in pride v vsako predlogo prek
  `context_processors` izrisovalnika. `SejaMiddleware` ga pri `POST` prebere iz
  telesa (samo `application/x-www-form-urlencoded`, največ 1 MiB), primerja s
  `secrets.compare_digest` in ob neujemanju odgovori s `403` kot stranjo. Telo
  vrne nazaj v tok, da ga endpoint prebere kot običajno. Žeton zahteva **vsaka
  metoda razen `GET` in `HEAD`**, ne samo `POST`: `V3-R06` bo dodajal akcije.
  Prijavni obrazec seje še nima, zato nosi **dvojno oddan piškotek**
  `csrf_prijava`.
- **Omejevanje ugibanja gre po identifikatorju, ne po naslovu** (`ADR-034` A):
  po 5 neuspehih v 15 minutah vsak nadaljnji poskus čaka 2 sekundi, preden se
  geslo sploh preveri; zgoščevanje samo teče v niti, da ~60 ms argon2 ne
  ustavi zanke dogodkov. To je **upočasnitev, ne zaklep** — zaklep bi pomenil,
  da lahko kdorkoli z znanim e-naslovom starša tega izklopi iz njegovega
  admina. Uspešna prijava števce pobriše.
- **Sporočila ne izdajo, ali račun obstaja.** Neznan identifikator, napačno
  geslo, nenastavljeno geslo in deaktiviran račun dajo isto besedilo; ob
  neznanem identifikatorju se zgostitev preveri proti lažni vrednosti, da je
  tudi odzivni čas enak. Edina izjema je otrokov račun: ta dobi razlago, da se
  prijavi v mobilni aplikaciji (`ADR-035` F).
- **Potekle seje in stari poskusi se čistijo ob vsakem poskusu prijave** (ne
  le ob uspešnem — računa brez gesla ni mogoče uspešno prijaviti) in ob naletu
  na potekel piškotek. Ne v zanki `Obdelovalec`: ta brez `OPENAI_API_KEY` sploh
  ne teče (`ADR-009`).
- **Geslo nastavi lastnik z ukazom** v vsebniku:
  `docker compose exec api python -m app.ukazi nastavi-geslo <identifikator>`.
  Geslo pride z `getpass`, nikoli iz argumenta ali okolja. **Od V3-R06 ukaz
  prekliče vse seje tega računa**, enako kot stran `/admin/family` — dve poti
  do istega dejanja z različnim pomenom bi bili past (`ADR-038` C). Najkrajše geslo je
  12 znakov za starša in **8 za otroka** — otrokovih 4 iz `ADR-035` G je
  razveljavil `ADR-036` E, ko je mobilna prijava postala dosegljiva z javnega
  interneta.
- **Seja pade ob treh rečeh, ne le ob poteku:** potekel rok, deaktiviran račun
  (`V3-R06`) in ugasnjena družina (`V3-R05`). Prvi dve sta v `seja_za_zeton` od
  svojih zahtev, tretja od `V3-R05`; vse tri so preverjene **ob vsaki uporabi
  seje** in ne le ob prijavi, ker seje ustvarja tudi telefon.
- **Telefon se s tem do V3-R04 ni srečal.** Odtlej uporablja isto tabelo
  `sessions`, le da žeton nosi v glavi `Authorization: Bearer`; glej razdelek
  spodaj.

## Prijava na telefonu (V3-R04)

Isti model identitete kot v brskalniku (`ADR-027`), drug prenosnik.
Izvedbene odločitve so v `ADR-036`.

| Pot | Metoda | Kaj |
|---|---|---|
| `/auth/login` | POST | JSON `{identifier, password}` → žeton, `user_id`, ime |
| `/auth/logout` | POST | izbriše sejo te naprave (zahteva žeton) |

- **`ZetonMiddleware` je plast, ne odvisnost**, iz istega razloga kot
  `SejaMiddleware`: telo zahteve se bere pred odvisnostmi, zato bi bila
  večmegabajtna slika prebrana, preden bi se izkazalo, da prijave ni.
  Sejo razreši enkrat in jo poda v `scope["state"]`, od koder družino
  prebere `daj_druzino` — ista odvisnost kot za admin.
- **Vsaka vloga ima svoja vrata** (`prijava.Vrata`), in vrata se preverijo
  **ob vsaki uporabi seje**, ne le ob prijavi. Do V3-R04 otrokove seje ni
  bilo mogoče ustvariti, zato je preverba ob prijavi zadoščala; odkar
  telefon seje ustvarja, bi isti žeton, prilepljen v piškotek `seja`,
  brez te vrstice odprl celoten `/admin`.
- **CSRF tu ni** in ga ni treba: brez piškotka ni zahteve, ki bi jo
  brskalnik poslal sam od sebe.
- **Omejevanje ugibanja je skupno** z brskalnikom — ista tabela
  `login_attempts`, isti prag, isti zamik (`ADR-035` E).
- **Odjava je najprej lokalna.** Telefon žeton zavrže v vsakem primeru;
  klic na strežnik je najboljši poskus. Nedosegljiv strežnik ne sme
  pustiti otroka prijavljenega na napravi. Če brisanje iz varne shrambe
  spodleti, to zabeleži tabela `naprava` in naslednji zagon tak žeton
  zavrže (`ADR-037`).
- **Lokalni zapis nosi lastnika.** `materials.user_id` in `attempts.user_id`
  v bazi telefona (migracija 3): naprava je skupna, identiteta pa ne.
  Prenaša, šteje in kaže se izključno lastnikovo; zapis brez lastnika
  posvoji vsaka razrešena seja — prijava in obnovitev žetona z diska.
  Podrobnosti so v razdelku o lokalni bazi.
- **`401` ni `failed`.** Zapis ostane `pending` in prenos počaka na
  prijavo; to je edina izjema od pravila `ADR-004` poleg `410`. Izid ga
  **loči** od nedosegljivega strežnika (`Izid.prijavaPotekla`), ker je to
  edino stanje vrste, ki ga uporabnica more odpraviti sama: domača stran
  pove „Prijava je potekla, prijavi se znova". Odjave ob `401` ni —
  aplikacija pove, ne ukrepa namesto otroka (`ADR-036`, tretji pregled).

## Člani družine (V3-R06)

Starš na `/admin/family` odpre račun otroku ali drugemu staršu, ponastavi geslo
in člana deaktivira. Poti so v tabeli zgoraj, pravila v `app/clani.py`,
poizvedbe v `ClaniRepository`, odločitve v `docs/odlocitve/ADR-038`. Nove
tabele ni — `users`, `credentials` in `sessions` so postavljene v V3-R03.

- **Tri kode zavrnitve in vsaka pomeni drugo pot naprej.** `404` za tujega in
  za neobstoječega člana (isto besedilo — obstoj tujega računa ni podatek za
  starša), `403` za dejanje, ki ni tvoje (sebe, lastnik sistema, zadnji aktivni
  starš), `409` za stanje, ki že je tako. Seznam dejanja, ki bi bilo zavrnjeno,
  sploh ne ponudi; odloči isto pravilo, ki ga tudi zavrne.
- **Vrstni red treh pravil o deaktivaciji je izbira sporočila, ne okras**:
  lastnik sistema, nato zadnji aktivni starš, šele nato „sebe ne". Vsa vodijo
  v isti `403`; edini starš v družini mora dobiti „najprej dodaj drugega
  starša", ne „naj to naredi drugi starš", ki mu ne more slediti
  (`CLAUDE.md` §1b, `ADR-038` „Popravki po drugem pregledu").
- **Ponastavitev gesla in deaktivacija v isti transakciji izbrišeta vse seje
  člana.** Ponastavitev, po kateri bi kje ostala veljavna seja, ne bi bila
  ponastavitev. Velja brez izjeme tudi zase: starš, ki ponastavi lastno geslo,
  se s tem odjavi (`ADR-038` D). Lena preverba `is_active` v
  `prijava.seja_za_zeton` ostane kot druga plast.
- **Deaktivacija je obrnljiva, seje pa se ne vrnejo** (`ADR-038` A). Nič drugega
  se ne dotakne: snov, vprašanja in poskusi člana ostanejo.
- **Lastnika sistema ni mogoče deaktivirati**, geslo mu ponastavi samo on sam
  (`ADR-038` G) — sicer bi drugi starš izklopil račun, na katerem stoji
  `V3-R05`. Zastavice `is_system_owner` nobena od teh poti ne podeli.
- **Enoličnost identifikatorja razsodi baza**, ne poizvedba: repozitorij je
  vezan na družino in čez njo ne sme brati, `IntegrityError` pa je tako ali
  tako edini izid brez tekme. Sporočilo ob zasedenem imenu ne pove ne pri kom
  ne za kakšno vrsto računa gre (`ADR-038` E).
- **Identifikator se normalizira** (obrezani robovi, male črke) **ob nastanku
  računa, ob prijavi na obojih vratih in v ukazu `nastavi-geslo`**. Brez tega
  bi bila `Ana@primer.si` in `ana@primer.si` dva računa; stranski učinek je,
  da se omejevanju ugibanja (`ADR-035` E) ni mogoče izogniti z velikimi črkami.
  Identifikatorji, ki so nastali pred to zahtevo, so že v tej obliki, zato
  migracije ni.
- **Dodajanje nima vmesne potrditve**, ponastavitev, deaktivacija in aktivacija
  jo imajo. Vmesna stran pri dodajanju bi začetno geslo spravila v skrito polje
  in v zgodovino brskalnika (`ADR-038` F). Geslo se ne vrne v izris nikoli —
  tudi ob napaki se vrneta le ime in identifikator.
- **Urejanja člana in seznama prijavljenih naprav ni** (`ADR-038` B in H).
  `sessions.device_label` se piše naprej, a ga ne bere nobena stran.

## Lastnik sistema odpira družine (V3-R05)

Lastnik sistema na `/admin/system` odpre novo družino z njenim prvim staršem,
staršem ponastavi geslo ter starša ali celo družino deaktivira in vrne v
uporabo. Poti so v tabeli zgoraj, pravila v `app/sistem.py` in `app/clani.py`,
poizvedbe v `DruzineRepository` in `ClaniRepository`, odločitve v
`docs/odlocitve/ADR-044`.

- **Za vsakogar drugega ta predpona ne obstaja.** `zahtevaj_lastnika_sistema`
  visi kot odvisnost na `APIRouter`, zato velja za vsako njegovo pot, tudi za
  tisto, ki bo dodana pozneje; dvigne `404`, ki ga izriše isti prestreznik kot
  vsako neobstoječo pot. `403` bi povedal, da stran obstaja.
- **Tudi napačna metoda je tu podatek.** Starlette ob ujemanju poti in
  neujemanju metode odgovori s `405`, še preden steče odvisnost — in razlika
  med `405` in `404` pove, da pot obstaja. Zato `admin.prestrezi_napako` pod
  to predpono `405` prevede v `404` in **zavrže glavo `Allow`**, ki bi
  naštela, kaj pot sprejema (`sistem.je_skrita_pot`). Pravilo je na enem mestu
  in velja za vsako pot te predpone in vsako metodo, ki je ta pot nima; test
  se generira iz `openapi()` in zajame tudi pot, dodano pozneje. Brez razlike
  po vlogi: lastnik ob ročno vtipkanem naslovu izgubi le točnejše sporočilo.
  **Ostale poti pod `/admin` ostanejo pri `405`** — tam obstoj poti ni
  skrivnost. `POST /admin/system/families` ima poleg tega registriran `GET`,
  ki lastnika s `303` pelje na seznam; da pot ne bi bila slepa ulica.
- **Meja obljube je zapisana** (`ADR-045`): skrivanje velja za odgovore
  aplikacije, **ne** za usmerjanje okvirja in **ne** za shemo poti. Da stran
  obstaja, je torej mogoče ugotoviti; kaj je na njej, ne. Podatke drži
  `zahtevaj_lastnika_sistema`, ne koda odgovora.
- **Lastnik vidi imena, števila članov, datum in stanje — vsebine ne.** Ne
  slik, ne prepisov, ne kvizov, ne statistike, ne urnikov (`ADR-044` B). To ni
  stvar izrisa: nobena pot te predpone teh tabel ne bere, `DruzinaZaPregled`
  jih ne nosi, in `tests/test_tesnjenje.py` to trdi na treh ravneh — s sledmi
  vsebine čez vse lastnikove strani, s protitestom, da trditev ni prazna, in s
  prestrezanjem izvedenih SQL stavkov.
- **Starši poimensko, otroci samo kot število.** Otroka ureja njegov starš
  (`V3-R06`) in lastnik nad njim nima nobenega dejanja, zato njegovega imena
  ta stran ne pozna. `user_id` otroka pod potjo `parents/` je `404`.
- **Dejanja nad člani tečejo skozi `ClaniRepository(seja, ciljna_druzina)`** —
  torej skozi repozitorij z družino v konstruktorju (`ADR-025`), le da jo tu
  izbere naslov in ne prijava. Pravila `app/clani.py` veljajo nespremenjena;
  pravilo o zadnjem aktivnem staršu je `ADR-038` obdržal prav za tega
  klicatelja. **Aktivacija starša** obstaja, ker bi bila družina z enim samim
  deaktiviranim staršem sicer zaklenjena za vedno (`ADR-044` F).
- **Lastnik ne more ugasniti svoje družine in ne sebe.** Na njej stoji račun z
  `is_system_owner`; dejanje, ki ga vmesnik ponuja, mora biti preživeto
  (isto sklepanje kot `ADR-038` G).
- **Besedilo o zunanjem vision API-ju** je konstanta `sistem.BESEDILO_ZASEBNOST`,
  izrisana ob obrazcu za novo družino — na mestu in v trenutku, ko ga lastnik
  potrebuje. Obrazca soglasja ni: to bi bil pravni okvir, ki ga `ADR-025`
  izrecno ne želi.

### Deaktivirana družina

`families.is_active` je zastavica po vzoru `users.is_active`, **ne** prelivanje
na člane (`ADR-044` A):

- Preverja se na **dveh** mestih: `prijava.preveri_prijavo` (prijava zavrnjena
  z istim besedilom kot vsaka druga neuspela — da je družina ugasnjena, ni
  podatek za tistega, ki ugiba) in `prijava.seja_za_zeton` (obstoječa seja
  neha veljati in se izbriše). Velja na **obojih vratih**: starš v brskalniku
  in otrok na telefonu.
- **Ugasnitev v isti transakciji izbriše seje vseh članov**; prižig jih ne
  vrne. Članov se ne dotakne, zato prižig vrne družino v stanje pred
  ugasnitvijo — kdor je bil deaktiviran prej, ostane deaktiviran.
- **Podatki ostanejo nedotaknjeni:** snov, vprašanja, kvizi, poskusi, urniki in
  slike na disku. Deaktivacija se dotakne samo zastavice in sej.
- **Obhod obdelave ugasnjeno družino preskoči** (`DruzineRepository.idji_aktivnih`):
  slike ostanejo `new` in se obdelajo po ponovni aktivaciji — isti vzorec kot
  mirujoči worker brez ključa (`ADR-009` B2). `worker.obnovi_obticale` gre
  naprej čez **vse** družine: ne kliče ničesar zunanjega, vrstica, ki bi tam
  ostala `processing`, pa bi bila tiha izguba.

Migracija `0011_stanje_druzine` doda stolpec s `server_default` `true`;
obstoječe družine ostanejo aktivne in prepisa podatkov ni. `downgrade` stolpec
spusti in **dokončno izgubi podatek, katera družina je bila ugasnjena**, vrstic
pa ne — isti vzorec kot `0004` in `0009`.

### Znane omejitve

- **Števila članov vključujejo deaktivirane.** „1 starš" na seznamu je lahko
  starš, ki je v tabeli označen kot deaktiviran. Šteje se članstvo, ne
  dejavnost.
- **Drugega lastnika sistema ni mogoče ustvariti.** Zastavice `is_system_owner`
  ne podeli nobena pot; postavi jo migracija `0008_uporabniki`. Če bo lastnikov
  kdaj več, bo pravilo o „svoji družini" treba napisati čez vse družine, v
  katerih kakšen je.
- **Obstoj strani je mogoče ugotoviti po dveh poteh** (`ADR-045`, zavestno):
  `GET /admin/system/` s končno poševnico vrne `307` na naslov brez nje, ker to
  preusmeritev naredi Starlette sam in prestreznik je ne vidi; izklop
  (`redirect_slashes=False`) bi veljal za vso aplikacijo in podrl `GET /admin/`.
  `/openapi.json` pa vsakemu veljavnemu žetonu vrne vse poti aplikacije.
- **`/openapi.json`, `/docs` in `/redoc` so dosegljivi vsakemu veljavnemu
  žetonu, tudi otrokovemu.** Brez žetona so `401` (`ZetonMiddleware`), z njim
  vrnejo celotno shemo poti — tudi `/admin/family` (V3-R06) in `/admin/system`.
  Tako je od `V1`; to **ni** lastnost `V3-R05`. Zaprtje je svoja zahteva.

## Google prijava za starša (V3-R08)

Starš na `/admin/racun` poveže svoj Google račun; od takrat se prijavi z geslom
ali z Googlom in obe poti dasta sejo v isti tabeli `sessions`. Odločitve so v
`docs/odlocitve/ADR-046`, pravila v `app/google.py`, poizvedbe v
`PrijavaRepository`.

**`ADR-027` je s tem preverjen in drži:** Google je nova vrstica v
`credentials`, ne nova shema. `users` in `sessions` se nista dotaknila.

| Pot | Metoda | Plast | Kdo jo sproži |
|---|---|---|---|
| `/admin/racun` | GET | `SejaMiddleware`, brez izjeme | prijavljen starš |
| `/admin/racun/google` | POST | `SejaMiddleware` + CSRF | prijavljen starš |
| `/admin/racun/google/odstrani` | POST | `SejaMiddleware` + CSRF | prijavljen starš |
| `/auth/google/login` | POST | izvzeta iz `ZetonMiddleware`; CSRF preveri sama | obiskovalec brez seje |
| `/auth/google/callback` | GET | izvzeta iz `ZetonMiddleware`; veže `state` | Googlova preusmeritev |

- **Razcep poti gre po tem, kdo klic sproži** (`ADR-046` B). Povezovanje in
  odstranitev sta pod `/admin`, ker ju sproži prijavljen starš — sejo in CSRF
  jima preveri ista plast kot vsaki drugi strani, in generirani test
  dosegljivosti (`V3-R03`) ju pokrije brez izjeme. Zunaj `/admin` sta samo
  tisti dve poti, ki ju sproži nekdo brez seje. `IZVZETE_POTI` je s tem
  zrasel za **dve točni poti**; `IZVZETE_PREDPONE` ostaja enočlanska.
- **`identifier` Google poverilnice je Googlov `sub`, ne e-naslov**
  (`ADR-046` A). `credentials.identifier` je enoličen čez celo namestitev, zato
  bi e-naslov podrl prav stanje, ki ga zahteva kriterij 2 — starša z geslom in
  Googlom na istem naslovu. `sub` je hkrati edina vrednost, za katero Google
  jamči, da se ne spremeni. E-naslov živi v novem stolpcu `credentials.label`
  in služi **izključno izrisu**: po njem se nikoli ne išče in nikoli ne
  prijavlja. Ob vsaki prijavi z Googlom se osveži.
- **Povratni klic je en sam za oba tokova** (`ADR-046` C). Kaj se dogaja, pove
  piškotek stanja, ne naslov; v Googlovi konzoli je zato vpisan en sam
  povratni naslov. Ta se sestavi iz nastavitve `DOMENA` in ne iz `request.url`:
  za Caddyjem je gostitelj v zahtevi notranje ime vsebnika.
- **`state` je vezivo in ne okras** (`ADR-046` D). Povratni klic je navaden
  `GET` iz tujega konteksta. Naključje iz `Stanje` živi v piškotku
  `google_state` (`HttpOnly`, `Secure`, `SameSite=Lax`, 10 minut) in se ob
  povratku primerja s `compare_digest`; piškotek nosi še **namen** in, pri
  povezovanju, **`user_id` starša, ki je tok sprožil**, ki se mora ujemati z
  dejavno sejo. Piškotek se pobriše ob **vsakem** izidu — enkratna raba je del
  veziva. `SameSite=Lax` je pravi in ne ohlapni: Googlova preusmeritev je
  vrhnja navigacija, zato piškotek pride s seboj, `Strict` bi tok pokvaril in
  `None` bi vezivo izničil. **Primerjata se bajta, ne niza:** `compare_digest`
  nad `str` zahteva čisti ASCII in ob vsakem drugem znaku vrže `TypeError` —
  `state` iz naslova in piškotek (latin-1) pa sta oba vhod od zunaj. Taka
  izjema bi bila 500 z golim angleškim besedilom na javni poti in bi ušla pred
  brisanjem piškotka, s čimer bi padla prav enkratna raba (najdeno v prvem
  pregledu `V3-R08`). Primerjava **ni svoja**: gre skozi
  `prijava.zetona_se_ujemata`, ki od `V3-R08` primerja bajte in pokriva vsa
  štiri klicna mesta — obe prijavi, `SejaMiddleware` in nalaganje urnika.
  Svoja dvojnica je bila prvi popravek te napake in je razhajanje tudi
  povzročila (`docs/02-izkusnje.md`).
  Brez tega veziva bi napadalec svoj Google račun prilepil na starševega in v
  njegovo družino vstopal, kolikor dolgo bi hotel — zato ima vsak od teh
  pogojev svoj test, ki dokaže tudi, da poverilnica **ni** nastala in da do
  Googla sploh ni prišlo.
- **Prijava nikoli ne ustvari uporabnika ali družine** (kriterij 3,
  `ADR-025`). Neznan `sub`, deaktiviran račun in ugasnjena družina dajo **isto**
  oznako napake; razlika bi bila podatek o tem, kdo v tej namestitvi obstaja.
  Registracija ostane zaprta.
- **Skozi naslov potuje oznaka, nikoli besedilo.** Prijavna stran izriše samo
  oznako, ki jo pozna `google.SPOROCILA_PRIJAVE`; neznana ne pokaže ničesar.
  Prosto besedilo v naslovu bi pomenilo, da lahko kdorkoli s pripravljeno
  povezavo nariše poljubno sporočilo na prijavno stran — in prav ta stran je
  tista, kjer je tako sporočilo vabilo.
- **Napaka pove tam, kjer jo bo bralec videl, in tako, kot se ga tiče.**
  **Kam** odloči seja: kdor je prijavljen, dobi stran s pojasnilom (`409`),
  kdor seje nima, prijavno stran — preusmeritev prijavljenega starša na prijavo
  bi mu povedala, da je bil odjavljen, česar ni bil. **Kaj** odloči tok:
  `SPOROCILA_POVEZAVE` in `SPOROCILA_PRIJAVE` sta dva slovarja nad istimi
  oznakami, ker staršu sredi povezovanja nasvet „prijavi se z geslom" ne pove
  ničesar (prijavljen je), na prijavni strani pa je prav ta nasvet pravi.
- **Odstranitev povezave ne odjavi in ne odnese gesla** (kriterij 6). Ni
  ponastavitev gesla, zato sej ne prekliče. Odstranitev, po kateri na računu ne
  bi ostala nobena poverilnica za prijavo — račun brez gesla shema dopušča in
  tako ga pusti migracija `0008` — se **zavrne** (`ADR-046` G); isto pravilo
  gumba tudi ne ponudi in stran pove, zakaj ga ni.
- **Enoličnost `sub` razsodi baza**, ne poizvedba pred vstavljanjem: ta bi bila
  tekma. `IntegrityError` prevede `je_zaseden_identifikator` v isto izjemo kot
  pri članih družine (`ADR-038` E) — kršitev je ista omejitev na istem stolpcu.
- **Google velja izključno za starša**, in to pove `prijava.Vrata`, ne nov
  `if`. Poverilnica `kind='google'` na otrokovem računu po nobeni poti ne more
  nastati, ker povezovanje teče pod `/admin`; pravilo vseeno stoji tam, kjer
  seja nastane (`ADR-046` H). Otrokov Google račun je izven obsega V3.
- **Podpisa ID žetona ne preverjamo, in to je zavestno** (`ADR-046` E).
  Podatke dobimo neposredno od Googla prek TLS, ne prek brskalnika; preverba
  podpisa je potrebna takrat, ko žeton pride po nezaupani poti. Zato ni
  `authlib` in ni `pyjwt[crypto]` z JWKS predpomnilnikom. `httpx` ni nov paket
  — nameščen je že prek `openai` —, a je odslej izrecno v `dependencies`.
- **Zahtevani obsegi so samo `openid`, `email` in `profile`.** Obseg, ki ga
  prosimo, je tisto, kar starš na Googlovem zaslonu prebere o nas.
- **Klic Googlu ima časovno omejitev (15 s) in teče v niti**, iz istega razloga
  kot argon2 v geselni prijavi: sinhron klic na zanki dogodkov bi ustavil vse
  ostale zahteve, tudi prenos slike s telefona.

### Namestitev brez Googla

Brez `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` ali `DOMENA` Google v tej
namestitvi ni na voljo (`Settings.google_je_nastavljen`, `ADR-046` F):

- gumba „Prijava z Google računom" na prijavni strani ni,
- ime v glavi ni povezava na `/admin/racun`,
- vseh **pet** Googlovih poti vrne **404** (ne 503: pot, ki je ta namestitev
  nima, za obiskovalca ne obstaja). Pet in ne štiri: poleg obeh dejanj in
  obeh poti zunaj `/admin` je tu tudi `GET /admin/racun` sam.

Strežnik se zažene normalno — ista drža kot pri manjkajočem `OPENAI_API_KEY`
(`ADR-009`): manjkajoča nastavitev ustavi eno zmožnost, ne strežnika. Prijava z
geslom ne potrebuje ničesar od tega.

Ali je Google na voljo, pove `google_na_voljo` iz obdelovalca konteksta
(`app/strani.py`) in ne posamezna pot: obdelovalec ključe, ki jih poda pot,
prepiše, zato ima vsak ključ enega samega lastnika (`docs/02-izkusnje.md`).

### Sklop zunaj repozitorija

V Google Cloud Console: projekt, **OAuth consent screen** tipa *External* z
obsegi `openid`/`email`/`profile`, nato **Credentials → OAuth client ID** tipa
*Web application* s povratnim naslovom
`https://school-buddy.duckdns.org/auth/google/callback` — **točno tako**, brez
končne poševnice, ker Google ujemanje zahteva znak za znak.

Aplikacija ostane v načinu **Testing**: prijavijo se lahko samo ročno vpisani
preizkusni računi (do 100). Za krog znancev je to dovolj in prihrani Googlovo
preverjanje aplikacije; širši krog je nova zahteva, ne popravek (`ADR-025`).

`client_id` in `client_secret` gresta v `apps/server/.env` kot
`GOOGLE_CLIENT_ID` in `GOOGLE_CLIENT_SECRET`. Skrivnosti v repozitoriju ni in
ne sme biti; `okolje.primer` nosi imeni brez vrednosti, kar varuje test.

### Znane omejitve

- **`credentials.label` je lahko zastarel.** Osveži se ob prijavi z Googlom,
  ne ob spremembi pri Googlu. Vrednost je prikaz in iz nje ne izhaja nobena
  pravica, zato je zastarel izpis cenejši od poizvedbe brez razloga.
- **Lastnik sistema tujih Google povezav ne ureja.** Povezavo sproži in
  odstrani izključno starš sam (kriterij 4); `/admin/system` se ni spremenil.
  Starš, ki izgubi dostop do svojega Google računa, se prijavi z geslom — to mu
  ponastavi lastnik sistema.
- **Kdaj je bila seja ustvarjena z Googlom, ni zapisano.** `sessions` se ni
  dotaknila (kriterij 1) in seznama prijavljenih naprav ni (`ADR-038` H).
- **Odjava iz Googla ni naša.** Naša odjava izbriše našo sejo; Googlove ne in
  je ne sme.

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

**Kviz ima naslovljenca** (V3-R07): enega otroka svoje družine. Izbere se
**nad seznamom**, ker odloča, katera snov velja za „že v kvizu"; polje se
izriše samo pri več kot enem otroku. Menjava otroka gre skozi `GET /new` in ne
skozi `POST /new`, ker se morajo kljukice preračunati po pravilu vstopa; skozi
predogled potuje v skritem polju, kot ves ostali izbor (`ADR-016` C).

**Branje ima privzetek, objava ga nima** (`ADR-039` A): `GET` brez `otrok`
vzame prvega po prikaznem imenu, `POST /admin/quizzes` brez njega pa je `409`
— skrito polje ni varovalka. Prazen niz šteje enako kot manjkajoče polje.
Družina **brez aktivnega otroka** vstopov na `/admin` ne dobi in pot vrne
`409`; isto pravilo odloči oboje.

**„Bila v kvizu" šteje po naslovljencu** (`ADR-017` B, zožen z `ADR-039` G):
poleg „kviz ni preklican" in „vprašanje je veljavno" velja še „kviz je bil
namenjen istemu otroku". Snov, iz katere je nastal kviz za sestro, je za brata
še vedno nova.

Seznam snovi **ni** omejen na snov naslovljenca: vprašanja so last družine.
Pri več kot enem otroku vsaka vrstica pove, čigava je snov. Poizvedba gre prek `quiz_items → questions.material_id`;
tabele `quiz_sources` ni in po `ADR-016` (D) ne bo, dokler ne bo naključnega
izbora.

Izbirnik so **štiri poizvedbe** ne glede na dolžino seznama: ena za snovi, ena
za števila veljavnih vprašanj (`GROUP BY material_id`), ena za množico snovi,
ki so že v kvizu, in ena za otroke družine (V3-R07). Tri je postalo štiri z
`V3-R07`; lastnost, ki šteje, je „stalno število ne glede na dolžino seznama",
in otroci so ena poizvedba na stran, ne ena na vrstico. Sličice se nalagajo z `loading="lazy"`, kot na strani
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

## Pregled po dnevih (V2-R07)

`GET /admin/days` pokaže **nearhivirane** slike **enega otroka** (V3-R07) v
obdobju, grupirane po lokalnem
koledarskem dnevu (padajoče) in znotraj dneva po vrstnem redu `PREDMETI`;
slike znotraj predmeta so **naraščajoče** po `taken_at`, ker so zaporedni
posnetki strani iste snovi (`ADR-003`). Predmet brez slik tistega dne se ne
izpiše, **dan brez slik pa se izpiše prazen** — prav odsotnost slik je odgovor
na vprašanje, ali je bila snov poslikana (`ADR-023`).

Obdobje je en dan (`?dan=YYYY-MM-DD`, privzeto današnji) ali teden
(`?obdobje=teden`), pri čemer je **teden zadnjih sedem dni, ki se končajo z
današnjim**, in ne koledarski teden. Sidro je današnji dan, zato gumb ne nosi
datuma in je `?obdobje=teden&dan=…` zavrnjen kot 400: parameter, ki na obseg ne
vpliva, ne sme izgledati, kot da nanj vpliva.

**Neveljaven vhod je 400 in ne tih padec na privzetek.** Tu se ta pot namenoma
razlikuje od statistike, kjer nerazberljiv `?leto=` pade na tekoče šolsko leto:
tam je okno pripomoček nad istimi podatki, tu je datum celoten pomen strani.
Razlog je zapisan v `ADR-023`, da razlika kdaj ne bo odkrita kot nedoslednost.

**Neveljaven `?otrok=` pa je 404** — tretje pravilo za tretjo vrsto parametra
(`ADR-039` B): otrok ni ne okno ne datum, ampak **identiteta podatkov**, in za
identiteto v tem projektu že velja `404` z istim besedilom za tujega in za
neobstoječega (`ADR-038`). Izbira otroka in izbira obdobja sta neodvisni in
vsaka mora drugo preživeti, zato gumbi obdobja nosijo `otrok` naprej.

**Meje obdobja so polodprte in lokalne** (`ADR-016` B). Izračuna jih
`app/casi.py:dnevi_od_do` in repozitoriju poda kot par UTC trenutkov;
grupiranje po lokalnem dnevu je v Pythonu, ker izraz za lokalni dan v SQL ni
prenosljiv med SQLite (testi) in Postgresom (produkcija).

**Grupiranje je drugi filter, in to je vidno v testih.** Snov, ki bi iz SQL
prišla čez zgornjo mejo, pade ven, ker njenega lokalnega dneva na seznamu dni
ni — stran je zato pravilna tudi ob meji `<= do`. Meje se zato presojajo nad
`MaterialsRepository.seznam_po_obdobju` in ne nad izrisom. Odkrito z
mutacijskim preizkusom v V2-R07.

`danes()` bere koledar v domačem pasu in ne strojne ure: v vsebniku teče UTC in
med lokalno polnočjo in dvema bi `date.today()` vrnil še prejšnji dan. Razlike
ne pokaže noben test nad stranjo, ker je stroj lastnika v istem pasu —
pritrjena je z namestnikom `datetime` (`TestDanes`).

V glavi strani piše, kdaj je strežnik nazadnje prejel sliko
(`max(materials.received_at)` čez **vse** zapise, tudi arhivirane). Brez tega
je prazen dan videti enako kot dan, ko telefon še ni prenašal.

Sličic ni in se s to zahtevo ne uvajajo: uporabi se ista pot do slike kot
drugje, z `loading="lazy"` in pomanjšavo v CSS. Teden je zato zgornja meja
obsega.

## Povečan prikaz slike (V2-R08)

Na `/admin/materials/{id}` je slika povezava na `/image`. Skripta klik
prestreže in odpre prikaz čez celo okno z isto datoteko, brez omejitve
`max-height: 78vh` (prikaz stoji zunaj `.snov`). Snov brez datoteke prikaza,
povezave in skripte nima.

**Meje so iz `ADR-024`** in veljajo za vsako prihodnjo skripto pod `/admin`:
vgrajena v predlogo, brez zunanjega vira, stran dela brez nje, in ničesar ne
pošilja ne sestavlja. Zato je prikaz v izrisu z atributom `hidden` in vse
povezave v njem izriše strežnik — sosede, prenos in ime datoteke. Slog mora
`hidden` vrniti izrecno (`.prekritje[hidden] { display: none; }`), ker ga
`display: grid` sicer prevlada.

**Puščici peljeta na podrobnosti soseda** s sidrom `#povecano`, ki prikaz ob
prihodu spet odpre; skripta ga ob zaprtju odstrani s `history.replaceState`.
Slika se v prikazu ne zamenja, zato se prenese samo tista, ki jo operater
gleda. Smer je smer mreže na strani predmeta: levo novejša, desno starejša.
Na robu je puščica `<span>` in ne povezava; ovijanja ni. Arhivirana snov
puščic nima, ker je v naboru ni.

**Nabor sosedov je nabor strani predmeta**: `MaterialsRepository` ima zanj en
filter (`_nabor_predmeta`) in en vrstni red (`_VRSTNI_RED_PREDMETA`:
`taken_at DESC, id DESC`), ki ju bereta `seznam_po_predmetu` in
`sosedi_v_predmetu`. Drugi ključ je nujen: dve sliki z istim časom bi imeli
nedoločen vrstni red in listanje bi eno preskočilo. `sosedi_v_predmetu` bere
samo stolpec `id` — ena poizvedba na stran, pri arhivirani snovi nobena.

Ime prenosa je `MAT_2026-09-04_09-30.jpg` (koda, lokalni čas na minuto; znaki
kode zunaj `[A-Za-z0-9-]` so `_`) in gre v atribut `download`. Pot `/image` in
njen odgovor sta ostala nespremenjena.

### Znane omejitve

- **Vedenja prikaza testi ne dokažejo** — samo zgradbo (skrit prikaz, povezave,
  ime, meje skripte). Odprtje, zapiranje, zaklep drsenja in tipke se preverijo
  v brskalniku.
- **Fokus v prikazu ni ujet**: tabulator ga lahko odnese na stran za njim.
- **Vsaka puščica je nova stran** in nov vnos v zgodovini brskalnika.

## Urnik in manjkajoče slike (V3-R09)

**Urnik je množica predmetov na posamezen dan**, brez ur in brez zaporedja, in
je **last otroka** (`ADR-028`). Pozna ponedeljek do petka (`ADR-041` F);
izmeničnih tednov ne.

Tabela `schedules` (`id`, `family_id`, `child_id`, `confirmed_at`,
`replaced_at`, `image_path`) in `schedule_entries` (`id`, `schedule_id`,
`weekday` 0–4, `subject`, `skip_photo`, enolično po `schedule_id + weekday +
subject`). Vnos družine nima — izpelje se iz urnika, kot pri `quiz_items`
(`ADR-029` C). Migracija `0010_urnik` je gol `CREATE TABLE`; `downgrade` obe
tabeli spusti in **dokončno izgubi vse urnike**, kot `0005_kvizi`.

**Veljaven urnik je en sam na otroka** in ga določa os `replaced_at IS NULL`,
po vzorcu `archived_at` (`ADR-011`) in `retired_at` (`ADR-015`). Enoličnost
uveljavlja **ena pot pisanja v eni transakciji** (`ScheduleRepository.potrdi`:
upokoji prejšnje, vstavi novega) in ne delni indeks — tega bi bilo treba
zapisati dvakrat, za SQLite in za Postgres. Zamenjava nosi **en trenutek**:
`replaced_at` starega je enak `confirmed_at` novega, zato razvrstitev med
njima ne loči in veljavnost stoji izključno na osi.

**Slika urnika ni snov.** Živi v `<images_dir>/<family_id>/urniki/<uuid>.jpg`
in nikoli v `materials`; iz nje ne nastane nobeno vprašanje. Sicer bi se
pojavila v izbirniku kvizov, v statistiki in na strani predmeta.

**Pot skozi vmesnik** je dvokoračna in teče v adminu (`ADR-041` A):

1. `POST /admin/schedule/proposal` naloži sliko, jo zapiše na disk in
   **sinhrono** pokliče model (`asyncio.to_thread`, ker je odjemalec OpenAI
   sinhron). Izid je izpolnjena mreža; v bazo se ne zapiše nič.
2. `POST /admin/schedule` potrdi mrežo. Skrito polje nosi `slika_id` in nikoli
   poti — pot sestavi strežnik.

Slika se zapiše **ob nalaganju in ne ob potrditvi** (`ADR-042`): med korakoma
je nova zahteva in strežnik med njima ne hrani ničesar, nositi bi jo moral
brskalnik kot base64. Cena je datoteka brez vrstice, kadar starš nalaganje
opusti. **Revizijske sledi urnik nima**, za razliko od `materials`: potrjen
urnik ni odgovor modela, ker ga starš vmes popravi.

**Mreža je urejljiva tudi brez slike** (`ADR-041` E) in je **cela**: kar v njej
ni označeno, na urniku ne obstaja — potrditev je zamenjava, ne krpanje. Vsaka
celica je izbirnik s tremi stanji (ni na urniku / se slika / se ne slika); dve
potrditveni polji bi dopustili četrto, nesmiselno kombinacijo. Skripte stran
nima (`ADR-024`).

**Model preslika kode sam**: prompt nosi seznam desetih kod, odgovor pa za
vsako celico `day`, `text` in `subject`. Kar ni ena od desetih kod, je
**nepreslikana celica** in se izpiše nad mrežo z dobesedno prebranim
besedilom — nikoli ne izpade molče in nikoli ne pride v potrjen urnik.

**Manjki** na `/admin/days`: za vsak **delno poslikan** dan se naštejejo
predmeti z urnika tistega dne brez ene same nearhivirane slike tega otroka, v
vrstnem redu `PREDMETI`. Računajo se ob izrisu (`app/urnik.py`,
`manjkajoci_predmeti`) in se nikjer ne predračunavajo, zato so pravilni tudi
takoj po premiku snovi v drug predmet (V3-R10). Tri stvari vrnejo prazno:
otrok brez urnika, dan brez ene same slike (`ADR-028` E2) in dan, ko je vse
poslikano. Stanje obdelave in berljivost na manjko ne vplivata; predmet z
`skip_photo` ga ne javlja nikoli; poslikan predmet zunaj urnika se ne javlja
in manjka tudi ne zapre.

### Znane omejitve

- **Pregled za nazaj sodi po trenutno veljavnem urniku** (`ADR-028` D2). Po
  polletni menjavi bo november ocenjen po februarskem urniku.
- **Arhiviran dan izgleda kot dan s samimi manjki**, ker se arhivirane slike ne
  štejejo.
- **Dan pouka brez slik in praznik sta videti enako** — oba brez manjkov.
- **Današnji dan se obravnava kot vsak drug**: delno poslikan dan opoldne
  manjke izpiše, čeprav pouk še traja.
- **Upokojeni urniki in njihove slike rastejo brez meje** in brez vmesnika, ki
  bi jih pokazal. Pri dveh na leto je to sprejeto.
- **Zakaj je model kaj prebral narobe, se za nazaj ne da ugotoviti** — sledi ni.
- **„Veljaven je en sam" drži pri zaporednem pisanju, ne pri sočasnem.**
  `potrdi` naredi `UPDATE ... WHERE replaced_at IS NULL` in nato `INSERT` v
  eni transakciji, brez zaklepa nad otrokom. Na Postgresu (`READ COMMITTED`)
  dve hkratni potrditvi istega otroka zato lahko pustita **dve** veljavni
  vrstici: `UPDATE` druge transakcije ne zajame vrstice, ki jo je prva vstavila
  po začetku njegovega skeniranja. Sprozilec je dvojni klik na „Potrdi urnik"
  — stran nima skripte, ki bi gumb onemogočila. Branje to ublaži
  (`veljaven` ima `order_by(confirmed_at desc, id desc).first()`), ne odpravi.
  `ADR-041` C je zavestno izbral, da enoličnosti ne uveljavlja shema; kriterij
  v `v3.md` pa je zapisan absolutno, zato naj razhajanje stoji tu in ne ostane
  implicitno. Popravek, ko bo potreben, je zaklep otroka ali delni indeks.

## Premik slike v drug predmet (V3-R10)

Obrazec na strani s podrobnostmi snovi (`<select>` z desetimi predmeti v
vrstnem redu urnika, trenutni izbran) in `POST /admin/materials/{id}/subject`.
Snov s kodo zunaj desetih trenutne možnosti nima, zato dobi **vodilno možnost
brez vrednosti** — sicer bi brskalnik izbral prvo (`NAR`) in klik bi snov tiho
vložil pod Naravoslovje. Prazna vrednost pade v isto vejo kot neznana koda.
`MaterialsRepository.premakni_v_predmet` v **eni transakciji** popravi
`materials.subject` in `questions.subject` vseh vprašanj te snovi, veljavnih
in upokojenih. Oba stavka nosita pogoj družine.

Pogoja „ni arhivirana" in „ni v obdelavi" sta **v stavku `UPDATE`**, ne v
branju pred njim (`ADR-040` C1): worker vprašanjem predmet prepiše iz snovi,
ki jo prebere tik pred zapisom, in branje-nato-pisanje bi pustilo okno, v
katerem nova vprašanja dobijo star predmet. Neizbran ali neznan predmet je
400 s slovensko stranjo, tuja ali neobstoječa snov 404.

Objavljeni kvizi se ne spremenijo — ne `quizzes.subject`, ne ime, ne postavke
(`ADR-016` E). Nove skripte obrazec ne prinese; edina skripta te strani ostane
povečan prikaz (`ADR-024`).

### Znane omejitve

- **Telefon predmeta ne izve.** Zgodovina na napravi kaže predmet, ki ga je
  izbral otrok ob slikanju; strežnik lokalne baze telefona ne piše
  (`ADR-040` A1). Ponovni prenos iste slike popravka ne povozi, ker je
  `POST /materials` idempotenten glede na `id`.
- **Prvotni predmet se nikjer ne hrani** in dnevnika premikov ni.
- **Premik je po ena snov.** Večkratne izbire na seznamu predmeta ni.

## Slovenske oblike števil

Slovenščina je pri števnikih **štirioblična** in ima dvojino: *1 slika,
2 sliki, 3 slike, 5 slik*. `stevilo_z_besedo` (`app/besedilo.py`) to zna;
oblike so **podatek in ne koda** — vsak samostalnik je četverica na enem mestu
(`SLIKE`, `VPRASANJA`, `SNOVI`, `POSKUSI`).

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

## Rezultat kviza in tisk (V2-R03)

**Rezultat ima samo rešen kviz** (`solved_at`), tudi preklican: preklic ima
prednost pri **stanju** (`ADR-019` C) in opozorilo ostane na vrhu, poskusi pa
so dejstvo in se pokažejo pod njim. Nerešen kviz — tudi napol ocenjen — se
izriše natanko tako kot pred V2-R03 in ne plača nobene poizvedbe več.

Rezultat je na **isti** strani kviza (`/admin/quizzes/{id}`) in ne na svoji
poti. Postavke so v štirih skupinah v vrstnem redu `OCENE` (od najtežje
navzdol), znotraj skupine po `position`. Skupina je vidna tudi prazna, s
številom 0 — kriterij zahteva „število v vsaki skupini". Peta skupina „Brez
ocene" nastane samo, kadar ni prazna: rešen kviz ima poskus pri vsaki postavki
in strežnik sprejme samo štiri kode, a postavka z nepoznano oceno ne sme iz
rezultata izpasti molče. Številka pri vprašanju je **številka v kvizu**
(`<li value>`), ne mesto v skupini.

Nad skupinami stoji stavek, da so ocene Mašina samoocena in ne preverjeno
znanje (`ADR-014`: kjer se prikaže, mora biti jasno, čigava trditev je).

**Trajanje** sta dve števili (`ADR-019` D): *razmislek* (pokazano → razkrit
odgovor) in *ocena* (razkrit odgovor → ocenjeno). Izračuna ju `casi.trajanje`;
negativna razlika (premik ure telefona) je „—", naiven čas iz SQLite se razume
kot UTC.

**Izvor** ima v rezultatu več stanj kot na strani nerešenega kviza: snov v
arhivu, arhiv s počiščeno sliko, aktivna snov brez slike na disku (isto pravilo
kot v izbirniku: `je_znotraj` in `velikost_slike`) in upokojeno vprašanje —
takrat je prepis na strani snovi novejši od vprašanja. Te oznake so **samo v
rezultatu**: stran nerešenega kviza se ne sme spremeniti, ker test iz V2-R01
dokazuje, da je ponovna obdelava ne spremeni (`prej == potem`).

Rešen kviz je **šest poizvedb** ne glede na dolžino: kviz, postavke,
vprašanja, snovi (`KviziRepository.snovi_postavk`, ena poizvedba po `id`),
poskusi (`poskusi_kviza`, ključani po postavki — postavka ima največ en poskus)
in otroci družine (V3-R07: stran mora povedati, čigav rezultat bereš).
Izbirnika tu ni — kviz ima natanko enega naslovljenca.

**Tisk** (`/admin/quizzes/{id}/print`) je tudi za reševanje na papir:

- del z vprašanji je **brez odgovorov in brez naslovov skupin** (naslov
  „Nisem vedela" bi Maši povedal, kaj je prvič mislila), s praznim okvirjem za
  odgovor; vrstni red od najtežje navzdol, oštevilčeno znova od 1;
- ključ (`.kljuc`) se začne na novem listu (`break-before: page`) in nosi iste
  številke, vprašanje in odgovor;
- besedilo je zamrznjeno iz postavk, kot povsod (`ADR-016` E).

Izbor ocen je obrazec `GET` s kljukicami `ocena` in skritim poljem `izbor=1`.
Brez `izbor` velja privzetek (*Nisem vedela*, *Težko*); s `izbor` in brez
nobene `ocena` je izbor prazen in stran pove, da ni kaj natisniti. Skrito polje
je nujno — obrazec brez obkljukanega okenca ne pošlje ničesar in bi se sicer
tiho vrnil v privzetek. Test to dokazuje tako, da obrazec prebere **iz
izrisa** in ga pošlje, ne z ročno sestavljenim naslovom. Nerešen kviz je 409.

Gumba „Natisni" ni — brez JavaScripta ga ni. Stran naroči Ctrl+P. Slog za tisk
je `@media print` v `osnova.html`: skrije glavo in vse z razredom
`ne-tiskaj` (obrazec, navodilo, povezavo nazaj).

**Slog v `osnova.html` je del vsake izrisane strani**, tudi njegovi komentarji.
Testi, ki trdijo, da neke besede na strani ni, jo vidijo tudi v `<style>`:
komentar z besedo „izbora" je med izvedbo podrl nepovezan test predogleda.
Komentarji v slogu osnove naj zato ne uporabljajo besed iz vmesnika.

### Znane omejitve

- **Postavitve na papirju testi ne dokažejo** — samo, da pravila obstajajo.
  Prelom pred ključem, višina okvirja za odgovor in skrita glava se preverijo v
  predogledu tiskanja brskalnika.
- **Vprašanj iz skupine „Brez ocene" ni mogoče natisniti** — obrazec ponudi
  samo štiri ocene. Taka skupina nastane le ob ročno spremenjeni bazi.
- **`?ocena=…` brez `izbor`** (ročno vtipkan naslov) se prezre in velja
  privzetek. Obrazec `izbor` pošlje vedno.

## Statistika čez kvize (V2-R04)

Dve strani pod `/admin`: pregled po predmetih (`/admin/statistics`) in stran
predmeta (`/admin/statistics/subjects/{koda}`) s tabelo po mesecih, seznamom
snovi in seznamom vprašanj. Snov svoje strani nima — vrstica snovi vodi na
obstoječo stran snovi. Pravila so v `docs/odlocitve/ADR-021`.

**Nič se ne shranjuje.** Vse se izračuna ob branju iz `question_attempts`
(`ADR-012`); statistika ne prinese nobene tabele, stolpca ne migracije.
Pravilnost se izpelje na enem mestu, `statistika.je_pravilna` (`ADR-014`).

**Kaj šteje:** vsak poskus z `mode = 'samoocena'` — tudi iz preklicanega kviza
(`ADR-021` E), iz napol rešenega kviza, na upokojeno vprašanje (z oznako,
`ADR-021` D) ter iz arhivirane ali dokončno izbrisane snovi. Postavka brez
poskusa ne šteje. Poskus brez vprašanja in poskus z neprepoznano oceno ne
gresta v razporeditev, a ju stran omeni s številom. Filter načina je v skupnem
`StatistikaRepository._pogoji`, da ga nobena poizvedba ne pozabi.

**Predmet je `questions.subject`**, ne `quizzes.subject`: dnevni kviz predmeta
nima.

**Obe strani sta ločeni po otroku** (V3-R07, `?otrok=`), brez možnosti „vsi
otroci" (`ADR-039` B). Privzet je prvi po prikaznem imenu; izbirnik se izriše
samo pri več kot enem otroku in našteje tudi **deaktivirane** — njihovi podatki
ostanejo (`V3-R06`). Povezave nosijo obe izbiri hkrati, sicer bi menjava leta
tiho vrnila privzetega otroka.

**Okno** je šolsko leto (parameter `leto`: `2026` za 2026/27 ali `vse`),
privzeto tekoče. Meja je lokalna polnoč 1. 9., polodprto — poleti je to 31. 8.
ob 22:00 UTC (`casi.solsko_leto`, `solsko_leto_od_do`). Parameter se bere kot
niz; nerazberljiva vrednost ali leto zunaj 2000–2100 pade na tekoče leto in
stran to pove. Časovna os je `answered_at` v domačem pasu.

**Razvrstitev** (`ADR-021` C): dva razdelka, „Postavljena večkrat" (≥ 2
poskusa) in „Postavljena enkrat"; znotraj po deležu *Nisem vedela* + *Težko*
padajoče, nato po številu poskusov, nato novejši zadnji poskus prvi, nato
`id`. Snovi so po istem ključu. Pregled po predmetih je po urniku, zato stavek
„Najtežje je zgoraj" stoji samo na strani predmeta. Pri vprašanju je zaporedje
ocen z datumi in povezavami na kvize.

**Odstotki** se zaokrožajo na celo število, polovica navzgor, v celoštevilski
aritmetiki (`statistika.odstotek`) — Pythonov `round` zaokroža bančno.

**Seštevanje je v Pythonu in ne v `GROUP BY`**: razvrstitev v mesece v domačem
pasu ni prenosljiva med SQLite in Postgresom. Stran predmeta je tri poizvedbe
ne glede na dolžino (poskusi, snovi, časi za izbiro let), pri kodi, ki je ni
na seznamu desetih, še četrta. Pravila štetja v `app/statistika.py` so čiste
funkcije brez seje, po delitvi `obdelava.py` / `worker.py`.

**`OZNAKE_OCEN` živi v `app/subjects.py`**: potrebujeta ga rezultat kviza in
statistika, zato ni last nobenega usmerjevalnika.

Pas razporeditve je slika (širina v odstotkih, brez JavaScripta); števila ob
njem so podatek.

Test „samo pod `/admin`" bere poti iz `app.openapi()["paths"]` in ne iz
`app.routes`: FastAPI 0.14x vključene usmerjevalnike v `app.routes` hrani kot
`_IncludedRouter` brez poti.

### Znane omejitve

- **Razdelek „Postavljena večkrat" bo sprva kratek.** Isto vprašanje pride
  znova le prek *Ročne izbire* ali dnevnega vstopa (`ADR-016` D).
- **Ponovna obdelava pretrga zgodovino vprašanja** — nova serija je nova
  identiteta (`ADR-021` D). Seštevek snovi se ne pretrga.
- **Stran predmeta bo čez leto dolga.** Popravek, če bo potreben, je
  ostranjevanje, ne tiho krajšanje.
- **Kdor je prijavljen kot starš, vidi ves `/admin` svoje družine**, tudi
  statistiko (`ADR-021` F). Ločenih pravic znotraj admina ni.

## Kvizi na telefonu (V2-R02)

Telefon dobi kviz kot **zaprt objekt s celotno vsebino** in ga reši brez
omrežja. Splošne sinhronizacije vprašanj ni (`ADR-016`, posledice).

### Pogodba

| Pot | Kaj |
|---|---|
| `GET /quizzes/pending` | **celoten delovni seznam** nepreklicanih in nerešenih kvizov **prijavljenega otroka** (V3-R07), najstarejši prvi, s postavkami; besedilo je zamrznjeno iz `quiz_items`, ne iz `questions`; pri vsaki postavki `answered` |
| `POST /quiz-attempts` | paket do 1000 poskusov; odgovor `200` z `recorded` = koliko jih je bilo res zapisanih |

Obe poti zahtevata **veljaven žeton otroka** (V3-R04) — nista pod `/admin`
in izvzetje (`ADR-006`) se ni razširilo. Vzorec je isti kot pri arhivu: brez kazalca in brez časa zadnje
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

Neuspeh pri prenosu poskusov ima dve veji (`ADR-020`). Nedosegljiv strežnik
(omrežje, potekel čas, 5xx, 408, 429) obhod konča pred branjem seznama.
**Trajna zavrnitev** paketa (4xx razen 408 in 429, v kodi `PaketZavrnjen`) pa
ne: paket se v istem obhodu pošlje znova **po en poskus**, sprejeti se
označijo, zavrnjeni ostanejo nepreneseni, naslednji paketi se pošljejo in
seznam se prebere. Razbitje je nujno, ker strežnik paket sprejme vsega ali nič,
telefon pa vedno pošlje najstarejše poskuse prve — en sam neveljaven poskus bi
sicer ustavil prenos vseh ocen za njim. Razbija se **samo ob `422`**, odgovoru
na neveljavno vsebino paketa (slab poskus ali neusklajena pogodba med APK in
strežnikom); ob 401, 403 ali 404 ne gre za vsebino, zato poskusi takrat
ostanejo in obhod gre brez ponavljanja naprej. Paket z enim poskusom se ne
ponavlja.

Poskus, ki ga strežnik posamič zavrne s `422`, si `KviziProvider` **zapomni
za čas zagona aplikacije** (množica v `useRef`, ne v bazi) in ga obhodi do
naslednjega zagona ne pošiljajo več. Brez tega bi z N obtičalimi poskusi vsak
obhod poslal 1 + N zahtevkov, za vedno. Ob novem zagonu se poskusijo znova —
ko je vzrok na strežniku odpravljen, gredo gor sami. Isti vzorec kot odmik pri
prenosu slik. Poskusi, zavrnjeni z 401, 403 ali 404, se ne zapomnijo in gredo
znova ob vsakem obhodu, v enem paketu. Meja med začasnim in trajnim je ista
kot pri prenosu slik (`ADR-004`).

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

- **Trajno zavrnjen poskus obtiči brez vidne sledi.** Ne ustavi ne novih
  kvizov ne ostalih ocen (`ADR-020`). Poskus, zavrnjen s `422`, ostane na
  telefonu in se pošlje znova ob naslednjem zagonu aplikacije — ta je lahko
  čez več dni, če je Android ne ubije. Stroški: ob vsakem zagonu enkrat vsak
  paket in še vsak poskus posebej — za N obtičalih največ ceil(N/500) + N
  zahtevkov, en sam obtičal poskus pa en zahtevek —, nato do naslednjega
  zagona samo novi poskusi. Ob neusklajeni pogodbi APK in strežnika je zavrnjen
  vsak poskus: N raste z vsako oceno, val ob zagonu je vse večji in branje
  seznama se medtem zamakne. Poskus, zavrnjen z 401, 403 ali 404, se pošlje
  znova ob vsakem obhodu (en zahtevek na paket). Kviz, ki mu pripada zavrnjen
  poskus, na strežniku ostane nerešen; na telefonu ne čaka, če ima poskus za
  vsako postavko. Trajna zavrnitev nastane ob napaki v kodi, ob obnovitvi
  strežniške baze iz starejše kopije, ob neusklajeni pogodbi APK in strežnika
  ali ob zamenjanem ključu; pravi popravek bi bil svoja zahteva, ne tiho
  brisanje.
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

## Javni dostop (V3-R02)

Strežnik je na `https://school-buddy.duckdns.org`. Odločitve so v `ADR-026` in
`ADR-034`.

```
telefon / brskalnik ─HTTPS 443─▶ usmerjevalnik ─▶ stroj:443 ─▶ caddy ─http─▶ api:8000 ─▶ db
                                                             omrežje spredaj    omrežje default
```

| Servis | Omrežje | Navzven |
|---|---|---|
| `caddy` (`caddy:2.11.4-alpine`) | `spredaj`, stalen naslov `172.30.10.10` | samo TCP 443 |
| `api` | `default` in `spredaj` | nič — brez `ports` |
| `db` | `default` | nič |

- **Certifikat** je Let's Encrypt prek TLS-ALPN-01. HTTP-01 je izklopljen, ker
  vrata 80 drži IIS (Aras Innovator); zato ni preusmeritve z `http://` in v
  brskalnik je treba vtipkati `https://`. HTTP/3 je izklopljen (brez UDP 443).
- **Obnavljanje certifikata je samodejno.** Certifikati in račun ACME so v
  volumnu `server_caddy-podatki`; brez njega bi vsak zagon prosil za nov
  certifikat in zadel omejitev Let's Encrypt.
- **`basic_auth` pred `/admin` je padel v V3-R03** (`ADR-026`, `ADR-035`).
  Admin varuje prijava v aplikaciji sami; `ADMIN_UPORABNIK` in
  `ADMIN_ZGOSTITEV` sta iz `okolje.primer` in Compose odstranjena.
- **Caddy sam odgovori na `/favicon.ico` s 204.** Brez tega ikona zavihka pride
  do `api`, ki zanjo vrne 401 — do V3-R04 zaradi API ključa, odtlej zaradi
  manjkajočega žetona. Z `basic_auth` je to brskalniku pobrisalo geslo za
  `/admin` (Chrome, Edge); odkar gesla v Caddyju ni, ostane le napaka v
  dnevniku ob vsakem odprtju. Admin se odpira z `/admin`.
- **`api` zaupa proxy glavam samo s Caddyjevega naslova**
  (`--proxy-headers --forwarded-allow-ips 172.30.10.10`, v Compose in v
  `Dockerfile`).
- **Znana omejitev: naslov odjemalca ni podatek.** Docker Desktop izvornega
  naslova ne ohrani; Caddy vidi vse odjemalce kot prehod omrežja. Omejevanje
  prijav v V3-R03 gre zato po identifikatorju, ne po naslovu (`ADR-034` A).
- **Ime projekta Compose je `server`** (ime mape) in je predpona volumnov z
  bazo in slikami. `docker-compose.yml` se ne premika; nikoli
  `docker compose down -v`.
- `tests/test_postavitev.py` bere `docker-compose.yml`, `Caddyfile` in
  `Dockerfile` kot besedilo in dokazuje objave vrat, zaupanje proxy glavam,
  TLS-ALPN, **odsotnost** `basic_auth`, ikono zavihka in eno samo spletišče.

### Postavitev na novem stroju

Sklop zunaj repozitorija, po vrsti:

1. **Domena.** DuckDNS, račun lastnika, poddomena `school-buddy`. Zapis `A`
   kaže na javni IP doma. Žeton DuckDNS strežnik ne potrebuje in ni v
   repozitoriju.
2. **Sprememba IP.** IP je statičen, zato posodabljanja ni. Če se spremeni: na
   duckdns.org vpiši nov IP; certifikat ostane veljaven.
3. **Usmerjevalnik.** TCP 443 → LAN naslov stroja (ob postavitvi
   `192.168.0.111`, rezerviran v DHCP). Vrat 80 in 8000 se ne preusmerja.
   Usmerjevalnik podpira NAT loopback, zato domena dela tudi z domačega omrežja.
4. **Požarni zid Windows.** Posebnega pravila ni: dohodni promet spusti pravilo
   „Docker Desktop Backend" na profilu **Zasebno**. Omrežje `Ethernet` mora
   ostati na profilu Zasebno — na Javnem isto pravilo promet blokira in strežnik
   z interneta tiho ni dosegljiv.
5. **`apps/server/.env`** po `okolje.primer`, s `DOMENA`, `ADMIN_UPORABNIK` in
   `ADMIN_ZGOSTITEV`. Zgostitev:
   `docker run --rm -it caddy:2.11.4-alpine caddy hash-password`, v `.env` v
   **enojnih narekovajih**, sicer Compose znake `$` razume kot spremenljivke.
6. **Prvi zagon.** `docker compose -f apps\server\docker-compose.yml up -d --build`.
   Caddy v nekaj sekundah pridobi certifikat (dnevnik:
   `certificate obtained successfully`).
7. **Preverba.** Z mobilnih podatkov `https://<domena>/health` →
   `{"status":"ok"}`; `/admin` vpraša za geslo; z gostitelja `127.0.0.1:8000`
   ne odgovori.
8. **Aplikacija.** `SERVER_BASE_URL` v EAS (okolje `preview`) =
   `https://<domena>`, nova gradnja APK, namestitev **čez** obstoječo
   aplikacijo (odstranitev izbriše slike, ki čakajo na prenos).
9. **Podatki** s starega stroja: kopija in obnova spodaj.

### Varnostna kopija

- `apps/server/varnostna-kopija/kopija.ps1` (PowerShell 7.3+): izpis baze in
  arhiv slik iz vsebnikov (`docker cp`, ne preusmeritev `>`, ki binarni izpis
  pokvari), SHA-256 vsake slike, `stanje.json` in `PREBERI.md`. Cilj
  `C:\varnostne-kopije\school_companion\<datum_ura>`; ohrani 14 celih kopij.
  Števila vrstic in seznam slik primerja pred kopijo in po njej.
- Dnevno opravilo v Razporejevalniku opravil ustvari lastnik:
  `pwsh.exe -NoProfile -File <repo>\apps\server\varnostna-kopija\kopija.ps1`.
- `obnova.ps1 -Mapa <kopija>` obnovi v prazen vsebnik baze in volumna
  `school-obnova*`, primerja revizijo, vrstice po tabelah in SHA-256 vsake
  slike, vrne izhod 0 ali 1 in pobriše samo `school-obnova*`. Ne teče prek
  Compose: drugi projekt iz iste datoteke bi trčil s podomrežjem `spredaj`
  (`ADR-034`, dopolnitev).
- **Preizkušeno 15. 9. 2026** na živem strežniku (38 snovi, 312 vprašanj,
  38 slik): vse se ujema; spremenjeno število vrstic ali spremenjena slika dasta
  izhod 1.
- **Kopija je na istem disku kot strežnik** in okvare diska ne preživi —
  sprejeta cena (`ADR-034` F).
- **Obnova v produkcijo na novem stroju** (postopek **ni bil preizkušen**;
  preizkušen je le `obnova.ps1` v `school-obnova*`):
  1. zaženi strežnik (koraka 5–6), nato `docker stop server-api-1`;
  2. `docker cp <kopija>\solski.dump server-db-1:/tmp/solski.dump` in
     `docker exec server-db-1 pg_restore -U solski -d solski --clean --if-exists /tmp/solski.dump`;
  3. slike razpakiraj prek začasnega vsebnika na volumnu, ker `api` stoji:
     `docker run --rm -v server_slike:/data/images -v <kopija>:/kopija:ro pgvector/pgvector:pg17 tar xzf /kopija/slike.tar.gz -C /data`;
  4. `docker start server-api-1` in primerjaj števila s `PREBERI.md` kopije.

## Zunanje odvisnosti

| Odvisnost | Namen | Kdaj dodana |
|---|---|---|
| Expo SDK 57 (`expo`, `expo-router`, `expo-status-bar`, `expo-splash-screen`) | ogrodje in datotečno usmerjanje | V1-R01 |
| `expo-camera` | zajem fotografije in dovoljenje za kamero | V1-R01 |
| `expo-sqlite` | lokalna baza na telefonu | V1-R01 |
| `expo-file-system` | `documentDirectory/photos/`, premik in brisanje datotek | V1-R01 |
| `expo-image-manipulator` | pomanjšanje na 1600 px in JPEG 0.8 | V1-R01 |
| `expo-crypto` | UUID, generiran na telefonu | V1-R01 |
| `expo-secure-store` | žeton seje; `expo-sqlite` in `AsyncStorage` nista šifrirana in žeton ne sme ležati ob slikah (`ADR-027`) | V3-R04 |
| `react-native`, `react`, `react-dom` | osnova | V1-R01 |
| `react-native-safe-area-context` | odmiki varnega območja; koda ga uvaža neposredno (`useSafeAreaInsets`) | V1-R01 |
| `expo-constants`, `expo-linking`, `react-native-screens`, `react-native-gesture-handler`, `react-native-reanimated`, `react-native-worklets` | `peerDependencies` paketa `expo-router`; koda jih ne uvaža neposredno | V1-R01 |
| razvojno: `jest`, `jest-expo`, `@testing-library/react-native`, `react-test-renderer`, `eslint`, `eslint-config-expo`, `typescript`, `babel-preset-expo`, `@types/node`, `@types/jest`, `@types/react` | preverbe | V1-R01 |

V1-R02 telefonu ni dodala nobene odvisnosti — prenos teče prek
`expo-file-system`, nastavitve pa prek `expo-constants`, oba že iz V1-R01.
Tudi V2-R02 ni dodala nobene, ne telefonu ne strežniku: UUID poskusa pride iz
`expo-crypto`, ki je v projektu od V1-R01.

`expo-secure-store` je nativni modul in zahteva vpis med `plugins` v
`app.json`; v testih se ne uporablja, ker ponudnik prijave dobi shrambo kot
lastnost.

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

### Slike vsebnikov

| Slika | Namen | Kdaj dodana |
|---|---|---|
| `pgvector/pgvector:pg17` | baza | V1-R02 |
| `caddy:2.11.4-alpine` | obratni posredniški strežnik, HTTPS; pripeta različica | V3-R02 |

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

Naslov strežnika pride v aplikacijo **ob gradnji**, iz spremenljivke okolja
`SERVER_BASE_URL` (Expo naloži `.env` sam, `app.config.ts` jo prepiše v
`extra`). Brez nje se worker ne zažene, aplikacija pa deluje kot v V1-R01 in
to tudi pove. Naslov brez sheme `https` šteje enako kot manjkajoč (V3-R02,
`ADR-034` E).

**`SERVER_API_KEY` od V3-R04 ne obstaja več.** Skrivnosti v gradnji ni;
kdo je prijavljen, pove žeton v varni shrambi. Spremenljivko je treba
pobrisati tudi na expo.dev — v APK ne pride, dokler pa je tam, je
skrivnost, ki je nihče ne vzdržuje.

Po isti poti pride tudi **oznaka gradnje** (V1-R06): `app.config.ts` prepiše
`EAS_BUILD_ID` v `extra.buildId`, domača stran pa jo izpiše kot
`1.0.0 · gradnja 317bdcd1`. Brez tega izpisa dveh APK na telefonu ni bilo
mogoče ločiti — verzija je bila pri obeh `1.0.0` in `versionCode` pri obeh 1;
`versionCode` odtlej šteje EAS sam (glej spodaj). Razvojna
gradnja spremenljivke nima in vrstica takrat pove `razvojna gradnja`; prazna
vrednost šteje enako kot odsotna.

#### Gradnja APK

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

Promet do strežnika je **samo `https`** (V3-R02). `SERVER_BASE_URL` v EAS
(okolje `preview`) je `https://school-buddy.duckdns.org`. Do V3-R02 je bil
promet nešifriran in ga je dovolil config plugin
`plugins/with-cleartext-traffic.js` (`ADR-010`, razveljavljen z `ADR-026`);
plugin in njegov test sta izbrisana, `app-config.test.ts` pa dokazuje, da ga
ni ne na disku ne v nastavitvah gradnje.

**Kaj je v zgrajeni APK, zeleni testi ne vidijo.** Dve preverbi, ki gresta
dlje:

```powershell
npx expo config --type introspect      # razreši plugine in izpiše manifest
unzip -o app.apk AndroidManifest.xml   # kaj je v resnici v zgrajeni APK
```

Prva pokaže v nekaj sekundah in brez gradnje, kaj pride v manifest; od V3-R02
`<application>` nima `usesCleartextTraffic`. Njen izpis vsebuje **naslov
strežnika** v čisti obliki; od V3-R04 v njem ni več nobene skrivnosti
(`extra.apiKey` je odpadel). Kadar gre le za manifest, ga poženi z
`EXPO_NO_DOTENV=1` in praznim `SERVER_BASE_URL`.

Druga pove, kaj je v zgrajeni APK. `AndroidManifest.xml` je tam **binarni
AXML**: ime atributa je v nizovnem bazenu in ga `grep -a` najde, vrednost pa ni
vidna kot besedilo. Odsotno ime `usesCleartextTraffic` je zato dokaz, da
dovoljenja ni.

Zadnja beseda ostane preizkus na telefonu, z mobilnimi podatki zunaj doma:
slika mora priti do stanja „Preneseno".

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

`.env` prebere **Docker Compose**, da razreši `${DATABASE_URL}` in poda
vrednosti vsebniku; strežnik sam `.env` ne bere, ker bi bil `env_file`
relativen na trenutno delovno mapo. Brez `DOMENA` se Compose ne zažene
(glej „Javni dostop"). `BIND_ADDRESS` od V3-R02 ne obstaja več,
`ADMIN_UPORABNIK` in `ADMIN_ZGOSTITEV` od V3-R03 ne, `API_KEY` pa od
V3-R04 ne.

**Po prvem zagonu `/admin` ni dosegljiv, dokler ni nastavljeno geslo** —
migracija ustvari uporabnika brez njega (`ADR-035` G):

```powershell
docker compose -f apps\server\docker-compose.yml exec api `
  python -m app.ukazi nastavi-geslo dejan.ambrus@gmail.com
```

Isti ukaz nastavi geslo otroku (identifikator `masa`). **Od V3-R04 ni več
izbiren:** brez njega se otrok ne more prijaviti v aplikacijo in prenos ne
teče. Najkrajše otrokovo geslo je 8 znakov, starševo 12 (`ADR-036` E).
Piškotek seje ima zastavico `Secure`; brskalniki jo sprejmejo tudi na
`http://localhost`, zato razvojni zagon mimo Caddyja deluje.

`OPENAI_API_KEY` je ključ do **tuje** storitve in ostaja. Brez njega
strežnik **normalno steče** in slike sprejema, ne teče pa obdelava. `OPENAI_MODEL` (privzeto
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
| Samodejni vpis + takojšen zaklep seje (Sysinternals Autologon, geslo kot LSA skrivnost) | ohrani preverjeno postavitev (Docker Desktop, Caddy na 443); malo dela | geslo mora biti shranjeno na stroju |
| Nadzorno opravilo, ki na ~15 min preveri `/health` in po potrebi požene `docker compose up -d` | pokrije tudi sesut Docker in zamrznjen WSL; ne zahteva gesla | sam po sebi ne reši odsotne seje |
| Docker Engine v WSL distribuciji namesto Docker Desktopa, zagnan kot opravilo ob zagonu | ne potrebuje prijave; odpravi tudi pripetost na staro 4.26.1 in morda omejitev naslova odjemalca (`ADR-034` A) | **WSL2 objavlja vrata prek NAT na `localhost`**, zato bi vrata 443 do Caddyja morala skozi `portproxy` — pravilo, ki ga je lahko narobe nastaviti in ki ga nihče ne testira |
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
