export type ResearchStatusType = {
  step: string;
  message: string;
};

export type ResearchOutput = {
  summary: string;
  details: {
    report: string;
  };
};

export type GlassStyle = {
  base: string;
  card: string;
  input: string;
};

export type AnimationStyle = {
  fadeIn: string;
  writing: string;
};

/** 后端 /config 暴露的少量状态：只用来决定「显示哪个模式标签」和「要不要提示缺 key」 */
export type ServerInfo = {
  app_mode?: 'fixture' | 'live';
  requires_llm_key?: boolean;
  dashscope_configured?: boolean;
  openrouter_configured?: boolean;
  openai_configured?: boolean;
  tavily_configured?: boolean;
};
