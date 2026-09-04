import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Alert, Linking } from 'react-native';

import CaptureScreen from '../app/slikaj/[subject]';

import { theme } from '@/ui/theme';

import {
  dovoljenje,
  odmikSpodaj,
  TEST_INSETS,
  type CameraMockState,
  type RouterMockState,
} from './screen-mocks';

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

/** Posname sliko in počaka na predogled. */
async function fotografiraj() {
  await fireEvent.press(screen.getByText('Fotografiraj'));
  return screen.findByText('Shrani');
}

let alert: jest.SpyInstance;

beforeEach(() => {
  jest.clearAllMocks();
  usmerjevalnik.stanje.params = { subject: 'MAT' };
  kamera.stanje.permission = dovoljenje();
  kamera.stanje.takePictureAsync.mockResolvedValue({ uri: 'file:///cache/posnetek.jpg' });
  shranjevanje.saveCapture.mockResolvedValue({ id: 'x' });
  alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
});

afterEach(() => {
  alert.mockRestore();
});

describe('dovoljenje za kamero', () => {
  it('med preverjanjem ne pokaže ne kamere ne napake', async () => {
    kamera.stanje.permission = null;

    await render(<CaptureScreen />);

    expect(screen.queryByTestId('kamera')).toBeNull();
    expect(screen.queryByText('Potrebujem dovoljenje za kamero')).toBeNull();
  });

  it('ob zavrnitvi pokaže prijazno sporočilo in gumb za ponovni poskus', async () => {
    kamera.stanje.permission = dovoljenje({ granted: false, canAskAgain: true });

    await render(<CaptureScreen />);

    expect(screen.getByText('Potrebujem dovoljenje za kamero')).toBeTruthy();
    expect(screen.queryByTestId('kamera')).toBeNull();

    await fireEvent.press(screen.getByText('Dovoli kamero'));

    expect(kamera.stanje.requestPermission).toHaveBeenCalledTimes(1);
  });

  it('ko vprašanje ni več mogoče, ponudi nastavitve telefona', async () => {
    kamera.stanje.permission = dovoljenje({ granted: false, canAskAgain: false });
    const nastavitve = jest.spyOn(Linking, 'openSettings').mockResolvedValue(undefined);

    await render(<CaptureScreen />);

    await fireEvent.press(screen.getByText('Odpri nastavitve'));

    expect(nastavitve).toHaveBeenCalledTimes(1);
    expect(kamera.stanje.requestPermission).not.toHaveBeenCalled();
    nastavitve.mockRestore();
  });

  it('z dovoljenjem pokaže kamero', async () => {
    await render(<CaptureScreen />);

    expect(screen.getByTestId('kamera')).toBeTruthy();
    expect(screen.getByText('Fotografiraj')).toBeTruthy();
  });
});

describe('neznan predmet', () => {
  it('pove, da predmet ni na seznamu, in ne odpre kamere', async () => {
    usmerjevalnik.stanje.params = { subject: 'XXX' };

    await render(<CaptureScreen />);

    expect(screen.getByText('Neznan predmet')).toBeTruthy();
    expect(screen.queryByTestId('kamera')).toBeNull();
  });
});

describe('predogled', () => {
  it('po posnetku ponudi Shrani in Ponovi', async () => {
    await render(<CaptureScreen />);

    await fotografiraj();

    expect(screen.getByText('Shrani')).toBeTruthy();
    expect(screen.getByText('Ponovi')).toBeTruthy();
    expect(screen.queryByTestId('kamera')).toBeNull();
  });

  it('„Ponovi" zavrže posnetek in vrne kamero, brez shranjevanja', async () => {
    await render(<CaptureScreen />);

    await fotografiraj();
    await fireEvent.press(screen.getByText('Ponovi'));

    expect(screen.getByTestId('kamera')).toBeTruthy();
    expect(screen.queryByText('Shrani')).toBeNull();
    expect(shranjevanje.saveCapture).not.toHaveBeenCalled();
  });

  it('„Ponovi" je mogoče uporabiti večkrat zapored', async () => {
    await render(<CaptureScreen />);

    for (let i = 0; i < 3; i++) {
      await fotografiraj();
      await fireEvent.press(screen.getByText('Ponovi'));
      expect(screen.getByTestId('kamera')).toBeTruthy();
    }

    expect(shranjevanje.saveCapture).not.toHaveBeenCalled();
  });
});

