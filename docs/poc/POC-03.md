# POC-03 — Predstavitvena stran in okno registracije

> Nastane v koraku 1 POC poti (`CLAUDE.md` §1d) na veji `poc/xx-…`.
> Je **edini del POC-a, ki pride v `main`** — koda se zavrže. Zato mora vse,
> kar je bilo vredno izvedeti, stati tukaj, ne v kodi in ne v pogovoru.

**Veja:** brez veje `poc/03-…` — predlogi so nastali v pogovoru zunaj
repozitorija; zapis je napisan naknadno na `docs/v6-registracija` (glej
*Ugotovitve → Pot tega zapisa*).
**Oblika:** `idejni/UX`
**Časovni okvir:** en krog = ena seja, največ trije krogi
**Sodba:** `Sprejeto`

**Kje je koda:** zunaj repozitorija, v lastnikovi mapi
`C:\Personal\School Companion App`:

- `domaca-stran-predlog.html` — predstavitvena stran (in skica prijave, ki ni
  vhod; glej *Namenoma ne rešujem*);
- `registracija-predlog.html` — okno registracije, stran „Moj račun" in prva
  stran po odobritvi, v vseh stanjih.

Izmišljeni podatki, slog in žetoni iz `POC-02`. Skripta je samo za preklop
stanj in teme v predogledu. Na tej veji sta samo ta zapis in posnetki zaslona
v `docs/poc/POC-03/`.

## Vprašanje

Ali kratka javna stran, ki pokaže, kaj Šolski pomočnik zna — s poudarkom na
sestavljanju testov in na kvizih —, skupaj z oknom registracije z Googlom
neznanemu staršu dovolj jasno pove, kaj dobi, kam gredo slike in kaj se
zgodi z njegovim zahtevkom, da ju želim uvesti?

## Kaj šteje kot »ok«

- Obiskovalec na prvem zaslonu razume, za koga je aplikacija in kaj dobi
  (test za tisk), in najde Registracijo in Prijavo.
- Testi in kvizi sta vidna kot glavni funkciji; ostalo je na drugem mestu.
- Stran naravnost pove, da slike gredo v zunanjo storitev.
- Okno registracije v vsakem stanju pove, kje v postopku je starš in kaj
  sledi; nobeno stanje ne obljublja e-pošte.
- Vse deluje pri širini 390 px brez vodoravnega drsenja in v temni temi.

## Namenoma ne rešujem

- **Lastnikove strani za odobritev** (`/admin/system`, `ADR-057` E). Dobi nov
  videz po pravilih V5.
- **Povezave otrokovega telefona s QR** (`V6-R01`). Stran jo samo omeni.
- **Prijavne strani.** Velja `POC-02` (posnetka 24–25). Pogled „Prijava" v
  `domaca-stran-predlog.html` je skica in **ni** vhod za implementacijo.
- **Besedila pravil zasebnosti.** Povezava „pravila zasebnosti" vodi na
  razdelek predstavitvene strani; pravno besedilo je odprto.
- **Googlovega uradnega gumba in Googlovega okna.** Gumb v predlogu ima
  nevtralen „G"; implementacija uporabi Googlov gumb po njihovih pravilih.
- **Drugega starša v isti družini.** Vsaka registracija ustvari svojo
  družino; primer, ko vsak od staršev naredi svojo, se zaenkrat ne rešuje.

## Krogi

### Krog 1 — 2026-10-10
- **Zgrajeno:** `domaca-stran-predlog.html` — uvod, „Kako deluje",
  „Za otroka / Za starše", „Kako ravnamo s podatki", „Kako do računa", noga;
  vgrajeni pogledi prijave, registracije, čakanja in zavrnitve. Slog in
  žetoni iz `POC-02`.
- **Kako preizkusiš:** odpri stran; ploščica „Predogled" spodaj levo preklaplja
  stran in temo. Zoži okno pod 860 px za telefon.
- **Tvoje pripombe:** „Od vseh funkcij mi največ pomaga sestavljanje testov z
  vmesnikom — naj bo tam poudarek."

### Krog 2 — 2026-10-10
- **Zgrajeno:** uvod o testu za tisk (list A4 in oblački klepeta); nov
  razdelek „Sestavi test v pogovoru" s prikazom urejevalnika (snov, klepet,
  list A4) in štirimi lastnostmi. Na pripombo še razdelek „Kvizi, ki jih
  otrok reši na telefonu" (sestavljanje, telefon s samooceno, statistika) in
  postavki Testi in Kvizi v meniju.
- **Kako preizkusiš:** kot krog 1.
- **Tvoje pripombe:** „Bi pa vseeno rad, da so tudi kvizi opazni." Po
  dopolnitvi: „Odlično, všeč mi je."

