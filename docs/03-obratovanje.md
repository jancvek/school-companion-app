# Obratovanje — postopki na stroju lastnika

Bere se ob potrebi, ne ob vsaki zahtevi (`CLAUDE.md` §0, `ADR-070`). Tu so
postopki, ki jih izvede lastnik zunaj repozitorija ali ob postavitvi. Kako je
sistem zgrajen, pove `01-arhitektura.md`; zakaj, povedo ADR-ji.

## Prvi zagon strežnika

```powershell
copy apps\server\okolje.primer apps\server\.env   # nato izpolni
docker compose -f apps\server\docker-compose.yml up -d --build
```

- Brez `DOMENA` se Compose ne zažene. Po vsaki spremembi `apps/server` znova
  `up -d --build` (`02-izkusnje.md`).
- **`/admin` ni dosegljiv, dokler staršu ni nastavljeno geslo** — migracija
  ustvari uporabnika brez njega (`ADR-035` G):

  ```powershell
  docker compose -f apps\server\docker-compose.yml exec api `
    python -m app.ukazi nastavi-geslo dejan.ambrus@gmail.com
  ```

  Najkrajše geslo je 12 znakov. Ukaz prekliče vse seje računa. **Otrok gesla
  nima** (V6-R01): telefon mu poveže starš na `/admin/family` s QR kodo, ukaz
  otrokov račun zavrne.
- `OPENAI_API_KEY` in `OPENAI_API_KEY_PREIZKUSI` sta neobvezna: brez prvega ne
  teče obdelava, brez drugega sestavljanje testov; strežnik teče.
- **Ime projekta Compose je `server`** in je predpona volumnov z bazo, slikami
  in certifikati. `docker-compose.yml` se ne premika; **nikoli
  `docker compose down -v`**.

## Postavitev na novem stroju

Po vrsti:

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
5. **`apps/server/.env`** po `okolje.primer`. Obvezni sta `DOMENA` in
   `POSTGRES_PASSWORD` (Compose se brez njiju ne zažene); `DATABASE_URL` ima
   privzetek, `IMAGES_DIR` nastavi Compose sam.
6. **Prvi zagon** (zgoraj). Caddy v nekaj sekundah pridobi certifikat
   (dnevnik: `certificate obtained successfully`). Obnavljanje je samodejno.
7. **Preverba.** Z mobilnih podatkov `https://<domena>/health` →
   `{"status":"ok"}`; `/admin` pelje na prijavno stran; z gostitelja
   `127.0.0.1:8000` ne odgovori.
8. **Geslo staršu** z ukazom zgoraj.
9. **Aplikacija.** `SERVER_BASE_URL` v EAS (okolje `preview`) =
   `https://<domena>`, nova gradnja APK, namestitev **čez** obstoječo
   aplikacijo (odstranitev izbriše slike, ki čakajo na prenos).
10. **Podatki** s starega stroja: kopija in obnova spodaj.

## Google Cloud Console

V Google Cloud Console: projekt, **OAuth consent screen** tipa *External* z
obsegi `openid`/`email`/`profile`, nato **Credentials → OAuth client ID** tipa
*Web application* s povratnim naslovom
`https://school-buddy.duckdns.org/auth/google/callback` — **točno tako**, brez
končne poševnice, ker Google ujemanje zahteva znak za znak.

Aplikacija je v načinu **Testing** in zahteva samo `openid`, `email` in
`profile`. Po `ADR-057` H (Googlova dokumentacija,
*Manage App Audience*) se v
tem načinu lahko prijavi in registrira tudi račun, ki **ni** na seznamu
preizkusnih uporabnikov; na tej namestitvi je to preverjeno (13. 10. 2026). Če
bi Google to spremenil (`403: access_denied`),
registracija deluje samo za ročno vpisane račune, dokler se aplikacija pri
Googlu ne objavi.

`client_id` in `client_secret` gresta v `apps/server/.env` kot
`GOOGLE_CLIENT_ID` in `GOOGLE_CLIENT_SECRET`. Skrivnosti v repozitoriju ni in
ne sme biti; `okolje.primer` nosi imeni brez vrednosti, kar varuje test.

## Gradnja APK in EAS

- Gradnja: `npx eas-cli@latest build`, profil `preview` v
  `apps/mobile/eas.json` (Android APK, interna distribucija, okolje `preview`).
  Naslov strežnika je med spremenljivkami okolja EAS za to okolje, ne v `.env`;
  `app.json` nosi `owner` in `extra.eas.projectId`.
- **`SERVER_API_KEY` od V3-R04 ne obstaja.** Če je še med spremenljivkami na
  expo.dev, jo pobriši — v APK ne pride, dokler pa je tam, je skrivnost, ki je
  nihče ne vzdržuje.
- **Kaj je v zgrajeni APK, zeleni testi ne vidijo.** Dve preverbi, ki gresta
  dlje:

  ```powershell
  npx expo config --type introspect      # razreši plugine in izpiše manifest
  unzip -o app.apk AndroidManifest.xml   # kaj je v resnici v zgrajeni APK
  ```

  Prva v nekaj sekundah in brez gradnje pokaže, kaj pride v manifest (od V3-R02
  `<application>` nima `usesCleartextTraffic`). Druga pove, kaj je v zgrajeni
  APK; branje binarnega manifesta je v `02-izkusnje.md`.
- **Zadnja beseda je preizkus na telefonu** z mobilnimi podatki zunaj doma:
  slika mora priti do stanja „Preneseno".

## Varnostna kopija in obnova

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

## Odprto: strežnik po nenadzorovanem ponovnem zagonu

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
