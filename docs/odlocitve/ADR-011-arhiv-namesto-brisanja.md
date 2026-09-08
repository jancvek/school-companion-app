# ADR-011: Arhiv namesto brisanja; telefon briše in to potrdi

- **Datum:** 2026-09-07
- **Nastalo pri:** V1-R07 (faza 1–2, pred implementacijo)
- **Status:** Sprejeto
- **Razveljavlja:** *„Brisanje velja samo na strežniku. Slika na telefonu
  ostane."* — `V1-R04`, „Razčiščeno v fazi 1" v `docs/verzije/v1.md`

## Kontekst

Slika, ki jo lastnik izbriše na admin strani, na telefonu ostane za vedno.
Poslati je ni več mogoče (`synced` je upload worker nikoli več ne pobere), zato
je tam mrtva teža, ki jo Maša še vedno vidi v Zgodovini.

Popraviti to ni samo stvar novega klica. `MaterialsRepository.pobrisi()` briše
trdo — vrstica gre, datoteka gre in za sabo ne ostane nič. **„Kaj je bilo
izbrisano" torej ni podatek, ki obstaja**, in dokler ne obstaja, telefonu ni
mogoče povedati ničesar.

## Možnosti

1. **Nagrobniki.** Tabela `deleted_materials`, telefon vpraša po seznamu.
   Za: majhno. Proti: prepis, povzetek in vprašanja gredo skupaj s sliko;
   posnetek, ki je na telefonu obtičal v `pending`, material ob naslednjem
   prenosu obudi (*data resurrection*).
2. **Telefon pošlje svoje id-je, strežnik pove, katerih nima.** Za: brez
   spremembe sheme. Proti: stoji na sklepu *odsotnost = izbrisano* — obnovitev
   baze iz starejše varnostne kopije ali prazen volumen po ponovni postavitvi
   Dockerja bi Maši pobrisal telefon. Napačna smer tveganja pri sistemu, kjer je
   telefon do prenosa edina kopija.
3. **Potisna obvestila (FCM).** Zahteva Google Play, dev build in zunanjo
   storitev. Nesorazmerno; „kar bi lahko bila mikrostoritev, naj bo funkcija".
4. **Arhiv — mehko brisanje s koristnim tovorom.** Slika se na strežniku
   umakne iz pregleda, a ostane; telefon jo zbriše in to potrdi.

## Odločitev

**Možnost 4.** Podrobnosti, ki so del te odločitve:

**Arhiv je svoja os, ne peto stanje.** `archived_at TIMESTAMPTZ NULL` (`NULL` =
aktivna). `status` je avtomat obdelave (`new → processing → ready | failed`) in
ga berejo `worker.py`, `obdelava.py` in repozitorij; arhiviran zapis je lahko
hkrati `ready`. Isti razlog kot pri `readable`, ki tudi ni peti status
(`ADR-009`).

**Delovni seznam namesto kurzorja.** Strežnik vrne materiale, ki so
`archived_at IS NOT NULL AND device_deleted_at IS NULL`. Seznam se sam krajša,
je idempotenten in **telefon si ne zapomni ničesar** — brez migracije lokalne
sheme. Časovni žig zadnje sinhronizacije je bil zavrnjen: pade na razliki ur in
na transakciji, ki dobi žig `T`, potrdi pa se, ko je telefon kurzor že premaknil
čezenj. Taka izguba se ne pokaže na testih, ampak čez pol leta kot ena slika,
ki na telefonu ostane.

**Potrditev pomeni „tega materiala na tej napravi ni več"**, ne „pravkar sem ga
izbrisal" — sicer po ponovni namestitvi aplikacije seznam nikoli ne pade na nič.
Zapiše se v `device_deleted_at`.

**Vrstni red na telefonu: vrstica, nato datoteka, nato potrditev.** Potrditev
šele, ko je lokalno opravljeno. Osirotela datoteka je nevidna in ozdravljiva
(vse se imenujejo `<id>.jpg`), vrstica brez datoteke je vidna okvara v
Zgodovini. Ponovljena potrditev je neškodljiva — prenos je *at-least-once*.

**Na telefonu ni nobene vidne oznake.** Slika tiho izgine. Ta zahteva zato v
aplikacijo ne prinese novega vidnega vedenja.

**`POST /materials` za arhiviran zapis vrne `410 Gone`** (v telesu
`archived: true`, a telefon se odloča po statusni kodi in telesa ne
razčlenjuje — nalagalec datotek ga ne izpostavlja zanesljivo). Brez tega
posnetek, ki je na telefonu obtičal v `pending` (aplikacija se je ubila med
strežnikovim 201 in `markSynced`) in je bil medtem arhiviran in potrjen, na
telefonu ostane za vedno — z delovnega seznama je namreč že padel.

**Worker arhiviranih ne pobira** in gumb „Pošlji v obdelavo" je pri njih skrit.
Za sliko, ki si jo umaknil, ne plačamo klica.

**Dve stopnji čiščenja.** „Počisti sliko" pobriše samo datoteko in je dovoljena
kadarkoli. „Izbriši dokončno" pobriše tudi vrstico in je dovoljena **šele, ko je
`device_deleted_at` postavljen** — sicer telefon za brisanje nikoli ne izve in
smo spet tam, kjer smo začeli. Oboje je ročno.

**Vrnitve iz arhiva ni.** Zavrnjena zavestno: slika je na telefonu takrat že
izgubljena, material bi znova postal viden samo na strežniku, gumb pa bi moral
obstajati, biti testiran in vzdrževan. Če se kdaj pokaže potreba, je to nova
zahteva — ne zakomentirana koda, ki se stara.

## Posledice

- **Kaj to olajša:** prepis, povzetek in vprašanja preživijo umik slike, kar je
  pogoj za `ADR-012`. Ponovni prenos arhiviranega zapisa materiala ne obudi.
  Telefon ne nosi stanja sinhronizacije, zato tu ni nove lokalne migracije.
- **Kaj to oteži:**
  - Vsaka poizvedba admin pregleda mora odslej izločiti arhivirane. Kjer se to
    pozabi, se arhiv tiho ne skrije — zato je to kriterij sprejemljivosti in ne
    podrobnost izvedbe.
  - Baza raste, ker se privzeto nič ne briše. Pri 5–25 slikah na teden je to
    zanemarljivo; velike so datoteke, ne vrstice, in te se dajo počistiti ločeno.
  - Brisanje ni več v celoti v rokah admin strani: dokončno brisanje čaka na
    telefon. Če telefona ni več (izguba, tovarniške nastavitve), vrstica ostane
    trajno nepotrjena. Tak primer se reši ročno in ta ADR ga ne pokriva.
- **Na katere zahteve to odslej vpliva:** `V1-R04` (pomen gumba za brisanje),
  `V1-R02` (`POST /materials` dobi novo polje v odgovoru), vse prihodnje
  zahteve, ki berejo seznam materialov.
