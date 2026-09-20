# ADR-038: Izvedba upravljanja uporabnikov v V3-R06

- **Datum:** 2026-09-19
- **Nastalo pri:** V3-R06 (fazi 1 in 2)
- **Status:** Sprejeto
- **Stoji na:** `ADR-025` (družina je lastnik, izolacija je lastnost kode),
  `ADR-027` (poverilnica ni uporabnik), `ADR-035` (seje, CSRF, prvo geslo),
  `ADR-024` (skripta na admin strani je izjema)
- **Dopolnjuje:** `ADR-035` G — geslo ne pride več samo z ukazom; glej C.

## Kontekst

`ADR-027` in `ADR-035` sta postavila tabele `users`, `credentials` in
`sessions` ter prijavo nad njimi. Nihče pa doslej ni mogel ustvariti računa:
uporabnika sta nastala v migraciji `0008_uporabniki`, geslo jima je vpisal
lastnik z ukazom v vsebniku. `V3-R06` to prenese v vmesnik — starš odslej
odpre račun svojemu otroku, doda drugega starša, ponastavi geslo in člana
deaktivira.

Kriteriji zahteve so v `docs/verzije/v3.md`. Ne povedo pa petih stvari, ki
spremenijo, kaj pride v kodo: ali je deaktivacija obrnljiva, ali se člane da
urejati, kaj pomeni „vmesna potrditev" pri dodajanju, kaj se zgodi, ko starš
ponastavi geslo sebi, in ali je lastnik sistema izjema. Vse to je faza 1
naslovila, dogovor pa je spodaj.

## Odločitve

### A — deaktivacija je obrnljiva

Deaktiviran član dobi na seznamu dejanje **„Aktiviraj znova"**, z isto vmesno
potrditvijo kot deaktivacija. `is_active` je logična zastavica in ne `retired_at`
po vzoru `ADR-011` in `ADR-015`: pri vprašanju je upokojitev dokončna, ker
vprašanje nosi statistiko in ga nadomesti novo, oseba pa se lahko vrne.
„Deaktiviran za vedno" bi pomenil, da otrok, ki se vrne, potrebuje **nov** račun
— in s tem novo identiteto, ločeno od svojih dosedanjih poskusov.

Aktivacija sej **ne obnovi**. Seje so ob deaktivaciji izbrisane in izbrisana
vrstica se ne vrne; član se prijavi znova.

### B — urejanja člana ni

Prikazno ime, e-naslov in uporabniško ime se po nastanku ne spreminjajo.
Kriterij 6 besedo „urejati" uporabi kot mejo za dejanja, ki obstajajo, in ne
kot zahtevo, da urejanje nastane. Sprememba identifikatorja je sprememba
poverilnice, s katero se človek prijavlja, in trči ob enoličnost iz E; če bo
kdaj potrebna, je nova zahteva in ne dodatek k tej.

### C — začetno geslo se vpiše v obrazec

`ADR-035` G je geslo v argumentu ukaza in v spremenljivki okolja zavrnil, ker
oboje **ostane zapisano**: argument v zgodovini lupine in v `docker inspect`,
okolje v `.env`. Telo zahteve `POST` čez HTTPS (`ADR-026`) ne ostane nikjer —
ne v dnevniku strežnika, ker ga ta ne izpisuje, ne v naslovu, ker je obrazec
`POST` in ne `GET`. Prepoved iz `ADR-035` G zato velja naprej za ukaz in se na
obrazec ne razteza.

Najmanjša dolžina ostane ista in na istem mestu (`prijava.NAJKRAJSE_GESLO`):
starš 12, otrok 8 (`ADR-036` E). Prisilne menjave gesla ob prvi prijavi ni —
krog uporabnikov so znanci (`ADR-025`).

