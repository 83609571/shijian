#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""I8 · 前后端一致性自检（CLI / HTTP /api/simulate / HTTP /api/score 三源比对）

用法：
    python3 -m finals.consistency            # 全量 20 组 + 冻结真源比对
    python3 -m finals.consistency --quick    # 仅南昌站节假日一组（现场 5 秒自证）

比对内容：
  1) 20 组（2 场景 × 5 枢纽 × 2 需求）逐组：
     - CLI experiments.run() vs HTTP /api/simulate：5 个 metrics 字段 + 3 个维度分
       （congestion/service/cost；robustness 两接口口径不同——实验口径 60、
        智能体口径动态——按交付单不比对）
     - 需求 1.0 的组另比对 HTTP /api/score 的 A 方案 metrics + 维度分
       （/api/score 不含需求参数，其方案天然在 1.0 口径）
  2) 冻结真源：data/agent_decision.json 的 D 方案 metrics vs /api/run 返回的 D 方案
- 容差：相对偏差 ≤ 0.5%；任一 FAIL 退出码非 0。
- 产物：output/experiments/consistency/consistency.json + 报告_一致性.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from experiments import run as exp_run            # noqa: E402
from experiments import score_plan as exp_score   # noqa: E402
from finals.matrix import build_groups            # noqa: E402  组定义复用（2×5×2）

OUT_DIR = os.path.join(HERE, "output", "experiments", "consistency")
TOLERANCE = 0.005   # 相对偏差 0.5%
METRIC_FIELDS = ("max_saturation", "avg_delay_min", "unmet_persons_per_hour",
                 "deferred_persons_per_hour", "required_trains")
DIM_FIELDS = ("congestion", "service", "cost")
DEFAULT_WEIGHTS = {"congestion": 40, "service": 30, "cost": 20, "robustness": 10}


def _safe_json(body: bytes) -> dict:
    try:
        return json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return {"raw": body.decode("utf-8", errors="replace")[:200]}


