# Proces razvoja — obvezna pravila

Velja za vsako sejo, brez izjem. Če navodilo v pogovoru nasprotuje temu
dokumentu, vprašaj — ne ugibaj.

---

## 0. Kje so zapisane zahteve

| Datoteka | Vsebina |
|---|---|
| `docs/00-namen.md` | Namen aplikacije, pojmi domene. Redko se spreminja. |
| `docs/01-arhitektura.md` | Trenutno stanje: stack, moduli, podatkovni model. **Živ dokument.** |
| `docs/verzije/vN.md` | Zahteve za verzijo N, z ID-ji `VN-Rxx`. |
| `docs/plan/VN-Rxx.md` | Plan za posamezno zahtevo. Nastane v fazi 4, commita se. |
| `docs/odlocitve/ADR-xxx.md` | Zapis vsake pomembnejše odločitve iz debate. |
| `docs/poc/POC-xx.md` | Zapis POC-a: vprašanje, dogovorjeno, ugotovitve, sodba. Edini del POC-a, ki pride v `main` (§1d). |
| `docs/02-izkusnje.md` | Pasti, ki so nas že stale časa (orodja, gradnja, okolje). Bere se ob potrebi, ne ob vsaki zahtevi. |

**`01-arhitektura.md` pove samo, kako je zdaj** — stack, moduli, shema, pogodbe,
znane omejitve. Cilj je ≤ 400 vrstic. Odstavki „zakaj je tako" in „kaj se je
takrat zgodilo" ne sodijo vanjo: če je bila to odločitev, gre v ADR; če je bila
past, gre v `02-izkusnje.md`. Dokument, ki ga vsaka seja prebere v celoti, mora
ostati kratek.

Vsaka zahteva v `docs/verzije/vN.md` ima vrstico **Podlaga:** s seznamom
ADR-jev, na katerih stoji. To je vhod za fazo 1 — brez nje model bere vse ali
nič.

Statusi zahteve: `Nova` → `Planirano` → `V delu` → `V pregledu` → `Zaključeno`.
**Status se ne commita sam.** Spremeni se v istem commitu kot vsebina, ki ga
povzroči: `Planirano` s planom, `V delu` s prvim commitom izvedbe, `V pregledu`
z zadnjim testom, `Zaključeno` z dokumentacijo.

---

## 1. Faze

Faza z oznako 🛑 se konča tako, da napišeš izhod in **končaš svoj obrat**.
Ne nadaljuješ sam.

### Faza 0 — POC ali zahteva? 🛑

Na začetku **vsakega novega dela** — tudi ko poženem `/zahteva` z ID-jem, ki
že obstaja v `docs/verzije/` — me najprej vprašaj:

> Gre za **POC** (preverjam idejo, koda se zavrže) ali za **dokončno
> zahtevo** (polna pot od faze 1)?

in končaj obrat. Vprašaj tudi, če se odgovor iz naročila zdi očiten — je ena
beseda. POC → §1d, zahteva → faza 1. Vprašanje odpade samo pri nadaljevanju
dela, ki je že začeto na svoji veji (`feat/…`, `fix/…`, `poc/…`).

### Faza 1 — Razumevanje 🛑

Preberi zahtevo, `docs/00-namen.md`, `docs/01-arhitektura.md`,
`docs/verzije/vN.md` tekoče verzije in ADR-je, ki jih zahteva navaja pod
**Podlaga**. Ostale ADR-je preleti **po naslovih** (`ls docs/odlocitve`) in
odpri le tiste, ki se zahteve očitno tičejo. Planov v `docs/plan/` ne beri —
so zapis za človeka, ne vhod za model. Nato preveri, ali je zahteva enoumna.

Vprašaj me, če velja karkoli od tega:

- pojem, ki ni definiran nikjer v `docs/`
- zahteva dopušča več implementacij z opazno različnimi posledicami
- ni jasno, kaj se zgodi v robnem primeru (prazno, napaka, hkratni dostop, prevelik vnos)
- ni jasno, kaj sproži funkcionalnost in kaj je vidni rezultat
- manjka kriterij, po katerem bo mogoče reči "to je narejeno"

Pravilo praga: **če bi svojo interpretacijo zapisal z besedo "predvidevam",
"verjetno", "najbrž" ali "po mojem" — to ni predpostavka, to je vprašanje.**

```
## Razumem tako
<parafraza v 3–6 vrsticah>

## Vprašanja
1. <vprašanje> — zakaj je pomembno: <posledica obeh odgovorov>

## Predpostavke, ki jih bom uporabil, če ne rečeš drugače
- ...
```

