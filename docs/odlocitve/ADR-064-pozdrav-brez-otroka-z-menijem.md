# ADR-064: `/admin` za družino brez otroka — trije koraki v običajni postavitvi z menijem

- **Datum:** 2026-10-13
- **Nastalo pri:** V6-R04 (fazi 1 in 2)
- **Status:** Sprejeto
- **Stoji na:** `ADR-062` E (pravilo „brez otroka", povezave korakov) in D
  (pozdrav ne ugiba spola), `ADR-056` G (stalni meni), `ADR-060` (izvedba
  novega videza), `ADR-024` (brez skripte), `docs/poc/POC-03.md` (posnetek 08)
- **Spreminja:** `ADR-062` E — razveljavi postavitev brez menija, gumb
  „Odjava" na strani ter korake „Google, Zahtevek, Odobritev" in oznako
  „Odobreno" (glej A in B). Ostalo iz E velja naprej (glej C).

## Kontekst

`ADR-062` E je določil, da `GET /admin` za družino brez otroka izriše posnetek
08 iz `POC-03` v postavitvi registracije, brez menija. Postavka „Predmeti" v
meniju vodi na `/admin`, zato starš brez otroka ob kliku nanjo izgubi meni, ki
ga ima na vseh drugih straneh; nazaj pride samo prek korakov na strani.
Lastnik je odgovore faze 1 potrdil 13. 10. 2026.

## Odločitve

### A — stran je v običajni postavitvi z menijem

Vsebina ostanejo samo trije koraki (Dodaj otroka, Namesti aplikacijo, Poslikaj
urnik), brez police predmetov in brez kartice „danes". Stran pa je običajna
stran admina: stalni meni, izbrana postavka „Predmeti", naslov zavihka
„Predmeti", naslov na strani „Pozdravljeni, <ime>".

Gumb „Odjava" na strani odpade: `ADR-062` E ga je dodal, ker je bila stran brez
menija slepa ulica; odjava je zdaj v meniju.

### B — zgodba registracije odpade; stran je za vse družine enaka

Trak „Google · Zahtevek · Odobritev", kljukica in oznaka „Odobreno" se ne
izrišejo nikomur. Vsaka družina brez otroka vidi „Pozdravljeni, <ime>" in
„<Družina X> še nima otroka. Najprej dodaj otroka, potem lahko začne
fotografirati." Razlikovanje „registriran z Googlom" v `pregled()` in iskanje
starševe poverilnice zanj odpadeta.

Posnetek 08 s tem ni več merilo za to stran; kriterij `V6-R02` o ujemanju s
posnetki velja zanjo samo še v besedilu korakov.

### C — kar iz `ADR-062` E ostane

- Brez novega stolpca: „brez otroka" je prazen `clani.otroci()`. Velja tudi za
  ročno odprto družino; s prvim otrokom je `/admin` običajen pregled.
- **Lastnik sistema te strani ne dobi** in ostane pri običajnem pregledu.
  Prvotni razlog (stran brez menija mu skrije „Sistem") je z A odpadel;
  izjema ostane, ker lastnik upravlja sistem, ne družine, in ga k dodajanju
  otroka ne vabimo.
- Povezave korakov in nastavitev `APK_URL` so nespremenjene.

### D — izvedba brez novega gradnika

Slog `.naslednji-koraki` ostane; dobi največjo širino, ker ga ne omejuje več
okno registracije. Pravilo `.okno-kljukica` je imelo eno samo rabo in gre ven.
Skripte ni (`ADR-024`).

## Posledice

- **Kaj to olajša:** starš ima meni na vsaki strani; `pregled()` ne bere več
  poverilnic.
- **Kaj to oteži:** sveže odobren starš ne dobi več potrditve „Odobreno" —
  da je odobren, pove to, da admin sploh vidi.
- **Na katere zahteve to vpliva:** `V6-R02` (prva stran po odobritvi), `V5-R01`
  (meni je zdaj na vsaki strani odobrene družine).
- **Zavestno izpuščeno:** polica predmetov ob korakih; koraki za družino, ki
  otroka že ima.
