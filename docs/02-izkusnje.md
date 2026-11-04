# Izkušnje — pasti, ki so nas že stale časa

Bere se ob potrebi, ne ob vsaki zahtevi (`CLAUDE.md` §0). Vsaka past: kaj se
zgodi, zakaj, kako se ji izogneš.

## Strežnik za Caddyjem (V3-R02)

### `basic_auth` in ikona zavihka
**Kaj:** Chrome in Edge sta geslo za `/admin` zahtevala ob vsakem kliku.
**Zakaj:** brskalnik geslo pošlje vnaprej tudi na `/favicon.ico`. Ta pot ni bila
pod `basic_auth`, prišla je do `api`, ta pa je vrnil 401 (API ključ). Brskalnik
401 na zahtevo z geslom razume kot zavrnjeno geslo in ga pozabi.
**Kako:** Caddy na `/favicon.ico` odgovori sam (204). Vsaka pot na isti domeni,
ki vrne 401 brez `basic_auth`, ima isti učinek — tudi koren `/`. V dnevniku se
vidi kot `GET /favicon.ico 401` v isti sekundi kot vsaka stran pod `/admin`.

### Docker Desktop ne ohrani naslova odjemalca
**Kaj:** vse zahteve s telefona so v dnevniku `api` imele naslov `172.18.0.1`.
**Zakaj:** preslikana vrata na Windows tečejo skozi Dockerjev posredniški proces.
**Kako:** naslova odjemalca v tej postavitvi ni; ne gradi ničesar, kar bi nanj
računalo (`ADR-034` A). Preveri z zahtevo z **druge** naprave — zahteva z
istega stroja pokaže prehod v vsaki postavitvi.

### Compose ustvari vsa omrežja, ne le potrebnih
**Kaj:** `docker compose -p drug-projekt up db` je padel s
`Pool overlaps with other one on this address space`.
**Zakaj:** omrežje s stalnim podomrežjem (`spredaj`) nastane ob vsakem projektu
iz iste datoteke, tudi če ga zagnani servis ne rabi.
**Kako:** drugi primerek iz iste datoteke na istem stroju ni mogoč, dokler teče
prvi. Preizkus obnove zato teče z navadnim `docker` (`ADR-034`, dopolnitev).

### Nova vrstica v `sh -c` je nov ukaz
**Kaj:** zastavica, prestavljena v naslednjo vrstico ukaza `command: >` v
Compose, bi tekla kot svoj ukaz; `uvicorn` bi tekel brez nje, brez napake.
**Kako:** zastavice ostanejo v isti vrstici kot program. Test v
`test_postavitev.py` to preverja.

### `docker compose up -d` ne zgradi nove slike
**Kaj:** po V3-R08 je pol ure tekla stara koda in migracija `0012` ni stekla.
**Zakaj:** sliko `api` (`build: .`) `up -d` zgradi samo, če je še ni —
spremenjene kode ne vidi. Vsebnik ustvari na novo le ob spremembi nastavitve
(pri V3-R08 nove spremenljivke `GOOGLE_*`), in še takrat iz stare slike.
**Kako:** po vsaki spremembi `apps/server` `docker compose up -d --build`.
Simptom: `Settings` nima novega polja, gumba na strani ni, `alembic current`
kaže staro revizijo.

### Zgostitev gesla v `.env`
**Kaj:** bcrypt zgostitev vsebuje `$`, ki ga Compose razume kot spremenljivko.
**Kako:** vrednost v `.env` v enojnih narekovajih. `docker compose config` jo
izpiše z `$$` — to je le ubežni zapis izpisa, ne napaka.

## Prijava in seje (V3-R03)

### `context_processors` prepišejo kontekst klicatelja
**Kaj:** prijavni obrazec je imel prazen CSRF žeton in vsak poskus prijave je
vrnil 403 — čeprav ga pot v kontekst izrecno poda.
**Zakaj:** Starlette obdelovalce konteksta izvede **za** klicateljem in z
`context.update(...)` njegove vrednosti prepiše. Obdelovalec je brez seje
vračal prazen `csrf` in s tem pobrisal žeton prijavne strani.
**Kako:** obdelovalec ključa, ki ga ne pozna, ne vrne (`app/strani.py`). Velja
za vsak `context_processor`: kar vrne, je močnejše od tega, kar poda pot.

