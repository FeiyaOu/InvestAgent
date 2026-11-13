# Analytics Agent 实施规格

更新日期：2026-11-12。以下状态以代码与 mock/数值测试为依据，不代表真实 API 或浏览器端到端验证。

## 当前完成情况

| 项目 | 状态 | 实际边界 |
|---|---|---|
| 结构化历史价格/基准/估值契约 | 已完成首版 | 含日期、来源、单位、复权/指标定义及 real/mock |
| DatasetStore / AnalysisStore | 已完成 | 请求内内存存储，不是跨请求持久化 |
| Market Data 结构化采集 | 已完成首版 | 个股/指数日线、PE TTM/PB MRQ快照；不是完整财报来源 |
| analyze_price_performance | 已完成 | 区间收益、年化波动率、回撤及序列 |
| compare_with_benchmark | 已完成 | 超额收益、beta、相关性、tracking error及比较序列 |
| compute_factors | 已完成 | 动量、均线偏离、滚动波动率、量比 |
| compare_valuations | 已完成 | 逐公司表、可比口径下的中位数/差值，不给买卖结论 |
| 独立 Analytics 子图 | 已完成 | 四工具循环、引用范围验证、有界执行、结构化缺失要求与输出校验 |
| Supervisor 调度 Analytics | 已完成 | 父图调用独立Analytics，Strategy仍unsupported |
| 上游数据/分析引用交接 | 已完成首版 | 仅从显式前置任务收集canonical引用，去重并校验范围 |
| 父图 AnalysisStore 注入 | 已完成 | 父图/已有计划执行图均按请求创建两个Store，不写入State |
| Planner 的分析数据先决任务细化 | 已完成首版 | 明确采集类型/区间/基准规则，规划输出检查Analytics直接数据依赖，仍需真实模型语义评估 |
| Composer 分析结果汇总 | 已完成 | 展示实际指标、比较表、口径、来源与缺失要求；模型失败保留确定性结果 |
| Streamlit/Plotly 分析图表 | 首版完成 | 指标卡、结果表、累计收益/回撤/基准/因子曲线及估值柱状图；当前会话最近请求快照 |
| analytics-methodology skill | 已创建并接入独立子图 | 固定加载仓库方法文件，进入系统上下文；公式和验证仍在工具代码中 |
| 真实模型/采集 API 的端到端评估 | 未执行 | 当前是确定性数值测试与 mock 模型/API 测试 |

## 设计原则落实与剩余边界

- **采集复用 Market Data**：Analytics 无行情 API，也不调用 Market Data Agent。
  它只读取外部提供的结构化引用；文本摘要不足以计算。跨 Agent 的采集依赖仍由未来父级接线负责。
- **pandas/NumPy 优先**：已落实，未引入 TA-Lib，未暴露大量独立指标工具。
- **图表就绪产物**：累计收益、回撤、基准和因子序列在 AnalysisStore；
  比较表在产物中。数据就绪不代表 Streamlit 已绘图或跨请求可恢复。
- **假设显式化**：保留数据复权口径、年化参数、基准 dataset_ref、样本数、单位、
  无填充策略与实际工具参数，模型文字不能替代这些元数据。
- **无风险利率暂不需要**：V1没有 Sharpe ratio 或 CAPM 预期收益；beta计算不需要该参数。
  后续新增依赖无风险利率的指标时再显式加入，不默认编造一个值。
- **代码验证输入**：按工具拒绝不兼容日期/币种/收益或估值定义。
  样本不足不总是整项拒绝：两个价格可算区间收益，波动率为null并说明；
  基准共同日期不足则拒绝比较。不填零、不输出NaN、不让模型猜算。
- **优化职责分离**：未引入 PyPortfolioOpt/HRP/Black-Litterman，留给未来 Strategy/Risk。
- **协方差输出未实现**：现有工具仅在内部使用相关统计量，不提供独立协方差矩阵产物；
  未来组合优化确有需要时再建设，不把它当作当前已交付能力。
- **估值数据限制**：现有源无明确股息率，增长、ROE、EPS采集尚未完成。
  比较工具可处理符合契约的这些指标，但不代表系统已能从真实来源获取它们。
- **解释质量限制**：引用及数值来源经代码校验；自由文字的完整性、准确性仍需真实模型评估。

## 职责与依赖

