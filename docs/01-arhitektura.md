# Arhitektura — trenutno stanje

> Kako je **zdaj** (`CLAUDE.md` §0); razlogi so v ADR-jih, pasti v `02-izkusnje.md`,
> postopki v `03-obratovanje.md`. Model ga posodobi ob vsaki spremembi stanja.

## Stack

| Plast | Tehnologija |
|---|---|
| Mobilna aplikacija | Expo SDK 57 (React Native, TypeScript), `expo-router`; APK prek EAS Build |
| Lokalna baza (telefon) | SQLite (`expo-sqlite`) — čakalna vrsta za delo brez povezave |
| Strežnik | FastAPI (Python 3.12), Jinja2, SQLAlchemy 2.0, Alembic |
| Baza (strežnik) | PostgreSQL 17 + pgvector (vektorskih stolpcev še ni) |
| Povezljivost | HTTPS na `school-buddy.duckdns.org`, Caddy pred `api` (`ADR-026`) |
| Model | OpenAI prek paketa `openai`: `gpt-4.1` za snov in urnik (`ADR-008`), svoj model za preizkuse |
| Obdelava v ozadju | `asyncio` opravilo v procesu `api`, brez Celery/Redis |
| Orkestracija | Docker Compose: `caddy` + `api` + `db` |

Razlogi za izbire: `ADR-077` A. Mapi `apps/mobile` in `apps/server` nimata
skupne kode in ne orodja za monorepo; vsaka ima svoje (`npm` / `pip`).

### Notranja delitev `apps/mobile`

| Mapa | Odgovornost |
|---|---|
| `app/` | zasloni, datotečno usmerjanje; `povezi.tsx` (QR), `prijava.tsx` (odjava), `kvizi/` |
| `src/constants/`, `src/config/` | deset predmetov, štiri ocene (`ocene.ts`); kar pride ob gradnji: naslov strežnika (samo `https`), oznaka gradnje |
| `src/db/` | migracije in poizvedbe (`materials`, `kvizi.ts`) za vmesnikom `MaterialsDatabase`; `expo-sqlite` samo v `open.ts` in korenski postavitvi |
| `src/sync/` | prenos, vrsta, brisanje arhiviranih, kvizi (`kvizi.ts`, `use-kvizi.tsx`), klic s časovno mejo (`http.ts`), prijava. **Edina mapa z omrežnim klicem** |
| `src/photos/`, `src/materials/`, `src/capture/` | stiskanje in zapis slike; shranjevanje (najprej datoteka, nato vrstica); stanje zaslona s kamero |
| `src/povezava/` | razčlenjevanje `school-companion://povezi?z=…`; brez omrežja |
| `src/ui/`, `src/types.ts`, `__tests__/` | gradniki in barve; tipi; testi |

React Compiler je izklopljen (`ADR-071` A1); `plugins/` ni. Zaslon z vsebino ob
spodnjem robu prišteje `useSafeAreaInsets().bottom`.

### Notranja delitev `apps/server`

| Datoteka | Odgovornost |
|---|---|
| `app/main.py` | tovarna aplikacije, življenjski cikel, `USMERJEVALNIKI_ZA_ODOBRENE`, `JAVNE_DATOTEKE` |
| `app/security.py` | `ZetonMiddleware` (telefon, `Authorization: Bearer`), `SejaMiddleware` (seja in CSRF pod `/admin`) |
| `app/dependencies.py` | odvisnosti iz `app.state`; `daj_druzino`, `daj_otroka` (iz seje), `zahtevaj_odobreno_druzino` |
| `app/db.py` | **edina pot do baze**: `MaterialsRepository`, `KviziRepository`, `StatistikaRepository` (bere), `ClaniRepository`, `ScheduleRepository`, `MeniRepository`, `PreizkusiRepository` — z obvezno družino — ter `DruzineRepository` in `PrijavaRepository` brez nje |
| `app/models.py`, `schemas.py`, `storage.py` | tabele; oblike odgovorov; zapis, meja mape družine in brisanje slik (podmapa `urniki/`) |
| `app/vision.py` | **edini uvoznik `openai`**: prompta, sheme, klic; snov in urnik nad `_izvedi_klic`, preizkus s svojim ključem in modelom; vsi nad `_poslji` |
| `app/obdelava.py`, `app/worker.py` | en zapis (prevzem, klic, izid; sinhrono) / časovnik obhodov brez poslovne logike |
| `app/routers/` | `materials`, `resevanje` (telefon); `vstop` (prijava, odjava, `/auth/*`, registracija); `admin` (predmeti, snov, arhiv, prepisi); `kvizi`, `statistika`, `dnevi`, `urnik`, `clani`, `sistem`, `racun`, `preizkusi`; `javno` (`GET /`, edini HTML zunaj `/admin`) |
| Pravila **brez FastAPI in brez baze** | `prijava.py` (argon2id, žetoni, CSRF, omejevanje, `next`, `Vrata`, `normaliziraj_identifikator`), `clani.py`, `sistem.py`, `google.py` (**edini, ki govori z Googlom**), `registracija.py`, `povezava.py` (**edini uvoznik `segno`**), `urnik.py`, `otroci.py`, `danes.py`, `prepisi.py`, `preizkus.py` (tudi brez `openai`), `statistika.py`, `meni.py`, `tedni.py`, `predstavitev.py` |
| Skupni izvlečki | `casi.py` (pas, meje dni, šolsko leto, `utc`, `trajanje`), `strani.py` (izris, strani 400/403/404/409, obdelovalec konteksta), `besedilo.py` (oblike števil), `subjects.py` (predmeti, barve, oznake, `OZNAKE_OCEN`) |
| `app/ukazi.py`, `settings.py`, `templates/`, `static/` | `python -m app.ukazi nastavi-geslo <identifikator>` (`getpass`); nastavitve iz okolja; predloge; `admin/slog.css`, `javno/slog.css`, `pisave/`, `vendor/` |
| `Caddyfile`, `varnostna-kopija/` | Caddy (domena, TLS-ALPN, ikona zavihka); `kopija.ps1`, `obnova.ps1` |

