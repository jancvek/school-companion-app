import { readFileSync, readdirSync } from 'node:fs';
import { join, relative } from 'node:path';

import { CREATE_KVIZI_TABLES_SQL } from '@/db/kvizi';
import { CREATE_MATERIALS_TABLE_SQL } from '@/db/materials';
import { CREATE_NAPRAVA_TABLE_SQL } from '@/db/naprava';
import { migriraj } from '@/db/migrations';

import { createTestDatabase } from './test-database';

/**
 * Kje sme živeti žeton (V3-R04).
 *
 * Kriterij pravi: **`expo-secure-store`, nikoli `expo-sqlite` in nikoli ob
 * slikah**. To ni lastnost, ki bi jo bilo mogoče preveriti z enim klicem — je
 * lastnost celotne kode, zato je varovalo statično, po vzoru
 * `no-network.test.ts`. Brez njega bi žeton nekoč pristal v lokalni bazi in
 * nihče tega ne bi opazil, dokler ne bi bilo prepozno.
 */

const KOREN = join(__dirname, '..');
const MAPE = ['app', 'src'];

/** Edina datoteka, ki se sme dotakniti varne shrambe. */
const DOVOLJENA = join('src', 'sync', 'prijava.ts');

function vseDatoteke(mapa: string): string[] {
  return readdirSync(mapa, { withFileTypes: true }).flatMap((vnos) => {
    const pot = join(mapa, vnos.name);
    if (vnos.isDirectory()) return vseDatoteke(pot);
    return /\.tsx?$/.test(vnos.name) ? [pot] : [];
  });
}

const datoteke = MAPE.flatMap((mapa) => vseDatoteke(join(KOREN, mapa)));
const relativno = (pot: string): string => relative(KOREN, pot);

/** Vsebina datoteke brez komentarjev — ostane samo to, kar se izvede. */
function brezKomentarjev(pot: string): string {
  return readFileSync(pot, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^[ \t]*\/\/.*$/gm, '');
}

describe('žeton živi samo v varni shrambi', () => {
  it('expo-secure-store uvaža natanko ena datoteka', () => {
    const uvozniki = datoteke
      .filter((pot) => /from\s+['"]expo-secure-store['"]/.test(readFileSync(pot, 'utf8')))
      .map(relativno);

    expect(uvozniki).toEqual([DOVOLJENA]);
  });

  it('nobena datoteka ne uvaža hkrati shrambe in lokalne baze', () => {
    // Datoteka, ki pozna oboje, je mesto, kjer bi žeton lahko zašel v bazo.
    const oboje = datoteke
      .filter((pot) => {
        const vsebina = readFileSync(pot, 'utf8');
        return (
          /from\s+['"]expo-secure-store['"]/.test(vsebina) &&
          /from\s+['"]expo-sqlite['"]/.test(vsebina)
        );
      })
      .map(relativno);

    expect(oboje).toEqual([]);
  });

  it('shema lokalne baze nima stolpca za žeton, geslo ali sejo', () => {
    const shema = [
      CREATE_MATERIALS_TABLE_SQL,
      CREATE_KVIZI_TABLES_SQL,
      CREATE_NAPRAVA_TABLE_SQL,
    ].join('\n');

    expect(shema).not.toMatch(/token|zeton|geslo|password|secret|seja/i);
  });

  it('migrirana baza nima nobene tabele ali stolpca za sejo', async () => {
    // Shema zgoraj je zamrznjena; ta test gleda, kaj po **vseh** migracijah
    // res stoji v bazi. Novega stolpca za žeton tako ne more prinesti niti
    // prihodnja migracija, ne da bi ta test padel.
    const db = createTestDatabase();
    try {
      await migriraj(db);
      const tabele = await db.getAllAsync<{ name: string }>(
        "SELECT name FROM sqlite_master WHERE type = 'table'",
        [],
      );

      for (const { name } of tabele) {
        expect(name).not.toMatch(/token|zeton|seja|session/i);
        const stolpci = await db.getAllAsync<{ name: string }>(
          `PRAGMA table_info(${name})`,
          [],
        );
        for (const stolpec of stolpci) {
          expect(stolpec.name).not.toMatch(/token|zeton|geslo|password|secret|session/i);
        }
      }
    } finally {
      db.close();
    }
  });

  it('API ključa ni nikjer več v kodi aplikacije', () => {
    // Prehod je oster (`docs/odlocitve/ADR-027`): ključ ne sme ostati niti kot
    // neuporabljena vrednost, ker bi bila to skrivnost v datoteki, ki jo
    // nihče ne vzdržuje.
    //
    // Komentarji so odšteti. Zgodovino — zakaj ključa **ni** — je prav, da
    // koda pove; varovalo, ki bi padlo na razlagi, bi razlago izgnalo.
    const ostanki = datoteke
      .filter((pot) => /X-API-Key|SERVER_API_KEY|\bapiKey\b/.test(brezKomentarjev(pot)))
      .map(relativno);

    expect(ostanki).toEqual([]);
  });

  it('tudi noben test ne pošilja več glave s ključem', () => {
    // Testi so pregledani ločeno in po ožjem vzorcu: `app-config` in
    // `server-config` ključ **morata** imenovati, ker dokazujeta prav
    // njegovo odsotnost, glava `X-API-Key` pa nima nobene take rabe več.
    // Ostanek vrednosti v testni nastavitvi je bil resničen (`ADR-036`,
    // popravki po pregledu) in `tsc` ga ni ujel, ker je bil literal vezan
    // na `const`.
    const ostanki = vseDatoteke(join(KOREN, '__tests__'))
      // Brez te datoteke: vzorec mora nekje pisati, in to je tu.
      .filter((pot) => !pot.endsWith('zeton-shramba.test.ts'))
      .filter((pot) => /X-API-Key/.test(brezKomentarjev(pot)))
      .map(relativno);

    expect(ostanki).toEqual([]);
  });
});
