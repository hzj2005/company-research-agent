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

/** 复核面板里单条证据的摘要：够判断「证据够不够」，不必把全文塞进 SSE */
export type ReviewEvidenceItem = {
  title: string;
  url: string;
  score: number;
  snippet: string;
};

/** HITL 人工复核时后端通过 SSE review_required 事件推给前端的决策上下文 */
export type ReviewPayload = {
  prompt: string;
  company: string;
  sections: string[];
  reference_count: number;
  degraded_sections: string[];
  /** 按栏目分组的证据摘要：没有它就只是盲批 */
  evidence?: Record<string, ReviewEvidenceItem[]>;
  decision_schema?: Record<string, string>;
};

/** 提交给 POST /research/{id}/review 的决策 */
export type ReviewDecision = {
  approved: boolean;
  rejected_sections: string[];
  note: string;
};

/** 历史结果里的一条证据（含正文原文） */
export type HistoryEvidence = {
  url: string;
  section: string;
  title: string;
  score: number;
  content: string;
  truncated: boolean;
};

/** 该公司之前某一次调研的完整结果 */
export type HistoryEntry = {
  job_id: string;
  company: string;
  status: string;
  created_at: string;
  report: string;
  report_chars: number;
  evidence_count: number;
  evidence?: HistoryEvidence[];
};

/** GET /research/history 的返回 */
export type HistoryResponse = {
  source: string;
  company: string;
  matches: HistoryEntry[];
};
