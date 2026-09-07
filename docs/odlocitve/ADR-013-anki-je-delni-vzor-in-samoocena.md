# ADR-013: Anki je delni vzor; odgovarjanje je štiristopenjska samoocena

- **Datum:** 2026-09-07
- **Nastalo pri:** V1-R07 (faza 1–2), velja za V2
- **Status:** Sprejeto
- **Zapira odprto vprašanje:** *„Kaj pomeni ,odgovori`"* iz `V1-R05`

## Kontekst

`V1-R05` je puščala odprto, kaj se ob odgovoru sploh zgodi: pokažemo odgovor
brez presoje, shranimo njen odgovor brez presoje, ali njen odgovor oceni model
(dodaten plačan klic). Brez odgovora na to ni mogoče povedati, kaj je „pravilno",
in brez tega ni statistike.

Namen, ki ga je lastnik postavil, je bolj določen od same statistike: **po
kvizu hoče seznam vprašanj, ki so bili Maši težki, da gresta skozi njih skupaj.**
Kviz ni ocenjevanje, ampak priprava na pogovor.

## Možnosti

1. **Pokaži odgovor, brez presoje.** Za: nič dela. Proti: ni podatka, iz katerega
   bi nastal seznam težkih vprašanj.
2. **Shrani njen prosti odgovor, brez presoje.** Za: vidiš, kaj je napisala.
   Proti: desetletnica tipka odgovore na telefonu; trenje ubije navado.
3. **Model presodi njen odgovor.** Za: objektivno. Proti: plačan klic na vsak
   odgovor in kviz, ki brez omrežja ne dela — proti načelu iz `docs/00-namen.md`.
4. **ABC izbira, pravilnost določi sistem.** Za: objektivna meritev, primerna za
   tisk. Proti: potrebuje distraktorje; ti so težki, modeli so pri njih šibki
   (tipično „preočitno napačen" ali „pomotoma tudi pravilen"), ugibanje pri treh
   možnostih pa da 33 % osnovno vrednost, zaradi česar odstotek ni primerljiv s
   samooceno.
5. **Samoocena po Ankijevem vzorcu.** Za: en dotik, brez tipkanja, deluje brez
   omrežja, zastonj; priklic iz prazne glave zapomni bolje kot prepoznavanje med
   ponujenimi možnostmi. Proti: samoocena desetletnice ni zanesljiva meritev —
   „sem vedela" po tem, ko odgovor že vidiš, je sistematično prevelika številka.

## Odločitev

**Možnost 5**, s štirimi stopnjami, in **možnost 4 ostane zapisan predlog za
nadgradnjo**, ne koda.

**Lestvica ima štiri gumbe:** `Nisem vedela` · `Težko` · `Srednje` · `Lahko`.
Ženska oblika, ker je uporabnica ena. Trije gumbi ne bi bili dovolj: brez ABC-ja
ni nikogar, ki bi določil pravilnost, in „težko" bi hkrati pomenilo „vedela sem
s trudom" in „nisem vedela". Prvi gumb je pravilnost, ostali trije težavnost.

**Gumb je hkrati „naprej".** En dotik da oba podatka in nobeno vprašanje ne
ostane neocenjeno, zato pregled rezultata nikoli ni na pol prazen.

**Njen prosti odgovor se ne tipka in ne shranjuje.** Zaporedje je: vprašanje →
*Pokaži odgovor* → ocena.

**Ocena se hrani surova, pravilnost se izpelje** (`ocena != 'nisem_vedela'`) in
se **ne** shranjuje. Ocena je dejstvo, pravilnost je interpretacija. Če se kdaj
odločimo, da tudi „Težko" šteje kot neznanje, izpeljava velja za nazaj, shranjen
stolpec pa bi lagal o vsem, kar je že zapisano.

**Hrani se trajanje** (`shown_at`, `answered_at`). Vprašanje, označeno „Lahko"
dve sekundi po razkritju odgovora, je mehak namig, da ga velja vseeno preleteti.
Ni nadzor in ni kriterij — je stolpec, brez katerega tega nikoli ne bi bilo
mogoče videti za nazaj.

**Pregled rezultata kviza je namen, ne stranski produkt.** Vprašanja razvrščena
po oceni (najtežja zgoraj), pri vsakem pravilen odgovor in povezava na izvorno
sliko in prepis, ter tisk samo izbranih ocen.

### Anki kot vzor — kaj prevzemamo in kaj ne

| Prevzemamo | Ne prevzemamo |
|---|---|
| `revlog`: ena vrstica na vsak odgovor je resnica, števci so kvečjemu predpomnilnik | algoritem razporejanja (SM-2, FSRS) — kvize sestavlja starš, ne algoritem |
| samoocena kot način odgovarjanja | intervali, zapadlost, „due" kartice |
| trajanje odgovora | vtičniki, tipi zapiskov, medpomnilnik kartic |
| zaporedna številka spremembe namesto ure za sinhronizacijo (`usn`) | |

Meja je del odločitve: kar od Ankija kdaj prevzamemo, mora priti kot zahteva,
ne kot podobnost.

### ABC kot predlog za nadgradnjo

Zavrnjen za zdaj, zapisan zato, da se ve, da je premišljen. Kasnejša uvedba je
čista migracija in ne prepis:

- nova tabela `question_options(id, question_id, text, is_correct, position, retired_at)`;
- nov `NULL`-abilen `question_attempts.chosen_option_id`;
- distraktorji iz **ločenega, samo tekstovnega klica** (vprašanje + odgovor +
  prepis) — deluje retrogradno na vseh obstoječih vprašanjih, brez ponovne
  obdelave slike in torej brez upokojitve vprašanj. `ADR-008` je treba takrat
  dopolniti: meja je „en modul govori z OpenAI", ne „en klic";
- statistiki obeh načinov se **nikoli** ne povprečita.

**Da to kasneje res ne bo prepis, morata veljati dve stvari že od prve zahteve
V2:** poskus je **dogodek** (vrstica na vsak odgovor), ne ocena na vprašanju; in
poskus nosi stolpec **`mode`**, zaenkrat vedno `samoocena`. Vse ostalo se doda
kasneje, zato se prazna tabela možnosti zdaj **ne** ustvari.

## Posledice

- **Kaj to olajša:** kviz deluje brez omrežja in brez dodatnega plačanega klica.
  Seznam težkih vprašanj nastane sam od sebe iz načina odgovarjanja.
- **Kaj to oteži:**
  - Odstotek pravilnih je samoocena in ne meritev. Kjerkoli se prikaže, mora biti
    jasno, čigava trditev je.
  - Pojem „Težavnost" v `docs/00-namen.md` se spremeni iz treh stopenj v štiri.
  - Maša ima teoretično razlog pritisniti „Lahko", da se izogne pogovoru. Zoper
    to ni tehnične rešitve; trajanje je edini mehak signal.
- **Na katere zahteve to odslej vpliva:** vse zahteve o kvizu v V2.
