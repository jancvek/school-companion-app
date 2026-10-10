# ADR-053: Preizkus iz POC-01 nadomesti delovne liste; V4 je verzija preizkusov

- **Datum:** 2026-10-10
- **Nastalo pri:** POC-01 (sodba `Sprejeto`), pred V4-R07
- **Status:** Sprejeto
- **Nadomešča:** `ADR-031`, `ADR-032`, `ADR-033` v celoti
- **Stoji na:** `docs/poc/POC-01.md` (*Dogovorjeno* in *Ugotovitve*),
  `ADR-048` F (sestavljanje prepisov izbora je čista funkcija, namenjena tudi
  generatorju), `ADR-039` A (naslovljenec je obvezen), `ADR-011` (nič se ne
  briše), `ADR-025` in `V3-R01` (družina je lastnik podatkov)

## Kontekst

V4 je bila 15. 9. zastavljena kot „delovni listi": razlaga, naloge in rešitve,
markdown kot resnica, Word kot izvoz, ročno urejanje, razred kot lastnost
otroka, opomba po rešenem listu kot vhod v naslednjega (`ADR-031`–`ADR-033`).
Nobena zahteva V4 ni bila začeta.

Lastnik je nato v POC-01 v treh krogih preizkusil drugačno izvedbo — s pravim
modelom in svojo snovjo — in jo sprejel: matematični **test** s točkami,
sestavljen v klepetu z modelom, natisnjen iz brskalnika. Med POC-om se je
pokazalo, da se večina temeljnih odločitev V4 obrne. Lastnik je odločil, da
se V4 v dosedanji obliki zavrže in nadomesti z rešitvijo iz POC-01.

## Možnosti

1. **Dopolniti V4** — novo zahtevo dodati, stare pustiti. Za: nič se ne
   umakne. Proti: V4 bi hkrati obljubljala Word in tisk iz brskalnika, ročno
   urejanje in samo klepet, razred kot podatek in razred v klepetu.
2. **Nova verzija V5, V4 ostane** — Za: V4 ostane nedotaknjena. Proti: V4 bi
   ostala kot načrt, ki ga nihče ne bo gradil, in bi vsako sejo zavajala.
3. **V4 postane verzija preizkusov** — dosedanje zahteve dobijo `Umaknjeno`,
   ID-ji ostanejo zasedeni, nove zahteve od `V4-R07` naprej. Za: ena verzija,
   en cilj, zgodovina ostane berljiva. Proti: ID-ji ne začnejo pri R01.

## Odločitev

**Možnost 3.** `ADR-031`, `ADR-032` in `ADR-033` so nadomeščeni v celoti;
zahteve `V4-R01`–`V4-R06` so `Umaknjeno`.

**A. Ime.** V kodi, bazi in imenih datotek `preizkus` (tabela `preizkusi`).
Poti pod `/admin` ostanejo angleške kot vse ostale; ime poti določi plan, ne
sme pa vsebovati `test`. V vmesniku „Test". Beseda `test` ostane rezervirana
za avtomatske teste (razlog iz `ADR-031` drži).
Ugovor iz `ADR-031` proti besedi „preizkus" („pomeni ocenjevanje, kar list
ni") ne velja več: list ima točke, ime in datum.

**B. Izhod je stran za tisk, ne datoteka.** Test in rešitve sta markdown s
formulami v LaTeX-u, izrisana v brskalniku na list A4 in natisnjena (ali
shranjena kot PDF) iz brskalnika. Worda ni. Rešitve so na svoji strani in se
natisnejo samo na izbiro. Naloga se ob tisku ne razdeli čez stran.

**C. Vhod so prepisi izbranih snovi.** Starš izbere slike na strani predmeta
(isti izbor kot „Prepisi izbranih", `ADR-048`) in klikne „Kreiraj test".
Besedilo za model je isto, kot ga sestavi `ADR-048` F. Slike so v
urejevalniku samo za ogled; model jih ne dobi. Predmet je znan iz strani.

**D. Sestavljanje je klepet z modelom; ročnega urejanja ni.** Vsak odgovor
modela vrne celoten test in rešitve. Model dobi fiksno navodilo, poiskano
**po predmetu** (danes samo matematika), prepise, trenutni test in rešitve,
**verigo sprejetih želja** do trenutnega koraka in novo željo — ne odgovorov
modela in ne razveljavljenih želja. Razred in dolžino starš pove v klepetu;
razred ni podatek v bazi. Navodilo, oblika vhoda in oznake (`[odgovor]`,
`prostor: …`) so dobesedno v `POC-01` *Ugotovitve*.

**E. Delo v teku živi samo v brskalniku.** Razveljavi/uveljavi po korakih
(vsak odgovor modela je korak); nova želja po razveljavitvi zavrže
razveljavljene korake. Strežnik je za model brez stanja. Vmesnega
shranjevanja, nadaljevanja pogovora kasneje in zgodovine različic ni.
Zaprtje okna izbriše delo — pred tem opozorilo.

**F. Shrani = preizkus je končan.** Zapis nastane šele ob „Shrani" in hrani
test, rešitve, snov (prepise), iz katere je nastal, predmet, naslovljenca,
čas in model. Shranjenega preizkusa se ne ureja; iz njega lahko nastane
**nov preizkus na tej osnovi**. Statusov ni — zapis obstaja samo za končan
preizkus. Nič se ne briše (`ADR-011`).

**G. Vsak preizkus je vezan na otroka.** Naslovljenec je obvezen, kot pri
kvizu (`ADR-039` A).

**H. Grafičnih nalog in slik v testu ni** (prevzeto iz `ADR-033` F).

## Kar ta ADR še ne odloči (faza 1 zahtev)

- Izris formul: knjižnici iz POC-a (marked, KaTeX), postreženi z lastnega
  strežnika, ali izris na strežniku (MathML). Oboje je nova zunanja
  odvisnost (trdi rob 5).
- Obseg izjeme od `ADR-024`: urejevalnik brez skripte ne deluje in shranjuje
  s klicem iz skripte.
- Privzeti model in imena nastavitev za ločen ključ.

## Posledice

- **Olajša:** ni pretvornika v Word, ni sheme za razred, ni statusov, ni
  datotek na disku; prva uporabna zahteva ne potrebuje migracije.
- **Oteži:** prva stran v adminu, kjer je skripta pogoj in ne nadgradnja;
  zaprtje okna med delom izgubi delo (sprejeto).
- **Zavrženo z V4:** opomba po rešenem listu kot vhod v naslednji list
  (`ADR-032` E, `ADR-033` H). Če jo lastnik kdaj želi, je to nova zahteva.
- **Vpliva na:** `docs/verzije/v4.md` (prepisana), `docs/00-namen.md` (pojmi),
  `V4-R07`, `V4-R08`.
