#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z2 · 20 组评测矩阵（2 场景 × 5 枢纽 × 2 需求强度）

用法：
    python3 -m finals.matrix            # 跑/续跑矩阵，产物写 output/experiments/matrix/
    python3 -m finals.matrix --verify   # 全量计算两遍，比对哈希（确定性验证，不写盘）

设计口径：
  - 每组：基准 + A/B/C/D（策略配置取自 data/agent_decision.json plans[].config，
    仅覆盖 scenario / demand_mult，不手写数值）+ 60 次随机盲搜
    （headway∈{8,9,10,12,15}、limit_level∈{0,1,2}、demand_mult∈{0.8,1.0,1.2,1.4}、
    fleet_limit 固定 480，seed=组号）。
  - 评分复用 experiments.run() / experiments.score_plan()（默认权重 40/30/20/10，
    稳健性固定 60，与消融实验同口径）；feasible 复用 agent.tools.t_guardrail_validate()；
    admissible / block_reason 复用 api_server.admissibility_of()。不另写评分公式。
  - 推荐方案 = admissible 方案中按总分最高者（未过服务底线不当选）。
  - 确定性：全部固定种子；--verify 对全部组数据做 json 规范化后比对哈希。
  - 续跑：每完成一组即落盘 matrix_<scenario>.json；重启后跳过已存在的组。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from experiments import run as exp_run            # noqa: E402  仿真（复用，不改）
from experiments import score_plan as exp_score   # noqa: E402  评分（复用，不改）
from agent import tools as T                      # noqa: E402  护栏校验（复用，不改）
from api_server import attach_economics           # noqa: E402  服务底线（复用，不改）
from api_server import admissibility_of           # noqa: E402  底线判定（复用，不改）
from api_server import flow_data                  # noqa: E402  只读 flow_*.json

OUT_DIR = os.path.join(HERE, "output", "experiments", "matrix")
SCENARIOS = ("holiday", "weekday")
HUBS_WANTED = ["南昌站", "九江站", "上饶站", "庐山站", "赣州站"]
DEMANDS = (1.0, 1.2)
BLIND_HEADWAY = (8, 9, 10, 12, 15)
BLIND_LIMIT = (0, 1, 2)
BLIND_ROUNDS = 60
PLAN_IDS = ("A", "B", "C", "D")
# 口径版本：v1 = 盲搜空间含 demand 0.8/1.4 且不筛 admissible（归档 matrix_legacy.json）；
#          v2 = 盲搜 demand 固定为组需求，仅 admissible 候选参与最优/P90（Z2b，已归档）；
#          v3 = 双口径拆分（Z2c）：口径甲「零增购 fleet 480」/ 口径乙「增购授权 fleet 600」
SPEC_VERSION = 3
LEGACY_SPEC_VERSION = 1


def resolve_hubs(scenario: str):
    """以 data/flow_*.json 实际站点为准返回 5 个枢纽；缺失时按客流降序补足并注明。"""
    names = {s.get("name") for s in flow_data(scenario).get("stations", [])}
    chosen = [h for h in HUBS_WANTED if h in names]
    replaced = []
    if len(chosen) < 5:
        ranked = sorted(flow_data(scenario).get("stations", []),
                        key=lambda s: s.get("flow", 0), reverse=True)
        for s in ranked:
            if s.get("name") and s["name"] not in chosen:
                chosen.append(s["name"])
                replaced.append(s["name"])
            if len(chosen) == 5:
                break
    return chosen[:5], replaced


def load_strategy_configs():
    """A/B/C/D 请求配置与基准配置（含方案名）：唯一来源是冻结决策文档，不手写数值。"""
    with open(os.path.join(HERE, "data", "agent_decision.json"), encoding="utf-8") as f:
        doc = json.load(f)
    base = {k: v for k, v in doc["baseline"]["config"].items()}
    plans = {p["id"]: {"name": p.get("name"),
                       "config": {k: v for k, v in p["config"].items()}}
             for p in doc["plans"]}
    missing = [pid for pid in PLAN_IDS if pid not in plans]
    if missing:
        raise SystemExit("冻结决策文档缺少方案：{}".format(missing))
    return base, plans


def build_groups():
    """20 组的 (gid, scenario, hub, demand) 与枢纽替换说明。"""
    groups = []
    notes = {}
    gid = 0
    for scenario in SCENARIOS:
        hubs, replaced = resolve_hubs(scenario)
        if replaced:
            notes[scenario] = replaced
        for hub in hubs:
            for d in DEMANDS:
                gid += 1
                groups.append((gid, scenario, hub, d))
    return groups, notes


