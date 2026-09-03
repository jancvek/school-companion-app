import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Alert, Linking } from 'react-native';

import CaptureScreen from '../app/slikaj/[subject]';

jest.mock('expo-router', () => {
  const stanje = {
    params: { subject: 'MAT' } as Record<string, string>,
    router: { push: jest.fn(), back: jest.fn(), dismissAll: jest.fn() },
  };
  return {
    __esModule: true,
    Stack: { Screen: () => null },
    useRouter: () => stanje.router,
    useLocalSearchParams: () => stanje.params,
    stanje,
  };
});

jest.mock('expo-camera', () => {
  const React = require('react');
  const { View } = require('react-native');
  const stanje = {
    permission: null as unknown,
    requestPermission: jest.fn(),
    takePictureAsync: jest.fn(),
  };
  const CameraView = React.forwardRef((props: object, ref: unknown) => {
    React.useImperativeHandle(ref, () => ({
      takePictureAsync: (...args: unknown[]) => stanje.takePictureAsync(...args),
    }));
    return React.createElement(View, { ...props, testID: 'kamera' });
  });
  CameraView.displayName = 'CameraView';
  return {
    __esModule: true,
    CameraView,
    useCameraPermissions: () => [stanje.permission, stanje.requestPermission],
    stanje,
  };
});

jest.mock('expo-sqlite', () => {
  const stanje = { db: {} as unknown };
  return { __esModule: true, useSQLiteContext: () => stanje.db, stanje };
});

jest.mock('@/materials/save', () => ({
  __esModule: true,
  saveCapture: jest.fn(),
}));

const usmerjevalnik = jest.requireMock('expo-router') as {
  stanje: {
    params: Record<string, string>;
    router: { push: jest.Mock; back: jest.Mock; dismissAll: jest.Mock };
  };
};
const kamera = jest.requireMock('expo-camera') as {
  stanje: { permission: unknown; requestPermission: jest.Mock; takePictureAsync: jest.Mock };
};
const shranjevanje = jest.requireMock('@/materials/save') as { saveCapture: jest.Mock };

function dovoljenje(overrides: Partial<{ granted: boolean; canAskAgain: boolean }> = {}) {
  return {
    granted: true,
    canAskAgain: true,
    status: 'granted',
    expires: 'never',
    ...overrides,
  };
}

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
  it('shrani s kodo predmeta in časom posnetka, nato vrne na domačo stran', async () => {
    await render(<CaptureScreen />);

    await fotografiraj();
    await fireEvent.press(screen.getByText('Shrani'));

    await waitFor(() => expect(shranjevanje.saveCapture).toHaveBeenCalledTimes(1));

    const [, vhod] = shranjevanje.saveCapture.mock.calls[0];
    expect(vhod.subject).toBe('MAT');
    expect(vhod.sourceUri).toBe('file:///cache/posnetek.jpg');
    expect(vhod.takenAt).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);

    expect(usmerjevalnik.stanje.router.dismissAll).toHaveBeenCalledTimes(1);
    expect(alert).toHaveBeenCalledWith('Shranjeno', expect.stringContaining('MAT'));
  });

  it('po uspešnem shranjevanju nadaljnji dotiki ne shranijo znova', async () => {
    await render(<CaptureScreen />);
    await fotografiraj();

    const shrani = screen.getByText('Shrani');
    await fireEvent.press(shrani);
    await waitFor(() => expect(shranjevanje.saveCapture).toHaveBeenCalledTimes(1));

    await fireEvent.press(shrani);
    await fireEvent.press(shrani);

    expect(shranjevanje.saveCapture).toHaveBeenCalledTimes(1);
    expect(usmerjevalnik.stanje.router.dismissAll).toHaveBeenCalledTimes(1);
  });

  it('ob napaki obdrži predogled in pove, kaj se je zgodilo', async () => {
    shranjevanje.saveCapture.mockRejectedValue(new Error('Na napravi ni prostora'));

    await render(<CaptureScreen />);

    await fotografiraj();
    await fireEvent.press(screen.getByText('Shrani'));

    await waitFor(() => expect(alert).toHaveBeenCalled());

    expect(alert).toHaveBeenCalledWith(
      'Shranjevanje ni uspelo',
      expect.stringContaining('Na napravi ni prostora'),
    );
    expect(usmerjevalnik.stanje.router.dismissAll).not.toHaveBeenCalled();
    expect(screen.getByText('Shrani')).toBeTruthy();
  });
});
