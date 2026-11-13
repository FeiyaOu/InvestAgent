"""Parent-graph research UI; explicit session summaries, no checkpoint memory."""
from __future__ import annotations

import os
from datetime import datetime, timezone
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import dotenv_values, load_dotenv
import streamlit as st

from app.analytics_dashboard import render_analytics_task
from app.strategy_dashboard import render_strategy_task
from app.report_viewer import render_report
from app.example_queries import example_queries, BOUNDARY_EXAMPLES

from src.tools import USE_REAL_DATA_ENV, parse_bool, data_mode, set_use_real_data

_ENV_PATH = os.path.join(_project_root, ".env")
load_dotenv(_ENV_PATH)
_REPORT_FIELDS = ("perception_data", "world_model", "reasoning_plans", "selected_plan")
_LABELS = {"completed": "已完成", "partial": "部分完成", "failed": "失败",
           "unsupported": "尚未接入", "blocked": "前置任务不可用"}

st.set_page_config(page_title="InvestAgent — 投研工作台", page_icon="📊", layout="wide")
st.markdown("""
<style>
.st-key-developer_debug [data-testid="stExpander"]:not([data-testid="stExpander"] [data-testid="stExpander"]) > details > summary {
    background-color: #e0f2fe;
    color: #075985;
    border-radius: 8px;
}
.st-key-developer_debug [data-testid="stExpander"]:not([data-testid="stExpander"] [data-testid="stExpander"]) > details > summary:hover {
    background-color: #bae6fd;
    color: #075985;
}
</style>
""", unsafe_allow_html=True)

# Invalidate session objects from the old dual-path UI on hot reload.
if st.session_state.get("ui_version") != 2:
    st.session_state.update(ui_version=2, conversation_history=[], last_result=None,
                            execution_events=[], report_progress={}, debug_events=[], analysis_snapshots={}, turn_count=0)
for key, default in {"conversation_history": [], "last_result": None, "execution_events": [],
                     "report_progress": {}, "debug_events": [], "analysis_snapshots": {}, "turn_count": 0, "query_input": ""}.items():
    if key not in st.session_state:
        st.session_state[key] = default
if "use_real_data" not in st.session_state:
    raw = dotenv_values(_ENV_PATH).get(USE_REAL_DATA_ENV, os.getenv(USE_REAL_DATA_ENV))
    st.session_state["use_real_data"] = parse_bool(raw, default=True)
set_use_real_data(st.session_state["use_real_data"])


def _fill_example(ident):
    cards=example_queries() + BOUNDARY_EXAMPLES
    st.session_state['query_input']=next(card['query'] for card in cards if card['id']==ident)


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
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.info("尚无可执行任务。")


def _debug_details(values):
    """Copy only observable node output; exclude provider metadata and report text."""
    details = {key: values[key] for key in (
        "plan", "planning_status", "planning_attempts", "planning_error",
        "last_task_id", "supervisor_status", "supervisor_error", "tool_rounds",
        "tool_calls_used", "output_retries", "status", "error",
    ) if key in values}
    if "messages" in values:
        details["messages"] = []
        for msg in values["messages"]:
            role = getattr(msg, "type", "unknown")
            if role == "system":
                continue
            item = {"role": role, "content": getattr(msg, "content", "")}
            if getattr(msg, "tool_calls", None):
                item["tool_calls"] = msg.tool_calls
            if getattr(msg, "tool_call_id", None):
                item["tool_call_id"] = msg.tool_call_id
            details["messages"].append(item)
    result = values.get("result")
    if isinstance(result, dict) and "answer" in result and "evidence_ids" in result:
        details["validated_result"] = {key: result.get(key) for key in ("answer", "evidence_ids", "missing_information", "dataset_refs")}
    if "task_results" in values:
        details["tasks"] = [{"task_id": ident, "category": r["category"], "depends_on": r["depends_on"],
                             "status": r["status"], "error": r.get("error")}
                            for ident, r in values["task_results"].items()]
    return details


def _render_planning(state, debug):
    with st.expander("Planner · 完整计划与规划状态", expanded=True):
        st.write({key: state.get(key) for key in ("planning_status", "planning_attempts", "planning_error")})
        for event in debug:
            if event["node"] == "planner_attempt":
                st.caption(f"第 {event['details']['attempt']} 次规划 · {event['details']['status']}")
                st.json(event)
        if state.get("plan"):
            st.json(state["plan"], expanded=True)
        else:
            st.info("等待 Planner 返回计划。")
    with st.expander("Supervisor · 调度与结果收集", expanded=True):
        st.caption("当前顺序调度；以下记录显示任务开始、依赖及终止结果。")
        for event in debug:
            if event["node"] == "task_started" or event["details"].get("tasks") is not None:
                st.json(event)


