# ADR-018: Objava kviza ne preverja, ali je bilo vprašanje medtem upokojeno

- **Datum:** 2026-09-09
- **Nastalo pri:** V2-R01 (faza 7 — neodvisen pregled)
- **Status:** Sprejeto
- **Preglasi:** vrstico kontrolnega seznama v `docs/plan/V2-R01.md`
  („Nikjer v izbirniku, predogledu ali **objavi** se ne bere upokojenih
  vprašanj"), kolikor se nanaša na objavo
- **Stoji na:** `ADR-016` (E — postavka zamrzne besedilo), `ADR-015`
  (upokojitev), `ADR-017`

## Kontekst

Plan `V2-R01` si na tej točki nasprotuje sam s sabo, kar je odkril pregled v
fazi 7:

- razdelek „Razčiščeno v fazi 1" pravi, da se vprašanje, ki je bilo upokojeno
  **med predogledom in objavo**, vseeno objavi;
- kontrolni seznam za pregledovalca na koncu istega dokumenta pa zahteva, da
  se upokojena vprašanja ne berejo nikjer, objavo vključno.

Koda dela po prvem. `KviziRepository.vprasanja_po_idjih` bere vprašanja po
identifikatorjih iz skritih polj, brez pogoja `retired_at IS NULL`.

Po `CLAUDE.md` §3 se plan za nazaj ne prepisuje; kar ga preglasi, gre v ADR.
Ta ADR to razreši, plan pa ostane, kakršen je bil — vključno z nasprotjem, ki
je bilo takrat spregledano.

## Odločitev

**Velja zapis iz faze 1: objava upokojitve ne preverja.** Kontrolni seznam
plana v tem delu ne velja.

Trije razlogi:

1. **Objavi se, kar je bilo videno.** Predogled je edina priložnost videti, kaj
   boš objavil (`ADR-016` A). Če bi objava tiho izpustila vprašanje, ki je bilo
   v predogledu, bi kviz imel manj postavk, kot jih je operater potrdil — in
   nobenega mesta, kjer bi to izvedel.
2. **Zavrnitev bi bila dražja od škode.** Alternativa „zavrni cel izbor" pomeni,
   da operater izgubi celotno sestavljanje zaradi dogodka, ki zahteva ponovno
   obdelavo v drugem zavihku v tistih tridesetih sekundah.
3. **Škode pravzaprav ni.** Postavka besedilo tako ali tako zamrzne
   (`ADR-016` E), upokojeno vprašanje pa obdrži svojo identiteto (`ADR-015`) —
   `V2-R04` ga zna šteti enako kot vsako drugo.

Meja te odločitve: **velja samo za objavo po opravljenem predogledu.** Izbirnik
in predogled upokojena vprašanja še naprej izločata; tam kontrolni seznam
plana velja nespremenjen. Vsak od obeh ima svoj dokaz — prva različica tega
ADR je za predogled imenovala testa, ki sta pokrivala samo izbirnik, in to je
odkril drugi krog pregleda:

| Kje | Poizvedba | Test |
|---|---|---|
| izbirnik — število vprašanj | `KviziRepository._stej_veljavna` | `test_obdelana_snov_brez_veljavnih_vprasanj` |
| izbirnik — „bila v kvizu" | `KviziRepository._ze_v_kvizu` | `test_upokojeno_vprasanje_ne_steje_za_bilo_v_kvizu` |
| **predogled** | `KviziRepository.snovi_z_vprasanji` | `test_predogled_ponudi_novo_serijo_in_ne_upokojene` |

Zadnja vrstica je pomembnejša od prvih dveh: predogled je poizvedba, ki
določa, kaj bo dejansko zamrznjeno v kviz. Če bi njen filter odpadel, bi
predogled po ponovni obdelavi ponudil staro serijo — obe imata `position`
1..n in med njima ne bi ločil nihče —, operater bi jo potrdil, objava pa bi
jo po tej odločitvi brez ugovora sprejela.

## Kaj objava vseeno preverja

Da to ni luknja, ampak ozko izvzetje. Objava je edina pot, ki v bazo piše, in
vsakemu polju iz obrazca pogleda pod prste — skrito polje ni varovalka, po
istem pravilu kot gumb, ki ga stran ne izriše:

- vstop mora biti eden od treh, predmetni vstop mora imeti predmet;
- vsak `question_id` mora obstajati in **noben se ne sme ponoviti** — sicer
  409 in nič v bazi. Oboje ujame ena primerjava: `najdena` je slovar, ključan
  po `id`, ki ga manjkajoče vprašanje skrajša, podvojeno pa ne podaljša;
- ime sme meriti največ 200 znakov in koda predmeta 16 — natanko širina
  stolpcev. Preverba je v kodi in ne v bazi, ker testi tečejo nad SQLite, ki
  dolžine `VARCHAR` ne uveljavlja: na Postgresu bi bil predolg vnos `DataError`
  in operater bi dobil angleški „Internal Server Error", zbirka pa bi bila
  zelena;
- besedilo se prepiše iz baze in nikoli iz obrazca.

Prva različica tega razdelka je za zavrnitev podvojitve navajala napačen
razlog — da je ločena preverba s `set()` potrebna, ker naj primerjava števila
najdenih podvojitve ne bi ujela. Ujame jo; ločena preverba je bila mrtva veja
in je ob tem popravku šla ven.

## Posledice

- **Kaj to olajša:** objava je ena poizvedba in en `commit`, brez veje, ki bi
  jo bilo treba razlagati operaterju.
- **Kaj to oteži:** kviz *lahko* — v praksi izjemoma — vsebuje postavko, ki
  kaže na upokojeno vprašanje. `V2-R04` mora to prenesti; ker statistika stoji
  na dnevniku poskusov in ne na veljavnosti vprašanja (`ADR-012`, `ADR-014`),
  to zanjo ni poseben primer.
- **Na katere zahteve to odslej vpliva:** `V2-R04` (upokojeno vprašanje se sme
  pojaviti med postavkami kviza).
