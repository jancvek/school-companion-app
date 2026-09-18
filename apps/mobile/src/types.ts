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
  /**
   * Kdo je bil prijavljen, ko je zapis nastal (V3-R04).
   *
   * `null` pomeni „ni bil prijavljen nihče" in ne „brez lastnika za vedno":
   * prva uspešna prijava tak zapis posvoji (`docs/odlocitve/ADR-036` B).
   * Prenaša se izključno tisto, kar je last prijavljene uporabnice.
   */
  user_id: string | null;
};

/** Koliko zapisov je v katerem stanju prenosa. */
export type SyncPovzetek = {
  pending: number;
  synced: number;
  failed: number;
};

/**
 * Štiri stopnje samoocene (`docs/odlocitve/ADR-014`). Prva je hkrati
 * pravilnost, ostale tri težavnost. Kode so iste kot na strežniku.
 */
export type Ocena = 'nisem_vedela' | 'tezko' | 'srednje' | 'lahko';

/** Način odgovarjanja; v V2 je edini samoocena (`ADR-014`). */
export type Nacin = 'samoocena';

/** Kviz, kot ga pošlje strežnik (`GET /quizzes/pending`). */
export type KvizStreznika = {
  id: string;
  name: string;
  /** Čas objave, ISO 8601 z pasom. */
  created_at: string;
  items: {
    id: string;
    position: number;
    question: string;
    answer: string;
    /** Postavka na strežniku že ima poskus (`ADR-019` E). */
    answered: boolean;
  }[];
};

/** Kviz, ki čaka na reševanje, s številom postavk in odgovorjenih. */
export type KvizNaSeznamu = {
  id: string;
  name: string;
  created_at: string;
  vprasanj: number;
  odgovorjenih: number;
};

/** Ena postavka lokalnega kviza, z izpeljanim podatkom, ali je odgovorjena. */
export type PostavkaKviza = {
  id: string;
  quiz_id: string;
  position: number;
  question_text: string;
  answer_text: string;
  /** Ima lokalni poskus ali je bila odgovorjena že na strežniku. */
  odgovorjena: boolean;
};

/**
 * En odgovor na eno postavko — dogodek (`ADR-012`). Imena polj so enaka imenom
 * stolpcev lokalne tabele `attempts`.
 */
export type Poskus = {
  /** UUID, generiran na telefonu; nosilec idempotentnosti. */
  id: string;
  quiz_id: string;
  quiz_item_id: string;
  mode: Nacin;
  rating: Ocena;
  /** Trije žigi, ISO 8601 v UTC (`ADR-019` D). */
  shown_at: string;
  revealed_at: string;
  answered_at: string;
  /** Kdaj ga je strežnik sprejel; `null`, dokler ni prenesen. */
  uploaded_at: string | null;
  /** Kdo je odgovoril; `null`, če ni bil prijavljen nihče (`ADR-036` B). */
  user_id: string | null;
};
