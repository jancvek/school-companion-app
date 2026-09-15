# ADR-034: Izvedba V3-R02 — DuckDNS, naslov odjemalca, dva koraka z ene veje

- **Datum:** 2026-09-15
- **Nastalo pri:** V3-R02 (faza 1 in 2)
- **Status:** Sprejeto
- **Dopolnjuje:** `ADR-026` (utemeljitev za `--proxy-headers`, pomen „lastne
  domene", izvedba dveh korakov)

## Kontekst

`ADR-026` je odločil *kaj*: Caddy pred `api`, samo vrata 443, TLS-ALPN-01,
`basic_auth` kot začasen čep, dva koraka. Pri pripravi V3-R02 se je pokazalo
šest vprašanj o tem, *kako*, in eno dejstvo, ki eno od utemeljitev v `ADR-026`
na tem stroju podre.

**Dejstvo, preverjeno 15. 9. 2026:** Docker Desktop (4.26.1, Engine 24.0.7) na
Windows vsebniku ne izroči pravega naslova odjemalca. Zahteve s telefona prek
Tailscale (`GET /materials/pending-deletion`, `GET /quizzes/pending` iz
aplikacije in `GET /admin` iz brskalnika na telefonu) so v dnevniku `api` vse
zapisane z naslovom `172.18.0.1` — prehodom omrežja Compose. Preslikana vrata
teče skozi Dockerjev lastni posredniški proces, ki izvorni naslov zamenja s
svojim.

`ADR-026` pa `--proxy-headers` utemeljuje z: *„Brez tega bo vsak odjemalec …
videti kot isti IP, kar omejevanje naredi neuporabno."* Caddy bi v tej
postavitvi v `X-Forwarded-For` pošteno zapisal `172.x.0.1` za vse
obiskovalce. Nastavitev bi bila pravilna, a brez učinka.

## Možnosti (naslov odjemalca)

1. **Omejitev sprejmeva in zapiševa.** `--proxy-headers` in njegov test
   ostaneta. Za: nič se ne podre, veriga je pravilna in začne delovati v
   trenutku, ko strežnik teče na Linuxu. Proti: na tem stroju naslov odjemalca
   ni podatek; omejevanje prijav mora stati na uporabniškem imenu.
2. **Caddy zunaj Dockerja, kot storitev Windows.** Za: pravi naslov. Proti:
   `api` mora dobiti vrata na `127.0.0.1` gostitelja (krši kriterij V3-R02),
   storitev živi zunaj repozitorija in zunaj Compose.
3. **Docker Engine v WSL namesto Docker Desktopa.** Za: reši vzrok. Proti:
   velik poseg v stroj, v `docs/01-arhitektura.md` že pretehtan in odložen.

## Odločitev

**A — omejitev naslova odjemalca je sprejeta (možnost 1).** Izbral lastnik.
`--proxy-headers` z zaupanjem samo Caddyjevemu naslovu ostane, ker je pravilen
in poceni. **Omejevanje poskusov prijave v `V3-R03` gre po identifikatorju
(uporabniškem imenu), ne po naslovu** — kriterij `V3-R03` to že tako zapiše.
Da kdo z znanim uporabniškim imenom lahko nagaja s počasnejšo prijavo, je
vprašanje za `V3-R03`, ne za to zahtevo.

**B — domena je `school-buddy.duckdns.org`.** DuckDNS je tretja stran samo v
DNS, ne v poti slik, zato izpolni namen „lastne domene" iz `ADR-026` (nobene
tretje strani med telefonom in strežnikom). `duckdns.org` je na seznamu javnih
pripon, zato omejitve Let's Encrypt veljajo za poddomeno, ne za vse uporabnike
DuckDNS.

**C — IP je statičen, dinamičnega DNS ni.** Zapis `A` na DuckDNS je nastavljen
ročno; v repozitoriju ni servisa, ki bi ga posodabljal. Če se IP kdaj
spremeni, je to ročni korak iz navodil v `docs/01-arhitektura.md`.

**D — dva koraka na eni veji, prvi gre v živo z veje.** Ena zahteva, en plan,
en merge. Korak 1 se na strežniku zažene z veje, takoj ko je commitan, ker se
del, ki ga v kodi ni (usmerjevalnik, požarni zid, certifikat, dostop od doma),
drugače ne da preizkusiti. Vmesno stanje je tisto iz `ADR-026`.

**E — aplikacija naslov, ki ni `https://`, zavrne v kodi.** Brez tega
„izključno https" drži samo prek nastavitve EAS, napačna nastavitev pa bi se
pokazala kot slike, ki večno čakajo na prenos. Z zavrnitvijo aplikacija pove,
da prenos ni nastavljen. Cena: razvojna gradnja ne more več na lokalni `http`
strežnik.

**F — varnostna kopija sta dve skripti v `scripts/`,** kopije na
`C:\varnostne-kopije\school_companion\`, hrani se zadnjih 14. Dnevno opravilo
v Windows ustvari lastnik. Obnova na prazno namestitev je ločen projekt
Compose s praznimi volumni na istem stroju. Kopija na istem disku ne preživi
okvare diska — to je sprejeto in zapisano, ne spregledano.

## Posledice

- **Kaj to olajša:** V3-R02 ne čaka na selitev stroja; preizkus zunanjega dela
  pride na začetek, ne na konec.
- **Kaj to oteži:**
  - Dnevnik in vsak prihodnji bralec naslova odjemalca vidita en sam naslov,
    dokler strežnik teče na Docker Desktop.
  - Produkcija med korakoma teče na nemergeani kodi. V mapi, iz katere teče,
    se med tem ne preklaplja na `main` in ne gradi znova.
- **Na katere zahteve to odslej vpliva:** `V3-R03` (omejevanje po
  identifikatorju), `V3-R05` (ponovna obnova kopije uporabi skripto iz F),
  `V3-R08` (povratni naslov na `school-buddy.duckdns.org`).

## Dopolnitev — preizkus obnove brez Compose (15. 9. 2026, med izvedbo)

**Preglasi:** v F besedi „ločen projekt Compose" in odločitev 11 v
`docs/plan/V3-R02.md` v istem delu. Plan ostane, kakršen je bil.

**Kontekst.** Poskus `docker compose -p school-obnova up --no-start db` je
padel s `Pool overlaps with other one on this address space`. Compose ob
zagonu ustvari **vsa** omrežja iz datoteke, ne le tista, ki jih izbrani servis
rabi; omrežje `spredaj` ima stalno podomrežje (`172.30.10.0/24`), ki ga že drži
živi strežnik. Drug projekt iz iste datoteke zato na istem stroju ne more
nastati, dokler teče prvi.

**Možnosti.**

1. **Obnova z navadnim `docker`.** Vsebnik baze in prazna volumna z imeni
   `school-obnova*`, ista slika baze kot v produkciji. Za: namen ostane
   (prazna namestitev, živi strežnik nedotaknjen), brez nove slike in brez
   spremembe `docker-compose.yml`. Proti: obnova ne gre skozi datoteko Compose,
   zato ne preveri, da iz nje nastane delujoča baza — to preveri vsak zagon
   produkcije.
2. **Nastavljivo podomrežje v `docker-compose.yml`.** Za: obnova skozi
   Compose. Proti: Caddyjev naslov in zaupanje v `api` postaneta spremenljivki,
   ki morata biti vedno usklajeni — prav napaka, pred katero varuje test
   zaupanja.

**Odločitev.** Možnost 1. Izbral lastnik. `scripts/obnova.ps1` ustvari samo
vire z imeni, ki se začnejo s `school-obnova`, in na koncu pobriše samo te.
