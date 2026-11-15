import { EXAMPLE_COMPANIES } from '../examples';

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
