# ADR-006: Strežnik dobi operatersko spletno stran, ki je ne varuje geslo

- **Datum:** 2026-09-05
- **Nastalo pri:** V1-R04 (faza 2 — preverba smiselnosti)
- **Status:** Sprejeto
- **Zoži:** izključitev v `docs/verzije/v1.md`, razdelek „Kaj v tej verziji
  izrecno NI": *„Web vmesnik — samo mobilna aplikacija."*

## Kontekst

Strežnik iz V1-R02 sprejema slike in jih zapisuje, nima pa nobenega načina,
da bi kdo videl, kaj je v njem. Edini pogled je `docker exec` in `psql`.

To postane resnična ovira v V1-R03, kjer bo vsaka slika sprožila plačan klic
zunanjega vision modela. Vprašanja „katero sliko je model dobil", „kaj je
vrnil" in „zakaj je ta padla" bo treba postavljati vsak dan, in odgovor v
`psql` je predrag, da bi ga kdo v resnici iskal.

Vloga, ki to potrebuje, v dokumentaciji že obstaja. `docs/00-namen.md`
opisuje lastnika sistema kot tistega, ki *„vzdržuje domači strežnik, API
ključe, **spremlja delovanje**"*. Orodja za zadnje ni.

Izključitev v `v1.md` je bila zapisana v kontekstu vprašanja, ali bo
aplikacija za učenko tudi spletna. Operaterske strani ni obravnavala — a
piše, kar piše, in je ni dovoljeno tiho zaobiti.

Ločeno vprašanje je zaščita. Vse poti razen `GET /health` danes varuje ASGI
vmesna plast, ki zahteva ključ v glavi `X-API-Key`. **Brskalnik take glave ne
zna poslati**, zato admin stran po obstoječi poti sploh ni dosegljiva.

## Možnosti

### A — ali sploh spletna stran

1. **Nič; ostane `psql`.** Za: izključitev ostane nedotaknjena, nič dela.
   Proti: nadzor nad V1-R03 postane tako neroden, da se v praksi ne bo
   izvajal; napačno obdelane slike bodo odkrite pozno ali nikoli.
2. **Ukazna orodja (`docker exec` + skripta).** Za: brez HTTP plasti in brez
   nove odvisnosti. Proti: slike so bistvo problema, terminal pa jih ne
   pokaže. „Poglej, kaj je model dobil" je vprašanje o sliki.
3. **Strežniško izrisana spletna stran.** Za: slike, metapodatki in akcije na
   enem mestu; naravna razširitev za V1-R03. Proti: zoži zapisano
   izključitev; nova odvisnost; nova varnostna površina.

### B — kako je zaščitena

1. **Brez zaščite; meja je Tailscale.** Za: nič kode, nič skrivnosti.
   Proti: kdorkoli v Tailscale omrežju vidi in briše.
2. **HTTP Basic z obstoječim `API_KEY`.** Za: ena skrivnost. Proti: veže
   operaterjevo geslo na ključ, ki je vgrajen v APK; menjava enega zahteva
   novo gradnjo drugega.
3. **HTTP Basic z ločenim `ADMIN_PASSWORD`.** Za: ločeni skrivnosti. Proti:
   ena spremenljivka okolja in ena koda več.

## Odločitev

**A3 + B1.** Strežnik dobi strežniško izrisano operatersko stran pod
predpono `/admin`, ki je ne varuje ne ključ ne geslo.

Izključitev v `v1.md` se zoži na: *„Spletnega vmesnika za učenko ni — Maša
dela izključno v mobilni aplikaciji. Operaterska stran na strežniku je
dovoljena."*

Model B1 je izbral lastnik: omrežje je zaprto s Tailscale, uporabnik je en
sam, stran ne omogoča ničesar, česar ne omogoča že dostop do stroja.
Možnost B3 ostaja zapisana kot pot, če se krog dostopa kdaj razširi.

Tehnične meje, ki jih ta odločitev nalaga:

- **Izvzetje iz preverbe ključa velja samo za predpono `/admin`.** Nobena
  obstoječa pot se ne izvzame in nobena obstoječa pot ne sme postati
  dosegljiva brez ključa.
- **Zraven gre regresijski test**, ki dokaže, da `POST /materials` brez
  ključa še vedno vrne 401. Brez njega je to izvzetje sprememba, ki je nihče
  ne opazi, dokler ni prepozno.
- Stran ne uporablja JavaScripta in ne uvaja gradnje frontenda v
  `apps/server`. Predloge izrisuje **Jinja2**, ki je edina nova odvisnost.

## Posledice

- **Kaj to olajša:** V1-R03 dobi mesto, kjer se prikažejo poslani prompt,
  odgovor modela, poraba tokenov in napaka — brez tega bi bilo razhroščevanje
  vision klicev slepo. Sliko, ki je napačno posneta, je mogoče odstraniti,
  preden zanjo kdo plača klic.
- **Kaj to oteži:**
  - `BIND_ADDRESS` postane edina meja pred pregledom vseh slik. Doslej je
    napačna vezava (npr. `0.0.0.0`) izpostavila pot, ki je zahtevala ključ;
    odslej izpostavi tudi galerijo. Privzetek `127.0.0.1` ostane namenoma
    neuporaben od zunaj.
  - Vsaka nova pot pod `/admin` je javna znotraj omrežja. To velja tudi za
    tiste, ki jih bo dodala V1-R03.
  - Kdorkoli v omrežju lahko izbriše sliko. Brisanje je nepovratno — glej
    spodaj.
- **Nepovratnost brisanja.** Ko je zapis na telefonu `synced`, ga upload
  worker nikoli več ne pošlje; gumb „Poskusi znova" vrne v vrsto samo zapise
  s stanjem `failed`. Slika, izbrisana na strežniku, je zato tam izgubljena
  za vedno, čeprav datoteka na telefonu ostane. Brisanje mora zato teči prek
  `POST` z vmesno potrditvijo, nikoli prek navadne povezave.
- **Na katere zahteve to odslej vpliva:** V1-R03 gradi prikaz rezultatov
  obdelave in gumb „Pošlji v obdelavo" na tej strani. V1-R05 (kviz v
  aplikaciji) se je ne dotika.