def post(base: str, path: str, payload: dict):
    req = urllib.request.Request(base + path, method="POST",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, _safe_json(r.read())
    except urllib.error.HTTPError as e:
        return e.code, _safe_json(e.read())


def rel_gap(a, b) -> float:
    try:
        a = float(a)
        b = float(b)
    except (TypeError, ValueError):
        return 100.0
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom * 100.0


def compare_fields(rows: list, tag: str, left: dict, right: dict, fields: list,
                   gmeta: dict) -> int:
    fails = 0
    for f in fields:
        lv, rv = left.get(f), right.get(f)
        gap = rel_gap(lv, rv)
        ok = gap <= TOLERANCE * 100
        fails += 0 if ok else 1
        rows.append({
            "source_pair": tag, "field": f, "left": lv, "right": rv,
            "rel_gap_pct": round(gap, 4), "pass": ok, **gmeta,
        })
    return fails


def run_checks(base: str, quick: bool) -> tuple:
    with open(os.path.join(HERE, "data", "agent_decision.json"), encoding="utf-8") as f:
        frozen = json.load(f)
    base_cfg = {k: v for k, v in frozen["baseline"]["config"].items()}
    plan_cfgs = {p["id"]: {k: v for k, v in p["config"].items()} for p in frozen["plans"]}
    frozen_d_metrics = frozen["plans"][3]["metrics"]   # 方案 D（冻结真源）

    groups, _ = build_groups()
    if quick:
        groups = [(1, "holiday", "南昌站", 1.0)]

    rows = []
    group_summary = []
    t0 = time.perf_counter()
    # 维度分参照基准：基准=同需求现状，与 /api/simulate 对齐
    #（12min / 8 编组 / 不限流，demand 跟随组需求）
    base_cache = {}
    for gid, scenario, hub, demand in groups:
        gmeta = {"group_id": gid, "scenario": scenario, "hub": hub,
                 "demand_mult": demand}
        bkey = (scenario, hub, demand)
        if bkey not in base_cache:
            base_cache[bkey] = exp_run({**base_cfg, "scenario": scenario,
                                        "demand_mult": demand}, hub)
        base_metrics = base_cache[bkey]
        # 三方共同的对照配置：A 方案参数（无 fleet 字段，两接口同口径）
        cli_cfg = {"scenario": scenario, "headway_min": 10.0, "formation_cars": 8,
                   "limit_level": 0, "demand_mult": demand}
        cli_metrics = exp_run(cli_cfg, hub)
        cli_dims = exp_score(cli_metrics, base_metrics)

        gfails = 0
        # 1) CLI vs /api/simulate
        st, sim = post(base, "/api/simulate",
                       {"scenario": scenario, "hub": hub, "headway": 10.0,
                        "formation_cars": 8, "limit_level": 0, "demand_mult": demand})
        sim_metrics = (sim.get("plan") or {}).get("metrics") or {}
        sim_dims = ((sim.get("plan") or {}).get("score") or {})
        gfails += compare_fields(rows, "cli_vs_simulate", cli_metrics, sim_metrics,
                                 METRIC_FIELDS, gmeta)
        gfails += compare_fields(rows, "cli_vs_simulate", cli_dims, sim_dims,
                                 DIM_FIELDS, gmeta)
        # 2) 需求 1.0 组：CLI vs /api/score（A 方案）
        score_plan_a = None
        if demand == 1.0:
            st2, score = post(base, "/api/score",
                              {"weights": DEFAULT_WEIGHTS, "scenario": scenario,
                               "hub": hub})
            for p in (score.get("plans") or []):
                if p.get("id") == "A":
                    score_plan_a = p
                    break
            if score_plan_a:
                gfails += compare_fields(rows, "cli_vs_score",
                                         cli_metrics, score_plan_a.get("metrics") or {},
                                         METRIC_FIELDS, gmeta)
                gfails += compare_fields(rows, "cli_vs_score",
                                         cli_dims, score_plan_a.get("dims") or {},
                                         DIM_FIELDS, gmeta)
        group_summary.append({
            **gmeta, "fail_fields": gfails,
            "checked_fields": len(METRIC_FIELDS) + len(DIM_FIELDS) +
                              (len(METRIC_FIELDS) + len(DIM_FIELDS) if demand == 1.0 else 0),
        })

    # 3) 冻结真源 D 方案 vs /api/run（一次）
    st3, run_resp = post(base, "/api/run",
                         {"scenario": "holiday", "hub": "南昌站", "provider": "local"})
    run_d = None
    for p in ((run_resp.get("doc") or {}).get("plans") or []):
        if p.get("id") == "D":
            run_d = p.get("metrics") or {}
            break
    gmeta = {"group_id": "-", "scenario": "holiday", "hub": "南昌站", "demand_mult": 1.0}
    nf = compare_fields(rows, "frozen_vs_run", frozen_d_metrics, run_d,
                        METRIC_FIELDS, gmeta)
    group_summary.append({**gmeta, "fail_fields": nf,
                          "checked_fields": len(METRIC_FIELDS),
                          "note": "冻结真源 D 方案 vs /api/run"})

    return rows, group_summary, time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser(description="I8 · 前后端一致性自检")
    ap.add_argument("--quick", action="store_true", help="仅南昌站节假日一组（现场 5 秒自证）")
    a = ap.parse_args()

    from api_server import Handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:{}".format(srv.server_address[1])

    rows, group_summary, elapsed = run_checks(base, a.quick)
    srv.shutdown()

    total = len(rows)
    passed = sum(1 for r in rows if r["pass"])
    fails = [r for r in rows if not r["pass"]]
    top_gaps = sorted(rows, key=lambda r: r["rel_gap_pct"], reverse=True)[:3]
    # 运行历史：报告头部同时呈现 全量 / 现场 quick 两条（各自保留最近一次）
    hist_path = os.path.join(OUT_DIR, "consistency.json")
    history = {"full": None, "quick": None}
    if os.path.exists(hist_path):
        try:
            with open(hist_path, encoding="utf-8") as f:
                prev = json.load(f)
            ph = prev.get("history") or {}
            history["full"] = ph.get("full")
            history["quick"] = ph.get("quick")
        except Exception:
            pass
    mode_key = "quick" if a.quick else "full"
    history[mode_key] = {"pass_count": passed, "total_count": total,
                         "elapsed_s": round(elapsed, 2),
                         "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tolerance_pct": TOLERANCE * 100,
        "quick": a.quick,
        "elapsed_s": round(elapsed, 2),
        "pass_count": passed,
        "total_count": total,
        "fail_count": len(fails),
        "top_gaps": top_gaps,
        "history": history,
        "group_summary": group_summary,
        "rows": rows,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "consistency.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    lines = ["# I8 · 前后端一致性自检报告\n",
             "> 容差：相对偏差 ≤ {}% · 用时 {}s · 模式：{}\n".format(
                 TOLERANCE * 100, result["elapsed_s"],
                 "quick（南昌站节假日一组）" if a.quick else "全量 20 组 + 冻结真源"),
             "> 汇总：{} \n".format(" / ".join(
                 "{} {}/{} · {}s".format(
                     ("全量" if k == "full" else "现场 quick"),
                     history[k]["pass_count"], history[k]["total_count"],
                     history[k]["elapsed_s"])
                 for k in ("full", "quick") if history.get(k))),
             "## 一、总览\n",
             "- 比对字段：**{}/{} PASS**（FAIL {}）".format(passed, total, len(fails)),
             "- 比对源：CLI experiments.run() ↔ HTTP /api/simulate ↔ HTTP /api/score；"
             "另比对冻结真源 D 方案 ↔ /api/run",
             "- 基准口径：基准=同需求现状（12min/8 编组/不限流，demand 跟随组需求），"
             "与 /api/simulate 对齐；/api/score 的 admissibility 基准不动（冻结于 agent_decision.json）",
             "- 维度口径说明：robustness 不比对（实验口径固定 60、智能体口径动态评估，属已知差异）",
             ""]
    if top_gaps:
        lines.append("## 二、差异最大的三个字段\n")
        for r in top_gaps:
            lines.append("- {}（{}）：left={} right={} 相对差 {}%".format(
                r["field"], r["source_pair"], r["left"], r["right"], r["rel_gap_pct"]))
        lines.append("")
    lines.append("## 三、逐组结果\n")
    lines.append("| 组 | 场景 | 枢纽 | 需求 | 比对字段 | FAIL 字段 |")
    lines.append("|---|---|---|---|---|---|")
    for g in group_summary:
        lines.append("| {group_id} | {scenario} | {hub} | ×{demand_mult} | "
                     "{checked_fields} | {fail_fields} |".format(**g))
    lines += ["", "复现：python3 -m finals.consistency（--quick 现场快速自证）"]
    with open(os.path.join(OUT_DIR, "报告_一致性.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("一致性自检：{}/{} 字段 PASS（quick={} · 用时 {}s）".format(
        passed, total, a.quick, result["elapsed_s"]))
    for r in top_gaps:
        print("  最大差异：{}（{}）left={} right={} 相对差 {}%".format(
            r["field"], r["source_pair"], r["left"], r["right"], r["rel_gap_pct"]))
    if fails:
        print("FAIL 明细（前 10）：")
        for r in fails[:10]:
            print("  {} {} {}: left={} right={}".format(
                r["group_id"], r["source_pair"], r["field"], r["left"], r["right"]))
    srv_ok = True
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
