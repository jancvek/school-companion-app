import { render, waitFor } from '@testing-library/react-native';
import { AppState, Text, type AppStateStatus } from 'react-native';

import { insertMaterial } from '@/db/materials';
import { migriraj } from '@/db/migrations';
import { SyncProvider } from '@/sync/use-sync';
import type { Izid } from '@/sync/upload';
import type { Material } from '@/types';

import { createTestDatabase } from './test-database';

/**
 * „Worker teče samo v ospredju" je razčiščena zahteva iz faze 1
 * (`docs/verzije/v1.md`, razdelek V1-R02). Prenos v ozadju je izrecno zunaj
 * obsega, zato mora worker ob odhodu aplikacije v ozadje res obmolkniti — in
 * ob vrnitvi spet oživeti.
 */

jest.mock('expo-sqlite', () => require('./screen-mocks').expoSqliteMock());

const NASTAVITVE = { baseUrl: 'http://sto.ts.net:8000', apiKey: 'kljuc' };
const USPEH: Izid = { vrsta: 'synced' };

let db: ReturnType<typeof createTestDatabase>;
let prvotnoStanje: string;
/** Poslušalec, ki ga ponudnik prijavi na `AppState`. */
let sporociStanje: (stanje: AppStateStatus) => void;

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
  jest.spyOn(AppState, 'addEventListener').mockImplementation((dogodek, poslusalec) => {
    if (dogodek === 'change') {
      sporociStanje = poslusalec as (stanje: AppStateStatus) => void;
    }
    return { remove: jest.fn() };
  });
});

afterEach(() => {
  (AppState as { currentState: string }).currentState = prvotnoStanje;
  jest.restoreAllMocks();
  db.close();
});

async function izrisi(prenesiEno: jest.Mock) {
  return render(
    <SyncProvider db={db} nastavitve={NASTAVITVE} prenesiEno={prenesiEno}>
      <Text>vsebina</Text>
    </SyncProvider>,
  );
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

it('ob odhodu v ozadje se ustavi, ob vrnitvi spet zažene', async () => {
  (AppState as { currentState: string }).currentState = 'background';
  await insertMaterial(db, material('a'));
  const prenesiEno = jest.fn(async () => USPEH);

  await izrisi(prenesiEno);
  await new Promise(process.nextTick);
  expect(prenesiEno).not.toHaveBeenCalled();

  sporociStanje('active');
  await waitFor(() => expect(prenesiEno).toHaveBeenCalledTimes(1));

  // Po prenosu ni več ničesar v vrsti; nov zapis in odhod v ozadje.
  await insertMaterial(db, material('b'));
  sporociStanje('background');
  await new Promise(process.nextTick);
  expect(prenesiEno).toHaveBeenCalledTimes(1);

  sporociStanje('active');
  await waitFor(() => expect(prenesiEno).toHaveBeenCalledTimes(2));
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
