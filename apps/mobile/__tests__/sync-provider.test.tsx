import { act, render, waitFor } from '@testing-library/react-native';
import { AppState, Text, type AppStateStatus } from 'react-native';

import { findById, insertMaterial } from '@/db/materials';
import { migriraj } from '@/db/migrations';
import { SyncProvider } from '@/sync/use-sync';
import type { Odjemalec } from '@/sync/izbrisi';
import type { Izid } from '@/sync/upload';
import { INTERVAL_MS } from '@/sync/worker';
import type { Material } from '@/types';

import { createTestDatabase } from './test-database';

/**
 * „Worker teče samo v ospredju" je razčiščena zahteva iz faze 1
 * (`docs/verzije/v1.md`, razdelek V1-R02). Prenos v ozadju je izrecno zunaj
 * obsega, zato mora worker ob odhodu aplikacije v ozadje res obmolkniti — in
 * ob vrnitvi spet oživeti.
 */

jest.mock('expo-sqlite', () => require('./screen-mocks').expoSqliteMock());

// Brisanje arhivirane snovi se dotakne datoteke prek `expo-file-system`.
// Podtaknemo ga, da ta test govori o priklopu na življenjski cikel in ne o
// disku; datoteke tu nikoli ni.
jest.mock('expo-file-system', () => ({
  __esModule: true,
  File: class {
    exists = false;
    delete() {}
  },
  UploadType: { MULTIPART: 'multipart' },
}));

const NASTAVITVE = { baseUrl: 'http://sto.ts.net:8000', apiKey: 'kljuc' };
const USPEH: Izid = { vrsta: 'synced' };

let db: ReturnType<typeof createTestDatabase>;
let prvotnoStanje: string;
/** Poslušalci, ki jih ponudnik prijavi na `AppState`. */
let poslusalci: ((stanje: AppStateStatus) => void)[];

/**
 * Sporoči novo stanje vsem prijavljenim poslušalcem.
 *
 * Seznam in ne ena vrednost: od V1-R07 ponudnik prijavi dva — prenos in
 * preverjanje arhiva. Mock, ki bi hranil zadnjega, bi prvega utišal in test
 * bi padel iz razloga, ki z njegovo trditvijo nima zveze.
 */
function sporociStanje(stanje: AppStateStatus): void {
  for (const poslusalec of [...poslusalci]) poslusalec(stanje);
}

/** Odjemalec za arhiv, ki nikoli ničesar ne najde. */
const MIREN_ODJEMALEC: Odjemalec = {
  preberiSeznam: async () => [],
  potrdi: async () => {},
};

function material(id: string): Material {
  return {
    id,
    subject: 'MAT',
    taken_at: '2026-09-01T10:00:00.000Z',
    file_uri: `file:///documents/photos/${id}.jpg`,
    sync_status: 'pending',
    sync_attempts: 0,
    last_attempt_at: null,
    sync_error: null,
  };
}

beforeEach(async () => {
  jest.clearAllMocks();
  db = createTestDatabase();
  await migriraj(db);

  prvotnoStanje = AppState.currentState;
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

async function izrisi(prenesiEno: jest.Mock, odjemalec = MIREN_ODJEMALEC) {
  return render(
    <SyncProvider
      db={db}
      nastavitve={NASTAVITVE}
      prenesiEno={prenesiEno}
      odjemalec={odjemalec}
    >
      <Text>vsebina</Text>
    </SyncProvider>,
  );
}

/** Odjemalec, ki enkrat vrne dani seznam in si zapomni potrditve. */
function odjemalecZ(ids: string[]): Odjemalec & {
  preberiSeznam: jest.Mock;
  potrdi: jest.Mock;
} {
  return {
    preberiSeznam: jest.fn(async () => ids),
    potrdi: jest.fn(async (_kaj: string[]) => {}),
  };
}

it('v ospredju prenaša', async () => {
  (AppState as { currentState: string }).currentState = 'active';
  await insertMaterial(db, material('a'));
  const prenesiEno = jest.fn(async () => USPEH);

  await izrisi(prenesiEno);

  await waitFor(() => expect(prenesiEno).toHaveBeenCalledTimes(1));
});

it('če aplikacija ob vpetju ni v ospredju, ne prenaša', async () => {
  (AppState as { currentState: string }).currentState = 'background';
  await insertMaterial(db, material('a'));
  const prenesiEno = jest.fn(async () => USPEH);

  await izrisi(prenesiEno);
  await new Promise(process.nextTick);

  expect(prenesiEno).not.toHaveBeenCalled();
});

it('ob vrnitvi v ospredje spet zažene', async () => {
  (AppState as { currentState: string }).currentState = 'background';
  await insertMaterial(db, material('a'));
  const prenesiEno = jest.fn(async () => USPEH);

  await izrisi(prenesiEno);
  await new Promise(process.nextTick);
  expect(prenesiEno).not.toHaveBeenCalled();

  sporociStanje('active');

  await waitFor(() => expect(prenesiEno).toHaveBeenCalledTimes(1));
});

/** Počaka, da se dokonča cikel workerja; ta je veriga več mikroopravil. */
async function pocakajNaCikel(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 20; i += 1) await Promise.resolve();
  });
}

