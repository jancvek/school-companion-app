# ADR-045: Kaj „za starša ne obstaja" obsega in kaj ne

- **Datum:** 2026-09-20
- **Nastalo pri:** V3-R05 (faza 2, po tretji vrnitvi istega mesta v pregledu)
- **Status:** Sprejeto
- **Dopolnjuje:** `ADR-044` G — obljubo skrivanja zoži na tisto, kar aplikacija
  lahko drži; kriterij 1 zahteve `V3-R05` je zato popravljen v
  `docs/verzije/v3.md`
- **Stoji na:** `ADR-025` (krog uporabnikov so znanci lastnika), `ADR-035` A
  (varovalo je plast, ne pazljivost), `ADR-044` (izvedba `V3-R05`)

## Kontekst

Kriterij 1 zahteve `V3-R05` je pisal: *„Stran `/admin/system`, vidna izključno
lastniku sistema. Za starša ne obstaja — 404, ne 403."* `ADR-044` G je to
izpeljal v odvisnost na usmerjevalniku, ki dvigne `404`.

Med pregledom se je isto mesto vrnilo **trikrat**:

1. `GET` na pot, ki obstaja samo kot `POST`, je vrnil `405` — torej „ta pot
   obstaja". Popravljeno z registrirano potjo.
2. `POST` na poti, ki obstajata samo kot `GET`, je vrnil `405` enako. Popravljeno
   s prevodom `405 → 404` in zavrženo glavo `Allow`, za celo predpono naenkrat.
3. `GET /admin/system/` (s končno poševnico) vrne `307` in v glavi `location`
   izda točen naslov; `/openapi.json` z veljavnim žetonom — tudi **otrokovim** —
   pa vrne shemo z vsemi potmi `/admin/system/...`.

Tretja vrnitev je znak, ki ga `CLAUDE.md` §7 imenuje izrecno: trije popravki
iste odločitve pomenijo, da je napačna odločitev, ne izvedba. Zato četrtega
popravka ni.

## Kontekst, ki ga prejšnji ADR ni imel

**„Nerazločljivo od neobstoječe poti" ni lastnost usmerjevalnika, ampak celega
sklada.** Vsako mesto, kjer okvir znano pot obravnava drugače od neznane —
ujemanje metode, preusmeritev ob poševnici, shema poti, jutri kaj četrtega — je
nova luknja. Teh mest ni mogoče prešteti, zato jih ni mogoče zapreti s seznamom
popravkov; vsak popravek je zaprl eno in pustil naslednjo.

**Kar je pri tem ves čas veljalo:** nobena od treh lukenj ni odprla nobenega
podatka tuje družine. Podatke drži `dependencies.zahtevaj_lastnika_sistema` na
usmerjevalniku, ne koda odgovora, in ta je tesen — dokazano z mutacijo, ki
podre štirinajst testov. Vse tri luknje izdajo izključno to, da stran
**obstaja**.

**Kdo je nasprotnik.** `ADR-025` pravi, da krog uporabnikov niso stranke, ampak
znanci lastnika, in da registracije ni. Starš, ki bi ugotovil, da obstaja
`/admin/system`, s tem ne dobi ničesar: ne vsebine, ne seznama družin, ne
imena. Skrivanje obstoja je torej **udobje in ne varovalo**, in obljuba brez
meje je bila napisana, kot da je varovalo.

## Odločitev

**Obljuba se zoži na tisto, kar aplikacija lahko drži, in meja se zapiše.**

Velja (in je preizkušeno s testi):

- Vsaka pot pod `/admin/system` vrne za vsakogar razen lastnika sistema `404`,
  **na vsako metodo** — tudi na tisto, ki je ta pot nima.
- Telo je **enako** telesu neobstoječe poti in glave `Allow` ni.
- Pravilo je na enem mestu (`admin.prestrezi_napako` + `sistem.je_skrita_pot`)
  in velja tudi za pot, ki bo dodana pozneje; test se generira iz `openapi()`.

Ne velja in se ne obljublja:

- **Usmerjanje okvirja.** `GET /admin/system/` s končno poševnico vrne `307` na
  naslov brez nje, ker Starlette to preusmeritev naredi sam, brez izjeme, in je
  prestreznik ne vidi. Izklop (`redirect_slashes=False`) bi veljal za **vso**
  aplikacijo in podrl preusmeritev za `/admin/`, naslov, ki ga brskalnik
  ponudi sam (`docs/01-arhitektura.md`, „Operaterska stran") — cena je večja od
  koristi.
- **Shema poti.** `/openapi.json` z veljavnim žetonom vrne vse poti aplikacije.
  To ni lastnost te zahteve: shema je odprta nosilcu žetona od `V1` in je
  razkrivala tudi `/admin/family` iz `V3-R06`. Če bo zaprta, bo to svoja
  zahteva s svojim ADR — glej „Kaj smo zavestno pustili odprto".

Kriterij 1 v `docs/verzije/v3.md` je popravljen, da to pove. **Koda se ne
spremeni**: stanje na veji `feat/v3-r05-lastnik-odpira-druzine` popravljeni
kriterij že izpolnjuje.

## Zavrnjeni možnosti

- **Zmanjšati površino** — ugasniti `/openapi.json`, `/docs` in `/redoc` v
  produkciji. Zapre eno od dveh lukenj in je sama po sebi smiselna, vendar je
  sprememba odločitve zunaj te zahteve (shema kot javna) in bi morala priti s
  svojim ADR. Poševnice ne zapre.
- **Opustiti skrivanje** — nazaj na `403` z nevtralno stranjo. Pošteno, a
  razveljavi zapisani kriterij in zahteva spremembo kode in testov za nekaj,
  kar danes že dela; poleg tega izgubi tudi to malo, kar skrivanje da.

## Posledice

- **Kaj to olajša:** obljuba je preverljiva in ima test za vsako svojo trditev.
  Naslednji bralec ne bo iskal četrte luknje kot napako, ker je meja zapisana.
- **Kaj to oteži:** iz `GET /admin/system/` in iz `/openapi.json` je mogoče
  ugotoviti, da stran obstaja. Sprejeto zavestno, ker so uporabniki znanci
  (`ADR-025`) in ker obstoj brez vsebine ni podatek, ki bi komu koristil.
- **Kaj smo zavestno pustili odprto:** `/openapi.json`, `/docs` in `/redoc` so
  dosegljivi vsakemu veljavnemu žetonu, tudi otrokovemu. Zaprtje je svoja
  zahteva; zapisano je kot znana omejitev v `docs/01-arhitektura.md`, da se ne
  izgubi.
- **Za prihodnje zahteve velja pravilo:** kadar kriterij zahteva, da se nekaj
  **ne vidi**, naj pove, kdo je nasprotnik in kje je meja. „Ne obstaja" brez
  meje je obljuba o celem skladu in je ni mogoče izpolniti.
