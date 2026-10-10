# ADR-032: Delovni list je entiteta, Word je njen izvoz

- **Datum:** 2026-09-15
- **Nastalo pri:** V4 (pred verzijo)
- **Status:** Nadomeščeno z `ADR-053` (2026-10-10) — delovni listi so
  zavrženi, V4 je verzija preizkusov

## Kontekst

Najcenejša izvedba delovnega lista je predogled kviza (`ADR-016`): klikneš,
počakaš, dobiš datoteko, aplikacija pozabi. Ta izvedba pa ne zna treh stvari,
ki jih lastnik hoče: ponovno natisniti isti list, zapisati, kako je šlo, in
preprečiti, da čez tri tedne iz iste snovi nastanejo skoraj iste naloge.

Hkrati pa je Word napačno mesto za resnico. Če je datoteka edini zapis, potem
vsak popravek pomeni novo generiranje, vsebine ni mogoče pregledati pred
tiskom, in razlika med dvema različicama ni vidna.

## Možnosti

1. **Generiraj in pozabi** — Za: nič sheme, nič hrambe. Proti: brez zgodovine,
   brez opomb, brez ponovnega tiska; zanka med listi ne obstaja.
2. **Entiteta s strukturiranim JSON telesom** — Za: natančen izris v Word,
   naloge kot polja. Proti: lastnik ne more sam popraviti tipkarske napake;
   razlika med dvema različicama JSON-a je neberljiva; en sam pokvarjen JSON
   iz modela ubije iteracijo.
3. **Entiteta z markdown vsebino** — Za: lastnik bere in popravlja sam;
   razlika je berljiva vrstica za vrstico; nekoliko čuden markdown je še vedno
   uporaben. Proti: izris v Word terja dogovorjene oznake, ne polj.

## Odločitev

**Delovni list je entiteta, njena vsebina je markdown, Word pa izvoz.**
(možnost 3)

**A. Trije statusi, brez četrtega.** `osnutek` → `pripravljen` → `arhiviran`.
`osnutek`: vsebina obstaja, dokumenta še ne. `pripravljen`: dokument je
ustvarjen. `arhiviran`: list je pospravljen (`ADR-011`, nič se ne briše).
Status „generiranje teče" ne obstaja — zapis lista nastane šele, ko je vsebina
tu. Spodletelo generiranje zato ne pusti ničesar za sabo in ne terja statusa
`spodletel`, ki bi ga bilo treba ponavljati.

**B. Med potrjeno vsebino in natisnjenim listom ni klica modela.** Pretvorba
markdown → Word je deterministična. Če bi se vmes zgodila še ena generacija,
lastnik ni potrdil ničesar.

**C. Ena datoteka na list, prepiše se.** Različic dokumenta ni. Zapis gre v
začasno datoteko in se preimenuje, da prekinjeno generiranje ne pusti
polovične datoteke, ki jo Word odpre z napako.

**D. Zastarelost je izpeljana, ne shranjena.** Dva časovna žiga — kdaj je bila
vsebina nazadnje spremenjena in kdaj nazadnje ustvarjen dokument. Prvi novejši
od drugega pomeni „dokument je zastarel". Novega statusa to ne terja.

**E. Opomba je edini zapis o rešenem listu.** Prosto besedilo, ki ga lastnik
napiše po pregledu popravljenega papirja. Rezultatov po nalogah se ne vnaša:
kljukice „prav/narobe" so videti bolj resne, a povedo manj, njihov strošek pa
je deset klikov po vsakem listu. Odsotnost opombe je podatek — arhiviran list
z opombo je opravljen, arhiviran brez opombe je odložen.

**F. Opomba zaklene generiranje.** Ko list dobi opombo, je bil rešen na
papirju; poznejši popravek vsebine bi pomenil, da opomba visi na nečem, česar
otrok ni nikoli imel v rokah. Nadaljnje delo gre prek **klona** — nov osnutek
z isto vsebino, izvirnik nedotaknjen. Poti iz `pripravljen` nazaj v `osnutek`
ni.

**G. Upokojitev vprašanj (`ADR-012`, `ADR-015`) na delovne liste ne velja.**
List ima prepisano vsebino v sebi; ponovna obdelava slike ga ne more razsuti.
Filtra `retired_at` v tej verziji ni nikjer — in prav odsotnost tega problema
je razlog, da je zamrznjena kopija pravilna izbira.

## Posledice

- Kaj to olajša: pregled pred tiskom; ponovni tisk; berljiva razlika med
  različicami; zanka med listi prek opomb (`ADR-033`); hramba je omejena na
  „toliko datotek, kolikor je listov".
- Kaj to oteži: markdown mora nositi tudi podatek o prostoru za odgovore, ker
  polj ni — oblika je dogovor, ne shema, in jo mora varovati pretvornik
  (`V4-R01`). Kdor bi hotel zgodovino različic vsebine, tega nima.
- Na katere zahteve to odslej vpliva: `V4-R01` (pretvornik in oblika),
  `V4-R03` (tabela, statusi, datoteka, klon), `V4-R05` (iteracija),
  `V4-R06` (opomba in zaklep).
- Če se kdaj pojavi želja po vnosu rezultatov po posameznih nalogah, je to
  sprememba te odločitve, ne dopolnitev: terja stabilno številčenje nalog med
  papirjem in zapisom, ki ga ta model namenoma nima.
