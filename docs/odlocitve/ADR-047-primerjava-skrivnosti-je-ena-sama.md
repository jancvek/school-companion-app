# ADR-047: Primerjava skrivnosti je ena sama in primerja bajte

- **Datum:** 2026-09-21
- **Nastalo pri:** V3-R08 (faza 7, po drugem pregledu)
- **Status:** Sprejeto
- **Stoji na:** `ADR-035` (CSRF žeton in seje), `ADR-046` H (dve pravili o isti
  stvari se prej ali slej razideta)
- **Razveljavlja:** nič. Popravlja izvedbo iz `V3-R03`, ne njene odločitve.

## Kontekst

`V3-R08` je dodala pot `POST /auth/google/login`, ki CSRF žeton preveri sama
(seje ob njej še ni), in povratni klic, ki primerja `state`. Oboje je
primerjava skrivnosti, ki pride iz zahteve.

Prvi pregled je našel, da `secrets.compare_digest` nad `str` zahteva čiste
ASCII znake in ob vsakem drugem vrže `TypeError`. Na povratnem klicu je to
pomenilo `500` z golim angleškim besedilom **in** — huje — izjemo, ki je ušla
pred brisanjem piškotka stanja, s čimer je padlo jamstvo `ADR-046` D o
enkratni rabi.

Prvi popravek je naredil **svojo** funkcijo `google._enaka` in popravil tisti
dve klicni mesti, ki sta bili v obsegu zahteve. Drugi pregled je pokazal, da to
ni bil popravek, ampak drugo pravilo: koren je `prijava.zetona_se_ujemata`, ki
ima **štiri** klicna mesta, in tri od njih so še naprej dajale `500`:

| Klicno mesto | Zahteva | Kaj je dajalo |
|---|---|---|
| `app/routers/vstop.py` (Google prijava) | V3-R08 | `500` na `POST /auth/google/login` |
| `app/routers/vstop.py` (admin prijava) | V3-R03 | `500` na `POST /admin/login` |
| `app/security.py` (`SejaMiddleware`) | V3-R03 | `500` na **vsak** `POST` pod `/admin` |
| `app/routers/urnik.py` (`ADR-043`) | V3-R09 | `500` na nalaganje slike urnika |

## Možnosti

1. **Ozko: popravi samo klicno mesto `V3-R08`.** Za: ostane strogo v obsegu
   zahteve (`CLAUDE.md` §5). Proti: `google._enaka` in
   `prijava.zetona_se_ujemata` ostaneta dve skoraj enaki funkciji za isto
   opravilo, ena pravilna in ena ne — natanko razhajanje, pred katerim svari
   `ADR-046` H, in ki se je tu zgodilo v **istem commitu**, ki ga je povzročil.
   Tri znane `500`-ke ostanejo v produkciji do nove zahteve.
2. **Pri korenu: popravi `prijava.zetona_se_ujemata`.** Ena vrstica, vsa štiri
   klicna mesta hkrati, `google._enaka` odpade. Proti: dotakne se modula, ki
   pripada `V3-R03`, torej formalno širi obseg zahteve.

## Odločitev

**Možnost 2**, po izrecni odločitvi lastnika (faza 7, drugi pregled).

`zetona_se_ujemata` primerja bajte:

```python
return secrets.compare_digest(prvi.encode("utf-8"), drugi.encode("utf-8"))
```

Utemeljitev, zakaj to ni razraščanje obsega v pomenu `CLAUDE.md` 9b:

- **Pogodba se ne spremeni.** Žeton z ne-ASCII znakom ni bil veljaven nikoli;
  spremeni se samo izid ob njem, iz `500` v `403`. Nobena zahteva `V3-R03` ne
  neha veljati in nobeno njeno vedenje se ne spremeni.
- **Merilo dokončanosti `V3-R08` tega tako ali tako zahteva.** `CLAUDE.md` §1b:
  sporočila o napakah so v slovenščini in ne kažejo surovega besedila
  sistemske napake. Na **moji** poti je to padlo, in čistega ozkega popravka
  ni: primerjava živi v tuji funkciji, zato bi ozek popravek pomenil ali
  podvojitev pravila ali seganje v tujo funkcijo mimo njenega imena.
- **Popravek odpravi vzrok, ne simptoma.** Trije preostali `500`-ji so isti
  hrošč na istem mestu; pustiti jih bi pomenilo zapisati novo zahtevo za eno
  vrstico, ki je že napisana.

Pokritost varuje **generiran** test
(`test_vsak_post_pod_adminom_prenese_ne_ascii_zeton`): poti bere iz
`app.openapi()`, zato zajame tudi pot, ki bo dodana jutri. Ročni seznam bi
bil isti razred napake kot ročno našteta klicna mesta.

## Posledice

- **Kaj to olajša:** vsaka prihodnja primerjava skrivnosti ima eno samo mesto,
  ki je pravilno; kdor bo pisal novo pot s CSRF žetonom, ne more zadeti te
  napake, ne da bi se ji izrecno izognil.
- **Kaj to oteži:** nič v kodi. V procesu pa pusti zapis, ki ga je treba brati
  kot opozorilo: **popravek, ki podvoji pravilo namesto da popravi skupnega,
  ni popravek.** Prvi krog `V3-R08` je to stalo enega pregleda.
- **Na katere zahteve to odslej vpliva:** `V3-R03` (obe prijavi in
  `SejaMiddleware`), `V3-R09` (nalaganje urnika), vsaka prihodnja pot s CSRF
  žetonom.