it('ob odhodu v ozadje se ustavi in ne prenaša naprej', async () => {
  // Lažne ure so tu bistvo testa, ne pripomoček. Brez premika časa bi bila
  // trditev prazna: razporejeni časovnik je 30-sekundni, v testu z resničnimi
  // urami nikoli ne poči, zato bi test ostal zelen tudi, če se worker ob
  // odhodu v ozadje sploh ne bi ustavil.
  jest.useFakeTimers();
  try {
    (AppState as { currentState: string }).currentState = 'active';
    await insertMaterial(db, material('a'));
    const prenesiEno = jest.fn(async () => USPEH);

    await izrisi(prenesiEno);
    await pocakajNaCikel();
    expect(prenesiEno).toHaveBeenCalledTimes(1);

    // Nov zapis v vrsti, aplikacija pa gre v ozadje.
    await insertMaterial(db, material('b'));
    sporociStanje('background');

    await act(async () => {
      jest.advanceTimersByTime(INTERVAL_MS * 3);
    });
    await pocakajNaCikel();

    // Brez `ustavi()` bi razporejeni časovnik tu počil in `b` bi šel na
    // strežnik, medtem ko je aplikacija v ozadju.
    expect(prenesiEno).toHaveBeenCalledTimes(1);

    sporociStanje('active');
    await pocakajNaCikel();

    expect(prenesiEno).toHaveBeenCalledTimes(2);
  } finally {
    jest.useRealTimers();
  }
});

it('brez nastavitev se worker ne prijavi na AppState', async () => {
  (AppState as { currentState: string }).currentState = 'active';
  await insertMaterial(db, material('a'));

  await render(
    <SyncProvider db={db} nastavitve={null}>
      <Text>vsebina</Text>
    </SyncProvider>,
  );
  await new Promise(process.nextTick);

  // Aplikacija deluje kot v V1-R01; zapis mirno čaka.
  expect(AppState.addEventListener).not.toHaveBeenCalled();
  const [vrstica] = await db.getAllAsync<Material>('SELECT * FROM materials', []);
  expect(vrstica.sync_status).toBe('pending');
});

/**
 * Preverjanje arhiva (V1-R07).
 *
 * Brez teh testov je mogoče priklop na življenjski cikel v celoti odstraniti,
 * zbirka pa ostane zelena: enotski testi v `sync-izbrisi.test.ts` preverjajo
 * `preveriIzbrisane` in ponavljalnik **ločeno**, nikoli spojena skozi
 * ponudnika. Aplikacija bi arhiviranih slik ne zbrisala nikoli.
 */
it('v ospredju pobriše snov, ki je na strežniku arhivirana', async () => {
  (AppState as { currentState: string }).currentState = 'active';
  await insertMaterial(db, material('a'));
  const odjemalec = odjemalecZ(['a']);

  await izrisi(jest.fn(async () => USPEH), odjemalec);

  await waitFor(async () => expect(await findById(db, 'a')).toBeNull());
  expect(odjemalec.potrdi).toHaveBeenCalledWith(['a']);
});

it('če aplikacija ob vpetju ni v ospredju, arhiva ne preverja', async () => {
  (AppState as { currentState: string }).currentState = 'background';
  const odjemalec = odjemalecZ(['a']);

  await izrisi(jest.fn(async () => USPEH), odjemalec);
  await new Promise(process.nextTick);

  expect(odjemalec.preberiSeznam).not.toHaveBeenCalled();
});

it('ob vrnitvi v ospredje spet preveri arhiv', async () => {
  (AppState as { currentState: string }).currentState = 'background';
  await insertMaterial(db, material('a'));
  const odjemalec = odjemalecZ(['a']);

  await izrisi(jest.fn(async () => USPEH), odjemalec);
  await new Promise(process.nextTick);
  expect(odjemalec.preberiSeznam).not.toHaveBeenCalled();

  sporociStanje('active');

  await waitFor(async () => expect(await findById(db, 'a')).toBeNull());
});
