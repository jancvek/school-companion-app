# POC-02 — Nov videz spletnega pregleda (admin)

> Nastane v koraku 1 POC poti (`CLAUDE.md` §1d) na veji `poc/02-…`.
> Je **edini del POC-a, ki pride v `main`** — koda se zavrže. Zato mora vse,
> kar je bilo vredno izvedeti, stati tukaj, ne v kodi in ne v pogovoru.

**Veja:** `poc/02-nov-slog`
**Oblika:** `idejni/UX`
**Časovni okvir:** en krog = ena seja, največ trije krogi
**Sodba:** `Sprejeto`

**Kje je koda:** zunaj repozitorija, v lastnikovi mapi
`C:\Personal\School Companion App` (`*-predlog.html`). Trinajst
samostojnih HTML strani z izmišljenimi podatki, povezanih med seboj. Na tej veji sta samo ta zapis in posnetki zaslona v
`docs/poc/POC-02/`.

## Vprašanje

Ali nov vizualni jezik — stalna navigacija, predmeti kot zvezki, kartice in
temna tema — naredi spletni pregled opazno preglednejši, tako da ga želim
uvesti na **vseh** straneh admina?

## Kaj šteje kot »ok«

- Ob odprtju `/admin` je brez branja jasno, kaj je danes poslikano in kje je
  kateri predmet.
- Na strani predmeta so dnevi in tedni ločeni na prvi pogled.
- Na strani slike je učna vsebina (povzetek, vprašanja, prepis) na prvem
  zaslonu, upravljanje in tehnični podatki pa ne motijo.
- Vse strani delujejo na telefonu (širina 390 px, brez vodoravnega drsenja)
  in v temni temi.

## Namenoma ne rešujem

- Predlogov za strani, ki dobijo nov videz po pravilih (glej *Ugotovitve →
  Strani po pravilih*) — zanje se predlog ne riše.
- Tiskanih izpisov (`kviz-tisk.html`, list A4 v `preizkus.html`): papir
  ostane, kakršen je; nov videz velja samo za zaslon.
- Pravih podatkov in povezave s strežnikom — predlogi so statični HTML.
- Pravih posnetkov zvezka — sličice so nadomestek (list karo zvezka).
- Mej `ADR-024`: predlogi imajo skripto **samo** za preklop stanj in teme v
  predogledu; vse, kar je del predloga, deluje brez nje.

## Krogi

### Krog 1 — 2026-10-10
- **Zgrajeno:** pet strani v enem slogu — Predmeti (`/admin`), predmet
  (`/admin/subjects/MAT`), slika (`/admin/materials/…`), Urnik
  (`/admin/schedule`), Družina (`/admin/family`). Vsaka ima ploščo
  „Predogled" za preklop stanj (npr. obdelano / v obdelavi / napaka / arhiv)
  in teme (sistem / svetla / temna).
- **Kako preizkusiš:** odpri `predmeti-predlog.html` in hodi po povezavah
  (zvezek MAT → sličica → nazaj prek drobtin; levi meni → Urnik, Družina).
  Zoži okno pod 860 px za telefon.
- **Tvoje pripombe:** „Vse predlagane strani so mi zelo všeč." Brez
  sprememb. Dodatno: strani, ki jih krog 1 ni pokril, ne smejo ostati v
  starem slogu.

### Krog 2 — 2026-10-10
- **Zgrajeno** (isti dan, v isti seji, na lastnikovo zahtevo): Po dnevih
  (`dnevi-predlog.html`), nova stran Kvizi (`kvizi-predlog.html`), izbor snovi
  za kviz (`kviz-izbirnik-predlog.html`), predogled kviza
  (`kviz-predogled-predlog.html`), kviz in rezultat (`kviz-predlog.html`:
  objavljen / rešen / preklican), Statistika (`statistika-predlog.html`),
  statistika predmeta (`statistika-mat-predlog.html`), prijava
  (`prijava-predlog.html`: obrazec / napačno geslo). Meni na vseh straneh
  zdaj vodi na prave predloge; Odjava vodi na prijavo.
