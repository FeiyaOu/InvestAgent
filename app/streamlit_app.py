"""Parent-graph research UI; explicit session summaries, no checkpoint memory."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import dotenv_values, load_dotenv
import streamlit as st

from src.tools import USE_REAL_DATA_ENV, parse_bool, data_mode, set_use_real_data

_ENV_PATH = os.path.join(_project_root, ".env")
load_dotenv(_ENV_PATH)
_SHOW_FINAL_REPORT = False
_REPORT_FIELDS = ("perception_data", "world_model", "reasoning_plans", "selected_plan")
_LABELS = {"completed": "已完成", "partial": "部分完成", "failed": "失败",
           "unsupported": "尚未接入", "blocked": "前置任务不可用"}

st.set_page_config(page_title="InvestAgent — 投研工作台", page_icon="📊", layout="wide")
# Invalidate session objects from the old dual-path UI on hot reload.
if st.session_state.get("ui_version") != 2:
    st.session_state.update(ui_version=2, conversation_history=[], last_result=None,
                            execution_events=[], report_progress={}, turn_count=0)
for key, default in {"conversation_history": [], "last_result": None, "execution_events": [],
                     "report_progress": {}, "turn_count": 0, "query_input": ""}.items():
    if key not in st.session_state:
        st.session_state[key] = default
if "use_real_data" not in st.session_state:
    raw = dotenv_values(_ENV_PATH).get(USE_REAL_DATA_ENV, os.getenv(USE_REAL_DATA_ENV))
    st.session_state["use_real_data"] = parse_bool(raw, default=True)
set_use_real_data(st.session_state["use_real_data"])


def _render_nodes(payload):
    for field in _REPORT_FIELDS:
        st.subheader(field)
        if payload.get(field) is None:
            st.info("尚未返回结果。")
        else:
            st.json(payload[field], expanded=True)


def _render_tasks(state):
    plan = state.get("plan") or {}
    records = state.get("task_results", {})
    rows = [{"task_id": t["task_id"], "类别": t["category"], "问题": t["question"],
             "依赖": ", ".join(t["depends_on"]),
             "状态": records.get(t["task_id"], {}).get("status", "pending")}
            for t in plan.get("tasks", [])]
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.info("尚无可执行任务。")


def _render_results(state, progress):
    records = state.get("task_results", {})
    with answer_tab:
        if state.get("final_response"):
            st.markdown(state["final_response"])
        elif records:
            for ident, record in records.items():
                st.markdown(f"**{ident} · {_LABELS.get(record['status'], record['status'])}**")
                if record["category"] == "market_data":
                    st.write((record.get("result") or {}).get("answer", ""))
        else:
            st.info("等待规划与任务结果。")
        if state.get("planning_status") == "needs_clarification":
            st.info("请补充信息后再次提交，当前未执行专家任务。")
        elif state.get("planning_status") == "failed" or state.get("supervisor_status") == "failed":
            st.error("本轮研究未完成，请查看任务状态与执行记录。")
        elif state.get("supervisor_status") == "partial":
            st.warning("本轮部分完成，未接入或失败的任务已单独标记。")
        if state.get("composition_status") == "fallback":
            st.warning("汇总生成失败，已保留逐任务结果。")
    with data_tab:
        found = False
        for ident, record in records.items():
            payload = record.get("result") or {}
            if record["category"] == "market_data":
                found = True
                st.markdown(f"**{ident} · {record['question']}**")
                st.write(payload.get("answer", "数据查询未完成。"))
                for evidence in payload.get("evidence", []):
                    st.json(evidence)
                for missing in payload.get("missing_information", []):
                    st.warning(missing)
            elif record["category"] == "report" and payload.get("perception_data") is not None:
                found = True
                st.markdown(f"**报告 {ident} · 感知数据**")
                st.json(payload["perception_data"])
        if not found:
            st.info("尚无数据证据。")
    with analysis_tab:
        st.caption("Analytics 与 Investment Strategy 尚未接入，相关任务会明确显示 unsupported。")
        for ident, record in records.items():
            if record["category"] in {"analytics", "investment_strategy"}:
                st.write(f"{ident}：{_LABELS.get(record['status'], record['status'])}")
            if record["category"] == "report":
                payload = record.get("result") or {}
                for field in _REPORT_FIELDS[1:]:
                    if payload.get(field) is not None:
                        st.markdown(f"**{ident} · {field}**")
                        st.json(payload[field])
    with report_tab:
        st.caption("四节点完整输出；最终报告正文、下载和评估暂时隐藏。")
        reports = dict(progress)
        for ident, record in records.items():
            if record["category"] == "report":
                reports[ident] = {**reports.get(ident, {}), **(record.get("result") or {})}
        if not reports:
            st.info("本轮尚无报告节点结果。")
        for ident, payload in reports.items():
            st.markdown(f"**报告任务 {ident}**")
            _render_nodes(payload)
            if _SHOW_FINAL_REPORT and payload.get("final_report"):
                st.write(payload["final_report"])


with st.sidebar:
    st.title("⚙️ 设置")
    st.toggle("使用真实 AKShare 数据", key="use_real_data")
    set_use_real_data(st.session_state["use_real_data"])
    st.caption(f"数据模式：{data_mode()}")
    st.caption("没有 checkpoint 自动记忆；每轮显式传入最近三轮会话摘要。")
    st.caption("摘要只在当前 Streamlit 会话内保留，刷新或服务重启后可能丢失。")
    if st.button("🔄 新对话", use_container_width=True):
        st.session_state.update(conversation_history=[], last_result=None, execution_events=[],
                                report_progress={}, turn_count=0)
        st.rerun()
    st.caption(f"已完成 {st.session_state['turn_count']} 轮")

st.title("📊 InvestAgent · 投研工作台")
st.caption("Planner → Supervisor → Market Data / Report → Composer")
st.info("数据查询与报告已接入；Analytics 和 Investment Strategy 尚未接入。报告正文暂时隐藏。")
if st.session_state["conversation_history"]:
    with st.expander("对话历史与上下文"):
        for turn in st.session_state["conversation_history"]:
            st.write(f"问题：{turn['query']}")
            st.write(f"摘要：{turn.get('response_preview', '')}")
examples = [("行情查询", "茅台和五粮液最新价格是多少？"),
            ("生成报告", "请生成新能源行业未来一年的投研报告，重点关注光伏。"),
            ("混合任务", "查询茅台价格，比较与五粮液的估值，并分析未来一年投资机会。")]
for col, (label, query) in zip(st.columns(3), examples):
    if col.button(label, use_container_width=True):
        st.session_state["query_input"] = query
user_query = st.text_area("您想研究什么？", key="query_input", height=110)
run_btn = st.button("🚀 运行研究任务", type="primary", use_container_width=True)
st.caption("报告主题、行业和时间范围请直接写入问题；目前不提供未绑定任务的全局报告参数。")
answer_tab, data_tab, analysis_tab, report_tab, trace_tab = st.tabs(
    ["回答", "数据与证据", "分析与策略", "节点结果", "执行记录"])
# Each tab has its own replaceable container during execution.
containers = [tab.empty() for tab in (answer_tab, data_tab, analysis_tab, report_tab)]

if run_btn and user_query.strip():
    from src.agent import create_invest_agent
    from src.parent_state import create_parent_state

    history = st.session_state["conversation_history"][-3:]
    summary = "\n\n".join(f"用户：{turn['query'][:800]}\n回答摘要：{turn.get('response_preview', '')[:1200]}"
                           for turn in history)
    initial = create_parent_state(user_query, conversation_context=summary)
    current, progress, events = dict(initial), {}, []
    active_task = None
    active_category = None
    config = {}
    try:
        from src.evaluation.langfuse_tracing import get_langfuse_handler
        handler = get_langfuse_handler()
        if handler:
            config["callbacks"] = [handler]
    except Exception:
        pass
    with trace_tab:
        status = st.status("研究任务运行中…", expanded=True)
    try:
        graph = create_invest_agent()
        for namespace, mode, update in graph.stream(initial, config=config,
                subgraphs=True, stream_mode=["updates", "custom"]):
            if mode == "custom":
                if update.get("event") == "task_started":
                    active_task, active_category = update["task_id"], update["category"]
                continue
            for node, values in update.items():
                if not isinstance(values, dict):
                    continue
                # Only root updates enter the parent snapshot. Nested channels stay local.
                if not namespace:
                    current.update(values)
                elif "task_results" in values:
                    current["task_results"] = values["task_results"]
                if namespace and active_task and active_category == "report":
                    fields = {key: values[key] for key in _REPORT_FIELDS if key in values}
                    if fields:
                        progress.setdefault(active_task, {}).update(fields)
                events.append({"step": len(events) + 1, "node": node,
                               "task_id": active_task or "", "scope": "/".join(namespace) or "parent"})
            # Render each view in its own replaceable tab container.
            old_tabs = (answer_tab, data_tab, analysis_tab, report_tab)
            answer_tab, data_tab, analysis_tab, report_tab = [c.container() for c in containers]
            _render_results(current, progress)
            answer_tab, data_tab, analysis_tab, report_tab = old_tabs
            with status:
                _render_tasks(current)
        status.update(label="研究执行结束", state="error" if current.get("supervisor_status") == "failed"
                      or current.get("planning_status") == "failed" else "complete", expanded=False)
    except Exception:
        current.update(final_response="运行异常，已保留本轮可用任务结果，请重试。", composition_status="failed")
        status.update(label="研究执行异常", state="error")
    st.session_state.update(last_result=current, report_progress=progress, execution_events=events,
                            turn_count=st.session_state["turn_count"] + 1)
    st.session_state["conversation_history"].append({"query": user_query.strip(),
        "response_preview": (current.get("final_response") or "")[:1200],
        "status": current.get("supervisor_status") or current.get("planning_status")})
    st.rerun()
elif run_btn:
    st.warning("请输入查询内容后再运行。")

state = st.session_state.get("last_result") or {}
# Initial run renders here; streaming uses the same view functions.
_render_results(state, st.session_state["report_progress"])
with trace_tab:
    _render_tasks(state)
    for key in ("planning_error", "supervisor_error", "composition_error"):
        if state.get(key):
            st.error(state[key]["message"])
    if st.session_state["execution_events"]:
        st.dataframe(st.session_state["execution_events"], hide_index=True, use_container_width=True)