**Kar potrebujeta oba usmerjevalnika, ni last nobenega** in ima javno ime brez
podčrtaja (`ADR-074` A). **Poslovna logika ne ve za `asyncio`**; menjava modela je
sprememba `vision.py` in ene spremenljivke okolja (`ADR-075` A).

## Podatkovni model

### Telefon — SQLite (`school-companion.db`), shema verzija 5

| Tabela | Stolpci | Opomba |
|---|---|---|
| `materials` | `id` (UUID s telefona), `subject`, `taken_at` (posnetek, UTC), `file_uri`, `sync_status` (`pending`/`synced`/`failed`), `sync_attempts`, `last_attempt_at`, `sync_error`, `user_id` | indeks `(subject, taken_at DESC)`; vrsta bere `ASC` |
| `quizzes` | `id`, `name`, `created_at`, `user_id` | vsebina zamrznjena |
| `quiz_items` | `id`, `quiz_id`, `position`, `question_text`, `answer_text`, `answered_on_server` | indeks `(quiz_id, position)` |
| `attempts` | `id`, `quiz_id`, `quiz_item_id` `UNIQUE`, `mode`, `rating`, `shown_at`, `revealed_at`, `answered_at`, `uploaded_at`, `user_id` | **brez FK** na `quizzes` |
| `naprava` | `id = 1` (`CHECK`), `odjava_ob` | sled nedokončane odjave (`ADR-037`) |

- **Migracije** (`PRAGMA user_version`): 1 `materials`, 2 kvizi, 3 `user_id` na
  `materials`/`attempts`, 4 `naprava`, 5 `user_id` na `quizzes`. Sveža namestitev
  gre skozi isto zaporedje; stare se ne popravljajo; `CREATE_*_SQL` sta
  zamrznjeni, testi tečejo nad kopijami starih shem (`ADR-071` B).
- **`failed`** samo ob 4xx razen 401, 408, 429; ostalo ostane `pending`; iz
  `failed` vrne samo „Poskusi znova" (`ADR-004`).
- **Lastnik:** pogoj je povsod `user_id IS ?` (vrsta, števci, Zgodovina,
  `retryFailed`, nepreneseni poskusi, `cakajociKvizi`, `najdiKviz`,
  `postavkeKviza` z dvema pogojema); `NULL` posvoji vsaka razrešena seja
  (`posvojiBrezLastnika`), `shraniKviz` samo iz `NULL` (`ADR-071` C).
- **Stanje kviza se izpelje** (lokalni poskus ali `answered_on_server = 1`).
  Neprenesen poskus se ne pobriše nikoli; `pobrisiKvizeRazen` ne pobriše kviza s
  tujim neprenesenim poskusom (`ADR-036` C). Žeton ob postavljeni
  `naprava.odjava_ob` se zavrže; prijava oznako počisti.

### Strežnik — PostgreSQL

