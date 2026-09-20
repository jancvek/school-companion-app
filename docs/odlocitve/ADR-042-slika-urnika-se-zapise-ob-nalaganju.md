# ADR-042: Slika urnika se zapiše ob nalaganju; urnik nima revizijske sledi

- **Datum:** 2026-09-20
- **Nastalo pri:** V3-R09 (faza 5, ob prvem koraku)
- **Status:** Sprejeto
- **Preglaša:** `docs/plan/V3-R09.md`, odločitvi *„Slika urnika se zapiše šele
  ob potrditvi"* in *„revizijska sled"* kot del glave tabele `schedules`.
  Plan se za nazaj ne popravlja (`CLAUDE.md` §3) — velja ta zapis.
- **Stoji na:** `ADR-041` (vnos v adminu, sinhrona obdelava), `ADR-008`
  (zakaj revizijska sled sploh obstaja), `ADR-025` (meja mape je družina)

## Kontekst

Plan `V3-R09` je odločil, da se slika urnika zapiše na disk **šele ob
potrditvi**, z utemeljitvijo, da do takrat „živi v pomnilniku zahteve".

Ta utemeljitev stoji na napačni sliki pretoka. Pot je dvokoračna:

1. `POST /admin/schedule/proposal` — starš odda datoteko, strežnik pokliče
   model, izriše mrežo in **zahteva se konča**.
2. `POST /admin/schedule` — starš odda popravljeno mrežo. To je **nova
   zahteva** in slike v njej ni.

Med korakoma strežnik ne hrani ničesar: seja nosi samo žeton in CSRF. Slika
torej ne more „počakati v pomnilniku" — nositi bi jo moral brskalnik, v
skritem polju kot base64. Pri 2 MB fotografiji je to ~2,7 MB v izrisani strani
in isto nazaj ob vsaki potrditvi.

## Možnosti

### A — zapis ob potrditvi, slika skozi skrito polje

Za: na disku ne nastane nič, česar ne bi potrdila vrstica v bazi.
Proti: ~2,7 MB base64 v HTML in v telesu vsakega `POST`; cena se plača ob
**vsakem** urejanju mreže, ne le ob opuščenem. Starš, ki mrežo popravi
dvakrat, jo plača dvakrat.

### B — zapis ob nalaganju, v `<images_dir>/<family_id>/urniki/<uuid>.jpg`

Mreža nosi samo `<uuid>`. Potrditev sliko poveže z vrstico.
Za: obrazec ostane majhen; cena nastane samo takrat, ko starš nalaganje
opusti. Sirota na disku je razred, ki ga projekt že pozna in izrecno sprejema
(`app/storage.py`: prekinjen prenos pusti ostanek v `.tmp/`).
Proti: datoteka brez vrstice, ki je nihče ne pospravi.

### C — zapis v `urniki/.tmp/`, premik ob potrditvi

Za: sirote so zbrane na enem mestu in bi jih kdaj bilo mogoče pospraviti.
Proti: dve mesti in premik za korist, ki je danes nihče ne pobere; pospravljalca
ta zahteva ne uvaja in brez njega je to samo druga mapa z istimi siroti.

**Izbrano: B.** Sirota stane prostor in je nevidna; base64 skozi obrazec stane
ob vsaki uporabi. Med „redko in nevidno" ter „vedno in vidno" je izbira ista
kot v `app/storage.py`: *„Sirota na disku je manjše zlo."*

## Revizijska sled

Plan je v glavo `schedules` uvrstil prompt, surov odgovor, ime modela in
porabo tokenov — po vzoru `materials`.

Na urniku ta sled ničesar ne nosi:

- **Noben kriterij `V3-R09` je ne zahteva.** Pri `materials` jo zahteva
  kriterij `V1-R03` izrecno.
- **`ADR-008` jo utemeljuje s primerjavo modelov** nad dejanskimi podatki.
  Primerjava se dela nad snovjo, ki je je na teden 5–25; urnik nastane dvakrat
  na leto in v vzorcu ne pomeni nič.
- **Potrjen urnik ni odgovor modela.** Starš ga vmes popravi, zato bi sled ob
  njem opisovala nekaj, česar vrstica ne vsebuje — ravno nasprotno od tega,
  čemur sled služi pri `materials`, kjer je zapis **je** odgovor modela.
- Cena bi bila pet stolpcev in nošenje surovega odgovora skozi skrito polje.

**Odločeno: `schedules` revizijske sledi nima.** Glava so `id`, `family_id`,
`child_id`, `confirmed_at`, `replaced_at`, `image_path`. Neuspeli klic se
zabeleži v dnevnik strežnika, kot povsod drugod.

## Posledice

- **Kaj to olajša:** obrazec mreže ostane majhen in hiter; tabela ostane ozka.
- **Kaj to oteži:**
  - V `<family_id>/urniki/` se nabirajo slike opuščenih nalaganj. Vmesnika, ki
    bi jih pokazal, in pospravljalca ta zahteva ne uvaja. Pri dveh nalaganjih
    na leto je to sprejeto; ko bo koga zmotilo, je to nova zahteva.
  - Zakaj je model kaj prebral narobe, se za nazaj ne da ugotoviti. Popravek
    je tako ali tako mreža pred očmi, ne analiza odgovora.
- **Na kaj to vpliva:** `image_path` je `NULL`-abilen — urnik, ki ga je starš
  potrdil brez nove slike (`ADR-041` E), slike nima in o tem ne laže.
