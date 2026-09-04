import { readFileSync, readdirSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

/**
 * Varovalka za kriterij „aplikacija ostane povsem uporabna, tudi če strežnik
 * ni dosegljiv".
 *
 * V V1-R01 je bila prepoved absolutna: nikjer nobenega omrežnega klica.
 * V1-R02 omrežje uvede, zato je prepoved **zožena, ne odpravljena** —
 * dovoljena je natanko ena mapa, `src/sync/`. Ker je zožitev rahljanje
 * obstoječe varovalke, je zraven nadomestna: spodaj se preveri tudi, da je
 * `src/sync/` res edina mapa, ki se omrežja dotakne. Brez nje bi se prepoved
 * dalo izničiti tako, da se klic preprosto preseli drugam.
 */

const KOREN = join(__dirname, '..');
const MAPE = ['app', 'src'];

/** Edina mapa, ki sme govoriti z omrežjem. */
const DOVOLJENA_MAPA = join('src', 'sync');

const PREPOVEDANI_VZORCI: { ime: string; vzorec: RegExp }[] = [
  // Klici
  { ime: 'fetch(', vzorec: /\bfetch\s*\(/ },
  { ime: 'XMLHttpRequest', vzorec: /\bXMLHttpRequest\b/ },
  { ime: 'axios', vzorec: /\baxios\b/ },
  { ime: 'new WebSocket', vzorec: /\bnew\s+WebSocket\b/ },
  { ime: 'EventSource', vzorec: /\bnew\s+EventSource\b/ },
  // Uvozi — klic bi šel mimo zgornjih vzorcev, če bi bil preimenovan.
  { ime: "uvoz 'expo/fetch'", vzorec: /from\s+['"]expo\/fetch['"]/ },
  { ime: "uvoz 'expo-network'", vzorec: /from\s+['"]expo-network['"]/ },
  { ime: "uvoz 'expo-updates'", vzorec: /from\s+['"]expo-updates['"]/ },
  { ime: 'uvoz nalaganja datotek', vzorec: /\b(UploadTask|DownloadTask|downloadFileAsync)\b/ },
  // Nalaganje prek `expo-file-system`; V1-R02 uporablja prav to.
  { ime: 'File(...).upload', vzorec: /\.upload\s*\(/ },
  { ime: 'UploadType', vzorec: /\bUploadType\b/ },
  { ime: 'naslov http(s)', vzorec: /['"`]https?:\/\// },
];

function vseDatoteke(mapa: string): string[] {
  return readdirSync(mapa, { withFileTypes: true }).flatMap((vnos) => {
    const pot = join(mapa, vnos.name);
    if (vnos.isDirectory()) return vseDatoteke(pot);
    return /\.tsx?$/.test(vnos.name) ? [pot] : [];
  });
}

/** Pot glede na koren `apps/mobile`, npr. `src/sync/upload.ts`. */
function relativno(pot: string): string {
  return relative(KOREN, pot);
}

function jeVDovoljeniMapi(pot: string): boolean {
  return relativno(pot).startsWith(DOVOLJENA_MAPA + sep);
}

function seDotakneOmrezja(pot: string): boolean {
  const vsebina = readFileSync(pot, 'utf8');
  return PREPOVEDANI_VZORCI.some(({ vzorec }) => vzorec.test(vsebina));
}

describe('omrežje je omejeno na en modul', () => {
  const datoteke = MAPE.flatMap((mapa) => vseDatoteke(join(KOREN, mapa)));
  const zunajDovoljeneMape = datoteke.filter((pot) => !jeVDovoljeniMapi(pot));

  it('najde izvorne datoteke, ki jih preverja', () => {
    expect(datoteke.length).toBeGreaterThan(5);
  });

  it('dovoljena mapa obstaja in ni prazna', () => {
    // Če se `src/sync/` kdaj preimenuje, mora ta test pasti — sicer bi
    // izjema ostala zapisana za mapo, ki je ni, prepoved pa bi tiho veljala
    // tudi za novo lokacijo omrežne kode.
    const vDovoljeni = datoteke.filter((pot) => jeVDovoljeniMapi(pot));
    expect(vDovoljeni.length).toBeGreaterThan(0);
  });

  it.each(PREPOVEDANI_VZORCI)(
    'nikjer razen v src/sync ne uporablja $ime',
    ({ vzorec }) => {
      const zadetki = zunajDovoljeneMape
        .filter((pot) => vzorec.test(readFileSync(pot, 'utf8')))
        .map(relativno);

      expect(zadetki).toEqual([]);
    },
  );

  it('src/sync je edina mapa, ki se omrežja sploh dotakne', () => {
    // Nadomestilo za zožitev prepovedi: prenos se ne sme preseliti drugam,
    // ne da bi ta test to javil.
    const mapeZOmrezjem = new Set(
      datoteke
        .filter(seDotakneOmrezja)
        .map((pot) => relativno(pot).split(sep).slice(0, -1).join(sep)),
    );

    expect([...mapeZOmrezjem].sort()).toEqual([DOVOLJENA_MAPA]);
  });
});
