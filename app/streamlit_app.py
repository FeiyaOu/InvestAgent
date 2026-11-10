# -*- coding: utf-8 -*-
"""
InvestAgent — Streamlit UI（多轮对话版）

混合型智能投研助手演示界面，支持多轮对话。
- 每个浏览器会话自动分配唯一 thread_id（MemorySaver 状态隔离）
- 对话历史面板展示历轮摘要
- "🔄 新对话"按钮重置 thread_id，开启全新会话
"""

from __future__ import annotations

import json
import os
import sys
import uuid

# 将项目根目录加入 Python 路径，确保 Streamlit Cloud 部署时 src 包可被正常导入
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import dotenv_values, load_dotenv
import streamlit as st

from src.tools import (
    USE_REAL_DATA_ENV,
    parse_bool,
    akshare_available,
    data_mode,
    set_use_real_data,
)

# 自动加载项目根目录的 .env 文件
_ENV_PATH = os.path.join(_project_root, ".env")
load_dotenv(dotenv_path=_ENV_PATH)


def _configured_use_real_data() -> bool:
    """toggle 的初始值取自 .env 文件本身，而不是进程 os.environ。

    os.environ 会被上一次（甚至其他浏览器会话的）toggle 写脏，
    直接拿它当默认值会让 .env 里的 USE_REAL_DATA=true 永远生效不了。
    """
    raw = dotenv_values(_ENV_PATH).get(USE_REAL_DATA_ENV)
    if raw is None:
        raw = os.getenv(USE_REAL_DATA_ENV)
    return parse_bool(raw, default=True)

# ============================================================
# 页面配置
# ============================================================

