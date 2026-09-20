/**
 * Priklop usklajevanja kvizov na življenjski cikel aplikacije (V2-R02).
 *
 * Svoj ponudnik in ne razširitev `SyncProvider`: ima svoj ritem, svoje stanje
 * (število čakajočih, odprti kviz) in svoje vmesnike. `SyncProvider` bi s tem
 * postal predal za vse, kar se kdaj dotakne strežnika.
 *
 * Teče samo v ospredju, kot vse ostalo: ob zagonu, ob vrnitvi v ospredje in
 * nato vsakih 5 minut. Takoj tudi po zadnji oceni kviza (`sprozi`).
 */

import { useSQLiteContext } from 'expo-sqlite';
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
import { AppState } from 'react-native';

import { preberiNastavitve, type ServerConfig } from '../config/server';
import { cakajociKvizi } from '../db/kvizi';
import type { MaterialsDatabase } from '../db/materials';
import { asMaterialsDatabase } from '../db/open';
import { ustvariPonavljalnik, type Ponavljalnik } from './izbrisi';
import { uskladiKvize, ustvariOdjemalcaKvizov, type OdjemalecKvizov } from './kvizi';
import { usePrijava } from './use-prijava';

export type KviziVrednost = {
  /** Koliko kvizov čaka na reševanje — iz lokalne baze. */
  cakajocih: number;
  /** Znova prebere število čakajočih. */
  osvezi(): Promise<void>;
  /** Takojšnje usklajevanje; ne čaka na izid. */
  sprozi(): void;
  /**
   * Kviz, ki ga Maša rešuje. Usklajevanje ga ne pobriše, tudi če ga strežnik
   * ne vrača več (`docs/odlocitve/ADR-019` C).
   */
  odpri(id: string): void;
  zapri(): void;
};

const KviziContext = createContext<KviziVrednost | null>(null);

export type KviziProviderProps = {
  children: ReactNode;
  /** Podtakljivo v testih; sicer baza iz `SQLiteProvider`. */
  db?: MaterialsDatabase;
  /** Podtakljivo v testih; sicer nastavitve iz gradnje. */
  nastavitve?: ServerConfig | null;
  /** Podtakljivo v testih; sicer pravi klic na strežnik. */
  odjemalec?: OdjemalecKvizov;
};

export function KviziProvider({
  children,
  db: dbLastnost,
  nastavitve: nastavitveLastnost,
  odjemalec: odjemalecLastnost,
}: KviziProviderProps) {
  const sqlite = useSQLiteContext();
  const db = useMemo(() => dbLastnost ?? asMaterialsDatabase(sqlite), [dbLastnost, sqlite]);

  const nastavitve = useMemo(
    () => (nastavitveLastnost === undefined ? preberiNastavitve() : nastavitveLastnost),
    [nastavitveLastnost],
  );

  const { seja } = usePrijava();
  const lastnik = seja?.userId ?? null;

  // Brez naslova ali brez prijave odjemalca ni: kvizi ne pridejo, aplikacija
  // pa deluje naprej kot pred V2-R02 (`docs/odlocitve/ADR-036` A).
  const odjemalec = useMemo<OdjemalecKvizov | null>(
    () =>
      odjemalecLastnost ??
      (nastavitve && seja ? ustvariOdjemalcaKvizov(nastavitve, seja) : null),
    [nastavitve, odjemalecLastnost, seja],
  );

  const [cakajocih, setCakajocih] = useState(0);
  const odprti = useRef<string | null>(null);
  const ponavljalnik = useRef<Ponavljalnik | null>(null);
  // Poskusi, ki jih je strežnik posamič zavrnil s 422 — za čas zagona
  // aplikacije, ne v bazi (`docs/odlocitve/ADR-020`). Ob novem zagonu se
  // poskusijo znova.
  const zavrnjeni = useRef<Set<string>>(new Set());

  const osvezi = useCallback(async () => {
    try {
      setCakajocih((await cakajociKvizi(db, lastnik)).length);
    } catch {
      // Števec je postranska informacija; napaka pri štetju ne sme podreti
      // domače strani. Isto pravilo kot pri števcu prenosa.
    }
  }, [db, lastnik]);

  useEffect(() => {
    if (odjemalec === null) return;

    const nov = ustvariPonavljalnik({
      naloga: async () => {
        await uskladiKvize(db, odjemalec, lastnik, odprti.current, zavrnjeni.current);
        await osvezi();
      },
    });
    ponavljalnik.current = nov;

    if (AppState.currentState === 'active') nov.zazeni();

    const narocnina = AppState.addEventListener('change', (stanje) => {
      if (stanje === 'active') {
        nov.zazeni();
      } else {
        nov.ustavi();
      }
    });

    return () => {
      narocnina.remove();
      nov.ustavi();
      ponavljalnik.current = null;
    };
  }, [db, lastnik, odjemalec, osvezi]);

  const sprozi = useCallback(() => {
    // `zazeni` pri tekočem obhodu ne naredi ničesar (zapora v ponavljalniku),
    // sicer takoj obhodi in razporedi naslednjega. V ozadju ne sprožimo —
    // tja usklajevanje ne sodi.
    if (AppState.currentState !== 'active') return;
    ponavljalnik.current?.zazeni();
  }, []);

  const odpri = useCallback((id: string) => {
    odprti.current = id;
  }, []);

  const zapri = useCallback(() => {
    odprti.current = null;
  }, []);

  const vrednost = useMemo<KviziVrednost>(
    () => ({ cakajocih, osvezi, sprozi, odpri, zapri }),
    [cakajocih, osvezi, sprozi, odpri, zapri],
  );

  return <KviziContext.Provider value={vrednost}>{children}</KviziContext.Provider>;
}

/**
 * Mirna vrednost zunaj ponudnika.
 *
 * **Ena sama, na ravni modula**, in ne nov objekt ob vsakem klicu: zaslon da
 * `osvezi` v odvisnosti `useFocusEffect`, in nova funkcija ob vsakem izrisu
 * bi učinek prožila znova in znova — skupaj s števcem prenosa, ki ob vsakem
 * proženju nastavi stanje, v neskončni zanki izrisov.
 */
const BREZ_PONUDNIKA: KviziVrednost = {
  cakajocih: 0,
  osvezi: async () => {},
  sprozi: () => {},
  odpri: () => {},
  zapri: () => {},
};

/**
 * Stanje kvizov. Zunaj ponudnika vrne mirno privzeto vrednost namesto izjeme
 * — zaslon, ki ga kdo izriše samostojno, se ne sme sesuti.
 */
export function useKvizi(): KviziVrednost {
  return useContext(KviziContext) ?? BREZ_PONUDNIKA;
}
