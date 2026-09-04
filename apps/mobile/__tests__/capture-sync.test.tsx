import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Alert } from 'react-native';

import CaptureScreen from '../app/slikaj/[subject]';
import { migriraj } from '@/db/migrations';
import { SyncProvider } from '@/sync/use-sync';

import { createTestDatabase } from './test-database';
import { dovoljenje, type CameraMockState, type RouterMockState } from './screen-mocks';

/**
 * Regresija za ADR-003.
 *
 * Po *Shrani* se prenos samo **sproži** — nanj se ne čaka. Če bi ga počakali,
 * bi zaporedno slikanje pri nedosegljivem strežniku obtičalo do poteka
 * časovne omejitve, kar je natanko tisto, čemur se ADR-003 izogiba.
 *
 * Test to dokaže tako, da prenos **nikoli ne konča**. Če bi ga koda čakala,
 * napisa „Shranjeno" ne bi bilo nikoli in test bi potekel.
 */

jest.mock('expo-router', () => require('./screen-mocks').expoRouterMock());
jest.mock('expo-camera', () => require('./screen-mocks').expoCameraMock());
jest.mock('expo-sqlite', () => require('./screen-mocks').expoSqliteMock());
jest.mock('react-native-safe-area-context', () => require('./screen-mocks').safeAreaMock());

jest.mock('@/materials/save', () => ({
  __esModule: true,
  saveCapture: jest.fn(),
}));

const usmerjevalnik = jest.requireMock('expo-router') as { stanje: RouterMockState };
const kamera = jest.requireMock('expo-camera') as { stanje: CameraMockState };
const shranjevanje = jest.requireMock('@/materials/save') as { saveCapture: jest.Mock };

const NASTAVITVE = { baseUrl: 'http://sto.ts.net:8000', apiKey: 'kljuc' };

let db: ReturnType<typeof createTestDatabase>;
let alert: jest.SpyInstance;

beforeEach(async () => {
  jest.clearAllMocks();
  db = createTestDatabase();
  await migriraj(db);
  usmerjevalnik.stanje.params = { subject: 'MAT' };
  kamera.stanje.permission = dovoljenje();
  kamera.stanje.takePictureAsync.mockResolvedValue({ uri: 'file:///cache/posnetek.jpg' });
  shranjevanje.saveCapture.mockResolvedValue({ id: 'x' });
  alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
});

afterEach(() => {
  db.close();
  alert.mockRestore();
});

it('shranjevanje se konča takoj, tudi če prenos nikoli ne odgovori', async () => {
  // Prenos, ki visi — telefon izven Tailscale omrežja.
  const prenesiEno = jest.fn(() => new Promise<never>(() => {}));

  await render(
    <SyncProvider db={db} nastavitve={NASTAVITVE} prenesiEno={prenesiEno}>
      <CaptureScreen />
    </SyncProvider>,
  );

  await fireEvent.press(screen.getByText('Fotografiraj'));
  await fireEvent.press(await screen.findByText('Shrani'));

  await waitFor(() => expect(screen.getByText('Shranjeno')).toBeTruthy());
  expect(screen.getByText('V tej seji: 1')).toBeTruthy();
  expect(alert).not.toHaveBeenCalled();
});

it('po shranjevanju se vrne na kamero, pripravljeno na naslednjo stran', async () => {
  const prenesiEno = jest.fn(() => new Promise<never>(() => {}));

  await render(
    <SyncProvider db={db} nastavitve={NASTAVITVE} prenesiEno={prenesiEno}>
      <CaptureScreen />
    </SyncProvider>,
  );

  await fireEvent.press(screen.getByText('Fotografiraj'));
  await fireEvent.press(await screen.findByText('Shrani'));

  // Zapora se mora sprostiti, sicer bi bilo zaporedno slikanje mrtvo.
  await waitFor(() => expect(screen.getByText('Fotografiraj')).toBeTruthy());
  expect(screen.queryByText('Shrani')).toBeNull();
});

it('brez nastavljenega prenosa shranjevanje deluje kot v V1-R01', async () => {
  await render(
    <SyncProvider db={db} nastavitve={null}>
      <CaptureScreen />
    </SyncProvider>,
  );

  await fireEvent.press(screen.getByText('Fotografiraj'));
  await fireEvent.press(await screen.findByText('Shrani'));

  await waitFor(() => expect(screen.getByText('Shranjeno')).toBeTruthy());
  expect(shranjevanje.saveCapture).toHaveBeenCalledTimes(1);
  expect(alert).not.toHaveBeenCalled();
});

it('napaka prenosa ne pokvari shranjevanja', async () => {
  const prenesiEno = jest.fn(async () => {
    throw new Error('vse je narobe');
  });

  await render(
    <SyncProvider db={db} nastavitve={NASTAVITVE} prenesiEno={prenesiEno}>
      <CaptureScreen />
    </SyncProvider>,
  );

  await fireEvent.press(screen.getByText('Fotografiraj'));
  await fireEvent.press(await screen.findByText('Shrani'));

  await waitFor(() => expect(screen.getByText('Shranjeno')).toBeTruthy());
  // Napaka prenosa ni napaka shranjevanja — uporabnice ne sme motiti.
  expect(alert).not.toHaveBeenCalled();
});
