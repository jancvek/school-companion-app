# ADR-010: Nešifriran HTTP je dovoljen za celotno aplikacijo

- **Datum:** 2026-09-07
- **Nastalo pri:** V1-R02 (popravek po sprejemu)
- **Status:** Sprejeto

## Kontekst

Prva gradnja APK prek EAS Build je pokazala napako, ki je enotski testi ne
morejo videti: vsaka fotografija ostane v stanju „Čaka na prenos". Vzrok ni v
logiki prenosa, ampak v gradnji.

Android od `targetSdk` 28 naprej nešifriran (`http://`) promet privzeto
blokira. Razvojna gradnja tega ne pokaže, ker predloga React Native v
**debug** manifest doda `android:usesCleartextTraffic="true"`; release
manifest ga nima. Naslov domačega strežnika je `http://<tailscale>:8000`,
zato Android klic zavrne, preden gre na omrežje.

Ugotovljeno na sami zgrajeni datoteki APK, ne po sklepanju:

| Preverba | Izid |
|---|---|
| `AndroidManifest.xml` v APK → `usesCleartextTraffic` | ni ga |
| `AndroidManifest.xml` → `networkSecurityConfig` | ni ga |
| `AndroidManifest.xml` → `android.permission.INTERNET` | je |
| `assets/app.config` → `extra.serverBaseUrl` | niz, protokol `http` |
| `assets/app.config` → `extra.apiKey` | niz, 44 znakov |
| Strežnik z domačega računalnika: `GET /`, `GET /materials` s ključem | 401 oz. 405 — strežnik živ, ključ sprejet |

Nastavitve so torej pravilno prišle v gradnjo in strežnik dela; manjka samo
dovoljenje na strani Androida.

Ključna omejitev pri izbiri poti: **`expo.android.usesCleartextTraffic` ni
podprt ključ** v shemi Expo konfiguracije (SDK 57, `@expo/config-types`).
Nastavitve zato ni mogoče dodati v `app.json` neposredno.

## Zakaj to ni nova zahteva

`CLAUDE.md`, merilo dokončanosti: „Vsak zaslon … preverjeno na napravi" in
kriterij V1-R02 „upload worker … ob uspehu nastavi `synced`". Dostavljeno se s
tem kriterijem ne ujema, novega vedenja nihče ne zahteva — to je **napaka**
po fazi 9b, ne sprememba zahteve. Ker je V1-R02 že mergeana, popravek ne more
nazaj na njeno vejo in dobi svojo: `fix/v1-r02-cleartext-http`.

## Možnosti

1. **`expo-build-properties`** z `android.usesCleartextTraffic` — Za: uradni
   Expo paket, nič lastne kode. Proti: **nova odvisnost** (`CLAUDE.md`, trdi
   rob 5) za eno vrstico v manifestu.
2. **Lokalni config plugin, dovoljenje za celo aplikacijo** — Za: brez nove
   odvisnosti (`expo/config-plugins` je del paketa `expo`); ena datoteka,
   testljiva kot čista funkcija. Proti: aplikacija sme na katerikoli `http://`
   naslov, ne le na domačega.
3. **Lokalni config plugin z `networkSecurityConfig` samo za gostitelja iz
   `SERVER_BASE_URL`** — Za: najožje dovoljenje. Proti: plugin mora ob gradnji
   brati okolje in generirati XML vir; več gibljivih delov v gradnji, ki jih
   noben test na razvojnem stroju ne preveri.
4. **HTTPS na strežniku (`tailscale serve`)** — Za: manifesta ni treba
   spreminjati. Proti: delo na strani strežnika in nova pot do njega; izven
   obsega tega popravka.

## Odločitev

Izbrana je **možnost 2**: lokalni config plugin, ki v glavni `<application>`
zapiše `android:usesCleartextTraffic="true"` za celotno aplikacijo.
Odločitev je sprejel lastnik.

Utemeljitev: edini omrežni klic v aplikaciji je v `src/sync/upload.ts` in gre
na naslov, ki pride ob gradnji; varnostna meja tega sistema je Tailscale
(`ADR-006`), ne šifriranje transporta. Manj gibljivih delov v gradnji pomeni
manj tihih odpovedi — prav ta razred napake je stal to gradnjo.

## Posledice

- **Kaj to olajša:** prenos slik dela v release APK; popravek je ena nova
  datoteka in ena vrstica v `app.json`, brez nove odvisnosti.
- **Kaj to oteži:** dovoljenje velja za vso aplikacijo. Če bi kdaj hodila na
  javno omrežje ali na drug naslov, je treba dovoljenje zožiti (možnost 3) ali
  preiti na HTTPS (možnost 4). To ostaja odprto in ni izbrisano — je zapisano
  tu.
- **Na katere zahteve to odslej vpliva:** V1-R02 (prenos sploh steče) in vsaka
  nadaljnja gradnja APK. V1-R05, če bo kviz hodil na strežnik, podeduje isto
  nastavitev.
- **Cena ostane vidna:** ključ in naslov sta še naprej vgrajena v APK
  (`docs/01-arhitektura.md`), promet do strežnika pa je odslej izrecno
  nešifriran znotraj Tailscale omrežja.