### Krog 3 — 2026-10-10 in 2026-10-11
- **Zgrajeno:** `registracija-predlog.html` — ločeno okno registracije s
  koraki Google → Zahtevek → Odobritev in vsemi stanji; predstavitvena stran
  vodi nanj, vgrajeni pogledi registracije so odstranjeni. 11. 10. usklajeno z
  `ADR-057` in `V6-R02`: polje „Ime družine", „Moj račun" za čakanje in
  zavrnitev, napaka „e-naslov z geslom", stanje „preveč zahtevkov"; noga
  predstavitvene strani ne omenja več Trgovine Play.
- **Kako preizkusiš:** odpri `registracija-predlog.html` ali klikni
  „Registracija" na predstavitveni strani; ploščica „Predogled" preklaplja
  stanja. Korak „Google" se po dveh sekundah sam vrne v „Zahtevek".
- **Tvoje pripombe:** sporočila skrbniku ne želi (odstranjeno); primera, ko
  oba starša naredita vsak svojo družino, zaenkrat ne rešujemo; polje „Ime
  družine" dodati v predlog, ne odstraniti iz `V6-R02`.

## Dogovorjeno

- Predstavitvena stran gre v implementacijo, kakor je na posnetkih 01
  (računalnik, temno, telefon). Vrstni red razdelkov: uvod (test za tisk) →
  „Sestavi test v pogovoru" → „Kvizi, ki jih otrok reši na telefonu" →
  „Kako deluje" → „Ena družina, dve orodji" → „Kako ravnamo s podatki" →
  „Kako do računa" → noga.
- **Poudarek:** testi prvi, kvizi drugi, vsak s svojim razdelkom in
  prikazom. V „Za starše" sta oba na vrhu in označena, v „Za otroka" kvizi.
- Glava: znak, meni (Testi, Kvizi, Kako deluje, Za otroka in starše,
  Zasebnost — sidra na isti strani), desno Prijava in Registracija.
- Registracija je **samo z Googlom**; okno, „Moj račun" in prva stran po
  odobritvi so po posnetkih 02–09.
- Zahtevek ima tri stvari: **ime družine**, **tvoje ime** (iz Googla,
  popravljivo) in **potrditveno polje soglasja**. Brez potrditve gumb
  „Oddaj zahtevek" ne deluje.
- **Sporočila skrbniku ni.**
- **Vsaka registracija ustvari svojo družino**; pridružitve drugega starša
  ni.
- Stran „čaka" izrecno pove, da e-pošte ne pošiljamo in da zahtevek ne
  poteče.
- Zavrnjen starš ima „Izbriši moj račun" z vmesno potrditvijo.
- Prva stran po odobritvi ponudi: Dodaj otroka, Namesti aplikacijo na
  otrokov telefon, Poslikaj urnik (neobvezno).
- Noga ne obljublja Trgovine Play.

## Ugotovitve

### Pot tega zapisa

POC je nastal v pogovoru 10. 10. 2026, brez veje `poc/03-…` in brez vnaprej
zapisanega vprašanja — korak 1 iz §1d je bil izpuščen. Vprašanje in „ok" sta
zato zapisana naknadno, iz predlogov in pripomb. Ker `v6.md` še ni v `main`,
gre zapis na `docs/v6-registracija` skupaj z `V6-R03`, ne na ločeno vejo
`docs/poc-03-…`.

### Predstavitvena stran po razdelkih