- **Kako preizkusiš:** kot pri krogu 1; tok kviza: Kvizi → „Kviz iz nove
  snovi" → „Sestavi kviz" → „Objavi kviz" → kviz (preklopi stanje na
  „Rešen").
- **Tvoje pripombe:** „Sprejmem.“ Brez pripomb — posnetki so, kakršni so,
  opis tega, kar mora implementacija narediti.

## Dogovorjeno

- Vseh pet strani gre v implementacijo, kakor so v krogu 1 (posnetki v
  `docs/poc/POC-02/`).
- Implementacija začne po mergeu V4-R07 **in V4-R08** (oba sta v `main` od
  2026-10-11); strani obeh (urejevalnik, shranjeni testi, ogled testa) so v
  obsegu po pravilih.
- **Nov videz dobijo vse strani admina** (28 predlog po V4-R08), v isti zahtevi — nobena
  ne ostane v starem slogu. Zahtevnejše dobijo predlog v krogu 2, ostale nov
  videz po pravilih iz *Ugotovitev*.
- **Nova stran Kvizi** (`/admin/quizzes`): obrazec za nov kviz in seznam vseh
  kvizov. Na strani Predmeti ostanejo zadnji štirje in povezava „Vsi kvizi".
  Postavka Kvizi v meniju vodi sem.
- **Ena zahteva** za ogrodje in vseh pet strani (ne razrez po straneh).
- Implementacija začne **po mergeu V4-R07**, ker ta spreminja `osnova.html`.
- Pisava **Atkinson Hyperlegible Next**, postrežena z lastnega strežnika
  (woff2 v repozitoriju, licenca OFL) — nova odvisnost, odobrena.
- Vhod za implementacijo sta ta zapis in posnetki zaslona; HTML predlogov
  implementacija ne bere (`ADR-052`, točka 5).

## Ugotovitve

### Barvni žetoni

| Žeton | Svetla | Temna | Raba |
|---|---|---|---|
| `ozadje` | `#eef1f4` | `#12171d` | ozadje strani |
| `ploskev` | `#ffffff` | `#1a2129` | kartice, meni |
| `ploskev-2` | `#f6f8fa` | `#212a33` | glave tabel, polja v kartici |
| `rob` | `#d7dde4` | `#2e3944` | robovi, ločila |
| `besedilo` | `#17202b` | `#e6ebf0` | |
| `zamolklo` | `#586474` | `#9aa6b4` | pomožno besedilo |
| `poudarek` | `#2f5d50` | `#7cc0a8` | povezave, glavni gumb, izbrano (obstoječa barva) |
| `poudarek-mehko` | `#e3eeea` | `#1f3530` | izbran element menija, oznake „ok" |
| `nevarno` / `-mehko` | `#a2402f` / `#f6e6e2` | `#e38b79` / `#3a2420` | brisanje, napaka, manjki |
| `opozorilo` / `-mehko` | `#7a5a12` / `#f4ecd9` | `#e2c27a` / `#352c17` | v obdelavi, neshranjen predlog |
| `nalepka` | `#fffdf8` | `#f3efe6` | nalepka na zvezku |

Barve predmetov (enake v obeh temah, bel tekst nanje): NAR `#3d7856`,
MAT `#2d5a8e`, TJA `#8a3a5b`, GEO `#8b5a26`, SLJ `#a63f3b`, LUM `#6f55a0`,
ZGO `#6a5843`, TIT `#44636e`, DKE `#5a7530`, GUM `#2b7a80`. Pripadajo
predmetu, zato sodijo v `subjects.py` ob kodo in ime, ne v predlogo.

Tema: privzeto po sistemu (`prefers-color-scheme`), brez skripte in brez
preklopa v vmesniku. Vsak žeton ima temno različico.

### Tipografija in mere
- Pisava Atkinson Hyperlegible Next (400, 500, 700, 800), rezerva
  `system-ui`. Osnova 16 px / 1,55; števila `tabular-nums`.