### `app.routes` ne pokaže poti vključenih usmerjevalnikov
**Kaj:** generirani test dosegljivosti je našel nič poti pod `/admin`.
**Zakaj:** ta različica FastAPI `include_router` shrani kot ovoj
(`_IncludedRouter`), ne kot razgrnjen seznam `APIRoute`; usmerjanje dela
normalno, introspekcija prek `app.routes` pa ne.
**Kako:** seznam poti se bere iz `app.openapi()["paths"]` — javni vmesnik, ki
ovoje razgrne. Tako ga berejo `test_prijava.py` in `test_tesnjenje.py`.

### Piškotek s `Secure` in `TestClient`
**Kaj:** vsak admin test je po uvedbi seje dobil 303 na prijavo.
**Zakaj:** `TestClient` privzeto govori `http://testserver`, piškotka z
zastavico `Secure` pa odjemalec čez `http` ne pošlje — enako kot brskalnik.
**Kako:** testni odjemalec teče na `https://testserver` (`tests/conftest.py`).
V brskalniku je `http://localhost` izjema in `Secure` piškotke sprejme, zato
razvojni zagon mimo Caddyja deluje.

## Preverba (V3-R09)

### `mypy` nad `app/` ni isto kot nad `apps/server`

Zagon `python -m mypy app/` iz mape `apps/server` preveri **samo produkcijsko
kodo**; testi ostanejo zunaj. Ograja poganja `mypy apps/server` iz korena
repozitorija (`ADR-005`) in s tem 68 datotek namesto 32.

V `V3-R09` je bilo zaradi tega dvakrat poročano „typecheck čist", ko je bilo v
testih osem napak. Zbirka je bila ves čas zelena — `pytest` tipov ne preverja,
zato razlike ni pokazalo nič drugega kot neodvisen pregled.

**Poganjaj ga tako, kot ga požene ograja**, iz korena repozitorija:

```powershell
python -m mypy apps/server
```

Isto velja za `ruff`: `ruff check app/` izpusti `tests/` in `alembic/`.

## Google prijava (V3-R08)

### `secrets.compare_digest` nad `str` zahteva ASCII
**Kaj:** povratni klic `GET /auth/google/callback?state=ž` je vrnil **500 z golim
angleškim `Internal Server Error`** — na javni, neavtenticirani poti.
**Zakaj:** `compare_digest` ob `str` z znakom izven ASCII vrže `TypeError`.
Vsi trije vhodi, ki jih primerjamo, pridejo od zunaj: `state` iz naslova, CSRF
žeton iz obrazca in vsak piškotek (Starlette glavo `Cookie` dekodira v latin-1).
Huje od kode odgovora je bila druga posledica: izjema je ušla **pred** brisanjem
piškotka stanja, zato je ta ostal živ in jamstvo o enkratni rabi je padlo.
**Kako:** primerjaj **bajte**, ne nizov — `compare_digest(a.encode("utf-8"),
b.encode("utf-8"))`. Takrat je vsak vhod veljaven in neujemanje je neujemanje,
ne izjema. Velja za vsako primerjavo skrivnosti, ki pride iz zahteve.

**Kar me je stalo drugega kroga pregleda:** prvi popravek je naredil svojo
kopijo primerjave v `app/google.py` in popravil samo tisti dve klicni mesti,
ki sta bili v obsegu zahteve. Koren pa je `prijava.zetona_se_ujemata`, ki ima
**štiri** klicna mesta (obe prijavi, `SejaMiddleware`, nalaganje urnika) — in
tri od njih so še naprej dajale 500. Popravek, ki podvoji pravilo namesto da
bi popravil skupnega, ni popravek; je drugo pravilo, ki se z uro razide od
prvega. Pravilo je zdaj eno samo in `google.py` svoje kopije nima.
**Pokritost varuje generiran test** (`test_vsak_post_pod_adminom_prenese_ne_ascii_zeton`),
ki poti bere iz `openapi()` in zato zajame tudi pot, dodano jutri.

### Ista oznaka, dva tokova, dve besedili
**Kaj:** starš, ki je bil prijavljen in je poskušal povezati Google, je ob
napaki dobil „…ali se prijavi z geslom" — nasvet, ki ga ne more ubogati, ker
prijavljen je.
**Zakaj:** en slovar sporočil za dva tokova. Oznaka napake je res ista
(`stanje`, `nedosegljiv`, `zavrnjeno`), pomen zanjo pa ne.
**Kako:** **kam** odgovoriti odloči seja, **kaj** odgovoriti odloči tok. Dva
slovarja nad istimi ključi sta cenejša od enega, ki polovici bralcev laže.

