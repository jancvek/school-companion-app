# ADR-008: Vision model je OpenAI `gpt-4.1`

- **Datum:** 2026-09-05
- **Nastalo pri:** V1-R03 (odločitev pred fazo 1; zahteva se še ni začela)
- **Status:** Sprejeto, **začasno** — glej „Kdaj to pregledava znova"
- **Razveljavlja:** izbiro „Claude ali Gemini" v `docs/01-arhitektura.md`
  (tabela Stack) in odprto točko „Katera vision storitev točno" pri V1-R03 v
  `docs/verzije/v1.md`

## Kontekst

`docs/01-arhitektura.md` je od začetka projekta navajal *„Cloud vision API
(Claude ali Gemini — izbira odprta)"*, `v1.md` pa je izbiro vezal na ročno
preverbo kvalitete prepisa, ki naj bi se izvedla pred V1-R01. Ta preverba se
takrat ni izvedla in je bila prestavljena pred V1-R03.

Odslej velja dvoje, kar to točko zapira:

1. **Preverba je izvedena.** Lastnik jo je opravil neodvisno od tega
   repozitorija, na Mašinih dejanskih zapiskih, in kvaliteto prepisa ocenil
   kot zadostno. Izid ni bil zabeležen v obliki, ki bi jo bilo mogoče
   ponoviti; zapisano je, da je bila opravljena in kaj je pokazala.
2. **Lastnik ima račun pri OpenAI** z delujočim plačilom. Anthropic in Google
   bi zahtevala nov račun in novo administracijo.

Ocena stroška pri obsegu 5–25 slik na teden (~100 na mesec, ~1.500 vhodnih in
~2.000 izhodnih tokenov na sliko) je pri vseh pretehtanih možnostih med nekaj
deset centi in petimi evri na mesec. **Cena ni bila odločilna** in tudi ne sme
biti; odločilna je kvaliteta prepisa slovenskega rokopisa.

## Možnosti

1. **Anthropic Claude.** Za: v dokumentaciji je bil naveden kot ena od dveh
   izbir. Proti: nov račun, nova administracija, brez izmerjene prednosti.
2. **Google Gemini.** Za: najnižja cena med pretehtanimi. Proti: nov račun; pri
   brezplačnem sloju je treba preveriti, ali se podatki uporabljajo za učenje —
   pri fotografijah otroških zvezkov to ni podrobnost.
3. **OpenAI `gpt-4.1`.** Za: račun in plačilo že delujeta; preverba na pravih
   zapiskih opravljena; strukturiran izhod po shemi podprt. Proti: `gpt-4.1` je
   **starejša generacija** od takrat aktualne vrste (GPT-5.6 Sol / Terra / Luna,
   GPT-6 Astra) — novejši model bi verjetno dal boljši prepis za manj denarja.

## Odločitev

Izbrana je možnost 3: **OpenAI, model `gpt-4.1`.**

Odločitev je **zavestno začasna** („zaenkrat", besede lastnika). Ni rezultat
primerjave z novejšimi modeli iste hiše, ampak tega, da je ta pot preizkušena
in odprta.

Iz tega sledi zahteva za izvedbo v V1-R03:

- **Klic modela živi v enem samem modulu** z ozko funkcijo `slika → rezultat`.
  Menjava modela ali ponudnika mora biti sprememba ene datoteke in ene
  nastavitve, ne predelava. Brez abstrakcijskih slojev in vtičnikov —
  `docs/00-namen.md`: *„Kar bi lahko bila mikrostoritev, naj bo funkcija."*
- **Ime modela je nastavitev, ne konstanta v kodi.** Zamenjava `gpt-4.1` z
  novejšim mora biti sprememba spremenljivke okolja in ponovni zagon.
- **Poraba tokenov in ime modela se shranita ob vsakem zapisu** (kriterij
  V1-R03). Brez tega primerjave med modeli ne bo mogoče narediti z dejanskimi
  podatki, ampak spet le na papirju.

`OPENAI_API_KEY` gre v `apps/server/.env`, kot `API_KEY`. Datoteka je v
`.gitignore`; vrednost vpiše lastnik. Prenos v vsebnik in polje v `Settings`
nastaneta v V1-R03.

## Posledice

- **Kaj to olajša:** V1-R03 lahko začne brez odprtega vprašanja o ponudniku.
  Nič novega ni treba registrirati.
- **Kaj to oteži:**
  - **Zasebnost.** Fotografije Mašinih zvezkov odslej potujejo k OpenAI.
    `docs/00-namen.md` to načelno že sprejema kot zavestno odločitev zaradi
    kvalitete prepisa; s tem ADR ima ta stavek konkretno ime prejemnika.
  - **Nova zunanja odvisnost** (uradni paket ali klic prek `httpx`) je odprta
    in jo mora odobriti lastnik v planu V1-R03. Ta ADR je ne odobri vnaprej.
  - Izbran je model, za katerega vemo, da ni najnovejši. To je zavestno; ni
    pa nekaj, na kar bi smeli pozabiti.
- **Kdaj to pregledava znova:** ko bo V1-R03 obdelala prvih nekaj deset slik
  in bodo v bazi prepisi, poraba tokenov in cena. Takrat je primerjava z
  novejšim modelom poceni in temelji na Mašini snovi, ne na ceniku. Sprememba
  modela je takrat sprememba nastavitve in nov ADR, ne nova zahteva.
