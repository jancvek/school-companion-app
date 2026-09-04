# ADR-003: Po *Shrani* ostanem na kameri, ne grem na domačo stran

- **Datum:** 2026-09-04
- **Nastalo pri:** V1-R01 (faza 9b — sprejem)
- **Status:** Sprejeto
- **Razveljavlja:** odločitev 8 v `docs/plan/V1-R01.md`

## Kontekst

Plan V1-R01 je v „Sprejete odločitve" pod točko 8 določil: *„Po Shrani se
vrnem na domačo stran s kratko potrditvijo."* Odločitev je bila sprejeta za
mizo, brez naprave v roki.

Ob ročnem preizkusu na telefonu (faza 9b) se je pokazalo, da je resnični
delovni vzorec drugačen. Maša ne fotografira ene strani, ampak **več strani
iste snovi zapored**. Pri vsakem posnetku jo je vrnilo na domačo stran, tako
da je morala za vsako naslednjo stran znova skozi *Slikaj snov* → izbira
predmeta → kamera. Trije dotiki med dvema stranema iste snovi.

Odločitev 8 torej ni bila napačna glede na to, kar sva takrat vedela — bila je
sprejeta brez podatka, ki ga da šele naprava.

Po fazi 9b to ni napaka, ampak **sprememba zahteve**: novo vedenje nasprotuje
sprejeti odločitvi. Ker V1-R01 ob tem zapisu še ni sprejeta in ni mergeana,
obseg še ni zaklenjen in sprememba sme v tekočo zahtevo — pod pogojem, da se
popravi izhodišče, ne samo koda. Ta zapis je ta pogoj.

## Možnosti

1. **Ostane, kot je (odločitev 8).** Za: nič dela, zahteva je preverjena in
   zelena. Proti: zaporedno slikanje, ki je resnični vzorec uporabe, je
   nadležno do te mere, da bo aplikacija ostala neuporabljena.
2. **Po *Shrani* nazaj na kamero istega predmeta.** Za: naslednjo stran
   posnameš z enim dotikom. Proti: podre dva obstoječa testa; potrditev ne
   more več biti modalna; treba je znova odpreti zaporo proti dvojnemu dotiku.
3. **Vprašati po vsakem posnetku „še ena stran?".** Za: eksplicitno. Proti:
   en dotik več pri vsakem posnetku — torej ravno tisto, čemur se izogibava.

## Odločitev

Izbrana je možnost 2. Po uspešnem *Shrani* se zaslon vrne na kamero **istega
predmeta**, pripravljen na naslednji posnetek.

Iz zaslona se gre nazaj s puščico v glavi zaslona, ki pelje na seznam
predmetov.

Ker zaslon ostane odprt, potrditev ne sme biti `Alert` — modalno okno bi bilo
treba odkliknjati po vsakem posnetku in bi pojedlo prav tisti dotik, ki ga
prihranimo. Namesto tega:

- kratek napis **„Shranjeno"**, ki sam ugasne po pribl. dveh sekundah,
- **števec shranjenih v tej seji** ob gumbu, da je ob hitrem slikanju vidno,
  koliko strani je dejansko zapisanih.

## Posledice

- **Kaj to olajša:** zaporedno slikanje več strani iste snovi — en dotik na
  stran namesto štirih.
- **Kaj to oteži:**
  - Zapora proti dvojnemu dotiku se mora po uspešnem shranjevanju **spet
    odpreti**. V1-R01 jo je namenoma pustila zaprto, ker je zaslon takrat
    odšel. Da se po sprostitvi res ne da shraniti drugič, pokrivata testa
    „po neuspehu je mogoče poskusiti znova" in „vsak posnetek da svojo
    vrstico".

    Dodana je bila še druga zapora, ključena na pot posnetka, za okno med
    sprostitvijo `zaklep` in ponovnim izrisom. **Odstranjena je bila znova**,
    ker tega okna ni:

    1. Med shranjevanjem je izrisan `busy = true`, `Pressable` pa `onPress` ob
       `disabled` sploh ne pokliče.
    2. Ob uspehu tečejo posodobitve stanja in sprostitev zapore v enem samem
       sinhronem zaporedju (med njimi ni `await`), zato jih React združi v en
       izris. Izrisanega stanja s hkrati `busy === false` in posnetkom v
       predogledu po uspešnem shranjevanju ni.

    Prvotna utemeljitev v tem zapisu je trdila, da „React izris potrdi pred
    naslednjim makroopravilom". **To je bilo napačno** — Reactov razvrščevalnik
    v React Native uporablja `setImmediate` oz. `MessageChannel`, kar je samo
    makroopravilo. Sklep je bil pravilen, pot do njega ne; popravljeno, ker bi
    se nanjo kdo oprl.

    Noben test zapore ni mogel podreti (pregled je to potrdil z mutacijo),
    hkrati pa je vnašala pravo napako: če bi kamera kdaj vrnila isto pot, bi
    drugi *Shrani* tiho ne naredil nič. Netestljiva obramba, ki doda svoj
    način odpovedi, je slabša od nič.
  - Brez modalne potrditve je večja nevarnost, da uporabnica ne opazi
    neuspeha. Zato števec, ne samo napis.
  - Dva obstoječa testa, ki trdita, da se pokliče `dismissAll()`, se
    spremenita.
- **Na katere zahteve to odslej vpliva:** na nobeno drugo. V1-R02 se veže na
  shemo tabele `materials`, ne na potek zaslonov; shema se ne spreminja.
