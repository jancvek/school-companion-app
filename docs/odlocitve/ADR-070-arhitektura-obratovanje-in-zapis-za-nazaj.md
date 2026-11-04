# ADR-070: Arhitektura ≤ 400 vrstic, obratovanje v svoj dokument, razlogi v tematske ADR-je

- **Datum:** 2026-11-04
- **Nastalo pri:** V6-R05 (faza 1)
- **Status:** Sprejeto
- **Izvaja:** `ADR-022` točko 2 („selitev je samostojna zahteva")
- **Spreminja:** `CLAUDE.md` §0 (tabela dokumentov dobi `docs/03-obratovanje.md`)

## Kontekst

`docs/01-arhitektura.md` ima 2.649 vrstic; `CLAUDE.md` §0 zahteva ≤ 400 in
samo trenutno stanje. Pri branju za V6-R05 so se pokazala štiri vprašanja, ki
jih pravilo „zakaj → ADR, past → `02-izkusnje.md`" ne razreši:

1. ~110 vrstic so **postopki** (postavitev na novem stroju, varnostna kopija
   in obnova, sklop pri Googlu, preverbe zgrajene APK) in ena **odprta
   odločitev** (strežnik po nenadzorovanem ponovnem zagonu). To ni ne stanje
   ne razlog ne past.
2. Večina razlogov v `01` je nastala ob izvedbi in **nima ADR-ja**.
3. Nekaj trditev je **zastarelih** (npr. `ADMIN_UPORABNIK` v postopku
   postavitve, padel v V3-R03).
4. Ali je 400 vrstic cilj ali meja.

## Možnosti

Za (1):

1. **A** — skrčeno ostane v `01`. Proti: proračun 400 vrstic se ne izide.
2. **B** — nov `docs/03-obratovanje.md`. Za: postopek je na enem mestu, `01`
   ostane stanje. Proti: nov dokument in sprememba `CLAUDE.md` §0.
3. **C** — postopki v ADR, odprta odločitev v `backlog.md`. Proti: ADR je
   zapis odločitve, ne priročnik; postopek bi se staral v zamrznjenem zapisu.

Za (2): en zbirni ADR ali več tematskih.

## Odločitev

- **(1) B.** `docs/03-obratovanje.md` nosi postopke in odprto odločitev o
  ponovnem zagonu. Je živ dokument kot `01`, a se bere **ob potrebi**, ne ob
  vsaki zahtevi. `CLAUDE.md` §0 ga doda v tabelo.
- **(2) Tematski ADR-ji** od `ADR-071` naprej, s statusom „Sprejeto — zapis za
  nazaj". Možnosti so v njih le, kjer jih je navajalo staro besedilo.
  **Obstoječi ADR-ji se ne dopolnjujejo**; če razlog v njih že piše, v `01`
  ostane samo sklic.
- **(3) Zastarele trditve se popravijo**, ne prenesejo dobesedno: v `01` mora
  stati, kar drži za kodo. Vsak tak popravek se našteje v poročilu V6-R05.
- **(4) ≤ 400 vrstic je merilo** zahteve V6-R05 (`wc -l`), ne le cilj.
- Kar je zapisano **samo v kodi** (docstring, komentar), ne šteje za ohranjeno.
- Kratka dejstva, na katera kažejo komentarji v kodi (`docs/01-arhitektura.md`),
  ostanejo v `01`, da komentarji ne postanejo napačni.

## Posledice

- **Olajša:** `01` je mogoče prebrati v celoti; razlog se poišče po naslovu
  ADR-ja.
- **Oteži:** sprememba postopka zdaj pomeni popravek `03`, ne `01`; dva živa
  dokumenta namesto enega.
- **Vpliva na:** vsako prihodnjo fazo 8 — dopolni se `01` (stanje) ali `03`
  (postopek), razlog gre v ADR, past v `02`.
