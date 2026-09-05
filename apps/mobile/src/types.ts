/**
 * Stanje prenosa zapisa na strežnik.
 *
 * Meja med `pending` in `failed` ni „koliko poskusov", ampak ali se stanje
 * sploh more spremeniti samo od sebe: `pending` je vse, kar bo jutri morda
 * šlo (strežnik ugasnjen, telefon izven omrežja), `failed` pa sodba o vsebini
 * zahteve, ki je ponavljanje ne bo spremenilo. Glej `docs/odlocitve/ADR-004`.
 */
export type SyncStatus = 'pending' | 'synced' | 'failed';

/** Vrstica v lokalni tabeli `materials`. Imena polj so enaka imenom stolpcev,
 *  ker se objekt bere neposredno iz `getAllAsync`. */
export type Material = {
  id: string;
  subject: string;
  /** Trenutek posnetka (ne shranjevanja), ISO 8601 v UTC. */
  taken_at: string;
  file_uri: string;
  sync_status: SyncStatus;
  /** Število neuspešnih poskusov prenosa. Zapis za vmesnik in diagnostiko. */
  sync_attempts: number;
  /** Zadnji poskus prenosa, ISO 8601 v UTC; `null`, dokler ga ni bilo. */
  last_attempt_at: string | null;
  /** Zakaj zadnji poskus ni uspel; `null`, če ni bilo napake. */
  sync_error: string | null;
};

/** Koliko zapisov je v katerem stanju prenosa. */
export type SyncPovzetek = {
  pending: number;
  synced: number;
  failed: number;
};
