"""Parent-graph research UI; explicit session summaries, no checkpoint memory."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import dotenv_values, load_dotenv
import streamlit as st

from app import ui_shell
from app.progress import build_steps, progress_html
from app.analytics_dashboard import render_analytics_task
from app.strategy_dashboard import render_strategy_task
from app.report_viewer import render_report
from app.example_queries import example_queries, BOUNDARY_EXAMPLES

from src.data.tools import USE_REAL_DATA_ENV, parse_bool, data_mode, set_use_real_data

_ENV_PATH = os.path.join(_project_root, ".env")
load_dotenv(_ENV_PATH)
_REPORT_FIELDS = ("perception_data", "world_model", "reasoning_plans", "selected_plan")
_LABELS = {"completed": "已完成", "partial": "部分完成", "failed": "失败",
           "unsupported": "尚未接入", "blocked": "前置任务不可用"}

st.set_page_config(page_title="InvestAgent — 投研工作台", page_icon="📊", layout="wide")
ui_shell.inject_styles()
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
                            execution_events=[], report_progress={}, debug_events=[], analysis_snapshots={},
                            strategy_series={}, turn_count=0)
for key, default in {"conversation_history": [], "last_result": None, "execution_events": [],
                     "report_progress": {}, "debug_events": [], "analysis_snapshots": {}, "strategy_series": {},
                     "turn_count": 0, "query_input": "", "view": "当前对话"}.items():
    if key not in st.session_state:
        st.session_state[key] = default
if "use_real_data" not in st.session_state:
    raw = dotenv_values(_ENV_PATH).get(USE_REAL_DATA_ENV, os.getenv(USE_REAL_DATA_ENV))
    st.session_state["use_real_data"] = parse_bool(raw, default=True)
set_use_real_data(st.session_state["use_real_data"])


_VIEWS = (("当前对话", "nav_chat", ":material/chat:"), ("报告中心", "nav_reports", ":material/description:"),
          ("研究记录", "nav_history", ":material/history:"))


def _fill_example(ident):
    cards=example_queries() + BOUNDARY_EXAMPLES
    st.session_state['query_input']=next(card['query'] for card in cards if card['id']==ident)
    st.session_state['view']='当前对话'


def _set_view(name):
    st.session_state['view']=name


def _new_conversation():
    st.session_state.update(conversation_history=[], last_result=None, execution_events=[],
                            report_progress={}, debug_events=[], analysis_snapshots={}, strategy_series={},
                            turn_count=0, view="当前对话")


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


def _render_debug(state, debug, dslots):
    with dslots["planning"].container():
        _render_planning(state, debug)
    with dslots["experts"].container():
        _render_experts(state, debug)


_RUN_STATUS = {"completed": "已完成", "partial": "部分完成", "failed": "未完成", "needs_clarification": "需要补充信息"}
_BADGE = {"completed": ("已完成", "green"), "partial": ("部分完成", "orange"), "failed": ("失败", "red"),
          "blocked": ("前置任务不可用", "red"), "unsupported": ("尚未接入", "gray")}
_SECTIONS = (("market_data", "数据与证据", "Market Data 采集的行情、估值与证据，均标注来源、日期与数据模式"),
             ("analytics", "分析结果", "基于本次采集数据的确定性计算，指标单位与参数见各计算产物"),
             ("investment_strategy", "策略与风险", "约束检查、组合风险与情景结果；历史回放不代表未来"),
             ("report", "研究报告", "完整报告在「报告中心」阅读与下载"))


def _evidence_rows(records):
    rows = []
    for ident, record in records.items():
        for item in (record.get("result") or {}).get("evidence", []) if record["category"] == "market_data" else []:
            rows.append({"任务": ident, "工具": item.get("tool_name"), "状态": item.get("status"),
                         "数据模式": item.get("data_mode"), "数据日期": item.get("as_of_date") or "未提供",
                         "采集时间": item.get("retrieved_at"), "来源": item.get("source_url") or ""})
    return rows


def _run_meta(state, records):
    history = st.session_state["conversation_history"]
    planning = state.get("planning_status")
    key = planning if planning in {"failed", "needs_clarification"} else state.get("supervisor_status")
    parts = [_RUN_STATUS.get(key or "", "进行中")]
    if history and history[-1].get("seconds") is not None and state is st.session_state.get("last_result"):
        parts.append(f"用时 {history[-1]['seconds']} 秒")
    parts.append(f"{len(_evidence_rows(records))} 条数据证据")
    return " · ".join(parts)


def _render_market_task(ident, record):
    payload = record.get("result") or {}
    st.markdown(f"**{record['question']}**")
    st.write(payload.get("answer") or "数据查询未完成。")
    for missing in payload.get("missing_information", []):
        st.warning(missing)


def _render_report_link(ident, record, render_id):
    st.markdown(f"**{record['question']}**")
    st.caption("报告正文不在此处重复展示，请前往报告中心阅读、核对校验提示并下载。")
    st.button("前往报告中心阅读与下载", key=f"goto_reports_{ident}_{render_id}", icon=":material/description:",
              on_click=_set_view, args=("报告中心",))


def _render_results(state, progress, slots, snapshots=None, render_id="final", strategy_series=None):
    if snapshots is None:
        snapshots = st.session_state.get("analysis_snapshots", {})
    if strategy_series is None:
        strategy_series = st.session_state.get("strategy_series", {})
    records = state.get("task_results", {})
    with slots["answer"].container():
        ui_shell.render_answer_head(_run_meta(state, records))
        if state.get("planning_status") == "needs_clarification":
            st.info("请补充信息后再次提交，当前未执行专家任务。")
        elif state.get("planning_status") == "failed" or state.get("supervisor_status") == "failed":
            st.error("本轮研究未完成，请查看任务状态与执行记录。")
        elif state.get("supervisor_status") == "partial":
            st.warning("本轮部分完成，未接入或失败的任务已单独标记。")
        if state.get("composition_status") == "fallback":
            st.warning("汇总生成失败，已保留逐任务结果。")
        if state.get("composition_summary"):
            ui_shell.render_summary(state["composition_summary"])
        elif state.get("final_response") and not records:
            st.markdown(state["final_response"])  # Clarification or planning failure: no task details exist.
        elif not records:
            st.info("等待规划与任务结果。")
        number = 0
        for category, title, subtitle in _SECTIONS:
            tasks = {ident: r for ident, r in records.items() if r["category"] == category}
            if not tasks:
                continue
            number += 1
            ui_shell.render_section_title(number, title, subtitle)
            for ident, record in tasks.items():
                label, color = _BADGE.get(record["status"], (record["status"], "gray"))
                st.badge(f"{ident} · {label}", color=color)
                if record.get("error"):
                    st.error(f"[{record['error']['type']}] {record['error']['message']}")
                if category == "market_data":
                    _render_market_task(ident, record)
                elif category == "analytics":
                    render_analytics_task(ident, record, snapshots, render_id=render_id)
                elif category == "investment_strategy":
                    render_strategy_task(ident, record, strategy_series.get(ident, {}), render_id=render_id)
                else:
                    _render_report_link(ident, record, render_id)
        rows = _evidence_rows(records)
        if rows:
            with st.expander(f"查看参考来源与局限（{len(rows)} 条数据证据）"):
                st.caption("证据为工具实际返回的记录；采集时间不等于行情日期，模拟数据不代表真实行情。")
                st.dataframe(rows, hide_index=True, width="stretch")
        if records and state.get("final_response"):
            with st.expander("逐任务文字明细"):
                st.markdown(state["final_response"])
    with slots["report"].container():
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


def _report_records(state):
    reports = {task['task_id']:{'question':task['question'], 'status':'running', 'result':None}
               for task in (state.get('plan') or {}).get('tasks',[]) if task['category']=='report'}
    reports.update({ident:record for ident,record in state.get('task_results', {}).items() if record['category']=='report'})
    return reports


def _result_layout():
    """Placeholders for one research turn; streaming and reruns both render into them."""
    question = st.empty()
    status_box = st.empty()
    body = st.empty()
    with st.container(key="developer_debug"):
        with st.expander("开发者调试", expanded=False):
            st.caption("用于排查规划、专家执行和报告生成；不影响上方产品结果。")
            planning_tab, experts_tab, report_tab = st.tabs(["任务规划与调度", "专家执行记录", "报告生成过程"])
    slots = {"question": question, "status": status_box, "answer": body, "report": report_tab.empty()}
    dslots = {"planning": planning_tab.empty(), "experts": experts_tab.empty(), "trace": planning_tab}
    return slots, dslots


def _run(user_query, slots, dslots):
    from src.agent import create_invest_agent
    from src.orchestration.parent_state import create_parent_state

    with slots["question"].container():
        ui_shell.render_question(user_query.strip())
    history = st.session_state["conversation_history"][-3:]
    summary = "\n\n".join(f"用户：{turn['query'][:800]}\n回答摘要：{turn.get('response_preview', '')[:1200]}"
                           for turn in history)
    initial = create_parent_state(user_query, conversation_context=summary)
    current, progress, events = dict(initial), {}, []
    debug = []
    snapshots, strategy_series = {}, {}
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
    started, attempts = time.monotonic(), []

    def show_progress():
        slots["status"].html(progress_html(build_steps(current, active_task, attempts), time.monotonic() - started))

    show_progress()
    try:
        graph = create_invest_agent()
        for namespace, mode, update in graph.stream(initial, config=config,
                subgraphs=True, stream_mode=["updates", "custom"]):
            if mode == "custom":
                if update.get("event") == "planner_attempt":
                    attempts.append(update)
                    debug.append({"step": len(debug) + 1, "node": "planner_attempt", "task_id": None,
                                  "category": None, "details": update,
                                  "received_at": datetime.now(timezone.utc).isoformat()})
                    _render_debug(current, debug, dslots)
                if update.get("event") == "strategy_diagnostic":
                    debug.append({"step": len(debug) + 1, "node": "strategy_diagnostic", "task_id": active_task,
                                  "category": "investment_strategy", "details": update,
                                  "received_at": datetime.now(timezone.utc).isoformat()})
                    _render_debug(current, debug, dslots)
                if update.get("event") == "analysis_artifacts":
                    snapshots.setdefault(update["task_id"], {}).update(update["artifacts"])
                if update.get("event") == "strategy_artifacts":
                    strategy_series.setdefault(update["task_id"], {}).update(update["series"])
                if update.get("event") == "task_started":
                    active_task, active_category = update["task_id"], update["category"]
                    debug.append({"step": len(debug) + 1, "node": "task_started", "task_id": active_task,
                                  "category": active_category, "details": update,
                                  "received_at": datetime.now(timezone.utc).isoformat()})
                show_progress()
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
            render_seq += 1
            _render_results(current, progress, slots, snapshots, render_id=f"stream_{render_seq}",
                            strategy_series=strategy_series)
            _render_debug(current, debug, dslots)
            show_progress()
    except Exception:
        current.update(final_response="运行异常，已保留本轮可用任务结果，请重试。", composition_status="failed")
    seconds = round(time.monotonic() - started)
    st.session_state.update(last_result=current, report_progress=progress, execution_events=events, debug_events=debug,
                            analysis_snapshots=snapshots, strategy_series=strategy_series,
                            turn_count=st.session_state["turn_count"] + 1)
    st.session_state["conversation_history"].append({"query": user_query.strip(),
        "response_preview": (current.get("final_response") or "")[:1200],
        "status": current.get("supervisor_status") or current.get("planning_status"), "seconds": seconds})
    st.rerun()


def _render_trace(state, dslots):
    _render_debug(state, st.session_state["debug_events"], dslots)
    with dslots["trace"]:
        _render_tasks(state)
        for key in ("planning_error", "supervisor_error", "composition_error"):
            if state.get(key):
                st.error(state[key]["message"])
        if st.session_state["execution_events"]:
            st.dataframe(st.session_state["execution_events"], hide_index=True, width="stretch")


def _query_box(label, placeholder, height):
    """One input widget per run; the key and button label are the stable UI contract."""
    query = st.text_area(label, key="query_input", height=height, max_chars=500, placeholder=placeholder)
    left, right = st.columns([3, 1], vertical_alignment="center")
    left.caption("点击示例只填入问题，确认内容后再运行。")
    clicked = right.button("运行研究任务", type="primary", icon=":material/send:", width="stretch")
    if clicked and not query.strip():
        st.warning("请输入查询内容后再运行。")
    return query, clicked and bool(query.strip())


def _render_examples():
    with st.expander("不知道从哪里开始？试试这些问题", expanded=True):
        cards = example_queries()
        for offset in (0, 3):
            for index, (col, card) in enumerate(zip(st.columns(3), cards[offset:offset + 3]), start=offset + 1):
                with col.container(border=True):
                    st.button(card['title'], key='example_' + card['id'], on_click=_fill_example,
                              args=(card['id'],), width='stretch')
                    st.caption(f"0{index} · {card['hint']}")
    with st.expander("更多测试场景", expanded=False):
        st.caption("边界场景用于检查数据缺失提示。机会与风险解释为实验性：已知输出校验问题尚未解决。")
        for col, card in zip(st.columns(3), BOUNDARY_EXAMPLES):
            col.button(card['title'], key='example_' + card['id'], on_click=_fill_example, args=(card['id'],),
                       width='stretch')


def _render_report_center(state):
    st.html('<div class="zh-section-head"><div><span>RESEARCH LIBRARY</span><h2>报告中心</h2></div>'
            '<p>阅读和下载本会话生成的完整报告；仅当前会话保留，刷新或服务重启后可能丢失。</p></div>')
    reports = _report_records(state)
    for ident, record in reports.items():
        render_report(ident, record, render_id="final")
    if not reports:
        st.info("这里展示完整报告的生成状态、成品阅读与下载。普通行情和分析查询不会生成报告。")
        st.button("试试生成报告", key="empty_report", on_click=_fill_example, args=("report",))


def _render_history():
    history = st.session_state["conversation_history"]
    st.html('<div class="zh-section-head"><div><span>ACTIVITY</span><h2>研究记录</h2></div>'
            f'<p>本会话共 {len(history)} 个问题；仅当前会话保留，刷新或服务重启后可能丢失。</p></div>')
    if not history:
        st.info("还没有研究记录。回到「当前对话」提出第一个问题。")
    for turn in reversed(history):
        with st.container(border=True):
            st.markdown(f"**{turn['query']}**")
            st.caption(f"状态：{_LABELS.get(turn.get('status') or '', turn.get('status') or '未知')}")
            if turn.get("response_preview"):
                st.caption(turn["response_preview"][:160] + ("…" if len(turn["response_preview"]) > 160 else ""))


with st.sidebar:
    ui_shell.render_brand()
    st.button("新对话", key="new_chat", icon=":material/add:", on_click=_new_conversation, width="stretch")
    for name, key, icon in _VIEWS:
        st.button(name, key=key, icon=icon, on_click=_set_view, args=(name,), width="stretch",
                  type="primary" if st.session_state["view"] == name else "tertiary")
    ui_shell.render_recent(st.session_state["conversation_history"])
    with st.expander("设置与数据模式"):
        st.toggle("使用真实 AKShare 数据", key="use_real_data")
        set_use_real_data(st.session_state["use_real_data"])
        st.caption(f"数据模式：{data_mode()}")
        st.caption("没有 checkpoint 自动记忆；每轮显式传入最近三轮会话摘要。")
        st.caption("摘要只在当前 Streamlit 会话内保留，刷新或服务重启后可能丢失。")
        st.caption(f"已完成 {st.session_state['turn_count']} 轮")

ui_shell.render_topbar(st.session_state["use_real_data"])
state = st.session_state.get("last_result") or {}
view = st.session_state["view"]

if view == "报告中心":
    _render_report_center(state)
elif view == "研究记录":
    _render_history()
elif not state:
    ui_shell.render_hero()
    query, run = _query_box("您想研究什么？", "例如：比较茅台和五粮液最新估值，以及过去一年的收益、波动率和最大回撤", 120)
    if run:
        _run(query, *_result_layout())
    _render_examples()
    ui_shell.render_capabilities()
    ui_shell.render_footer()
else:
    slots, dslots = _result_layout()
    if st.session_state["conversation_history"]:
        with slots["question"].container():
            ui_shell.render_question(st.session_state["conversation_history"][-1]["query"])
    _render_results(state, st.session_state["report_progress"], slots)
    _render_trace(state, dslots)
    query, run = _query_box("基于以上结果继续追问", "例如：再和沪深300比较一下", 80)
    if run:
        _run(query, slots, dslots)
