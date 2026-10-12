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

### F1 — števci so en stavek; dva testa štetja poizvedb dobita novo številko

Štiri štetja menija so en sam stavek s štirimi podizrazi (`MeniRepository`),
vsak s pogojem družine: vsaka stran plača eno poizvedbo in ne štirih.

Dva prej zelena testa štejeta poizvedbe strani z natančno številko in ju H ne
pokriva (nista testa zgradbe). Lastnik je 12. 10. 2026 odobril dvig:
`test_izbirnik_je_stiri_poizvedbe_ne_glede_na_stevilo_snovi` s 4 na 5 in
`test_rezultat_je_sest_poizvedb` s 6 na 7. Lastnost, ki jo varujeta — stalno
število ne glede na dolžino seznama — ostane; imeni testov ostaneta, ker ju
navajajo starejši zapisi.

### C1 — vrstni red pravil praznega dne: urnik pred koledarjem

C našteje „današnji in prihodnji dan → še pride" kot **prvo** pravilo.
Izvedba ga da na **tretje** mesto, za „nihče nima urnika" in „predmeta ta dan
ni na urniku": prihodnja sreda, ko matematike ni na urniku, je „Ni na urniku"
in ne „Še pride", družina brez urnika pa na prihodnjih dneh ne dobi nobenega
razloga. „Še pride" bi v obeh primerih obljubil sliko, ki je urnik ne
predvideva. Za dan, ko predmet **je** na urniku, velja C nespremenjeno —
tudi današnji dan je ves dan „še pride".

To je odstopanje od vrstnega reda, zapisanega v C. **Lastnik ga je
12. 10. 2026 potrdil:** velja red iz tega razdelka.

### E1 — en gumb v vrstici izbora namesto dveh

`V3-R11` je „Prepisi izbranih" (in `V4-R07` „Kreiraj test") postavil nad
seznam **in** pod njega, da po izboru na vrhu ni treba drseti čez cel predmet.
`POC-02` (posnetek 03) ima namesto tega **vrstico izbora**, prilepljeno na dno
zaslona. Gumb je zato eden; namen kriterija — dosegljiv brez drsenja — ostane.
Brskalnik brez `:has()` vrstico kaže ves čas, prav tako prilepljeno.

Števec v vrstici se glasi „Izbrano: 3" in ne „3 izbranih" kot na posnetku:
število izpiše CSS števec, ki besede ne zna sklanjati, oblika z dvopičjem pa
je pravilna pri vsakem številu (`docs/01-arhitektura.md`, „Slovenske oblike
števil").

Besedilo rdečega dne je „Po urniku je bil ta predmet, slik ni." in ne „…je
bila matematika…": glagol se mora ujemati s spolom imena predmeta, ki ga ta
projekt ne sklanja.

### H1 — štirje prej zeleni testi zunaj soglasja H

Pregled je našel štiri prej zelene teste, pri katerih se je spremenila
**trditev** in ne samo zgradba, zato jih H ne pokriva. Lastnik jih je
12. 10. 2026 izrecno potrdil:

| Test | Prej | Zdaj | Zakaj |
|---|---|---|---|
| `test_gumb_stoji_nad_seznamom_in_pod_njim` (V3-R11; preimenovan) | „Prepisi izbranih" dvakrat | enkrat, v prilepljeni vrstici izbora | E1 |
| `TestGumbNaStraniPredmeta` (V4-R07) | „Kreiraj test" dvakrat | enkrat, v isti vrstici | E1 |
| `test_najnovejsa_slika_je_prva` | sliki v istem tednu | sliki v različnih tednih | stran je razvrščena po tednih (E) |
| `TestPovecava`, trditev o vrstnem redu na strani predmeta | ob enakem času je novejši `id` prvi | ob enakem času je starejši `id` prvi | znotraj dneva tečejo slike od najstarejše naprej (E); listanje ostane v svoji smeri in nobene slike ne preskoči |

S tem je kriterij `V3-R11` „gumb nad seznamom in pod njim" razveljavljen v
delu o **dveh** gumbih; njegov namen (dosegljiv brez drsenja) nosi vrstica
izbora.

### I1 — povečava ostane skripta V2-R08, brez `:target`

`POC-02` omenja povečavo s CSS `:target` na sidru `#povecano`; faza 1 je to
predvidela kot pot brez skripte. Izvedba je **ne** doda: skripta ob zaprtju
sidro odstrani s `history.replaceState`, to pa stanja `:target` v brskalnikih
ne posodobi — prikaz bi po zaprtju ostal odprt. Pot brez skripte ostane tista
iz `ADR-024` (meja 3): povezava odpre izvirnik.

Posnetek 04 ima pod sliko gumb „Povečaj". Ta je druga povezava
`a[data-povecava]` na isti izvirnik, zato skripta klik prestreže na **vseh**
takih povezavah (`querySelectorAll` namesto `querySelector`) in si zapomni,
katera je prikaz odprla, da se fokus ob zaprtju vrne nanjo. To sta edini
spremembi skripte; njene meje ostanejo.

### J1 — slog ima dva dela: zaslon in papir (po pregledu)

Prvi pregled je pokazal, da „pravila za tisk so nespremenjena" ni isto kot
„papir je nespremenjen": nova osnovna pravila (naslovi, povezave, prelom
besed, pisava) so veljala tudi na papirju in na listu A4 preizkusa, ki je
papir že na zaslonu.

