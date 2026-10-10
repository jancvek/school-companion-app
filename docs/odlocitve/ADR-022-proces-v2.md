# ADR-022: Proces v2 — manj branja in pisanja, enako strog pregled

- **Datum:** 2026-09-11
- **Nastalo pri:** celostni pregled projekta po V2-R04 (zunaj zahteve)
- **Status:** Sprejeto (merge v `main` 2026-09-11, commit 77893c5)
- **Spreminja:** `CLAUDE.md` (§0, faza 1, faza 4, faza 7, faza 9b, nov §1c), `docs/plan/PREDLOGA.md`; predlaga spremembe `.claude/commands/zahteva.md`
  in `.claude/agents/pregledovalec.md` (glej Dodatek — teh datotek model po
  trdem robu 4 ne spreminja)

## Kontekst

Po osmih dneh in 133 commitih je pregled celotnega projekta pokazal, da proces
iz `CLAUDE.md` deluje: dokumentacija in koda se ujemata, pregledovalec je v
ADR-020 trikrat ujel resnične napake, verify gate drži. Stane pa na napačnih
mestih:

- `/zahteva` pred prvo besedo prebere vse v `docs/` — 7.349 vrstic, od tega
  4.100 vrstic planov in ADR-jev, ki so zgodovinski zapis. Z vsako verzijo
  številka raste.
- `01-arhitektura.md` ima 1.150 vrstic in raste narativno („odkrito v
  V1-R03, ko je test padel…"). Bere jo vsaka seja v celoti.
- 48 od 133 commitov (36 %) je procesnih: `plan`, `status v pregledu`,
  `zaključek in dokumentacija`, `Merge`.
- Plani imajo 250–370 vrstic tudi za spremembe treh datotek; razdelka
  *Koraki* in *Spremenjene datoteke* zastarata prvi dan.
- ADR-020 je šel skozi tri različice in pet krogov pregleda. Vsak popravek
  je bil na strani telefona; nihče ni vprašal, ali je pogodba
  (`POST /quiz-attempts` vse ali nič) prava. Proces je dober pri „ali je
  narejeno prav" in slabši pri „ali delamo pravo stvar".
- ADR-010 (cleartext) je nastal, ker se preizkus na napravi z APK iz veje
  ni zgodil pred mergem.

## Odločitev

1. **Faza 1 bere ciljno.** `00-namen`, `01-arhitektura`, `vN.md` tekoče
   verzije in ADR-je iz vrstice **Podlaga** pri zahtevi. Ostale ADR-je po
   naslovih; planov nikoli. Vrstica *Podlaga* postane obvezna.
2. **`01-arhitektura.md` pove samo, kako je zdaj** (cilj ≤ 400 vrstic).
   „Zakaj" gre v ADR, „past" v nov `docs/02-izkusnje.md`. Selitev je
   samostojna zahteva, ne stranski učinek.
3. **Kratka pot (§1c)** za nizko tveganje: brez plana kot datoteke, brez
   samostojnih statusnih commitov; faza 1, pregledovalec in verify ostanejo.
4. **Status se ne commita sam** — vedno z vsebino, ki ga povzroči.
5. **Tretjič isto mesto → nazaj v fazo 2** z vprašanjem, ali je napaka v
   izvedbi ali v odločitvi.
6. **Predloga plana** se skrči na odločitve, meje, kaj lahko podre in teste;
   koraki samo pri visokem tveganju.
7. **Faza 9b:** sprememba vedenja na telefonu se ne merga brez preizkusa z
   APK iz veje.

## Kar ta ADR izrecno ne ureja

Obratovanje (varnostna kopija, nadzor `/health`, zagon Dockerja po ponovnem
zagonu stroja) je lastnik ob sprejemu **zavestno pustil zunaj**. Proces zanj
ne dobi ne datoteke ne merila. Če se to kdaj spremeni, je to nova zahteva.

## Kaj ostane

Faza 1 s pragom „predvidevam = vprašanje", ADR ob vsakem dvomu, zamrznjeni
plani, neodvisen pregledovalec, verify vezan na HEAD, trdi robovi, merilo
dokončanosti.

## Posledice

- **Olajša:** začetek zahteve bere ~1.500 vrstic namesto ~7.300; tretjina
  commitov izgine; majhne spremembe gredo skozi v enem obratu.
- **Oteži:** vrstica *Podlaga* je nova obveznost pri pisanju zahtev — če
  manjka, faza 1 bere premalo. Kratka pot zahteva poštenost pri oceni
  tveganja; pravilo „če nisi prepričan, ne velja" ostane.
- **Ne spremeni:** strogosti pregleda. Kratka pot skrajša pisanje, ne
  pregleda.

## Dodatek — predlagane spremembe v `.claude/` (spremeni lastnik)

### `.claude/commands/zahteva.md`, točka 1

Namesto:

> Preberi `docs/00-namen.md`, `docs/01-arhitektura.md`, vse v
> `docs/verzije/`, `docs/plan/` in `docs/odlocitve/`, preden karkoli rečeš.

naj piše:

> Preberi `docs/00-namen.md`, `docs/01-arhitektura.md`, `docs/verzije/vN.md`
> tekoče verzije in ADR-je iz vrstice **Podlaga** pri zahtevi $1. Ostale
> ADR-je preleti po naslovih (`ls docs/odlocitve`) in odpri le tiste, ki se
> zahteve tičejo. Planov ne beri, razen plana za $1, če že obstaja.

### `.claude/agents/pregledovalec.md`, razdelek „Kaj preveri"

Dodaj tri točke:

> - **Pogodba.** Če sprememba spremeni pot med telefonom in strežnikom: je
>   zapletenost na pravi strani? Strežnik ve več in se popravi z enim
>   zagonom; APK se popravi z novo gradnjo. Logika, ki jo telefon rabi samo
>   zato, da preživi odgovor strežnika, je znak napačne pogodbe.
> - **Kaj se zgodi ob odpovedi.** Baza dol, disk poln, zunanji API vrne 5xx
>   ali potek časa, telefon brez povezave. Za vsako pokaži vrstico, ki to
>   obravnava. Začasna napaka, ki se obravnava kot trajna, je KRITIČNO.
> - **Ponavljanje.** Poglej `git log --oneline main..HEAD`. Če se isto mesto
>   (isti ADR, ista funkcija) popravlja tretjič, to zapiši kot KRITIČNO z
>   besedilom „vzorec ponavljanja — verjetno napačna odločitev, ne izvedba"
>   in ne predlagaj četrtega popravka.

Odstrani točko **Higiena** (pozabljeni `console.log`, zakomentirana koda,
`TODO`): to ujameta `ruff` in `eslint`, pregledovalec pa naj pozornost porabi
za vedenje. Skrivnosti v kodi in nevalidiran vhod ostaneta — pod **Kar
manjka**.
