import type { ConfigContext, ExpoConfig } from 'expo/config';

/**
 * Naslov strežnika in API ključ prideta v aplikacijo **ob gradnji**, iz
 * spremenljivk okolja (Expo naloži `.env` sam). V aplikaciji ni zaslona z
 * nastavitvami — odločitev 10 v `docs/plan/V1-R02.md`.
 *
 * Ključ s tem konča vgrajen v APK. To je zavestno: gre za en družinski ključ
 * na omrežju, ki je že zaprto s Tailscale. Cena je, da zamenjava ključa
 * zahteva novo gradnjo.
 *
 * Manjkajoča vrednost ni napaka ob gradnji — aplikacija mora delovati tudi
 * brez nastavljenega prenosa (odločitev 11), samo prenašati ne zna.
 *
 * `buildId` je oznaka gradnje EAS (V1-R06). Domača stran jo izpiše, da je s
 * telefona vidno, katera gradnja je nameščena; v razvoju je spremenljivke ni
 * in aplikacija to pove z „razvojna gradnja".
 */
export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: config.name ?? 'Šolski pomočnik',
  slug: config.slug ?? 'school-companion',
  extra: {
    ...config.extra,
    serverBaseUrl: process.env.SERVER_BASE_URL ?? null,
    apiKey: process.env.SERVER_API_KEY ?? null,
    buildId: process.env.EAS_BUILD_ID ?? null,
  },
});
