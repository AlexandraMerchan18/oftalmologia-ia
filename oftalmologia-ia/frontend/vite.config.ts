/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo (npm run dev) /api se redirige al backend local.
// En Docker no se usa: nginx sirve el build y hace el proxy (ver nginx.conf).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
