# 英伟达 研究报告（live，中文原生输出）

> 2026-11-15 真实运行：Tavily advanced 检索（每栏 2 条 query、每条取 5 条结果）+
> qwen-plus 抽取。标题与四个栏目标题已中文化；正文由提示词强制用简体中文书写，
> 公司名/产品名/型号保留英文原名。**本次为缓存重放，0 credits**（首次抓取共 24 credits）。
>
> 四栏共 68 条结论、20 个引用。

# 英伟达 研究报告

## 公司概况

- 英伟达（NVIDIA）成立于1993年，由 Jensen Huang、Chris Malachowsky 和 Curtis Priem 共同创立。 [1]
- 英伟达总部位于美国加利福尼亚州圣克拉拉（Santa Clara, California）。 [1]
- 英伟达在纳斯达克交易所上市，股票代码为 NVDA。 [1]
- 英伟达设计并开发图形处理单元（GPU）、中央处理器（CPU）和片上系统（SoC）单元。 [2]
- 英伟达的产品面向游戏、专业可视化、数据中心和汽车市场。 [2]
- 英伟达提供人工智能与数据科学、数据中心与云计算、设计与可视化、边缘计算、高性能计算（HPC）及自动驾驶车辆解决方案。 [2]
- 英伟达旗下品牌包括 GeForce NOW、Quadro、GeForce、SHIELD、vGPU、DOCA、Jetson 和 BlueField。 [2]
- 英伟达运营分为 Compute & Networking 和 Graphics 两大业务板块。 [4]
- Compute & Networking 板块提供数据中心加速计算与网络平台、人工智能解决方案与软件，以及汽车平台与自动驾驶及电动汽车解决方案（含软件）。 [4]
- Graphics 板块提供面向游戏和 PC 的 GeForce GPU，以及面向企业工作站图形的 Quadro/NVIDIA RTX GPU。 [4]
- 英伟达产品应用于游戏、专业可视化、数据中心和汽车市场。 [4]
- 英伟达客户包括原始设备制造商（OEM）、原始设计制造商（ODM）、系统集成商、分销商、独立软件供应商（ISV）、云服务提供商（CSP）、显卡附加板制造商、汽车制造商及一级汽车供应商等。 [4]
- 英伟达与 Cisco 合作开发 Ultra-Dense Small Form Factor Pluggable（USFP）高密度可插拔光模块。 [4]
- 英伟达与 ChipAgents 合作开发 Build-A-Chip-Bench，一个用于执行芯片设计任务的 AI 代理基准测试工具。 [4]
- 英伟达与联发科（MediaTek）建立战略联盟，共同构建下一代 AI 计算平台。 [4]
- 英伟达主要产品包括面向游戏的 GeForce 显卡、面向人工智能的 A 系列和 H 系列芯片、面向移动与嵌入式设备的 Tegra 处理器、面向 AI 个人电脑的 RTX Spark 芯片，以及面向开发者的 CUDA 软件。 [11]
- 截至2025年，英伟达在全球独立显卡（discrete graphics）细分市场占有92%的市场份额。 [11]
- 2022年，OpenAI 发布 ChatGPT 时所用的超级计算机配备了10,000块英伟达 GPU。 [11]
- 2026年10月，英伟达签署新合作协议，共同建设下一代 AI 基础设施通用基础。 [2]
- 2026年9月，英伟达与 CoreWeave 宣布 NVIDIA Vera Rubin NVL72 系统（搭载 Spectrum-X 以太网）在 CoreWeave Cloud 上线，Cognition 为首个生产客户；CoreWeave 计划提供 NVIDIA Vera CPU 以支持智能体（agentic）AI 工作负载。 [2]
- 2026年10月，英伟达、HPE 和 Kamiwaza 联合 SHI International 推出全面符合美国《第508条》（Section 508）合规性要求的解决方案。 [2]

## 行业概况

- 英伟达（NVIDIA）在GPU市场的占有率为85%。 [7]
- AMD在GPU市场的占有率为7%，且该份额在2025年第三季度增长了0.8个百分点。 [7]
- 英伟达、AMD和Intel共同构成AI芯片市场的主要参与者，但并非该领域全部玩家。 [5]
- 除英伟达、AMD和Intel外， Alphabet（GOOG）、Amazon（AMZN）、Apple（AAPL）、IBM（IBM）、Microsoft（MSFT）、Qualcomm（QCOM）等大型科技公司也在自研AI芯片，主要用于内部使用而非对外销售。 [5]
- 谷歌（Google）自研芯片TPU目前仅在谷歌资料中心得到验证，未来计划向外部出售。 [9]
- 亚马逊（Amazon）最新推出的Trainium 3芯片主要目标是为客户提供更多不同的计算工作负载选择，其最大优势是性价比，并不预期取代英伟达产品。 [9]
- AMD于2024年推出面向数据中心的GPU MI300，比英伟达第二代数据中心GPU晚发货一年以上。 [16]
- AMD的MI300芯片在软件生态方面仍落后于英伟达，导致其编程和使用难度更高。 [16]
- Intel推出的AI芯片Gaudi系列在某些方面可与英伟达芯片相媲美。 [16]
- 华为（Huawei）被认为是对英伟达及美国AI技术主导地位最具威胁性的中国竞争对手。 [16]
- 应用专用集成电路（ASIC）因其针对特定AI工作负载的低成本优势，正被超大规模云服务商（hyperscalers）采用，对英伟达构成挑战。 [16]
- 英伟达的芯片应用生态比谷歌、亚马逊等竞争对手更广泛。 [9]
- 英伟达、AMD和Intel是AI芯片市场的主要竞争者，此外还有Cerebras、CoreWeave、Broadcom、Marvell、Tenstorrent等公司参与竞争。 [12]

