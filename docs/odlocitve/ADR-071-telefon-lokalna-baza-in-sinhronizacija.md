# ADR-071: Telefon — lokalna baza, lastnik zapisa in sinhronizacija (zapis za nazaj)

- **Datum:** 2026-11-04
- **Nastalo pri:** V6-R05 (zapis za nazaj; razlogi so nastali ob zahtevah, ki so navedene pri vsaki točki)
- **Status:** Sprejeto — zapis za nazaj

## Kontekst

Do V6-R05 so ti razlogi živeli v `docs/01-arhitektura.md` ob opisu stanja.
`ADR-070` jih seli sem, da arhitektura pove samo, kako je. Kar je tu, je že
izvedeno; ADR ne odpira ničesar novega. Odločitve, ki imajo svoj ADR, so tam
in tu samo navedene.

## Odločitve in razlogi

### A. Ogrodje aplikacije (V1-R01)

1. **React Compiler je izklopljen.** Expo predloga ga vklopi
   (`experiments.reactCompiler`), `jest` pa ga ne uporablja — zastavica pride
   iz Babelovega `caller`, ki ga testni prevod ne nastavi, in je z nastavitvijo
   preseta ni mogoče vsiliti. Testi bi torej preverjali drugače preveden kod,
   kot se namesti na telefon. Ker aplikacija ni zahtevna in je varnostna mreža
   projekta prav v testih, je skladnost pomembnejša od memoizacije. Če ga bomo
   kdaj vklopili, mora zraven priti način, da isto velja tudi v testih.
2. **Baza je za tankim vmesnikom `MaterialsDatabase`**, ki ga funkcije dobijo
   kot argument. Razlog: poslovna logika je testljiva brez naprave. (Stari
   `01` je trdil, da se `expo-sqlite` pojavi samo v `src/db/open.ts` in korenski
   postavitvi; ob V6-R05 to ne drži več — `useSQLiteContext` uvažajo tudi
   zasloni in ponudniki.)
3. **Mape `plugins/` ni** od V3-R02: edini config plugin (dovoljenje za
   nešifriran promet, `ADR-010`) je odstranjen skupaj z nešifriranim prometom
   (`ADR-026`).

### B. Lokalna shema in migracije (V1-R02, V2-R02, V3-R04, V3-R07)

1. **Shema je verzionirana** (`PRAGMA user_version`). `CREATE TABLE IF NOT
   EXISTS` obstoječi tabeli novega stolpca ne doda in tega ne javi; brez
   migracij bi se telefon z zapisi iz V1-R01 tiho pokvaril, testi nad svežo
   bazo pa bi bili zeleni.
2. **Sveža namestitev gre skozi isto zaporedje migracij kot nadgradnja** —
   dve poti bi pomenili dve shemi, od katerih bi bila testirana samo ena.
3. **Stare migracije se ne popravljajo** — telefon, ki je migracijo že
   prestal, je nikoli več ne požene; kar je narobe, popravi nova migracija.
4. **Test migracije teče nad dobesedno kopijo starejše sheme**
   (`__tests__/test-database.ts`: zamrznjena shema V1-R01, `SHEMA_VERZIJE_1`,
   `_2`, `_4`), ne nad shemo iz kode — sicer bi migracijo preverjal nad tem, kar
   sam ustvari. Kopije so take, kakršna je bila baza na Mašinem telefonu pred
   ustrezno zahtevo.
5. **V1-R07 lokalne sheme ni spremenila:** telefon o arhivu ne hrani ničesar,
   ker delovni seznam pride vsakič v celoti s strežnika. `SHEMA_VERZIJA` je
   takrat ostala 1; na 2 jo je dvignila V2-R02.
6. **Čakalna vrsta bere `taken_at ASC`**, zgodovina `DESC`: najstarejši posnetek
   ne sme čakati najdlje.

### C. Lastnik zapisa (V3-R04, V3-R07)

1. **`user_id IS NULL` pomeni „nastalo, ko ni bil prijavljen nihče"**, ne
   „brez lastnika za vedno". Tak zapis posvoji **vsaka razrešena seja**
   (prijava in obnovitev žetona z diska), ne le prijava: okno, v katerem tak
   zapis nastane, se odpre tudi, kadar branje ali brisanje iz varne shrambe
   spodleti, in vezava na prijavo bi ga pustila nedosegljivega za vedno
   (`ADR-036`, popravki po drugem pregledu). Brez posvojitve bi bila nadgradnja
   Mašinega telefona vrsta, ki ne odide nikoli — vse obstoječe vrstice so bile
   brez lastnika.
