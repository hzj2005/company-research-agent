import { useState } from 'react';
import { Building2, Loader2, Search } from 'lucide-react';
import ExampleChips from './ExampleChips';

interface ResearchFormProps {
  onSubmit: (company: string) => Promise<void>;
  isResearching: boolean;
  /** 服务端没有可用模型 key 时禁用提交，避免点了必然失败 */
  blocked: boolean;
}

const ResearchForm = ({ onSubmit, isResearching, blocked }: ResearchFormProps) => {
  const [company, setCompany] = useState('');

  const start = async (value: string) => {
    const name = value.trim();
    if (!name || isResearching || blocked) return;
    await onSubmit(name);
  };

  const disabled = isResearching || blocked || !company.trim();

  return (
    <div>
      <div className="research-surface rounded-[18px] research-form">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void start(company);
          }}
        >
          <label htmlFor="companyName" className="field-label">
            公司名称
          </label>
          <div className="relative company-field">
            <Building2
              className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 z-10"
              stroke="#2677FF"
              strokeWidth={1.5}
              aria-hidden="true"
            />
            <input
              id="companyName"
              required
              type="text"
              autoComplete="off"
              value={company}
              onChange={(event) => setCompany(event.target.value)}
              className="research-input company-name-input"
              placeholder="输入公司名，例如 英伟达、Notion、字节跳动"
            />
          </div>

          <button type="submit" disabled={disabled} className="research-submit">
            <span className="flex items-center justify-center gap-2">
              {isResearching ? (
                <>
                  <Loader2 className="animate-spin h-5 w-5" stroke="#ffffff" strokeWidth={1.8} aria-hidden="true" />
                  <span className="text-sm font-medium">调研中…</span>
                </>
              ) : (
                <>
                  <Search className="h-4 w-4" strokeWidth={1.8} aria-hidden="true" />
                  <span className="text-sm font-medium">开始调研</span>
                </>
              )}
            </span>
          </button>
        </form>
      </div>

      <ExampleChips
        disabled={isResearching || blocked}
        onPick={(name) => {
          setCompany(name);
          void start(name);
        }}
      />
    </div>
  );
};

export default ResearchForm;
