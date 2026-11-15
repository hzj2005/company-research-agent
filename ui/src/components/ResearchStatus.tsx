import { Loader2, CheckCircle2, XCircle } from 'lucide-react';
import type { ResearchStatusType } from '../types';

interface ResearchStatusProps {
  status: ResearchStatusType | null;
  error: string | null;
  isComplete: boolean;
}

const ResearchStatus = ({ status, error, isComplete }: ResearchStatusProps) => {
  if (!status && !error) return null;

  const tone = error ? 'error' : isComplete ? 'done' : 'running';
  const ring = {
    error: 'bg-[#FE363B]/10 border-[#FE363B]/20',
    done: 'bg-[#22C55E]/10 border-[#22C55E]/20',
    running: 'bg-[#2677FF]/10 border-[#2677FF]/20'
  }[tone];

  const title = error ? '出错了' : isComplete ? '完成' : status?.step ?? '进行中';
  const detail = error ?? status?.message ?? '';

  return (
    <div className="research-surface rounded-2xl p-5 font-sans">
      <div className="flex items-center gap-4">
        <div className={`flex-shrink-0 p-2 rounded-full border ${ring}`}>
          {error ? (
            <XCircle className="h-5 w-5 text-[#FE363B]" strokeWidth={1.6} aria-hidden="true" />
          ) : isComplete ? (
            <CheckCircle2 className="h-5 w-5 text-[#22C55E]" strokeWidth={1.6} aria-hidden="true" />
          ) : (
            <Loader2 className="h-5 w-5 animate-spin text-[#2677FF]" strokeWidth={1.6} aria-hidden="true" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-medium text-gray-900/90">{title}</p>
          {detail && <p className="text-sm text-gray-600 whitespace-pre-wrap">{detail}</p>}
        </div>
      </div>
    </div>
  );
};

export default ResearchStatus;