- Naslov strani 1,75–2,25 rem, 800; naslov razdelka 1,1–1,3 rem, 700.
- Zaobljenost kartic 10 px, gumbov 8 px, oznak (pilul) polna.
- Ločilo telefon/računalnik: 860 px.

### Ogrodje
- Levo stalen meni (15,5 rem): znak in ime družine zgoraj; Predmeti, Po
  dnevih, Kvizi, Testi (shranjeni testi, V4-R08), Urnik, Statistika |
  Družina, Arhiv, Sistem (samo lastnik sistema); spodaj ime (povezava na račun), vloga, Odjava. Ob postavki
  števec, kjer ga stran že pozna (slike, kvizi, arhiv).
- Pod 860 px: meni postane vrstica na vrhu z vodoravno drsečimi postavkami.
- Razdelki „Testi" (V4-R08), „Pregled po dnevih", „Urnik", „Družina",
  „Sistem", „Statistika" na dnu `/admin` odpadejo — nadomesti jih meni.

### Gradniki
- **Zvezek** (predmet): platnica v barvi predmeta, temnejši rob vezave levo,
  velika koda zgoraj, bela nalepka z imenom, spodaj število slik. Predmet brez
  slik ostane na polici kot črtkan obris z „še ni slik".
- **Čip** predmeta: koda na barvi predmeta (MAT 3).
- **Oznaka** (pilula): ok / čaka / napaka / nevtralna.
- **Gumb**: polni (glavno dejanje), obrobljeni (drugotno), rdeče obrobljen
  (uničujoče), polno rdeč samo za nepovratno (Izbriši dokončno, Deaktiviraj
  na potrditveni strani).
- **Obvestilo**: vrstica z barvno piko ali obarvano polje (čaka/napaka/arhiv)
  — vedno pove, kaj narediti.

