# ADR-062: Izvedba registracije in odobritve — poti, vezivo obrazca, zapora, prehodi stanja

- **Datum:** 2026-10-12
- **Nastalo pri:** V6-R02 (fazi 1 in 2)
- **Status:** Sprejeto
- **Stoji na:** `ADR-057` (samoregistracija z Googlom in odobritev), `ADR-046`
  (Google prijava, vezivo stanja), `ADR-044` in `ADR-045` (lastnikov pogled in
  njegova meja), `ADR-038` (vmesne potrditve, pravila o članih), `ADR-035`
  (seja, dvojno oddan CSRF žeton), `ADR-024` (skripta je izjema)
- **Spreminja:** kriterij `V6-R02` o posnetkih (`02–09` → `02, 04–09`, glej A);
  `ADR-046` F v delu „`/admin/racun` brez Googla je 404" (glej J);
  **`ADR-057` F** in kriterij `V6-R02` v delu „omejevanje po IP" — nadomešča ju
  dnevna meja za celo namestitev (glej F).

## Kontekst

`ADR-057` pove, **kaj** se zgodi: starš se registrira z Googlom, družina čaka,
lastnik odloči. Ne pove pa stvari, ki odločijo, kaj pride v kodo in v shemo:
kje stojijo poti, kako Googlova istovetnost preživi od povratnega klica do
oddanega obrazca, ne da bi povratni klic kaj ustvaril, kako je zapora
izvedena čez devet usmerjevalnikov, kateri prehodi stanja obstajajo in kaj je
s posnetki, ki jih brez skripte ni mogoče narediti. Faza 1 je to naslovila;
lastnik je predloge potrdil 12. 10. 2026.

## Odločitve

### A — posnetek 03 odpade

„Odpiram Google …" z vrtavko in gumbom „Prekliči" je bil v predlogu
simulirano stanje. Gumb je `POST`, ki s `303` pelje naravnost h Googlu;
vmesna stran bi terjala skripto na javni strani (`ADR-024`). Kriterij se glasi
„posnetki 02 in 04–09".

### B — povezav na `/` in na pravila zasebnosti do `V6-R03` ni

„← Domača stran", „Na domačo stran" in „pravila zasebnosti" kažejo na
predstavitveno stran, ki nastane z `V6-R03`. Do takrat jih ni; doda jih
`V6-R03`. Soglasje zato pokaže **celotno besedilo** v razširljivem bloku
(`<details>`) tik ob potrditvenem polju.

### C — dve besedili o zunanji storitvi, obe v `app/sistem.py`

- `BESEDILO_ZASEBNOST_JAVNO` — novo, v drugi osebi za starša; vir za soglasje
  in (z `V6-R03`) za razdelek „Kako ravnamo s podatki":

  > Slike zvezkov, ki jih otrok posname v aplikaciji, se prenesejo na naš
  > strežnik, od tam pa v zunanjo storitev (OpenAI), ki jih prepiše in iz njih
  > sestavi vprašanja. Brez tega aplikacija ne deluje. Kar nastane iz slik —
  > prepisi, vprašanja, kvizi, testi in odgovori — ostane na strežniku in ga
  > vidi samo tvoja družina.

- `BESEDILO_ZASEBNOST` — obstoječe, za lastnika ob ročnem obrazcu
  (`ADR-044` C velja naprej). Odpade samo stavek „Aplikacija ni objavljena in
  ni namenjena širšemu krogu", ki ne drži več.

### D — besedila ne ugibajo spola

Posnetki imajo „Prijavljena z Googlom" in „Dobrodošla, Ana". Spola ne poznamo,
zato: „Prijava z Googlom" nad e-naslovom in „Pozdravljeni, Ana". Ostalo
besedilo je po posnetkih, vključno z besedo **„skrbnik sistema"** (kriterij
pravi „administrator"; gre za isto osebo, lastnika sistema).

### E — prva stran po odobritvi je `/admin`, dokler družina nima otroka

