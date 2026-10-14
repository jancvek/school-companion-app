# ADR-065: Backlog je mesto za ideje, o katerih še ni odločeno

- **Datum:** 2026-10-14
- **Nastalo pri:** pogovor o starševskem načinu aplikacije (zunaj zahteve)
- **Status:** Sprejeto (2026-10-14)
- **Spreminja:** `CLAUDE.md` (§0, faza 0, faza 1, faza 9b), nova
  `docs/backlog.md`
- **Stoji na:** `ADR-022` (proces), `ADR-052` (POC pot)

## Kontekst

Proces pozna tri vrste zapisov: zahteve (`docs/verzije/`), preverjanje idej
(`docs/poc/`) in odločitve (`docs/odlocitve/`). Vsi trije pomenijo, da je
lastnik že rekel „to delamo" ali vsaj „to preverjamo".

Ne pokrije pa ideje, ki jo lastnik želi ohraniti, ne pa še začeti. Prvi tak
primer je starševski način mobilne aplikacije: razdelan v pogovoru, s sedmimi
odprtimi vprašanji in s tremi sprejetimi ADR-ji, ki bi jih odprl. Lastnik ga
ne želi v zahteve. Brez mesta v repozitoriju taka razdelava živi samo v
pogovoru — in čez nekaj mesecev nihče več ne ve, katere odločitve bi ideja
podrla.

## Možnosti

1. **Brez spremembe** — ideja ostane v pogovoru ali v lastnikovih zapiskih.
   Za: nič novega. Proti: razdelava se izgubi, vprašanja se odpirajo znova.
2. **Zahteva s statusom `Nova` v prihodnji verziji** — Za: obstoječa oblika.
   Proti: zahteva ima kriterije sprejemljivosti in s tem obljubo; lastnik je
   izrecno ne želi. Verzija bi se napolnila s stvarmi, ki morda ne bodo nikoli
   zgrajene.
3. **ADR s statusom `Predlagano`** — Za: obstoječa mapa. Proti: ADR je zapis
   odločitve; predlog v isti mapi zabriše, kaj velja.
4. **Ločena datoteka `docs/backlog.md`** (izbrano) — Za: jasno ločeno od
   zahtev in odločitev; en dokument, ki ga je mogoče prebrati v celoti.
   Proti: še en dokument, ki ga je treba vzdrževati.

## Odločitev

Možnost 4.

1. **Ena datoteka**, vsak vnos svoj razdelek z ID-jem `B-xx`. ID omogoča, da
   se POC, ADR ali zahteva sklicuje nanj (**Podlaga:** `B-01`). Mapa z
   datoteko na vnos šele, ko datoteka postane nepregledna.
2. **Vnos ni odločitev.** Nima kriterijev sprejemljivosti. Pogled modela ob
   zapisu je označen kot *Predlog smeri (ni dogovor)*.
3. **Najdragocenejši del vnosa je *Česa se dotakne*** — sprejeti ADR-ji, ki
   bi jih ideja podrla ali odprla. To je podatek, ki ga čez čas nihče več ne
   ve na pamet.
4. **Backlog ni podlaga za kodo.** Iz njega vodi pot samo skozi fazo 0 (POC
   ali zahteva); ADR nastane šele tam.
5. **V fazi 1 se ne bere**, razen če ga zahteva navaja pod **Podlaga**. Sicer
   bi vsaka zahteva vlekla s sabo vse nedokončane ideje.
6. **Vnos doda ali spremeni lastnik ali model na lastnikovo izrecno
   naročilo.** Tudi ugotovitve iz faze 9b gredo v backlog samo na lastnikov
   ukaz.
7. **Vnos se ne briše.** Statusi `Ideja` → `Prevzeto v POC-xx` /
   `Prevzeto v VN-Rxx` ali `Zavrženo`; status se spremeni v istem commitu,
   v katerem nastane POC ali zahteva.

## Posledice

- **Olajša:** ideja z razdelavo in odprtimi vprašanji se ohrani brez
  zaveze; faza 0 ali POC kasneje začneta iz zapisanega, ne iz spomina.
- **Oteži:** vnos se lahko razide s kodo — ADR, na katerega se sklicuje, je
  lahko medtem nadomeščen. Zato se *Česa se dotakne* ob prevzemu preveri
  znova; vnos ni vir resnice o stanju sistema.
- **Ne spremeni:** poti POC-a in zahteve od faze 1 naprej.