| Tabela (`id` `VARCHAR(36)`, časi `TIMESTAMPTZ`, ista shema nad SQLite) | Ključni stolpci | Opomba |
|---|---|---|
| `families` | `id`, `name` (ni enoličen), `created_at`, `is_active`, `status` (`pending`/`approved`/`rejected`), `consent_at`, `decided_at` | `id` je tudi ime mape slik |
| `users` | `id`, `family_id`, `role` (`parent`/`child`), `display_name`, `is_system_owner`, `is_active`, `created_at` | oseba brez gesla |
| `credentials` | `user_id`, `kind` (`password`/`google`), `identifier` **UNIQUE** čez namestitev, `secret_hash`, `label`, časi | e-naslov ali Googlov `sub`; `label` samo za izris; **otrok poverilnice nima** |
| `sessions` | `user_id`, `token_hash` **UNIQUE** (SHA-256), `csrf_token`, `created_at`, `expires_at`, `last_used_at`, `device_label` | `device_label` se piše, ne bere |
| `login_attempts` | `identifier`, `ip_address`, `created_at` | **brez družine**; tudi oznaki `POVEZAVA-TELEFONA`, `REGISTRACIJA` |
| `link_tokens` | `family_id`, `child_id`, `token_hash` **UNIQUE**, `created_at`, `expires_at` | ≤ 10 min, ob unovčenju izgine |
| `materials` | `id` (UUID s telefona), `family_id`, `child_id`, `subject`, `taken_at`, `image_path`, `status`, `received_at`, `archived_at`, `device_deleted_at`, `readable`, `transcript`, `summary`, `prompt`, `raw_response`, `model`, `input_tokens`, `output_tokens`, `error` | `status`: `new` → `processing` → `ready` \| `failed` |
| `questions` | `family_id`, `material_id` (`SET NULL`), `subject`, `material_taken_at`, `position`, `question`, `answer`, `retired_at` | `position` znotraj serije |
| `quizzes` | `family_id`, `child_id` (naslovljenec), `name`, `subject` (`NULL` = več predmetov), `created_at`, `canceled_at`, `solved_at` | brez `status` |
| `quiz_items` | `quiz_id` (**`CASCADE`**), `question_id` (`SET NULL`), `position` čez kviz, `question_text`, `answer_text` | družina in otrok iz kviza |
| `question_attempts` | `id` (UUID s telefona), `family_id`, `child_id` (kdo je odgovoril), `quiz_item_id` **UNIQUE** brez `ondelete`, `mode`, `rating`, `shown_at`, `revealed_at`, `answered_at`, `received_at` | poskus je dogodek |
| `schedules` / `schedule_entries` | `family_id`, `child_id`, `confirmed_at`, `replaced_at`, `image_path` / `schedule_id`, `weekday` 0–4, `subject`, `skip_photo` | vnos enoličen po `schedule_id + weekday + subject` |
| `preizkusi` | `family_id`, `child_id`, `subject`, `title`, `test_md`, `solutions_md`, `source_md`, `model`, `saved_at`, `saved_by`, `base_id`, `given_at`, `solved_at` | brez `DELETE`; edini `UPDATE` je `zapisi_predajo` |

- **Izolacija je lastnost kode** (`ADR-025`): družina v konstruktorju brez
  privzetka (prazen niz je `ValueError`), pogoj družine v vsaki poizvedbi in
  `UPDATE`, brez `Session.get` nad podatki. Družino in otroka pove seja, nikoli
  telo; otrok je argument poizvedbe. `DruzineRepository` člane le šteje
  (`ADR-044` E). `tests/test_tesnjenje.py` pošlje tuje identifikatorje na vsako
  pot in metodo.
- **`family_id NOT NULL`** imajo `materials`, `questions`, `quizzes`,
  `question_attempts`, `schedules`, `preizkusi`; `quiz_items` in
  `schedule_entries` ga izpeljeta (`ADR-029` C); **`child_id`** imajo
  `materials`, `quizzes`, `question_attempts`, `schedules`, `preizkusi`, ne pa
  `questions` (`ADR-039` G).
- **Nič se ne briše, upokoji se** (`ADR-012`, `ADR-015`): vprašanje preživi
  material (`material_id` → `NULL`, tudi prek ORM na SQLite); ponovna obdelava
  staro serijo upokoji. Zveze `Material`: `vsa_vprasanja` (edina pisljiva),
  `veljavna_vprasanja`, `upokojena_vprasanja` (`viewonly`) (`ADR-072` C).
- **Osi namesto stanj:** `archived_at`, `retired_at`, `canceled_at`/`solved_at`
  (preklic ima pri prikazu prednost; `solved_at` postavi strežnik v transakciji
  zadnjega poskusa), `replaced_at` (en veljaven urnik na otroka, ena pot pisanja
  `ScheduleRepository.potrdi`, `ADR-041` C), `given_at`/`solved_at`.
- **`quiz_items → quizzes` je edina kaskada**; `QuizItem.question` je
  enosmerna; postavka zamrzne `question_id` in besedilo (`ADR-016` E).
- **Slike:** `/data/images/<family_id>/<id>.jpg`, urniki v `…/urniki/`; meja je
  mapa družine (`storage.mapa_druzine`, kanoničen UUID); zapis prek `.tmp/` in
  atomarnega premika, vrstica za datoteko; brisanje vrstica, nato datoteka.
- **Alembic:** `env.py` bere `DATABASE_URL`, samo kadar url ni nastavljen;
  `fileConfig(..., disable_existing_loggers=False)`.

