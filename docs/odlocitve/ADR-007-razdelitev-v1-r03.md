# ADR-007: V1-R03 se razdeli na obdelavo in kviz

- **Datum:** 2026-09-05
- **Nastalo pri:** V1-R03 (faza 2 — preverba smiselnosti, pred začetkom dela)
- **Status:** Sprejeto
- **Zoži:** obseg zahteve `V1-R03` v `docs/verzije/v1.md`

## Kontekst

`V1-R03 — Vision obdelava in kviz` je bila zapisana kot ena zahteva s šestimi
kriteriji. Prvi štirje živijo na strežniku (worker zanka, klic vision modela,
zapis rezultata, obravnava napak), zadnja dva v mobilni aplikaciji (prikaz
vprašanj, ocena težavnosti).

Med njima ni skupne kode. Sta v dveh jezikih, v dveh mapah, z dvema
načinoma testiranja. Skupaj imata dovolj datotek, da bi en sam pregled v
fazi 7 pokrival hkrati Python worker, klic zunanjega API-ja, migracijo sheme,
React zaslon in lokalno bazo na telefonu — kar je natanko tisto, kar naj bi
delitev na zahteve preprečila.

Obstaja tudi vrstna odvisnost, ki v skupni zahtevi ni vidna: **dokler ni
izmerjeno, kako dobro model prebere slovenski rokopis, ni znano, ali se
vmesnik za vprašanja sploh splača graditi.** `v1.md` to tveganje že priznava
(„Pred V1-R01 priporočena preverba"), a ga skupna zahteva sili obiti.

Ločeno je lastnik zahteval operatersko spletno stran (glej
`docs/odlocitve/ADR-006`), ki nastane pred obdelavo in ji služi kot testno
okolje.

## Možnosti

1. **Ostane ena zahteva.** Za: nič dela z dokumentacijo. Proti: ena veja s
   ~15 datotekami v dveh jezikih; en pregled čez oboje; kviz nastane, preden
   je znano, ali so vprašanja uporabna.
2. **Razdelitev na dve zahtevi.** Za: vsaka plast svoj pregled in svoj
   verify; med njima je točka, na kateri se da izmeriti kvaliteto prepisa in
   se odločiti. Proti: dva cikla faz namesto enega.
3. **Razdelitev in preštevilčenje po vrstnem redu izvedbe.** Za: številke
   berejo kot zaporedje. Proti: `V1-R03` je že omenjen v komentarjih kode
   (`app/models.py`, `app/routers/materials.py`, `app/storage.py`) in v
   `docs/01-arhitektura.md` kot „vision obdelava". Preštevilčenje bi te
   zapise spremenilo v laž.

## Odločitev

Izbrana je možnost 2.

| ID | Obseg | Vrstni red izvedbe |
|---|---|---|
| `V1-R04` | Admin pregled slik po predmetih (ADR-006) | 1. |
| `V1-R03` | Vision obdelava na strežniku | 2. |
| `V1-R05` | Kviz v mobilni aplikaciji | 3. |

**Številka zahteve ni vrstni red izvedbe.** Vrstni red pove polje „Odvisna
od" pri vsaki zahtevi. `V1-R03` obdrži svojo številko, ker se nanjo sklicujejo
komentarji v obstoječi kodi.

Iz `V1-R03` se izločita zadnja dva kriterija (prikaz vprašanj v aplikaciji in
zapis ocene v `question_feedback`) in postaneta `V1-R05`. Odprto vprašanje o
arhiviranju neodgovorjenih materialov gre z njima.

`V1-R03` hkrati dobi kriterije, ki v prvotnem zapisu manjkajo, izhajajo pa iz
namena „spremljati delovanje ChatGPT API-ja": poslani prompt, surov odgovor
modela, ime modela in poraba tokenov se shranijo ob zapisu in prikažejo na
admin strani.

## Posledice

- **Kaj to olajša:** med obdelavo in kvizom nastane točka odločitve. Če se
  prepis slovenskega rokopisa izkaže za neuporaben, se `V1-R05` premisli ali
  odpove, ne da bi bilo delo že vloženo. `V1-R04` pred tem postavi okolje, v
  katerem je ta meritev sploh vidna.
- **Kaj to oteži:** trije cikli faz namesto enega; tri veje, trije pregledi,
  trije verify.
- **Na katere zahteve to odslej vpliva:** `V1-R03` je odvisna od `V1-R04`,
  `V1-R05` od `V1-R03`. Kriteriji `V1-R01` in `V1-R02` ostanejo nedotaknjeni.
