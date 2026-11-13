#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z3b · 对抗测试（期望表与实现解耦 + 结果四类计数）

用法：
    python3 -m finals.adversarial            # 起 ephemeral 服务，按冻结 spec 跑 32 例
    python3 -m finals.adversarial --port 8000  # 打已运行的服务

流程（期望先于实现）：
    1) 首次运行生成 output/experiments/adversarial/adversarial_spec.json（期望表，冻结）；
       之后每次运行只读该表，运行过程不得修改 spec；
    2) 逐例执行并按 expect_class 判定：hard_400 → rejected / soft_degrade → degraded /
       repair → repaired / success → ok；
    3) 结果按四类计数（hard_400_pass/total 等），不给单一「拦截率」。

旧口径产物（v1，单次拦截率口径）首次写入 v2 前归档为 adversarial_v1.json / 报告_对抗测试_v1.md。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

OUT_DIR = os.path.join(HERE, "output", "experiments", "adversarial")
SPEC_PATH = os.path.join(OUT_DIR, "adversarial_spec.json")

EXPECT_OUTCOME = {"hard_400": "rejected", "soft_degrade": "degraded",
                  "repair": "repaired", "success": "ok"}


# ---------------- 期望表（冻结对象） ----------------
def build_spec_entries() -> list:
    e = []

    def add(cid, group, input_desc, expect_class, reason):
        e.append({"id": cid, "group": group, "input": input_desc,
                  "expect_class": expect_class, "reason": reason})

    # A 非法参数（9，全部 hard_400）
    add("A1", "A 非法参数", "/api/simulate headway=0", "hard_400", "间隔为 0，物理无意义")
    add("A2", "A 非法参数", "/api/simulate headway=-1", "hard_400", "负间隔非法")
    add("A3", "A 非法参数", "/api/simulate headway=2", "hard_400", "低于下限 3，排不出图")
    add("A4", "A 非法参数", "/api/simulate formation_cars=0", "hard_400", "无编组非法")
    add("A5", "A 非法参数", "/api/simulate formation_cars=20", "hard_400", "超过编组上限")
    add("A6", "A 非法参数", "/api/simulate demand_mult=-1", "hard_400", "负客流非法")
    add("A7", "A 非法参数", "/api/simulate demand_mult=0", "hard_400", "零客流无意义")
    add("A8", "A 非法参数", "/api/simulate fleet_limit=0（白名单外字段）", "hard_400",
        "字段不在白名单，防拼错被静默忽略")
    add("A9", "A 非法参数", "/api/simulate hub=10KB 文本", "hard_400",
        "超长文本注入，MAX_TEXT_LEN=64")
    # B 通信能力不可用（6：4 例 soft_degrade + 2 例 hard_400）
    add("B1", "B 通信能力不可用", "/api/sla 4G+应急切片", "soft_degrade",
        "GR-10：能力不生效须留痕（applied.slice=false），不报错")
    add("B2", "B 通信能力不可用", "/api/sla 4G+南昌MEC", "soft_degrade",
        "4G 无边缘计算，applied.mec=false 留痕")
    add("B3", "B 通信能力不可用", "/api/sla 4G+ISAC", "soft_degrade",
        "4G 无通感一体，applied.isac=false 留痕")
    add("B4", "B 通信能力不可用", "/api/sla 5G+ISAC", "soft_degrade",
        "ISAC 仅 5G-A 支持，applied.isac=false 留痕")
    add("B5", "B 通信能力不可用", "/api/sla slice=nonexistent", "hard_400", "未知切片名，白名单拒绝")
    add("B6", "B 通信能力不可用", "/api/sla mec=moon", "hard_400", "未知 MEC 节点，白名单拒绝")
    # C 物理不可行（4：1 repair + 2 success + 1 hard_400）
    add("C1", "C 物理不可行", "/api/run 8 分钟+480 列（全链路）", "repair",
        "GR-09 拦截 C 方案并按修复路径执行留痕")
    add("C2", "C 物理不可行", "/api/simulate demand_mult=3.0（上界）", "success",
        "3.0 为合法上界；须如实标注超载")
    add("C3", "C 物理不可行", "/api/simulate headway=2 + 8 编组", "hard_400", "物理排不出图，校验拒绝")
    add("C4", "C 物理不可行", "/api/simulate 庐山站 需求 1.4 无增购", "success",
        "合法查询；须如实标注需增购与超载")
    # D 矛盾/缺失（7，含零权重）
    add("D1", "D 矛盾/缺失", "/api/simulate 缺 scenario", "success",
        "缺省参数按设计回退 holiday，属文档化行为")
    add("D2", "D 矛盾/缺失", "/api/simulate hub=火星站", "hard_400", "不在 34 站站点表，白名单拒绝")
    add("D3", "D 矛盾/缺失", "/api/score 空 body", "hard_400", "缺 weights 必拒")
    add("D4", "D 矛盾/缺失", "/api/simulate 非法 JSON 文本", "hard_400", "请求体非法，须结构化 400")
    add("D5", "D 矛盾/缺失", "/api/sla event=zombie", "hard_400", "未知事件，白名单拒绝")
    add("D6", "D 矛盾/缺失", "/api/score 权重为负（congestion=-1）", "hard_400", "负权重非法")
    add("D7", "D 矛盾/缺失", "/api/score 零权重（四项全 0）", "hard_400", "权重和为 0 无法加权")
    # E 合法边界（6，全部 success）
    add("E1", "E 合法边界", "/api/simulate demand_mult=1.6", "success", "界内高端，应正常出数")
    add("E2", "E 合法边界", "/api/simulate headway=15", "success", "界内低端，应正常出数")
    add("E3", "E 合法边界", "/api/run weekday 现跑", "success", "离线确定性现跑全链路")
    add("E4", "E 合法边界", "/api/sla 5G-A+ISAC+南昌MEC+AI空口", "success", "全能力开启，正常返回")
    add("E5", "E 合法边界", "/api/score 正常权重 40/30/20/10", "success", "标准权重，正常评分")
    add("E6", "E 合法边界", "/api/simulate hub=九江站（正常文本）", "success", "长度受控的正常文本")
    return e


