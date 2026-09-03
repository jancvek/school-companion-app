/**
 * En sam projekt (`jest-expo/android`) zadošča — univerzalni preset bi iste
 * teste pognal še za iOS in splet, brez dodatne informacije.
 */
module.exports = {
  preset: 'jest-expo/android',
  // Prvi test, ki izriše komponento, plača prevod React Native skozi Babel.
  // Ob hladnem predpomnilniku traja to čez deset sekund, zato privzetih 5 s
  // ni proračun za počasen test, ampak za prazen predpomnilnik. Na svežem
  // klonu (in v `scripts/verify.ps1`) bi zbirka brez tega padla.
  testTimeout: 60_000,
  // Samo `*.test.ts(x)`, da pomožne datoteke v `__tests__` niso videti kot
  // testi brez testov.
  testMatch: ['<rootDir>/__tests__/**/*.test.ts?(x)'],
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
  },
  collectCoverageFrom: ['src/**/*.{ts,tsx}', 'app/**/*.tsx'],
};