| Razdelek | Vsebina | Gradniki |
|---|---|---|
| Glava | znak, meni sider, Prijava (drugotni), Registracija (glavni); lepljiva, prosojno ozadje | gumbi iz `POC-02` |
| Uvod | „Test za tisk iz tega, kar se je otrok res učil." Opis poti zvezek → prepis → test in kviz; gumba „Registriraj se z Googlom" in „Kako nastane test"; oznaki „Testi za matematiko · Kvizi za vse predmete" | list A4, oblački klepeta, kartica „Snov: 3 slike" |
| Polica | vrsta hrbtov zvezkov v barvah predmetov | hrbet |
| Sestavi test v pogovoru | oznaka „Glavno orodje"; prikaz urejevalnika: vrstica (Razveljavi, Uveljavi, Natisni / PDF, Shrani), levo snov in klepet s predlogi, desno list A4 z označeno spremenjeno nalogo; štiri lastnosti | urejevalnik (prikaz), list A4, kartice lastnosti |
| Kvizi | oznaka „Ponavljanje"; sestavljanje (vprašanja po snovi, izbrana obkljukana, „Objavi kviz"), telefon (vprašanje, odgovor, štiri ocene), statistika (pas po predmetu, legenda, opomba „kje se zatika"); štiri lastnosti | izbor vprašanj, telefon, pas samoocene |
| Kako deluje | štirje koraki: Fotografiraj, Prepis, Test za tisk, Kviz na telefonu | oštevilčene kartice |
| Ena družina, dve orodji | Za otroka (Android): QR, fotografiranje brez čakanja, kvizi, zgodovina. Za starše: testi, kvizi, po dnevih, urnik, statistika, družina | seznam s kljukicami |
| Kako ravnamo s podatki | podatki so družinski; slike gredo v zunanji model (poudarjeno); nič se ne izgubi; dopolnjuje zvezek | kartice, ena v opozorilni barvi |
| Kako do računa | zelena plošča: gumba in trije koraki (Google → odobritev → dodaj otroka) | |
| Noga | znak, Zasebnost, Prijava, „Aplikacija za Android" | |

### Okno registracije

- **Postavitev:** levo plošča v barvi poudarka (znak, naslov „Kar se otrok
  uči, na enem mestu.", tri koristi — testi in kvizi poudarjena —, polica
  zvezkov spodaj); desno okno širine 30 rem s koraki na vrhu. Pod 960 px se
  leva plošča skrči na znak in polico.
- **Koraki:** krog s številko; tekoči obrobljen z mehkim obročem, opravljen
  ✓ v barvi poudarka, čaka „…" v opozorilni barvi, zavrnjen ✕ v barvi
  nevarnosti.

| Stanje | Posnetek | Kaj vidi starš |
|---|---|---|
| Začetek | 02 | „Nadaljuj z Googlom", okvir „Iz Google računa vzamemo" (ime, e-naslov, nič drugega), Prijava |
| Google | 03 | vrtavka „Odpiram Google …", Prekliči |
| Zahtevek | 04 | prijavljeni račun in „Drug račun", ime družine, tvoje ime, soglasje, „Oddaj zahtevek" (onemogočen do potrditve), „Zahtevek ne poteče" |
| E-naslov z geslom | 05 | začetek z napako: račun z geslom že obstaja → prijava z geslom, Google povežeš v nastavitvah (`ADR-057` A) |
| Preveč zahtevkov | 06 | zahtevek z opozorilom „Trenutno čaka preveč zahtevkov … čez nekaj dni"; oddaja zaprta (`ADR-057` F) |
| Moj račun — čaka | 07 | „Moj račun", ime, e-naslov, družina, časovnica, „E-pošte ne pošiljamo", Odjava |
| Odobreno | 08 | „Dobrodošla, Ana", trije naslednji koraki |
| Moj račun — zavrnjeno | 09 | časovnica z zavrnitvijo, „Izbriši moj račun" (kaj se izbriše, da se lahko registrira znova) |

### Gradniki, novi glede na POC-02

- **List A4 kot prikaz:** papir je bel tudi v temni temi; naloge s točkami,
  črte za računanje, spremenjena naloga v rumenem pasu. Ulomki so narisani s
  HTML (števec nad imenovalcem), brez KaTeX.
- **Oblaček klepeta:** starš v barvi poudarka desno, pomočnik na ploskvi
  levo.
- **Telefon:** temen okvir; zaslon ima stalne barve, neodvisne od teme strani
  (ocene so berljive v obeh temah).
- **Pas samoocene po predmetu:** štiri barve `o0`–`o3` iz statistike.
- **Koraki na vrhu okna, časovnica, okvir „kaj vzamemo", polje soglasja** v
  opozorilni barvi.

### Pasti

- **`BESEDILO_ZASEBNOST` v `app/sistem.py` ne drži več za javnost.** Napisano
  je za lastnika, ki odpira družino znancu („Preden odpreš družino, to povej
  staršu", „Aplikacija ni objavljena in ni namenjena širšemu krogu").
  `V6-R02` ga uporabi za soglasje, `V6-R03` za razdelek o podatkih — preden je
  karkoli od tega javno, ga je treba prepisati v drugo osebo za starša.
- **Prikazi so slike z izmišljenimi podatki**, ne žive komponente: ne kličejo
  strežnika in ne berejo podatkov nobene družine.
- **Trditve morajo držati na dan objave:** „Testi za matematiko"
  (`ADR-053`), „Kvizi za vse predmete", „Aplikacija za Android", QR prijava
  šele po `V6-R01`.
- **Pisava s CDN-ja** je v predlogu samo za predogled; implementacija jo
  streže sama (`ADR-056`).
- **„Moj račun"** je po `ADR-057` C stran pod `/admin`. Predlog jo kaže v
  postavitvi registracije, brez menija, ker neodobrena družina menija nima.
- **Lepljiva glava** s prosojnim ozadjem rabi `backdrop-filter`; brez njega
  ostane neprosojna — sprejemljivo.

## Sodba

**2026-10-11 — `Sprejeto`.** Lastnik je predstavitveno stran po drugem krogu
sprejel brez pripomb („Odlično, všeč mi je"), okno registracije pa po tretjem
z dvema poenostavitvama (brez sporočila skrbniku, vsaka registracija svoja
družina). Odločitev je zapisana v `ADR-059`; implementacija je nova zahteva
`V6-R03` (predstavitvena stran), okno registracije pa postane del podlage
`V6-R02`.
