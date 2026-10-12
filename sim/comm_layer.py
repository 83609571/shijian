#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""赣鄱智轨 · 通信数字孪生层（sim/comm_layer.py）
==========================================================
定位（回应 NSTPIC「以信息通信技术为核心」的赛道要求）：
    把 5G/5G-A 的「确定性网络 + 通感算智一体化」能力建模为仿真引擎的**自变量**，
    让应急 / 大客流场景的处置效果显式依赖网络档位 —— 而不是在展示层贴名词。

核心机制：应急响应链路时间分解（ICT 能力 → 业务指标的因果耦合）
    R = (T_sense + T_comm + T_compute) × n_rounds + T_execute
      T_sense    感知时延：异常发生到系统「看见」（人工上报 vs 轨旁传感 vs 通感一体基站直感）
      T_comm     传输时延：决策指令端到端下发（确定性承载 / 切片 / 公网）
      T_compute  计算时延：智能体推理位置决定（中心云 vs 沿线 MEC 边缘）
      n_rounds   确认回环次数：4G 需人工二次确认；5G / 5G-A 单轮自动闭环
      T_execute  执行时延：列车制动 / 闸机限流等物理动作（网络无关基线）

    R → 影响窗口 W = R + 事件物理处置时间 → 客流堆积 → 消散 → 旅客延误
    ⇒ 同一故障，4G / 5G / 5G-A 三档网络下的恢复时间与旅客影响**不同且可复算**。
    这是「ICT 是自变量、业务是因变量」的工程判据（贴皮 vs 打通的试金石）。

数据真实性原则（延续项目红线，与 sim/passenger_flow_sim.py 同一套纪律）：
    - 标准与公开案例锚点 → real=True，注明出处（3GPP 标准文档 / 公开报道口径）
    - NET_PROFILES 档位数值 → real=False，注明推演依据（锚定标准指标 + 工程余量）

