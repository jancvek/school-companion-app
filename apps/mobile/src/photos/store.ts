import { Directory, File, Paths } from 'expo-file-system';
import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';

/** Širina, na katero se slika pomanjša pred shranjevanjem. */
export const PHOTO_MAX_WIDTH = 1600;
/** JPEG kvaliteta stisnjene slike. */
export const PHOTO_JPEG_QUALITY = 0.8;
/** Podmapa v `documentDirectory`, kjer živijo slike. */
export const PHOTOS_DIRECTORY_NAME = 'photos';

export function photosDirectory(): Directory {
  return new Directory(Paths.document, PHOTOS_DIRECTORY_NAME);
}

/**
 * Pomanjša na {@link PHOTO_MAX_WIDTH} px širine in stisne v JPEG.
 * Rezultat je začasna datoteka v predpomnilniku.
 */
export async function compressPhoto(sourceUri: string): Promise<string> {
  const image = await ImageManipulator.manipulate(sourceUri)
    .resize({ width: PHOTO_MAX_WIDTH })
    .renderAsync();

  const result = await image.saveAsync({
    compress: PHOTO_JPEG_QUALITY,
    format: SaveFormat.JPEG,
  });

  return result.uri;
}

/**
 * Stisne posnetek in ga premakne v `documentDirectory/photos/<ime>`.
 * Vrne končni `file://` naslov.
 *
 * Napake (npr. poln pomnilnik) se prenesejo naprej — klicatelj mora
 * poskrbeti, da v tem primeru ne nastane vrstica v bazi.
 */
export async function savePhoto(sourceUri: string, fileName: string): Promise<string> {
  const compressedUri = await compressPhoto(sourceUri);

  const directory = photosDirectory();
  directory.create({ intermediates: true, idempotent: true });

  const target = new File(directory, fileName);
  await new File(compressedUri).move(target);

  return target.uri;
}

/**
 * Pobriše sliko, za katero se je izkazalo, da vrstice v bazi ne bo.
 * Napake namenoma požre — brisanje je pospravljanje za drugo napako in je ne
 * sme prekriti.
 */
export function discardPhoto(fileUri: string): void {
  try {
    const file = new File(fileUri);
    if (file.exists) file.delete();
  } catch {
    // Sirota na disku je manjše zlo kot napaka, ki povozi prvotno.
  }
}
