# ADR-044: Izvedba odpiranja družin — stanje družine, meja lastnikovega pogleda, mirujoča obdelava

- **Datum:** 2026-09-20
- **Nastalo pri:** V3-R05 (fazi 1 in 2)
- **Status:** Sprejeto
- **Stoji na:** `ADR-025` (družina je lastnik, izolacija je lastnost kode,
  ločnica lastnik sistema / starš), `ADR-027` (poverilnica ni uporabnik),
  `ADR-035` (seje, CSRF, prvo geslo), `ADR-038` (pravila o članih družine,
  lastnik sistema je izjema), `ADR-009` (mirujoča obdelava brez ključa),
  `ADR-029` B (obhod obdelave gre po družinah)

## Kontekst

`ADR-025` je odločil, da je družina edini obseg lastništva, in da družino ter
prvega starša v njej odpre **lastnik sistema**. Zastavica `is_system_owner`
obstaja od `V3-R03`, bere pa jo doslej samo pravilo iz `ADR-038` G. Pogleda,
skozi katerega bi lastnik kaj odprl, ni; `families` ima ime in datum nastanka
in nič drugega.

Kriteriji `V3-R05` v `docs/verzije/v3.md` povedo, kaj mora stran znati. Ne
povedo pa šestih stvari, ki odločijo, kaj pride v kodo in kaj v shemo: kaj
deaktivirana družina sploh je, koliko lastnik o tuji družini vidi, kje stoji
besedilo o zunanjem vision API-ju, kaj se med deaktivacijo dogaja z obdelavo v
ozadju, kako daleč sme repozitorij brez družine in kdo starša vrne nazaj v
uporabo. Fazi 1 in 2 sta jih naslovili, dogovor je spodaj.

## Odločitve

### A — deaktivirana družina je zastavica na družini, ne prelivanje na člane

`families.is_active` je logična zastavica, po vzoru `users.is_active`
(`ADR-038` A). Prijava in vsaka uporaba seje jo preverita; **`users` se ne
dotaknemo**.

1. **Zastavica na družini** (izbrano). Za: ponovna aktivacija vrne družino
   natanko v stanje pred deaktivacijo — kdor je bil deaktiviran prej, ostane
   deaktiviran. Stanje je na enem mestu in tam, kjer je dejanje. Proti: vsaka
   pot do identitete mora zastavico prebrati; pozabljena preverba je tiho
   odprta vrata.
2. **Prelivanje na člane** (`users.is_active = false` za vse). Za: nobene nove
   preverbe v prijavi. Proti: podatek o tem, kdo je bil deaktiviran že prej, se
   nepovratno izgubi, zato aktivacija ne bi bila obrnljiva v pomenu, ki ga
   `ADR-038` A zahteva pri osebah. Deaktivacija družine bi bila s tem bolj
   uničujoča od deaktivacije osebe, kar je obrnjeno od pričakovanja.

Preverba stoji na **dveh** mestih, kot pri osebi: `prijava.preveri_prijavo`
(prijava se zavrne z istim besedilom kot vsaka druga neuspela prijava in ne
izda, da družina obstaja) in `prijava.seja_za_zeton` (obstoječa seja neha
veljati in se izbriše). Obe poizvedbi se na `families` že pridružujeta zaradi
imena družine, zato je to en stolpec več in ne nova poizvedba.

**Deaktivacija v isti transakciji izbriše seje vseh članov družine**, enako kot
pri osebi (`ADR-038` A in D); lena preverba ob uporabi seje ostane kot druga
plast. Aktivacija sej ne vrne — izbrisana vrstica se ne vrne.

**Podatki ostanejo nedotaknjeni.** Snov, vprašanja, kvizi, poskusi, urniki in
slike na disku se ne premaknejo in ne spremenijo. „Nič se ne briše, vse se
upokoji" (`docs/00-namen.md`) velja tudi za družine.

### B — lastnik vidi družine in starše, otroke samo kot število

Seznam družin pokaže ime, število staršev, število otrok, datum nastanka in
stanje. Stran ene družine pokaže **starše poimensko** (prikazno ime, e-naslov,
stanje), ker jim lastnik ponastavlja geslo in jih deaktivira, in otroke
**samo kot število**.

1. **Samo starši poimensko** (izbrano). Za: kriterij 4 pravi, da lastnik vidi
   imena, števila, datum in stanje; otrok je stvar svojega starša (`V3-R06`) in
   lastnik nad njim nima nobenega dejanja. Proti: lastnik, ki bi otroku moral
   pomagati, tega ne more brez starša — kar je pravilno, a ne vedno udobno.