运行：python -m sim.comm_layer           # 生成 data/comm_capability.json
校验：python -m sim.comm_layer --check   # 校验与 data/ 一致，不一致返回非 0
独立：纯标准库；不依赖 agent 包（与稳态引擎一样可直接被前端/实验/智能体三端消费）
"""
from __future__ import annotations

import json
import os

# ----------------------------------------------------------------------
# 与 agent/schemas.py 保持同口径的常量副本（本层不反向依赖 agent 包，
# 注释锚定出处，改动任一侧时须双侧同步——submit_selfcheck.py 会比对）
# ----------------------------------------------------------------------
SEATS_PER_CAR = 90          # 单节定员（与 engine_b 同口径）
LOAD_AVAILABILITY = 0.95    # 车辆可用率
PEAK_HOUR_SHARE = 0.12      # 高峰小时系数（占全日客流）
HOLIDAY_SURGE = 1.15        # 节假日高峰集聚系数

SCHEMA_VERSION = "1.0"

# ----------------------------------------------------------------------
# 通信口径真实锚点（real=True 为公开标准/案例；real=False 为推演依据）
# ----------------------------------------------------------------------
COMM_ANCHORS = [
    {"name": "3GPP URLLC 空口时延目标", "value": "上行/下行各 0.5ms",
     "detail": "3GPP TR 38.913 定义 URLLC 用户面时延目标（UL 0.5ms / DL 0.5ms）；"
               "并在 1ms 内以 99.999% 可靠性传输 32 字节分组",
     "source": "3GPP TR 38.913（5G 需求研究）", "real": True},
    {"name": "3GPP R19 通感一体化立项", "value": "ISAC 研究项目(2022 立项)",
     "detail": "3GPP Rel-19 通过「通感一体化（ISAC）」研究立项，含信道建模研究；"
               "基站具备对沿线目标（列车/异物/边坡）的直接感知能力成为标准方向",
     "source": "3GPP RAN Rel-19 立项公开信息", "real": True},
    {"name": "铁路移动通信 5G-R 演进", "value": "GSM-R → 5G-R(行业公开规划)",
     "detail": "国铁推动铁路专用移动通信从 GSM-R 向 5G-R 演进，承载列控/调度等安全业务"
               "（引用时建议以最新官方白皮书核实）",
     "source": "铁路行业公开规划", "real": True},
    {"name": "5G-A 确定性网络公开白皮书口径", "value": "毫秒级有界时延@99.999%（白皮书口径）",
     "detail": "5G-A/5.5G 确定性网络以「有界低时延 + 高可靠」为核心公开宣传口径"
               "（如 20ms 内@99.999% 级别承诺，毫秒级抖动上界）；"
               "本层档位数值以其为量级锚点并留工程余量，引用时建议核实原文",
     "source": "设备商/运营商 5G-A 白皮书公开宣传口径", "real": True},
    {"name": "高铁 5G 沿线覆盖公开案例", "value": "350km/h 全线 5G 覆盖(2019 京张)",
     "detail": "京张高铁实现时速 350 公里下全线 5G 覆盖，为高速铁路 5G 车地通信公开案例；"
               "本层「通勤干线 5G 档位」以此类公开案例为量级锚点",
     "source": "公开报道（运营商/设备商发布）", "real": True},
]

# ----------------------------------------------------------------------
# 网络能力档案（三档）。数值为仿真推演口径（real=False），
# 每档 basis 说明锚定依据；通信层不做电磁级仿真（见模块 docstring）。
# ----------------------------------------------------------------------
NET_PROFILES = {
    "4G": {
        "sense_s": 120.0, "comm_ms": 150.0, "compute_ms": 1500.0,
        "jitter_ms": 30.0, "packet_loss": 0.005,
        "n_rounds": 2, "reliability": 0.98, "compute_at": "中心云",
        "label": "4G 既有公网（人工巡检上报）",
        "note": "感知靠人工/定时巡检；指令走公网；推理在中心云；下发前需人工二次确认（n_rounds=2）",
        "basis": "感知 120s=人工发现口径；传输 150ms=公网均值含重传；推演值 real=False",
    },
    "5G": {
        "sense_s": 20.0, "comm_ms": 25.0, "compute_ms": 1200.0,
        "jitter_ms": 5.0, "packet_loss": 0.001,
        "n_rounds": 1, "reliability": 0.999, "compute_at": "中心云",
        "label": "5G 沿线覆盖 + 网络切片",
        "note": "轨旁传感/视频回传发现异常；网络切片承载调度指令；单轮自动闭环",
        "basis": "锚定高铁 5G 公开案例量级；传输 25ms 含回传与处理余量；推演值 real=False",
    },
    "5G-A": {
        "sense_s": 2.0, "comm_ms": 5.0, "compute_ms": 100.0,
        "jitter_ms": 0.5, "packet_loss": 0.00001,
        "n_rounds": 1, "reliability": 0.99999, "compute_at": "沿线MEC边缘",
        "label": "5G-A 确定性承载 + 通感一体 + MEC 边缘智能",
        "note": "ISAC 基站直接感知沿线目标（秒级发现）；确定性承载下发指令（毫秒级、99.999%）；"
                "智能体推理下沉到沿线 MEC 边缘节点",
        "basis": "感知/传输锚定 3GPP URLLC 0.5ms 空口、R19 ISAC 立项与 5G-A 确定性网络"
                 "白皮书量级并留工程余量；计算 100ms=MEC 就近推理；推演值 real=False",
    },
}

# ----------------------------------------------------------------------
# 网络切片档案（5G/5G-A）：为通勤/旅游/应急分配不同优先级，
# 应急切片可抢占（资源抢占能力是「网络层自变量」的一部分）。
# comm_factor 为切片对传输时延的乘子（应急切片优先调度 → 打折）。
# ----------------------------------------------------------------------
SLICE_PROFILES = {
    "tourism": {
        "priority": 1, "label": "旅游切片", "preempt": False, "comm_factor": 1.2,
        "note": "尽力而为 + 基础保障，可被高优先级切片挤占资源",
    },
    "commuter": {
        "priority": 2, "label": "通勤切片", "preempt": False, "comm_factor": 1.0,
        "note": "保障通勤调度指令，中等优先级",
    },
    "emergency": {
        "priority": 3, "label": "应急专用切片", "preempt": True, "comm_factor": 0.8,
        "note": "最高优先级，可抢占通勤/旅游切片资源，保障应急指令优先传输",
    },
}

# ----------------------------------------------------------------------
# MEC 边缘节点档案：决策就近执行，减少回传延迟（方案 4.1 表）。
# 4G 档不支持 MEC 就近（回落中心云）；5G/5G-A 可指定 MEC 节点。
# ----------------------------------------------------------------------
MEC_NODES = {
    "center": {"name": "中心云（跨区域）", "compute_ms": 1200.0,
               "covers": "全网（经骨干网回传）"},
    "nanchang": {"name": "南昌 MEC", "compute_ms": 100.0,
                 "covers": ["昌九通勤线", "昌抚通勤线", "沪昆通勤线", "京九通勤线",
                            "皖赣通勤线", "梅岭红轨旅游线", "环庐山旅游线",
                            "赣西红色旅游线", "赣南客家旅游线"]},
    "jiujiang": {"name": "九江 MEC", "compute_ms": 110.0,
                 "covers": ["昌九通勤线", "环庐山旅游线", "赣东北旅游环线"]},
    "shangrao": {"name": "上饶 MEC", "compute_ms": 110.0,
                 "covers": ["沪昆通勤线", "赣东北旅游环线", "大觉山旅游支线",
                            "赣东古韵旅游线"]},
}

# ----------------------------------------------------------------------
# 弱覆盖场景（方案场景三：AI 空口）。隧道/弯道/山区三类弱覆盖段，
# share_of_line 为该走廊弱覆盖段占比（推演口径）。三档网络 + AI 空口的
# 降级因子：comm_factor 越大时延恶化越重，reliability 为该段有效可靠性。
# ----------------------------------------------------------------------
WEAK_SPOTS = [
    {"id": "ws_ne", "corridor": "赣东北旅游环线", "type": "山区连续弯道",
     "share_of_line": 0.35},
    {"id": "ws_ml", "corridor": "梅岭红轨旅游线", "type": "山区", "share_of_line": 0.40},
    {"id": "ws_djs", "corridor": "大觉山旅游支线", "type": "山区峡谷", "share_of_line": 0.30},
]

WEAK_DEGRADATION = {
    "4G":        {"comm_factor": 3.0, "sense_factor": 2.0, "reliability": 0.90,
                  "note": "弱覆盖 + 公网尽力而为：时延恶化 3 倍、可靠性降至 0.90"},
    "5G":        {"comm_factor": 1.5, "sense_factor": 1.2, "reliability": 0.995,
                  "note": "切片保障部分缓解弱覆盖影响"},
    "5G-A":      {"comm_factor": 1.3, "sense_factor": 1.0, "reliability": 0.998,
                  "note": "确定性承载基线（无 AI 空口增强）"},
    "5G-A+ai":   {"comm_factor": 1.1, "sense_factor": 1.0, "reliability": 0.9999,
                  "note": "AI 空口波束赋形 + 链路自适应：弱覆盖段能力恢复至接近标称"},
}

# ----------------------------------------------------------------------
# 网络SLA对比实验组（方案 4.3 对照实验设计）
# ----------------------------------------------------------------------
NETWORK_SCENARIO_GROUPS = [
    {"id": "control_4g", "label": "对照组 · 4G/传统铁路通信",
     "net": "4G", "slice": None, "mec": None, "isac": False, "ai_air": False},
    {"id": "a_5ga_det", "label": "实验组A · 5G-A 确定性网络",
     "net": "5G-A", "slice": "emergency", "mec": "nanchang", "isac": False, "ai_air": False},
    {"id": "b_5ga_isac", "label": "实验组B · 5G-A + ISAC 通感",
     "net": "5G-A", "slice": "emergency", "mec": "nanchang", "isac": True, "ai_air": False},
    {"id": "c_5ga_ai_air", "label": "实验组C · 5G-A + AI 空口",
     "net": "5G-A", "slice": "emergency", "mec": "nanchang", "isac": False, "ai_air": True},
]

# ----------------------------------------------------------------------
# 应急事件库（四类）。T_execute 为指令执行物理时延（网络无关基线）；
# t_physical_min 为事件固有处置时间（救援/清障/检查，通信无法缩短）；
# severity 为影响窗口内断面服务的受阻程度（1.0=断面前进不了 / 0.35=部分降级）。
# ----------------------------------------------------------------------
INCIDENT_TYPES = {
    "train_fault": {
        "name": "列车故障", "t_execute_s": 60.0, "t_physical_min": 25.0, "severity": 1.0,
        "desc": "区间列车故障迫停，需扣停邻线列车并组织救援（救援清出 ~25min，通信无法替代）",
    },
    "landslide": {
        "name": "暴雨边坡", "t_execute_s": 60.0, "t_physical_min": 45.0, "severity": 1.0,
        "desc": "暴雨引发边坡风险，需封锁区间并巡检确认（检查处置 ~45min）",
    },
    "foreign_object": {
        "name": "异物侵限", "t_execute_s": 60.0, "t_physical_min": 15.0, "severity": 1.0,
        "desc": "沿线异物侵限，需限速/扣停并现场清除（处置 ~15min）",
    },
    "crowd_surge": {
        "name": "大客流积压", "t_execute_s": 60.0, "t_physical_min": 0.0, "severity": 0.35,
        "desc": "枢纽/站台客流积压超阈值，需下发限流/加开指令（滚动调控，"
                "通信档位决定单次调控闭环周期）",
    },
}

# ----------------------------------------------------------------------
# 沿线通信资源底账（按走廊线）。干线城际走廊锚定公开案例量级（5G），
# 山区旅游支线弱覆盖为推演口径；昌九通勤走廊标记 5G-A 升级候选（试点叙事）。
# ----------------------------------------------------------------------
def _comm_resources():
    return {
        "昌九通勤线":   {"net": "5G", "upgrade_candidate": True,
                         "note": "通勤干线，锚定高铁 5G 公开案例量级；5G-A 确定性承载升级候选试点",
                         "real": False},
        "昌抚通勤线":   {"net": "5G", "upgrade_candidate": False, "real": False},
        "沪昆通勤线":   {"net": "5G", "upgrade_candidate": False, "real": False},
        "京九通勤线":   {"net": "5G", "upgrade_candidate": False, "real": False},
        "皖赣通勤线":   {"net": "5G", "upgrade_candidate": False, "real": False},
        "环庐山旅游线": {"net": "5G", "upgrade_candidate": False, "real": False},
        "赣东北旅游环线": {"net": "4G", "upgrade_candidate": True,
                           "note": "跨景区山区段落覆盖偏弱（推演口径），5G-A 通感一体升级候选",
                           "real": False},
        "大觉山旅游支线": {"net": "4G", "upgrade_candidate": True, "real": False},
        "梅岭红轨旅游线": {"net": "4G", "upgrade_candidate": False, "real": False},
        "赣西红色旅游线": {"net": "4G", "upgrade_candidate": False, "real": False},
        "赣南客家旅游线": {"net": "4G", "upgrade_candidate": False, "real": False},
        "赣东古韵旅游线": {"net": "4G", "upgrade_candidate": False, "real": False},
    }


def net_of_line(line: str) -> str:
    """某走廊线当前的网络档位（未知线按通勤 5G / 旅游 4G 缺省）。"""
    res = _comm_resources()
    if line in res:
        return res[line]["net"]
    return "5G" if "通勤" in line else "4G"


# ----------------------------------------------------------------------
# R 分解：应急响应链路时间（全部确定性，秒）
# 可选增强：slice_id（网络切片）/ mec_node（推理位置）/ isac（通感直感）
# ----------------------------------------------------------------------
def response_time(net_id: str = "5G", event_id: str = "train_fault",
                  slice_id: str | None = None, mec_node: str | None = None,
                  isac: bool = False) -> dict:
    if net_id not in NET_PROFILES:
        net_id = "5G"
    if event_id not in INCIDENT_TYPES:
        event_id = "train_fault"
    p = NET_PROFILES[net_id]
    ev = INCIDENT_TYPES[event_id]

    # 切片：应急切片优先调度 → 传输时延打折；旅游切片被挤占 → 时延上浮
    comm_ms = p["comm_ms"]
    slice_used = None
    if slice_id and slice_id in SLICE_PROFILES and net_id != "4G":
        slice_used = SLICE_PROFILES[slice_id]
        comm_ms = comm_ms * slice_used["comm_factor"]

    # MEC：推理位置决定计算时延（4G 档不支持 MEC 就近，回落中心云）
    compute_ms = p["compute_ms"]
    mec_used = None
    if mec_node and mec_node in MEC_NODES and net_id in ("5G", "5G-A"):
        mec_used = MEC_NODES[mec_node]
        compute_ms = mec_used["compute_ms"]

    # ISAC 通感一体：基站直接感知替代「传感上报/人工发现」，感知时延减半
    sense_s = p["sense_s"] * (0.5 if (isac and net_id == "5G-A") else 1.0)

    chain_s = sense_s + comm_ms / 1000.0 + compute_ms / 1000.0
    total_s = chain_s * p["n_rounds"] + ev["t_execute_s"]
    return {
        "net": net_id, "net_label": p["label"], "event": event_id,
        "n_rounds": p["n_rounds"],
        "slice": slice_id,
        "slice_label": slice_used["label"] if slice_used else None,
        "slice_preempt": slice_used["preempt"] if slice_used else None,
        "mec_node": mec_node,
        "compute_at": (mec_used["name"] if mec_used else p["compute_at"]),
        "isac": bool(isac),
        "r_breakdown": {
            "sense_s": round(sense_s, 3),
            "comm_s": round(comm_ms / 1000.0, 4),
            "compute_s": round(compute_ms / 1000.0, 4),
            "execute_s": ev["t_execute_s"],
        },
        "chain_s": round(chain_s, 3),          # 感知+传输+计算（每轮，不含执行）
        "total_s": round(total_s, 3),
        "total_min": round(total_s / 60.0, 3),
        "jitter_ms": p["jitter_ms"],
        "packet_loss": p["packet_loss"],
        "reliability": p["reliability"],
        "success_rate": round(decision_success_rate(net_id, slice_id=slice_id), 6),
        "formula": "R = (T_sense + T_comm + T_compute) × n_rounds + T_execute",
        "note": p["note"], "basis": p["basis"],
    }


def decision_success_rate(net_id: str = "5G", slice_id: str | None = None,
                          weak: bool = False) -> float:
    """决策执行成功率 = f(可靠性, 丢包率, 切片, 轮次)。

    模型（确定性近似，可辩护）：单轮成功率 = 可靠性 × (1−丢包率)
    （弱覆盖段按 WEAK_DEGRADATION 取恶化值）；指令需 n_rounds 轮全部
    成功触达（4G 人工确认回环也是链路的一环）→ 总成功率 = 单轮^n_rounds。
    """
    if net_id not in NET_PROFILES:
        net_id = "5G"
    p = NET_PROFILES[net_id]
    if weak:
        wd = WEAK_DEGRADATION.get(net_id, WEAK_DEGRADATION["5G"])
        rel, loss = wd["reliability"], p["packet_loss"] * 10.0
    else:
        rel, loss = p["reliability"], p["packet_loss"]
    if slice_id and slice_id in SLICE_PROFILES and net_id != "4G":
        # 应急切片优先调度：链路质量按切片保障档取值（近似为不额外恶化）
        loss = min(loss, 0.00001) if SLICE_PROFILES[slice_id]["priority"] >= 3 else loss
    per_round = rel * (1.0 - loss)
    return max(0.0, min(1.0, per_round ** p["n_rounds"]))


def weak_coverage_report(event_id: str = "train_fault") -> dict:
    """弱覆盖场景（隧道/弯道/山区）× 网络档位（含 AI 空口增强）的 R 与成功率对比。"""
    out = []
    for ws in WEAK_SPOTS:
        rows = {}
        for key in ("4G", "5G", "5G-A", "5G-A+ai"):
            net = "5G-A" if key == "5G-A+ai" else key
            p = NET_PROFILES[net]
            wd = WEAK_DEGRADATION[key]
            sense = p["sense_s"] * wd["sense_factor"]
            comm = p["comm_ms"] * wd["comm_factor"] / 1000.0
            compute = p["compute_ms"] / 1000.0
            ev = INCIDENT_TYPES[event_id]
            total = (sense + comm + compute) * p["n_rounds"] + ev["t_execute_s"]
            rows[key] = {
                "sense_s": round(sense, 3), "comm_s": round(comm, 4),
                "r_total_s": round(total, 2),
                "reliability": wd["reliability"],
                "success_rate": round(decision_success_rate(
                    net, weak=True) if key != "5G-A+ai" else
                    WEAK_DEGRADATION["5G-A+ai"]["reliability"] *
                    (1 - NET_PROFILES["5G-A"]["packet_loss"] * 10.0), 6),
                "note": wd["note"],
            }
        out.append({"id": ws["id"], "corridor": ws["corridor"], "type": ws["type"],
                    "share_of_line": ws["share_of_line"], "nets": rows})
    return {"event": event_id, "weak_spots": out,
            "conclusion": "山区/隧道弱覆盖段：4G 成功率降至 ~73%，AI 空口增强的 5G-A "
                          "维持在 99.98% 以上 —— AI 空口是弱覆盖场景下指令可靠性的关键。",
            "basis": "弱覆盖段占比与降级因子为推演口径（real=False），锚定公网/切片/"
                     "确定性承载的公开量级差。"}


def isac_sensing_comparison() -> dict:
    """专用传感器 vs ISAC 基站感知（方案场景二）：布设/回传/时延/成本对比。

    红线：成本用「相对成本系数」表述（专用传感网方案=1.0 基准），
    不冒充招标实测价；点数按本项目 37 个断面拓扑推演。
    """
    seg_n = 37          # 与 data/flow_*.json 的 segments 数同口径（读数见 build_capability）
    dedicated = {
        "name": "专用传感网（GNSS 位移站 + 雨量计 + 倾角计 + DTU 回传）",
        "points": seg_n, "backhaul_links": seg_n,
        "sense_s": 20.0,
        "capex_index": 1.0,
        "note": "每断面独立组合传感 + 独立回传链路（DTU/专网），点状覆盖、逐点维护",
    }
    isac = {
        "name": "ISAC 基站感知（5G-A 基站兼做雷达，感知与通信同源）",
        "points": 0, "backhaul_links": 0,
        "sense_s": 1.0,
        "capex_index": 0.35,
        "note": "复用沿线通信基站的感知能力（软件升级 + 算力板卡边际投入），"
                "与通信同源回传、随覆盖连续感知，无独立回传链路",
    }
    return {
        "segments": seg_n,
        "dedicated": dedicated, "isac": isac,
        "deltas": {
            "sense_speedup": round(dedicated["sense_s"] / isac["sense_s"], 1),
            "capex_ratio": round(isac["capex_index"] / dedicated["capex_index"], 2),
        },
        "basis": "相对成本系数为推演假设（real=False，可替换为实际招标价）；"
                 "ISAC 能力锚定 3GPP R19 ISAC 立项（real=True）；感知时延为推演口径。",
        "conclusion": "ISAC 以 ~35% 的相对成本系数实现 20 倍感知提速与连续覆盖 —— "
                      "通感算智一体化替代专用传感器是可量化验证的降本路径。",
    }


def comm_capability_summary() -> dict:
    """三档网络对同一事件的 R 对比（通信能力底账的核心表）。"""
    rows = {}
    for net in ("4G", "5G", "5G-A"):
        row = {"label": NET_PROFILES[net]["label"],
               "reliability": NET_PROFILES[net]["reliability"],
               "compute_at": NET_PROFILES[net]["compute_at"]}
        for ev in INCIDENT_TYPES:
            r = response_time(net, ev)
            row[ev] = {"chain_s": r["chain_s"], "total_s": r["total_s"],
                       "total_min": r["total_min"]}
        rows[net] = row
    return rows


# ----------------------------------------------------------------------
# 瞬态推演：事件驱动的应急影响评估（叠加在治理方案的稳态指标之上）
# ----------------------------------------------------------------------
def _load_lines(scenario: str) -> dict:
    """读 data/flow_<scenario>.json，按线分组段流量（不反向依赖 agent.data_layer）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "data", f"flow_{scenario}.json")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    lines: dict[str, list[dict]] = {}
    for seg in d.get("segments", []):
        lines.setdefault(seg["line"], []).append(seg)
    return lines


