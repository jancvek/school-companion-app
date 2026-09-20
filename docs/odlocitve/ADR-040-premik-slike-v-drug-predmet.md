# ADR-040: Premik slike v drug predmet

- **Datum:** 2026-09-20
- **Nastalo pri:** V3-R10
- **Status:** Sprejeto

## Kontekst

Otrok ob slikanju včasih izbere napačen predmet. Snov je potem na napačnem
seznamu predmeta, v izbirniku kvizov pod napačnim predmetom, njena vprašanja pa
štejejo v statistiko napačnega predmeta. Popraviti jo je mogoče samo na
telefonu pred prenosom, kar v praksi pomeni nikoli.

Predmet živi na treh mestih: `materials.subject` (telefon ga pošlje ob
prenosu), `questions.subject` (kopija ob nastanku vprašanja, `ADR-012`,
`ADR-017` B) in `quizzes.subject` z imenom kviza (ob objavi). Na telefonu je
še lokalni `materials.subject`, ki ga strežnik nikoli ne prepiše.

## Možnosti

**A — Telefon**

1. **A1 — samo strežnik.** Za: pogodba s telefonom ostane, brez lokalne
   migracije, brez APK. Proti: zgodovina na telefonu kaže prvotni predmet.
2. **A2 — strežnik in telefon.** Za: ena resnica povsod. Proti: nov kanal
   strežnik → telefon za posamezne snovi, lokalna migracija, preizkus na
   napravi; približno trikrat večja zahteva za zaslon, ki ga otrok redko gleda.

**B — Vprašanja, ki so iz snovi že nastala**

1. **B1 — vsa vprašanja snovi, veljavna in upokojena.** Za: statistika se
   preseli k pravemu predmetu; upokojena vprašanja z zgodovino poskusov ne
   ostanejo pod napačnim. Proti: statistika predmeta za nazaj se spremeni.
2. **B2 — samo veljavna.** Proti: poskusi upokojenih ostanejo pod napačnim
   predmetom, ista snov pa je v statistiki razcepljena na dva predmeta.
3. **B3 — nič.** Proti: statistika in izbirnik si ne bi bila enotna.

**C — Snov v obdelavi**

Worker vprašanja ustvari v `zapisi_izid` in jim predmet prepiše iz snovi, ki
jo prebere tik pred zapisom. Če bi se predmet spremenil med tem branjem in
commitom workerja, bi nova vprašanja dobila star predmet, `UPDATE` vprašanj
pa jih ne bi videl, ker še niso commitana.

1. **C1 — pogojni `UPDATE materials ... WHERE status <> 'processing' AND
   archived_at IS NULL`**, nato v isti transakciji `UPDATE questions`. Na
   Postgresu počaka na zaklep vrstice, ki ga drži worker, in pogoj preveri
   znova nad commitano vrstico; ko snov ni več v obdelavi, so vprašanja
   commitana in jih drugi stavek ujame. Isti vzorec kot prevzem v workerju.
2. **C2 — premik dovoljen vedno.** Proti: zgoraj opisano okno.

**D — Objavljeni kvizi**

1. **D1 — ne spreminjajo se.** Objavljen kviz je zamrznjen (`ADR-016` E),
   ime „MAT — 9. 9. 2026" je že natisnjeno.
2. **D2 — preimenujejo se.** Proti: kviz čez več snovi bi lahko postal
   mešan, ime pa ne bi bilo več tisto na papirju.

## Odločitev

**A1, B1, C1, D1.** Poleg tega:

- Izbrati je mogoče samo enega od desetih predmetov iz `PREDMETI`; neznana
  koda vrne 400. Snov z neznano kodo se lahko premakne k znanemu predmetu.
- Arhivirana snov se ne premika (`ADR-011`: arhiv je umik, ne urejanje).
- Prvotni predmet se nikjer ne hrani — brez novega stolpca in brez migracije.
- Premik ni nepovraten (premakne se lahko nazaj), zato vmesne potrditvene
  strani ni, enako kot pri „Pošlji v obdelavo".

## Posledice

- Kaj to olajša: napačno oznako popravi starš v dveh klikih; statistika in
  izbirnik kvizov sta usklajena s popravljenim predmetom.
- Kaj to oteži: telefon in strežnik se lahko glede predmeta razlikujeta
  (znana omejitev). Statistika predmeta ni več nespremenljiva za nazaj.
- Na katere zahteve to odslej vpliva: `V3-R09` (manjkajoče slike po urniku
  bodo brale popravljen predmet, kar je pravilno); vsaka prihodnja pot, ki
  predmet kopira iz snovi, mora upoštevati, da se ta lahko spremeni.