Če vprašanj ni, to izrecno napiši in nadaljuj.

### Faza 2 — Preverba smiselnosti 🛑 (samo če najdeš dvom)

Zdaj, ko je zahteva jasna, preveri, ali je **prava**:

- **Je že implementirana?** Poišči v kodi. Če je delno, povej kaj manjka.
- **Ali kaj podira?** Katere zahteve `VN-Rxx` bi prenehale veljati? Kateri testi
  bi padli? Kateri API-ji, sheme ali shranjeni podatki se spremenijo?
- **Je v nasprotju s prejšnjo odločitvijo?** Preveri `docs/odlocitve/`.
- **Obstaja opazno boljša pot?** Predlagaj jo, tudi če te nisem vprašal.
- **Migracija:** ali obstoječi podatki po tej spremembi še vzdržijo?

Brez dvoma: napiši "Preverba čista: <kaj si preveril>" in nadaljuj.
Z dvomom: opiši ga, predlagaj alternativo, **ustavi se**. Ko se dogovoriva,
zapiši izid v `docs/odlocitve/ADR-xxx.md`.

### Faza 3 — Branch

**Branch nastane pred planom, ne pred implementacijo.** Plan je artefakt te
zahteve in mora živeti na njeni veji, sicer se pri prehodu med sejami izgubi.

```powershell
git switch main
git pull --ff-only
git switch -c feat/v1-r03-kratek-opis
```

Pravila:

- Vedno iz svežega `main`, nikoli iz drugega feature brancha.
- Ena zahteva = en branch. Ime: `feat/<verzija>-<id>-<kratek-opis>`, popravki `fix/...`.
- Če je delovni imenik umazan, se **ustavi** in vprašaj. Nikoli ne stash-aj in
  ne resetiraj mojega dela.
- Vse nadaljnje faze tečejo v tem istem worktreeju. Nova seja pomeni novo sejo
  v isti mapi, ne nove mape.

Posodobi status zahteve na `Planirano`.

### Faza 4 — Vpliv in plan 🛑 (če plan zahteva odločitev)

Najprej se odloči po lestvici spodaj, ali plan sploh nastane kot datoteka.
Če nastane, ga napiši po `docs/plan/PREDLOGA.md` in commitaj:

```powershell
git add docs/plan/VN-Rxx.md docs/verzije/
git commit -m "VN-Rxx: plan"
```

Commit plana je pomemben. Če se pozneje izkaže, da je bil plan napačen, hočem
videti, kaj je bilo takrat dogovorjeno.

Odloči se sam po tej lestvici:

- **Nizko tveganje** (znotraj obstoječih vzorcev, brez nove odvisnosti, brez
  migracije sheme, brez spremembe javnega vmesnika, ≲ 3 datoteke) → **kratka
  pot** (§1c): plan je nekaj vrstic v poročilu, ne datoteka; nadaljuj brez
  čakanja.
- **Vse ostalo** → napiši `docs/plan/VN-Rxx.md`, ga commitaj, 🛑 povej, da je
  plan commitan, in počakaj na moj "gremo".

Če nisi prepričan, v katero skupino spada, spada v drugo.

Med čakanjem plan popravim neposredno v datoteki. Ko rečem "gremo", ga **preberi
znova z diska** — moja verzija velja, ne tvoj spomin nanj.

### Faza 5 — Implementacija

Status na `V delu`.

- Drži se plana. Če ugotoviš, da plan ne drži, se **ustavi** in povej.
- Ne spreminjaj stvari zunaj obsega zahteve. Kar opaziš mimogrede, si zapiši in
  povej na koncu.
- Commitaj sproti na feature branch. Sporočila `VN-Rxx: <kaj>`.

### Faza 6 — Testi (zanka)

Napiši teste iz plana, plus:

- srečno pot,
- vsak robni primer, razčiščen v fazi 1,
- regresijski test za vsako zahtevo, za katero si v fazi 2 rekel, da bi jo lahko razbila.

Zaženi celoten paket. **Če testi padejo:** popravi in poženi znova. Zanka je
tvoja odgovornost.

Ustavi se in vprašaj, ko:

- trije neuspešni poskusi popravka istega testa,
- popravek bi zahteval spremembo obstoječega, prej zelenega testa,
- test kaže, da je bila zahteva sama napačno zastavljena.

Nikoli ne "popravi" testa tako, da ga oslabiš, izključiš ali označiš za `skip`.

### Faza 7 — Neodvisen pregled

Status na `V pregledu`. Pokliči:

```
@pregledovalec preglej VN-Rxx
```