## 财务概况

- 英伟达（NVIDIA）截至最近季度末（mrq）的总现金（Total Cash）为62.47B美元 [14]
- 英伟达（NVIDIA）截至最近季度末（mrq）的每股现金（Total Cash Per Share）为2.59美元 [14]
- 英伟达（NVIDIA）截至最近季度末（mrq）的流动比率（Current Ratio）为4.59 [14]
- 英伟达（NVIDIA）截至最近季度末（mrq）的每股账面价值（Book Value Per Share）为9.48美元 [14]
- 英伟达（NVIDIA）过去十二个月（ttm）的经营性现金流（Operating Cash Flow）为134.36B美元 [14]
- 英伟达（NVIDIA）已发行普通股数量（Shares Outstanding）为24.15B股 [14]
- 英伟达（NVIDIA）截至2026年10月30日的做空股份数（Shares Short）为279.58M股 [14]
- 英伟达（NVIDIA）截至2026年10月30日的做空股份数占已发行股份比例（Short % of Shares Outstanding）为1.16% [14]
- 英伟达（NVIDIA）截至2026年9月30日前一个月的做空股份数（Shares Short）为311.39M股 [14]
- 英伟达（NVIDIA）前向年度股息收益率（Forward Annual Dividend Yield）为0.58% [14]
- 英伟达（NVIDIA）过去十二个月股息收益率（Trailing Annual Dividend Yield）为0.17% [14]
- 英伟达（NVIDIA）在2026年9月28日将其股票回购授权额度提高了150B美元，使总授权额度达到235B美元 [18]
- 英伟达（NVIDIA）2026财年第二季度（截至2026年7月26日）营收为96.2B美元，同比增长106% [18]
- 英伟达（NVIDIA）2026财年第二季度数据中心业务（Data Center）营收为89B美元，同比增长117% [18]
- 英伟达（NVIDIA）2026财年营收为215.9B美元，同比增长65% [19]
- 英伟达（NVIDIA）当前远期市盈率（forward P/E ratio）为22.22x [19]
- 英伟达（NVIDIA）截至2026年11月13日的非稀释市值（Non diluted market cap）为3,932,338,950,000美元 [20]
- 英伟达（NVIDIA）截至2026年11月13日的市销率（Price to sales trailing 12 months）为12.98 [20]
- 英伟达（NVIDIA）截至2026年10月30日的做空股份数占流通股比例（Short percent of float）为1.21% [20]
- 英伟达（NVIDIA）最近一次派息日期（Last dividend date）为2026年9月10日 [20]

## 新闻动态

- 英伟达（NVIDIA）于2026年8月10日宣布与Apollo、BlackRock、Blackstone、Brookfield、Goldman Sachs和KKR建立战略合作伙伴关系，共同设立AI算力基础设施融资平台，目标是动员超500亿美元的第三方资本。 [3]
- 英伟达与SK集团于2026年7月24日宣布达成超5000亿美元的全面合作计划，涵盖AI工厂建设与AI内存供应。 [6]
- SK Telecom将基于英伟达Vera Rubin基础设施和DSX平台，在韩国建设一座规模达2吉瓦（2-gigawatt）的AI云，首座AI工厂计划于2027年上线，所用HBM4内存由SK hynix提供。 [6]
- 英伟达与Meta于2026年10月26日宣布扩大在Muse及Muse系列模型上的合作，以提升推理与训练性能，并计划深化NVIDIA OpenShell Reference Architecture（含NVIDIA OpenShell™与NVIDIA Sentry）等技术协作。 [8]
- 英伟达将向Meta的股权融资中投资30亿美元。 [8]
- 英伟达与Ilya Sutskever创立的Safe Superintelligence Inc.（SSI）于2026年7月27日宣布建立长期战略合作关系，英伟达向SSI进行重大投资，并提供Vera Rubin平台支持，使SSI算力提升一个数量级。 [13]
- 英伟达与IBIDEN、三星电机（Samsung Electro-Mechanics）、欣兴电子（Unimicron Technology Corporation）签署基板协议，预计三年内合计推动产能提升2.5倍。 [15]
- Amkor计划到2028年底将其先进封装产能提升超300%。 [15]
- 京元电（KYEC）将在美国新建工厂，获英伟达11亿美元产能预留预付款支持。 [15]
- 矽品（SPIL）目标在2027年年中将其共封装光学（co-packaged optics）光引擎产能提升15倍，并于2028年底再翻倍。 [15]
- 英伟达向IBIDEN提供数十亿美元产能预留预付款，支持其日本大野工厂（Ono Plant）扩建，目标产能达当前水平的3倍，新增产能预计于2028年第一季度开始爬坡。 [15]
- 英伟达支持三星电机在韩国世宗与釜山升级现有设施并新建工厂；至2028年，分配给英伟达的基板产能预计将占三星电机全年封装基板总产能的很大一部分。 [15]
- 英伟达与欣兴电子签署产能预留协议，支持其在台湾KF厂的基板制造扩产，新增产能预计于2027年第二季度起逐步释放，2028年年中达满产。 [15]
- 英伟达与Amkor计划在韩国扩大先进封装产能，目标在2028年底前将中介层晶圆（interposer wafer）产能提升超300%，以支持当前及下一代平台更高产量。 [15]