| Migracija (razlogi `ADR-072` F) | Kaj | `downgrade` |
|---|---|---|
| `0001`, `0002` | `materials` in razširitev `vector`; stolpci obdelave in `questions` | spusti tabeli in stolpce |
| `0003_arhiv` | arhiv; FK `questions.material_id` → `SET NULL` | izbriše vprašanja brez materiala |
| `0004`, `0005`, `0006` | `retired_at`; kvizi; `solved_at` in poskusi | izgubi upokojitev; kvize; poskuse in rešenost |
| `0007_druzine` | družina Cvek (stalen `id`), `family_id`, slike v mapo družine; `IMAGES_DIR` obvezen pri neprazni bazi | ne pri več družinah |
| `0008_uporabniki` | identiteta; starš (lastnik sistema) in otrok Cvek **brez gesla** | izgubi uporabnike, gesla, seje |
| `0009_otrok_na_zapisu` | `child_id`; ustavi se, če ima družina 0 ali > 1 otroka | izgubi pripis otroka |
| `0010`, `0011`, `0012` | urnik; `families.is_active`; `credentials.label` | izgubi urnike; ugasnitev; prikazni e-naslov |
| `0013`, `0014` | `preizkusi`; `link_tokens` in izbris geselnih poverilnic otrok | izgubi preizkuse; poverilnic ne vrne |
| `0015`, `0016` | odobritev družine (obstoječe `approved`); predaja preizkusa | ne, dokler obstaja neodobrena; izgubi predajo |

## Pogodbe telefon ↔ strežnik

Vse zahtevajo žeton otroka (`ZetonMiddleware`, `ADR-036`). Izvzeti: `GET
/health`, `POST /auth/link`, `POST /auth/login`, Googlovi poti brez seje, točna
pot `/` in predpona `/admin` (nikoli `/administration`); odjava telefona ni.
Popis pribija `tests/test_security.py`, mejo `TestPrijavaOstajaZahtevanaDrugod`.

| Pot | Kaj |
|---|---|
| `POST /materials` | multipart `id`, `subject`, `taken_at`, `file`. `201` prvič; `200` + `created: false` ponovno (nič se ne prepiše); `410` arhiviran (telefon zapis zbriše); `409` `id` v drugi družini; `401` (ostane `pending`) |
| `GET /materials/pending-deletion`, `POST /materials/deleted-on-device` | celoten seznam arhiviranega, česar naprava še ni potrdila; potrditev (ponovljena ne premakne nič) |
| `GET /quizzes/pending` | vsi nepreklicani nerešeni kvizi prijavljenega otroka, najstarejši prvi; besedilo iz `quiz_items`; `answered` |
| `POST /quiz-attempts` | ≤ 1000 poskusov, **vse ali nič** (`422`); ponovljen paket in drugi poskus postavke: `200`, `recorded: 0`; poskus za tuj kviz se ne zapiše |
| `POST /auth/link`, `/auth/login`, `/auth/logout` | `{token}` iz QR → žeton seje, `user_id`, ime; škrbina za stari APK (vedno `401`); izbris seje naprave |

Časi v odgovorih nosijo pas UTC (`casi.utc`). Na telefonu:

- **Prenos** prek `File.upload`, meja 60 s, zaporedno, samo v ospredju: ob
  zagonu, po *Shrani* (brez čakanja), vsakih 30 s, po neuspehu do 5 min.
- **Kvizi** (`KviziProvider`): ob zagonu, vrnitvi v ospredje, vsakih 5 min in po
  zadnji oceni; najprej poskusi gor, nato seznam; kvizi, ki jih ni na seznamu, se
  pobrišejo razen odprtega. Ob `422` po en poskus, posamič zavrnjen počaka na
  naslednji zagon; 401/403/404 poskuse pusti (`ADR-020`). Nerazberljiv seznam vrže.
- **Brisanje arhiviranih** vsakih 5 min: vrstica, datoteka, potrditev. **`401`**
  je `Izid.prijavaPotekla`: „Prijava je potekla. Prosi starša za novo kodo."
  Odjave ob `401` ni; odjava je najprej lokalna (`ADR-037`).
- **Povezava s QR** (`app/povezi.tsx`): unovči → shrani → posvoji → počisti
  oznako odjave → odjavi prejšnjo sejo. Ponovitev kode samo po nedosegljivem
  strežniku.

## Vstop in varnost

Poti: `GET/POST /admin/login` (piškotek `csrf_prijava`, prijava na `next`),
`POST /admin/logout`, `GET/POST /admin/register` (brez seje, CSRF preveri sama),
`POST /auth/google/login` in `GET /auth/google/callback` (brez seje; en povratni
klic za prijavo, povezovanje in registracijo).

