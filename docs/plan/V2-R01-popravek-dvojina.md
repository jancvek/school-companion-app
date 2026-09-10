# Plan: popravek — slovenska dvojina na starih straneh

> Nastane v fazi 4 in se commita na feature branch.
> Med čakanjem ga popravim neposredno v tej datoteki; moja verzija velja.
> Po mergu ni več aktualen; hrani se kot zapis, kaj je bilo takrat dogovorjeno.

**Branch:** `fix/dvojina-na-starih-straneh`

## Zahteva

Ni nova zahteva. Popravek kršitve **merila dokončanosti** iz `CLAUDE.md`
(„Jezik vmesnika je slovenščina"), ki velja za vsako zahtevo in se v kriterijih
posameznih zahtev ne ponavlja. Tri strani izpisujejo število slik v dveh
oblikah namesto v štirih in pri 2, 3 in 4 napišejo nepravilno slovenščino.

Odkrito ob izvedbi `V2-R01`, ki je za svoje strani uvedla štirioblično
`_stevilo_z_besedo` in s tem pustila v vmesniku dva standarda hkrati. Zapisano
je bilo v `docs/verzije/v2.md`, razdelek „Odločeno ob izvedbi", kot postavka za
pogovor; lastnik je odločil, da se popravi.

## Razčiščeno v fazi 1

| Vprašanje | Odgovor |
|---|---|
| Katera mesta so narobe | Tri: `predmeti.html:8`, `predmet.html:9`, `arhiv.html:10`. Vsa tri pišejo `{{ n }} {{ "slika" if n == 1 else "slik" }}`. |
| Katera so že pravilna | `snov.html` („Upokojena vprašanja: N") in `brisanje.html` („veljavnih: N, upokojenih: N"). Oblika z dvopičjem je pravilna pri vsakem številu. **Teh se ne dotikam.** |
| Pravilne oblike | *1 slika, 2 sliki, 3 slike, 5 slik.* Ločnica po ostanku pri sto — *101 slika*, *102 sliki*. |
| Kam gre funkcija | Iz `app/routers/kvizi.py` v nov `app/besedilo.py`. Usmerjevalnik ni lastnik jezikovnega pravila, ki ga potrebujeta oba. |
| Kdo sklanja | Usmerjevalnik, ne predloga. Predloga dobi gotov niz — isto pravilo kot pri `_pogled` („predloga ne računa in ne oblikuje"). |
| Ali se spremeni `brisanje.html` | Samo **komentar**, ne besedilo. Glej fazo 2. |

## Preverba iz faze 2

- **Že implementirano:** delno. `_stevilo_z_besedo` obstaja od `V2-R01`, a živi
  v `app/routers/kvizi.py` in je uporabljena samo tam.
- **Kaj lahko podre:**
  - `tests/test_admin.py::TestSeznamPredmetov::test_stevci_so_pravi` trdi
    `">2</span>" in vrstica_predmeta(...)` — to je števec ob predmetu in ne ta
    niz; ostane nedotaknjen.
  - Testi, ki iščejo „slik" v besedilu strani, se bodo morda morali uskladiti.
    Sprememba pogodbe, ne oslabitev: besedilo je bilo napačno.
  - `tests/test_kvizi.py` uvaža `_stevilo_z_besedo` iz `app.routers.kvizi`;
    uvoz se preseli.
- **Preglašena odločitev:** komentar v `brisanje.html` (V2-R05) pravi, da je
  „sklanjatev v predlogi več kode kot vrednosti". Takrat je držalo, zdaj ne —
  funkcija obstaja in je preizkušena. Ker odločitev ni bila zapisana v ADR,
  ampak samo v komentarju, se popravi tam. Novega ADR ne pišem: nobena
  zapisana odločitev projekta se ne razveljavlja, spremeni se le utemeljitev,
  ki ni več resnična. **Besedilo `brisanje.html` ostane nespremenjeno**, ker
  je pravilno.
- **Migracija:** je ni. Sheme se ne dotika.

## Sprejete odločitve

1. **Nov modul `app/besedilo.py`.** Tretji po `app/casi.py` in `app/strani.py`,
   po istem načelu: kar potrebujeta oba usmerjevalnika, ni last nobenega od
   njiju. Vsebuje `stevilo_z_besedo` in oblike (`SLIKE`, `VPRASANJA`, `SNOVI`).
   Ime je javno, brez podčrtaja — podčrtaj pomeni „ne uvažaj od zunaj".
2. **Sklanja usmerjevalnik, ne predloga.** `pregled`, `predmet` in `arhiv`
   dobijo gotov niz v kontekstu. Predloga ostane postavitev.
3. **Oblike so podatek, ne koda.** Vsak samostalnik je četverica na enem mestu,
   da se pri naslednji uporabi ne ugiba znova.
4. **`brisanje.html` in `snov.html` se vsebinsko ne spremenita.** Njuna oblika
   z dvopičjem je pravilna; menjava bi bila okus, ne popravek.

## Izrecno zunaj obsega

- **Besedilo, ki števila nima** (npr. „Prepis in vprašanja teh snovi ostajajo").
- **Sklanjatev po sklonih** — funkcija pozna število, ne sklona. „iz N snovi"
  je v `V2-R01` rešeno tako, da je oblika za rodilnik konstanta.
- **Telefon.** Ima svoje besedilo in svoj jezik; ta popravek se ga ne dotika.
- **Preimenovanje ali združevanje `casi.py` / `strani.py` / `besedilo.py`.**

## Vpliv

- **Nove datoteke:** `apps/server/app/besedilo.py`, `docs/plan/V2-R01-popravek-dvojina.md`.
- **Spremenjene datoteke:**
  - `apps/server/app/routers/kvizi.py` — `_stevilo_z_besedo` in oblike gredo ven, uvozijo se nazaj.
  - `apps/server/app/routers/admin.py` — trije pogledi dobijo gotov niz.
  - `apps/server/app/templates/predmeti.html`, `predmet.html`, `arhiv.html` — niz namesto pogoja.
  - `apps/server/app/templates/brisanje.html` — **samo komentar**.
  - `apps/server/tests/test_kvizi.py` — preseljen uvoz.
  - `apps/server/tests/test_admin.py` — nove trditve o oblikah.
  - `docs/01-arhitektura.md` (faza 8).
- **Spremembe navzven:** besedilo na treh straneh `/admin`. **Brez sheme, brez
  nove poti, brez nove odvisnosti, brez sprememb API-ja proti telefonu.**
- **Prizadete zahteve:** nobene. Kriteriji `V1-R04`, `V1-R07` in `V2-R01`
  ostanejo izpolnjeni; popravlja se merilo dokončanosti, ki velja čez vse.
- **Tveganja:** minimalna. Največje je, da kakšen obstoječi test išče „slik" v
  besedilu in pade — to je vidno takoj in je uskladitev, ne oslabitev.

## Ocena tveganja

`nizko` **po vsebini**, a **nad mejo po črki pravila.** Lestvica iz faze 4
postavlja mejo pri „≲ 3 datoteke"; tu jih je šest (nov modul, dva
usmerjevalnika, tri predloge), plus testi in dokumentacija.

Zakaj vseeno menim, da je nizko: vsaka od šestih sprememb je mehanska in
znotraj obstoječega vzorca, funkcija je že preizkušena in v produkciji od
`V2-R01`, sheme ni, odvisnosti ni, javnega vmesnika ni. Edino, kar se v resnici
spremeni, so trije nizi na strani.

Ker pravilo pravi „če nisi prepričan, spada v drugo skupino", **plan počaka na
tvoj „gremo"** — čeprav bi ga sam ocenil za nizkega.

## Koraki

1. `app/besedilo.py`: `stevilo_z_besedo` + četverice `SLIKE`, `VPRASANJA`, `SNOVI`.
2. `routers/kvizi.py`: funkcija in oblike ven, uvoz od tam.
3. `routers/admin.py`: `pregled`, `predmet` in `arhiv` dodajo gotov niz.
4. Tri predloge: niz namesto pogoja. `brisanje.html`: popravljen komentar.
5. Testi: oblike za slike v `test_admin.py`, preseljen uvoz v `test_kvizi.py`.
6. Celotna preverba iz `CLAUDE.md`, faza 8 — poženeš jo ti (ograja mi je ne da).

## Test casi

| Primer | Vhod / stanje | Pričakovano |
|---|---|---|
| Ena slika | predmet z 1 sliko | „1 slika" |
| **Dve sliki (dvojina)** | predmet z 2 slikama | „2 sliki", nikjer „2 slik" |
| Tri, štiri | predmet s 3 oz. 4 slikami | „3 slike", „4 slike" |
| Pet in več | predmet s 5 slikami | „5 slik" |
| Nič | predmet brez slik | stran pove svoje sporočilo, brez „0 slika" |
| Pregled sešteje čez predmete | 2 sliki pri MAT, 1 pri SLJ | „Skupaj 3 slike v uporabi" |
| Arhiv | 2 arhivirani sliki | „2 sliki" |
| Ostanek pri sto | `stevilo_z_besedo(101, SLIKE)` | „101 slika"; 102 → „102 sliki"; 111 → „111 slik" |
| Kvizi delujejo naprej | obstoječi testi `test_kvizi.py` | zeleni po preselitvi uvoza |
| `brisanje.html` nespremenjena | potrditvena stran brisanja | besedilo isto kot prej |

## Kriteriji, po katerih bo pregledovalec sodil

- [ ] Nikjer v `apps/server/app/templates/` ni več vzorca
      `{{ "…" if … == 1 else "…" }}`.
- [ ] `stevilo_z_besedo` živi v `app/besedilo.py`; `routers/kvizi.py` je ne
      definira več.
- [ ] Sklanja usmerjevalnik; predloga dobi gotov niz.
- [ ] Dvojina je pokrita s testom, ki pade ob dvoobličnem sklanjanju.
- [ ] `brisanje.html` in `snov.html` sta vsebinsko nespremenjeni.
- [ ] Brez sheme, brez nove odvisnosti, telefon nedotaknjen.

---
## Moje pripombe (izpolnim jaz)
- 
