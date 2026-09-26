# ADR-049: Prepisi izbranih nosijo tudi povzetek in vprašanja

- **Datum:** 2026-09-26
- **Nastalo pri:** V3-R12 (debata z lastnikom, faza 1–2)
- **Status:** Sprejeto
- **Stoji na:** `ADR-048`, `ADR-015` (veljavna vprašanja so `retired_at IS NULL`),
  `ADR-025` (družina je lastnik podatkov)
- **Nadomešča:** odločitev **D** iz `ADR-048` v delu „pod glavo je prepis" in
  odločitev **E** v delu „slika brez prepisa prispeva samo glavo". Glava,
  vrstni red in vse ostale odločitve `ADR-048` (A, B, C, F, G) veljajo naprej.

## Kontekst

Lastnik besedilo s stranjo „Prepisi izbranih" (`V3-R11`) lepi v ChatGPT, da
iz njega sestavi vaje. Snov na strežniku ima poleg prepisa še povzetek
(`summary`) in vprašanja z odgovori, ki jih je sestavil model. Oboje je
koristno pri sestavljanju vaj — povzetek pove, za kaj pri snovi gre, vprašanja
pa, kaj je že vprašano in kaj je pravilen odgovor — a danes ostane zunaj
besedila.

Odprta so bila štiri vprašanja: oblika (markdown ali JSON), ali je obseg
izbirljiv, ali gredo zraven tudi odgovori in kaj s prazno sestavino.

## Odločitve

### A — Oblika ostane markdown; vsaka sestavina ima svoj podnaslov

Pod glavo slike (nespremenjena iz `ADR-048` D) stojijo do trije deli, vsak s
podnaslovom tretje ravni in vedno v tem vrstnem redu:

```
## MAT — 12. september 2026, 10:32 · Ana

### Povzetek
<povzetek>

### Prepis
<prepis>

### Vprašanja
1. V: <vprašanje>
   O: <odgovor>
2. V: ...
   O: ...
```

Podnaslov je tudi pri sliki, ki ima samo prepis — oznaka, za kaj gre, ne sme
biti odvisna od tega, ali je snov imela še kaj drugega.

- Zavrnjeno: **JSON.** Strojno enoumen, a prepis v njem postane en sam niz z
  ubežnimi znaki (`\n`, `\"`) — v polju je neberljiv in ima opazno več znakov,
  ChatGPT pa markdown podnaslove razume enako dobro kot ključe. Razlog iz
  `ADR-048` D velja še močneje, ko so kosi trije.
- Zavrnjeno: izbira oblike na strani. Dve obliki pomenita dva izpisa in dve
  zbirki testov za isto dejanje.

### B — Vedno vse tri sestavine; izbire ni

Kljukic „povzetek / prepis / vprašanja" ni. Kdor potrebuje manj, odvečno
pobriše po lepljenju.

- Proti: besedilo je daljše in hitreje doseže mejo sporočila v ChatGPT.
  Sprejeto — števec znakov nad poljem (`ADR-048` A) to pokaže, in ker
  strežnik ne reže, lastnik sam lepi v več kosih.

### C — Vprašanja z odgovori, samo veljavna

Vsako vprašanje nosi tudi svoj odgovor. Šteje samo **veljavna** serija
(`retired_at IS NULL`, `ADR-015`), urejena po `position`; upokojena vprašanja
v besedilo nikoli ne pridejo. Številčenje je 1, 2, 3 … po vrstnem redu
izpisa, ne neposredno `position`, da luknja ne more nastati.

Večvrstično vprašanje ali odgovor ostane v isti točki seznama: nadaljevalne
vrstice so zamaknjene tako kot `O:`, sicer bi markdown točko prekinil.

### D — Prazna sestavina se izpusti, skupaj s podnaslovom

Povzetek ali prepis, ki ga ni ali je iz samih presledkov, in snov brez
veljavnih vprašanj ne dobijo podnaslova. Snov brez vsega prispeva samo glavo,
tako kot doslej (`ADR-048` E, sled, da je bila snov tisti dan).

- Zavrnjeno: podnaslov z oznako „(ni)". Pri vsaki neobdelani sliki bi dodal
  tri vrstice šuma, ki ne povedo ničesar, česar ne pove že odsotnost.

### E — Vprašanja se naložijo z eno poizvedbo, samo za izbrane

Sestavljanje ostane čista funkcija brez baze (`ADR-048` F); vprašanja dobi
kot podatek. Klicalec jih prebere z **eno** poizvedbo za vse izbrane snovi,
omejeno na družino in na `retired_at IS NULL`. Branje po snoveh (`veljavna_vprasanja`
na vsakem `Material`) bi pri „Izberi vse" pomenilo eno poizvedbo na sliko.

Poizvedba nosi mejo družine sama in ne sloni samo na tem, da so identifikatorji
snovi že prešli nabor predmeta — pot dobi svoj primer v
`tests/test_tesnjenje.py`.

## Posledice

- **Kaj to olajša:** sestavljanje vaj brez odpiranja posameznih snovi; pozneje
  `V4-R04`, če bo sestavljanje uporabil.
- **Kaj to oteži:** besedilo je daljše; testi `V3-R11`, ki preverjajo
  natančno besedilo, se spremenijo (dovoljeno ob sprejemu tega ADR).
- **Na katere zahteve to odslej vpliva:** `V3-R12` (stoji na tem ADR);
  `V3-R11` ostane zaključena, njen kriterij o obliki glave in vrstnem redu
  velja naprej, kriterij „slika brez prepisa samo glavo" pa se bere kot
  „slika brez vseh treh sestavin samo glavo".
