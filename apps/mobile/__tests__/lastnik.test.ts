import {
  neprenesenePoskuse,
  pobrisiKvizeRazen,
  shraniKviz,
  zapisiPoskus,
} from '@/db/kvizi';
import {
  countByStatus,
  insertMaterial,
  listBySubject,
  listPending,
  posvojiBrezLastnika,
  retryFailed,
  type MaterialsDatabase,
} from '@/db/materials';
import { migriraj } from '@/db/migrations';
import { prenesiCakajoce } from '@/sync/worker';
import type { Material, Poskus } from '@/types';

import { kvizStreznika, poskus } from './kvizi-podatki';
import { createTestDatabase } from './test-database';

/**
 * Lastnik lokalnega zapisa (V3-R04, `docs/odlocitve/ADR-036` B in C).
 *
 * Naprava je skupna, identiteta pa ne. Ti testi pokrivajo natanko tisto, kar
 * kriterij zahteva: **zapis enega otroka ne odide pod žetonom drugega** — ne
 * snov ne poskus — in pri tem se nič ne izgubi.
 */

const MASA = 'u-masa';
const JAKA = 'u-jaka';

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
    user_id: MASA,
    ...overrides,
  };
}

describe('lastnik snovi', () => {
  let db: MaterialsDatabase & { close(): void };

  beforeEach(async () => {
    db = createTestDatabase();
    await migriraj(db);
  });

  afterEach(() => db.close());

  it('vrsta za prenos nosi samo zapise prijavljene uporabnice', async () => {
    await insertMaterial(db, material({ id: 'moj', user_id: MASA }));
    await insertMaterial(db, material({ id: 'tuj', user_id: JAKA }));

    expect((await listPending(db, MASA)).map((m) => m.id)).toEqual(['moj']);
    expect((await listPending(db, JAKA)).map((m) => m.id)).toEqual(['tuj']);
  });

  it('brez prijave vrsta nosi samo zapise brez lastnika', async () => {
    await insertMaterial(db, material({ id: 'nicejev', user_id: null }));
    await insertMaterial(db, material({ id: 'masin', user_id: MASA }));

    expect((await listPending(db, null)).map((m) => m.id)).toEqual(['nicejev']);
  });

  it('prenos tujega zapisa sploh ne poskusi', async () => {
    // To je jedro kriterija: ne gre za to, da bi strežnik tak prenos zavrnil,
    // ampak da do njega sploh ne pride.
    await insertMaterial(db, material({ id: 'tuj', user_id: JAKA }));
    const preneseni: string[] = [];

    const povzetek = await prenesiCakajoce(
      db,
      async (m) => {
        preneseni.push(m.id);
        return { vrsta: 'synced' };
      },
      MASA,
    );

    expect(preneseni).toEqual([]);
    expect(povzetek).toEqual({ preneseni: 0, cakajoci: 0, neuspeli: 0, prijavaPotekla: false });
  });

  it('tuj zapis po menjavi uporabnika ostane in ne izgine', async () => {
    await insertMaterial(db, material({ id: 'masin', user_id: MASA }));

    await prenesiCakajoce(db, async () => ({ vrsta: 'synced' }), JAKA);

    // Mašin zapis je še vedno v vrsti — za Mašo, ne za Jaka.
    expect((await listPending(db, MASA)).map((m) => m.id)).toEqual(['masin']);
  });

  it('števec šteje samo lastnikove zapise', async () => {
    await insertMaterial(db, material({ id: 'a', user_id: MASA }));
    await insertMaterial(db, material({ id: 'b', user_id: MASA, sync_status: 'failed' }));
    await insertMaterial(db, material({ id: 'c', user_id: JAKA }));

    expect(await countByStatus(db, MASA)).toEqual({ pending: 1, synced: 0, failed: 1 });
    expect(await countByStatus(db, JAKA)).toEqual({ pending: 1, synced: 0, failed: 0 });
  });

  it('zgodovina ne pokaže zapisov druge uporabnice', async () => {
    // Zvezek ene sestre ni stvar druge; in zapis, ki bi ga Zgodovina kazala,
    // prenos pa nikoli ne poslal, bi bil videti kot okvara.
    await insertMaterial(db, material({ id: 'moj', user_id: MASA }));
    await insertMaterial(db, material({ id: 'tuj', user_id: JAKA }));

    expect((await listBySubject(db, 'MAT', MASA)).map((m) => m.id)).toEqual(['moj']);
  });

  it('po odjavi Zgodovina ne pokaže zapisov, ki so nastali pod prijavo', async () => {
    // Zapisana posledica pravila B (`ADR-036`, popravki po pregledu), ne
    // spregled: naprava brez prijavljene osebe ne ve, komu bi smela kazati,
    // in odjava na skupnem telefonu ne sme biti način, kako videti sestrine
    // zvezke. Posnetki ostanejo in se po ponovni prijavi vrnejo.
    await insertMaterial(db, material({ id: 'masin', user_id: MASA }));

    // Odjavljena aplikacija: lastnika ni.
    expect(await listBySubject(db, 'MAT', null)).toEqual([]);

    // Zapis je še vedno tam in se po prijavi vrne.
    expect((await listBySubject(db, 'MAT', MASA)).map((m) => m.id)).toEqual(['masin']);
  });

  it('„Poskusi znova" ne vrne v vrsto tujih neuspelih zapisov', async () => {
    await insertMaterial(db, material({ id: 'tuj', user_id: JAKA, sync_status: 'failed' }));

    await retryFailed(db, MASA);

    expect(await countByStatus(db, JAKA)).toEqual({ pending: 0, synced: 0, failed: 1 });
  });
});

