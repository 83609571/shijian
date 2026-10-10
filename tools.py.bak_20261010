"""L3 智能体层 · Function-Calling 工具集（真实后端实现）

设计原则：
  1. 每个工具都是**真函数**，不是给 LLM 看的说明文字。工具的返回结构里有
     `evidence` 字段，标明数据来自「文件 / 计算 / 外部引擎」中的哪一种 ——
     答辩现场可以逐条点开看。
  2. 工具粒度按「一次不可再分的可验证动作」切分：读数据、配参数、校验、跑仿真、
     读结果、出方案、做敏感性、出报告。这样 Critic 才能因为「某一项不过」而只重跑一项。
  3. 工具**不强制全调**。Planner 按需调用，trace 会记录实际调用序列 ——
     这正是 ITSAC 评分表里「智能体实际参与分析过程」要考的东西。
"""
from __future__ import annotations

import json
import os

from . import data_layer as dl
from . import guardrail as gl
from . import schemas as S
from . import sim_adapter as sa

# ---------------- 给 LLM 的 tool 定义（OpenAI / DeepSeek 兼容格式）----------------
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_data_anchor",
            "description": "查询 L1 层可信数据台账：站点客流、上座率、景区客流等锚点统计数据，"
                           "并返回该站点的 real 标注与推演依据。用于在规划前确认数据可信度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "station_id": {"type": "string", "description": "站点名称或索引，如 '南昌站'"},
                    "scene_type": {"type": "string", "enum": ["workday", "weekend", "holiday", "weekday"],
                                   "description": "场景类型"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "config_simulation_param",
            "description": "生成仿真配置参数：发车间隔、编组、限流等级、需求乘子；输出交给 sim 适配器。",
            "parameters": {
                "type": "object",
                "properties": {
                    "baseline_flag": {"type": "boolean", "description": "true=基准场景，false=治理方案"},
                    "headway": {"type": "integer", "description": "发车间隔（分钟）"},
                    "formation_cars": {"type": "integer", "enum": [2, 4, 6, 8], "description": "编组辆数"},
                    "limit_level": {"type": "integer", "enum": [0, 1, 2, 3], "description": "限流等级"},
                    "demand_mult": {"type": "number", "description": "需求乘子，1.0=标定客流"},
                },
                "required": ["baseline_flag"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "guardrail_validate",
            "description": "调用确定性规则护栏，校验仿真参数是否合规（最小/最大发车间隔、编组上限、"
                           "限流阈值、三级限流配套疏运等 8 条规则），越界返回拦截理由与修正建议。",
            "parameters": {
                "type": "object",
                "properties": {"param_json": {"type": "object", "description": "待校验的参数对象"}},
                "required": ["param_json"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_simulation",
            "description": "执行仿真，返回仿真输出指标：平均延误、饱和度、排队长度、吞吐量、能耗。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sim_engine": {"type": "string", "enum": ["auto", "transtar", "engine_b"],
                                   "description": "仿真引擎；auto 会自动探测外部引擎并回落"},
                    "config_json": {"type": "object", "description": "仿真配置"},
                    "hub": {"type": "string", "description": "关注枢纽站，默认 南昌站"},
                },
                "required": ["config_json"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_sim_result",
            "description": "从磁盘读取仿真结果文件，提取量化指标并做单位归一化。",
            "parameters": {
                "type": "object",
                "properties": {"result_path": {"type": "string", "description": "结果 JSON 路径或 result_id"}},
                "required": ["result_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_candidate_plan",
            "description": "生成多套候选治理方案（A/B/C），针对枢纽拥堵：压缩间隔、三级限流+加开疏运、"
                           "组合策略。注意：本工具只生成**参数候选**，参数是否合法由护栏判定。",
            "parameters": {
                "type": "object",
                "properties": {
                    "problem_desc": {"type": "string", "description": "待治理问题描述"},
                    "n_plans": {"type": "integer", "description": "候选方案数量，默认 3"},
                },
                "required": ["problem_desc"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sensitivity_scan",
            "description": "执行敏感性扰动：客流 ±20%、发车间隔 ±2min，输出扰动后指标集合与稳健性判定。",
            "parameters": {
                "type": "object",
                "properties": {"base_config": {"type": "object", "description": "基准配置"}},
                "required": ["base_config"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_report_markdown",
            "description": "输出治理方案 Markdown 报告，含指标对比表、方案解释与 trace 摘要，用于参赛研究报告。",
            "parameters": {
                "type": "object",
                "properties": {
                    "baseline": {"type": "object"}, "plans": {"type": "array"},
                    "recommended": {"type": "string"},
                },
                "required": ["baseline", "plans"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_engine_status",
            "description": "查询仿真引擎可用性：外部引擎（TranStar）探针结果与内置引擎状态。"
                           "用于向评委说明引擎选型与回落理由。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


class ToolContext:
    """工具执行上下文：持有输出目录与结果注册表（结果同时落盘 + 内存索引）。"""

    def __init__(self, out_dir: str, scenario: str = "holiday", hub: str = "南昌站"):
        self.out_dir = out_dir
        self.sim_dir = os.path.join(out_dir, "sim_results")
        self.trace_dir = os.path.join(out_dir, "trace")
        os.makedirs(self.sim_dir, exist_ok=True)
        os.makedirs(self.trace_dir, exist_ok=True)
        self.scenario = scenario
        self.hub = hub
        self.results: dict[str, dict] = {}


# ---------------- 工具实现 ----------------

def t_query_data_anchor(ctx: ToolContext, station_id=None, scene_type=None, **_) -> dict:
    sc = "holiday" if scene_type in ("holiday", "weekend") else ctx.scenario
    a = dl.anchors(sc)
    out = {"ok": True, "scenario": sc, "evidence": "data/flow_%s.json（L1 层唯一数据源）" % sc,
           "network": dl.network_summary(sc),
           "public_anchors": a["public_anchors"],
           "credibility": {"stations_total": a["stations_total"],
                           "real_stat": a["stations_real_stat"],
                           "simulated": a["stations_simulated"],
                           "with_basis": a["stations_with_basis"]},
           "source_note": a["source_note"]}
    if station_id:
        s = dl.find_station(sc, station_id)
        if s:
            out["station"] = s
            out["station_basis"] = s.get("anchor", "未标注推演依据")
        else:
            out["station"] = None
            out["note"] = f"未找到站点 '{station_id}'"
    return out


def t_config_simulation_param(ctx: ToolContext, baseline_flag=True, headway=None,
                              formation_cars=None, limit_level=None, demand_mult=None,
                              **extra) -> dict:
    if baseline_flag:
        cfg = {"scenario": ctx.scenario, "formation_cars": 8, "limit_level": 0,
               "demand_mult": 1.0, "baseline_flag": True}
        # 基准场景按线路属性取基准间隔（通勤 8min / 旅游 15min）；此处给统一口径 12min 的加权值
        cfg["headway_min"] = headway if headway is not None else 12.0
        cfg["_headway_by_type"] = True
    else:
        cfg = {"scenario": ctx.scenario,
               "headway_min": headway if headway is not None else 10.0,
               "formation_cars": formation_cars if formation_cars is not None else 8,
               "limit_level": limit_level if limit_level is not None else 0,
               "demand_mult": demand_mult if demand_mult is not None else 1.0,
               "baseline_flag": False}
    if extra:
        cfg.update({k: v for k, v in extra.items() if v is not None})
    norm, rec = S.normalize_config(cfg)
    return {"ok": True, "config": norm, "normalized": rec,
            "evidence": "agent/schemas.py::normalize_config（参数域收敛）"}


def t_guardrail_validate(ctx: ToolContext, param_json=None, plan_id=None, **kw) -> dict:
    p = {k: v for k, v in (param_json or {}).items() if k != "plan_id"}
    p.update({k: v for k, v in kw.items() if v is not None and k != "param_json"})
    if not p:
        return {"ok": False, "error": "param_json 为空", "plan_id": plan_id}
    v = gl.validate(p)
    if not v["passed"]:
        r = gl.repair(p)
        v["repair"] = {"ok": r["ok"], "rounds": r["rounds"],
                       "effective": {k: r["effective"][k] for k in
                                     ("headway_min", "formation_cars", "limit_level", "demand_mult")}}
    v["ok"] = True
    v["plan_id"] = plan_id
    v["evidence"] = "agent/guardrail.py::RULES（9 条确定性规则）"
    return v


def t_run_simulation(ctx: ToolContext, config_json=None, sim_engine="auto", hub=None,
                     plan_id=None, **kw) -> dict:
    cfg = {k: v for k, v in (config_json or {}).items() if k != "plan_id"}
    cfg.update({k: v for k, v in kw.items() if v is not None and k != "config_json"})
    cfg.setdefault("scenario", ctx.scenario)
    requested = S.normalize_config(cfg)[0]
    _F = ("headway_min", "formation_cars", "limit_level", "demand_mult")
    # ★ 证据链必须记录「调用方真正下发的原值」★
    #   requested 是钳制后的值，用它当证据会导致 requested ≡ repaired_to，
    #   评委看到的是「护栏什么也没改」——恰好把最该展示的拦截过程抹掉了。
    raw_asked = {k: cfg.get(k) for k in _F if k in cfg}
    # ★ 护栏闸门：越界参数不允许直接下发仿真，必须先经修正再执行 ★
    g = gl.validate(cfg)
    applied = None
    if not g["passed"]:
        rep = gl.repair(cfg)
        normalized_to = {k: requested[k] for k in _F}
        applied = {
            "intercepted": True,
            "violations": [{"id": v["id"], "name": v["name"], "why": v["why"], "fix": v["fix"]}
                           for v in g["violations"]],
            # 三段留痕：原始下发 → 规范钳制 → 逐条修复后实际执行
            "requested": raw_asked,
            "normalized_to": normalized_to,
            "repaired_to": {k: rep["effective"][k] for k in _F},
            "repair_rounds": rep["rounds"],
            "soft_clamped": g.get("soft_clamped", []),
        }
        cfg = dict(rep["effective"])
        cfg["scenario"] = requested["scenario"]
    r = sa.run_simulation(cfg, engine=sim_engine, hub=hub or ctx.hub)
    path = os.path.join(ctx.sim_dir, f"{r['run_id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    ctx.results[r["run_id"]] = r
    return {"ok": True, "run_id": r["run_id"], "result_path": path, "plan_id": plan_id,
            "engine": r["engine"], "engine_label": r["engine_label"],
            "engine_detail": r["engine_detail"],
            "metrics": r["metrics"], "top_bottlenecks": r["top_bottlenecks"],
            "config": r["config"], "requested_config": requested,
            "raw_requested": raw_asked,
            "guardrail_gate": {"passed": g["passed"], "intercepted": bool(applied),
                               "violations": [v["id"] for v in g["violations"]],
                               "checked_values": g.get("checked_values"),
                               "applied": applied},
            "normalized": r["normalized"],
            "evidence": f"仿真引擎 {r['engine']} · 结果落盘 {os.path.relpath(path, ctx.out_dir)}"
                        + ("· 参数经护栏修正后执行（原值 "
                           + ", ".join(f"{k}={raw_asked.get(k)}" for k in _F if k in raw_asked)
                           + "）" if applied else "· 参数一次通过护栏")
            }


def t_read_sim_result(ctx: ToolContext, result_path=None, **_) -> dict:
    if not result_path:
        return {"ok": False, "error": "缺少 result_path"}
    p = result_path
    if not os.path.isabs(p):
        cand = os.path.join(ctx.sim_dir, p if p.endswith(".json") else p + ".json")
        p = cand if os.path.exists(cand) else os.path.join(ctx.out_dir, result_path)
    if not os.path.exists(p):
        return {"ok": False, "error": f"结果文件不存在：{p}"}
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    m = d.get("metrics", {})
    problems = S.check_metrics(m)
    flat = {
        "平均延误(分)": m.get("avg_delay_min"),
        "站台最大饱和度": m.get("max_saturation"),
        "最大积压(人)": m.get("max_queue_persons"),
        "未承运(人/小时)": m.get("unmet_persons_per_hour"),
        "吞吐(人/小时)": m.get("throughput_persons_per_hour"),
        "枢纽饱和度": m.get("hub_saturation"),
        "牵引能耗(kWh/日)": m.get("energy_kwh_per_day"),
    }
    return {"ok": not problems, "result_path": p, "run_id": d.get("run_id"),
            "engine": d.get("engine"), "metrics": m, "normalized_metrics": flat,
            "contract_problems": problems, "top_bottlenecks": d.get("top_bottlenecks", [])[:5],
            "evidence": f"读取文件 {os.path.basename(p)}；契约校验"
                        + ("通过" if not problems else f"异常 {problems}")}


def t_generate_candidate_plan(ctx: ToolContext, problem_desc="", n_plans=3, **_) -> dict:
    """生成参数候选（不是结论）。三套候选覆盖「供给端 / 需求端 / 增购扩容」三类治理范式。

    注意：候选里刻意留了一条**会被护栏拦停**的方案（C）——
    这不是为了做演示效果，而是因为「压缩间隔不花钱」是竞赛/汇报里最常见的错误直觉。
    把配车约束显式建模后，护栏会当场把它拦下来并给出修正路径。
    """
    sc = ctx.scenario
    fl = int(S.DEFAULT_FLEET_LIMIT)
    plans = [
        {
            "id": "A", "name": "供给端：在配车上限内压缩发车间隔",
            "rationale": "不动需求端，直接把统一间隔由 12min 压到 10min。配车 447 列 ≤ 可用 480 列，"
                         "在车辆资产约束内，是「不增购前提下的最优供给改善」。",
            "config": {"scenario": sc, "headway_min": 10.0, "formation_cars": 8,
                       "limit_level": 0, "demand_mult": 1.0, "fleet_limit": fl},
        },
        {
            "id": "B", "name": "需求端：三级限流 + 维持既有间隔",
            "rationale": "不动运力，仅对超设计容量的站点实施三级限流（只出不进）。"
                         "能耗与配车完全不变，代价是站外滞留 —— 这是运能受限时的次优选择。",
            "config": {"scenario": sc, "headway_min": 12.0, "formation_cars": 8,
                       "limit_level": 3, "demand_mult": 1.0, "fleet_limit": fl},
        },
        {
            "id": "C", "name": "高密度运营（未同步申请增购车辆）",
            "rationale": "把间隔压到 8min。此处**故意不追加配车额度**，用以检验护栏能否识别"
                         "「纸面间隔排不出图」这一类不可执行方案。",
            "config": {"scenario": sc, "headway_min": 8.0, "formation_cars": 8,
                       "limit_level": 1, "demand_mult": 1.0, "fleet_limit": fl},
        },
    ][:max(1, int(n_plans or 3))]
    for p in plans:
        p["config"]["baseline_flag"] = False
    baseline = {"scenario": sc, "headway_min": 12.0, "formation_cars": 8,
                "limit_level": 0, "demand_mult": 1.0, "fleet_limit": fl,
                "baseline_flag": True}
    return {"ok": True, "problem_desc": problem_desc, "baseline_candidate": baseline,
            "plans": plans, "fleet_limit": fl,
            "evidence": "候选参数由三类治理范式生成；合法性交由护栏判定（含 GR-09 配车约束）"}


def t_sensitivity_scan(ctx: ToolContext, base_config=None, plan_id=None, **_) -> dict:
    """敏感性：客流 ±20%、发车间隔 ±2min。逐个方案独立扫描，互不搭便车。"""
    cfg = {k: v for k, v in (base_config or {}).items() if k != "plan_id"}
    cfg.setdefault("scenario", ctx.scenario)
    h = float(cfg.get("headway_min", 10.0))
    dm = float(cfg.get("demand_mult", 1.0))
    cases = []
    for label, dh, ddm in [
        ("基准", 0, 0.0), ("客流 +20%", 0, 0.2), ("客流 -20%", 0, -0.2),
        ("间隔 -2min", -2, 0.0), ("间隔 +2min", 2, 0.0),
        ("客流+20% & 间隔+2min", 2, 0.2),
    ]:
        c = dict(cfg)
        c["headway_min"] = max(4.0, h + dh)
        c["demand_mult"] = round(dm * (1.0 + ddm), 3)
        r = sa.run_engine_b(S.normalize_config(c)[0], ctx.scenario, ctx.hub)
        cases.append({"case": label, "headway_min": c["headway_min"], "demand_mult": c["demand_mult"],
                      "max_saturation": r["metrics"]["max_saturation"],
                      "avg_delay_min": r["metrics"]["avg_delay_min"],
                      "unmet_persons_per_hour": r["metrics"]["unmet_persons_per_hour"]})
    sats = [c["max_saturation"] for c in cases]
    robust = max(sats) <= 1.0
    return {"ok": True, "plan_id": plan_id, "cases": cases,
            "max_saturation_range": [min(sats), max(sats)],
            "robust": robust,
            "verdict": "推荐方案在全扰动域内均不超饱和" if robust else
                       "推荐方案在不利扰动下仍会超饱和，建议叠加需求端管控",
            "evidence": "6 组确定性扰动重仿真（同引擎、同数据）"}


def t_export_report_markdown(ctx: ToolContext, baseline=None, plans=None,
                             recommended=None, narration=None, **_) -> dict:
    from . import report as rp
    md = rp.build_markdown(baseline=baseline or {}, plans=plans or [],
                           recommended=recommended or "", narration=narration or "",
                           ctx=ctx)
    p = os.path.join(ctx.out_dir, "治理方案报告.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(md)
    return {"ok": True, "report_path": p, "chars": len(md),
            "evidence": f"报告落盘 {os.path.relpath(p, ctx.out_dir)}"}


def t_get_engine_status(ctx: ToolContext, **_) -> dict:
    s = sa.engine_status()
    return {"ok": True, **s,
            "evidence": "agent/sim_adapter.py::probe_transtar（真实文件系统探测）"}


DISPATCH = {
    "query_data_anchor": t_query_data_anchor,
    "config_simulation_param": t_config_simulation_param,
    "guardrail_validate": t_guardrail_validate,
    "run_simulation": t_run_simulation,
    "read_sim_result": t_read_sim_result,
    "generate_candidate_plan": t_generate_candidate_plan,
    "sensitivity_scan": t_sensitivity_scan,
    "export_report_markdown": t_export_report_markdown,
    "get_engine_status": t_get_engine_status,
}

TOOL_NAMES = list(DISPATCH.keys())


def call(ctx: ToolContext, name: str, args: dict | None = None) -> dict:
    fn = DISPATCH.get(name)
    if not fn:
        return {"ok": False, "error": f"未注册的工具 '{name}'",
                "available": TOOL_NAMES}
    try:
        return fn(ctx, **(args or {}))
    except TypeError as e:
        return {"ok": False, "error": f"参数不匹配：{e}", "tool": name, "args": args}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "tool": name}