2. **Pogoj je `user_id IS ?` in ne `=`**, da isti stavek velja za prijavljeno
   uporabnico in za neprijavljeno aplikacijo.
3. **Kviz nosi lastnika od V3-R07.** Do takrat `cakajociKvizi`, `najdiKviz` in
   `postavkeKviza` niso filtrirale, zato je na skupnem telefonu otrok B videl
   kvize otroka A (tiste, na katerih je visel neprenesen tuj poskus, `ADR-036`
   C) in v njih postavke, ki so bile zanj videti odgovorjene.
4. **Kviz brez lastnika posvoji seja lokalno in brez omrežja**, sicer otrok
   brez povezave kvizov ne bi videl; `shraniKviz` ga ob obhodu posvoji samo iz
   `NULL`, ker je vsebina zamrznjena (`ADR-016` E).
5. **`postavkeKviza` ima dva pogoja:** stik na `quizzes` in filtriran stik na
   `attempts`. Drugi je nujen: tuj poskus ne sme postavke narediti odgovorjene,
   sicer bi kviz na seznamu visel za vedno.

### D. Kvizi v lokalni bazi (V2-R02)

1. **Stanje kviza se ne shranjuje, izpelje se** v eni poizvedbi
   (`cakajociKvizi`), ki jo bereta števec in seznam — eno pravilo na enem mestu.
2. **`attempts` nima tujega ključa na `quizzes`:** kviz se lahko pobriše
   (preklic, `ADR-019` C), preden so njegovi poskusi preneseni.
3. **Prenesen poskus se ne pobriše takoj** — dokazuje, da je postavka
   odgovorjena, dokler strežnik kviza ne neha vračati. Zato `oznaciPrenesene`
   teče pred `pobrisiKvizeRazen`.

### E. Prenos in usklajevanje (V1-R02, V1-R07, V2-R02, V3-R04, V6-R01)

1. **`410` za arhiviran zapis telefon šteje za uspeh in zapis zbriše.** Brez
   tega bi posnetek, ki je obtičal v `pending`, tam ostal za vedno — z
   delovnega seznama za brisanje je lahko že padel.
2. **Prenos gre prek `File.upload`** (nativni multipart z diska, brez nalaganja
   v pomnilnik JS).
3. **Časovna omejitev 60 s ni okras:** cikel, ki se ne konča, pusti zaporo
   workerja postavljeno in worker je do ponovnega zagona mrtev.
4. **Po *Shrani* se prenos samo sproži, nanj se ne čaka** — sicer bi zaporedno
   slikanje ob nedosegljivem strežniku obtičalo in `ADR-003` bi padel.
5. **Kvizi: najprej poskusi gor, nato seznam dol.** Strežnik kviz reši v isti
   transakciji kot zadnji poskus, zato je seznam po prenosu že brez pravkar
   rešenega kviza.
6. **Poskus, ki ga strežnik posamič zavrne s `422`, si `KviziProvider`
   zapomni za čas zagona** (množica v `useRef`, ne v bazi). Brez tega bi z N
   obtičalimi poskusi vsak obhod poslal 1 + N zahtevkov, za vedno; ob novem
   zagonu se poskusijo znova, da gredo gor sami, ko je vzrok na strežniku
   odpravljen. Razbija se samo ob `422`, ker 401, 403 in 404 niso sodba o
   vsebini (`ADR-020`).
7. **Nerazberljiv odgovor s seznamom kvizov vrže**, ne vrne praznega seznama:
   prazen seznam bi obhod razumel kot „nič več ne čaka" in pobrisal tudi napol
   rešene kvize.
8. **Arhiv: najprej vrstica, nato datoteka, šele nato potrditev.** Potrditev
   pred brisanjem bi pomenila zapis, ki ga strežnik šteje za pospravljenega,
   na telefonu pa ostane. Zapis, ki ga naprava nima, se potrdi takoj —
   potrditev pomeni „tega tu ni več".
9. **`401` ni `failed` in ga izid loči od nedosegljivega strežnika**
   (`Izid.prijavaPotekla`), ker je to edino stanje vrste, ki ga uporabnica more
   odpraviti sama. Odjave ob `401` ni — aplikacija pove, ne ukrepa namesto
   otroka (`ADR-036`, tretji pregled).

## Posledice

- Razlogi so na enem mestu po temi; `01-arhitektura.md` nosi le pravila.
- Sprememba katerega koli pravila zgoraj je nova odločitev in nov ADR.
