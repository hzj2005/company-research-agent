import { useState } from 'react';
import { CheckCircle2, XCircle, Loader2, UserCheck } from 'lucide-react';
import type { ReviewPayload } from '../types';
import { glassStyle } from '../styles';

interface ReviewPanelProps {
  payload: ReviewPayload;
  isSubmitting: boolean;
  onSubmit: (approved: boolean, rejectedSections: string[], note: string) => void;
}

const SECTION_LABELS: Record<string, string> = {
  company: '公司概览',
  industry: '行业',
  financial: '财务',
  news: '新闻动态',
};

/**
 * HITL 成稿前的人工复核面板。只在后端开了 `human_review` 且不自动批准时，
 * 由 SSE 的 `review_required` 事件触发。默认链路（开关关）永远不会出现。
 */
const ReviewPanel = ({ payload, isSubmitting, onSubmit }: ReviewPanelProps) => {
  const [rejected, setRejected] = useState<Set<string>>(new Set());
  const [note, setNote] = useState('');

  const toggle = (section: string) => {
    setRejected((prev) => {
      const next = new Set(prev);
      if (next.has(section)) next.delete(section);
      else next.add(section);
      return next;
    });
  };

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
            {payload.company} · 已检索 {payload.reference_count} 条引用
          </p>
        </div>
      </div>

      <p className="text-sm text-gray-700 mb-3">
        批准后立即生成报告；也可以勾选要拒答的栏目（勾选项会用「未找到公开依据」代替正文）。
      </p>

      <div className="grid grid-cols-2 gap-2 mb-4">
        {payload.sections.map((section) => (
          <button
            key={section}
            type="button"
            onClick={() => toggle(section)}
            className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-sm transition-colors ${
              rejected.has(section)
                ? 'border-[#FE363B]/40 bg-[#FE363B]/10 text-[#FE363B]'
                : 'border-gray-200 bg-white/60 text-gray-700 hover:border-[#2677FF]/40'
            }`}
          >
            <span
              className={`h-4 w-4 rounded border ${
                rejected.has(section)
                  ? 'border-[#FE363B] bg-[#FE363B]/20'
                  : 'border-gray-300'
              }`}
            />
            {SECTION_LABELS[section] ?? section}
          </button>
        ))}
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
