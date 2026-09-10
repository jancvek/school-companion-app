# ADR-019: Reševanje kviza na telefonu — odprt kviz, en poskus na postavko, preklic ne zavrže poskusov

- **Datum:** 2026-09-10
- **Nastalo pri:** V2-R02 (faza 1, po vprašanjih lastniku)
- **Status:** Sprejeto
- **Zapira:** razdelek „Odprto / ne vem še" pri `V2-R02` v `docs/verzije/v2.md`
- **Razširi:** kriterij `V2-R02` o trajanju (dva časovna žiga → trije)
- **Stoji na:** `ADR-012` (poskus je dogodek), `ADR-014` (samoocena, trajanje),
  `ADR-016` F in `ADR-011` (delovni seznam namesto kazalca), `ADR-017` C
  (`solved_at` je od `V2-R02`)

## Kontekst

Osnutek `V2-R02` je puščal odprta dva primera (kviz na pol, ponoven ogled) in
migracijo lokalne sheme. Ob razčiščevanju so se pokazali še trije, pri katerih
bi izvedba brez odločitve ubrala eno od poti z opazno različnimi posledicami
za `V2-R03` in `V2-R04`: preklic kviza, ki je že na telefonu; tretji časovni
žig; in ali sme postavka imeti več poskusov. Lastnik je vseh pet odločil po
predlogu.

## Odločitve

### A — Kviz na pol ostane odprt

Kviz, ki ga Maša zapusti pred zadnjo oceno, ostane na seznamu in se ob
naslednjem odprtju nadaljuje pri **prvi neocenjeni postavki**. Že dane ocene se
prenesejo sproti; kviz na strežniku ostane nerešen.

- Za: stanje „opuščen" ne nastane; kriterij „neocenjenega vprašanja ni" drži,
  zato rezultat `V2-R03` nikoli ni na pol prazen.
- Proti: gumb „Kvizi" ostane označen, dokler kviz ni končan. To je namen.

### B — Rešenega kviza ni mogoče pogledati znova

Po zadnji oceni kviz izgine s seznama. Na telefonu se pobriše, ko so vsi
njegovi poskusi preneseni in ga strežnik ne vrača več.

- Za: lokalna baza je delovni prostor, ne arhiv. Maša ne vidi svojih ocen
  zbranih — rezultat in statistika sta lastnikova (`V2-R03`, `V2-R04`).
- Proti: kviza za ponavljanje na telefonu ni. Če bo potreben, je nova zahteva.

### C — Preklic ne zavrže poskusov in ne zmoti reševanja

Kviz, ki ga lastnik prekliče, ko je že na telefonu:

- s seznama izgine ob naslednjem usklajevanju, **nikoli pa sredi reševanja** —
  kviz, ki je ta hip odprt, se ne pobriše;
- poskusi, ki so zanj že nastali, se prenesejo, **strežnik jih sprejme**. Dogodek
  je dejstvo (`ADR-012`), in zavrnjen poskus bi v lokalni vrsti obtičal za vedno;
- rešenost se izpelje enako kot pri vsakem kvizu; pri prikazu stanja ima
  preklic prednost pred rešenostjo.

### D — Trije časovni žigi: pokazano, razkrito, ocenjeno

Poskus nosi `shown_at`, `revealed_at` (dotik *Pokaži odgovor*) in
`answered_at`. Kriterij osnutka je naštel dva.

- Za: `ADR-014` kot mehak signal navaja „*Lahko* dve sekundi po razkritju
  odgovora" — iz dveh žigov se to ne da izračunati. Stolpec, dodan pozneje, bi
  bil prazen za vse že rešene kvize.
- Proti: en stolpec več. Časi so s telefona in lahko lažejo, če se ura telefona
  premakne; razlike med njimi so zanesljivejše od absolutnih vrednosti.

### E — Ena postavka, en poskus; prvi zmaga

Postavka kviza ima največ en poskus. Strežnik drugi poskus za isto postavko (z
drugim `id`) sprejme kot uspeh, a ga **ne zapiše**. Seznam kvizov za telefon pri
vsaki postavki pove, ali je že odgovorjena, da jo telefon preskoči.

- Za: pokrije ponovno namestitev aplikacije sredi kviza — brez tega bi Maša že
  odgovorjena vprašanja reševala znova. `V2-R03` in `V2-R04` ne rabita
  pravila, kateri od dveh poskusov velja. Zavrnitev s 4xx bi po `ADR-004`
  pomenila zapis, ki na telefonu obtiči.
- Proti: drugi poskus se tiho izgubi. Nastane lahko samo ob ponovni namestitvi
  sredi prenosa, in takrat je prvi pravi.

Idempotentnost po `id` (`ADR-012`) velja naprej: ponovljen prenos istega
poskusa ne naredi ničesar.

## Posledice

- **Kaj to olajša:** stanje kviza na telefonu je izpeljivo iz postavk in
  poskusov, brez stolpca stanja. Rezultat (`V2-R03`) ima na postavko natanko en
  poskus. Preklic ni nikoli razlog za izgubo podatka.
- **Kaj to oteži:**
  - Lokalni poskusi ne smejo biti vezani na lokalni kviz s kaskado — kviz se
    lahko pobriše (C), preden so njegovi poskusi preneseni.
  - Preklican kviz ima lahko `solved_at`. Prikaz mora vedeti, da preklic
    prevlada.
  - Strežnik mora vzdrževati enoličnost postavke v poskusih.
- **Na katere zahteve to odslej vpliva:** `V2-R02` (obseg), `V2-R03` (en
  poskus na postavko, trije žigi za trajanje), `V2-R04` (poskusi preklicanih
  kvizov obstajajo in jih mora znati obravnavati).
