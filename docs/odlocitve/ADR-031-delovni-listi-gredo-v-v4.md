# ADR-031: Delovni listi gredo v V4 in se ne imenujejo „test"

- **Datum:** 2026-09-15
- **Nastalo pri:** V4 (pred verzijo)
- **Status:** Sprejeto

## Kontekst

Starš želi iz otrokovih poslikanih zapiskov sestaviti list, ki ga natisne in
da otroku reševati s svinčnikom: kratka razlaga snovi („plonk"), naloge s
prostorom za odgovore, in na ločenem listu rešitve s postopkom reševanja.
Otrok tega nikoli ne vidi v mobilni aplikaciji — obstaja samo v starševskem
(admin) pogledu in na papirju.

Dve vprašanji sta terjali odločitev, preden nastane ena sama zahteva:

1. **Kam to sodi.** V3 je izrecno verzija brez novih zmožnosti: dodaja mejo in
   identiteto, ne funkcionalnosti (`docs/verzije/v3.md`). Delovni listi so po
   obsegu večji od vsega, kar V3 dodaja — generator, iteracija, pretvorba v
   Word, opombe, arhiv.
2. **Kako se to imenuje.** V pogovoru temu rečeva „test". V repozitoriju sta
   `pytest` in `jest`, mapa `tests/` in datoteke `test_*.py`.

Tretje vprašanje je odvisnost: list mora biti pisan za določen razred, razred
pa je lastnost otroka — otroka kot uporabnika pa uvede šele V3.

## Možnosti

1. **Dodatek k V3** — Za: razred nastane v isti verziji kot uporabniki; ena
   verzija manj. Proti: podre obljubo „sprememb v funkcionalnosti ni", ki je v
   `v3.md` zapisana kot merilo obsega; V3 bi se podvojila.
2. **Pred V3, z razredom kot nastavitvijo namestitve** — Za: uporabno takoj.
   Proti: nastavitev, ki jo je treba kasneje odstraniti; take se ne odstranijo.
   Z več otroki v družini (`V3-R07`) je en sam razred na namestitev tudi
   napačen podatek, ne le začasen.
3. **Svoja verzija V4, za V3** — Za: obseg ostane berljiv, razred pride tja,
   kamor sodi; V3 ostane, kar je obljubila. Proti: čaka na celo V3.

Glede imena:

1. **`test`** — Za: tako mu rečeva. Proti: `pytest` pobira `test_*`, mapa
   `tests/` je zasedena, in vsak pogovor o „testih" odslej terja pojasnilo.
2. **`preizkus`** — Za: brez trka. Proti: pomeni preverjanje znanja za oceno,
   kar ta list ni.
3. **`delovni_list`** — Za: brez trka in pošten opis; razlaga, naloge in
   rešitve na papirju niso ocenjevanje. Proti: daljše.

## Odločitev

**Delovni listi so verzija V4 in se gradijo za V3** (možnost 3). V4-R01
(pretvornik markdown → Word) je edina zahteva, ki na V3 ne čaka in se sme
graditi vzporedno, ker ne pozna ne baze ne uporabnikov.

**V kodi, bazi, poteh in imenih datotek je to `delovni_list`** (angl.
`worksheet`, kjer je koda v angleščini). Beseda „test" ostane rezervirana za
avtomatske teste. V pogovoru z lastnikom ostaja „test" dovoljena — to je
razlika med besediščem pogovora in besediščem repozitorija in je namerna.

## Posledice

- Kaj to olajša: obseg V3 ostane zaprt; delovni listi dobijo svoj cilj in
  svoje „kaj izrecno ni"; `grep delovni_list` nikoli ne zadene testne
  infrastrukture.
- Kaj to oteži: funkcionalnost čaka na V3. Kdor jo hoče prej, mora odpreti
  možnost 2 kot novo odločitev in pri tem zapisati, kdaj se začasni razred
  odstrani.
- Na katere zahteve to odslej vpliva: vse zahteve V4. `V4-R02` (razred otroka)
  je odvisna od `V3-R06`, `V4-R03` od `V3-R01` in `V3-R07`.
- Pojma „delovni list" in „opomba" gresta v `docs/00-namen.md`, sicer sta
  po `CLAUDE.md` fazi 1 nedefinirana pojma.
