"""L5 交付层 · Markdown 治理报告生成器

报告不是把 JSON 打印一遍，而是回答四个评委必问的问题：
  ① 问题是什么（量化）、② 你试了哪些方案（可复现）、③ 为什么选这个（多目标权衡）、
  ④ 这个结论有多稳（敏感性）、⑤ 怎么复现（trace 与命令）。
"""
from __future__ import annotations

import os

METRIC_LABEL = [
    ("max_saturation", "站台最大饱和度", "—", 3),
    ("hub_saturation", "枢纽饱和度", "—", 3),
    ("avg_delay_min", "平均延误", "min", 2),
    ("max_queue_persons", "最大积压", "人", 0),
    ("unmet_persons_per_hour", "断面未承运", "人/h", 0),
    ("deferred_persons_per_hour", "限流站外滞留", "人/h", 0),
    ("throughput_persons_per_hour", "承运吞吐", "人/h", 0),
    ("required_trains", "所需配车", "列", 0),
    ("energy_kwh_per_day", "牵引能耗", "kWh/日", 0),
]


def _fmt(v, nd=2):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.{nd}f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    out = ["| " + " | ".join(rows[0]) + " |",
           "|" + "|".join(["---"] * len(rows[0])) + "|"]
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def build_markdown(*, baseline: dict, plans: list[dict], recommended: str,
                   narration: str, ctx) -> str:
    bm = (baseline or {}).get("metrics", {}) or {}
    L = []
    L.append("# 赣鄱智轨 · 枢纽拥堵治理方案报告")
    L.append("")
    L.append("> 本报告由 L3 智能体层自动生成：Planner 拆解问题 → 调用仿真工具 → "
             "Critic 评估指标 → 多目标排序。全部工具调用入参、出参与时间戳见 trace 日志。")
    L.append("")

    L.append("## 一、问题界定")
    L.append("")
    L.append(f"- 场景：`{ctx.scenario}`（holiday=节假日 / weekday=工作日）")
    L.append(f"- 关注枢纽：**{ctx.hub}**")
    L.append(f"- 基准状态（未治理）：{_fmt(bm.get('max_saturation'), 3)}")
    b_bottleneck = (baseline or {}).get("top_bottlenecks", [])
    if b_bottleneck:
        L.append("")
        L.append("基准场景瓶颈清单（按饱和度降序）：")
        L.append("")
        L.append(_table([["站点", "类型", "饱和度", "瓶颈环节", "积压(人)"]] + [
            [b["name"], "通勤" if b["type"] == "commuter" else "旅游",
             f"**{b['saturation']:.3f}**",
             "站台容量" if b["binding"] == "platform" else "换乘通道",
             f"{b['queue_persons']:,}"] for b in b_bottleneck]))
    L.append("")

    L.append("## 二、基准 vs 候选方案指标对比")
    L.append("")
    head = ["指标"] + ["基准"] + [f"{p['id']} {p.get('name', '')}" for p in plans]
    rows = [head]
    for key, label, unit, nd in METRIC_LABEL:
        def val(src):
            v = (src or {}).get(key)
            if key == "energy_kwh_per_day" and isinstance(v, (int, float)):
                return _fmt(v / 1000.0, 1)     # kWh → MWh，避免七位数读数
            return _fmt(v, nd)
        rows.append([f"{label}（{'MWh/日' if key == 'energy_kwh_per_day' else unit}）"
                     if unit != "—" else label,
                     val(bm)] + [val(p.get("metrics")) for p in plans])
    rows.append(["护栏校验"] + ["基准不适用"] +
                [("通过" if (p.get("guardrail") or {}).get("passed") else
                  "**拦截** " + ",".join(v["id"] for v in
                                         (p.get("guardrail") or {}).get("violations", [])))
                 for p in plans])
    L.append(_table(rows))
    L.append("")
    # 被护栏修正过的方案必须显式披露「请求参数 vs 实际执行参数」
    fixed = [p for p in plans
             if ((p.get("guardrail") or {}).get("gate") or {}).get("applied")]
    if fixed:
        L.append("### 护栏闸门记录（请求参数 ≠ 实际执行参数，必须披露）")
        L.append("")

        def _cfgline(d):
            """把四项运营参数压成一行；缺项如实写「未提供」而不是崩掉。"""
            d = d or {}
            def g(k, suf, nd=1):
                v = d.get(k)
                return "未提供" if v is None else f"{v:g}{suf}" if suf == "'" else f"{v}{suf}"
            return ("间隔 %s / 编组 %s / 限流 %s 级 / 客流 ×%s" % (
                g("headway_min", "'"), g("formation_cars", " 辆"),
                d.get("limit_level", "—"), d.get("demand_mult", "—")))

        L.append(_table([["方案", "护栏判定", "请求参数（Planner 原值）",
                          "实际执行参数（修正后）", "修正依据"]]
                        + [[f"{p['id']}",
                            "、".join(f"{v['id']} {v['name']}"
                                     for v in p["guardrail"]["gate"]["applied"]["violations"]),
                            _cfgline(p["guardrail"]["gate"]["applied"].get("requested")),
                            _cfgline(p["guardrail"]["gate"]["applied"].get("repaired_to")),
                            (p["guardrail"]["gate"]["applied"]["violations"] or [{}])[0].get("fix", "—")]
                           for p in fixed]))
        L.append("")
        # 若存在「被规范化静默钳制」的字段，单独披露 —— 钳制不等于违规，但同样要留痕
        soft = [(p["id"], s) for p in fixed
                for s in (p["guardrail"]["gate"]["applied"].get("soft_clamped") or [])]
        if soft:
            L.append("> 另有字段在进入护栏前已被参数域规范化钳制（非违规拦截，一并留痕）："
                     + "；".join(f"方案 {pid} `{s['field']}` {s.get('from')} → {s.get('to')}"
                                 f"（{s.get('rule')}）" for pid, s in soft))
            L.append("")
        L.append("> 说明：被拦截的方案**不是**直接丢弃，而是由护栏给出修正路径后执行 —— "
                 "trace 中同时保留了原始请求参数、规范化钳制值与修正后的执行参数，三者都可复现。")
        L.append("")

    if any(p.get("score") for p in plans):
        L.append("### 多目标打分（0–100；权重：拥堵缓解 0.4 / 服务水平 0.3 / 资源代价 0.2 / 稳健性 0.1）")
        L.append("")
        L.append("> 拥堵缓解以「站台饱和度 ≤ 0.85」为达标线、0.30 为满分基准；"
                 "服务水平把**断面未承运 + 限流站外滞留**一并计入 —— 限流不是免费的；"
                 "资源代价把**牵引能耗与配车需求**一并计入 —— 增购车辆同样不是免费的。")
        L.append("")
        L.append(_table([["方案", "拥堵缓解", "服务水平", "资源代价", "稳健性", "**加权总分**", "结论"]] + [
            [f"{p['id']} {p.get('name', '')}",
             _fmt((p.get("score") or {}).get("congestion"), 1),
             _fmt((p.get("score") or {}).get("service"), 1),
             _fmt((p.get("score") or {}).get("cost"), 1),
             _fmt((p.get("score") or {}).get("robustness"), 1),
             f"**{_fmt((p.get('score') or {}).get('total'), 1)}**",
             "**推荐**" if p["id"] == recommended else ""] for p in plans]))
        L.append("")

    L.append("## 三、方案解释")
    L.append("")
    for p in plans:
        g = p.get("guardrail") or {}
        L.append(f"### 方案 {p['id']} · {p.get('name', '')}")
        L.append("")
        L.append(f"- **治理思路**：{p.get('rationale', '—')}")
        c = p.get("config") or {}
        ec = p.get("effective_config") or {}
        L.append(f"- **执行参数**：发车间隔 {c.get('headway_min')} min · "
                 f"编组 {c.get('formation_cars')} 辆 · 限流 {c.get('limit_level')} 级 · "
                 f"需求乘子 {c.get('demand_mult')}")
        if ec and (abs(float(ec.get("headway_min", 0)) - float(c.get("headway_min", 0))) > 1e-6
                   or int(ec.get("limit_level", 0)) != int(c.get("limit_level", 0))):
            L.append(f"- **护栏修正后实际执行**：发车间隔 {ec.get('headway_min')} min · "
                     f"编组 {ec.get('formation_cars')} 辆 · 限流 {ec.get('limit_level')} 级")
        L.append(f"- **护栏校验**：{'通过（9 条规则全部满足）' if g.get('passed') else '拦截 → 已按修正路径执行'}")
        if not g.get("passed"):
            for v in g.get("violations", []):
                L.append(f"  - `{v['id']} {v['name']}` — {v['why']} 修正：{v['fix']}")
        if g.get("normalized"):
            L.append("- **参数规范化记录**：")
            for n in g["normalized"]:
                L.append(f"  - `{n['field']}`：{n['from']} → {n['to']}（依据 {n['rule']}）")
        d = p.get("delta") or {}
        if d:
            L.append("- **相对基准变化**：" + "；".join(
                f"{k} {v}" for k, v in d.items()))
        L.append("")

    L.append("## 四、敏感性分析")
    L.append("")
    L.append("对**每个候选方案**分别做 6 组确定性扰动重仿真（客流 ±20%、发车间隔 ±2min 及其组合），"
             "避免「只验证推荐方案」带来的评分偏差。")
    L.append("")
    rows = [["方案", "饱和度区间（确定性扰动域）", "最不利饱和度", "稳健性判定"]]
    for p in plans:
        s = p.get("sensitivity")
        if not s:
            rows.append([f"{p['id']}", "未扫描", "—", "—"])
            continue
        lo, hi = s.get("max_saturation_range", [None, None])
        rows.append([f"{p['id']} {p.get('name', '')}",
                     f"[{_fmt(lo, 3)}, {_fmt(hi, 3)}]",
                     f"**{_fmt(hi, 3)}**",
                     "稳健" if s.get("robust") else "不利扰动下超饱和"])
    L.append(_table(rows))
    L.append("")
    rec_plan = next((p for p in plans if p["id"] == recommended), plans[0] if plans else None)
    if rec_plan and rec_plan.get("sensitivity"):
        L.append(f"**推荐方案 {rec_plan['id']} 的扰动明细**：")
        L.append("")
        L.append(_table([["扰动情形", "发车间隔", "需求乘子", "最大饱和度", "平均延误", "未承运(人/h)"]] + [
            [c["case"], f"{c['headway_min']}", f"{c['demand_mult']}",
             _fmt(c["max_saturation"], 3), _fmt(c["avg_delay_min"]), f"{c['unmet_persons_per_hour']:,}"]
            for c in rec_plan["sensitivity"].get("cases", [])]))
        L.append("")
        L.append(f"**稳健性结论**：{rec_plan['sensitivity'].get('verdict', '—')}")
    L.append("")

    L.append("## 五、智能体推理说明")
    L.append("")
    L.append(narration or "—")
    L.append("")

    L.append("## 六、复现方式")
    L.append("")
    L.append("```bash")
    L.append("# 1. 生成决策文档、trace 与报告")
    L.append("python3 run_agent.py --scenario holiday --hub 南昌站")
    L.append("# 2. 前端读取 web/data/agent_decision.json 渲染智能体面板")
    L.append("python3 -m http.server 8000   # 然后访问 index.html")
    L.append("```")
    L.append("")
    L.append(f"- trace 目录：`{os.path.relpath(ctx.trace_dir, ctx.out_dir)}/`")
    L.append(f"- 仿真结果目录：`{os.path.relpath(ctx.sim_dir, ctx.out_dir)}/`")
    L.append("")
    return "\n".join(L)
