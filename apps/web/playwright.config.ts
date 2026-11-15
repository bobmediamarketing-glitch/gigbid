import { defineConfig, devices } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

// The tests run against the production build served by FastAPI (one origin, like the deployment),
// with a fresh GigSim and fresh databases on their own ports, so they never touch dev data.
const ROOT = resolve(HERE, "../..");
const PY = process.env.PYTHON ?? (process.platform === "win32" ? join(ROOT, ".venv", "Scripts", "python.exe") : "python");
const DATA = join(HERE, "test-results", `e2e-data-${Date.now()}`);
mkdirSync(DATA, { recursive: true });
const GIGSIM_PORT = 8101;
const API_PORT = 8001;

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 120_000,
  expect: { timeout: 45_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: `http://localhost:${API_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      command: `"${PY}" -m uvicorn gigsim.app:app --port ${GIGSIM_PORT}`,
      cwd: ROOT,
      url: `http://localhost:${GIGSIM_PORT}/health`,
      env: { GIGSIM_STATE_FILE: join(DATA, "gigsim.json"), GIGSIM_ERROR_RATE: "0", GIGSIM_SPEED: "60" },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `"${PY}" -m uvicorn apps.api.main:app --port ${API_PORT}`,
      cwd: ROOT,
      url: `http://localhost:${API_PORT}/api/ping`,
      env: {
        GIGSIM_BASE_URL: `http://localhost:${GIGSIM_PORT}`,
        APP_DATABASE_URL: `sqlite:///${join(DATA, "app.sqlite")}`,
        DATABASE_URL: `sqlite:///${join(DATA, "checkpoints.sqlite")}`,
        MEMORY_DATABASE_URL: `sqlite:///${join(DATA, "memory.sqlite")}`,
        WORKSPACE_DIR: join(DATA, "workspace"),
        GIGBID_SYNC_INTERVAL_S: "5",
        GIGBID_OFFLINE: "1",
      },
      reuseExistingServer: false,
      timeout: 90_000,
    },
  ],
});

