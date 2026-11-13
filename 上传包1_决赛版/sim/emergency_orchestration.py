"""四智能体应急联动编排层（一体化处置方案落地）

定位：客流预估 → 风险感知 → 四智能体协同调度 → 仿真验证 的全链路闭环。
四类智能体：灾害预警(≤3s) / 维保调度(≤5s) / 应急联动(≤5s) / 客流预测(≤10s)。
时间模型（确定性，与 comm_layer 同底账）：
    阶段耗时 = 决策预算（方案口径上限，智能体在 MEC 运行，含计算）
             + 网络传输（NET_PROFILES.comm_ms × 切片因子）
    T0 感知  = ISAC 通感直感秒级发现（5G-A）/ 人工巡检分钟级（4G）
    总响应   = T0感知 + Σ各阶段耗时；对照口径 = 人工调度 2 小时
仿真验证：基线（既有间隔+既有网络） vs 处置后（方案配置+5G-A全要素），
    复用 comm_layer.simulate_incident / simulate_network_scenario，可复算。
全部数值为仿真推演（real=False 口径），锚点台账见 data/comm_capability.json。
"""
from __future__ import annotations

import json
import os

from . import comm_layer as CL

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# 四智能体决策预算（秒，方案 2.4 口径上限；智能体在 MEC 边缘运行）
AGENT_BUDGETS = [
    {"agent": "灾害预警智能体", "budget_s": 3.0,
     "duty": "多源数据融合判定风险等级，标记风险区段，推送预警"},
    {"agent": "维保调度智能体", "budget_s": 5.0,
     "duty": "生成限速指令、派发维保工单、远程复位尝试、备用车预案"},
    {"agent": "应急联动智能体", "budget_s": 5.0,
     "duty": "改线绕行、加开列车、应急接驳、信息发布"},
    {"agent": "客流预测智能体", "budget_s": 10.0,
     "duty": "预测改线后客流变化，动态调整发车间隔与编组"},
]

MANUAL_BASELINE_MIN = 120.0     # 人工调度口径（方案：远快于人工调度的 2 小时）

# 边坡风险分级（方案 2.3）
RISK_LEVELS = [
    {"level": "黄色", "displacement": "0.6mm/d", "rain": "降雨持续",
     "action": "加密巡检，准备限速"},
    {"level": "橙色", "displacement": "1.0mm/d", "rain": "降雨超阈值",
     "action": "限速20km/h，改线准备"},
    {"level": "红色", "displacement": "突破历史极值", "rain": "极端降雨",
     "action": "区段停运，全线疏散"},
]

