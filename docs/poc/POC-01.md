# POC-01 — Kreiranje matematičnega testa iz prepisov in klepeta

> Nastane v koraku 1 POC poti (`CLAUDE.md` §1d) na veji `poc/01-…`.
> Je **edini del POC-a, ki pride v `main`** — koda se zavrže. Zato mora vse,
> kar je bilo vredno izvedeti, stati tukaj, ne v kodi in ne v pogovoru.

**Veja:** `poc/01-kreiranje-matematicnega-testa`
**Oblika:** `idejni/UX`
**Časovni okvir:** en krog = ena seja, največ trije krogi
**Sodba:** `Sprejeto`

**Kje je koda:** zunaj repozitorija, v lastnikovi mapi `math-md-viewer`
(razširitev obstoječega lokalnega POC-a za prikaz markdowna s KaTeX). Snov in
ključ API sta lokalni datoteki v tisti mapi in **nikoli** ne prideta v
repozitorij. Na tej veji je samo ta zapis.

## Vprašanje

Ali iz prepisov izbrane snovi in nekaj želja v klepetu nastane matematični
test, ki ga lastnik natisne na A4 in brez ročnih popravkov da otroku
reševati?

## Kaj šteje kot »ok«

- Iz 3–5 prepisov ene snovi nastane test na **eni strani A4**, natisnjen iz
  brskalnika (Ctrl+P / „Natisni"), brez ročnega popravljanja besedila.
- Formule so na papirju pravilno izrisane (ulomki, potence, koreni), zapis je
  slovenski (decimalna vejica, `\cdot`, `:`), test je črno-bel.
- Prostora za odgovore je pod vsako nalogo dovolj, da otrok računa na listu.
- Naloge izhajajo iz izbrane snovi, ne iz splošne matematike tega razreda.
- Želja v klepetu („tretja naloga naj bo lažja", „skrajšaj na eno stran")
  spremeni to, kar je bilo zahtevano, in ostalega ne razsuje.
- Med čakanjem je jasno, da se test ustvarja; generiranje traja največ
  okoli minute.
- Zaslon: na desni ~2/3 predogled lista A4, na levi sličice izbranih slik
  (klik odpre galerijo), pod njimi klepet s predlogi in gumb „Kreiraj test".
  Pred prvim generiranjem je list prazen z napisom, kaj storiti.

## Namenoma ne rešujem

- ~~**Shranjevanja.**~~ V krogu 2 dodano po odločitvi lastnika (glej
  *Krogi* in *Dogovorjeno*). Še vedno ni: statusov (`osnutek` /
  `pripravljen` / `arhiviran`), arhiviranja, opombe, hkratnega osveževanja
  dveh oken.
- **Worda.** Izhod je tisk iz brskalnika (`ADR-032` in `V4-R01` predvidevata
  Word — glej *Ugotovitve*).
- **Razreda kot podatka.** Razred lastnik, kadar hoče, napiše v klepet; v
  aplikaciji in v fiksnem navodilu ni zapisan.
- **Ročnega urejanja besedila testa.** Test se spreminja samo prek klepeta.
- **Delovnega lista** v smislu V4 (razlaga + naloge + rešitve). Samo test.
- **Slik kot vhoda za model.** Vhod so prepisi; slike so na zaslonu samo za
  ogled snovi.
- **Izbora snovi v aplikaciji.** Je že rešen (`ADR-048`, „Prepisi izbranih");
  v POC-u snov pride iz lokalne mape.
- **Drugih predmetov, prijave, družin, baze.**
- **Mej `ADR-024`.** POC uporablja skripto in KaTeX s CDN-ja; kako to v
  produkciji, je vprašanje za zahtevo, ne za ta POC.
- **Pretakanja odgovora (streaming).** Vrtavka med čakanjem zadošča.

## Krogi

### Krog 1 — 2026-10-10
- **Zgrajeno** (v `math-md-viewer`, zunaj repozitorija):
  - `server.py` — lokalni strežnik v Pythonu brez dodatnih paketov
    (`http.server` + `urllib`). Streže stran in `snov/`, bere
    `snov/prepisi.md`, kliče OpenAI Responses API s strukturiranim izhodom
    (JSON: `sporocilo`, `test_md`, `resitve_md`). Ključ in model v `.env`.
    Vsak klic zapiše trajanje in žetone v konzolo in `poraba.log`, celoten
    zadnji klic v `zadnji_klic.json`.
  - `sestavi.html` — levo sličice snovi (klik odpre galerijo s puščicami in
    Esc), povezava na surove prepise, klepet s predlogi, gumb „Kreiraj test"
    (po prvem „Posodobi test"); desno predogled A4 z merilnikom dolžine in
    črto konca strani, rešitve na svojem listu, „Natisni / PDF" z izbiro,
    ali se natisnejo tudi rešitve. Med čakanjem vrtavka s štoparico.
  - Fiksno navodilo modelu: `NAVODILO` v `server.py` (prepisano spodaj pod
    *Ugotovitve*, ko bo potrjeno).
- **Preverjeno pred predajo** (z lažnim modelom, brez pravega klica):
  izris formul, oznak prostora in črt za odgovore; tisk v PDF (naloga se ne
  razdeli čez stran, rešitve na svoji strani in samo, če so obkljukane);
  pot popravka (model dobi trenutni test in zadnjo željo); napaka modela
  pusti prejšnji test.
- **Kako preizkusiš:** glej `README.md` v `math-md-viewer` — `.env`, mapa
  `snov/` s `prepisi.md` in slikami, `python server.py`,
  <http://localhost:8000>. Natisni vsaj en test na papir.
- **Tvoje pripombe:** pred preizkusom s pravim modelom je lastnik po
  pogovoru o shranjevanju odločil, da gre takoj v krog 2 s shranjevanjem.
  Preizkus kakovosti testov s pravim modelom ostaja odprt in velja za oba
  kroga.

### Krog 2 — 2026-10-10
- **Vprašanje kroga:** ali zgodovina različic in vrnitev na prejšnjo v
  klepetnem urejevalniku res koristita, in ali je samodejno shranjevanje ob
  vsakem odgovoru modela dovolj (brez ločenega gumba „Shrani").
- **Zgrajeno:**
  - Shranjevanje v datoteke: `testi/<id>/test.json` (zamrznjena snov:
    prepisi in imena slik), `testi/<id>/slike/` (kopije), in
    `testi/<id>/razlicica-NNN.json` za vsako različico (želja, odgovor
    modela, `test_md`, `resitve_md`, poraba, čas). Pisanje prek začasne
    datoteke in preimenovanja; nov test se sestavi v začasni mapi.
  - Model pri popravku dobi **zamrznjene** prepise testa, ne trenutne
    `snov/`. Strežnik sam prebere zadnjo različico — brskalnik vsebine
    testa ne pošilja več.
  - `?test=<id>` v naslovu; osvežitev odpre isti test in sestavi klepet iz
    različic. Seznam „Testi" in gumb „Nov test".
  - Izbirnik različic nad listom in oznake `rN` v klepetu. Starejša
    različica se pokaže z rumenim pasom „Gledaš različico X od Y" ter
    gumboma „Obnovi to različico" in „Nazaj na zadnjo"; med ogledom klepet
    ne sprejema želja.
  - Obnovitev = nova različica s kopijo stare vsebine (`vir: obnovitev`).
  - Zaščita: brskalnik pošlje številko različice, na kateri temelji;
    strežnik ob neujemanju vrne 409 („spremenjeno v drugem oknu"). Na
    test hkrati teče največ eno ustvarjanje.
  - Neposlano besedilo v klepetu se hrani v `localStorage` po testu.
- **Preverjeno pred predajo** (lažni model): nov test, popravek, osvežitev
  (klepet in osnutek ostaneta), ogled stare različice, obnovitev, seznam
  testov, 409 ob zastareli različici, nov test ne podeduje osnutka.
- **Kako preizkusiš:** kot krog 1; nato osveži stran, zapri in znova odpri,
  poskusi „Testi", starejšo različico in obnovitev. Za dve okni odpri isti
  test v dveh zavihkih in pošlji željo iz obeh.
- **Tvoje pripombe:** shranjevanje poenostaviti. Na predmet se dela en test
  naenkrat; vmesnega shranjevanja in kasnejšega nadaljevanja pogovora ne
  želi (to bi pomenilo hraniti ves kontekst). Namesto zgodovine različic
  samo razveljavi/uveljavi. Shrani = test je končan, shrani se samo md.
  Pred zaprtjem okna opozorilo, da bosta test in pogovor izbrisana. Pregled
  vseh shranjenih testov z datumom in predmetom; možnost „nov test na tej
  osnovi".

### Krog 3 — 2026-10-10 (zadnji)
- **Zgrajeno:**
  - Urejanje živi **samo v brskalniku**: seznam korakov in kazalec.
    Razveljavi/Uveljavi (gumba, Ctrl+Z/Ctrl+Y izven polj). Nova želja po
    razveljavitvi zavrže razveljavljene korake. V klepetu so razveljavljeni
    koraki prečrtani.
  - Strežnik je za model **brez stanja**: brskalnik pošlje snov, trenutni
    test in rešitve, verigo dosedanjih želja (samo do kazalca) in novo
    željo. Navodilo modelu dobi razdelek o dosedanjih željah (veljajo
    naprej, npr. razred, razen če jih nova želja spremeni).
  - **Shrani** zapiše en `.md` v `testi/<datum>_<čas>_<predmet>.md`: glava
    (predmet, čas, naslov, model), nato test, rešitve in snov, ločeni z
    oznakami `<!-- TEST -->`, `<!-- RESITVE -->`, `<!-- SNOV -->`. Po
    shranjevanju se test odpre za ogled; urejanje je končano.
  - **Zavrzi** začne znova. Opozorilo pred izgubo: brskalnikovo ob
    zapiranju/osvežitvi (`beforeunload`), lastno okno pri „Nov test",
    „Zavrzi" in odpiranju shranjenega testa.
  - Predmet se razbere iz glav prepisov (`## MAT — …`, `ADR-048` D); če jih
    je več ali nobene, ga starš vpiše. Brez predmeta ni shranjevanja.
  - **Shranjeni testi**: tabela (shranjen, predmet, naslov), najnovejši
    prvi, filter po predmetu. Ogled je samo branje in tisk; **Nov test na
    tej osnovi** odpre urejevalnik s shranjenim testom kot izhodiščem
    (pod njega se ne da razveljaviti) in z njegovo snovjo.
- **Preverjeno pred predajo** (lažni model): nov test in popravek, veriga
  želja v vhodu, razveljavi/uveljavi, nova želja po razveljavitvi (veriga
  brez razveljavljene želje), lastno opozorilo, brskalnikovo opozorilo ob
  osvežitvi, shrani → ogled, seznam, nov test na osnovi (snov iz
  shranjenega testa, prazna veriga).
- **Kako preizkusiš:** `README.md` v `math-md-viewer`. Testi iz kroga 2
  (mape `testi/2026…-…/`) v novem seznamu niso prikazani.
- **Tvoje pripombe:** brez pripomb; lastnik naroči plan in izvedbo
  rešitve, kakršna je v krogu 3.

## Dogovorjeno

- 2026-10-10: To je POC (`ADR-052`), ne zahteva.
- 2026-10-10: Cilj je list, natisnjen na A4.
- 2026-10-10: Samo test, ne delovni list.
- 2026-10-10: Word zaenkrat ni potreben.
- 2026-10-10: Vhod za model je prepis, ne slika.
- 2026-10-10: Razred ni nikjer zapisan; če je potreben, ga lastnik napiše v
  klepet.
- 2026-10-10: Ročnega urejanja testa ni; spreminja se samo prek klepeta.
- 2026-10-10: Brez shranjevanja.
- 2026-10-10: POC je razširitev `math-md-viewer`, snov iz lokalne mape.
- 2026-10-10: Ločen ključ OpenAI samo za to funkcionalnost.
- 2026-10-10: Model ob popravku dobi prepise, trenutni test in rešitve ter
  samo zadnjo željo, ne zgodovine klepeta (kot `ADR-033` C).
- 2026-10-10: Model vrne JSON `sporocilo`, `test_md`, `resitve_md`.
- 2026-10-10: Rešitve s postopkom so na drugi strani in se natisnejo samo
  na izbiro.
- 2026-10-10: Prostor za odgovor je oznaka `prostor: majhen|srednji|velik`,
  kratek odgovor v vrstici `[odgovor]`; črte nariše izris, model ne riše
  podčrtajev.
- 2026-10-10: Privzeti model `gpt-5.6-terra`, `reasoning: medium`; primerjava
  z `gpt-5.6-luna` na isti snovi. Model je samo nastavitev.
- 2026-10-10: Lokalni strežnik brez dodatnih paketov drži ključ; ključ nikoli
  ne pride v brskalnik.
Dogovori kroga 2 o shranjevanju (od tu do konca bloka) so v krogu 3
**nadomeščeni** z dogovori pod njimi; ostajajo zapisani kot pot odločanja.

- 2026-10-10: Shranjevanje je samodejno ob vsakem uspešnem odgovoru modela;
  ločenega gumba „Shrani" ni, ker test spreminja samo model.
- 2026-10-10: Vsak odgovor modela je nova različica; nič se ne prepiše
  (sprememba `ADR-033` C, ki je hranil samo zadnjo vsebino — razlog zanjo je
  bilo ročno urejanje, ki ga ni).
- 2026-10-10: Vrnitev na staro različico naredi novo različico s kopijo; nič
  se ne briše in zgodovina se ne veji.
- 2026-10-10: Zapis testa nastane ob prvem uspešnem odgovoru, ne prej
  (`ADR-032` A ostane). Do takrat izbor in neposlano besedilo živita v
  brskalniku.
- 2026-10-10: Ob nastanku se zamrznejo prepisi snovi (in seznam slik);
  popravki tečejo na zamrznjeni snovi.
- 2026-10-10: Klepet se ne hrani posebej; sestavi se iz različic (želja +
  odgovor modela).
- 2026-10-10: Zaščita pred dvema oknoma z optimističnim zaklepanjem
  (številka različice, 409).
- 2026-10-10: Brez Wordove datoteke odpadeta `ADR-032` C in D (datoteka na
  disku, zastarelost dokumenta); vse je v bazi.
- 2026-10-10: Shranjevanje se preizkusi v krogu 2 POC-a z datotekami;
  produkcijska izvedba bo v bazi.

Krog 3 (veljavno):

- 2026-10-10: Na predmet se dela **en test naenkrat**. Delo v teku se ne
  shranjuje nikamor; omejitev zato velja sama od sebe (en urejevalnik).
  Prepovedi dveh zavihkov ni.
- 2026-10-10: Med urejanjem samo **razveljavi/uveljavi** v brskalniku;
  zgodovine različic na strežniku ni.
- 2026-10-10: Model dobi trenutni test, **verigo sprejetih želja** do
  trenutnega koraka (brez odgovorov modela in brez razveljavljenih želja)
  in novo željo. Tako razveljavitev ne terja posebnega sporočila modelu, in
  razred iz prve želje velja tudi pri kasnejših popravkih.
- 2026-10-10: **Shrani = test je končan.** Shrani se samo markdown: test,
  rešitve in snov (prepisi), iz katere je nastal, s predmetom in časom.
  Shranjenega testa se ne ureja.
- 2026-10-10: **Zavrzi** je druga pot iz urejevalnika.
- 2026-10-10: Pred izgubo neshranjenega testa opozorilo (brskalnikovo ob
  zapiranju, lastno znotraj strani). Zaprtje med ustvarjanjem izgubi tudi
  že plačan odgovor — sprejeto.
- 2026-10-10: Pregled shranjenih testov: datum in čas shranjevanja,
  predmet, naslov; filter po predmetu.
- 2026-10-10: **Nov test na tej osnovi**: shranjen test je izhodišče novega
  urejanja, s svojo snovjo.
- 2026-10-10: S tem odpadejo statusi `osnutek`/`pripravljen` iz `ADR-032` A
  — zapis obstaja samo za končan test. Odprto vprašanje o statusu
  „pripravljen" je s tem zaprto.

## Ugotovitve

Pred krogom 1, iz branja kode in dokumentov:

- **Funkcionalnost se prekriva z V4** (`ADR-031`–`ADR-033`,
  `docs/verzije/v4.md`). Razlike, ki jih bo ob sodbi `Sprejeto` treba zapisati
  v ADR: izhod je tisk/PDF iz HTML namesto Worda (`ADR-032`, `V4-R01`); test
  namesto delovnega lista; razred kot vnos v klepet namesto lastnosti otroka
  (`V4-R02`); brez ročnega urejanja (`V4-R05` ga predvideva).
- **Prepis ne nosi zapisa formul.** `PROMPT` v `apps/server/app/vision.py`
  naroči „formul in računov ne razlagaj — samo prepiši jih", oblike zapisa
  (LaTeX) pa ne določa. Ulomki in potence so v prepisu verjetno ploščati
  („3/4", „2 3"). POC bo pokazal, ali to modelu pri sestavljanju testa
  škodi; če da, je to sprememba vision poziva, ne tega POC-a.
- **Vrstica samih podčrtajev je v markdownu vodoravna črta** (`<hr>`), ne
  prostor za odgovor. V obstoječem `test.md` je to videti prav po naključju.
- **KaTeX s CDN-ja krši mejo 2 iz `ADR-024`** (brez CDN-ja, brez zunanje
  knjižnice). Možnosti za zahtevo: LaTeX → MathML na strežniku (brskalnik
  izriše sam, tisk dela, nova Python odvisnost), KaTeX postrežen s strežnika
  (sprememba `ADR-024`), ali CDN (sprememba `ADR-024`).
- **Model.** Ob nastanku zapisa (oktober 2026) ima OpenAI družino GPT-5.6
  (Sol, Terra, Luna). Cene po virih niso enotne; ocena za en test z Terro je
  reda 0,10–0,20 €. Izmerjene številke pridejo sem po krogu 1.
- **Izmerjeno s pravim modelom** (lastnik, 10. 10. 2026, ena snov,
  ~5 300 vhodnih žetonov za nov test):

  | Model | Vrsta | Trajanje | Izhod (od tega razmišljanje) |
  |---|---|---|---|
  | gpt-5.6-terra, medium | nov test | 19–27 s | 2 300–3 000 (600–1 000) |
  | gpt-5.6-luna, medium | nov test | 16–23 s | 1 900–2 300 (250–400) |
  | gpt-5.6-luna, medium | popravek | 14–16 s | 1 500–2 000 (60–90) |

  Ocena cene po cenah Vercel AI Gateway (Terra 2 $ / 12 $ na milijon):
  nov test s Terro ≈ 0,05 $. Ceno Lune je treba preveriti na openai.com —
  viri navajajo 0,20 $/1,20 $ do 1 $/6 $ na milijon; v vsakem primeru
  ≤ 0,02 $ na test. **Strošek ni omejitev; čakanje 15–30 s je sprejemljivo
  in pod mejo „največ okoli minute".**
- **Predpomnjenje deluje pri ponovitvi istega klica** (5 339 od 5 342
  žetonov), pri popravku pa je zajelo le ~1 300 žetonov (navodilo), ne
  snovi. Vzrok ni raziskan; pri teh cenah ni pomemben.
- Model brez navedenega razreda razred oceni sam in to pove v sporočilu
  („primeren za 5. ali 6. razred").
  API ID je `gpt-5.6-terra`; po Vercel AI Gateway 2 $ vhod, 0,20 $
  predpomnjen vhod, 12 $ izhod na milijon žetonov; razmišljanje šteje v izhod.
- **`\frac` v vrstici je za otroka premajhen** (KaTeX ga izriše v velikosti
  besedila). Izris ga zamenja z `\dfrac`; enako bo veljalo za produkcijski
  izris, ne glede na knjižnico.
- **Tisk:** brskalnik privzeto ne tiska ozadij, zato so črte za odgovore
  robovi elementov, ne ozadje. Vsaka naloga je zavita v element z
  `break-inside: avoid`, da se ne razdeli čez stran. Rob strani je v
  `@page` (15 mm / 18 mm), ne v odmiku lista — sicer druga stran nima
  zgornjega roba. Chrome privzeto doda glavo in nogo (naslov, datum); v
  pogovornem oknu jih je treba izklopiti.
- **Merilnik dolžine** deli višino vsebine z natisljivo višino strani
  (297 − 30 mm). Je ocena: ker se naloge ne delijo, je natisnjenih strani
  lahko več, kot kaže število.

- **Oblika vhoda v model (krog 3).** Navodilo gre v `instructions`, vse
  ostalo v en sam `input` v tem vrstnem redu (snov prva, da jo OpenAI lahko
  vzame iz predpomnilnika):

  ```
  SNOV (prepisi iz zvezka, najstarejši prvi):
  <<<
  <besedilo strani „Prepisi izbranih">
  >>>

  DOSEDANJE ŽELJE (trenutni test jih že upošteva):   ← samo pri popravku
  1. …
  TRENUTNI TEST: <<< … >>>                           ← samo pri popravku
  TRENUTNE REŠITVE: <<< … >>>                        ← samo pri popravku

  NOVA ŽELJA STARŠA (popravi trenutni test):  /  ŽELJA STARŠA (sestavi nov test):
  <želja>
  ```

  Izhod je strukturiran (Responses API, `text.format` = `json_schema`,
  `strict: true`) s tremi obveznimi nizi `sporocilo`, `test_md`,
  `resitve_md`. Prazen `test_md` pomeni, da model testa ni mogel sestaviti
  (sporočilo pove zakaj). `reasoning.effort = medium`,
  `max_output_tokens = 20000`.
- **Navodilo modelu, kakršno je bilo sprejeto v krogu 3** (dobesedno; koda
  POC-a se zavrže, zato je tukaj edini zapis):

  ```text
  Si izkušen učitelj matematike v slovenski osnovni šoli. Iz prepisov učenčevega
  zvezka sestaviš pisni test, ki ga starš natisne na papir A4 in ga da otroku
  reševati s svinčnikom.

  VSEBINA
  - Naloge izhajajo SAMO iz priložene snovi: isti tipi nalog, isti pojmi,
    podobna težavnost. Ne dodajaj snovi, ki je v prepisih ni.
  - Prepisi so dobesedni prepisi fotografij zvezka in so lahko nepopolni:
    ulomki so lahko zapisani ploščato (3/4), potence brez nadpisa (2 3 namesto
    2^3), deli so lahko označeni [neberljivo]. Iz konteksta razberi, kaj je
    mišljeno. Iz delov, ki jih ne razumeš, ne sestavljaj nalog.
  - Test nima slik. Ni nalog, ki zahtevajo sliko, graf, skico, mrežo ali
    geometrijsko konstrukcijo. Če je snov taka, sestavi računske ali besedilne
    naloge o istih pojmih, ali v sporočilu povej, česa ni mogoče.
  - Če snovi ni dovolj za smiseln test, to povej v polju "sporocilo" in ne
    zapolnjuj testa z nepovezanimi nalogami.
  - Številke izberi tako, da se računi lepo izidejo, kot v šolskih nalogah.
  - Vsako nalogo sam reši in preveri, preden jo vrneš. Rešitve morajo biti
    pravilne.
  - Če starš ne pove razreda, ga oceni iz snovi. Če ne pove dolžine, naj bo
    test dolg eno stran A4: okoli 5 do 7 nalog, od lažjih k težjim.

  ZAPIS (slovenski šolski zapis)
  - Decimalna vejica (3,5), nikoli pika. Množenje \cdot, deljenje z
    dvopičjem (:). Velika števila s presledkom (12 500).
  - Oznake kot v slovenskih učbenikih, npr. D(a, b) za največji skupni
    delitelj in v(a, b) za najmanjši skupni večkratnik.
  - Besedilo v slovenščini, kratko in jasno, v 2. osebi ednine (Izračunaj,
    Reši, Zapiši). Pazi na dvojino: 1 točka, 2 točki, 3 točke, 4 točke,
    5 točk.

  OBLIKA polja "test_md" (markdown)
  - Matematiko piši v LaTeX: v vrstici $...$, samostojno $$...$$. Drugih
    oznak ne uporabljaj: brez \( \), brez HTML, brez slik, brez barv, brez
    emojijev, brez tabel. Test je črno-bel.
  - Prva vrstica: "# " in naslov testa (npr. "# Preverjanje znanja – ulomki").
  - Druga vrstica natanko:
    **Ime in priimek:** [odgovor-dolg] **Datum:** [odgovor] **Točke:** [odgovor-kratek] / N
    kjer je N vsota točk vseh nalog.
  - Vsaka naloga se začne z vrstico "## N. Kratek naslov (X točk)", N je
    zaporedna številka od 1 naprej. Pod njo navodilo v enem stavku.
  - Podnaloge piši kot ločene odstavke "a) ...", "b) ..." (vsaka v svoji
    vrstici, med njimi prazna vrstica).
  - Kjer otrok vpiše kratek rezultat v vrstico, napiši [odgovor]
    (npr. "a) $\frac{3}{4} + \frac{1}{8} =$ [odgovor]").
  - Kjer otrok potrebuje prostor za računanje, napiši samostojno vrstico
    "prostor: majhen", "prostor: srednji" ali "prostor: velik"
    (približno 2, 4 ali 7 vrstic). Prostor odmeri po zahtevnosti računa.
  - Nikoli ne riši črt s podčrtaji (____) in ne uporabljaj ločil "---".

  OBLIKA polja "resitve_md" (markdown, isti zapis matematike)
  - Prva vrstica "# Rešitve". Za vsako nalogo "## N." z istimi številkami in
    podnalogami kot v testu. Kratek postopek v nekaj korakih, končni rezultat
    krepko (**...**).

  POPRAVKI
  - Ko dobiš TRENUTNI TEST in novo željo starša, vrni CELOTEN popravljen test
    in celotne rešitve. Spremeni samo to, kar starš želi, in kar je zaradi
    tega nujno (številčenje, vsota točk). Ostale naloge pusti dobesedno enake.
  - DOSEDANJE ŽELJE so želje, ki jih trenutni test že upošteva. Veljajo še
    naprej (npr. razred, dolžina, vrste nalog), razen če jih nova želja
    izrecno spremeni.

  POLJE "sporocilo"
  - 1 do 3 kratki stavki v slovenščini: kaj si naredil ali spremenil, in
    morebitno opozorilo (npr. del snovi je bil neberljiv). Brez pozdravov.
  ```
- **Dogovorjene oznake v `test_md`, ki jih izriše stran:** `[odgovor]`
  (črta 30 mm), `[odgovor-kratek]` (14 mm), `[odgovor-dolg]` (52 mm), in
  samostojna vrstica `prostor: majhen|srednji|velik` (2, 4 ali 7 črt po
  8,5 mm). Izris zamenja vsak `\frac` z `\dfrac`. Naloga (od `##` do
  naslednjega `##`) se ob tisku ne razdeli.

Odprto po krogu 2 (ni odločeno):

- **Status „pripravljen"** je v V4 pomenil „Word ustvarjen". Brez Worda ga je
  treba na novo opredeliti (ročno „Zaključi", ob tisku, ali brez njega) —
  povezano z opombo in zaklepom (`V4-R06`).
- **Hkratno urejanje na dveh napravah** — ali zadošča 409 ali je potrebno
  samodejno osveževanje.

## Sodba

**2026-10-10 — `Sprejeto`.** Lastnik je s pravim modelom (`gpt-5.6-terra`
in `gpt-5.6-luna`) sestavil več testov iz svoje snovi, preizkusil vse tri
kroge in naročil izvedbo rešitve iz kroga 3. Izvedba gre kot nova zahteva po
polni poti (`CLAUDE.md` §1d, korak 6); ADR in zahteva nastaneta ob zapisu v
`main` (korak 5).