### `git checkout <datoteka>` odnese necommitane popravke
**Kaj:** med mutacijskim preizkusom sem mutacijo vrnil z `git checkout` — in s
tem pobrisal tudi popravke, ki na tej datoteki še niso bili commitani.
**Kako:** pred mutacijo naredi kopijo datoteke (`cp` v začasno mapo) in jo vrni
s `cp`. `git checkout` vrne **commitano** stanje, ne stanja pred mutacijo.

### Mutacijski preizkus v delovnem drevesu zastrupi vzporeden verify
**Kaj:** lastnikov `verify.ps1` je padel z 12 testi, ki so v resnici zeleni.
Izpis je kazal izvorno vrstico z `.encode("utf-8")`, izjema pa je govorila
o primerjavi **nizov** — izvorna in izvedena koda si nista ustrezali.
**Zakaj:** mutacijski preizkus (namerno pokvarim kodo in preverim, da test
pade) sem delal kar v delovnem drevesu. Okno je bilo pol minute; v njem je
`verify.ps1` modul uvozil in ga je nato 4 minute in 40 sekund držal v
pomnilniku. Python modul uvozi enkrat, zato vrnitev datoteke na to nima
vpliva. Drevo je takrat imelo **nove teste in staro napako** — kombinacijo,
ki v nobenem commitu ne obstaja.
**Kako:** mutacija je namenoma pokvarjena koda in v skupnem drevesu je mina.
Bodisi teče v ločeni kopiji repozitorija, bodisi lastnika vnaprej opozorim,
naj v tem času ne poganja verify. Rdeč izid, ki mu ne ustreza noben commit,
je treba prepoznati in zavreči, ne popravljati — sicer se popravlja napaka,
ki je ni.

## Registracija (V6-R02)

### Vrstni red `INSERT` brez `relationship()`
**Kaj:** oddaja obrazca registracije je na produkciji vrnila 500
(`ForeignKeyViolation ... fk_credentials_user_id`), zbirka pa je bila zelena.
**Zakaj:** SQLAlchemy vrstni red vstavljanja znotraj enega `flush()` izpelje iz
`relationship()`, ne iz tujih ključev. Med `Family`, `User` in `Credential`
zveze ni, zato je `credentials` vstavil pred `users` — vrstni red je bil po
abecedi tabel, ne po naključju. SQLite brez `PRAGMA foreign_keys=ON` ključev
ne preverja, Postgres jih ob vsakem stavku. Isti vzorec sta imeli
`ustvari_z_prvim_starsem` (V3-R05) in `ustvari_clana` (V3-R06).
**Kako:** kadar ena transakcija ustvari vrstico in njenega otroka brez zveze v
ORM, gre vstavljanje skozi `_vstavi_po_vrsti` (`app/db.py`) — `flush()` po
vsaki vrstici, starš prvi. Novo tako pot dodaj v
`tests/test_vrstni_red_vstavljanja.py`, ki teče nad motorjem z vklopljenimi
ključi in bere zaporedje stavkov.

## Telefon (V1-R01, V2-R02, V3-R04)

### `jest` ne prevaja z React Compilerjem
**Kaj:** Expo predloga vklopi `experiments.reactCompiler`, testi pa tečejo nad
kodo brez njega.
**Zakaj:** zastavica pride iz Babelovega `caller`, ki ga testni prevod ne
nastavi, in je z nastavitvijo preseta ni mogoče vsiliti.
**Kako:** prevajalnik je izklopljen (`ADR-071` A1). Kdor ga vklopi, mora najprej
najti način, da velja tudi v testih.

### Edge-to-edge na Androidu
**Kaj:** gumb ob spodnjem robu konča pod sistemsko navigacijsko vrstico.
**Zakaj:** od Expo SDK 54 Android riše *edge-to-edge*.
**Kako:** zaslon prišteje `useSafeAreaInsets().bottom`. `SafeAreaProvider`
postavi `expo-router` sam, zato ga v `app/_layout.tsx` ni. Preveri na napravi
(`CLAUDE.md` §1b).

### `CREATE TABLE IF NOT EXISTS` ne doda stolpca
**Kaj:** telefon z zapisi iz starejše različice bi se tiho pokvaril, testi nad
svežo bazo pa bi bili zeleni.
**Zakaj:** stavek obstoječe tabele ne spremeni in tega ne javi.
**Kako:** vsaka sprememba lokalne sheme je migracija; test teče nad dobesedno
kopijo stare sheme (`ADR-071` B).

