/**
 * Expo sicer zna delati brez te datoteke, jest-expo pa ne — brez nje Babel
 * ne zna prebrati Flow tipov v `@react-native/jest-preset`.
 */
module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
  };
};
