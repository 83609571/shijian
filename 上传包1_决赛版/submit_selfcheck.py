#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S-09 提交包逐项自检脚本（在提交前跑，任一 FAIL 需处理）
依据：整改工单 5.3 提交前 10 分钟自检清单 + 本报告 S-09。
用法：python3 submit_selfcheck.py [--finals]
      --finals 追加决赛口径检查：黑名单扫描 / 决赛材料齐套 / 冻结数字回归断言（依据 决赛材料/A1）
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE

def scan(exts, needles, extra_exclude=(), skip_bak=False, skip_prefixes=()):
    """在项目源码中扫描敏感词（排除 lib/ 与 output/；extra_exclude 追加排除目录，
    skip_prefixes 按仓库相对路径前缀跳过个别文件）。"""
    hits = []
    exclude = ("lib", "output", "__pycache__", ".git", ".workbuddy", "node_modules") + tuple(extra_exclude)
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in exclude]
        for f in files:
            if skip_bak and ".bak" in f:
                continue
            if not f.endswith(exts):
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
            if any(rel.startswith(sp) for sp in skip_prefixes):
                continue
            try:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        if any(n in line for n in needles):
                            hits.append(f"{rel}:{i}")
            except Exception:
                pass
    return hits

def main():
    finals = "--finals" in sys.argv
    ok = True
    def check(name, cond, detail=""):
        nonlocal ok
        flag = "PASS" if cond else "FAIL"
        if not cond: ok = False
        print(f"  [{flag}] {name}" + (f"  —— {detail}" if detail else ""))

    print("=" * 62)
    print("赣鄱智轨 · 提交包自检（S-09）")
    print("=" * 62)

    # 1) 无残留配色描述（通勤蓝/旅游绿）
    print("\n[1] 配色口径残留检查")
    hits = scan((".js", ".html", ".md"), ["通勤蓝", "旅游绿"])
    check("无'通勤蓝/旅游绿'残留", not hits, ";".join(hits[:5]))

    # 2) 真实 AK 检查 —— 开发目录保留真实 AK 以运行地图属正常；提交包必须占位化
    print("\n[2] 真实 AK 检查（本地开发可保留；提交包必须占位化）")
    lok = os.path.join(ROOT, "js", "local-ak.js")
    real_ak = []
    if os.path.exists(lok):
        txt = open(lok, encoding="utf-8").read()
        for m in re.finditer(r"['\"]([A-Za-z0-9_\-]{20,})['\"]", txt):
            real_ak.append(m.group(1))
    if real_ak:
        print(f"  [WARN] local-ak.js 含 {len(real_ak)} 个疑似真实 AK。本地运行地图必需，可保留；")
        print(f"        制作提交包时请替换为占位符（如 'YOUR_BAIDU_AK'）或删除本文件，避免泄露与配额盗刷。")
    else:
        print("  [PASS] 无疑似真实 AK")
    ok = ok  # AK 为 WARN 级，不计入 FAIL（提交包打包时单独处理）

    # 3) 数据版本一致
    print("\n[3] 数据版本一致性")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "sim", "passenger_flow_sim.py"), "--check"],
                       cwd=ROOT, capture_output=True, text=True)
    check("sim --check 通过", r.returncode == 0, (r.stdout or r.stderr).splitlines()[-1] if r.stdout else "exit非0")
    # 3b) 通信数字孪生层一致性（5G-A 通感算智）
    r2 = subprocess.run([sys.executable, "-m", "sim.comm_layer", "--check"],
                        cwd=ROOT, capture_output=True, text=True)
    check("comm_layer --check 通过", r2.returncode == 0, (r2.stdout or r2.stderr).strip().splitlines()[-1] if (r2.stdout or r2.stderr) else "exit非0")

    # 4) 无内部工作记录混入（评估与提升、答辩问答库、SWOT 等过程文档；
    #    output/ 内的治理报告/trace/仿真结果是合法成果佐证，应保留）
    print("\n[4] 内部工作记录扫描")
    internal = [d for d in ("评估与提升", ".zcode", "答辩问答库", "SWOT", "演示分镜")
                if os.path.exists(os.path.join(ROOT, d))]
    check("提交包无内部过程文档", len(internal) == 0, f"检出:{internal}")
    # 提示：output/ 为运行产物（成果佐证），不计入内部记录
    if os.path.exists(os.path.join(ROOT, "output")):
        print("  [INFO] output/（治理报告/trace/仿真结果）为合法成果佐证，提交时按需保留。")

    # 5) 入口文件存在
    print("\n[5] 双入口存在性")
    for f in ("index.html", "bmap.html"):
        check(f"{f} 存在", os.path.exists(os.path.join(ROOT, f)))

    # 6) 决赛口径黑名单扫描（仅 --finals；依据 决赛材料/A1 §五）
    if finals:
        print("\n[6] 决赛口径黑名单扫描"
              "（sim/ agent/ 为引擎源码不扫；决赛材料/ 仅排除 A1/A2/Z 三份政策文档，"
              "A3/A4/A5 落地后纳入扫描）")
        blacklist = [
            "7 条真实锚点", "9 个工具", "9 条护栏", "5 个 Agent", "5 个agent",
            "37 步", "37步", "58 步", "58步",
            "校赛演示版",
            "D:\\工作", "c:\\Users\\黄47",
            "以轨代巴减排",  # A1 §五禁用表述；index.html 中《以轨代巴》为源方案标题引用，非减排表述
        ]
        bl_hits = scan((".js", ".html", ".md", ".txt"), blacklist, skip_bak=True,
                       extra_exclude=("sim", "agent", "_规划",
                                      ".zcode", ".claude", "_codebuddy"),
                       skip_prefixes=("决赛材料/A1_", "决赛材料/A2_", "决赛材料/Z_"))
        check("口径黑名单 0 命中", not bl_hits,
              ";".join(bl_hits[:8]) if bl_hits else "10 类漂移词（含无空格变体）全部干净")

        # 7) 决赛材料齐套（WARN 级，不阻断退出码；A3/A4/A5 由主会话 11-12 前定稿）
        print("\n[7] 决赛材料齐套（WARN 级，不阻断）")
        fj = os.path.join(ROOT, "决赛材料")
        for prefix in ("A1", "A2", "A3", "A4", "A5"):
            found = sorted(f for f in os.listdir(fj)
                           if f.startswith(prefix + "_") and f.endswith(".md")) \
                if os.path.isdir(fj) else []
            if found:
                print(f"  [PASS] {prefix} ：{found[0]}")
            else:
                print(f"  [WARN] {prefix} 缺件（决赛材料/{prefix}_*.md），11-12 前需定稿送印")

        # 8) 数字回归断言（A1 第四节冻结数字；工具/护栏按 A1 口径"代码清点"）
        print("\n[8] 数字回归断言（冻结口径）")
        try:
            with open(os.path.join(ROOT, "data", "agent_decision.json"), encoding="utf-8") as fh:
                ad = json.load(fh)
            d_plans = [p for p in ad.get("plans", []) if p.get("id") == "D"]
            d_total = d_plans[0].get("score", {}).get("total") if d_plans else None
            check("推荐方案 D 总分 = 83.6（±0.1）",
                  isinstance(d_total, (int, float)) and abs(d_total - 83.6) <= 0.1,
                  f"实际 {d_total}")
            tr = ad.get("trace", {})
            print(f"  [INFO] 运行时证据：{tr.get('steps')} 步 / {tr.get('tool_calls')} 次工具调用"
                  f" / {tr.get('failed_calls')} 失败（离线口径 39/25/0）")
        except Exception as e:
            check("data/agent_decision.json 可读且含方案 D", False, repr(e))

        try:
            with open(os.path.join(ROOT, "agent", "tools.py"), encoding="utf-8") as fh:
                tool_names = set(re.findall(r'"name":\s*"([a-z_0-9]+)"', fh.read()))
            check("工具注册表 13 个（代码清点）", len(tool_names) == 13, f"清点得 {len(tool_names)}")
        except Exception as e:
            check("agent/tools.py 工具清点", False, repr(e))

        try:
            with open(os.path.join(ROOT, "agent", "guardrail.py"), encoding="utf-8") as fh:
                gr_ids = set(re.findall(r'"id":\s*"(GR-\d{2})"', fh.read()))
            check("护栏规则 10 条 GR-01~GR-10（代码清点）", len(gr_ids) == 10, f"清点得 {len(gr_ids)}")
        except Exception as e:
            check("agent/guardrail.py 护栏清点", False, repr(e))

        try:
            with open(os.path.join(ROOT, "output", "experiments", "network_sla_holiday.json"),
                      encoding="utf-8") as fh:
                ns = json.load(fh)
            ctl = ns["groups"]["control_4g"]["events"]["train_fault"]["chain_s"]
            a5g = ns["groups"]["a_5ga_det"]["events"]["train_fault"]["chain_s"]
            check("网络 SLA 4G chain_s = 121.65", abs(ctl - 121.65) < 0.005, f"实际 {ctl}")
            check("网络 SLA 5G-A chain_s = 2.104", abs(a5g - 2.104) < 0.0005, f"实际 {a5g}")
        except Exception as e:
            check("output/experiments/network_sla_holiday.json 断言", False, repr(e))

    print("\n" + "=" * 62)
    verdict = "✅ 全部 PASS，可提交" if ok else "❌ 存在 FAIL，请处理后再提交"
    if finals and ok:
        verdict += "（含决赛口径检查）"
    print("结论:", verdict)
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
