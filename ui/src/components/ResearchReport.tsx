import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Check, Copy, Download, Loader2 } from 'lucide-react';
import { glassStyle, fadeInAnimation } from '../styles';

interface ResearchReportProps {
  report: string;
  companyName: string;
  isGeneratingPdf: boolean;
  isCopied: boolean;
  onCopyToClipboard: () => void;
  onGeneratePdf: () => void;
}

const ResearchReport = ({
  report,
  companyName,
  isGeneratingPdf,
  isCopied,
  onCopyToClipboard,
  onGeneratePdf
}: ResearchReportProps) => {
  if (!report) return null;

  return (
    <div className={`${glassStyle.card} ${fadeInAnimation.fadeIn} font-sans`}>
      <div className="flex items-center justify-between gap-3 mb-4">
        <p className="text-sm text-gray-600 truncate">{companyName}</p>
        <div className="flex gap-2">
          <button
            onClick={onCopyToClipboard}
            aria-label={isCopied ? '已复制' : '复制报告'}
            title={isCopied ? '已复制' : '复制报告'}
            className="report-action"
          >
            {isCopied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          </button>
          <button
            onClick={onGeneratePdf}
            disabled={isGeneratingPdf}
            title="导出 PDF"
            className="report-action disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isGeneratingPdf ? (
              <Loader2 className="animate-spin h-4 w-4" aria-hidden="true" />
            ) : (
              <Download className="h-4 w-4" aria-hidden="true" />
            )}
          </button>
        </div>
      </div>

      <div className="report-content">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            h1: ({ children, ...props }) => {
              const isReferences = String(children).includes('References');
              return (
                <>
                  {isReferences && (
                    <div className="h-[1px] w-full bg-gradient-to-r from-transparent via-gray-300 to-transparent my-8" />
                  )}
                  <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 mt-4 mb-6 break-words" {...props}>
                    {children}
                  </h1>
                </>
              );
            },
            h2: (props) => (
              <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-4 pb-2 border-b border-gray-200" {...props} />
            ),
            h3: (props) => <h3 className="text-lg font-semibold text-gray-900 mt-6 mb-3" {...props} />,
            ul: (props) => <ul className="text-gray-800 space-y-1.5 list-disc pl-6 my-2" {...props} />,
            ol: (props) => <ol className="text-gray-800 space-y-1 list-decimal pl-6 my-2" {...props} />,
            li: (props) => <li className="text-gray-800" {...props} />,
            p: (props) => <p className="text-gray-800 my-2" {...props} />,
            a: ({ href, ...props }) => (
              <a
                href={href}
                className="text-[#2677FF] hover:text-[#8FBCFA] underline decoration-[#2677FF] break-all"
                target="_blank"
                rel="noopener noreferrer"
                {...props}
              />
            )
          }}
        >
          {report}
        </ReactMarkdown>
      </div>
    </div>
  );
};

export default ResearchReport;