def _blind_search(gid: int, scenario: str, hub: str, demand: float,
                  fleet_limit: int, base_metrics: dict) -> dict:
    """随机盲搜（公平口径）：seed=组号×1000+fleet（显式数值，跨运行稳定）；
    demand 固定为组需求；只有 admissible 候选参与最优/P90。"""
    rng = random.Random(gid * 1000 + fleet_limit)
    scores_adm = []
    admissible_count = 0
    best_cfg = None
    for _ in range(BLIND_ROUNDS):
        cfg = {"scenario": scenario,
               "headway_min": rng.choice(BLIND_HEADWAY),
               "formation_cars": 8,
               "limit_level": rng.choice(BLIND_LIMIT),
               "demand_mult": demand,
               "fleet_limit": fleet_limit,
               "baseline_flag": False}
        gres = T.t_guardrail_validate(None, param_json=cfg)
        feasible = bool(gres.get("passed"))
        m = exp_run(cfg, hub)
        s = exp_score(m, base_metrics)["total"]
        adm, _ = admissibility_of({"feasible": feasible, "metrics": m}, base_metrics)
        if adm:
            admissible_count += 1
            scores_adm.append(s)
            if best_cfg is None or s > best_cfg[0]:
                best_cfg = (s, cfg)
    ranked = sorted(scores_adm)
    return {
        "seed": "{}@{}".format(gid, fleet_limit), "rounds": BLIND_ROUNDS,
        "fleet_limit": fleet_limit,
        "space": {"headway_min": list(BLIND_HEADWAY),
                  "limit_level": list(BLIND_LIMIT),
                  "demand_mult": demand},
        "admissible_count": admissible_count,
        "admissible_rate": round(admissible_count / BLIND_ROUNDS, 4),
        "best": ranked[-1] if ranked else None,
        "p90": (ranked[min(len(ranked) - 1, math.ceil(0.9 * len(ranked)) - 1)]
                if ranked else None),
        "best_config": best_cfg[1] if best_cfg else None,
        "scores_admissible": scores_adm,
    }


def compute_group(gid: int, scenario: str, hub: str, demand: float, base_cfg: dict,
                  plan_cfgs: dict) -> dict:
    base = {**base_cfg, "scenario": scenario, "demand_mult": demand}
    base_metrics = exp_run(base, hub)

    plans = []
    for pid in PLAN_IDS:
        cfg = {**plan_cfgs[pid]["config"], "scenario": scenario, "demand_mult": demand,
               "baseline_flag": False}
        g = T.t_guardrail_validate(None, param_json=cfg, plan_id=pid)
        metrics = exp_run(cfg, hub)
        score = exp_score(metrics, base_metrics)
        plans.append({
            "id": pid,
            "name": plan_cfgs[pid]["name"],
            "config": cfg,
            "guardrail": {"passed": bool(g.get("passed")),
                          "violations": [
                              {"id": v.get("id"), "name": v.get("name")}
                              for v in (g.get("violations") or []) if isinstance(v, dict)]},
            "metrics": metrics,
            "score": score,
        })

    # 服务底线 / 经济标签：与 /api/run 完全同一套函数（api_server.attach_economics）
    doc = attach_economics({"baseline": {"metrics": base_metrics}, "plans": plans})
    plans = doc["plans"]

    def track(pool_plans: list, fleet_limit: int) -> dict:
        admissible = [p for p in pool_plans if p.get("admissible")]
        rec = max(admissible, key=lambda p: p["score"]["total"]) if admissible else None
        blind = _blind_search(gid, scenario, hub, demand, fleet_limit, base_metrics)
        rec_total = rec["score"]["total"] if rec else None
        rec_delay = rec["metrics"]["avg_delay_min"] if rec else None
        p90 = blind["p90"]
        return {
            "fleet_limit": fleet_limit,
            "pool_ids": [p["id"] for p in pool_plans],
            "recommended": None if rec is None else {
                "id": rec["id"], "name": rec["name"], "score": rec_total,
                "metrics": rec["metrics"],
                "requires_capex": rec.get("requires_capex"),
                "additional_trains": rec.get("additional_trains"),
            },
            "blind": blind,
            "compare": {
                "recommended_beats_p90": bool(rec_total is not None and
                                              (p90 is None or rec_total > p90)),
                "delay_improvement_min": (round(base_metrics["avg_delay_min"] - rec_delay, 2)
                                          if rec_delay is not None else None),
            },
        }

    # 口径甲（零增购）：池 = 配置 fleet ≤ 480 的方案（D 因需 600 排除；C 留池由护栏拦）
    # 口径乙（增购授权 600）：池 = 全部方案（D 可行；C 仍按自身 480 被拦）
    track_nc = track([p for p in plans if (p["config"].get("fleet_limit") or 480) <= 480], 480)
    track_cx = track(list(plans), 600)

    return {
        "group_id": gid,
        "scenario": scenario,
        "hub": hub,
        "demand_mult": demand,
        "baseline": {"config": base, "metrics": base_metrics},
        "plans": plans,
        "tracks": {"nocapex": track_nc, "capex": track_cx},
    }


