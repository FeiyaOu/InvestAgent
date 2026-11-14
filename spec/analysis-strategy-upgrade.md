# 分析与策略能力升级规格（V2）

> 2026-11-14 起草并确认；阶段 1 已按 TDD 实现（未做真实数据验收，见文末交付记录）；阶段 2、3 为已确认方向，契约在各自开始前细化。
> 本文覆盖 Market Data / Analytics / Strategy/Risk / UI 的跨专家升级；各专家既有 V1 规格保持有效。

## 范围与原则

用户确认的能力（2026-11-14）：技术因子（RSI、MACD、布林带、换手率）、PS、同行 z-score、
组合风险（VaR/CVaR）、历史情景重演、最小方差/风险平价、调仓清单、净值与风险看板；
阶段 3 接入财务指标、机构持仓与研报评级表（仅结构化字段）。

明确不做：IC 加权因子合成、股吧情绪、固定权重综合买入评分、研报正文解读、利率冲击、
GBM 蒙特卡洛、最大夏普/有效前沿（无用户收益假设时）。行业约束/冲击待行业分类接入后另议。

沿用 V1 原则：
- 分工不变：Market Data 只采集；Analytics 只做基于数据集的确定性计算，不接触持仓；
  Strategy/Risk 负责持仓、约束与情景，持仓由代码注入，模型不可改写；UI 只读产物。
- 缺失不补零、不前视、不静默丢弃；不足样本返回 null 与原因。
- 数值来自工具产物；模型只选择工具与解释，Composer 不重算。
- 结果是"在给定数据与假设下的计算"，不是预测、概率或买卖建议。

## 阶段划分

| 阶段 | 内容 | 新数据源 |
|---|---|---|
| 1 | 换手率、PS；批量价格采集；RSI/MACD/布林带；收益矩阵与协方差；同行 z-score（技术、估值）；组合风险与 VaR/CVaR；历史情景重演；组合约束检查；看板 | 无 |
| 2 | 最小方差、风险平价（单票上限、不做空、最低持仓数、换手限制）；调仓清单；持仓饼图与调仓表 | 无 |
| 3 | 接口实测后接入：业绩报表与三大报表、机构持仓、研报评级表；z-score 增加基本面与情绪维度 | AKShare |

## 工具分配总表

| 专家 | 工具 | 阶段 | 类型 |
|---|---|---|---|
| Market Data | `get_price_history` 增加换手率 | 1 | 扩展 |
| Market Data | `get_valuation_snapshot` 增加 PS TTM | 1 | 扩展 |
| Market Data | `get_price_history_batch` | 1 | 新增 |
| Analytics | `compute_factors` 增加 rsi / macd_hist_pct / bollinger_pct_b / turnover | 1 | 扩展 |
| Analytics | `compare_valuations` 增加 ps_ttm | 1 | 扩展 |
| Analytics | `build_return_matrix` | 1 | 新增 |
| Analytics | `rank_peers` | 1 | 新增 |
| Strategy/Risk | `assess_portfolio_risk` | 1 | 新增 |
| Strategy/Risk | `replay_historical_scenario` | 1 | 新增 |
| Strategy/Risk | `evaluate_risk_constraints` 组合级约束 | 1 | 扩展 |
| Strategy/Risk | `optimize_portfolio`、`build_rebalance_plan` | 2 | 新增 |
| Market Data | `get_financial_report`、`get_institutional_holdings`、`get_analyst_ratings` | 3 | 新增 |
| Analytics | `compare_fundamentals`、`summarize_analyst_consensus`、`compute_holding_changes` | 3 | 新增 |

---

## 阶段 1 详细契约

### 1.1 数据契约：换手率与 PS（src/core/datasets.py、src/data/tools.py）

**换手率**
- `PriceRow` 增加 `turnover: float | None`（≥0，单位 fraction）。
- `PriceDataset` / `DatasetRef` 增加 `turnover_unit: Literal["fraction", "not_available"]`，
  默认 `not_available`；校验规则与 `volume_unit` 相同（有值必须有单位）。
- 东方财富 `stock_zh_a_hist` 的 `换手率` 为百分比，除以 100；新浪 `stock_zh_a_daily` 的
  `turnover` 已为 fraction（成交量/流通股本），流通股本为空时为 None。指数不提供换手率。
