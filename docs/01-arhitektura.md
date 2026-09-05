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
| `apps/mobile` | Kamera, izbira predmeta, lokalna baza, zgodovina, upload worker | `apps/mobile/` (od V1-R01; upload worker od V1-R02) |
| `apps/server` | Prevzem slik (`POST /materials`), preverba ključa, shramba, operaterska stran `/admin`, vision obdelava v ozadju | `apps/server/` (od V1-R02; `/admin` od V1-R04; obdelava od V1-R03) |

Ločena mapi namenoma ne delita orodij za monorepo (npr. Turborepo) — gre za
dva jezika (TypeScript / Python) brez skupne kode, zato vsaka živi s svojim
običajnim orodjem (`npm`/`package.json` v `apps/mobile`,
`pip`/`pyproject.toml` v `apps/server`).

### Notranja delitev `apps/mobile`

| Mapa | Odgovornost |
|---|---|
| `app/` | zasloni; usmerjanje je datotečno (`expo-router`) |
| `src/constants/` | seznam desetih predmetov (`{ value, label }`) |
| `src/config/` | naslov strežnika in API ključ, kot sta prišla ob gradnji |
| `src/db/` | verzionirana shema (migracije) in poizvedbe nad tabelo `materials` |
| `src/sync/` | prenos na strežnik: en prenos, čakalna vrsta, priklop na življenjski cikel. **Edina mapa v aplikaciji z omrežnim klicem.** |
| `src/photos/` | stiskanje slike in zapis v `documentDirectory/photos/` |
| `src/materials/` | shranjevanje posnetka: najprej datoteka, nato vrstica |
| `src/capture/` | stanje zaslona s kamero (kamera ↔ predogled) |
| `src/ui/` | skupni gradniki in barve |
| `src/types.ts` | tip `Material` (ena vrstica tabele `materials`) |
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
| `app/routers/admin.py` | operaterska stran |
| `app/db.py` | motor, seje in `MaterialsRepository` — edina pot do baze |
| `app/models.py` | tabeli `materials` in `questions` |
| `app/storage.py` | zapis, meja mape in brisanje slik na disku |
| `app/vision.py` | **edini modul, ki uvaža `openai`**: prompt, shema odgovora, klic |
| `app/obdelava.py` | kaj se zgodi z enim zapisom: prevzem, klic, zapis izida. Sinhron |
| `app/worker.py` | časovnik: obhodi v presledkih, zagon in ustavitev. Brez poslovne logike |
| `app/settings.py` | nastavitve iz okolja |
| `app/subjects.py` | predmeti in slovenske oznake stanj |

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

Indeks `materials_subject_taken_at (subject, taken_at DESC)` — zgodovina bere
po predmetu in po času navzdol. Čakalna vrsta bere obratno (`taken_at ASC`),
da najstarejši posnetek ne čaka najdlje.

Meja med `pending` in `failed` ni število poskusov, ampak ali se stanje more
spremeniti samo od sebe: 4xx razen 408 in 429 je sodba o vsebini zahteve in
gre v `failed`, omrežna napaka in 5xx ostaneta `pending`. Iz `failed` zapis
vrne samo gumb „Poskusi znova". Glej `docs/odlocitve/ADR-004`.

#### Migracije lokalne sheme

Shema je verzionirana prek `PRAGMA user_version` (`src/db/migrations.ts`);
trenutna verzija je **1**. `CREATE TABLE IF NOT EXISTS` obstoječi tabeli
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
| `material_id` | `VARCHAR(36) NOT NULL` | tuji ključ na `materials.id`, `ON DELETE CASCADE`, indeksiran |
| `position` | `INTEGER NOT NULL` | zaporedje znotraj materiala, od 1 |
| `question` | `TEXT NOT NULL` | besedilo vprašanja |
| `answer` | `TEXT NOT NULL` | pričakovan odgovor |

Vprašanja imajo svojo tabelo in ne polja JSON, ker bo `V1-R05` ocene težavnosti
vezala na `question_id`. **Vprašanje ni trajno:** ponovna obdelava zavrže
prejšnji izid skupaj z vsemi vprašanji materiala (`docs/odlocitve/ADR-009`).

Kaskada je nastavljena **dvakrat**: `ondelete="CASCADE"` v shemi in
`cascade="all, delete-orphan"` v ORM. Prvo velja na Postgresu, drugo tudi na
SQLite, ki tujih ključev privzeto ne uveljavlja — brez druge bi testi
dokazovali manj kot produkcija.

`id` je `VARCHAR` in ne `UUID`, čas pa `DateTime(timezone=True)`, ker mora ista
shema stati nad Postgresom (produkcija) in nad SQLite (testi).

Migracije vodi **Alembic** (`apps/server/alembic/`). Prva migracija ustvari
razširitev `vector` — vektorskih stolpcev še ni, iskanje po pomenu je V2.
`alembic/env.py` povezavo bere iz `DATABASE_URL`, vendar **samo, kadar url ni
že izrecno nastavljen**; obratna prednost bi pomenila, da se testi migracije
povežejo na živo bazo.

Slike živijo v `/data/images/<id>.jpg`. Zapis gre najprej v
`/data/images/.tmp/` pod enoličnim imenom in se na končno mesto premakne
atomarno; vrstica v bazi nastane šele za datoteko. Prekinjen prenos zato ne
pusti polovične slike na mestu, kjer jo bo V1-R03 iskal kot celo.

## Prenos telefon → strežnik

`POST /materials` sprejme multipart z `id`, `subject`, `taken_at` in `file`.
Prvi prenos vrne **201**, ponoven prenos istega `id` **200** in polje
`created: false` — telefon oboje šteje za uspeh. Obstoječi zapis se ne prepiše
in slika se ne povozi.

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
| `/admin/materials/{id}/delete` | GET | potrditvena stran |
| `/admin/materials/{id}/delete` | POST | izbriše in preusmeri (303) |
| `/admin/materials/{id}/reprocess` | POST | vrne v vrsto in preusmeri (303) |

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
datoteka brez vrstice je nevidna sirota, ki stane samo prostor. Brisanje je
nepovratno — zapis, ki je na telefonu `synced`, upload worker nikoli več ne
pošlje.

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

Naslov strežnika in API ključ prideta v aplikacijo **ob gradnji**, iz
spremenljivk okolja `SERVER_BASE_URL` in `SERVER_API_KEY` (Expo naloži `.env`
sam, `app.config.ts` ju prepiše v `extra`). Brez njiju se worker ne zažene,
aplikacija pa deluje kot v V1-R01 in to tudi pove. Ključ s tem konča vgrajen v
APK — to je zavestno, ker gre za en družinski ključ na omrežju, ki je že
zaprto s Tailscale; cena je, da zamenjava ključa zahteva novo gradnjo.

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