### Strani
- **Predmeti:** kartica Danes (vrstica na otroka: ✓ poslikano + čipi
  predmetov ali ○ še ni slik; ob vikendu en stavek), polica zvezkov po urniku,
  Kvizi (izbira predmeta, „Kviz iz nove snovi" polni, „Izberi snov ročno"
  obrobljeni, povezava „Kaj smo se danes učili"), tabela zadnjih kvizov
  (Kviz, Predmet, Otrok, Nastal, Stanje, Vprašanj) in „Vsi kvizi". Na
  telefonu tabela postane vrstice.
- **Predmet:** teden je blok z glavo (razpon dni, „Ta teden"/„Prejšnji
  teden", število slik, „Izberi teden"); v njem pet stolpcev Pon–Pet. Dan:
  sličice z uro in otrokom, „Izberi dan"; danes obarvan. Prazni dnevi: ni na
  urniku (šrafirano), po urniku je bil predmet in slik ni (rdeče), še pride.
  Stanje obdelave na sličici samo, kadar ni „obdelano". Kljukica je sosed
  povezave (kriterij V3-R11 ostane). Vrstica izbora se pokaže z
  `form:has(input:checked)` in šteje izbrane s CSS števcem — brez skripte.
  „Pokaži starejše tedne" na dnu. Na telefonu dnevi drug pod drugim, dnevi
  brez urnika skriti.
- **Slika:** drobtine, listanje „← Novejša | 3 od 24 | Starejša →" na
  strani (ne le v povečavi). Levo slika (lepljiva) s Povečaj / Prenesi
  izvirnik in Posneto / Na strežniku / Velikost. Desno Povzetek, Vprašanja
  (oštevilčena, odgovor pod vprašanjem, vrstica o upokojenih), Prepis. Pod
  tem Upravljanje (vsako dejanje z enim stavkom posledic) in zloženi
  Tehnični podatki (model, tokeni, pot, ID, prompt, surov odgovor). Povečava
  deluje s CSS `:target` na obstoječem sidru `#povecano`.
- **Urnik:** izbira otroka kot zavihka (povezavi, brez „Pokaži"); vrstica
  stanja (potrjen od … / prebran s slike, ni shranjen / brez urnika + „Vnesi
  urnik"); teden na pogled (pet stolpcev s predmeti, „se ne slika" črtkano);
  mreža v `<details>` „Uredi urnik". Celice ostanejo `<select>` z istimi
  vrednostmi (`""`, `da`, `brez`); barva prek `:has(option:checked)`. Ob
  mreži kartice: „Tega nisem znal uvrstiti", prebrana slika, Preberi s slike
  (JPEG/PNG do 10 MB), legenda celic.
- **Po dnevih:** izbira otroka (zavihka) desno v glavi; obdobje kot zavihki
  Danes / Včeraj / Zadnjih 7 dni (danes „Ta teden" — preimenovano, ker pomeni
  zadnjih sedem dni, ne koledarskega tedna) in izbira dneva. Pod tem ena
  vrstica: obdobje, število slik, „arhivirane niso prikazane". Vsak dan je
  kartica: datum, „danes", število slik, desno **Manjka** s črtkanimi čipi
  predmetov (samo pri delno poslikanem dnevu, `ADR-028` E2); v kartici so
  predmeti drug ob drugem (čip, ime, število) s sličicami in uro pod njimi.
  Dan brez slik je ena črtkana vrstica „Tega dne ni nobene slike."
  „Nazadnje prejeto" je v uvodnem stavku, krepko.
- **Kvizi (nova stran):** kartica Nov kviz (predmet, „Kviz iz nove snovi",
  „Izberi snov ročno", desno povezava „Kaj smo se danes učili", razlaga v
  enem odstavku); filtra kot zavihka — stanje (Vsi / Čakajo / Rešeni /
  Preklicani, s številom) in otrok (Oba / Jaka / Tim); tabela kot na
  Predmetih, razdeljena z vrsticami po mesecih.
- **Izbor snovi za kviz:** drobtine Kvizi / Nov kviz; naslov „Nov kviz iz
  matematike"; **koraka** 1 Izberi snov → 2 Preglej in objavi (tudi na
  predogledu, prvi kot opravljen); kartica nastavitev: „Kviz za" (zavihka,
  s stavkom, da menjava na novo obkljuka) in „Vprašanj na sliko". Seznam po
  tednih (Ta teden / Prejšnji teden), vrstica: kljukica, sličica, dan in
  ura, število vprašanj; izbrana vrstica rahlo obarvana; neizbirna brez
  kljukice, zamolkla, z razlogom v barvi opozorila („še v obdelavi", „slika
  ni berljiva"); že uporabljena izbirna z „že v kvizu »…«". „Izberi vse /
  Počisti izbor" nad seznamom. Vrstica izbora spodaj kot na strani predmeta
  (CSS števec) z gumbom „Sestavi kviz".
- **Predogled kviza:** v uvodu otrok, število vprašanj in snovi ter krepko
  „Ta stran ničesar ne shrani."; izpuščeno kot obvestilo; vsaka snov kartica
  (čip, dan in ura, število, „Odpri snov") z oštevilčenimi vprašanji (zvezna
  številka čez kviz) in odgovori; desno lepljiva kartica **Objava**: ime
  kviza, „Objavi kviz", stavka o zamrznitvi in o tem, kdaj ga otrok dobi,
  „Nazaj na izbor". Na ožjem zaslonu je Objava pod snovmi.
- **Kviz:** drobtine; naslov; pod njim čip predmeta, otrok, število vprašanj,
  datum objave; desno oznaka stanja. *Objavljen:* tiho obvestilo, da čaka
  na reševanje, in seznam vprašanj z izvorom. *Rešen:* kartica rezultata
  (čas rešitve, „Natisni vprašanja s ključem", širok pas razporeditve,
  legenda s števili, stavek o samooceni) in skupine po oceni od najtežje
  navzdol — vsaka z barvnim levim robom, vprašanje obdrži svojo številko iz
  kviza, pod njim izvor in čas razmisleka. *Preklican:* tiho obvestilo
  (kdaj, nič izbrisano, snov se spet ponudi) in seznam. Na dnu „Prekliči
  kviz" kot vrstica upravljanja (ne pri preklicanem).
- **Statistika:** izbira otroka v glavi; obdobje kot zavihki „Šolsko leto
  2026/27 | 2025/26"; desno legenda štirih ocen. Kartica „skupaj" (ocen,
  pravilnih, težkih, širok pas, pravilo štetja). Tabela predmetov po urniku:
  čip in ime (povezava), ocen, pas z ocenami pod njim, pravilnih, težkih;
  predmet brez ocen zamolkel s šrafiranim praznim pasom in „—". Na telefonu
  vrstica v dveh nivojih.
- **Statistika predmeta:** drobtine; platnica in ime predmeta; ista orodja
  in kartica skupaj. Vrstni red: **Postavljena večkrat** (prvo, ker je
  bistvo strani) — kartica vprašanja z odgovorom, izvorom in „postavljeno
  N-krat" ter **zaporedjem ocen** kot vrsto kartic s puščicami (datum,
  ocena v barvi, ime kviza kot povezava); nato Po mesecih in Snovi kot
  tabeli; **Postavljena enkrat** je zložena (`<details>`) s številom in
  razlogom.