def _render_experts(state, debug):
    with st.expander("Strategy/Risk · 模型、工具与校验", expanded=True):
        found = False
        for event in debug:
            if event.get("category") == "investment_strategy":
                found = True
                st.json(event)
        if not found:
            st.info("暂无 Strategy/Risk 执行事件。")
    with st.expander("Analytics · 模型、工具与校验", expanded=True):
        found = False
        for event in debug:
            if event.get("category") == "analytics":
                found = True
                st.json(event)
        if not found:
            st.info("暂无 Analytics 执行事件。")
    with st.expander("Market Data · 模型输出、工具批次与校验", expanded=True):
        st.caption("同一条 AI 消息里的多个 tool_calls 是同轮批次，可由 ToolNode 并行执行；跨消息批次为后续轮次。时间为收到节点事件的时间，不代表单个工具开始或结束时间。")
        found = False
        for event in debug:
            if event.get("category") == "market_data" and event["node"] in {"initialize", "agent", "tools", "finalize"}:
                found = True
                st.markdown(f"**{event['task_id']} · {event['node']} · 事件 {event['step']}**")
                st.json(event, expanded=True)
        if not found:
            st.info("暂无 Market Data 内部事件；需运行新请求采集。")


def _render_debug(state, debug):
    with planning_slot.container():
        _render_planning(state, debug)
    with experts_slot.container():
        _render_experts(state, debug)


def _render_results(state, progress, snapshots=None, render_id="final"):
    if snapshots is None:
        snapshots = st.session_state.get("analysis_snapshots", {})
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
            if record.get("error"):
                st.error(f"{ident} [{record['error']['type']}]：{record['error']['message']}")
            if record["category"] == "market_data":
                found = True
                st.markdown(f"**{ident} · {record['question']}**")
                st.write(payload.get("answer", "数据查询未完成。"))
                for ref in payload.get("dataset_refs", []):
                    st.markdown("**已注册历史数据集（仅本次请求有效）**")
                    st.json(ref)
                for evidence in payload.get("evidence", []):
                    st.json(evidence)
                for missing in payload.get("missing_information", []):
                    st.warning(missing)
        if not found:
            st.info("尚无数据证据。")
    with analysis_tab:
        st.caption("分析图表来自已验证计算产物；仅在当前会话保留最近请求。Strategy/Risk V1 已接入。")
        for ident, record in records.items():
            if record["category"] == "analytics":
                render_analytics_task(ident, record, snapshots, render_id=render_id)
            if record["category"] == "investment_strategy":
                render_strategy_task(ident, record)
    with report_tab:
        st.caption("四节点完整输出保持可见；成品报告请到「报告中心」查看和下载。")
        reports = dict(progress)
        for ident, record in records.items():
            if record["category"] == "report":
                reports[ident] = {**reports.get(ident, {}), **(record.get("result") or {})}
        if not reports:
            st.info("本轮尚无报告节点结果。")
        for ident, payload in reports.items():
            st.markdown(f"**报告任务 {ident}**")
            _render_nodes(payload)
    with reader_tab:
        reports = {task['task_id']:{'question':task['question'], 'status':'running', 'result':None}
                   for task in (state.get('plan') or {}).get('tasks',[]) if task['category']=='report'}
        reports.update({ident:record for ident,record in records.items() if record['category']=='report'})
        for ident, record in reports.items():
            render_report(ident, record, render_id=render_id)
        if not reports:
            st.info("这里展示完整报告的生成状态、成品阅读与下载。普通行情和分析查询不会生成报告。")
            st.button("试试生成报告", key=f"empty_report_{render_id}", on_click=_fill_example, args=("report",))


with st.sidebar:
    st.title("⚙️ 设置")
    st.toggle("使用真实 AKShare 数据", key="use_real_data")
    set_use_real_data(st.session_state["use_real_data"])
    st.caption(f"数据模式：{data_mode()}")
    st.caption("没有 checkpoint 自动记忆；每轮显式传入最近三轮会话摘要。")
    st.caption("摘要只在当前 Streamlit 会话内保留，刷新或服务重启后可能丢失。")
    if st.button("🔄 新对话", width="stretch"):
        st.session_state.update(conversation_history=[], last_result=None, execution_events=[],
                                report_progress={}, debug_events=[], analysis_snapshots={}, turn_count=0)
        st.rerun()
    st.caption(f"已完成 {st.session_state['turn_count']} 轮")

st.title("📊 InvestAgent · 投研工作台")
st.caption("查询市场、比较表现，或生成一份行业研究报告。")
st.info("这是一个投研助手，可以帮你查询行情、比较股票、分析历史表现和风险，也能生成行业研究报告。展开示例选择问题，或在下方直接输入需求，再点击「运行研究任务」。回答和图表可在结果页查看，生成的报告可在「报告中心」阅读和下载。目前支持基于最近三轮对话上下文进行连续追问，更长的多轮对话能力待后续开发。点击侧边栏「新对话」可清空当前会话，开启新一轮交流。")
if st.session_state["conversation_history"]:
    with st.expander("对话历史与上下文"):
        for turn in st.session_state["conversation_history"]:
            st.write(f"问题：{turn['query']}")
            st.write(f"摘要：{turn.get('response_preview', '')}")
st.caption("点击示例只填入问题，确认内容后再运行。")
with st.expander("试试这些问题", expanded=False):
    cards=example_queries()
    for offset in (0,3):
        for col,card in zip(st.columns(3),cards[offset:offset+3]):
            with col.container(border=True):
                st.button(card['title'],key='example_'+card['id'],on_click=_fill_example,args=(card['id'],),width='stretch')
                st.caption(card['hint'])
