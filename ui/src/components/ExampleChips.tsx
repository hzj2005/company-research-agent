/**
 * 首页默认可选的公司。全部写死在这里，只用于「点一下就填进去」，
 * 不再是上游那套「填 url / 总部 / 行业」的表单——后端只消费公司名。
 */
export const EXAMPLE_COMPANIES = [
  'Stripe',
  'Shopify',
  'Notion',
  'Tesla',
  'Airbnb',
  'Slack',
  'Spotify',
  'Microsoft',
  'Apple',
  'Amazon',
  'Google',
  'Netflix',
  'Meta',
  'Nvidia',
  'Adobe',
  'Figma',
  'Zoom',
  'Salesforce',
  'Uber',
  'Coinbase',
  'Datadog',
  'Snowflake',
  'Canva',
  'Atlassian',
];

interface ExampleChipsProps {
  disabled: boolean;
  onPick: (company: string) => void;
}

const ExampleChips = ({ disabled, onPick }: ExampleChipsProps) => (
  <div className="example-suggestions">
    <span>试试这些公司</span>
    {EXAMPLE_COMPANIES.map((name) => (
      <button
        key={name}
        type="button"
        className="example-chip"
        disabled={disabled}
        onClick={() => onPick(name)}
      >
        <img
          src={`/company-logos/${name.toLowerCase()}.png`}
          alt=""
          width="18"
          height="18"
          className="company-logo"
          onError={(event) => {
            // logo 缺失时不要让浏览器画一个碎图标
            event.currentTarget.style.display = 'none';
          }}
        />
        {name}
      </button>
    ))}
  </div>
);

export default ExampleChips;
