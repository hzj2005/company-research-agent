# 字节跳动 研究报告（live，中文）

> 2026-11-15 真实运行：Tavily advanced 检索 4 次（每栏 1 条 query，每条取 5 篇）+ qwen-plus 抽取。
> 四栏 19/11/7/8 条结论、16 个引用，来源含 bytedance.com / wikipedia / linkedin 等。
> **本次 8 credits**。

# 字节跳动 研究报告

## 公司概况

- 字节跳动（ByteDance）由张一鸣（Yiming Zhang）和梁汝波（Rubo Liang）等人于2012年创立。 [2]
- 字节跳动于2012年8月推出其旗舰产品之一今日头条（Toutiao）。 [2]
- 字节跳动于2016年9月在中国推出抖音（Douyin）。 [2]
- 字节跳动于2017年5月在大陆以外地区推出TikTok。 [2]
- 字节跳动于2017年11月收购Musical.ly，并随后将其与TikTok合并。 [2]
- 字节跳动在全球近120个城市设有办公室，包括奥斯汀、巴塞罗那、北京、柏林、迪拜、都柏林、香港、雅加达、伦敦、洛杉矶、纽约、巴黎、西雅图、首尔、上海、深圳、新加坡和东京。 [2]
- 字节跳动拥有超过150,000名员工。 [2]
- 字节跳动的产品与服务包括TikTok、CapCut、TikTok Shop、Lark、Pico、Mobile Legends: Bang Bang（MLBB）、今日头条（Toutiao）、抖音（Douyin）、番茄小说（Fanqie）、西瓜视频（Xigua）、飞书（Feishu）和抖音电商（Douyin E-commerce）。 [2]
- 字节跳动还运营Dola、Dreamina、Fizzo、Lemon8、PICO、Douyin、Toutiao、Doubao、Fanqie Novel、Hongguo、Soda Music等产品。 [4]
- 字节跳动的产品组合覆盖全球150多个市场，拥有超过20亿用户。 [4]
- TikTok的全球总部位于洛杉矶和新加坡，并在柏林、迪拜、雅加达、伦敦、墨西哥城、纽约、巴黎、圣保罗、圣何塞、首尔、悉尼和东京设有办公室。 [4]
- PICO是一个聚焦VR一体机技术的VR平台，致力于构建集成的XR平台。 [4]
- TikTok Commerce是一套创新的电子商务解决方案，例如TikTok Shop，旨在激励消费者并为商家驱动销售。 [4]
- TikTok For Business是TikTok的广告平台，支持品牌通过创意内容和数据驱动的营销方案触达并吸引受众。 [4]
- 字节跳动开发了TikTok/Douyin、今日头条（Toutiao）、剪映（CapCut）、Lemon8等应用。 [5]
- 字节跳动开发了生成式AI模型，面向中国和国际市场。 [5]
- 字节跳动的子公司包括Nuverse和Dcar。 [5]
- 字节跳动拥有约110,000名员工，分布在全球30多个国家。 [6]
- 字节跳动是TikTok、TikTok Music、Doubao、Seed、Seed-oss、Seedance、Seedream、CapCut、Toutiao、Whee、Lark、PICO、Lemon8、SoundOn、Baike.com、BuzzVideo、Trae（IDE）等产品的开发者。 [5]

## 行业概况

- 字节跳动在中国国内的主要竞争对手是腾讯（Tencent）、百度（Baidu）、阿里巴巴（Alibaba）、新浪（Sina）、搜狐（Sohu）、网易（Netease）、快手（Kwai Inc.）、哔哩哔哩（Bilibili）和美团（Meituan）等国内互联网巨头。 [8]
- 字节跳动在国际上的主要竞争对手是Meta（Facebook）和Google（Alphabet）等拥有数十年市场存在、成熟广告生态和强大开发者社区的西方科技平台。 [1]
- 字节跳动的核心可触达市场是全球数字广告市场，尤其是社交与视频广告；该市场2025年估值为574.8亿美元，预计2035年将增长至近2万亿美元，复合年增长率（CAGR）为13.2%。 [1]
- 社交电商市场2025年估值为1.5万亿美元，预计2034年将增长至8.7万亿美元，复合年增长率（CAGR）为21.5%。 [1]
- TikTok在东南亚的GMV年增长率超过40%，字节跳动生态系统的月活跃用户数约为20亿。 [1]
- 截至2022年，字节跳动旗下抖音（Douyin）和TikTok的广告收入合计超300亿美元，使其在全球广告发布商中排名第五。 [3]
- 2022年，TikTok单独的广告收入预计达11.64亿美元，较此前两年实现三倍增长。 [3]
- 字节跳动旗下抖音（Douyin）和TikTok合计占全球数字广告市场的份额将超过5%（2022年），高于2019年的2.0%。 [3]
- TikTok当前日独立设备数为1.0987亿台，在短视频行业中处于领先地位；快手（Kuaishou）位居第二，紧随其后争夺市场份额。 [7]
- 字节跳动在短视频行业已建立无可比拟的竞争优势，其业务主要依托TikTok平台；公司内部竞争产品包括今日头条（Toutiao）和西瓜视频（Watermelon Video）。 [7]
- 腾讯（Tencent）通过微信（WeChat）超10亿用户基础及微信新闻（Tencent News）的无缝整合，成为字节跳动在新闻聚合领域的重要竞争对手。 [9]

## 财务概况

