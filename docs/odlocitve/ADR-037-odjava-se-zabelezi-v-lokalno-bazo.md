# ADR-037: Odjava se zabeleži v lokalno bazo, ne le v varno shrambo

- **Datum:** 2026-09-19
- **Nastalo pri:** V3-R04 (faza 7, tretji obhod pregleda)
- **Status:** Sprejeto
- **Stoji na:** `ADR-036` B (lastnik na vrstici, posvojitev), `ADR-027`
  (neprozorni žetoni), `ADR-004` (migracije lokalne sheme)
- **Razveljavlja:** v `ADR-036` pravilo, da je **vsak** žeton, prebran z diska,
  veljavna seja. Posvojitev ostane vezana na razrešeno sejo; razrešitev sama
  dobi dodaten pogoj.

## Kontekst

`pozabiSejo` napako brisanja **požre** (`src/sync/prijava.ts`), in to je prav:
nedosegljiva varna shramba ne sme pustiti otroka prijavljenega na napravi, na
kateri se je hotel odjaviti. Cena te odločitve je, da žeton ob spodleteli
odjavi ostane na disku.

`ADR-036` je nato posvojitev vezal na **vsako razrešeno sejo**, tudi na tisto
iz žetona, prebranega z diska. Tretji obhod pregleda je pokazal, kaj se v
kombinaciji zgodi:

1. Maša se odjavi; brisanje iz varne shrambe tiho spodleti. Seja v pomnilniku
   vseeno pade, zato je aplikacija videti odjavljena.
2. Jaka slika. Posnetki nastanejo brez lastnika.
3. Aplikacija se zapre in znova odpre. `preberiSejo` najde **Mašin** žeton in
   sejo obnovi.
4. Posvojitev pripiše **Jakove posnetke Maši**.

Mašina seja je na strežniku že izbrisana, zato prenos vrne `401`. Jaka teh
posnetkov ne dobi nazaj — posvojitev vzame samo tiste brez lastnika —, in
nihče jih ne vidi.

To ni napaka posvojitve. Pravilo „vsaka razrešena seja posvoji" ne zna ločiti
*„žeton na disku je veljaven"* od *„žeton na disku je ostanek spodletele
odjave"*, ker je edini vir resnice o seji isti disk, ki je odpovedal.

## Možnosti

1. **Pustimo tako in zapišemo kot ceno.** Za: nič dela. Proti: tiha
   napačna pripisanost na skupnem telefonu — natanko tisto, kar je `V3-R04`
   hotel preprečiti. Redko, a brez sledi in brez poti nazaj.
2. **Posvoji šele potrjena seja** — prvi uspešen odgovor strežnika, ne prebran
   žeton. Za: zastarel žeton ne posvoji ničesar, ker ga strežnik zavrne.
   Proti: posvojitev postane odvisna od omrežja. Na telefonu brez povezave bi
   posnetki ostali brez lastnika in jih Zgodovina ne bi kazala do prvega stika
   s strežnikom — to trči ob načelo *„aplikacija nikoli ne čaka na strežnik"*.
3. **Odjavo zabeležimo v lokalno bazo.** Ob odjavi se v SQLite zapiše oznaka;
   ob zagonu žeton, ki jo sreča, ne velja in se zavrže. Za: napaka je v varni
   shrambi, oznaka pa gre v shrambo, ki v tem scenariju **dela** — ista, v
   katero se zapisujejo posnetki. Brez omrežja in brez ugibanja. Proti: ena
   migracija lokalne sheme več in eno stanje več.

## Odločitev

**Možnost 3.**

```
naprava (id = 1, odjava_ob TEXT)     -- migracija 4
```

- **Ob odjavi:** najprej oznaka v SQLite, nato brisanje iz varne shrambe. Če
  brisanje **uspe**, se oznaka takoj počisti. Oznaka torej obstaja samo takrat,
  kadar je odjava ostala nedokončana — ali ker je brisanje spodletelo, ali ker
  je aplikacija med korakoma umrla.
- **Ob zagonu:** žeton, ki ga sreča postavljena oznaka, se **zavrže**.
  Aplikacija je neprijavljena, brisanje se poskusi znova in oznaka se ob uspehu
  počisti. Posvojitve ni, ker ni seje — Jakovi posnetki ostanejo brez lastnika
  in jih posvoji njegova prijava.
- **Ob prijavi:** oznaka se počisti. Nova prijava prekliče vsako nedokončano
  odjavo pred njo.

`pozabiSejo` zato odslej **pove, ali je uspela**. Še naprej ne vrže; razlika je
le v tem, da klicatelj izve, ali sme oznako počistiti.

Posvojitev ostane, kakršna je: vezana na razrešeno sejo, ne na prijavo
(`ADR-036`, popravki po drugem pregledu). Spremeni se samo to, katere seje se
sploh razrešijo.

## Posledice

- **Kaj to olajša:** menjava uporabnika na skupnem telefonu je odslej odporna
  na odpoved varne shrambe. `V3-R06` bo preklic sej lahko gradil na isti
  oznaki, če bo hotel odjavo vsiliti z druge naprave.
- **Kaj to oteži:**
  - Lokalna shema gre na verzijo **4** in z njo pride zamrznjena kopija
    `SHEMA_VERZIJE_3` za migracijski test (`ADR-004`).
  - Ena vrstica stanja, ki ni v varni shrambi. Če bi kdo kdaj lokalno bazo
    počistil, ne pa varne shrambe, bi star žeton spet obveljal — a to je
    dejanje, ki ga aplikacija ne počne.
  - Cena odločitve `ADR-036` G (odjava je najprej lokalna) je s tem plačana
    na pravem mestu: odjava ostane takojšnja, sled pa se ne izgubi.
- **Na katere zahteve to vpliva:** `V3-R06` (ponastavitev gesla in
  deaktivacija prekličeta seje — ta oznaka je lokalni par tega), `V3-R07`
  (lastnik zapisa mora biti pravi, sicer statistika govori o napačnem otroku).