- **`SejaMiddleware`** zahteva sejo pod `/admin` razen `POTI_BREZ_SEJE`
  (`/admin/login`, `/admin/register`); sicer `303` na prijavo z `?next=` (samo
  relativna pot pod `/admin`, `urlencode`, samo varne metode).
- **Žeton seje** `secrets.token_urlsafe(32)`, v bazi SHA-256; piškotek `seja`
  `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, 30 dni, drseči (osvežitev
  največ na uro). Primerjava skozi `prijava.zetona_se_ujemata` (`ADR-047`).
- **CSRF** je v vrstici seje, v predloge pride prek obdelovalca konteksta, velja
  za vse metode razen `GET`/`HEAD`; plast bere telo `x-www-form-urlencoded`
  ≤ 1 MiB (`NAJVECJE_TELO_OBRAZCA`). `POST /admin/schedule/proposal` ga preveri
  sama (`poti_s_svojim_csrf`, enočlanski, `ADR-043`).
- **Omejevanje** po identifikatorju: po 5 neuspehih v 15 min 2 s pred preverbo;
  uspeh števce pobriše (`ADR-034` A). Povezava telefona ima isto upočasnitev,
  skupno za namestitev (`POVEZAVA-TELEFONA`), uspeh je ne pobriše. **Isto sporočilo** za vsako neuspelo prijavo razen
  otrokovega računa (`ADR-035` F).
- **Seja pade** ob poteku, deaktiviranem računu, ugasnjeni družini — preverjeno
  ob vsaki uporabi, skupaj z **vrati vloge** (`prijava.Vrata`). Potekle seje in
  stari poskusi se čistijo ob vsakem poskusu prijave.
- **Povezovalni žeton** (`ADR-061`): 10 min, enkrat, pogojni `DELETE` s sejo v
  isti transakciji; nov prejšnjega izbriše; vsak neveljaven da isti `401`.
  „Prekliči prijave" in deaktivacija izbrišeta seje in kodo.
- **`/admin/system`**: `zahtevaj_lastnika_sistema` na `APIRouter`, sicer `404`;
  `405` tam postane `404` brez `Allow` (`sistem.je_skrita_pot`), drugod ostane
  (`ADR-045`).
- **Odobritev** (`ADR-057`, `ADR-062`): neodobrena seja dobi `303` na
  `/admin/racun`; odprti so `/admin/racun` (`GET`), izbris, odjava, prijava in
  registracija. **Nov usmerjevalnik pod `/admin` sodi v
  `USMERJEVALNIKI_ZA_ODOBRENE`.** Prehodi `pending → approved|rejected`,
  `rejected → approved` (pogojni `UPDATE`); ročno odprta družina je `approved`.
- **Registracija:** neznan `sub` dobi podpisan piškotek `registracija` (ključ ob
  zagonu v `app.state`) in nič se ne zapiše; oddan obrazec ustvari družino
  `pending`, starša, poverilnico `google` in sejo. Meji 20 čakajočih in 10 v 24 h.
- **Google** (`ADR-046`, `ADR-073` E): `identifier` je `sub`; piškotek
  `google_state` se pobriše ob vsakem izidu. Brez `GOOGLE_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET` ali `DOMENA` je pet Googlovih poti `404` (tudi
  `/admin/racun`, razen za neodobreno družino) in registracije ni.
- **Člani** (`ADR-038`): `404` tuj ali neobstoječ, `403` ni tvoje, `409` že tako;
  ponastavitev in deaktivacija izbrišeta seje člana; lastnik sistema se ne
  deaktivira; identifikator se normalizira; enoličnost razsodi baza.
- **Ugasnjena družina** (`ADR-044` A): seje članov padejo, podatki ostanejo;
  obhod obdelave jo preskoči, `obnovi_obticale` ne.

## Obdelava z modelom

Zanka (`asyncio`, `lifespan`) vsakih `WORKER_INTERVAL_SECONDS` (30) pobere `new`
po aktivnih družinah, najstarejše prve, zaporedno, v niti; prevzem je pogojni
`UPDATE`, prevzem in izid sta ločeni transakciji.

| Iz | V | Kdaj |
|---|---|---|
| `new` | `processing` | prevzem v obhodu |
| `processing` | `ready` | klic uspel (tudi `readable=false`, brez prepisa in vprašanj) |
| `processing` | `failed` | napaka klica, neveljaven odgovor, ni datoteke (brez klica) |
| `processing` | `new` | ob zagonu (obtičal) ali če izida ni kam zapisati |
| `ready` \| `failed` \| `new` | `new` | „Pošlji v obdelavo": prepis in sled se zavržeta, vprašanja upokojijo takoj |

Slika gre kot base64 `data:` URL; odgovor po `json_schema` `strict` in skozi
Pydantic (5–10 vprašanj); revizijska sled ob vsakem izidu. **Brez
`OPENAI_API_KEY` zanka ne teče** (`ADR-009`). Urnik pokliče model sinhrono
(`ADR-041` B). Preizkus: Chat Completions, `strict`, `reasoning_effort=medium`,
`max_completion_tokens=20000`, meja `OPENAI_TIMEOUT_SECONDS`, brez ponovitev,
`OPENAI_API_KEY_PREIZKUSI` in `OPENAI_MODEL_PREIZKUSI` (`gpt-5.6-luna`); ena
vrstica dnevnika na klic brez vsebine.

## Operaterska stran `/admin`

Strežniško izrisan HTML brez gradnje frontenda; poti angleške, besedilo slovensko.

- **Skripta je izjema** (`ADR-024`): `snov.html`, `prepisi.html`,
  `preizkus.html`, `preizkus-ogled.html` (`ADR-054`, `ADR-055`; skupna
  `_preizkus-izris.html`, `_preizkus-slog.html`); `TestBrezJavaScripta` izvzame
  natanko te. Bloka ogrodja: `glava`, `razred_telesa`.
- **Videz** (`ADR-056`, `ADR-060`): en slog z `@media screen` (tema, prelom
  860 px) in `@media print` (dobesedno pred V5-R01, varuje
  `tests/podatki/slog_pred_v5_r01.css`); pisava z lastnega strežnika; šest
  `JAVNE_DATOTEKE` brez seje (točne poti, `GET`/`HEAD`).
- **Meni** na vsaki strani odobrene družine (`app/meni.py`); števci so ena
  poizvedba (`MeniRepository.stevci`); lastnik vidi število čakajočih družin.
- **Napake** pod `/admin` izriše prestreznik v `create_app`, drugod ostanejo JSON.
  Pot predmeta je `subjects/{koda:path}`. Predloge v `app/templates/` (pot iz
  `__file__`, `package-data`), izrisovalnik v `app.state.predloge`.
- **Sklanja usmerjevalnik** (`stevilo_z_besedo`, ostanek pri 100, `ADR-074` D).
  **Čas** v pasu `Europe/Ljubljana`; naiven čas iz SQLite je UTC; grupiranje po
  dnevu in mesecu v Pythonu (`ADR-074` C).

| Predpona | Poti |
|---|---|
| `/admin` | predmeti s števci in kartico „danes"; družina brez otroka dobi tri korake |
| `/admin/subjects/{koda}` | slike po tednih; `?vse=1`, `?teden=`, `?dan=`; pri `MAT` „Kreiraj test" in „Shranjeni testi (N)" |
| `/admin/materials/{id}` | podrobnosti, `/image`; `archive`, `purge-image`, `delete` (z vmesnima stranema), `reprocess`, `subject` |
| `/admin/archive`, `/admin/transcripts` | arhivirane; prepisi izbranih (`POST`, nič ne shrani; `GET` 303) |
| `/admin/quizzes` | seznam po mesecih (`?stanje=`, `?otrok=`), objava; `/new` (`?izbor=`), `/preview`, `/{id}`, `/{id}/print`, `/{id}/cancel` |
| `/admin/statistics`, `/admin/days` | pregled in `/subjects/{koda}` (`?leto=`, `?otrok=`); en otrok (`?dan=`, `?obdobje=`, `?otrok=`) |
| `/admin/schedule` | mreža, potrditev, `/proposal`, `/image/{slika_id}` |
| `/admin/assessments` | pregled (`?predmet=`, `?stanje=`), shrani (JSON); `/compose`, `/generate` (JSON), `/{id}`, `/{id}/compose`, `/{id}/handover` |
| `/admin/family` | člani (`?dodaj=`); `children`, `parents`; `members/{id}/` `password`, `link` (QR, `no-store`), `revoke`, `deactivate`, `activate` |
| `/admin/system` | družine; `families` (`GET` 303), `families/{id}` z `deactivate`, `activate`, `approve`, `reject`, `parents/{user_id}/…` |
| `/admin/racun`, `/admin/static/…` | načini prijave ali stanje zahtevka, `izbrisi`, `google`, `google/odstrani`; statične datoteke |

`GET /` je predstavitvena stran (`ADR-059`, `ADR-063`): za vsakogar ista, brez
seje, baze, piškotka, skripte in tujih virov; registracija je povezava na
`/admin/register`. **Kdor spremeni funkcijo, ki jo stran omenja, popravi tudi
stran**; del oznak varuje `tests/test_predstavitev.py`.

## Pravila pogledov (razlogi: `ADR-076`)

- **Sestavljalnik** (`ADR-016`, `ADR-017`): *Nova snov* (obkljukana še ne v kvizu
  tega otroka), *Ročna izbira* (nič), *Kaj smo se danes učili* (današnja čez
  predmete, vse); „danes" je `taken_at` v domačem pasu. Objava brez naslovljenca
  je `409` (`ADR-039` A); snov brez veljavnih vprašanj je neizbirna z razlogom;
  predogled ne shrani; objava preveri dolžine (200/16), besedilo vzame iz baze,
  upokojitve ne preverja (`ADR-018`). Vprašanj na sliko 1–10, privzeto 3.
- **Rezultat in tisk:** samo rešen kviz; skupine po `OCENE` in „Brez ocene";
  trajanje *razmislek*/*ocena*; tisk brez odgovorov in naslovov skupin, ključ na
  novem listu, izbor ocen z `GET` in `izbor=1` (privzeto *Nisem vedela*,
  *Težko*); nerešen je `409`.
- **Statistika** (`ADR-021`): nič se ne shranjuje; šteje vsak poskus
  `samoocena`; predmet je `questions.subject`; po otroku in šolskem letu od 1. 9.
  ali `vse`; razvrstitev po deležu *Nisem vedela* + *Težko*.
- **Po dnevih** (`ADR-023`): en otrok, dan ali zadnjih sedem dni; prazen dan se
  izpiše; neveljaven datum `400`, tuj otrok `404`; glava pove zadnji prejem;
  manjki z urnika za delno poslikan dan, ob izrisu.
- **Povečan prikaz:** puščici na soseda (`#povecano`), `taken_at DESC, id DESC`;
  prenos `MAT_2026-09-04_09-30.jpg`. **Urnik** (`ADR-028`, `ADR-041`, `ADR-042`):
  pon–pet, množica predmetov na dan, celica s tremi stanji, slika ob nalaganju.
