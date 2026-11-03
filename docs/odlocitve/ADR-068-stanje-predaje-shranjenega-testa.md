# ADR-068: Shranjen test ima stanje predaje; vsebina ostane nespremenljiva

- **Datum:** 2026-11-03
- **Nastalo pri:** `V4-R10` (iz `B-02`, fazi 1 in 2)
- **Status:** Sprejeto
- **Spreminja:** `ADR-053` F v delu „Statusov ni — zapis obstaja samo za
  končan preizkus" in docstring modela `Preizkus` („zapis se ne spremeni
  nikoli"); `ADR-055` A v delu „filter samo po predmetu"
- **Stoji na:** `ADR-053` (F, G), `ADR-055` (A, D, H), `ADR-011`, `ADR-025`

## Kontekst

Shranjen test danes ne pove, ali je že bil pri otroku in ali ga je otrok
rešil. Lastnik želi to označiti kasneje, na shranjenem testu, stanje vrniti
nazaj ob napačnem kliku in na pregledu filtrirati teste „v reševanju" in
„rešene" (`B-02`, odgovori lastnika 2026-10-16 in 2026-11-03).

`ADR-053` F pravi, da statusov ni in da se zapis ne spremeni. Brez tega ADR-ja
bi pregled kode spremembo pravilno zavrnil — ali pa bi jo kdo izpeljal s
splošnim `UPDATE`, ki odpre pot urejanju vsebine.

## Možnosti

1. **Stolpec s stanjem** (`shranjen | v-resevanju | resen`) — Za: en stolpec.
   Proti: čas predaje se izgubi in ga kasnejša migracija starim vrsticam ne
   more več dati (isti razlog kot `base_id`, `ADR-055` E).
2. **Dva časa, stanje izpeljano** (izbrano) — Za: enaka cena, čas ostane,
   stanje se ne more razići s časi. Proti: vrnitev čas pobriše, zato čas ni
   zgodovina.
3. **Tabela dogodkov predaje** — Za: polna zgodovina („kolikokrat je bil
   test pri otroku"). Proti: lastnik je ne rabi; več sheme in poizvedb za isti
   prikaz.

## Odločitev

Možnost 2.

**A. Dva časa na `preizkusi`.** `given_at` in `solved_at`, oba `NULL`
dovoljena. Stanje je izpeljano: brez časov *shranjen*, z `given_at`
*v reševanju*, s `solved_at` *rešen*. `solved_at` brez `given_at` ne nastane.

**B. Vsebina ostane nespremenljiva, spremeni se samo predaja.** Repozitorij
dobi eno metodo, ki piše samo ta dva stolpca. Test, rešitve, snov, predmet,
naslovljenec, model in čas shranjevanja ostanejo brez `UPDATE`; `ADR-053` F
in model `Preizkus` se v tem delu popravita.

**C. Prehodi.**

| Iz | Dejanje | V |
|---|---|---|
| shranjen | Dan otroku | v reševanju (`given_at` = zdaj) |
| shranjen | Rešen | rešen (oba časa = zdaj) |
| v reševanju | Rešen | rešen (`solved_at` = zdaj) |
| v reševanju | Vrni | shranjen (`given_at` = `NULL`) |
| rešen | Vrni | v reševanju (`solved_at` = `NULL`) |

Drugih prehodov ni.

**D. Dejanje velja za stanje, ki ga je starš videl.** Obrazec pošlje dejanje
in stanje, iz katerega je bilo dano; strežnik zapiše samo, če je stanje še
tako (pogoj v istem `UPDATE`). Sicer se ne zgodi nič in ogled pokaže
trenutno stanje. Brez tega bi dvojni klik ali dva starša hkrati z „Vrni"
test vrnila za dva koraka.

**E. Vrnitev ni brisanje.** Pobriše vrednost v stolpcu, zapis testa ostane;
`ADR-011` ne pade. Čas po vrnitvi zato ni zgodovina, ampak trenutno stanje.

**F. Kje.** Samo na ogledu shranjenega testa, kot navaden obrazec s CSRF
žetonom in 303 nazaj na ogled. Skripta ogleda ostane, kakršna je: strežnika
ne kliče in ničesar ne pošilja (`ADR-055` D).

**G. Prikaz.** Datuma se nikjer ne prikazujeta. Pregled dobi filter stanja,
ki se sestavlja s filtrom predmeta (`ADR-055` A se v tem delu razširi);
neznano stanje da prazen seznam kot neznan predmet. Vrstica pokaže oznako
„v reševanju" ali „rešen".

**H. Brez omejitev po otroku.** Test deaktiviranega otroka (`ADR-055` H) se
da označevati naprej. „Nov test na tej osnovi" je nova vrstica in začne kot
*shranjen*.

## Posledice

- **Olajša:** `B-03` (opombe) lahko stoji ob istem zapisu, ne da bi odprl
  urejanje vsebine.
- **Oteži:** model `Preizkus` ni več „nikoli spremenjen"; varovalo je ozka
  metoda in test, da nobena druga pot ne piše v `preizkusi`.
- **Razveljavitev migracije** stolpca odstrani in stanje predaje izgubi;
  vrstice ostanejo. Ker izguba ne odpre dostopa, se razveljavitev ne ustavi.
- **Vpliva na:** `V4-R08` (pregled in ogled), `docs/01-arhitektura.md`,
  `test_tesnjenje.py` (nova pot), `test_migracija.py` (`0016`).
