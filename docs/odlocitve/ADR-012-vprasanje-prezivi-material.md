# ADR-012: Vprašanje preživi material; nič se ne briše, vse se upokoji

- **Datum:** 2026-09-07
- **Nastalo pri:** V1-R07 (faza 1–2, pred implementacijo)
- **Status:** Sprejeto
- **Nadomešča:** odločitev **A1** iz `ADR-009` — *„Ponovna obdelava … zbriše …
  vsa vprašanja tega materiala."* Odločitev **B2** istega ADR (brez ključa
  worker miruje) ostane v veljavi nedotaknjena.

## Kontekst

`ADR-009` je zapisal, da ponovna obdelava zavrže prejšnji rezultat skupaj z
vsemi vprašanji, in v isti sapi povedal, zakaj to zapisuje: *„`V1-R05` se mora
odločiti, ali je to sprejemljivo … vendar tega ne sme odkriti naknadno v kodi."*

Zdaj se odloča. Lastnik hoče **statistiko na posamezno vprašanje čez leta** —
kolikokrat je bilo postavljeno in kako težko ji je bilo — da se lahko po vsakem
kvizu z Mašo osebno lotita samo tistih vprašanj, ki so ji bila težka. Ob tem
`ADR-011` uvaja dokončno brisanje materiala.

Obe stvari trčita v isto točko: **vprašanje danes ni trajno.** Ena ponovna
obdelava ali eno dokončno brisanje bi vzela vso zgodovino odgovorov.

## Možnosti

1. **Ostane kot v `ADR-009`.** Za: nič dela. Proti: statistika, ki jo je mogoče
   uničiti z enim klikom, ni statistika.
2. **Vprašanje se upokoji, ne zbriše.** Za: material ima še vedno natanko en
   *aktiven* niz vprašanj, zgodovina pa ostane. Proti: tabela raste in vsaka
   poizvedba mora znati izločiti upokojena.
3. **Verzioniranje serij obdelave** (`materials` + `obdelave` + `questions`).
   Za: popolna sled. Proti: prav tisti razpad na tri tabele, ki ga je `ADR-009`
   zavrnil kot velik del dela za korist, ki je takrat ni bilo.

## Odločitev

**Možnost 2, v obliki enega pravila: nič se ne briše, vse se upokoji.**

- **Vprašanje dobi `retired_at`.** Ponovna obdelava staro serijo upokoji in
  ustvari novo. Prepis, povzetek, prompt, surov odgovor in poraba tokenov se še
  naprej povozijo — tam ni ničesar, kar bi kdo vlekel skozi leta.
- **`questions.material_id` postane `NULL`-abilen z `ON DELETE SET NULL`**, in
  `cascade="all, delete-orphan"` v ORM gre ven. Dvojna kaskada iz `models.py` je
  bila postavljena namenoma; ta ADR jo namenoma odstrani.
- **Vprašanje nosi denormaliziran izvor:** `subject` in `material_taken_at` se
  ob nastanku prekopirata vanj. Tudi brez materiala potem še vedno pove, iz
  katere snovi in katerega dne je. Isti vzorec kot račun, ki prepiše naslov
  kupca, namesto da ga referencira — zapis, ki preživi svojega starša, mora
  nositi svoj kontekst s sabo.
- **Statistika je dnevnik dogodkov, ne števca.** Tabela `question_attempts` z
  vrstico na vsak posamezen odgovor; `id` generira **telefon**. Razlog ni
  čistost: prenos s telefona je *at-least-once*, in ponovljen
  `UPDATE stevec = stevec + 1` tiho pokvari podatke, ponovljen `INSERT` z istim
  UUID pa ne naredi nič. To je isto načelo, ki v `docs/00-namen.md` že velja za
  `materials`. Če se odstotki kdaj izkažejo za počasne, se števci dodajo kot
  predpomnilnik — nikoli kot resnica.
- **Poskus nosi `mode`** (zaenkrat vedno `samoocena`), da je vsaka statistika
  samoopisna od prvega dne. Glej `ADR-014`.

## Kaj se izvede kdaj

| Del | Kje |
|---|---|
| `material_id` nullable, `SET NULL`, brez ORM kaskade, denormaliziran izvor | **V1-R07** — dokončno brisanje iz `ADR-011` tega ne more brez |
| `retired_at`, sprememba ponovne obdelave, `question_attempts` | **V2** |

Do takrat ponovna obdelava vprašanja še vedno zavrže. To je sprejemljivo, ker
statistike takrat še ni in torej ni česa izgubiti — ne pa zato, ker bi bilo prav.

## Posledice

- **Kaj to olajša:** kviz izpred dveh let ostane v celoti berljiv tudi po treh
  ponovnih obdelavah materiala. Dokončno brisanje slike ne uniči znanja, ki je
  iz nje nastalo. Kasnejša uvedba ABC vprašanj (`ADR-014`) ne more razbiti
  ničesar za nazaj, ker se za nazaj nič ne spreminja.
- **Kaj to oteži:**
  - Vsaka poizvedba nad vprašanji mora izločiti upokojena. Kjer se to pozabi, se
    v kvizu tiho pojavi staro vprašanje.
  - Vprašanje brez materiala je v adminu videti kot sirota. Prikaz mora znati
    povedati „izvorna slika je izbrisana", ne pokazati prazne vrstice.
  - Baza raste enosmerno. Pri tem obsegu je to nekaj deset tisoč vrstic na leto
    in ni razlog za čiščenje.
- **Na katere zahteve to odslej vpliva:** vse zahteve o kvizu v V2, `V1-R07`
  (migracija sheme), in `ADR-009`, ki od tu naprej velja samo še v delu B2.