- **Prijava:** edina stran brez menija. Levo barvna plošča (poudarek) z
  znakom, polico desetih hrbtov zvezkov v barvah predmetov in enim stavkom
  o aplikaciji; desno obrazec (E-naslov, Geslo, „Prijavi me", ločilo „ali",
  „Prijava z Google računom", oba pojasnila). Napaka nad obrazcem kot
  obvestilo. Na telefonu je plošča nizek pas nad obrazcem.
- **Družina:** kartice v skupinah Otroci / Starši z vrstico, kaj vloga lahko;
  oznake (to si ti, lastnik sistema, samo Google, deaktiviran); dejanja na
  dnu kartice, Deaktiviraj rdeče desno; pri otroku povezava Urnik. Dodajanje
  v dveh `<details>`, odpira ju tudi gumb na vrhu. Napaka ob polju, ki jo je
  povzročilo. Potrditev deaktivacije: kartica s posledicami (! takoj, •
  teče naprej, ✓ ostane).

### Strani po pravilih (brez predloga)

Vse uporabljajo ogrodje, žetone in gradnike od zgoraj. Vsebina, obrazci,
poti in metode (`GET`/`POST`, CSRF) ostanejo nespremenjeni.

Stanje predlog: `main` po mergeu V4-R08 (28 strani; `_statistika.html`,
`_preizkus-izris.html` in `_preizkus-slog.html` so deli, ne strani).

| Predloga | Kaj je | Po čem se ravna |
|---|---|---|
| `arhiviranje.html`, `brisanje.html`, `clani-geslo.html`, `clani-stanje.html` (tudi aktivacija), `sistem-stanje.html` | potrditvene strani | kartica potrditve kot pri deaktivaciji (posnetek 14): kdo/kaj zgoraj, naslov kot vprašanje, posledice v seznamu (! takoj, • teče naprej, ✓ ostane), polno rdeč gumb samo za nepovratno, drugače polni; „Prekliči" obrobljen |
| `arhiv.html` | arhivirane slike | mreža sličic kot na strani predmeta (brez tednov), oznaka „v arhivu" in datum arhiviranja pod sličico |
| `prepisi.html` | prepisi izbranih slik | glava z drobtinami na predmet; polje s prepisi ostane (označi in kopiraj), oblikovano kot blok prepisa na strani slike — gumba „Kopiraj" ni, ker bi rabil skripto |
| `racun.html` | lasten račun | kartice in polja obrazca kot pri Družini (posnetek 12–13) |
| `sistem.html`, `sistem-druzina.html` | družine (lastnik sistema) | kartice družin kot kartice članov; člani družine kot pri Družini |
| `najdena-ni.html` | 404 | kartica z enim stavkom, kaj se je zgodilo, in povezavo nazaj na Predmeti |
| `kviz-tisk.html` | tisk kviza | zaslonski del v ogrodju; `@media print` ostane nespremenjen |
| `preizkus.html` | urejevalnik preizkusa (V4-R07) | ogrodje in žetoni za zaslon; predogled A4 in njegov tisk ostaneta, kot ju določa `ADR-054` |
| `preizkusi.html` | shranjeni testi (V4-R08) | kot nova stran Kvizi (posnetek 16): filter po predmetu kot zavihki, tabela (Shranjeno, Predmet kot čip, Naslov, Otrok), prazen seznam kot obvestilo z navodilom; postavka Testi v meniju vodi sem |
| `preizkus-ogled.html` | ogled shranjenega testa (V4-R08) | drobtine Testi / naslov, meta kot pri kvizu (čip, otrok, shranjeno, model), gumbi kot pri strani slike; list A4 in tisk ostaneta, kot ju določata `ADR-054` in `ADR-055` |

### Pasti in novo vedenje (ni samo slog)
- `test_admin.py::TestSeznamPredmetov::test_vrstni_red_predmetov_je_urnik_in_ne_abeceda` išče prvo
  pojavitev kode na celi strani. Nova stran ima kode prej (čipi v kartici
  Danes, tabela kvizov). Tudi vgrajen `<style>` z žetoni `--NAR … --GUM` bi
  test podrl ali ga — ker so v vrstnem redu urnika — naredil zelenega iz
  napačnega razloga. Test je treba omejiti na polico predmetov; to je
  sprememba prej zelenega testa in jo mora odobriti lastnik.
- Slog v ločeni datoteki (`/static/…`): razlog za vgrajen slog v
  `osnova.html` (streženje statičnih datotek) od V4-R07 ne velja več. To je
  odločitev za ADR.
- **Novi podatki, ki jih strežnik danes ne da predlogam:**
  - stran predmeta po tednih: razvrstitev po ISO tednu in dnevu, urnik za
    manjke, deljenje po tednih („Pokaži starejše tedne");
  - **odprto:** čigav urnik velja za manjke na strani predmeta, ko imata
    otroka različen urnik (stran ni po otroku, `ADR-039`);
  - urnik: razlika med prebranim predlogom in potrjenim urnikom (pike);
    prebrana slika ob potrjenem urniku pomeni hranjenje poti slike;
  - družina: ali ima starš povezan Google (oznaka „Google in geslo");
  - slika: položaj v predmetu („3 od 24");
  - nova stran Kvizi (`/admin/quizzes`) z vsemi kvizi, filtroma po stanju
    in otroku ter delitvijo po mesecih; Predmeti pokažejo samo zadnje štiri;
  - izbor snovi za kviz: delitev po tednih, „Izberi vse / Počisti izbor"
    (kot `?vse=1` na strani predmeta);
  - statistika predmeta: drug vrstni red razdelkov in zložen „Postavljena
    enkrat"; obstoječi testi, ki iščejo besedilo po vrstnem redu, se lahko
    spremenijo;
  - Po dnevih: „Ta teden" → „Zadnjih 7 dni" (samo besedilo).
- Sobotni posnetki na strani predmeta niso umeščeni (stolpcev je pet).
- `:has()` in `color-mix()` sta pogoj za vrstico izbora, barve celic urnika
  in prazne zvezke. Ob brskalniku brez njiju se vedenje ne pokvari, izgubi se
  samo barva.
- Na telefonu vseh trinajst predlogov brez vodoravnega drsenja (preverjeno
  pri 390 px).

## Sodba

Po krogu 1 (2026-10-10): `Še en krog` — pet strani sprejetih brez pripomb,
krog 2 za zahtevnejše strani.

**2026-10-11 — `Sprejeto`.** Lastnik je po krogu 2 nov videz sprejel brez
pripomb. Odločitev je v `docs/odlocitve/ADR-056-nov-videz-admina.md`,
implementacija je zahteva `V5-R01` v `docs/verzije/v5.md` (nova verzija V5,
ker nov videz nima zveze s preizkusi iz V4).
