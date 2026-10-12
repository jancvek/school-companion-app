/**
 * Kdo je prijavljen na tej napravi (V3-R04, V6-R01).
 *
 * Od `V6-R01` seja ne nastane iz gesla, ampak iz povezovalnega žetona, ki ga
 * starš pokaže kot QR kodo (`docs/odlocitve/ADR-058`, `ADR-061`). Vse ostalo
 * — posvojitev, oznaka odjave, obnovitev z diska — je ostalo, kot je bilo.
 *
 * Najbolj zunanji od treh ponudnikov: prenos in kvizi brez seje nimata s kom
 * govoriti, seja pa o njiju ne ve ničesar.
 *
 * **Prijava ne zapre aplikacije** (`docs/odlocitve/ADR-036` A). Dokler se
 * nihče ne prijavi, kamera, shranjevanje in Zgodovina delajo naprej; miruje
 * samo prenos. Zato tu ni zaslona, ki bi čakal pred vsem ostalim, in tudi ne
 * stanja „nalagam", ki bi ga bilo treba prikazati: dokler se seja bere z
 * diska, je aplikacija preprosto neprijavljena.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { preberiNastavitve, type ServerConfig } from '../config/server';
import { posvojiBrezLastnika, type MaterialsDatabase } from '../db/materials';
import { jeOdjavaNedokoncana, koncajOdjavo, zacniOdjavo } from '../db/naprava';
import { asMaterialsDatabase } from '../db/open';
import { useSQLiteContext } from 'expo-sqlite';
import {
  odjaviSe,
  poveziSe,
  pozabiSejo,
  preberiSejo,
  shraniSejo,
  type Seja,
  type VarnaShramba,
} from './prijava';

/**
 * Oznaka o nedokončani odjavi — tri funkcije, ki **ne vržejo**.
 *
 * Ista obljuba kot pri `posvoji` in iz istega razloga: to je stanje ob robu
 * seje, ne seja sama. Baza, ki oznake ne zapiše, ne sme preprečiti odjave;
 * baza, ki je ne zna prebrati, ne sme preprečiti zagona. Ob dvomu se šteje,
 * da odjave ni bilo — to je izid, ki ohrani sejo in ničesar ne pripiše
 * napačnemu otroku (`docs/odlocitve/ADR-037`).
 */
async function zacni(db: MaterialsDatabase): Promise<void> {
  try {
    await zacniOdjavo(db, new Date().toISOString());
  } catch {
    // Glej opis zgoraj.
  }
}

async function koncaj(db: MaterialsDatabase): Promise<void> {
  try {
    await koncajOdjavo(db);
  } catch {
    // Glej opis zgoraj. Oznaka ostane; naslednji zagon žeton zavrže še enkrat,
    // kar je neprijetno, a varno.
  }
}

async function ostanekOdjave(db: MaterialsDatabase): Promise<boolean> {
  try {
    return await jeOdjavaNedokoncana(db);
  } catch {
    return false;
  }
}

/**
 * Posvojitev, ki **ne vrže** (`docs/odlocitve/ADR-036`, popravki).
 *
 * Ista obljuba kot pri `preberiSejo` in `pozabiSejo`: kar je ob robu seje, ne
 * sme podreti seje same. Padla posvojitev — poln disk, zaklenjena baza — bi
 * sicer preprečila `setSeja` in aplikacija bi ostala videti neprijavljena,
 * čeprav veljaven žeton na disku je. To bi bilo hujše od tega, kar posvojitev
 * popravlja, in uporabnica o tem ne bi izvedela ničesar.
 *
 * Izpuščena posvojitev se popravi sama: naslednja razrešena seja jo ponovi,
 * ker so vrstice še vedno `user_id IS NULL`.
 */
async function posvoji(db: MaterialsDatabase, userId: string): Promise<void> {
  try {
    await posvojiBrezLastnika(db, userId);
  } catch {
    // Glej opis zgoraj.
  }
}

