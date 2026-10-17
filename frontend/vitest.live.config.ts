import { defineConfig } from 'vitest/config';
import base from './vitest.config';

export default defineConfig({
  ...base,
  test: {
    ...base.test,
    include: ['verification/**/*.live.test.tsx'],
    testTimeout: 15000,
    hookTimeout: 15000,
  },
});
