# ADR-048: Prepisi izbranih slik — izbor s kljukicami, stran z besedilom, kopiranje kot nadgradnja

- **Datum:** 2026-09-21
- **Nastalo pri:** V3-R11 (debata z lastnikom, pred fazo 1)
- **Status:** Sprejeto; odločitev **D** v delu „pod glavo je prepis" in
  odločitev **E** v delu „samo glava, kadar ni prepisa" sta razširjeni z
  `ADR-049`: pod glavo so povzetek, prepis in vprašanja, vsak s podnaslovom.
  Ostale odločitve veljajo naprej.
- **Stoji na:** `ADR-024` (JavaScript samo kot nadgradnja, štiri meje),
  `ADR-016` A in G (izbirnik s kljukicami), `ADR-025` (družina je lastnik
  podatkov), `ADR-026` (HTTPS prek Caddyja), `ADR-035` D (CSRF žeton)
- **Razveljavlja:** nič. Razširi izjemo iz `ADR-024` na drugo predlogo.

## Kontekst

Lastnik prepise snovi lepi v ChatGPT, da iz njih sam sestavi vaje. Danes to
pomeni odpreti vsako snov posebej in iz nje kopirati prepis. Želi na strani
predmeta označiti poljubno število slik in z enim dejanjem dobiti vse
njihove prepise v odložišču.

Ob tem so se pokazala štiri vprašanja, ki bi jih izvedba sicer rešila po
tihem:

1. Je odložišče dovolj veliko?
2. Kopiranje v odložišče brez skripte ne gre, admin stran pa je brez skripte
   privzeto (`ADR-024`).
3. Izbor potuje od strani do strežnika — kako, če je izbranih nekaj sto slik?
4. Kaj z izbrano sliko, ki prepisa nima?

## Odločitve

### A — Velikost odložišča ni omejitev; omejitev je cilj lepljenja

Prepis ene strani je nekaj KB; tudi sto slik je pod pol MB. Brskalnik in
operacijski sistem v odložišču brez težav držita več MB besedila. Kar
količino res omeji, je sporočilo v ChatGPT, in ta meja se spreminja brez
nas. Zato strežnik ničesar ne reže in ne opozarja na prag, ampak pokaže
**število slik in znakov** nad besedilom. Lastnik sam presodi, ali bo
lepil v enem ali več kosih.

- Proti: brez zapisane meje lahko lastnik prilepi preveč in to izve šele v
  ChatGPT. Sprejeto — prag, ki ga ne nadziramo, bi bil v kodi napačen, še
  preden bi bil commitan.

### B — Izbor gre z `POST`, ne z `GET`

Predmet bo čez šolsko leto nosil nekaj sto slik (`ADR-017` A). Ponovljen
parameter z UUID je okoli 40 znakov na sliko; tristo slik je ~12 KB naslova,
kar je na meji tistega, kar sprejmeta Caddy in uvicorn. `GET` bi odpovedal
prav pri največjem izboru, in to z napako, ki jo lastnik vidi kot „stran ne
dela".

Zato je izbor obrazec `POST` s CSRF žetonom (`ADR-035` D), po vzorcu predogleda
kviza (`ADR-016` C). Pot je svoja, `POST /admin/transcripts`, predmet gre v
skritem polju. Pot pod `/admin/subjects/{koda:path}` ni izbrana, ker bi
pretvornik `:path` požrl tudi pripono in bi razločevanje slonelo na metodi.

- Proti: stran s prepisi ni zaznamek in je ni mogoče osvežiti brez ponovnega
  pošiljanja obrazca. Sprejeto — stran je trenutni izpis, ne stanje.

### C — Rezultat je stran z besedilom; kopiranje je nadgradnja

Stran „Prepisi izbranih" pokaže vse prepise v enem polju `<textarea readonly>`.
Ctrl+A, Ctrl+C dela vedno, tudi brez skripte in brez HTTPS. To je meja 3 iz
`ADR-024`: stran mora delovati brez skripte.

Gumb „Kopiraj v odložišče" je vgrajena skripta — **druga izjema** za
`snov.html`. Veljajo vse štiri meje `ADR-024`, in še tri, ki so posebej za
to stran:

