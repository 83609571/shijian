"""赣鄱智轨 · L3 智能体层（Planner-Executor-Critic）

模块地图：
    schemas.py      L1 数据契约 + 参数域 + 决策文档组装
    data_layer.py   L1 统一数据源（34 站口径）与可信度台账
    sim_adapter.py  L2 双引擎仿真适配器（TranStar 探针 + 自研三层饱和度假真）
    guardrail.py    L3 确定性护栏（原 mirrorDispatch 规则降级为护栏）
    tools.py        L3 9 个 Function-Calling 工具的真实实现
    llm_client.py   L3 可插拔 LLM 客户端（DS4.1-Flash / GLM / OpenAI 兼容 / 离线确定性）
    trace.py        L3 结构化 trace 日志（可回放证据链）
    agent_loop.py   L3 Planner-Executor-Critic 状态机
    report.py       L5 Markdown 治理报告生成器

设计纪律：
    · 先跑通数据与机制，再上模型。智能体的"大脑"可换，护栏与评分不可换。
    · 所有数字都能指回「文件」或「计算」或「外部引擎」，不做无依据声明。
"""
__all__ = ["schemas", "data_layer", "sim_adapter", "guardrail", "tools",
           "llm_client", "trace", "agent_loop", "report"]
__version__ = "1.0.0"
