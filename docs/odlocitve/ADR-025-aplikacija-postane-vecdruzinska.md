# ADR-025: Aplikacija postane večdružinska; družina je lastnik vseh podatkov

- **Datum:** 2026-09-14
- **Nastalo pri:** V3 (pogovor pred verzijo)
- **Status:** Sprejeto
- **Preglasi:** `docs/00-namen.md`, razdelek „Kaj aplikacija namenoma NI",
  prva alineja: *„Ni večuporabniška platforma — ena družina, en API ključ,
  brez prijave/registracije uporabnikov."*

## Kontekst

Doslej je bil sistem namenjen eni učenki in enemu lastniku. Meja med njunima
podatkoma ni obstajala, ker ni bilo česa mejiti: vse v bazi je bilo njuno.
Prav zato nobena tabela nima lastnika in nobena poizvedba nima pogoja, ki bi
ga preverjal.

Lastnik zdaj hoče, da isti strežnik uporablja več družin — znanci, ne stranke.
Vsaka družina ima enega ali več staršev in enega ali več otrok.
Funkcionalnost ostane ista kot danes; edina novost je, da obstaja več ločenih
kopij istega sveta.

Ključno pri tem je, kaj *ni* zahtevano: ni odprte registracije, ni pravnega
okvira, ni deljenja med družinami, ni izvoza. Zahtevana je izolacija, ne
platforma.

## Možnosti

1. **Ena namestitev na družino.** Vsak prijatelj dobi svoj strežnik in svojo
   bazo. Za: nič kode, popolna izolacija po konstrukciji, nobene nove napake v
   obstoječih poizvedbah. Proti: pet strojev, pet posodobitev, pet API ključev
   za OpenAI in pet varnostnih kopij. Lastnik bi vzdrževal pet sistemov ali pa
   bi to prevalil na ljudi, ki tega ne znajo.
2. **Ena namestitev, družina kot lastnik podatkov.** Za: en stroj, ena
   posodobitev, ena varnostna kopija; model družine je tako ali tako potreben,
   ker ima ena družina več oseb. Proti: izolacija odslej ni lastnost okolja,
   ampak lastnost kode — vsaka pozabljena beseda `WHERE` je uhajanje tujih
   podatkov.
3. **Polna platforma.** Odprta registracija, pogoji uporabe, politika
   zasebnosti, izvoz in izbris podatkov. Za: edina poštena pot, če bi krog
   presegel znance. Proti: večji kos dela kot V1 in V2 skupaj, za potrebo, ki
   je nihče nima.

## Odločitev

**Možnost 2.** Ena namestitev; **družina je edini obseg lastništva** vseh
podatkov.

Model:

- **Družina** ima ime in nič drugega. Ni naslova, ni plačila, ni nastavitev.
- **Uporabnik** pripada natanko eni družini in ima vlogo `parent` ali `child`.
- **Lastnik sistema** je ločena reč od starša. Danes sta to ista oseba, jutri
  ne. Lastnik sistema vzdržuje strežnik, ključe in varnostne kopije ter odpira
  družine; starš je skrbnik svoje družine in ne vidi čez njeno mejo. Ker se ta
  ločnica pozneje ne da uvesti brez migracije, nastane zdaj.
- **Registracija je zaprta.** Družino in prvega starša v njej odpre lastnik
  sistema. Nihče se ne prijavi sam.

Tehnične meje, ki jih ta odločitev nalaga:

- **Izolacija ne sme biti stvar pazljivosti.** Repozitoriji ne smejo znati
  brati brez družine: `family_id` je argument konstruktorja
  (`MaterialsRepository(session, family_id)`), brez privzetka in brez metode,
  ki ga obide. Pozabljen pogoj mora biti napaka ob prevodu ali ob zagonu, ne
  tiho uhajanje.
- **Slike na disku se ločijo po družinah.** Pot do slike ne sme biti uganljiva
  iz samega UUID-ja brez preverbe družine.
- **Zraven gre regresijski test, ki dokaže tesnjenje:** dve družini, vsaka s
  svojo snovjo, in preverba, da nobena pot ne vrne tuje. Brez tega je ta
  odločitev samo namera.

## Posledice

- **Kaj to olajša:** več otrok v eni družini postane mogoče, kar je koristno
  že za lastnika samega, ne šele za prijatelje.
- **Kaj to oteži:**
  - Nastane nov razred napake, ki ga sveža baza z eno družino nikoli ne
    pokaže. Vsak test, ki teče nad eno samo družino, je od zdaj naprej
    nepopoln.
  - Varnostna kopija preide iz lastnikove skrbi zase v skrb za tuje otroke.
    Odprta težava „backup" iz pregleda 11. 9. 2026 s tem neha biti odložljiva.
  - Zasebnostna cena iz `docs/00-namen.md` (slike zvezkov gredo v zunanji
    vision API) odslej velja za tuje otroke. Lastnik mora to povedati vsakemu
    staršu, ki se pridruži. To je dogovor med znanci in ne pravni dokument —
    a mora biti izrecen, ne privzet.
- **Zavestno izpuščeno:** pogoji uporabe, politika zasebnosti, izvoz in izbris
  podatkov na zahtevo. Krog uporabnikov so znanci lastnika. **Če se krog
  razširi čez znance, to ni popravek te odločitve, ampak nova verzija**, in
  možnost 3 zgoraj je njeno izhodišče.