- 字节跳动（ByteDance）在2025年预计实现约50亿美元利润 [15]
- 字节跳动（ByteDance）已在其2025年前三个季度累计实现约40亿美元净利润 [15]
- 字节跳动（ByteDance）2024年第二季度营收达约48亿美元，同比增长25% [12]
- 字节跳动（ByteDance）2024年第一季度营收超43亿美元 [12]
- 字节跳动（ByteDance）最新员工股份回购计划将其估值定为超330亿美元 [12]
- 字节跳动（ByteDance）在2024年11月的私募市场交易中估值为480亿美元 [16]
- 字节跳动（ByteDance）在2025年某次股权出售中估值升至550亿美元，较2024年11月估值增长15% [16]

## 新闻动态

- MPA（美国电影协会）与字节跳动于2026年8月17日宣布达成全球备忘录（MOU），旨在为AI视频与图像生成模型（如Seedance和Seedream）建立知识产权保护框架。 [10]
- 该MOU涉及TikTok、TikTok USDS联合体、CapCut和Dreamina等平台提供的Seedance和Seedream模型。 [10]
- MPA曾于2026年2月就Seedream 5.0 Lite和Seedance 2.0向字节跳动发出停止侵权函（cease and desist letter）。 [10]
- 在MOU达成前，字节跳动已推出Seedream 5.0 Pro和Seedance 2.5，称其进一步加强了知识产权保护措施。 [10]
- TikTok USDS联合体有限责任公司（Joint Venture LLC）于2026年1月23日成立，字节跳动持有其19.9%股权。 [13]
- TikTok USDS联合体的三大管理投资者为Silver Lake、Oracle和MGX，各自持股15%。 [13]
- TikTok USDS联合体的其他投资者包括Dell Family Office、Vastmere Strategic Investments、Alpha Wave Partners、Revolution、Merritt Way、Via Nova、Virgo LI和NJJ Capital。 [13]
- TikTok USDS联合体所设保障措施亦覆盖CapCut、Lemon8及美国境内的其他多款应用与网站。 [13]

## References

[1] Report: ByteDance Business Breakdown & Founding Story | Contrary Research — https://research.contrary.com/company/bytedance
[2] ByteDance - Inspire Creativity, Enrich Life — https://www.bytedance.com
[3] ByteDance expands the ranks of duopoly challengers — https://www.emarketer.com/content/bytedance-expands-ranks-of-duopoly-challengers
[4] Products & Services - ByteDance — https://www.bytedance.com/products-services
[5] ByteDance - Wikipedia — https://en.wikipedia.org/wiki/ByteDance
[6] ByteDance — https://www.linkedin.com/company/bytedance
[7] Research on the Core Competitiveness of Short Video Industry in the Context of Big Data—A Case Study of Tiktok of Bytedance Company — https://www.scirp.net/journal/paperinformation?paperid=116928
[8] 北京字节跳动科技有限公司 Information — https://rocketreach.co/bei-jing-zi-jie-tiao-dong-ke-ji-you-xian-gong-si-profile_b45edc76fc6b063e
[9] ByteDance’s global rise: An exemplar of strategic adaptability and digital innovation in a global context - Arif Perdana, S. Vijayakumar Bharathi, 2026 — https://journals.sagepub.com/doi/10.1177/20438869231211598
[10] MPA and ByteDance Announce Global Agreement to Protect Intellectual Property on AI Video and Image Generation Models - Newsroom | TikTok — https://newsroom.tiktok.com/mpa-and-bytedance-announce-global-agreement-to-protect-intellectual-property-on-ai-video-and-image-generation-models?lang=en
[11] TikTok owner ByteDance eyes valuation of over $330 billion as ... — https://links.message.bloomberg.com/s/c/cTBjlqRCUiMIRbFi_GmLDD3DjJ6SszpdVg8JQVd1dBnJ8_7MXCeJ1b1cCu0jBHvnU8fgY5wxo6bbJuFsMx7uawIDhntqFsBQCwzPFiXqlmrudhdz0C_-v4Sz5rRnzkZEWmAbPuqOlaIfVIj0Cd7jXvXKWL-VZsDMhZZpgqEbklG5-ReG8RGUb5xUoAM2QCJaG8XH48L4cV8aQP1kAJdsGzEIye2gmYqi7IokGQRzoOURjSXs07y18kCDrmS2vnmqOnPcTc1l0n7gjF0cjn5a9HS0RyKASh0Dz_cUm5vTz3fkknp-iaPpqkS2pqBo_8U7wgj-IwFgh3VmvD_bRlcGelt316CUu_cHYNouIElnXV6c_OahZ40MaSdQOwU/2kIjVw3DF9Wo_3qNVJ1Z1aUkujw441DL/12
[12] Exclusive: TikTok owner ByteDance sets valuation at over $330 billion as revenue grows, sources say — https://finance.yahoo.com/news/exclusive-tiktok-owner-bytedance-sets-142117183.html
[13] Announcement from the new TikTok USDS Joint Venture LLC - Newsroom | TikTok — https://newsroom.tiktok.com/announcement-from-the-new-tiktok-usds-joint-venture-llc?lang=en
[14] TikTok owner ByteDance sets valuation at over $330 bln — https://finance.yahoo.com/video/tiktok-owner-bytedance-sets-valuation-033232113.html
[15] ByteDance on track for $50 billion profit in 2025, Bloomberg reports — https://ca.finance.yahoo.com/news/bytedance-track-50-billion-profit-160612359.html
[16] ByteDance valuation surges to $550 billion in stake sale, Reuters reports — https://finance.yahoo.com/news/bytedance-valuation-surges-550-billion-174713731.html
