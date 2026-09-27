# ADR-050: Današnje slike na domači strani admina

- **Datum:** 2026-09-27
- **Nastalo pri:** V3-R13
- **Status:** Sprejeto

## Kontekst

Starš ob odprtju admina najprej želi vedeti eno stvar: ali je otrok danes že
kaj poslikal. Odgovor danes obstaja na `/admin/days` (`V2-R07`, `ADR-023`),
vendar šele po kliku in z vsemi sličicami. Domača stran `/admin` kaže samo
skupna števila slik po predmetih čez vso zgodovino.

`V3` pravi „sprememb v funkcionalnosti ni" z naštetimi izjemami. Ta zahteva
je šesta izjema: majhna, samo bralna, brez sheme in brez telefona — iz istega
razloga kot `V3-R10` (`ADR-040`).

## Možnosti

**A — Kaj pomeni „danes slikala"**

1. **A1 — nearhivirane slike otroka s `taken_at` na današnji lokalni dan, ki so
   že na strežniku.** Isti nabor kot `/admin/days` za današnji dan
   (`seznam_po_obdobju`, `dnevi_od_do`). Za: številki na obeh straneh se
   ujemata; brez nove poizvedbe. Proti: slika, ki na telefonu čaka na
   sinhronizacijo, se ne vidi.
2. **A2 — tudi arhivirane.** Proti: kartica in `/admin/days` bi pri istem dnevu
   kazali različni števili.

**B — Več otrok**

1. **B1 — ena vrstica na aktivnega otroka.** Za: pri enem otroku je to ena
   vrstica, pri dveh ni nobeden skrit. Seštevka čez otroke ni, zato pravilo
   `ADR-039` B („brez možnosti vsi otroci") ni kršeno — to je seznam, ne
   združena številka.
2. **B2 — samo privzeti otrok.** Proti: drugi otrok je na domači strani neviden.

**C — Stanje brez slik**

1. **C1 — nevtralno.** Siv krožec, „danes še ni slik". Zjutraj je to normalno
   stanje, ne napaka.
2. **C2 — opozorilo.** Proti: kartica bi vsak dan do prve slike kričala.
3. **C3 — plus manjki po urniku (`V3-R09`).** Proti: kartica ni več
   enostavna; manjki ostanejo na `/admin/days`.

**D — Dnevi brez pouka**

1. **D1 — samo sobota in nedelja.** Kartica napiše „Danes je vikend." in nič
   drugega, tudi če so tisti dan slike.
2. **D2 — tudi državni prazniki.** Proti: trdo zapisan koledar s premičnim
   praznikom; šolskih počitnic vseeno ne pokrije.

**E — Besedilo**

1. **E1 — brez glagola s spolom:** „Maša — danes že poslikano" in „Maša —
   danes še ni slik". Aplikacija spola otroka ne pozna in ga ne hrani.
2. **E2 — „Maša je danes že slikala".** Proti: pri fantu napačno.

## Odločitev

**A1, B1, C1, D1, E1.** Poleg tega:

- Pri vsakem otroku so našteti samo predmeti s slikami, s številom, v
  vrstnem redu `PREDMETI`; neznane kode na koncu po abecedi in se ne
  izpustijo (odločitev 3 v `docs/plan/V1-R04.md`).
- Vrstica je povezava na `/admin/days` za današnji dan tega otroka.
  `?otrok=` je v naslovu samo, kadar ima družina več kot enega otroka
  (`ADR-039` B).
- Družina brez aktivnega otroka kartice nima.
- Kartica stoji **nad** seznamom predmetov. Test vrstnega reda predmetov na
  domači strani (`test_vrstni_red_predmetov_je_urnik_in_ne_abeceda`) je
  zasnovan brez slik, zato ga kartica ne podre; nov test vrstnega reda s
  sliko od danes gleda samo seznam `<ul class="predmeti">`.

## Posledice

- Kaj to olajša: odgovor „ali je že slikala" je vidno ob odprtju admina.
- Kaj to oteži: domača stran postane odvisna od današnjega dne, zato testi
  strani dan podajo sami in ne berejo ure stroja.
- Na katere zahteve to odslej vpliva: vsaka prihodnja sprememba nabora na
  `/admin/days` (npr. štetje arhiviranih) mora spremeniti tudi kartico, sicer
  se številki razideta. Kdor bi uvedel praznike ali počitnice, jih uvede
  na obeh mestih.