2. **Vsi člani poimensko.** Za: ena stran za vse. Proti: lastniku da imena in
   prijavna imena tujih otrok, ne da bi imel z njimi kaj početi. To je natanko
   meja, ki jo kriterij 4 postavlja in ki jo zahteva sama opisuje kot izbiro:
   „da je dostop tehnično mogoč, ne pomeni, da ga da vmesnik".

**Vsebine ni nikjer.** Ne slik, ne prepisov, ne povzetkov, ne vprašanj, ne
kvizov, ne statistike, ne urnikov. To ni stvar dobre volje izrisa: pod
`/admin/system` ni nobene poti, ki bi jih brala, in test to pribije s sledmi
tuje družine iz `tests/test_tesnjenje.py`.

### C — besedilo o zunanjem vision API-ju stoji ob obrazcu za novo družino

`ADR-025` zahteva, da je zasebnostna cena povedana **izrecno** vsakemu staršu,
ki se pridruži, in da je to dogovor med znanci in ne pravni dokument.

Besedilo je konstanta v `app/sistem.py` in se izriše na `/admin/system`, tik ob
obrazcu za novo družino — torej na mestu in v trenutku, ko ga lastnik
potrebuje. Ni datoteke v `docs/`, ki bi jo bilo treba iskati, in **ni obrazca
soglasja**: potrditev ob prvi prijavi bi bila pravni okvir, ki ga `ADR-025`
izrecno ne želi.

Da je konstanta v modulu in ne prosto besedilo v predlogi, ima en razlog:
kriterij 7 zahteva, da besedilo obstaja, in test to trdi o konstanti, ne o
zapisu HTML.

### D — obdelava ugasnjene družine miruje

`app/obdelava.py` gre po `DruzineRepository.idji()` čez vse družine. Brez te
odločitve bi slike ugasnjene družine, ki so ostale v stanju `new`, vseeno
odšle v OpenAI in bile plačane — za družino, ki je izklopljena in v katero
nihče ne more.

1. **Obhod preskoči ugasnjene družine** (izbrano). Slike ostanejo `new` in se
   obdelajo, ko je družina spet prižgana. To je natanko vzorec mirujočega
   workerja iz `ADR-009` B2: odsotnost pogoja za delo ni napaka in ne sme
   proizvesti dela ne `failed` zapisov.
2. **Pusti, kot je.** Za: prižgana družina je takoj popolna. Proti: zunanji
   klic in njegova cena za nekoga, ki je izklopljen — in „deaktivirano" bi
   pomenilo samo „nihče se ne more prijaviti".

**`obnovi_obticale` ostane čez vse družine**, tudi ugasnjene. Ta ne kliče
ničesar zunanjega in ne stane nič; vrstica, ki bi ostala `processing` za vedno,
pa bi se po ponovni aktivaciji vlekla naprej kot tiha izguba. Zato ima
`DruzineRepository` dve metodi in ne ene s tiho spremenjenim pomenom:
`idji()` (vse) in `idji_aktivnih()` (za obhod obdelave).

### E — kam sme repozitorij brez družine

`ADR-025` pravi, da repozitorij ne sme znati brati brez družine. Lastnikov
pogled je po naravi čez družine, zato ta ADR mejo zapiše, namesto da bi jo
vsaka poizvedba znova presojala:

- Čez družine se bere **izključno `families` in `users`** — ime družine, datum,
  stanje in števila članov. Nikoli `materials`, `questions`, `quizzes`,
  `quiz_items`, `question_attempts`, `schedules` ali `schedule_entries`.
- To počne **obstoječi `DruzineRepository`** (že danes edini repozitorij brez
  družine poleg `PrijavaRepository`, `ADR-029` B) in ne nova vrsta
  repozitorija. Četrta vrsta bi pomenila četrto mesto, kjer je treba vedeti,
  kaj sme.
- **Vsako dejanje nad članom teče skozi `ClaniRepository(seja, ciljna_druzina)`**
  — torej skozi repozitorij, ki ima družino v konstruktorju, kot zahteva
  `ADR-025`. Ciljna družina pride iz naslova in je preverjena, da obstaja.
  Pravila `app/clani.py` veljajo nespremenjena: prav zato je `ADR-038` pravilo
  o zadnjem aktivnem staršu obdržal.

Cena te meje je, da nove metode pristanejo v edinem razredu, ki ga varovalo
`test_vsaka_javna_metoda_repozitorija_ima_primer` **ne** gleda — ta našteva
pet repozitorijev z družino. Zato dobi `DruzineRepository` svoje varovalo:
zapisan seznam javnih metod (nova metoda tam podre zbirko in terja odločitev o
tej meji) in test, ki nad stranmi lastnika trdi, da v njih ni nobene sledi
vsebine tuje družine.

