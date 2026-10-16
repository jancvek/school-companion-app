# Backlog — ideje, o katerih še ni odločeno

Tu živijo ideje, ki jih lastnik želi ohraniti, ne pa še zgraditi. **Vnos ni
odločitev in ni zahteva** (`ADR-065`):

- Vnos ni podlaga za kodo. Iz backloga vodi pot samo skozi fazo 0 v
  `CLAUDE.md` — POC (§1d) ali zahteva. Šele tam nastane ADR.
- V fazi 1 se backlog ne bere, razen če ga zahteva navaja pod **Podlaga**.
- Vnos doda ali spremeni lastnik ali model na lastnikovo izrecno naročilo.
- *Predlog smeri* je pogled modela ob zapisu, ne dogovor. Dogovor nastane
  šele v POC-u (*Dogovorjeno*) ali v ADR-ju.
- Vnos se ne briše. Ko je prevzet ali zavržen, se mu spremeni status, vsebina
  ostane — da se isto vprašanje ne razdeluje dvakrat.

**Statusi:** `Ideja` → `Prevzeto v POC-xx` / `Prevzeto v VN-Rxx` ali
`Zavrženo` (z razlogom). Status se spremeni v istem commitu, v katerem nastane
`POC-xx` ali `VN-Rxx`.

**Oblika vnosa:** naslov `## B-xx — <ime>`, nato vrstice *Status*, *Dodano* in
*Česa se dotakne* (sprejeti ADR-ji, ki bi padli ali se odprli), ter razdelki
*Zakaj*, *Kaj*, *Česa ni*, *Predlog smeri (ni dogovor)*, *Pasti* in
*Odprta vprašanja*. Nov vnos dobi naslednjo prosto številko.

---

## B-01 — Starševski način mobilne aplikacije

