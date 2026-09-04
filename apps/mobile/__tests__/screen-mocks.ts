/**
 * Skupni mocki za komponentne teste zaslonov.
 *
 * Kličejo se iz `jest.mock(..., () => require('./screen-mocks').xMock())`.
 * Vsak testni paket dobi svojo kopijo stanja, ker jest za vsako datoteko
 * naredi svoj register modulov.
 */

export type RouterMockState = {
  params: Record<string, string>;
  router: { push: jest.Mock; back: jest.Mock; dismissAll: jest.Mock };
};

export function expoRouterMock() {
  const stanje: RouterMockState = {
    params: {},
    router: { push: jest.fn(), back: jest.fn(), dismissAll: jest.fn() },
  };
  return {
    __esModule: true,
    Stack: { Screen: () => null },
    useRouter: () => stanje.router,
    useLocalSearchParams: () => stanje.params,
    stanje,
  };
}

export type CameraMockState = {
  permission: unknown;
  requestPermission: jest.Mock;
  takePictureAsync: jest.Mock;
};

export function expoCameraMock() {
  const React = require('react');
  const { View } = require('react-native');

  const stanje: CameraMockState = {
    permission: null,
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
}

export function expoSqliteMock() {
  const stanje = { db: {} as unknown };
  return { __esModule: true, useSQLiteContext: () => stanje.db, stanje };
}

/**
 * Odmiki varnega območja. Namenoma niso ničle — mock, ki ga prinaša
 * `react-native-safe-area-context`, jih vrne 0, s čimer test ne bi ločil
 * pravilnega odmika od manjkajočega.
 */
export const TEST_INSETS = { top: 24, bottom: 48, left: 0, right: 0 };

export function safeAreaMock() {
  return {
    __esModule: true,
    useSafeAreaInsets: () => TEST_INSETS,
    SafeAreaProvider: ({ children }: { children: unknown }) => children,
  };
}

/**
 * Zadnji `paddingBottom` iz sloga. React Native sloge podaja kot gnezdena
 * polja, zato jih je treba najprej sploščiti.
 */
export function odmikSpodaj(style: unknown): number {
  const kosi = Array.isArray(style) ? style.flat(Infinity) : [style];
  for (const kos of [...kosi].reverse()) {
    const vrednost = (kos as { paddingBottom?: number } | null)?.paddingBottom;
    if (typeof vrednost === 'number') return vrednost;
  }
  return 0;
}

/** Privzeto dovoljenje za kamero; `overrides` obrne, kar test potrebuje. */
export function dovoljenje(
  overrides: Partial<{ granted: boolean; canAskAgain: boolean }> = {},
) {
  return {
    granted: true,
    canAskAgain: true,
    status: 'granted',
    expires: 'never',
    ...overrides,
  };
}
