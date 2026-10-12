"""智能体层 · 四智能体应急编排适配桥

将 sim.emergency_orchestration 的输出裁剪为工具调用友好（体量可控、字段可审计），
完整明细以 data/emergency_orchestration.json 为准（由 python -m sim.emergency_orchestration 生成）。
"""
from __future__ import annotations

import json
import os

from sim import emergency_orchestration as EO

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "emergency_orchestration.json")


def _load_all() -> dict:
    if os.path.exists(_DATA):
        return json.load(open(_DATA, encoding="utf-8"))
    return EO.run_all()


def run_scene(scene_id: str) -> dict:
    sc = EO.run_scene(scene_id)
    tl, ctl, v = sc["timeline"], sc["timeline_control_4g"], sc["verify"]
    return {
        "scene": sc["scene_id"], "name": sc["scene_name"], "risk": sc["risk"],
        "trigger": sc["trigger"], "hub": sc["hub"],
        "forecast_1h": sc["forecast"]["next_1h_total"],
        "agents": [{"agent": a["agent"], "window": f"{a['start_s']}~{a['end_s']}s",
                    "decision_s": a["decision_budget_s"], "comm_s": a["comm_s"]}
                   for a in tl["stages"]],
        "t0": {"sense_s": tl["sense_s"], "label": tl["t0_label"]},
        "total_response_s": tl["total_s"],
        "control_4g_total_s": ctl["total_s"],
        "manual_baseline_min": sc["manual_baseline_min"],
        "speedup_vs_manual": sc["speedup_vs_manual"],
        "net": {"label": tl["net_label"], "slice": tl["slice_label"],
                "compute_at": tl["compute_at"], "isac": tl["isac"]},
        "actions": sc["steps"],
        "map_visual": sc["map_visual"],
        "verify": (None if not v else {
            "recovery_min": f"{v['baseline']['recovery_min']} → {v['handled']['recovery_min']}",
            "affected": f"{v['baseline']['affected']:,} → {v['handled']['affected']:,}",
            "delay_person_min": f"{v['baseline']['delay_person_min']:,} → "
                                f"{v['handled']['delay_person_min']:,}",
            "note": v["note"]}),
        "evidence": "sim/emergency_orchestration.py · comm_layer 同底账 · 全确定性可复算",
    }


def summary() -> dict:
    out = _load_all()
    return {
        "agents": out["agents"],
        "risk_levels": out["risk_levels"],
        "total_response_budget_s": out["total_response_budget_s"],
        "manual_baseline_min": out["manual_baseline_min"],
        "scenes": [{"scene": s["scene_id"], "name": s["scene_name"], "risk": s["risk"],
                    "hub": s["hub"], "total_response_s": s["timeline"]["total_s"],
                    "speedup_vs_manual": s["speedup_vs_manual"]}
                   for s in out["scenes"]],
        "conclusion": out["conclusion"],
    }