- **Status:** Ideja
- **Dodano:** 2026-10-14
- **Česa se dotakne:** `ADR-036` D (starš se v mobilno aplikacijo ne
  prijavi); `ADR-039` in pogodba v `routers/materials.py` (otrok pride iz
  seje, ne iz multiparta); `ADR-061` (povezava telefona s QR); `ADR-050`
  (kartica „danes")

### Zakaj

Starš želi na telefonu videti, ali je otrok ta dan že slikal in kaj je
slikal. Kadar otrok nima svojega telefona, naj snov namesto njega poslika
starš; v aplikaciji izbere, v imenu katerega otroka slika, in slika se shrani
pod tega otroka.

### Kaj

- Ista aplikacija za otroka in starša; način določi vloga v seji.
- Starš ima zaenkrat samo dvoje:
  - pogled **„Danes"** — ali je otrok danes že kaj slikal in kaj;
  - **„Slikaj za …"** — slikanje snovi v imenu izbranega otroka.

### Česa ni

- Kvizov za starša na telefonu.
- Obvestil („otrok je ravnokar slikal").
- Pregleda prejšnjih dni na telefonu — ta ostane na spletni strani.
- Prepisov in povzetkov v pogledu „Danes".

### Predlog smeri (ni dogovor)

- **Povezava telefona:** starš poveže telefon s QR kodo iz „Moj račun", z
  istim mehanizmom kot otrok (`link_tokens`, `ADR-061`), le žeton je vezan na
  starša. Gumb „Odpri na tem telefonu" pokrije primer, ko je stran odprta na
  istem telefonu. Prijava z Googlom v aplikaciji bi pomenila novo odvisnost,
  nastavitev odtisa SHA-1 v Google Cloud in drugo pot do seje za isti
  rezultat.
- **Lastnik slike:** pri otrokovi seji ostane vse po starem (stari APK mora
  delati naprej). Pri starševi seji je `child_id` v prenosu obvezen; strežnik
  preveri, da gre za aktivnega otroka **te** družine, tuj ali neobstoječ otrok
  je `404` (`ADR-038`).
- **Telefon:** lokalna tabela `materials` dobi stolpec, komu slika pripada,
  poleg `user_id` (čigava seja jo pošlje) — migracija lokalne sheme
  (`ADR-004`). Seznam otrok se shrani na telefon ob povezavi in se osvežuje,
  da kamera brez povezave ne čaka na strežnik.
- **„Danes":** nova pot z odgovorom JSON nad isto sestavo kot `app/danes.py`
  (`ADR-050`), da se številki na spletu in telefonu ne moreta razići. Besedilo
  pove, kaj je **prišlo na strežnik**, ne kaj je otrok slikal („Na strežnik
  danes še ni prišla nobena slika").
- **Sličice:** nova pot, ki sliko postreže z žetonom (danes jo streže samo
  spletna stran s piškotkom), vezana na družino, `Cache-Control: private`.

### Pasti

- **Napačen pripis otroka je tih in se razširi** v kvize, statistiko in teste
  tega otroka. Ime otroka mora biti ves čas vidno na zaslonu kamere; na
  spletni strani bi kazalo imeti „prestavi k drugemu otroku" po vzorcu
  `ADR-040`.
- **Starševska seja na telefonu vidi slike vseh otrok.** „Prekliči prijave"
  mora veljati tudi za starša; žeton s telefona ne sme odpirati `/admin`.
- **Družina, ki čaka ali je zavrnjena** (`ADR-057`), telefona ne sme povezati.

### Odprta vprašanja

1. Kaj je glavni razlog — pogled ali slikanje namesto otroka? Ali bi za
   pogled zadoščala spletna stran v brskalniku na telefonu?
2. Ali se zapiše, kdo je fotografiral (`taken_by`), in se to vidi v pregledu
   po dnevih? Predlog: da — danes en stolpec, pozneje podatka ni mogoče dobiti
   nazaj.
3. Kdaj starš izbere otroka: pred vsako sliko ali enkrat ob odprtju kamere
   (velja do zaprtja)? Predlog: enkrat ob odprtju; pri enem otroku izbire ni
   (`ADR-051`).
4. Kaj pomeni „kaj je slikal": predmet, število slik in sličice s povečavo —
   brez prepisa?
5. Samo danes?
6. Ali „Danes" pokaže tudi manjke po urniku (`ADR-028`)?
7. POC (posnetka „Danes" in kamere z izbiro otroka) ali takoj zahteva?

---

## B-02 — Test v reševanju in rešen test

- **Status:** Ideja
- **Dodano:** 2026-10-16
- **Česa se dotakne:** `ADR-053` F (shranjen preizkus se ne ureja,
  „statusov ni"); `PreizkusiRepository` v `app/db.py` in model `Preizkus`
  (zapis „se ne spremeni nikoli", ni `UPDATE`); `ADR-055` A (pregled
  shranjenih testov, filter samo po predmetu); `ADR-011` (nič se ne briše)

### Zakaj

Shranjen test danes ne pove, ali je že bil pri otroku in ali ga je otrok
rešil. Starš želi na pregledu testov videti, kateri testi so trenutno pri
otroku.

### Kaj

- Ko starš test shrani, ga lahko označi, da je bil **dan otroku** (v
  reševanju), in kasneje, da ga je otrok **rešil**.
- Pregled shranjenih testov dobi filter **„V reševanju"**.

### Česa ni

- Ocen, točk in opomb o tem, kako je otrok reševal (opombe pri shranjenih
  testih so ločena misel, v backlogu še ni zapisana).
- Reševanja na telefonu — test ostane na papirju (`ADR-053` B).
- Opomnikov in obvestil („test je pri otroku že teden dni").

### Predlog smeri (ni dogovor)

- **Vsebina ostane nespremenljiva, spremeni se samo predaja.** Tabela
  `preizkusi` dobi dva časovna žiga, `given_at` in `solved_at` (oba lahko
  `NULL`); stanje je izpeljano: brez žigov *shranjen*, z `given_at`
  *v reševanju*, s `solved_at` *rešen*. Repozitorij dobi eno ozko metodo, ki
  zapiše samo ta dva stolpca; test, rešitve, snov in naslovljenec ostanejo
  brez `UPDATE`. `ADR-053` F se v tem delu spremeni z novim ADR-jem.
- **Žig namesto besedila stanja:** datum predaje in rešitve pride zraven
  zastonj, kasnejša migracija pa ga starim vrsticam ne bi mogla dati (isti
  razlog kot `base_id`, `ADR-055` E).
- **Kje se označi:** ob shranjevanju potrditveno polje „Dan otroku" (test se
  pogosto natisne in preda takoj); na ogledu shranjenega testa gumb „Dan
  otroku" oz. „Rešen". „Rešen" brez predhodnega „dan" je dovoljen in
  nastavi oba žiga.
- **Pregled:** filter stanja se sestavlja s filtrom predmeta
  (`?predmet=MAT&stanje=v-resevanju`), v vsaki vrstici je oznaka stanja.
  Neznano stanje da prazen seznam, kot neznan predmet (`ADR-055` A).
- **Nov test na osnovi** začne brez stanja — je nov list papirja.

### Pasti

- **`ADR-053` F izrecno pravi „statusov ni"**, model `Preizkus` pa „zapis se
  ne spremeni nikoli". Brez novega ADR-ja pregled kode spremembo zavrne —
  ali pa jo kdo izpelje s splošnim `UPDATE` in s tem odpre pot urejanju
  vsebine.
- **Statusi delovnih listov (`ADR-032`, nadomeščen) niso zgled.** Tam je šlo
  za stanje vsebine (`osnutek` → `pripravljen` → `arhiviran`), tu za predajo
  papirja otroku; vsebina je ob shranjevanju že končana.
- **Napačen klik.** Če se stanja ne da vrniti, ostane „rešen" test, ki ga
  otrok ni videl; če se da, se izgubi datum.
- **Deaktiviran otrok** (`ADR-055` H dovoli test zanj): njegov test v
  reševanju bi v filtru visel za vedno.
- **„Rešen" ni isto kot „pregledan".** Če pridejo opombe, se odpre
  vprašanje tretjega stanja.

### Odprta vprašanja

1. Se oznaka nastavi ob shranjevanju, kasneje na ogledu, ali oboje?
2. Se stanje lahko vrne nazaj (napačen klik)?
3. Rabi filter samo „V reševanju" ali tudi „Rešeni" in „Še ni dan"?
4. Se v seznamu vidi, kdaj je bil test dan oz. rešen (npr. „pri otroku 3
   dni")?
5. Ali „rešen" kasneje dobi opombo — in ali naj se ideja o opombah zapiše
   kot svoj vnos ali kot del tega?
6. Naj se testi v reševanju pokažejo tudi na kartici „Danes" (`ADR-050`)?