Brez novega stolpca: `GET /admin` za družino brez otrok izriše posnetek 08
(„Pozdravljeni, …", trije koraki). Ko je dodan prvi otrok, je `/admin`
običajen pregled. Vidi jo tudi ročno odprta družina brez otrok.

Dve izjemi, dodani po prvem pregledu (12. 10. 2026):

- **Lastnik sistema te strani ne dobi.** Je brez menija, on pa prav v meniju
  vidi „Sistem" in število zahtevkov, ki čakajo nanj.
- **Koraki „Google, Zahtevek, Odobritev" in oznaka „Odobreno" se izrišejo samo
  staršu, ki se je registriral z Googlom** (brez geselne poverilnice, z Google
  poverilnico). Družini, ki jo je odprl lastnik, bi pripovedovali o poti, ki
  je ni prehodila; ta dobi iste tri korake naprej in stavek „Družina … še
  nima otroka". Ime družine je na strani v obeh oblikah, ker stran nima
  menija, ki ga sicer pove.

Stran je v postavitvi registracije, brez menija, kot na posnetku — zato dobi
gumb **„Odjava"** (kot 07 in 09), ki ga posnetek 08 nima; stran brez menija in
brez odjave bi bila slepa ulica.

> **Delno razveljavljeno z `ADR-064` (13. 10. 2026):** stran je odslej v
> običajni postavitvi z menijem, brez gumba „Odjava", korakov in oznake
> „Odobreno" — za vse družine enaka. Pravilo „brez otroka", izjema za
> lastnika sistema in povezave korakov veljajo naprej.

Koraki: „Dodaj otroka" → `/admin/family?dodaj=otrok`; „Poslikaj urnik" →
`/admin/schedule`; „Namesti aplikacijo na otrokov telefon" → naslov iz nove,
neobvezne nastavitve okolja `APK_URL`. Brez nje se ta vrstica izriše brez
povezave in pove, naj starš povezavo dobi od skrbnika.

### F — meji javnega obrazca

- **Največ 20 družin v stanju `pending`.** Zavrnjene ne štejejo. Meja se
  preveri ob izrisu obrazca (posnetek 06) in znova ob oddaji.
- **Največ 10 oddanih registracij v 24 urah za celo namestitev.** Vsaka
  uspešno oddana registracija zapiše vrstico v `login_attempts` z oznako
  `REGISTRACIJA` (velike črke, kot `POVEZAVA-TELEFONA`); šteje se po oznaki.
  Naslov se zapiše za pogled nazaj, **ne za odločitev**.

  **Meje po IP ni** — popravljeno 12. 10. 2026, pred prvo vrstico kode, s
  soglasjem lastnika. `ADR-057` F in prvotni kriterij sta jo zahtevala, prva
  različica te odločitve in plan (`docs/plan/V6-R02.md`, „3 registracije na IP
  v 24 h") pa sta jo prevzela. V tej postavitvi je ni mogoče narediti: Docker
  Desktop izvornega naslova ne ohrani in vsi odjemalci pridejo z naslova
  prehoda (`ADR-034` A, `docs/02-izkusnje.md`). Meja po IP bi bila v resnici
  skupna meja 3 na dan. Ta odločitev v tem delu **preglasi `ADR-057` F** in
  vrstice plana o meji po IP; kriterij v `docs/verzije/v6.md` je popravljen.
  Vsaka registracija že zahteva svoj potrjen Google račun, zato je glavna
  zavora meja čakajočih; dnevna meja omeji rast zavrnjenih vrstic.
- Obe dasta isto besedilo („poskusi pozneje"); katera je ugriznila, obrazec
  ne pove.
- Štetje in vstavljanje nista ena transakcija: ob sočasnih oddajah je meja
  lahko presežena za nekaj vrstic. Sprejeto — meja je zavora, ne pogodba.

### G — istovetnost med povratnim klicem in obrazcem nosi podpisan piškotek

„Povratni klic sam ne ustvari ničesar" (`ADR-057` A), `sub` pa mora do
oddanega obrazca priti **neponarejen** — sicer bi si kdo registriral tuj
Google račun in lastnik tega računa bi se pozneje „prijavil" v napadalčevo
družino.

1. **Podpisan piškotek** (izbrano). `registracija`: `sub`, e-naslov, ime in
   rok (10 minut), podpisano s HMAC-SHA256; `HttpOnly`, `Secure`,
   `SameSite=Lax`. Ključ je `secrets.token_bytes(32)`, ustvarjen ob zagonu
   strežnika in shranjen v `app.state`. Za: brez nove nastavitve, brez vrstice
   v bazi. Proti: ponovni zagon strežnika prekine registracije, ki so ravno
   med Googlom in oddajo — starš klikne „Nadaljuj z Googlom" znova.
2. **Vrstica v pomožni tabeli.** Preživi ponovni zagon, a povratni klic potem
   nekaj zapiše, in tabelo je treba čistiti.

Piškotek se pobriše ob uspešni oddaji in ob vsakem novem začetku toka.
Strežnik teče kot **en proces** (`Dockerfile`); z več delavci bi ključ moral
v nastavitve.

### H — dva vstopa, en izid

Prijavna stran obdrži „Prijava z Google računom" in dobi povezavo
„Registracija z Google računom" na okno registracije. Oba začetka gresta skozi
isti `POST /auth/google/login` in isti povratni klic; izid odloči `sub`:

| `sub` | Izid |
|---|---|
| znan, račun in družina aktivna | prijava (tudi če je tok začelo okno registracije) |
| znan, račun deaktiviran ali družina ugasnjena | zavrnitev kot danes |
| neznan, e-naslov nepotrjen ali ga ni | zavrnitev s pojasnilom |
| neznan, e-naslov ima geselno poverilnico | zavrnitev: prijavi se z geslom, Google poveži v nastavitvah (posnetek 05) |
| neznan | piškotek iz G in obrazec (posnetek 04) |

`google.Namen` dobi tretjo vrednost `REGISTRACIJA`; ta **ne** spremeni izida,
samo pove, na kateri strani se pokaže napaka (okno registracije namesto
prijavne strani).

Posledica: neznan Google račun ne dobi več iste oznake kot deaktiviran. Kdor
ima Google račun, s tem izve, ali je v tej namestitvi že vpisan — o **svojem**
računu. Sprejeto; `V3-R08` kriterij 3 je `ADR-057` v tem delu že razveljavil.

### I — okno registracije je `/admin/register`, izvzeto iz seje

| Pot | Metoda | Kaj |
|---|---|---|
| `/admin/register` | GET | okno: začetek (02) ali, s veljavnim piškotkom iz G, obrazec (04, 06) |
| `/admin/register` | POST | oddaja obrazca: družina `pending`, starš, poverilnica `google`, seja |

Pod `/admin` in ne zunaj njega: `IZVZETE_POTI` in `IZVZETE_PREDPONE`
(`ZetonMiddleware`) ostaneta nedotaknjeni, `POTI_BREZ_SEJE` pa zraste za eno
točno pot — poleg prijavne strani, ki ji je ta po naravi enaka. Plast za to
pot seje in CSRF ne preverja, zato `POST` žeton preveri **sam**, z istim
dvojno oddanim piškotkom `csrf_prijava` kot prijava (`ADR-035` D).

„Drug račun" je isti obrazec kot „Nadaljuj z Googlom" (`prompt=select_account`
je že nastavljen), ne nova pot.

### J — zapora je odvisnost, pripeta ob priklopu vsakega usmerjevalnika

`SejaUporabnika` dobi `family_status`. Odvisnost `zahtevaj_odobreno_druzino`
za sejo družine, ki ni `approved`, dvigne izjemo, ki jo prestreznik prevede v
`303` na `/admin/racun`. Pripne se v `main.py` ob `include_router` vsakemu
usmerjevalniku pod `/admin` z enega seznama — usmerjevalnik, dodan jutri mimo
seznama, ujame test, generiran iz seznama poti.

Odprte ostanejo natanko: `GET /admin/racun`, `GET` in `POST
/admin/racun/izbrisi`, `POST /admin/logout`, `/admin/login` in
`/admin/register`. Googlovi dejanji pod `/admin/racun` sta zaprti.

**„Moj račun" je obstoječi `/admin/racun`.** Za neodobreno družino izriše
posnetka 07 in 09 (postavitev registracije, brez menija), za odobreno ostane,
kot je. Za neodobreno družino se izriše **tudi brez nastavljenega Googla**
(`ADR-046` F je tam dal 404): starš, ki čaka, mora svojo stran videti, tudi če
lastnik Google medtem izklopi.

**Meja:** statične datoteke pod `/admin/static` niso pot usmerjevalnika in jih
zapora ne zajame. Tam so slog, pisava, KaTeX in marked — nič, kar bi nosilo
podatek katerekoli družine. Telefona se zapora ne tiče: otrok v neodobreni
družini ne more nastati.

### K — prehodi stanja

`families.status`: `pending`, `approved`, `rejected` (v vmesniku „čaka",
„odobrena", „zavrnjena"; vrednosti v bazi angleške kot `role` in `kind`).

- `pending → approved`, `pending → rejected`, `rejected → approved`.
- **`approved → rejected` ne obstaja.** `ADR-057` G sloni na tem, da zavrnjena
  družina nima vsebine; odobrena jo lahko ima. Odobreno družino lastnik
  ugasne (`is_active`), ne zavrne.
- Prehod je pogojni `UPDATE` na trenutno stanje; če ne spremeni ničesar, je
  odgovor `409`. Čas odločitve gre v `families.decided_at` (posnetek 09 kaže
  datum zavrnitve).
- „Odobri" in „Zavrni" imata vmesno stran (`GET`) in `POST` s CSRF, po vzoru
  `ADR-038` F: `/admin/system/families/{id}/approve` in `…/reject`.
- Zahtevka v stanju `pending` starš ne more umakniti; izbris je samo za
  `rejected`.

### L — izbris zavrnjenega računa

`GET /admin/racun/izbrisi` je vmesna stran, `POST` izbriše v **eni
transakciji** seje, poverilnice, uporabnike in družino — pogojno na
`status = 'rejected'` v istem stavku, da odobritev, ki pride vmes, zmaga.
Teče skozi `ClaniRepository(seja, družina iz seje)`: družine iz naslova tu ni.
Tuji ključi so brez `ondelete`; če bi družina kljub vsemu imela vsebino, baza
izbris zavrne in stran to pove.

### M — kdo bere in piše kaj

- **`PrijavaRepository`** (pred sejo, brez družine): ali ima e-naslov geselno
  poverilnico, število čakajočih, število registracij v zadnjih 24 urah, zapis
  registracije (družina, starš, poverilnica in vrstica v `login_attempts` v
  eni transakciji). Bere in piše samo tabele identitete in `families`.
- **`DruzineRepository`** (lastnik): čakajoče družine s staršem in e-naslovom,
  število čakajočih, starši vseh družin, prehod stanja. Meja `ADR-044` E velja
  — `families`, `users` in zdaj še `credentials` (način prijave in e-naslov);
  nikoli vsebina. Zapisani seznam javnih metod se dopolni.
- **`ClaniRepository`**: izbris iz L.

### N — shema

Migracija `0015`: `families.status` (`VARCHAR(16) NOT NULL`, `server_default`
`'approved'` — obstoječe družine so s tem odobrene), `families.consent_at` in
`families.decided_at` (oba `NULL`-abilna). Datum zahtevka je `created_at`.
`ustvari_z_prvim_starsem` stanje `approved` vpiše izrecno.

`downgrade` se **ne izvede**, če obstaja družina, ki ni `approved`: brez
stolpca bi čakajoča in zavrnjena družina tiho postali polnopravni. Isti vzorec
kot razveljavitev `0007` z dvema družinama.

### O — starš brez geselne poverilnice nima ponastavitve gesla

Do te zahteve je imel vsak starš vrstico `kind='password'` (četudi brez
gesla). Starš, registriran z Googlom, je nima, zato `ponastavi_geslo` zanj ne
spremeni ničesar in bi dal „dejanja nisem izvedel". Po vzoru otroka v
`V6-R01`: dejanje se zanj ne ponudi ne na `/admin/family` ne na
`/admin/system`, klic pa da `403` z razlago. Nastavitev gesla takemu staršu je
nova zahteva, če bo.

### P — tabela uporabnikov na `/admin/system`

Starši vseh družin: ime, e-naslov (identifikator geselne poverilnice, sicer
oznaka Google poverilnice), družina, način prijave (geslo, Google ali oboje),
**dve oznaki stanja** (družina: čaka, odobrena, zavrnjena; oseba ali družina
deaktivirana), datum nastanka. Otroci samo kot število ob družini
(`ADR-044` B).

### Q — števec čakajočih

Samo lastniku, ob postavki „Sistem", na vsaki strani — tudi pod
`/admin/system`, kjer števcev vsebine še naprej ni (`ADR-060` F). Ena
poizvedba nad `families`; nič se ne izriše.

### R — ime iz Googla

`RacunGoogla` dobi `name`. Služi samo predizpolnitvi polja „Tvoje ime" in
potuje v piškotku iz G; kar starš odda, gre v `users.display_name`. Googlovega
imena posebej ne hranimo.

## Posledice

- **Kaj to olajša:** `V6-R03` dobi cilj za gumb „Registracija" in en vir
  besedila o podatkih; povezave iz B doda sama.
- **Kaj to oteži:**
  - Vsak nov usmerjevalnik pod `/admin` mora na seznam iz J; pozabljenega
    ujame generirani test, ne plast.
  - `POTI_BREZ_SEJE` ni več enočlanska; varovalni test se dopolni.
  - Ključ podpisa živi v pomnilniku procesa (G).
  - Prvič obstaja pot, ki briše družino (L). Varuje jo pogoj na stanju in
    odsotnost `approved → rejected` (K).
- **Zavestno izpuščeno:** umik čakajočega zahtevka, nastavitev gesla staršu
  brez geselne poverilnice, uradni Googlov gumb z logotipom (gumb je v slogu
  obstoječega na prijavni strani), pridružitev drugega starša z Googlom
  (ostane `V3-R06`), soglasje za ročno odprte družine (`ADR-057` D).