Ta agent nima orodij za pisanje. Pregleda commitano, staged, necommitano **in
nesledene datoteke** — ne samo diff proti `main`.

- `VRNI V POPRAVEK` → popravi kritične točke, nazaj na fazo 6, pokliči ga znova.
  Njegovih pripomb ne zavračaj brez utemeljitve; če se ne strinjaš, povej meni.
- **Tretjič isto mesto → nazaj v fazo 2.** Če pregledovalec tretjič vrne isto
  mesto (isti ADR, ista funkcija, isti robni primer), popravka ne pišeš več.
  Ustavi se in vprašaj: *je napaka v izvedbi ali v odločitvi, ki jo izvedba
  varuje?* Predlagaj vsaj eno alternativo, ki spremeni **odločitev**, ne kode
  (npr. pogodbo med telefonom in strežnikom). Trije popravki iste odločitve so
  znak, da je bila odločitev napačna, ne izvedba.
- `PRIPRAVLJENO ZA ČLOVEŠKI PREGLED` → naprej.

### Faza 8 — Zaključni dostavek

**Vse, kar mora priti v `main`, mora biti commitano na tej veji.** Po mergu
commit na `main` ni mogoč, ker ga ograja blokira.

Na tej veji zato zdaj:

1. Posodobi status zahteve v `docs/verzije/vN.md` na `Zaključeno` in vpiši ime veje.
2. Dopolni `docs/01-arhitektura.md`, če se je stanje spremenilo.
3. Commitaj: `git commit -m "VN-Rxx: zaključek in dokumentacija"`.

Nato poženi celotno preverbo:

```powershell
pwsh -File scripts/verify.ps1
```

Skripta zapiše rezultat, vezan na trenutni HEAD. Merge brez zelenega rezultata
za točno ta commit ne bo mogoč. Če po tem karkoli commitaš, jo poženi znova.

### Faza 9 — Poročilo 🛑 KONEC AVTOMATIKE

```
## Končano: VN-Rxx
Branch: feat/...

### Kaj je narejeno
...

### Commiti
<git log --oneline main..HEAD>

### Datoteke
<git status --short>

### Pregledovalec
<sodba in ključne ugotovitve>

### Verify
<izpis scripts/verify.ps1 in HEAD, na katerem je tekel>

### Kako preveriš ročno
1. ...

### Za pogovor
- <kar si opazil zunaj obsega>
```

Nato **končaj obrat.** Jaz pregledam in preizkusim.

### Faza 9b — Sprejem 🛑

Zdaj preizkusim sam. **Zahteva, ki spremeni vedenje na telefonu, se ne merga,
dokler ni preizkušena na napravi z APK iz te veje** — ne z razvojno gradnjo.
Razvojna gradnja ne pokaže razreda napak, ki nastanejo ob gradnji
(`docs/odlocitve/ADR-010`). Kar najdem, ne gre samodejno ne v to zahtevo ne v novo —
najprej ga uvrstiva. Ločnica ni velikost, ampak **ali obstoječi dogovor kršiš
ali ga širiš**:

| Izid | Kaj to pomeni | Kam gre |
|---|---|---|
| **Napaka** | Dostavljeno se ne ujema s kriterijem sprejemljivosti ali z merilom dokončanosti. Nič novega ne zahtevam. | Nazaj na fazo 5, **ista veja, ista zahteva.** Nova postavka ne nastane. |
| **Sprememba zahteve** | Novo vedenje ali vedenje, ki nasprotuje kriteriju oz. sprejeti odločitvi. | Odločim jaz — glej spodaj. |
| **Sprejeto** | Nič od zgornjega. | Faza 10. |

Preizkus uvrstitve: **pripombo poskusi preslikati nazaj na kriterij, zapisano
predpostavko ali odločitev.** Če se da — napaka. Če se ne da — sprememba.
Če nisi prepričan, vprašaj mene; ne uvrsti sam v svojo korist.

**Sprememba zahteve pred sprejemom** sme v tekočo zahtevo, ker obseg do
sprejema ni zaklenjen — vendar samo tako, da se popravi izhodišče, ne samo
koda. Tiho dodana koda je razraščanje obsega. Zaporedje:

1. `docs/odlocitve/ADR-xxx.md` — kaj se spreminja, zakaj, katero prejšnjo
   odločitev razveljavlja.
2. `docs/verzije/vN.md` — popravljen ali dodan kriterij sprejemljivosti.
3. Status zahteve nazaj na `V delu`.
4. Faze 5–9 znova, vključno z novim pregledom in novim verify.