Analytics 执行可复现的历史表现、基准、估值和因子计算，不提出未来投资建议或做组合优化。
未来投资机会属于 investment_strategy；需要定量依据时依赖 Analytics，
Analytics 缺少数据集时依赖 market_data。已有合适数据时不强制重复采集。
依赖按任务输入决定，不固定每次执行 market_data → analytics → strategy。
Strategy 还应接收相关原始定性证据，不能只依赖 Analytics 摘要。

## 分步实施

1. **数据契约与请求内存储：已完成**，见下节。
2. **日线采集已完成**：共享工具层新增结构化采集工具，Market Data 返回数据集引用；原报告工具保持兼容。估值快照已补齐，完整财报采集不在首版范围。
3. **V1 工具已独立实现**：表现、基准、小目录因子及估值比较；已接独立 Analytics 子图，尚未接父级调度。
4. **独立子图已完成**，局部状态、工具循环、预算和输出验证；修正阶段不重新执行工具。
5. **首版独立测试已完成**，覆盖真实计算产物、缺失数据、权限边界和失败行为；尚无真实模型语义评估。
6. **已完成首版调度接线**：共享存储、引用交接及AnalyticsResult→TaskResult边界验证，报告不改。
7. Planner / Composer / UI 接入计划依赖、分析解释及 Plotly 图表。
8. 按数据成熟度建设 V2。

## V1 工具（已独立实现，未接父级调度）

| 工具 | 内容 |
|---|---|
| analyze_price_performance | 区间收益、年化波动率、最大回撤、累计收益与回撤序列 |
| compare_with_benchmark | 相对表现、beta、相关性、tracking error、对齐比较序列 |
| compute_factors | 小范围明确目录：动量、波动、趋势和均线；不暴露大量独立指标工具 |
| compare_valuations | PE/PB/股息率、增长和盈利质量比较；不可用指标说明原因 |

pandas / NumPy 优先，TA-Lib 按具体指标需求后加。
收益年化、频率、缺失处理、复权口径、基准和有效样本数必须明确；仅在指标需要时加入无风险利率。
工具只读取结构化数据，返回数值与图表序列，不让模型从文本摘要猜数字。

## V2 工具（待实现）

- evaluate_factors：Rank IC、前瞻分组收益、换手率。
- analyze_factor_redundancy：相关性与因子重叠。
- compare_historical_valuations：历史分位和区间。
- evaluate_signal_strategy：明确规则、成本、基准与样本外验证。

需要多股票时序、历史股票池和财务实际可用日期，避免前视及幸存者偏差。
PyPortfolioOpt、HRP、Black-Litterman 留给未来 Strategy / Risk，不放入 V1 Analytics。

## Analytics 局部状态（方案，尚未实现）

- 输入：task、subjects、time_range、dataset_refs、existing_analysis_refs、assumptions。
- 执行：messages、tool_rounds、tool_calls_used、output_retries、analysis_artifacts。
- 输出：result、status、error。
- result 包含 summary、findings、analysis_refs、chart_refs、dataset_refs、assumptions、limitations、missing_information。

完整 DataFrame 不放入图 State。每个计算产物记录数值、单位、参数、区间、样本数和来源。
缺数据时返回结构化缺失要求，不由 Analytics 自行调用 Market Data Agent；父级负责跨 Agent 调度。
自动补充规划尚不实现。方法型 skill 指导选择和解释，公式及验证仍在 Python 工具中。

## 步骤1：数据层已实现

`src/datasets.py` 提供：

- PriceDataset：单标的日频价格，stock/index/fund；元数据包含 symbol、market、currency、provider、
  source_url、带时区 retrieved_at、real/mock、adjustment、price_unit、volume_unit。
- 复权类型明确为 none/qfq/hfq/total_return；这些是数据标签，不代表可互换或自动含分红收益。
- 每行 date / close 必填，OHLCV 其余字段可缺；数值有限，价格为正，成交量非负。
  日期严格递增且唯一，OHLC 范围一致，不自动排序、去重、补值或填零。
- 成交量统一 shares；供应商如返回手数，后续适配层必须转换，缺失用 not_available。
- ValuationDataset：单标的观察日期，report_period / available_at 可选且不可晚于观察日；
  首版为单快照而非完整 point-in-time 财务面板。
- 指标支持 pe_ttm、pb、dividend_yield、revenue_growth、earnings_growth、roe、eps，
  单位分别检查 multiple / percent / currency_per_share；percent 的2表示2%，不是0.02。
  缺失 value=None 时须提供 missing_reason，不把负收益下不适用 PE 当作正常估值排序。
  仍保留负数原值供计算工具判断，不在数据层替用户作估值结论。
