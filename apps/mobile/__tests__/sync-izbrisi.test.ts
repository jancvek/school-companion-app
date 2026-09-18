import { findById, insertMaterial, type MaterialsDatabase } from '@/db/materials';
import {
  preveriIzbrisane,
  pobrisiLokalno,
  ustvariOdjemalca,
  ustvariPonavljalnik,
  type Odjemalec,
  type Zahteva,
} from '@/sync/izbrisi';
import { prenesiCakajoce } from '@/sync/worker';
import type { Izid } from '@/sync/upload';
import type { Material } from '@/types';

import { createMigratedDatabase } from './test-database';
import type { Seja } from '@/sync/prijava';

/** Seja, s katero se v testih izkaže telefon (V3-R04). */
const SEJA: Seja = { zeton: 'zeton-za-teste', userId: 'maša', ime: 'Maša' };

const NASTAVITVE = { baseUrl: 'https://school-buddy.duckdns.org' };

function material(id: string, overrides: Partial<Material> = {}): Material {
  return {
    id,
    subject: 'MAT',
    taken_at: '2026-09-01T10:00:00.000Z',
    file_uri: `file:///documents/photos/${id}.jpg`,
    sync_status: 'synced',
    sync_attempts: 0,
    last_attempt_at: null,
    sync_error: null,
  user_id: null,
    ...overrides,
  };
}

/** Odjemalec, ki vrne dani seznam in si zapomni, kaj smo potrdili. */
function odjemalec(ids: string[]): Odjemalec & { potrjeni: string[][] } {
  const potrjeni: string[][] = [];
  return {
    potrjeni,
    preberiSeznam: async () => ids,
    potrdi: async (kaj) => {
      potrjeni.push(kaj);
    },
  };
}

describe('preveriIzbrisane', () => {
  let db: MaterialsDatabase & { close(): void };

  beforeEach(async () => {
    db = await createMigratedDatabase();
  });

  afterEach(() => db.close());

  it('pobriše vrstico in datoteko ter nato potrdi', async () => {
    await insertMaterial(db, material('a'));
    const pobrisane: string[] = [];
    const streznik = odjemalec(['a']);

    const izid = await preveriIzbrisane(db, streznik, (uri) => {
      pobrisane.push(uri);
    });

    expect(await findById(db, 'a')).toBeNull();
    expect(pobrisane).toEqual(['file:///documents/photos/a.jpg']);
    expect(streznik.potrjeni).toEqual([['a']]);
    expect(izid).toEqual({ pobrisani: 1, potrjeni: 1, neuspeli: 0 });
  });

  it('vrstico pobriše pred datoteko', async () => {
    // Vrstica brez datoteke je vidna okvara v Zgodovini, osirotela datoteka je
    // nevidna in stane samo prostor. Če se vrstni red kdaj obrne, mora ta test
    // pasti — sicer se to opazi šele na telefonu.
    await insertMaterial(db, material('a'));
    let vrsticaObBrisanjuDatoteke: Material | null = material('a');

    await preveriIzbrisane(db, odjemalec(['a']), () => {
      void findById(db, 'a').then((zapis) => {
        vrsticaObBrisanjuDatoteke = zapis;
      });
    });
    await new Promise(process.nextTick);

    expect(vrsticaObBrisanjuDatoteke).toBeNull();
  });

  it('potrdi tudi zapis, ki ga na tej napravi ni', async () => {
    // Potrditev pomeni „tega tu ni več", ne „pravkar sem ga izbrisal". Brez
    // tega seznam po ponovni namestitvi aplikacije nikoli ne pade na nič.
    const streznik = odjemalec(['ni-ga']);

    const izid = await preveriIzbrisane(db, streznik, () => {
      throw new Error('datoteke se ne dotikamo');
    });

    expect(streznik.potrjeni).toEqual([['ni-ga']]);
    expect(izid).toEqual({ pobrisani: 0, potrjeni: 1, neuspeli: 0 });
  });

  it('ne potrdi zapisa, čigar datoteke ni znal pobrisati', async () => {
    // Potrditev pred dejanskim brisanjem bi pomenila zapis, ki ga strežnik
    // šteje za pospravljenega, na telefonu pa ostane.
    await insertMaterial(db, material('a'));
    await insertMaterial(db, material('b'));
    const streznik = odjemalec(['a', 'b']);

    const izid = await preveriIzbrisane(db, streznik, (uri) => {
      if (uri.includes('a.jpg')) throw new Error('disk');
    });

    expect(streznik.potrjeni).toEqual([['b']]);
    expect(izid.potrjeni).toBe(1);
    // Vrstica za „a" je kljub temu šla — brisanje datoteke je drugi korak.
    expect(await findById(db, 'a')).toBeNull();
    // Zato mora izid to povedati: `pobrisani` šteje samo do konca
    // pospravljene zapise („b"), `neuspeli` pa je znak klicatelju, da se je
    // baza vseeno spremenila in da je treba osvežiti števce.
    expect(izid.pobrisani).toBe(1);
    expect(izid.neuspeli).toBe(1);
  });

  it('ena neuspela datoteka ne ustavi ostalih', async () => {
    await insertMaterial(db, material('a'));
    await insertMaterial(db, material('b'));

    await preveriIzbrisane(db, odjemalec(['a', 'b']), (uri) => {
      if (uri.includes('a.jpg')) throw new Error('disk');
    });

    expect(await findById(db, 'b')).toBeNull();
  });

  it('praznega seznama ne potrjuje', async () => {
    const streznik = odjemalec([]);

    const izid = await preveriIzbrisane(db, streznik, () => {});

    expect(streznik.potrjeni).toEqual([]);
    expect(izid).toEqual({ pobrisani: 0, potrjeni: 0, neuspeli: 0 });
  });

  it('nedosegljiv strežnik pusti zapise pri miru', async () => {
    await insertMaterial(db, material('a'));
    const streznik: Odjemalec = {
      preberiSeznam: async () => {
        throw new Error('ni omrežja');
      },
      potrdi: async () => {},
    };

    await expect(preveriIzbrisane(db, streznik, () => {})).rejects.toThrow();
    expect(await findById(db, 'a')).not.toBeNull();
  });

  it('briše ne glede na stanje prenosa', async () => {
    // Zapis, ki je na telefonu obtičal v `pending`, mora izginiti enako kot
    // prenesen — sicer bi ostal v vrsti za strežnik, ki ga noče več.
    await insertMaterial(db, material('a', { sync_status: 'pending' }));

    await preveriIzbrisane(db, odjemalec(['a']), () => {});

    expect(await findById(db, 'a')).toBeNull();
  });
});

