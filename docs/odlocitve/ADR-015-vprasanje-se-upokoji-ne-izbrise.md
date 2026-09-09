# ADR-015: Ponovna obdelava vprašanja upokoji, ne izbriše

- **Datum:** 2026-09-09
- **Nastalo pri:** V2-R01 (faza 1, zasnova sestavljalnika kvizov)
- **Status:** Sprejeto
- **Nadomešča:** odločitev **A1** iz `ADR-009` (ponovna obdelava zbriše vsa
  vprašanja materiala). Odločitev **B2** iz `ADR-009` velja naprej.
- **Doda:** zahtevo `V2-R05`, ki mora biti zgrajena pred `V2-R01`

## Kontekst

`ADR-009` je določil, da gumb „Pošlji v obdelavo" skupaj s prejšnjim rezultatom
zbriše **vsa vprašanja materiala**. Isti ADR je to odločitev sam pogojno odprl:
zapisal je, da bo morala zahteva za kviz (takrat `V1-R05`, danes V2) povedati,
ali je to sprejemljivo, in da tega ne sme odkriti naknadno v kodi.

Zdaj je odgovor znan in je **ne**.

`ADR-012` je vprašanju življenje že podaljšal čez brisanje materiala
(`material_id` nullable, `ON DELETE SET NULL`), ker vprašanje nosi statistiko.
Ponovna obdelava pa ga še vedno pobriše. Ko bo `V2-R01` kviz zamrznil in bodo
njegove postavke kazale na `question_id`, bo torej gumb „Pošlji v obdelavo"
tiho razbil **objavljen kviz** — natanko kriterij, ki ga `V2-R01` obljublja.
Isto velja za `V2-R04`: statistika na vprašanje čez leta je smiselna samo, če
vprašanje ohrani identiteto.

## Možnosti

1. **Brisanje ostane; kviz hrani samo kopijo besedila.** Za: na obdelavi ni
   nobenega dela; kviz je berljiv tudi po ponovni obdelavi. Proti: identiteta
   vprašanja se pretrga — isto vprašanje po ponovni obdelavi postane drugo
   vprašanje in zgodovina poskusov nanj se ne veže več. `V2-R04` bi štela dve
   vrsti istega vprašanja kot dve različni.
2. **Vprašanje se upokoji (`retired_at`), nova serija nastane poleg.** Za:
   tuji ključ je vedno veljaven; zgodovina se ne pretrga; trditev iz `ADR-009`
   „material ima največ en veljaven niz vprašanj" ostane resnična — le
   „veljaven" odslej pomeni `retired_at IS NULL`. Proti: vsak bralec vprašanj
   mora odslej filtrirati; tabela raste s podatki, ki niso vidni.
3. **Gumb ob obstoječih kvizih ali ocenah opozori in brisanje potrdi.** Za:
   najmanj dela. Proti: odgovornost se prelaga na človeka ob 22h, dejanje pa
   ostane nepovratno — natanko cena, ki jo `ADR-009` sam navaja kot težo te
   odločitve. Opozorilo ni invarianta.

## Odločitev

**Možnost 2.**

- `questions` dobi stolpec `retired_at TIMESTAMPTZ NULL`. `NULL` pomeni
  veljavno vprašanje.
- Ponovna obdelava vsem dosedanjim vprašanjem materiala postavi `retired_at`
  in šele nato vstavi novo serijo. **Nič se ne briše.** Ostali del prejšnjega
  rezultata (prepis, povzetek, revizijska sled) se še naprej prepiše, kot
  pravi `ADR-009`.
- „Vprašanja materiala" odslej povsod pomeni `retired_at IS NULL`.
  `position` je enolična znotraj **serije**, ne znotraj materiala.
- Dokončno brisanje materiala vprašanj še naprej ne briše — `ADR-012` velja
  naprej in `material_id` gre na `NULL`.
- **Ročnega gumba „upokoji" ni.** Upokojitev je posledica ponovne obdelave, ne
  samostojno dejanje; drugače bi bilo treba odgovoriti, kaj naredi z objavljenim
  kvizom, in to je vprašanje brez potrebe.

## Posledice

- **Kaj to olajša:** kviz sme kazati na `question_id` in kriterij o zamrznjenih
  postavkah je izpolnjiv. `V2-R04` dobi stabilno identiteto vprašanja čez
  ponovne obdelave. Revizijska sled je popolnejša: vidi se, kaj je model vrnil
  prvič in kaj drugič, kar je natanko primerjava, ki jo predvideva `ADR-008`.
- **Kaj to oteži:**
  - Vsaka poizvedba nad `questions` mora filtrirati `retired_at IS NULL`.
    Pozabljen filter se **v svežih testih ne pokaže**, ker ima material takrat
    natanko eno serijo; pokaže se šele pri prvi ponovni obdelavi v produkciji.
    Zato je regresijski test „obdelaj dvakrat, nato preberi vprašanja in
    sestavi kviz" obvezen, ne priporočen.
  - Vprašanj bo skozi leta več, kot jih je vidnih. Pri 5–25 slikah na teden je
    to nepomembno.
  - Admin stran mora povedati, da upokojena vprašanja obstajajo, sicer je
    razlika med „ni vprašanj" in „vsa so upokojena" nevidna. To je kriterij
    `V2-R05`, ne stvar okusa.
- **Migracija:** nov nullable stolpec; obstoječe vrstice ostanejo `NULL`, torej
  veljavne. Brez prepisa podatkov in brez migracije lokalne sheme na telefonu.
- **Na katere zahteve to odslej vpliva:** `V2-R05` (nova, gradi se prva),
  `V2-R01` (zamrznitev postavk), `V2-R04` (statistika). `V1-R03` ostane
  zaključena; njeno vedenje ob ponovni obdelavi popravi `V2-R05`.
