import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Linking } from 'react-native';

import PoveziScreen, { SPOROCILO_NI_NASA_KODA } from '../app/povezi';
import { insertMaterial, listPending, type MaterialsDatabase } from '@/db/materials';
import { migriraj } from '@/db/migrations';
import { jeOdjavaNedokoncana, zacniOdjavo } from '@/db/naprava';
import { PrijavaProvider } from '@/sync/use-prijava';
import { SyncProvider } from '@/sync/use-sync';
import type { Material } from '@/types';
import { theme } from '@/ui/theme';

import { SEJA, ustvariShrambo, type TestnaShramba } from './shramba';
import { createTestDatabase } from './test-database';
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
// `expo-secure-store` je nativni modul; testi ga ne kličejo, ker `PrijavaProvider`
// dobi shrambo kot lastnost — mock je tu samo zato, da se uvoz razreši.
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
}));

const usmerjevalnik = jest.requireMock('expo-router') as { stanje: RouterMockState };
const kamera = jest.requireMock('expo-camera') as { stanje: CameraMockState };

const NASTAVITVE = { baseUrl: 'https://school-buddy.duckdns.org' };

/** Povezovalni žeton, kakršnega nosi QR koda (43 znakov, kot na strežniku). */
const ZETON = 'aB3_dE6-gH9jKlMnOpQrStUvWxYz0123456789-_AbC';
const KODA = `school-companion://povezi?z=${ZETON}`;

/** Seja, ki jo strežnik vrne ob povezavi — **drug** otrok kot v `SEJA`. */
const NOVA = { zeton: 'nov-zeton', userId: 'u-jaka', ime: 'Jaka' };

/**
 * Zaslon za povezavo telefona (V6-R01).
 *
 * Do `V6-R01` je sejo dal prijavni obrazec; testi, ki so skozenj dokazovali
 * posvojitev, oznako odjave in sporočila (`ADR-036`, `ADR-037`), tečejo
 * odslej skozi ta zaslon. Strežnika zaslon ne kliče sam — to počne
 * `src/sync/prijava.ts`; tu je `fetch` podtaknjen, da se vidi, kaj bi šlo
 * na pot in kaj vidi otrok.
 */

function material(overrides: Partial<Material> = {}): Material {
  return {
    id: 'm-1',
    subject: 'MAT',
    taken_at: '2026-09-01T10:00:00.000Z',
    file_uri: 'file:///documents/photos/m-1.jpg',
    sync_status: 'pending',
    sync_attempts: 0,
    last_attempt_at: null,
    sync_error: null,
    user_id: null,
    ...overrides,
  };
}

function uspeh() {
  return {
    ok: true,
    status: 200,
    json: async () => ({
      token: NOVA.zeton,
      user_id: NOVA.userId,
      display_name: NOVA.ime,
      expires_at: '2026-11-11T10:00:00+00:00',
    }),
  };
}

function zavrnitev(status: number, detail: unknown) {
  return { ok: false, status, json: async () => ({ detail }) };
}

