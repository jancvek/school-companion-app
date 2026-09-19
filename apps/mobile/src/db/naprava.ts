/**
 * Stanje naprave, ki ne sodi v varno shrambo (V3-R04, `ADR-037`).
 *
 * Zaenkrat ena sama stvar: **ali je zadnja odjava ostala nedokončana.**
 *
 * Zakaj tu in ne v `expo-secure-store`: oznaka obstaja prav zato, ker varna
 * shramba lahko odpove. `pozabiSejo` napako brisanja požre — sicer bi
 * nedosegljiva shramba pustila otroka prijavljenega na napravi, na kateri se
 * je hotel odjaviti —, zato žeton ob taki odpovedi ostane na disku. Brez te
 * oznake bi ga naslednji zagon prebral kot veljavno sejo in posvojil posnetke
 * drugega otroka prejšnjemu (`ADR-037`, kontekst).
 *
 * Tabela ima natanko eno vrstico. `CHECK (id = 1)` to jamči v shemi in ne v
 * kodi: vrstica, ki bi nastala po pomoti, bi pomenila dve resnici o isti
 * napravi.
 */

import type { MaterialsDatabase } from './materials';

/**
 * Shema, kakršno ustvari migracija 4 — **ne dopolnjuj je**, iz istega razloga
 * kot `CREATE_MATERIALS_TABLE_SQL`: telefon, ki je migracijo že prestal, je
 * nikoli več ne požene (`ADR-004`).
 */
export const CREATE_NAPRAVA_TABLE_SQL = `
CREATE TABLE IF NOT EXISTS naprava (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  odjava_ob TEXT
);
`;

type NapravaVrstica = { odjava_ob: string | null };

/**
 * Zabeleži, da se je odjava **začela**.
 *
 * Kliče se **pred** brisanjem iz varne shrambe. Obratni vrstni red bi pustil
 * okno, v katerem je žeton že izbrisan, oznake pa še ni — in prav v tem oknu
 * aplikacija najpogosteje umre, ker jo uporabnica takrat zapre.
 */
export async function zacniOdjavo(db: MaterialsDatabase, kdaj: string): Promise<void> {
  await db.runAsync(
    `INSERT INTO naprava (id, odjava_ob) VALUES (1, ?)
     ON CONFLICT(id) DO UPDATE SET odjava_ob = excluded.odjava_ob`,
    [kdaj],
  );
}

/**
 * Počisti oznako — odjava je prišla do konca, ali pa jo je preklicala prijava.
 *
 * `INSERT` in ne samo `UPDATE`: nad bazo, v kateri vrstice še ni, bi `UPDATE`
 * tiho ne naredil ničesar, kar je tu sicer neškodljivo, a bi pomenilo, da se
 * ta funkcija obnaša drugače kot njen par zgoraj.
 */
export async function koncajOdjavo(db: MaterialsDatabase): Promise<void> {
  await db.runAsync(
    `INSERT INTO naprava (id, odjava_ob) VALUES (1, NULL)
     ON CONFLICT(id) DO UPDATE SET odjava_ob = NULL`,
    [],
  );
}

/**
 * Ali je zadnja odjava ostala nedokončana.
 *
 * `true` pomeni: žeton, ki ga morda najdemo v varni shrambi, je **ostanek**
 * in ne seja. Prazna baza vrne `false` — naprava, na kateri se ni odjavil še
 * nihče, nima česa razveljavljati.
 */
export async function jeOdjavaNedokoncana(db: MaterialsDatabase): Promise<boolean> {
  const vrstice = await db.getAllAsync<NapravaVrstica>(
    'SELECT odjava_ob FROM naprava WHERE id = 1',
    [],
  );
  return vrstice[0]?.odjava_ob != null;
}
