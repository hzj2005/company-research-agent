import { useState, useEffect, useRef } from "react";
import { Header, ResearchStatus, ResearchReport, ResearchForm } from "./components";
import type { ResearchStatusType, ServerInfo } from "./types";
import { glassStyle } from "./styles";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

/**
 * 后端 SSE 只推三种事件：progress（带节点名）/ complete（整篇报告）/ error。
 * 上游那套 query_generating、curation、briefing_start、report_chunk 等
 * 在新图里从来不会发出，对应面板已一并删除。
 */
const NODE_LABELS: Record<string, string> = {
  grounding: "检索公开资料",
  research: "补搜证据不足的栏目",
  curate: "清洗与去重",
  evidence_check: "核对每个栏目的证据量",
  rewrite_query: "换措辞重试",
  degrade: "证据不足，按规则拒答",
  human_review: "等待人工复核",
  briefing: "生成报告",
};

function App() {
  const [company, setCompany] = useState("");
  const [isResearching, setIsResearching] = useState(false);
  const [status, setStatus] = useState<ResearchStatusType | null>(null);
  const [report, setReport] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isComplete, setIsComplete] = useState(false);
  const [isGeneratingPdf, setIsGeneratingPdf] = useState(false);
  const [isCopied, setIsCopied] = useState(false);
  const [server, setServer] = useState<ServerInfo | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/config`)
      .then((response) => (response.ok ? response.json() : null))
      .then(setServer)
      .catch(() => setServer(null));

    return () => {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
    };
  }, []);

  const mode = server?.app_mode ?? null;
  const isLive = mode === "live";

  // 服务端缺 key 时提前说清楚：之前界面上那两个 key 输入框是摆设，后端只读环境变量
  const missing: string[] = [];
  if (isLive && server?.requires_llm_key && !server.dashscope_configured
      && !server.openrouter_configured && !server.openai_configured) {
    missing.push("模型 key（DASHSCOPE_API_KEY）");
  }
  if (isLive && server?.tavily_configured === false) {
    missing.push("检索 key（TAVILY_API_KEY）");
  }
  const blocked = missing.length > 0;

  const streamResults = (jobId: string) => {
    const source = new EventSource(`${API_URL}/research/${jobId}/stream`);
    eventSourceRef.current = source;

    source.onmessage = (event) => {
      let data: {
        type?: string;
        step?: string;
        report?: string;
        error?: string;
      };
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }

      if (data.type === "progress" && data.step) {
        setStatus({
          step: NODE_LABELS[data.step] ?? data.step,
          message: `当前节点：${data.step}`,
        });
      } else if (data.type === "complete" && data.report) {
        setReport(data.report);
        setStatus({ step: "完成", message: "报告已生成" });
        setIsComplete(true);
        setIsResearching(false);
        source.close();
      } else if (data.type === "error") {
        setError(data.error || "调研失败");
        setIsResearching(false);
        source.close();
      }
    };

    source.onerror = () => {
      setError("与后端的连接中断；任务可能仍在后台运行");
      setIsResearching(false);
      source.close();
    };
  };

  const handleSubmit = async (name: string) => {
    setError(null);
    setReport("");
    setIsComplete(false);
    setIsResearching(true);
    setCompany(name);
    setStatus({ step: "准备中", message: "正在创建调研任务…" });

    eventSourceRef.current?.close();
    eventSourceRef.current = null;

    try {
      const response = await fetch(`${API_URL}/research`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company: name }),
      });
      if (!response.ok) throw new Error(`创建任务失败（HTTP ${response.status}）`);

      const data = await response.json();
      if (!data.job_id) throw new Error("后端没有返回 job_id");
      streamResults(data.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法发起调研");
      setStatus(null);
      setIsResearching(false);
    }
  };

  const handleCopy = async () => {
    if (!report) return;
    try {
      await navigator.clipboard.writeText(report);
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000);
    } catch {
      setError("复制失败，可手动选中报告文本");
    }
  };

  const handleGeneratePdf = async () => {
    if (!report || isGeneratingPdf) return;
    setIsGeneratingPdf(true);
    try {
      const response = await fetch(`${API_URL}/generate-pdf`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report_content: report, company_name: company || "research_report" }),
      });
      if (!response.ok) throw new Error(`导出失败（HTTP ${response.status}）`);

      const url = window.URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `${company || "research_report"}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导出 PDF 失败");
    } finally {
      setIsGeneratingPdf(false);
    }
  };

  return (
    <div className="app-shell">
      <div className="landscape-background" aria-hidden="true">
        <img src="/tavily-landscape.webp" alt="" />
        <div className="landscape-fade-top" />
        <div className="landscape-fade-bottom" />
      </div>

      <div className="research-workspace">
        <Header mode={mode} />

        {blocked && (
          <div className={`${glassStyle.card} notice-card`}>
            服务端缺少 {missing.join(" 和 ")}，现在点下去必然失败。启动后端前先设好环境变量，
            或直接用 <code>uv run python run_server.py</code> 启动（它会自动读取系统变量）。
          </div>
        )}

        <ResearchForm onSubmit={handleSubmit} isResearching={isResearching} blocked={blocked} />

        <ResearchStatus status={status} error={error} isComplete={isComplete} />

        {report && (
          <ResearchReport
            report={report}
            companyName={company}
            isGeneratingPdf={isGeneratingPdf}
            isCopied={isCopied}
            onCopyToClipboard={handleCopy}
            onGeneratePdf={handleGeneratePdf}
          />
        )}
      </div>
    </div>
  );
}

export default App;