st.set_page_config(
    page_title="InvestAgent — 投研工作台",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# 会话状态初始化（多轮对话核心）
# ============================================================

if "thread_id" not in st.session_state:
    st.session_state["thread_id"] = str(uuid.uuid4())

if "conversation_history" not in st.session_state:
    st.session_state["conversation_history"] = []

if "turn_count" not in st.session_state:
    st.session_state["turn_count"] = 0

if "last_result" not in st.session_state:   # ← 新增：持久化最新运行结果
    st.session_state["last_result"] = None

if "last_eval_results" not in st.session_state:
    st.session_state["last_eval_results"] = None

if "query_input" not in st.session_state:
    st.session_state["query_input"] = ""

# toggle 的持久状态：首次进入按 .env 配置初始化，之后由 widget 自己维护
if "use_real_data" not in st.session_state:
    st.session_state["use_real_data"] = _configured_use_real_data()

# 每次脚本重跑（包括 st.rerun 之后）都先把会话选择同步进 os.environ，
# 这样工具层的读取不再依赖"侧边栏必须先渲染"这个隐式顺序。
set_use_real_data(st.session_state["use_real_data"])

# ============================================================
# 侧边栏：设置
# ============================================================

with st.sidebar:
    st.title("⚙️ 设置")

    def _on_data_mode_change() -> None:
        """toggle 改变时立刻把新值写进 os.environ，不等下一次脚本重跑。"""
        set_use_real_data(st.session_state["use_real_data"])

    st.toggle(
        "使用真实 AKShare 数据",
        key="use_real_data",          # 显式 key：状态存入 session_state，跨 rerun 不丢失
        on_change=_on_data_mode_change,
        help="关闭时使用 mock 数据（适合演示或网络不稳定时）。默认值来自 .env 的 USE_REAL_DATA。",
    )

    # 回显工具层实际生效的模式（读的是 src.tools，不是本地变量），
    # toggle 与真实行为不一致时一眼可见
    _mode = data_mode()
    if _mode == "real":
        _ak_ok, _ak_info = akshare_available()
        if _ak_ok:
            st.success(f"🟢 数据源：真实 AKShare（v{_ak_info}）")
        else:
            st.error(f"🔴 已选真实数据，但 akshare 不可用：{_ak_info}\n\n请执行 `pip install akshare`")
    else:
        st.info("🟡 数据源：模拟 mock 数据")

    with st.expander("🔍 数据源自检"):
        st.caption("直接调用工具层，确认返回的是真实行情还是 mock / 降级文本")
        if st.button("运行自检", use_container_width=True):
            from src.tools import (
                get_index_performance,
                get_macro_indicators,
                get_sector_performance,
                search_stock_news,
            )

            probes = [
                ("行业板块", lambda: get_sector_performance.invoke({"sector": "光伏"})),
                ("指数行情", lambda: get_index_performance.invoke({})),
                ("宏观指标", lambda: get_macro_indicators.invoke({})),
                ("市场新闻", lambda: search_stock_news.invoke({"keyword": "新能源"})),
            ]
            for name, probe in probes:
                with st.spinner(f"{name}..."):
                    try:
                        out = probe()
                    except Exception as e:  # 工具内部已兜底，这里只防御性兜一层
                        out = f"调用异常：{type(e).__name__}: {e}"
                st.markdown(f"**{name}**")
                st.caption(out[:400])

    st.divider()

    # ---- 多轮对话控制 ----
    st.markdown("**💬 当前会话**")
    thread_short = st.session_state["thread_id"][:8]
    st.caption(f"Thread: `{thread_short}...`")
    st.caption(f"第 {st.session_state['turn_count']} 轮")

    if st.button("🔄 新对话", use_container_width=True, help="重置会话，清除对话历史"):
        st.session_state["thread_id"] = str(uuid.uuid4())
        st.session_state["conversation_history"] = []
        st.session_state["turn_count"] = 0
        st.session_state["last_result"] = None
        st.session_state["last_query"] = ""
        st.session_state["last_eval_results"] = None
        st.session_state["execution_events"] = []
        st.rerun()

    st.divider()
    st.markdown("**关于本项目**")
    st.markdown("""
投研工作台展示数据证据、专家分析与报告。

- 普通问题：数据查询、分析、策略与风险
- 报告请求：完整研究与报告校验
- 当前引擎：原有双路径流程

会话内结果保留在内存中，刷新或服务重启后可能丢失。
    """)

    st.divider()
    with st.expander("📋 C1–C9 Spec 约束"):
        st.markdown("""
| 约束 | 内容 |
|---|---|
| C1 | 4个分析维度完整 |
| C2 | 摘要 ≥ 100 字 |
| C3 | 置信度 ∈ [0,1] |
| C4 | 评级为 buy/hold/sell |
| C5 | 来源 ≥ 3 个 |
| C6 | 风险因素非空 |
| C7 | 投资论点 ≥ 50 字 |
| C8 | 路由模式合法 |
| C9 | Reactive 回答非空 |
        """)

# ============================================================
# 主页面
# ============================================================

st.title("📊 InvestAgent · 投研工作台")
st.caption("查数据 · 做分析 · 比较策略 · 生成报告")
st.info("界面已按新工作流组织；任务拆解、Supervisor 专家调度与独立报告子图尚未接入。当前运行仍使用原有双路径引擎，分析问题也可能生成报告。")
with st.expander("工作流设计"):
    st.markdown("问题拆解 → Supervisor 调度 → 数据查询 / 量化分析 / 策略与风险 → 汇总回答。明确要求报告时，进入报告子图。")
    st.caption("新流程接入后，同一请求可包含多个任务，已完成的答案先展示，其他任务继续执行。")

# ---- 对话历史面板 ----
if st.session_state["conversation_history"]:
    with st.expander(f"💬 对话历史（{len(st.session_state['conversation_history'])} 轮）", expanded=False):
        for i, turn in enumerate(st.session_state["conversation_history"], 1):
            mode_icon = "⚡" if turn["mode"] == "reactive" else "🔬"
            rating = turn.get("rating", "")
            rating_str = f" → {rating.upper()}" if rating else ""
            st.markdown(f"**第{i}轮** {mode_icon} `{turn['mode']}`{rating_str}")
            st.caption(f"Q: {turn['query'][:60]}{'...' if len(turn['query']) > 60 else ''}")
            if turn.get("response_preview"):
                st.caption(f"A: {turn['response_preview'][:80]}...")
            st.divider()

# ---- 示例查询 ----
st.markdown("**快速示例：**")
col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("行情查询", use_container_width=True):
        st.session_state["query_input"] = "今天新能源板块行情如何？"

with col2:
    if st.button("生成报告", use_container_width=True):
        st.session_state["query_input"] = "请生成一份新能源行业未来一年的投资研究报告，重点关注光伏板块。"

with col3:
    if st.button("比较与分析", use_container_width=True):
        st.session_state["query_input"] = "茅台和五粮液现在什么价格？比较它们的估值，并分析未来一年的投资机会。"

with col4:
    # 追问按钮：只有在有历史时才有意义
    followup_disabled = len(st.session_state["conversation_history"]) == 0
    if st.button("↩️ 追问", use_container_width=True, disabled=followup_disabled,
                 help="针对上一轮分析结果提问"):
        st.session_state["query_input"] = "上述分析中，哪个风险因素最值得关注？请展开说明。"

st.divider()

# ---- 输入区 ----
user_query = st.text_area(
    "您想研究什么？",
    height=110,
    placeholder="可以询问行情、比较估值、分析风险；需要完整报告时，请明确写出生成投研报告。",
    key="query_input",
)

with st.expander("⚙️ 高级选项（可选）"):
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        research_topic = st.text_input("研究主题", placeholder="新能源行业")
    with col_b:
        industry_focus = st.text_input("行业焦点", placeholder="光伏")
    with col_c:
        time_horizon = st.selectbox("时间范围", ["中期", "短期", "长期"])

run_btn = st.button("🚀 运行研究任务", type="primary", use_container_width=True)

# 临时展示开关：只影响 UI，不改变报告生成和校验流程。
_SHOW_FINAL_REPORT = False


def _render_node_results(state: dict) -> None:
    """完整展示节点输出，不截断字段、不依赖报告是否生成成功。"""
    for key in ("perception_data", "world_model", "reasoning_plans", "selected_plan"):
        st.subheader(key)
        value = state.get(key)
        if value is None:
            st.info("尚未返回结果。")
        else:
            st.json(value, expanded=True)


# 结果容器在执行前创建，流式结果写入对应视图。
answer_tab, data_tab, analysis_tab, report_tab, trace_tab = st.tabs(
    ["回答", "数据与证据", "分析与策略", "节点结果", "执行记录"]
)
with answer_tab:
    live_answer = st.empty()
with data_tab:
    live_data = st.empty()
with analysis_tab:
    live_analysis = st.empty()
with report_tab:
    live_report = st.empty()
with trace_tab:
    live_trace = st.container()

if not st.session_state.get("last_result"):
    live_answer.info("提交一个问题开始研究。完成的回答会在这里展示。")
    live_data.info("尚无数据。运行后展示引擎实际返回的感知数据；历史价格与量化数据集待接入。")
    live_analysis.info("尚无分析。这里展示市场模型、候选策略与决策依据。")
    live_report.info("深度研究运行后，这里直接展示四个节点的完整输出；最终报告暂时隐藏。")

# ============================================================
# 运行 Agent — 使用 LangGraph stream() 实时展示每个节点进度
# ============================================================

# 节点名称 → UI 标签映射
_NODE_LABELS = {
    "assess":           "📍 [评估] 判断查询类型与复杂度",
    "perception":       "📡 [感知] 市场数据分析师收集市场数据",
    "modeling":         "🌍 [建模] 宏观经济学家构建市场模型",
    "reasoning":        "💡 [推理] 策略研究员生成候选投资方案",
    "decision":         "🎯 [决策] 投资委员会主席选择最优方案",
    "report":           "📄 [报告] 撰写专家生成投研报告",
    "validator":        "✅ [校验] 独立合规审查员检查报告",
    "reactive_agent":   "⚡ [反应] 处理简单查询",
    "tools":            "🔧 [工具] 调用 AKShare 市场数据",
    "extract_response": "💬 [提取] 整理最终回答",
}


if run_btn and user_query.strip():
    from src.agent import create_invest_agent

    # 兜底：运行前再同步一次数据模式，确保 stream() 期间工具读到的就是 toggle 的当前值
    set_use_real_data(st.session_state["use_real_data"])

    turn_num = st.session_state["turn_count"] + 1
    thread_id = st.session_state["thread_id"]

    # 构建初始 state（与 run_invest_agent 保持一致）
    initial_state = {
        "user_query": user_query.strip(),
        "research_topic": research_topic or user_query.strip(),
        "industry_focus": industry_focus or "",
        "time_horizon": time_horizon,
        "processing_mode": None,
        "query_type": None,
        "messages": [],
        "final_response": None,
        "perception_data": None,
        "world_model": None,
        "reasoning_plans": None,
        "selected_plan": None,
        "final_report": None,
        "validation_errors": None,
        "retry_count": 0,
        "current_phase": "assess",
        "error": None,
    }
    config = {"configurable": {"thread_id": thread_id}}

    # 注入 LangFuse 追踪（配置了 LANGFUSE_* 才启用）
    try:
        from src.evaluation.langfuse_tracing import get_langfuse_handler
        lf_handler = get_langfuse_handler()
        if lf_handler:
            config["callbacks"] = [lf_handler]
    except Exception:
        pass

    _mode_label = "真实 AKShare 数据" if data_mode() == "real" else "模拟 mock 数据"
    with live_trace.status(f"InvestAgent 运行中（第{turn_num}轮）· {_mode_label}...", expanded=True) as status:
        try:
            agent = create_invest_agent()
            accumulated_state = dict(initial_state)
            execution_events = []

            for event in agent.stream(initial_state, config=config, subgraphs=True):
                # Nested graph updates are (namespace, update); accept flat updates as well.
                namespace, chunk = event if isinstance(event, tuple) else ((), event)
                # The parent re-emits the entire child state on completion. Individual
                # child updates have already been rendered; avoid duplicate UI events.
                if not namespace and "report_workflow" in chunk:
                    accumulated_state.update(chunk["report_workflow"])
                    continue
                node_name = list(chunk.keys())[0]
                state_update = chunk[node_name]
                accumulated_state.update(state_update)
                execution_events.append({"step": len(execution_events) + 1, "node": node_name,
                                         "status": "失败" if state_update.get("error") else "已返回"})
                if state_update.get("final_response"):
                    live_answer.markdown(state_update["final_response"])
                if state_update.get("perception_data"):
                    live_data.json(state_update["perception_data"])
                for field in ("world_model", "reasoning_plans", "selected_plan"):
                    if state_update.get(field):
                        live_analysis.json(state_update[field])
                if any(key in state_update for key in ("perception_data", "world_model", "reasoning_plans", "selected_plan")):
                    with live_report.container():
                        _render_node_results(accumulated_state)
                if state_update.get("error"):
                    live_answer.error(state_update["error"])

                label = _NODE_LABELS.get(node_name, f"执行节点: {node_name}")

                # 为关键节点附加额外上下文
                if node_name == "assess":
                    mode = state_update.get("processing_mode", "")
                    topic = state_update.get("research_topic", "")
                    st.write(f"{label} → `{mode}` | 主题: {topic[:30]}")

                elif node_name == "reasoning":
                    plans = state_update.get("reasoning_plans", [])
                    count = len(plans) if isinstance(plans, list) else "?"
                    st.write(f"{label} → 生成 {count} 个候选方案")

                elif node_name == "validator":
                    errors = state_update.get("validation_errors", [])
                    phase = state_update.get("current_phase", "")
                    if not errors:
                        st.write(f"{label} ✓ 全部通过")
                    elif phase == "completed":
                        warn_types = [e["type"] for e in errors]
                        st.write(f"{label} ⚠️ 带质量警告完成: {warn_types}")
                    else:
                        retry = state_update.get("retry_count", 1)
                        st.write(f"{label} 🔄 触发重试 #{retry}")

                else:
                    st.write(label)

            # chunk 只含各节点的增量，messages 由 add_messages reducer 追加，dict.update 会覆盖成最后一批；
            # 从 checkpointer 取 reducer 合并后的完整 state
            final_state = {**accumulated_state, **agent.get_state(config).values}
            st.session_state["execution_events"] = execution_events
            status.update(
                label="研究未完成" if final_state.get("error") else "运行完成",
                state="error" if final_state.get("error") else "complete", expanded=False,
            )

        except Exception as e:
            status.update(label=f"❌ 运行出错: {e}", state="error")
            st.error(f"Agent 运行失败：{e}")
            st.stop()

    # 计算对话历史摘要
    processing_mode = final_state.get("processing_mode", "unknown")
    turn_record = {"query": user_query.strip(), "mode": processing_mode, "rating": "", "response_preview": ""}

    if processing_mode == "reactive":
        turn_record["response_preview"] = (final_state.get("final_response") or "")[:120]
    elif final_state.get("final_report"):
        try:
            r = json.loads(final_state["final_report"])
            turn_record["rating"] = r.get("overall_rating", "")
            turn_record["response_preview"] = r.get("investment_thesis", "")[:120]
        except Exception:
            pass

    # 持久化 → rerun（rerun 后展示块从 session_state 读取结果）
    st.session_state["last_result"] = final_state
    st.session_state["last_query"] = user_query.strip()
    st.session_state["last_eval_results"] = None   # 新一轮运行清除旧评估
    st.session_state["turn_count"] = turn_num
    st.session_state["conversation_history"].append(turn_record)
    st.rerun()

elif run_btn and not user_query.strip():
    st.warning("请输入查询内容后再运行。")

# ============================================================
# 展示最新结果（从 session_state 读取，rerun 后依然可见）
# ============================================================

if st.session_state.get("last_result"):
    from src.stages.reporter import validate_report

    final_state = st.session_state["last_result"]
    processing_mode = final_state.get("processing_mode", "unknown")

    if final_state.get("error"):
        with answer_tab:
            st.error(final_state["error"])
    with trace_tab:
        st.caption(f"当前引擎路径：{processing_mode} · 会话 {st.session_state['thread_id'][:8]}")
        if st.session_state.get("execution_events"):
            st.dataframe(st.session_state["execution_events"], hide_index=True, use_container_width=True)
        with st.expander("消息与工具调用"):
            for msg in final_state.get("messages", []):
                st.write(f"{type(msg).__name__}: {getattr(msg, 'content', '')}")
                if getattr(msg, "tool_calls", None):
                    st.json(msg.tool_calls)

    with answer_tab:
        st.caption(f"第 {st.session_state['turn_count']} 轮 · {st.session_state.get('last_query', '')}")
        if final_state.get("final_response"):
            st.markdown(final_state["final_response"])
        elif final_state.get("selected_plan"):
            st.markdown(final_state["selected_plan"].get("investment_thesis", ""))
            st.caption("以上为决策摘要。四个节点的完整输出见「节点结果」；最终报告暂时隐藏。")
        elif not final_state.get("error"):
            st.info("本轮未返回可展示的回答。")

    if not final_state.get("perception_data"):
        with data_tab:
            st.info("本轮没有结构化证据输出。数据查询的工具原文可在执行记录中查看。")
    if not any(final_state.get(k) for k in ("world_model", "reasoning_plans", "selected_plan")):
        with analysis_tab:
            st.info("本轮没有独立分析结果；量化分析工具尚未接入。")
    with report_tab:
        st.caption("临时调试视图：完整展示中间结果，最终报告与报告评估暂时隐藏。")
        _render_node_results(final_state)

    with data_tab:
        if final_state.get("perception_data"):
            evidence = final_state["perception_data"]
            st.subheader("市场证据")
            st.caption("当前为模型整理的数据摘要；来源、时间戳与原始数据集将随新工具接入。")
            st.markdown(evidence.get("market_overview", ""))
            if evidence.get("key_indicators"):
                st.dataframe(
                    [{"指标": key, "说明": value} for key, value in evidence["key_indicators"].items()],
                    hide_index=True, use_container_width=True,
                )
            if evidence.get("recent_news"):
                st.markdown("**近期消息**")
                for news in evidence["recent_news"]:
                    st.write(news)
            with st.expander("原始阶段输出"):
                st.json(evidence)

    with analysis_tab:
        if final_state.get("world_model"):
            with st.expander("🌍 阶段2：市场内部模型"):
                wm = final_state["world_model"]
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**市场状态：** {wm.get('market_state','N/A')}")
                    st.markdown(f"**经济周期：** {wm.get('economic_cycle','N/A')}")
                    st.markdown(f"**市场情绪：** {wm.get('market_sentiment','N/A')}")
                with c2:
                    for r in wm.get("risk_factors", []):
                        st.markdown(f"- {r}")

        if final_state.get("reasoning_plans"):
            with st.expander("💡 阶段3：候选投资方案"):
                for plan in (final_state["reasoning_plans"] if isinstance(final_state["reasoning_plans"], list) else []):
                    st.markdown(f"**方案 {plan.get('plan_id','N/A')}** — 置信度：{plan.get('confidence_level','N/A')}")
                    st.markdown(f"> {plan.get('hypothesis','')}")

        if final_state.get("selected_plan"):
            with st.expander("🎯 阶段4：投资决策"):
                sp = final_state["selected_plan"]
                st.markdown(f"**选定方案：** `{sp.get('selected_plan_id','N/A')}`")
                st.info(sp.get("investment_thesis", ""))
                st.markdown(f"**建议：** {sp.get('recommendation','N/A')} · **时间框架：** {sp.get('timeframe','N/A')}")

    with report_tab:
        if _SHOW_FINAL_REPORT and final_state.get("final_report"):
            st.subheader("📄 最终投研报告")
            try:
                report = json.loads(final_state["final_report"])
                st.download_button("下载报告 JSON", data=json.dumps(report, ensure_ascii=False, indent=2),
                                   file_name="investment_report.json", mime="application/json")
                errors = validate_report(report)
                if errors:
                    st.warning(f"⚠️ {len(errors)} 个质量问题：{[e['type'] for e in errors]}")
                else:
                    st.success("✅ 报告通过 C1–C7 全部约束校验")

                rating_color = {"buy": "🟢", "hold": "🟡", "sell": "🔴"}.get(report.get("overall_rating",""), "⚪")
                c1, c2, c3 = st.columns(3)
                c1.metric("整体评级", f"{rating_color} {report.get('overall_rating','N/A').upper()}")
                c2.metric("研究主题", report.get("research_topic","N/A"))
                c3.metric("时间范围", report.get("time_horizon","N/A"))

                for dim_name, dim_data in report.get("dimensions", {}).items():
                    label = {"fundamental":"基本面","market":"市场面","news":"消息面","analyst":"分析师"}.get(dim_name, dim_name)
                    conf = dim_data.get("confidence", 0)
                    with st.expander(f"{label}（置信度 {conf:.0%}）"):
                        st.write(dim_data.get("summary",""))

                if report.get("risk_factors"):
                    st.markdown("**⚠️ 风险因素：**")
                    for r in report["risk_factors"]:
                        st.markdown(f"- {r}")

                if report.get("sources"):
                    with st.expander("📚 数据来源"):
                        for s in report["sources"]:
                            st.markdown(f"- {s}")

                with st.expander("🔧 原始 JSON 报告"):
                    st.json(report)

            except json.JSONDecodeError:
                st.code(final_state["final_report"])

        retry_count = final_state.get("retry_count", 0)
        if retry_count > 0:
            st.info(f"ℹ️ Validator 触发了 {retry_count} 次重试")

    # ============================================================
    # 评估面板（OpenEvals，点击后按需运行）
    # ============================================================
    with report_tab:
        if _SHOW_FINAL_REPORT and final_state.get("final_report"):
            st.divider()
            st.subheader("📊 质量评估（OpenEvals）")
            st.caption("使用 Qwen 作为评判 LLM，评估报告的相关性、幻觉程度和投资论点质量")

            eval_col1, eval_col2 = st.columns([1, 3])
            with eval_col1:
                run_eval_btn = st.button("▶ 运行评估", use_container_width=True,
                                         help="需要 DASHSCOPE_API_KEY（约需10-20秒）")
            with eval_col2:
                if not os.getenv("DASHSCOPE_API_KEY"):
                    st.warning("需要 DASHSCOPE_API_KEY 才能运行评估")

            if run_eval_btn:
                from src.evaluation.openevals_eval import run_openevals

                with st.spinner("OpenEvals 评估中（Qwen-as-judge）..."):
                    eval_results = run_openevals(final_state)
                    st.session_state["last_eval_results"] = eval_results

            # 显示评估结果
            if st.session_state.get("last_eval_results"):
                er = st.session_state["last_eval_results"]
                ec1, ec2, ec3 = st.columns(3)

                def _score_display(result: dict, label: str, col):
                    score = result.get("score")
                    with col:
                        if score is None:
                            st.metric(label, "N/A")
                            st.caption(result.get("reasoning", "")[:100])
                        else:
                            score_pct = f"{score:.0%}" if isinstance(score, float) else str(score)
                            color = "🟢" if isinstance(score, float) and score >= 0.7 else (
                                "🟡" if isinstance(score, float) and score >= 0.4 else "🔴"
                            )
                            st.metric(label, f"{color} {score_pct}")
                            with st.expander("评审理由"):
                                st.write(result.get("reasoning", ""))

                _score_display(er.get("answer_relevance", {}), "回答相关性", ec1)
                _score_display(er.get("hallucination", {}),    "幻觉程度↓", ec2)
                _score_display(er.get("thesis_quality", {}),   "投资论点质量", ec3)

                st.caption("注：幻觉程度分数越低越好（0=无幻觉，1=大量虚构）")
