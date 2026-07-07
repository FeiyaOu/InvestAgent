# AKShare 数据调用设计

> 本文档说明 InvestAgent 中 AKShare 数据的调用位置、调用方式、数据内容以及设计原则。

---

## 核心原则

**AKShare 只在工具层调用，后续推理阶段不再碰外部数据。**

数据收集（感知阶段 + Reactive 工具）与分析推理（建模/推理/决策/报告）严格分离。
如果需要替换数据源（如接入 Wind、Tushare），只需修改 `src/tools.py`，Agent 架构不变。

---

## 调用位置：两条路径

### 路径一：Deliberative 路径 — 感知阶段直接调用

`src/stages/perception.py` 在调用 LLM 之前，**确定性地调用全部4个工具**，无需 LLM 决策：

```python
def perception(state: InvestAgentState) -> dict:
    # Step 1：直接调用工具获取原始市场数据（确定性，每次都调这4个）
    sector_data = get_sector_performance.invoke({"sector": state["industry_focus"]})
    index_data  = get_index_performance.invoke({})
    macro_data  = get_macro_indicators.invoke({})
    news_data   = search_stock_news.invoke({"keyword": state["research_topic"]})

    # Step 2：把4份原始数据喂给 LLM，综合整理为结构化 PerceptionOutput
    chain = _create_chain()
    result = chain.invoke({
        "sector_data": sector_data,
        "index_data":  index_data,
        "macro_data":  macro_data,
        "news_data":   news_data,
        ...
    })
```

AKShare 数据是 LLM 分析的原材料，LLM 的职责是将原始数据综合整理为结构化感知报告。

### 路径二：Reactive 路径 — LLM 自主决定调哪个工具

`src/agent.py` 的 `reactive_agent` 节点将工具绑定给 LLM，**LLM 自己决定是否调用、调哪个**：

```python
def reactive_agent(state: InvestAgentState) -> dict:
    llm_with_tools = ChatTongyi(...).bind_tools(INVEST_TOOLS)  # 告知 LLM 可用工具
    response = llm_with_tools.invoke(messages)
    # LLM 可能输出 tool_calls → ToolNode 执行 → 回到 reactive_agent（有向环①）
    # LLM 也可能直接回答 → extract_response → END
```

例：用户问"今天新能源板块怎样" → LLM 判断需要数据 → 自主调 `get_sector_performance("新能源")` → 得到结果 → 生成回答。

---

## 4个工具及数据内容

| 工具函数 | AKShare 接口 | 读取内容 | 适用路径 |
|---|---|---|---|
| `get_sector_performance(sector)` | `stock_board_industry_summary_ths()` | 指定行业板块涨跌幅、成交额、主力净流入 | Deliberative + Reactive |
| `get_index_performance()` | `index_zh_a_hist()` | 上证指数、创业板指近期行情（OHLCV）| Deliberative + Reactive |
| `get_macro_indicators()` | `macro_china_pmi_yearly()` | 制造业 PMI、非制造业 PMI | Deliberative + Reactive |
| `search_stock_news(keyword)` | `stock_news_em()` | 与关键词相关的近期市场新闻标题 | Deliberative + Reactive |

---

## 数据流向

```
AKShare
  ├─ get_sector_performance(industry_focus) ─┐
  ├─ get_index_performance()                 ├─→ [perception 节点]
  ├─ get_macro_indicators()                  ┤   LLM 综合 → PerceptionOutput
  └─ search_stock_news(research_topic)      ─┘       ↓
                                                 [modeling]   ← 纯 LLM，读 perception_data
                                                 [reasoning]  ← 纯 LLM，读 world_model
                                                 [decision]   ← 纯 LLM，读 reasoning_plans
                                                 [report]     ← 纯 LLM，读全部
                                                 [validator]  ← 校验，不调外部数据

  同一套工具也绑定给 reactive_agent（INVEST_TOOLS）
  → LLM 按需自主调用，触发有向环①
```

---

## Fallback 与数据模式开关

每个工具都有两层保护：

```python
def get_sector_performance(sector: str) -> str:
    # 层1：USE_REAL_DATA 开关（每次调用时读取，支持测试 monkeypatch）
    if not _should_use_real_data():
        return f"{sector} 板块（模拟数据）：涨跌幅 +2.31%，..."

    # 层2：网络异常 fallback（不崩溃 Agent，返回提示文本继续推理）
    try:
        import akshare as ak
        ...
    except Exception as e:
        return f"{sector} 数据暂时无法获取（{type(e).__name__}），请基于已有信息分析。"
```

| 环境变量 | 行为 |
|---|---|
| `USE_REAL_DATA=true`（默认）| 调用真实 AKShare，需要网络 |
| `USE_REAL_DATA=false` | 返回预设 mock 数据，零网络依赖 |
| 测试层 | `monkeypatch.setenv("USE_REAL_DATA", "false")`，单元测试零网络 |

---

## 扩展说明

**为什么用 AKShare 而不是 mock 数据？**

AKShare 完全免费、无需 API key，直接 `pip install akshare` 即用。
相比 mock 数据，真实 AKShare 数据让演示更有说服力，同时 fallback 机制保证网络不稳定时 Agent 不崩溃。

**如何替换为其他数据源？**

只需修改 `src/tools.py` 中各工具函数的实现体，保持函数签名和返回格式（字符串）不变，Agent 架构完全不需要修改。LangGraph 的工具协议与数据来源无关。

**后4个阶段为什么不再调 AKShare？**

建模、推理、决策、报告阶段处理的是感知阶段已经整理好的结构化数据（`perception_data`, `world_model` 等），属于纯 LLM 推理，不需要再获取新数据。数据收集和推理分离是正确的分层设计。
