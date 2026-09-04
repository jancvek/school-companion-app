import { fireEvent, render, screen } from '@testing-library/react-native';

import HomeScreen from '../app/index';
import PickSubjectForCaptureScreen from '../app/slikaj/index';
import PickSubjectForHistoryScreen from '../app/zgodovina/index';
import { SUBJECTS } from '@/constants/subjects';
import type { RouterMockState } from './screen-mocks';

jest.mock('expo-router', () => require('./screen-mocks').expoRouterMock());
jest.mock('react-native-safe-area-context', () => require('./screen-mocks').safeAreaMock());

const usmerjevalnik = jest.requireMock('expo-router') as { stanje: RouterMockState };

beforeEach(() => {
  jest.clearAllMocks();
});

describe('domača stran', () => {
  it('ponuja natanko gumba „Slikaj snov" in „Zgodovina"', async () => {
    await render(<HomeScreen />);

    expect(screen.getByText('Slikaj snov')).toBeTruthy();
    expect(screen.getByText('Zgodovina')).toBeTruthy();
  });

  it('„Slikaj snov" pelje na izbiro predmeta za slikanje', async () => {
    await render(<HomeScreen />);

    await fireEvent.press(screen.getByText('Slikaj snov'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenCalledWith('/slikaj');
  });

  it('„Zgodovina" pelje na izbiro predmeta za zgodovino', async () => {
    await render(<HomeScreen />);

    await fireEvent.press(screen.getByText('Zgodovina'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenCalledWith('/zgodovina');
  });
});

describe('izbira predmeta', () => {
  it('izriše vseh deset predmetov v dogovorjenem vrstnem redu', async () => {
    await render(<PickSubjectForCaptureScreen />);

    for (const predmet of SUBJECTS) {
      expect(screen.getByText(predmet.label)).toBeTruthy();
    }
  });

  it('pri slikanju nese kodo predmeta naprej, ne oznake', async () => {
    await render(<PickSubjectForCaptureScreen />);

    await fireEvent.press(screen.getByText('MAT — Matematika'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenCalledWith({
      pathname: '/slikaj/[subject]',
      params: { subject: 'MAT' },
    });
  });

  it('v zgodovini nese kodo predmeta naprej, ne oznake', async () => {
    await render(<PickSubjectForHistoryScreen />);

    await fireEvent.press(screen.getByText('GUM — Glasbena umetnost'));

    expect(usmerjevalnik.stanje.router.push).toHaveBeenCalledWith({
      pathname: '/zgodovina/[subject]',
      params: { subject: 'GUM' },
    });
  });

  it('tudi predmet brez posnetkov je na seznamu zgodovine', async () => {
    await render(<PickSubjectForHistoryScreen />);

    expect(screen.getByText('GUM — Glasbena umetnost')).toBeTruthy();
  });
});