## References

[1] NVIDIA Corporation (NVDA): An Overview of Its Business Model and AI-Driven Growth — https://tickeron.com/blogs/nvidia-corporation-nvda-an-overview-of-its-business-model-and-ai-driven-growth-32430
[2] Nvidia Corp Company Profile - Nvidia Corp  Overview - GlobalData — https://www.globaldata.com/company-profile/NVIDIA-Corp
[3] NVIDIA Partners With Apollo, BlackRock, Blackstone, Brookfield, Goldman Sachs and KKR to Establish AI Compute Infrastructure Financing Platforms to Mobilize Over $500 Billion of Third-Party Capital | NVIDIA Newsroom — https://nvidianews.nvidia.com/news/nvidia-partners-with-apollo-blackrock-blackstone-brookfield-goldman-sachs-and-kkr-to-establish-ai-compute-infrastructure-financing-platforms-to-mobilize-over-500-billion-of-third-party-capital
[4] NVIDIA Corporation (NVDA) Company Profile & Facts - Yahoo Finance — https://finance.yahoo.com/quote/NVDA/profile
[5] Nvidia Competitors: Who Are the AI Chip Alternatives? - NerdWallet — https://www.nerdwallet.com/investing/learn/nvidia-competitors
[6] SK Group and NVIDIA Expand Strategic Partnership Across AI Factories and Next-Generation Memory | NVIDIA Newsroom — https://nvidianews.nvidia.com/news/sk-group-and-nvidia-expand-strategic-partnership-across-ai-factories-and-next-generation-memory
[7] Nvidia's 85% GPU Market Share Faces Growing Competition: Is This AI Stock Still a Buy for 2026? — https://finance.yahoo.com/news/nvidias-85-gpu-market-share-210500376.html
[8] NVIDIA and Meta to Expand Collaboration on Muse and Muse Family of Models Amid Robust Growth | NVIDIA Newsroom — https://nvidianews.nvidia.com/news/nvidia-and-meta-to-expand-collaboration-on-muse-and-muse-family-of-models-amid-robust-growth
[9] 英伟达估值接近历史低位，“抄底英伟达”摆在桌面 — https://www.tradingkey.com/zh-hans/analysis/stocks/us-stock/251359683-nvidia-stock-gpu-google-tpu-amazon-trainium-competition-market-share-tradingkey
[10] NVIDIA Corporation | — https://www.thirdbridge.com/en-us/companies/nvidia-corporation.a1ce3520-6a0f-45c9-be1c-8bf318f3f59a
[11] NVIDIA Corporation — https://www.britannica.com/money/NVIDIA-Corporation
[12] Nvidia Competitors: Complete List & Market Landscape — https://www.distillintelligence.com/competitors/nvidia
[13] Ilya Sutskever’s Safe Superintelligence Inc. and NVIDIA Announce Long-Term Strategic Partnership | NVIDIA Newsroom — https://nvidianews.nvidia.com/news/ilya-sutskevers-safe-superintelligence-inc-and-nvidia-announce-long-term-strategic-partnership
[14] NVIDIA Corporation (NVDA) Valuation Measures & Financial Statistics — https://finance.yahoo.com/quote/NVDA/key-statistics
[15] NVIDIA and Supply Chain Partners Expand Capacity to Accelerate AI Infrastructure Buildout | NVIDIA Newsroom — https://nvidianews.nvidia.com/news/nvidia-and-supply-chain-partners-expand-capacity-to-accelerate-ai-infrastructure-buildout
[16] Nvidia Competitors: AMD and Startups Close in on AI Chip Market - Business Insider — https://www.businessinsider.com/nvidia-competitors
[17] NVIDIA Corp. Financial Statements - NVDA — https://www.wsj.com/market-data/quotes/NVDA/financials
[18] Nvidia's record buyback exposes strange Wall Street gap — https://sg.finance.yahoo.com/news/nvidias-record-buyback-exposes-strange-223200630.html
[19] Nvidia's valuation just hit a multiyear low — even as revenue sets records — https://finance.yahoo.com/technology/article/nvidias-valuation-just-hit-a-multiyear-low--even-as-revenue-sets-records-155948933.html
[20] NVIDIA Corporation (NVDA) Stock Price, News, Quote & History - Yahoo Finance — https://finance.yahoo.com/quote/NVDA
