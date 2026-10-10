# ADR-024: JavaScript je na `/admin` dovoljen, a samo kot nadgradnja

- **Datum:** 2026-09-12
- **Nastalo pri:** V2-R08 (faza 1 — razumevanje)
- **Status:** Sprejeto
- **Preglasi:** odločitev 1 v `docs/plan/V1-R04.md` v delu „brez
  JavaScripta"; kriterij V1-R04 v `docs/verzije/v1.md` („Stran ne uporablja
  JavaScripta in v `apps/server` ne uvaja gradnje frontenda") in isto vrstico
  med tehničnimi mejami v `ADR-006`
- **Stoji na:** `ADR-006` (stran je javna znotraj omrežja in nima seje)
- **Delno spremenjeno z:** `ADR-054` — za `preizkus.html` veljajo meje iz
  `ADR-054`, za vse ostale strani ta ADR

## Kontekst

Operaterska stran je od `V1-R04` namerno brez JavaScripta. Pravilo se v
dokumentaciji ponovi štirikrat: kot sprejeta odločitev 1 v planu `V1-R04`, kot
kriterij sprejemljivosti iste zahteve, kot tehnična meja v `ADR-006` in nato
še kot kriterij v `V2-R03` („tiskanje je HTML z `@media print`, ne knjižnica
za PDF") in `V2-R04`. Cena je bila vsakič vidna in vsakič sprejeta: gumba
„Natisni" ni, ker ga brez skripte ni, in stran namesto njega naroči Ctrl+P.

`V2-R08` hoče povečan prikaz slike s tipko `Esc` in listanjem s tipkama
puščic. To je prva zahteva, ki se ob to mejo ustavi tako, da je brez nje ni
mogoče izpolniti v celoti.

## Možnosti

1. **A — brez skripte, prekritje na `:target`.** Povezava `#slika` odpre
   prekritje, ki ga izriše CSS.
   Za: pravilo ostane nedotaknjeno; zapiranje s klikom zunaj, gumbom in
   brskalnikovim „nazaj" dela.
   Proti: `Esc` ne dela in tipkovnice ni. Naslov strani nosi `#slika`, kar
   pomeni, da osvežitev strani prekritje spet odpre. Vsaka naslednja prikazna
   izboljšava bo naletela na isto mejo in bo terjala isto debato.

2. **B — klik odpre `/admin/materials/{id}/image` v novem zavihku.**
   Za: nič kode; brskalnik da povečavo in shranjevanje zastonj.
   Proti: brez listanja, brez sloga strani, in operater konča v zavihku, iz
   katerega se ne vrne na podrobnosti.

3. **C — skripta, z zapisanimi mejami.**
   Za: `V2-R08` izpolnjena v celoti.
   Proti: prvo odstopanje od pravila, ki je štirikrat zapisano. Odstopanje
   brez meje se razraste; meja mora nastati zdaj, ne takrat, ko se bo to
   pokazalo.

## Odločitev

**Izbrana je C.** Lastnik je `Esc` in tipkovnico ocenil kot dovolj, da se
pravilo umakne — ne pa dovolj, da se umakne brez nadomestila. Namesto enega
pravila, ki je stran branilo samo, veljajo odslej štiri meje, ki jih mora
nekdo brati:

1. **Brez gradnje frontenda.** Nobenega `npm`, `package.json`, bundlerja ali
   generatorja v `apps/server`. Skripta živi vgrajena v predlogo, natanko
   tako, kot v `osnova.html` že živi slog — in iz istega razloga: ločena
   datoteka bi zahtevala streženje statičnih datotek.
2. **Brez zunanje knjižnice.** Nobene povezave na CDN — strežnik stoji za
   Tailscale in zunanjega omrežja lahko sploh nima — in nobene knjižnice,
   prepisane v repozitorij. Kar skripta počne, počne z DOM API.
3. **Stran mora delovati brez skripte.** Nadgradnja, ne pogoj. Vsak element,
   ki ga skripta naredi klikljivega, je že v izrisanem HTML povezava, ki
   nekam pelje; skripta klik samo prestreže. Brskalnik z izklopljeno skripto
   ali napaka v njej ne smeta pustiti strani, ki ne odgovarja.
4. **Skripta ne piše v bazo in ne sestavlja poti.** Vsako dejanje, ki
   spremeni stanje, ostane obrazec ali povezava, ki jo je izrisal strežnik.
   Razlog je `ADR-006`: stran nima gesla in nima seje, zato je edina
   preostala obramba ta, da vsaka pot, ki piše, pride iz obrazca, ki ga je
   izrisal strežnik.

Meja te odločitve: ADR skripto **dovoljuje, ne predpisuje.** Kriterij „brez
JavaScripta" v `V2-R07` in kjerkoli drugje velja naprej, dokler ga zahteva
sama ne umakne. Stran brez skripte ostaja privzetek.

## Posledice

- **Kaj to olajša:** `V2-R08`. In vsako poznejšo čisto prikazno izboljšavo, ki
  je danes ne pišemo samo zato, ker brez skripte ne gre.
- **Kaj to oteži — dokazovanje.** Pytest nad izrisanim HTML skripte ne
  izvede. Dokazljivo je samo, kaj je v izrisu: povezava pod sliko, podatkovni
  atributi, prisotnost skripte. Kako se prekritje res obnaša, dokaže šele
  ročni preizkus v fazi 9b. To je nova vrsta luknje v dokazu — merilo
  dokončanosti („testi kaj dokazujejo") na tem delu ne prime in ga ne sme
  navidezno pokrivati zelen test, ki preverja le, da je v HTML niz `<script>`.
- **Kaj to oteži — mejo.** „Brez JavaScripta" je bilo pravilo, ki ga ni bilo
  treba razlagati in se ga ni dalo napol upoštevati. Štiri meje zgoraj je
  mogoče obiti po nesreči. Pregledovalec jih mora preverjati izrecno.
- **Na katere zahteve to odslej vpliva:** `V2-R08` (stoji na tem ADR);
  `docs/01-arhitektura.md` bo ob zaključku `V2-R08` treba popraviti na treh
  mestih, kjer danes trdi, da stran skripte nima.
