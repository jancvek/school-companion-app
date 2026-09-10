import { fireEvent, render, screen, within } from '@testing-library/react-native';

import HomeScreen from '../app/index';
import KviziScreen from '../app/kvizi/index';
import { shraniKviz, zapisiPoskus } from '@/db/kvizi';
import { migriraj } from '@/db/migrations';
import { KviziProvider } from '@/sync/use-kvizi';
import { theme } from '@/ui/theme';

import { kvizStreznika, poskus } from './kvizi-podatki';
import { odmikSpodaj, TEST_INSETS, type RouterMockState } from './screen-mocks';
import { createTestDatabase } from './test-database';

jest.mock('expo-router', () => require('./screen-mocks').expoRouterMock());
jest.mock('expo-sqlite', () => require('./screen-mocks').expoSqliteMock());
jest.mock('react-native-safe-area-context', () => require('./screen-mocks').safeAreaMock());

const usmerjevalnik = jest.requireMock('expo-router') as { stanje: RouterMockState };
const sqlite = jest.requireMock('expo-sqlite') as { stanje: { db: unknown } };

let db: ReturnType<typeof createTestDatabase>;

beforeEach(async () => {
  jest.clearAllMocks();
  db = createTestDatabase();
  await migriraj(db);
  sqlite.stanje.db = db;
});

afterEach(() => {
  db.close();
});

describe('seznam kvizov', () => {
  it('našteje čakajoče, najstarejšega prvega, rešenega ne', async () => {
    await shraniKviz(db, kvizStreznika('mlajsi', 2, { name: 'MAT — 10. 9. 2026', created_at: '2026-09-10T08:00:00+00:00' }));
    await shraniKviz(db, kvizStreznika('starejsi', 2, { name: 'SLJ — 8. 9. 2026', created_at: '2026-09-08T08:00:00+00:00' }));
    await shraniKviz(db, kvizStreznika('resen', 1, { name: 'Rešen' }));
    await zapisiPoskus(db, poskus('resen', 1));

    await render(<KviziScreen />);

    const vrstice = await screen.findAllByTestId('kviz');
    expect(vrstice).toHaveLength(2);
    expect(screen.queryByText('Rešen')).toBeNull();
    // Najstarejši prvi, čeprav je bil shranjen drugi.
    expect(within(vrstice[0]).getByText('SLJ — 8. 9. 2026')).toBeTruthy();
    expect(within(vrstice[1]).getByText('MAT — 10. 9. 2026')).toBeTruthy();
  });

  it('napol rešen kviz pove, koliko je odgovorjenega', async () => {
    await shraniKviz(db, kvizStreznika('k1', 3));
    await zapisiPoskus(db, poskus('k1', 1));

    await render(<KviziScreen />);

    expect(await screen.findByText('Odgovorjenih: 1 od 3')).toBeTruthy();
  });

  it('nov kviz pove število vprašanj', async () => {
    await shraniKviz(db, kvizStreznika('k1', 3));

    await render(<KviziScreen />);

    expect(await screen.findByText('Vprašanj: 3')).toBeTruthy();
  });

  it('ko nič ne čaka, to pove in ne pokaže napake', async () => {
    await render(<KviziScreen />);

    expect(await screen.findByText('Ni kvizov')).toBeTruthy();
  });

  it('pritisk odpre kviz', async () => {
    await shraniKviz(db, kvizStreznika('k1', 1));
    await render(<KviziScreen />);

    await fireEvent.press(await screen.findByTestId('kviz'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenCalledWith({
      pathname: '/kvizi/[id]',
      params: { id: 'k1' },
    });
  });

  it('zadnji kviz ne obtiči pod sistemsko navigacijsko vrstico', async () => {
    await shraniKviz(db, kvizStreznika('k1', 1));
    await render(<KviziScreen />);

    const seznam = await screen.findByTestId('seznam-kvizov');

    expect(odmikSpodaj(seznam.props.contentContainerStyle)).toBe(
      theme.spacing + TEST_INSETS.bottom,
    );
  });

  it('napaka baze da slovensko sporočilo, kaj naj naredi', async () => {
    sqlite.stanje.db = {
      ...db,
      getAllAsync: async () => {
        throw new Error('disk I/O error');
      },
    };

    await render(<KviziScreen />);

    expect(await screen.findByText('Kvizov ni bilo mogoče prebrati')).toBeTruthy();
    expect(screen.getByText(/poskusi znova/)).toBeTruthy();
  });
});

describe('gumb „Kvizi" na domači strani', () => {
  async function izrisi() {
    return render(
      <KviziProvider db={db} nastavitve={null}>
        <HomeScreen />
      </KviziProvider>,
    );
  }

  it('brez čakajočih kvizov je le „Kvizi"', async () => {
    await izrisi();

    expect(await screen.findByText('Kvizi')).toBeTruthy();
  });

  it('kadar kaj čaka, nosi število', async () => {
    await shraniKviz(db, kvizStreznika('k1', 1));
    await shraniKviz(db, kvizStreznika('k2', 2));
    await shraniKviz(db, kvizStreznika('resen', 1));
    await zapisiPoskus(db, poskus('resen', 1));

    await izrisi();

    expect(await screen.findByText('Kvizi · 2')).toBeTruthy();
  });

  it('kadar kaj čaka, ima poudarjen rob', async () => {
    await shraniKviz(db, kvizStreznika('k1', 1));
    await izrisi();
    await screen.findByText('Kvizi · 1');

    const gumb = screen.getByTestId('gumb-kvizi');
    const slog = JSON.stringify(gumb.props.style);

    expect(slog).toContain(theme.accent);
  });
});
