# Plan: V1-R06 (popravek) — versionCode iz EAS in zaključek zahteve

> Nastane v fazi 4 in se commita na feature branch.
> Med čakanjem ga popravim neposredno v tej datoteki; moja verzija velja.
> Po mergu ni več aktualen; hrani se kot zapis, kaj je bilo takrat dogovorjeno.

**Branch:** `fix/v1-r06-eas-versioncode`

## Zahteva

V1-R06, peti kriterij: vsaka gradnja profila `preview` mora dobiti svoj
`versionCode`, da gradnji loči tudi Android sam. Kriterij je bil ob pisanju
zahteve namenoma odložen, ker `apps/mobile/eas.json` na veji
`feat/v1-r06-vidna-verzija` ni obstajal — veja je nastala iz `244854d`
(Merge V1-R03), `eas.json` pa je na `main` prišel šele z `d34f578`
(Merge V1-R02 popravek). Sedmi korak plana V1-R06 se zato glasi „po mergu
popravka V1-R02", a po mergu ni bil izveden. Ta popravek ga izvede in zahtevo
zaključi po fazi 8.

## Razčiščeno v fazi 1

| Vprašanje | Odgovor |
|---|---|
| Je to nova zahteva ali napaka | **Napaka** po fazi 9b — pripomba se preslika na obstoječi peti kriterij V1-R06. Ista zahteva, nova veja, ker je izvirna merge-ana. |
| Kam gre `appVersionSource` | V `cli`, kot ga bere EAS CLI. |
| Kam gre `autoIncrement` | V profil `preview`, kot pravi kriterij. |
| Se kljukice postavijo zdaj | **Ne.** V1-R06 izrecno pravi, da se postavijo po preizkusu na telefonu (faza 9b). Enak vzorec kot V1-R07. |
| Gre status na `Zaključeno` | Da. Po fazi 8 `Zaključeno` pomeni „dostavljeno, čaka na sprejem", ne „preizkušeno na napravi". |
| Se plan V1-R06 popravi | **Ne** — trdi rob 3, plan se za nazaj ne prepisuje. |
| Je potreben ADR | Ne. Popravek izvede odločitev, ki je že zapisana v kriteriju; nobene prejšnje ne razveljavlja. |

## Preverba iz faze 2

- **Že implementirano:** ne. `apps/mobile/eas.json` ima
  `"appVersionSource": "local"` in profil `preview` brez `autoIncrement`.
- **Kaj lahko podre:** nič v aplikaciji. `eas.json` bere izključno EAS CLI ob
  gradnji; nobena koda in noben test se nanj danes ne sklicujeta. Prehod na
  `remote` pomeni, da verzijo od prve gradnje naprej hrani EAS in ne
  repozitorij — `app.json` polja `android.versionCode` nima, zato ni česa
  poteptati.
- **Skladnost s prejšnjimi odločitvami:** `ADR-010` se dotika istega
  `eas.json`, a le profila `preview` glede okolja in tipa gradnje; ta popravek
  tistih polj ne spreminja. Nobenega ADR o verzioniranju gradenj ni.
- **Migracija:** ni je, ne na strežniku ne na telefonu.

## Sprejete odločitve

- Popravek gre v **isto zahtevo** V1-R06, ne v novo. Nova postavka ne nastane.
- Kljukice kriterijev ostanejo prazne do preizkusa na napravi; status vseeno
  gre na `Zaključeno`.
- V zahtevi se zabeleži ime te veje, po vzoru V1-R02 („Popravek po sprejemu").

## Izrecno zunaj obsega

- Prikaz `versionCode` v vmesniku — plan V1-R06 ga izrecno izloča.
- Sama gradnja APK in preizkus na telefonu — to je faza 9b.
- Karkoli iz V1-R02 ali V1-R07, kar prav tako čaka na isti preizkus.

## Vpliv

- **Spremenjene datoteke:** `apps/mobile/eas.json`, `docs/verzije/v1.md`,
  `docs/01-arhitektura.md`.
- **Nove datoteke:** `apps/mobile/__tests__/eas-config.test.ts`, ta plan.
- **Spremembe navzven:** nobene v aplikaciji. Spremeni se samo, kako EAS
  določi `versionCode` ob gradnji.
- **Prizadete zahteve:** V1-R06 (dokončanje). V1-R02 se ne dotakne — profil
  `preview` obdrži `distribution`, `environment` in `buildType`.
- **Tveganja:** prva gradnja po tej spremembi vzpostavi oddaljeni števec pri
  EAS. Če bi kdaj hoteli nazaj na `local`, je to ročna poravnava številke —
  a ta zahteva prav to centralizacijo hoče.

## Ocena tveganja

`nizko` — dve vrstici konfiguracije, ki je koda ne bere, brez nove odvisnosti,
brez migracije in brez spremembe javnega vmesnika. Ostalo je dokumentacija,
ki jo faza 8 tako ali tako zahteva.

## Koraki

1. `apps/mobile/eas.json`: `cli.appVersionSource` → `"remote"`,
   `build.preview.autoIncrement` → `true`.
2. `apps/mobile/__tests__/eas-config.test.ts`: regresijski test nad
   `eas.json`, po vzoru `cleartext-plugin.test.ts`, ki registracijo plugina
   prav tako preverja nad `app.json`.
3. `docs/verzije/v1.md`: status V1-R06 na `Zaključeno`, ime popravkovne veje,
   opomba pri petem kriteriju, da odloženi korak ni več odložen; vrstica v
   tabeli vrstnega reda dobi status.
4. `docs/01-arhitektura.md`: zabeleži, od kod pride `versionCode`.
5. `lint`, `typecheck`, celotna zbirka.
6. Pregledovalec, nato celotna preverba iz `scripts/` na končnem HEAD.

## Test casi

| Primer | Vhod / stanje | Pričakovano |
|---|---|---|
| Vir verzije | `eas.json` → `cli.appVersionSource` | `"remote"` |
| Samodejno štetje | `eas.json` → `build.preview.autoIncrement` | `true` |
| Regresija ADR-010 | `eas.json` → `build.preview` | `environment: "preview"`, `distribution: "internal"`, `android.buildType: "apk"` nedotaknjeni |
| Profil obstaja | `eas.json` → `build` | ključ `preview` je prisoten |

## Kriteriji, po katerih bo pregledovalec sodil

- [ ] `eas.json` ostane veljaven JSON in obdrži vsa polja iz `ADR-010`.
- [ ] Test pade, če se `appVersionSource` vrne na `local` ali `autoIncrement`
      izgine (mutacijska preverba).
- [ ] Plan `docs/plan/V1-R06.md` je nedotaknjen.
- [ ] Kljukice kriterijev V1-R06 niso postavljene brez preizkusa na napravi.
- [ ] Nobene nove odvisnosti.

---
## Moje pripombe (izpolnim jaz)
-
