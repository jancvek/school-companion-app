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

- **Status:** Prevzeto v V4-R10
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

---

## B-04 — Testi za vse predmete

- **Status:** Ideja
- **Dodano:** 2026-11-03 (misel iz pogovora 2026-10-14)
- **Česa se dotakne:** `ADR-053` D (navodilo se poišče po predmetu, danes
  obstaja samo za matematiko) in H (grafičnih nalog in slik ni); `ADR-066`
  (vsaka sprememba navodila je zahteva z novim ADR-jem, ki nosi celotno
  besedilo); `V4-R07` (gumb „Kreiraj test" samo na strani matematike);
  `NAVODILA` in `navodilo_za` v `app/preizkus.py`; izris v
  `_preizkus-izris.html` (KaTeX, oznake prostora)

### Zakaj

Od vseh funkcij lastniku najbolj pomaga sestavljanje testov v klepetu s
predogledom A4, danes pa dela samo pri matematiki. Starš teste rabi tudi pri
ostalih predmetih.

### Kaj

- Sestavljanje testov pri vseh predmetih, s posebnostmi po predmetu
  (lastnik, 2026-10-14).
- Navodilo modelu je fiksno po predmetu (lastnik, 2026-10-14).
- Vsi predmeti naenkrat, v eni zahtevi (lastnik, 2026-10-14).

### Česa ni

- Trajnih želja staršev — navodila, ki bi ga starš shranil za predmet
  (lastnik, 2026-10-14).
- Ločenega preizkušanja navodila za vsak predmet posebej (lastnik,
  2026-10-14).

### Predlog smeri (ni dogovor)

- **Skupno jedro in razdelek po predmetu.** Oblika izhoda (`sporocilo`,
  `test_md`, `resitve_md`), točke, oznake prostora, vrstni red postavk in
  tisk so enaki za vse predmete; po predmetu se razlikujejo vrste nalog in
  zapis. Deset razdelkov ob enem jedru se ne more razići tako kot deset
  ločenih navodil.
- **Izvirnik je ADR** (`ADR-066` 2): nov ADR nosi celotno besedilo jedra in
  vseh razdelkov, test primerja vsako konstanto z zapisom.
- **Gumb „Kreiraj test"** pri vsakem predmetu, ki ima navodilo.
  `navodilo_za` že vrne `None` za predmet brez navodila, zato tak predmet ni
  napaka, ampak stanje.

### Pasti

- **Izris je danes matematičen.** `\frac` → `\dfrac`, decimalna vejica in
  KaTeX so pravila matematike. Pri jezikih so naloge drugačne (dopolnjevanje,
  prevod, izbira med možnostmi, povezovanje) in oznake `[odgovor-kratek]` /
  `[odgovor-dolg]` morda ne zadoščajo.
- **Brez preizkušanja navodil je prvi pravi preizkus vsakega predmeta šele v
  fazi 9b.** Deset predmetov v eni zahtevi pomeni deset ročnih preizkusov
  natisnjenega testa pred mergom.
- **Pravilo o vrstnem redu postavk** (`ADR-066`) mora biti v jedru, ne v
  razdelku matematike: primer iz pogovora 2026-10-14 (present simple /
  continuous) je bil prav jezikovni.
- **Predmeti brez pričakovane slike** (LUM, GUM, TIT so na urniku označeni z
  „ne pričakuj slike", `ADR-028`) imajo malo snovi, iz katere bi test
  nastal.

### Odprta vprašanja

1. Res vseh deset predmetov, tudi LUM, GUM in TIT?
2. Katere vrste nalog pri posameznem predmetu (npr. pri TJA dopolnjevanje
   in prevod, pri NAR, GEO in ZGO odprta vprašanja, drži / ne drži,
   povezovanje)? Kdo napiše razdelek: model predlaga, lastnik potrdi?
3. TJA: so navodila nalog v testu angleška ali slovenska?
4. Rabi test novo oznako za izbiro med možnostmi (a, b, c) ali za
   povezovanje?
5. POC ali zahteva? „Brez ločenega preizkušanja" govori za zahtevo, tveganje
   v *Pasteh* za POC.

---

## B-05 — Plonkec ob testu

- **Status:** Ideja
- **Dodano:** 2026-11-03 (misel iz pogovora 2026-10-14)
- **Česa se dotakne:** `ADR-053` B (izhod sta test in rešitve, vsak na svoji
  strani) in F (shrani = končan; kaj zapis hrani); `ADR-066` (oblika
  izhoda modela in navodilo); `ADR-055` in model `Preizkus` (tabela
  `preizkusi`, brez `UPDATE`); tisk v `_preizkus-izris.html`; `B-04`

### Zakaj

Ob testu naj otrok dobi kratka, hitro razvidna pravila za temo, ki jo test
preverja. Rešitve se s testom shranjujejo že od `V4-R08`; plonkec je drugi
del iste misli iz pogovora 2026-10-14.

### Kaj

- Ob vsakem testu vedno nastane plonkec: kratka, hitro razvidna pravila
  glede na temo testa (lastnik, 2026-10-14).
- Plonkec nastane na isti način kot rešitve (lastnik, 2026-10-14).
- Shrani se skupaj s testom (lastnik, 2026-10-14).
- Namenjen je **otroku ali staršu**: na strnjen, pregleden način navede
  pravila teme (lastnik, 2026-11-03).
- **Tisk na izbiro, tako kot rešitve:** ob tisku vpraša, ali naj se natisne
  tudi plonkec; če ne, se ne natisne (lastnik, 2026-11-03).
- **Največ ena stran A4** (lastnik, 2026-11-03).
- **Spreminja se z željami v istem klepetu kot test** (lastnik, 2026-11-03).
- **Za vse predmete takoj**, ne najprej samo matematika (lastnik,
  2026-11-03).

### Česa ni

Še ni dogovorjeno; glej *Odprta vprašanja*.

### Predlog smeri (ni dogovor)

- **Tretje polje v odgovoru modela** (`plonkec_md`) poleg `test_md` in
  `resitve_md`, v istem klicu. Navodilo pove, kaj plonkec je (pravila in
  formule, ne rešene naloge). Sprememba navodila je nov ADR po `ADR-066`.
- **Stolpec v `preizkusi`**, zapisan ob vstavljanju. To ni `UPDATE`, zato
  nespremenljivost zapisa (`ADR-053` F) ostane; stare vrstice imajo `NULL`.
  Je pa migracija sheme.
- **Tisk:** plonkec na svoji strani, za rešitvami ali pred njimi.
- **Vsebina:** pravila in postopki ter največ en kratek zgled z drugačnimi
  števili in besedami kot naloge v testu; jezik otroka za njegov razred.
  Cilj približno pol strani, meja ena stran.
- **Navodilo za plonkec po predmetu** (pri jezikih slovnična pravila in
  tabele, pri matematiki formule in postopki) — skupaj z navodili iz
  `B-04`.

### Pasti

- **Plonkec lahko izda odgovore**, če model vanj prepiše rešen primer, ki je
  tudi naloga v testu. Navodilo mora ločiti pravilo od rešitve naloge.
- **Vsak korak klepeta postane daljši.** Model vsakič vrne celoten test,
  rešitve in plonkec: več izhodnih žetonov in daljše čakanje pri vsaki želji.
- **Stari testi plonkca nimajo.** Ogled starega testa ga ne sme pričakovati;
  „Nov test na tej osnovi" ga mora ustvariti.
- Pri `B-04` je plonkec pri jezikih nekaj drugega kot pri matematiki.
- **„Za vse predmete takoj" je vezano na `B-04`.** Testi danes obstajajo
  samo za matematiko; plonkec za druge predmete pride šele s testi zanje.
  Če `B-05` gre pred `B-04`, plonkec velja za vse predmete, ki takrat imajo
  test, in navodilo za plonkec mora biti napisano tako, da ga `B-04` le
  razširi.

### Odprta vprašanja

1. Je plonkec za otroka med reševanjem (zraven testa) ali za učenje pred
   testom? Od tega je odvisno, ali sme vsebovati pravilo, ki nalogo reši.
2. ~~Vedno ali na izbiro?~~ Na izbiro, ob tisku vpraša kot pri rešitvah
   (lastnik, 2026-11-03).
3. ~~Koliko prostora?~~ Največ ena stran A4 (lastnik, 2026-11-03).
4. ~~Želje v istem klepetu?~~ Da (lastnik, 2026-11-03).
5. ~~Vsi predmeti ali najprej matematika?~~ Vsi predmeti takoj (lastnik,
   2026-11-03).
6. V jeziku otroka za njegov razred ali bolj strokovno za odraslega?

---

## B-06 — Prehodna napaka vision obdelave se ponovi sama

- **Status:** Ideja
- **Dodano:** 2026-11-03 (ugotovitev celostnega pregleda 2026-09-11)
- **Česa se dotakne:** `ADR-009` (kdaj je `failed` prav; mirujoč worker brez
  ključa); `ADR-004` (na telefonu je meja med `pending` in `failed` „ali se
  stanje sploh more spremeniti"); `ADR-044` D (ugasnjene družine obhod
  preskoči); `_opis_statusa` v `app/vision.py`; `_izid_za` v
  `app/obdelava.py`; `MaterialsRepository.seznam_novih` (bere samo `new`)

### Zakaj

Prehodna napaka klica vision modela (časovna omejitev, prekinjena povezava,
HTTP 429, 5xx) danes konča kot `failed`, enako kot trajna. Worker bere samo
zapise `new`, zato se taka slika sama nikoli ne obdela, dokler je starš ročno
ne pošlje v obdelavo. Na telefonu je ista razlika že rešena (`ADR-004`:
začasna napaka ni trajna).

### Kaj

- Prehodna napaka vision klica se ponovi sama, brez ročnega „Pošlji v
  obdelavo" (lastnik, 2026-11-03).

### Česa ni

- Sprememb ročnega „Pošlji v obdelavo" (`ADR-009`).
- Ponavljanja pri sestavljanju testa (`V4-R07`) — tam napako vidi starš v
  klepetu in sam poskusi znova. (Predlog modela, lastnik še ni potrdil.)

### Predlog smeri (ni dogovor)

- **Ista meja kot na telefonu** (`ADR-004`): 408, 429, 5xx, časovna
  omejitev in prekinjena povezava so prehodne, ostalo je trajno.
  `_opis_statusa` te primere že loči.
- **Prehodna napaka vrne zapis v `new`** s številom poskusov in časom, pred
  katerim ga worker ne vzame. Po zgornji meji poskusov gre v `failed` z
  zadnjim sporočilom. To je migracija sheme `materials`.
- Na strani snovi vrstica „čaka na ponovni poskus", da starš ne pošilja
  ročno nečesa, kar se bo zgodilo samo.

### Pasti

- **Vsak poskus je plačan.** 429 zaradi porabljene kvote se s ponavljanjem
  ne popravi; brez zgornje meje bi worker kvoto tolkel v nedogled.
- **Manjkajoč ključ ni napaka** (`ADR-009` B) in ne sme proizvesti
  poskusov; **ugasnjena družina** (`ADR-044` D) ostane preskočena.
- **Migracije se testirajo samo nad SQLite** (pregled 2026-09-11): Postgres
  veja nove migracije prvič teče na živi bazi.
- Obstoječi zapisi `failed` s prehodno napako: brez odločitve ostanejo
  `failed` za vedno.

### Odprta vprašanja

1. Koliko poskusov in v kakšnih razmikih?
2. Je neveljaven odgovor modela (pokvarjen JSON) prehoden ali trajen?
3. Mora starš videti, da slika čaka na ponovni poskus, ali zadošča končni
   izid?
4. Kaj z obstoječimi zapisi `failed` s prehodno napako: ostanejo, ali jih
   migracija vrne v `new`?
5. POC ali zahteva?
