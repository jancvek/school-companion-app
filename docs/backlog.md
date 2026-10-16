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

- Shranjen test starš **kasneje** (ne ob shranjevanju) označi, da je bil
  **dan otroku** (v reševanju), in nato, da ga je otrok **rešil**
  (lastnik, 2026-10-16).
- Pregled shranjenih testov dobi filtra **„V reševanju"** in **„Rešeni"**.
  Filtra „Še ni dan" lastnik ne rabi (2026-10-16).
- Stanje se da **vrniti nazaj** — napačen klik se popravi (2026-10-16).

### Česa ni

- Ocen, točk in opomb o tem, kako je otrok reševal — opombe so svoj vnos,
  `B-03`.
- Prikaza, koliko dni je test pri otroku (lastnik, 2026-10-16).
- Testov v reševanju na kartici „Danes" (`ADR-050`) (lastnik, 2026-10-16).
- Oznake ob shranjevanju — samo kasneje, na shranjenem testu.
- Reševanja na telefonu — test ostane na papirju (`ADR-053` B).
- Opomnikov in obvestil („test je pri otroku že teden dni").

### Predlog smeri (ni dogovor)

- **Vsebina ostane nespremenljiva, spremeni se samo predaja.** Tabela
  `preizkusi` dobi dva časovna žiga, `given_at` in `solved_at` (oba lahko
  `NULL`); stanje je izpeljano: brez žigov *shranjen*, z `given_at`
  *v reševanju*, s `solved_at` *rešen*. Repozitorij dobi eno ozko metodo, ki
  zapiše samo ta dva stolpca; test, rešitve, snov in naslovljenec ostanejo
  brez `UPDATE`. `ADR-053` F se v tem delu spremeni z novim ADR-jem.
- **Žig namesto besedila stanja:** datuma se ne prikazujeta, a kasnejša
  migracija ju starim vrsticam ne bi mogla dati (isti razlog kot `base_id`,
  `ADR-055` E), cena pa je enaka kot pri stolpcu s stanjem.
- **Kje se označi:** na ogledu shranjenega testa gumb „Dan otroku" oz.
  „Rešen". „Rešen" brez predhodnega „dan" je dovoljen in nastavi oba žiga.
  Urejevalnik in pot shranjevanja (`ADR-055` G) ostaneta nespremenjena.
- **Pregled:** filter stanja se sestavlja s filtrom predmeta
  (`?predmet=MAT&stanje=v-resevanju`), v vsaki vrstici je oznaka stanja.
  Neznano stanje da prazen seznam, kot neznan predmet (`ADR-055` A).
- **Vrnitev** pobriše zadnji žig (rešen → v reševanju → shranjen). Brisanje
  vrednosti v stolpcu ni brisanje zapisa, zato `ADR-011` ne pade; v novem
  ADR-ju naj bo to vseeno izrecno zapisano.
- **Nov test na osnovi** začne brez stanja — je nov list papirja.

### Pasti

- **`ADR-053` F izrecno pravi „statusov ni"**, model `Preizkus` pa „zapis se
  ne spremeni nikoli". Brez novega ADR-ja pregled kode spremembo zavrne —
  ali pa jo kdo izpelje s splošnim `UPDATE` in s tem odpre pot urejanju
  vsebine.
- **Statusi delovnih listov (`ADR-032`, nadomeščen) niso zgled.** Tam je šlo
  za stanje vsebine (`osnutek` → `pripravljen` → `arhiviran`), tu za predajo
  papirja otroku; vsebina je ob shranjevanju že končana.
- **Vrnitev izgubi datum.** Ker se stanje da vrniti, žig po vrnitvi ni več
  zgodovina, ampak trenutno stanje. Če bi kdaj rabili „kolikokrat je bil
  test pri otroku", bi bila potrebna tabela dogodkov — za zdaj ne.
- **Deaktiviran otrok** (`ADR-055` H dovoli test zanj): njegov test v
  reševanju bi v filtru visel za vedno.
- **„Rešen" ni isto kot „pregledan".** Če pride `B-03` (opombe), se odpre
  vprašanje tretjega stanja.

### Odprta vprašanja

1. ~~Kdaj se označi?~~ Kasneje, na shranjenem testu (lastnik,
   2026-10-16).
2. ~~Se stanje lahko vrne nazaj?~~ Da (lastnik, 2026-10-16).
3. ~~Kateri filtri?~~ „V reševanju" in „Rešeni"; „Še ni dan" ne
   (lastnik, 2026-10-16).
4. ~~Se vidi, koliko dni je test pri otroku?~~ Ne (lastnik, 2026-10-16).
5. ~~Opombe del tega vnosa?~~ Ne, svoj vnos `B-03` (lastnik, 2026-10-16).
6. ~~Na kartici „Danes"?~~ Ne (lastnik, 2026-10-16).

Odprtih vprašanj ni več; vnos je pripravljen za fazo 0 (POC ali zahteva).

---

## B-03 — Opombe pri shranjenem testu

- **Status:** Ideja
- **Dodano:** 2026-10-16 (misel iz pogovora 2026-10-14)
- **Česa se dotakne:** `ADR-053` F (shranjen preizkus se ne ureja) in
  *Posledice* („opomba po rešenem listu kot vhod v naslednji list" je bila z
  V4 zavržena — „če jo lastnik kdaj želi, je to nova zahteva");
  `ADR-053` D (kaj model dobi v klepetu); `ADR-066` (navodilo za test se
  spreminja z zahtevo); `PreizkusiRepository` in model `Preizkus` (brez
  `UPDATE`); `B-02` (stanje *rešen*)

### Zakaj

Po rešenem testu starš želi zapisati, kako je šlo — na primer, kaj je bilo
otroku težko. Danes tega ni kam zapisati in se pozabi.

### Kaj

- Pri shranjenem testu je **ena opomba v prostem besedilu**, ki jo starš
  lahko **kadarkoli dopolni, spremeni ali pobriše** — ni vezana na stanje
  *rešen* iz `B-02` (lastnik, 2026-10-16).
- Opomba se vidi na ogledu shranjenega testa, **v seznamu testov ne**
  (lastnik, 2026-10-16).
- **Opombe gredo v klepet za nov test** — model jih upošteva pri sestavi
  (lastnik, 2026-10-16).

### Česa ni

- Ocen in točk.
- Sprememb testa samega — test ostane, kakršen je bil shranjen.
- Samodejne analize ali povzemanja opomb z modelom zunaj klepeta za nov
  test.
- Zgodovine različic opombe.

### Predlog smeri (ni dogovor)

- **Opomba je svoja tabela 1 : 1, ne stolpec testa.** `preizkusi_opombe`
  (`preizkus_id` kot primarni ključ, `family_id`, `text`, `updated_at`):
  `preizkusi` ostane brez `UPDATE`, opomba pa se prepisuje. Pobrisana
  opomba je prazno besedilo ali odsotna vrstica — zapis testa se ne briše,
  zato `ADR-011` ne pade; v ADR-ju naj bo to izrecno.
- **V klepet gre kot del vhoda, ne kot želja.** Opomba je kontekst poleg
  prepisov (`ADR-053` D), z oznako, da gre za zapis starša o prejšnjem
  reševanju; v verigo želja ne spada, ker je ni mogoče razveljaviti kot
  korak. Navodilo modelu pove, kaj z njo — to je sprememba navodila po
  `ADR-066`.
- **Pri „Nov test na tej osnovi"** gre zraven opomba izhodiščnega testa —
  to je najbolj očiten primer.
- Obrazec s CSRF žetonom na ogledu testa, kot drugi `POST` pod `/admin`.
  Besedilo gre v predlogo samo skozi samodejno ubežanje (Jinja), ne skozi
  izris markdowna — opomba ni besedilo modela.

### Pasti

- **`ADR-053` je opombo kot vhod v naslednji test izrecno zavrgel** in
  pravi, da je to nova zahteva. Lastnik jo zdaj želi, zato rabi nov ADR, ki
  `ADR-053` D in *Posledice* v tem delu nadomesti — ne sme pripolzeti zraven
  kot „samo še to".
- **Pisanje v `preizkusi` odpre urejanje.** Če se opomba doda kot stolpec,
  repozitorij dobi `UPDATE` na tabeli, ki ga danes namerno nima — isti
  razlog kot pri `B-02`.
- **Opomba je osebni podatek o otroku** (kaj mu ne gre) in z njo **odide k
  OpenAI**. Prepisi gredo tja že danes, opomba pa je starševa ocena otroka,
  ne snov. Ostane v družini (`ADR-025`) in se ne prikazuje nikjer zunaj
  ogleda testa in klepeta.
- **Opomba se spreminja, test pa ne.** Test, sestavljen z opombo, ki je bila
  kasneje prepisana, ne pove več, na kaj se je model oprl. Če je to
  pomembno, se besedilo opombe ob shranjevanju novega testa zamrzne poleg
  snovi (kot prepisi, `ADR-053` F).
- **Opomba je prosto besedilo v vhodu modela** — starš lahko vanjo (ne da bi
  hotel) napiše navodilo, ki se bije s fiksnim navodilom. Navodilo mora
  povedati, da opomba opisuje otroka, ne spreminja pravil testa.

### Odprta vprašanja

1. ~~Koliko opomb?~~ Ena tekstovna opomba na test (lastnik, 2026-10-16).
2. ~~Popravek, brisanje?~~ Da, kadarkoli dopolni ali spremeni (lastnik,
   2026-10-16).
3. ~~Vezana na *rešen*?~~ Ne, kadarkoli (lastnik, 2026-10-16).
4. ~~V seznamu testov?~~ Ne (lastnik, 2026-10-16).
5. ~~V klepet za nov test?~~ Da (lastnik, 2026-10-16).
6. **Katere opombe** gredo v klepet pri testu **iz snovi** (ne na osnovi):
   nobena, zadnjih nekaj opomb istega otroka pri istem predmetu, ali jih
   starš izbere sam?
7. Gre opomba v klepet samodejno, ali jo starš v urejevalniku vidi in jo
   lahko izključi?
8. Se besedilo uporabljene opombe ob shranjevanju novega testa zamrzne
   (glej *Pasti*)?