1. Skripta prebere samo vsebino polja na strani in jo preda
   `navigator.clipboard.writeText`. Besedila ne sestavlja, ne krajša in ne
   preoblikuje — kar je v odložišču, je natanko to, kar je v polju.
2. Skripta ne kliče strežnika (`fetch`, `XMLHttpRequest`, `sendBeacon`) in ne
   pošilja obrazcev.
3. Ob neuspehu (stran ni v varnem kontekstu, brskalnik dostop zavrne)
   skripta besedilo v polju označi in pove „Kopiraj s Ctrl+C". Tiho
   neuspešen gumb je huje kot gumba nič.

`navigator.clipboard` dela samo v varnem kontekstu. Prek Caddyja (`ADR-026`)
je stran na HTTPS in to drži; ob dostopu prek golega `http://` z lokalnega
naslova gumb pade v tretjo mejo, polje pa dela naprej.

`TestBrezJavaScripta` izvzame novo predlogo, nič drugega. Enako kot pri
`V2-R08` pytest skripte ne izvede: dokazljivo je samo, kaj je v izrisu.
Obnašanje gumba dokaže ročni preizkus v fazi 9b.

### D — Oblika besedila: glava na sliko, najstarejša prva

Vsaka izbrana slika prispeva glavo v markdownu, pod njo prepis:

```
## MAT — 12. september 2026, 10:32 · Ana

<prepis>
```

Ime otroka je v glavi samo, če ga snov ima (`V3-R07`). Slike so urejene od
**najstarejše** naprej po `taken_at`, čeprav stran predmeta kaže najnovejše
prve: besedilo se bere kot snov v zaporedju, kot je nastajala.

Markdown in ne golo besedilo, ker ChatGPT glave razume kot mejo med kosi
snovi, v navadnem urejevalniku pa ostanejo berljive.

### E — Slika brez prepisa: navadna kljukica, v besedilu samo glava

Lastnik je izrecno izbral: slika, ki prepisa nima (še v obdelavi, neuspela,
neberljiva), ima **navadno kljukico** in ni posebej označena. V besedilu
prispeva samo glavo, pod njo ni ničesar.

To je zavestno drugače kot `ADR-016` G, kjer neizbirna snov ostane brez
kljukice in z razlogom. Tam bi manjkajoča snov tiho skrčila kviz; tu glava
ostane v besedilu in sled, da je bila snov tisti dan, ni izgubljena.

### F — Izbor ne pozna tujih ID-jev; ničesar se ne shrani

Šteje samo ID, ki je v naboru strani predmeta (`_nabor_predmeta`: ta
družina, ta predmet, brez arhiva). ID druge družine, drugega predmeta,
arhivirane ali neobstoječe snovi se **tiho izpusti** — tak ID ne more nastati
iz izrisanega obrazca, zato ni napaka uporabnika, ki bi jo bilo treba
razložiti, in z odgovorom ne sme razkriti, da tuja snov obstaja.

Nič se ne zapiše v bazo. Sestavljanje je čista funkcija na strežniku (izbor
snovi → besedilo), ločena od predloge, da jo lahko pozneje uporabi tudi
generator delovnih listov (`V4-R04`). To je možnost, ne obljuba.

### G — „Izberi vse" brez skripte

Povezava `?vse=1` na strani predmeta jo izriše z vsemi kljukicami. Brez
skripte in brez nove izjeme; privzeto je obkljukano nič.

## Posledice

- **Kaj to olajša:** pripravo vaj iz snovi, dokler V4 ne pripelje
  generatorja; in pozneje `V4-R04`, ki dobi sestavljanje prepisov že
  napisano in preizkušeno.
- **Kaj to oteži:** izjema od „brez skripte" ni več ena. Pregledovalec mora
  meje `ADR-024` in tri meje iz C preverjati izrecno pri obeh predlogah.
- **Na katere zahteve to odslej vpliva:** `V3-R11` (stoji na tem ADR);
  `docs/01-arhitektura.md` ob zaključku `V3-R11` na mestih, ki trdijo, da ima
  skripto samo `snov.html`.
