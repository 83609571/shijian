#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""赣鄱智轨 · 交互演示台 API + 静态服务（零第三方依赖，纯 Python 标准库）

作用（I1 批次，依据 决赛材料/Z_交互呈现增强工作包.md）：
  1) 把仿真 / 通信 / 智能体能力包成本地 HTTP 接口，评委出题、后端现算；
  2) 非 /api/* 的 GET 回退为项目根静态文件，stage.html 与 API 同源，
     不需要 CORS、不需要第二个端口；
  3) 所有运行产物写 output/scratch/，data/agent_decision*.json 等冻结
     文件一律只读，现场反复点不污染答辩真源。

用法：
    python3 api_server.py               # 默认监听 127.0.0.1:8000（现场不对外暴露）
    HOST=0.0.0.0 PORT=9000 python3 api_server.py
    python3 api_server.py --selftest    # 自检：6 条路由全 200 且 /api/sla < 30ms

接口：
    GET  / /health                      健康检查 + 使用说明
    GET  /decision?scenario=...         读取冻结决策文档（只读，不重跑）
    POST /run?scenario=...&hub=...      现场运行完整智能体（兼容旧入口，产物同样进 scratch）
    POST /api/simulate                  入参 {scenario,hub,headway,formation_cars,limit_level,demand_mult}
                                        返回基准与该配置的指标 + Critic 口径评分（不跑智能体）
    POST /api/sla                       入参 {net,slice,mec,isac,ai_air,event}
                                        返回 R=(感知+传输+计算)×轮次+执行 五段分解与成功率；
                                        ai_air=true 且 5G-A 时附弱覆盖段成功率对照（I3）
    POST /api/score                     入参 {weights:{congestion,service,cost,robustness},scenario,hub}
                                        权重归一化后重算四方案总分（I2a；维度分取自 Critic 原始输出，
                                        权重常量出处 agent/agent_loop.py:34，公式同构 399-400 行）；
                                        P2 服务底线：admissible = 过护栏且延误/未承运不高于现状，
                                        recommended = admissible 中最高分（与 /api/run 共用规则）
    POST /api/run                       同 /run，JSON 入参，返回决策 JSON 与耗时；
                                        每个 plan 附经济标签（additional_trains /
                                        requires_capex / policy_flag /
                                        breakeven_vot_yuan_per_hour，E1 运行时派生，
                                        口径见 决赛材料/经济性与投入产出应答口径_v1.0.md）
    GET  /api/trace/latest?limit=40     output/trace/ 最新一份的 meta + events
    GET  /api/anchors                   flow_*.json 的 real_anchors + 每站 anchor/real + 通信锚点台账
    GET  /api/stations?scenario=...     34 站溯源台账 + 统计（I2b）
    GET  /*（其余）                      静态文件回退（默认 index.html，防目录穿越）

安全与口径：
  - HOST 默认 127.0.0.1；/api/run 默认 provider=local（离线确定性，断网可跑），
    显式传 provider 才联网，与 A1 口径纪律一致；
  - 所有接口带 X-Response-Time 头；目标 /api/simulate <120ms、/api/sla <30ms、/api/run <2s；
  - 非法入参返回 400 结构化 JSON（{ok:false, error, allowed}），任何异常不向前端抛堆栈；
  - 数字全部来自 sim/ 与 experiments.py 既有函数，本文件不含任何计算常量。
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RUN_AGENT = os.path.join(HERE, "run_agent.py")
SCRATCH_DIR = os.path.join(HERE, "output", "scratch")
TRACE_DIR = os.path.join(HERE, "output", "trace")
VERSION = "决赛版 v3.0"

# 智能体单次完整运行 0.23s，但首次冷启动含解释器/IO，给足余量
RUN_TIMEOUT = 120
LOCK = threading.Lock()  # 同一时刻只允许一次智能体运行，防止产物竞争

PROVIDERS = ("local", "deepseek", "glm", "openai", "auto")
SCENARIOS = ("holiday", "weekday")

# /api/simulate 展示层入参边界（仅供 400 提示；引擎常量仍以 sim/ 为准，此处不复制口径数值）
SIM_LIMITS = {
    "headway": (3.0, 30.0),
    "formation_cars": (2, 12),
    "limit_level": (0, 3),
    "demand_mult": (0.5, 3.0),
}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".map": "application/json",
    ".woff2": "font/woff2",
}


class ApiError(Exception):
    """带 HTTP 状态码的业务异常：被捕获后回结构化 JSON，不抛堆栈。"""

    def __init__(self, code: int, message: str, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.extra = extra or {}


# ---------------- 惰性引擎导入（数字全部来自既有模块） ----------------
_EXP = None
_EXP_LOCK = threading.Lock()


def experiments():
    global _EXP
    if _EXP is None:
        with _EXP_LOCK:
            if _EXP is None:
                import experiments as exp_mod  # 复用 run()/score_plan()，口径与消融实验一致
                _EXP = exp_mod
    return _EXP


_CL = None
_CL_LOCK = threading.Lock()


def comm_layer():
    global _CL
    if _CL is None:
        with _CL_LOCK:
            if _CL is None:
                from sim import comm_layer as cl_mod  # 复用 response_time()，R 链路唯一口径
                _CL = cl_mod
    return _CL


_PD = None
_PD_LOCK = threading.Lock()


def predict_mod():
    """赛后迭代层（predict.py）：百度真实数据 + 客流预测。
    只加新层不改冻结口径：不读改 data/、不动 sim/ 常量，产物只进 scratch。"""
    global _PD
    if _PD is None:
        with _PD_LOCK:
            if _PD is None:
                import predict as pd_mod
                _PD = pd_mod
    return _PD


_FLOW: dict = {}
_FLOW_LOCK = threading.Lock()


def flow_data(scenario: str) -> dict:
    with _FLOW_LOCK:
        if scenario not in _FLOW:
            p = os.path.join(HERE, "data", f"flow_{scenario}.json")
            with open(p, encoding="utf-8") as f:
                _FLOW[scenario] = json.load(f)
    return _FLOW[scenario]


def station_names(scenario: str) -> list:
    return [s.get("name") for s in flow_data(scenario).get("stations", []) if s.get("name")]


# ---------------- 智能体子进程（产物只进 scratch） ----------------
# 经济性标签口径（E1，依据 决赛材料/经济性与投入产出应答口径_v1.0.md 第二节；
# 属展示层派生常量，不改 sim/ agent/ 任何计算常量）
FLEET_AVAILABLE = 480            # 现有可用车辆（列）
ELEC_PRICE_YUAN_PER_KWH = 0.65   # 电价占位口径（元/kWh）
ECONOMICS_NOTE = ("盈亏平衡时间价值 = 日增电费 ÷ 日减旅客延误人·小时；"
                  "按节假日客流总量与系统平均延误线性折算，未计人工与维保，属下限估计。")

_HOLIDAY_FLOW = None
_HOLIDAY_FLOW_LOCK = threading.Lock()


def holiday_daily_flow() -> int:
    """节假日客流总量 = data/flow_holiday.json 34 站 flow 汇总（运行时读取，约 36.2 万人/日）。"""
    global _HOLIDAY_FLOW
    with _HOLIDAY_FLOW_LOCK:
        if _HOLIDAY_FLOW is None:
            _HOLIDAY_FLOW = sum(s.get("flow", 0)
                                for s in flow_data("holiday").get("stations", []))
    return _HOLIDAY_FLOW


def _fmt_num(v) -> str:
    """拒绝理由里的数值展示：保留引擎精度，去掉浮点尾巴。"""
    return "%g" % round(v, 2)


def admissibility_of(plan: dict, base_metrics: dict) -> tuple[bool, str | None]:
    """P2 服务底线（/api/run 与 /api/score 共用，保证两接口口径一致）：

    admissible = feasible 且 延误不高于现状 且 未承运不高于现状。
    返回 (admissible, reject_reason)；数值由 metrics 动态生成，不写死。
    """
    if plan.get("feasible") is False:
        return False, plan.get("block_reason") or "护栏拦截"
    m = plan.get("metrics") or {}
    d, bd = m.get("avg_delay_min"), base_metrics.get("avg_delay_min")
    u, bu = m.get("unmet_persons_per_hour"), base_metrics.get("unmet_persons_per_hour")
    reasons = []
    if isinstance(d, (int, float)) and isinstance(bd, (int, float)) and d > bd:
        reasons.append(f"未过服务底线：延误 {_fmt_num(d)} 高于现状 {_fmt_num(bd)}")
    if isinstance(u, (int, float)) and isinstance(bu, (int, float)) and u > bu:
        reasons.append(f"未过服务底线：未承运 {_fmt_num(u)} 高于现状 {_fmt_num(bu)}")
    if reasons:
        return False, "；".join(reasons)
    if not isinstance(d, (int, float)) or not isinstance(u, (int, float)):
        return False, "未过服务底线：方案指标缺失"
    return True, None


def fleet_block_reason(violations: list) -> str:
    """把护栏违规项拼成一句可直接展示的拦截原因（数值取 violations 明细，不写死）。

    例：GR-09 配车超限：需 582 列，可用 480 列
    """
    parts = []
    for v in violations:
        vid = v.get("id") or "GR"
        need = (v.get("fleet_detail") or {}).get("required_trains")
        if vid == "GR-09" and isinstance(need, (int, float)):
            parts.append(f"{vid} 配车超限：需 {int(round(need))} 列，"
                         f"可用 {FLEET_AVAILABLE} 列")
        else:
            parts.append(f"{vid} {v.get('name') or '护栏拦截'}".strip())
    return "；".join(parts) or "未通过护栏校验"


def attach_economics(doc: dict) -> dict:
    """为 /api/run 响应体的每个 plan 附加经济性派生字段（仅内存，不写回 data/）。

    未过护栏（guardrail.passed == false）的方案不可执行：feasible=False，
    block_reason 由违规项拼出，经济字段一律 null（避免被读成「免费的更优解」）。

    通过护栏时：
    additional_trains = max(0, required_trains - 480)
    requires_capex    = additional_trains > 0
    policy_flag       = "expand_fleet"（该方案 config.fleet_limit > 480 时）
    breakeven_vot_yuan_per_hour = 日增电费 ÷ 日减旅客延误人·小时（延误不降则 null）
    """
    base = doc.get("baseline", {}).get("metrics", {})
    base_delay = base.get("avg_delay_min")
    base_energy = base.get("energy_kwh_per_day")
    total_flow = holiday_daily_flow()
    for plan in doc.get("plans", []):
        guardrail = plan.get("guardrail") or {}
        if guardrail.get("passed") is False:
            plan["feasible"] = False
            plan["block_reason"] = fleet_block_reason(guardrail.get("violations") or [])
            plan["additional_trains"] = None
            plan["requires_capex"] = None
            plan["policy_flag"] = None
            plan["breakeven_vot_yuan_per_hour"] = None
            plan["admissible"], plan["reject_reason"] = admissibility_of(plan, base)
            continue
        plan["feasible"] = True
        plan["block_reason"] = None
        metrics = plan.get("metrics", {})
        rt = metrics.get("required_trains")
        add = max(0, rt - FLEET_AVAILABLE) if isinstance(rt, (int, float)) else None
        plan["additional_trains"] = add
        plan["requires_capex"] = (add > 0) if add is not None else None
        fl = (plan.get("config") or {}).get("fleet_limit")
        plan["policy_flag"] = ("expand_fleet"
                               if isinstance(fl, (int, float)) and fl > FLEET_AVAILABLE else None)
        be = None
        if isinstance(base_delay, (int, float)) and isinstance(base_energy, (int, float)):
            d = metrics.get("avg_delay_min")
            e = metrics.get("energy_kwh_per_day")
            if isinstance(d, (int, float)) and isinstance(e, (int, float)):
                saved_ph = total_flow * (base_delay - d) / 60.0
                cost_yuan = (e - base_energy) * ELEC_PRICE_YUAN_PER_KWH
                if saved_ph > 0 and cost_yuan > 0:
                    be = round(cost_yuan / saved_ph, 1)
        plan["breakeven_vot_yuan_per_hour"] = be
        plan["admissible"], plan["reject_reason"] = admissibility_of(plan, base)
    doc["economics"] = {
        "fleet_available": FLEET_AVAILABLE,
        "elec_price_yuan_per_kwh": ELEC_PRICE_YUAN_PER_KWH,
        "holiday_daily_flow_persons": total_flow,
        "note": ECONOMICS_NOTE,
    }
    return doc


def run_agent(scenario: str, hub: str, provider: str = "local") -> tuple[dict, str, float]:
    """跑完整智能体链路，返回 (决策文档, 产物相对路径, 耗时秒)。

    --out 指向 output/scratch/：sim_results/ 快照、trace/、治理报告全部落 scratch，
    既不写 data/agent_decision*.json（冻结只读），也不覆盖 output/ 下的已跟踪文件。
    """
    ts = time.strftime("%Y%m%dT%H%M%S")
    out_path = os.path.join(SCRATCH_DIR, f"agent_decision_{scenario}_{ts}.json")
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    cmd = [sys.executable, RUN_AGENT,
           "--scenario", scenario, "--hub", hub,
           "--provider", provider,
           "--out", SCRATCH_DIR,
           "--decision-out", out_path, "--quiet"]
    # 子进程强制 UTF-8 输出（Windows 控制台默认 GBK，混合解码会崩）
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=RUN_TIMEOUT, env=env)
    elapsed = time.perf_counter() - t0
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        raise ApiError(500, f"run_agent.py 退出码 {proc.returncode}：{tail}")
    with open(out_path, encoding="utf-8") as f:
        return json.load(f), os.path.relpath(out_path, HERE), elapsed


def read_decision(scenario: str) -> dict | None:
    p = os.path.join(HERE, "data", f"agent_decision_{scenario}.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ---------------- 入参校验（白名单 + 类型，非法即 400） ----------------
def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _reject_unknown(params: dict, allowed: tuple, endpoint: str) -> None:
    """入参白名单：JSON body 里的未知字段一律 400（防止拼错字段名被静默忽略）。"""
    unknown = sorted(k for k in params if k not in allowed)
    if unknown:
        raise ApiError(400, "{} 收到未知字段：{}（白名单校验）".format(endpoint, "、".join(unknown)),
                       {"allowed": list(allowed)})


# Z3b：字符串入参最大长度（对抗超长文本注入；演示接口无合法超长用例）
MAX_TEXT_LEN = 64


def _check_text_len(params: dict, endpoint: str) -> None:
    for k, v in params.items():
        if isinstance(v, str) and len(v) > MAX_TEXT_LEN:
            raise ApiError(400, "{}.{} 超过最大长度 {}（实际 {} 字符）".format(
                endpoint, k, MAX_TEXT_LEN, len(v)),
                {"allowed": {"max_text_len": MAX_TEXT_LEN}})


def _pick(params: dict, q: dict, key: str):
    """JSON body 优先，query 兜底。"""
    if key in params:
        return params[key]
    vals = q.get(key)
    return vals[0] if vals else None


def validate_run_params(params: dict, q: dict) -> dict:
    _reject_unknown(params, ("scenario", "hub", "provider"), "/api/run")
    _check_text_len(params, "/api/run")
    scen = _pick(params, q, "scenario") or "holiday"
    if scen not in SCENARIOS:
        raise ApiError(400, f"scenario 必须是 {' 或 '.join(SCENARIOS)}",
                       {"allowed": {"scenario": list(SCENARIOS)}})
    hub = _pick(params, q, "hub") or "南昌站"
    if hub not in station_names(scen):
        raise ApiError(400, f"hub「{hub}」不在 {scen} 场景站点表中",
                       {"allowed": {"hub": station_names(scen)[:8] + ["…"]}})
    provider = _pick(params, q, "provider") or "local"
    if provider not in PROVIDERS:
        raise ApiError(400, f"provider 必须是 {'/'.join(PROVIDERS)}",
                       {"allowed": {"provider": list(PROVIDERS)}})
    return {"scenario": scen, "hub": hub, "provider": provider}


def validate_simulate_params(params: dict, q: dict) -> dict:
    _reject_unknown(params, ("scenario", "hub", "headway",
                             "formation_cars", "limit_level", "demand_mult"), "/api/simulate")
    _check_text_len(params, "/api/simulate")
    scen = _pick(params, q, "scenario") or "holiday"
    if scen not in SCENARIOS:
        raise ApiError(400, f"scenario 必须是 {' 或 '.join(SCENARIOS)}",
                       {"allowed": {"scenario": list(SCENARIOS)}})
    hub = _pick(params, q, "hub") or "南昌站"
    if hub not in station_names(scen):
        raise ApiError(400, f"hub「{hub}」不在 {scen} 场景站点表中",
                       {"allowed": {"hub": station_names(scen)[:8] + ["…"]}})

    headway = _pick(params, q, "headway")
    headway = 8.0 if headway is None else headway
    if not _is_num(headway) or not SIM_LIMITS["headway"][0] <= headway <= SIM_LIMITS["headway"][1]:
        raise ApiError(400, "headway 必须是 3~30 的数字（发车间隔，分钟）",
                       {"allowed": {"headway": list(SIM_LIMITS["headway"])}})

    cars = _pick(params, q, "formation_cars")
    cars = 8 if cars is None else cars
    if isinstance(cars, bool) or not isinstance(cars, int) \
            or not SIM_LIMITS["formation_cars"][0] <= cars <= SIM_LIMITS["formation_cars"][1]:
        raise ApiError(400, "formation_cars 必须是 2~12 的整数（每列编组辆数）",
                       {"allowed": {"formation_cars": list(SIM_LIMITS["formation_cars"])}})

    limit = _pick(params, q, "limit_level")
    limit = 1 if limit is None else limit
    if isinstance(limit, bool) or not isinstance(limit, int) \
            or not SIM_LIMITS["limit_level"][0] <= limit <= SIM_LIMITS["limit_level"][1]:
        raise ApiError(400, "limit_level 必须是 0~3 的整数（限流等级）",
                       {"allowed": {"limit_level": list(SIM_LIMITS["limit_level"])}})

    mult = _pick(params, q, "demand_mult")
    mult = 1.0 if mult is None else mult
    if not _is_num(mult) or not SIM_LIMITS["demand_mult"][0] <= mult <= SIM_LIMITS["demand_mult"][1]:
        raise ApiError(400, "demand_mult 必须是 0.5~3.0 的数字（客流倍率）",
                       {"allowed": {"demand_mult": list(SIM_LIMITS["demand_mult"])}})

    return {"scenario": scen, "hub": hub, "headway": float(headway),
            "formation_cars": cars, "limit_level": limit, "demand_mult": float(mult)}


def validate_sla_params(params: dict, q: dict) -> dict:
    _reject_unknown(params, ("net", "slice", "mec", "isac", "ai_air", "event"), "/api/sla")
    _check_text_len(params, "/api/sla")
    cl = comm_layer()
    net = _pick(params, q, "net") or "4G"
    if net not in cl.NET_PROFILES:
        raise ApiError(400, f"net 必须是 {'/'.join(cl.NET_PROFILES)}",
                       {"allowed": {"net": list(cl.NET_PROFILES)}})
    event = _pick(params, q, "event") or "train_fault"
    if event not in cl.INCIDENT_TYPES:
        raise ApiError(400, f"event 必须是 {'/'.join(cl.INCIDENT_TYPES)}",
                       {"allowed": {"event": list(cl.INCIDENT_TYPES)}})
    sl = _pick(params, q, "slice")
    if sl is not None and sl not in cl.SLICE_PROFILES:
        raise ApiError(400, f"slice 必须是 {'/'.join(cl.SLICE_PROFILES)} 或不传",
                       {"allowed": {"slice": list(cl.SLICE_PROFILES)}})
    mec = _pick(params, q, "mec")
    if mec is not None and mec not in cl.MEC_NODES:
        raise ApiError(400, f"mec 必须是 {'/'.join(cl.MEC_NODES)} 或不传",
                       {"allowed": {"mec": list(cl.MEC_NODES)}})
    isac = _pick(params, q, "isac")
    if isac is not None and not isinstance(isac, bool):
        raise ApiError(400, "isac 必须是布尔值 true/false",
                       {"allowed": {"isac": [True, False]}})
    ai_air = _pick(params, q, "ai_air")
    if ai_air is not None and not isinstance(ai_air, bool):
        raise ApiError(400, "ai_air 必须是布尔值 true/false",
                       {"allowed": {"ai_air": [True, False]}})
    return {"net": net, "event": event, "slice": sl, "mec": mec,
            "isac": bool(isac), "ai_air": bool(ai_air)}


SCORE_DIMS = ("congestion", "service", "cost", "robustness")


def validate_score_params(params: dict, q: dict) -> dict:
    _reject_unknown(params, ("scenario", "hub", "weights"), "/api/score")
    _check_text_len(params, "/api/score")
    scen = _pick(params, q, "scenario") or "holiday"
    if scen not in SCENARIOS:
        raise ApiError(400, f"scenario 必须是 {' 或 '.join(SCENARIOS)}",
                       {"allowed": {"scenario": list(SCENARIOS)}})
    hub = _pick(params, q, "hub") or "南昌站"
    if hub not in station_names(scen):
        raise ApiError(400, f"hub「{hub}」不在 {scen} 场景站点表中",
                       {"allowed": {"hub": station_names(scen)[:8] + ["…"]}})
    w = params.get("weights")
    if not isinstance(w, dict):
        raise ApiError(400, "weights 必须是对象，含 congestion/service/cost/robustness 四个键",
                       {"allowed": {"weights": list(SCORE_DIMS)}})
    raw = {}
    for k in SCORE_DIMS:
        v = w.get(k)
        if not _is_num(v) or not math.isfinite(v) or v < 0:
            raise ApiError(400, f"weights.{k} 必须是 ≥0 的数字",
                           {"allowed": {"weights": {k: "number ≥0"}}})
        raw[k] = float(v)
    total = sum(raw.values())
    if total <= 0:
        raise ApiError(400, "权重之和必须大于 0", {"allowed": {"weights": "至少一项 >0"}})
    norm = {k: raw[k] / total for k in SCORE_DIMS}
    return {"scenario": scen, "hub": hub, "weights_raw": raw, "weights_norm": norm}


def decision_doc_for(scenario: str, hub: str) -> tuple[dict, bool]:
    """评分用决策文档：(holiday, 南昌站) 直接用冻结真源 data/agent_decision.json；
    其余组合现跑离线确定性智能体（产物仍只进 scratch）。返回 (doc, 是否冻结真源)。"""
    if scenario == "holiday" and hub == "南昌站":
        p = os.path.join(HERE, "data", "agent_decision.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f), True
    doc, _, _ = run_agent(scenario, hub, "local")
    return doc, False


# ---------------- trace 步骤统一化（I4：前端不解析原始 JSON 结构） ----------------
TRACE_SUFFIX = "_trace.json"
RUN_ID_RE = re.compile(r"[A-Za-z0-9_\-]{1,100}")


def trace_files():
    """扫描两个 trace 落点，返回 [(run_id, 绝对路径)]；run_id = 文件名去掉 _trace.json。"""
    out = []
    for d in (TRACE_DIR, os.path.join(SCRATCH_DIR, "trace")):
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(TRACE_SUFFIX):
                    out.append((f[:-len(TRACE_SUFFIX)], os.path.join(d, f)))
    return out


def _parse_maybe_json(v):
    """trace 里 violations/applied/metrics 等字段是二次编码的 JSON 字符串，统一解开。"""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v


def _num(v, nd=2):
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return v


def _guardrail_block(ev):
    """从 guardrail_validate 事件提取三段留痕；非护栏事件返回 None。

    注意：trace 录制器会把超长字符串截断成「…(len=N)」（violations/applied/effective
    均可能被截断而无法 json.loads），因此三段取自未截断的结构化字段：
    requested = 入参 param_json；normalized = checked_values；repaired = repair.effective；
    rule_id/violations 用正则从被截断字符串的可读前缀提取。three_stage 字符串本身完整，
    一并返回作兜底展示。
    """
    res = ev.get("result")
    if not isinstance(res, dict) or ("passed" not in res and "three_stage" not in res):
        return None
    raw_violations = res.get("violations")
    violations = _parse_maybe_json(raw_violations)
    if not isinstance(violations, list):
        s = raw_violations if isinstance(raw_violations, str) else ""
        ids = list(dict.fromkeys(re.findall(r"GR-\d{2}", s)))
        names = re.findall(r'"name":\s*"([^"]+)"', s)
        violations = [{"id": i, "name": names[j] if j < len(names) else None}
                      for j, i in enumerate(ids)]
    repair = res.get("repair") if isinstance(res.get("repair"), dict) else None
    args = ev.get("args")
    requested = args.get("param_json") if isinstance(args, dict) else None
    repaired = None
    if isinstance(repair, dict) and isinstance(repair.get("effective"), dict):
        repaired = repair["effective"]
    return {
        "rule_id": ",".join(v.get("id") for v in violations if v.get("id")) or None,
        "requested": requested,
        "normalized": res.get("checked_values") if isinstance(res.get("checked_values"), dict) else None,
        "repaired": repaired,
        "passed": res.get("passed"),
        "violations": violations,
        "three_stage": res.get("three_stage"),
    }


def _metrics_summary(metrics):
    m = _parse_maybe_json(metrics)
    if not isinstance(m, dict):
        return None
    return "饱和度 {} · 延误 {}min · 未承运 {}/h".format(
        _num(m.get("max_saturation")), _num(m.get("avg_delay_min")),
        _num(m.get("unmet_persons_per_hour"), 0))


def _result_summary(tool, res):
    """按工具生成一句话返回摘要；未知工具走通用兜底（标量键值前 3 项）。"""
    if not isinstance(res, dict):
        return "（无结构化返回）"
    if tool == "guardrail_validate":
        if res.get("passed") is False:
            v = _parse_maybe_json(res.get("violations"))
            if not isinstance(v, list):
                ids = list(dict.fromkeys(re.findall(r"GR-\d{2}", res.get("violations") or "")))
                v = [{"id": i} for i in ids]
            names = "、".join(x.get("id") for x in v if isinstance(x, dict) and x.get("id"))
            return "护栏拦截：{}".format(names or "违规")
        return "护栏通过{}".format("（方案 {}）".format(res["plan_id"]) if res.get("plan_id") else "")
    if tool in ("run_simulation", "read_sim_result"):
        parts = ["run {}".format(res.get("run_id"))]
        if res.get("engine"):
            parts.append("引擎 {}".format(res["engine"]))
        ms = _metrics_summary(res.get("metrics"))
        if ms:
            parts.append(ms)
        return " · ".join(parts)
    if tool == "generate_candidate_plan":
        plans = _parse_maybe_json(res.get("plans")) or []
        ids = [p.get("id") for p in plans if isinstance(p, dict) and p.get("id")]
        return "生成 {} 个候选方案：{}".format(len(ids), "、".join(ids) if ids else "—")
    if tool == "config_simulation_param":
        return "参数已配置（归一化 {} 项）".format(len(res.get("normalized") or []))
    if tool == "get_engine_status":
        return "活跃引擎：{}".format(res.get("active"))
    scalars = [(k, v) for k, v in res.items()
               if isinstance(v, (str, int, float, bool)) and k != "ok"]
    brief = " · ".join("{}={}".format(k, _num(v) if isinstance(v, float) else v)
                       for k, v in scalars[:3])
    return ("ok · " + brief) if brief else "ok"


def _build_steps(events):
    """把原始 events 统一为 steps：index/phase/tool/args/result_summary/
    duration_ms/guardrail（rule_id, requested, normalized, repaired, passed）。"""
    steps = []
    for i, ev in enumerate(events, 1):
        kind = ev.get("kind")
        actor = ev.get("actor") or "planner"
        phase = actor if actor in ("planner", "executor", "critic") else "executor"
        g = None
        args = None
        ok = None
        duration = None
        if kind == "tool_call":
            tool = ev.get("tool") or "（未知工具）"
            res = ev.get("result")
            g = _guardrail_block(ev)
            summary = _result_summary(tool, res)
            args = ev.get("args")
            ok = ev.get("ok")
            duration = ev.get("duration_ms")
        elif kind == "critic":
            tool = "Critic 评审"
            scores = ev.get("scores") or {}
            totals = " / ".join(
                "{} {}".format(pid, _num((scores.get(pid) or {}).get("total")))
                for pid in ("A", "B", "C", "D") if isinstance(scores.get(pid), dict))
            summary = "verdict={}{}".format(ev.get("verdict"), (" · " + totals) if totals else "")
        else:  # phase
            tool = ev.get("name") or "phase"
            detail = ev.get("detail") or {}
            args = detail if isinstance(detail, dict) else None
            if tool == "start":
                summary = "启动：{}".format(detail.get("loop") or "Planner-Executor-Critic 闭环")
            else:
                scalars = [(k, v) for k, v in (detail or {}).items()
                           if isinstance(v, (str, int, float, bool))]
                summary = " · ".join("{}={}".format(k, v) for k, v in scalars[:3]) or tool
        hit = bool(g and (g.get("passed") is False or g.get("violations")))
        steps.append({
            "index": i, "kind": kind, "phase": phase, "tool": tool,
            "args": args, "result_summary": summary,
            "duration_ms": duration, "ok": ok,
            "guardrail": g, "guardrail_hit": hit,
        })
    return steps


def _trace_guardrail_hits(events):
    hits = 0
    for e in events:
        if e.get("kind") == "tool_call" and e.get("tool") == "guardrail_validate":
            g = _guardrail_block(e)
            if g and (g.get("passed") is False or g.get("violations")):
                hits += 1
    return hits


# ---------------- HTTP Handler ----------------
class Handler(BaseHTTPRequestHandler):
    server_version = "GanpoFinalsAPI/3.0"
    protocol_version = "HTTP/1.1"

    # -- 基础发送 --
    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")  # 供静态页同源/跨域调用
        self.send_header("X-Response-Time", f"{(time.perf_counter() - self._t0) * 1000:.2f}ms")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, fs_path: str) -> None:
        ext = os.path.splitext(fs_path)[1].lower()
        with open(fs_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(ext, "application/octet-stream"))
        self.send_header("X-Response-Time", f"{(time.perf_counter() - self._t0) * 1000:.2f}ms")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- 请求体 --
    def _read_json_body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n > 0 else b""
        if not raw.strip():
            return {}
        try:
            val = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ApiError(400, "请求体不是合法 JSON")
        if not isinstance(val, dict):
            raise ApiError(400, "请求体必须是 JSON 对象")
        return val

    # -- 路由 --
    def do_GET(self):
        self._t0 = time.perf_counter()
        try:
            self._route_get()
        except ApiError as e:
            self._send(e.code, dict({"ok": False, "error": str(e)}, **e.extra))
        except Exception as e:  # noqa: BLE001 —— 面向演示的 API，结构化错误，不抛堆栈
            self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        self._t0 = time.perf_counter()
        try:
            self._route_post()
        except ApiError as e:
            self._send(e.code, dict({"ok": False, "error": str(e)}, **e.extra))
        except Exception as e:  # noqa: BLE001
            self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

    def _route_get(self):
        u = urlparse(self.path)
        if u.path in ("/", "/health"):
            self._send(200, {
                "ok": True,
                "service": "赣鄱智轨 · 交互演示台 API",
                "version": VERSION,
                "provider_default": "local（离线确定性，断网可跑）",
                "endpoints": {
                    "GET /decision?scenario=holiday|weekday": "读取冻结决策文档（只读）",
                    "POST /api/simulate": "{scenario,hub,headway,formation_cars,limit_level,demand_mult} → 指标+评分",
                    "POST /api/sla": "{net,slice,mec,isac,ai_air,event} → R 五段分解+成功率",
                    "POST /api/score": "{weights:{congestion,service,cost,robustness},scenario,hub}"
                                       " → 四方案维度分+按新权重总分（归一化；服务底线筛选 P2）",
                    "POST /api/run": "{scenario,hub[,provider]} → 现场重跑智能体（产物进 output/scratch/，plan 附经济标签）",
                    "GET /api/trace/latest?limit=40": "最新 trace 的 meta+events",
                    "GET /api/forecast?scenario=holiday": "逐小时客流预测（仿真推演）+ 百度真实特征校准（赛后迭代层）",
                    "GET /api/baidu/status": "百度数据层 AK/缓存健康状态",
                    "GET /api/anchors": "真实锚点台账（19 客流×2 场景 + 5 通信）",
                    "GET /api/stations?scenario=holiday": "34 站溯源（flow/real/anchor/走廊）+ 统计",
                    "GET /*": "静态文件回退（默认 index.html）",
                },
            })
            return
        if u.path == "/decision":
            scen = (parse_qs(u.query).get("scenario") or ["holiday"])[0]
            if scen not in SCENARIOS:
                raise ApiError(400, f"scenario 必须是 {' 或 '.join(SCENARIOS)}",
                               {"allowed": {"scenario": list(SCENARIOS)}})
            doc = read_decision(scen)
            if doc is None:
                self._send(404, {"ok": False, "error": f"尚无 {scen} 决策文档"})
                return
            self._send(200, {"ok": True, "scenario": scen, "doc": doc})
            return
        if u.path == "/api/anchors":
            self._api_anchors()
            return
        if u.path == "/api/trace/list":
            self._api_trace_list()
            return
        if u.path == "/api/trace":
            self._api_trace(parse_qs(u.query))
            return
        if u.path == "/api/stations":
            self._api_stations(parse_qs(u.query))
            return
        if u.path == "/api/trace/latest":
            self._api_trace_latest(parse_qs(u.query))
            return
        if u.path == "/api/forecast":
            self._api_forecast(parse_qs(u.query))
            return
        if u.path == "/api/baidu/status":
            self._api_baidu_status()
            return
        if u.path.startswith("/api/"):
            raise ApiError(404, f"未知 API 路径：{u.path}")
        self._serve_static(u)

    def _route_post(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/run":  # 旧入口：query 入参，产物同样只进 scratch
            p = validate_run_params({}, q)
            with LOCK:
                doc, out_rel, elapsed = run_agent(p["scenario"], p["hub"], p["provider"])
            self._send(200, {"ok": True, "scenario": p["scenario"], "hub": p["hub"],
                             "doc": attach_economics(doc)})
            return
        params = self._read_json_body() if u.path.startswith("/api/") else {}
        if u.path == "/api/run":
            p = validate_run_params(params, q)
            with LOCK:
                doc, out_rel, elapsed = run_agent(p["scenario"], p["hub"], p["provider"])
            self._send(200, {"ok": True, "scenario": p["scenario"], "hub": p["hub"],
                             "provider": p["provider"], "elapsed_s": round(elapsed, 3),
                             "out_path": out_rel, "doc": attach_economics(doc)})
            return
        if u.path == "/api/simulate":
            self._api_simulate(params, q)
            return
        if u.path == "/api/sla":
            self._api_sla(params, q)
            return
        if u.path == "/api/score":
            self._api_score(params, q)
            return
        raise ApiError(404, f"未知 API 路径：{u.path}")

    # -- API 实现 --
    def _api_simulate(self, params: dict, q: dict) -> None:
        p = validate_simulate_params(params, q)
        exp = experiments()
        scen, hub = p["scenario"], p["hub"]
        # P3：基准 = 同需求现状（12min / 8 编组 / 不限流的既有运营参数，需求跟随请求）
        base_cfg = {"scenario": scen, "headway_min": 12.0, "formation_cars": 8,
                    "limit_level": 0, "demand_mult": p["demand_mult"],
                    "baseline_flag": True}
        plan_raw = {"scenario": scen, "headway_min": p["headway"],
                    "formation_cars": p["formation_cars"], "limit_level": p["limit_level"],
                    "demand_mult": p["demand_mult"]}
        base_metrics = exp.run(base_cfg, hub)
        plan_metrics = exp.run(plan_raw, hub)
        base_score = exp.score_plan(base_metrics, base_metrics)
        # 稳健性未做敏感性扫描，按 Critic 保守口径 60 计（与 experiments.py 消融一致）
        plan_score = exp.score_plan(plan_metrics, base_metrics)
        delta = {k: round(plan_metrics.get(k, 0) - base_metrics.get(k, 0), 4)
                 for k in ("max_saturation", "avg_delay_min", "unmet_persons_per_hour")}
        self._send(200, {
            "ok": True, "scenario": scen, "hub": hub,
            "config": p,
            "baseline": {"config": {k: base_cfg[k] for k in
                                    ("headway_min", "formation_cars", "limit_level", "demand_mult")},
                         "metrics": base_metrics, "score": base_score},
            "plan": {"config": plan_raw, "metrics": plan_metrics, "score": plan_score},
            "delta": delta,
            "fleet_available": FLEET_AVAILABLE,
            "over_capacity": plan_metrics.get("max_saturation", 0) > 1.0,
            "robustness_mode": "fixed60",
            "note": "数字来自 sim 引擎 + experiments.score_plan（与 Critic 同口径）；"
                    "稳健性未扫描按保守 60 计（robustness_mode=fixed60），"
                    "与智能体推荐口径（材料 83.6）不同源，前端不应展示本接口总分。",
        })

    def _api_sla(self, params: dict, q: dict) -> None:
        p = validate_sla_params(params, q)
        cl = comm_layer()
        res = cl.response_time(p["net"], event_id=p["event"],
                               slice_id=p["slice"], mec_node=p["mec"], isac=p["isac"])
        ai_applied = p["ai_air"] and p["net"] == "5G-A"
        weak = cl.weak_coverage_report(p["event"]) if ai_applied else None
        applied = {
            "slice": res.get("slice_label") is not None,
            "mec": p["mec"] is not None and p["net"] in ("5G", "5G-A"),
            "isac": p["isac"] and p["net"] == "5G-A",
            "ai_air": ai_applied,
        }
        self._send(200, {
            "ok": True,
            "input": p,
            "applied": applied,
            "result": res,
            "weak": weak,
            "note": "R = (T_sense + T_comm + T_compute) × n_rounds + T_execute；"
                    "执行段为物理处置时间，不计入通信增益。",
        })

    def _api_score(self, params: dict, q: dict) -> None:
        """I2a/P2：按自定义权重重算四方案总分，并按服务底线筛选推荐。
        维度分全部取自 Critic 原始输出，本接口只做归一化加权和
        （与 agent/agent_loop.py:399-400 同构），不另写公式；
        admissible 规则与 /api/run 共用 admissibility_of()。"""
        p = validate_score_params(params, q)
        doc, frozen = decision_doc_for(p["scenario"], p["hub"])
        doc = attach_economics(doc)
        w = p["weights_norm"]
        base = doc.get("baseline", {}).get("metrics", {})
        metric_keys = ("avg_delay_min", "unmet_persons_per_hour",
                       "max_saturation", "required_trains",
                       "deferred_persons_per_hour")
        plans_out = []
        admissible_pool = []
        for plan in doc.get("plans", []):
            s = plan.get("score") or {}
            total_new = round(sum(w[k] * float(s.get(k, 0.0)) for k in SCORE_DIMS), 1)
            ec = plan.get("effective_config") or {}
            pm = plan.get("metrics") or {}
            item = {
                "id": plan.get("id"), "name": plan.get("name"),
                "feasible": plan.get("feasible"), "block_reason": plan.get("block_reason"),
                "admissible": plan.get("admissible"),
                "reject_reason": plan.get("reject_reason"),
                "metrics": {k: pm.get(k) for k in metric_keys},
                "dims": {k: s.get(k) for k in SCORE_DIMS},
                "total_default": s.get("total"),
                "total": total_new,
                "config_summary": {"headway_min": ec.get("headway_min"),
                                   "limit_level": ec.get("limit_level"),
                                   "fleet_limit": (plan.get("config") or {}).get("fleet_limit")},
                "additional_trains": plan.get("additional_trains"),
                "requires_capex": plan.get("requires_capex"),
            }
            plans_out.append(item)
            if item["admissible"]:
                admissible_pool.append((item["total"], item["id"]))
        recommended = max(admissible_pool)[1] if admissible_pool else None
        self._send(200, {
            "ok": True, "scenario": p["scenario"], "hub": p["hub"],
            "weights": {"raw": p["weights_raw"],
                        "normalized": {k: round(v, 4) for k, v in w.items()}},
            "baseline": {k: base.get(k) for k in metric_keys},
            "plans": plans_out,
            "recommended": recommended,
            "recommended_admissible": recommended,
            "rule": "服务底线：延误不高于现状、未承运不高于现状；"
                    "admissible = 过护栏（feasible）且满足底线。"
                    "recommended / recommended_admissible = admissible 方案中按当前权重最高分；"
                    "未过底线的方案即使分数最高也不当选。",
            "formula": {
                "dims_source": "plans[].score（Critic 原始维度分，智能体口径，未改动）",
                "weights_default": "agent/agent_loop.py:34 WEIGHTS = {congestion .40, service .30, "
                                   "cost .20, robustness .10}",
                "total_formula": "与 agent/agent_loop.py:399-400 同构的加权和；本接口仅将权重"
                                 "按入参归一化后重算，不另写维度公式",
                "admissible_rule": "与 /api/run 共用 api_server.admissibility_of()，两接口口径一致",
            },
            "frozen_source": frozen,
        })

    def _api_trace_list(self) -> None:
        """I4：可用 run 列表（两落点合并），按 run_id（时间戳前缀）倒序。"""
        runs = []
        for run_id, path in trace_files():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            evs = data.get("events") or []
            meta = data.get("meta") or {}
            runs.append({
                "run_id": run_id,
                "file": os.path.relpath(path, HERE),
                "started_at": data.get("started_at"),
                "scenario": meta.get("scenario"),
                "hub": meta.get("hub"),
                "engine_mode": (meta.get("engine") or {}).get("mode"),
                "steps": data.get("total_events", len(evs)),
                "tool_calls": sum(1 for e in evs if e.get("kind") == "tool_call"),
                "guardrail_hits": _trace_guardrail_hits(evs),
            })
        runs.sort(key=lambda r: r["run_id"], reverse=True)
        self._send(200, {"ok": True, "runs": runs, "count": len(runs)})

    def _api_trace(self, q: dict) -> None:
        """I4：按 run_id 返回完整 trace（统一 steps + 元信息）。"""
        run_id = (q.get("run_id") or [""])[0]
        if not RUN_ID_RE.fullmatch(run_id or ""):
            raise ApiError(400, "run_id 只允许字母/数字/下划线/连字符",
                           {"allowed": {"run_id": "trace 文件名去掉 _trace.json 后缀"}})
        found = None
        for rid, path in trace_files():
            if rid == run_id:
                found = path
                break
        if found is None:
            raise ApiError(404, f"run_id 不存在：{run_id}")
        with open(found, encoding="utf-8") as f:
            data = json.load(f)
        events = data.get("events") or []
        steps = _build_steps(events)
        n_tools = sum(1 for s in steps if s["kind"] == "tool_call")
        n_hits = sum(1 for s in steps if s["guardrail_hit"])
        meta = data.get("meta") or {}
        self._send(200, {
            "ok": True, "run_id": run_id,
            "file": os.path.relpath(found, HERE),
            "meta": meta,
            "started_at": data.get("started_at"),
            "total_duration_ms": data.get("total_duration_ms"),
            # I4 补丁：顶层字段与 list 接口同源
            "total_steps": len(steps),
            "tool_calls": n_tools,
            "guardrail_hits": n_hits,
            "scenario": meta.get("scenario"),
            "hub": meta.get("hub"),
            "engine": (meta.get("engine") or {}).get("mode"),
            "counts": {
                "steps": len(steps),
                "tool_calls": n_tools,
                "guardrail_hits": n_hits,
            },
            "steps": steps,
        })

    def _api_stations(self, q: dict) -> None:
        """I2b：34 站溯源台账。字段全部读自 data/flow_*.json：
        corridor 由 type 派生（数据无走廊字段）；source 数据中不存在，返回 None；
        is_hub 按演示枢纽集标注（数据无显式枢纽标记）。"""
        scen = (q.get("scenario") or ["holiday"])[0]
        if scen not in SCENARIOS:
            raise ApiError(400, f"scenario 必须是 {' 或 '.join(SCENARIOS)}",
                           {"allowed": {"scenario": list(SCENARIOS)}})
        fd = flow_data(scen)
        stations = fd.get("stations") or []
        hub_names = {"南昌站", "九江站", "上饶站", "庐山站", "赣州站"}
        corridor_of = {"commuter": "通勤走廊", "tourism": "旅游走廊"}
        out = [{
            "name": s.get("name"),
            "flow": s.get("flow"),
            "real": bool(s.get("real")),
            "anchor": s.get("anchor"),
            "source": s.get("source"),
            "corridor": s.get("corridor") or corridor_of.get(s.get("type")),
            "is_hub": s.get("name") in hub_names,
        } for s in stations]
        anchors = [a for a in (fd.get("real_anchors") or []) if isinstance(a, dict)]
        real_n = sum(1 for s in stations if s.get("real"))
        self._send(200, {
            "ok": True, "scenario": scen,
            "unit": fd.get("unit"),
            "stations": out,
            "stats": {
                "total": len(out),
                "real_count": real_n,
                "inferred_count": len(out) - real_n,
                "anchor_count": len(anchors),
                "anchor_list": [{"name": a.get("name"), "value": a.get("value")}
                                for a in anchors],
            },
            "note": fd.get("source_note"),
        })

    def _api_forecast(self, q: dict) -> None:
        """赛后迭代层：逐小时客流预测（仿真推演）+ 百度真实特征（外部校准）。
        AK 透传 ?ak=（仅本机内存，不入日志不入产物）；断网自动降级 offline_fallback。
        不持全局 LOCK：预测的网络 IO 有独立互斥与短超时，不阻塞 /api/run。"""
        scen = (q.get("scenario") or ["holiday"])[0]
        if scen not in SCENARIOS:
            raise ApiError(400, f"scenario 必须是 {' 或 '.join(SCENARIOS)}",
                           {"allowed": {"scenario": list(SCENARIOS)}})
        ak = (q.get("ak") or [None])[0]
        try:
            doc = predict_mod().forecast(scen, ak)
        except ApiError:
            raise
        except Exception as e:
            raise ApiError(500, f"预测失败：{type(e).__name__}")
        self._send(200, doc)

    def _api_baidu_status(self) -> None:
        """百度数据层健康状态：AK 是否配置、来源、缓存位置。不联网探测。"""
        pm = predict_mod()
        ak, source = pm.read_ak()
        self._send(200, {
            "ok": True,
            "ak_configured": bool(ak),
            "ak_source": source,
            "cache_dir": os.path.relpath(pm.CACHE_DIR, HERE),
            "note": "AK 三级读取：?ak= 透传 → 环境变量 GANPO_BMAP_AK → js/local-ak.js；"
                    "密钥只在本机，不进仓库。",
        })

    def _api_trace_latest(self, q: dict) -> None:
        raw = (q.get("limit") or ["40"])[0]
        try:
            limit = int(raw)
        except ValueError:
            raise ApiError(400, "limit 必须是整数", {"allowed": {"limit": "1~500"}})
        limit = max(1, min(500, limit))
        # trace 有两个落点：历史运行在 output/trace/，API 运行在 output/scratch/trace/
        #（E1 起 --out 指向 scratch）。文件名带时间戳自排序，跨目录按（名称, mtime）取最新。
        candidates = []
        for d in (TRACE_DIR, os.path.join(SCRATCH_DIR, "trace")):
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if f.endswith(".json"):
                        p = os.path.join(d, f)
                        candidates.append((f, os.path.getmtime(p), p))
        if not candidates:
            raise ApiError(404, "暂无 trace 文件：请先运行一次智能体")
        candidates.sort()
        _, _, latest_path = candidates[-1]
        with open(latest_path, encoding="utf-8") as f:
            data = json.load(f)
        events = data.get("events", [])
        self._send(200, {
            "ok": True, "file": os.path.relpath(latest_path, HERE),
            "meta": data.get("meta"), "started_at": data.get("started_at"),
            "total_events": data.get("total_events", len(events)),
            "total_duration_ms": data.get("total_duration_ms"),
            "tools_used": data.get("tools_used"),
            "events_returned": min(limit, len(events)),
            "events": events[:limit],
        })

    def _api_anchors(self) -> None:
        scenarios = {}
        for scen in SCENARIOS:
            fd = flow_data(scen)
            scenarios[scen] = {
                "real_anchors": fd.get("real_anchors", []),
                "stations": [{"name": s.get("name"), "type": s.get("type"),
                              "flow": s.get("flow"), "real": s.get("real"),
                              "anchor": s.get("anchor")} for s in fd.get("stations", [])],
            }
        cap_path = os.path.join(HERE, "data", "comm_capability.json")
        comm_anchors = []
        if os.path.exists(cap_path):
            with open(cap_path, encoding="utf-8") as f:
                comm_anchors = json.load(f).get("comm_anchors", [])
        self._send(200, {
            "ok": True,
            "scenarios": scenarios,
            "comm_anchors": comm_anchors,
            "counts": {s: len(v["real_anchors"]) for s, v in scenarios.items()}
                      | {"comm": len(comm_anchors)},
        })

    # -- 静态回退（防目录穿越） --
    def _serve_static(self, u) -> None:
        path = unquote(u.path)
        if path in ("", "/"):
            path = "/index.html"
        parts = path.lstrip("/").split("/")
        if any(seg in ("", ".", "..") or seg.startswith(".") or "\\" in seg for seg in parts):
            self._send(403, {"ok": False, "error": "forbidden path"})
            return
        root_real = os.path.realpath(HERE)
        fs_path = os.path.realpath(os.path.join(root_real, *parts))
        if os.path.commonpath([root_real, fs_path]) != root_real:
            self._send(403, {"ok": False, "error": "forbidden path"})
            return
        if not os.path.isfile(fs_path):
            self._send(404, {"ok": False, "error": f"static not found: {path}"})
            return
        self._send_file(fs_path)

    def log_message(self, fmt, *args):
        sys.stderr.write("[api] " + (fmt % args) + "\n")


# ---------------- 自检 ----------------
def selftest() -> int:
    """起临时服务，依次打 6 条路由 + 静态回退附加检查，打印返回码与耗时。"""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def hit(method: str, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=RUN_TIMEOUT + 30) as r:
                return r.status, (time.perf_counter() - t0) * 1000
        except urllib.error.HTTPError as e:
            return e.code, (time.perf_counter() - t0) * 1000

    # 判定逻辑与 _api_trace_latest 保持一致：两个 trace 落点（output/trace/ 与
    # output/scratch/trace/）任一存在 .json 即视为"有 trace"，预期 200。
    #（旧逻辑只看 output/trace/，scratch 有 trace 时会误报 FAIL）
    has_trace = bool(trace_files()) or any(
        os.path.isdir(d) and any(f.endswith(".json") for f in os.listdir(d))
        for d in (TRACE_DIR, os.path.join(SCRATCH_DIR, "trace")))
    trace_expect = 200 if has_trace else 404  # 无 trace 时 404 属结构化正常行为

    rows = [
        ("GET  /               健康检查",        "GET",  "/", None, 200, ""),
        ("GET  /api/anchors    锚点台账",        "GET",  "/api/anchors", None, 200, ""),
        ("GET  /api/trace/latest trace",         "GET",  "/api/trace/latest?limit=5", None,
         trace_expect, "" if has_trace else "（无 trace，404 即正确）"),
        ("POST /api/sla        R 链路（目标<30ms）", "POST", "/api/sla",
         {"net": "4G", "event": "train_fault"}, 200, ""),
        ("POST /api/simulate   仿真+评分（目标<120ms）", "POST", "/api/simulate",
         {"scenario": "holiday", "hub": "南昌站", "headway": 8, "formation_cars": 8,
          "limit_level": 1, "demand_mult": 1.0}, 200, ""),
        ("POST /api/run        离线智能体（目标<2s）", "POST", "/api/run",
         {"scenario": "holiday", "hub": "南昌站", "provider": "local"}, 200, ""),
        ("GET  /stage.html     静态回退（附加）", "GET", "/stage.html", None, 200, ""),
    ]

    print("=" * 64)
    print(f"赣鄱智轨 api_server 自检  {base}")
    print("=" * 64)
    all_ok = True
    sla_ms = None
    for name, method, path, payload, expect, _ in rows:
        code, ms = hit(method, path, payload)
        if name.startswith("POST /api/sla"):
            sla_ms = ms
        ok = code == expect
        all_ok = all_ok and ok
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {code}  {ms:8.2f} ms   {name}")
        if not ok:
            print(f"         期望 {expect}，实际 {code}")

    ok = all_ok and sla_ms is not None and sla_ms < 30.0
    print("-" * 64)
    print(f"结论: {'✅ 自检通过' if ok else '❌ 自检未通过'}"
          f"（6 条路由全 200{'（trace 为预期 404）' if not has_trace else ''}"
          f" 且 /api/sla {sla_ms:.2f}ms < 30ms）" if sla_ms is not None else "结论: ❌ /api/sla 未执行")
    srv.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="赣鄱智轨 · 交互演示台 API + 静态服务")
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"),
                    help="监听地址，默认 127.0.0.1（可被 HOST 环境变量覆盖）")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")),
                    help="监听端口，默认 8000（可被 PORT 环境变量覆盖）")
    ap.add_argument("--selftest", action="store_true", help="自检后退出")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    print(f"赣鄱智轨 · 交互演示台 API + 静态服务  http://{a.host}:{a.port}")
    print(f"  演示台  http://{a.host}:{a.port}/stage.html")
    print("  POST /api/simulate | /api/sla | /api/run   GET /api/anchors | /api/trace/latest")
    print("  产物写 output/scratch/，data/ 冻结文件只读；Ctrl+C 退出")
    try:
        ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n[api] 已退出")