describe('posvojitev zapisov brez lastnika', () => {
  let db: MaterialsDatabase & { close(): void };

  beforeEach(async () => {
    db = createTestDatabase();
    await migriraj(db);
  });

  afterEach(() => db.close());

  it('posvojitev vzame snov, ki je nastala pred njo', async () => {
    // To je Mašin telefon po nadgradnji: vse obstoječe vrstice so brez
    // lastnika in bi brez posvojitve obtičale za vedno (`ADR-036` B).
    await insertMaterial(db, material({ id: 'stara', user_id: null }));

    await posvojiBrezLastnika(db, MASA);

    expect((await listPending(db, MASA)).map((m) => m.id)).toEqual(['stara']);
    expect(await listPending(db, null)).toEqual([]);
  });

  it('posvoji tudi neprenesene poskuse', async () => {
    await shraniKviz(db, kvizStreznika('k1', 1));
    await zapisiPoskus(db, poskus('k1', 1, { user_id: null }));

    await posvojiBrezLastnika(db, MASA);

    expect((await neprenesenePoskuse(db, MASA)).map((p) => p.id)).toEqual(['k1-a1']);
  });

  it('tujega zapisa ne posvoji', async () => {
    await insertMaterial(db, material({ id: 'jakov', user_id: JAKA }));

    await posvojiBrezLastnika(db, MASA);

    expect((await listPending(db, JAKA)).map((m) => m.id)).toEqual(['jakov']);
    expect(await listPending(db, MASA)).toEqual([]);
  });
});

describe('lastnik poskusa (ADR-036 C)', () => {
  let db: MaterialsDatabase & { close(): void };

  beforeEach(async () => {
    db = createTestDatabase();
    await migriraj(db);
  });

  afterEach(() => db.close());

  /** Neprenesen poskus dane osebe na svežem kvizu. */
  async function neprenesen(quizId: string, lastnik: string | null): Promise<Poskus> {
    await shraniKviz(db, kvizStreznika(quizId, 1));
    const p = poskus(quizId, 1, { user_id: lastnik });
    await zapisiPoskus(db, p);
    return p;
  }

  it('za prenos pobere samo poskuse prijavljene uporabnice', async () => {
    await neprenesen('k-masa', MASA);
    await neprenesen('k-jaka', JAKA);

    expect((await neprenesenePoskuse(db, MASA)).map((p) => p.id)).toEqual(['k-masa-a1']);
    expect((await neprenesenePoskuse(db, JAKA)).map((p) => p.id)).toEqual(['k-jaka-a1']);
  });

  it('kviz s tujim neprenesenim poskusom se ob usklajevanju ne pobriše', async () => {
    // Seznam s strežnika je seznam **prijavljenega** otroka. Brez te varovalke
    // bi kvizi prejšnjega padli, njegovi neposlani poskusi pa bi ostali kot
    // sirote — in bi šli gor pod napačnim žetonom.
    await neprenesen('k-jaka', JAKA);

    const pobrisani = await pobrisiKvizeRazen(db, [], null, MASA);

    expect(pobrisani).toBe(0);
    expect((await neprenesenePoskuse(db, JAKA)).map((p) => p.id)).toEqual(['k-jaka-a1']);
  });

  it('kviz brez tujih neprenesenih poskusov se pobriše kot doslej', async () => {
    // Varovalka ne sme ustaviti običajnega pospravljanja (`ADR-019` B).
    await shraniKviz(db, kvizStreznika('k-star', 1));

    expect(await pobrisiKvizeRazen(db, [], null, MASA)).toBe(1);
  });

  it('svoj neprenesen poskus kviza ne obdrži — ta gre gor in kviz za njim', async () => {
    // Pravilo `ADR-012` velja naprej: poskus se ne pobriše, dokler ni prenesen;
    // kviz pa sme iti, ker ga strežnik ne vrača več.
    await neprenesen('k-moj', MASA);

    const pobrisani = await pobrisiKvizeRazen(db, [], null, MASA);

    expect(pobrisani).toBe(1);
    expect((await neprenesenePoskuse(db, MASA)).map((p) => p.id)).toEqual(['k-moj-a1']);
  });
});
