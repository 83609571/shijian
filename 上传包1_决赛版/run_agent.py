#!/usr/bin/env python3
"""赣鄱智轨 · L3 智能体层 命令行入口

用法：
    # 离线确定性模式（无 API Key 也能完整跑通，默认）
    python3 run_agent.py --scenario holiday --hub 南昌站

    # 接入 DS4.1-Flash（OpenAI 兼容）
    export DS41_API_KEY=sk-xxx
    export DS41_MODEL=<控制台确认的模型 id>
    python3 run_agent.py --provider deepseek

    # 接入 GLM5.2
    export GLM_API_KEY=xxx
    export GLM_MODEL=<控制台确认的模型 id>
    python3 run_agent.py --provider glm

产物：
    data/agent_decision.json   前端智能体面板直接消费（唯一真源）
    output/trace/*.json        每次运行的完整工具调用证据链
    output/sim_results/*.json  每次仿真的完整结果
    output/治理方案报告.md      L5 交付层 Markdown 报告
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from agent import agent_loop as AL          # noqa: E402
from agent import data_layer as dl          # noqa: E402
from agent import llm_client as LC          # noqa: E402
from agent import schemas as S              # noqa: E402
from agent import sim_adapter as sa         # noqa: E402
from agent import tools as T                # noqa: E402
from agent.trace import TraceRecorder       # noqa: E402

DEFAULT_QUERY = ("南昌站节假日大客流，换乘通道与站台拥堵，请开展仿真推演，"
                 "给出可执行的分级治理方案，并说明各方案的代价。")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="赣鄱智轨 L3 智能体层")
    ap.add_argument("--scenario", default="holiday", choices=["holiday", "weekday"])
    ap.add_argument("--hub", default="南昌站")
    ap.add_argument("--provider", default=None,
                    help="auto / deepseek / glm / openai / local")
    ap.add_argument("--query", default=DEFAULT_QUERY)
    ap.add_argument("--out", default=os.path.join(HERE, "output"))
    ap.add_argument("--decision-out", default=os.path.join(HERE, "data", "agent_decision.json"),
                    help="前端消费的决策文档输出路径")
    ap.add_argument("--max-rounds", type=int, default=12)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    print("=" * 78)
    print("赣鄱智轨 · L3 智能体层（Planner-Executor-Critic）")
    print("=" * 78)

    # 0. 数据契约自检（先跑通数据，再上模型）
    print("\n[0] L1 数据契约自检")
    for sc in ("weekday", "holiday"):
        s = dl.network_summary(sc)
        a_ = dl.anchors(sc)
        print(f"    {sc:<8} 站点 {s['station_count']} · 区间 {s['segment_count']} · "
              f"日客流 {s['daily_total_wan']} 万 · 公开锚点 {a_['public_anchor_count']} 条")

    # 1. 引擎状态
    print("\n[1] L2 仿真引擎状态")
    es = sa.engine_status()
    print(f"    引擎A TranStar: available={es['engine_a']['available']}"
          f"  ({es['engine_a'].get('reason', 'ok')})")
    print(f"    引擎B 自研三层饱和度假真: {es['engine_b']['label']}（{es['engine_b']['deps']}）")
    print(f"    当前生效引擎: {es['active']}")

    # 2. Planner
    planner, engine_meta = LC.build_planner(a.scenario, a.hub, a.provider)
    print("\n[2] L3 Planner")
    if engine_meta["mode"] == "llm":
        print(f"    模式: LLM · provider={engine_meta['provider']} · model={engine_meta['model']}")
    else:
        forced = (a.provider or "").strip().lower() == "local"
        reason = "已通过 --provider local 强制离线" if forced else "未检测到 API Key"
        print(f"    模式: 离线确定性规划器（{reason}）")
        print(f"    说明: {engine_meta['note']}")
        if not forced:
            print(f"    提示: 设置 DS41_API_KEY / GLM_API_KEY 后加 --provider 即可切换到真实大模型，")
            print(f"          主循环与工具集无需任何改动。")

    # 3. 主循环
    ctx = T.ToolContext(a.out, a.scenario, a.hub)
    ts = S.now_iso().replace(":", "").replace("-", "")[:15]
    # ★ trace 文件名必须唯一且自证来源 ★
    #   原实现只精确到秒，同一秒内跑两次（如本地模式与 LLM 模式对照跑）
    #   后一次会**静默覆盖**前一次的完整证据链 —— 实测已复现。
    #   这里把 provider 写进文件名，并在冲突时顺延序号。
    base = f"{ts}_{a.scenario}_{engine_meta.get('provider', 'na')}"
    trace_path = os.path.join(ctx.trace_dir, f"{base}_trace.json")
    _k = 1
    while os.path.exists(trace_path):
        _k += 1
        trace_path = os.path.join(ctx.trace_dir, f"{base}_{_k}_trace.json")
    trace = TraceRecorder(trace_path,
                          meta={"scenario": a.scenario, "hub": a.hub,
                                "query": a.query, "engine": engine_meta,
                                "tools_registered": T.TOOL_NAMES})
    loop = AL.AgentLoop(ctx, planner, trace, scenario=a.scenario, hub=a.hub,
                        max_rounds=a.max_rounds, verbose=not a.quiet)
    print("\n[3] Planner-Executor-Critic 主循环")
    doc, trace = loop.run(a.query)

    # 4. 落盘
    os.makedirs(os.path.dirname(a.decision_out), exist_ok=True)
    with open(a.decision_out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    tp = trace.write()

    # 5. 汇总
    print("\n[4] 运行结果")
    b = (doc.get("baseline") or {}).get("metrics") or {}
    rec = next((p for p in doc["plans"] if p["id"] == doc.get("recommended")), None)
    print(f"    基准: 最大饱和度 {b.get('max_saturation')} · 平均延误 {b.get('avg_delay_min')} min"
          f" · 最大积压 {b.get('max_queue_persons')} 人")
    print("    候选方案对比:")
    for p in doc["plans"]:
        m = p.get("metrics") or {}
        sc = p.get("score") or {}
        flag = "★推荐" if p["id"] == doc.get("recommended") else "     "
        print(f"      {flag} {p['id']} {p.get('name', ''):<28} "
              f"sat={m.get('max_saturation')} delay={m.get('avg_delay_min')} "
              f"unmet={m.get('unmet_persons_per_hour')} 总分={sc.get('total')}")
    if rec:
        print(f"    推荐: 方案 {rec['id']}（总分 {(rec.get('score') or {}).get('total')}）")
    t = doc["trace"]
    print(f"\n    trace: {t['path']} · {t['steps']} 步 · 工具调用 {t['tool_calls']} 次 · "
          f"失败 {t['failed_calls']} 次")
    print(f"    已用工具: {', '.join(t['tools_used'])}")
    print(f"    决策文档: {a.decision_out}")
    print(f"    治理报告: {ctx.out_dir}/治理方案报告.md")
    print("\n" + "=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
