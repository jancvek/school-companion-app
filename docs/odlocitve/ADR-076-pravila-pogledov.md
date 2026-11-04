# ADR-076: Pravila pogledov — kvizi, rezultat, statistika, dnevi, urnik, prepisi (zapis za nazaj)

- **Datum:** 2026-11-04
- **Nastalo pri:** V6-R05 (zapis za nazaj; izvorne zahteve so pri točkah)
- **Status:** Sprejeto — zapis za nazaj

## Kontekst

Razlogi za posamezne strani `/admin` iz `docs/01-arhitektura.md`, ki jih
ADR-ji zahtev ne nosijo ali jih nosijo brez razloga (`ADR-070`).

## Odločitve in razlogi

### A. Sestavljalnik kvizov (V2-R01, V3-R07)

1. **Vstopi se razlikujejo tudi po obsegu seznama** (`ADR-017` A), ne le po
   kljukicah (`ADR-016`): dnevni vstop bi sicer naštel celotno zgodovino vseh
   predmetov, da bi obkljukal tri današnje slike.
2. **Naslovljenec se izbere nad seznamom**, ker odloča, katera snov je „že v
   kvizu". Menjava gre skozi `GET /new`, ne `POST /new`, ker se morajo kljukice
   preračunati po pravilu vstopa.
3. **Seznam snovi ni omejen na snov naslovljenca**, ker so vprašanja last
   družine.
4. **Izbirnik je stalno število poizvedb** (štiri) ne glede na dolžino seznama —
   otroci so ena poizvedba na stran, ne na vrstico. Če seznam postane
   neuporaben, je popravek ostranjevanje, ne tiho krajšanje.
5. **Razlogov neizbirnosti je pet, ne štirje:** poleg treh iz kriterija stanje
   dopušča še „obdelano, a brez veljavnih vprašanj" (snov v ponovni obdelavi).
6. **Predogled nosi dva obrazca:** „Objavi" identifikatorje vprašanj (objavi se
   natanko videno), „Nazaj na izbor" izbor snovi in število na sliko, da je
   izbor ob vrnitvi tak, kot je bil.
7. **Objava je edina pot, ki piše, zato preveri vsako polje**, besedilo pa
   prepiše iz baze, nikoli iz obrazca.
8. **Razdelek s kvizi na `/admin` stoji pod predmeti:** ime kviza vsebuje kodo
   predmeta in bi zgoraj postalo prva pojavitev kode ter podrlo test, ki po
   vrstnem redu pojavitev dokazuje, da so predmeti po urniku.

### B. Pregled po dnevih in povečan prikaz (V2-R07, V2-R08)

1. **Dan brez slik se izpiše prazen** — odsotnost je odgovor (`ADR-023`).
2. **Teden je zadnjih sedem dni do danes**, zato gumb ne nosi datuma in
   `?obdobje=teden&dan=…` je 400: parameter, ki na obseg ne vpliva, ne sme
   izgledati, kot da vpliva.
3. **Gumbi obdobja nosijo `otrok` naprej**, ker sta izbiri neodvisni in mora
   vsaka drugo preživeti.
4. **V glavi je zadnji prejem slike** (čez vse zapise): brez njega je prazen dan
   videti enako kot dan, ko telefon še ni prenašal.
5. **Sličic ni**; uporabi se ista pot do slike z `loading="lazy"`, zato je teden
   zgornja meja obsega.
6. **Povečan prikaz ne zamenja slike**, puščici peljeta na soseda: prenese se
   samo slika, ki jo operater gleda.
7. **Vrstni red predmeta ima drugi ključ `id`:** dve sliki z istim časom bi
   imeli nedoločen vrstni red in listanje bi eno preskočilo.

### C. Urnik in manjki (V3-R09)

1. **Celica je izbirnik s tremi stanji**, ker bi dve potrditveni polji dopustili
   četrto, nesmiselno kombinacijo. Mreža je cela: potrditev je zamenjava.
