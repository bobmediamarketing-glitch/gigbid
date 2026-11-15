import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev the API runs on :8000; proxying keeps everything same-origin, so the session cookie
// and Server-Sent Events work exactly as in production (where FastAPI serves the built app).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.API_URL ?? "http://localhost:8000", changeOrigin: false } },
  },
  build: { outDir: "dist", sourcemap: true },
});
