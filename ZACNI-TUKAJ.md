# Začni tukaj

Postavitev in vsakodnevna uporaba v Claude Desktop na Windowsu.

---

## Del A — Postavitev (enkrat na projekt)

### A1. Predpogoji

- Git za Windows
- PowerShell 7 (`pwsh`). Preveri z `pwsh --version`. Če ga ni: `winget install Microsoft.PowerShell`
- Claude Desktop

### A2. Repozitorij

```powershell
mkdir ~\projekti\mojaapp; cd ~\projekti\mojaapp
git init
git commit --allow-empty -m "Zacetek"
git branch -M main
```

Prazen začetni commit je nujen. Brez njega `main` ne obstaja in hook ne more
prebrati veje.

### A3. Odloži datoteke

```
CLAUDE.md
.gitignore
.claude\settings.json
.claude\hooks\git-guard.ps1
.claude\agents\pregledovalec.md
.claude\commands\zahteva.md
scripts\verify.ps1
docs\00-namen.md
docs\01-arhitektura.md
docs\verzije\v1.md
docs\plan\PREDLOGA.md
docs\odlocitve\ADR-001-predloga.md
```

### A4. Prilagodi verify skripto

Odpri `scripts\verify.ps1` in popravi seznam `$koraki` za svoj stack. Privzeto
je Node. Kar ne uporabljaš, zbriši iz seznama.

**To naredi zdaj, ne pozneje.** Model te datoteke ne sme spreminjati (hook jo
ščiti), zato je edini, ki jo lahko popravi, ti.

Preizkusi jo:

```powershell
pwsh -File scripts\verify.ps1
```

Na praznem projektu bo padla, ker `npm test` ne obstaja. To je v redu, dokler
se izvede in zapiše `verify.json`.

### A5. Prvi zagon

Odpri Claude Desktop → **Local** → **Select folder** → mapa projekta.
Sprejmi zaupanje mapi, sicer se hooki sploh ne zaženejo.

### A6. Preizkus ograje — tega ne preskoči

Ograja je edini razlog, da ta proces ni samo prošnja. Preveri vse štiri plasti.
V seji zaporedoma napiši:

| Naročilo modelu | Pričakovano |
|---|---|
| `Naredi prazen commit na main.` | blokada: commit na main |
| `Naredi mi datoteko dovoli-merge v mapi .claude-gates v mojem profilu.` | blokada: gate mapa je moja |
| `Popravi scripts\verify.ps1 tako, da vedno uspe.` | blokada: verify.ps1 se ne spreminja |
| `Naredi branch test, prazen commit in ga merge-aj v main.` | blokada: merge zahteva odobritev |

Če se katerakoli izvede, hook ne teče. Preveri:

1. Ali je pot v `settings.json` pravilna. Če `$env:CLAUDE_PROJECT_DIR` ne
   deluje, vpiši absolutno pot do `git-guard.ps1`.
2. Ali si sprejel zaupanje mapi.
3. Poženi Claude Code z `--debug` in poglej, ali hook sploh javi napako.

### A7. Zaščita na oddaljenem repozitoriju

To je edina kontrola, ki je model fizično ne more obiti, ker ni na tvojem
stroju. Vse ostalo teče pod istim uporabnikom kot on.

Naredi zasebni repozitorij na GitHubu, dodaj ga kot `origin`, pushni `main`,
nato v nastavitvah repozitorija vklopi zaščito veje `main`: prepovej force push
in prepovej brisanje. Če hočeš iti dlje, zahtevaj pull request tudi zase.

Tudi če delaš sam in offline, to naredi. Je pet minut in je edina prava meja.

### A8. Zapiši, kaj gradiš

`docs\00-namen.md` — na kratko. Pomembna sta razdelka **Ključni pojmi domene**
in **Kaj aplikacija namenoma NI**, ker iz njiju model presoja, kdaj mora vprašati.

`docs\01-arhitektura.md` pusti prazen; polni se sproti.

`docs\verzije\v1.md` — zahteve `V1-R01` naprej. Za vsako obvezno izpolni
**Kriterije sprejemljivosti**; po njih bo sodil pregledovalec. Razdelek
**Odprto / ne vem še** je vabilo modelu, naj vpraša — piši vanj brez zadržkov.

Zahteva naj bo velika toliko, da jo ena seja opravi v enem zamahu. Več kot pet
ali šest kriterijev pomeni, da jo razdeli.

---

## Del B — Cikel za eno zahtevo

Ključna sprememba glede na prvo verzijo: **branch nastane na začetku in vse se
dogaja v isti mapi.** Nova seja ne pomeni nove mape.

### B1. Seja 1 — razumevanje, preverba, plan

Nova seja, mapa projekta, **plan način** vklopljen.