- 记录换算来源；不用成交量反推缺失换手率。

**PS**
- `MetricName` 增加 `ps_ttm`，单位 `multiple`，basis `PS_TTM`；来源为 `stock_value_em` 的 `市销率`。
- 非正 PS 与 PE 同样不进入相对比较。`compare_valuations` 的 allowed 与 known_bases 同步增加。

### 1.2 批量价格采集：get_price_history_batch（Market Data）

```text
get_price_history_batch(queries: list[str], start_date, end_date,
                        asset_type="stock", adjustment="qfq") -> str
```
- 2–20 个不重复标的，共用同一区间与复权口径；逐个复用 `get_price_history` 的采集与回退逻辑。
- 一次调用计为 1 次工具调用（预算按调用计）；每个成功标的各自注册一个 PriceDataset。
- 返回 `{"status": "available" | "partial" | "unavailable", "items": [{query, status, dataset_ref | error}]}`；
  部分失败不影响已成功标的，全部失败为 unavailable。
- Market Data 节点当前只收集单个 `dataset_ref`，需扩展为同时处理 `items[*].dataset_ref`。
- 新浪回退每个标的启动一个子进程，20 个标的全部回退时耗时显著；记录在 limitations。

### 1.3 因子扩展：compute_factors（Analytics）

因子计算抽为纯函数模块 `src/specialists/analytics/factors.py`，供 `compute_factors` 与 `rank_peers` 共用。

| 因子 | 定义 | 默认参数 | 单位 |
|---|---|---|---|
| `rsi` | Wilder 平滑 RSI | `rsi_window=14` | `index_0_100` |
| `macd_hist_pct` | (MACD − signal) / 收盘价；EMA 用 `adjust=False` | `12, 26, 9` | fraction |
| `bollinger_pct_b` | (P − 下轨)/(上轨 − 下轨)，中轨为 `window` 日均线，带宽 k 倍样本标准差 | `window`、`bollinger_k=2` | dimensionless |
| `turnover` | 最近 `window` 个观察值的平均换手率 | `window` | fraction |

- MACD 除以收盘价，使不同价位股票可比；原始 MACD、signal 与 histogram 序列保留在 series 供图表使用。
- 预热期不足时为 null：RSI 需 `rsi_window+1` 个价格，MACD 需 `slow+signal` 个，布林带需 `window` 个。
- 上下轨相等时 %B 为 null 并说明原因；换手率不可用时 `turnover` 为 null。
- assumptions 记录全部参数；新增参数有范围校验（与现有 window 校验风格一致）。

### 1.4 收益矩阵与协方差：build_return_matrix（Analytics）

```text
build_return_matrix(dataset_ids: list[str], config, min_observations=60, periods_per_year=252) -> str
```
- 输入 1–50 个不同标的的日频 PriceDataset；股票须为 qfq / hfq / total_return 且口径一致，
  拒绝未复权股票；币种一致；包含 mock 时写入 limitations。
- 对齐：取全部标的**共同交易日**（内连接）后计算简单日收益；不填充、不前推。
  assumptions 记录对齐前后各标的观察数与被剔除日期数。
- 共同收益观察数须 ≥ max(min_observations, 2 × 标的数)，否则 unavailable。
- 协方差：样本协方差（ddof=1），同时给出年化值（× periods_per_year）与相关系数；不做收缩估计。
- 产物：`table` 存每对标的的 daily_covariance / annualized_covariance / correlation；
  `metrics` 存各标的年化波动率；`series` 按标的存对齐后的日收益（供 Strategy 历史模拟）。
- 收益序列可能较大：Supervisor 的 `analysis_artifacts` 事件不携带该产物的收益序列，只携带矩阵表。

### 1.5 同行相对位置：rank_peers（Analytics）

```text
rank_peers(price_dataset_ids: list[str], valuation_dataset_ids: list[str], factors: list[str], config,
           window=20, rsi_window=14) -> str
```
- 维度：技术面（momentum、realized_volatility、rsi、macd_hist_pct、bollinger_pct_b、turnover）、
  估值（pe_ttm、pb、ps_ttm）。阶段 3 增加基本面与情绪维度。
