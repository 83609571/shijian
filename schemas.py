"""L1 数据层 · 数据契约（JSON-Schema 风格，纯标准库实现）

设计目的：
  1. 固定「智能体 ↔ 仿真 ↔ 前端」三方的数据形状，避免 P0-5 版本漂移
     （旧交接包里 sim 脚本输出 12 站、web 数据是 34 站，两套口径并存）。
  2. 所有越界值在此被规范化并记录 `normalized` 记录，绝不静默改数。

不使用 pydantic，是为了让本模块在零第三方依赖下也能跑
（评委拿到 zip 后 `python3 run_agent.py` 即可复现，无需 pip install）。
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone

SCHEMA_VERSION = "1.0"

# ---------------- 常量：仿真物理参数（全部显式、可答辩）----------------
SEATS_PER_CAR = 90           # 单节定员（跨座式单轨/城际公交化列车）
OPERATING_HOURS = 16.0       # 日运营小时
LOAD_AVAILABILITY = 0.95     # 车辆可用率（检修备用）
PEAK_HOUR_SHARE = 0.12       # 高峰小时系数（占全日客流）
CHANNEL_WIDTH_M = 8.0        # 枢纽换乘通道有效净宽
CHANNEL_FLOW_PER_M_MIN = 60.0  # 通道单位宽度通行能力 人/(m·min)
MAX_QUEUE_WINDOW_H = 0.5     # 积压统计窗口（半小时）

GUARDRAIL = {
    "headway_min":   {"min": 4.0,  "max": 30.0, "unit": "min",  "note": "最小发车间隔受信号与折返能力约束；超过 30min 不构成公共交通服务"},
    "formation_cars": {"enum": [2, 4, 6, 8],    "unit": "辆",   "note": "编组上限受站台长度约束，8 辆为站台设计上限"},
    "limit_level":   {"enum": [0, 1, 2, 3],     "unit": "级",   "note": "0=不限流 1=一级 2=二级 3=三级（只出不进）"},
    "demand_mult":   {"min": 0.5,  "max": 2.0,  "unit": "倍",   "note": "需求乘子，超出 ±100% 视为模型外推不可信"},
    "fleet_limit":   {"min": 6,    "max": 1200, "unit": "列",   "note": "可用列车总数上限（车辆资产硬约束）"},
}

DEFAULT_FLEET_LIMIT = 480   # 全网可用列车数（列，含检修备用）—— 见下方说明
# 说明：本网络为**省域尺度**复合轨道网（12 条线，营业里程合计约 2 699 km），
# 按城际公交化 120 km/h、跨座式单轨 60 km/h 核算，12 min 统一间隔需配车 374 列。
# 初期投放 480 列为方案给定规模，因此「继续压缩间隔」会顶到车辆资产上限 ——
# 这是护栏 GR-09 得以真实拦停方案的物理依据，不是人为设卡。


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def digest(obj) -> str:
    """对任意可序列化对象取短摘要，用于 trace 中比对入参/出参是否变化。"""
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def normalize_config(raw: dict) -> tuple[dict, list[dict]]:
    """把任意来源（LLM 输出 / 前端 / 命令行）的参数收敛到合法区间。

    返回 (规范化后的配置, 规范化记录列表)。规范化记录会进入 trace，
    保证「LLM 原始输出」与「实际执行参数」都可追溯 —— 这是护栏可解释性的关键。
    """
    raw = raw or {}
    record: list[dict] = []
    cfg = {}

    def clamp(key, default):
        spec = GUARDRAIL[key]
        v = raw.get(key, default)
        try:
            if "enum" in spec:
                v = int(v)
                if v not in spec["enum"]:
                    pick = min(spec["enum"], key=lambda x: abs(x - v))
                    record.append({"field": key, "from": raw.get(key), "to": pick,
                                   "rule": f"enum{spec['enum']}"})
                    v = pick
            else:
                v = float(v)
                if v < spec["min"]:
                    record.append({"field": key, "from": raw.get(key), "to": spec["min"],
                                   "rule": f">={spec['min']}"})
                    v = spec["min"]
                elif v > spec["max"]:
                    record.append({"field": key, "from": raw.get(key), "to": spec["max"],
                                   "rule": f"<={spec['max']}"})
                    v = spec["max"]
        except (TypeError, ValueError):
            record.append({"field": key, "from": raw.get(key), "to": default,
                           "rule": "type-fallback"})
            v = default
        return v

    cfg["headway_min"] = round(clamp("headway_min", 8.0), 2)
    cfg["formation_cars"] = int(clamp("formation_cars", 8))
    cfg["limit_level"] = int(clamp("limit_level", 0))
    cfg["demand_mult"] = round(clamp("demand_mult", 1.0), 3)
    cfg["fleet_limit"] = int(clamp("fleet_limit", DEFAULT_FLEET_LIMIT))
    cfg["scenario"] = raw.get("scenario", "holiday")
    if cfg["scenario"] not in ("weekday", "holiday"):
        record.append({"field": "scenario", "from": raw.get("scenario"), "to": "holiday",
                       "rule": "enum['weekday','holiday']"})
        cfg["scenario"] = "holiday"

    # 分流比例：三级限流时仅开放部分进站量
    cfg["intake_factor"] = {0: 1.0, 1: 0.92, 2: 0.80, 3: 0.65}[cfg["limit_level"]]
    cfg["baseline_flag"] = bool(raw.get("baseline_flag", False))
    return cfg, record


_RULE_FIELDS = ("headway_min", "formation_cars", "limit_level", "demand_mult")


def fill_defaults(raw: dict) -> dict:
    """只补默认值、**不做区间钳制**的参数装配（护栏校验专用通道）。

    为什么必须单独有一条通道：
        原实现里 guardrail.validate() 是把 9 条规则跑在 normalize_config() 的
        输出上，而后者已经把越界值钳回合法区间 —— 规则永远看不到越界值。
        实测后果：GR-01 / GR-02 / GR-03 / GR-04 / GR-06 / GR-08 六条规则
        **从未触发过**，只有 GR-05 / GR-07 / GR-09 有可能命中。
        也就是说「9 条护栏规则真实拦截」这句话当时是站不住的。
        现在：规则判定跑在本函数（原值）上，effective 仍走 normalize_config（钳制后）。

    注意与 normalize_config 的分工：
        fill_defaults  → 回答「调用方要什么」→ 给护栏看
        normalize_config → 回答「实际能执行什么」→ 给仿真看
    """
    raw = raw or {}
    out = {}
    for key, default in (("headway_min", 8.0), ("formation_cars", 8),
                         ("limit_level", 0), ("demand_mult", 1.0),
                         ("fleet_limit", DEFAULT_FLEET_LIMIT)):
        v = raw.get(key, default)
        try:
            v = int(v) if key in ("formation_cars", "limit_level", "fleet_limit") else float(v)
        except (TypeError, ValueError):
            v = default
        out[key] = v
    sc = raw.get("scenario", "holiday")
    out["scenario"] = sc if sc in ("weekday", "holiday") else "holiday"
    out["baseline_flag"] = bool(raw.get("baseline_flag", False))
    out["intake_factor"] = {0: 1.0, 1: 0.92, 2: 0.80, 3: 0.65}.get(out["limit_level"], 1.0)
    return out


def metrics_shape() -> dict:
    """仿真输出指标的契约骨架（供文档与校验使用）。"""
    return {
        "avg_delay_min": float,        # 需求加权平均候车+滞留延误（分钟）
        "max_saturation": float,       # 最大站台/通道饱和度
        "max_queue_persons": int,      # 最大积压人数
        "unmet_persons_per_hour": int,  # 断面无法承运人数（人/小时）
        "deferred_persons_per_hour": int,  # 限流滞留（站外未进站）人数（人/小时）
        "throughput_persons_per_hour": int,
        "hub_saturation": float,       # 枢纽换乘通道饱和度
        "required_trains": int,        # 完成该方案所需配车数（列）
        "energy_kwh_per_day": float,   # 牵引能耗估算
        "per_line": list,
    }


def check_metrics(m: dict) -> list[str]:
    """契约校验：返回缺失/类型不符的字段列表（空列表 = 通过）。"""
    problems = []
    for k, t in metrics_shape().items():
        if k not in m:
            problems.append(f"missing:{k}")
        elif t is float and not isinstance(m[k], (int, float)):
            problems.append(f"type:{k}")
    for k in ("max_saturation", "hub_saturation"):
        if k in m and isinstance(m[k], (int, float)) and not math.isfinite(m[k]):
            problems.append(f"nonfinite:{k}")
    return problems


def decision_document(*, engine, scenario, parsed, baseline, plans, recommended,
                      agents, risk_segments, reroute, trace_meta, narration) -> dict:
    """组装前端要消费的 `agent_decision.json`（唯一真源，前端不再硬编码）。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "engine": engine,
        "scenario": scenario,
        "problem_parsed": parsed,
        "baseline": baseline,
        "plans": plans,
        "recommended": recommended,
        "agents": agents,
        "risk_segments": risk_segments,
        "reroute": reroute,
        "trace": trace_meta,
        "narration": narration,
    }
