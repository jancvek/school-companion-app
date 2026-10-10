# ADR-052: POC pot — idejo preveriš, preden se zaveže zahteva

- **Datum:** 2026-10-10
- **Nastalo pri:** pogovor o procesu (zunaj zahteve)
- **Status:** Sprejeto (2026-10-10)
- **Spreminja:** `CLAUDE.md` (§0, nova faza 0, nov §1d, trdi rob 7), nova
  `docs/poc/PREDLOGA.md`; predlaga spremembe `.claude/commands/zahteva.md` in
  `.claude/hooks/git-guard.ps1` (glej Dodatek — teh datotek model ne spreminja)

## Kontekst

Proces iz `CLAUDE.md` (ADR-022) dobro deluje, ko lastnik točno ve, kaj hoče:
faza 1 razčisti vprašanja, nato gre zahteva skozi plan, teste, pregled in
verify. Ne pokrije pa primera, ko je ideja še odprta: lastnik bi rad hitro
videl nekaj delujočega, se ob tem zmenil za podrobnosti in šele potem rekel
»to je to«.

Če se tak poskus pelje kot zahteva, se na nedokončani ideji plača celoten
proces (plan, testi, pregledovalec). Če se pelje mimo procesa, nastane koda
brez testov in pregleda, ki zlahka zdrsne v `main` — znana past »prototip
konča v produkciji«.

Uveljavljena praksa loči dve stezi (dual-track agile): *discovery* preverja,
ali je stvar vredna gradnje, *delivery* jo zgradi pravilno. Obstoječi proces je
čisti delivery.

## Možnosti

1. **Brez spremembe** — POC se dela priložnostno. Za: nič novega. Proti:
   dogovori ostanejo v pogovoru, koda brez pregleda išče pot v `main`.
2. **POC kot zahteva po kratki poti** — Za: obstoječa pravila. Proti: kratka
   pot zahteva teste, pregled in merge; POC bi se plačal kot produkcija in
   končal v `main`.
3. **POC se razvije v produkcijo (»tracer bullet«)** — Za: nič se ne zavrže.
   Proti: koda mora biti od začetka produkcijska, kar POC upočasni; meja med
   poskusom in izdelkom zbledi.
4. **Ločena POC pot, koda se zavrže, ohrani se zapis** — Za: POC je hiter,
   dogovori so zapisani, `main` ostane zaščiten. Proti: implementacija se
   napiše znova.

## Odločitev

Možnost 4.

1. **Faza 0.** Na začetku vsakega novega dela — tudi pri `/zahteva` z
   obstoječim ID-jem — model vpraša: *POC ali dokončna zahteva?* in konča
   obrat. Brez izjem; odpade le pri nadaljevanju dela na že obstoječi veji.
2. **POC odgovori na eno vprašanje** in ima eno od dveh oblik: idejni/UX
   (po možnosti več različic drugo ob drugi) ali tehnični (spike).
3. **Edini trajni izdelek je `docs/poc/POC-xx.md`**: vprašanje, krogi,
   *Dogovorjeno*, *Ugotovitve*, sodba. Dogovori se zapisujejo sproti.
4. **Veja `poc/…` se nikoli ne merga.** Zapis pride v `main` prek ločene veje
   `docs/poc-xx-…` — tudi pri sodbi `Zavrženo`, da se isto vprašanje ne
   preverja dvakrat.
5. **Koda POC-a se ne prenaša**, tudi ne po delih, in ni vhod za nobeno fazo
   zahteve. Brez izjem.
6. **Sproščeno:** plan, testi, pregledovalec, verify, merilo dokončanosti,
   statusi. **Ostane:** trdi robovi; nič proti javnemu strežniku ali pravim
   podatkom družin; brez migracij nad obstoječimi podatki.
7. **Časovni okvir:** en krog = ena seja, največ trije krogi, nato sodba
   `Sprejeto` ali `Zavrženo`. Kar ostane odprto, je nov POC z ožjim
   vprašanjem. Opuščen POC se zapre kot `Zavrženo` (»opuščeno«).
8. **Na telefonu zadošča razvojna gradnja.** ADR-010 lovi napake ob gradnji,
   ki pri POC-u niso vprašanje; APK iz veje je pogoj pri zahtevi (faza 9b).
9. Pri sodbi `Sprejeto` nastaneta ADR z odločitvijo in nova zahteva `VN-Rxx`
   (status `Nova`, **Podlaga:** ta ADR in `POC-xx`), katere kriteriji
   sprejemljivosti izhajajo iz *Dogovorjeno*. Implementacija gre po polni poti.

## Posledice

- **Olajša:** ideja se preveri v eni seji brez procesnega bremena; detajli,
  dogovorjeni ob delujočem POC-u, postanejo kriteriji in faza 1 zahteve je
  kratka.
- **Oteži:** implementacija se napiše znova. Pri delu z modelom je to poceni —
  drag je dogovor, kaj naj koda počne, in ta se ohrani.
- **Tveganje:** *Ugotovitve* so edini most iz kode v zahtevo. Kar ni zapisano,
  se izgubi — zato se POC ne zapre, dokler razdelek ni izpolnjen.
- **Ne spremeni:** poti zahteve od faze 1 naprej.

## Dodatek — predlagane spremembe v `.claude/` (spremeni lastnik)

### `.claude/commands/zahteva.md`

Pred točko 1 dodaj:

> 0. Če za $1 še ni veje, me najprej vprašaj, ali gre za POC ali za
>    dokončno zahtevo (`CLAUDE.md`, faza 0), in končaj obrat. Pri POC-u
>    sledi §1d. Če veja že obstaja, je to nadaljevanje in vprašanje odpade.

(Še vedno odprta je tudi sprememba točke 1 iz Dodatka ADR-022.)

### `.claude/hooks/git-guard.ps1`

Pred razdelek `# 4. Merge / push / tag` dodaj — blokira tudi, ko je gate
odprt:

```powershell
# ============================================================
# 3b. POC veje se ne mergajo (ADR-052)
# ============================================================
# Ujame tudi `git -c … merge` in `git -C … merge`, ne ujame pa bralnih
# `git merge-base`, `git log main..poc/…` in sporočila `-m "… docs/poc/…"`.
$pocMerge = '(?i)\bgit\b(?:\s+-[cC]\s+\S+)*\s+(?:merge(?!-)|cherry-pick|pull)\b[^;&|]*?\s(?:origin/|remotes/origin/|refs/heads/)?poc/'
if ($n -match $pocMerge) {
    Deny 'veja poc/... se ne merga. Iz POC-a gre v main samo docs/poc/POC-xx.md (CLAUDE.md §1d).'
}
```

Preizkušeno na 13 primerih (Python `re`, enak vzorec). Ne ujame
`git cherry-pick <sha>` — ograja ustavi nesrečo, ne odločenega obhoda.
Veja `docs/poc-xx-…` (z vezajem) se s tem ne ujame in gre skozi običajni gate.
