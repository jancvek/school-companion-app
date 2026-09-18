import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { AppState } from 'react-native';

import HomeScreen from '../app/index';
import PickSubjectForCaptureScreen from '../app/slikaj/index';
import PickSubjectForHistoryScreen from '../app/zgodovina/index';
import { preberiNastavitve } from '@/config/server';
import { SUBJECTS } from '@/constants/subjects';
import { insertMaterial, listPending } from '@/db/materials';
import { migriraj } from '@/db/migrations';
import { SPOROCILO_POTEKLA_PRIJAVA, type Seja } from '@/sync/prijava';
import type { Izid } from '@/sync/upload';
import { PrijavaProvider } from '@/sync/use-prijava';
import { SyncProvider } from '@/sync/use-sync';
import type { Material } from '@/types';
import { theme } from '@/ui/theme';

import { SEJA, ustvariShrambo } from './shramba';
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
  // Privzeto lastnik seje: tako zapis nastane, ko je kdo prijavljen.
  user_id: SEJA.userId,
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe('domača stran', () => {
  it('ponuja natanko gumbe „Slikaj snov", „Zgodovina" in „Kvizi"', async () => {
    // Do V2-R02 sta bila gumba dva (kriterij V1-R01); V2-R02 izrecno doda
    // tretjega. Sprememba pogodbe, ne oslabitev: zdaj je preštet vsak gumb.
    await render(<HomeScreen />);

    expect(screen.getByText('Slikaj snov')).toBeTruthy();
    expect(screen.getByText('Zgodovina')).toBeTruthy();
    expect(screen.getByText('Kvizi')).toBeTruthy();
    // Četrti je prijava (V3-R04): vnos, ne vrata (ADR-036 A).
    expect(screen.getByTestId('gumb-prijava')).toBeTruthy();
    expect(screen.getAllByRole('button')).toHaveLength(4);
  });

  it('„Kvizi" pelje na seznam kvizov', async () => {
    await render(<HomeScreen />);

    await fireEvent.press(screen.getByText('Kvizi'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenCalledWith('/kvizi');
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

  let prvotnoStanje: string;

  beforeEach(async () => {
    db = createTestDatabase();
    await migriraj(db);
    // Brez tega se razporejevalnik ne zažene in `poCiklu` nikoli ne javi
    // izida — vrstica o potekli prijavi bi manjkala iz napačnega razloga.
    prvotnoStanje = AppState.currentState;
    (AppState as { currentState: string }).currentState = 'active';
  });

  afterEach(() => {
    (AppState as { currentState: string }).currentState = prvotnoStanje;
    db.close();
  });

  /** Domača stran znotraj obeh ponudnikov, z bazo in nastavitvami iz testa. */
  async function izrisi(
    nastavljen: boolean,
    seja: Seja | null = SEJA,
    izid: Izid = { vrsta: 'pending', razlog: 'test' },
  ) {
    const nastavitve = nastavljen ? { baseUrl: 'https://school-buddy.duckdns.org' } : null;
    return render(
      <PrijavaProvider db={db} nastavitve={nastavitve} shramba={ustvariShrambo(seja)}>
        <SyncProvider db={db} nastavitve={nastavitve} prenesiEno={async () => izid}>
          <HomeScreen />
        </SyncProvider>
      </PrijavaProvider>,
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

  it('potekla prijava to pove naravnost, ne le v števcu', async () => {
    // Kriterij V3-R04: „Ob neveljavnem žetonu aplikacija to pove razumljivo
    // (Prijava je potekla, prijavi se znova) in ne izgubi nobene lokalno
    // shranjene snovi.“ Zapis v `sync_error` tega ne stori: ne izriše ga
    // nihče. Brez te vrstice je potekla prijava videti enako kot ugasnjen
    // strežnik — števec stoji in otrok ne ve, da mora kaj narediti.
    await insertMaterial(db, material({ id: 'a' }));

    await izrisi(true, SEJA, {
      vrsta: 'pending',
      razlog: SPOROCILO_POTEKLA_PRIJAVA,
      prijavaPotekla: true,
    });

    const vrstica = await screen.findByTestId('prijava-potekla');
    expect(vrstica.props.children).toMatch(/prijavi se znova/i);
    // Snov ostane na telefonu in tega sporočilo tudi pove.
    expect(vrstica.props.children).toMatch(/ostanejo na telefonu/i);
    expect((await listPending(db, SEJA.userId)).map((m) => m.id)).toEqual(['a']);
  });

  it('nedosegljiv strežnik ni videti kot potekla prijava', async () => {
    // Sicer bi otrok ob vsaki izgubljeni povezavi poskusil ponovno prijavo.
    await insertMaterial(db, material({ id: 'a' }));

    await izrisi(true, SEJA, { vrsta: 'pending', razlog: 'Strežnik ni dosegljiv.' });

    expect(await screen.findByTestId('stevec-cakajocih')).toBeTruthy();
    expect(screen.queryByTestId('prijava-potekla')).toBeNull();
  });

  it('brez nastavljenega prenosa pove, da posnetki ostajajo na telefonu', async () => {
    await insertMaterial(db, material({ id: 'a' }));

    await izrisi(false);

    expect(await screen.findByTestId('prenos-ni-nastavljen')).toBeTruthy();
    expect(screen.queryByTestId('stevec-cakajocih')).toBeNull();
  });

  it('http naslov iz gradnje pove, da prenos ni nastavljen (V3-R02)', async () => {
    // Gradnja nešifriranega prometa ne dovoli več; brez tega bi posnetki večno
    // čakali na prenos in stran bi kazala le števec (`ADR-034` E).
    await insertMaterial(db, material({ id: 'a' }));
    const nastavitve = preberiNastavitve({ serverBaseUrl: 'http://sto.ts.net:8000' });

    await render(
      <PrijavaProvider db={db} nastavitve={nastavitve} shramba={ustvariShrambo(SEJA)}>
        <SyncProvider
          db={db}
          nastavitve={nastavitve}
          prenesiEno={async () => ({ vrsta: 'pending', razlog: 'test' })}
        >
          <HomeScreen />
        </SyncProvider>
      </PrijavaProvider>,
    );

    expect(await screen.findByTestId('prenos-ni-nastavljen')).toBeTruthy();
    expect(screen.queryByTestId('stevec-cakajocih')).toBeNull();
  });


  it('brez prijave pove, da posnetki čakajo, in števca ne pokaže', async () => {
    // Prijava ni pogoj za slikanje; blokiran je izključno prenos (ADR-036 A).
    await insertMaterial(db, material({ id: 'a' }));

    await izrisi(true, null);

    expect(await screen.findByTestId('ni-prijave')).toBeTruthy();
    expect(screen.queryByTestId('števec-čakajocih')).toBeNull();
  });

  it('brez prijave domača stran še vedno dela', async () => {
    await izrisi(true, null);

    await fireEvent.press(screen.getByText('Slikaj snov'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenCalledWith('/slikaj');
  });

  it('vnos za prijavo pove, kdo je prijavljen, in pelje na prijavo', async () => {
    await izrisi(true);

    expect(await screen.findByText('Prijavljena: Maša')).toBeTruthy();

    await fireEvent.press(screen.getByTestId('gumb-prijava'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenCalledWith('/prijava');
  });

  it('števec ne šteje zapisov druge uporabnice', async () => {
    // Skupni telefon: Mašin zapis in Jakov. Stran kaže samo Mašinega, ker se
    // samo ta prenese (ADR-036 B).
    await insertMaterial(db, material({ id: 'moj', user_id: SEJA.userId }));
    await insertMaterial(db, material({ id: 'tuj', user_id: 'u-jaka' }));

    await izrisi(true);

    expect(await screen.findByText('Za prenos: 1')).toBeTruthy();
  });

  it('brez nastavljenega prenosa domača stran še vedno dela', async () => {
    await izrisi(false);

    await fireEvent.press(screen.getByText('Slikaj snov'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenCalledWith('/slikaj');
  });
});

describe('vidna verzija (V1-R06)', () => {
  it('domača stran pove, katera gradnja je nameščena', async () => {
    await render(<HomeScreen />);

    const vrstica = await screen.findByTestId('verzija');

    // Brez te vrstice dveh APK z isto verzijo na telefonu ni mogoče ločiti.
    expect(vrstica).toBeTruthy();
    expect(String(vrstica.props.children)).toMatch(/gradnja/);
  });

  it('vrstica z verzijo se ne da pritisniti', async () => {
    // Izpis, ne gumb: dotik mora iti mimo nje, da ne tekmuje z „Slikaj snov".
    // Trditev je o vedenju in ne o lastnostih samega <Text> — sicer bi vrstica
    // lahko postala gumb, zavit v <Pressable>, in test bi to preživel.
    // Ugotovitev pregledovalca ob drugem pregledu.
    await render(<HomeScreen />);

    await fireEvent.press(await screen.findByTestId('verzija'));

    expect(usmerjevalnik.stanje.router.push).not.toHaveBeenCalled();
  });
});
