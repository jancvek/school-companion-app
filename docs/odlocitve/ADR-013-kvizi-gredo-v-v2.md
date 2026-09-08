# ADR-013: Kvizi gredo v V2; `V1-R05` se umakne; V1 se zapre z R06 in R07

- **Datum:** 2026-09-07
- **Nastalo pri:** V1-R07 (faza 1–2)
- **Status:** Sprejeto
- **Umika:** `V1-R05 — Kviz v mobilni aplikaciji`
- **Popravlja:** cilj verzije 1 v `docs/verzije/v1.md`

## Kontekst

`V1-R05` ima danes tri kriterije v treh vrsticah. Med usklajevanjem se je
pokazalo, kaj kviz v resnici obsega: kviz kot shranjen objekt, sestavljalnik na
admin strani z izbiro slik, predogled, tisk vprašanj in ključa, prenos kvizov na
telefon, odgovarjanje, prenos poskusov nazaj, pregled rezultata po ocenah in
statistika čez več kvizov.

To ni ena zahteva. `CLAUDE.md` pravi „ena zahteva = en branch"; šest nepovezanih
kosov na eni veji pomeni en pregled, ki ne more biti temeljit, in en verify, ki
ne pove, kaj od tega je pokvarjeno.

## Možnosti

1. **`V1-R05` prepišemo v pet ali šest kriterijev.** Za: V1 ostane cel po
   črki svojega cilja. Proti: ena veja s šestimi kosi — natanko to, čemur se
   proces izogiba.
2. **`V1-R05` umaknemo, kviz postane V2.** Za: vsaka zahteva je pregledljiva;
   V1 se zapre in dobi tag. Proti: cilj V1 govori o kvizu in ga je treba
   popraviti.
3. **`V1-R05` pustimo minimalno, V2 doda ostalo.** Proti: kviz bi gradili
   dvakrat, drugič pa razgradili prvega.

## Odločitev

**Možnost 2.**

- `V1-R05` dobi status `Umaknjena` s kazalcem na V2. Zahteve ne brišemo —
  zapisana je bila, razdeljena je bila (`ADR-007`) in ta sled ostane.
- Cilj verzije 1 se popravi tako, da govori o tem, kar V1 res dostavi: slikanje,
  zanesljiv prenos, obdelava v prepis in vprašanja, ter pregled in umik slik.
  Vprašanja **nastanejo** v V1 (`V1-R03`); vadi se z njimi v V2.
- V1 se zapre z `V1-R06` in `V1-R07`, nato tag `v1.0.0`.
- Odpre se `docs/verzije/v2.md` z zahtevami za kviz.

Popravek cilja je dovoljen, ker je `V1-R05` v statusu `Nova` in ni bila nikoli
zgrajena. Pravilo iz faze 9b — *„po sprejemu pogajanja ni več"* — velja za
sprejete zahteve; ta ni bila niti planirana.

## Posledice

- **Kaj to olajša:** V1 dobi konec, ki ga je mogoče doseči. Vsaka zahteva V2 je
  svoja veja s svojim pregledom.
- **Kaj to oteži:** Maša do V2 z vprašanji ne dela ničesar — nastajajo in čakajo
  v bazi. To je bilo že prej res, odkar je `ADR-007` kviz izločil iz `V1-R03`;
  odslej je to vidno tudi v cilju verzije, namesto da bi bilo skrito v statusu
  ene zahteve.
- **Na katere zahteve to odslej vpliva:** `V1-R05` (umaknjena), vse zahteve V2.
