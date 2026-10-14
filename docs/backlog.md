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
