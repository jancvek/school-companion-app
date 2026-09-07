# Namen aplikacije

## Kaj to je

Mobilna aplikacija za eno učenko (Maša), s katero po šoli fotografira
obravnavano učno snov. Slike se lokalno shranijo, nato prenesejo na domači
strežnik, kjer jih vision model prepiše in iz njih sestavi kratek kviz. Maša
na vprašanja odgovarja in ocenjuje težavnost, kar z leti tvori osebno bazo
znanja iz njenih lastnih zapiskov.

## Problem, ki ga rešuje

Učna snov se po pouku zdaj nikamor ne zapiše sistematično — zvezki in
učbeniki ostanejo neorganizirani. Ni enostavnega načina za ponavljanje ali
samopreverjanje iz dejanske snovi, ki jo je Maša tisti dan imela pri pouku.

## Kdo jo uporablja

| Vloga | Kaj počne |
|---|---|
| Maša (učenka, osnovna šola) | Fotografira snov, odgovarja na generirana vprašanja, ocenjuje težavnost |
| Lastnik sistema (starš) | Vzdržuje domači strežnik, API ključe, spremlja delovanje |

## Ključni pojmi domene

| Pojem | Pomen |
|---|---|
| Snov / material | En fotografiran zapis učne vsebine: slika + predmet + datum/ura + (po obdelavi) prepis in vprašanja |
| Predmet | Šolski predmet iz vnaprej določenega (hardcoded) seznama, npr. SLO, MAT, ANG |
| Zgodovina | Pregled preteklih posnetkov snovi, razvrščenih po predmetu in času (najnovejši prvi) |
| Arhiv | Snov, ki je na strežniku umaknjena iz pregleda in na telefonu izbrisana, na strežniku pa ostane s prepisom in vprašanji. Nadomešča brisanje; glej `docs/odlocitve/ADR-010` |
| Sinhronizacija (`sync_status`) | Stanje prenosa slike s telefona na strežnik: `pending` → `synced` |
| Status obdelave (na strežniku) | `new` → `processing` → `ready` \| `failed` — ali je vision model že prepisal sliko in sestavil vprašanja |
| Prepis (`transcript`) | Dobesedno besedilo, ki ga vision model prebere s slike |
| Povzetek (`summary`) | Dva do štirje stavki o vsebini ene snovi, da je snov prepoznavna brez branja celega prepisa |
| Berljivost (`readable`) | Ali je model s slike sploh znal brati. Neberljiva slika je obdelana, a brez prepisa in vprašanj |
| Kviz | 5–10 vprašanj in odgovorov, ki jih AI sestavi iz ene snovi |
| Težavnost | Ocena, ki jo Maša izbere po razkritju odgovora: *nisem vedela / težko / srednje / lahko*. Prva stopnja pove tudi, da odgovora ni vedela; ostale tri so težavnost. Štiri stopnje in ne tri — glej `docs/odlocitve/ADR-013` |

## Načela, ki veljajo povsod

- Aplikacija nikoli ne čaka na strežnik — fotografiranje in lokalno
  shranjevanje delujeta tudi brez povezave; prenos na strežnik gre v ločeni
  čakalni vrsti.
- En strežnik, ena baza, ena aplikacija. Kar bi lahko bila mikrostoritev,
  naj bo funkcija.
- UUID za material generira telefon, ne strežnik, da ponovni poskus prenosa
  nikoli ne podvoji zapisa.
- Zasebnost: slike učenkinih zvezkov gredo v zunanji (cloud) vision API. To
  je zavestna odločitev zaradi kvalitete prepisa slovenskega rokopisa, ne
  privzeta izbira, in mora ostati vidna uporabniku.
- Nič se ne briše, vse se upokoji. Vprašanje, ki je bilo kdaj postavljeno,
  ostane — tudi ko ga nadomesti novo in tudi ko slike, iz katere je nastalo,
  ni več. Kar ni več v uporabi, dobi datum upokojitve, ne izbrisa
  (`docs/odlocitve/ADR-011`).
- Anki je delni vzor, z zapisano mejo. Prevzemamo dnevnik odgovorov namesto
  števcev, samooceno kot način odgovarjanja in zaporedno številko spremembe
  namesto ure za sinhronizacijo. Ne prevzemamo algoritma razporejanja —
  kvize sestavlja starš, ne algoritem. Kar od Ankija kdaj še prevzamemo, mora
  priti kot zahteva, ne kot podobnost (`docs/odlocitve/ADR-013`).

## Kaj aplikacija namenoma NI

- Ni večuporabniška platforma — ena družina, en API ključ, brez
  prijave/registracije uporabnikov.
- Ni objavljena na Google Play — distribucija samo prek EAS Build APK.
- Ni orodje za analitiko ali poročanje staršem ali šoli.
- Ni zamenjava za zvezek — dopolnjuje ga, ne nadomešča papirnega
  zapisovanja.