# ----------------------------------------------------------------------
# 五类典型场景（方案 第四章）
# ----------------------------------------------------------------------
SCENES = [
    {
        "id": "landslide", "name": "暴雨边坡滑坡", "event": "landslide",
        "trigger": "三清山—婺源区间连续降雨超阈值，ISAC 基站感知位移速率突破红色阈值",
        "risk": "红色", "hub": "婺源站",
        "scenario": "holiday",
        "baseline_cfg": {"headway_min": 12.0, "formation_cars": 8},
        "handled_cfg": {"headway_min": 8.0, "formation_cars": 8, "limit_level": 1},
        "handled_net": "5G-A", "slice": "emergency", "mec": "shangrao", "isac": True,
        "steps": [
            {"agent": "灾害预警智能体", "actions": ["判定红色预警", "标记风险区段（三清山—婺源）"]},
            {"agent": "维保调度智能体", "actions": ["区段限速 20km/h", "加密巡检", "派发维保工单至最近班组"]},
            {"agent": "应急联动智能体", "actions": ["改经婺源东站绕行", "启动上饶—婺源应急接驳巴士", "昌九线加开 1 列临时列车"]},
            {"agent": "客流预测智能体", "actions": ["环线发车间隔调至 30 分钟", "预测绕行站点客流转移"]},
        ],
        "map_visual": ["风险区段红色闪烁", "改线路径绿色虚线", "应急巴士黄色虚线", "告警标签"],
    },
    {
        "id": "train_fault", "name": "单轨列车故障", "event": "train_fault",
        "trigger": "环庐山旅游线列车牵引逆变器过温报警，被迫区间停车",
        "risk": "橙色", "hub": "九江站",
        "scenario": "holiday",
        "baseline_cfg": {"headway_min": 12.0, "formation_cars": 8},
        "handled_cfg": {"headway_min": 8.0, "formation_cars": 8, "limit_level": 1},
        "handled_net": "5G-A", "slice": "emergency", "mec": "jiujiang", "isac": False,
        "steps": [
            {"agent": "灾害预警智能体", "actions": ["车辆状态监测自动报警确认", "标记故障区段"]},
            {"agent": "维保调度智能体", "actions": ["远程复位尝试", "失败→九江站调派备用单轨连挂救援", "工单派发最近维修班组"]},
            {"agent": "应急联动智能体", "actions": ["昌九通勤线加开临时列车接驳", "车载广播/APP 推送告知"]},
            {"agent": "客流预测智能体", "actions": ["调整环庐山线后续间隔防积压"]},
        ],
        "map_visual": ["故障区段红色闪烁", "故障车图标", "备用列车蓝色轨迹", "推送通知角标"],
    },
    {
        "id": "crowd_surge", "name": "节假日大客流", "event": "crowd_surge",
        "trigger": "三清山景区预约量突破最大承载量，上饶站站台候车超设计容量 120%",
        "risk": "橙色", "hub": "上饶站",
        "scenario": "holiday",
        "baseline_cfg": {"headway_min": 15.0, "formation_cars": 8},
        "handled_cfg": {"headway_min": 8.0, "formation_cars": 8, "limit_level": 3},
        "handled_net": "5G-A", "slice": "tourism", "mec": "shangrao", "isac": False,
        "steps": [
            {"agent": "客流预测智能体", "actions": ["预测站台超容 120%", "启动三级限流预案"]},
            {"agent": "维保调度智能体", "actions": ["闸机限流参数下发", "加派站务引导"]},
            {"agent": "应急联动智能体", "actions": ["三清山站只出不进", "引导至上饶站换乘", "加开上饶→南昌/九江临时市域列车"]},
            {"agent": "客流预测智能体", "actions": ["环线间隔 15→8 分钟", "平衡换乘站运力"]},
        ],
        "map_visual": ["大客流站点红色脉冲光圈", "限流标记", "三级限流方案卡"],
    },
    {
        "id": "extreme_rain", "name": "百年一遇极端降水", "event": "landslide",
        "trigger": "连续降雨量突破历史极值，气象/雨量/位移/轨道积水四源并中",
        "risk": "红色", "hub": "南昌站",
        "scenario": "holiday",
        "baseline_cfg": {"headway_min": 12.0, "formation_cars": 8},
        "handled_cfg": {"headway_min": 15.0, "formation_cars": 8, "limit_level": 3},
        "handled_net": "5G-A", "slice": "emergency", "mec": "nanchang", "isac": True,
        "steps": [
            {"agent": "灾害预警智能体", "actions": ["接入气象预警/降雨量/边坡位移/轨道积水四类数据源", "判定红色预警"]},
            {"agent": "维保调度智能体", "actions": ["全线停运指令", "排水系统检查", "设备防护挡板加装"]},
            {"agent": "应急联动智能体", "actions": ["旅客疏散组织", "应急接驳巴士待命", "通勤层加开临时列车转运滞留"]},
            {"agent": "客流预测智能体", "actions": ["预测客流骤降与滞留峰值", "运力集中疏散通道"]},
        ],
        "map_visual": ["全线红色高亮", "停运标记", "疏散路径绿色箭头"],
    },
    {
        "id": "transfer_bottleneck", "name": "南昌站换乘瓶颈", "event": "crowd_surge",
        "trigger": "节假日换乘量 2,800→11,550 人次，通道超设计通行能力",
        "risk": "橙色", "hub": "南昌站",
        "scenario": "holiday",
        "baseline_cfg": {"headway_min": 15.0, "formation_cars": 8},
        "handled_cfg": {"headway_min": 8.0, "formation_cars": 8, "limit_level": 2},
        "handled_net": "5G-A", "slice": "emergency", "mec": "nanchang", "isac": False,
        "steps": [
            {"agent": "客流预测智能体", "actions": ["预测换乘量超通道设计容量", "输出最优限流建议"]},
            {"agent": "维保调度智能体", "actions": ["楼扶梯组的应急检修待命"]},
            {"agent": "应急联动智能体", "actions": ["加开疏运列车", "通道限流", "启动备用通道"]},
            {"agent": "客流预测智能体", "actions": ["单轨间隔 15→8 分钟", "验证通道拥挤度回落"]},
        ],
        "map_visual": ["换乘通道热力红色高亮", "限流栏杆图标", "疏运列车轨迹"],
    },
]


