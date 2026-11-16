import { useState } from 'react';
import { CheckCircle2, XCircle, Loader2, UserCheck, ChevronDown, ChevronRight, ExternalLink } from 'lucide-react';
import type { ReviewPayload, ReviewEvidenceItem } from '../types';
import { glassStyle } from '../styles';

interface ReviewPanelProps {
  payload: ReviewPayload;
  isSubmitting: boolean;
  onSubmit: (approved: boolean, rejectedSections: string[], note: string) => void;
}

/**
 * 栏目 key → 中文标题。必须与 config/settings.yaml 里的栏目名一致，
 * 否则勾选框里写「公司概览」、报告里写「公司概况」，用户会以为不是同一个栏目。
 */
const SECTION_LABELS: Record<string, string> = {
  company: '公司概况',
  industry: '行业概况',
  financial: '财务概况',
  news: '新闻动态',
};

const EvidenceList = ({ items }: { items: ReviewEvidenceItem[] }) => {
  if (!items.length) {
    return <p className="text-xs text-gray-500 mt-1">本栏目没有可用证据</p>;
  }
  return (
    <ul className="mt-2 space-y-2">
      {items.map((item, idx) => (
        <li key={`${item.url}-${idx}`} className="text-xs leading-relaxed">
          <div className="flex items-start gap-1.5">
            {item.url ? (
              <a
                href={item.url}
                target="_blank"
                rel="noreferrer"
                className="font-medium text-[#2677FF] hover:underline flex items-center gap-1 min-w-0"
              >
                <span className="truncate">{item.title || item.url}</span>
                <ExternalLink className="h-3 w-3 flex-shrink-0" strokeWidth={1.8} aria-hidden="true" />
              </a>
            ) : (
              <span className="font-medium text-gray-700 truncate">{item.title || "（无标题）"}</span>
            )}
            <span className="flex-shrink-0 text-gray-400">相关度 {item.score.toFixed(2)}</span>
          </div>
          {item.snippet && (
            <p className="text-gray-600 mt-0.5 line-clamp-3">{item.snippet}</p>
          )}
        </li>
      ))}
    </ul>
  );
};

/**
 * HITL 成稿前的人工复核面板。只在后端开了 `human_review` 且不自动批准时，
 * 由 SSE 的 `review_required` 事件触发。默认链路（开关关）永远不会出现。
 *
 * 面板必须给出**可判断的依据**：每栏列出实际检索到的证据（标题/来源/摘录），
 * 否则复核人只能看到一个引用总数，既定不了该不该批，也定不了拒答哪一栏。
 */
const ReviewPanel = ({ payload, isSubmitting, onSubmit }: ReviewPanelProps) => {
  const [rejected, setRejected] = useState<Set<string>>(new Set());
  const [note, setNote] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (section: string) => {
    setRejected((prev) => {
      const next = new Set(prev);
      if (next.has(section)) next.delete(section);
      else next.add(section);
      return next;
    });
  };

  const toggleExpand = (section: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(section)) next.delete(section);
      else next.add(section);
      return next;
    });
  };

  const degraded = new Set(payload.degraded_sections ?? []);
  const evidence = payload.evidence ?? {};
  const allRejected = rejected.size === payload.sections.length;
  const submitApprove = () => onSubmit(true, Array.from(rejected), note);
  const submitRejectAll = () => onSubmit(false, [], note);

  return (
    <div className={`${glassStyle.card} font-sans`}>
      <div className="flex items-center gap-3 mb-4">
        <div className="flex-shrink-0 p-2 rounded-full border bg-[#2677FF]/10 border-[#2677FF]/20">
          <UserCheck className="h-5 w-5 text-[#2677FF]" strokeWidth={1.6} aria-hidden="true" />
        </div>
        <div>
          <p className="font-medium text-gray-900/90">人工复核成稿</p>
          <p className="text-sm text-gray-600">
            {payload.company} · 共检索 {payload.reference_count} 条引用
          </p>
        </div>
      </div>

      <p className="text-sm text-gray-700 mb-3">
        先看每栏的证据，再决定批准出稿、还是把证据不足的栏目勾掉（勾选项会用「未找到公开依据」代替正文）。
      </p>

      <div className="space-y-2 mb-4">
        {payload.sections.map((section) => {
          const items = evidence[section] ?? [];
          const isDegraded = degraded.has(section);
          const isRejected = rejected.has(section);
          const open = expanded.has(section);
          return (
            <div
              key={section}
              className={`rounded-xl border px-3 py-2 ${
                isRejected
                  ? 'border-[#FE363B]/40 bg-[#FE363B]/10'
                  : 'border-gray-200 bg-white/60'
              }`}
            >
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => toggle(section)}
                  className="flex items-center gap-2 text-sm font-medium flex-1 min-w-0 text-left"
                >
                  <span
                    className={`h-4 w-4 rounded border flex-shrink-0 ${
                      isRejected
                        ? 'border-[#FE363B] bg-[#FE363B]/20'
                        : 'border-gray-300'
                    }`}
                  />
                  <span className={isRejected ? 'text-[#FE363B]' : 'text-gray-800'}>
                    {SECTION_LABELS[section] ?? section}
                  </span>
                  {isDegraded && (
                    <span className="text-xs text-gray-500">（已因证据不足拒答）</span>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => toggleExpand(section)}
                  className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800 flex-shrink-0"
                >
                  {items.length} 条证据
                  {open ? (
                    <ChevronDown className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                  )}
                </button>
              </div>
              {open && <EvidenceList items={items} />}
            </div>
          );
        })}
      </div>

      <textarea
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="复核备注（可选）"
        className="research-input w-full mb-4 resize-none"
        rows={2}
        maxLength={300}
      />

      <div className="flex flex-col sm:flex-row gap-2">
        <button
          type="button"
          onClick={submitApprove}
          disabled={isSubmitting}
          className="research-submit flex-1"
        >
          <span className="flex items-center justify-center gap-2">
            {isSubmitting ? (
              <Loader2 className="animate-spin h-5 w-5" stroke="#ffffff" strokeWidth={1.8} aria-hidden="true" />
            ) : (
              <CheckCircle2 className="h-4 w-4" strokeWidth={1.8} aria-hidden="true" />
            )}
            <span className="text-sm font-medium">
              {allRejected && rejected.size > 0 ? '确认拒答所选栏目' : '批准出稿'}
            </span>
          </span>
        </button>
        <button
          type="button"
          onClick={submitRejectAll}
          disabled={isSubmitting}
          className="flex items-center justify-center gap-2 rounded-xl border border-[#FE363B]/30 bg-[#FE363B]/10 px-4 py-2 text-[#FE363B] hover:bg-[#FE363B]/20 disabled:opacity-50"
        >
          <XCircle className="h-4 w-4" strokeWidth={1.8} aria-hidden="true" />
          <span className="text-sm font-medium">整体拒答</span>
        </button>
      </div>
    </div>
  );
};

export default ReviewPanel;