- 同一因子须 ≥ 5 个有效值才计算，否则该因子为 null 并说明；标的总数上限 20。
- 价格类因子在全部价格数据集的**共同最后交易日**计算；估值类沿用 compare_valuations 的同日、同币种要求。
- 输出每个标的每个因子的：原始值、z-score（样本均值与 ddof=1 标准差）、百分位（并列取平均名次）、
  有效样本数、剔除原因。非正 PE/PB/PS 剔除。
- 不合成总分，不标注因子方向好坏，不排序推荐；limitations 固定包含
  "这是给定样本内的相对位置，不代表预测能力或投资价值；样本小时 z-score 不稳定"。

### 1.6 组合风险：assess_portfolio_risk（Strategy/Risk）

```text
assess_portfolio_risk(return_matrix_analysis_id: str, config) -> str
```
- 持仓来自运行时注入的 `Portfolio`；收益矩阵须为授权引用中的 `build_return_matrix` 产物，
  覆盖全部非现金持仓，`end_date` 不晚于持仓日期。缺任一持仓则 unavailable，不静默剔除。
- 组合日收益 = 收益矩阵 × 当前权重，现金收益为 0（**恒定权重回放**：每日再平衡到当前权重）。
  这是"当前组合在历史收益下的表现"，不是该组合的真实历史业绩，limitations 必须说明。
- 指标（损失以正数 fraction 表示，1 日持有期）：

| 指标 | 方法 | 最少收益观察数 |
|---|---|---|
| 组合年化波动率 | 样本标准差 × √periods_per_year | 20 |
| 回放净值最大回撤 | 恒定权重净值序列 | 20 |
| 历史 VaR 95% / 99% | 经验分位数 `np.quantile(method="linear")` 取负 | 100 / 250 |
| 历史 CVaR 95% / 99% | 不高于 VaR 阈值的收益均值取负 | 100 / 250 |
| 参数 VaR 95% / 99% | 正态：−(μ + zσ)，z 取常量 −1.6449 / −2.3263 | 20 |
| 参数 CVaR 95% / 99% | 正态：σ·φ(z)/α − μ | 20 |

- 样本不足的指标为 null 并说明；参数法注明"正态假设低估尾部风险"。阶段 1 只提供 1 日持有期。
- 净值序列存入 StrategyStore，通过新的 `strategy_artifacts` 自定义事件交给 UI，不进入图状态。

### 1.7 组合级约束：evaluate_risk_constraints（扩展）

- `max_portfolio_volatility`、`max_portfolio_drawdown` 不再固定返回 unknown：在授权引用中查找覆盖全部持仓的
  `build_return_matrix` 产物，调用与 1.6 相同的纯函数计算后比较；找不到时仍为 unknown 并说明原因。
- 组合风险纯函数放在 `src/specialists/strategy/portfolio_risk.py`，两个工具共用，不重复实现。

### 1.8 历史情景重演：replay_historical_scenario（Strategy/Risk）

```text
replay_historical_scenario(scenario_key: Literal["2008_gfc", "2015_crash", "2020_covid"], config) -> str
```
- 情景目录写死在代码中，模型只能选 key，不能自定日期（按上证综指收盘价高低点，2026-11-14 验收核对后更正）：

| key | 名称 | 区间 |
|---|---|---|
| `2008_gfc` | 2008 全球金融危机 | 2007-10-16 → 2008-11-04 |
| `2015_crash` | 2015 股灾 | 2015-06-12 → 2015-08-26 |
| `2020_covid` | 2020 新冠冲击 | 2020-01-13 → 2020-03-23 |

- 直接使用授权的 PriceDataset（不依赖收益矩阵）：每个持仓取区间内首个与最后一个交易日，
  计算区间收益与买入持有路径的最大回撤；组合收益 = Σ 权重 × 区间收益，现金收益 0。
- 任一非现金持仓在情景开始日尚未上市或数据未覆盖：列出可用持仓的个股结果与覆盖权重，
  **不计算组合收益**；阶段 1 不使用行业或指数代理。
- 可选：若同时提供基准指数数据集，附带同区间基准收益作为对照。
- 用户通过 `StrategyParameters.historical_scenarios: list[scenario_key]` 显式请求；
  有该字段时由代码确保调用对应工具（沿用 V1 显式约束的做法）。

### 1.9 StrategyStore 与结果契约

