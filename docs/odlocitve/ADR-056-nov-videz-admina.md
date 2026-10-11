# ADR-056: Nov videz admina iz POC-02; V5 je verzija novega videza

- **Datum:** 2026-10-11
- **Nastalo pri:** POC-02 (sodba `Sprejeto`), pred V5-R01
- **Status:** Sprejeto
- **Stoji na:** `docs/poc/POC-02.md` (*Dogovorjeno*, *Ugotovitve*) in
  posnetkih v `docs/poc/POC-02/`; `ADR-024` (skripta je nadgradnja, ne
  pogoj), `ADR-054` in `ADR-055` (izjemi za urejevalnik in ogled preizkusa),
  `ADR-028` E2 (manjki samo pri delno poslikanem dnevu), `ADR-039`
  (naslovljenec, izbira otroka, brez sklanjanja imen)
- **Spreminja:** videz vseh strani pod `/admin` (28 predlog po V4-R08)

## Kontekst

Admin je zrasel stran za stranjo od V1 naprej. Vse strani si delijo eno
ogrodje (`osnova.html`) z vgrajenim slogom, navigacija pa je razdelek na dnu
`/admin` („Pregled po dnevih", „Urnik", „Družina", „Testi" …). Lastnik je
želel sodobnejši in preglednejši videz.

V POC-02 je v dveh krogih nastalo trinajst statičnih predlogov z izmišljenimi
podatki — Predmeti, stran predmeta, slika, Urnik, Družina (krog 1) in Po
dnevih, Kvizi, izbor snovi, predogled, kviz, obe strani Statistike, prijava
(krog 2). Lastnik je oba kroga sprejel brez pripomb in odločil, da nobena
stran ne ostane v starem slogu.

## Možnosti

1. **Prenova stran za stranjo, vsaka svoja zahteva** — Za: majhni koraki.
   Proti: dolgo obdobje, ko ima admin dva sloga; ogrodje (meni) spremeni vse
   strani že v prvem koraku.
2. **Ena zahteva za ogrodje in vse strani** — Za: en sam prehod, nikoli
   mešanega videza. Proti: velika zahteva; plan jo mora razdeliti na
   zaporedne korake.
3. **Samo žetoni in pisava, postavitve ostanejo** — Za: majhno. Proti: ne
   odgovori na vprašanje POC-a (preglednost je v postavitvi, ne v barvah).

## Odločitev

**Možnost 2**, kot ena zahteva `V5-R01` v novi verziji V5 (V4 je verzija
preizkusov in je zaključena).

**A. Vizualni jezik** je tisti iz `POC-02` *Ugotovitve*: barvni žetoni za
svetlo in temno temo, barve predmetov, tipografija in mere, ogrodje z
menijem, gradniki (zvezek, čip, oznaka, gumbi, obvestilo) in opis vsake
strani. Posnetki v `docs/poc/POC-02/` so del dogovora. HTML predlogov
implementacija ne bere (`ADR-052`, točka 5).

**B. Obseg so vse strani admina.** Strani iz obeh krogov se ujemajo s
posnetki; ostale dobijo nov videz po tabeli *Strani po pravilih* v
`POC-02`.

**C. Pisava Atkinson Hyperlegible Next**, datoteke woff2 v repozitoriju,
postrežene z lastnega strežnika (licenca OFL). Nova zunanja odvisnost, ki jo
je lastnik odobril (trdi rob 5). Rezerva je `system-ui`.

**D. Tema sledi sistemu** (`prefers-color-scheme`); preklopa v vmesniku ni.

**E. Barve predmetov pripadajo predmetu** in živijo ob kodi in imenu v
`subjects.py`, ne v predlogi.

**F. Nov videz ne doda skripte.** Vrstica izbora, štetje izbranih, barve
celic urnika in prazni zvezki so CSS (`:has()`, števci, `<details>`).
Obstoječe skripte (povečava V2-R08, urejevalnik `ADR-054`, ogled `ADR-055`)
ostanejo v svojih mejah. Ob brskalniku brez `:has()` se izgubi samo barva,
vedenje ne.

**G. Meni nadomesti razdelke na `/admin`.** Postavke: Predmeti, Po dnevih,
Kvizi, Testi, Urnik, Statistika | Družina, Arhiv, Sistem (samo lastnik
sistema). Postavka Kvizi vodi na **novo stran** `/admin/quizzes` z vsemi
kvizi; Predmeti pokažejo zadnje štiri in „Vsi kvizi".

**H. Tisk ostane, kakršen je**: `kviz-tisk.html` in list A4 urejevalnika in
ogleda preizkusa. Nov videz velja za zaslon.

**I. Poti, metode in obrazci ostanejo**: vsak `GET`/`POST`, CSRF žeton,
ime polja in vrednost ostanejo, kot so. Novo je samo, kar je v `POC-02`
zapisano kot novo vedenje (stran Kvizi, filtri, delitev po tednih …).

## Kar ta ADR še ne odloči (faza 1 zahteve)

- **Slog v ločeni datoteki** pod `/admin/static/` ali še naprej vgrajen v
  `osnova.html`. Razlog za vgrajenega (ni bilo streženja statičnih datotek)
  od V4-R07 ne velja več.
- **Čigav urnik** velja za manjke na strani predmeta, ko ima družina več
  otrok z različnim urnikom (stran predmeta ni po otroku, `ADR-039`).
- **Sobotni posnetki** na strani predmeta (stolpcev je pet).
- **Deljenje po tednih** („Pokaži starejše tedne") ali vse na eni strani.
- **Test vrstnega reda predmetov** na `/admin` išče prvo pojavitev kode na
  strani; nova stran ima kode prej. Sprememba prej zelenega testa potrebuje
  lastnikovo soglasje (`CLAUDE.md`, faza 6).
- Podatki, ki jih strežnik predlogam danes ne da: razlike pri urniku s slike,
  oznaka „Google" pri staršu, položaj slike v predmetu („3 od 24").

## Posledice

- **Olajša:** en slog in ena navigacija za vse strani; nova stran dobi videz
  iz gradnikov, ne iz okusa.
- **Oteži:** velika zahteva, ki se dotakne vseh predlog in več testov, ki
  berejo HTML; plan jo mora razrezati na zaporedne commite.
- **Ne spremeni:** aplikacije na telefonu, podatkovnega modela (razen če
  faza 1 odloči drugače za katerega od odprtih podatkov), tiska.
- **Vpliva na:** `docs/verzije/v5.md` (nova), `docs/01-arhitektura.md`
  (ogrodje, pisava, slog) ob zaključku `V5-R01`.
