# ADR-009: Ponovna obdelava zavrže prejšnji rezultat; brez ključa worker miruje

- **Datum:** 2026-09-05
- **Nastalo pri:** V1-R03 (faza 1–2, pred implementacijo)
- **Status:** Sprejeto
- **Zoži:** robni primer *„API ključ manjka ali je napačen → … `status='failed'`"*
  pri V1-R03 v `docs/verzije/v1.md`
- **Doda:** pravilo o usodi prejšnjega rezultata ob „Pošlji v obdelavo", ki ga
  kriteriji V1-R03 ne povedo

## Kontekst

Kriteriji V1-R03 imata dve luknji, ki se pokažeta šele ob pisanju kode in
imata vsaka opazno različni izvedbi.

**Prva: kaj se zgodi s prejšnjim rezultatom ob ponovni obdelavi.** Kriterij
pravi le, da gumb „Pošlji v obdelavo" zapis vrne v `new` — tudi iz `ready`.
Ne pove, ali prejšnji prepis, povzetek in vprašanja ostanejo. To ni
podrobnost: `V1-R05` bo ocene težavnosti vezala na `question_id`, torej na
identiteto posameznega vprašanja.

**Druga: kaj pomeni „manjkajoč ključ".** Robni primer združuje dva zelo
različna primera v en izid. Napačen ključ je odgovor storitve (OpenAI vrne
401) — takrat je `failed` prav. Manjkajoč ključ pa je stanje strežnika, ne
posamezne slike: če se `api` kdaj zažene brez `OPENAI_API_KEY` — in
`docker-compose.yml` ga danes v vsebnik sploh ne prenaša — bi **vsaka**
prispela slika v nekaj sekundah pristala v `failed`. Vsako od njih bi bilo
treba potem ročno vrniti v obdelavo, po eno naenkrat, prek admin strani.
Napaka v konfiguraciji bi tako proizvedla delo, sorazmerno s številom slik.

## Možnosti

### A — prejšnji rezultat ob ponovni obdelavi

1. **Zavrže se.** Za: material ima natanko en veljaven niz vprašanj; admin
   stran med `processing` kaže, kar je res — da rezultata trenutno ni.
   Proti: če nov klic pade, je star (morda uporaben) prepis izgubljen.
2. **Obdrži se do uspeha novega.** Za: neuspel poskus ničesar ne odvzame.
   Proti: med `processing` stran kaže star rezultat, kot da je nov; ob uspehu
   je treba stara vprašanja vseeno zbrisati, torej se problem samo prestavi.
3. **Hrani se zgodovina vseh poskusov.** Za: primerjava med modeli iz
   dejanskih podatkov. Proti: `materials` bi razpadel na `materials` +
   `obdelave` + `questions`, admin stran pa bi morala izbirati med različicami
   — velik del dela za korist, ki jo ADR-008 predvideva šele ob pregledu
   modela.

### B — manjkajoč `OPENAI_API_KEY`

1. **Dobesedno po kriteriju: vsaka slika v `failed`.** Za: stanje je vidno na
   admin strani, ne le v logih. Proti: napaka v konfiguraciji naredi ročno
   delo pri vseh slikah; slike se same ne obdelajo, ko ključ dodaš.
2. **Worker se ne zažene, slike ostanejo `new`.** Za: ko ključ dodaš in
   strežnik zaženeš znova, se čakajoče slike obdelajo same; `new` pomeni
   „čaka na obdelavo" in to je res. Proti: napaka je vidna samo v logu ob
   zagonu, ne na admin strani.

## Odločitev

**A1 + B2.**

**Ponovna obdelava zapis vrne v `new` in hkrati zbriše prejšnji rezultat:**
`transcript`, `summary`, `readable`, poslani prompt, surov odgovor, ime
modela, porabo tokenov, besedilo napake in **vsa vprašanja tega materiala**.
Material ima ob vsakem trenutku največ en niz vprašanj.

Ta odločitev je zapisana zdaj, ker jo mora `V1-R05` poznati: ocena težavnosti,
vezana na `question_id`, izgine skupaj z vprašanjem, ki ga je ponovna obdelava
zavrgla. `V1-R05` se mora odločiti, ali je to sprejemljivo, ali pa mora
takrat gumb ob obstoječih ocenah opozoriti — vendar tega ne sme odkriti
naknadno v kodi.

**Brez `OPENAI_API_KEY` se worker ne zažene.** Ob zagonu strežnika gre v log
glasen zapis, da obdelava ne teče, ker ključa ni. Slike ostanejo `new` in
čakajo. Kriterij, ki pravi `status='failed'`, odslej velja samo za primer, ko
storitev ključ **zavrne** (401 ali 403 od OpenAI) — to je odgovor o eni
zahtevi in gre v `failed` kot vsaka druga napaka klica.

## Posledice

- **Kaj to olajša:** napačno nastavljen strežnik ne pokvari vrste. Ključ se
  doda, strežnik zažene znova in zaostanek se obdela sam. Admin stran nikoli
  ne kaže rezultata, ki ne pripada trenutnemu stanju zapisa.
- **Kaj to oteži:**
  - Ponovna obdelava je nepovratna na isti način kot brisanje: star prepis je
    po pritisku na gumb izgubljen, tudi če nov klic pade. Gumb zato ne sme
    biti navadna povezava — enako pravilo kot pri brisanju v ADR-006.
  - Odsotnost ključa je vidna samo v logu strežnika. Kdor gleda samo admin
    stran, vidi slike, ki dolgo ostajajo „čaka na obdelavo", in ne izve,
    zakaj. To je zavestna cena; če se izkaže za moteče, je opozorilo na admin
    strani nova zahteva, ne napaka te.
  - Ponovna obdelava vsakič stane nov klic. Ker pod `/admin` ni prijave
    (ADR-006), to velja za kogarkoli v Tailscale omrežju. ADR-006 to površino
    že sprejema; nova je samo posledica, da zloraba odslej stane denar in ne
    le podatke.
- **Na katere zahteve to odslej vpliva:** `V1-R05` mora upoštevati, da
  vprašanje ni trajno. `V1-R03` sama dobi obveznost, da je gumb `POST` in da
  worker ob manjkajočem ključu zapiše razlog v log.