- `StrategyStore.put` 增加 `risk_results: list[dict]` 与 `series: dict[str, list[{date, value}]]`；
  `StrategyResult` 增加 `risk_results`。series 不进入父图状态与 Composer 输入。
- 有持仓且存在兼容收益矩阵时，由代码确保调用 `assess_portfolio_risk`。

### 1.10 编排层

**Planner**（规则加入 prompt 与校验示例）
- 组合风险：market_data（批量采集全部持仓同区间日线）→ analytics（build_return_matrix）→ strategy。
- 用户未指定回看区间时，组合风险默认回看 **2 年**（满足 99% VaR 的 250 个样本），
  question 中写明绝对起止日期，并作为显式假设展示。
- 历史情景：每个情景单独规划覆盖该区间的批量采集任务，strategy 依赖这些任务。
- 同行排名：market_data 批量采集价格（及估值快照）→ analytics（rank_peers）。

**Strategy handoff**：`strategy_inputs` 透传直接依赖中的 `build_return_matrix` 引用与价格数据集引用。

**Composer**（prompt 规则）
- "1 日 VaR95% = x" 表示历史上约 5% 的交易日亏损超过 x，不是最大可能损失。
- 恒定权重回放与情景重演不是真实历史业绩，也不预示未来。
- z-score 与百分位是样本内相对位置，不是评分或推荐。

### 1.11 UI（app/）

- Analytics 看板：因子排名表（按维度分组，显示原始值、z-score 与百分位）。
- Strategy 看板：组合净值曲线、风险指标卡（VaR/CVaR 标明方法与样本数）、情景重演表（含覆盖权重）。
- 数据来自 `analysis_artifacts` 与新增 `strategy_artifacts` 事件中的当前请求快照，不持久化。

### 1.12 实施顺序（每步先写失败测试）

1. 数据契约：换手率、PS（含单位换算与校验测试）。
2. `get_price_history_batch` 与 Market Data 节点的多引用收集。
3. `factors.py` 纯函数与 `compute_factors` 扩展（用已知序列核对 RSI/MACD/%B 数值）。
4. `build_return_matrix`（对齐、样本门槛、协方差与 numpy 结果一致）。
5. `rank_peers`（有效样本门槛、剔除规则、无总分）。
6. `portfolio_risk.py` 纯函数、StrategyStore 扩展、`assess_portfolio_risk`、组合级约束。
7. `replay_historical_scenario` 与 `historical_scenarios` 参数。
8. Planner / handoff / Composer。
9. UI 看板与 `strategy_artifacts` 事件。
10. 真实数据人工验收（单独记录，不进入单元测试）。

### 1.13 验收标准

- 单元测试全部 mock AKShare 与 LLM；每个新工具覆盖：正常值、样本不足、口径不一致、缺失持仓、mock 标记。
- 数值类工具用手算或 numpy/pandas 独立实现交叉核对。
- `pytest tests/ -q`、`python linters/check_agent_structure.py` 通过。
- 端到端（真实 key）至少覆盖：3 只持仓的组合风险、一个历史情景、5 只同行排名，记录耗时与失败原因。

### 1.14 阶段 1 交付记录（2026-11-14）

1.12 的第 1–9 步已完成，全部单元测试（471 个）、ruff 与结构 lint 通过。用户确认 1.6 恒定权重、1.8 情景区间与不使用代理、
1.10 默认回看 2 年、仅 1 日 VaR。与上文契约不同或需要说明的实现细节：

- MACD 参数固定为 12/26/9（`factors.MACD_SPANS`），未作为工具参数开放；RSI 窗口与布林带 k 可调。
- 工具参数的类型由 LangChain schema 先行校验：非整数窗口在 schema 层报错（ToolNode 转为可见工具错误），
  布尔值传给浮点参数会被 schema 转为数值；范围校验仍在工具内。
- rank_peers 百分位为 `rank(method="average", pct=True)`，即名次/样本数；assumptions 中显式记录 `composite_score: not_computed`。
- Analytics 节点的数据集授权检查扩展到 `price_dataset_ids`、`valuation_dataset_ids`；`window` 覆盖同样作用于 rank_peers。
- Strategy 新工具与 V1 一样全部由代码按输入强制调用，模型只生成解释：有持仓且存在兼容收益矩阵时调用
  `assess_portfolio_risk`；`historical_scenarios` 中每个 key 调用一次 `replay_historical_scenario`。
  默认工具预算由 12 次调至 16 次，以容纳约束 1 + 压力测试 ≤10 + 组合风险 1 + 情景 ≤3。
