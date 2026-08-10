/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_API_KEY: string;
  readonly VITE_USER_EXTERNAL_ID: string;
  readonly VITE_USER_EMAIL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
