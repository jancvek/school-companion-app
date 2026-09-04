import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Alert } from 'react-native';

import CaptureScreen from '../app/slikaj/[subject]';
import { dovoljenje, type CameraMockState, type RouterMockState } from './screen-mocks';

/**
 * Med shranjevanjem sta gumba onemogočena. To ni kozmetika: `Pressable` ob
 * `disabled` `onPress` sploh ne pokliče, in prav to je obramba, ki skupaj z
 * združevanjem izrisov poskrbi, da en posnetek da natanko eno vrstico
 * (glej komentar nad `zaklep` v app/slikaj/[subject].tsx in ADR-003).
 *
 * Zahteva shranjevanje, ki visi, zato datoteka stoji zase — čakanje na tak
 * `fireEvent.press` bi v drugih testih zaklenilo `act(...)`.
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
  usmerjevalnik.stanje.params = { subject: 'MAT' };
  kamera.stanje.permission = dovoljenje();
  kamera.stanje.takePictureAsync.mockResolvedValue({ uri: 'file:///cache/posnetek.jpg' });
  alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
});

afterEach(() => {
  alert.mockRestore();
});

it('med shranjevanjem sta gumba onemogočena, zato drugi dotik ne shrani', async () => {
  let koncaj!: (zapis: unknown) => void;
  shranjevanje.saveCapture.mockReturnValue(
    new Promise((resolve) => {
      koncaj = resolve;
    }),
  );

  await render(<CaptureScreen />);
  await fireEvent.press(screen.getByText('Fotografiraj'));

  const shrani = await screen.findByText('Shrani');
  // Namenoma brez `await`: shranjevanje visi, zato se ta act ne bi nikoli
  // zaključil.
  void fireEvent.press(shrani);

  await waitFor(() => expect(shranjevanje.saveCapture).toHaveBeenCalledTimes(1));

  // Oba gumba sta zdaj onemogočena — to je tisto, kar prepreči drugi klic.
  expect(gumbJeOnemogocen('Shrani')).toBe(true);
  expect(gumbJeOnemogocen('Ponovi')).toBe(true);

  await act(async () => {
    koncaj({ id: 'x' });
  });

  await waitFor(() => expect(screen.getByText('V tej seji: 1')).toBeTruthy());
  expect(shranjevanje.saveCapture).toHaveBeenCalledTimes(1);
});

/** Pressable stanje razglasi prek `accessibilityState`. */
function gumbJeOnemogocen(napis: string): boolean {
  let vozlisce = screen.getByText(napis).parent;

  while (vozlisce) {
    const stanje = vozlisce.props?.accessibilityState;
    if (stanje && 'disabled' in stanje) return stanje.disabled === true;
    vozlisce = vozlisce.parent;
  }

  throw new Error(`Gumb „${napis}" nima accessibilityState.`);
}