def forecast_flow(scenario: str = "holiday") -> dict:
    """客流预估（第一环）：站点/段流量走向 + 未来 1-2h 预判（确定性口径）。"""
    path = os.path.join(DATA_DIR, f"flow_{scenario}.json")
    d = json.load(open(path, encoding="utf-8"))
    sts = d["stations"]
    total = sum(s["flow"] for s in sts)
    top5 = sorted(sts, key=lambda s: -s["flow"])[:5]
    peak = CL.PEAK_HOUR_SHARE
    return {
        "scenario": scenario,
        "daily_total": total,
        "next_1h_total": round(total * peak),
        "next_2h_total": round(total * peak * 1.85),
        "top5": [{"name": s["name"], "flow": s["flow"],
                  "next_1h": round(s["flow"] * peak)} for s in top5],
        "method": "站点基础流量×场景乘子；段流量=两端站点均值；峰值小时占比 "
                  f"{peak:.0%}；预测在 MEC 边缘运行，结果毫秒级同步调度中心",
        "multipliers": {"weekday": {"commuter": 1.00, "tourism": 0.45},
                        "holiday": {"commuter": 0.75, "tourism": 2.60}},
    }


def _timeline(net: str, slice_id: str, mec: str, isac: bool) -> dict:
    """确定性时间线：T0 感知 + 四智能体阶段（决策预算 + 网络传输）。"""
    p = CL.NET_PROFILES[net]
    sl = CL.SLICE_PROFILES.get(slice_id) if slice_id and net != "4G" else None
    comm_ms = p["comm_ms"] * (sl["comm_factor"] if sl else 1.0)
    sense_s = p["sense_s"] * (0.5 if (isac and net == "5G-A") else 1.0)
    compute_ms = (CL.MEC_NODES[mec]["compute_ms"]
                  if (mec and net in ("5G", "5G-A")) else p["compute_ms"])
    stages, t = [], sense_s
    for i, a in enumerate(AGENT_BUDGETS):
        # 决策预算为上限（含 MEC 计算）；网络传输单列；4G 人工确认轮次翻倍
        decision = a["budget_s"] * (p["n_rounds"] if net == "4G" else 1)
        # 4G：推理在中心云，计算时延叠加在阶段内；5G-A：MEC 就近已含于预算
        extra = (compute_ms / 1000.0) if net == "4G" else 0.0
        stage_s = decision + extra + comm_ms / 1000.0
        stages.append({
            "seq": i + 1, "agent": a["agent"], "duty": a["duty"],
            "decision_budget_s": decision, "comm_s": round(comm_ms / 1000.0, 4),
            "stage_s": round(stage_s, 3),
            "start_s": round(t, 3), "end_s": round(t + stage_s, 3),
        })
        t += stage_s
    return {
        "net": net, "net_label": p["label"],
        "slice": slice_id, "slice_label": sl["label"] if sl else None,
        "mec": mec, "compute_at": (CL.MEC_NODES[mec]["name"]
                                    if mec and net in ("5G", "5G-A") else p["compute_at"]),
        "isac": bool(isac), "sense_s": round(sense_s, 3),
        "t0_label": "ISAC 通感直感" if (isac and net == "5G-A")
                     else ("轨旁传感/视频回传" if net != "4G" else "人工巡检上报"),
        "stages": stages, "total_s": round(t, 2),
        "formula": "总响应 = T0感知 + Σ(决策预算(×人工确认轮次) + 中心云计算(仅4G) + 网络传输)",
    }


