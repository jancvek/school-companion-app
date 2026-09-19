/**
 * Prijava in odjava telefona (V3-R04).
 *
 * Modul je v `src/sync/`, ker se dotakne omrežja — regresijski test
 * `__tests__/no-network.test.ts` drugje tega ne dovoli. Shramba žetona je
 * `expo-secure-store` in **nikoli** `expo-sqlite`: lokalna baza leži ob
 * slikah in ni šifrirana (`docs/odlocitve/ADR-027`).
 *
 * Kaj ta modul namenoma **ne** počne: ne odloča, kdaj se kdo prijavi, in ne
 * briše lokalnih zapisov. Prvo je naloga zaslona, drugo se ne zgodi nikoli —
 * odjava vzame žeton, ne posnetkov (`ADR-036` G).
 */

import * as SecureStore from 'expo-secure-store';

import type { ServerConfig } from '../config/server';
import { poslji, type Zahteva } from './http';

/** Koliko čakamo na prijavo; argon2 na strežniku je namenoma počasen. */
export const CASOVNA_OMEJITEV_MS = 30_000;

/** Ključ, pod katerim v varni shrambi leži seja. */
export const KLJUC_SEJE = 'seja';

/** Kdo je prijavljen na tej napravi. */
export type Seja = {
  /** Neprozoren žeton; aplikacija iz njega ne razbira ničesar (`ADR-027`). */
  zeton: string;
  /** `id` uporabnika — lastnik lokalnih zapisov (`ADR-036` B). */
  userId: string;
  /** Ime, kot ga pokažemo na domači strani. */
  ime: string;
};

/**
 * Napaka, ki jo uporabnica sme videti.
 *
 * Sporočilo je v slovenščini in pove, kaj naj naredi; surovega besedila
 * sistemske napake ne kaže kot edine vsebine (merilo dokončanosti).
 */
export class NapakaPrijave extends Error {
  constructor(sporocilo: string) {
    super(sporocilo);
    this.name = 'NapakaPrijave';
  }
}

const SPOROCILO_NI_NASTAVLJEN =
  'Prenos ni nastavljen, zato prijava ni mogoča. Aplikacijo je treba zgraditi z naslovom strežnika.';

const SPOROCILO_NEDOSEGLJIV =
  'Strežnik ni dosegljiv. Preveri povezavo in poskusi znova; posnetki na telefonu ostanejo.';

const SPOROCILO_NERAZUMLJIV =
  'Strežnik je odgovoril nepričakovano. Poskusi znova; če se ponovi, povej staršu.';

/**
 * Sporočilo, ki ga uporabnica vidi, ko žeton ni več veljaven.
 *
 * Isto besedilo za potekel in za odvzet žeton: za Mašo je razlika brez
 * pomena, dejanje pa isto (kriterij `V3-R04`).
 */
export const SPOROCILO_POTEKLA_PRIJAVA = 'Prijava je potekla, prijavi se znova.';

/** Kar ta modul potrebuje od varne shrambe; v testih se podtakne. */
export type VarnaShramba = {
  getItemAsync(kljuc: string): Promise<string | null>;
  setItemAsync(kljuc: string, vrednost: string): Promise<void>;
  deleteItemAsync(kljuc: string): Promise<void>;
};

const privzetaShramba: VarnaShramba = {
  getItemAsync: (kljuc) => SecureStore.getItemAsync(kljuc),
  setItemAsync: (kljuc, vrednost) => SecureStore.setItemAsync(kljuc, vrednost),
  deleteItemAsync: (kljuc) => SecureStore.deleteItemAsync(kljuc),
};

/** Ali je razbrani objekt res seja; shrambi ne verjamemo na besedo. */
function jeSeja(vrednost: unknown): vrednost is Seja {
  if (typeof vrednost !== 'object' || vrednost === null) return false;
  const s = vrednost as Record<string, unknown>;
  return typeof s.zeton === 'string' && typeof s.userId === 'string' && typeof s.ime === 'string';
}

/**
 * Seja iz varne shrambe, ali `null`.
 *
 * **Nikoli ne vrže.** Shramba je lahko nedosegljiva (naprava brez zaslonskega
 * zaklepa, poškodovan ključ) ali pa vsebuje zapis iz starejše različice;
 * aplikacija mora v obeh primerih delovati naprej, samo neprijavljena
 * (`ADR-036` A).
 */
export async function preberiSejo(
  shramba: VarnaShramba = privzetaShramba,
): Promise<Seja | null> {
  try {
    const zapis = await shramba.getItemAsync(KLJUC_SEJE);
    if (zapis === null) return null;
    const razbrano: unknown = JSON.parse(zapis);
    return jeSeja(razbrano) ? razbrano : null;
  } catch {
    return null;
  }
}

/** Zapiše sejo v varno shrambo. */
export async function shraniSejo(
  seja: Seja,
  shramba: VarnaShramba = privzetaShramba,
): Promise<void> {
  await shramba.setItemAsync(KLJUC_SEJE, JSON.stringify(seja));
}