- available_at 未提供时无法证明 point-in-time 可用性；未来历史因子工具必须拒绝或明确限制，
  不能因可选日期为空就声称已防止前视偏差。
- DatasetRef：包含唯一 ID、来源、symbol、时间区间、行数及价格口径，不包含 rows。
  需进入 JSON 状态时使用 model_dump(mode="json")。
- DatasetStore：每请求显式创建独立实例，put/get/get_ref/clear；不可作为全局缓存。
  注册时重新验证，即使输入为被修改过的模型也不信任；读写复制防止调用方修改存储内容。
  锁保护并发访问，为未来同轮工具提供共享请求内数据容器。
- 未设置数据库、持久化、自动过期、API 抓取或图注入。引用只在同一存储实例存在期间可解析；
  后续接线需显式注入同一实例，不能从一个裸 dataset_id 在新请求中恢复数据。

单元测试无 API：覆盖无效价格、日期、单位、缺失值、估值日期与指标单位、对象变更隔离、
请求隔离、引用 JSON 往返及清空。真实数据采集与计算延迟尚未测试。


## 步骤2：结构化历史价格已接入（2026-11-12）

新增 `src/tools.py:get_price_history`，仅加入 Market Data 的默认工具集合，
原 INVEST_TOOLS 和报告 perception 的四工具调用不改。

- 输入 query、start_date / end_date（ISO日期）、asset_type（stock/index）、adjustment（none/qfq/hfq）。
- 股票支持沪深六位代码或现有名称解析；指数要求明确六位代码且 adjustment=none。
- 最长3660天，不接受反向区间或未来终止日；相对日期基于 Market Data 输入中的上海当前日期解析。
- 实盘使用 stock_zh_a_hist / index_zh_a_hist，错误返回 JSON unavailable + error，不伪造模拟回退。
  无有效行时不注册数据；不自动排序、去重或填充异常数据，校验失败明确不可用。