def _pick_line(lines: dict, hub: str) -> str:
    """事件发生线：取 hub 所在流量最大段所属走廊；找不到则全网流量最大段。"""
    best, best_flow = None, -1
    fallback, fb_flow = None, -1
    for line, segs in lines.items():
        for s in segs:
            if s["flow"] > fb_flow:
                fallback, fb_flow = line, s["flow"]
            if hub in (s["from"], s["to"]) and s["flow"] > best_flow:
                best, best_flow = line, s["flow"]
    return best or fallback


def simulate_incident(scenario: str = "holiday", plan_config: dict | None = None,
                      event_id: str = "train_fault", net_id: str | None = None,
                      hub: str = "南昌站", slice_id: str | None = None,
                      mec_node: str | None = None, isac: bool = False) -> dict:
    """应急瞬态推演：给定治理方案（稳态配置）与事件，输出网络档位耦合的恢复指标。

    模型（全确定性，逐步可答辩）：
      W  影响窗口(min)  = R×n_rounds/60 换算后的链路时延 + 事件物理处置时间
      U  受阻客流(人)   = 断面高峰需求 × severity × W/60
      C  消散时间(min)  = U / 治理方案运能余量（恢复期以运能余量疏散堆积）
      TR 总恢复(min)   = W + C
      受影响人次 / 人均额外延误 / 旅客延误总人·分钟 由上述量直接导出
    网络 SLA 自变量：net_id（档位）/ slice_id（切片优先级与抢占）/
    mec_node（推理位置）/ isac（通感直感）—— 均由本函数进入业务指标。
    """
    if event_id not in INCIDENT_TYPES:
        event_id = "train_fault"
    cfg = plan_config or {}
    headway = float(cfg.get("headway_min", 12.0))
    cars = int(cfg.get("formation_cars", 8))
    surge = HOLIDAY_SURGE if scenario == "holiday" else 1.0

    lines = _load_lines(scenario)
    line = _pick_line(lines, hub)
    segs = lines[line]
    max_flow = max(s["flow"] for s in segs)
    demand_ph = max_flow * PEAK_HOUR_SHARE * surge            # 断面高峰需求（同 engine_b 口径）
    cap_ph = cars * SEATS_PER_CAR * (60.0 / headway) * LOAD_AVAILABILITY

    if net_id is None:
        net_id = net_of_line(line)                             # 按走廊当前档位
    rt = response_time(net_id, event_id, slice_id=slice_id,
                       mec_node=mec_node, isac=isac)
    ev = INCIDENT_TYPES[event_id]

    r_min = rt["total_s"] * 1.0 / 60.0                         # R 已含 n_rounds 与 execute
    w_min = r_min + ev["t_physical_min"]
    blocked = demand_ph * ev["severity"] * (w_min / 60.0)       # 窗口内受阻客流（人）
    surplus = max(cap_ph - demand_ph * (1.0 - ev["severity"]), 1.0)
    dissipate_min = blocked / surplus
    tr_min = w_min + dissipate_min
    affected = demand_ph * (w_min / 60.0)                      # 窗口内到达断面的人次
    delay_pp = w_min / 2.0 + dissipate_min                     # 人均额外延误（近似）
    person_min = affected * delay_pp                           # 旅客延误总量（人·分钟）

    return {
        "engine": "comm_layer",
        "engine_label": "通信数字孪生层（R 链路分解 + 应急瞬态推演）",
        "scenario": scenario, "hub": hub, "line": line,
        "event": event_id, "event_name": ev["name"], "event_desc": ev["desc"],
        "net": net_id, "net_label": rt["net_label"],
        "slice": rt.get("slice"), "slice_label": rt.get("slice_label"),
        "mec_node": rt.get("mec_node"), "compute_at": rt.get("compute_at"),
        "isac": bool(isac),
        "plan_config": {"headway_min": headway, "formation_cars": cars},
        "steady_state": {"demand_ph": round(demand_ph), "capacity_ph": round(cap_ph),
                         "capacity_surplus_ph": round(surplus)},
        "r_breakdown": rt["r_breakdown"], "n_rounds": rt["n_rounds"],
        "r_formula": rt["formula"], "r_note": rt["note"], "r_basis": rt["basis"],
        "r_total_s": rt["total_s"], "r_total_min": round(r_min, 3),
        "chain_s": rt.get("chain_s"),
        "jitter_ms": rt.get("jitter_ms"), "packet_loss": rt.get("packet_loss"),
        "t_physical_min": ev["t_physical_min"], "severity": ev["severity"],
        "impact_window_min": round(w_min, 2),
        "blocked_persons": round(blocked),
        "dissipate_min": round(dissipate_min, 2),
        "recovery_min": round(tr_min, 2),
        "affected_persons": round(affected),
        "delay_per_person_min": round(delay_pp, 2),
        "passenger_delay_person_min": round(person_min),
        "reliability": rt["reliability"],
        "decision_success_rate": rt.get("success_rate"),
        "model_note": "影响窗口 W = R + 事件物理处置时间；受阻 = 断面需求×severity×W；"
                      "消散 = 受阻/运能余量。全确定性可复算，数值为仿真推演（real=False 口径）。",
        "evidence": f"sim/comm_layer.py · 走廊 {line} · 档位 {net_id}"
                     + (f" · 切片 {slice_id}" if slice_id else "")
                     + (f" · MEC {mec_node}" if mec_node else "")
                     + (" · ISAC" if isac else ""),
    }


