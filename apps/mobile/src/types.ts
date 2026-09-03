/** Stanje sinhronizacije zapisa. V1-R01 zna ustvariti samo `pending`;
 *  prehod v `synced` je predmet V1-R02. */
export type SyncStatus = 'pending' | 'synced';

/** Vrstica v lokalni tabeli `materials`. Imena polj so enaka imenom stolpcev,
 *  ker se objekt bere neposredno iz `getAllAsync`. */
export type Material = {
  id: string;
  subject: string;
  /** Trenutek posnetka (ne shranjevanja), ISO 8601 v UTC. */
  taken_at: string;
  file_uri: string;
  sync_status: SyncStatus;
};