describe('prenos, ki naleti na arhiviran zapis', () => {
  let db: MaterialsDatabase & { close(): void };

  beforeEach(async () => {
    db = await createMigratedDatabase();
  });

  afterEach(() => db.close());

  it('zapis pobriše lokalno in ga ne šteje za neuspeh', async () => {
    // Rob, ki ga seznam za brisanje ne pokrije: posnetek je obtičal v
    // `pending`, medtem ko je bil na strežniku arhiviran in že potrjen, zato
    // je s seznama padel (`docs/odlocitve/ADR-011`).
    await insertMaterial(db, material('a', { sync_status: 'pending' }));
    const arhiviran: Izid = { vrsta: 'arhiviran' };

    const povzetek = await prenesiCakajoce(db, async () => arhiviran, null, async (baza, zapis) =>
      pobrisiLokalno(baza, zapis, () => {}),
    );

    expect(await findById(db, 'a')).toBeNull();
    expect(povzetek).toEqual({ preneseni: 0, cakajoci: 0, neuspeli: 0, prijavaPotekla: false });
  });
});

describe('odjemalec za arhiv', () => {
  it('pošlje ključ in prebere seznam', async () => {
    let videnUrl = '';
    let videneGlave: Record<string, string> = {};
    const zahteva: Zahteva = async (url, moznosti) => {
      videnUrl = url;
      videneGlave = moznosti.headers;
      return { ok: true, status: 200, json: async () => ({ ids: ['a', 'b'] }) };
    };

    const ids = await ustvariOdjemalca(NASTAVITVE, SEJA, zahteva).preberiSeznam();

    expect(videnUrl).toBe('https://school-buddy.duckdns.org/materials/pending-deletion');
    expect(videneGlave['Authorization']).toBe(`Bearer ${SEJA.zeton}`);
    expect(ids).toEqual(['a', 'b']);
  });

  it('neuspešen odgovor vrže in ne vrne praznega seznama', async () => {
    // Tiho vračanje praznega seznama bi bilo videti kot „ni nič za pobrisati"
    // in bi napako skrilo za vedno.
    const zahteva: Zahteva = async () => ({
      ok: false,
      status: 401,
      json: async () => ({}),
    });

    await expect(
      ustvariOdjemalca(NASTAVITVE, SEJA, zahteva).preberiSeznam(),
    ).rejects.toThrow(/401/);
  });

  it('odgovoru, ki ni seznam nizov, ne verjame', async () => {
    const zahteva: Zahteva = async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ids: ['a', 7, null] }),
    });

    expect(await ustvariOdjemalca(NASTAVITVE, SEJA, zahteva).preberiSeznam()).toEqual(['a']);
  });

  it('potrditev pošlje id-je v telesu', async () => {
    let telo = '';
    const zahteva: Zahteva = async (_url, moznosti) => {
      telo = moznosti.body ?? '';
      return { ok: true, status: 200, json: async () => ({ confirmed: 1 }) };
    };

    await ustvariOdjemalca(NASTAVITVE, SEJA, zahteva).potrdi(['a']);

    expect(JSON.parse(telo)).toEqual({ ids: ['a'] });
  });

  it('klic, ki se ne konča, se konča sam', async () => {
    // Isti razlog kot pri prenosu: viseč klic pusti zaporo postavljeno in
    // ponavljanje je do ponovnega zagona aplikacije mrtvo.
    const zahteva: Zahteva = (_url, moznosti) =>
      new Promise((_resolve, reject) => {
        moznosti.signal.addEventListener('abort', () => reject(new Error('prekinjeno')));
      });

    await expect(
      ustvariOdjemalca(NASTAVITVE, SEJA, zahteva, 10).preberiSeznam(),
    ).rejects.toThrow();
  });
});

