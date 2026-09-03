/**
 * Testi pokrivajo samo logiko (predmeti, baza, shranjevanje, stanje kamere),
 * zato en sam projekt (`jest-expo/android`) zadošča — univerzalni preset bi
 * iste teste pognal še za iOS in splet, brez dodatne informacije.
 */
module.exports = {
  preset: 'jest-expo/android',
  // Samo `*.test.ts(x)`, da pomožne datoteke v `__tests__` niso videti kot
  // testi brez testov.
  testMatch: ['<rootDir>/__tests__/**/*.test.ts?(x)'],
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
  },
  collectCoverageFrom: ['src/**/*.{ts,tsx}', 'app/**/*.tsx'],
};