with st.expander("更多测试场景", expanded=False):
    st.caption("边界场景用于检查数据缺失提示。机会与风险解释为实验性：已知输出校验问题尚未解决。")
    for col,card in zip(st.columns(3),BOUNDARY_EXAMPLES):
        col.button(card['title'],key='example_'+card['id'],on_click=_fill_example,args=(card['id'],),width='stretch')

user_query = st.text_area("您想研究什么？", key="query_input", height=110)
run_btn = st.button("🚀 运行研究任务", type="primary", width="stretch")

answer_tab, combined_tab, reader_tab = st.tabs(["回答", "数据与分析", "报告中心"])
with combined_tab:
    data_tab=st.container()
    analysis_tab=st.container()
with st.container(key="developer_debug"):
    with st.expander("开发者调试", expanded=False):
        st.caption("用于排查规划、专家执行和报告生成；不影响上方产品结果。")
        planning_tab, experts_tab, report_tab = st.tabs(["任务规划与调度", "专家执行记录", "报告生成过程"])
trace_tab=planning_tab
planning_slot=planning_tab.empty()
experts_slot=experts_tab.empty()
# Independent placeholders keep streamed views replaceable and downloads unique.
containers = [tab.empty() for tab in (answer_tab, data_tab, analysis_tab, report_tab, reader_tab)]

if run_btn and user_query.strip():
    from src.agent import create_invest_agent
    from src.parent_state import create_parent_state

    history = st.session_state["conversation_history"][-3:]
    summary = "\n\n".join(f"用户：{turn['query'][:800]}\n回答摘要：{turn.get('response_preview', '')[:1200]}"
                           for turn in history)
    initial = create_parent_state(user_query, conversation_context=summary)
    current, progress, events = dict(initial), {}, []
    debug = []
    snapshots = {}
    render_seq = 0
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
    with answer_tab:
        status = st.status("研究任务运行中…", expanded=True)
    try:
        graph = create_invest_agent()
        for namespace, mode, update in graph.stream(initial, config=config,
                subgraphs=True, stream_mode=["updates", "custom"]):
            if mode == "custom":
                if update.get("event") == "planner_attempt":
                    debug.append({"step": len(debug) + 1, "node": "planner_attempt", "task_id": None,
                                  "category": None, "details": update,
                                  "received_at": datetime.now(timezone.utc).isoformat()})
                    _render_debug(current, debug)
                if update.get("event") == "strategy_diagnostic":
                    debug.append({"step": len(debug) + 1, "node": "strategy_diagnostic", "task_id": active_task,
                                  "category": "investment_strategy", "details": update,
                                  "received_at": datetime.now(timezone.utc).isoformat()})
                    _render_debug(current, debug)
                if update.get("event") == "analysis_artifacts":
                    snapshots.setdefault(update["task_id"], {}).update(update["artifacts"])
                if update.get("event") == "task_started":
                    active_task, active_category = update["task_id"], update["category"]
                    debug.append({"step": len(debug) + 1, "node": "task_started", "task_id": active_task,
                                  "category": active_category, "details": update,
                                  "received_at": datetime.now(timezone.utc).isoformat()})
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
                detail = _debug_details(values)
                if detail:
                    debug.append({"step": len(debug) + 1, "node": node,
                                  "task_id": active_task if namespace else None,
                                  "category": active_category if namespace else None,
                                  "scope": "/".join(namespace) or "parent", "details": detail,
                                  "received_at": datetime.now(timezone.utc).isoformat()})
                events.append({"step": len(events) + 1, "node": node,
                               "task_id": active_task or "", "scope": "/".join(namespace) or "parent"})
            # Render each view in its own replaceable tab container.
            old_tabs = (answer_tab, data_tab, analysis_tab, report_tab, reader_tab)
            answer_tab, data_tab, analysis_tab, report_tab, reader_tab = [c.container() for c in containers]
            render_seq += 1
            _render_results(current, progress, snapshots, render_id=f"stream_{render_seq}")
            answer_tab, data_tab, analysis_tab, report_tab, reader_tab = old_tabs
            _render_debug(current, debug)
            with status:
                _render_tasks(current)
        status.update(label="研究执行结束", state="error" if current.get("supervisor_status") == "failed"
                      or current.get("planning_status") == "failed" else "complete", expanded=False)
    except Exception:
        current.update(final_response="运行异常，已保留本轮可用任务结果，请重试。", composition_status="failed")
        status.update(label="研究执行异常", state="error")
    st.session_state.update(last_result=current, report_progress=progress, execution_events=events, debug_events=debug, analysis_snapshots=snapshots,
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
    _render_debug(state, st.session_state["debug_events"])
    _render_tasks(state)
    for key in ("planning_error", "supervisor_error", "composition_error"):
        if state.get(key):
            st.error(state[key]["message"])
    if st.session_state["execution_events"]:
        st.dataframe(st.session_state["execution_events"], hide_index=True, width="stretch")