- StrategyStore 将 series 与产物分开存放，产物只带 `series_keys`；`get_series` 按 scope 校验。
  Supervisor 通过 `strategy_artifacts` 事件把序列交给 UI；`analysis_artifacts` 事件中收益矩阵产物的 series 置空。
- 组合约束检查在没有收益矩阵引用时直接返回 unknown，不要求配置 analysis_store。
- 情景覆盖判定：区间内首个交易日不晚于开始日 + 7 天、最后交易日不早于结束日 − 7 天（`COVERAGE_TOLERANCE_DAYS`）。
- 顺带修复：Strategy 看板原先直接格式化 `portfolio_return`，为 None 时页面会崩溃。

未完成：第 10 步真实数据人工验收（需真实 DashScope key 与网络）；情景区间日期仍需用真实上证综指数据核对；
Planner 新规则只做了契约测试，尚未用真实模型验证拆解是否稳定。

### 1.15 真实数据验收记录（2026-11-14 第一轮）

脚本：会话 scratchpad 中的 `acceptance/run_acceptance.py`（真实 DashScope + AKShare，不进仓库与单元测试）。
总耗时 475s（工具探测约 105s）。

| 场景 | 判定 | 耗时 | 结论 |
|---|---|---|---|
| S1 3 只持仓组合风险 | 通过 | 71s | 拆解为批量采集 → 收益矩阵 → 策略，与预期一致；默认回看 2 年生效（484 个收益观察值），VaR/CVaR 均有值 |
| S2 2015 股灾重演 | 未通过（行为符合契约） | 82s | 长江电力 2015-06 起停牌重组，区间内无数据；按契约不给组合收益、不用代理，茅台/招行正常回放 |
| S3 5 只白酒同行排名 | 判定通过但结果不可信 | 217s | Planner 将山西汾酒写成 600829（应为 600809），整条链路采集并展示了错误公司的数据 |

工具探测：换手率 28/28 有值且为 fraction；PS TTM 可取（茅台 10.29）；东方财富历史行情全部失败并回退新浪，
单只约 12–13s，5 只两年日线批量 67s；估值接口（stock_value_em）正常。

情景日期按上证综指**收盘价**核对：2015 正确；2008 结束日应为 2008-11-04（收盘 1706.70，10-28 为盘中低点）；
2020 应为 2020-01-13（3115.57）→ 2020-03-23（2660.17）。

发现与修复优先级：

| 优先级 | 问题 | 修复方向 |
|---|---|---|
| P0 | 名称→代码依赖模型记忆；采集工具对六位代码不做核对，错误代码会贯穿整条链路 | 名称与代码交叉校验，数据集携带证券简称（见 1.16） |
| P1 | Composer 写出"RSI 超过 60 处于超买区间"与名次表述；技术因子解读规则只在 Analytics skill 中 | Composer prompt 补充技术因子与排名规则 |
| P1 | 用户要求"近 30 日动量"，Planner 未写入 `analytics_parameters.window`，实际按 20 日计算却被标为 30 日 | Planner 规则：用户指定窗口须写入参数 |
| P1 | 2008、2020 情景日期按盘中而非收盘价 | 更正目录日期 |
| P2 | S2 多规划注定失败的收益矩阵任务；S3 多拆逐只因子与估值比较两步（约 36s） | Planner 规则：情景重演不建矩阵；rank_peers 直接依赖采集任务 |
| P2 | 批量采集串行，且东财连续失败仍逐只先试东财 | 批量并行（新浪路径已在子进程中隔离）；评估回退顺序 |
| P3 | 5 个样本中 PE 873 倍的极端值使 z-score 失去区分度 | 稳健 z-score（中位数/MAD）或极端值提示 |
| P3 | 停牌与未上市同样视为未覆盖 | 停牌期间收益记 0 并标注复牌补跌风险，另行设计 |

### 1.16 P0 修复：证券名称与代码交叉校验

