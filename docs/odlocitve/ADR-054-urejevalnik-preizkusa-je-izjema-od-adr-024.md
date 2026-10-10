# ADR-054: Urejevalnik preizkusa je izjema od `ADR-024`; KaTeX in marked lokalno; klic modela v `vision.py`

- **Datum:** 2026-10-10
- **Nastalo pri:** V4-R07 (faza 1)
- **Status:** Sprejeto
- **Spreminja:** `ADR-024` — za eno predlogo (`preizkus.html`) namesto štirih
  mej veljajo meje spodaj; za vse ostale strani `ADR-024` velja naprej
- **Stoji na:** `ADR-053`, `ADR-035` D (CSRF v plasti seje), `ADR-026`
  (javni strežnik za Caddyjem), `ADR-008` (en modul za ponudnika modela)

## Kontekst

`ADR-024` dovoljuje skripto na `/admin` samo kot nadgradnjo, s štirimi
mejami: (1) brez gradnje frontenda, skripta vgrajena v predlogo; (2) brez
zunanje knjižnice, tudi prepisane v repozitorij; (3) stran mora delovati brez
skripte; (4) skripta ne piše in ne sestavlja poti — razlog je bil `ADR-006`
(stran brez gesla in seje).

Urejevalnik preizkusa (`ADR-053`) brez skripte ne obstaja: stanje dela
(koraki, razveljavi/uveljavi) živi samo v brskalniku, klepet kliče model, list
se izriše iz markdowna z LaTeX-om. To podre meje 2, 3 in 4.

Ob tem je bilo treba odločiti, kje živi klic modela: `vision.py` je po
`ADR-008` edini modul, ki uvaža `openai`.

## Možnosti

Za izris formul:

1. **KaTeX in marked s CDN-ja** (kot v POC-01) — Za: nič v repozitoriju.
   Proti: admin je odvisen od tujega strežnika in vsako odprtje strani mu
   pove, da je stran odprta.
2. **KaTeX in marked, prepisana v repozitorij in postrežena z našega
   strežnika** — Za: preizkušeno v POC-01, enak izris na zaslonu in papirju,
   brez tujih klicev. Proti: ~350 KB tujih datotek v repozitoriju; prva
   statična pot.
3. **Izris na strežniku v MathML** (`markdown-it-py`, `latex2mathml`) — Za:
   brez knjižnice v brskalniku. Proti: formule opazno slabše od POC-a; dve
   novi Python odvisnosti; izris po vsakem odgovoru gre skozi strežnik.

Za klic modela:

1. **Nov modul s svojim uvozom `openai`** — Proti: krši `ADR-008`.
2. **Nov klicalec v `vision.py`**, po vzoru `naredi_klicalca_urnika`
   (V3-R09) — Za: en modul za ponudnika ostane en modul. Proti: ime modula ne
   pove več vsega.

## Odločitev

**Izris: možnost 2. Klic modela: možnost 2.** Lastnik je potrdil obe in
novo zunanjo odvisnost (trdi rob 5).

Za predlogo `preizkus.html` namesto štirih mej `ADR-024` velja:

1. **Brez gradnje frontenda — ostane.** Ni `npm`, `package.json`, bundlerja.
   Lastna skripta je vgrajena v predlogo.
2. **Zunanji knjižnici sta natanko dve**, z zaklenjeno različico v imenu
   mape: `marked` 15.0.12 in `katex` 0.16.22 (z `contrib/auto-render`).
   Prepisani sta v `apps/server/app/static/vendor/` skupaj z licenco, samo
   pomanjšane datoteke in pisave `woff2`. Postreženi sta pod `/admin/static`
   — za sejo, kot vse pod `/admin`. **Nobene povezave na CDN** v nobeni
   predlogi; to preverja test.
3. **Stran brez skripte ne deluje — sprejeto.** Brez skripte pokaže
   `<noscript>` sporočilo v slovenščini. Stran, s katere se v urejevalnik
   pride (stran predmeta), ostane brez skripte.
4. **Skripta kliče strežnik** s `fetch`, telo je obrazec
   (`application/x-www-form-urlencoded`) s CSRF žetonom v polju `csrf`, zato
   plast seje in CSRF (`ADR-035` D) ostane nespremenjena. Razlog za staro
   mejo (`ADR-006`, stran brez seje) od `V3-R03` ne velja. Odgovor je JSON;
   odgovor, ki ni JSON (potekla seja, prevelik obrazec), skripta prikaže kot
   „Seja je potekla ali je stran zastarela".

Klic modela je `naredi_klicalca_preizkusa` v `vision.py`, s svojim ključem in
modelom iz nastavitev (`OPENAI_API_KEY_PREIZKUSI`, `OPENAI_MODEL_PREIZKUSI`,
privzeto `gpt-5.6-luna`). Navodilo, sestavljanje vhoda in razčlenitev
odgovora so v novem modulu brez `openai`, enako kot je urnik razdeljen med
`urnik.py` in `vision.py`.

## Posledice

- **Olajša:** `V4-R08` in vsak nadaljnji predmet uporabi isto stran in isti
  mehanizem.
- **Oteži:** dokaz obnašanja strani je ročni (faza 9b); pytest skripte ne
  izvede (enako kot `ADR-024`). Nadgradnja KaTeX/marked je ročna zamenjava
  mape in sprememba tega ADR-ja.
- **Vpliva na:** `TestBrezJavaScripta` (izvzeta še `preizkus.html`),
  `pyproject.toml` (podatkovne datoteke paketa), `docs/01-arhitektura.md`
  (razdelek o skripti na adminu), `okolje.primer`.