describe('ponavljalnik', () => {
  it('dveh obhodov ne pusti teči hkrati', async () => {
    let tece = 0;
    let najvec = 0;
    // Predmet in ne spremenljivka: TypeScript prireditve v zaprtju ne vidi
    // in bi tip zožil na `null`.
    const ura: { sprosti: (() => void) | null } = { sprosti: null };

    const ponavljalnik = ustvariPonavljalnik({
      naloga: async () => {
        tece += 1;
        najvec = Math.max(najvec, tece);
        await new Promise<void>((resolve) => {
          ura.sprosti = () => resolve();
        });
        tece -= 1;
      },
      intervalMs: 0,
      nastaviCasovnik: (f) => {
        f();
        return 0 as unknown as ReturnType<typeof setTimeout>;
      },
      pocistiCasovnik: () => {},
    });

    ponavljalnik.zazeni();
    await new Promise(process.nextTick);
    ponavljalnik.ustavi();
    ura.sprosti?.();
    await new Promise(process.nextTick);

    expect(najvec).toBe(1);
  });

  it('po ustavitvi ne razporedi novega obhoda', async () => {
    let koliko = 0;
    const ura: { sprozi: (() => void) | null } = { sprozi: null };

    const ponavljalnik = ustvariPonavljalnik({
      naloga: async () => {
        koliko += 1;
      },
      nastaviCasovnik: (f) => {
        ura.sprozi = f;
        return 0 as unknown as ReturnType<typeof setTimeout>;
      },
      pocistiCasovnik: () => {},
    });

    ponavljalnik.zazeni();
    await new Promise(process.nextTick);
    ponavljalnik.ustavi();
    ura.sprozi?.();
    await new Promise(process.nextTick);

    expect(koliko).toBe(1);
  });

  it('napaka naloge ne ubije ponavljanja', async () => {
    let koliko = 0;
    const ura: { sprozi: (() => void) | null } = { sprozi: null };

    const ponavljalnik = ustvariPonavljalnik({
      naloga: async () => {
        koliko += 1;
        throw new Error('strežnik ni dosegljiv');
      },
      nastaviCasovnik: (f) => {
        ura.sprozi = f;
        return 0 as unknown as ReturnType<typeof setTimeout>;
      },
      pocistiCasovnik: () => {},
    });

    ponavljalnik.zazeni();
    await new Promise(process.nextTick);
    ura.sprozi?.();
    await new Promise(process.nextTick);
    ponavljalnik.ustavi();

    expect(koliko).toBe(2);
  });
});