- **Prepisi** (`ADR-048`, `ADR-049`): en predmet; glava `## <koda> — <čas>[ · <otrok>]`, nato Povzetek, Prepis, Vprašanja.
- **Preizkus** (`ADR-053`–`ADR-055`, `ADR-066`–`ADR-068`): v kodi `preizkus`, v
  vmesniku „test"; navodilo samo za `MAT`; snov sestavi strežnik
  (`admin.prepisi_izbora`); delo živi v brskalniku do „Shrani"; besedilo modela
  je nezaupanja vreden vhod; predaja *shranjen* → *v reševanju* → *rešen* s
  pogojem `iz` v `UPDATE`.
- **Premik snovi** (`ADR-040`): ena transakcija za snov in vsa vprašanja, pogoja
  v `UPDATE`; objavljeni kvizi se ne spremenijo. **Arhiv** (`ADR-011`): svoja os,
  brez vrnitve; „Izbriši dokončno" šele po `device_deleted_at`.
- **Ime otroka** samo pri več otrocih, kot vrednost polja (`ADR-039` F3,
  `ADR-051`); varuje `TestImenaPriEnemOtroku`.

## Znane omejitve

- **Obdelava je vezana na en proces `api`**; `--workers` bi sliko plačal dvakrat.
  `POST /quiz-attempts` s tujim `id` poskusa vrne `500` (`ADR-072` B2).
