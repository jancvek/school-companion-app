# ADR-017: Obseg izbirnika, kdaj je snov „bila v kvizu" in odložen `solved_at`

- **Datum:** 2026-09-09
- **Nastalo pri:** V2-R01 (faza 1–2, po vprašanjih lastniku)
- **Status:** Sprejeto
- **Preglasi:** `ADR-016` v dveh točkah — stavek v (A), da se vstopi
  razlikujejo *samo* po obkljukanju, in `solved_at` v razdelku „Podatkovni
  model, ki iz tega sledi"
- **Stoji na:** `ADR-016` (oblika sestavljalnika), `ADR-015` (upokojitev),
  `ADR-011` (arhiv je svoja os)

## Kontekst

`ADR-016` je obliko sestavljalnika določil, preden je bila napisana ena sama
vrstica kode. Ob načrtovanju izvedbe so se pokazale tri mesta, kjer zapisano
ne vzdrži dobesednega branja ali si nasprotuje samo s sabo. Ta ADR jih razreši
in **`ADR-016` pusti pri miru** — po pravilu iz `CLAUDE.md` §3 se plan in
odločitev za nazaj ne prepisujeta.

## Odločitve

### A — Vstopi se razlikujejo tudi po obsegu seznama, ne le po obkljukanju

`ADR-016` (A) pravi, da vsi vstopi vodijo v isti izbirnik in se razlikujejo
„**samo** po tem, kaj je vnaprej obkljukano". Dobesedno vzeto to ne more
držati:

- Dnevni vstop gre čez vse predmete. Če bi se razlikoval le v obkljukanju, bi
  moral našteti celotno zgodovino vseh desetih predmetov, da bi obkljukal tri
  današnje slike.
- Vstop *Ročna izbira* („nič ni obkljukano") ima smisel samo, če seznam
  vsebuje tudi snov, ki je v kvizu **že bila**. Sicer je z ročno izbiro ni
  mogoče doseči in vstop ne more nič, česar ne more *Nova snov*.

Odslej velja:

| Vstop | Kaj seznam našteje | Kaj je obkljukano |
|---|---|---|
| *Nova snov* | vsa nearhivirana snov izbranega predmeta | tista, ki še ni bila v kvizu |
| *Ročna izbira* | vsa nearhivirana snov izbranega predmeta | nič |
| *Kaj smo se danes učili* | današnja nearhivirana snov, **čez vse predmete** | vsa našteta |

Namen `ADR-016` (A) — en obrazec, en predogled, ena pot skozi teste — s tem
ostane nedotaknjen: predloga, obrazec, predogled in objava so isti. Razlikuje
se ena poizvedba.

- Za: *Ročna izbira* postane uporabna; dnevni vstop ostane kratek; odkljukanje
  predlagane slike, zaradi katerega je `ADR-016` (A) sploh nastal, dela pri
  vseh treh enako.
- Proti, ki ga je treba vedeti: **seznam predmeta raste čez leto.** Pri 5–25
  slikah na teden je to po enem šolskem letu nekaj sto vrstic s sličicami. Za
  zdaj je odgovor `loading="lazy"`, isti kot na strani predmeta; če stran kdaj
  postane neuporabna, je pravi popravek ostranjevanje ali meja „zadnjih N", ne
  tiho krajšanje seznama.

### B — „Bila v kvizu" se meri po **veljavnih** vprašanjih

Ker `quiz_sources` po `ADR-016` (D) ne nastane, se privzeti izbor *Nove snovi*
izpelje iz postavk: snov je bila v kvizu, če je kakšno njeno vprašanje v
nepreklicanem kvizu. `ADR-015` je s tem odprl vprašanje, ki ga `ADR-016` ni
imel: kaj po ponovni obdelavi, ko so stara vprašanja upokojena in je nastala
nova serija?

**Šteje samo veljavno vprašanje** (`retired_at IS NULL`). Ponovno obdelana
snov se torej v *Novi snovi* spet ponudi.

- Za: ponovna obdelava se požene prav zato, ker prvi prepis ni bil dober.
  Pri nasprotnem branju popravljena snov v privzeti izbor ne bi prišla nikoli
  in bi jo bilo treba loviti z *Ročno izbiro* — gumb „Pošlji v obdelavo" in
  kvizi bi bili uporabna vsak zase, skupaj pa ne.
- Za: „veljavno vprašanje" je natanko to, kar `ADR-015` misli z „vprašanja
  materiala". Drugačna meja bi na tem mestu uvedla tretji pomen.
- Proti: snov, ki je bila v kvizu in je bila pozneje ponovno obdelana iz
  nepovezanega razloga, se spet ponudi. Odkljuka se; `ADR-016` (B) to ceno za
  privzeti izbor že sprejema.

Posledica za shemo: `quiz_items` **ne dobi svojega `material_id`.** Pot do
snovi gre prek `quiz_items.question_id → questions.material_id`, kar vzdrži
zato, ker se vprašanja od `ADR-012` in `ADR-015` nikoli ne brišejo. Ko je
material dokončno izbrisan, je `questions.material_id` `NULL`, snov pa je
razpoznavna iz denormaliziranih `questions.subject` in
`questions.material_taken_at` — točno tako, kot je `V1-R07` predvidela.

### C — `solved_at` pride šele z `V2-R02`

`ADR-016` ga je naštel v predlaganem podatkovnem modelu, kriterij v
`docs/verzije/v2.md` pa piše „(pozneje) `solved_at`". `V2-R01` ga ne bi ne
pisala ne brala.

Stolpec **v tej zahtevi ne nastane.** Doda ga migracija zahteve `V2-R02`,
skupaj s poskusi, ki ga edini znajo napolniti.

- Za: isti argument, s katerim je `ADR-016` (D) zavrnil `quiz_sources` —
  „prazna neuporabljena tabela je ostanek generatorja, ne priprava na
  prihodnost". Isto velja za stolpec. `CLAUDE.md` ima to pravilo v merilu
  dokončanosti.
- Proti: `V2-R02` bo potrebovala svojo migracijo za en `NULL`-abilen stolpec.
  To je nekaj vrstic in ne prepis podatkov.

Stanje kviza je v `V2-R01` zato dvojno: **objavljen** ali **preklican**.
Trditev iz `ADR-016` (C), da kviz nima stolpca `status`, s tem velja naprej in
se ne spreminja.

## Posledice

- **Kaj to olajša:** izbirnik je ena poizvedba na vstop in ena predloga.
  Ponovna obdelava in kvizi delujeta skupaj. Shema `V2-R01` nima nobenega
  stolpca, ki ga ta zahteva ne bi uporabljala.
- **Kaj to oteži:** seznam predmeta bo čez leto dolg (glej A). `V2-R02` mora
  prinesti svojo migracijo.
- **Na katere zahteve to odslej vpliva:** `V2-R01` (obseg poizvedb, shema),
  `V2-R02` (`solved_at` je njena, ne podedovana), `V2-R04` (statistika bo
  morala vedeti, da „snov je bila v kvizu" pomeni veljavna vprašanja).
