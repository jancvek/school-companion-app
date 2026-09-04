# ADR-004: Lokalna shema `materials` se spremeni — migracija in tretje stanje sinhronizacije

- **Datum:** 2026-09-04
- **Nastalo pri:** V1-R02 (faza 2 — preverba smiselnosti)
- **Status:** Sprejeto
- **Razveljavlja:** trditev v `docs/odlocitve/ADR-003`, razdelek „Posledice": *„V1-R02 se
  veže na shemo tabele `materials`, ne na potek zaslonov; shema se ne spreminja."*

## Kontekst

ADR-003 je ob koncu V1-R01 zapisal, da se lokalna shema v V1-R02 ne bo
spreminjala. Ta trditev je bila napisana v kontekstu vprašanja o poteku
zaslonov in ni bila rezultat pregleda potreb upload workerja.

Ob razčiščevanju V1-R02 (faza 1) se je pokazalo, da ne drži. Dve zahtevi jo
podreta:

1. **Trajno zavrnjen prenos.** `sync_status` pozna samo `pending` in `synced`.
   Zapis, ki ga strežnik zavrne z 401 (napačen ključ) ali 413 (prevelika
   datoteka), bi ostal `pending` in bi se poskušal prenesti do konca časa —
   ob vsakem zagonu aplikacije, vsakih 30 sekund, brez možnosti, da to kdo
   opazi.
2. **Vidno stanje sinhronizacije.** Lastnik je v fazi 1 odločil, da mora biti
   stanje vidno v vmesniku. Napis „prenos ni uspel" brez razloga ni uporaben,
   razlog pa se nima kam zapisati.

Hkrati velja resnična ovira: **na telefonu že so podatki iz V1-R01.**
`CREATE TABLE IF NOT EXISTS` obstoječi tabeli novega stolpca ne doda in ga
tudi ne javi — tabela preprosto ostane stara, poizvedbe pa začnejo padati na
napravi, medtem ko so testi nad svežo bazo zeleni. To je najbolj zahrbtna
oblika te napake, ker je enotski testi ne vidijo.

## Možnosti

1. **Brez sprememb sheme; neuspeh se ne zapisuje.** Za: ADR-003 ostane
   nedotaknjen, nič migracije. Proti: zapis z napačnim ključem se poskuša
   prenesti neskončno; vmesnik ne more ločiti „še ni na vrsti" od „ne bo
   nikoli"; kriterij o vidnem stanju je neizpolnljiv.
2. **Shema se spremeni, baza na testnem telefonu se pobriše.** Za: najmanj
   kode, ni migracijskega mehanizma. Proti: izgubijo se posnetki, ki jih je
   lastnik naredil ob ročnem preizkusu V1-R01; predvsem pa bi bil to
   precedens — ista poteza bi se ponovila v V1-R03, ko se shema spet
   spremeni, in takrat bo v bazi tedne dela.
3. **Shema se spremeni, z verzioniranim migracijskim mehanizmom.** Za:
   obstoječi posnetki preživijo; V1-R03 dobi pot, po kateri gre naprej. Proti:
   nekaj kode in en test več; mehanizem je treba narediti prav zdaj, ne
   kasneje.

## Odločitev

Izbrana je možnost 3.

Lokalna shema dobi verzijo, vodeno prek `PRAGMA user_version`. Baza iz V1-R01
(brez zapisane verzije, torej `user_version = 0`) se ob prvem zagonu nove
različice preseli naprej z `ALTER TABLE`, brez izgube vrstic. Sveža namestitev
gre skozi isto zaporedje migracij, ne po ločeni poti — sicer bi obstajali dve
shemi, ki se sčasoma razideta, in samo ena od njiju bi bila testirana.

Tabela `materials` dobi:

| Stolpec | Tip | Pomen |
|---|---|---|
| `sync_attempts` | `INTEGER NOT NULL DEFAULT 0` | število neuspešnih poskusov, za odmik med poskusi |
| `last_attempt_at` | `TEXT` | ISO 8601 v UTC, zadnji poskus; `NULL`, dokler ga ni bilo |
| `sync_error` | `TEXT` | zadnja napaka, da vmesnik zna povedati, zakaj ni šlo |

`sync_status` dobi tretjo vrednost **`failed`**. Meja med `pending` in
`failed` ni „koliko poskusov", ampak **ali se stanje sploh more spremeniti
samo od sebe**:

- **`failed`** — strežnik je odgovoril s 4xx, razen 408 in 429. To je sodba o
  vsebini zahteve (napačen ključ, pokvarjen zapis, prevelika datoteka) in
  ponavljanje je ne bo spremenilo. Poskušanje se ustavi.
- **`pending` ostane** — omrežna napaka, potekel čas, 5xx, 408, 429. Strežnik
  je lahko samo ugasnjen ali telefon izven Tailscale omrežja; jutri bo šlo.

Iz `failed` se zapis vrne v `pending` samo na izrecno zahtevo uporabnice
(gumb „Poskusi znova"), nikoli sam od sebe. Če bi se vračal sam, bi bila
razlika med stanjema brez pomena.

## Posledice

- **Kaj to olajša:** V1-R03 dobi migracijsko pot, ki že obstaja in je
  testirana. Vmesnik lahko loči tri stanja in pove, katero je katero.
- **Kaj to oteži:**
  - Migracijski mehanizem je nova plast, ki mora biti pravilna od prvega dne;
    napaka v njej je vidna šele na napravi z obstoječimi podatki.
  - Vsak nadaljnji poseg v shemo mora dodati novo migracijo, ne popraviti
    stare. Popravljena stara migracija na telefonu, ki jo je že prestal, ne
    steče nikoli več.
  - Potreben je test, ki migracijo pelje **nad bazo, zgrajeno po shemi
    V1-R01**, ne nad svežo. Test nad svežo bazo tu ne dokazuje ničesar.
  - `Material` v `src/types.ts` dobi tri polja in tretjo vrednost
    `sync_status`; vsak obstoječi test, ki sestavlja `Material`, se dotakne.
- **Na katere zahteve to odslej vpliva:** V1-R03 gradi na tem mehanizmu.
  Kriteriji V1-R01 ostanejo veljavni — `sync_status` novega zapisa je še
  vedno `pending`.
