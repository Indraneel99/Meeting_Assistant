import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { ApiConfig } from "../api/types";

const STORAGE_KEY = "meeting-assistant-config";

function loadConfig(): ApiConfig {
  const defaults: ApiConfig = {
    baseUrl: import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000",
    accessToken: "",
    userExternalId: import.meta.env.VITE_USER_EXTERNAL_ID || "dev-user",
    userEmail: import.meta.env.VITE_USER_EMAIL || "dev@example.com",
  };

  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored) as Partial<ApiConfig> & { apiKey?: string };
      return {
        ...defaults,
        ...parsed,
        accessToken: parsed.accessToken || "",
      };
    }
  } catch {
    // ignore invalid stored config
  }
  return defaults;
}

interface ConfigContextValue {
  config: ApiConfig;
  updateConfig: (patch: Partial<ApiConfig>) => void;
  clearSession: () => void;
  isAuthenticated: boolean;
}

const ConfigContext = createContext<ConfigContextValue | null>(null);

export function ConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<ApiConfig>(loadConfig);

  const value = useMemo(
    () => ({
      config,
      isAuthenticated: Boolean(config.accessToken),
      updateConfig: (patch: Partial<ApiConfig>) => {
        setConfig((current) => {
          const next = { ...current, ...patch };
          localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
          return next;
        });
      },
      clearSession: () => {
        setConfig((current) => {
          const next = { ...current, accessToken: "" };
          localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
          return next;
        });
      },
    }),
    [config],
  );

  return <ConfigContext.Provider value={value}>{children}</ConfigContext.Provider>;
}

export function useConfig() {
  const context = useContext(ConfigContext);
  if (!context) {
    throw new Error("useConfig must be used within ConfigProvider");
  }
  return context;
}