### Zastarele tipizirane poti
**Kaj:** `typecheck` pade ob vsakem novem zaslonu, čeprav je koda pravilna
(V2-R02).
**Zakaj:** `experiments.typedRoutes` bere `.expo/types/router.d.ts`, ki je
git-ignoriran in ga ustvari Metro; lokalna kopija zastari, svež klon je nima.
**Kako:** `npx expo customize tsconfig.json` (ali `npm start`); nobene sledene
datoteke ne spremeni.

### Nativni modul brez vpisa v `plugins`
**Kaj:** `expo-secure-store` je nativni modul.
**Zakaj:** nativni modul pride v gradnjo prek vpisa v `plugins`; testi ga ne
uporabljajo, zato manjkajočega vpisa ne opazijo.
**Kako:** mora biti med `plugins` v `app.json`, sicer ga zgrajena APK nima.

### Kaj je v zgrajeni APK, se ne vidi kot besedilo
**Kaj:** `AndroidManifest.xml` v APK je binarni AXML.
**Zakaj:** ime atributa je v nizovnem bazenu in ga `grep -a` najde, vrednost pa
ni vidna kot besedilo.
**Kako:** odsotno ime (npr. `usesCleartextTraffic`) je dokaz, da atributa ni;
prisotnega ime samo ne dokaže vrednosti. `npx expo config --type introspect`
izpiše naslov strežnika v čisti obliki — kadar gre le za manifest, ga poženi z
`EXPO_NO_DOTENV=1` in praznim `SERVER_BASE_URL`.

## Shema in migracije strežnika (V1-R03, V1-R07, V2-R01, V2-R05)

### `fileConfig` v Alembicu utiša dnevnik testov
**Kaj:** test dnevniškega zapisa ob manjkajočem `OPENAI_API_KEY` je padel samo v
celotni zbirki, ne sam (V1-R03).
**Zakaj:** privzeti `disable_existing_loggers=True` utiša vse že ustvarjene
zapisovalnike. V produkciji je to nevidno (`alembic upgrade head` je svoj
proces), v testih pa Alembic teče v istem procesu.
**Kako:** `alembic/env.py` kliče `fileConfig(..., disable_existing_loggers=False)`.

### Nevtralno ime filtrirane zveze
**Kaj:** pozabljen filter `retired_at IS NULL` nad svežo bazo ni viden — material
ima takrat natanko eno serijo vprašanj (V2-R05).
**Zakaj:** razlika med filtrirano in nefiltrirano zvezo se pokaže šele po prvi
ponovni obdelavi.
**Kako:** zvezo preimenuj, ne le filtriraj (`veljavna_vprasanja`,
`vsa_vprasanja`); `mypy` nato pomete čez vse bralce (`ADR-072` C5).

### SQLite ne zna `ALTER` tujega ključa
**Kaj:** migracija `0003_arhiv` mora prevesiti FK s `CASCADE` na `SET NULL`.
**Zakaj:** `ALTER` tujega ključa na SQLite ne obstaja.
**Kako:** na SQLite `op.batch_alter_table` s `copy_from` (tabela se prepiše),
na Postgresu navaden `ALTER`. Ime starega ključa je dialektni privzetek
(`questions_material_id_fkey`), novi je poimenovan.

### SQLite ne uveljavlja dolžine `VARCHAR`
**Kaj:** predolg vnos je v testih zelen, na Postgresu pa `DataError` in angleški
„Internal Server Error" (V2-R01).
**Zakaj:** testi tečejo nad SQLite, produkcija nad Postgresom.
**Kako:** dolžino preveri koda pred zapisom (`ADR-074` B6).

## Operaterska stran (V1-R04, V2-R01, V2-R07, V2-R08, V3-R11)

### Lovilna pot prekrije preusmeritev ob poševnici
**Kaj:** `GET /admin/` je vrnil 404 s trditvijo, da strani ni.
**Zakaj:** prvi poskus strani 404 je bila pot `/{ostanek:path}` na koncu
usmerjevalnika; ta je prekrila Starlettejevo preusmeritev ob končni poševnici.
**Kako:** napake izriše prestreznik `StarletteHTTPException`, ki se sproži šele,
ko poti res ni.

### Predloge brez `package-data`
**Kaj:** testi so zeleni, vsebnik pa pade ob prvi zahtevi.
**Zakaj:** predloge niso Python; brez `[tool.setuptools.package-data]` v
`pyproject.toml` jih nameščeni paket nima.
**Kako:** vsaka nova vrsta podatkovne datoteke (predloge, `static/`) gre v
`package-data`. Pot do predlog se izpelje iz `__file__`, ne iz trenutne mape.

