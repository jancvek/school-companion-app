import {
  captureReducer,
  initialCaptureState,
  isPreviewing,
  type CaptureState,
} from '@/capture/session';

const POSNETEK = { uri: 'file:///cache/Camera/prvi.jpg', takenAt: '2026-09-03T14:32:10.000Z' };
const DRUGI = { uri: 'file:///cache/Camera/drugi.jpg', takenAt: '2026-09-03T14:33:00.000Z' };

describe('stanje zaslona s kamero', () => {
  it('se začne pri kameri, brez posnetka', () => {
    expect(initialCaptureState.photo).toBeNull();
    expect(isPreviewing(initialCaptureState)).toBe(false);
  });

  it('po posnetku pokaže predogled s potjo in časom posnetka', () => {
    const stanje = captureReducer(initialCaptureState, { type: 'captured', photo: POSNETEK });

    expect(isPreviewing(stanje)).toBe(true);
    expect(stanje.photo).toEqual(POSNETEK);
  });

  it('„Ponovi" zavrže prejšnjo pot do slike in čas posnetka', () => {
    const predogled = captureReducer(initialCaptureState, {
      type: 'captured',
      photo: POSNETEK,
    });

    const poPonovi = captureReducer(predogled, { type: 'retake' });

    expect(poPonovi.photo).toBeNull();
    expect(isPreviewing(poPonovi)).toBe(false);
  });

  it('„Ponovi" je mogoče uporabiti neomejeno', () => {
    let stanje: CaptureState = initialCaptureState;

    for (const posnetek of [POSNETEK, DRUGI, POSNETEK]) {
      stanje = captureReducer(stanje, { type: 'captured', photo: posnetek });
      expect(stanje.photo).toEqual(posnetek);
      stanje = captureReducer(stanje, { type: 'retake' });
      expect(stanje.photo).toBeNull();
    }

    expect(stanje).toEqual(initialCaptureState);
  });

  it('nov posnetek nadomesti prejšnjega', () => {
    const prvi = captureReducer(initialCaptureState, { type: 'captured', photo: POSNETEK });
    const drugi = captureReducer(prvi, { type: 'captured', photo: DRUGI });

    expect(drugi.photo).toEqual(DRUGI);
  });
});
