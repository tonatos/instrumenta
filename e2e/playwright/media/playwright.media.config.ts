import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

/** Logical UI size (layout). */
const VIEWPORT = { width: 1366, height: 1024 };

export default defineConfig({
  testDir: "./",
  testMatch: "record-tour.spec.ts",
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  timeout: 300_000,
  use: {
    baseURL: process.env.BASE_URL || "http://localhost:5173",
    viewport: VIEWPORT,
    // Retina framebuffer — CDP screencast captures device pixels.
    deviceScaleFactor: 2,
    trace: "off",
    // Built-in Playwright video is soft VP8; HQ path uses CDP JPEG → ffmpeg.
    video: "off",
    launchOptions: {
      args: [
        "--disable-dev-shm-usage",
        "--font-render-hinting=none",
        "--enable-font-antialiasing",
      ],
    },
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: VIEWPORT,
        deviceScaleFactor: 2,
      },
    },
  ],
  outputDir: path.join(__dirname, "test-results"),
  webServer: process.env.CI
    ? undefined
    : [
        {
          command: "cd ../../backend && go run ./cmd/api",
          url: "http://localhost:8000/health",
          reuseExistingServer: true,
          timeout: 120_000,
        },
        {
          command: "cd ../../frontend && npm run dev",
          url: "http://localhost:5173",
          reuseExistingServer: true,
          timeout: 120_000,
        },
      ],
});
