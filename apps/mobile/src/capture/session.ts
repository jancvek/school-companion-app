/**
 * Stanje zaslona s kamero. Ločeno od zaslona zato, ker je „Ponovi" edini del
 * te poti, ki ga je mogoče preveriti brez naprave.
 */

export type CapturedPhoto = {
  uri: string;
  /** Trenutek posnetka, ne shranjevanja. */
  takenAt: string;
};

export type CaptureState = {
  /** `null` pomeni: kaži kamero. Sicer: kaži predogled. */
  photo: CapturedPhoto | null;
};

export type CaptureAction =
  | { type: 'captured'; photo: CapturedPhoto }
  | { type: 'retake' };

export const initialCaptureState: CaptureState = { photo: null };

export function captureReducer(
  state: CaptureState,
  action: CaptureAction,
): CaptureState {
  switch (action.type) {
    case 'captured':
      return { photo: action.photo };
    // „Ponovi" zavrže pot do slike in čas posnetka. Ponavljanje ni omejeno —
    // stanje po zavrnitvi je enako začetnemu.
    case 'retake':
      return initialCaptureState;
    default:
      return state;
  }
}

export function isPreviewing(state: CaptureState): boolean {
  return state.photo !== null;
}
