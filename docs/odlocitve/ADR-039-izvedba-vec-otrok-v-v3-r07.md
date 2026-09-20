# ADR-039: Izvedba „več otrok v družini" v V3-R07; naslovljenec kviza, lastnik snovi in poskusa

- **Datum:** 2026-09-20
- **Nastalo pri:** V3-R07 (fazi 1 in 2)
- **Status:** Sprejeto
- **Stoji na:** `ADR-025` (družina je lastnik, izolacija je lastnost kode),
  `ADR-021` (kaj statistika šteje in kako razvršča), `ADR-019` (en poskus na
  postavko, prvi zmaga), `ADR-036` (lastnik lokalnega zapisa na telefonu,
  starš se v aplikacijo ne prijavi), `ADR-038` (vzorec zavrnitev in vmesnih
  potrditev pri članih družine), `ADR-004` (migracije lokalne sheme)
- **Zoži:** `ADR-017` B — „snov je bila v kvizu" odslej šteje **po
  naslovljencu**, ne čez celo družino; glej G.
- **Dopolnjuje:** `ADR-019` E — „prvi zmaga" dobi drugi primer tihega
  sprejema: poskus za kviz, naslovljen na drugega otroka; glej D.
- **Izpolnjuje:** odloženo nalogo iz `ADR-036` C in iz
  `docs/01-arhitektura.md` („V V3-R04 je kviz še last družine; `V3-R07` to
  reši tam.")

## Kontekst

Do te zahteve je bil **kviz last družine**. V družini z enim otrokom je to
brez posledic in prav zato se ni videlo, da manjka: „kviz" je pomenil „kviz za
Mašo", ker druge možnosti ni bilo. Z `V3-R06` starš odpre račun drugemu
otroku, in od tistega trenutka naprej „kviz", „statistika" in „snov" brez
otroka ne pomenijo ničesar.

`V3-R01` je dal vsakemu podatku družino, `V3-R04` pa je na **telefonu** dal
vsakemu lokalnemu zapisu lastnika (`materials.user_id`, `attempts.user_id`).
Na strežniku lastnika ni nikjer. Ta zahteva je druga polovica istega dela in
edina v `V3`, ki spremeni obstoječe vedenje.

Kriteriji zahteve so v `docs/verzije/v3.md`. Ne povedo pa sedmih stvari, ki
spremenijo, kaj pride v kodo: kaj stori družina brez otroka, ali izbirnik
pozna „vse otroke", kaj naredi migracija s kvizi in snovjo, kaj se zgodi s
poskusom za tuj kviz, ali je v obsegu tudi telefon, katere admin strani dobijo
razsežnost otroka, in po čem se šteje „snov je bila v kvizu". Vse to je faza 1
naslovila; dogovor je spodaj.

## Odločitve

### A — naslovljenec je obvezen; družina brez otroka kviza ne sestavi

`quizzes.child_id` je `NOT NULL`. Kviz brez naslovljenca ne sme obstajati:
prav ta stolpec je razlog te zahteve in `NULL`-abilen bi pomenil, da „kviz za
nikogar" ostane veljavno stanje, ki ga mora znati obravnavati vsaka poizvedba
za njim.

Posledica je, da družina **brez aktivnega otroka** kviza ne more objaviti.
Zato:

1. razdelek „Kvizi" na `/admin` takrat vstopov v sestavljalnik **ne ponudi**
   in na njihovem mestu pove, naj starš najprej doda otroka na
   `/admin/family`;
2. pot, poklicana neposredno, vrne **409** z istim besedilom.

Oboje odloči **isto pravilo** — vzorec `ADR-038`: dejanja, ki bi bilo
zavrnjeno, seznam sploh ne ponudi, in gumb, ki ga stran ne izriše, ni
varovalka.

Koda je `409` in ne `403`: to ni dejanje, ki ne bi bilo tvoje (`403` po
`ADR-038`), ampak stanje družine, ki tega dejanja ta hip ne dopušča.

Sestavljalnik ponudi samo **aktivne** otroke. Kviz, ki je že naslovljen na
otroka, ki je pozneje deaktiviran, ostane nedotaknjen — nič se ne briše
(`ADR-011`, `V3-R06`); le rešiti ga ni mogoče, ker se ta otrok ne more
prijaviti.

### B — izbirnik otroka nima možnosti „vsi otroci"

1. **Privzeto skupno, z možnostjo zožitve na enega otroka.** Za: starš vidi
   celotno družino na enem mestu. Proti: privzeti pogled sešteje dva otroka v
   številko, ki ne odgovori na nobeno vprašanje — delež *Nisem vedela* čez
   Mašo in njenega brata ni podatek o nobenem od njiju.
2. **En otrok naenkrat, privzeto prvi po prikaznem imenu.**

**Izbrano: B2.** `ADR-021` A pravi, da je statistika *„lastnikov delovni
pripomoček za pogovor z Mašo"* — pogovor teče z enim otrokom. `V3-R09` bo
manjke z urnika računal po otroku in po **njegovem** urniku, kjer skupni
pogled sploh ni definiran; en vzorec za obe strani je vreden več kot ena
dodatna možnost.

Izbira potuje kot `?otrok=<id>`. Neznan ali **tuj** `id` je **404** z istim
besedilom kot neobstoječ — obstoj tujega računa ni podatek, ki bi ga starš
smel dobiti (`V3-R06`, `ADR-038`).

To se namenoma razhaja z obema obstoječima praviloma za neveljaven parameter:
statistika nerazberljiv `?leto=` tiho pade na tekoče leto, `/admin/days` pa
neveljaven `?dan=` zavrne s `400` (`ADR-023`). Razlog za tretje pravilo je, da
`otrok` ni ne okno nad istimi podatki ne datum, ampak **identiteta podatkov**,
in za identiteto v tem projektu že obstaja pravilo — `404`.

Pri družini z **enim** otrokom se izbirnik ne izriše (kriterij zahteve:
izbirnika, ki nima česa izbirati, ni). Podatek v bazi je zapisan enako; razlika
je samo v vmesniku.

### C — migracija pripiše edinega otroka družine in se sicer ustavi

`child_id` je `NOT NULL` na `materials`, `quizzes` in `question_attempts`.
Kriterij zahteve imenuje samo poskuse („obstoječe pripiše Maši"); naslovljenec
kviza in lastnik snovi sta ista stvar in ista migracija.

Pravilo je **„edini otrok družine"**, ne „Maša" in ne „prvi po `created_at`":
ime otroka v migraciji bi bilo ime produkcijske vrstice v kodi.

Družina z **nič ali več kot enim** otrokom migracijo **ustavi z razlago v
slovenščini** in ne naredi ničesar. Dve zavrnjeni možnosti in zakaj:

- *ugani (npr. najstarejši otrok)* — tiho bi pripisala tuje odgovore napačni
  osebi, in to je natanko podatek, ki ga potem nihče ne zna popraviti;
- *pusti `NULL`* — stolpec potem ne more biti `NOT NULL` in A odpade.

Na produkciji je danes ena družina (Cvek) z enim otrokom (Maša), zato je
pravilo enoumno in migracija teče.

`downgrade` stolpce spusti. **Dokončno izgubi pripis otroka** — nobene vrstice
ne izgubi, po istem vzorcu kot `0004` (izgubi upokojitev) in za razliko od
`0005` (izgubi cele kvize). Vrnitev čezenj je smiselna samo nad bazo z eno
samo družino z enim otrokom.

### D — poskus za tuj kviz se sprejme in ne zapiše

Po tej zahtevi `GET /quizzes/pending` vrača samo kvize prijavljenega otroka.
Poskus za kviz, naslovljen na **drugega** otroka, zato nastane samo iz
zastarelih lokalnih podatkov na skupnem telefonu. Tri poti:

1. **`422`.** Po `ADR-020` telefon paket razbije in pošlje poskuse posamič;
   zavrnjeni obtiči do naslednjega zagona aplikacije in nato spet, za vedno.
2. **`200`, ne zapiše se, ne šteje v `recorded`.**
3. **Zapiši ga z otrokom, ki je res odgovoril.** Po `ADR-012` je poskus
   dejstvo. Proti: v statistiki otroka B se pojavi kviz, ki ni njegov, in
   `ADR-021` razvrstitev bi mešala dve osebi.

**Izbrano: D2.** To je natanko obnašanje, ki ga `ADR-019` E že predpisuje za
drugi poskus iste postavke, in iz istega razloga: stanje nastane ob ponovni
namestitvi ali menjavi uporabnika, telefon pa ne sme obtičati (`ADR-004`).

Cena, ki jo je treba vedeti: tak poskus se **tiho izgubi**. Nastane lahko le
tako, da je otrok B odgovoril na vprašanje kviza otroka A na skupnem telefonu
— torej odgovor, ki v statistiki nobenega od njiju nima pomena.

### E — telefon je v obsegu; lokalna shema gre na 5

`pobrisiKvizeRazen` lastnika že pozna (`ADR-036` C), `cakajociKvizi`,
`najdiKviz` in `postavkeKviza` pa ne filtrirajo **nič**. Na skupnem telefonu
zato otrok B vidi kvize otroka A — tiste, ki so ostali, ker na njih visi
neprenesen tuj poskus — in v njih postavke, ki so zanj videti odgovorjene.

`docs/01-arhitektura.md` to nalogo izrecno odlaga na to zahtevo. Zato:

- lokalna migracija **5** doda `quizzes.user_id` (indeksiran, `NULL`-abilen,
  isti vzorec kot migracija 3);
- `cakajociKvizi`, `najdiKviz` in `postavkeKviza` filtrirajo po lastniku, po
  istem pravilu `user_id IS ?` kot vse ostalo (velja tudi za neprijavljeno
  aplikacijo);
- zamrznjena kopija `SHEMA_VERZIJE_4` pride v `__tests__/test-database.ts`
  (`ADR-004`: test migracije ne sme teči nad shemo iz kode);
- zahteva se preizkusi **na napravi z APK iz te veje** (`ADR-010`, merilo
  dokončanosti).

`quizzes.user_id` je `NULL`-abilen in ne `NOT NULL`: kviz, ki je na telefon
prišel pred to migracijo, lastnika nima, posvoji pa ga ista pot kot posnetke
(`ADR-036`, „posvoji vsaka razrešena seja"). `NOT NULL` bi zahteval ugibanje v
migraciji na napravi, kjer ni nikogar, ki bi ga vprašal.

### F — razsežnost otroka dobijo tri strani, oznako pa štiri

**Izbirnik otroka** (`?otrok=`, po B): `/admin/days`, `/admin/statistics` in
`/admin/statistics/subjects/{koda}`.

**Samo oznako z imenom otroka, brez izbirnika:** stran snovi
(`/admin/materials/{id}`), stran predmeta (`/admin/subjects/{koda}`), arhiv
(`/admin/archive`) in stran kviza (`/admin/quizzes/{id}`, kjer je naslovljenec
en sam in izbirati ni česa).

**Ne spremeni se:** pregled `/admin` s števci po predmetih. Števec pove, koliko
snovi ima družina pri predmetu, in to ostane res.

Oznaka se izriše **samo, kadar ima družina več kot enega otroka** — isto
pravilo kot za izbirnik. Družina z enim otrokom ne dobi imena na vsako vrstico,
ker tam ne pove ničesar.

„Zgodovina" iz kriterija zahteve je po `docs/00-namen.md` **zaslon na
telefonu**, in ta po `V3-R04` že filtrira po lastniku (`listBySubject`). Nove
zahteve tam ni; zgornji seznam je branje kriterija, ki pokrije admin poglede
na preteklo snov, ne da bi izumil filtre, ki jih ne zahteva nihče.

### G — „snov je bila v kvizu" se šteje po naslovljencu

`ADR-017` B pravi, da vstop *Nova snov* obkljuka snov, katere nobeno veljavno
vprašanje ni v nepreklicanem kvizu. Doslej je bilo to čez celo družino, ker
druge možnosti ni bilo.

Odslej se šteje **po naslovljencu**: snov, iz katere je bil sestavljen kviz za
otroka A, je za otroka B še vedno „nova".

Brez tega bi *Nova snov* za drugega otroka skrila natanko tisto snov, ki jo
kriterij zahteve izrecno dovoli uporabiti (*„starš lahko iz snovi enega otroka
sestavi kviz za drugega"*) — in starš bi moral vedeti, da mora uporabiti
*Ročno izbiro*, da bi prišel do nje.

Posledica, ki jo je treba izvesti: **naslovljenec mora biti znan pred
seznamom**, ne šele ob objavi. Zato je polje na **vrhu izbirnika** in skozi
predogled potuje v skritih poljih, kot vse ostalo stanje izbora (`ADR-016` C:
predogled ničesar ne shrani). Pri enem otroku je polje izpolnjeno samo in se
ne izriše.

`ADR-017` B s tem ne preneha veljati — preklican kviz še vedno ne šteje in
nova serija vprašanj je še vedno „ni bila v kvizu". Zoži se samo obseg
štetja.

Vprašanja ostanejo **last družine** in ne otroka; to zahteva kriterij sam in
je zavestna izbira, ne posledica. `questions.child_id` ne obstaja.

## Posledice

- **Kaj to olajša:** `V3-R09` dobi vzorec izbire otroka, na katerega se lahko
  sklicuje, in snov, ki že nosi otroka — brez tega urnik kot last otroka ne bi
  imel na kaj vezati manjkov. `V3-R05` dobi še eno pot, ki jo mora pokriti
  regresijski test tesnjenja, in ta pot zdaj obstaja.
- **Kaj to oteži:**
  - Nastane **drugi** razred napake, ki ga baza z enim otrokom ne pokaže —
    tako kot `ADR-025` uvaja enega za družino. Vsak test nad družino z enim
    otrokom je od zdaj nepopoln enako, kot je test nad eno družino.
  - Star APK neha pravilno delovati: pogodba `GET /quizzes/pending` se zoži.
    Star APK sicer ne pade — dobi samo kvize prijavljenega otroka, kar je
    pravilno — a njegov seznam še vedno kaže tuje lokalne kvize, dokler ni
    nameščen nov. Na produkciji je to nevidno, dokler ima družina enega otroka.
  - Statistika ima odslej dve osi (predmet in otrok), kar pomeni, da je vsako
    število na teh straneh odvisno od izbire, ki je prej ni bilo.
- **Na katere zahteve to vpliva:** `V2-R01` (naslovljenec v izbirniku, G),
  `V2-R02` (zožena pogodba, D), `V2-R03` (oznaka naslovljenca), `V2-R04` in
  `V2-R07` (izbirnik otroka, B in F), `V3-R01` (tesnjenje dobi nove primere),
  `V3-R09` (izbira otroka sledi B).
