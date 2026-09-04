import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Alert } from 'react-native';

import CaptureScreen from '../app/slikaj/[subject]';
import { dovoljenje, type CameraMockState, type RouterMockState } from './screen-mocks';

/**
 * Dva dotika v istem tiku — razlog, zakaj je zapora v `app/slikaj/[subject].tsx`
 * `useRef` in ne `useState`: oba klica vidita isto (staro) vrednost stanja.
 *
 * Živi v svoji datoteki namenoma. Dva prekrivajoča se `act(...)` klica pustita
 * upodabljalnik v stanju, ki podre naslednji test v isti datoteki; z lastnim
 * paketom to nikogar ne moti.
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
let napake: jest.SpyInstance;

beforeEach(() => {
  jest.clearAllMocks();
  // Prekrivajoča se act(...) klica pustita upodabljalnik v stanju, iz katerega
  // se komponenta ne odklopi čisto — časovnik napisa „Shranjeno" bi zato ostal
  // odprt in jest ne bi končal. Z lažnimi urami pravega časovnika sploh ni.
  jest.useFakeTimers();
  // React se pritoži nad prekrivajočima se act(...) klicema. Prav ta prekritje
  // je bistvo tega testa, zato utišamo natanko to sporočilo — vsa ostala
  // ostanejo vidna.
  const izvirni = console.error;
  napake = jest.spyOn(console, 'error').mockImplementation((...args) => {
    if (typeof args[0] === 'string' && args[0].includes('overlapping act()')) return;
    izvirni(...args);
  });
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
  napake.mockRestore();
});

it('dva dotika na Shrani v istem tiku shranita samo enkrat', async () => {
  await render(<CaptureScreen />);

  await fireEvent.press(screen.getByText('Fotografiraj'));
  const shrani = await screen.findByText('Shrani');

  // Brez `await` med njima: oba onPress stečeta, preden se stanje osveži.
  const prvi = fireEvent.press(shrani);
  const drugi = fireEvent.press(shrani);
  await Promise.all([prvi, drugi]);

  // ADR-003: zaslon ostane odprt, zato se konec shranjevanja vidi po števcu.
  await waitFor(() => expect(screen.getByText('V tej seji: 1')).toBeTruthy());

  expect(shranjevanje.saveCapture).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('V tej seji: 2')).toBeNull();
});
