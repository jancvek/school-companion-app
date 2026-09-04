import type { ServerConfig } from '@/config/server';
import { prenesi, razvrstiStatus, type NaloziDatoteko } from '@/sync/upload';
import type { Material } from '@/types';

// Nativnega modula v testu ni; podtaknemo ga, da uvoz ne pade.
jest.mock('expo-file-system', () => ({
  __esModule: true,
  File: class {},
  UploadType: { BINARY_CONTENT: 0, MULTIPART: 1 },
}));

const NASTAVITVE: ServerConfig = { baseUrl: 'http://sto.jedro.ts.net:8000', apiKey: 'skrivnost' };

function material(overrides: Partial<Material> = {}): Material {
  return {
    id: 'id-1',
    subject: 'MAT',
    taken_at: '2026-09-01T10:00:00.000Z',
    file_uri: 'file:///documents/photos/id-1.jpg',
    sync_status: 'pending',
    sync_attempts: 0,
    last_attempt_at: null,
    sync_error: null,
    ...overrides,
  };
}

/** Nalagalec, ki vrne dani status. */
function vrni(status: number): NaloziDatoteko {
  return async () => ({ status });
}

describe('razvrščanje statusa', () => {
  it.each([200, 201, 204])('%i je uspeh', (status) => {
    // 201 je nov zapis, 200 zapis, ki je na strežniku že bil. Idempotentnost
    // je uspeh, ne napaka.
    expect(razvrstiStatus(status).vrsta).toBe('synced');
  });

  it.each([400, 401, 403, 404, 413, 422])('%i je dokončna zavrnitev', (status) => {
    expect(razvrstiStatus(status).vrsta).toBe('failed');
  });

  it.each([408, 429])('%i ostane v vrsti, čeprav je 4xx', (status) => {
    // 408 je potekel čas, 429 prošnja po počasnejšem tempu. Oboje mine samo
    // od sebe, zato zapis ne sme obtičati kot dokončno neuspel.
    expect(razvrstiStatus(status).vrsta).toBe('pending');
  });

  it.each([500, 502, 503])('%i ostane v vrsti', (status) => {
    expect(razvrstiStatus(status).vrsta).toBe('pending');
  });

  it('razlog pri zavrnjenem ključu pove, kaj je treba narediti', () => {
    const izid = razvrstiStatus(401);

    expect(izid.vrsta).toBe('failed');
    if (izid.vrsta !== 'synced') {
      expect(izid.razlog).toMatch(/ključ/i);
      expect(izid.razlog).not.toMatch(/^401$/);
    }
  });
});

describe('en prenos', () => {
  it('pošlje ključ v glavi in metapodatke kot polja', async () => {
    const nalozi = jest.fn<ReturnType<NaloziDatoteko>, Parameters<NaloziDatoteko>>(
      async () => ({ status: 201 }),
    );

    await prenesi(material(), NASTAVITVE, nalozi);

    expect(nalozi).toHaveBeenCalledWith(
      'file:///documents/photos/id-1.jpg',
      'http://sto.jedro.ts.net:8000/materials',
      {
        headers: { 'X-API-Key': 'skrivnost' },
        parameters: {
          id: 'id-1',
          subject: 'MAT',
          taken_at: '2026-09-01T10:00:00.000Z',
        },
        signal: expect.any(AbortSignal),
      },
    );
  });

  it('uspeh vrne synced', async () => {
    await expect(prenesi(material(), NASTAVITVE, vrni(201))).resolves.toEqual({
      vrsta: 'synced',
    });
  });

  it('podvojen prenos (200) je prav tako uspeh', async () => {
    await expect(prenesi(material(), NASTAVITVE, vrni(200))).resolves.toEqual({
      vrsta: 'synced',
    });
  });

  it('nedosegljiv strežnik pusti zapis v vrsti in ne vrže naprej', async () => {
    const nalozi: NaloziDatoteko = async () => {
      throw new Error('Network request failed');
    };

    const izid = await prenesi(material(), NASTAVITVE, nalozi);

    // Klicatelj je worker, ki teče brez čakanja — vržena napaka bi končala
    // kot nezavrnjena obljuba.
    expect(izid.vrsta).toBe('pending');
    if (izid.vrsta !== 'synced') {
      expect(izid.razlog).toMatch(/ni dosegljiv/i);
    }
  });

  it('tudi napaka, ki ni Error, ne pobegne', async () => {
    const nalozi: NaloziDatoteko = async () => {
      throw 'nekaj čisto drugega';
    };

    await expect(prenesi(material(), NASTAVITVE, nalozi)).resolves.toMatchObject({
      vrsta: 'pending',
    });
  });
});

describe('časovna omejitev prenosa', () => {
  it('viseč prenos se konča kot pending, ne kot viseča obljuba', async () => {
    // Brez tega bi cikel workerja obtičal, zapora `tece` bi ostala postavljena
    // in worker bi bil mrtev do ponovnega zagona aplikacije.
    const nalozi: NaloziDatoteko = () => new Promise(() => {});

    const izid = await prenesi(material(), NASTAVITVE, nalozi, 30);

    expect(izid.vrsta).toBe('pending');
    if (izid.vrsta !== 'synced') {
      expect(izid.razlog).toMatch(/ni odzval pravočasno/i);
    }
  });

  it('ob poteku časa prekine tudi nativni prenos', async () => {
    let signal: AbortSignal | undefined;
    const nalozi: NaloziDatoteko = (_uri, _url, moznosti) => {
      signal = moznosti.signal;
      return new Promise(() => {});
    };

    await prenesi(material(), NASTAVITVE, nalozi, 30);

    // Sicer bi za sabo puščali odprte povezave.
    expect(signal?.aborted).toBe(true);
  });

  it('pravočasen odgovor ni prekinjen', async () => {
    let signal: AbortSignal | undefined;
    const nalozi: NaloziDatoteko = async (_uri, _url, moznosti) => {
      signal = moznosti.signal;
      return { status: 201 };
    };

    const izid = await prenesi(material(), NASTAVITVE, nalozi, 10_000);

    expect(izid.vrsta).toBe('synced');
    expect(signal?.aborted).toBe(false);
  });
});
