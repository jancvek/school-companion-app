import * as Crypto from 'expo-crypto';

import { insertMaterial, type MaterialsDatabase } from '../db/materials';
import { discardPhoto, savePhoto } from '../photos/store';
import type { Material } from '../types';

export type SaveCaptureInput = {
  /** Koda predmeta iz `SUBJECTS`. */
  subject: string;
  /** Trenutek posnetka, ISO 8601 v UTC. */
  takenAt: string;
  /** Začasni naslov, ki ga vrne kamera. */
  sourceUri: string;
  /**
   * Kdo je bil prijavljen ob posnetku; `null`, če nihče (V3-R04).
   *
   * Neobvezno in privzeto `null`, ker prijava ni pogoj za slikanje
   * (`docs/odlocitve/ADR-036` A): posnetek nastane tudi brez nje in ga
   * posvoji prva prijava.
   */
  userId?: string | null;
};

/**
 * Shrani posnetek: najprej datoteko, šele nato vrstico v bazi.
 *
 * Vrstni red ni naključen. Če pisanje datoteke pade (poln pomnilnik), vrstice
 * ni — nikoli ne ostane zapis brez slike. Obratni vrstni red bi puščal sirote.
 *
 * V obratni smeri (datoteka je zapisana, vstavljanje pade) datoteko pobrišemo,
 * da na disku ne ostane slika, ki je nič ne kaže.
 */
export async function saveCapture(
  db: MaterialsDatabase,
  { subject, takenAt, sourceUri, userId = null }: SaveCaptureInput,
): Promise<Material> {
  const id = Crypto.randomUUID();

  const fileUri = await savePhoto(sourceUri, `${id}.jpg`);

  const material: Material = {
    id,
    subject,
    taken_at: takenAt,
    file_uri: fileUri,
    sync_status: 'pending',
    sync_attempts: 0,
    last_attempt_at: null,
    sync_error: null,
    user_id: userId,
  };

  try {
    await insertMaterial(db, material);
  } catch (napaka) {
    discardPhoto(fileUri);
    throw napaka;
  }

  return material;
}
