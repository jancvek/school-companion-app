import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import HomeScreen from '../app/index';
import PickSubjectForCaptureScreen from '../app/slikaj/index';
import PickSubjectForHistoryScreen from '../app/zgodovina/index';
import { SUBJECTS } from '@/constants/subjects';
import { insertMaterial } from '@/db/materials';
import { migriraj } from '@/db/migrations';
import { SyncProvider } from '@/sync/use-sync';
import type { Material } from '@/types';
import { theme } from '@/ui/theme';

import { createTestDatabase } from './test-database';
import { odmikSpodaj, TEST_INSETS, type RouterMockState } from './screen-mocks';

jest.mock('expo-router', () => require('./screen-mocks').expoRouterMock());
jest.mock('expo-sqlite', () => require('./screen-mocks').expoSqliteMock());
jest.mock('react-native-safe-area-context', () => require('./screen-mocks').safeAreaMock());

const usmerjevalnik = jest.requireMock('expo-router') as { stanje: RouterMockState };

function material(overrides: Partial<Material> = {}): Material {
  return {
    id: 'id-1',
    subject: 'MAT',
    taken_at: '2026-09-01T10:00:00.000Z',
    file_uri: 'file:///documents/photos/id-1.jpg',
    sync_status: 'pending',
    sync_attempts: 0,
    last_attempt_at: null,
    sync_error: null,
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe('domača stran', () => {
  it('ponuja natanko gumba „Slikaj snov" in „Zgodovina"', async () => {
    await render(<HomeScreen />);

    expect(screen.getByText('Slikaj snov')).toBeTruthy();
    expect(screen.getByText('Zgodovina')).toBeTruthy();
  });

  it('„Slikaj snov" pelje na izbiro predmeta za slikanje', async () => {
    await render(<HomeScreen />);

    await fireEvent.press(screen.getByText('Slikaj snov'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenCalledWith('/slikaj');
  });

  it('„Zgodovina" pelje na izbiro predmeta za zgodovino', async () => {
    await render(<HomeScreen />);

    await fireEvent.press(screen.getByText('Zgodovina'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenCalledWith('/zgodovina');
  });
});

describe('izbira predmeta', () => {
  it('izriše vseh deset predmetov v dogovorjenem vrstnem redu', async () => {
    await render(<PickSubjectForCaptureScreen />);

    for (const predmet of SUBJECTS) {
      expect(screen.getByText(predmet.label)).toBeTruthy();
    }
  });

  it('pri slikanju nese kodo predmeta naprej, ne oznake', async () => {
    await render(<PickSubjectForCaptureScreen />);

    await fireEvent.press(screen.getByText('MAT — Matematika'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenCalledWith({
      pathname: '/slikaj/[subject]',
      params: { subject: 'MAT' },
    });
  });

  it('v zgodovini nese kodo predmeta naprej, ne oznake', async () => {
    await render(<PickSubjectForHistoryScreen />);

    await fireEvent.press(screen.getByText('GUM — Glasbena umetnost'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenCalledWith({
      pathname: '/zgodovina/[subject]',
      params: { subject: 'GUM' },
    });
  });

  it('tudi predmet brez posnetkov je na seznamu zgodovine', async () => {
    await render(<PickSubjectForHistoryScreen />);

    expect(screen.getByText('GUM — Glasbena umetnost')).toBeTruthy();
  });

  it('zadnji predmet ne obtiči pod sistemsko navigacijsko vrstico', async () => {
    await render(<PickSubjectForCaptureScreen />);

    const seznam = screen.getByTestId('seznam-predmetov');

    expect(odmikSpodaj(seznam.props.contentContainerStyle)).toBe(
      theme.spacing + TEST_INSETS.bottom,
    );
  });
});

describe('stanje prenosa na domači strani', () => {
  let db: ReturnType<typeof createTestDatabase>;

  beforeEach(async () => {
    db = createTestDatabase();
    await migriraj(db);
  });

  afterEach(() => {
    db.close();
  });

  /** Domača stran znotraj ponudnika, z bazo in nastavitvami iz testa. */
  async function izrisi(nastavljen: boolean) {
    const nastavitve = nastavljen
      ? { baseUrl: 'http://sto.ts.net:8000', apiKey: 'k' }
      : null;
    return render(
      <SyncProvider db={db} nastavitve={nastavitve} prenesiEno={async () => ({ vrsta: 'pending', razlog: 'test' })}>
        <HomeScreen />
      </SyncProvider>,
    );
  }

  it('pokaže, koliko posnetkov čaka na prenos', async () => {
    await insertMaterial(db, material({ id: 'a' }));
    await insertMaterial(db, material({ id: 'b' }));
    await insertMaterial(db, material({ id: 'c', sync_status: 'synced' }));

    await izrisi(true);

    // Prenesenih ne šteje — vidno mora biti, koliko jih je še na telefonu.
    expect(await screen.findByText('Za prenos: 2')).toBeTruthy();
  });

  it('ko ni ničesar v vrsti, to tudi pove', async () => {
    await insertMaterial(db, material({ id: 'a', sync_status: 'synced' }));

    await izrisi(true);

    expect(await screen.findByText('Vse preneseno')).toBeTruthy();
  });

  it('neuspeli imajo svojo vrstico, ker se sami ne popravijo', async () => {
    await insertMaterial(db, material({ id: 'a' }));
    await insertMaterial(db, material({ id: 'b', sync_status: 'failed' }));

    await izrisi(true);

    await waitFor(() => {
      expect(screen.getByTestId('stevec-neuspelih')).toBeTruthy();
    });
    expect(screen.getByTestId('stevec-neuspelih').props.children).toContain(1);
  });

  it('brez neuspelih te vrstice ni', async () => {
    await insertMaterial(db, material({ id: 'a' }));

    await izrisi(true);

    await waitFor(() => expect(screen.getByTestId('stevec-cakajocih')).toBeTruthy());
    expect(screen.queryByTestId('stevec-neuspelih')).toBeNull();
  });

  it('brez nastavljenega prenosa pove, da posnetki ostajajo na telefonu', async () => {
    await insertMaterial(db, material({ id: 'a' }));

    await izrisi(false);

    expect(await screen.findByTestId('prenos-ni-nastavljen')).toBeTruthy();
    expect(screen.queryByTestId('stevec-cakajocih')).toBeNull();
  });

  it('brez nastavljenega prenosa domača stran še vedno dela', async () => {
    await izrisi(false);

    await fireEvent.press(screen.getByText('Slikaj snov'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenCalledWith('/slikaj');
  });
});
