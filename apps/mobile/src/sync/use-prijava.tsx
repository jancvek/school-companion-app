/**
 * Kdo je prijavljen na tej napravi (V3-R04).
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
  useState,
  type ReactNode,
} from 'react';

import { preberiNastavitve, type ServerConfig } from '../config/server';
import { posvojiBrezLastnika, type MaterialsDatabase } from '../db/materials';
import { asMaterialsDatabase } from '../db/open';
import { useSQLiteContext } from 'expo-sqlite';
import {
  odjaviSe,
  pozabiSejo,
  preberiSejo,
  prijaviSe,
  shraniSejo,
  type Seja,
  type VarnaShramba,
} from './prijava';

export type PrijavaVrednost = {
  /** Trenutna seja, ali `null`, kadar ni prijavljen nihče. */
  seja: Seja | null;
  /**
   * Prijavi se. Ob neuspehu **vrže** `NapakaPrijave` s slovenskim sporočilom,
   * ki ga zaslon pokaže; ob uspehu posvoji zapise brez lastnika.
   */
  prijavi(identifikator: string, geslo: string): Promise<void>;
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

  const [seja, setSeja] = useState<Seja | null>(null);

  // Žeton z diska ob zagonu. `preberiSejo` ne vrže nikoli, zato tu ni veje za
  // napako: nedosegljiva shramba pomeni neprijavljeno aplikacijo, ne pokvarjene.
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
      const najdena = await preberiSejo(shramba);
      // Posvojitev teče pred `velja`: tudi če je zaslon medtem odšel, je
      // vrstica že v bazi in pravi lastnik je znan. Klic je idempotenten.
      if (najdena !== null) await posvojiBrezLastnika(db, najdena.userId);
      if (!velja) return;
      setSeja(najdena);
    })();
    return () => {
      velja = false;
    };
  }, [db, shramba]);

  const prijavi = useCallback(
    async (identifikator: string, geslo: string) => {
      const nova = await prijaviSe(nastavitve, identifikator, geslo);
      await shraniSejo(nova, shramba);
      // Posvojitev je del prijave in ne prenosa: zapisi, ki so nastali, ko ni
      // bil prijavljen nihče — na Mašinem telefonu ob nadgradnji vsi —, bi
      // sicer v vrsti obtičali za vedno (`ADR-036` B). Isto stori obnovitev
      // seje z diska; pravilo je „vsaka razrešena seja posvoji", ne „prijava".
      await posvojiBrezLastnika(db, nova.userId);
      setSeja(nova);
    },
    [db, nastavitve, shramba],
  );

  const odjavi = useCallback(async () => {
    const prejsnja = seja;
    // Najprej lokalno: nedosegljiv strežnik ne sme pustiti otroka
    // prijavljenega na napravi, na kateri se je hotel odjaviti (`ADR-036` G).
    setSeja(null);
    await pozabiSejo(shramba);
    if (prejsnja !== null) await odjaviSe(nastavitve, prejsnja);
  }, [nastavitve, seja, shramba]);

  const vrednost = useMemo<PrijavaVrednost>(
    () => ({ seja, prijavi, odjavi }),
    [odjavi, prijavi, seja],
  );

  return <PrijavaContext.Provider value={vrednost}>{children}</PrijavaContext.Provider>;
}

/**
 * Mirna vrednost zunaj ponudnika — ena sama, na ravni modula, iz istega
 * razloga kot pri kvizih: nov objekt ob vsakem klicu bi prožil učinke zaslonov.
 */
const BREZ_PONUDNIKA: PrijavaVrednost = {
  seja: null,
  prijavi: async () => {},
  odjavi: async () => {},
};

/** Kdo je prijavljen. Zunaj ponudnika: nihče, in to ni napaka. */
export function usePrijava(): PrijavaVrednost {
  return useContext(PrijavaContext) ?? BREZ_PONUDNIKA;
}
