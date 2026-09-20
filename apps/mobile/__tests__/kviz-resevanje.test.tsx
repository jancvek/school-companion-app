import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { AppState } from 'react-native';

import ResevanjeKvizaScreen from '../app/kvizi/[id]';
import { neprenesenePoskuse, postavkeKviza, shraniKviz, zapisiPoskus } from '@/db/kvizi';
import { migriraj } from '@/db/migrations';
import type { OdjemalecKvizov } from '@/sync/kvizi';
import { KviziProvider } from '@/sync/use-kvizi';
import { PrijavaProvider } from '@/sync/use-prijava';
import type { KvizStreznika, Poskus } from '@/types';
import { theme } from '@/ui/theme';

import { kvizStreznika, poskus } from './kvizi-podatki';
import { odmikSpodaj, TEST_INSETS, type RouterMockState } from './screen-mocks';
import { SEJA, ustvariShrambo } from './shramba';
import { createTestDatabase } from './test-database';

jest.mock('expo-router', () => require('./screen-mocks').expoRouterMock());
jest.mock('expo-sqlite', () => require('./screen-mocks').expoSqliteMock());
jest.mock('react-native-safe-area-context', () => require('./screen-mocks').safeAreaMock());

// Predpona `mock` ni okras: jest tovarni v `jest.mock` dovoli samo zunanje
// spremenljivke s tem imenom, ker se tovarna dvigne nad uvoze.
let mockStevec = 0;
jest.mock('expo-secure-store', () => ({
  __esModule: true,
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
}));

jest.mock('expo-crypto', () => ({
  __esModule: true,
  randomUUID: () => {
    mockStevec += 1;
    return `uuid-${mockStevec}`;
  },
}));

const usmerjevalnik = jest.requireMock('expo-router') as { stanje: RouterMockState };
const sqlite = jest.requireMock('expo-sqlite') as { stanje: { db: unknown } };

let db: ReturnType<typeof createTestDatabase>;
let prvotnoStanje: string;

beforeEach(async () => {
  jest.clearAllMocks();
  mockStevec = 0;
  db = createTestDatabase();
  await migriraj(db);
  sqlite.stanje.db = db;
  usmerjevalnik.stanje.params = { id: 'k1' };
  prvotnoStanje = AppState.currentState;
  (AppState as { currentState: string }).currentState = 'active';
});

afterEach(() => {
  (AppState as { currentState: string }).currentState = prvotnoStanje;
  jest.useRealTimers();
  db.close();
});

/** Odjemalec, ki vrne dani seznam in beleži poslane poskuse. */
function odjemalec(kvizi: KvizStreznika[]): OdjemalecKvizov & {
  posljiPoskuse: jest.Mock;
  preberiKvize: jest.Mock;
} {
  return {
    posljiPoskuse: jest.fn(async (_p: readonly Poskus[]) => {}),
    preberiKvize: jest.fn(async () => kvizi),
  };
}

async function izrisi(streznik?: OdjemalecKvizov) {
  return render(
    <KviziProvider db={db} nastavitve={null} odjemalec={streznik}>
      <ResevanjeKvizaScreen />
    </KviziProvider>,
  );
}