### Vrstni red registracije poti
**Kaj:** `GET /admin/quizzes/new` registriran za `/{quiz_id}` bi „new" prebral kot
identifikator kviza.
**Zakaj:** FastAPI vzame prvo registrirano pot, ki se ujema.
**Kako:** stalna pot pred parametrično.

### `FormParser` ima `max_fields=1000`
**Kaj:** „Izberi vse" na dovolj velikem predmetu je vrnil `400` z golim angleškim
besedilom (V3-R11).
**Zakaj:** meja ni v `parse`, ampak v povratnem klicu `on_field_end`; izbor je eno
polje na sliko.
**Kako:** pot obrazec prebere sama, `await request.form(max_fields=...)`; meja
je velikost telesa (`ADR-076` D3).

### `hidden` in `display: grid`
**Kaj:** element z atributom `hidden` je bil viden (V2-R08).
**Zakaj:** `display: grid` v slogu prevlada nad `hidden`.
**Kako:** slog `hidden` vrne izrecno: `.prekritje[hidden] { display: none; }`.

### Grupiranje v Pythonu je drugi filter
**Kaj:** napačna zgornja meja obdobja v SQL (`<= do`) se na strani ne pokaže
(V2-R07, odkrito z mutacijskim preizkusom).
**Zakaj:** snov čez mejo pade ven, ker njenega lokalnega dneva na seznamu dni ni.
**Kako:** meje presojaj nad `MaterialsRepository.seznam_po_obdobju`, ne nad
izrisom.

### `date.today()` v vsebniku je UTC
**Kaj:** med lokalno polnočjo in dvema bi „danes" vrnil prejšnji dan; noben test
nad stranjo tega ne pokaže, ker je stroj lastnika v istem pasu.
**Kako:** `casi.danes()` bere koledar v domačem pasu; pritrjeno z namestnikom
`datetime` (`TestDanes`).

### `ZoneInfo` ob uvozu modula
**Kaj:** manjkajoča baza pasov bi podrla tudi `GET /health` in `POST /materials`.
**Zakaj:** izjema ob uvozu modula pade ob nalaganju aplikacije, ne le na strani s
časom.
**Kako:** `ZoneInfo` se ustvari ob prvi uporabi.

### SQLite vrne naiven čas
**Kaj:** Postgres `TIMESTAMPTZ` vrne s pasom, SQLite brez; telefon bi naiven čas
prebral kot svoj lokalni.
**Zakaj:** SQLite podatka o pasu ne hrani.
**Kako:** prikaz čas normalizira v UTC pred pretvorbo; odgovori telefonu nosijo
izrecen pas (`casi.utc`).

### Dvooblični vzorec v predlogi
**Kaj:** „2 vprašanj" je bil vsak dan viden in ga noben test ni ujel.
**Zakaj:** vzorec `{{ "…" if … == 1 else "…" }}` pozna dve obliki, slovenščina
štiri.
**Kako:** `stevilo_z_besedo`; test nad datotekami predlog vzorec prepove
(`ADR-074` D).

### Dnevnik usmerjevalnika pod uvicornom
**Kaj:** vrstica `INFO` iz `app.routers.preizkusi` se ne izpiše (V4-R07).
**Zakaj:** uvicorn korenskega zapisovalnika ne nastavi.
**Kako:** dnevnik ima svoj izpis (`main._vklopi_dnevnik_porabe`).

## Orodja na tem stroju

- **`python` in `pip` na tem računu kažeta v venv projekta**, ker je
  `apps\server\.venv\Scripts` na začetku uporabniškega `PATH` (`ADR-005`).

- **`scripts/` je del ograje** in agentu ni dovoljena za pisanje. Nove skripte
  gredo k modulu, ki mu pripadajo (npr. `apps/server/varnostna-kopija/`).
- **`powershell.exe` (5.1) skript ne požene** (pravilnik izvajanja), a tudi ne
  pozna `$PSNativeCommandUseErrorActionPreference`. Skripte zahtevajo
  PowerShell 7.3 (`#Requires`) in se kličejo s `pwsh`.
- **Preusmeritev `>` v PowerShellu pokvari binarni izhod** (npr. `pg_dump -Fc`).
  Binaren izhod nastane v vsebniku in gre ven z `docker cp`.
- **Orodja `eas` na stroju ni.** Gradnja gre z `npx eas-cli@latest build`,
  spremenljivke EAS pa se urejajo na expo.dev.
