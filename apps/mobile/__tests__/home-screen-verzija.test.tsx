/**
 * Ožičenje domače strani na `opisVerzije` (V1-R06).
 *
 * Svoja datoteka zato, ker potrebuje lasten `expo-constants` — mock v skupni
 * datoteki bi vplival tudi na teste stanja prenosa.
 *
 * Zakaj sploh: test, ki preveri le, da vrstica obstaja in vsebuje besedo
 * „gradnja", ostane zelen tudi, če kdo `{opisVerzije()}` zamenja s trdo
 * vpisanim nizom. Ugotovitev pregledovalca pri prvem pregledu V1-R06.
 */

import { render, screen } from '@testing-library/react-native';

import HomeScreen from '../app/index';

jest.mock('expo-router', () => require('./screen-mocks').expoRouterMock());
jest.mock('expo-sqlite', () => require('./screen-mocks').expoSqliteMock());
jest.mock('react-native-safe-area-context', () => require('./screen-mocks').safeAreaMock());
jest.mock('expo-constants', () => ({
  __esModule: true,
  default: {
    expoConfig: {
      version: '2.3.4',
      extra: { buildId: '317bdcd1-c7db-4c2c-8a6b-1cb1ce15ea29' },
    },
  },
}));

describe('domača stran in vgrajena gradnja', () => {
  it('izpiše natanko tisto verzijo in gradnjo, ki sta prišli ob gradnji', async () => {
    await render(<HomeScreen />);

    // Verzija namenoma ni `1.0.0`: trdo vpisan niz bi tak test preživel.
    expect(await screen.findByText('2.3.4 · gradnja 317bdcd1')).toBeTruthy();
  });
});