2. **Nepreslikana celica se izpiše z dobesednim besedilom** in nikoli ne pride v
   potrjen urnik — nikoli ne izpade molče.
3. **Manjki se računajo ob izrisu**, zato so pravilni tudi takoj po premiku snovi.
4. **„Veljaven je en sam" drži pri zaporednem pisanju**; `ADR-041` C je zavestno
   izbral, da enoličnosti ne uveljavlja shema, kriterij v `v3.md` pa je zapisan
   absolutno — razhajanje stoji kot znana omejitev, da ne ostane implicitno.

### D. Prepisi izbranih (V3-R11, V3-R12)

1. **Kljukica je sosed povezave, ne otrok**, sicer bi klik odprl podrobnosti.
   Gumb stoji nad seznamom in pod njim, ker predmet čez leto nosi nekaj sto slik.
2. **Pot je svoja**, ne pod `subjects/{koda:path}`, kjer bi `:path` požrl
   pripono; `POST`, ker bi `GET` pri nekaj sto UUID odpovedal (`ADR-048` B).
3. **Brez meje števila polj** (`max_fields=math.inf`): izbor je eno polje na
   sliko in „Izberi vse" bi sicer vrnil `400` z angleškim besedilom; končna meja
   bi težavo le premaknila. Edina meja je telo 1 MiB v `SejaMiddleware`.
   **Cena je izmerjena:** 1200 slik se razčleni v 0,012 s, 1 MiB praznih polj
   (349 525) v 3,4 s z vrhom ~85 MiB; uvicorn brez `--workers` za ta čas zadrži
   tudi prevzem slik. Poslati ga zna le prijavljen starš s CSRF žetonom (danes
   lastnik sam). Sprejeto zavestno.
4. **Tuj, arhiviran, tujepredmetni in neobstoječ identifikator se tiho
   izpustijo:** iz izrisanega obrazca ne morejo nastati, odgovor pa ne sme
   izdati, da tuja snov obstaja.

### E. Premik, rezultat, statistika, arhiv (V3-R10, V2-R03, V2-R04, V1-R07)

1. **Izbirnik predmeta pri neznani kodi dobi vodilno možnost brez vrednosti**,
   sicer bi brskalnik izbral prvo (`NAR`) in klik bi snov tiho vložil pod
   Naravoslovje.
2. **Rezultat: prazna skupina je vidna z 0** (kriterij „število v vsaki
   skupini"); **peta skupina „Brez ocene"** nastane le neprazna, ker postavka z
   neznano oceno ne sme izpasti molče.
3. **Oznake izvora so samo v rezultatu:** stran nerešenega kviza se ne sme
   spremeniti, ker test iz V2-R01 dokazuje, da je ponovna obdelava ne spremeni.
4. **Tisk je brez naslovov skupin**, ker bi „Nisem vedela" Maši povedal, kaj je
   prvič mislila. **Skrito polje `izbor=1` je nujno:** obrazec brez obkljukanega
   okenca ne pošlje ničesar in bi se tiho vrnil v privzetek; test obrazec
   prebere iz izrisa.
5. **Statistika: predmet je `questions.subject`**, ker dnevni kviz predmeta nima.
   Povezave nosijo obe izbiri (otrok, leto), sicer bi menjava leta vrnila
   privzetega otroka. Odstotki se zaokrožajo celoštevilsko, polovica navzgor,
   ker Pythonov `round` zaokroža bančno.
6. **Arhiv: odgovor je celoten delovni seznam, ne odsek za kazalcem**; časovni
   žig zadnje sinhronizacije je bil zavrnjen, ker pade na razliki ur in na
   transakciji, ki se potrdi, ko je telefon kazalec že premaknil (`ADR-011`).
   „Izbriši dokončno" šele po `device_deleted_at`, sicer telefon za brisanje
   nikoli ne izve; pravilo velja v vmesniku, poti in repozitoriju, ker gumb, ki
   ga stran ne izriše, ni varovalka.

## Posledice

- `01-arhitektura.md` nosi pravila pogledov v alinejah; razlogi so tu.