/**
 * Pobriše sejo iz varne shrambe. Vrne, **ali je uspelo**.
 *
 * **Ne vrže.** Odjava, ki bi padla, bi pustila otroka prijavljenega na
 * napravi, na kateri se je hotel odjaviti — zato seja v pomnilniku pade v
 * vsakem primeru.
 *
 * Izid pa klicatelj potrebuje: ob neuspehu žeton ostane na disku in ga mora
 * naslednji zagon prepoznati kot **ostanek**, ne kot sejo. To ve po oznaki v
 * lokalni bazi (`src/db/naprava.ts`, `docs/odlocitve/ADR-037`), ki se sme
 * počistiti samo takrat, kadar je brisanje res uspelo.
 */
export async function pozabiSejo(shramba: VarnaShramba = privzetaShramba): Promise<boolean> {
  try {
    await shramba.deleteItemAsync(KLJUC_SEJE);
    return true;
  } catch {
    return false;
  }
}

/** Glava, s katero se telefon izkaže na vsaki poti (`ADR-027`). */
export function glaveSeje(seja: Seja): Record<string, string> {
  return { Authorization: `Bearer ${seja.zeton}` };
}

/** Odgovor strežnika na uspešno prijavo; strežniku ne verjamemo na besedo. */
function sejaIzOdgovora(telo: unknown): Seja {
  if (typeof telo !== 'object' || telo === null) throw new NapakaPrijave(SPOROCILO_NERAZUMLJIV);
  const t = telo as Record<string, unknown>;
  if (
    typeof t.token !== 'string' ||
    typeof t.user_id !== 'string' ||
    typeof t.display_name !== 'string'
  ) {
    throw new NapakaPrijave(SPOROCILO_NERAZUMLJIV);
  }
  return { zeton: t.token, userId: t.user_id, ime: t.display_name };
}

/** Sporočilo strežnika ob zavrnitvi, ali privzeto, če ga ni. */
function sporociloZavrnitve(telo: unknown): string {
  if (typeof telo === 'object' && telo !== null) {
    const podrobnost = (telo as { detail?: unknown }).detail;
    if (typeof podrobnost === 'string' && podrobnost.length > 0) return podrobnost;
  }
  return 'Uporabniško ime ali geslo ni pravo.';
}

/**
 * Prijavi se in vrne sejo; ob neuspehu vrže `NapakaPrijave` s sporočilom,
 * ki ga je mogoče pokazati.
 *
 * Seje **ne shrani** — to naredi klicatelj, skupaj s posvojitvijo zapisov
 * brez lastnika. Tako je v enem mestu vidno, da prijava na telefonu naredi
 * dvoje, ne eno.
 */
export async function prijaviSe(
  nastavitve: ServerConfig | null,
  identifikator: string,
  geslo: string,
  zahteva: Zahteva = fetch as unknown as Zahteva,
  casovnaOmejitevMs: number = CASOVNA_OMEJITEV_MS,
): Promise<Seja> {
  if (nastavitve === null) throw new NapakaPrijave(SPOROCILO_NI_NASTAVLJEN);

  let odgovor;
  try {
    odgovor = await poslji(
      zahteva,
      `${nastavitve.baseUrl}/auth/login`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifier: identifikator, password: geslo }),
      },
      casovnaOmejitevMs,
    );
  } catch {
    throw new NapakaPrijave(SPOROCILO_NEDOSEGLJIV);
  }

  if (!odgovor.ok) {
    let telo: unknown = null;
    try {
      telo = await odgovor.json();
    } catch {
      // Telo ni JSON. Sporočilo pade na privzetek; koda je pomembnejša.
    }
    throw new NapakaPrijave(
      odgovor.status >= 500 ? SPOROCILO_NEDOSEGLJIV : sporociloZavrnitve(telo),
    );
  }

  try {
    return sejaIzOdgovora(await odgovor.json());
  } catch (napaka) {
    if (napaka instanceof NapakaPrijave) throw napaka;
    throw new NapakaPrijave(SPOROCILO_NERAZUMLJIV);
  }
}

/**
 * Odjava na strežniku. **Najboljši poskus, ne pogoj** (`ADR-036` G).
 *
 * Nedosegljiv strežnik ne sme pustiti otroka prijavljenega na napravi, zato
 * ta funkcija ne vrže: klicatelj žeton pobriše v vsakem primeru. Seja na
 * strežniku takrat ostane do poteka roka — to je zapisana cena.
 */
export async function odjaviSe(
  nastavitve: ServerConfig | null,
  seja: Seja,
  zahteva: Zahteva = fetch as unknown as Zahteva,
  casovnaOmejitevMs: number = CASOVNA_OMEJITEV_MS,
): Promise<void> {
  if (nastavitve === null) return;
  try {
    await poslji(
      zahteva,
      `${nastavitve.baseUrl}/auth/logout`,
      { method: 'POST', headers: glaveSeje(seja) },
      casovnaOmejitevMs,
    );
  } catch {
    // Glej opis zgoraj.
  }
}
