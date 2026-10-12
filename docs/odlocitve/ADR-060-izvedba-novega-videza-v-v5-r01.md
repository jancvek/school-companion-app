# ADR-060: Izvedba novega videza v V5-R01 — slog v datoteki, prazni dnevi predmeta, števci menija

- **Datum:** 2026-10-12
- **Nastalo pri:** V5-R01 (fazi 1 in 2)
- **Status:** Sprejeto
- **Stoji na:** `ADR-056` (nov videz, obseg, meni, poti ostanejo), `POC-02`
  (*Ugotovitve*, posnetki), `ADR-028` E2 (manjki samo pri delno poslikanem
  dnevu), `ADR-039` B, F in F3 (izbira otroka, oznake, brez sklanjanja imen),
  `ADR-035` (`SejaMiddleware`), `ADR-044` B in `ADR-045` (lastnikove strani ne
  berejo vsebine družin), `ADR-017` A (brez tihega krajšanja)
- **Preglaša:** `ADR-024`, meja 1, v delu „slog živi vgrajen v predlogo" —
  razlog (ni streženja statičnih datotek) od V4-R07 ne velja. Za **skripto**
  meja 1 ostane, kakršna je.
- **Širi:** `ADR-056` I („poti ostanejo") za eno novo pot `GET`; glej G.
- **Zapre:** vse točke iz `ADR-056`, *Kar ta ADR še ne odloči*.

## Kontekst

`ADR-056` je odločil, kaj se spremeni, in šest stvari pustil fazi 1 zahteve.
Ob branju kode sta se pokazali še dve, ki ju POC ni mogel videti: statične
datoteke so pod `/admin/static`, torej za sejo, prijavna stran pa seje nima; in
posnetek 10 kaže prebrano sliko urnika, za katero ne obstaja nobena pot.

## Odločitve

### A — slog je ločena datoteka; slog in pisave so izvzeti iz seje kot točne poti

1. **Vgrajen slog, prijava z rezervno pisavo.** Za: brez posega v varnostno
   mejo. Proti: posnetka 24–25 se ne ujemata; besede iz sloga ostanejo v vsakem
   izrisu in podirajo teste, ki trdijo, da besede na strani ni
   (`docs/01-arhitektura.md`, „Slog v `osnova.html` je del vsake izrisane
   strani").
2. **Ločena datoteka, izvzeta kot točne poti.**
3. **Druga predpona zunaj `/admin`.** Proti: `ZetonMiddleware` bi dobil novo
   izvzeto predpono, kar je širša izjema kot pet točnih poti.

**Izbrano: 2.** Slog je `app/static/admin/slog.css`, pisave
`app/static/pisave/atkinson-hyperlegible-next/*.woff2`. V `izvzete_poti` plasti
`SejaMiddleware` pridejo **točne poti** teh datotek (ena datoteka sloga, štiri
pisave) — ne predpona in ne vzorec. Datoteke ne nosijo nobenega podatka
družine. Test dokazuje troje: vsaka izvzeta pot obstaja na disku, vsaka druga
datoteka pod `/admin/static` brez seje ostane `303`, in nabor izvzetih poti je
natanko zapisani (nova pot vanj ne zaide tiho — vzorec `poti_s_svojim_csrf`).

Slog za tisk kviza (`@media print`) se preseli skupaj z ostalim slogom,
**pravila ostanejo dobesedno ista** (`ADR-056` H). `_preizkus-slog.html`
ostane, kjer je (`ADR-054`).

### B — pisava: štiri statične datoteke iz uradnega repozitorija

Atkinson Hyperlegible Next, woff2, reže 400, 500, 700 in 800, iz repozitorija
`googlefonts/atkinson-hyperlegible-next` (Braille Institute), z `OFL.txt` v
isti mapi. Statične in ne variabilna datoteka: štiri reže so vse, kar
`POC-02` uporablja. Nadgradnja je ročna zamenjava mape, kot pri KaTeX
(`ADR-054`). V paket pridejo po obstoječem vzorcu `static/**/*`.

### C — prazni dnevi na strani predmeta

Stran predmeta **ni po otroku** (`ADR-039` F) in izbirnika ne dobi. Za dan
brez ene same nearhivirane slike tega predmeta velja, po vrsti:

1. **Prihodnji dan in današnji dan → „Še pride."** Današnji dan je ves dan
   „še pride"; rdeč postane šele naslednji dan. `/admin/days` se s tem **ne**
   spremeni (tam današnji manjki ostanejo, `docs/01-arhitektura.md`).
2. **Rdeče („Po urniku je bil predmet, slik ni")**, če velja za **vsaj enega
   otroka** oboje: predmet ima tisti dan na veljavnem urniku brez
   `skip_photo`, **in** je tisti dan poslikal vsaj en drug predmet
   (`ADR-028` E2 — dan brez ene same slike je praznik ali odsotnost, ne
   manjko). Pri več kot enem otroku stoji ime otroka kot vrednost pred
   besedilom (`Tim · po urniku …`), nikoli za predlogom (`ADR-039` F3).
3. **„Ni na urniku" (šrafirano)**, če predmeta tisti dan nima na urniku noben
   otrok ali ga imajo vsi s `skip_photo`.
4. **Sicer prazno, brez razloga**: predmet je na urniku, a otrok tisti dan ni
   poslikal ničesar (E2), ali pa družina nima otroka z veljavnim urnikom.

Sodi se po **trenutno veljavnem** urniku, kot povsod (`ADR-028` D2). Pravilo
živi v `app/urnik.py` kot čista funkcija; podatek o „poslikal kaj drugega"
je ena poizvedba čez obdobje strani (dan, otrok), ne ena na dan.

### D — vikend na strani predmeta

Teden ima pet stolpcev. **Sobota in nedelja dobita stolpec samo v tednu, ki
ima posnetek na ta dan.** Vikend dan praznega stanja nima (urnik pozna
ponedeljek do petka, `ADR-041` F).

### E — vsi tedni na eni strani; tedni brez slik se preskočijo

Gumba „Pokaži starejše tedne" **ni** — odstopanje od posnetka 03. Brez
skripte bi bil povezava, ki izbor izgubi, in „Izberi vse" bi dobil dva
pomena. Stran ostane en obrazec z leno naložitvijo slik, kot od V3-R11;
popravek, če bo kdaj potreben, je ostranjevanje (`ADR-017` A).

Teden brez ene same slike predmeta se **ne izriše**. Cena: teden, ko je bil
predmet na urniku in ni nastala nobena slika, na tej strani ni viden; ostane
viden na „Po dnevih".

„Izberi teden" in „Izberi dan" sta povezavi na isto stran s parametrom, po
vzorcu `?vse=1` (`ADR-048` G); prejšnjega ročnega izbora ne ohranita.

### F — števci v meniju

Na **vsaki** strani pod `/admin`, razen pod `/admin/system`: Predmeti (slike v
uporabi), Kvizi (**čakajoči** — nepreklicani in nerešeni), Testi (shranjeni
preizkusi), Arhiv (arhivirane slike). Štejejo se v obdelovalcu konteksta
(`app/strani.py`), največ štiri poizvedbe na izris. Števec z vrednostjo nič se
ne izriše.

Pod `/admin/system` števcev ni: te strani ne berejo vsebine nobene družine, in
to trdi test s prestrezanjem SQL (`ADR-044` B). Pravilo je vezano na pot, ne
na vlogo — lastnik sistema na svojih družinskih straneh števce vidi.

### G — slika urnika dobi pot

`GET /admin/schedule/image/{slika_id}`: postreže datoteko iz
`<images_dir>/<family_id>/urniki/<slika_id>.jpg`. Pot sestavi strežnik iz
kanoničnega UUID (`urnik._pot_slike`, `ADR-042`); družina je iz seje, zato je
tuja ali neobstoječa slika `404` z istim besedilom. Kartica „Prebrana slika"
jo pokaže pri neshranjenem predlogu (iz `slika_id`) in pri potrjenem urniku,
ki sliko ima (iz `schedules.image_path`).

To je edina nova pot poleg `GET /admin/quizzes`. `ADR-056` I ostane v
veljavi za vse ostalo.

### H — prej zeleni testi

Lastnik je v fazi 1 dal soglasje za dvoje (`CLAUDE.md`, faza 6):

1. `TestSeznamPredmetov::test_vrstni_red_predmetov_je_urnik_in_ne_abeceda`
   se omeji na polico predmetov.
2. Test, ki bere **zgradbo** izrisa (ime razreda, oznako, vrstni red besedila),
   se sme prilagoditi novi zgradbi, **če trditev o vedenju ostane**. Vsak tak
   test je naštet v poročilu. Test, pri katerem trditve ni mogoče ohraniti, je
   vprašanje za lastnika, ne popravek.

Nobeden se ne izbriše, ne izključi in ne označi za `skip`.

## Posledice

- **Olajša:** slog ni več del vsakega izrisa; prijava ima isti videz kot
  ostalo; stran predmeta in „Po dnevih" sodita manjke po istem E2.
- **Oteži:** `izvzete_poti` plasti seje ni več enočlanski — varuje ga test iz
  A. Prazni dnevi predmeta imajo štiri stanja in eno od njih („sicer prazno")
  ni narisano na posnetku 03. Današnji dan se na dveh straneh obravnava
  različno, zavestno.
- **Vpliva na:** `V3-R03` (izvzetje iz seje), `V3-R09` (nova pot za sliko
  urnika, pravilo praznih dni v `app/urnik.py`), `V3-R11` (izbor tedna in
  dneva), `V2-R01` (seznam kvizov na svoji strani); `docs/01-arhitektura.md`
  ob zaključku.

## Dopolnitve med izvedbo (12. 10. 2026)

### A1 — javne datoteke imajo svoj nabor, ne `izvzete_poti`

A pravi, da točne poti pridejo „v `izvzete_poti`". Izvedba jim da **svoje
polje** plasti (`javne_datoteke`, v `main.py` `JAVNE_DATOTEKE`), iz dveh
razlogov:

- `izvzete_poti` izvzame **vsako metodo** — namenjen je prijavi, kjer mora
  skozi tudi `POST`. Javna datoteka se samo bere, zato je izvzeta samo za
  `GET` in `HEAD`.
- `test_poti_brez_seje_ostane_samo_prijava` (V3-R08) trdi, da je prijava edina
  pot brez seje. Tako ostane **nespremenjen in zelen**; nov nabor ima svoj
  test. Vzorec je isti kot pri `poti_s_svojim_csrf` (`ADR-043`).

Odločitev iz A se s tem ne spremeni: pet točnih poti, nič drugega.

### B1 — tip vsebine pisave je vpisan izrecno

Python 3.12 pripone `.woff2` ne pozna in slika `python:3.12-slim` nima
`/etc/mime.types`, zato bi `StaticFiles` pisavo postregel kot `text/plain`.
`main.py` zato vpiše `font/woff2` sam; test ga preverja pri vsaki pisavi.
