import { useCallback, useEffect, useState } from 'react';

export interface LLMSettings {
  openrouterApiKey: string;
  model: string;
}

export interface ServerConfig {
  // 后端运行模式：fixture 用本地语料 + stub，不需要任何 key；live 才需要
  app_mode?: 'fixture' | 'live';
  requires_llm_key?: boolean;
  openrouter_configured: boolean;
  openai_configured: boolean;
  dashscope_configured?: boolean;
  tavily_configured?: boolean;
  default_model: string;
}

const STORAGE_KEY = 'company-research:llm-settings';

const readStoredSettings = (): Partial<LLMSettings> => {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}');
  } catch {
    return {};
  }
};

// Settings live only in this browser's localStorage and are sent with each research request
export const useLLMSettings = () => {
  const [settings, setSettings] = useState<LLMSettings>(() => ({
    openrouterApiKey: '',
    model: '',
    ...readStoredSettings(),
  }));

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {
      // Storage unavailable (private mode etc.) — settings still work for this session
    }
  }, [settings]);

  const updateSettings = useCallback((patch: Partial<LLMSettings>) => {
    setSettings((previous) => ({ ...previous, ...patch }));
  }, []);

  return [settings, updateSettings] as const;
};
