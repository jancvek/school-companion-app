# ADR-077: Gradnja, okolje in postavitev (zapis za nazaj)

- **Datum:** 2026-11-04
- **Nastalo pri:** V6-R05 (zapis za nazaj; izvorne zahteve so pri točkah)
- **Status:** Sprejeto — zapis za nazaj

## Kontekst

Razlogi iz razdelkov „Stack", „Zunanje odvisnosti", „Javni dostop" in „Kako
se poganja in testira" v `docs/01-arhitektura.md`, ki nimajo lastnega ADR-ja
(`ADR-070`). Postopki so v `docs/03-obratovanje.md`.

## Odločitve in razlogi

### A. Stack (V1-R01 do V1-R03)

1. **Expo (React Native, TypeScript):** EAS Build da APK brez Trgovine Play in
   Android Studia; `expo-camera`, `expo-sqlite` in `expo-file-system` pokrijejo
   vse brez nativne kode.
2. **SQLite na telefonu** je čakalna vrsta za delovanje brez povezave.
3. **FastAPI**: naraven za klice AI/vision, lahek.
4. **PostgreSQL + pgvector:** ena baza za metapodatke in (kasneje) vektorje, brez
   ločene vektorske baze. Prva migracija ustvari razširitev `vector`;
   vektorskih stolpcev še ni.
5. **Obdelava je `asyncio` opravilo v procesu `api`, brez Celery in Redisa:**
   pri 5–25 slikah na teden ne rešita nobene težave; „kar bi lahko bila
   mikrostoritev, naj bo funkcija".
6. **Brez orodja za monorepo** (npr. Turborepo): dva jezika brez skupne kode,
   zato vsaka mapa živi s svojim orodjem (`npm` / `pip`).

### B. Odvisnosti

1. **`psycopg[binary]`**, ker na Windows ni prevajalnika; **SQLAlchemy pripet na
   2.0** (`<2.1`), ker 2.1 podre `mypy` (V3-R12).
2. **`openai`** je izbran zaradi strukturiranega izhoda po shemi (V1-R03).
3. **`expo-secure-store`** za žeton, ker `expo-sqlite` in `AsyncStorage` nista
   šifrirana in žeton ne sme ležati ob slikah (`ADR-027`). V testih se ne
   uporablja, ker ponudnik prijave dobi shrambo kot lastnost.
4. **V1-R02 in V2-R02 nista dodali odvisnosti:** prenos gre prek
   `expo-file-system`, nastavitve prek `expo-constants`, UUID poskusa iz
   `expo-crypto`.
5. **Knjižnici v brskalniku sta prepisani v repozitorij**, brez `npm` in
   `package.json`; nadgradnja je ročna zamenjava mape in sprememba `ADR-054`.
6. **Testi baze na telefonu tečejo nad `node:sqlite`**, ki je del Node.js in ne
   nova odvisnost. **Testi strežnika tečejo nad SQLite** skozi plast
   repozitorija, brez Postgresa in Dockerja; cena je, da pgvector in
   Postgres-specifično vedenje nista pokrita.

### C. Gradnja aplikacije (V1-R06, V3-R02, V3-R04)

1. **Naslov strežnika pride ob gradnji** (`SERVER_BASE_URL` → `extra`); brez
   njega worker ne teče, aplikacija pa deluje kot v V1-R01 in to pove. Naslov
   brez `https` šteje kot manjkajoč (`ADR-034` E).
2. **`SERVER_API_KEY` od V3-R04 ne obstaja:** skrivnosti v gradnji ni, kdo je
   prijavljen, pove žeton v varni shrambi.
3. **Oznaka gradnje na domači strani** (`EAS_BUILD_ID`): brez nje dveh APK ni
   bilo mogoče ločiti — verzija je bila pri obeh `1.0.0` in `versionCode` 1.
4. **`versionCode` hrani EAS** (`appVersionSource: "remote"`, `autoIncrement`),
   v `app.json` ga namenoma ni: številka, ki bi jo bilo treba ročno povečevati,
   se pozabi natanko takrat, ko je potrebna. Cena: svež klon števca ne pozna.
5. **Kaj je v zgrajeni APK, zeleni testi ne vidijo** — zato preverbi manifesta
   in na koncu preizkus na telefonu z mobilnimi podatki (`ADR-010`, `03`).

### D. Strežnik in okolje (V1-R02, V3-R02, V3-R03)

1. **`.env` prebere Docker Compose**, ne strežnik, ker bi bil `env_file`
   relativen na trenutno delovno mapo.
2. **`mypy.ini` je v korenu**, ker mypy nastavitve bere iz trenutne mape,
   `verify.ps1` pa ga kliče iz korena; `ruff` in `pytest` imata nastavitve v
   `apps/server/pyproject.toml`.
3. **Piškotek seje je `Secure` tudi pri razvoju:** brskalniki ga sprejmejo na
   `http://localhost`, zato razvojni zagon mimo Caddyja deluje.
4. **Certifikat gre prek TLS-ALPN-01**, ker vrata 80 drži IIS (Aras Innovator);
   zato ni preusmeritve z `http://`. HTTP/3 je izklopljen (brez UDP 443).
   Certifikati so v volumnu `server_caddy-podatki`, sicer bi vsak zagon prosil
   za nov certifikat in zadel omejitev Let's Encrypt.
5. **Caddy sam odgovori na `/favicon.ico` s 204:** sicer ikona zavihka pride do
   `api`, ki zanjo vrne 401. Z `basic_auth` je to brisalo geslo (`02`); odkar
   ga ni, ostane le napaka v dnevniku ob vsakem odprtju.
6. **`api` zaupa proxy glavam samo s Caddyjevega naslova** (`172.30.10.10`).
7. **Če strežnik preraste ta stroj**, je pravi odgovor ločena Linux naprava, ne
   prepletanje WSL-a (`03`, odprta odločitev o ponovnem zagonu).

## Posledice

- `01-arhitektura.md` nosi stack, odvisnosti in ukaze brez razlogov; postopki
  so v `03-obratovanje.md`.
