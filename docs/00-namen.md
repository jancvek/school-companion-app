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
| Sinhronizacija (`sync_status`) | Stanje prenosa slike s telefona na strežnik: `pending` → `synced` |
| Status obdelave (na strežniku) | `new` → `processing` → `ready` \| `failed` — ali je vision model že prepisal sliko in sestavil vprašanja |
| Prepis (`transcript`) | Dobesedno besedilo, ki ga vision model prebere s slike |
| Kviz | 5–10 vprašanj in odgovorov, ki jih AI sestavi iz ene snovi |
| Težavnost | Ocena lahko / srednje / težko, ki jo Maša doda k vsakemu vprašanju po odgovoru |

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

## Kaj aplikacija namenoma NI

- Ni večuporabniška platforma — ena družina, en API ključ, brez
  prijave/registracije uporabnikov.
- Ni objavljena na Google Play — distribucija samo prek EAS Build APK.
- Ni orodje za analitiko ali poročanje staršem ali šoli.
- Ni zamenjava za zvezek — dopolnjuje ga, ne nadomešča papirnega
  zapisovanja.
