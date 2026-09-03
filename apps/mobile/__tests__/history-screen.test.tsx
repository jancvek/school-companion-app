import { render, screen, waitFor } from '@testing-library/react-native';

import HistoryForSubjectScreen from '../app/zgodovina/[subject]';
import { createMaterialsTable, insertMaterial } from '@/db/materials';
import type { Material } from '@/types';

import { createTestDatabase } from './test-database';

jest.mock('expo-router', () => {
  const stanje = {
    params: { subject: 'GUM' } as Record<string, string>,
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

jest.mock('expo-sqlite', () => {
  const stanje = { db: {} as unknown };
  return { __esModule: true, useSQLiteContext: () => stanje.db, stanje };
});

const usmerjevalnik = jest.requireMock('expo-router') as {
  stanje: { params: Record<string, string> };
};
const sqlite = jest.requireMock('expo-sqlite') as { stanje: { db: unknown } };

function material(overrides: Partial<Material> = {}): Material {
  const zapis: Material = {
    id: 'id-1',
    subject: 'MAT',
    taken_at: '2026-09-01T10:00:00.000Z',
    file_uri: '',
    sync_status: 'pending',
    ...overrides,
  };
  // Ime datoteke sledi id-ju, tako kot v `saveCapture`.
  return { ...zapis, file_uri: overrides.file_uri ?? `file:///documents/photos/${zapis.id}.jpg` };
}

let db: ReturnType<typeof createTestDatabase>;

beforeEach(async () => {
  jest.clearAllMocks();
  db = createTestDatabase();
  await createMaterialsTable(db);
  sqlite.stanje.db = db;
  usmerjevalnik.stanje.params = { subject: 'MAT' };
});

afterEach(() => {
  db.close();
});

describe('zgodovina predmeta', () => {
  it('pri predmetu brez posnetkov pokaže jasno sporočilo, ne napake', async () => {
    usmerjevalnik.stanje.params = { subject: 'GUM' };

    await render(<HistoryForSubjectScreen />);

    expect(await screen.findByText('Še ni posnetkov')).toBeTruthy();
    expect(screen.getByText(/GUM — Glasbena umetnost/)).toBeTruthy();
  });

  it('pokaže posnetke od najnovejšega navzdol', async () => {
    await insertMaterial(db, material({ id: 'star', taken_at: '2026-09-01T08:00:00.000Z' }));
    await insertMaterial(db, material({ id: 'nov', taken_at: '2026-09-03T08:00:00.000Z' }));

    await render(<HistoryForSubjectScreen />);

    const slike = await screen.findAllByTestId('posnetek');
    expect(slike.map((slika) => slika.props.source.uri)).toEqual([
      'file:///documents/photos/nov.jpg',
      'file:///documents/photos/star.jpg',
    ]);
  });

  it('ne pokaže posnetkov drugih predmetov', async () => {
    await insertMaterial(db, material({ id: 'mat-1', subject: 'MAT' }));
    await insertMaterial(db, material({ id: 'slj-1', subject: 'SLJ' }));

    await render(<HistoryForSubjectScreen />);

    const slike = await screen.findAllByTestId('posnetek');
    expect(slike).toHaveLength(1);
    expect(slike[0].props.source.uri).toBe('file:///documents/photos/mat-1.jpg');
  });

  it('pri neznanem predmetu ne poskuša brati baze', async () => {
    usmerjevalnik.stanje.params = { subject: 'XXX' };
    const poizvedba = jest.spyOn(db, 'getAllAsync');

    await render(<HistoryForSubjectScreen />);

    expect(screen.getByText('Neznan predmet')).toBeTruthy();
    expect(poizvedba).not.toHaveBeenCalled();
    poizvedba.mockRestore();
  });

  it('napako pri branju pokaže, namesto da bi se sesula', async () => {
    jest.spyOn(db, 'getAllAsync').mockRejectedValue(new Error('baza je zaklenjena'));

    await render(<HistoryForSubjectScreen />);

    expect(await screen.findByText('Zgodovine ni bilo mogoče prebrati')).toBeTruthy();
    expect(screen.getByText('baza je zaklenjena')).toBeTruthy();
  });
});
