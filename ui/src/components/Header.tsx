interface HeaderProps {
  /** 后端 /config 报的运行模式：live 会花 Tavily 额度，fixture 用本地语料 */
  mode: 'fixture' | 'live' | null;
}

const Header = ({ mode }: HeaderProps) => (
  <header>
    <nav className="site-nav" aria-label="主导航">
      <a href="https://tavily.com" target="_blank" rel="noopener noreferrer" className="brand-link" aria-label="Tavily 官网">
        <img src="/tavily-by-nebius.svg" alt="Tavily by Nebius" className="brand-logo" width="362" height="109" />
      </a>
      {mode && (
        <span
          className={`mode-pill${mode === 'live' ? ' mode-pill--live' : ' mode-pill--fixture'}`}
          title={mode === 'live'
            ? '真实联网检索：每次调研会消耗 Tavily 额度'
            : '演示模式：使用本地固定语料，不联网、不花钱'}
        >
          {mode === 'live' ? '真实调研' : '演示数据'}
        </span>
      )}
    </nav>
    <div className="hero">
      <h1>公司调研助手</h1>
      <p className="hero-description">
        输入一个公司名，自动检索公开网页，产出一份分四栏、每条都带引用编号的简报。
        证据不够时会明确写「未找到公开依据」，而不是硬编。
      </p>
    </div>
  </header>
);

export default Header;
