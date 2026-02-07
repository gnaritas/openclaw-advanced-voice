export default {
  testEnvironment: 'node',
  transform: {},
  testMatch: ['**/__tests__/**/*.test.js', '**/*.test.js'],
  collectCoverageFrom: ['index.js'],
  coveragePathIgnorePatterns: ['/node_modules/', '/.git/', '/__tests__/'],
};
