# ADR-067: Tudi naloga, daljša od strani, se v predogledu začne na novi strani

- **Datum:** 2026-10-14
- **Nastalo pri:** `V4-R09`, faza 5 (primerjava predogleda z natisnjenim PDF)
- **Status:** Sprejeto (2026-10-14)
- **Spreminja:** `docs/plan/V4-R09.md` v vrstici testnega primera „Prelom v
  predogledu … naloga, daljša od strani, brez njega" (plan ostane, kakršen je;
  velja ta zapis)
- **Stoji na:** `ADR-053` B (naloga se ob tisku ne razdeli), `ADR-066`

## Kontekst

Plan `V4-R09` je predvidel, da predogled pred nalogo, ki ne gre več na stran,
vstavi prazen prostor — **razen** pri nalogi, daljši od cele strani: ta naj bi
se začela tam, kjer je, in se razdelila, ker se ob tisku tudi razdeli.

Primerjava z natisnjenim PDF-jem (Chrome, `--print-to-pdf`, test z nalogo,
dolgo približno dve strani in pol) je pokazala, da tisk ravna drugače: tudi
dolgo nalogo z `break-inside: avoid` najprej prestavi na novo stran in jo
razdeli šele tam. Po planu bi se predogled in PDF od te naloge naprej
razhajala za eno stran, kar krši kriterij „predogled in natisnjen PDF se na
vsaki strani začneta z isto nalogo".

## Možnosti

1. **Po planu** — dolga naloga brez praznega prostora. Proti: predogled ne
   kaže tiska; razlika je znana omejitev, ki jo starš opazi šele na papirju.
2. **Kot tisk** (izbrano) — vsaka naloga, ki seže čez konec strani in se ne
   začne na vrhu strani, dobi prazen prostor, ne glede na dolžino. Znotraj
   naloge, daljše od strani, je črta tam, kjer se konča natisljiva višina.

## Odločitev

Možnost 2. V `izmeriList` (`_preizkus-izris.html`) odpade pogoj o dolžini
naloge. Tisk se ne spremeni.

## Posledice

- Pri nalogi, daljši od strani, ostane spodnji del prejšnje strani prazen — v
  predogledu in na papirju enako.
- Preverjeno samo s Chromom. Če drug brskalnik dolge naloge ne prestavi, se
  predogled pri njem razlikuje; to se pokaže v ročnem preizkusu (9b).
- Kje znotraj dolge naloge tisk dejansko prelomi (med vrsticami), predogled
  le približa s črto na natisljivi višini.
