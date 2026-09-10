import { act, render, waitFor } from '@testing-library/react-native';
import { AppState, Text, type AppStateStatus } from 'react-native';

import { shraniKviz, zapisiPoskus } from '@/db/kvizi';
import { migriraj } from '@/db/migrations';
import { PaketZavrnjen, type OdjemalecKvizov } from '@/sync/kvizi';
import { KviziProvider } from '@/sync/use-kvizi';
import type { Poskus } from '@/types';

import { kvizStreznika, poskus } from './kvizi-podatki';
import { createTestDatabase } from './test-database';

/**
 * Priklop usklajevanja kvizov na življenjski cikel (V2-R02, `ADR-020`).
 *
 * Pomnjenje zavrnjenih poskusov živi v ponudniku. Enotski testi v
 * `sync-kvizi.test.ts` množico podajo sami in zato ne vidijo, ali jo ponudnik
 * res ohrani med obhodi — ponudnik, ki bi vsakič podal novo, bi bil tam zelen.
 *
 * **Vsak izris se na koncu odmontira.** Ponudnik razporedi 5-minutni časovnik;
 * test, ki ga pusti živega, jestu ne da končati (šesti pregled V2-R02).
 */

jest.mock('expo-sqlite', () => require('./screen-mocks').expoSqliteMock());

let db: ReturnType<typeof createTestDatabase>;
let prvotnoStanje: string;
let poslusalci: ((stanje: AppStateStatus) => void)[];

/** Sporoči novo stanje vsem prijavljenim poslušalcem, znotraj `act`. */
async function sporociStanje(stanje: AppStateStatus): Promise<void> {
  await act(async () => {
    for (const poslusalec of [...poslusalci]) poslusalec(stanje);
  });
}

beforeEach(async () => {
  db = createTestDatabase();
  await migriraj(db);
  prvotnoStanje = AppState.currentState;
  (AppState as { currentState: string }).currentState = 'active';
  poslusalci = [];
  jest.spyOn(AppState, 'addEventListener').mockImplementation((dogodek, poslusalec) => {
    if (dogodek !== 'change') return { remove: jest.fn() };
    const f = poslusalec as (stanje: AppStateStatus) => void;
    poslusalci.push(f);
    return {
      remove: jest.fn(() => {
        poslusalci = poslusalci.filter((p) => p !== f);
      }),
    };
  });
});

afterEach(() => {
  (AppState as { currentState: string }).currentState = prvotnoStanje;
  jest.restoreAllMocks();
  db.close();
});

/** Strežnik, ki vsak paket zavrne s 422 in vrača isti kviz. */
function zavracajoc(): OdjemalecKvizov & { posljiPoskuse: jest.Mock; preberiKvize: jest.Mock } {
  return {
    posljiPoskuse: jest.fn(async (_p: readonly Poskus[]) => {
      throw new PaketZavrnjen(422);
    }),
    preberiKvize: jest.fn(async () => [kvizStreznika('k1', 2)]),
  };
}

function izrisi(streznik: OdjemalecKvizov) {
  return render(
    <KviziProvider db={db} nastavitve={null} odjemalec={streznik}>
      <Text>vsebina</Text>
    </KviziProvider>,
  );
}

it('zavrnjene poskuse si zapomni med obhodi in jih ob novem zagonu poskusi znova', async () => {
  await shraniKviz(db, kvizStreznika('k1', 2));
  await zapisiPoskus(db, poskus('k1', 1));
  await zapisiPoskus(db, poskus('k1', 2));
  const streznik = zavracajoc();

  const prvi = await izrisi(streznik);
  try {
    // Prvi obhod: paket z dvema in oba posamič.
    await waitFor(() => expect(streznik.preberiKvize).toHaveBeenCalledTimes(1));
    expect(streznik.posljiPoskuse).toHaveBeenCalledTimes(3);

    // Vrnitev v ospredje sproži nov obhod v istem zagonu.
    await sporociStanje('background');
    await sporociStanje('active');
    await waitFor(() => expect(streznik.preberiKvize).toHaveBeenCalledTimes(2));
    expect(streznik.posljiPoskuse).toHaveBeenCalledTimes(3);
  } finally {
    // `await`: odmontiranje je v tej različici knjižnice asinhrono. Brez njega
    // se prekriva z naslednjim izrisom in ponavljalnik se ne ustavi.
    await prvi.unmount();
  }

  // Nov zagon aplikacije: nov ponudnik, prazna množica.
  const drugi = await izrisi(streznik);
  try {
    await waitFor(() => expect(streznik.preberiKvize).toHaveBeenCalledTimes(3));
    expect(streznik.posljiPoskuse).toHaveBeenCalledTimes(6);
  } finally {
    await drugi.unmount();
  }
});