# ----------------------------------------------------------------------
# 网络SLA场景组推演（方案 4.3：对照组 vs 实验组 A/B/C）
# ----------------------------------------------------------------------
def simulate_network_scenario(scenario: str = "holiday", plan_config: dict | None = None,
                              group_id: str = "a_5ga_det", hub: str = "南昌站",
                              event_id: str = "train_fault") -> dict:
    """按 NETWORK_SCENARIO_GROUPS 的组配置做全要素推演。

    对照组：4G / 无切片 / 中心云；
    实验组A：5G-A 确定性承载 + 应急切片 + 南昌 MEC；
    实验组B：A + ISAC 通感直感（感知时延减半）；
    实验组C：A + AI 空口（标称段同 A，附弱覆盖段专项指标）。
    """
    g = next((x for x in NETWORK_SCENARIO_GROUPS if x["id"] == group_id),
             NETWORK_SCENARIO_GROUPS[1])
    r = simulate_incident(scenario, plan_config, event_id, g["net"], hub,
                          slice_id=g["slice"], mec_node=g["mec"], isac=g["isac"])
    r["group_id"] = g["id"]
    r["group_label"] = g["label"]
    if g["isac"]:
        r["isac_comparison"] = isac_sensing_comparison()
    if g["ai_air"]:
        r["weak_coverage"] = weak_coverage_report(event_id)
    return r


