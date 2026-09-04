/**
 * Nastavitve prenosa, kot so prišle v aplikacijo ob gradnji.
 *
 * Odsotnost ni napaka: brez naslova ali ključa aplikacija deluje natanko tako
 * kot v V1-R01, samo prenašati ne zna (odločitev 11 v planu). Zato vrne
 * `null`, ne vrže izjeme.
 */

import Constants from 'expo-constants';

export type ServerConfig = {
  /** Osnovni naslov strežnika, brez poševnice na koncu. */
  baseUrl: string;
  apiKey: string;
};

/** Neprazen niz ali `null`; presledki se ne štejejo za vrednost. */
function niz(vrednost: unknown): string | null {
  if (typeof vrednost !== 'string') return null;
  const obrezan = vrednost.trim();
  return obrezan.length > 0 ? obrezan : null;
}

/**
 * Prebere nastavitve iz `extra`. Argument je tu zato, da ga testi podajo
 * neposredno in jim ni treba posnemati celotnega `expo-constants`.
 */
export function preberiNastavitve(
  extra: Record<string, unknown> | undefined | null = Constants.expoConfig?.extra,
): ServerConfig | null {
  const baseUrl = niz(extra?.serverBaseUrl);
  const apiKey = niz(extra?.apiKey);

  if (baseUrl === null || apiKey === null) return null;

  return { baseUrl: baseUrl.replace(/\/+$/, ''), apiKey };
}