- `/openapi.json`, `/docs`, `/redoc` so dosegljivi vsakemu veljavnemu žetonu,
  tudi otrokovemu; `GET /admin/system/` vrne `307` (`ADR-045`). Drugega lastnika
  sistema ni mogoče ustvariti; števila članov vključujejo deaktivirane.
- **Povezava telefona:** stari APK po izteku seje ne more noter; enkratnost ni
  dokazana s sočasnim testom; dvojni klik lahko pusti dva žetona (`child_id` ni
  enoličen), oba potečeta v 10 min; po „Prekliči prijave" telefon kaže
  „Prijavljena" do prvega `401`; vzporedna povezava pusti sejo, ki poteče sama;
  vedenje odprtega zaslona ob novi povezavi določa `expo-router`.
- **Google:** `label` je lahko zastarel; lastnik tujih povezav ne ureja; nastanek
  seje z Googlom ni zapisan; Googlove odjave ni.
- **Registracija:** zapora ne zajame `/admin/static`; meji se štejeta pred
  zapisom; zahtevka ni mogoče umakniti; starš z Googlom nima gesla; pravnega
  besedila zasebnosti ni (`/#zasebnost`); sočasnost izbrisa in odobritve ni
  testirana; zavrnjene družine ostanejo do izbrisa.
- **Kvizi na telefonu** (`ADR-020`): trajno zavrnjen poskus obtiči brez sledi (ob
  zagonu do ceil(N/500) + N zahtevkov; ob neusklajeni pogodbi N raste); hkratna
  paketa lahko pustita `solved_at` prazen; ponovitev ob `IntegrityError` ni
  testirana; `sprozi` med obhodom ne naredi nič; kviz, odprt med obhodom, se
  lahko lokalno pobriše; `shraniKviz` ni ena transakcija.
