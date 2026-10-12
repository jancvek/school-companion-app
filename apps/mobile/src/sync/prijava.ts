/**
 * Povezava in odjava telefona (V3-R04, V6-R01).
 *
 * Do `V6-R01` se je otrok prijavil z uporabniškim imenom in geslom. Odslej
 * gesla nima: telefon poveže starš s QR kodo, aplikacija pa enkratni žeton
 * iz nje zamenja za sejo (`docs/odlocitve/ADR-058`, `ADR-061`). Seja sama je
 * ista kot prej.
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

/**
 * Koliko čakamo na povezavo ali odjavo. Strežnik sme pred preverbo žetona
 * namenoma počakati (`ADR-061` E), zato meja ni kratka.
 */
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
  /**
   * Ali sme isti poskus znova (V6-R01). `true` samo, kadar zahteva do
   * strežnika ni prišla ali je ta odgovoril „poskusi pozneje": koda takrat ni
   * porabljena. Po zavrnitvi bi ponovitev iste kode samo štela v mejo
   * poskusov, ki je skupna za vso namestitev (`ADR-061` E).
   */
  readonly ponovljivo: boolean;

  constructor(sporocilo: string, ponovljivo = false) {
    super(sporocilo);
    this.name = 'NapakaPrijave';
    this.ponovljivo = ponovljivo;
  }
}

const SPOROCILO_NI_NASTAVLJEN =
  'Prenos ni nastavljen, zato telefona ni mogoče povezati. Povej staršu.';

const SPOROCILO_NEDOSEGLJIV =
  'Strežnik ni dosegljiv. Preveri povezavo in poskusi znova; posnetki na telefonu ostanejo.';

const SPOROCILO_NERAZUMLJIV =
  'Strežnik je odgovoril nepričakovano. Poskusi znova; če se ponovi, povej staršu.';

/**
 * Sporočilo, ki ga uporabnica vidi, ko žeton seje ni več veljaven.
 *
 * Isto besedilo za potekel in za odvzet žeton: za otroka je razlika brez
 * pomena, dejanje pa isto (kriterij `V3-R04`). Od `V6-R01` se otrok ne more
 * prijaviti sam, zato sporočilo pove, koga naj prosi.
 */
export const SPOROCILO_POTEKLA_PRIJAVA = 'Prijava je potekla. Prosi starša za novo kodo.';

/**
 * Kar otrok vidi, ko povezovalni žeton ne velja — potekel, že porabljen ali
 * neznan. Strežnik pove isto (`ADR-061` F); to besedilo je tu za primer, ko
 * zavrnitev pride brez razumljivega telesa.
 */
export const SPOROCILO_KODA_NE_VELJA = 'Koda ne velja več. Prosi starša za novo.';

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

/** Odgovor strežnika na uspešno povezavo; strežniku ne verjamemo na besedo. */
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

/** Sporočilo strežnika ob zavrnjeni kodi, ali privzeto, če ga ni. */
function sporociloZavrnitve(telo: unknown): string {
  if (typeof telo === 'object' && telo !== null) {
    const podrobnost = (telo as { detail?: unknown }).detail;
    if (typeof podrobnost === 'string' && podrobnost.length > 0) return podrobnost;
  }
  return SPOROCILO_KODA_NE_VELJA;
}

/** Statusi, ki ne pomenijo sodbe o kodi, ampak „poskusi pozneje" (`ADR-004`). */
const ZACASNI_STATUSI = new Set([408, 429]);

/**
 * Sporočilo za neuspešen odgovor.
 *
 * Besedilo strežnika se pokaže **samo ob `401`** — to je edini odgovor, za
 * katerega vemo, da ga je napisala pot povezave in da je v slovenščini.
 * Vsak drug 4xx (npr. `404` strežnika, ki poti še nima, ali `422`) bi sicer
 * na zaslon prinesel surovo angleško besedilo ogrodja.
 */
function sporociloNeuspeha(status: number, telo: unknown): string {
  if (status === 401) return sporociloZavrnitve(telo);
  if (status >= 500 || ZACASNI_STATUSI.has(status)) return SPOROCILO_NEDOSEGLJIV;
  return SPOROCILO_NERAZUMLJIV;
}

/**
 * Unovči povezovalni žeton in vrne sejo; ob neuspehu vrže `NapakaPrijave` s
 * sporočilom, ki ga je mogoče pokazati.
 *
 * Seje **ne shrani** — to naredi klicatelj, skupaj s posvojitvijo zapisov
 * brez lastnika. Tako je v enem mestu vidno, da povezava na telefonu naredi
 * dvoje, ne eno.
 *
 * Nedosegljiv strežnik žetona ne porabi: zahteva do njega ni prišla, zato
 * sme otrok isto kodo prebrati znova (`docs/plan/V6-R01.md`).
 */
export async function poveziSe(
  nastavitve: ServerConfig | null,
  zeton: string,
  zahteva: Zahteva = fetch as unknown as Zahteva,
  casovnaOmejitevMs: number = CASOVNA_OMEJITEV_MS,
): Promise<Seja> {
  if (nastavitve === null) throw new NapakaPrijave(SPOROCILO_NI_NASTAVLJEN);

  let odgovor;
  try {
    odgovor = await poslji(
      zahteva,
      `${nastavitve.baseUrl}/auth/link`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: zeton }),
      },
      casovnaOmejitevMs,
    );
  } catch {
    throw new NapakaPrijave(SPOROCILO_NEDOSEGLJIV, true);
  }

  if (!odgovor.ok) {
    let telo: unknown = null;
    try {
      telo = await odgovor.json();
    } catch {
      // Telo ni JSON. Sporočilo pade na privzetek; koda je pomembnejša.
    }
    const sporocilo = sporociloNeuspeha(odgovor.status, telo);
    throw new NapakaPrijave(sporocilo, sporocilo === SPOROCILO_NEDOSEGLJIV);
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