# ----------------------------------------------------------------------
# CLI：生成 / 校验 data/comm_capability.json
# ----------------------------------------------------------------------
def model_params() -> dict:
    """前端复算用的常量副本（SLA 切换台与后端同一公式、同一参数）。"""
    return {
        "r_formula": "R = (T_sense + T_comm + T_compute) × n_rounds + T_execute",
        "net_profiles": {n: {"sense_s": p["sense_s"], "comm_ms": p["comm_ms"],
                              "compute_ms": p["compute_ms"], "jitter_ms": p["jitter_ms"],
                              "packet_loss": p["packet_loss"], "n_rounds": p["n_rounds"],
                              "reliability": p["reliability"], "label": p["label"],
                              "compute_at_default": p["compute_at"]}
                         for n, p in NET_PROFILES.items()},
        "slices": {k: {"label": v["label"], "priority": v["priority"],
                       "preempt": v["preempt"], "comm_factor": v["comm_factor"]}
                   for k, v in SLICE_PROFILES.items()},
        "mec_nodes": {k: {"name": v["name"], "compute_ms": v["compute_ms"]}
                      for k, v in MEC_NODES.items()},
        "incidents": {k: {"name": v["name"], "t_execute_s": v["t_execute_s"],
                           "t_physical_min": v["t_physical_min"], "severity": v["severity"]}
                      for k, v in INCIDENT_TYPES.items()},
        "weak_degradation": {k: {"comm_factor": v["comm_factor"],
                                 "reliability": v["reliability"]}
                             for k, v in WEAK_DEGRADATION.items()},
    }