**Po sprejemu** (zahteva je mergeana) pogajanja ni več: sprememba je nova
zahteva `VN-Rxx`.

### Faza 10 — Merge (samo na moj izrecni ukaz)

Gate odprem jaz, zunaj repozitorija. Ko rečem "merge":

```powershell
git switch main
git merge --no-ff feat/... -m "Merge VN-Rxx"
```

Če je zgodovina veje razdrobljena, mi prej predlagaj squash.
Ko so vse zahteve verzije `Zaključeno` in merge-ane, predlagaj tag `vN.0.0`.

---

## 1b. Merilo dokončanosti

Velja za **vsako** zahtevo in se v kriterijih posameznih zahtev ne ponavlja.
Kriteriji v `docs/verzije/vN.md` povedo, *kaj* mora zahteva znati; ta seznam
pove, *kdaj* je karkoli od tega sploh dokončano. Kršitev tega seznama je
napaka po fazi 9b, ne nova zahteva.

- **Varno območje.** Vsak zaslon z vsebino ali gumbi ob robu upošteva sistemske
  odmike (na Androidu je edge-to-edge privzet). Preverjeno na napravi, ne le v
  testu.
- **Jezik vmesnika je slovenščina.** Sporočila o napakah povedo, kaj naj
  uporabnica naredi, in ne kažejo surovega besedila sistemske napake kot
  edine vsebine.
- **Brez omrežja v verziji 1**, dokler zahteva tega izrecno ne uvede.
- **Zeleno:** `lint`, `typecheck`, testi — in verify, vezan na trenutni HEAD.
- **Testi kaj dokazujejo.** Test, ki ostane zelen ob pokvarjeni implementaciji,
  ne šteje. Ob dvomu mutiraj kodo in preveri, da test pade.
- **Ponovljivost.** Zbirka je zelena tudi ob hladnem predpomnilniku in na
  svežem klonu, ne samo na tvojem stroju.
- **Brez ostankov generatorjev.** Kar je pustil `create-*` in se ne uporablja,
  gre ven.
- **Delovni imenik je čist** in vse je commitano na veji zahteve.

Seznam raste iz izkušenj: ko se kaj pokaže kot ponavljajoča se napaka, sodi
sem, ne v kriterije ene zahteve.

---

## 1c. Kratka pot

Ne gre vsaka sprememba skozi vseh deset faz. **Kratka pot** velja, kadar so
izpolnjeni vsi pogoji iz lestvice v fazi 4 (znotraj obstoječih vzorcev, brez
nove odvisnosti, brez migracije sheme, brez spremembe javnega vmesnika,
≲ 3 datoteke). Če nisi prepričan, kratka pot ne velja.

Kratka pot: faza 1 (vprašanja) → branch → izvedba in testi → pregledovalec →
verify → poročilo. Razlike od polne poti:

- plana kot datoteke ni — plan je do pet vrstic v poročilu (kaj, kje, kateri
  testi);
- `docs/01-arhitektura.md` se dopolni samo, če se je stanje res spremenilo;
- ADR nastane samo, če je bila sprejeta odločitev, ki bi jo kdo kdaj iskal.

Če se med delom izkaže, da kateri pogoj ne drži (migracija, četrta datoteka,
sprememba vmesnika), preskoči na polno pot: plan se napiše takrat in se
commita, delo do tega trenutka ostane na veji.

Kar je enako: faza 1, pregledovalec, verify vezan na HEAD, merilo dokončanosti,
trdi robovi. Kratka pot skrajša pisanje, ne pregleda.

---

## 1d. POC pot

POC odgovori na **eno vprašanje**: ali je ideja prava (videz, potek,
uporabnost) ali ali tehnično sploh gre. Edini trajni izdelek je **sodba in kar
sva se dogovorila** — koda se zavrže (`ADR-052`).

Oblika se izbere v koraku 1:

- **Idejni/UX** — kako bi izgledalo in teklo. Po možnosti več različic istega
  zaslona s stikalom med njimi, da jih primerjaš drugo ob drugi.
- **Tehnični (spike)** — ali gre (model, knjižnica, zmogljivost). Najmanjši
  program, ki odgovori na vprašanje; vmesnik samo, če je vmesnik vprašanje.

Koraki:

1. **Vprašanje 🛑.** Naslednji prosti `POC-xx` (`ls docs/poc`, tudi na vejah
   `poc/…`). Veja `poc/xx-kratek-opis` iz svežega `main`. Na njej
   `docs/poc/POC-xx.md` po `docs/poc/PREDLOGA.md`: vprašanje, oblika, kaj
   šteje kot »ok«, kaj namenoma ne rešujem. Commitaj in počakaj na potrditev.
