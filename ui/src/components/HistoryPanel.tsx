import { useState } from 'react';
import { History, ExternalLink, ChevronDown, ChevronRight, Loader2, RefreshCw, Clock } from 'lucide-react';
import type { HistoryEntry } from '../types';
import { glassStyle } from '../styles';

interface HistoryPanelProps {
  company: string;
  entries: HistoryEntry[];
  isLoading: boolean;
  /** 「在线重新查询」：点了才真去跑一次新的调研 */
  onRefresh: () => void;
  isRefreshing: boolean;
}

const SECTION_LABELS: Record<string, string> = {
  company: '公司概况',
  industry: '行业概况',
  financial: '财务概况',
  news: '新闻动态',
};

const daysAgo = (iso: string): string => {
  const then = new Date(iso).getTime();
  if (!then) return '';
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (days <= 0) return '今天';
  if (days === 1) return '昨天';
  return `${days} 天前`;
};

const EntryCard = ({ entry }: { entry: HistoryEntry }) => {
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);
  const [showReport, setShowReport] = useState(false);

  const grouped: Record<string, typeof entry.evidence> = {};
  (entry.evidence ?? []).forEach((item) => {
    const key = item.section;
    grouped[key] = grouped[key] ?? [];
    grouped[key]!.push(item);
  });

  return (
    <div className="rounded-xl border border-gray-200 bg-white/70 p-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-medium text-gray-800 text-sm truncate">{entry.company}</span>
          <span className="text-xs text-gray-500 flex items-center gap-1 flex-shrink-0">
            <Clock className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
            {daysAgo(entry.created_at)}
          </span>
        </div>
        <span className="text-xs text-gray-500 flex-shrink-0">
          报告 {entry.report_chars} 字符 · 证据 {entry.evidence_count} 条
        </span>
      </div>

      <button
        type="button"
        onClick={() => setShowReport((v) => !v)}
        className="mt-2 flex items-center gap-1 text-xs text-[#2677FF] hover:underline"
      >
        {showReport ? (
          <ChevronDown className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
        )}
        {showReport ? '收起报告' : '展开报告全文'}
      </button>

      {showReport && (
        <div className="mt-2 rounded-lg bg-gray-50 border border-gray-100 p-3 max-h-96 overflow-auto">
          <pre className="text-xs leading-relaxed text-gray-700 whitespace-pre-wrap font-sans">
            {entry.report}
          </pre>
        </div>
      )}

      {Object.keys(grouped).length > 0 && (
        <div className="mt-2 space-y-1">
          {Object.entries(grouped).map(([section, items]) => (
            <div key={section}>
              <button
                type="button"
                onClick={() => setOpenEvidence(openEvidence === section ? null : section)}
                className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-900"
              >
                {openEvidence === section ? (
                  <ChevronDown className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                )}
                {SECTION_LABELS[section] ?? section} · {items?.length ?? 0} 条原文
              </button>
              {openEvidence === section && (
                <ul className="mt-1 ml-4 space-y-2">
                  {(items ?? []).map((item) => (
                    <li key={item.url} className="text-xs leading-relaxed">
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
                          <span className="font-medium text-gray-700 truncate">{item.title}</span>
                        )}
                        <span className="flex-shrink-0 text-gray-400">相关度 {item.score.toFixed(2)}</span>
                      </div>
                      {item.content && (
                        <p className="text-gray-600 mt-0.5 whitespace-pre-wrap break-words">
                          {item.content.length > 600 ? item.content.slice(0, 600) + '…' : item.content}
                        </p>
                      )}
                      {item.truncated && (
                        <p className="text-amber-600 mt-0.5">（原文过长，已截断保存）</p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

/**
 * 历史结果面板：搜同一个公司时先把上次查到的内容摆出来，再问要不要重新联网查。
 * 目的很实际——重复调研会白烧检索额度，而多数时候旧结果已经够用。
 */
const HistoryPanel = ({
  company,
  entries,
  isLoading,
  onRefresh,
  isRefreshing,
}: HistoryPanelProps) => {
  const latest = entries[0];
  const staleDays = latest ? Math.floor((Date.now() - new Date(latest.created_at).getTime()) / 86_400_000) : 0;

  return (
    <div className={`${glassStyle.card} font-sans`}>
      <div className="flex items-center gap-3 mb-3">
        <div className="flex-shrink-0 p-2 rounded-full border bg-[#2677FF]/10 border-[#2677FF]/20">
          <History className="h-5 w-5 text-[#2677FF]" strokeWidth={1.6} aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <p className="font-medium text-gray-900/90">找到 {company} 的历史调研结果</p>
          <p className="text-sm text-gray-600">
            {isLoading
              ? '正在读取…'
              : `共 ${entries.length} 次记录，最近一次是 ${daysAgo(latest?.created_at ?? '')}`}
          </p>
        </div>
      </div>

      {!isLoading && entries.length === 0 && (
        <p className="text-sm text-gray-600">没有查到历史结果，需要联网查询一次。</p>
      )}

      {entries.length > 0 && (
        <div className="space-y-2 mb-4">
          {entries.map((entry) => (
            <EntryCard key={entry.job_id} entry={entry} />
          ))}
        </div>
      )}

      <div className="flex flex-col sm:flex-row gap-2">
        <button
          type="button"
          onClick={onRefresh}
          disabled={isRefreshing || isLoading}
          className="research-submit flex-1"
        >
          <span className="flex items-center justify-center gap-2">
            {isRefreshing ? (
              <Loader2 className="animate-spin h-5 w-5" stroke="#ffffff" strokeWidth={1.8} aria-hidden="true" />
            ) : (
              <RefreshCw className="h-4 w-4" strokeWidth={1.8} aria-hidden="true" />
            )}
            <span className="text-sm font-medium">
              {isRefreshing ? '正在在线查询…' : '需要最新数据？在线重新查询'}
            </span>
          </span>
        </button>
      </div>

      {staleDays >= 30 && (
        <p className="mt-2 text-xs text-amber-700">
          最近一次记录是 {staleDays} 天前的，内容可能已经过时。
        </p>
      )}
    </div>
  );
};

export default HistoryPanel;
