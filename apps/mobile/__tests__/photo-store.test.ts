import {
  PHOTO_JPEG_QUALITY,
  PHOTO_MAX_WIDTH,
  compressPhoto,
  savePhoto,
} from '@/photos/store';

jest.mock('expo-image-manipulator', () => {
  const saveAsync = jest.fn();
  const renderAsync = jest.fn();
  const resize = jest.fn();
  const manipulate = jest.fn();
  return {
    __esModule: true,
    ImageManipulator: { manipulate },
    SaveFormat: { JPEG: 'jpeg', PNG: 'png', WEBP: 'webp' },
    spies: { manipulate, resize, renderAsync, saveAsync },
  };
});

jest.mock('expo-file-system', () => {
  const create = jest.fn();
  const move = jest.fn();
  const toUri = (parts: unknown[]) =>
    parts
      .map((part) => (typeof part === 'string' ? part : (part as { uri: string }).uri))
      .join('/');

  class Directory {
    uri: string;
    constructor(...parts: unknown[]) {
      this.uri = toUri(parts);
    }
    create(options: unknown) {
      create(options);
    }
  }

  class File {
    uri: string;
    constructor(...parts: unknown[]) {
      this.uri = toUri(parts);
    }
    move(target: { uri: string }) {
      return move(this.uri, target.uri);
    }
  }

  return {
    __esModule: true,
    Directory,
    File,
    Paths: { document: { uri: 'file:///documents' } },
    spies: { create, move },
  };
});

type Spy = jest.Mock;

const manipulator = jest.requireMock('expo-image-manipulator') as {
  spies: { manipulate: Spy; resize: Spy; renderAsync: Spy; saveAsync: Spy };
};
const fileSystem = jest.requireMock('expo-file-system') as {
  spies: { create: Spy; move: Spy };
};

const IZVIRNIK = 'file:///cache/Camera/original.jpg';
const STISNJENA = 'file:///cache/ImageManipulator/stisnjena.jpg';

beforeEach(() => {
  jest.clearAllMocks();

  manipulator.spies.saveAsync.mockResolvedValue({ uri: STISNJENA, width: 1600, height: 1200 });
  manipulator.spies.renderAsync.mockResolvedValue({ saveAsync: manipulator.spies.saveAsync });
  manipulator.spies.resize.mockReturnValue({ renderAsync: manipulator.spies.renderAsync });
  manipulator.spies.manipulate.mockReturnValue({ resize: manipulator.spies.resize });

  fileSystem.spies.move.mockResolvedValue(undefined);
});

describe('stiskanje slike', () => {
  it('pomanjša na 1600 px in shrani kot JPEG s kvaliteto 0.8', async () => {
    await expect(compressPhoto(IZVIRNIK)).resolves.toBe(STISNJENA);

    expect(manipulator.spies.manipulate).toHaveBeenCalledWith(IZVIRNIK);
    expect(manipulator.spies.resize).toHaveBeenCalledWith({ width: PHOTO_MAX_WIDTH });
    expect(manipulator.spies.resize).toHaveBeenCalledWith({ width: 1600 });
    expect(manipulator.spies.saveAsync).toHaveBeenCalledWith({
      compress: PHOTO_JPEG_QUALITY,
      format: 'jpeg',
    });
    expect(PHOTO_JPEG_QUALITY).toBe(0.8);
  });
});

describe('shranjevanje slike', () => {
  it('premakne stisnjeno sliko v documentDirectory/photos in vrne njen naslov', async () => {
    const naslov = await savePhoto(IZVIRNIK, 'abc.jpg');

    expect(fileSystem.spies.create).toHaveBeenCalledWith({
      intermediates: true,
      idempotent: true,
    });
    expect(fileSystem.spies.move).toHaveBeenCalledWith(
      STISNJENA,
      'file:///documents/photos/abc.jpg',
    );
    expect(naslov).toBe('file:///documents/photos/abc.jpg');
  });

  it('prenese napako pisanja naprej', async () => {
    fileSystem.spies.move.mockRejectedValue(new Error('Na napravi ni prostora'));

    await expect(savePhoto(IZVIRNIK, 'abc.jpg')).rejects.toThrow('Na napravi ni prostora');
  });
});