def run_scene(scene_id: str = "landslide", verify: bool = True) -> dict:
    """单场景全链路：客流预估 → 时间线 → 仿真验证（基线 vs 处置后）。"""
    sc = next((s for s in SCENES if s["id"] == scene_id), SCENES[0])
    tl = _timeline(sc["handled_net"], sc["slice"], sc["mec"], sc["isac"])
    tl_ctl = _timeline("4G", None, None, False)
    out = {
        "scene_id": sc["id"], "scene_name": sc["name"],
        "trigger": sc["trigger"], "risk": sc["risk"],
        "event": sc["event"], "hub": sc["hub"],
        "risk_levels": RISK_LEVELS,
        "forecast": forecast_flow(sc["scenario"]),
        "timeline": tl,
        "timeline_control_4g": tl_ctl,
        "manual_baseline_min": MANUAL_BASELINE_MIN,
        "speedup_vs_manual": round(MANUAL_BASELINE_MIN * 60 / max(tl["total_s"], 0.1), 1),
        "steps": sc["steps"],
        "map_visual": sc["map_visual"],
        "verify": None,
    }
    if verify:
        base = CL.simulate_incident(sc["scenario"], sc["baseline_cfg"],
                                    sc["event"], None, sc["hub"])
        handled = CL.simulate_network_scenario(
            sc["scenario"], sc["handled_cfg"],
            next(g["id"] for g in CL.NETWORK_SCENARIO_GROUPS
                 if g["net"] == sc["handled_net"] and bool(g["isac"]) == bool(sc["isac"])),
            sc["hub"], sc["event"])
        # 场景三/五以限流+压缩间隔为主，handled 配置经 handled_cfg 传入，
        # simulate_network_scenario 固定用组内默认方案，此处按场景配置重算 handled：
        handled = CL.simulate_incident(sc["scenario"], sc["handled_cfg"], sc["event"],
                                       sc["handled_net"], sc["hub"],
                                       slice_id=sc["slice"], mec_node=sc["mec"],
                                       isac=sc["isac"])
        out["verify"] = {
            "baseline": {"net": base["net"], "headway_min": base["plan_config"]["headway_min"],
                         "recovery_min": base["recovery_min"],
                         "affected": base["affected_persons"],
                         "delay_person_min": base["passenger_delay_person_min"]},
            "handled": {"net": handled["net"], "slice": handled.get("slice"),
                        "headway_min": handled["plan_config"]["headway_min"],
                        "recovery_min": handled["recovery_min"],
                        "affected": handled["affected_persons"],
                        "delay_person_min": handled["passenger_delay_person_min"]},
            "delta": {"recovery_gain_min": round(base["recovery_min"] - handled["recovery_min"], 2),
                      "affected_reduction": base["affected_persons"] - handled["affected_persons"],
                      "delay_person_min_reduction":
                          base["passenger_delay_person_min"] - handled["passenger_delay_person_min"]},
            "note": "基线=既有间隔+走廊既有网络；处置后=方案配置+5G-A全要素（应急切片+MEC+ISAC）。"
                    "全部经 comm_layer 确定性复算，可复现。",
        }
    return out


def run_all(verify: bool = True) -> dict:
    scenes = [run_scene(s["id"], verify) for s in SCENES]
    return {
        "schema": "emergency_orchestration v1.0",
        "engine": "comm_layer + engine_b 口径（全确定性）",
        "agents": AGENT_BUDGETS,
        "risk_levels": RISK_LEVELS,
        "total_response_budget_s": sum(a["budget_s"] for a in AGENT_BUDGETS),
        "manual_baseline_min": MANUAL_BASELINE_MIN,
        "scenes": scenes,
        "conclusion": "客流走向提前预判，事故触发秒级响应，四类智能体协同处置，"
                      "仿真引擎全程验证：5G-A 全要素下总响应 ≈"
                      f"{min(s['timeline']['total_s'] for s in scenes)}~"
                      f"{max(s['timeline']['total_s'] for s in scenes)}s"
                      f"（决策预算 {sum(a['budget_s'] for a in AGENT_BUDGETS)}s + 感知与传输），"
                      f"较人工调度 {MANUAL_BASELINE_MIN:.0f}min 快约两个数量级。",
    }


def _write_data(out: dict) -> str:
    path = os.path.join(DATA_DIR, "emergency_orchestration.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return path


if __name__ == "__main__":
    import sys
    out = run_all()
    path = _write_data(out)
    print("=== 四智能体应急联动 · 一体化处置编排 ===")
    print(f"  输出: {path}")
    print(f"  决策预算合计: {out['total_response_budget_s']}s（四智能体）· 人工调度对照 {out['manual_baseline_min']:.0f}min")
    for sc in out["scenes"]:
        tl = sc["timeline"]
        v = sc["verify"]
        print(f"\n[{sc['scene_name']}] 风险 {sc['risk']} · {tl['net_label']}"
              f" · 切片 {tl['slice_label']} · {tl['compute_at']}")
        print(f"  T0 感知 {tl['sense_s']}s（{tl['t0_label']}）")
        for st in tl["stages"]:
            print(f"  {st['seq']}. {st['agent']:<8} 决策{st['decision_budget_s']}s"
                  f" + 传输{st['comm_s']}s → {st['start_s']}~{st['end_s']}s")
        print(f"  总响应 {tl['total_s']}s（较人工快 {sc['speedup_vs_manual']}×）")
        if v:
            print(f"  仿真验证: 恢复 {v['baseline']['recovery_min']}→{v['handled']['recovery_min']}min"
                  f"（- {v['delta']['recovery_gain_min']}min）· 受影响 "
                  f"{v['baseline']['affected']:,}→{v['handled']['affected']:,} 人"
                  f"（- {v['delta']['affected_reduction']:,}）· 旅客延误 "
                  f"{v['baseline']['delay_person_min']:,}→{v['handled']['delay_person_min']:,} 人·分钟")
    print("\n" + out["conclusion"])
    sys.exit(0)
