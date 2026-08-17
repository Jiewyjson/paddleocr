import { defineConfig } from "astro/config";
import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";

const ocrApiOrigin = process.env.OCR_API_ORIGIN || "http://192.168.5.24:8788";

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
