import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Alert } from 'react-native';

import CaptureScreen, { POTRDITEV_MS } from '../app/slikaj/[subject]';
import { dovoljenje, type CameraMockState, type RouterMockState } from './screen-mocks';

/**
 * Napis „Shranjeno" sam ugasne, števec pa ostane (ADR-003). Za to so potrebne
 * lažne ure, zato živi v svoji datoteki — mešanje z resničnimi bi bilo v
 * ostalih testih zaslona samo vir nestabilnosti.
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

let alert: jest.SpyInstance;

beforeEach(() => {
  jest.clearAllMocks();
  jest.useFakeTimers();
  usmerjevalnik.stanje.params = { subject: 'MAT' };
  kamera.stanje.permission = dovoljenje();
  kamera.stanje.takePictureAsync.mockResolvedValue({ uri: 'file:///cache/posnetek.jpg' });
  shranjevanje.saveCapture.mockResolvedValue({ id: 'x' });
  alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
});

afterEach(() => {
  jest.clearAllTimers();
  jest.useRealTimers();
  alert.mockRestore();
});

it('napis „Shranjeno" sam ugasne, števec pa ostane', async () => {
  await render(<CaptureScreen />);

  await fireEvent.press(screen.getByText('Fotografiraj'));
  await fireEvent.press(await screen.findByText('Shrani'));

  await waitFor(() => expect(screen.getByText('Shranjeno')).toBeTruthy());
  expect(screen.getByText('V tej seji: 1')).toBeTruthy();

  await act(async () => {
    jest.advanceTimersByTime(POTRDITEV_MS + 100);
  });

  expect(screen.queryByText('Shranjeno')).toBeNull();
  expect(screen.getByText('V tej seji: 1')).toBeTruthy();
});
