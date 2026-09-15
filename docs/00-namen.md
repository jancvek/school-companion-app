# Namen aplikacije

## Kaj to je

Mobilna aplikacija za učenca, s katero po šoli fotografira obravnavano učno
snov. Slike se lokalno shranijo, nato prenesejo na domači strežnik, kjer jih
vision model prepiše in iz njih sestavi kratek kviz. Učenec na vprašanja
odgovarja in ocenjuje težavnost, kar z leti tvori osebno bazo znanja iz
njegovih lastnih zapiskov. Iz iste snovi starš sestavi tudi delovne liste za
tiskanje (`docs/odlocitve/ADR-031`).

Isti domači strežnik uporablja več družin (`docs/odlocitve/ADR-025`). Vsaka
družina ima enega ali več staršev in enega ali več otrok ter vidi izključno
svoje podatke.

## Problem, ki ga rešuje

Učna snov se po pouku zdaj nikamor ne zapiše sistematično — zvezki in
učbeniki ostanejo neorganizirani. Ni enostavnega načina za ponavljanje ali
samopreverjanje iz dejanske snovi, ki jo je Maša tisti dan imela pri pouku.

## Kdo jo uporablja

| Vloga | Kaj počne |
|---|---|
| Otrok (učenec, osnovna šola) | Fotografira snov, odgovarja na generirana vprašanja, ocenjuje težavnost. Dela izključno v mobilni aplikaciji |
| Starš | Spremlja delovanje svoje družine, sestavlja kvize in delovne liste, gleda statistiko, odpira in ureja račune svojih otrok. Dela izključno v spletnem adminu. Ne vidi čez mejo svoje družine |
| Lastnik sistema | Vzdržuje domači strežnik, API ključe in varnostne kopije ter odpira nove družine. Ena sama oseba za vso namestitev. Danes je to tudi starš, jutri ni nujno (`docs/odlocitve/ADR-025`) |

## Ključni pojmi domene

| Pojem | Pomen |
|---|---|
| Družina | Obseg lastništva vseh podatkov: eden ali več staršev in eden ali več otrok. Nobena poizvedba ne prestopi njene meje; glej `docs/odlocitve/ADR-025` |
| Snov / material | En fotografiran zapis učne vsebine: slika + predmet + datum/ura + (po obdelavi) prepis in vprašanja |
| Predmet | Šolski predmet iz vnaprej določenega (hardcoded) seznama, npr. SLO, MAT, ANG |
| Zgodovina | Pregled preteklih posnetkov snovi, razvrščenih po predmetu in času (najnovejši prvi) |
| Arhiv | Snov, ki je na strežniku umaknjena iz pregleda in na telefonu izbrisana, na strežniku pa ostane s prepisom in vprašanji. Nadomešča brisanje; glej `docs/odlocitve/ADR-011` |
| Sinhronizacija (`sync_status`) | Stanje prenosa slike s telefona na strežnik: `pending` → `synced` |
| Status obdelave (na strežniku) | `new` → `processing` → `ready` \| `failed` — ali je vision model že prepisal sliko in sestavil vprašanja |
| Prepis (`transcript`) | Dobesedno besedilo, ki ga vision model prebere s slike |
| Povzetek (`summary`) | Dva do štirje stavki o vsebini ene snovi, da je snov prepoznavna brez branja celega prepisa |
| Berljivost (`readable`) | Ali je model s slike sploh znal brati. Neberljiva slika je obdelana, a brez prepisa in vprašanj |
| Vprašanja snovi | 5–10 vprašanj in odgovorov, ki jih AI sestavi iz ene snovi (V1-R03) |
| Kviz | Nabor vprašanj z odgovori iz ene ali več snovi, ki ga lastnik sestavi in objavi na admin strani (V2-R01); Maša ga reši na telefonu in vsako vprašanje oceni (V2-R02). Rešen je, ko ima vsako vprašanje oceno |
| Težavnost | Ocena, ki jo Maša izbere po razkritju odgovora: *nisem vedela / težko / srednje / lahko*. Prva stopnja pove tudi, da odgovora ni vedela; ostale tri so težavnost. Štiri stopnje in ne tri — glej `docs/odlocitve/ADR-014` |
| Delovni list | Natisnjen list, ki ga starš sestavi iz otrokove snovi: kratka razlaga, naloge s prostorom za odgovore in rešitve s postopkom na ločenem listu. Otrok ga reši s svinčnikom in v mobilni aplikaciji ne obstaja. V kodi in bazi `delovni_list`, nikoli `test` — glej `docs/odlocitve/ADR-031` |
| Opomba (k delovnemu listu) | Prosto besedilo, ki ga starš zapiše po pregledu rešenega lista. Edini zapis o tem, kako je šlo, in hkrati vhod v naslednji delovni list pri istem predmetu — glej `docs/odlocitve/ADR-032` |
| Razred | Razred osnovne šole, ki ga otrok obiskuje. Lastnost otroka, ne družine in ne namestitve; ob nastanku delovnega lista se vanj prepiše — glej `docs/odlocitve/ADR-033` |

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
  (`docs/odlocitve/ADR-012`).
- Anki je delni vzor, z zapisano mejo. Prevzemamo dnevnik odgovorov namesto
  števcev, samooceno kot način odgovarjanja in zaporedno številko spremembe
  namesto ure za sinhronizacijo. Ne prevzemamo algoritma razporejanja —
  kvize sestavlja starš, ne algoritem. Kar od Ankija kdaj še prevzamemo, mora
  priti kot zahteva, ne kot podobnost (`docs/odlocitve/ADR-014`).

## Kaj aplikacija namenoma NI

- Ni odprta platforma. Več družin je od `docs/odlocitve/ADR-025` podprtih, a
  **registracije ni**: družino in prvega starša v njej odpre lastnik sistema.
  Krog uporabnikov so njegovi znanci, zato ni pogojev uporabe, ni politike
  zasebnosti in ni izvoza podatkov. Če se krog razširi čez znance, je to nova
  verzija, ne popravek.
- Ni objavljena na Google Play — distribucija samo prek EAS Build APK.
- Ni orodje za poročanje šoli ali tretjim. Pregled ocen čez kvize (V2-R04) je
  lastnikov delovni pripomoček za pogovor z Mašo — brez izvoza, brez PDF in
  brez knjižnice za grafe (`docs/odlocitve/ADR-021` A).
- Ni zamenjava za zvezek — dopolnjuje ga, ne nadomešča papirnega
  zapisovanja.