**Ukaz `nastavi-geslo` ostane.** Z njim lastnik postavi prvo geslo staršu, ki
ga je ustvarila migracija — brez njega bi bila namestitev brez poti v `/admin`.
Odslej pa **tudi ukaz prekliče seje**, enako kot stran: dve poti do istega
dejanja z različnim pomenom bi bili past, in `app/ukazi.py` je preklic že
obljubljal („preklic sej pride z V3-R06").

### D — ponastavitev gesla velja brez izjeme, tudi zase

Starš sme ponastaviti geslo tudi sebi, in pravilo „ponastavitev prekliče vse
seje tega uporabnika" takrat velja **tudi za sejo, v kateri ravno kliče**.
Stran ga zato pelje na prijavo.

Izjema („vse seje razen te") bi bila drugo pravilo, ki bi se moralo držati
vseh poti — tudi ukaza iz C, kjer seje, v kateri se kliče, sploh ni. Starega
gesla pri tem ne vpisuje: kdor ima sejo, ima dostop do vsega, kar seja odpira,
in vpis starega gesla bi bil obred brez učinka.

### E — enoličnost uveljavi baza, identifikator se normalizira

**Enoličnost.** `credentials.identifier` je `UNIQUE` čez celo namestitev.
Repozitorij te zahteve pa je vezan na družino (`ADR-025`) in **ne sme**
poizvedovati čezenj, zato zasedenosti imena ne preverja s poizvedbo: vrstica
se poskusi vstaviti in `IntegrityError` se prevede v slovensko sporočilo.
To ni samo skladnost z `ADR-025` — poizvedba pred vstavljanjem je tekma, ki jo
baza tako ali tako razsodi.

**Sporočilo ne izda tuje družine:** „To ime je že zasedeno. Izberi drugo."
Kriterij 2 zahteva jasnost, kriterij 6 pa pravi, da obstoj tujega uporabnika ni
podatek za starša. Nekaj informacije je pri globalni enoličnosti neizogibno;
besedilo brez „pri kom" in brez razlike med e-naslovom in uporabniškim imenom
je najmanjši možen izid.

**Normalizacija.** Identifikator se ob nastanku **in ob prijavi** poravna na
male črke in obrezane robove. Brez tega enoličnost ne drži v pomenu, ki ga
zahteva kriterij: `Ana@primer.si` in `ana@primer.si` bi bila dva računa, kar je
natanko dvoumnost, ki naj bi jo enoličnost preprečila. Ker se normalizira ob
nastanku, se mora tudi ob prijavi, sicer se starš ne more prijaviti z zapisom,
kakršnega je vtipkal. Stranski učinek je dobrodošel: omejevanje ugibanja
(`ADR-035` E) šteje po normaliziranem identifikatorju, zato se mu z menjavo
velikih črk ni več mogoče izogniti.

Obstoječa identifikatorja (`dejan.ambrus@gmail.com`, `masa`) sta že taka, zato
migracije ni.

### F — vmesna potrditev je za posledice, ne za vnos

Kriterij pravi „vse akcije so `POST` s CSRF žetonom in vmesno potrditvijo".
Vmesno stran dobijo **ponastavitev gesla, deaktivacija in aktivacija**; ta
stran je hkrati tista, na kateri se novo geslo vpiše.

**Dodajanje člana vmesne strani nima.** Imela bi jo lahko samo tako, da bi
začetno geslo potovalo skozi skrito polje druge strani — geslo bi se s tem
zapisalo v HTML in v zgodovino brskalnika, kar je natanko to, čemur se izogiba
C. Oddani obrazec z imenom, identifikatorjem in geslom je sam po sebi
premišljeno dejanje; podvojitev bi kupila obred in plačala z izpostavljenim
geslom.

### G — lastnik sistema je izjema

Računa z `is_system_owner` **ni mogoče deaktivirati**, geslo pa mu sme
ponastaviti samo on sam. Brez tega bi drugi starš v isti družini lahko izklopil
lastnika sistema iz njegovega lastnega strežnika in s tem `V3-R05` (odpiranje
družin), ki na tej zastavici stoji.

To ni zaščita pred zlonamernostjo — stroj je lastnikov in dostop do baze ima —
ampak pred zmoto: dejanje, ki ga vmesnik ponuja, mora biti dejanje, ki ga je
mogoče preživeti.

### H — seznama prijavljenih naprav ni

`models.py` pri `sessions.device_label` piše, da stolpec obstaja, „da je seznam
sej v `V3-R06` berljiv". Kriteriji zahteve seznama naprav ne omenjajo, zato ga
ta zahteva **ne naredi**. Opomba v modelu se popravi, da ne obljublja česa,
česar ni — obljuba v komentarju je past za naslednjega bralca.

Stolpec ostane: pisan je ob vsaki prijavi in bo seznam, ko in če bo, nosil.

## Posledice

- **Kaj to olajša:** `V3-R05` podeduje repozitorij z obvezno družino, pravila
  o zadnjem staršu in vzorec potrditvenih strani; lastniku sistema ostane
  dodati samo pogled čez družine. `V3-R07` dobi več otrok v družini kot
  resnično stanje in ne le kot možnost v shemi.
- **Kaj to oteži:**
  - `app/prijava.py` in `app/ukazi.py` se dotakneta zaradi E in C, čeprav sta
    iz `V3-R03`. Normalizacija ob prijavi je sprememba obnašanja poti, ki je ta
    zahteva sicer ne bi odpirala. Sedi v `preveri_prijavo` in `koliko_cakati`
    in ne v `app/routers/vstop.py`, kot je predvideval plan: pravilo mora
    veljati za obe vrati in za vsak zapis v `login_attempts`, pravilo, ki bi ga
    moral ponoviti vsak klicatelj, pa bo kdo kdaj pozabil.
  - Nove poti morajo dobiti vnos v `tests/test_tesnjenje.py` (`PRIMERI_POTI`)
    in nov repozitorij v `PRIMERI_REPOZITORIJEV`; brez tega zbirka pade. Tako
    je varovalo mišljeno in to je cena, ki jo `ADR-025` zavestno plačuje.
  - Družina z enim samim staršem ima mesto, ki ga ni mogoče zapustiti: tega
    starša ni mogoče deaktivirati, dokler v družini ni drugega.
- **Zavestno izpuščeno:** urejanje članov (B), seznam naprav (H), obnovitev
  gesla po e-pošti (`ADR-027`, ni SMTP), premik člana v drugo družino in
  sprememba vloge. Vse to so nove zahteve, če bodo.

## Popravki po prvem pregledu (19. 9. 2026)

Pregledovalec je našel, da kriterij „zadnjega starša v družini ni mogoče
deaktivirati" nima testa, ki bi padel ob pokvarjeni izvedbi. Ob popravku se je
pokazalo več od manjkajočega testa, zato to zapisujemo sem in ne samo v kodo.

**Pravilo o zadnjem staršu po nobeni od devetih poti ni dosegljivo.** Klicatelj
je vedno **aktiven starš te družine** — sejo ima samo tak, ker jo
`prijava.seja_za_zeton` neaktivnemu izbriše in `vloga_sodi` otroka ne spusti.
Zato velja: če je cilj tuj **aktiven** starš, sta aktivna vsaj dva in pravilo
ne ugrizne; če je cilj on sam, prej ugrizne pravilo „sebe ne". Kriterij danes
drži **po zaslugi pravila „sebe ne"**, ne po zaslugi štetja staršev.

Pravilo kljub temu **ostane**. `V3-R05` pripelje klicatelja zunaj družine
(lastnik sistema deaktivira starša tuje družine) in takrat je to edino pravilo,
ki družino obvaruje pred tem, da ostane brez nekoga, ki jo ureja. Odstraniti ga
zdaj bi pomenilo, da ga bo treba takrat napisati na novo — in napisati na novo
bi pomenilo tudi **ugotoviti na novo**, da je potreben.

Ker čez HTTP dokaza ni, je priklop pribit tam, kjer bo pravilo dejansko
uporabljeno: test kliče `routers.clani._zavrnitev_deaktivacije` s klicateljem
zunaj družine in pade, če se `aktivnih_starsev` zamenja s konstanto. Zraven
stoji test, da `ClaniRepository.aktivnih_starsev` šteje pravo reč (ne otrok, ne
deaktiviranih, ne tuje družine).

Iz istega pregleda še troje, manjšega:

- **Najkrajše geslo je v obrazcu izpisano iz `prijava.NAJKRAJSE_GESLO`**, ne
  vtipkano v predlogo. Vtipkana bi se z zavrnitvijo razšla in nalepka bi lagala,
  ne da bi kak test padel.
- **Stran za ponastavitev gesla pove mejo, preden je geslo vtipkano** dvakrat.
- **`IntegrityError` se v „to ime je že zasedeno" prevede samo takrat, kadar je
  kršitev res enoličnost identifikatorja** (`db.je_zaseden_identifikator`).
  Prej bi vsaka kršitev integritete — na Postgresu tudi tuji ključ na družino —
  poslala uporabnico iskat drugo ime, ki ni bilo težava.

## Popravki po drugem pregledu (19. 9. 2026)

**Vrstni red pravil v `zakaj_ne_sme_deaktivirati` je zamenjan**: najprej
lastnik sistema, nato zadnji aktivni starš, šele nato „sebe ne".

Vsa tri pravila vodijo v isti `403` in se razlikujejo samo po tem, kaj povedo,
naj uporabnica naredi. Dokler je bilo „sebe ne" prvo, je starš, ki je v družini
sam, dobil *„naj to naredi drugi starš v družini"* — nasvet, ki mu ni mogel
slediti, ker drugega starša ni. **Enostarševska družina ni robni primer**: tako
izgleda vsaka nova družina, po migraciji `0008` in po `V3-R05`. Merilo
dokončanosti (`CLAUDE.md` §1b) zahteva, da sporočilo pove, kaj naj uporabnica
naredi; *„najprej dodaj drugega starša, potem tega"* to pove.

To je **napaka po fazi 9b in ne sprememba zahteve**: pripomba se preslika
nazaj na zapisano merilo dokončanosti, ne na novo vedenje. Noben kriterij ne
pove, katero od treh pravil naj ob dveh hkratnih zadetkih zmaga.

Zamenjava razveljavi ugotovitev prvega kroga, da pravilo o zadnjem staršu čez
HTTP ni dosegljivo: odkar je pred „sebe ne", ga edini starš v družini doseže,
ko poskusi deaktivirati sebe. Test nad privatno `routers.clani._zavrnitev_deaktivacije`
je zato **odpadel** in ga je nadomestil navaden test čez pot; priklop na pravo
število je pribit tam. Utemeljitev, da pravilo ostane zaradi `V3-R05`, s tem
ni več edina — pravilo zdaj tudi dela.
