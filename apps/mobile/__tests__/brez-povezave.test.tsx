import { randomUUID } from 'node:crypto';

import { fireEvent, render, screen, waitFor, act } from '@testing-library/react-native';

import PoveziScreen from '../app/povezi';
import {
  countByStatus,
  listBySubject,
  listPending,
  type MaterialsDatabase,
} from '@/db/materials';
import { migriraj } from '@/db/migrations';
import { saveCapture } from '@/materials/save';
import { PrijavaProvider } from '@/sync/use-prijava';
import { SyncProvider } from '@/sync/use-sync';

import { ustvariShrambo } from './shramba';
import { createTestDatabase } from './test-database';
import { dovoljenje, type CameraMockState, type RouterMockState } from './screen-mocks';

jest.mock('expo-router', () => require('./screen-mocks').expoRouterMock());
jest.mock('expo-camera', () => require('./screen-mocks').expoCameraMock());
jest.mock('expo-sqlite', () => require('./screen-mocks').expoSqliteMock());
jest.mock('react-native-safe-area-context', () => require('./screen-mocks').safeAreaMock());
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
}));
jest.mock('expo-crypto', () => ({ __esModule: true, randomUUID: jest.fn() }));
jest.mock('@/photos/store', () => ({
  __esModule: true,
  savePhoto: jest.fn(),
  discardPhoto: jest.fn(),
}));

const usmerjevalnik = jest.requireMock('expo-router') as { stanje: RouterMockState };
const kamera = jest.requireMock('expo-camera') as { stanje: CameraMockState };
const crypto = jest.requireMock('expo-crypto') as { randomUUID: jest.Mock };
const store = jest.requireMock('@/photos/store') as { savePhoto: jest.Mock };

const NASTAVITVE = { baseUrl: 'https://school-buddy.duckdns.org' };
const KODA = 'school-companion://povezi?z=aB3_dE6-gH9jKlMnOpQrStUvWxYz0123456789-_AbC';

/**
 * Kriterij `V6-R01`: **načelo brez povezave velja naprej** (`ADR-036` A,
 * `ADR-058` G) — brez povezave kamera, shranjevanje in zgodovina delajo.
 *
 * Povezava telefona je nadomestila prijavo in je, tako kot ona, edino, kar
 * omrežje potrebuje. Ta test gre čez cel dan otroka brez omrežja in brez
 * povezanega telefona: posnetek nastane, Zgodovina ga pokaže, poskus povezave
 * pove, kaj je narobe, in posnetka ne izgubi; ko omrežje pride, ga povezava
 * posvoji.
 */
describe('telefon brez omrežja in brez povezave', () => {
  let db: MaterialsDatabase & { close(): void };
  let omrezje: jest.Mock;

  beforeEach(async () => {
    jest.clearAllMocks();
    usmerjevalnik.stanje.params = {};
    usmerjevalnik.stanje.router.canGoBack.mockReturnValue(true);
    kamera.stanje.permission = dovoljenje();
    crypto.randomUUID.mockImplementation(() => randomUUID());
    store.savePhoto.mockImplementation(
      async (_izvor: string, ime: string) => `file:///documents/photos/${ime}`,
    );
    db = createTestDatabase();
    await migriraj(db);
    // Omrežja ni: vsaka zahteva pade, kot pade na telefonu brez signala.
    omrezje = jest.fn(async () => {
      throw new Error('Network request failed');
    });
    (globalThis as { fetch?: unknown }).fetch = omrezje;
  });

  afterEach(() => {
    db.close();
    delete (globalThis as { fetch?: unknown }).fetch;
  });

  it('posnetek se shrani in Zgodovina ga pokaže, čeprav ni ne omrežja ne povezave', async () => {
    const posnetek = await saveCapture(db, {
      subject: 'MAT',
      takenAt: '2026-10-12T08:15:00.000Z',
      sourceUri: 'file:///cache/Camera/original.jpg',
      userId: null,
    });

    // Shranjevanje omrežja ni niti poskusilo doseči.
    expect(omrezje).not.toHaveBeenCalled();
    // Zgodovina nepovezanega telefona bere zapise brez lastnika.
    expect((await listBySubject(db, 'MAT', null)).map((m) => m.id)).toEqual([posnetek.id]);
    expect(await countByStatus(db, null)).toMatchObject({ pending: 1, failed: 0 });
  });

  it('poskus povezave brez omrežja pove, kaj narediti, in posnetka ne izgubi', async () => {
    const posnetek = await saveCapture(db, {
      subject: 'MAT',
      takenAt: '2026-10-12T08:15:00.000Z',
      sourceUri: 'file:///cache/Camera/original.jpg',
      userId: null,
    });
    const shramba = ustvariShrambo();
    await render(
      <PrijavaProvider db={db} nastavitve={NASTAVITVE} shramba={shramba}>
        <SyncProvider db={db} nastavitve={NASTAVITVE}>
          <PoveziScreen />
        </SyncProvider>
      </PrijavaProvider>,
    );
    await act(async () => {});

    await fireEvent(screen.getByTestId('kamera'), 'barcodeScanned', { data: KODA });

    const besedilo = (await screen.findByTestId('napaka-povezave')).props.children as string;
    expect(besedilo).toMatch(/ni dosegljiv/i);
    expect(besedilo).toMatch(/posnetki na telefonu ostanejo/i);
    expect(shramba.vsebina()).toBeUndefined();
    // Posnetek je še vedno tam, še vedno čaka in še vedno nima lastnika.
    expect((await listBySubject(db, 'MAT', null)).map((m) => m.id)).toEqual([posnetek.id]);
    expect((await listPending(db, null)).map((m) => m.id)).toEqual([posnetek.id]);

    // Omrežje pride nazaj: ista koda uspe in posnetek dobi lastnika.
    omrezje.mockImplementation(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        token: 'nov-zeton',
        user_id: 'u-masa',
        display_name: 'Maša',
        expires_at: '2026-11-11T10:00:00+00:00',
      }),
    }));
    await fireEvent.press(screen.getByTestId('gumb-znova'));
    await fireEvent(screen.getByTestId('kamera'), 'barcodeScanned', { data: KODA });

    await waitFor(() => expect(usmerjevalnik.stanje.router.back).toHaveBeenCalled());
    await waitFor(async () => {
      expect((await listPending(db, 'u-masa')).map((m) => m.id)).toEqual([posnetek.id]);
    });
    expect((await listBySubject(db, 'MAT', 'u-masa')).map((m) => m.id)).toEqual([posnetek.id]);
  });
});