- **Urnik:** za nazaj sodi po trenutnem urniku; arhiviran dan izgleda kot manjki;
  dan brez slik in praznik sta enaka; danes javi manjke med poukom; upokojeni
  urniki rastejo; sledi branja ni; dve hkratni potrditvi lahko pustita dva
  veljavna urnika (`ADR-076` C4).
- **Prepisi:** stran ni zaznamek; izbor je en predmet; 1 MiB praznih polj zadrži
  strežnik ~3,4 s (`ADR-076` D3).
- **Preizkus:** zaprtje okna izgubi neshranjeno; urejevalnik iz izbora ni
  zaznamek; samo matematika; prelom predogleda preverjen samo s Chromom; `$` je
  vedno ločilo formule; seja baze je odprta med klicem modela; po poteku seje
  shranjevanje iz odprtega okna ne gre; sličic pri ogledu ni; brisanja, arhiva,
  preimenovanja in ostranjevanja ni; model je trditev brskalnika.
- **Vedenja v brskalniku testi ne dokažejo** (urejevalnik, ogled, odložišče,
  povečan prikaz, papir) — samo izris. Fokus v povečanem prikazu ni ujet, vsaka
  puščica je nova stran.
- **Rezultat:** „Brez ocene" ni mogoče natisniti; `?ocena=` brez `izbor` se
  prezre. **Premik snovi:** telefon predmeta ne izve; prvotni se ne hrani; po ena.
- **Statistika:** „Postavljena večkrat" je sprva kratek; ponovna obdelava pretrga
  zgodovino vprašanja; stran predmeta bo dolga; vsak starš vidi ves `/admin`.
- **Testi strežnika tečejo nad SQLite**, ki tujih ključev privzeto ne uveljavlja;
  pgvector in Postgres nista pokrita. **Naslov odjemalca ni podatek**
  (`ADR-034` A). Kopija je na istem disku; po nenadzorovanem ponovnem zagonu
  strežnik ostane dol (`03-obratovanje.md`).

## Zunanje odvisnosti

`apps/mobile`: `expo` SDK 57, `expo-router`, `expo-status-bar`,
`expo-splash-screen`, `expo-camera` (tudi QR), `expo-sqlite`, `expo-file-system`,
`expo-image-manipulator` (1600 px, JPEG 0.8), `expo-crypto` (UUID),
`expo-secure-store` (žeton, `ADR-027`; v `plugins`), `react-native`, `react`,
`react-dom`, `react-native-safe-area-context`; `peerDependencies` `expo-router`
(`expo-constants`, `expo-linking`, `react-native-screens`, `-gesture-handler`,
`-reanimated`, `-worklets`); razvojno `jest`, `jest-expo`,
`@testing-library/react-native`, `react-test-renderer`, `eslint`,
`eslint-config-expo`, `typescript`, `babel-preset-expo`, `@types/*`.

`apps/server`: `fastapi`, `uvicorn[standard]`, `python-multipart`,
`sqlalchemy<2.1`, `psycopg[binary]`, `alembic`, `pydantic-settings`, `jinja2`,
`openai`, `httpx`, `segno>=1.6,<2` (`ADR-061` A); razvojno `ruff`, `mypy`,
`pytest`. V brskalniku, prepisano v `app/static/`: `marked` 15.0.12, `katex`
0.16.22 z `auto-render` (`ADR-054`), Atkinson Hyperlegible Next (OFL). Slike:
`pgvector/pgvector:pg17`, `caddy:2.11.4-alpine`.

Postavitev: `caddy` (omrežje `spredaj`, `172.30.10.10`, navzven samo TCP 443,
TLS-ALPN-01, `/favicon.ico` → 204), `api` (`default` in `spredaj`, brez `ports`,
proxy glavam zaupa samo s Caddyja), `db` (`default`). Ime projekta Compose je
`server`. `tests/test_postavitev.py` to bere kot besedilo.

## Kako se poganja in testira

```powershell
npm --prefix apps/mobile install       # nato: run lint, run typecheck, test
ruff check apps/server; mypy apps/server; pytest apps/server
pwsh -File scripts/verify.ps1          # šest korakov; nič se ne preskoči
```

- Testi baze telefona tečejo nad `node:sqlite`; kamera in dovoljenja se
  preverijo na napravi; `npx expo export -p android` preveri prevod.
- `SERVER_BASE_URL` (samo `https`) in `EAS_BUILD_ID` prideta ob gradnji v `extra`;
  domača stran izpiše `1.0.0 · gradnja <id>` ali `razvojna gradnja`; `versionCode`
  hrani EAS (`ADR-077` C).
- Strežnik: venv `apps\server\.venv` na `PATH` (`ADR-005`), `mypy.ini` v korenu,
  `.env` bere Compose. Postavitev, prvi zagon, gradnja APK, kopije:
  `03-obratovanje.md`.