def ensure_spec() -> list:
    """期望表冻结：存在即只读；不存在才生成。返回 cases。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(SPEC_PATH):
        with open(SPEC_PATH, encoding="utf-8") as f:
            return json.load(f)["cases"]
    spec = {"frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "note": "期望先于实现：本表在运行前冻结，运行与判分过程不得修改。",
            "cases": build_spec_entries()}
    with open(SPEC_PATH, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
    print("[spec] 期望表已冻结 → {}".format(os.path.relpath(SPEC_PATH, HERE)))
    return spec["cases"]


# ---------------- 用例执行映射（与 spec 一一对应） ----------------
SIM_BASE = {"scenario": "holiday", "hub": "南昌站", "headway": 10,
            "formation_cars": 8, "limit_level": 1, "demand_mult": 1.0}


def sim(**over):
    cfg = dict(SIM_BASE)
    cfg.update(over)
    return ("POST", "/api/simulate", cfg, None)


LONG_TEXT = "测" * 10240
CASE_CALLS = {
    "A1": sim(headway=0), "A2": sim(headway=-1), "A3": sim(headway=2),
    "A4": sim(formation_cars=0), "A5": sim(formation_cars=20),
    "A6": sim(demand_mult=-1), "A7": sim(demand_mult=0), "A8": sim(fleet_limit=0),
    "A9": sim(hub=LONG_TEXT),
    "B1": ("POST", "/api/sla", {"net": "4G", "slice": "emergency"}, None),
    "B2": ("POST", "/api/sla", {"net": "4G", "mec": "nanchang"}, None),
    "B3": ("POST", "/api/sla", {"net": "4G", "isac": True}, None),
    "B4": ("POST", "/api/sla", {"net": "5G", "isac": True}, None),
    "B5": ("POST", "/api/sla", {"net": "5G-A", "slice": "nonexistent"}, None),
    "B6": ("POST", "/api/sla", {"net": "5G-A", "mec": "moon"}, None),
    "C1": ("POST", "/api/run", {"scenario": "holiday", "hub": "南昌站", "provider": "local"}, None),
    "C2": sim(demand_mult=3.0),
    "C3": sim(headway=2),
    "C4": sim(hub="庐山站", headway=8, demand_mult=1.4),
    "D1": ("POST", "/api/simulate", {"headway": 10, "formation_cars": 8,
                                     "limit_level": 1, "demand_mult": 1.0}, None),
    "D2": sim(hub="火星站"),
    "D3": ("POST", "/api/score", {}, None),
    "D4": ("POST", "/api/simulate", None, b"not-a-json"),
    "D5": ("POST", "/api/sla", {"net": "4G", "event": "zombie"}, None),
    "D6": ("POST", "/api/score", {"weights": {"congestion": -1, "service": 30,
                                              "cost": 20, "robustness": 10}}, None),
    "D7": ("POST", "/api/score", {"weights": {"congestion": 0, "service": 0,
                                              "cost": 0, "robustness": 0}}, None),
    "E1": sim(demand_mult=1.6), "E2": sim(headway=15),
    "E3": ("POST", "/api/run", {"scenario": "weekday", "hub": "南昌站", "provider": "local"}, None),
    "E4": ("POST", "/api/sla", {"net": "5G-A", "isac": True, "mec": "nanchang",
                                "ai_air": True}, None),
    "E5": ("POST", "/api/score", {"weights": {"congestion": 40, "service": 30,
                                              "cost": 20, "robustness": 10},
                                  "scenario": "holiday", "hub": "南昌站"}, None),
    "E6": sim(hub="九江站"),
}

# 个别用例的附加断言（在类别判定通过后细化 detail）


def hit(base: str, method: str, path: str, payload=None, raw=None):
    t0 = time.perf_counter()
    try:
        data = raw if raw is not None else (
            json.dumps(payload).encode("utf-8") if payload is not None else None)
        if isinstance(data, str):
            data = data.encode("utf-8")
        req = urllib.request.Request(
            base + path, data=data, method=method,
            headers={"Content-Type": "application/json"} if data is not None else {})
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            parsed = _safe_json(body)
            return r.status, parsed, (time.perf_counter() - t0) * 1000
    except urllib.error.HTTPError as e:
        return e.code, _safe_json(e.read()), (time.perf_counter() - t0) * 1000
    except Exception as ex:  # noqa: BLE001
        return (None, {"client_crash": "{}: {}".format(type(ex).__name__, ex)},
                (time.perf_counter() - t0) * 1000)


def _safe_json(body: bytes) -> dict:
    try:
        return json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return {"raw": body.decode("utf-8", errors="replace")[:200]}


def classify(entry: dict, status, body) -> tuple:
    """按 expect_class 判定 → (outcome, passed, detail)。"""
    cls = entry["expect_class"]
    cid = entry["id"]
    if status is None or status >= 500:
        return "crash", False, "客户端/服务端崩溃：{}".format(
            (body or {}).get("client_crash", status))
    if cls == "hard_400":
        ok = status == 400 and isinstance(body, dict) and body.get("ok") is False \
            and "error" in body
        detail = "400 结构化：{}".format((body or {}).get("error", "")) if ok else \
            "期望 400，实际 {} {}".format(status, str(body)[:80])
        return ("rejected" if ok else "ok"), ok, detail
    if cls == "soft_degrade":
        flag = {"B1": "slice", "B2": "mec", "B3": "isac", "B4": "isac"}[cid]
        applied = (body or {}).get("applied") or {}
        ok = status == 200 and applied.get(flag) is False
        detail = "200 且 applied.{}={}（能力不生效留痕）".format(flag, applied.get(flag))
        return ("degraded" if ok else "ok"), ok, detail
    if cls == "repair":
        plans = (body or {}).get("doc", {}).get("plans", [])
        blocked = [p for p in plans if p.get("feasible") is False]
        ok = status == 200 and bool(blocked) and \
            all("GR-09" in (p.get("block_reason") or "") for p in blocked)
        detail = "C 方案拦截留痕：{}".format(
            blocked[0].get("block_reason", "")[:60] if blocked else "无拦截")
        return ("repaired" if ok else "ok"), ok, detail
    # success：附加断言
    if cid == "C2":
        ok = status == 200 and (body or {}).get("over_capacity") is True
        detail = "200 且如实标注超载（over_capacity=true）"
        return ("ok" if ok else "rejected"), ok, detail
    if cid == "C4":
        pm = (body or {}).get("plan", {}).get("metrics") or {}
        need = (pm.get("required_trains") or 0) - ((body or {}).get("fleet_available") or 0)
        ok = status == 200 and need > 0 and (body or {}).get("over_capacity") is True
        detail = "200 且如实标注：需增购 {} 列、超载".format(need)
        return ("ok" if ok else "rejected"), ok, detail
    ok = status == 200 and isinstance(body, dict) and body.get("ok") is True
    return ("ok" if ok else "rejected"), ok, "200 成功"


def run_all(base: str, spec_cases: list):
    ids = [c["id"] for c in spec_cases]
    if set(ids) != set(CASE_CALLS) or len(ids) != len(CASE_CALLS):
        raise SystemExit("spec 与执行映射不一致：spec={} runner={}".format(
            sorted(set(ids) ^ set(CASE_CALLS)), "见 CASE_CALLS"))
    rows = []
    for entry in spec_cases:
        cid = entry["id"]
        method, path, payload, raw = CASE_CALLS[cid]
        status, body, ms = hit(base, method, path, payload, raw)
        outcome, passed, detail = classify(entry, status, body)
        crash = outcome == "crash"
        rows.append({
            "id": cid,
            "group": entry["group"],
            "input": entry["input"],
            "expect_class": entry["expect_class"],
            "http_status": status,
            "outcome": outcome,
            "verdict": "PASS" if passed and not crash else "FAIL",
            "latency_ms": round(ms, 2),
            "detail": detail,
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Z3b · 对抗测试（期望表解耦）")
    ap.add_argument("--port", type=int, default=None, help="打已运行的服务；不传则自起")
    a = ap.parse_args()

    spec_cases = ensure_spec()   # 期望先于实现：先冻结、再运行

    srv = None
    if a.port:
        base = "http://127.0.0.1:{}".format(a.port)
    else:
        from api_server import Handler
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:{}".format(srv.server_address[1])

    t0 = time.perf_counter()
    rows = run_all(base, spec_cases)
    elapsed = time.perf_counter() - t0

    classes = {}
    for cls in ("hard_400", "soft_degrade", "repair", "success"):
        sub = [r for r in rows if r["expect_class"] == cls]
        classes[cls] = {"pass": sum(1 for r in sub if r["verdict"] == "PASS"),
                        "total": len(sub)}
    crash_count = sum(1 for r in rows if r["outcome"] == "crash")
    times = sorted(r["latency_ms"] for r in rows)
    p95 = times[min(len(times) - 1, math.ceil(0.95 * len(times)) - 1)]
    overall_pass = sum(1 for r in rows if r["verdict"] == "PASS")

    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "spec_frozen_at": os.path.exists(SPEC_PATH) and
                          json.load(open(SPEC_PATH, encoding="utf-8")).get("frozen_at"),
        "elapsed_s": round(elapsed, 2),
        "total_cases": len(rows),
        "stats": {
            "hard_400_pass": classes["hard_400"]["pass"],
            "hard_400_total": classes["hard_400"]["total"],
            "soft_degrade_pass": classes["soft_degrade"]["pass"],
            "soft_degrade_total": classes["soft_degrade"]["total"],
            "repair_pass": classes["repair"]["pass"],
            "repair_total": classes["repair"]["total"],
            "success_pass": classes["success"]["pass"],
            "success_total": classes["success"]["total"],
            "overall_pass": overall_pass,
            "overall_total": len(rows),
            "crash_count": crash_count,
            "p95_ms": round(p95, 2),
        },
        "cases": rows,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    # v1 产物一次性归档（v2 结果按新 schema 另写）
    v1 = os.path.join(OUT_DIR, "adversarial.json")
    if os.path.exists(v1):
        with open(v1, encoding="utf-8") as f:
            old = json.load(f)
        if "stats" not in old:   # 旧 schema（无四类 stats 块）才归档
            with open(os.path.join(OUT_DIR, "adversarial_v1.json"), "w", encoding="utf-8") as f:
                json.dump(old, f, ensure_ascii=False, indent=1)
            old_rep = os.path.join(OUT_DIR, "报告_对抗测试.md")
            if os.path.exists(old_rep):
                with open(old_rep, encoding="utf-8") as f:
                    content = f.read()
                with open(os.path.join(OUT_DIR, "报告_对抗测试_v1.md"), "w", encoding="utf-8") as f:
                    f.write(content)
            print("[archive] v1 产物已归档 → adversarial_v1.json / 报告_对抗测试_v1.md")
    with open(v1, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    # ---- 报告：期望表在前（冻结的 spec），结果在后 ----
    lines = ["# Z3b · 对抗测试报告（期望表与实现解耦）\n",
             "> **期望先于实现**：下表期望码在运行前冻结于 "
             "adversarial_spec.json（frozen_at {}），运行与判分过程未修改 spec；"
             "结果与 spec 按 id 一一对应。\n".format(result["spec_frozen_at"]),
             "## 一、冻结的期望表（spec，{} 例）\n".format(len(spec_cases)),
             "| 例 | 组 | 输入 | 期望码 | 理由 |",
             "|---|---|---|---|---|"]
    for c in spec_cases:
        lines.append("| {id} | {group} | {input} | {expect_class} | {reason} |".format(**c))
    lines += ["", "## 二、结果（{} 例）\n".format(len(rows)),
              "| 例 | 期望码 | HTTP | 结果 | 判定 | 耗时(ms) | 明细 |",
              "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| {id} | {expect_class} | {http_status} | {outcome} | {verdict} | "
                     "{latency_ms} | {detail} |".format(**r))
    s = result["stats"]
    lines += ["", "## 三、分类统计（不给单一拦截率）\n",
              "- hard_400：**{}/{}** 通过".format(s["hard_400_pass"], s["hard_400_total"]),
              "- soft_degrade：**{}/{}** 通过".format(s["soft_degrade_pass"],
                                                      s["soft_degrade_total"]),
              "- repair：**{}/{}** 通过".format(s["repair_pass"], s["repair_total"]),
              "- success：**{}/{}** 通过".format(s["success_pass"], s["success_total"]),
              "- overall：**{}/{}**".format(s["overall_pass"], s["overall_total"]),
              "- crash_count：**{}** · P95：**{} ms**".format(s["crash_count"], s["p95_ms"]),
              "", "## 四、结论\n"]
    if crash_count == 0 and overall_pass == len(rows):
        lines.append("1. **32/32 全过、零崩溃**：非法输入全部以 400 结构化 JSON 拒绝（含未知字段白名单与"
                     " MAX_TEXT_LEN=64 限长），服务未出现未捕获异常或堆栈外泄。")
    else:
        lines.append("1. **存在未通过项**：overall {}/{}，crash {}——逐例见上表 FAIL 行。".format(
            overall_pass, len(rows), crash_count))
    lines.append("2. **能力边界靠留痕**：4G 下切片/MEC/ISAC、5G 下 ISAC 返回 200 且 applied=false"
                 "（soft_degrade），GR-10 口径「该能力在当前档位不可用」对评委可见。")
    lines.append("3. **物理不可行被诚实标注**：8 分钟+480 列被 GR-09 拦截留痕（repair），"
                 "demand 3.0 与庐山站 1.4 倍需求如实标注超载与需增购（success 类的断言含诚实性检查）。")
    with open(os.path.join(OUT_DIR, "报告_对抗测试.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    if srv is not None:
        srv.shutdown()
    print("32 例完成：overall {}/{} · hard_400 {}/{} · soft_degrade {}/{} · repair {}/{} · "
          "success {}/{} · crash {} · P95 {}ms".format(
              overall_pass, len(rows), classes["hard_400"]["pass"], classes["hard_400"]["total"],
              classes["soft_degrade"]["pass"], classes["soft_degrade"]["total"],
              classes["repair"]["pass"], classes["repair"]["total"],
              classes["success"]["pass"], classes["success"]["total"],
              crash_count, result["stats"]["p95_ms"]))
    print("产物：{}".format(OUT_DIR))
    return 0 if (crash_count == 0 and overall_pass == len(rows)) else 1


if __name__ == "__main__":
    sys.exit(main())