- 权威代码表：仓库快照 `src/data/a_share_directory.json`（沪市主板、科创板与深市 A 股，含 `generated_at`），
  由 `scripts/refresh_security_directory.py` 离线生成，全部来源成功且不少于 4000 只才原子替换旧快照。
  请求路径只读快照、每进程读一次，不联网；快照缺失或损坏时回退静态常用表并标为未核对，局限说明注明快照日期。
- 修订原因（第二轮验收，2026-11-14）：最初设计在请求时调用 `stock_info_a_code_name()`。实测上交所列表分页抓取
  主板约 51s、科创板约 43s，且中途常失败；失败不缓存导致每只股票都重试，批量 5 只由 67s 增至 214s，
  代码表拿不到时"山西汾酒(600829)"按未核对放行。东方财富逐只查询接口同样超时。故改为离线快照。
- 采集工具接受"名称"、"代码"或"名称(代码)"。同时给出名称与代码且不一致时返回 unavailable，
  错误信息给出名称对应的正确代码，由 Market Data 在预算内重试；不静默改用任一方。
- 仅有名称时按代码表精确匹配简称（静态表中的常用简称如"茅台"仍可用）；无法唯一解析时失败，不猜测。
- 数据集新增 `security_name`（来源于代码表；无法获取时为 None 并在 limitations 中注明未核对）。
- Planner 与 Market Data prompt 要求股票以"名称(代码)"形式书写和传参；Composer 只使用数据集中的证券简称。

### 1.17 P1 修复（2026-11-14）

- Composer prompt 提为模块常量 `_SYSTEM`，新增：不把 RSI 数值称为超买/超卖、不把 MACD 柱或布林带位置说成买卖信号；
  不用“第1名/排名第一/领先”等名次表述，改用样本内相对高低与百分位；因子窗口以计算假设中的 window/rsi_window 为准。
- Planner：用户明确给出因子窗口（如“近30日动量”）时写入 `analytics_parameters.assumptions.window`，
  按交易日观察值数解释，question 中的窗口须与参数一致。
- 情景目录按上证综指收盘价更正：`2008_gfc` 2007-10-16 → 2008-11-04；`2020_covid` 2020-01-13 → 2020-03-23；2015 不变。
  Planner prompt 中的区间同步更新。
- 以上为 prompt 与目录改动，单元测试只能校验规则存在与日期；实际效果需真实模型重跑验收确认。

### 1.18 第三轮验收记录（2026-11-14，P0 快照版 + P1）

总耗时 463s。第二轮因请求时拉代码表导致反复重试，已中止，不计结果。

- P0 拦截生效：`山西汾酒(600829)` 0s 内被拒（返回 600809 提示，未登记数据集）；茅台简称核对为“贵州茅台”；
  单只 11s、批量 5 只 62s，恢复第一轮水平。情景日期更正后三段均与收盘价高低点吻合。
- S1 通过（97s）。S2 仍因长江电力停牌未覆盖（符合契约）；本轮 Planner 未再多建收益矩阵。
- S3 未通过：Planner 再次写成 600829（稳定的记忆错误）；两个采集任务均拦截，回答明确告知代码错误，
  但 Market Data 未按提示重试，汾酒缺席。P1 窗口写入生效（window=30），但 Planner 把“近30日”当成采集区间，
  只取 22 行，不足以计算 30 日动量；Planner 未规划 rank_peers；技术分析任务以 dataset_scope_error 失败（请求细节未记录）；
  五粮液批量采集偶发失败一次。回答未出现超买/超卖/名次表述，但写出“PB 最高显示资产重估溢价”，违反既有规则。

后续修复：
- P0b：持仓 `Position.symbol` 必须是代码，Planner 无法只写名称。改为 prompt 优先只写名称，并在规划阶段用快照
  确定性核对计划中所有“名称(代码)”与持仓（新增可选 `Position.name`），不一致时把正确代码作为修正反馈。
- P1b：采集区间与因子窗口分离，技术因子默认采集 1 年。
- P1c：“相对位置”规划 rank_peers，直接依赖采集任务，并给出示例。
- P1d：Analytics 数据集越权时发出诊断事件（工具名、参数键、越权引用数），验收脚本记录。
- P2：Composer 输出的确定性禁用表述检查。

### 1.19 阶段 1 收尾状态（2026-11-14）

