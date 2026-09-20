# ADR-041: Izvedba urnika — vnos v adminu, sinhrona obdelava, upokojitev

- **Datum:** 2026-09-20
- **Nastalo pri:** V3-R09 (fazi 1 in 2)
- **Status:** Sprejeto
- **Stoji na:** `ADR-028` (urnik je množica predmetov po dnevih, manjki so
  vrstica v pregledu po dnevih), `ADR-025` (družina je lastnik podatkov),
  `ADR-024` (skripta na `/admin` je izjema), `ADR-008` (klic modela je v enem
  modulu), `ADR-039` (izbira otroka v pogledih po otroku)
- **Dopolnjuje:** kriterije `V3-R09` v `docs/verzije/v3.md` — glej odločitev E

## Kontekst

`ADR-028` je odločil, **kaj** urnik je in kaj manjko pomeni. Pustil je odprtih
pet stvari, brez katerih izvedbe ni mogoče začeti; zahteva `V3-R09` jih je
naštela pod „Odprto za fazo 1". Ta ADR jih zapre.

Vprašanja niso enakovredna: prvo (kod vstopi slika) določi obseg zahteve,
drugo (kdaj se obdela) določi, koliko sheme nastane, tretje in četrto sta
majhni, peto pa **razširi zapisani kriterij** in zato ne sme ostati samo
dogovor iz pogovora.

## Možnosti in odločitve

### A — kako slika urnika pride v sistem

1. **Nalaganje na admin strani.** Za: telefon se ne dotakne, kar je isto
   sklepanje kot `ADR-028` C1 pri prikazu manjkov; urnik potrjuje starš in
   nalaga ga tam, kjer ga potrjuje. Proti: prvi obrazec z datoteko pod
   `/admin` — dotlej so slike prihajale izključno s `POST /materials`.
2. **Kamera na telefonu.** Za: fotografiranje je smisel aplikacije in otrok
   ima urnik pri roki. Proti: nov zaslon, nova vrstica v lokalni bazi, nova
   pot v `src/sync/`, migracija lokalne sheme in obvezen preizkus na napravi z
   APK — podvojen obseg za dejanje, ki se zgodi dvakrat na leto, in razred
   napak iz `ADR-010` povrhu.

**Izbrano: A1.**

### B — kdaj se predlog obdela

1. **Sinhrono ob nalaganju.** Za: starš stoji pred zaslonom in izid je
   obrazec, ki ga mora tako ali tako popraviti; ni druge čakalne vrste, ni
   tabele za nepotrjen predlog, ni novih stanj in ni strani, na katero se je
   treba vrniti. Proti: zahteva traja, dokler traja klic.
2. **Prek workerja (`ADR-009`).** Za: enak vzorec kot snov; dolgi klic ne
   visi na zahtevi. Proti: druga čakalna vrsta poleg `materials`, svoj
   `new`/`processing`/`ready`/`failed` in obstojen nepotrjen predlog —
   bistveno več sheme za pot, ki se uporabi dvakrat na leto.

**Izbrano: B1.** Cena je vidna in sprejeta: starš ob oddaji čaka do
`openai_timeout_seconds` (danes 120 s) brez vmesnega prikaza, ker stran nima
skripte (`ADR-024`). Posebne krajše časovne omejitve za to pot ne uvajamo —
nastavitev, ki bi jo nekdo moral vzdrževati, je dražja od čakanja dvakrat na
leto. Endpoint je sinhron (`def`), zato ga Starlette požene v pomožni niti in
strežnik medtem streže naprej.

### C — kaj ostane od prejšnjega urnika

1. **Upokojitev.** Za: `docs/00-namen.md` med načeli, ki veljajo povsod, pravi
   „nič se ne briše, vse se upokoji"; cena je en `NULL`-abilen stolpec in en
   pogoj v poizvedbi — isti vzorec kot `materials.archived_at` (`ADR-011`) in
   `questions.retired_at` (`ADR-015`). Proti: v bazi ležijo vrstice, ki jih ne
   bere nihče.
