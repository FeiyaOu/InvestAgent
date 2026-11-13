# InvestAgent — LangGraph 投研助手

用户输入由 Planner 拆为任务，Supervisor 调度 Market Data / Analytics / Strategy / Report 子图，Composer 汇总结果。
数据查询、Analytics 和完整报告已接入调度；分析汇总与 Plotly 看板已接入，Strategy/Risk V1 已接入（约束检查与静态压力测试）。
原 Reactive 路径已移除。完整设计见 [主规格](spec/invest_spec.md) 与 [架构](spec/project-architecture.md)。

```text
用户输入 + 显式会话摘要 → Planner → Supervisor → Composer → 回答
                                    ├─ Market Data（LLM + ToolNode）
                                    ├─ Analytics（确定性计算与图表）
                                    ├─ Strategy/Risk（约束检查与静态压力测试）
                                    └─ Report（感知→建模→推理→决策→报告→校验）
```

Streamlit 展示逐任务结果与报告四个中间节点；生成后可在“报告中心”查看并下载Markdown/HTML。
报告仅保留当前会话最近结果，不提供长期分享链接，详见[报告交付规格](spec/report-delivery.md)。
没有 checkpoint 自动记忆；会话摘要仅存于当前浏览器会话，刷新或重启可能丢失。

## 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境（推荐 Python 3.11+）
python -m venv .venv
source .venv/bin/activate

# 安装依赖
make install       # 运行时依赖
make install-dev   # 含测试/lint 工具
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

```env
# 必填：通义千问 API Key
DASHSCOPE_API_KEY=your_key_here

# 可选：LangFuse 链路追踪
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com

# 可选：false 时使用 mock 数据（离线测试/演示）
USE_REAL_DATA=true
```

### 3. 启动 UI

```bash
make run
# 或直接：streamlit run app/streamlit_app.py
```

---

## 测试

```bash
make test                 # 运行全部测试
make test-reporter        # 仅报告结构合规测试（C1–C7）
make test-agent           # 仅路由行为测试（C8–C9）
make test-integration     # 端到端集成测试（需 DASHSCOPE_API_KEY）
```

测试设计原则：
- **单元测试** mock LLM，Stage 函数与 LLM 完全解耦，可在无网络环境运行
- **集成测试** 使用 `USE_REAL_DATA=false` + 真实 LLM，验证完整流程
- 每条 Spec 约束（C1–C9）都有对应测试类，约束变更必须同步更新测试

---

## 报告输出格式

报告任务的 `task_results[task_id]["result"]["final_report"]` 保留标准 JSON（非顶层返回字段）：

```json
{
  "research_topic": "新能源行业",
  "industry_focus": "光伏",
  "time_horizon": "中期",
  "report_date": "2026-07-08",
  "dimensions": {
    "fundamental": { "summary": "≥100字的基本面分析", "confidence": 0.85 },
    "market":      { "summary": "≥100字的市场行情分析", "confidence": 0.78 },
    "news":        { "summary": "≥100字的新闻舆情分析", "confidence": 0.72 },
    "analyst":     { "summary": "≥100字的分析师观点", "confidence": 0.80 }
  },
  "investment_thesis": "≥50字的核心投资逻辑",
  "supporting_evidence": ["证据1", "证据2", "证据3"],
  "overall_rating": "buy",
  "risk_factors": ["风险1", "风险2"],
  "sources": ["来源1", "来源2", "来源3"]
}
```

---

## Spec 约束速查

| 编号 | 约束 | 校验位置 |
|---|---|---|
| C1 | 报告包含全部4个 dimensions | `validator` 节点 |
| C2 | 每个 `dimension.summary` ≥ 100字符 | `validator` 节点 |
| C3 | 每个 `dimension.confidence` ∈ [0.0, 1.0] | `validator` 节点 |
| C4 | `overall_rating` ∈ {buy, hold, sell} | `validator` 节点 |
| C5 | `sources` ≥ 3项 | `validator` 节点 |
| C6 | `risk_factors` 非空 | `validator` 节点 |
| C7 | `investment_thesis` ≥ 50字符 | `validator` 节点 |
| C8 | 四类任务及有效依赖计划 | `test_agent.py` / `test_planner.py` |
| C9 | 父图 `final_response` 非空 | `test_agent.py` / `test_parent_graph.py` |

---

## Lint

```bash
make lint
# ruff check src/ tests/ + 自定义架构依赖检查（禁止反向依赖）
```

---

## 许可

MIT


## Python 公共入口

```python
from src.agent import run_invest_agent
state = run_invest_agent("查询茅台价格", conversation_context="此前讨论贵州茅台")
print(state["final_response"])
print(state["task_results"])
```

旧 processing_mode / 顶层 final_report / thread_id 记忆约定不再支持。

界面提供“回答 / 数据与分析 / 报告中心”三个结果视图；开发者调试默认收起。
六张示例卡片可填入问题后手动运行，边界与实验性问题在“更多测试场景”。
