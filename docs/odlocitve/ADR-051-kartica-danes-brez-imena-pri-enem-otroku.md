# ADR-051: Kartica „danes" pri enem otroku ne nosi imena

- **Datum:** 2026-09-27
- **Nastalo pri:** V3-R13 (pregled, faza 7; odločil lastnik)
- **Status:** Sprejeto
- **Stoji na:** `ADR-039` F3 (ime samo pri več kot enem otroku, brez izjeme)
- **Nadomešča:** odločitev **E1** iz `ADR-050` v delu, ki ime predpisuje
  vedno („Maša — danes že poslikano"). Pravilo „brez glagola s spolom" iz E1
  in vse ostale odločitve `ADR-050` veljajo naprej.

## Kontekst

`ADR-050` E1 je predpisal vrstico „<ime> — danes že poslikano" za vsakega
otroka. `ADR-039` F3 točka 1 pa pravi, da se ime izriše samo pri več kot enem
otroku, brez izjeme, in to varuje `TestImenaPriEnemOtroku`, ki pomete čez vse
strani `/admin`. Prva izvedba `V3-R13` je sledila E1; varovalni test je padel
ob vsakem delavniku, zelena zbirka pa je bila le posledica zagona v nedeljo,
ko kartica imena ne izriše.

## Možnosti

1. **Pri enem otroku vrstica brez imena.** Za: skladno s F3, varovalni test
   ostane nespremenjen; pri enem otroku ime ne loči ničesar.
2. **Nov izjemni primer F3 za kartico.** Proti: F3 je „brez izjeme" prav zato,
   ker je bil že enkrat pozabljen na enem klicnem mestu; sprememba prej
   zelenega varovala.

## Odločitev

**Možnost 1.** Pri enem otroku: „✓ Danes že poslikano" oziroma „○ Danes še
ni slik", brez imena. Pri več otrocih ostane „Maša — danes že poslikano", ime
kot vrednost polja pred ločilom (F3 točka 2).

Pravilo uveljavi **tip**, ne predloga: vrstica nosi ime ali `None`, po vzorcu
`IzbiraOtroka.ime_za_prikaz` (F3).

## Posledice

- Kriterij `V3-R13` v `docs/verzije/v3.md` je popravljen.
- `docs/plan/V3-R13.md` ostane, kakršen je bil (`CLAUDE.md` §3).
- Ker je bila napaka skrita za dnem v tednu, testi strani `/admin` odslej
  tečejo na stalen delavnik (`autouse` fixture v `tests/conftest.py`); vikend
  preverjajo testi kartice sami.