describe('shranjevanje', () => {
  it('shrani s kodo predmeta in časom posnetka', async () => {
    await render(<CaptureScreen />);

    await fotografiraj();
    await fireEvent.press(screen.getByText('Shrani'));

    await waitFor(() => expect(shranjevanje.saveCapture).toHaveBeenCalledTimes(1));

    const [, vhod] = shranjevanje.saveCapture.mock.calls[0];
    expect(vhod.subject).toBe('MAT');
    expect(vhod.sourceUri).toBe('file:///cache/posnetek.jpg');
    expect(vhod.takenAt).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);

    // ADR-003: ne gremo več na domačo stran in ne odpiramo modalnega okna.
    expect(usmerjevalnik.stanje.router.dismissAll).not.toHaveBeenCalled();
    expect(alert).not.toHaveBeenCalled();
  });

  it('po shranjevanju vrne kamero istega predmeta, pripravljeno na naslednjo stran', async () => {
    await render(<CaptureScreen />);

    await fotografiraj();
    await fireEvent.press(screen.getByText('Shrani'));

    await waitFor(() => expect(screen.getByTestId('kamera')).toBeTruthy());

    expect(screen.getByText('Fotografiraj')).toBeTruthy();
    expect(screen.queryByText('Shrani')).toBeNull();
    expect(screen.queryByText('Ponovi')).toBeNull();
  });

  it('potrdi z napisom in šteje shranjene v tej seji', async () => {
    await render(<CaptureScreen />);

    await fotografiraj();
    await fireEvent.press(screen.getByText('Shrani'));

    await waitFor(() => expect(screen.getByText('Shranjeno')).toBeTruthy());
    expect(screen.getByText('V tej seji: 1')).toBeTruthy();

    kamera.stanje.takePictureAsync.mockResolvedValue({ uri: 'file:///cache/druga.jpg' });
    await fotografiraj();
    await fireEvent.press(screen.getByText('Shrani'));

    await waitFor(() => expect(screen.getByText('V tej seji: 2')).toBeTruthy());
    expect(shranjevanje.saveCapture).toHaveBeenCalledTimes(2);
  });

  it('vsak posnetek da svojo vrstico, z lastnim časom in potjo', async () => {
    await render(<CaptureScreen />);

    await fotografiraj();
    await fireEvent.press(screen.getByText('Shrani'));
    await waitFor(() => expect(shranjevanje.saveCapture).toHaveBeenCalledTimes(1));

    kamera.stanje.takePictureAsync.mockResolvedValue({ uri: 'file:///cache/druga.jpg' });
    await fotografiraj();
    await fireEvent.press(screen.getByText('Shrani'));
    await waitFor(() => expect(shranjevanje.saveCapture).toHaveBeenCalledTimes(2));

    const [, prvi] = shranjevanje.saveCapture.mock.calls[0];
    const [, drugi] = shranjevanje.saveCapture.mock.calls[1];
    expect(prvi.sourceUri).toBe('file:///cache/posnetek.jpg');
    expect(drugi.sourceUri).toBe('file:///cache/druga.jpg');
    expect(drugi.subject).toBe('MAT');
  });

  it('ob napaki obdrži predogled, ne šteje in ne potrdi', async () => {
    shranjevanje.saveCapture.mockRejectedValue(new Error('Na napravi ni prostora'));

    await render(<CaptureScreen />);

    await fotografiraj();
    await fireEvent.press(screen.getByText('Shrani'));

    await waitFor(() => expect(alert).toHaveBeenCalled());

    expect(alert).toHaveBeenCalledWith(
      'Shranjevanje ni uspelo',
      expect.stringContaining('Na napravi ni prostora'),
    );
    expect(screen.getByText('Shrani')).toBeTruthy();
    expect(screen.queryByText('Shranjeno')).toBeNull();
    expect(screen.queryByText('V tej seji: 1')).toBeNull();
  });

  it('po neuspehu je mogoče poskusiti znova', async () => {
    shranjevanje.saveCapture.mockRejectedValueOnce(new Error('Na napravi ni prostora'));

    await render(<CaptureScreen />);

    await fotografiraj();
    await fireEvent.press(screen.getByText('Shrani'));
    await waitFor(() => expect(alert).toHaveBeenCalled());

    await fireEvent.press(screen.getByText('Shrani'));

    await waitFor(() => expect(screen.getByText('V tej seji: 1')).toBeTruthy());
    expect(shranjevanje.saveCapture).toHaveBeenCalledTimes(2);
  });
});

describe('varno območje', () => {
  // Točna vrednost, ne „vsaj toliko" — sicer bi test prepustil tudi trdo
  // vpisano konstanto, ki z odmiki nima nič.
  const PRICAKOVAN = theme.spacing + TEST_INSETS.bottom;

  it('gumbi imajo odmik za sistemsko navigacijsko vrstico', async () => {
    await render(<CaptureScreen />);

    expect(odmikSpodaj(screen.getByTestId('akcije').props.style)).toBe(PRICAKOVAN);
  });

  it('odmik ostane tudi v predogledu', async () => {
    await render(<CaptureScreen />);
    await fotografiraj();

    expect(odmikSpodaj(screen.getByTestId('akcije').props.style)).toBe(PRICAKOVAN);
  });
});
