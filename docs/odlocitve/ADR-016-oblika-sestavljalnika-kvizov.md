# ADR-016: Oblika sestavljalnika kvizov — en izbirnik, brezstanjski predogled, brez randoma

- **Datum:** 2026-09-09
- **Nastalo pri:** V2-R01 (faza 1, zasnova)
- **Status:** Sprejeto
- **Zoži:** kriterije `V2-R01` v `docs/verzije/v2.md` (random, zavračanje
  posameznega vprašanja in „premešaj znova" gredo med predloge za nadgradnjo)
- **Stoji na:** `ADR-015` (vprašanje se upokoji), `ADR-011` (arhiv je svoja os)

## Kontekst

`V2-R01` je bila zapisana kot skica: „sistem vzame določeno število naključnih
vprašanj na sliko, jaz jih pregledam in kviz objavim". Ob zasnovi se je
pokazalo šest mest, kjer skica dopušča opazno različne izvedbe. Ker gre za
obliko, ki jo bosta `V2-R02` in `V2-R03` prevzeli takšno, kot bo, so odločitve
zapisane zdaj in ne odkrite v kodi.

## Odločitve

### A — En izbirnik s tremi vstopi, ne dva ločena toka

Prvotni predlog sta bili dve akciji: „sestavi dnevni kviz" in „izberi slike".
Namesto tega **vsi vstopi vodijo v isti izbirnik slik** in se razlikujejo samo
po tem, kaj je vnaprej obkljukano.

- Za: en obrazec, en predogled, ena pot skozi teste. In v praksi boljše tudi za
  operaterja — ko je ena od predlaganih slik zamazana ali dvojnik, jo odkljuka,
  namesto da bi zapustil samodejni tok in začel v ročnem.
- Proti: dnevni kviz zahteva en pogled več (najprej izbor, potem potrditev).
  Sprejeto — ta pogled je hkrati edina priložnost videti, kaj boš objavil.

### B — Privzeti izbor je „še ni bilo v kvizu", ne „danes"

Za predmetni vstop („Nova snov") je privzeti izbor **vsa snov predmeta, ki še
ni bila v nobenem kvizu**, ne snov današnjega dne.

- Za: če kviza kak dan ne narediš, snov tistega dne ne izpade tiho — ostane v
  izboru, dokler je ne uporabiš. Seznam se krajša sam. To je isti vzorec, ki
  ga `ADR-011` že uporablja pri `GET /materials/pending-deletion`: strežnik vrne
  cel delovni seznam, nihče si ne rabi zapomniti kazalca, in zamujen obhod nič
  ne pokvari.
- Proti: ob prvem zagonu je obkljukano vse, kar je bilo kdaj obdelano. Rešuje
  se z odkljukanjem in z opozorilom v predogledu, ne z molčečo omejitvijo —
  tiho odrezan izbor je huje od dolgega.

**„Danes" ostane, a kot svoj vstop:** „Kaj smo se danes učili" gre **čez vse
predmete** in obkljuka snov današnjega dne. Tam je „danes" cel pomen akcije in
zaostanka ne sme pobirati.

„Danes" pomeni `taken_at` (trenutek posnetka, ne prejema) v pasu
`Europe/Ljubljana`, od polnoči do polnoči. `taken_at` zato, ker je to trenutek
snovi; razlika se pokaže samo pri posnetku pozno zvečer, ki se prenese po
polnoči, in takrat je pravilna prav ura posnetka.

**Preklican kviz ne šteje za „bil v kvizu".** Snov iz preklicanega kviza se
spet ponudi — kviz je bil preklican prav zato, ker ni bil pravi.

### C — Predogled je brezstanjski; stanja `osnutek` ni

Osnutek `V2-R01` je predvidel stanja `osnutek → objavljen → rešen`. Predogled
namesto tega **ničesar ne shrani**: izbor potuje skozi skrita polja obrazca in
zapis v bazi nastane šele ob „Objavi", v eni transakciji.

- Za: v bazi ne nastajajo mrtvi osnutki, ki jih nihče nikoli ne pospravi, in
  seznam kvizov kaže samo kvize. Brez JavaScripta je to izvedljivo s čistim
  HTML obrazcem.
- Proti: zaprt zavihek med predogledom pomeni izgubljen izbor. Sprejeto —
  sestavljanje traja pol minute.

Posledica: **kviz nima stolpca `status`.** Stanje se izpelje iz `canceled_at`
in `solved_at`, tako kot je arhiv v `ADR-011` ločena os in ne peto stanje
`status`. Objavljen kviz je preprosto kviz, ki obstaja.

### D — Brez randoma; prvih N po `position`; brez `quiz_sources`

Vzame se prvih N veljavnih vprašanj po `position`, privzeto **3**, s poljem v
obrazcu. Random, zavračanje posameznega vprašanja v predogledu in „premešaj
znova" gredo med predloge za nadgradnjo.

- Za: manj kode, en sam predvidljiv izid, in noben del ni zgrajen, preden se
  ve, ali je potreben.
- Proti, ki ga je treba vedeti: **„prva tri" pomeni vrstni red, kot ga je
  vrnil model, ne izbora po kakovosti.** Vprašanja od četrtega naprej ne pridejo
  nikoli na vrsto, čeprav so plačana, in ista slika da v dveh kvizih ista
  vprašanja. To je zavestna cena prve različice, ne spregled.

**`quiz_sources` (recept za ponovno mešanje) v tej zahtevi ne nastane.** Brez
randoma je recept izpeljiv iz postavk; prazna neuporabljena tabela je ostanek
generatorja, ne priprava na prihodnost.

### E — Postavka hrani `question_id` **in** kopijo besedila

`quiz_items` hrani tuji ključ na vprašanje in hkrati prepis besedila vprašanja
in odgovora ob objavi.

- Ključ zato, ker `V2-R04` potrebuje stabilno identiteto vprašanja (mogoč šele
  po `ADR-015`).
- Kopija zato, ker mora biti kviz izpred let berljiv tudi, če je bila izvorna
  snov medtem dokončno izbrisana in je `material_id` na `NULL` (`ADR-012`).
  Dve ravni obrambe za kriterij „objavljen kviz zamrzne svoje postavke": ena
  za identiteto, ena za berljivost.

### F — Objavljen kviz se prekliče, ne izbriše

Napačno objavljen kviz dobi `canceled_at`. Brisanja ni.

- Isti razlog kot `ADR-011`: zapis, ki ga je telefon morda že prenesel, mora
  imeti stanje, ki ga je mogoče sinhronizirati; izbrisane vrstice ni mogoče
  sporočiti. `V2-R02` bo preklicane kvize preprosto nehala pošiljati, po istem
  vzorcu kot delovni seznam pri arhivu.

### G — Katera snov se sploh ponudi

Samo `status='ready'`, `readable=true` in vsaj eno veljavno vprašanje.
Arhivirana snov se **ne** ponudi: arhiv pomeni pospravljeno, vprašanja pa
preživijo arhiv zaradi statistike, ne zato, da bi jih še kvizirali.
(„Ponovi pred testom iz starejše snovi" je svoja, pozneje zapisana zahteva.)

Snov, ki še ni obdelana ali je obdelava pri njej padla, je v izbirniku
**vidna, a neizbirna, z razlogom**, in predogled šteje, koliko je bilo takih.
Molčeč izpust bi pomenil kviz iz polovice dneva, brez sledi, da manjka pol.

## Podatkovni model, ki iz tega sledi

Dokončna oblika se zapiše v plan `V2-R01` (faza 4) in v
`docs/01-arhitektura.md` (faza 8); tu je zapisano samo, kar odločitve zgoraj že
določajo.

`quizzes`: `id` (UUID, strežnik), `name`, `subject` **nullable** (`NULL` =
kviz čez več predmetov), `created_at`, `canceled_at` nullable, `solved_at`
nullable (izpelje `V2-R02`).

`quiz_items`: `id`, `quiz_id` (FK, `ON DELETE CASCADE` — postavka brez kviza
nima pomena), `question_id` (FK, `ON DELETE SET NULL`), `position` (zaporedje v
kvizu), `question_text`, `answer_text`.

## Posledice

- **Kaj to olajša:** `V2-R01` je ena veja z enim pregledom. Telefon (`V2-R02`)
  dobi kviz, ki je zaprt objekt s celotno vsebino — delta sinhronizacija vseh
  vprašanj ni potrebna.
- **Kaj to oteži:** dokler `V2-R02` ni zgrajena, kviz obstaja samo v adminu in
  ga Maša ne vidi. To je zavestno.
- **Na katere zahteve to odslej vpliva:** `V2-R01` (kriteriji prepisani),
  `V2-R02` (prenos objavljenih in nepreklicanih), `V2-R03` (postavka nosi
  kopijo besedila, zato je rezultat berljiv tudi brez izvorne snovi).
