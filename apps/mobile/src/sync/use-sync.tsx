/**
 * Priklop workerja na življenjski cikel aplikacije.
 *
 * Worker je eden, zato živi v kontekstu in ne v vsakem zaslonu posebej — dva
 * hkratna bi isti zapis poslala dvakrat.
 *
 * Teče samo, dokler je aplikacija v ospredju. Ko gre v ozadje, se ustavi:
 * prenos v ozadju je izrecno zunaj obsega V1-R02.
 *
 * Datoteka je `.tsx` in ne `.ts`, kot je predvideval plan, ker vsebuje
 * ponudnika konteksta.
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
import { countByStatus, retryFailed, type MaterialsDatabase } from '../db/materials';
import { asMaterialsDatabase } from '../db/open';
import type { SyncPovzetek } from '../types';
import { prenesi, type Izid } from './upload';
import { ustvariRazporejevalnik, type PrenesiEno, type Razporejevalnik } from './worker';

const PRAZEN_POVZETEK: SyncPovzetek = { pending: 0, synced: 0, failed: 0 };

export type SyncVrednost = {
  /** Ali sta naslov strežnika in ključ sploh prišla v to gradnjo. */
  nastavljen: boolean;
  povzetek: SyncPovzetek;
  /** Znova prebere števce iz baze. */
  osvezi(): Promise<void>;
  /** Takojšen poskus prenosa; ne čaka na izid. */
  sprozi(): void;
  /** Vrne neuspele zapise v vrsto in takoj poskusi znova. */
  poskusiZnova(): Promise<void>;
};

const SyncContext = createContext<SyncVrednost | null>(null);

export type SyncProviderProps = {
  children: ReactNode;
  /** Podtakljivo v testih; sicer baza iz `SQLiteProvider`. */
  db?: MaterialsDatabase;
  /** Podtakljivo v testih; sicer nastavitve iz gradnje. */
  nastavitve?: ServerConfig | null;
  /** Podtakljivo v testih; sicer pravi prenos. */
  prenesiEno?: PrenesiEno;
};

export function SyncProvider({
  children,
  db: dbLastnost,
  nastavitve: nastavitveLastnost,
  prenesiEno: prenesiEnoLastnost,
}: SyncProviderProps) {
  const sqlite = useSQLiteContext();
  const db = useMemo(
    () => dbLastnost ?? asMaterialsDatabase(sqlite),
    [dbLastnost, sqlite],
  );

  const nastavitve = useMemo(
    () => (nastavitveLastnost === undefined ? preberiNastavitve() : nastavitveLastnost),
    [nastavitveLastnost],
  );

  const [povzetek, setPovzetek] = useState<SyncPovzetek>(PRAZEN_POVZETEK);
  const razporejevalnik = useRef<Razporejevalnik | null>(null);

  const osvezi = useCallback(async () => {
    try {
      setPovzetek(await countByStatus(db));
    } catch {
      // Števec je postranska informacija. Če je ni, zaslon še vedno dela —
      // napaka pri štetju ne sme podreti domače strani.
    }
  }, [db]);

  const prenesiEno = useCallback<PrenesiEno>(
    async (material): Promise<Izid> => {
      if (prenesiEnoLastnost) return prenesiEnoLastnost(material);
      if (!nastavitve) return { vrsta: 'pending', razlog: 'Prenos ni nastavljen.' };
      return prenesi(material, nastavitve);
    },
    [nastavitve, prenesiEnoLastnost],
  );

  // Prvega branja števcev tu ni namenoma: zaslon, ki jih kaže, jih prebere ob
  // prihodu nase (`useFocusEffect`), worker pa po vsakem ciklu. Branje še ob
  // vpetju ponudnika bi bilo tretja pot do iste stvari — in setState v telesu
  // učinka, ki ga React Compiler upravičeno javi.
  useEffect(() => {
    // Brez naslova ali ključa se worker sploh ne zažene. Aplikacija deluje
    // naprej kot v V1-R01, zapisi pa mirno čakajo (odločitev 11).
    if (!nastavitve && !prenesiEnoLastnost) {
      razporejevalnik.current = null;
      return;
    }

    const nov = ustvariRazporejevalnik({
      db,
      prenesiEno,
      poCiklu: () => {
        void osvezi();
      },
    });
    razporejevalnik.current = nov;

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
      razporejevalnik.current = null;
    };
  }, [db, nastavitve, osvezi, prenesiEno, prenesiEnoLastnost]);

  const sprozi = useCallback(() => {
    razporejevalnik.current?.sprozi();
  }, []);

  const poskusiZnova = useCallback(async () => {
    await retryFailed(db);
    await osvezi();
    razporejevalnik.current?.sprozi();
  }, [db, osvezi]);

  const vrednost = useMemo<SyncVrednost>(
    () => ({ nastavljen: nastavitve !== null, povzetek, osvezi, sprozi, poskusiZnova }),
    [nastavitve, osvezi, poskusiZnova, povzetek, sprozi],
  );

  return <SyncContext.Provider value={vrednost}>{children}</SyncContext.Provider>;
}

/**
 * Stanje prenosa. Zunaj ponudnika vrne mirno privzeto vrednost namesto
 * izjeme — zaslon, ki ga kdo izriše samostojno, se ne sme sesuti.
 */
export function useSync(): SyncVrednost {
  const vrednost = useContext(SyncContext);
  if (vrednost) return vrednost;

  return {
    nastavljen: false,
    povzetek: PRAZEN_POVZETEK,
    osvezi: async () => {},
    sprozi: () => {},
    poskusiZnova: async () => {},
  };
}
