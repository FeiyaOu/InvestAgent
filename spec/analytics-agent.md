# Analytics Agent 实施规格

日期：2026-11-12。方案已确认，分步建设。当前完成步骤1及步骤2的日线历史价格采集，尚无 Analytics Agent 或计算工具；财务/估值采集待补。

## 职责与依赖

Analytics 执行可复现的历史表现、基准、估值和因子计算，不提出未来投资建议或做组合优化。
未来投资机会属于 investment_strategy；需要定量依据时依赖 Analytics，
Analytics 缺少数据集时依赖 market_data。已有合适数据时不强制重复采集。
依赖按任务输入决定，不固定每次执行 market_data → analytics → strategy。
Strategy 还应接收相关原始定性证据，不能只依赖 Analytics 摘要。

## 分步实施

1. **数据契约与请求内存储：已完成**，见下节。
2. **日线采集已完成**：共享工具层新增结构化采集工具，Market Data 返回数据集引用；原报告工具保持兼容。财务/估值采集后续补齐。
3. TDD 实现 V1 计算工具，先表现与基准，再因子及估值。
4. 独立 Analytics 子图，采用局部状态、工具循环、预算和输出验证，修正阶段不重新执行工具。
5. 独立测试数值、图表产物来源、缺失数据与失败行为。
6. Supervisor 接入 Analytics 及 dataset / analysis 引用交接，暂不改报告内部。
7. Planner / Composer / UI 接入计划依赖、分析解释及 Plotly 图表。
8. 按数据成熟度建设 V2。

## V1 工具（待实现）

| 工具 | 内容 |
|---|---|
| analyze_price_performance | 区间收益、年化波动率、最大回撤、累计收益与回撤序列 |
| compare_with_benchmark | 相对表现、beta、相关性、tracking error、对齐比较序列 |
| compute_factors | 小范围明确目录：动量、波动、趋势和均线；不暴露大量独立指标工具 |
| compare_valuations | PE/PB/股息率、增长和盈利质量比较；不可用指标说明原因 |

pandas / NumPy 优先，TA-Lib 按具体指标需求后加。
收益年化、无风险利率、频率、缺失处理、复权口径、基准和有效样本数必须明确。
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
