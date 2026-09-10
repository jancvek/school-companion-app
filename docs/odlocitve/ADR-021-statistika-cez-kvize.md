# ADR-021: Statistika čez kvize — kaj šteje, kako se razvršča in da ni poročanje

- **Datum:** 2026-09-10
- **Nastalo pri:** V2-R04 (faza 1, po vprašanjih lastniku)
- **Status:** Sprejeto
- **Zapira:** razdelek „Odprto / ne vem še" pri `V2-R04` v `docs/verzije/v2.md`
- **Zoži:** `docs/00-namen.md`, „Kaj aplikacija namenoma NI" — *„Ni orodje za
  analitiko ali poročanje staršem ali šoli."*
- **Stoji na:** `ADR-012` (poskus je dogodek), `ADR-014` (samoocena, pravilnost
  se izpelje), `ADR-015` (upokojeno vprašanje ohrani identiteto), `ADR-018`
  (postavka sme kazati na upokojeno vprašanje), `ADR-019` C (poskusi
  preklicanih kvizov obstajajo), `ADR-006` (zaščita `/admin`)

## Kontekst

Osnutek `V2-R04` je imel štiri kriterije in dve odprti vprašanji (privzeto
časovno okno, upokojena vprašanja). Ob razčiščevanju so se pokazala še štiri
mesta, kjer bi izvedba brez odločitve ubrala eno od poti z opazno različnimi
posledicami: kaj pomeni „kako se spreminja skozi leto", kdaj je vprašanje
„vztrajno težko", ali štejejo poskusi preklicanih kvizov in kaj pomeni „vidna
samo lastniku". Poleg tega zahteva dobesedno prebrana nasprotuje stavku v
`docs/00-namen.md`. Lastnik je vseh šest odločil po predlogu.

## Odločitve

### A — Statistika za lastnika ni poročanje

`docs/00-namen.md` pravi, da aplikacija *„ni orodje za analitiko ali poročanje
staršem ali šoli"*. Dobesedno vzeto `V2-R04` temu nasprotuje; namen stavka pa je
bil drug — aplikacija ne sme postati platforma za poročila, ki gredo iz hiše.

Stavek se zoži na: *„Ni orodje za poročanje šoli ali tretjim. Pregled ocen čez
kvize (`V2-R04`) je lastnikov delovni pripomoček za pogovor z Mašo — brez
izvoza, brez PDF in brez knjižnice za grafe."*

Isti vzorec kot `ADR-006`, ki je zožil izključitev „Web vmesnik" v `v1.md`.

### B — Časovna os je šolsko leto; meseci po predmetu, zaporedje pri vprašanju

- **Okno** je šolsko leto, od 1. 9. do 31. 8. v pasu `Europe/Ljubljana`,
  polodprto. Privzeto je **tekoče**; mogoče je izbrati prejšnja in „vse".
- **Po predmetu** tabela po mesecih izbranega šolskega leta: razporeditev ocen
  in delež pravilnih na mesec. V oknu „vse" je vrstica na šolsko leto.
- **Pri vprašanju** zaporedje ocen z datumi, npr. *Nisem vedela 12. 9. → Težko
  3. 10. → Lahko 20. 11.* — iz njega se vidi, ali se ga je naučila.
- **Čas poskusa** je `answered_at` (trenutek ocene), ne `received_at`: ta se
  zamakne, kadar je bil telefon več dni brez omrežja. Premik ure telefona na
  mesečni ravni ne šteje.

Zavrnjeno: samo filter od–do. Najmanj dela, a trenda ne pokaže — primerjava
bi bila na operaterju.

### C — „Vztrajno težko" je delež, ne zadnja ocena

Vprašanja se razvrstijo po deležu ocen *Nisem vedela* + *Težko* med vsemi
poskusi v oknu, najtežja zgoraj. **Na vrhu so vprašanja z vsaj dvema
poskusoma**, pod njimi v svojem razdelku tista z enim — en sam poskus je že
rezultat kviza (`V2-R03`) in še ni „vztrajno".