P0b、P1b–P1d 已实现（501 个单元测试通过）。第四轮验收因运行中机器休眠、网络中断而无效（新浪子进程与 DashScope 均失败），
不计结果；随后单独调用 Planner 确认代码与模型均正常，S3 样本中 Planner 只写名称、采集 1 年、window=30，身份校验通过。
用户决定暂停验收，进入阶段 2。遗留问题（后续处理）：

- P1c 部分生效：规划了 rank_peers，但仍多拆技术面、估值两个中间排名任务。
- Planner 把 PS 口径写成“PS FY”，工具实际提供 PS TTM。
- 第三轮 Analytics `dataset_scope_error` 的原因待用 `analytics_diagnostic` 事件确认。
- P2：Composer 输出的确定性禁用表述检查（如“资产重估溢价”）；批量采集并行化；东财历史接口持续失败时的回退顺序。
- P3：极端值下的稳健 z-score；停牌持仓的情景重演处理。
- P0b、P1b–P1d 尚无有效的真实数据验收，进入下一次验收时一并确认。

---

## 阶段 2 详细契约（2026-11-14 起草，待确认后按 TDD 实施）

### 2.1 范围与原则

两个 Strategy/Risk 工具：`optimize_portfolio`（最小方差、风险平价）与 `build_rebalance_plan`（调仓执行清单）。
沿用阶段 1：工具由代码按显式输入强制调用；输入由运行时注入、模型不可改写；输出是"给定数据、假设与约束下的数学解/
执行计算"，不是推荐、预测或买卖建议。不做最大夏普/有效前沿（没有可信的预期收益）、行业约束、杠杆与做空。

### 2.2 输入契约（StrategyParameters 扩展）

```text
optimization:                          # 有此字段才执行优化
  objective: "min_variance" | "risk_parity"
  max_weight: float | None             # 单票上限，(0, 1]
  min_weight: float = 0                # 入选资产的权重下限，[0, max_weight)
  min_holdings: int | None             # 最低持仓数，见 2.4
  max_turnover: float | None           # 单边换手上限 Σ|w − w0|/2，需当前持仓
  target_cash_weight: float | None     # 未给时沿用当前持仓现金权重，无持仓时为 0
  candidates: list[名称或代码]          # 候选池；未给时用当前持仓

holdings:                              # 有此字段才生成调仓清单
  as_of_date, currency=CNY
  cash_amount: float >= 0              # 现金金额（元）
  positions: [{symbol, name?, shares: int >= 0}]
```

- `holdings` 与阶段 1 的 `portfolio`（权重）是两种输入：给了 holdings 时，当前权重由"股数 × 最新收盘价 + 现金"推出，
  不再要求用户另报权重；两者同时给出且不一致时以 holdings 为准并在 limitations 中说明。

### 2.3 optimize_portfolio（Strategy/Risk）

- 输入：授权的 `build_return_matrix` 产物，必须覆盖全部候选资产；当前权重来自 portfolio 或 holdings（换手约束需要）。
- 协方差：收益矩阵的样本协方差（年化）。可选 `covariance: "sample" | "ledoit_wolf"`，默认 sample；
  Ledoit-Wolf 收缩用 numpy 自行实现，不引入 scikit-learn。
- 目标：
  - `min_variance`：min wᵀΣw。
  - `risk_parity`（等风险贡献）：min Σᵢ(RCᵢ − σ²/N)²，RCᵢ = wᵢ(Σw)ᵢ；有上限等约束时可能无法完全相等，输出实际风险贡献。
- 约束：Σw = 1 − target_cash_weight；0 ≤ w ≤ max_weight；不做空；换手约束用辅助变量 w = w0 + u − v（u, v ≥ 0）线性化。
- 求解：`scipy.optimize.minimize(method="SLSQP")`，多个起点（等权、当前权重、逆波动率）取最优可行解；
  不可行或未收敛时返回 infeasible 与原因（例如"单票上限 × 资产数 < 1 − 现金"），不返回近似违约解。
- 输出（risk_results 风格的 `optimization_results`）：目标权重、当前权重、Δw、换手率、组合年化波动、
  各资产风险贡献占比、是否触及上限/换手约束、求解状态与迭代信息；series 无。
- limitations 固定包含："基于历史协方差的数学解，不预测收益；样本期变化或极端行情下结果可能大幅不同；不构成配置建议。"

### 2.4 最低持仓数的语义