describe('reševanje kviza', () => {
  it('pokaže vprašanje brez odgovora in brez gumbov za oceno', async () => {
    await shraniKviz(db, kvizStreznika('k1', 3), null);

    await izrisi();

    expect(await screen.findByText('Vprašanje 1?')).toBeTruthy();
    expect(screen.getByTestId('napredek').props.children).toBe('Vprašanje 1 od 3');
    expect(screen.queryByTestId('odgovor')).toBeNull();
    // Neocenjenega vprašanja ni: pred razkritjem se ne da oceniti.
    expect(screen.queryByText('Srednje')).toBeNull();
    expect(screen.getByText('Pokaži odgovor')).toBeTruthy();
  });

  it('„Pokaži odgovor" razkrije odgovor in štiri ocene', async () => {
    await shraniKviz(db, kvizStreznika('k1', 3), null);
    await izrisi();

    await fireEvent.press(await screen.findByText('Pokaži odgovor'));

    expect(screen.getByTestId('odgovor').props.children).toBe('Odgovor 1.');
    for (const oznaka of ['Nisem vedela', 'Težko', 'Srednje', 'Lahko']) {
      expect(screen.getByText(oznaka)).toBeTruthy();
    }
    expect(screen.queryByText('Pokaži odgovor')).toBeNull();
  });

  it('ocena zapiše poskus in je hkrati „naprej"', async () => {
    await shraniKviz(db, kvizStreznika('k1', 3), null);
    await izrisi();

    await fireEvent.press(await screen.findByText('Pokaži odgovor'));
    await fireEvent.press(screen.getByText('Srednje'));

    expect(await screen.findByText('Vprašanje 2?')).toBeTruthy();
    expect(screen.getByTestId('napredek').props.children).toBe('Vprašanje 2 od 3');
    expect(screen.queryByTestId('odgovor')).toBeNull();
    const [zapisan] = await neprenesenePoskuse(db, null);
    expect(zapisan).toEqual(
      expect.objectContaining({
        id: 'uuid-1',
        quiz_id: 'k1',
        quiz_item_id: 'k1-p1',
        mode: 'samoocena',
        rating: 'srednje',
        uploaded_at: null,
      }),
    );
  });

  it('poskus dobi lastnika, ki je ta hip prijavljen (V3-R04)', async () => {
    // Zrcalno posnetku: brez lastnika na poskusu bi ga `neprenesenePoskuse`
    // za prijavljenega otroka spregledala ali pa bi ga posvojila napačna
    // prijava — in ocena enega otroka bi pristala v statistiki drugega
    // (`docs/odlocitve/ADR-036` B in C).
    await shraniKviz(db, kvizStreznika('k1', 2), null);
    await render(
      <PrijavaProvider db={db} nastavitve={null} shramba={ustvariShrambo(SEJA)}>
        <KviziProvider db={db} nastavitve={null}>
          <ResevanjeKvizaScreen />
        </KviziProvider>
      </PrijavaProvider>,
    );
    await screen.findByText('Vprašanje 1?');

    await fireEvent.press(screen.getByText('Pokaži odgovor'));
    await fireEvent.press(screen.getByText('Srednje'));

    await waitFor(async () =>
      expect(await neprenesenePoskuse(db, SEJA.userId)).toHaveLength(1),
    );
    // In ne „brez lastnika“: tak poskus bi posvojila katerakoli prijava.
    expect(await neprenesenePoskuse(db, null)).toEqual([]);
  });

  it('zapiše tri žige: pokazano, razkrito, ocenjeno', async () => {
    jest.useFakeTimers({ now: new Date('2026-09-10T15:00:00.000Z'), doNotFake: ['nextTick', 'setImmediate'] });
    await shraniKviz(db, kvizStreznika('k1', 2), null);
    await izrisi();
    await screen.findByText('Vprašanje 1?');

    jest.setSystemTime(new Date('2026-09-10T15:00:07.000Z'));
    await fireEvent.press(screen.getByText('Pokaži odgovor'));
    jest.setSystemTime(new Date('2026-09-10T15:00:09.000Z'));
    await fireEvent.press(screen.getByText('Lahko'));

    await waitFor(async () => expect(await neprenesenePoskuse(db, null)).toHaveLength(1));
    const [zapisan] = await neprenesenePoskuse(db, null);
    expect(zapisan.shown_at).toBe('2026-09-10T15:00:00.000Z');
    expect(zapisan.revealed_at).toBe('2026-09-10T15:00:07.000Z');
    expect(zapisan.answered_at).toBe('2026-09-10T15:00:09.000Z');
  });

  it('zapuščen kviz se nadaljuje pri prvi neocenjeni postavki', async () => {
    await shraniKviz(db, kvizStreznika('k1', 5), null);
    await zapisiPoskus(db, poskus('k1', 1));
    await zapisiPoskus(db, poskus('k1', 2));

    await izrisi();

    expect(await screen.findByText('Vprašanje 3?')).toBeTruthy();
    expect(screen.getByTestId('napredek').props.children).toBe('Vprašanje 3 od 5');
  });

  it('postavko, odgovorjeno na strežniku, preskoči', async () => {
    const kviz = kvizStreznika('k1', 3);
    kviz.items[0].answered = true;
    await shraniKviz(db, kviz, null);

    await izrisi();

    expect(await screen.findByText('Vprašanje 2?')).toBeTruthy();
  });

  it('po zadnji oceni pove „Kviz je končan", brez številk ocen, in pošlje poskuse', async () => {
    await shraniKviz(db, kvizStreznika('k1', 2), null);
    const streznik = odjemalec([kvizStreznika('k1', 2)]);
    await izrisi(streznik);
    // Prvi obhod ob vpetju: ni kaj poslati.
    await waitFor(() => expect(streznik.preberiKvize).toHaveBeenCalledTimes(1));

    await fireEvent.press(await screen.findByText('Pokaži odgovor'));
    await fireEvent.press(screen.getByText('Nisem vedela'));
    await fireEvent.press(await screen.findByText('Pokaži odgovor'));
    await fireEvent.press(screen.getByText('Lahko'));

    expect(await screen.findByText('Kviz je končan')).toBeTruthy();
    expect(screen.queryByText(/Nisem vedela|Lahko|Težko|Srednje/)).toBeNull();
    expect(screen.queryByText(/\d/)).toBeNull();
    // Usklajevanje se sproži takoj, ne čez pet minut.
    await waitFor(() => expect(streznik.posljiPoskuse).toHaveBeenCalledTimes(1));
    expect(streznik.posljiPoskuse.mock.calls[0][0]).toHaveLength(2);
  });

  it('„Nazaj na kvize" po koncu vrne na seznam', async () => {
    await shraniKviz(db, kvizStreznika('k1', 1), null);
    await izrisi();

    await fireEvent.press(await screen.findByText('Pokaži odgovor'));
    await fireEvent.press(screen.getByText('Težko'));
    await fireEvent.press(await screen.findByText('Nazaj na kvize'));

    expect(usmerjevalnik.stanje.router.back).toHaveBeenCalled();
  });

  it('odprt kviz ne izgine, tudi če ga strežnik ne vrača več', async () => {
    // `ADR-019` C: preklic na strežniku ne sme Maši vzeti zaslona pod prsti.
    await shraniKviz(db, kvizStreznika('k1', 2), null);
    const streznik = odjemalec([]);

    const { unmount } = await izrisi(streznik);
    await waitFor(() => expect(streznik.preberiKvize).toHaveBeenCalled());
    await act(async () => {
      await Promise.resolve();
    });

    expect(await postavkeKviza(db, 'k1', null)).toHaveLength(2);
    // `await`, sicer se test konča pred odmontiranjem in ponavljalnik ostane živ.
    await unmount();
  });

  it('gumbi ob spodnjem robu upoštevajo varno območje', async () => {
    await shraniKviz(db, kvizStreznika('k1', 1), null);
    await izrisi();

    const vrstica = await screen.findByTestId('spodnja-vrstica');

    expect(odmikSpodaj(vrstica.props.style)).toBe(theme.spacing + TEST_INSETS.bottom);
  });

  it('kviza, ki ga ni, ne izriše kot napako, ampak pove, kaj naj naredi', async () => {
    await izrisi();

    expect(await screen.findByText('Tega kviza ni na telefonu')).toBeTruthy();
    expect(screen.getByText('Nazaj na kvize')).toBeTruthy();
  });

  it('neuspešno shranjena ocena pusti vprašanje in pove, kaj naj naredi', async () => {
    await shraniKviz(db, kvizStreznika('k1', 2), null);
    sqlite.stanje.db = {
      ...db,
      runAsync: async () => {
        throw new Error('disk full');
      },
    };
    await izrisi();

    await fireEvent.press(await screen.findByText('Pokaži odgovor'));
    await fireEvent.press(screen.getByText('Srednje'));

    expect(await screen.findByTestId('napaka-shranjevanja')).toBeTruthy();
    expect(screen.getByText('Vprašanje 1?')).toBeTruthy();
    expect(screen.getByTestId('odgovor')).toBeTruthy();
  });
});
