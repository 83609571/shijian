"""L3 智能体层 · 可插拔 LLM 客户端

为什么要做成「可插拔 + 可离线」：
    竞赛环境（评委机器 / 演示笔记本 / 校园网）不保证能连上任何大模型 API，
    也可能根本没有 API Key。如果智能体链路强依赖外部 API，
    那么现场一旦断网或额度耗尽，整个「智能体参与分析过程」就归零。

四档 provider（按优先级自动探测）：
    1. deepseek   —— DS4.1-Flash（OpenAI 兼容协议）
    2. glm        —— 智谱 GLM（GLM5.2 等）
    3. openai     —— 任意 OpenAI 兼容端点（自建 vLLM / 校内网关 / Ollama）
    4. local      —— 零依赖确定性规划器（**离线兜底，协议等价**）

关于 local 模式的诚实说明（答辩时必须讲清楚，不能含混）：
    它不是大模型，是**同一套工具调用协议的确定性策略替身**。
    它存在的意义是：无密钥/断网环境下，Planner→Executor→Critic 循环、护栏、
    trace 落盘、多目标评估、报告生成这条链路依然完整可跑、可复现、可演示。
    接入 API 后，只需切换 provider，主循环与工具集**一行都不用改**。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from . import tools as T

DEFAULT_TIMEOUT = 120
ANTHROPIC_STYLE = False  # 预留：如需接入 Claude 风格端点在此扩展


def _cfgkey(c: dict) -> tuple:
    """方案参数指纹（与 agent_loop._key 保持一致的口径）。"""
    return (round(float(c.get("headway_min", 0)), 2), int(c.get("formation_cars", 0)),
            int(c.get("limit_level", 0)), round(float(c.get("demand_mult", 1)), 3))


# ---------------- 通用 OpenAI 兼容客户端 ----------------
class OpenAICompatClient:
    """只需 base_url + api_key + model 即可工作（stdlib 实现，零依赖）。"""

    name = "openai"
    mode = "llm"

    def __init__(self, base_url: str, api_key: str, model: str, *, name=None,
                 temperature: float = 0.2, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        if name:
            self.name = name

    # -- 底层 HTTP --
    def _post(self, path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        # 显式绕过环境代理，避免校内代理劫持 API 调用
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    # -- 对外：一次 chat（带工具） --
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        payload = {"model": self.model, "messages": messages,
                   "temperature": self.temperature}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        t0 = time.time()
        raw = self._post("/chat/completions", payload)
        msg = (raw.get("choices") or [{}])[0].get("message", {}) or {}
        calls = []
        for c in msg.get("tool_calls") or []:
            fn = c.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"__raw__": args}
            calls.append({"id": c.get("id"), "name": fn.get("name"), "arguments": args or {}})
        return {"content": msg.get("content") or "", "tool_calls": calls,
                "duration_ms": int((time.time() - t0) * 1000),
                "usage": raw.get("usage"), "model": raw.get("model", self.model)}

    def probe(self) -> dict:
        try:
            self.chat([{"role": "user", "content": "ping"}], tools=None)
            return {"ok": True, "provider": self.name, "model": self.model}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "provider": self.name, "model": self.model,
                    "error": f"{type(e).__name__}: {e}"}


# ---------------- 离线确定性规划器 ----------------
class LocalDeterministicPlanner:
    """零依赖、确定性、协议等价的规划器（离线兜底）。

    它按「真实的状态依赖」做决策，而不是播一段固定脚本：
      · 若尚无引擎状态 → 先探引擎、查数据可信度
      · 若尚无候选方案 → 生成候选
      · 若某方案尚未校验 → 先护栏校验，再仿真，再读结果
      · 若基准缺失 → 先跑基准
      · 若方案都已评估 → 对最优方案做敏感性扫描
      · 若 Critic 要求加强 → 生成强化档方案并重跑
      · 全部就绪 → 导出报告
    """

    name = "local"
    mode = "local"

    def __init__(self, scenario: str = "holiday", hub: str = "南昌站"):
        self.scenario = scenario
        self.hub = hub
        self.model = "local-deterministic-planner"

    # ---- 决策主函数：返回 {"tool_calls":[...], "content": "..."} ----
    def decide(self, state: dict) -> dict:
        st = state
        done = {t["tool"] for t in st.get("tool_log", [])}
        calls: list[dict] = []
        notes: list[str] = []

        if "get_engine_status" not in done:
            calls.append({"name": "get_engine_status", "arguments": {}})
            notes.append("先确认仿真引擎可用性（外部引擎探针 + 内置引擎）")

        if "query_data_anchor" not in done:
            calls.append({"name": "query_data_anchor",
                          "arguments": {"station_id": self.hub,
                                        "scene_type": "holiday" if self.scenario == "holiday" else "workday"}})
            notes.append("读取 L1 可信度台账，确认锚点与逐站推演依据")

        if "generate_candidate_plan" not in done:
            calls.append({"name": "generate_candidate_plan",
                          "arguments": {"problem_desc": st.get("user_query", ""), "n_plans": 3}})
            notes.append("生成三类治理范式的候选参数（供给端 / 需求端 / 组合）")

        # 基准场景
        if st.get("baseline") is None:
            base_cfg = {"scenario": self.scenario, "headway_min": 12, "formation_cars": 8,
                        "limit_level": 0, "demand_mult": 1.0, "baseline_flag": True}
            calls.append({"name": "config_simulation_param", "arguments": {"baseline_flag": True}})
            calls.append({"name": "guardrail_validate", "arguments": {"param_json": base_cfg}})
            calls.append({"name": "run_simulation",
                          "arguments": {"sim_engine": "auto", "config_json": base_cfg,
                                        "hub": self.hub}})
            notes.append("建立基准（未治理）状态：统一间隔 12min、8 辆编组、不限流")

        # 各候选方案：护栏校验与仿真同一轮下发（run_simulation 内部仍有护栏闸门兜底）
        # 每个调用都显式带 plan_id —— C 与 D 参数指纹相同，只能靠 id 区分
        for p in st.get("plans", []):
            if not p.get("guardrail"):
                calls.append({"name": "guardrail_validate",
                              "arguments": {"param_json": p["config"], "plan_id": p["id"]}})
            if not p.get("run_id"):
                calls.append({"name": "run_simulation",
                              "arguments": {"sim_engine": "auto", "config_json": p["config"],
                                            "hub": self.hub, "plan_id": p["id"]}})
            elif not p.get("metrics_read"):
                calls.append({"name": "read_sim_result",
                              "arguments": {"result_path": f"{p['run_id']}.json"}})
        if st.get("plans") and any(not p.get("run_id") for p in st["plans"]):
            notes.append("逐方案执行「护栏校验 → 仿真 → 读结果」三步；越界参数由护栏拦停并修正后执行")

        # 敏感性：对每个已完成仿真的方案各自扫描（互不搭便车）
        sens_map = st.get("sensitivity_by_plan") or {}
        for p in st.get("plans", []):
            eff = p.get("effective_config")
            if not p.get("run_id") or not eff:
                continue
            if p["id"] in sens_map or _cfgkey(eff) in sens_map:
                continue
            calls.append({"name": "sensitivity_scan",
                          "arguments": {"base_config": eff, "plan_id": p["id"]}})
            notes.append(f"对方案 {p['id']} 做 6 组扰动重仿真，检验其结论稳健性")

        # 报告：所有方案都完成仿真 + 敏感性扫描后才导出（避免过早出报告）
        rec = st.get("recommended_plan")
        all_plans = st.get("plans") or []
        runs = [p for p in all_plans if p.get("run_id")]
        complete = (all_plans and len(runs) == len(all_plans)
                    and len(st.get("sensitivity_by_plan") or {}) >= len(runs))
        if rec and complete and not st.get("report_done"):
            calls.append({"name": "export_report_markdown",
                          "arguments": {"baseline": st.get("baseline") or {},
                                        "plans": st.get("plans") or [],
                                        "recommended": rec["id"],
                                        "narration": st.get("narration", "")}})
            notes.append("导出 Markdown 治理报告")

        if not calls:
            return {"tool_calls": [], "content": "分析链路已完成，无需继续调用工具。"}

        return {"tool_calls": calls,
                "content": "本轮计划：" + "；".join(notes) if notes else "继续补全分析链路。",
                "duration_ms": 1}

    # ---- Critic 要求加强时的再规划 ----
    def reinforce(self, existing_ids=None) -> list[dict]:
        """给出强化档方案（当 Critic 判定「不达标」时调用）。

        强化档的关键区别：**同步申请增购车辆**，把配车额度从 480 列提到 600 列。
        这正是被护栏 GR-09 拦下后，Planner 应该给出的正确应对 ——
        不是硬闯约束，而是把「扩容」作为一个显式的、有代价的决策提出来。

        实现已统一到 agent_loop.make_reinforcement（含 id 避让），
        避免与 LLM 自行生成的方案撞号导致静默去重。
        """
        from .agent_loop import make_reinforcement
        return make_reinforcement(self.scenario, existing_ids or [])

    def probe(self) -> dict:
        return {"ok": True, "provider": "local", "model": self.model,
                "note": "离线确定性规划器：协议等价替身，无需 API Key"}


# ---------------- Provider 自动探测 ----------------
def _env(*names, default=None):
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return default


def detect_provider(prefer: str | None = None):
    """按 prefer → 环境变量顺序挑一个可用 provider；都没有则回落 local。"""
    prefer = (prefer or os.environ.get("GANPO_LLM_PROVIDER", "")).strip().lower()
    cands = []
    ds_key = _env("DS41_API_KEY", "DEEPSEEK_API_KEY")
    glm_key = _env("GLM_API_KEY", "ZHIPU_API_KEY", "ZHIPUAI_API_KEY")
    oa_key = _env("OPENAI_API_KEY")
    if ds_key:
        cands.append(("deepseek", OpenAICompatClient(
            _env("DS41_BASE_URL", default="https://api.deepseek.com/v1"),
            ds_key, _env("DS41_MODEL", default="deepseek-chat"), name="deepseek")))
    if glm_key:
        cands.append(("glm", OpenAICompatClient(
            _env("GLM_BASE_URL", default="https://open.bigmodel.cn/api/paas/v4"),
            glm_key, _env("GLM_MODEL", default="glm-4-plus"), name="glm")))
    if oa_key:
        cands.append(("openai", OpenAICompatClient(
            _env("OPENAI_BASE_URL", default="https://api.openai.com/v1"),
            oa_key, _env("OPENAI_MODEL", default="gpt-4o-mini"), name="openai")))
    if prefer and prefer not in ("local", "auto"):
        for nm, c in cands:
            if nm == prefer:
                return c
        # 指定的 provider 无密钥 → 仍如实回报，不静默换成别的
        return None
    return cands[0][1] if cands else None


def build_planner(scenario: str = "holiday", hub: str = "南昌站", prefer: str | None = None):
    """返回 (planner, engine_meta)。无可用密钥时给本地确定性规划器。"""
    client = detect_provider(prefer)
    if client is None:
        p = LocalDeterministicPlanner(scenario, hub)
        return p, {"mode": "local", "provider": "local", "model": p.model,
                   "network": False,
                   "note": "未检测到 API Key，使用离线确定性规划器（协议等价替身）"}
    return client, {"mode": "llm", "provider": client.name, "model": client.model,
                    "network": True,
                    "base_url": getattr(client, "base_url", None)}


def build_critic(prefer: str | None = None):
    """Critic 也用同一个 provider（同模型自评 + 确定性打分兜底）。"""
    return detect_provider(prefer)


__all__ = ["OpenAICompatClient", "LocalDeterministicPlanner", "build_planner",
           "build_critic", "detect_provider", "AGENT_TOOLS" , "T"]
AGENT_TOOLS = T.AGENT_TOOLS
