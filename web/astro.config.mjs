import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig } from "astro/config";
import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";

// astro.config.mjs is evaluated before Vite injects `.env`.
// OCR_API_ORIGIN must match the address FastAPI actually binds (OCR_BIND_HOST).
function loadDotenv(path) {
  try {
    const env = {};
    for (const raw of readFileSync(path, "utf8").split("\n")) {
      const line = raw.trim();
      if (!line || line.startsWith("#")) continue;
      const eq = line.indexOf("=");
      if (eq === -1) continue;
      env[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
    }
    return env;
  } catch {
    return {};
  }
}

const fileEnv = loadDotenv(fileURLToPath(new URL("./.env", import.meta.url)));
const ocrApiOrigin =
  process.env.OCR_API_ORIGIN || fileEnv.OCR_API_ORIGIN || "http://127.0.0.1:8788";

export default defineConfig({
  integrations: [react()],
  server: {
    host: true,
    port: 4321,
  },
  vite: {
    plugins: [tailwindcss()],
    server: {
      host: true,
      allowedHosts: ["ocr.wyjsonw.com", ".wyjsonw.com"],
      proxy: {
        "/api/ocr": {
          target: ocrApiOrigin,
          changeOrigin: true,
          rewrite: () => "/v1/ocr",
        },
      },
    },
  },
});
