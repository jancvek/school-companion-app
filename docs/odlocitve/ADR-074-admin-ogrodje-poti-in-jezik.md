# ADR-074: Admin — ogrodje strani, poti, napake in jezik (zapis za nazaj)

- **Datum:** 2026-11-04
- **Nastalo pri:** V6-R05 (zapis za nazaj; izvorne zahteve so pri točkah)
- **Status:** Sprejeto — zapis za nazaj

## Kontekst

Razlogi za ogrodje operaterske strani iz `docs/01-arhitektura.md`, ki nimajo
lastnega ADR-ja (`ADR-070`). Videz je v `ADR-056` in `ADR-060`, skripte v
`ADR-024`, `ADR-054`, `ADR-055`.

## Odločitve in razlogi

### A. Delitev modulov (V2-R01)

1. **`app/casi.py`, `app/strani.py` in `app/besedilo.py` so izvlečki iz
   usmerjevalnikov, ne nove plasti.** Prva dva sta nastala zaradi krožnega
   uvoza: `kvizi` potrebuje `daj_predloge` in obe strani z napako, `admin` pa
   seznam kvizov — v `admin.py` bi krog `admin → kvizi → admin` padel ob uvozu.
   Tretji je prišel s popravkom dvojine, ko je isto pravilo potreboval `admin`.
2. Iz tega pravilo: **kar potrebujeta oba usmerjevalnika, ni last nobenega** in
   ima javno ime brez podčrtaja — podčrtaj pomeni „ne uvažaj od zunaj", uvoz od
   zunaj pa je prav razlog, da modul obstaja. (Pravilo stoji tudi v
   `01-arhitektura.md`, ker nanj kaže koda.)
3. **`OZNAKE_OCEN` je v `app/subjects.py`** (V2-R04), ker ga potrebujeta
   rezultat kviza in statistika.

### B. Poti in napake (V1-R04, V2-R01, V2-R07)

1. **Poti so angleške kot obstoječi API, vidno besedilo slovensko.**
2. **Prestreznik `StarletteHTTPException` velja samo pod `/admin`**, ker morajo
   odgovori `POST /materials` ostati JSON — telefon tam pričakuje sporočilo o
   napaki, ne strani.
3. **Pot predmeta je `subjects/{koda:path}`, povezava ubežana za URL**, ker koda
   sme vsebovati karkoli (`POST /materials` jo omejuje le po dolžini); brez
   obojega bi bile slike s poševnico ali vprašajem v kodi nedosegljive.
4. **Po brisanju zadnje slike predmeta zunaj desetih stran pelje na pregled**,
   ker tak predmet obstaja samo, dokler ima sliko, in bi bila njegova stran 404.
   Kriterij „preusmeri na seznam predmeta" in kriterij „neznana koda je 404" si
   v tem kotu nasprotujeta; izbrana je stran, ki obstaja.
5. **Polja obrazcev s številom se berejo kot niz** (npr. „vprašanj na sliko"):
   `int` bi ob nerazberljivi vrednosti dal surov angleški `422` pod predpono,
   kjer je vse slovensko. Nerazberljiva vrednost pade na privzetek in polje to
   pokaže.
6. **Dolžine (ime 200, koda 16) preveri koda, ne baza:** testi tečejo nad
   SQLite, ki dolžine `VARCHAR` ne uveljavlja; na Postgresu bi bil predolg vnos
   `DataError` in operater bi dobil angleški „Internal Server Error".
7. **Pri `?dan=` je neveljaven vhod 400, pri `?leto=` pa padec na privzetek:**
   tam je okno pripomoček nad istimi podatki, tu je datum celoten pomen strani
   (`ADR-023`). Za `?otrok=` velja 404 kot za vsako identiteto (`ADR-039` B,
   `ADR-038`).

### C. Čas (V1-R07, V2-R07, V2-R04)

1. **Ure so v pasu `Europe/Ljubljana`**, ker jih operater primerja s
   telefonom. Bazo pasov prinese sistem (`/usr/share/zoneinfo`, na Windows
   `tzdata`, ki ga zahteva že `psycopg`), zato ni nove odvisnosti.
2. **`ZoneInfo` se ustvari ob prvi uporabi, ne ob uvozu** — sicer bi manjkajoča
   baza pasov podrla tudi `GET /health` in `POST /materials`.
3. **Čas iz baze se pred pretvorbo normalizira v UTC**, ker ga SQLite vrne brez
   pasu, Postgres pa s pasom.
4. **`danes()` bere koledar v domačem pasu, ne strojne ure:** vsebnik teče v
   UTC in med lokalno polnočjo in dvema bi `date.today()` vrnil prejšnji dan.
5. **Grupiranje po lokalnem dnevu in mesecu je v Pythonu, ne v SQL**, ker izraz
   za lokalni dan ni prenosljiv med SQLite in Postgresom. Meje se izračunajo v
   usmerjevalniku in repozitoriju podajo kot par UTC trenutkov; repozitorij za
   pasove ne ve.

### D. Slovenske oblike števil (V2-R01, popravek dvojine)

1. **Oblike so podatek, ne koda:** vsak samostalnik je četverica na enem mestu.
2. **Ločnica gre po ostanku pri deljenju s sto, ne po zadnji števki** — edini
   način, da sta 21 in 101 različna: *enaindvajset* zahteva rodilnik množine
   („21 slik"), *sto ena* ednino („101 slika"); zato tudi „111 slik".
3. **Sklanja usmerjevalnik, ne predloga** — „predloga ne računa in ne oblikuje".
   Kjer besedilo zahteva sklon (rodilnik „iz N snovi"), je oblika pri vsakem
   številu ista in je konstanta v predlogi.
4. **`snov.html` in `brisanje.html` sklanjatve namenoma ne uporabljata:** oblika
   z dvopičjem je pravilna pri vsakem številu; menjava bi bila okus.
5. **Test lovi dvoobličnost nad datotekami predlog, ne nad izrisom**: vzorec
   `{{ "…" if … == 1 else "…" }}` je bil vir napake, ki je bila vsak dan vidna
   in je noben test ni ujel.

## Posledice

- Pravila ostanejo v `01-arhitektura.md`; tu so razlogi, da se ob spremembi
  vidi, kaj se z njo podre.