2. **Krog.** Zgradi in povej, kako preizkusim. En krog = ena seja. 🛑
3. **Pregled.** Kar se zmeniva, **takoj** zapiši v *Dogovorjeno* in commitaj —
   ne samo v pogovor. Kar si izvedel iz kode, gre v *Ugotovitve*.
4. **Sodba 🛑 (moja).** `Sprejeto`, `Zavrženo` ali `Še en krog`. Največ trije
   krogi; četrti samo, če ga izrecno odobrim in to piše v `POC-xx.md`.
5. **Zapis v `main`.** Iz svežega `main` veja `docs/poc-xx-kratek-opis`; nanjo
   prenesi samo zapis (`git checkout poc/xx-… -- docs/poc/POC-xx.md`) s sodbo.
   Pri `Sprejeto` dodaj še ADR z odločitvijo in novo zahtevo `VN-Rxx` v
   `docs/verzije/vN.md` (status `Nova`, **Podlaga:** ta ADR in `POC-xx`,
   kriteriji sprejemljivosti iz *Dogovorjeno*). Poročilo 🛑, merge na moj ukaz.
   Zapis gre v `main` tudi pri `Zavrženo`, da istega vprašanja ne preverjava
   dvakrat.
6. **Implementacija** je nova zahteva po polni poti, od faze 0.

Pravila:

- **Veja `poc/…` se nikoli ne merga**; iz nje se v `main` prenese samo
  `docs/poc/POC-xx.md`. Veja ostane kot referenca, brisanje je moje.
- **Koda POC-a ni vhod za zahtevo.** V fazah 1–5 je ne bereš in ne kopiraš,
  niti po delih. Kar je bilo vredno vedeti, mora biti v *Ugotovitvah* — POC se
  ne zapre, dokler razdelek ni izpolnjen.
- **Ne velja:** plan, testi, pregledovalec, verify, merilo dokončanosti (§1b),
  statusi zahteve. Kakovost je »dovolj, da odgovori na vprašanje«: brez novih
  abstrakcij, deljenih modulov in obravnave napak, ki je vprašanje ne rabi.
- **Velja:** trdi robovi (§2) in še:
  - nikoli proti javnemu strežniku ali pravim podatkom družin — lokalno, z
    ločeno bazo;
  - brez migracij sheme nad obstoječimi podatki;
  - na telefonu zadošča razvojna gradnja; APK iz veje je pogoj šele pri
    zahtevi (faza 9b).
- Commit sporočila `POC-xx: <kaj>`.

---

## 2. Trdi robovi

1. Nobenega merga, pusha ali taga brez mojega izrecnega ukaza v tej seji.
   Prejšnje dovoljenje ne velja za naslednjo zahtevo.
2. Commit na feature branch je prost. Commit na `main` ni.
3. Nobenega `git reset --hard`, `git clean -fd`, `git push --force`,
   `git rebase`, brisanja branchev ali worktreejev.
4. **Ograje ne odpiraš in ne spreminjaš.** Mapa `.claude-gates`, datoteke v
   `.claude/hooks/`, `.claude/settings.json` in `scripts/verify.ps1` niso
   tvoje. Če je katera od njih narobe, mi to povej; ne popravi je sam.
5. Nobene nove zunanje odvisnosti brez vprašanja.
6. Nobenih skrivnosti v repozitoriju. `.env` je v `.gitignore`.
7. Veja `poc/…` se nikoli ne merga v `main` (§1d). Če ti to naročim, me
   opozori nanj.

## 3. Zamik med planom in kodo

**Plan se za nazaj nikoli ne prepisuje.** `docs/plan/VN-Rxx.md` je zapis, kaj
je bilo takrat dogovorjeno, in prav v tem je njegova vrednost. Kar ga
preglasi, gre v `docs/odlocitve/ADR-xxx.md`, ki pove, katero odločitev
razveljavlja. Plan ostane, kakršen je bil.

Če je od faze 4 minilo več dni in se je `main` medtem premaknil, plana ne
popravljaj. Povej mi, koliko je `main` naprej (`git log --oneline HEAD..main`),
in predlagaj, ali gre za rebase obsega ali za nov cikel od faze 1.

## 4. Ko sem odsoten

Stroj teče 24/7 in seja lahko čaka. **Čakanje je pravilen izid.** Ne izogibaj se
vprašanju samo zato, da bi lahko nadaljeval. Raje tri dobra vprašanja naenkrat
kot eno na uro.
