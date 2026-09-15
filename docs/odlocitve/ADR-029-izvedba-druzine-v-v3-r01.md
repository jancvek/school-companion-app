# ADR-029: Izvedba družine v V3-R01 — izbira pred prijavo, obdelava po družinah, družina na vprašanjih

- **Datum:** 2026-09-14
- **Nastalo pri:** V3-R01 (faza 1)
- **Status:** Sprejeto
- **Stoji na:** `ADR-025` (družina je edini obseg lastništva)
- **Preglaša:** `docs/verzije/v3.md`, `V3-R01`, dva kriterija — ime stolpca
  `families.ime` (postane `name`) in izpeljavo družine na `questions` iz
  starša (postane stolpec). Obe spremembi sta v `v3.md` popravljeni s
  kazalcem na ta zapis.

## Kontekst

`ADR-025` pove, *da* je družina lastnik vseh podatkov in da repozitorij brez
nje ne zna brati. Faza 1 zahteve `V3-R01` je našla pet mest, kjer iz tega ne
sledi enolično, *kako*:

- Poti morajo družino od nekod dobiti, prijava pa pride šele z `V3-R03`
  (admin) in `V3-R04` (telefon).
- Obdelava v ozadju dela čez vse slike, repozitorija brez družine pa ni.
- `questions.material_id` je lahko `NULL` (`ADR-012`), in takrat družine
  „iz starša" ni mogoče izpeljati.
- Identifikator snovi generira telefon in je globalen primarni ključ; tuja
  družina ga lahko (v teoriji) pošlje.
- Kriterij poimenuje stolpec slovensko, vse obstoječe sheme so angleške.

## Možnosti in odločitve

### A — od kod pot dobi družino, dokler ni prijave

1. **Edina družina iz baze.** Odvisnost prebere tabelo `families`; če v njej
   ni natanko ena vrstica, zahteva pade z jasnim sporočilom. Za: ni nastavitve,
   ki bi bila lahko napačna; druge družine pred `V3-R05` po vrstnem redu zahtev
   tako ali tako ni. Proti: ena poizvedba več na zahtevo.
2. **`FAMILY_ID` iz okolja.** Za: brez poizvedbe. Proti: nova spremenljivka, ki
   jo lastnik nastavi ročno in `V3-R04` spet odstrani; napačna vrednost je tiha.

**Izbrano: A1.** Odvisnost je začasna in pade, ko jo zamenja seja
(`V3-R03`) oziroma žeton (`V3-R04`).

### B — obdelava v ozadju

1. **Po družinah.** Seznam družin, nato za vsako svoj repozitorij. Isto velja za
   obnovo obtičalih ob zagonu.
2. **Bralec vrste brez družine.** Za: en obhod čez vse. Proti: to je natanko
   „metoda, ki obide družino", ki jo `ADR-025` prepoveduje.

**Izbrano: B1.** Posledica: pravilo `V1-R03` „najstarejši posnetek prvi"
odslej velja **znotraj družine**, ne čez vse. Pri eni družini se ne spremeni
nič; pri več lahko ena družina čaka na obhod druge.

### C — družina na `questions`

1. **Izpeljava iz materiala** (dobesedno po kriteriju). Proti: vprašanje
   dokončno izbrisane snovi v bazi nima družine in je dosegljivo samo prek
   postavke kviza — izolacija takega vprašanja je stvar pravilnega `JOIN`, ne
   sheme.
2. **Stolpec `family_id`, zapisan ob nastanku.** Isti vzorec kot
   `questions.subject` in `material_taken_at`, ki obstajata prav za primer, ko
   materiala ni več (`ADR-012`).

**Izbrano: C2.** `quiz_items` ostane brez stolpca: `quiz_id` je `NOT NULL` in
postavka brez kviza ne obstaja, zato je izpeljava prek `quizzes.family_id`
brez izjem.

### D — `POST /materials` z `id`, ki obstaja v drugi družini

1. **`409`, nič se ne zapiše.** Telefon ga po `ADR-004` označi kot `failed`.
2. **Kot „že obstaja" (`200`, `created: false`).** Proti: telefon misli, da je
   slika prenesena, v njegovi družini pa je ni; odgovor izda obstoj tujega
   zapisa.

**Izbrano: D1.** Primarni ključ ostane globalen. V praksi se to brez namernega
ponarejanja ne zgodi, ker je `id` UUID s telefona.

### E — ime stolpca

**Izbrano: `name`**, zaradi doslednosti z `quizzes.name` in ostalo shemo.

## Posledice

- **Kaj to olajša:** izbira družine je na enem mestu (ena odvisnost), ki ga
  `V3-R03` in `V3-R04` zamenjata, ne da bi se dotaknila repozitorijev.
- **Kaj to oteži:**
  - Vsaka zahteva pod `/admin` in vsaka pot telefona do `V3-R03`/`V3-R04`
    plača poizvedbo po družini.
  - Druga družina v bazi pred `V3-R03`/`V3-R04` ustavi vse poti (500). To je
    namen, ne stranski učinek.
  - Pogodba s telefonom dobi nov izid (`409`), ki ga pravilno delujoč telefon
    ne vidi nikoli.
- **Na katere zahteve to vpliva:** `V3-R03` in `V3-R04` odstranita odvisnost
  iz A1. `V3-R05` ne sme dodati druge družine, dokler je A1 še v kodi.
