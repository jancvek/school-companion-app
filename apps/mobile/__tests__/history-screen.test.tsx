import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import HistoryForSubjectScreen from '../app/zgodovina/[subject]';
import { insertMaterial } from '@/db/materials';
import { migriraj } from '@/db/migrations';
import { SyncProvider } from '@/sync/use-sync';
import type { Material } from '@/types';

import { createTestDatabase } from './test-database';
import { theme } from '@/ui/theme';
import { odmikSpodaj, TEST_INSETS, type RouterMockState } from './screen-mocks';

jest.mock('expo-router', () => require('./screen-mocks').expoRouterMock());
jest.mock('expo-sqlite', () => require('./screen-mocks').expoSqliteMock());
jest.mock('react-native-safe-area-context', () => require('./screen-mocks').safeAreaMock());

const usmerjevalnik = jest.requireMock('expo-router') as { stanje: RouterMockState };
const sqlite = jest.requireMock('expo-sqlite') as { stanje: { db: unknown } };

function material(overrides: Partial<Material> = {}): Material {
  const zapis: Material = {
    id: 'id-1',
    subject: 'MAT',
    taken_at: '2026-09-01T10:00:00.000Z',
    file_uri: '',
    sync_status: 'pending',
    sync_attempts: 0,
    last_attempt_at: null,
    sync_error: null,
    ...overrides,
  };
  // Ime datoteke sledi id-ju, tako kot v `saveCapture`.
  return { ...zapis, file_uri: overrides.file_uri ?? `file:///documents/photos/${zapis.id}.jpg` };
}

let db: ReturnType<typeof createTestDatabase>;

beforeEach(async () => {
  jest.clearAllMocks();
  db = createTestDatabase();
  await migriraj(db);
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

  it('zadnji posnetek ne obtiči pod sistemsko navigacijsko vrstico', async () => {
    await insertMaterial(db, material({ id: 'mat-1' }));

    await render(<HistoryForSubjectScreen />);

    const seznam = await screen.findByTestId('seznam-posnetkov');

    expect(odmikSpodaj(seznam.props.contentContainerStyle)).toBe(
      theme.spacing + TEST_INSETS.bottom,
    );
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
    // Merilo dokončanosti: sporočilo mora povedati, kaj naj uporabnica naredi,
    // ne le surove napake.
    expect(screen.getByText(/Vrni se in poskusi znova/)).toBeTruthy();
    expect(screen.getByText(/baza je zaklenjena/)).toBeTruthy();
  });
});

describe('stanje prenosa v zgodovini', () => {
  it('vsako stanje ima svojo oznako', async () => {
    await insertMaterial(db, material({ id: 'a', sync_status: 'pending' }));
    await insertMaterial(db, material({ id: 'b', sync_status: 'synced' }));
    await insertMaterial(db, material({ id: 'c', sync_status: 'failed' }));

    await render(<HistoryForSubjectScreen />);

    expect(await screen.findByTestId('stanje-prenosa-pending')).toBeTruthy();
    expect(screen.getByTestId('stanje-prenosa-synced')).toBeTruthy();
    expect(screen.getByTestId('stanje-prenosa-failed')).toBeTruthy();
  });

  it('oznake so v slovenščini in povedo stanje', async () => {
    await insertMaterial(db, material({ id: 'a', sync_status: 'pending' }));

    await render(<HistoryForSubjectScreen />);

    expect(await screen.findByText('Čaka na prenos')).toBeTruthy();
  });

  it('gumb „Poskusi znova" je viden samo, kadar je kaj neuspelo', async () => {
    await insertMaterial(db, material({ id: 'a', sync_status: 'pending' }));

    await render(<HistoryForSubjectScreen />);

    await screen.findAllByTestId('posnetek');
    expect(screen.queryByTestId('poskusi-znova')).toBeNull();
  });

  it('gumb se pokaže ob neuspelem zapisu', async () => {
    await insertMaterial(db, material({ id: 'a', sync_status: 'failed' }));

    await render(<HistoryForSubjectScreen />);

    expect(await screen.findByTestId('poskusi-znova')).toBeTruthy();
  });
});

describe('gumb „Poskusi znova"', () => {
  it('vrne neuspel zapis v vrsto in počisti napako', async () => {
    await insertMaterial(
      db,
      material({ id: 'a', sync_status: 'failed', sync_error: 'strežnik je zavrnil ključ' }),
    );
    const prenesiEno = jest.fn(() => new Promise<never>(() => {}));

    await render(
      <SyncProvider db={db} nastavitve={null} prenesiEno={prenesiEno}>
        <HistoryForSubjectScreen />
      </SyncProvider>,
    );

    await fireEvent.press(await screen.findByTestId('poskusi-znova'));

    await waitFor(async () => {
      const [vrstica] = await db.getAllAsync<Material>(
        'SELECT * FROM materials WHERE id = ?',
        ['a'],
      );
      expect(vrstica.sync_status).toBe('pending');
      expect(vrstica.sync_error).toBeNull();
    });
  });

  it('po dotiku gumba seznam pokaže novo stanje in gumb izgine', async () => {
    await insertMaterial(db, material({ id: 'a', sync_status: 'failed' }));

    await render(
      <SyncProvider db={db} nastavitve={null}>
        <HistoryForSubjectScreen />
      </SyncProvider>,
    );

    await fireEvent.press(await screen.findByTestId('poskusi-znova'));

    // Brez osvežitve seznama bi gumb izgledal, kot da ni naredil ničesar.
    expect(await screen.findByTestId('stanje-prenosa-pending')).toBeTruthy();
    await waitFor(() => expect(screen.queryByTestId('poskusi-znova')).toBeNull());
  });
});