精确的"至少 k 只"是基数约束（混合整数规划），SLSQP 无法直接求解。阶段 2 采用：
- `min_holdings ≤ 候选数` 必须成立，否则 infeasible；
- 若同时给出 `min_weight > 0`：所有候选资产权重 ≥ min_weight，持仓数即候选数，天然满足；
- 若未给 `min_weight`：求解后统计权重 ≥ 0.5% 的资产数，不足 k 时以 `min_weight = 0.5%` 对全部候选重解一次；
  仍不满足则 infeasible。结果中标明采用的处理方式。

### 2.5 build_rebalance_plan（Strategy/Risk）

- 输入：holdings、`optimize_portfolio` 产物（目标权重）、覆盖全部相关标的的价格数据集（取最新收盘价及其日期）。
- 计算：总资产 = Σ股数×收盘价 + 现金；目标股数 = 目标权重 × 总资产 / 价格，按交易单位取整：
  主板与创业板 100 股一手；科创板（688）最少 200 股、之后 1 股递增；卖出可包含不足一手的零股（须一次卖出）。
- 费用（均为可调参数，默认值在结果中展示，需用户按自己的券商核对）：
  佣金万分之 2.5、单笔最低 5 元；印花税 0.05%（仅卖出）；过户费 0.001%（双边）；滑点 10 个基点（双边，按成交额计）。
- 先卖后买；买入受"现金 + 卖出净额"约束，不足时按目标差额比例缩减买入并说明，不产生负现金。
- 输出：每个标的的当前股数、目标股数、交易股数（买/卖）、参考价及日期、成交额、各项费用；合计费用、
  调仓后现金、调仓后实际权重与目标权重的偏差、实际换手率。
- limitations："参考价为数据集最新收盘价，不是实时可成交价；费用为默认假设；未考虑涨跌停、停牌与流动性；不构成交易指令或建议。"

### 2.6 编排、展示与依赖

- 新增依赖 `scipy`（只在 `strategy/optimizer.py` 中使用）。
- Strategy 强制调用：有 optimization 且存在覆盖候选的收益矩阵时调用 `optimize_portfolio`；
  另有 holdings 时在优化后调用 `build_rebalance_plan`。默认工具预算按需上调。
- Planner：组合优化链路为 market_data（批量采集候选 2 年日线）→ analytics（build_return_matrix）→ strategy；
  optimization/holdings 只抄录用户明确给出的约束与持仓，不替用户设定上限。
- Composer：优化权重是给定假设下的数学解，不称为推荐配置；调仓清单是执行计算，不称为交易建议；必须说明费用为默认假设。
- UI：目标权重饼图（与当前权重对比）、风险贡献条形图、调仓清单表与费用合计。

### 2.7 实施顺序（每步先写失败测试）

1. 输入契约：optimization / holdings 及其校验。
2. `strategy/optimizer.py` 纯函数：最小方差、风险平价、换手线性化、多起点与不可行判定（与解析解或枚举结果交叉核对）。
3. `optimize_portfolio` 工具、StrategyStore/StrategyResult 增加 `optimization_results`。
4. 交易单位与费用纯函数、`build_rebalance_plan` 工具。
5. Strategy 强制调用、预算、交接与结果汇总。
6. Planner / Composer 规则。
7. UI 看板。
8. 真实数据验收（组合优化 + 调仓各一个场景）。

## 阶段 3 方向（开始前做接口实测）

数据源定为 AKShare（不引入 Baostock），源码核查（AKShare 1.20.25）结果：
- `stock_yjbb_em(date=报告期)`：全市场截面，含 ROE、毛利率、营收/利润同比、每股经营现金流、EPS、
  所处行业与"最新公告日期"。该日期可能是更正公告日，偏保守但非严格 point-in-time。
- `stock_zcfz_em` / `stock_lrb_em` / `stock_xjll_em`：三大报表截面，含资产负债率与"公告日期"；
  ROA 由净利润/总资产计算。
- 新浪 `stock_financial_analysis_indicator` 只有报告期，不使用。
- 缺公告日时以法定披露截止日为 available_at（一季报 4/30、半年报 8/31、三季报 10/31、年报次年 4/30）。
- 截面接口单次返回全市场，请求内按报告期缓存。
- 机构持仓（十大流通股东、基金持仓）与研报评级表接口在实测时确认字段与披露滞后。