export type PrijavaVrednost = {
  /** Trenutna seja, ali `null`, kadar ni prijavljen nihče. */
  seja: Seja | null;
  /**
   * Poveže telefon z žetonom iz QR kode ali odprte povezave. Ob neuspehu
   * **vrže** `NapakaPrijave` s slovenskim sporočilom, ki ga zaslon pokaže, in
   * obstoječe seje se ne dotakne; ob uspehu posvoji zapise brez lastnika in
   * zamenja sejo, če je katera že bila (`ADR-061` I).
   */
  povezi(zeton: string): Promise<void>;
  /** Odjavi se. Lokalnih slik in poskusov se ne dotakne (`ADR-036` G). */
  odjavi(): Promise<void>;
};

const PrijavaContext = createContext<PrijavaVrednost | null>(null);

export type PrijavaProviderProps = {
  children: ReactNode;
  /** Podtakljivo v testih; sicer baza iz `SQLiteProvider`. */
  db?: MaterialsDatabase;
  /** Podtakljivo v testih; sicer naslov iz gradnje. */
  nastavitve?: ServerConfig | null;
  /** Podtakljivo v testih; sicer `expo-secure-store`. */
  shramba?: VarnaShramba;
};

export function PrijavaProvider({
  children,
  db: dbLastnost,
  nastavitve: nastavitveLastnost,
  shramba,
}: PrijavaProviderProps) {
  const sqlite = useSQLiteContext();
  const db = useMemo(() => dbLastnost ?? asMaterialsDatabase(sqlite), [dbLastnost, sqlite]);

  const nastavitve = useMemo(
    () => (nastavitveLastnost === undefined ? preberiNastavitve() : nastavitveLastnost),
    [nastavitveLastnost],
  );

  const [seja, setSejaStanja] = useState<Seja | null>(null);

  // Ista vrednost kot `seja`, dosegljiva **po** `await`. `povezi` počaka na
  // konec branja ob zagonu in šele nato pogleda, katero sejo zamenjuje; iz
  // zaprtja bi takrat prebral vrednost izpred čakanja — pri povezavi, ki
  // aplikacijo šele odpre, vedno `null` — in prejšnje seje na strežniku ne bi
  // odjavil.
  const trenutna = useRef<Seja | null>(null);
  const setSeja = useCallback((nova: Seja | null) => {
    trenutna.current = nova;
    setSejaStanja(nova);
  }, []);

  // Obljuba, ki se izpolni, ko je branje žetona z diska ob zagonu končano.
  // Nanjo počaka `povezi`: povezava, ki aplikacijo šele odpre, sproži
  // unovčenje, še preden je to branje steklo — in branje bi nato novo sejo v
  // stanju prepisalo s staro, v najslabšem primeru (oznaka iz `ADR-037`) pa
  // pravkar shranjen žeton pobrisalo z diska.
  //
  // Nastane ob prvem izrisu in ne v učinku: učinki otrok tečejo pred učinki
  // staršev, zato bi zaslon s povezavo sicer čakal na obljubo, ki je še ni.
  // Stanje z začetno funkcijo in ne referenca: vrednost se ne spremeni nikoli,
  // referenc pa se med izrisom ne bere.
  const [zagon] = useState(() => {
    let koncan: () => void = () => {};
    const obljuba = new Promise<void>((izpolni) => {
      koncan = izpolni;
    });
    return { obljuba, koncan };
  });

  // Žeton z diska ob zagonu. Ne `preberiSejo` ne `posvoji` ne vržeta, zato tu
  // ni veje za napako: nedosegljiva shramba ali baza pomeni neprijavljeno
  // aplikacijo oziroma odloženo posvojitev, ne pokvarjene aplikacije.
  //
  // Dokler branje ne konča, je aplikacija videti neprijavljena, in posnetek,
  // ki nastane v tem oknu, ostane brez lastnika. Zato **posvoji tudi obnovitev
  // seje**, ne samo prijava: okno se ne odpre le ob zagonu, ampak tudi, kadar
  // branje ali brisanje iz varne shrambe spodleti — in tak zapis bi sicer
  // ostal nedosegljiv za vedno, ker ga ne vidi ne Zgodovina ne vrsta za
  // prenos (`docs/odlocitve/ADR-036` B).
  useEffect(() => {
    let velja = true;
    void (async () => {
      try {
        const najdena = await preberiSejo(shramba);
        // Žeton, ki ga sreča oznaka o nedokončani odjavi, je **ostanek** in ne
        // seja (`docs/odlocitve/ADR-037`). Brez tega bi se po spodleteli odjavi
        // prejšnja seja obnovila in posvojila posnetke, ki jih je med tem
        // naredil kdo drug.
        if (najdena !== null && (await ostanekOdjave(db))) {
          if (await pozabiSejo(shramba)) await koncaj(db);
          if (!velja) return;
          setSeja(null);
          return;
        }
        // Posvojitev teče pred `velja`: tudi če je zaslon medtem odšel, je
        // vrstica že v bazi in pravi lastnik je znan. Klic je idempotenten.
        if (najdena !== null) await posvoji(db, najdena.userId);
        if (!velja) return;
        setSeja(najdena);
      } finally {
        // V vsakem primeru: povezava, ki čaka na zagon, ne sme čakati večno.
        zagon.koncan();
      }
    })();
    return () => {
      velja = false;
    };
  }, [db, setSeja, shramba, zagon]);

  const povezi = useCallback(
    async (zeton: string) => {
      await zagon.obljuba;
      const prejsnja = trenutna.current;
      // Unovčenje je **prvo** (`ADR-061` I): če spodleti, vrže in vse ostane,
      // kot je bilo — tudi seja, ki je morda že bila.
      const nova = await poveziSe(nastavitve, zeton);
      // Nova seja staro prepiše pod istim ključem v enem zapisu, zato stari
      // žeton na disku ne ostane in oznake iz `ADR-037` ta pot ne postavlja.
      await shraniSejo(nova, shramba);
      // Posvojitev je del povezave in ne prenosa: zapisi, ki so nastali, ko ni
      // bil povezan nihče, bi sicer v vrsti obtičali za vedno (`ADR-036` B).
      // Isto stori obnovitev seje z diska; pravilo je „vsaka razrešena seja
      // posvoji". Zapisi prejšnjega otroka ostanejo njegovi.
      await posvoji(db, nova.userId);
      // Nova povezava prekliče vsako nedokončano odjavo pred njo: žeton na
      // disku je odslej ta, ne prejšnji (`ADR-037`).
      await koncaj(db);
      setSeja(nova);
      // Prejšnja seja te naprave na strežniku ni več potrebna. Najboljši
      // poskus, kot pri odjavi (`ADR-036` G), in nanj se ne čaka: telefon je
      // že povezan in zaslon naj ne visi na strežniku.
      if (prejsnja !== null && prejsnja.zeton !== nova.zeton) {
        void odjaviSe(nastavitve, prejsnja);
      }
    },
    [db, nastavitve, setSeja, shramba, zagon],
  );

  const odjavi = useCallback(async () => {
    const prejsnja = seja;
    // Oznaka **pred** brisanjem: obratni vrstni red bi pustil okno, v katerem
    // je žeton že izbrisan, oznake pa še ni — in prav v tem oknu uporabnica
    // aplikacijo najpogosteje zapre (`docs/odlocitve/ADR-037`).
    await zacni(db);
    // Nato lokalno: nedosegljiva shramba ali strežnik ne smeta pustiti otroka
    // prijavljenega na napravi, na kateri se je hotel odjaviti (`ADR-036` G).
    setSeja(null);
    if (await pozabiSejo(shramba)) await koncaj(db);
    if (prejsnja !== null) await odjaviSe(nastavitve, prejsnja);
  }, [db, nastavitve, seja, setSeja, shramba]);

  const vrednost = useMemo<PrijavaVrednost>(
    () => ({ seja, povezi, odjavi }),
    [odjavi, povezi, seja],
  );

  return <PrijavaContext.Provider value={vrednost}>{children}</PrijavaContext.Provider>;
}

/**
 * Mirna vrednost zunaj ponudnika — ena sama, na ravni modula, iz istega
 * razloga kot pri kvizih: nov objekt ob vsakem klicu bi prožil učinke zaslonov.
 */
const BREZ_PONUDNIKA: PrijavaVrednost = {
  seja: null,
  povezi: async () => {},
  odjavi: async () => {},
};

/** Kdo je prijavljen. Zunaj ponudnika: nihče, in to ni napaka. */
export function usePrijava(): PrijavaVrednost {
  return useContext(PrijavaContext) ?? BREZ_PONUDNIKA;
}
