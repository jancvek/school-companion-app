/**
 * Verzionirana shema lokalne baze.
 *
 * Zakaj sploh: `CREATE TABLE IF NOT EXISTS` obstoječi tabeli novega stolpca ne
 * doda in tega ne javi. Na telefonu, kjer so posnetki iz V1-R01, bi tabela
 * ostala stara, poizvedbe pa bi začele padati — medtem ko so testi nad svežo
 * bazo zeleni. Glej `docs/odlocitve/ADR-004`.
 *
 * Pravilo, ki velja odslej: **stare migracije se ne popravljajo.** Telefon, ki
 * je migracijo že prestal, je nikoli več ne požene. Kar je narobe, popravi
 * nova migracija.
 */

import { CREATE_KVIZI_TABLES_SQL } from './kvizi';
import { CREATE_MATERIALS_TABLE_SQL, type MaterialsDatabase } from './materials';
import { CREATE_NAPRAVA_TABLE_SQL } from './naprava';

/** Verzija sheme, ki jo pričakuje ta različica aplikacije. */
export const SHEMA_VERZIJA = 4;

type Migracija = {
  /** Verzija, ki velja, ko se ta korak konča. */
  doVerzije: number;
  izvedi(db: MaterialsDatabase): Promise<void>;
};

/**
 * Stolpci, ki jih shema V1-R01 ni imela.
 *
 * `sync_attempts` in `last_attempt_at` sta zapis za vmesnik in za
 * diagnostiko; razporejanje poskusov živi v workerju (odločitev 14 v planu).
 */
const STOLPCI_ZA_SINHRONIZACIJO = [
  'sync_attempts INTEGER NOT NULL DEFAULT 0',
  'last_attempt_at TEXT',
  'sync_error TEXT',
];

const MIGRACIJE: Migracija[] = [
  {
    doVerzije: 1,
    async izvedi(db) {
      // Tabela obstaja pri nadgradnji z V1-R01 in je ni pri sveži namestitvi.
      // Obe poti gresta skozi isto zaporedje, sicer bi obstajali dve shemi in
      // samo ena bi bila testirana (ADR-004).
      await db.execAsync(CREATE_MATERIALS_TABLE_SQL);

      const obstojeci = await imenaStolpcev(db, 'materials');
      for (const definicija of STOLPCI_ZA_SINHRONIZACIJO) {
        const ime = definicija.split(' ')[0];
        if (obstojeci.has(ime)) continue;
        await db.execAsync(`ALTER TABLE materials ADD COLUMN ${definicija}`);
      }
    },
  },
  {
    // Kvizi, postavke in poskusi (V2-R02). Samo nove tabele; `materials` se
    // ne dotakne. `IF NOT EXISTS` naredi korak ponovljiv, če se aplikacija
    // ubije med ustvarjanjem tabel in nastavitvijo `user_version`.
    doVerzije: 2,
    async izvedi(db) {
      await db.execAsync(CREATE_KVIZI_TABLES_SQL);
    },
  },
  {
    // Lastnik zapisa (V3-R04, `docs/odlocitve/ADR-036` B). Naprava je skupna,
    // identiteta pa ne: brez tega stolpca bi posnetek enega otroka odšel na
    // strežnik pod žetonom drugega.
    //
    // Obstoječe vrstice ostanejo z `NULL` — to pomeni „nastalo, ko ni bil
    // prijavljen nihče" in ne „brez lastnika za vedno": posvoji jih vsaka
    // razrešena seja (`posvojiBrezLastnika`), torej prijava ali obnovitev
    // žetona z diska. Brez tega bi bila nadgradnja Mašinega telefona vrsta,
    // ki ne odide nikoli.
    doVerzije: 3,
    async izvedi(db) {
      for (const tabela of ['materials', 'attempts']) {
        const obstojeci = await imenaStolpcev(db, tabela);
        if (obstojeci.has('user_id')) continue;
        await db.execAsync(`ALTER TABLE ${tabela} ADD COLUMN user_id TEXT`);
      }
      // Vrsta se bere po lastniku, `attempts` pa še po `uploaded_at`.
      await db.execAsync(`
        CREATE INDEX IF NOT EXISTS materials_user_id ON materials (user_id);
        CREATE INDEX IF NOT EXISTS attempts_user_id ON attempts (user_id);
      `);
    },
  },
  {
    // Sled o nedokončani odjavi (V3-R04, `docs/odlocitve/ADR-037`). Oznaka
    // sodi v to bazo prav zato, ker obstaja za primer, ko odpove varna
    // shramba: brez nje bi žeton, ki ga odjava ni uspela pobrisati, ob
    // naslednjem zagonu obveljal kot seja.
    //
    // Samo nova tabela; `materials` in `attempts` se ne dotakne.
    doVerzije: 4,
    async izvedi(db) {
      await db.execAsync(CREATE_NAPRAVA_TABLE_SQL);
    },
  },
];

type StolpecVrstica = { name: string };
type VerzijaVrstica = { user_version: number };

/** Imena stolpcev dane tabele. Prazna množica, če tabele ni. */
async function imenaStolpcev(
  db: MaterialsDatabase,
  tabela: string,
): Promise<Set<string>> {
  const vrstice = await db.getAllAsync<StolpecVrstica>(
    `PRAGMA table_info(${tabela})`,
    [],
  );
  return new Set(vrstice.map((vrstica) => vrstica.name));
}

/** Trenutna verzija sheme; sveža baza vrne 0. */
export async function preberiVerzijo(db: MaterialsDatabase): Promise<number> {
  const vrstice = await db.getAllAsync<VerzijaVrstica>('PRAGMA user_version', []);
  return vrstice[0]?.user_version ?? 0;
}

/**
 * Postavi shemo na {@link SHEMA_VERZIJA} in vrne doseženo verzijo.
 *
 * Migracije se poženejo po vrsti in samo tiste, ki še niso bile. Ponoven klic
 * nad že migrirano bazo ne naredi ničesar.
 */
export async function migriraj(db: MaterialsDatabase): Promise<number> {
  let verzija = await preberiVerzijo(db);

  for (const migracija of MIGRACIJE) {
    if (verzija >= migracija.doVerzije) continue;

    await migracija.izvedi(db);
    // `PRAGMA` ne sprejme parametrov; vrednost je konstanta iz kode, ne vnos.
    await db.execAsync(`PRAGMA user_version = ${migracija.doVerzije}`);
    verzija = migracija.doVerzije;
  }

  return verzija;
}
