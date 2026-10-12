import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import PrijavaScreen from '../app/prijava';
import { insertMaterial, listPending, type MaterialsDatabase } from '@/db/materials';
import { migriraj } from '@/db/migrations';
import { jeOdjavaNedokoncana } from '@/db/naprava';
import { shraniSejo } from '@/sync/prijava';
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
 * Zaslon povezave in odjave (V3-R04, V6-R01).
 *
 * Do `V6-R01` je bil to prijavni obrazec z uporabniškim imenom in geslom.
 * Otrok gesla nima več (`ADR-058`): sejo da zaslon `app/povezi.tsx`, in testi,
 * ki so skozi obrazec dokazovali prijavo, njena sporočila in posvojitev, so
 * zdaj v `povezi-zaslon.test.tsx`. Tu ostane, kar se dogaja **brez**
 * povezovanja: obnovitev seje z diska, odjava in oznaka o nedokončani odjavi
 * (`ADR-036`, `ADR-037`).
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

/** Odmik `padding` iz sloga; sloge React Native podaja kot gnezdena polja. */
function odmik(style: unknown): number {
  const kosi = Array.isArray(style) ? style.flat(Infinity) : [style];
  for (const kos of [...kosi].reverse()) {
    const vrednost = (kos as { padding?: number } | null)?.padding;
    if (typeof vrednost === 'number') return vrednost;
  }
  return 0;
}

describe('zaslon povezave in odjave', () => {
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
      expect(screen.getByTestId(prijavljena ? 'prijavljen' : 'ni-povezan')).toBeTruthy();
    });
    return izid;
  }

  /**
   * Pritisne gumb za odjavo in počaka, da se zaslon umiri.
   *
   * Čaka na nepovezano obliko zaslona in ne le na izginotje napisa
   * `Odjavljam…`: odjava je veriga obljub (oznaka, shramba, strežnik), zaslon
   * pa je odjavljen šele, ko to pokaže. Brez tega bi se naslednji `render` v
   * istem testu prepletel z nedokončanim `act`.
   */
  async function odjavi() {
    await act(async () => {
      fireEvent.press(screen.getByTestId('gumb-odjava'));
    });
    await waitFor(() => {
      expect(screen.getByTestId('ni-povezan')).toBeTruthy();
    });
  }

  it('obnovljena seja posvoji zapise, ki so nastali brez prijave', async () => {
    // Posnetek, ki nastane, **dokler je aplikacija videti neprijavljena**
    // (spodletelo branje ali spodletelo brisanje iz varne shrambe), bi brez
    // tega ostal nedosegljiv za vedno: ne v Zgodovini, ne v vrsti za prenos,
    // ne v števcih. Kriterij V3-R04 pravi, da se **nobena** lokalno
    // shranjena snov ne izgubi — zato posvoji vsaka razrešena seja, ne
    // samo prijava (`docs/odlocitve/ADR-036` B).
    await insertMaterial(db, material({ id: 'v-oknu', user_id: null }));

    // Zagon z žetonom, ki je že v shrambi: `povezi()` se ne pokliče.
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

    // Aplikacija je nepovezana in Jakov posnetek čaka na **njegovo**
    // povezavo, ne na Mašino.
    expect(screen.getByTestId('ni-povezan')).toBeTruthy();
    expect(await listPending(db, SEJA.userId)).toEqual([]);
    expect((await listPending(db, null)).map((m) => m.id)).toEqual(['jakov']);
  });

  it('uspešna odjava oznake ne pusti za sabo', async () => {
    // Sicer bi naslednja seja na isti napravi ostala brez posvojitve, ker bi
    // oznaka že veljavno sejo razglasila za ostanek.
    const shramba = ustvariShrambo(SEJA);
    await izrisi(shramba, true);

    await odjavi();
    expect(await jeOdjavaNedokoncana(db)).toBe(false);
    await insertMaterial(db, material({ id: 'po-odjavi', user_id: null }));

    // Nova seja na disku, kakršno zapiše povezava telefona (njen zaslon ima
    // svoje teste), in nov zagon: seja obvelja in posvoji.
    await shraniSejo(SEJA, shramba);
    await izrisi(shramba, true);

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
    expect(screen.getByTestId('ni-povezan')).toBeTruthy();
    expect(shramba.vsebina()).toContain(SEJA.zeton);
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

  it('obnovljena seja ne posvoji zapisov druge uporabnice', async () => {
    // Posvojitev je za zapise **brez** lastnika; tuj zapis ostane tuj.
    await insertMaterial(db, material({ id: 'jakov', user_id: 'u-jaka' }));

    await izrisi(ustvariShrambo(SEJA), true);

    expect(await listPending(db, SEJA.userId)).toEqual([]);
    expect((await listPending(db, 'u-jaka')).map((m) => m.id)).toEqual(['jakov']);
  });

  it('prijavljeni vidi svoje ime in gumb za odjavo', async () => {
    await izrisi(ustvariShrambo(SEJA), true);

    expect(screen.getByTestId('prijavljen').props.children).toContain('Maša');
    expect(screen.getByTestId('gumb-odjava')).toBeTruthy();
  });

  it('polj za uporabniško ime in geslo ni več', async () => {
    // Kriterij `V6-R01`: mobilna prijava z geslom odpade. Zaslon mora to tudi
    // povedati, sicer otrok išče, kam bi geslo vpisal.
    await izrisi(ustvariShrambo());

    expect(screen.queryByTestId('polje-ime')).toBeNull();
    expect(screen.queryByTestId('polje-geslo')).toBeNull();
    expect(screen.getByText(/Gesla ne potrebuješ/)).toBeTruthy();
    expect(odgovor).not.toHaveBeenCalled();
  });

  it('nepovezan telefon ponudi povezavo s QR kodo', async () => {
    await izrisi(ustvariShrambo());

    expect(screen.getByText('Poveži s QR kodo')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('gumb-povezi'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenLastCalledWith('/povezi');
  });

  it('povezan telefon je mogoče povezati znova', async () => {
    // Pot po „Prekliči prijave": telefon še hrani žeton, ki na strežniku ne
    // velja več, in otrok mora priti do bralnika brez odjave (`ADR-061` I).
    await izrisi(ustvariShrambo(SEJA), true);

    expect(screen.getByText('Poveži znova s QR kodo')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('gumb-povezi'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenLastCalledWith('/povezi');
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

    expect(odmikSpodaj(vsebina.props.style)).toBe(theme.spacing + TEST_INSETS.bottom);
  });

  it('prijavljena veja ne obtiči pod sistemsko navigacijsko vrstico', async () => {
    // Gumb za odjavo je v drugi veji istega zaslona in ima svoj odmik;
    // en test bi drugo vejo pustil nepokrito.
    await izrisi(ustvariShrambo(SEJA), true);

    const vsebina = screen.getByTestId('odjava-vsebina');

    expect(odmikSpodaj(vsebina.props.style)).toBe(theme.spacing + TEST_INSETS.bottom);
  });

  it('obe veji imata odmik od stranskih robov', async () => {
    // Odjavna veja ga je sprva imela samo spodaj, zato sta se besedilo in
    // gumb dotikala levega in desnega roba — edini tak zaslon v aplikaciji.
    await izrisi(ustvariShrambo());
    expect(odmik(screen.getByTestId('prijava-vsebina').props.style)).toBe(theme.spacing * 1.5);

    await izrisi(ustvariShrambo(SEJA), true);
    expect(odmik(screen.getByTestId('odjava-vsebina').props.style)).toBe(
      theme.spacing * 1.5,
    );
  });
});