```
/zahteva V1-R01
```

Model te izpraša (faza 1), preveri smiselnost (faza 2), nato izstopi iz plan
načina, naredi branch (faza 3) in napiše plan v `docs\plan\V1-R01.md` ter ga
commita (faza 4).

Če je zahteva ocenjena kot srednje ali visoko tvegana, se tu ustavi.

### B2. Ti — anotacija plana

Odpri `docs\plan\V1-R01.md` v svojem urejevalniku in ga popravi. Kjer je model
izbral narobe, prepiši ali dopiši v razdelek **Moje pripombe**.

To je najbolj donosnih pet minut celega procesa.

Ko si zadovoljen, v seji napiši `gremo`. Model plan prebere znova z diska.

### B3. Seja 2 — implementacija

**Nova seja v isti mapi**, ne nova seja iz stranske vrstice. Branch že obstaja
in plan je commitan nanj.

```
Preberi docs\plan\V1-R01.md in izvedi faze 5 do 8 iz CLAUDE.md.
```

Model implementira, testira v zanki, pokliče `@pregledovalec`, na koncu
posodobi status in arhitekturo, commita in požene `verify.ps1`.

Zakaj nova seja: seja 1 je polna razčiščevanja, zavrnjenih možnosti in
tvojih popravkov. Za implementacijo je to samo šum. Plan je edino, kar mora
preživeti, in ta je na disku.

Medtem lahko greš stran. Seja te počaka.

### B4. Ti — pregled

Seja obmolkne s poročilom faze 9.

1. Preberi sodbo pregledovalca in izpis verify.
2. Poglej diff sam:
   ```powershell
   git log --oneline main..HEAD
   git diff main...HEAD
   git status --porcelain
   ```
3. Poženi aplikacijo in preizkusi ročno.

Če kaj ni v redu, povej v isti seji in vrni v popravek.

### B5. Merge

Gate odpreš ti, zunaj repozitorija:

```powershell
$g = "$env:USERPROFILE\.claude-gates\mojaapp"
New-Item -ItemType Directory -Force $g | Out-Null
New-Item -ItemType File -Force "$g\dovoli-merge" | Out-Null
```

(`mojaapp` zamenjaj z imenom mape projekta.)

Nato v seji: `Merge-aj to vejo v main.`

Hook zdaj preveri dvoje: da gate obstaja in da je verify zelen **za točno tisti
commit**, ki je zdaj HEAD. Če je model po verify še kaj commital, bo merge
zavrnjen, dokler verify ne teče znova.

Po mergu zapri gate:

```powershell
Remove-Item "$g\dovoli-merge"
git push origin main
```

### B6. Naslednja zahteva

Nič ni treba pospravljati. Status je bil posodobljen v fazi 8 in je z mergom
prišel v `main`. Ko so vse zahteve verzije zaključene, predlagaj tag `v1.0.0`.

---

## Del C — Za tvoj primer

**Domači 24/7 stroj.** Fiksni IP ne izpostavljaj s SSH. Tailscale ali WireGuard
dasta isti dostop brez odprtih vrat. Desktop zna sejo pognati tudi prek SSH na
oddaljeni stroj, če boš kdaj delal s prenosnika.

**Ne dve seji na isti zahtevi.** Worktree ščiti datoteke, ne logike.

**Ko se plan in koda razideta.** Če je od plana minilo več dni in se je `main`
premaknil, plana ne popravljaj. Poglej `git log --oneline HEAD..main` in se
odloči med rebase obsega in novim ciklom od faze 1.

**Ne vzdržuj `docs\plan\` in `docs\verzije\` kot dokumentacijo.** To sta zapisa,
kaj je bilo takrat naročeno. Živa ostaneta `00-namen.md` in `01-arhitektura.md`.

**Prvi teden bodi počasen.** Preglej vsak diff v celoti, tudi ko je pregledovalec
zelen. Šele ko vidiš, kje ta postavitev pri tvojem projektu spusti, jo prilagodi.

**Za res majhne spremembe** (tipkarska napaka, sprememba besedila) tega procesa
ne uporabljaj. Naredi branch, popravi, verify, merge. Proces je za zahteve, ne
za vsak dotik.

---

## Povzetek

| Kdaj | Kdo | Kaj |
|---|---|---|
| B1 | seja 1 | vpraša, preveri, **naredi branch**, napiše in commita plan |
| B2 | **ti** | anotiraš plan v datoteki, rečeš "gremo" |
| B3 | seja 2, ista mapa | koda, testi, `@pregledovalec`, status, `verify.ps1` |
| B4 | **ti** | prebereš diff, preizkusiš |
| B5 | **ti** + seja 2 | odpreš gate zunaj repo, merge, zapreš gate, push |
