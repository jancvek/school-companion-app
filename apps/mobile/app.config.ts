import type { ConfigContext, ExpoConfig } from 'expo/config';

/**
 * Naslov strežnika pride v aplikacijo **ob gradnji**, iz spremenljivke okolja
 * (Expo naloži `.env` sam). V aplikaciji ni zaslona z nastavitvami —
 * odločitev 10 v `docs/plan/V1-R02.md`.
 *
 * `SERVER_API_KEY` tu ni več (V3-R04). En vgrajen ključ za vse družine je bil
 * skrivnost, ki jo je nosil vsak APK; zamenjal ga je žeton, ki nastane ob
 * prijavi in živi v varni shrambi (`docs/odlocitve/ADR-027`, `ADR-036`).
 * Spremenljivko je treba pobrisati tudi na expo.dev, sicer ostane v okolju
 * gradnje, čeprav je nihče ne bere.
 *
 * `SERVER_BASE_URL` mora biti `https://`; drugačen naslov aplikacija šteje za
 * nenastavljen prenos (`src/config/server.ts`, `docs/odlocitve/ADR-034` E).
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
    buildId: process.env.EAS_BUILD_ID ?? null,
  },
});
