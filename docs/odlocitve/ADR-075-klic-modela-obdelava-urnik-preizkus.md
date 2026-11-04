# ADR-075: Klic modela — obdelava snovi, urnik in preizkus (zapis za nazaj)

- **Datum:** 2026-11-04
- **Nastalo pri:** V6-R05 (zapis za nazaj; izvorne zahteve so pri točkah)
- **Status:** Sprejeto — zapis za nazaj

## Kontekst

Razlogi iz razdelka „Vision obdelava" in sorodnih v `docs/01-arhitektura.md`,
ki jih `ADR-007`, `ADR-008`, `ADR-009`, `ADR-041` in `ADR-053`–`ADR-055` ne
nosijo (`ADR-070`).

## Odločitve in razlogi

### A. Zanka in prevzem (V1-R03, V3-R01, V3-R05)

1. **`obdelava.py` je sinhrona in ne ve za `asyncio`, `worker.py` je samo
   časovnik:** poslovna logika je testljiva brez zaganjanja zanke.
2. **`vision.py` je edini uvoznik `openai`** (`ADR-008`): menjava modela ali
   ponudnika mora biti sprememba ene datoteke in ene spremenljivke okolja.
3. **Delo teče v niti (`asyncio.to_thread`)**, ker sta SQLAlchemy in odjemalec
   OpenAI sinhrona; brez tega bi en klic za sto sekund ustavil cel strežnik.
4. **Prevzem je pogojni `UPDATE ... WHERE status='new'`** z nadaljevanjem samo
   ob natanko eni spremenjeni vrstici. Danes teče en proces in tekmovanja ni;
   pogoj je tam, da ga tudi ne bo, če kdo doda `--workers`. Prevzem in zapis
   izida sta ločeni transakciji, ker med njima teče klic, ki traja sekunde.
5. **Obnova obtičalih ob zagonu stoji na sklepu „ta hip ni v obdelavi nič"**,
   ki drži samo pri enem procesu; drugi proces bi vrnil v `new` zapise, ki jih
   prvi obdeluje, in slika bi bila plačana dvakrat. Pogojni prevzem tega ne
   prepreči (dva zaporedna, vsak zase veljavna prehoda). Prava rešitev, če bo
   potrebna, je zaklep na ravni baze, ne več procesov.
6. **`obnovi_obticale` gre čez vse družine, tudi ugasnjene**, obhod pa ugasnjene
   preskoči: obnova ne kliče ničesar zunanjega, vrstica, ki bi ostala
   `processing`, pa bi bila tiha izguba (`ADR-044`).
7. **Zaustavitev ne čaka razmika ne serije**; zapis v teku se dokonča, ker bi
   bil prekinjen klic plačan in zavržen.

### B. Izid (V1-R03, V2-R05)

1. **Neberljiva slika ni peti status:** klic je uspel in bil plačan, zato to ni
   napaka obdelave — `ready` z `readable=false`.
2. **Vrstica brez datoteke gre v `failed` brez klica** — za sliko, ki je ni, ne
   plačamo.
3. **„Pošlji v obdelavo" vprašanja upokoji takoj**, ne ob novem izidu, sicer bi
   snov ves čas klica kazala stara vprašanja ob praznem prepisu. Stran zato pove
   število upokojenih; brez njega bi bila razlika med „ni vprašanj" in „vsa so
   upokojena" nevidna (`ADR-015`).
4. **Slika potuje kot base64 v `data:` URL**, ker so slike dosegljive samo pod
   `/admin` za prijavo in OpenAI do njih nima dostopa.
5. **Odgovor gre po `strict` shemi in še skozi Pydantic:** `strict` je obljuba
   storitve, ne naša invarianta, in ne zna povedati „med 5 in 10 vprašanj" —
   `minItems` v strogem načinu ni podprt, zato mejo uveljavimo ob sprejemu.
6. **Revizijska sled ob vsakem izidu, tudi neuspešnem** (prompt v celoti, surov
   odgovor, model, tokeni): brez nje primerjave modelov iz `ADR-008` ne bo z
   dejanskimi podatki. Cene v evrih ne računamo — cenik v nastavitvah bi se
   staral neopazno.

### C. Urnik in preizkus (V3-R09, V4-R07)

1. **Klic urnika teče sinhrono ob zahtevi** (`ADR-041` B), zato „klic modela
   teče v ozadju" ne velja več za vse klice.
2. **Dnevnik klica preizkusa nosi samo predmet, model, trajanje in tokene** —
   brez snovi, želja, testa in ključa. Dnevnik `app.routers.preizkusi` ima svoj
   izpis, ker uvicorn korenskega ne nastavi.

## Posledice

- `01-arhitektura.md` nosi zanko, prehode in omejitev enega procesa; razlogi so
  tu.
