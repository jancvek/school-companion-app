# Plan: V1-R02 (popravek) — nešifriran HTTP v release gradnji

> Nastane v fazi 4 in se commita na vejo popravka.
> Plan V1-R02 se ne prepisuje; ta datoteka je zapis, kaj je bilo dogovorjeno
> zdaj. Odločitev, ki plan V1-R02 dopolnjuje, je `docs/odlocitve/ADR-010`.

**Branch:** `fix/v1-r02-cleartext-http`

## Zahteva

V1-R02 (napaka po fazi 9b, odkrita po mergu). Zgrajena APK ne prenese nobene
slike: Android v release gradnji blokira `http://`, ker manifest nima
`android:usesCleartextTraffic`. Vsak poskus vrže izjemo, `upload.ts` jo
pravilno obravnava kot „ni odgovora strežnika" in zapis ostane `pending` —
za vedno. Popravek doda dovoljenje ob gradnji, brez spremembe logike prenosa.

## Razčiščeno v fazi 1

| Vprašanje | Odgovor |
|---|---|
| Kako široko dovoliti `http` | Za celotno aplikacijo (`ADR-010`, možnost 2) |
| Nova odvisnost (`expo-build-properties`) | Ne. `expo/config-plugins` je že del paketa `expo` |
| Kaj z nespravljenima `app.json` in `eas.json` na `main` | Gresta na to vejo, kot prvi commit |
| Je to nova zahteva | Ne — napaka po merilu dokončanosti; svoja veja, ker je V1-R02 mergeana |
| Verzija aplikacije | Ostane `1.0.0` |

## Preverba iz faze 2

- **Že implementirano:** ne. Ne v `app.json`, ne v `app.config.ts`, ne v
  `src/` ni omembe `usesCleartextTraffic` ali `networkSecurityConfig`.
- **Kaj lahko podre:** nič v obstoječi kodi — plugin teče ob gradnji, ne v
  aplikaciji. Tveganje je, da bi bil plugin narobe registriran in bi gradnja
  padla; to se pokaže takoj, ob naslednji gradnji.
- **Skladnost s prejšnjimi odločitvami:** `ADR-006` postavlja varnostno mejo
  na Tailscale, ne na transportno šifriranje — dovoljenje je s tem skladno.
  `ADR-002` je precedens, da nastavitve gradnje v `apps/mobile` smejo ostati,
  če imajo zapis.
- **Migracija:** ni je. Shema (telefon in strežnik) ostane nedotaknjena.
  Zapisi, ki so obtičali v `pending`, se po namestitvi nove APK prenesejo
  sami — worker jih pobere ob prvem zagonu.

## Sprejete odločitve

- Dovoljenje velja za celo aplikacijo, ne samo za enega gostitelja (`ADR-010`).
- Plugin je `.js` z JSDoc tipi, ne `.ts`: Expo plugine nalaga z navadnim
  `require`, brez prevoda TypeScripta.
- Logika mutacije manifesta je izvožena posebej, da jo test kliče kot čisto
  funkcijo, brez zaganjanja gradnje.

## Izrecno zunaj obsega

- HTTPS na strežniku (`tailscale serve`) — ostaja odprta pot v `ADR-010`.
- Zožitev dovoljenja na enega gostitelja prek `networkSecurityConfig`.
- Prikaz razloga neuspeha (`sync_error`) v vmesniku. Prav zaradi njegove
  odsotnosti je diagnoza terjala razstavljanje APK; to je nova zahteva, ne
  ta popravek.
- Karkoli v `apps/server`.

## Vpliv

- **Spremenjene datoteke:** `apps/mobile/app.json` (registracija plugina),
  `docs/verzije/v1.md` (kriterij in opomba pri V1-R02),
  `docs/01-arhitektura.md` (zapis o gradnji).
- **Nove datoteke:** `apps/mobile/plugins/with-cleartext-traffic.js`,
  `apps/mobile/__tests__/cleartext-plugin.test.ts`,
  `docs/odlocitve/ADR-010-cleartext-http-za-tailscale.md`, ta plan.
  Na veji sta že `apps/mobile/eas.json` in sprememba `app.json` z `owner` in
  `extra.eas.projectId` (prvi commit).
- **Spremembe navzven:** `AndroidManifest.xml` v gradnji dobi
  `android:usesCleartextTraffic="true"`. Vmesnik, API in shema nespremenjeni.
- **Prizadete zahteve:** V1-R02 (zdaj šele izpolnjena na napravi). V1-R01,
  V1-R03 in V1-R04 se ne dotaknemo.
- **Tveganja:** plugin, ki se ne izvede (napačna pot v `plugins`), je tiho
  neuspešen — gradnja uspe, aplikacija pa spet ne prenaša. Zato zadnji korak
  ni zelena zbirka testov, ampak preverba manifesta v zgrajeni APK.

## Ocena tveganja

`nizko` — brez nove odvisnosti, brez migracije sheme, brez spremembe javnega
vmesnika; koda aplikacije se ne dotakne. Pot je bila izbrana in potrjena pred
začetkom (`ADR-010`), zato po commitu plana ne čakam.

## Koraki

1. Plugin `plugins/with-cleartext-traffic.js`: `withAndroidManifest` postavi
   `android:usesCleartextTraffic="true"` v glavno `<application>`.
2. Registracija v `app.json` → `expo.plugins`.
3. Test nad izvoženo funkcijo mutacije, z mutacijsko preverbo (odstranim
   nastavljanje atributa — test mora pasti).
4. `lint`, `typecheck`, celotna zbirka testov.
5. Pregledovalec.
6. Dokumentacija (`v1.md`, `01-arhitektura.md`) in celotna preverba iz
   `scripts/`.
7. Nova gradnja APK, razstavitev manifesta, preizkus na telefonu.

## Test casi

| Primer | Vhod / stanje | Pričakovano |
|---|---|---|
| Manifest brez atributa | `<application android:name=".MainApplication">` | po pluginu je `android:usesCleartextTraffic` enak `'true'` |
| Manifest z atributom `false` | atribut je `"false"` | prepisan v `"true"` |
| Manifest brez glavne aplikacije | `application` brez `.MainApplication` | vrže napako, ne vrne tiho nespremenjenega manifesta |
| Ostali atributi | `application` ima `android:label` | ostanejo nedotaknjeni |
| Registracija | `app.json` | `plugins` vsebuje `./plugins/with-cleartext-traffic` |

## Kriteriji, po katerih bo pregledovalec sodil

- [ ] Plugin ne spreminja ničesar razen enega atributa v glavni `<application>`.
- [ ] Test pade, če plugin atributa ne nastavi (mutacijska preverba opravljena).
- [ ] Registracija v `app.json` je prava pot in se ujema z imenom datoteke.
- [ ] Nobene nove odvisnosti v `package.json`.
- [ ] Koda aplikacije (`src/`, `app/`) je nedotaknjena.
- [ ] `ADR-010` pove, kaj je bilo izbrano, zakaj in kaj ostaja odprto.
- [ ] Dokumentacija pove, da je promet do strežnika nešifriran znotraj
      Tailscale omrežja.

---
## Moje pripombe (izpolnim jaz)
-
