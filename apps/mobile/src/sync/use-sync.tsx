/**
 * Priklop workerja na življenjski cikel aplikacije.
 *
 * Worker je eden, zato živi v kontekstu in ne v vsakem zaslonu posebej — dva
 * hkratna bi isti zapis poslala dvakrat.
 *
 * Teče samo, dokler je aplikacija v ospredju. Ko gre v ozadje, se ustavi:
 * prenos v ozadju je izrecno zunaj obsega V1-R02.
 *
 * Od V1-R07 sta tu dve ponavljanji z različnim ritmom: prenos vsakih 30 s (s
 * podvojevanjem po neuspehih) in preverjanje arhiva vsakih 5 minut. Drugo je
 * počasno opravilo brez povoda — 30-sekundni ritem bi bil zanj brez pomena.
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
import {
  preveriIzbrisane,
  ustvariOdjemalca,
  ustvariPonavljalnik,
  type Odjemalec,
  type Ponavljalnik,
} from './izbrisi';
import { usePrijava } from './use-prijava';
import { prenesi, type Izid } from './upload';
import { ustvariRazporejevalnik, type PrenesiEno, type Razporejevalnik } from './worker';

const PRAZEN_POVZETEK: SyncPovzetek = { pending: 0, synced: 0, failed: 0 };

export type SyncVrednost = {
  /** Ali je naslov strežnika sploh prišel v to gradnjo. */
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
  /** Podtakljivo v testih; sicer pravi klic na strežnik (V1-R07). */
  odjemalec?: Odjemalec;
};

export function SyncProvider({
  children,
  db: dbLastnost,
  nastavitve: nastavitveLastnost,
  prenesiEno: prenesiEnoLastnost,
  odjemalec: odjemalecLastnost,
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

  const { seja } = usePrijava();
  // Lastnik zapisov, ki jih ta naprava ta hip prenaša in šteje. `null` pomeni
  // „ni prijavljen nihče" in ne „vsi": tuj zapis ni ne štet ne poslan
  // (`docs/odlocitve/ADR-036` B).
  const lastnik = seja?.userId ?? null;

  const [povzetek, setPovzetek] = useState<SyncPovzetek>(PRAZEN_POVZETEK);
  const razporejevalnik = useRef<Razporejevalnik | null>(null);

  // Odjemalec za arhiv nastane samo, kadar je naslov v gradnji **in** je kdo
  // prijavljen. Brez enega ali drugega aplikacija deluje kot v V1-R01 in nima
  // s kom govoriti.
  const odjemalec = useMemo<Odjemalec | null>(
    () => odjemalecLastnost ?? (nastavitve && seja ? ustvariOdjemalca(nastavitve, seja) : null),
    [nastavitve, odjemalecLastnost, seja],
  );

  const osvezi = useCallback(async () => {
    try {
      setPovzetek(await countByStatus(db, lastnik));
    } catch {
      // Števec je postranska informacija. Če je ni, zaslon še vedno dela —
      // napaka pri štetju ne sme podreti domače strani.
    }
  }, [db, lastnik]);

  const prenesiEno = useCallback<PrenesiEno>(
    async (material): Promise<Izid> => {
      if (prenesiEnoLastnost) return prenesiEnoLastnost(material);
      if (!nastavitve) return { vrsta: 'pending', razlog: 'Prenos ni nastavljen.' };
      if (!seja) return { vrsta: 'pending', razlog: 'Nisi prijavljena.' };
      return prenesi(material, nastavitve, seja);
    },
    [nastavitve, prenesiEnoLastnost, seja],
  );

  // Prvega branja števcev tu ni namenoma: zaslon, ki jih kaže, jih prebere ob
  // prihodu nase (`useFocusEffect`), worker pa po vsakem ciklu. Branje še ob
  // vpetju ponudnika bi bilo tretja pot do iste stvari — in setState v telesu
  // učinka, ki ga React Compiler upravičeno javi.
  useEffect(() => {
    // Brez naslova ali brez prijave se worker sploh ne zažene. Aplikacija
    // deluje naprej kot v V1-R01, zapisi pa mirno čakajo (odločitev 11;
    // `ADR-036` A za prijavo).
    if (!(nastavitve && seja) && !prenesiEnoLastnost) {
      razporejevalnik.current = null;
      return;
    }

    const nov = ustvariRazporejevalnik({
      db,
      lastnik,
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
  }, [db, lastnik, nastavitve, osvezi, prenesiEno, prenesiEnoLastnost, seja]);

  // Preverjanje arhiva (V1-R07). Svoj učinek in ne veja v zgornjem: ritma
  // sta različna, ustavljanje pa je isto — oboje teče samo v ospredju.
  useEffect(() => {
    if (odjemalec === null) return;

    const ponavljalnik: Ponavljalnik = ustvariPonavljalnik({
      naloga: async () => {
        const izid = await preveriIzbrisane(db, odjemalec);
        // Običajen obhod ne najde ničesar in takrat baze ne beremo po
        // nepotrebnem. Ob neuspehu osvežimo, čeprav se baza morda ni
        // spremenila: vrstica je takrat lahko že šla in spodletelo je šele
        // brisanje datoteke, eno odvečno branje pa je cenejše od števca,
        // ki laže.
        //
        // Kadar odpove sama potrditev strežniku, `preveriIzbrisane` vrže in
        // sem sploh ne pridemo. Števci so takrat do naslednjega cikla
        // prenosa (30 s) zastareli; to je zavestna cena, ne spregled.
        if (izid.pobrisani > 0 || izid.neuspeli > 0) await osvezi();
      },
    });

    if (AppState.currentState === 'active') ponavljalnik.zazeni();

    const narocnina = AppState.addEventListener('change', (stanje) => {
      if (stanje === 'active') {
        ponavljalnik.zazeni();
      } else {
        ponavljalnik.ustavi();
      }
    });

    return () => {
      narocnina.remove();
      ponavljalnik.ustavi();
    };
  }, [db, odjemalec, osvezi]);

  const sprozi = useCallback(() => {
    razporejevalnik.current?.sprozi();
  }, []);

  const poskusiZnova = useCallback(async () => {
    await retryFailed(db, lastnik);
    await osvezi();
    razporejevalnik.current?.sprozi();
  }, [db, lastnik, osvezi]);

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
