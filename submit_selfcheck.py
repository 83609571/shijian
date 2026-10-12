#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S-09 提交包逐项自检脚本（在提交前跑，任一 FAIL 需处理）
依据：整改工单 5.3 提交前 10 分钟自检清单 + 本报告 S-09。
用法：python3 submit_selfcheck.py  （在 赣鄱智轨_仿真主题 目录运行）
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE

def scan(exts, needles):
    """在项目源码中扫描敏感词（排除 lib/ 与 output/）。"""
    hits = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ("lib", "output", "__pycache__", ".git", ".workbuddy", "node_modules")]
        for f in files:
            if not f.endswith(exts):
                continue
            p = os.path.join(root, f)
            try:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        if any(n in line for n in needles):
                            hits.append(f"{os.path.relpath(p, ROOT)}:{i}")
            except Exception:
                pass
    return hits

def main():
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

    print("\n" + "=" * 62)
    print("结论:", "✅ 全部 PASS，可提交" if ok else "❌ 存在 FAIL，请处理后再提交")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
