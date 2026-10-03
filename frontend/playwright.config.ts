import { defineConfig, devices } from '@playwright/test';

// 端到端测试对真实后端运行，不使用桩服务。
// 使用地址需与后端 cors_origins 中的来源一致，否则浏览器会拒绝请求。
const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:5173';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      // 使用系统已安装的浏览器，无需另行下载。
      name: 'chrome',
      use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    },
  ],
});