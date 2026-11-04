# ADR-072: Strežnik — shema, lastništvo in migracije (zapis za nazaj)

- **Datum:** 2026-11-04
- **Nastalo pri:** V6-R05 (zapis za nazaj; izvorne zahteve so pri točkah)
- **Status:** Sprejeto — zapis za nazaj

## Kontekst

Razlogi iz `docs/01-arhitektura.md`, razdelek o shemi PostgreSQL, ki nimajo
lastnega ADR-ja ali jih ADR navaja brez razloga (`ADR-070`). Vse je izvedeno.

## Odločitve in razlogi

### A. Splošno

1. **`id` je `VARCHAR` in ne `UUID`, čas `DateTime(timezone=True)`**, ker mora
   ista shema stati nad Postgresom (produkcija) in nad SQLite (testi).
2. **Brisanje gre v obratnem vrstnem redu kot sprejem: najprej vrstica, nato
   datoteka** (V1-R04). Vrstica brez datoteke je pokvarjen vnos, ki ga operater
   vidi; datoteka brez vrstice je nevidna sirota, ki stane samo prostor. Isto
   velja na telefonu.
3. **Slika gre najprej v `<mapa družine>/.tmp/` in se premakne atomarno;
   vrstica nastane šele za datoteko** (V1-R02). Prekinjen prenos zato ne pusti
   polovične slike tam, kjer jo obdelava išče kot celo.

### B. Družina in otrok (V3-R01, V3-R07)

1. **Izolacija je lastnost kode** (`ADR-025`). Začasna izbira „edina družina v
   bazi" (`ADR-029` A) je odpadla skupaj z API ključem (`ADR-036` F); druga
   družina v bazi zato ne ustavi več ničesar, kar je bil pogoj za `V3-R05`.
2. **`POST /quiz-attempts` s tujim `id` poskusa vrne `500`** (dvakrat
   `IntegrityError`). Obvoz s poizvedbo brez družine ni dovoljen, drugačen izid
   pa bi bil nova odločitev o pogodbi s telefonom. Brez ponarejanja se ne zgodi.
3. **Družina je meja lastništva, otrok meja pomena:** v družini z več otroki
   „kviz" in „statistika" brez njega ne povesta nič. Zato je **otrok argument
   poizvedbe, družina argument konstruktorja** — družina je meja izolacije,
   otrok izbira pogleda znotraj nje.
4. **Ime otroka uveljavljajo vrata, ne klicna mesta** (`_imena`,
   `_ime_otroka`, `Naslovljenec.ime_za_prikaz`), da nova stran z imenom pade
   v `TestImenaPriEnemOtroku` in ne v pregledu (`ADR-039` F3).

### C. Snov in vprašanja (V1-R02, V1-R03, V1-R07, V2-R05, V3-R10)

1. **Stolpci V1-R03 na `materials` so `NULL`-abilni**, ker so morale vrstice iz
   V1-R02 migracijo prestati nedotaknjene.
2. **Vprašanja imajo svojo tabelo in ne polja JSON**, ker V2-R02 ocene veže na
   `question_id`.
3. **Do V2-R05 je ponovna obdelava zavrgla vprašanja**; `ADR-015` jih upokoji.
   `retired_at` je svoja os (vzorec `archived_at`, `ADR-011`); `position` je
   enolična znotraj serije, ker se z vsako obdelavo začne znova; serija se
   prepozna po skupnem `retired_at`, brez stolpca za oznako.
4. **Do V1-R07 je bila kaskada nastavljena dvakrat** (`ondelete="CASCADE"` in
   `cascade="all, delete-orphan"`); `ADR-012` je obe odstranil. ORM ob brisanju
   materiala nulira `material_id` tudi na SQLite, kjer tuji ključi niso
   uveljavljeni, zato testi dokazujejo isto kot produkcija.
5. **Tri zveze na `questions` in nobena z imenom `questions`:**
   `vsa_vprasanja` je edina pisljiva, ker nosi vstavljanje nove serije in
   nuliranje `material_id` — filtrirana zveza upokojenih ne bi videla in ti bi
   ostali z visečim ključem; `veljavna_vprasanja` je to, kar `ADR-015` misli z
   „vprašanja materiala"; `upokojena_vprasanja` je za števec. Filtrirani sta
   `viewonly=True`, sicer bi SQLAlchemy tri zveze nad istim ključem razumel kot
   tri lastnike. Zveza je bila **preimenovana in ne le filtrirana**, ker je
   nevtralno ime past: pozabljen filter nad svežo bazo ni viden (material ima
   eno serijo). Preimenovanje pomete čez bralce z `mypy`.
