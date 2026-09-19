import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import PrijavaScreen from '../app/prijava';
import { insertMaterial, listPending, type MaterialsDatabase } from '@/db/materials';
import { migriraj } from '@/db/migrations';
import { jeOdjavaNedokoncana, zacniOdjavo } from '@/db/naprava';
import { PrijavaProvider } from '@/sync/use-prijava';
import { SyncProvider } from '@/sync/use-sync';
import type { Material } from '@/types';
import { theme } from '@/ui/theme';

import { SEJA, ustvariShrambo, type TestnaShramba } from './shramba';
import { createTestDatabase } from './test-database';
import { odmikSpodaj, TEST_INSETS, type RouterMockState } from './screen-mocks';

jest.mock('expo-router', () => require('./screen-mocks').expoRouterMock());
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

const NASTAVITVE = { baseUrl: 'https://school-buddy.duckdns.org' };

/**
 * Prijavni zaslon (V3-R04).
 *
 * Zaslon ne kliče strežnika sam — to počne `src/sync/prijava.ts`, ki ima svoje
 * teste. Tu se preverja, kaj vidi in dobi **uporabnica**: da so sporočila v
 * slovenščini, da prijava ne izgubi posnetkov in da je odjava odjava.
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

describe('prijavni zaslon', () => {
  let db: MaterialsDatabase & { close(): void };
  let odgovor: jest.Mock;

  beforeEach(async () => {
    db = createTestDatabase();
    await migriraj(db);
    odgovor = jest.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        token: 'nov-zeton',
        user_id: SEJA.userId,
        display_name: 'Maša',
        expires_at: '2026-10-18T10:00:00+00:00',
      }),
    }));
    (globalThis as { fetch?: unknown }).fetch = odgovor;
  });

  afterEach(() => {
    db.close();
    delete (globalThis as { fetch?: unknown }).fetch;
  });

  async function izrisi(shramba: TestnaShramba, prijavljena = false) {
    const izid = await render(
      <PrijavaProvider db={db} nastavitve={NASTAVITVE} shramba={shramba}>
        <SyncProvider
          db={db}
          nastavitve={NASTAVITVE}
          prenesiEno={async () => ({ vrsta: 'pending', razlog: 'test' })}
        >
          <PrijavaScreen />
        </SyncProvider>
      </PrijavaProvider>,
    );
    // Branje žetona z diska je učinek; dokler ne steče, je zaslon videti kot
    // neprijavljen. Testi zato počakajo na obliko, ki jo pričakujejo.
    await waitFor(() => {
      expect(screen.getByTestId(prijavljena ? 'prijavljen' : 'polje-ime')).toBeTruthy();
    });
    return izid;
  }

  /**
   * Pritisne gumb in počaka, da se zaslon umiri.
   *
   * Prijava je veriga obljub (klic, shramba, posvojitev); en `act` ne
   * zajamči, da so vse že pretekle. Čakanje na izginotje napisa
   * `Prijavljam…` je pogoj, ki ga zaslon sam postavi in odstrani.
   */
  async function vpisiInPotrdi(ime: string, geslo: string) {
    await fireEvent.changeText(screen.getByTestId('polje-ime'), ime);
    await fireEvent.changeText(screen.getByTestId('polje-geslo'), geslo);
    await act(async () => {
      fireEvent.press(screen.getByTestId('gumb-prijava'));
    });
    await waitFor(() => {
      expect(screen.queryByText('Prijavljam…')).toBeNull();
    });
  }

  /**
   * Isto za odjavo.
   *
   * Čaka na prijavni obrazec in ne le na izginotje napisa `Odjavljam…`:
   * odjava je veriga obljub (oznaka, shramba, strežnik), zaslon pa je
   * odjavljen šele, ko pokaže obrazec. Brez tega bi se naslednji `render` v
   * istem testu prepletel z nedokončanim `act`.
   */
  async function odjavi() {
    await act(async () => {
      fireEvent.press(screen.getByTestId('gumb-odjava'));
    });
    await waitFor(() => {
      expect(screen.getByTestId('polje-ime')).toBeTruthy();
    });
  }

  it('uspešna prijava shrani sejo in se vrne nazaj', async () => {
    const shramba = ustvariShrambo();
    await izrisi(shramba);

    await vpisiInPotrdi('masa', 'geslo-otroka');

    expect(shramba.vsebina()).toContain('nov-zeton');
    expect(usmerjevalnik.stanje.router.back).toHaveBeenCalled();
  });

  it('prijava posvoji posnetke, ki so nastali pred njo', async () => {
    // Kriterij V3-R04 in `ADR-036` B: vrsta, ki je nastala brez prijave, po
    // prijavi odide — ne obtiči.
    const shramba = ustvariShrambo();
    await insertMaterial(db, material({ id: 'pred-prijavo', user_id: null }));
    await izrisi(shramba);

    await vpisiInPotrdi('masa', 'geslo-otroka');

    await waitFor(async () => {
      expect((await listPending(db, SEJA.userId)).map((m) => m.id)).toEqual(['pred-prijavo']);
    });
  });

  it('obnovljena seja posvoji zapise, ki so nastali brez prijave', async () => {
    // Posnetek, ki nastane, **dokler je aplikacija videti neprijavljena**
    // (spodletelo branje ali spodletelo brisanje iz varne shrambe), bi brez
    // tega ostal nedosegljiv za vedno: ne v Zgodovini, ne v vrsti za prenos,
    // ne v števcih. Kriterij V3-R04 pravi, da se **nobena** lokalno
    // shranjena snov ne izgubi — zato posvoji vsaka razrešena seja, ne
    // samo prijava (`docs/odlocitve/ADR-036` B).
    await insertMaterial(db, material({ id: 'v-oknu', user_id: null }));

    // Zagon z žetonom, ki je že v shrambi: `prijavi()` se ne pokliče.
    await izrisi(ustvariShrambo(SEJA), true);

    await waitFor(async () => {
      expect((await listPending(db, SEJA.userId)).map((m) => m.id)).toEqual(['v-oknu']);
    });
    expect(await listPending(db, null)).toEqual([]);
  });

  it('žeton, ki ga je pustila spodletela odjava, ne obvelja kot seja', async () => {
    // Jedro `ADR-037`. Zaporedje: Maša se odjavi, brisanje iz varne
    // shrambe tiho pade, Jaka slika, aplikacija se zapre in znova odpre.
    // Brez oznake bi se Mašina seja obnovila in posvojila Jakove posnetke.
    const shramba = ustvariShrambo(SEJA);
    await izrisi(shramba, true);

    // Brisanje iz varne shrambe spodleti; žeton ostane na disku.
    shramba.pokvari();
    await odjavi();
    expect(shramba.vsebina()).toContain(SEJA.zeton);

    // Jakov posnetek, nastal po odjavi: brez lastnika.
    await insertMaterial(db, material({ id: 'jakov', user_id: null }));
    shramba.popravi();

    // Nov zagon: ista shramba, isti žeton. Prejšnjega drevesa ne odklapljamo
    // ročno — `screen` kaže na zadnji izris, pospravi pa ju oba `cleanup`.
    await izrisi(shramba);

    // Aplikacija je neprijavljena in Jakov posnetek čaka na **njegovo**
    // prijavo, ne na Mašino.
    expect(screen.getByTestId('polje-ime')).toBeTruthy();
    expect(await listPending(db, SEJA.userId)).toEqual([]);
    expect((await listPending(db, null)).map((m) => m.id)).toEqual(['jakov']);
  });

  it('uspešna odjava oznake ne pusti za sabo', async () => {
    // Sicer bi naslednja prijava na isti napravi ostala brez posvojitve,
    // ker bi oznaka že veljavno sejo razglasila za ostanek.
    const shramba = ustvariShrambo(SEJA);
    await izrisi(shramba, true);

    await odjavi();
    await insertMaterial(db, material({ id: 'po-odjavi', user_id: null }));

    await izrisi(shramba);
    await vpisiInPotrdi('masa', 'geslo-otroka');

    await waitFor(async () => {
      expect((await listPending(db, SEJA.userId)).map((m) => m.id)).toEqual(['po-odjavi']);
    });
  });

  it('zagon z ostankom brisanje ponovi in oznako počisti', async () => {
    // `ADR-037` tega ne obljublja mimogrede: žeton, ki bi ostal na disku za
    // vedno, bi bil skrivnost, ki je nihče ne vzdržuje, in vsak naslednji
    // zagon bi ga znova zavračal.
    const shramba = ustvariShrambo(SEJA);
    await izrisi(shramba, true);

    shramba.pokvari();
    await odjavi();
    shramba.popravi();

    await izrisi(shramba);

    await waitFor(() => expect(shramba.vsebina()).toBeUndefined());
    expect(await jeOdjavaNedokoncana(db)).toBe(false);
  });

  it('če tudi drugo brisanje spodleti, oznaka ostane', async () => {
    // Pogoj `if (await pozabiSejo(...))` na poti zagona: oznako sme počistiti
    // samo brisanje, ki je **uspelo**. Sicer bi šel naslednji zagon mimo nje,
    // žeton bi obveljal kot seja — in to je natanko napaka, zaradi katere je
    // `ADR-037` nastal, samo en zagon pozneje.
    // Odpove **samo brisanje**: žeton ostane berljiv. Popolna odpoved tega ne
    // pokaže, ker takrat tudi branje vrne `null` in koda do te veje ne pride.
    const shramba = ustvariShrambo(SEJA);
    await izrisi(shramba, true);

    shramba.pokvariBrisanje();
    await odjavi();

    // Nov zagon, brisanje še vedno ne dela.
    await izrisi(shramba);

    expect(await jeOdjavaNedokoncana(db)).toBe(true);
    expect(screen.getByTestId('polje-ime')).toBeTruthy();
    expect(shramba.vsebina()).toContain(SEJA.zeton);
  });

  it('prijava prekliče nedokončano odjavo pred njo', async () => {
    // Oznaka brez žetona: odjava je žeton pobrisala, `koncaj` pa je padel
    // (okvarjena baza). Zagon je tedaj ne počisti — veja za ostanek se
    // ujame samo, kadar žeton **je**. Počisti jo prijava, in to je edino
    // mesto, kjer se to zgodi.
    //
    // Sicer bi **veljaven** žeton ob naslednjem zagonu srečal staro oznako
    // in bi bil zavržen — tiha odjava brez sporočila (`ADR-037`).
    await zacniOdjavo(db, '2026-09-19T08:00:00.000Z');
    const shramba = ustvariShrambo();

    await izrisi(shramba);
    expect(await jeOdjavaNedokoncana(db)).toBe(true);

    await vpisiInPotrdi('masa', 'geslo-otroka');

    expect(await jeOdjavaNedokoncana(db)).toBe(false);

    // Nov zagon: sveža seja obvelja in ni zavržena kot ostanek.
    await izrisi(shramba, true);
    expect(screen.getByTestId('prijavljen')).toBeTruthy();
  });

  it('oznaka nastane pred brisanjem iz varne shrambe', async () => {
    // Vrstni red je jedro `ADR-037`: obratni bi pustil okno, v katerem je
    // žeton že izbrisan, oznake pa še ni — in prav takrat uporabnica
    // aplikacijo najpogosteje zapre.
    const shramba = ustvariShrambo(SEJA);
    let oznakaObBrisanju: boolean | null = null;
    const opazovana = {
      ...shramba,
      deleteItemAsync: async (kljuc: string) => {
        oznakaObBrisanju = await jeOdjavaNedokoncana(db);
        return shramba.deleteItemAsync(kljuc);
      },
    };

    await izrisi(opazovana, true);
    await odjavi();

    expect(oznakaObBrisanju).toBe(true);
  });

  it('obnovljena seja preživi padlo posvojitev', async () => {
    // Posvojitev je ob robu seje, ne seja sama: če pade (poln disk,
    // zaklenjena baza), mora žeton z diska še vedno obveljati. Sicer bi
    // aplikacija ostala videti neprijavljena, čeprav veljavna prijava
    // obstaja — in uporabnica o tem ne bi izvedela ničesar.
    const pokvarjena = {
      ...db,
      runAsync: async (stavek: string, parametri: unknown[]) => {
        if (stavek.includes('user_id IS NULL')) throw new Error('database is locked');
        return db.runAsync(stavek, parametri as never);
      },
    };

    await render(
      <PrijavaProvider
        db={pokvarjena}
        nastavitve={NASTAVITVE}
        shramba={ustvariShrambo(SEJA)}
      >
        <SyncProvider db={pokvarjena} nastavitve={NASTAVITVE}>
          <PrijavaScreen />
        </SyncProvider>
      </PrijavaProvider>,
    );

    // Seja je obveljala; posvojitev se ponovi ob naslednji razrešeni seji.
    expect(await screen.findByTestId('prijavljen')).toBeTruthy();
  });

  it('prijava uspe, tudi če posvojitev pade', async () => {
    // Zrcalno: žeton je ob padcu posvojitve že na disku in seja na
    // strežniku ustvarjena, zato bi bilo sporočilo „Prijava ni uspela“ laž.
    const pokvarjena = {
      ...db,
      runAsync: async (stavek: string, parametri: unknown[]) => {
        if (stavek.includes('user_id IS NULL')) throw new Error('database is locked');
        return db.runAsync(stavek, parametri as never);
      },
    };
    const shramba = ustvariShrambo();

    await render(
      <PrijavaProvider db={pokvarjena} nastavitve={NASTAVITVE} shramba={shramba}>
        <SyncProvider db={pokvarjena} nastavitve={NASTAVITVE}>
          <PrijavaScreen />
        </SyncProvider>
      </PrijavaProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('polje-ime')).toBeTruthy());

    await vpisiInPotrdi('masa', 'geslo-otroka');

    expect(screen.queryByTestId('napaka-prijave')).toBeNull();
    expect(shramba.vsebina()).toContain('nov-zeton');
    expect(usmerjevalnik.stanje.router.back).toHaveBeenCalled();
  });

  it('obnovljena seja ne posvoji zapisov druge uporabnice', async () => {
    // Posvojitev je za zapise **brez** lastnika; tuj zapis ostane tuj.
    await insertMaterial(db, material({ id: 'jakov', user_id: 'u-jaka' }));

    await izrisi(ustvariShrambo(SEJA), true);

    expect(await listPending(db, SEJA.userId)).toEqual([]);
    expect((await listPending(db, 'u-jaka')).map((m) => m.id)).toEqual(['jakov']);
  });

  it('napačno geslo pokaže sporočilo v slovenščini in ne shrani ničesar', async () => {
    odgovor.mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: 'Uporabniško ime ali geslo ni pravo.' }),
    });
    const shramba = ustvariShrambo();
    await izrisi(shramba);

    await vpisiInPotrdi('masa', 'napacno');

    expect(await screen.findByTestId('napaka-prijave')).toBeTruthy();
    expect(screen.getByTestId('napaka-prijave').props.children).toMatch(/geslo/i);
    expect(shramba.vsebina()).toBeUndefined();
  });

  it('starševski račun dobi razlago, kam sodi', async () => {
    odgovor.mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({
        detail: 'Ta račun je starševski in se prijavi na spletni strani, ne v aplikaciji.',
      }),
    });
    await izrisi(ustvariShrambo());

    await vpisiInPotrdi('stars@primer.test', 'geslo-starsa-12');

    expect((await screen.findByTestId('napaka-prijave')).props.children).toMatch(
      /spletni strani/i,
    );
  });

  it('nedosegljiv strežnik ne pokaže surove sistemske napake', async () => {
    odgovor.mockRejectedValue(new Error('Network request failed'));
    await izrisi(ustvariShrambo());

    await vpisiInPotrdi('masa', 'geslo-otroka');

    const besedilo = (await screen.findByTestId('napaka-prijave')).props.children as string;
    expect(besedilo).not.toMatch(/Network request failed/);
    expect(besedilo).toMatch(/posnetki/i);
  });

  it('brez nastavljenega naslova pove, zakaj prijava ni mogoča', async () => {
    await render(
      <PrijavaProvider db={db} nastavitve={null} shramba={ustvariShrambo()}>
        <SyncProvider db={db} nastavitve={null}>
          <PrijavaScreen />
        </SyncProvider>
      </PrijavaProvider>,
    );
    await act(async () => {});

    expect(screen.getByTestId('prenos-ni-nastavljen')).toBeTruthy();
  });

  it('prijavljeni vidi svoje ime in gumb za odjavo', async () => {
    await izrisi(ustvariShrambo(SEJA), true);

    expect(screen.getByTestId('prijavljen').props.children).toContain('Maša');
    expect(screen.getByTestId('gumb-odjava')).toBeTruthy();
  });

  it('odjava pobriše žeton, lokalnih posnetkov pa ne', async () => {
    // Kriterij V3-R04: „Odjava izbriše žeton in sejo na strežniku, lokalnih
    // slik pa ne briše."
    const shramba = ustvariShrambo(SEJA);
    await insertMaterial(db, material({ id: 'moj', user_id: SEJA.userId }));
    await izrisi(shramba, true);

    await odjavi();

    expect(shramba.vsebina()).toBeUndefined();
    expect((await listPending(db, SEJA.userId)).map((m) => m.id)).toEqual(['moj']);
  });

  it('odjava ostane odjava, tudi če strežnik ne odgovori', async () => {
    // Nedosegljiv strežnik ne sme pustiti otroka prijavljenega na napravi,
    // na kateri se je hotel odjaviti (`ADR-036` G).
    odgovor.mockRejectedValue(new Error('Network request failed'));
    const shramba = ustvariShrambo(SEJA);
    await izrisi(shramba, true);

    await odjavi();

    expect(shramba.vsebina()).toBeUndefined();
    expect(usmerjevalnik.stanje.router.back).toHaveBeenCalled();
  });

  it('neprijavljena veja ne obtiči pod sistemsko navigacijsko vrstico', async () => {
    // Android riše edge-to-edge (merilo dokončanosti), zato mora gumb
    // prišteti spodnji odmik varnega območja — sicer je pod sistemsko
    // navigacijsko vrstico in ga ni mogoče pritisniti.
    await izrisi(ustvariShrambo());

    const vsebina = screen.getByTestId('prijava-vsebina');

    expect(odmikSpodaj(vsebina.props.contentContainerStyle)).toBe(
      theme.spacing + TEST_INSETS.bottom,
    );
  });

  it('prijavljena veja ne obtiči pod sistemsko navigacijsko vrstico', async () => {
    // Gumb za odjavo je v drugi veji istega zaslona in ima svoj odmik;
    // en test bi drugo vejo pustil nepokrito.
    await izrisi(ustvariShrambo(SEJA), true);

    const vsebina = screen.getByTestId('odjava-vsebina');

    expect(odmikSpodaj(vsebina.props.style)).toBe(theme.spacing + TEST_INSETS.bottom);
  });
});