def groups_hash(all_groups: list) -> str:
    payload = json.dumps(all_groups, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_all(verbose: bool = False):
    """全量计算（内存），返回 (groups, notes)。--verify 用：不落盘。"""
    base_cfg, plan_cfgs = load_strategy_configs()
    groups, notes = build_groups()
    out = []
    for gid, scenario, hub, demand in groups:
        g = compute_group(gid, scenario, hub, demand, base_cfg, plan_cfgs)
        out.append(g)
        if verbose:
            print("  组 {}：{} {} ×{:.1f} 甲推荐={} 乙推荐={}".format(
                gid, scenario, hub, demand,
                (g["tracks"]["nocapex"]["recommended"] or {}).get("id"),
                (g["tracks"]["capex"]["recommended"] or {}).get("id")), flush=True)
    return out, notes


def scenario_file(scenario: str) -> str:
    return os.path.join(OUT_DIR, "matrix_{}.json".format(scenario))


def archive_legacy_if_needed() -> None:
    """历史口径结果归档到 matrix_legacy.json（versions 列表，只增不改不删）。"""
    legacy_path = os.path.join(OUT_DIR, "matrix_legacy.json")
    versions = []
    if os.path.exists(legacy_path):
        with open(legacy_path, encoding="utf-8") as f:
            legacy = json.load(f)
        versions = legacy.get("versions") or []
        if not versions and legacy.get("spec_version") == LEGACY_SPEC_VERSION:
            # v1 平铺结构迁移为 versions 列表
            versions = [{"spec_version": LEGACY_SPEC_VERSION,
                         "note": legacy.get("note"),
                         "stats": legacy.get("stats"), "rows": legacy.get("rows")}]
    old_summary_path = os.path.join(OUT_DIR, "matrix_summary.json")
    if os.path.exists(old_summary_path):
        with open(old_summary_path, encoding="utf-8") as f:
            old = json.load(f)
        sv = old.get("spec_version")
        if sv is not None and sv != SPEC_VERSION and \
                all(v.get("spec_version") != sv for v in versions):
            versions.append({"spec_version": sv,
                             "generated_at": old.get("generated_at"),
                             "stats": old.get("stats"), "rows": old.get("rows")})
            print("[legacy] v{} 口径结果已归档 → matrix_legacy.json".format(sv), flush=True)
    payload = {
        "note": "历史口径对照库：v1 = 盲搜可降需求刷分；v2 = 盲搜固定需求但推荐混池"
                "（零增购/增购未分表）；当前 v3 = 双口径拆分。只增不改。",
        "versions": versions,
    }
    with open(legacy_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)


def load_existing(scenario: str) -> dict:
    """读取既有结果；口径版本不符（旧口径）则丢弃组数据（已归档 legacy）。"""
    path = scenario_file(scenario)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("spec_version") == SPEC_VERSION:
            return data
        print("[{}] 口径版本不符（文件 v{} ≠ 当前 v{}），丢弃旧组数据重新计算".format(
            scenario, data.get("spec_version"), SPEC_VERSION), flush=True)
    return {"scenario": scenario, "spec_version": SPEC_VERSION, "groups": []}


def save_scenario(scenario: str, data: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    data["spec_version"] = SPEC_VERSION
    path = scenario_file(scenario)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def run_matrix() -> int:
    archive_legacy_if_needed()
    base_cfg, plan_cfgs = load_strategy_configs()
    groups, notes = build_groups()
    by_scenario = {}
    for gid, scenario, hub, demand in groups:
        by_scenario.setdefault(scenario, []).append((gid, hub, demand))

    all_rows = []
    totals = {"beats_p90": 0, "infeasible": 0, "blocks": 0}
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    t0 = time.time()
    for scenario in SCENARIOS:
        data = load_existing(scenario)
        done = {(g["hub"], round(g["demand_mult"], 2)) for g in data["groups"]}
        for gid, hub, demand in by_scenario[scenario]:
            if (hub, round(demand, 2)) in done:
                print("[{}/{}] 跳过已完成组 {}：{} ×{:.1f}".format(
                    scenario, gid, gid, hub, demand), flush=True)
                continue
            print("[{}] 组 {}/20：{} {} ×{:.1f} 计算中…".format(
                scenario, gid, gid, hub, demand), flush=True)
            g = compute_group(gid, scenario, hub, demand, base_cfg, plan_cfgs)
            data["groups"].append(g)
            save_scenario(scenario, data)   # 每完成一组即落盘，中断可续跑
            print("  完成：甲推荐 {} （胜P90={}）· 乙推荐 {} （胜P90={}）".format(
                (g["tracks"]["nocapex"]["recommended"] or {}).get("id"),
                g["tracks"]["nocapex"]["compare"]["recommended_beats_p90"],
                (g["tracks"]["capex"]["recommended"] or {}).get("id"),
                g["tracks"]["capex"]["compare"]["recommended_beats_p90"]), flush=True)

    # 汇总（读回全部组，含续跑的历史组）
    all_groups = []
    for scenario in SCENARIOS:
        all_groups.extend(load_existing(scenario)["groups"])
    if len(all_groups) < 20:
        print("警告：仅完成 {}/20 组（存在未完成组，重跑本命令可续）".format(len(all_groups)))

    def track_stats(groups: list, key: str) -> dict:
        rows = []
        beats = 0
        infeasible = 0
        blocks = 0
        gaps = []
        for g in groups:
            t = g["tracks"][key]
            rec = t.get("recommended") or {}
            rows.append({
                "group_id": g["group_id"], "scenario": g["scenario"], "hub": g["hub"],
                "demand_mult": g["demand_mult"],
                "recommended_id": rec.get("id"), "recommended_score": rec.get("score"),
                "recommended_delay": (rec.get("metrics") or {}).get("avg_delay_min"),
                "requires_capex": rec.get("requires_capex"),
                "additional_trains": rec.get("additional_trains"),
                "blind_admissible_rate": t["blind"]["admissible_rate"],
                "blind_best": t["blind"]["best"], "blind_p90": t["blind"]["p90"],
                "beats_p90": t["compare"]["recommended_beats_p90"],
                "delay_improvement_min": t["compare"]["delay_improvement_min"],
            })
            beats += 1 if t["compare"]["recommended_beats_p90"] else 0
            if t["blind"]["best"] is not None and rec.get("score") is not None:
                gaps.append(t["blind"]["best"] - rec["score"])
            for p in g["plans"]:
                if p.get("feasible") is False:
                    infeasible += 1
            blocks += sum(1 for p in g["plans"] if p.get("feasible") is False)
        n = len(rows)
        rec_ids = {}
        for r in rows:
            rec_ids[r["recommended_id"]] = rec_ids.get(r["recommended_id"], 0) + 1
        by_scenario = {}
        for scen in SCENARIOS:
            srows = [r for r in rows if r["scenario"] == scen]
            by_scenario[scen] = {
                "beats_p90_count": sum(1 for r in srows if r["beats_p90"]),
                "total": len(srows),
            }
        return {
            "rows": rows,
            "stats": {
                "recommended_beats_p90_count": beats,
                "by_scenario": by_scenario,
                "recommended_avg_score": (round(sum(r["recommended_score"] or 0
                                                    for r in rows) / n, 1) if n else None),
                "avg_delay_improvement_min": (round(sum(r["delay_improvement_min"] or 0
                                                        for r in rows) / n, 2) if n else None),
                "blind_admissible_rate": (round(sum(r["blind_admissible_rate"]
                                                    for r in rows) / n, 4) if n else None),
                "blind_best_gap_avg": (round(sum(gaps) / len(gaps), 2) if gaps else None),
                "infeasible_plan_count": infeasible,
                "guardrail_block_count": blocks,
                "recommended_id_counts": rec_ids,
            },
        }

    nocapex = track_stats(all_groups, "nocapex")
    capex = track_stats(all_groups, "capex")
    all_rows = nocapex["rows"]
    n = len(all_rows)

    summary = {
        "generated_at": started,
        "elapsed_s": round(time.time() - t0, 1),
        "spec_version": SPEC_VERSION,
        "groups_completed": n,
        "stats_nocapex": nocapex["stats"],
        "stats_capex": capex["stats"],
        "rows_nocapex": nocapex["rows"],
        "rows_capex": capex["rows"],
        "hub_notes": notes,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "matrix_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    write_report(summary, notes)
    print()
    print("完成 {}/20 组 · 甲（零增购 480）胜出 {}/20 · 乙（增购授权 600）胜出 {}/20".format(
        n, nocapex["stats"]["recommended_beats_p90_count"],
        capex["stats"]["recommended_beats_p90_count"]))
    print("平均延误改善：甲 {} min · 乙 {} min".format(
        nocapex["stats"]["avg_delay_improvement_min"],
        capex["stats"]["avg_delay_improvement_min"]))
    print("产物：{}".format(OUT_DIR))
    return 0 if n == 20 else 1


def write_report(summary: dict, notes: dict) -> None:
    sn = summary["stats_nocapex"]
    sx = summary["stats_capex"]
    lines = []
    lines.append("# Z2 · 20 组评测矩阵报告（双口径 v{}）\n".format(summary["spec_version"]))
    lines.append("> **评分口径**：experiments.score_plan，默认权重 40/30/20/10，"
                 "稳健性固定 60（与消融实验同口径）；admissible = 过护栏且过服务底线"
                 "（延误/未承运不高于现状），与 /api/run 同源；盲搜候选同样只计 admissible，"
                 "P90 为最近邻位法。\n")
    lines.append("> 生成：{} · 用时 {}s · 2 场景 × 5 枢纽 × 2 需求（1.0/1.2）\n".format(
        summary["generated_at"], summary["elapsed_s"]))
    if notes:
        for scenario, replaced in notes.items():
            lines.append("> 注：{} 场景中数据缺少预设枢纽，已按 flow_{}.json 客流降序替换为：{}\n".format(
                scenario, scenario, "、".join(replaced)))

    def section(title, citability, st, rows):
        out = ["## {}\n".format(title),
               "> 引用标记：{}\n".format(citability),
               "| 组 | 场景 | 枢纽 | 需求 | 推荐 | 推荐分 | 需增购 | 盲搜可行率 | "
               "随机最优 | 随机P90 | 胜P90 | 延误改善(min) |",
               "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            capex = "—"
            if r["requires_capex"] is not None:
                capex = ("是（+{} 列）".format(r["additional_trains"])
                         if r["requires_capex"] else "否（零增购）")
            out.append("| {group_id} | {scenario} | {hub} | ×{demand_mult} | {recommended_id} | "
                       "{recommended_score} | {capex} | {blind_admissible_rate} | {blind_best} | "
                       "{blind_p90} | {win} | {impr} |".format(
                           capex=capex, win="✓" if r["beats_p90"] else "✗",
                           impr=r["delay_improvement_min"], **r))
        out += ["",
                "**统计**：胜出 **{}/20** · 平均分 {} · 平均延误改善 {} min · "
                "盲搜可行率 {} · 不可行方案 {}（=护栏拦截 {}） · 推荐分布 {}".format(
                    st["recommended_beats_p90_count"], st["recommended_avg_score"],
                    st["avg_delay_improvement_min"], st["blind_admissible_rate"],
                    st["infeasible_plan_count"], st["guardrail_block_count"],
                    "、".join("{}×{}".format(k, v)
                              for k, v in sorted(st["recommended_id_counts"].items()))),
                ""]
        return out

    lines += section(
        "口径甲 · 零增购（fleet_limit=480）",
        "**PPT 可引用（数字如实）**：延误改善、服务底线行为可直接引用；"
        "但「系统胜出盲搜」的表述**不可引用**——盲搜同空间平均略优（见结论 1/2）",
        sn, summary["rows_nocapex"])
    lines += section(
        "口径乙 · 同等增购授权（fleet_limit=600）",
        "**PPT 可引用，但必须带前提**：所有表述须注明「在增购授权至 600 列的前提下」；"
        "不得表述为既有运力下的最优（A1 红线）；「系统胜出盲搜」同样**不可引用**",
        sx, summary["rows_capex"])

    lines += ["## 三、结论\n"]
    lines.append("1. **系统四范式不是参数空间的最优（重要诚实发现）**：盲搜在同空间、同 60 次内"
                 "每组都找到了分数更高的 admissible 组合（甲口径平均高 {} 分，多为 10 分钟档叠加"
                 "二级限流）——Critic 的固定候选池 A/B/C/D 值得扩充「密度+限流」组合档。".format(
                     sn["blind_best_gap_avg"]))
    lines.append("2. **盲搜在既定评分函数下确实更优（更正：不存在「底线盲区」）**：service 维度"
                 "已计入 deferred（experiments.py:63-66），滞留亦按 0.5×headway 折算进 avg_delay"
                 "（sim_adapter.py:228-229）——盲搜的领先是同一评分函数下的真实优势，"
                 "归因是候选集差异而非评分口径；扩池对照见 报告_扩池对照.md。")
    lines.append("3. **系统的确定性价值不靠分数差**：一次生成的推荐即达盲搜 60 次的同一量级"
                 "（差距平均 {} 分），且全程可解释、可审计、带护栏与底线——与 A1 口径"
                 "「83.6 ≈ 60 次盲搜 83.5」的持平论断一致。".format(sn["blind_best_gap_avg"]))
    lines.append("")
    lines.append("分场景胜出（严格大于 P90）：甲 holiday {}/10、weekday {}/10；"
                 "乙 holiday {}/10、weekday {}/10。".format(
                     sn["by_scenario"]["holiday"]["beats_p90_count"],
                     sn["by_scenario"]["weekday"]["beats_p90_count"],
                     sx["by_scenario"]["holiday"]["beats_p90_count"],
                     sx["by_scenario"]["weekday"]["beats_p90_count"]))
    lines.append("")
    lines.append("## 四、为什么盲搜必须固定需求\n")
    lines.append("v1（见 matrix_legacy.json）允许盲搜取 demand_mult=0.8——低于组需求，"
                 "10/10 个节假日组的盲搜最高分全部来自「少运客刷分」，推荐仅胜 4/20。考试改题不是对比。")
    lines.append("")
    lines.append("v2 起盲搜需求固定为组需求；v3 进一步把推荐拆成甲/乙两口径——"
                 "v2 的单列推荐把「零增购最优」与「授权增购最优」混在一张表里，"
                 "同一列在不同组指向不同的车辆资产前提，PPT 引用容易断章取义；"
                 "拆开后口径甲/乙各自前提清晰，引用时带各自的车辆资产前提即可。")
    lines.append("")
    lines.append("## 五、复现命令\n")
    lines.append("```bash")
    lines.append("python3 -m finals.matrix            # 跑/续跑（每完成一组即落盘）")
    lines.append("python3 -m finals.matrix --verify    # 全量计算两遍比对哈希（确定性验证）")
    lines.append("```")
    with open(os.path.join(OUT_DIR, "报告_矩阵.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def cmd_verify() -> int:
    print("[verify] 全量计算第一遍…", flush=True)
    t0 = time.time()
    first, _ = compute_all(verbose=True)
    h1 = groups_hash(first)
    print("[verify] 第一遍哈希 sha256={}".format(h1[:16]))
    print("[verify] 全量计算第二遍…", flush=True)
    second, _ = compute_all(verbose=False)
    h2 = groups_hash(second)
    print("[verify] 第二遍哈希 sha256={}".format(h2[:16]))
    ok = h1 == h2
    print("[verify] 用时 {:.1f}s".format(time.time() - t0))
    print("结论: {}".format("✅ determinism PASS（两遍哈希一致）" if ok else "❌ determinism FAIL"))
    return 0 if ok else 1


# ---------------- Z2e · 扩池对照（穷举格点 vs 系统四范式 vs 盲搜） ----------------
SCORE_DIMS = ("congestion", "service", "cost", "robustness")
TIE_TOLERANCE = 0.5  # 差 ≤0.5 分算持平


def compute_expanded(all_groups: list) -> dict:
    """与盲搜同格点穷举（headway × limit × 组需求，fleet 按口径 480/600），
    三个对象对比：系统四范式最优 / 扩池最优（穷举）/ 盲搜最优（随机 60）。"""
    out_groups = []
    for g in all_groups:
        scenario, hub, demand = g["scenario"], g["hub"], g["demand_mult"]
        base_metrics = g["baseline"]["metrics"]
        tracks = {}
        for key, fleet in (("nocapex", 480), ("capex", 600)):
            grid = []
            for hw in BLIND_HEADWAY:
                for ll in BLIND_LIMIT:
                    cfg = {"scenario": scenario, "headway_min": hw, "formation_cars": 8,
                           "limit_level": ll, "demand_mult": demand,
                           "fleet_limit": fleet, "baseline_flag": False}
                    # 与盲搜同一条 admissible 门槛：过护栏且过服务底线才入池
                    gres = T.t_guardrail_validate(None, param_json=cfg)
                    feasible = bool(gres.get("passed"))
                    m = exp_run(cfg, hub)
                    s = exp_score(m, base_metrics)
                    adm, _ = admissibility_of({"feasible": feasible, "metrics": m},
                                              base_metrics)
                    if adm:
                        grid.append({"config": cfg, "score": s["total"],
                                     "dims": {k: s[k] for k in SCORE_DIMS}})
            expanded_best = max(grid, key=lambda x: x["score"])
            sys_rec = (g["tracks"][key].get("recommended") or {})
            sys_plan = next((p for p in g["plans"] if p["id"] == sys_rec.get("id")), None)
            sys_score = sys_plan["score"]["total"] if sys_plan else None
            sys_dims = ({k: sys_plan["score"][k] for k in SCORE_DIMS} if sys_plan else None)
            blind_best = g["tracks"][key]["blind"].get("best")
            blind_cfg = g["tracks"][key]["blind"].get("best_config")
            blind_dims = None
            if blind_cfg:
                match = [x for x in grid
                         if x["config"]["headway_min"] == blind_cfg.get("headway_min")
                         and x["config"]["limit_level"] == blind_cfg.get("limit_level")]
                blind_dims = match[0]["dims"] if match else None
            gap_to_blind = (round(expanded_best["score"] - blind_best, 2)
                            if blind_best is not None else None)
            gap_to_system = (round(expanded_best["score"] - sys_score, 2)
                             if sys_score is not None else None)
            tracks[key] = {
                "fleet_limit": fleet,
                "system": {"id": sys_rec.get("id"), "score": sys_score, "dims": sys_dims},
                "expanded_best": {"config": expanded_best["config"],
                                  "score": expanded_best["score"],
                                  "dims": expanded_best["dims"]},
                "blind_best": {"score": blind_best, "dims": blind_dims},
                "expanded_vs_blind": {
                    "tie": gap_to_blind is not None and abs(gap_to_blind) <= TIE_TOLERANCE,
                    "gap": gap_to_blind,
                },
                "expanded_vs_system": {"gap": gap_to_system},
            }
        out_groups.append({"group_id": g["group_id"], "scenario": scenario, "hub": hub,
                           "demand_mult": demand, "tracks": tracks})

    def track_stats(groups: list, key: str) -> dict:
        rows = []
        tie = miss = 0
        sys_gaps = []
        dim_gaps = {k: [] for k in SCORE_DIMS}
        by_scenario = {}
        for g in groups:
            t = g["tracks"][key]
            sys_best = t["system"]
            exp_best = t["expanded_best"]
            blind_best = t["blind_best"]
            tie_flag = t["expanded_vs_blind"]["tie"]
            if not tie_flag and (blind_best["score"] or 0) < (exp_best["score"] or 0):
                miss += 1   # 盲搜 60 次未抽到格点最优
            if sys_best.get("score") is not None:
                sys_gaps.append(exp_best["score"] - sys_best["score"])
                for k in SCORE_DIMS:
                    sd = (sys_best.get("dims") or {}).get(k)
                    if sd is not None:
                        dim_gaps[k].append(exp_best["dims"][k] - sd)
            rows.append({
                "group_id": g["group_id"], "scenario": g["scenario"], "hub": g["hub"],
                "demand_mult": g["demand_mult"],
                "system_id": sys_best.get("id"), "system_score": sys_best.get("score"),
                "expanded_score": exp_best["score"],
                "expanded_headway": exp_best["config"]["headway_min"],
                "expanded_limit": exp_best["config"]["limit_level"],
                "blind_score": blind_best.get("score"),
                "tie": tie_flag,
                "expanded_vs_system_gap": t["expanded_vs_system"]["gap"],
            })
        n = len(rows)
        by_scen = {}
        for scen in SCENARIOS:
            srows = [r for r in rows if r["scenario"] == scen]
            by_scen[scen] = {"tie_count": sum(1 for r in srows if r["tie"]),
                             "total": len(srows)}
        return {
            "rows": rows,
            "stats": {
                "tie_count": sum(1 for r in rows if r["tie"]),
                "blind_miss_count": miss,
                "still_behind_count": 0,   # 穷举格点 ⊇ 随机采样，构造性为 0
                "system_gap_avg": (round(sum(sys_gaps) / len(sys_gaps), 2)
                                   if sys_gaps else None),
                "dim_gaps_avg": {k: (round(sum(v) / len(v), 2) if v else None)
                                 for k, v in dim_gaps.items()},
                "by_scenario": by_scen,
            },
        }

    stats_nocapex = track_stats(out_groups, "nocapex")
    stats_capex = track_stats(out_groups, "capex")
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "spec_version": SPEC_VERSION,
        "note": "扩池对照：与盲搜同格点穷举（headway {} × limit {} × 组需求，fleet 按口径），"
                "三对象对比（系统四范式最优 / 扩池最优 / 盲搜最优），评分同一 score_plan。".format(
                    list(BLIND_HEADWAY), list(BLIND_LIMIT)),
        "groups": out_groups,
        "stats_nocapex": stats_nocapex["stats"],
        "rows_nocapex": stats_nocapex["rows"],
        "stats_capex": stats_capex["stats"],
        "rows_capex": stats_capex["rows"],
    }


def write_expanded_report(expanded: dict) -> None:
    sn = expanded["stats_nocapex"]
    sx = expanded["stats_capex"]

    def dim_line(gaps):
        return "拥堵 {:+} · 服务 {:+} · 成本 {:+} · 稳健 {:+}".format(
            gaps["congestion"], gaps["service"], gaps["cost"], gaps["robustness"])

    lines = ["# Z2e · 扩池对照报告（系统四范式 vs 穷举格点 vs 盲搜）\n"]
    lines.append("> {}".format(expanded["note"]))
    lines.append("> 评分口径：experiments.score_plan（默认权重 40/30/20/10，稳健性固定 60，"
                 "与消融同口径）；格点 = headway {} × limit {} × 组需求，fleet 按口径；"
                 "持平判定：差 ≤ {} 分。\n".format(
                     list(BLIND_HEADWAY), list(BLIND_LIMIT), TIE_TOLERANCE))
    for title, st, rows, premise in (
            ("口径甲 · 零增购（fleet 480）",
             sn, expanded["rows_nocapex"], "全部对象均在既有 480 列内"),
            ("口径乙 · 增购授权（fleet 600）",
             sx, expanded["rows_capex"], "全部对象在增购授权至 600 列的前提下")):
        lines.append("## {}\n".format(title))
        lines.append("> 前提：{}。三个对象使用同一评分函数与同一格点。\n".format(premise))
        lines.append("| 组 | 场景 | 枢纽 | 需求 | 系统最优 | 系统分 | 扩池最优（配置） | 扩池分 | "
                     "盲搜最优 | 扩池vs盲搜 | 扩池vs系统差 |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in rows:
            lines.append("| {group_id} | {scenario} | {hub} | ×{demand_mult} | {system_id} | "
                         "{system_score} | {expanded_headway}min+L{expanded_limit} | "
                         "{expanded_score} | {blind_score} | {tie_txt} | {expanded_vs_system_gap:+} |".format(
                             tie_txt="持平" if r["tie"] else "盲搜低{:.2f}".format(
                                 r["expanded_score"] - (r["blind_score"] or 0)), **r))
        lines += ["", "**统计**：扩池与盲搜持平 **{}/{}** 组（差 ≤{} 分）· 盲搜 60 次未采到格点最优 "
                  "**{}** 组 · 扩池仍落后盲搜 **{}** 组（穷举 ⊇ 随机采样，构造性为 0）· "
                  "系统落后扩池平均 **{:+} 分** · 维度差异（扩池 − 系统，均值）：{}。\n".format(
                      st["tie_count"], len(rows), TIE_TOLERANCE, st["blind_miss_count"],
                      st["still_behind_count"], st["system_gap_avg"],
                      dim_line(st["dim_gaps_avg"]))]
    lines.append("## 结论\n")
    lines.append("1. **差距来自候选池规模，不是评分方法**：扩池（穷举同格点）后与盲搜持平"
                 "甲 {}/{}、乙 {}/{} 组，仍落后 0 组——三个对象共用同一 score_plan，方法无差；"
                 "系统四范式（4 个候选）输给格点（{} 个候选/口径）的地方，"
                 "全部能用「池里没有那个组合」解释。".format(
                     sn["tie_count"], len(expanded["rows_nocapex"]),
                     sx["tie_count"], len(expanded["rows_capex"]),
                     len(BLIND_HEADWAY) * len(BLIND_LIMIT)))
    lines.append("2. **扩池最优长这样（维度差异，扩池 − 系统四范式，均值）**："
                 "甲：{}；乙：{}。稳健性在实验口径下固定 60，差异为 0 属预期。".format(
                     dim_line(sn["dim_gaps_avg"]), dim_line(sx["dim_gaps_avg"])))
    lines.append("3. **对系统的可执行改进**：把「密度+限流」组合档（如 10min+二级限流）加入 Critic "
                 "候选池，即可在不改评分方法的前提下收回差距——这是候选生成器的工作，不是评分器的工作。")
    lines.append("")
    lines.append("复现：python3 -m finals.matrix（先出 20 组）→ python3 -m finals.matrix --expanded")
    with open(os.path.join(OUT_DIR, "报告_扩池对照.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def cmd_expanded() -> int:
    all_groups = []
    for scenario in SCENARIOS:
        data = load_existing(scenario)
        all_groups.extend(data.get("groups") or [])
    if len(all_groups) < 20:
        print("错误：矩阵未完成（{}/20），先运行 python3 -m finals.matrix".format(len(all_groups)))
        return 1
    expanded = compute_expanded(all_groups)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "matrix_expanded.json"), "w", encoding="utf-8") as f:
        json.dump(expanded, f, ensure_ascii=False, indent=1)
    write_expanded_report(expanded)
    # matrix_summary.json 只新增 expanded 段，不改既有字段
    summary_path = os.path.join(OUT_DIR, "matrix_summary.json")
    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)
    summary["expanded"] = {
        "generated_at": expanded["generated_at"],
        "stats_nocapex": expanded["stats_nocapex"],
        "stats_capex": expanded["stats_capex"],
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("扩池对照完成：甲 持平 {}/{} · 乙 持平 {}/{} · 系统落后扩池平均 甲 {:+} / 乙 {:+} 分".format(
        expanded["stats_nocapex"]["tie_count"], len(expanded["rows_nocapex"]),
        expanded["stats_capex"]["tie_count"], len(expanded["rows_capex"]),
        expanded["stats_nocapex"]["system_gap_avg"],
        expanded["stats_capex"]["system_gap_avg"]))
    print("产物：matrix_expanded.json · 报告_扩池对照.md · matrix_summary.json(+expanded)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Z2 · 20 组评测矩阵")
    ap.add_argument("--verify", action="store_true", help="两遍全量计算比对哈希（不写盘）")
    ap.add_argument("--expanded", action="store_true",
                    help="扩池对照：穷举格点 vs 系统四范式 vs 盲搜（需先完成矩阵）")
    a = ap.parse_args()
    if a.verify:
        return cmd_verify()
    if a.expanded:
        return cmd_expanded()
    return run_matrix()


if __name__ == "__main__":
    sys.exit(main())
