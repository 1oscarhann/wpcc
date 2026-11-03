import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev the API runs on :8000 and is proxied, so the browser sees one origin (same-site cookies).
const API = process.env.HF_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: "127.0.0.1",
    proxy: {
      "/api": { target: API, changeOrigin: false },
      "/ws": { target: API.replace(/^http/, "ws"), ws: true },
    },
  },
  preview: { port: 4173 },
  build: { target: "es2022", sourcemap: true, assetsInlineLimit: 0 },
  test: { environment: "jsdom", include: ["tests/unit/**/*.test.ts"] },
});