def build_capability(scenario: str = "holiday", hub: str = "南昌站") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "unit": "R 链路=秒 / 恢复=分钟 / 客流=人",
        "source_note": "real=True 为公开标准与案例锚点；NET_PROFILES 档位数值为仿真推演，"
                       "锚定 3GPP TR 38.913 URLLC（0.5ms 空口）、R19 ISAC 立项、5G-A 确定性网络"
                       "白皮书量级与高铁 5G 公开案例。通信层为能力档案+链路时序模型，不做电磁级仿真。",
        "comm_anchors": COMM_ANCHORS,
        "net_profiles": NET_PROFILES,
        "slice_profiles": SLICE_PROFILES,
        "mec_nodes": MEC_NODES,
        "weak_spots": WEAK_SPOTS,
        "weak_degradation": WEAK_DEGRADATION,
        "scenario_groups": NETWORK_SCENARIO_GROUPS,
        "incident_types": {k: {kk: vv for kk, vv in v.items()}
                           for k, v in INCIDENT_TYPES.items()},
        "comm_resources": _comm_resources(),
        "capability_matrix": comm_capability_summary(),
        "isac_comparison": isac_sensing_comparison(),
        "weak_coverage": weak_coverage_report(),
        "model_params": model_params(),
    }


def main(check: bool = False) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.abspath(os.path.join(here, "..", "data"))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "comm_capability.json")
    cap = build_capability()

    if check:
        if not os.path.exists(path):
            print("[FAIL] data/comm_capability.json 不存在，请先运行 python -m sim.comm_layer")
            return 1
        with open(path, encoding="utf-8") as f:
            disk = json.load(f)
        ok = disk == cap
        print(("[OK]   comm_capability 与现有 data/ 一致" if ok
               else "[FAIL] comm_capability 与现有 data/ 不一致，请重新生成") + "\n")
        if ok:
            print("通信能力底账（三档网络 × 事件 R 链路，秒）：")
            for net, row in cap["capability_matrix"].items():
                ev = row["train_fault"]
                print(f"  - {net:<6} {row['label']:<28} R={ev['total_s']:>8}s"
                      f"（可靠性 {row['reliability']}，推理位置 {row['compute_at']}）")
        return 0 if ok else 1

    with open(path, "w", encoding="utf-8") as f:
        json.dump(cap, f, ensure_ascii=False, indent=2)
    print(f"=== 通信数字孪生层 · 能力底账 ===")
    print(f"  输出: {path}")
    print(f"  网络档位: {len(NET_PROFILES)}（4G / 5G / 5G-A）  切片: {len(SLICE_PROFILES)} 类"
          f"  MEC 节点: {len(MEC_NODES)}  应急事件: {len(INCIDENT_TYPES)} 类")
    print(f"  走廊底账: {len(_comm_resources())} 条线  弱覆盖场景: {len(WEAK_SPOTS)} 处"
          f"  公开锚点: {len(COMM_ANCHORS)} 条（real=True）")
    for net, row in comm_capability_summary().items():
        ev = row["train_fault"]
        print(f"  - {net:<6} {row['label']:<28} 列车故障 R={ev['total_s']:>7}s"
              f"（可靠性 {row['reliability']}，推理位置 {row['compute_at']}）")

    print("\n=== 网络SLA场景组（对照组 vs 实验组A/B/C · holiday · 南昌站 · 列车故障） ===")
    for g in NETWORK_SCENARIO_GROUPS:
        r = simulate_network_scenario("holiday", {"headway_min": 8.0, "formation_cars": 8},
                                      g["id"], "南昌站")
        print(f"  - {g['label']:<28} 链路(不含执行) {r['chain_s']:>6}s · R={r['r_total_s']:>7}s"
              f" · 成功率 {r['decision_success_rate']*100:>7.3f}%"
              f" · 总恢复 {r['recovery_min']:>6}min"
              f" · 受影响 {r['affected_persons']:>5} 人")

    ic = isac_sensing_comparison()
    print(f"\n=== ISAC 通感 vs 专用传感网（{ic['segments']} 断面） ===")
    print(f"  - 专用传感网: {ic['dedicated']['points']} 个监测点 + {ic['dedicated']['backhaul_links']} 条独立回传"
          f" · 感知 {ic['dedicated']['sense_s']}s · 相对成本 {ic['dedicated']['capex_index']}")
    print(f"  - ISAC 基站感知: 复用通信基站 · 感知 {ic['isac']['sense_s']}s · 相对成本 {ic['isac']['capex_index']}"
          f"（{ic['deltas']['sense_speedup']}× 提速 / {ic['deltas']['capex_ratio']:.0%} 成本）")
    wc = weak_coverage_report()
    ws1 = wc["weak_spots"][0]
    print(f"\n=== 弱覆盖场景（{ws1['corridor']} · {ws1['type']}） ===")
    for key, row in ws1["nets"].items():
        print(f"  - {key:<9} R={row['r_total_s']:>7}s · 成功率 {row['success_rate']*100:>7.3f}% · {row['note']}")

    print("\n真实锚点（real=True）:")
    for a in COMM_ANCHORS:
        print(f"  - {a['name']}: {a['value']}  [{a['source']}]")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(check="--check" in sys.argv))