6. **`_upokoji_vprasanja` ne commita** (klicatelj commita, da sta upokojitev in
   nova serija ena transakcija) in teče s `synchronize_session="fetch"`, da žig
   dobijo tudi predmeti, naloženi v isti seji.
7. **`subject` in `material_taken_at` sta denormalizirana**, da vprašanje brez
   materiala še pove, iz katere snovi in katerega dne je. `subject` ni
   zamrznjen: premik snovi ga popravi (`ADR-040` B1).

### D. Kvizi in poskusi (V2-R01, V2-R02)

1. **Kviz nima stolpca `status`**; stanje se izpelje iz `canceled_at` in
   `solved_at`, po vzorcu `ADR-011`/`ADR-015`. Osi sta neodvisni, ker telefon
   lahko da poskuse, preden izve za preklic (`ADR-019` C).
2. **`solved_at` postavi strežnik sam**, v transakciji poskusa, ki zapolni
   zadnjo postavko, in ga ne premakne več; čas je strežnikov, časi s telefona so
   pri poskusih. Prišel je z V2-R02, ker ga je šele ta znala napolniti
   (`ADR-017` C).
3. **`quiz_items → quizzes` je edina kaskada brisanja v shemi:** postavka brez
   kviza nima pomena, za razliko od vprašanja, ki nosi statistiko. Kvizov se ne
   briše — kaskada je tam, da shema pove resnico.
4. **`QuizItem.question` je enosmerna.** Povratna bi ORM-ju dala pot, po kateri
   bi ob brisanju vprašanja nulil `question_id` — vprašanja pa se ne brišejo,
   zato bi bila to mrtva pot z živimi posledicami.
5. **FK poskusa na postavko je brez kaskade in brez `SET NULL`:** poskus nosi
   statistiko, zato naj baza brisanje kviza s poskusi raje zavrne. `question_id`
   na poskusu ni, ker je izpeljiv.

### E. Urnik (V3-R09)

1. **Enoličnost veljavnega urnika uveljavlja ena pot pisanja v eni
   transakciji**, ne delni indeks — tega bi bilo treba zapisati dvakrat, za
   SQLite in Postgres (`ADR-041` C). Zamenjava nosi en trenutek
   (`replaced_at` starega = `confirmed_at` novega), zato veljavnost stoji
   izključno na osi.
2. **Slika urnika ni snov** in nikoli ne pride v `materials`, sicer bi se
   pojavila v izbirniku kvizov, statistiki in na strani predmeta.
3. **Urnik nima revizijske sledi**, ker potrjen urnik ni odgovor modela — starš
   ga vmes popravi.

### F. Migracije

1. **`0003_arhiv`** gre na SQLite skozi `batch_alter_table` s `copy_from`, ker
   `ALTER` tujega ključa tam ne obstaja.
2. **`downgrade` migracij, ki dokončno izgubijo podatek** (`0004` upokojitev,
   `0005` kvize, `0006` poskuse, `0009` pripis otroka, `0010` urnike, `0011`
   stanje družine, `0013` preizkuse, `0014` poverilnic otrok ne vrne), je
   smiseln samo nad bazo, kjer tega podatka še ni. `0006`: ponoven `upgrade` bi
   kvize naredil nerešene in telefon bi jih prenesel znova. `0005` spusti
   najprej otroka, sicer bi FK na Postgresu brisanje zavrnil.
3. **`0007_druzine`:** premik slik ni del transakcije baze, zato je
   idempotenten (vir je in cilja ni → premakni; vira ni → pusti) in `id`
   družine Cvek je stalen — ponovni zagon po prekinitvi pride do istega stanja.
   `IMAGES_DIR` je obvezen, kadar baza ni prazna, preverba je pred prvim DDL.
   Če `downgrade` pade po premiku slik, se pozdravi s ponovnim `downgrade`.
4. **`0014_povezava_telefona`:** seje otrok ostanejo, ker visijo na `users`, ne
   na poverilnici.
5. **`0015_odobritev_druzine`:** `downgrade` se ne izvede, dokler obstaja
   družina, ki ni `approved` — brez stolpca bi čakajoča in zavrnjena tiho
   postali polnopravni.
6. **`alembic/env.py` bere `DATABASE_URL` samo, kadar url ni že izrecno
   nastavljen**; obratna prednost bi pomenila, da se testi migracije povežejo
   na živo bazo.

## Posledice

- `01-arhitektura.md` nosi tabele, invariante in tabelo migracij; razlogi so tu.
