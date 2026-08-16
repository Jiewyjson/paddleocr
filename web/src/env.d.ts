/// <reference types="astro/client" />

interface ImportMetaEnv {
  readonly PUBLIC_OCR_ENDPOINT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