2. **Izbris.** Za: manj vrstic. Proti: prvo mesto, kjer se načelo prekrši, in
   prekrši se ga zaradi prihranka, ki ga nihče ni izmeril.

**Izbrano: C1.** Upokojen urnik obdrži svoje vnose in svojo sliko na disku.
Veljaven je natanko tisti z `replaced_at IS NULL`; enoličnosti ne uveljavlja
shema, ampak ena pot pisanja v eni transakciji.

### D — kdo sme urnik potrditi

1. **Samo starš.** Pri A1 to ni izbira, ampak posledica: `prijava.Vrata`
   otroku `/admin` zapre v celoti in to pravilo je namenoma eno samo, ne dve
   zrcalni veji (`ADR-035` F, `ADR-036` D).
2. **Tudi otrok za svojega.** Zahtevalo bi nova vrata ali novo pot za telefon,
   kar `ADR-028` C1 zavrača.

**Izbrano: D1.**

### E — je urejevalna mreža dosegljiva brez nove slike

Kriterij `V3-R09` pravi: *„Vision model iz slike predlaga urnik; starš ga v
urejevalni mreži popravi in potrdi."* Dobesedno branje pomeni, da brez slike
mreže ni.

1. **Mreža je vedno urejljiva.** Kaže trenutno veljaven urnik; slika je način,
   da se napolni, ne edini vstop. Za: neuspela ali neberljiva obdelava — ki jo
   kriterij izrecno predvideva — ima izhod, ki ni „slikaj znova"; popravek ene
   celice čez pol leta ne terja nove fotografije.
   Proti: **širše od zapisanega kriterija.**
2. **Samo prek slike.** Za: dobesedno po kriteriju. Proti: edini odgovor na
   neuspelo obdelavo je nova fotografija iste stvari.

**Izbrano: E1.** To ni dovoljenje za ročni vnos kot **edino** pot in zato ne
nasprotuje `ADR-028` A3 — tista odločitev je zavrnila urnik brez slike kot
zasnovo, ne popravka mreže kot dejanje. Ker gre za razširitev obsega pred
sprejemom, se po `CLAUDE.md` (faza 9b) popravi izhodišče in ne le koda:
kriteriji `V3-R09` v `docs/verzije/v3.md` dobijo vrstico o tem.

### F — dnevi na urniku

Urnik pozna **ponedeljek do petek**. Sobota in nedelja na mreži ne obstajata,
zato manjka tam ne more nastati po sami zgradbi in ne po posebnem pravilu.
Izmeničnih tednov ni že po `ADR-028`.

## Posledice

- **Kaj to olajša:** zahteva ostane na strežniku. Telefon, njegova shema in
  gradnja APK se ne dotaknejo, zato preizkus na napravi iz merila dokončanosti
  za to zahtevo ni na kritični poti.
- **Kaj to oteži:**
  - `app/vision.py` odslej kliče **dve** poti: worker za snov in zahteva pod
    `/admin` za urnik. Modul ostane edini uvoznik `openai` (`ADR-008`), a
    „klic modela se zgodi v ozadju" ni več res in v `01-arhitektura.md` tako
    ne sme pisati.
  - Nalaganje datoteke pod `/admin` je nova površina: velikost in vrsto
    datoteke je treba omejiti tam, kjer je do zdaj to delal `POST /materials`.
  - Upokojeni urniki in njihove slike rastejo brez zgornje meje in brez
    vmesnika, ki bi jih pokazal. Pri dveh na leto je to sprejeto.
- **Na katere zahteve to vpliva:** `V3-R05` mora nove poti dobiti v
  `tests/test_tesnjenje.py`, kot velja za vsako pot te verzije. Vsaka
  prihodnja zahteva, ki bo hotela urnik na telefonu, manjke po urah ali
  zgodovino urnikov z veljavnostjo, je nova zahteva in ne popravek te.
