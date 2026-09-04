# ADR-002: Nastavitve Claude vtičnika v `apps/mobile` ostanejo

- **Datum:** 2026-09-03
- **Nastalo pri:** V1-R01
- **Status:** Sprejeto

## Kontekst

`npx create-expo-app` je pri postavitvi `apps/mobile` (faza 5) poleg projekta
ustvaril tudi mapo `.claude/` z eno datoteko, ki vklopi uradni Expo vtičnik za
Claude Code:

```json
{ "enabledPlugins": { "expo@claude-plugins-official": true } }
```

Datoteka je pristala v prvem commitu zahteve. Pregledovalec jo je upravičeno
javil dvakrat, iz dveh razlogov:

- Plan `docs/plan/V1-R01.md` je v tabeli „Vpliv" ne našteva — je torej
  sprememba obsega, ki ni bila dogovorjena.
- `CLAUDE.md`, trdi rob 4, izrecno pravi, da nastavitvene datoteke Claude Code
  niso modelove. Ograja (`git-guard.ps1`) zato blokira vsak ukaz, ki to pot
  omeni — model je torej ne more niti prebrati z lupino niti odstraniti.

Vsebinsko gre za nastavitev razvojnega okolja, ne za ograjo in ne za del
aplikacije. Claude Code bere nastavitve iz korena projekta; ta datoteka vpliva
samo na delo znotraj `apps/mobile`.

## Možnosti

1. **Odstraniti jo** — Za: diff zahteve ostane točno tak, kot ga opisuje plan;
   nič nedogovorjenega. Proti: vtičnik, ki pozna Expo, je pri delu na tem
   modulu koristen; datoteko bi naslednji `create-expo-app` tako ali tako
   vrnil.
2. **Obdržati tiho** — Za: nič dela. Proti: v repozitoriju ostane
   nedokumentirana nastavitev, ki jo bo vsak nadaljnji pregled javljal znova,
   ker izgleda kot poseg v ograjo.
3. **Obdržati in zapisati odločitev** — Za: koristna nastavitev ostane, hkrati
   pa je jasno, od kod je prišla in da ni poskus odpiranja ograje.
   Proti: en dokument več.

## Odločitev

Izbrana je možnost 3. Datoteka `apps/mobile/.claude/settings.json` ostane v
repozitoriju.

Utemeljitev: gre za nastavitev razvojnega orodja, omejeno na `apps/mobile`, in
ne za ograjo. Ker pa jo ograja obravnava enako kot ograjo, mora obstajati
zapis, sicer je videti kot tiho odstopanje od plana.

Odločitev je sprejel lastnik; model je datoteko samo javil.

## Posledice

- **Kaj to olajša:** delo na `apps/mobile` s vtičnikom, ki pozna Expo.
- **Kaj to oteži:** nič v teku dela. Model te datoteke ne more spreminjati ne
  brisati — če jo bo kdaj treba popraviti, to naredi lastnik.
- **Na katere zahteve to odslej vpliva:** na nobeno vsebinsko. Velja kot
  precedens za datoteke, ki jih generatorji projektov pustijo za sabo: če
  ostanejo, dobijo zapis; če ne sodijo v projekt, gredo ven.

## Druga datoteka iz iste predloge

`create-expo-app` je pustil tudi `apps/mobile/scripts/reset-project.js` —
mrtvo skripto, ki ob zagonu izbriše `src` in `scripts`. Zanjo je bila
odločitev nasprotna: **gre ven.** Odstrani jo lastnik, ker dovoljenjska plast
modelu zavrne vsak ukaz z besedo `scripts`.

Ta ADR ne trdi, da je odstranitev že izvedena — ob nastanku tega zapisa
datoteka še obstaja. Če jo bereš in `git ls-files apps/mobile/scripts` še
vedno vrne zadetek, odstranitev ni bila opravljena.