describe('zaslon za povezavo telefona', () => {
  let db: MaterialsDatabase & { close(): void };
  let odgovor: jest.Mock;

  beforeEach(async () => {
    jest.clearAllMocks();
    usmerjevalnik.stanje.params = {};
    usmerjevalnik.stanje.router.canGoBack.mockReturnValue(true);
    kamera.stanje.permission = dovoljenje();
    db = createTestDatabase();
    await migriraj(db);
    odgovor = jest.fn(async () => uspeh());
    (globalThis as { fetch?: unknown }).fetch = odgovor;
  });

  afterEach(() => {
    db.close();
    delete (globalThis as { fetch?: unknown }).fetch;
  });

  function drevo(shramba: TestnaShramba, nastavitve: typeof NASTAVITVE | null = NASTAVITVE) {
    return (
      <PrijavaProvider db={db} nastavitve={nastavitve} shramba={shramba}>
        <SyncProvider
          db={db}
          nastavitve={nastavitve}
          prenesiEno={async () => ({ vrsta: 'pending', razlog: 'test' })}
        >
          <PoveziScreen />
        </SyncProvider>
      </PrijavaProvider>
    );
  }

  async function izrisi(shramba: TestnaShramba, z?: string) {
    usmerjevalnik.stanje.params = z === undefined ? {} : { z };
    const izid = await render(drevo(shramba));
    await act(async () => {});
    return izid;
  }

  /** Kamera javi prebrano kodo, kot jo javi `expo-camera`. */
  async function preberi(data: string) {
    await fireEvent(screen.getByTestId('kamera'), 'barcodeScanned', { data });
  }

  /** Zahteve na pot povezave; odjava prejšnje seje gre na drugo pot. */
  function zahtevePovezave() {
    return odgovor.mock.calls.filter(([url]) => String(url).endsWith('/auth/link'));
  }

  async function povezano() {
    await waitFor(() => expect(usmerjevalnik.stanje.router.back).toHaveBeenCalled());
  }

  // --- Odprta povezava („Odpri na tem telefonu") ---------------------------

  it('odprta povezava unovči žeton, shrani sejo in se vrne', async () => {
    const shramba = ustvariShrambo();

    await izrisi(shramba, ZETON);
    await povezano();

    const [url, moznosti] = zahtevePovezave()[0];
    expect(url).toBe('https://school-buddy.duckdns.org/auth/link');
    expect(JSON.parse(moznosti.body)).toEqual({ token: ZETON });
    expect(shramba.vsebina()).toContain(NOVA.zeton);
    expect(usmerjevalnik.stanje.router.replace).not.toHaveBeenCalled();
  });

  it('povezava, ki je aplikacijo šele odprla, pelje na domačo stran', async () => {
    // Za njo ni zaslona, kamor bi se bilo mogoče vrniti.
    usmerjevalnik.stanje.router.canGoBack.mockReturnValue(false);

    await izrisi(ustvariShrambo(), ZETON);

    await waitFor(() => {
      expect(usmerjevalnik.stanje.router.replace).toHaveBeenCalledWith('/');
    });
    expect(usmerjevalnik.stanje.router.back).not.toHaveBeenCalled();
  });

  it('isto povezavo unovči samo enkrat', async () => {
    // Žeton je enkraten: druga zahteva bi uspešno povezavo pokazala kot
    // neveljavno kodo.
    const shramba = ustvariShrambo();
    const izid = await izrisi(shramba, ZETON);
    await povezano();

    // Usmerjevalnik z novo identiteto: učinek odprte povezave steče znova,
    // parameter pa je isti. Brez varovala bi šel isti žeton še enkrat na pot.
    usmerjevalnik.stanje.router = { ...usmerjevalnik.stanje.router };
    await izid.rerender(drevo(shramba));
    await act(async () => {});

    expect(zahtevePovezave()).toHaveLength(1);
    expect(screen.queryByTestId('napaka-povezave')).toBeNull();
  });

  it('povezava z nečim, kar ni žeton, ne gre na strežnik', async () => {
    await izrisi(ustvariShrambo(), 'to ni žeton');

    expect((await screen.findByTestId('napaka-povezave')).props.children).toBe(
      SPOROCILO_NI_NASA_KODA,
    );
    expect(odgovor).not.toHaveBeenCalled();
  });

  it('zavrnjena koda pove, kaj naj otrok naredi, in ne shrani ničesar', async () => {
    odgovor.mockResolvedValue(zavrnitev(401, 'Koda ne velja več. Prosi starša za novo.'));
    const shramba = ustvariShrambo();

    await izrisi(shramba, ZETON);

    const besedilo = (await screen.findByTestId('napaka-povezave')).props.children as string;
    expect(besedilo).toMatch(/prosi starša za novo/i);
    expect(shramba.vsebina()).toBeUndefined();
    expect(usmerjevalnik.stanje.router.back).not.toHaveBeenCalled();
    expect(usmerjevalnik.stanje.router.replace).not.toHaveBeenCalled();
  });

  it('po zavrnjeni povezavi je mogoče prebrati novo kodo s kamero', async () => {
    odgovor.mockResolvedValueOnce(zavrnitev(401, 'Koda ne velja več. Prosi starša za novo.'));
    const shramba = ustvariShrambo();
    await izrisi(shramba, ZETON);
    await screen.findByTestId('napaka-povezave');

    await fireEvent.press(screen.getByTestId('gumb-znova'));
    await preberi(`school-companion://povezi?z=${'n'.repeat(43)}`);
    await povezano();

    expect(JSON.parse(zahtevePovezave()[1][1].body)).toEqual({ token: 'n'.repeat(43) });
    expect(shramba.vsebina()).toContain(NOVA.zeton);
  });

  // --- Kamera --------------------------------------------------------------

  it('prebrana koda poveže telefon', async () => {
    const shramba = ustvariShrambo();
    await izrisi(shramba);
    expect(screen.getByTestId('navodilo')).toBeTruthy();

    await preberi(KODA);
    await povezano();

    expect(JSON.parse(zahtevePovezave()[0][1].body)).toEqual({ token: ZETON });
    expect(shramba.vsebina()).toContain(NOVA.zeton);
  });

  it('bralnik bere samo QR kode', async () => {
    await izrisi(ustvariShrambo());

    expect(screen.getByTestId('kamera').props.barcodeScannerSettings).toEqual({
      barcodeTypes: ['qr'],
    });
  });

  it.each([
    ['spletna stran', 'https://primer.test/povezi?z=aaaaaaaaaaaaaaaaaaaaaaaa'],
    ['koda druge aplikacije', 'drugaaplikacija://povezi?z=aaaaaaaaaaaaaaaaaaaaaaaa'],
    ['golo besedilo', 'Dober dan'],
  ])('tuja koda (%s) dobi sporočilo in ne gre na strežnik', async (_opis, vsebina) => {
    const shramba = ustvariShrambo();
    await izrisi(shramba);

    await preberi(vsebina);

    expect(screen.getByTestId('napaka-povezave').props.children).toBe(SPOROCILO_NI_NASA_KODA);
    expect(SPOROCILO_NI_NASA_KODA).toMatch(/To ni koda Šolskega pomočnika/);
    expect(odgovor).not.toHaveBeenCalled();
    expect(shramba.vsebina()).toBeUndefined();
  });

  it('po tuji kodi bralnik po „Poskusi znova" bere naprej', async () => {
    await izrisi(ustvariShrambo());
    await preberi('Dober dan');
    // Dokler sporočilo čaka, bralnik miruje — sicer bi ga koda, ki je še pred
    // kamero, takoj prepisala.
    expect(screen.getByTestId('kamera').props.onBarcodeScanned).toBeUndefined();

    await fireEvent.press(screen.getByTestId('gumb-znova'));
    expect(screen.queryByTestId('napaka-povezave')).toBeNull();
    await preberi(KODA);
    await povezano();

    expect(zahtevePovezave()).toHaveLength(1);
  });

  it('koda, ki jo kamera javi večkrat, sproži eno samo zahtevo', async () => {
    // Bralnik isto kodo javi ob vsaki sličici. Vsaka zahteva z neveljavno
    // kodo šteje v mejo poskusov na strežniku (`ADR-061` E).
    odgovor.mockResolvedValue(zavrnitev(401, 'Koda ne velja več. Prosi starša za novo.'));
    await izrisi(ustvariShrambo());

    // Trije klici v istem tiku, mimo `fireEvent`: ta med klici počaka na
    // izris, kamera pa ne.
    const javi = screen.getByTestId('kamera').props.onBarcodeScanned as (dogodek: {
      data: string;
    }) => void;
    await act(async () => {
      javi({ data: KODA });
      javi({ data: KODA });
      javi({ data: KODA });
    });
    await screen.findByTestId('napaka-povezave');

    expect(zahtevePovezave()).toHaveLength(1);
  });

  it('med povezovanjem druga koda ne sproži druge zahteve', async () => {
    // Dve različni kodi v istem tiku (dva zaslona pred kamero): velja prva.
    // Druga zahteva bi tekmovala s prvo za isto sejo na telefonu.
    await izrisi(ustvariShrambo());
    const javi = screen.getByTestId('kamera').props.onBarcodeScanned as (dogodek: {
      data: string;
    }) => void;

    await act(async () => {
      javi({ data: KODA });
      javi({ data: `school-companion://povezi?z=${'d'.repeat(43)}` });
    });
    await povezano();

    expect(zahtevePovezave()).toHaveLength(1);
    expect(JSON.parse(zahtevePovezave()[0][1].body)).toEqual({ token: ZETON });
  });

  it('nedosegljiv strežnik kode ne porabi: po „Poskusi znova" ista koda uspe', async () => {
    odgovor.mockRejectedValueOnce(new Error('Network request failed'));
    const shramba = ustvariShrambo();
    await izrisi(shramba);

    await preberi(KODA);

    const besedilo = (await screen.findByTestId('napaka-povezave')).props.children as string;
    // Surovo besedilo sistemske napake ne sme biti edina vsebina sporočila.
    expect(besedilo).not.toMatch(/Network request failed/);
    expect(besedilo).toMatch(/poskusi znova/i);
    expect(besedilo).toMatch(/posnetki/i);
    expect(shramba.vsebina()).toBeUndefined();

    await fireEvent.press(screen.getByTestId('gumb-znova'));
    await preberi(KODA);
    await povezano();

    expect(zahtevePovezave()).toHaveLength(2);
    expect(shramba.vsebina()).toContain(NOVA.zeton);
  });

  it('med povezovanjem to pove in kode ne bere', async () => {
    let izpolni: (vrednost: unknown) => void = () => {};
    odgovor.mockImplementationOnce(
      () =>
        new Promise((razresi) => {
          izpolni = razresi;
        }),
    );
    await izrisi(ustvariShrambo());

    await preberi(KODA);

    expect(await screen.findByTestId('povezujem')).toBeTruthy();
    expect(screen.queryByTestId('kamera')).toBeNull();

    await act(async () => izpolni(uspeh()));
    await povezano();
  });

  it('brez dovoljenja za kamero ponudi, da ga da', async () => {
    kamera.stanje.permission = dovoljenje({ granted: false });
    await izrisi(ustvariShrambo());

    expect(screen.getByTestId('brez-kamere')).toBeTruthy();
    expect(screen.queryByTestId('kamera')).toBeNull();
    await fireEvent.press(screen.getByTestId('gumb-dovoljenje'));

    expect(kamera.stanje.requestPermission).toHaveBeenCalled();
  });

  it('trajno zavrnjeno dovoljenje pelje v nastavitve telefona', async () => {
    const nastavitveTelefona = jest.spyOn(Linking, 'openSettings').mockResolvedValue();
    kamera.stanje.permission = dovoljenje({ granted: false, canAskAgain: false });
    await izrisi(ustvariShrambo());

    await fireEvent.press(screen.getByTestId('gumb-dovoljenje'));

    expect(nastavitveTelefona).toHaveBeenCalled();
    expect(kamera.stanje.requestPermission).not.toHaveBeenCalled();
    nastavitveTelefona.mockRestore();
  });

  it('odprta povezava poveže tudi brez dovoljenja za kamero', async () => {
    // Gumb „Odpri na tem telefonu" je prav za primer, ko kamera ne pride v
    // poštev (`ADR-058` C).
    kamera.stanje.permission = dovoljenje({ granted: false });
    const shramba = ustvariShrambo();

    await izrisi(shramba, ZETON);
    await povezano();

    expect(shramba.vsebina()).toContain(NOVA.zeton);
  });

  it('brez nastavljenega naslova pove, zakaj povezava ni mogoča', async () => {
    usmerjevalnik.stanje.params = { z: ZETON };
    await render(drevo(ustvariShrambo(), null));
    await act(async () => {});

    expect(screen.getByTestId('prenos-ni-nastavljen').props.children).toMatch(/povej staršu/i);
    expect(screen.queryByTestId('kamera')).toBeNull();
    expect(odgovor).not.toHaveBeenCalled();
  });

  // --- Seja po povezavi (`ADR-036`, `ADR-037`, `ADR-061` I) ------------------

  it('povezava posvoji posnetke, ki so nastali pred njo', async () => {
    // Kriterij V3-R04 in `ADR-036` B: vrsta, ki je nastala brez povezave, po
    // povezavi odide — ne obtiči.
    await insertMaterial(db, material({ id: 'pred-povezavo', user_id: null }));

    await izrisi(ustvariShrambo(), ZETON);
    await povezano();

    await waitFor(async () => {
      expect((await listPending(db, NOVA.userId)).map((m) => m.id)).toEqual(['pred-povezavo']);
    });
    expect(await listPending(db, null)).toEqual([]);
  });

  it('povezava zamenja sejo, ki je na telefonu že bila', async () => {
    // `ADR-061` I: pot po „Prekliči prijave" in pot menjave otroka na skupnem
    // telefonu. Zapisi prejšnjega otroka ostanejo njegovi (`ADR-036` B).
    const shramba = ustvariShrambo(SEJA);
    await insertMaterial(db, material({ id: 'masin', user_id: SEJA.userId }));

    await izrisi(shramba, ZETON);
    await povezano();

    expect(shramba.vsebina()).toContain(NOVA.zeton);
    expect(shramba.vsebina()).not.toContain(SEJA.zeton);
    expect((await listPending(db, SEJA.userId)).map((m) => m.id)).toEqual(['masin']);
    expect(await listPending(db, NOVA.userId)).toEqual([]);
  });

  it('prejšnjo sejo odjavi tudi na strežniku', async () => {
    await izrisi(ustvariShrambo(SEJA), ZETON);
    await povezano();

    await waitFor(() => {
      const odjave = odgovor.mock.calls.filter(([url]) => String(url).endsWith('/auth/logout'));
      expect(odjave).toHaveLength(1);
      expect(odjave[0][1].headers['Authorization']).toBe(`Bearer ${SEJA.zeton}`);
    });
  });

  it('nedosegljiva odjava prejšnje seje povezave ne pokvari', async () => {
    // Najboljši poskus, kot pri odjavi (`ADR-036` G).
    odgovor.mockImplementation(async (url: string) => {
      if (String(url).endsWith('/auth/logout')) throw new Error('Network request failed');
      return uspeh();
    });
    const shramba = ustvariShrambo(SEJA);

    await izrisi(shramba, ZETON);
    await povezano();

    expect(shramba.vsebina()).toContain(NOVA.zeton);
    expect(screen.queryByTestId('napaka-povezave')).toBeNull();
  });

  it('neuspela povezava obstoječe seje ne spremeni', async () => {
    // Unovčenje je prvo: če spodleti, ostane vse, kot je bilo.
    odgovor.mockResolvedValue(zavrnitev(401, 'Koda ne velja več. Prosi starša za novo.'));
    const shramba = ustvariShrambo(SEJA);
    await insertMaterial(db, material({ id: 'brez', user_id: null }));

    await izrisi(shramba, ZETON);
    await screen.findByTestId('napaka-povezave');

    expect(shramba.vsebina()).toContain(SEJA.zeton);
    expect(odgovor.mock.calls.every(([url]) => !String(url).endsWith('/auth/logout'))).toBe(true);
    // Zapis brez lastnika je ob zagonu posvojila obnovljena seja, ne povezava.
    expect((await listPending(db, SEJA.userId)).map((m) => m.id)).toEqual(['brez']);
  });

  it('povezava prekliče nedokončano odjavo pred njo', async () => {
    // Oznaka brez žetona: odjava je žeton pobrisala, čiščenje oznake pa je
    // padlo. Zagon je tedaj ne počisti; počisti jo povezava. Sicer bi
    // **veljaven** žeton ob naslednjem zagonu srečal staro oznako in bi bil
    // zavržen — tiha odjava brez sporočila (`ADR-037`).
    await zacniOdjavo(db, '2026-09-19T08:00:00.000Z');
    const shramba = ustvariShrambo();

    await izrisi(shramba, ZETON);
    await povezano();

    expect(await jeOdjavaNedokoncana(db)).toBe(false);
  });

  it('povezava počaka, da se konča branje ob zagonu', async () => {
    // Povezava, ki aplikacijo šele odpre, sproži unovčenje, še preden je
    // steklo branje žetona z diska. Brez čakanja bi ostanek spodletele odjave
    // (`ADR-037`) pobrisal **pravkar shranjeno** sejo: telefon bi bil po
    // naslednjem zagonu spet nepovezan, koda pa porabljena.
    await zacniOdjavo(db, '2026-09-19T08:00:00.000Z');
    const shramba = ustvariShrambo(SEJA);
    // Branje z diska je namenoma počasnejše od odgovora strežnika.
    const pocasna: TestnaShramba = {
      ...shramba,
      getItemAsync: async (kljuc) => {
        await new Promise((razresi) => setTimeout(razresi, 30));
        return shramba.getItemAsync(kljuc);
      },
    };

    await izrisi(pocasna, ZETON);
    await povezano();

    expect(shramba.vsebina()).toContain(NOVA.zeton);
    expect(await jeOdjavaNedokoncana(db)).toBe(false);
    // Ostanek ni seja, zato strežniku ni kaj odjaviti.
    expect(odgovor.mock.calls.every(([url]) => !String(url).endsWith('/auth/logout'))).toBe(true);
  });

  it('povezava uspe, tudi če posvojitev pade', async () => {
    // Žeton je ob padcu posvojitve že na disku in seja na strežniku
    // ustvarjena, zato bi bilo sporočilo „Povezava ni uspela" laž.
    const pokvarjena = {
      ...db,
      runAsync: async (stavek: string, parametri: unknown[]) => {
        if (stavek.includes('user_id IS NULL')) throw new Error('database is locked');
        return db.runAsync(stavek, parametri as never);
      },
    };
    const shramba = ustvariShrambo();
    usmerjevalnik.stanje.params = { z: ZETON };

    await render(
      <PrijavaProvider db={pokvarjena} nastavitve={NASTAVITVE} shramba={shramba}>
        <SyncProvider db={pokvarjena} nastavitve={NASTAVITVE}>
          <PoveziScreen />
        </SyncProvider>
      </PrijavaProvider>,
    );
    await povezano();

    expect(screen.queryByTestId('napaka-povezave')).toBeNull();
    expect(shramba.vsebina()).toContain(NOVA.zeton);
  });

  // --- Varno območje (merilo dokončanosti) -----------------------------------

  it('navodilo pod kamero ne obtiči pod sistemsko navigacijsko vrstico', async () => {
    await izrisi(ustvariShrambo());

    expect(odmikSpodaj(screen.getByTestId('povezi-vsebina').props.style)).toBe(
      theme.spacing + TEST_INSETS.bottom,
    );
  });

  it('zaslon brez kamere ne obtiči pod sistemsko navigacijsko vrstico', async () => {
    // Druga veja istega zaslona ima svoj odmik; en test bi jo pustil nepokrito.
    kamera.stanje.permission = dovoljenje({ granted: false });
    await izrisi(ustvariShrambo());

    expect(odmikSpodaj(screen.getByTestId('povezi-vsebina').props.style)).toBe(
      theme.spacing + TEST_INSETS.bottom,
    );
  });
});
