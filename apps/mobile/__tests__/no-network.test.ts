import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Regresija za kriterij „aplikacija deluje v celoti brez internetne povezave".
 * V1-R01 ne sme vsebovati nobenega omrežnega klica; prenos na strežnik je
 * predmet V1-R02.
 */

const KOREN = join(__dirname, '..');
const MAPE = ['app', 'src'];

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
  { ime: 'naslov http(s)', vzorec: /['"`]https?:\/\// },
];

function vseDatoteke(mapa: string): string[] {
  return readdirSync(mapa, { withFileTypes: true }).flatMap((vnos) => {
    const pot = join(mapa, vnos.name);
    if (vnos.isDirectory()) return vseDatoteke(pot);
    return /\.tsx?$/.test(vnos.name) ? [pot] : [];
  });
}

describe('brez omrežja', () => {
  const datoteke = MAPE.flatMap((mapa) => vseDatoteke(join(KOREN, mapa)));

  it('najde izvorne datoteke, ki jih preverja', () => {
    expect(datoteke.length).toBeGreaterThan(5);
  });

  it.each(PREPOVEDANI_VZORCI)('nikjer ne uporablja $ime', ({ vzorec }) => {
    const zadetki = datoteke.filter((pot) => vzorec.test(readFileSync(pot, 'utf8')));

    expect(zadetki).toEqual([]);
  });
});