- 按 AKShare 股票历史接口的手数口径将成交量乘100规范为 shares；
  指数价格单位为 points，首版不返回指数成交量，避免对指数成交量作错误解释。
  接口说明参考 [AKShare 股票文档](https://akshare.akfamily.xyz/data/stock/stock.html)
  与 [指数文档](https://github.com/akfamily/akshare/blob/main/docs/data/index/index.md)。
- 模拟模式生成工作日人工序列，标记 mock / synthetic_demo，明确不代表真实行情或交易所节假日。
- 工具返回 status、dataset_ref、first_close、last_close、limitations，模型不接收整表。
- 配置中的 dataset_store 是 RunnableConfig 注入值，不在模型可调用参数 schema 中。
- 父图每次 supervise 创建独立 DatasetStore，经配置传给 Supervisor / Market Data；
  create_response_graph 同样按请求创建。存储不写入 State，任务之间仅同次请求内共享。
- 独立调用 Market Data / Supervisor 时，如要使用历史工具，调用方须在 configurable 中提供 DatasetStore。
  未提供时历史工具返回 missing_store，而不是不可解析的引用。
- MarketDataResult 新增 dataset_refs（默认空），由工具节点从实际存储取 canonical ref，
  不让 LLM 回填或编造 ID；使用 JSON-safe 序列化，Supervisor 继续验证领域结果。
- 结构化工具的证据写入数据区间终止日、来源和真实/模拟状态；工具 unavailable 作为错误证据。
- UI 展示引用元数据；原始序列仅在本次请求存储存在期间可解析，当前未实现重开页面绘图或持久化下载。

测试覆盖股票/指数规范化、无数据/网络与输入错误、模拟状态、无效供应商数据、
隐藏运行配置、ToolNode 真结构执行、引用收集和父图跨请求隔离；全部使用 mock。
未执行真实行情 API。下一步开始 V1 表现/基准计算工具，估值计算仍需财务与估值采集支持。


## 步骤3：表现与基准工具（2026-11-12 已实现，未接 Agent）

`src/analytics_tools.py` 提供两个 @tool，不调用 LLM 或数据 API。
输入 dataset_id，基准比较另需 benchmark_dataset_id，periods_per_year 默认252，可选1–366。
运行时在 RunnableConfig.configurable 显式提供同请求 dataset_store 和 analysis_store。
当前父图只注入 dataset_store；analysis_store 尚未接入运行入口，需待 Analytics 建设时统一注入。

### 表现工具

analyze_price_performance：至少2个价格，计算 close_last / close_first - 1、
价格 / 历史累计最高价格 - 1 的最小值（最大回撤为非正数）、
简单收益率的样本标准差（ddof=1）乘 sqrt(periods_per_year)。
少于2个收益观察值时波动率为空，说明限制，不伪造零波动。
图表产物为归一化累计收益和回撤序列。

### 基准工具

compare_with_benchmark：共同日期 inner join，不 forward fill，至少3个共同价格。
同一共同区间内计算简单收益，beta=cov(asset,benchmark)/var(benchmark)，
相关性、样本收益差标准差乘 sqrt(periods_per_year) 为 tracking_error。
超额区间收益定义为两个累计收益的差，不是相对财富比率或 alpha。
币种不一致、总回报与价格收益基准不一致时拒绝计算；不自动汇率转换。
零或近零方差下 beta / 相关性按可定义性返回 null 并说明；零方差阈值1e-18。
对齐丢弃任一数据集日期时，收益间隔可能不再连续，不年化 tracking_error，返回 null。
共同样本上的 beta/相关性仍保留并注明对齐限制。
图表产物为标的与基准共同区间累计收益序列。

### 产物与状态

`src/analytics_artifacts.py` 定义 AnalysisArtifact / SeriesPoint / AnalysisStore，
记录 canonical dataset_refs、创建时间、区间、收益样本数、metrics、metric_units、assumptions、limitations。
收益、波动率和回撤用 fraction（0.1代表10%），beta/相关性无量纲。
模拟标记、未复权风险、连续交易日年化假设及非总回报限制随产物保存。

工具返回 available + analysis_ref 或 unavailable + 结构化错误。
analysis_ref 包含指标与 chart_refs，不包含完整序列；序列只在请求内 AnalysisStore，
chart_refs 由 analysis_id / series_key 组成，可读取 artifact.series[series_key]。
引用不能跨新建存储实例解析，存储读写复制、支持 clear，未持久化或新增图状态大数组。
available 只表示计算完成，不代表样本充分或结论可靠，必须保留 limitations。

```python
from src.datasets import DatasetStore
from src.analytics_artifacts import AnalysisStore
from src.analytics_tools import analyze_price_performance

# prices 是已有、经验证的 PriceDataset。
datasets, analyses = DatasetStore(), AnalysisStore()
# ref = datasets.put(prices)
# result = analyze_price_performance.invoke({"dataset_id": ref.dataset_id}, config={
#     "configurable": {"dataset_store": datasets, "analysis_store": analyses}})
```

数值测试用可手算序列覆盖收益/回撤/波动率、基准同收益、零方差、缺失日期、
币种/收益口径不兼容、模拟数据、引用失效及对象复制；不运行真实 API。
下一步按原计划实现小目录因子计算；估值工具需先补齐结构化财务/估值来源。


## V1 价格因子、估值采集与比较（2026-11-12 已实现）

### compute_factors

独立 @tool，输入 dataset_id、window（2–252个观察值）、factors 和 periods_per_year（默认252）。
默认 momentum / sma_gap / realized_volatility，可显式选择 volume_ratio；拒绝空目录、未知或重复因子。

| 因子 | 定义 |
|---|---|
| momentum | P[t] / P[t-window] - 1，不跳过最近月份 |
| sma_gap | 当前价格 / 含当前观察值的 window 均线 - 1 |
| realized_volatility | window 个简单收益的样本标准差（ddof=1）乘年化平方根 |
| volume_ratio | 当前成交量 / 含当前观察值的 window 平均成交量 |

只用向后滚动窗口；不将 warm-up 缺失填零，不补缺失成交量。
样本不足、零成交量分母等使最新指标为 null，附原因；图表仅存有效点，不含 NaN。
series 保留在 AnalysisStore，工具返回 analysis_ref，不代表已证明预测能力或实现因子回测。

### get_valuation_snapshot

新增 src/tools.py 工具，加入 Market Data 默认集合，原报告 INVEST_TOOLS 不变。
query 支持沪深 A 股代码/既有名称；as_of_date 默认为上海当天，不支持未来日期。
实盘通过 AKShare stock_value_em 取观察日期不晚于请求日期的最新唯一记录，
不将取数时间冒充估值观察日期；重复日期或无数据明确 unavailable。

按照 [AKShare 官方实现](https://github.com/akfamily/akshare/blob/main/akshare/stock/valuation/stock_value_em.py)
映射 PE(TTM) → pe_ttm / PE_TTM，市净率 → pb / PB_MRQ，不使用 PE(静) 补缺。
该来源不提供明确股息率，dividend_yield 返回 null 和 missing_reason，不用零代替。
未提供报告期/公告时间，不推断 available_at，不保证历史 point-in-time 可用性。
请求日期与实际观察日期不同会提示；实盘错误不改用模拟，模拟模式明确 synthetic_demo。
保留非正原值供比较工具判断，不将负PE视为低估。
工具注册 ValuationDataset，返回 canonical dataset_ref、metrics、requested_date、limitations。
Market Data 工具节点自动收集引用和实际日期，最终输出验证规则不变。

### compare_valuations

独立 @tool，输入2–20个不同公司的 valuation_snapshot 引用；相同币种与相同观察日期为前提。
默认比较 pe_ttm / pb，可显式选择已有指标目录。重复引用、公司、日期/币种不匹配及非估值数据拒绝。

AnalysisArtifact 新增 table（默认空），比较表保留逐公司原值、可用值、单位、定义与缺失/不适用原因。
非正 PE/PB 不参与汇总，raw_value 保留；未提供的股息率等仍为 null，不填零。
每项指标只有所有公司数值有效、已知定义一致时才计算 median 和 max-min spread，否则二者为 null。
已知定义目录：PE_TTM；PB_MRQ/PB_LYR；DIVIDEND_YIELD_TTM；REVENUE_YOY；EARNINGS_YOY；
ROE_TTM/ROE_FY；EPS_TTM/EPS_FY。即使任意两个未知标签相同也不视为口径可比。
财务类增长/ROE/EPS 还须相同报告期并提供可用日期，不能据空日期假设可比。
工具不生成买卖评级、低估排名或未来投资结论；行业、增长与质量仍需其他证据。
sample_size 在表现工具是收益间隔数，在估值比较是公司数，后者通过 assumptions.sample_size_unit 明示。

### 本轮范围与验证

独立 Analytics Agent 已完成；Supervisor analytics dispatch、AnalysisStore 的父图注入及 Plotly 看板尚未接入。
报告内部未改，不因新增工具而声称估值研究已端到端上线。
测试使用 mock 供应商与可手算序列，覆盖因子值/无前视/缺失量、估值口径、日期、缺失值、
非正PE、未知定义、静态PE不可替代、来源失败及 Market Data 引用收集。未调用真实数据 API。


## 步骤4–5：独立 Analytics 子图（2026-11-12 已实现）

### 入口与局部状态

`src/analytics_agent.py:create_analytics_agent()` 构建 initialize → agent ↔ tools → finalize 子图。
`src/stages/analytics.py` 包含模型节点，`src/analytics_state.py` 定义输入与输出模型。
默认工具为 V1 四个计算工具，不含市场 API 或其他 Agent 的调用接口。
不设置 checkpoint；独立任务在 initialize 清空旧消息、计数器和计算结果。

输入 task、subjects、time_range、dataset_refs、existing_analysis_refs、assumptions。
引用字典的 ID 在运行时存储解析，元数据以 store 的 canonical ref 为准，
而不是信任调用方提交的数值或来源。数据引用不可重复，过期或跨存储实例引用明确失败。
existing_analysis_refs 仅允许基于本任务 dataset_refs 的产物；已明确指定参数与旧产物不一致时拒绝复用。
现有 input 必须显式列出复用产物所依赖的数据，不从一个裸 analysis_id 自动扩大数据权限。

assumptions 首版支持可选 periods_per_year（1–366）、window（2–252）及固定 missing_data=no_fill。
显式指定的参数在适用工具执行前覆盖模型选择，未指定时保留模型选择/工具默认值。
实际计算假设由每个 canonical 分析产物保留，输入假设不代替实际参数。

### 数据与工具范围

调用者通过 RunnableConfig.configurable 提供同请求 dataset_store 和 analysis_store。
无输入数据/已有产物时，不调用模型，直接 partial + MissingDataRequest，交由未来父级处理。
有引用但没有运行时存储则 missing_store；无效输入/引用在计算前终止。
工具只能访问输入清单中的数据 ID；尝试访问其他 ID 返回 dataset_scope_error，不执行该批。
工具返回产物 ID 必须能在 AnalysisStore 找到，且其源数据不超出任务范围。
输入/输出 State 不保存 DataFrame 或完整图表序列。

默认最多3轮工具、累计8次调用、1次输出修正；可配置上限分别为5/20/2，允许0。
修正时不绑定工具，仍返回工具调用时直接 invalid_output，不重复计算。
预算只控制次数，不是墙钟超时。不进行自动采集、重新规划、任务级重试或长期缓存。

### 结果与缺失要求

模型只输出 summary、analysis_ids、missing_information、missing_data_requests。
最终 findings 的数值、单位和比较表，analysis_refs、chart_refs、有效假设和限制，
全部从实际存储产物构造，不由模型回填或篡改。解释文字仍需后续真实模型质量评估。
未引用实际产物且未说明缺失信息的回答不通过；未知/重复 analysis_ids 不通过。

MissingDataRequest 字段：kind（price_history/benchmark_history/valuation_snapshot/unspecified）、
subjects、time_range、reason。缺数据不触发跨 Agent 调用。

输出 result 包含 summary、findings、analysis_refs、chart_refs、dataset_refs、assumptions、
limitations、missing_information、missing_data_requests。
status 为 running / completed / partial / failed；工具错误、模拟输入、不可定义指标、
缺失信息或没有可用计算结果使最终状态 partial；失败返回结构化 error。
历史表现不代表未来等通用限制仍保留，但不单独将所有正常结果标为 partial。

```python
from src.analytics_agent import create_analytics_agent
from src.analytics_artifacts import AnalysisStore

# datasets 是当前请求 DatasetStore，price_ref 是其中已注册的 DatasetRef。
# state = create_analytics_agent().invoke({
#     "task": "分析该股票历史表现", "dataset_refs": [price_ref.model_dump(mode="json")]
# }, config={"configurable": {"dataset_store": datasets, "analysis_store": AnalysisStore()}})
```

### 验证与下一步

测试使用真实确定性工具 + fake LLM，覆盖数值引用、图表来源、无数据、过期/外部数据、
假设覆盖和复用冲突、工具失败、模拟/短样本、预算、输出修正、虚构 ID、任务消息隔离。
未运行真实数据 API 或真实模型分类/解释评估。
本轮不改 Supervisor、Planner、Composer 或 UI；父图仍将 analytics 返回 unsupported。
下一步单独实现 Supervisor 的 Analytics dispatch、数据引用交接及 AnalysisStore 注入，
之后适配 Composer 和图表展示；报告子图内部仍保持不变。


## Analytics 方法型 skill（2026-11-12 已实现）

方法文件位于 `research_skills/analytics-methodology/SKILL.md`，属于应用运行时资源，
不安装到开发者个人 Codex skills，也不依赖客户端的斜杠命令。

覆盖四工具选择、先决数据、任务区间与基准确认、参数及产物复用、
fraction解释、模拟/短样本/估值口径限制、缺失数据要求与Strategy/Risk职责边界。
不重复维护计算公式实现，不赋予新工具权限，不改变输出schema或执行预算。

`src/stages/analytics.py:load_analytics_methodology()` 从基于模块位置的固定仓库路径读取，
移除可选frontmatter，正文作为独立SystemMessage进入Analytics上下文。
无模型控制的路径或动态skill搜索；每个有效可执行请求读取一次，不缓存，修改文件对下一次请求生效。
源schema和方法内容分别注入，不将方法文件当作str.format模板处理。

文件缺失、不可读、空正文或frontmatter未闭合时，返回methodology_unavailable，
不调用模型。无数据请求原本就不调用模型，直接返回缺失要求，无需读取方法文件。
部署必须携带research_skills目录，不能只复制src。

测试验证方法正文实际进入系统消息、原schema保留、加载不受cwd影响、
文件修改后重新读取、缺失/空文件处理。skill通过结构校验；未做真实模型效果对比。
尚未接Supervisor/UI的状态不变，原报告内部不改。


## 步骤6：共享存储与 Supervisor 接入（2026-11-12 已实现）

### 请求内存储

create_parent_graph() 和 create_response_graph() 的执行边界每请求新建 DatasetStore / AnalysisStore，
经configurable传入Supervisor及子图。两个实例在同请求的任务间共享，在不同请求间隔离，
不写入ParentState、提示词或任务结果。
直接调用Supervisor仍由调用方提供存储；无引用的Analytics任务可返回缺失要求而无需创建模型。

### 调度与交接

Supervisor新增analytics_graph可选注入，默认使用create_analytics_agent()，不再把analytics标为unsupported。
只有investment_strategy继续unsupported。现有顺序调度、partial允许继续、失败阻断下游规则不变。

src/analytics_handoff.py实现边界：
- 只从任务depends_on里的market_data / analytics结果收集dataset_refs；
  analytics前置结果另提供analysis_refs作为existing_analysis_refs。
- 引用按ID去重，在当前Store重新解析取canonical元数据，不从文本摘要猜数据，
  不授予未声明前置任务的数据，不从report内部拿数据或替换其研究阶段。
- analytics链的前置result携带其源dataset_refs，因此可沿显式依赖继续复用产物。
- task传原问题，subjects取canonical数据的symbol，time_range暂留空、assumptions暂为空；
  精确的时间/窗口/年化等参数从Planner传入仍属下一阶段，不宣称已完成结构化提取。
- 无数据引用仍调用Analytics的确定性缺失路径，返回partial和missing_data_requests，
  不自动采集、不重新规划、不把数据不足当作分析完成。

### 输出边界

AnalyticsResult先经Pydantic验证，结果声明的数据ID不得超出输入范围。
analysis_refs必须存在于当前AnalysisStore且其所有来源数据在输入范围。
边界再次从Store重建findings数值、单位、表格、chart_refs、有效假设和产物限制；
即使返回载荷携带篡改数值也不会作为canonical结果进入TaskResult。
重复、未知、过期或越界引用导致任务失败，独立任务继续，依赖任务阻断。
子图结构化错误保留；模拟数据、未定义指标、缺失要求或无产物不会升级为completed。
外层仍只向父图返回task_results、supervisor_status、supervisor_error。

### 未完成内容与验证

Planner专门的数据先决任务规划、Composer分析结果消费、Plotly图表/序列生命周期仍待下一步。
现有Composer尚不会展示Analytics findings；UI仅修正能力状态说明，未新增图表功能。
原报告内部未改。请求结束后完整图表序列未持久化，裸chart_refs不能跨请求解析。

测试覆盖依赖交接、产物复用、数据去重、假引用和篡改数值、无数据缺失路径、
失败/Strategy未接入、父图双Store隔离，以及父图→MarketData测试采集→真实Analytics计算结构的mock模型链路。
未调用真实模型或数据API。


## 步骤7a：Planner 数据依赖与 Composer 分析汇总（2026-11-12 已实现）

### Planner

生成计划时要求每个analytics任务直接依赖market_data或analytics任务。
检查在TaskPlan.validate_analytics_dependencies()执行，失败进入现有有界修正，耗尽则规划失败。
通用TaskPlan验证仍允许手工提交无依赖Analytics任务，使独立Supervisor可返回结构化缺失要求；
不把此回退误认为Planner已经提供数据。
拓扑检查只能证明存在可传引用的前置类别，不能证明模型选择了正确数据或采集区间。

Prompt明确要求历史表现/因子获取get_price_history数据，估值比较获取同观察日的get_valuation_snapshot，
基准比较采集用户指定基准与标的共同区间；不把最新价或近30日文本摘要当作完整历史数据。
以当前上海日期解释相对时间，区分去年自然年与过去一年；历史采集任务明确ISO起止日期。
基准/区间不明确且影响回答时澄清，不为所有任务发明默认基准。
同类多标的可共享采集，报告内部不重复拆成外部分析链，Strategy仍按类别规划但尚未接入。
文本会话摘要不是可复用dataset_id；跨请求不复用已失效引用。

PlanTask新增可选analytics_parameters，仅analytics类别允许包含：
subjects、time_range、assumptions（使用已有AnalyticsAssumptions的窗口/年化/no_fill约束）。
未指定时保留旧任务结构；TaskPlan.to_state / TaskResult.to_state 统一序列化可选参数，
不删除必需的error=None等字段。Supervisor将参数通过analytics_handoff传给子图；
用户未指定参数时继续由工具默认或子图选择，实际参数仍来自计算产物。
参数含义、实际日期覆盖与数据适配的完整语义正确性仍需后续真实模型评估。

### Composer

先验证统一TaskResult，再验证AnalyticsResult；AnalyticsFinding约束数值有限、类型与单位结构。
给模型的分析投影只包含解释、指标/表格、实际假设、来源元数据、样本/区间和缺失限制，
不包含完整图表序列、局部消息或报告正文。
模型仅汇总，不重新计算、填null或把低PE等同买入机会。

无论模型是否成功，确定性逐任务部分保留：
- 数值与单位，fraction转换百分数时同时保留原数值口径；percent不重复乘100。
- 比较表的公司、指标、定义与缺失原因，不为不适用指标填零。
- 分析区间、样本数（单位见实际假设）、requested/effective参数、来源与复权/数据模式。
- limitations、missing_information和missing_data_requests。

仅Analytics结果也可触发模型汇总，不再只显示完成状态；模型失败时fallback保留上述内容。
报告负载仍按原规则隐藏，模型不接收report正文。
UI本轮只更新能力说明，回答区域自然显示Composer新输出；Plotly图表与独立分析看板尚未实现。

### 验证

mock测试覆盖缺失数据依赖计划修正、仅report依赖拒绝、分析参数契约与适配、
当前日期/采集规则注入、指标/单位/来源/缺失信息展示、模型失败回退及非有限数值拒绝。
父图结构测试继续采用真实计算工具，检查最终回答含实际计算指标。
未进行真实模型规划质量或真实行情端到端评估；动态补数据重规划仍未实现。


## 步骤7b：分析看板与 Plotly（2026-11-12）

本节更新前文历史实施记录中的图表待办状态。独立展示模块为 `app/analytics_dashboard.py`，
Streamlit「分析与策略」页按任务展示指标卡、结果表与交互图表：累计价格收益、回撤、
标的/基准对照及已有因子序列；估值仅绘制单位和定义一致的有效观察值。
缺失值保留在表中，不填零；没有序列时不生成占位曲线。fraction 以百分比显示，percent 不重复缩放。
来源、数据模式、实际区间、复权、样本数、假设与限制一起展示，mock 数据显式提示。

Supervisor 在结果校验后通过 `analysis_artifacts` custom stream event 发送引用的规范产物快照。
完整序列不进入 ParentState、TaskResult 或 Composer 提示词。
UI 按 task_id / analysis_id 保存快照到 session_state，并校验产物身份和数据集范围。
重绘使用快照，不重新抓取或计算；新请求替换上一轮快照，新对话清空。
缺少快照时仍展示引用中的指标并提示图表不可用。该机制没有数据库或 checkpoint，
不承诺服务重启后的恢复或跨请求历史图表留存。

依赖新增 `plotly>=6.0,<7`。单元测试使用确定性测试产物，覆盖实际图表值、单位、
基准双曲线、估值缺失、任务隔离、自定义事件交接、重绘与新对话清理。
报告子图内部及四阶段输出展示保持原状，最终报告正文仍隐藏。
浏览器预览工具不可用，尚未完成浏览器截图视觉验收；未调用真实行情或 LLM。


## 行情回退与估值引用执行修正（2026-11-12）

真实复现东方财富 stock_zh_a_hist 返回 Push2RateLimitError，而新浪 stock_zh_a_daily 可返回同区间日线。
结构化个股历史采集在东方财富异常或空结果时回退新浪，保留请求区间与复权；新浪成交量已为股，
不再乘100，来源及链接记录实际供应商。指数路径不变，不回退模拟数据。
失败只暴露异常类名，不返回可能含敏感内容的原始异常文本。数据验证失败仍不注册数据集。

Analytics 明确 dataset_refs 是引用，pe_ttm/pb 是字段，PE_TTM/PB_MRQ 是口径。
估值任务仅持有2–20个估值快照、无既有产物、未调用工具而直接回答时，节点补发一次
compare_valuations 默认比较，以实际工具结果决定可比性；仍遵守数据范围和工具预算。
该保护不影响已有工具选择、输出修复或价格分析路径。工具返回后不重复补发。
报告子图内部保持不变。回归测试隔离真实API；真实接口探测单独执行。


### 股票代码格式兼容（2026-11-12）
共享股票解析支持600519.SH、sh600519、SH.600519及大小写变体，规范化为六位代码；
交易所与代码前缀冲突时拒绝，不从任意文本提取数字。Planner明确前复权=qfq、后复权=hfq、
不复权=none，避免混合描述；该提示不等于对真实模型规划质量的保证。