- Za: delež pove, da je bilo vprašanje težko čez čas, kar zahteva pravi.
- Proti: vprašanje, ki je bilo trikrat *Nisem vedela* in nato *Lahko*, ostane
  visoko, čeprav se ga je naučila. Zato zaporedje ocen iz (B) — zadnja ocena je
  vidna ob vsakem vprašanju, le razvrstitev ne teče po njej.

### D — Upokojena vprašanja štejejo zraven, z oznako

Po `ADR-015` je vprašanje iz nove serije **nova identiteta**, tudi kadar je
besedilo enako; zgodovina poskusov se nanj ne prenese. Povezovanja po besedilu
ni — bilo bi hevristično in bi `ADR-015` obšlo po stranskih vratih.

Upokojeno vprašanje s poskusi zato:

- **šteje** v seštevek snovi in predmeta — poskus je dejstvo o tem, kar je
  Maša odgovorila (`ADR-012`), in izpust bi po vsaki ponovni obdelavi tiho
  spremenil številke snovi;
- je v seznamu vprašanj **z oznako „upokojeno"**.

Cena, ki jo je treba vedeti: ponovna obdelava snovi pretrga zgodovino
**posameznega vprašanja** — novo vprašanje začne pri nič. Seštevek snovi se ne
pretrga.

### E — Poskusi preklicanih kvizov štejejo

Ocena je Mašin resničen odgovor; preklic pove, da je bil kviz napačno
sestavljen, ne da odgovor ni obstajal. V zaporedju ocen je vnos iz preklicanega
kviza označen.

To se **namenoma razhaja** z `ADR-016` B in `ADR-017` B, kjer preklican kviz za
„snov je bila v kvizu" ne šteje. Tam gre za vprašanje sestave (ali naj se snov
spet ponudi), tu za vprašanje dejstva (kaj je odgovorila). Nobena od obeh
odločitev s tem ne preneha veljati.

### F — „Vidna samo lastniku" pomeni: samo pod `/admin`

Statistika živi samo pod predpono `/admin`, nobena pot z API ključem je ne
vrača in na telefon ne pride. Zaščita ostane takšna, kot jo določa `ADR-006` B1.

Cena, ki jo je treba vedeti: Mašin telefon je v omrežju Tailscale (sicer ne bi
mogel prenašati slik) in bi `/admin` v brskalniku lahko odprl. To velja za cel
`/admin` od `V1-R04` in ni novo. Če se to kdaj izkaže za težavo, je pot
`ADR-006` B3 (geslo in CSRF žeton) — kot svoja zahteva za cel `/admin`.

## Posledice

- **Kaj to olajša:** statistika ne potrebuje nove tabele, stolpca ne migracije —
  vse se izpelje iz obstoječega dnevnika ob branju. Pravila, kaj šteje, so ena
  (vse, kar je bilo ocenjeno v načinu `samoocena`), zato ni vej, ki bi jih bilo
  treba razlagati.
- **Kaj to oteži:**
  - Razdelek z večkrat postavljenimi vprašanji bo sprva prazen ali kratek.
    Sestavljalnik vzame prvih N po `position` (`ADR-016` D), *Nova snov* pa
    obkljuka samo snov, ki v kvizu še ni bila — isto vprašanje pride znova le,
    če ga lastnik vzame z *Ročno izbiro* ali dnevnim vstopom.
  - Ponovna obdelava pretrga zgodovino posameznega vprašanja (D).
  - Odstotek je samoocena; kjerkoli se prikaže, stoji zraven, čigava trditev je
    (`ADR-014`).
- **Na katere zahteve to odslej vpliva:** `V2-R04`. Predlog „utežen izbor
  vprašanj" iz `docs/verzije/v2.md` bi stal na istih pravilih štetja.