### F — starša vrne v uporabo lastnik, in to ni širitev obsega

Kriterij 3 pove ponastavitev gesla in deaktivacijo. Aktivacije ne pove, a brez
nje ima družina z enim staršem stanje, iz katerega ni izhoda: deaktiviranega
starša po `V3-R06` aktivira drug starš njegove družine, in če drugega ni, ga ne
more nihče. Deaktivacija bi bila s tem nepovratna, kar `ADR-038` A izrecno
zavrača.

Aktivacija je torej **posledica že sprejete odločitve**, ne novo vedenje, in
zato sodi v to zahtevo, ne v novo (`CLAUDE.md` §9b, preizkus uvrstitve).

### G — „za starša ne obstaja" je odvisnost usmerjevalnika, ne `if` v vsaki poti

> **Zoženo z `ADR-045`.** Skrivanje velja za odgovore aplikacije: vsaka pot pod
> predpono vrne `404` na vsako metodo, z enakim telesom in brez glave `Allow`.
> **Ne** velja za usmerjanje okvirja (preusmeritev ob končni poševnici) in ne
> za shemo poti (`/openapi.json`). Kako smo do te meje prišli — po treh
> popravkih istega mesta — je zapisano tam.

Kriterij 1 zahteva `404` in ne `403`. Zavrnitev stoji kot odvisnost na
`APIRouter`, zato velja za **vsako** pot tega usmerjevalnika, tudi za tisto, ki
bo dodana jutri; dvigne `HTTPException(404)`, ki jo `admin.prestrezi_napako`
izriše kot navadno stran „Te strani na strežniku ni." — enako, kot izgleda
resnično neobstoječa pot.

`if` v vsakem endpointu bi bil pravilo, ki ga je mogoče pozabiti, in pozabljen
bi tiho odprl pogled čez vse družine. Isto sklepanje kot pri `SejaMiddleware`
(`ADR-035` A): koda, ki napake ne dopusti, je boljša od testa, ki jo prijavi.
Zraven vseeno pride test, ki se **generira iz seznama poti** aplikacije, kot
test dosegljivosti iz `V3-R03`.

### H — obnovitev kopije nad bazo z več družinami je sprejemni korak

Kriterij 6 zahteva, da je obnovitev varnostne kopije preverjena znova nad bazo
z več družinami. Tega ni mogoče narediti v tej seji in ne pred mergem: skripta
teče nad živim Dockerjem, druga družina v produkcijski bazi pa nastane šele,
ko lastnik to zahtevo uporabi.

Zato: lastnik v fazi 9b odpre preizkusno družino, požene
`varnostna-kopija\obnova.ps1` in jo nato deaktivira. Kriterij ostane pogoj pred
**prvo tujo** družino, ne pogoj za merge. Zapis izida gre v
`docs/01-arhitektura.md`, razdelek „Varnostna kopija", kot pri preizkusu
15. 9. 2026.

## Posledice

- **Kaj to olajša:** `V3-R08` (Google prijava) dobi lastnikov pogled, ki ga ne
  bo treba odpirati; večdružinskost neha biti stvar sheme in testov in postane
  stanje, v katerem se koda dejansko uporablja.
- **Kaj to oteži:**
  - `app/prijava.py` in obe poizvedbi identitete se dotaknejo zaradi A, čeprav
    sta iz `V3-R03` — prijava dobi nov razlog za zavrnitev. Enako kot pri
    normalizaciji v `ADR-038` E: pravilo mora veljati za obe vrati, zato sedi v
    `preveri_prijavo` in `seja_za_zeton` in ne v usmerjevalnikih.
  - Dvanajst novih poti mora dobiti vnos v `PRIMERI_POTI`
    (`tests/test_tesnjenje.py`); za navadnega starša je vsaka od njih `404` in
    prav to je dokaz tesnjenja.
  - Zastavico družine je odslej treba prebrati povsod, kjer se odloča o
    identiteti. Pozabljeno mesto je tiho odprta vrata, zato sta obe mesti
    pokriti s testom in ne le z branjem.
- **Zavestno izpuščeno:** brisanje družine (ostane deaktivacija), premik
  uporabnika med družinami, preimenovanje družine, pogled lastnika v vsebino
  tuje družine (B), soglasje starša ob prvi prijavi (C), seznam prijavljenih
  naprav (`ADR-038` H velja naprej). Vse to so nove zahteve, če bodo.
