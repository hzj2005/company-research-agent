import { useEffect, useRef, useState } from 'react';
import { Loader2, Send } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { glassStyle } from '../styles';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const SECTION_LABELS: Record<string, string> = {
  company: '公司概况',
  industry: '行业竞争',
  financial: '财务融资',
  news: '新闻动态',
};

const NODE_LABELS: Record<string, string> = {
  grounding: '准备检索',
  route: '判断你想看什么',
  research: '并行调研选中的栏目',
  briefing: '拼装报告并编号',
  human_review: '等待人工复核',
};

type ClarifyOption = { key: string; label: string };

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  text?: string;
  report?: string;
  company?: string;
  sections?: string[];
  options?: ClarifyOption[];
  status?: 'running' | 'done' | 'error';
  jobId?: string;
};

interface ChatPanelProps {
  /** 服务端缺 key 时禁用发送，避免点了必然失败 */
  blocked: boolean;
}

/**
 * 对话式调研：一句话 → 后端判定公司与栏目 → 只跑选中的子图。
 *
 * 两种回复：
 * - clarify：追问（缺公司或没给范围），**不建任务、不花检索额度**，并给可点选项；
 * - accepted：任务已建，开 SSE 看进度，完成后把报告作为一条消息追加。
 */
const ChatPanel = ({ blocked }: ChatPanelProps) => {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'hello',
      role: 'assistant',
      text: '告诉我你想了解哪家公司、想看哪几块（公司概况 / 行业竞争 / 财务融资 / 新闻动态），我就只查这几块。',
    },
  ]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [threadId, setThreadId] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  useEffect(() => () => sourceRef.current?.close(), []);

  const patch = (id: string, next: Partial<ChatMessage>) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...next } : m)));
  };

  const stream = (jobId: string, messageId: string) => {
    sourceRef.current?.close();
    const source = new EventSource(`${API_URL}/research/${jobId}/stream`);
    sourceRef.current = source;

    source.onmessage = (event) => {
      let data: { type?: string; step?: string; report?: string; error?: string };
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      if (data.type === 'progress' && data.step) {
        patch(messageId, { text: `正在：${NODE_LABELS[data.step] ?? data.step}…` });
      } else if (data.type === 'complete' && data.report) {
        patch(messageId, { report: data.report, text: undefined, status: 'done' });
        setBusy(false);
        source.close();
      } else if (data.type === 'error') {
        patch(messageId, { text: data.error || '调研失败', status: 'error' });
        setBusy(false);
        source.close();
      }
    };

    source.onerror = () => {
      patch(messageId, { text: '与后端的连接中断；任务可能仍在后台运行', status: 'error' });
      setBusy(false);
      source.close();
    };
  };

  const send = async (raw: string) => {
    const text = raw.trim();
    if (!text || busy || blocked) return;

    const assistantId = `a-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { id: `u-${Date.now()}`, role: 'user', text },
      { id: assistantId, role: 'assistant', text: '正在判断范围…', status: 'running' },
    ]);
    setInput('');
    setBusy(true);

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, thread_id: threadId }),
      });
      if (!response.ok) throw new Error(`请求失败（HTTP ${response.status}）`);
      const data = await response.json();
      if (data.thread_id) setThreadId(data.thread_id);

      if (data.type === 'clarify') {
        patch(assistantId, {
          text: data.question || '能说得再具体一点吗？',
          options: data.options ?? [],
          status: 'done',
        });
        setBusy(false);
        return;
      }

      const sections: string[] = data.sections ?? [];
      const scope = sections.map((s) => SECTION_LABELS[s] ?? s).join('、');
      patch(assistantId, {
        text: `好，本次范围：${scope || '全部栏目'}。正在调研…`,
        company: data.company,
        sections,
        jobId: data.job_id,
      });
      if (data.job_id) stream(data.job_id, assistantId);
    } catch (err) {
      patch(assistantId, {
        text: err instanceof Error ? err.message : '发起调研失败',
        status: 'error',
      });
      setBusy(false);
    }
  };

  const disabled = busy || blocked || !input.trim();

  return (
    <div className={`${glassStyle.card} flex flex-col gap-4`}>
      <div className="flex max-h-[62vh] flex-col gap-3 overflow-y-auto pr-1">
        {messages.map((message) => {
          const mine = message.role === 'user';
          return (
            <div key={message.id} className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[86%] rounded-[14px] px-4 py-3 text-sm leading-relaxed ${
                  mine
                    ? 'bg-[#2677FF] text-white'
                    : 'bg-white/75 text-slate-800 ring-1 ring-slate-200/70'
                }`}
              >
                {message.text && <p className="whitespace-pre-wrap">{message.text}</p>}

                {message.sections && message.sections.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {message.sections.map((section) => (
                      <span
                        key={section}
                        className="rounded-full bg-[#EAF1FE] px-2.5 py-0.5 text-xs text-[#1F5FCC]"
                      >
                        {SECTION_LABELS[section] ?? section}
                      </span>
                    ))}
                  </div>
                )}

                {message.options && message.options.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {message.options.map((option) => (
                      <button
                        key={option.key}
                        type="button"
                        disabled={busy}
                        onClick={() => void send(option.key === 'all' ? '全都要' : option.label)}
                        className="rounded-full border border-[#BFD5FF] bg-white px-3 py-1 text-xs text-[#1F5FCC] transition hover:bg-[#EAF1FE] disabled:opacity-50"
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                )}

                {message.report && (
                  <div className="prose prose-sm mt-1 max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.report}</ReactMarkdown>
                  </div>
                )}

                {message.status === 'running' && (
                  <span className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                    稍候，正在跑选中的栏目
                  </span>
                )}

                {message.status === 'done' &&
                  message.sections &&
                  message.sections.length > 0 &&
                  message.sections.length < 4 && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void send('全部都要')}
                      className="mt-3 rounded-full border border-[#BFD5FF] bg-white px-3 py-1 text-xs text-[#1F5FCC] transition hover:bg-[#EAF1FE] disabled:opacity-50"
                    >
                      补全其余栏目
                    </button>
                  )}
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      <form
        className="flex items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void send(input);
        }}
      >
        <textarea
          rows={2}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              void send(input);
            }
          }}
          placeholder="例如：帮我看看 Notion 的融资和最近新闻"
          className={`${glassStyle.input} flex-1 resize-none`}
          disabled={blocked}
        />
        <button type="submit" disabled={disabled} className="research-submit">
          <span className="flex items-center justify-center gap-2">
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" stroke="#ffffff" strokeWidth={1.8} aria-hidden="true" />
            ) : (
              <Send className="h-4 w-4" strokeWidth={1.8} aria-hidden="true" />
            )}
            <span className="text-sm font-medium">发送</span>
          </span>
        </button>
      </form>
    </div>
  );
};

export default ChatPanel;