`slog.css` ima zato dva dela in nič tretjega razen `@font-face`:

- **`@media screen`** — vsa pravila novega videza. Temna tema je znotraj
  njega, zato papir ostane svetel brez posebnega pogoja.
- **`@media print`** — **dobesedno** slog, ki ga je `osnova.html` nosila pred
  V5-R01, s svojim blokom za tisk na koncu. Varuje ga zamrznjena kopija
  `apps/server/tests/podatki/slog_pred_v5_r01.css`: kdor spremeni papir,
  mora spremeniti tudi njo, in to se vidi v pregledu.

List A4 (`.list`) je na zaslonu, zato ga varuje peščica pravil v delu za
zaslon, ki splošna pravila novega videza na njem razveljavijo (višina vrstice
in velikost naslovov, barva povezav, prelom besed). Po višini lista merilnik
računa strani (`ADR-054`).

Posledica: predloga, ki bi na papirju potrebovala **nov** razred, ga v delu
za papir nima. Tisk kviza in list preizkusa uporabljata samo razrede izpred
V5-R01.

Pravilo urejevalnika za odstavek z napako je zoženo na `p.napaka`, da ne
zadene oznake in značke z razredom `napaka`. Postavitev prijavne strani nosi
razred telesa `prijavna` in ne `:has()`.

## Odstopanja od posnetkov in zapisa POC-02 (12. 10. 2026)

Posnetki v `docs/poc/POC-02/` so del dogovora (`ADR-056` A), a so risani z
izmišljenimi podatki in brez pravil, ki jih ta projekt že ima. Kjer sta si
posnetek in starejše pravilo nasprotovala, je obveljalo pravilo; vsako
odstopanje je tu, da ga lastnik ob sprejemu potrdi ali zavrne.

| Kje | Posnetek / zapis | Izvedba | Zakaj |
|---|---|---|---|
| Predmet, rdeč dan | „Po urniku je bila matematika, slik ni." | „Po urniku je bil ta predmet, slik ni." | Glagol bi se moral ujemati s spolom imena predmeta. |
| Predmet in izbor snovi, vrstica izbora | „3 izbranih" | „Izbrano: 3" | Število izpiše CSS števec, ki ne sklanja (E1). |
| Predmet | „Pokaži starejše tedne" | gumba ni | `ADR-060` E. |
| Predmet, prazen dan | tri stanja | štiri: še „brez razloga" | `ADR-060` C. |
| Slika, pod naslovom | „Matematika, posnel Jaka" | „MAT — Matematika · Jaka" | Glagol s spolom; ime je vrednost za ločilom (`ADR-039` F3). |
| Slika, upokojena vprašanja | „2 vprašanji … sta upokojeni" | „Upokojena vprašanja: 2" | Oblika z dvopičjem je pravilna pri vsakem številu. |
| Slika, povečava | CSS `:target` | skripta V2-R08 | I1. |
| Družina, oznake | „aktiven", „deaktiviran" | „aktiven račun", „deaktiviran račun" | Samostalniška oblika ne določa spola osebe (V3-R06). |
| Družina, podnaslov | „2 otroka in 3 starši, od tega 1 deaktiviran." | „Skupaj 5 članov." | Trije sklanjani števniki in pridevnik s spolom. |
| Potrditev deaktivacije | „Deaktivirati Timov račun?" | ime nad vprašanjem „Deaktivirati račun?" | Svojilni pridevnik iz poljubnega imena (`ADR-039` F3). |
| Urnik brez urnika | „Jaka še nima urnika." | „Urnika še ni." | Brez imena v povedi; čigav je, pove zavihek. |
| Izbor snovi, naslov | „Nov kviz iz matematike" | obstoječi naslovi vstopov („Nova snov" …) | Rodilnik imena predmeta. |
| Izbor snovi, že uporabljena | „že v kvizu »Naravna števila«" | „že v kvizu" | Imena kviza izbirnik ne bere; nova poizvedba ni bila dogovorjena. |
| Predogled, gumb | „Objavi kviz", „Sestavi kviz" | „Objavi", „Sestavi" | Gumbi so glagoli (`ADR-039`, popravki po drugem pregledu). |
| Kviz, podnaslov | čip in ločena polja | „Maša · MAT · 3 vprašanja · objavljen …" | Vrstica `<p class="pod">` je mesto, kjer `TestImenaPriEnemOtroku` preverja ime. |
| Prepisi | „gumba Kopiraj ni" | gumb in skripta V3-R11 ostaneta | Gumb obstaja od V3-R11 (`ADR-048` C); odstranitev bi bila izguba vedenja, ne videz. |

### Novi parametri obstoječih poti

`ADR-056` I pravi, da poti ostanejo. Poleg dveh novih poti (`GET
/admin/quizzes`, `GET /admin/schedule/image/{slika_id}`) so štiri obstoječe
`GET` poti dobile **neobvezen** parameter, vse po vzorcu `?vse=1` (`ADR-048`
G) — povezava na isto stran namesto skripte:

- `/admin/subjects/{koda}`: `?teden=<ponedeljek>`, `?dan=<dan>` (izbor);
- `/admin/quizzes/new`: `?izbor=vse|nic`;
- `/admin/family`: `?dodaj=otrok|stars` (odprt obrazec).

Vrednost, ki je stran sama ne izriše, se prezre.
