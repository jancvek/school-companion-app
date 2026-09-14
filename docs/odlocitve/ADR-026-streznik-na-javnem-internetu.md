# ADR-026: Strežnik gre na javni internet s HTTPS; Tailscale odpade

- **Datum:** 2026-09-14
- **Nastalo pri:** V3 (pogovor pred verzijo)
- **Status:** Sprejeto
- **Razveljavlja:** `ADR-010` v celoti (nešifriran HTTP za celotno
  aplikacijo); `ADR-006`, odločitev **B1** (operaterska stran brez zaščite,
  ker je meja Tailscale)
- **Stoji na:** `ADR-025` (več družin)

## Kontekst

`ADR-006` in `ADR-010` stojita na isti trditvi: *varnostna meja tega sistema
je Tailscale.* Iz nje sledi, da admin stran ne potrebuje gesla in da promet ne
potrebuje šifriranja.

`ADR-025` to trditev razveljavi. Uporabniki bodo v več gospodinjstvih, na
napravah, ki niso lastnikove. Zahtevati od vsake družine namestitev in
vzdrževanje Tailscale odjemalca pomeni, da sistema ne bo uporabljal nihče.

Preverjeno pred odločitvijo: lastnik ima **javni IP** (ne CGNAT), torej so na
mizi vse tri poti spodaj, ne le tiste brez odprtih vrat.

## Možnosti

1. **Cloudflare Tunnel.** Odhodna povezava s strežnika navzven; na
   usmerjevalniku ni odprtih vrat. Za: deluje tudi za CGNAT, domači IP ostane
   skrit, certifikat in obnavljanje sta tuja skrb, `BIND_ADDRESS` ostane
   `127.0.0.1` tudi ob napačni nastavitvi. Proti: nov zunanji ponudnik v poti;
   slike otroških zvezkov potujejo skozi dodatnega posrednika.
2. **Odprta vrata 80/443 + Caddy + Let's Encrypt + dinamični DNS.** Za: nobene
   tretje strani; Caddy je ena binarna datoteka in ~5 vrstic nastavitve;
   certifikat se obnavlja sam. Proti: domači IP je javno viden; skenerji
   pridejo v urah; omejevanje hitrosti in zaklep ob poskusih prijave sta
   odslej naša skrb, ne skrb omrežja.
3. **Tailscale Funnel.** Javni HTTPS brez odprtih vrat in brez odjemalca pri
   uporabniku. Za: najmanjša sprememba obstoječega. Proti: promet teče skozi
   Tailscale infrastrukturo; lastnik Tailscale odstranjuje, ne dodaja.

## Odločitev

**Možnost 2.** Lastna domena, `A` zapis na domači IP, Caddy kot obratni
posredniški strežnik pred `api`, samodejni certifikat Let's Encrypt.
Odločitev je sprejel lastnik: javni IP obstaja in tretje strani v poti do slik
svojih in tujih otrok noče.

Tehnične meje, ki jih ta odločitev nalaga:

- **`api` se ne veže na gostiteljev naslov.** Ostane v omrežju Docker Compose,
  dosegljiv samo Caddyju. Navzven sta odprti izključno vrati 80 in 443, in
  vrata 80 samo zaradi izdaje certifikata in preusmeritve na HTTPS.
- **`uvicorn` teče s `--proxy-headers`, z zaupanjem samo Caddyjevemu naslovu.**
  Brez tega bo vsak odjemalec v dnevniku in v omejevalniku hitrosti videti kot
  isti IP, kar omejevanje naredi neuporabno.
- **Nobena pot ni dosegljiva brez prijave**, razen `GET /health`, prijavne
  strani in statičnih virov. To je nasprotje stanja iz `ADR-006` in mora
  priti z regresijskim testom, ki dokaže 401 oz. 303 na vsaki poti pod
  `/admin` brez seje.
- **Omejevanje hitrosti in zaklep** na prijavnih poteh. Geslo otroka je kratko
  in bo ostalo kratko; edina resna obramba je, da ugibanje ne gre hitro.
- **Vtičnik za cleartext (`plugins/`) in njegov test gresta ven.** Dovoljenje
  `usesCleartextTraffic` se ne sme prenesti v naslednjo gradnjo; aplikacija
  govori izključno `https`.
- **Če IP ni statičen, gre zraven dinamični DNS.** Domača namestitev, ki mesec
  dni deluje in nato tiho ni več dosegljiva, je slabša od take, ki ni delovala
  nikoli.
- **Varnostna kopija baze in slik je pogoj za prvo tujo družino**, ne poznejša
  izboljšava.

## Posledice

- **Kaj to olajša:** otrokov telefon lahko pošlje sliko iz šole po mobilnih
  podatkih, ne šele doma na domačem omrežju. Google prijava (`ADR-027`) dobi
  stabilen `https` naslov za povratni klic, brez katerega je ni.
- **Kaj to oteži:**
  - Domači stroj je odslej dosegljiv z interneta. Vsaka nova pot je javna
    površina, ne več pot v zaprtem omrežju.
  - Nastavitev ni več samo v repozitoriju: domena, zapis DNS, usmerjevalnik in
    obnavljanje certifikata živijo zunaj njega. Ta sklop mora biti zapisan v
    `docs/01-arhitektura.md`, sicer ga ob selitvi stroja nihče ne bo znal
    ponoviti.
  - `ADR-010` je s tem zaprt. Njegova odprta točka („dovoljenje velja za vso
    aplikacijo, kar je treba kdaj zožiti") se ne zoži, ampak odpade.
- **Cena ostane vidna:** domači IP je javno znan vsakomur, ki pogleda zapis
  DNS te domene.
