# Strategy/Risk V1 实施步骤与开发准则

日期：2026-11-13。用户授权按步骤自主完成V1；权威范围见[investment-strategy-agent.md](investment-strategy-agent.md)。
选择实施规格而非个人Codex skill，便于与代码一起版本管理。

## 从Analytics开发中保留的经验

先定输入、产物和父子图边界，再写工具和Agent；每一步先写失败测试。
引用不是数据本身，不让LLM凭元数据推断指标缺失；工具读取请求内规范数据。
固定策略由代码设置；数据缺失、格式错误、模型失败分开，错误信息可定位且不泄露输入。
修正最终输出时不再开放计算工具；预算限制、引用授权及状态清理在代码执行，不只靠提示词。
数值来自规范产物，Composer与UI不能只展示LLM解释而丢失确定性结果。
单元测试隔离模型和API；真实模型抽样只能说明兼容，不能当作稳定性保证。
不要在同一次交付引入不具备数据前提的估值预测或V2优化库。

## 顺序与完成条件

1. **契约**：独立StrategyState、输入/参数/结果模型；现金+持仓权重和为1，V1仅同币种多头，
   日期明确，不自动归一化。风险限制只接受明确输入，情景标注user/agent_proposed。
2. **规范产物**：请求级StrategyStore；产物携带任务scope、输入快照、工具名与限制。
   完整数据不进入ParentState；过期、跨任务引用拒绝。
3. **确定性工具**：evaluate_risk_constraints与简单价格冲击stress_test_portfolio。
   不拿单股风险冒充组合风险；未覆盖持仓的冲击不默认当零；现金冲击明确为零。
   对未提供限制、缺风险数据、币种/日期不兼容返回可解释结果，不虚构阈值。
4. **子图**：initialize→agent↔ToolNode→finalize，有界工具/输出修正；固定运行时输入注入工具，
   防止LLM重写持仓与限制。机会/风险解释须引用授权证据；数值结果由Store重建。
5. **交接与调度**：Planner支持strategy_parameters，Supervisor收集直接依赖的证据及数据/分析引用，
   注入独立任务scope。父图与response_graph创建请求级Store。普通策略解释不强制持仓或全部工具。
6. **Composer与UI**：显示解释、引用、检查结果、压力测试、假设/限制及缺失要求；
   逐任务和确定性结果在模型汇总失败时仍可用，显示Strategy内部执行记录。
7. **验收**：契约/数值/边界/mock LLM子图/父图集成/Streamlit AppTest；全量pytest、结构lint、
   diff检查。保留报告子图原样。不承诺此阶段已做真实模型或浏览器视觉验收。
8. **交付**：同步范围、实际限制、未完项与测试证据，列出用户可试用问题。

## 本轮边界

V1风险限制首批支持单股仓位及已有单股风险指标阈值；组合波动率/回撤没有对应组合产物时标为无法检查。
简单压力测试：指定每个持仓的价格冲击，收益为权重×冲击之和，现金收益0，
不模拟相关性、再平衡、交易费用、税费、FX或路径依赖，不推断情景概率。
独立StrategyStore用于任务作用域校验和规范重建，不提供持久化、checkpoint或跨请求恢复。
估值情景、优化、风险平价、HRP、Black-Litterman均不在本轮实现。

状态：V1首版步骤1–8已完成；以末尾交付记录为准。


## 交付记录（2026-11-13）

| 步骤 | 实际交付 |
|---|---|
| 契约 | src/strategy_state.py，Portfolio/RiskConstraints/PriceScenario/StrategyInput/Answer/Result/State |
| 产物 | src/strategy_artifacts.py，线程安全、按scope校验、输入快照绑定、请求级存储 |
| 工具 | src/strategy_tools.py，两个确定性工具，工具schema不向模型暴露运行时输入 |
| 子图 | src/strategy_agent.py + src/stages/strategy.py，固定methodology、有界循环与无工具修正 |
| 交接 | src/strategy_handoff.py，规范引用重建、直接依赖授权、结果数值重建 |
| 父图 | Supervisor/parent_graph/response_graph及Planner strategy_parameters接入 |
| 展示 | Composer确定性回退、app/strategy_dashboard.py、Strategy/Risk内部执行记录 |
| 验收 | 契约/工具/边界/子图/父图/AppTest回归及结构lint；真实模型假设组合抽查成功 |

真实抽查结果：Planner两次尝试，两个策略任务完成，Composer完成；仓位60%/30%/现金10%，
冲击-20%/-10%对应组合收益-15%，50%单股上限检查正确。没有调用行情API。
单一样本不证明模型全场景质量；不宣称完成浏览器截图视觉验收。
所有原报告内部文件未改，V2及盈利数据依赖明确保留后续。

最终验证：全量单元测试359 passed、2 integration deselected；结构lint和git diff --check通过。
回归包括伪造数值重建、不能通过省略引用隐藏已执行的违规检查、跨scope/过期引用拒绝、
输出修正禁用工具、状态重置、现金组合、数据缺失及UI重绘。未修改原报告内部文件。


工具适用性补充（2026-11-13）：V1确定性工具按显式输入编排，解释LLM不绑定工具，
包括没有任何约束/情景的首次纯解释。意外tool_calls不执行，记录安全名称并有界修正。
这是双股表现+估值实测tool_scope_error的修正，不通过放开工具权限解决。


引用修正经验（2026-11-13）：不要让LLM再次选择代码已经确定的工具产物；模型输出schema移除artifact_ids，
每次生成/修正分类列出引用，并给业务引用异常提供明确字段诊断。上游analysis_不等于策略strategy_产物。

## 最新验收限制（2026-11-13）

用户复测确认：纯策略解释invalid_output仍未解决。此前“V1首版完成”不应理解为所有真实问题均已通过，
尤其双股PE/PB+一年表现→机会/风险链路仍为已知缺陷。
按用户要求暂缓排查并继续其他工作；详见[专题问题记录](investment-strategy-agent.md#未解决问题纯策略解释-invalid_output2026-11-13)。
