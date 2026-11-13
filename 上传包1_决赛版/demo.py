#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""赣鄱智轨 · 现场一键启动（I7，纯 Python 标准库）

用法：
    python3 demo.py                 # 起 api_server（默认 8000，被占自动 +10）并打开演示台
    python3 demo.py --port 9000     # 指定起始端口
    python3 demo.py --no-browser    # 只起服务不开浏览器（录屏/远程用）
    python3 demo.py --check         # 演示前自检：仿真/通信/api 三项，全过退出码 0

行为：
    1) 从 --port 起向后找可用端口（最多 +10），打印实际端口；
    2) 用当前解释器起 api_server 子进程，轮询 GET / 直到 200（最多 8 秒）；
    3) 成功后打开浏览器到 /stage.html（Windows os.startfile / macOS open）；
    4) Ctrl+C 退出时终止子进程，不留孤儿进程。
"""
import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
API_SERVER = os.path.join(HERE, "api_server.py")
BANNER = """\
================================================================
赣鄱智轨 · 决赛版 v3.0 现场演示
  演示台    {stage}
  API 健康  {api}
  快捷键    F = 大屏字号 · 空格 = trace 播放/暂停
  退出      Ctrl+C（子进程一并退出，不留孤儿）
================================================================"""


def find_free_port(start: int, tries: int = 10):
    """从 start 起向后找可绑定端口（含 start 本身，最多 +10）；找不到返回 None。"""
    for offset in range(tries + 1):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return None


def wait_up(url: str, timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.25)
    return False


def open_browser(url: str) -> None:
    if sys.platform == "win32" and hasattr(os, "startfile"):
        os.startfile(url)  # noqa: S606 —— Windows 资源管理器打开
    elif sys.platform == "darwin":
        subprocess.Popen(["open", url], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(url)


def run_check() -> int:
    """三项自检：仿真锚点、通信台账、api_server 自检。打印三行总结。"""
    checks = [
        ("passenger_flow_sim --check", [sys.executable, "-m", "sim.passenger_flow_sim", "--check"]),
        ("comm_layer --check", [sys.executable, "-m", "sim.comm_layer", "--check"]),
        ("api_server --selftest", [sys.executable, API_SERVER, "--selftest"]),
    ]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    results = []
    for name, cmd in checks:
        print("[demo --check] {}: 运行中…".format(name))
        p = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env)
        ok = p.returncode == 0
        results.append((name, ok))
        lines = [ln for ln in ((p.stdout or "") + (p.stderr or "")).strip().splitlines() if ln.strip()]
        print("  " + (lines[-1] if lines else "exit={}".format(p.returncode)))
    print()
    for name, ok in results:
        print("  [{}] {}".format("PASS" if ok else "FAIL", name))
    all_ok = all(ok for _, ok in results)
    print("结论: {}".format("[OK] 三项全过，可去现场" if all_ok else "[NG] 存在失败，先修再出门"))
    return 0 if all_ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="赣鄱智轨 · 现场一键启动")
    ap.add_argument("--port", type=int, default=8000, help="起始端口，默认 8000，被占自动 +10")
    ap.add_argument("--no-browser", action="store_true", help="只起服务，不打开浏览器")
    ap.add_argument("--check", action="store_true", help="演示前自检后退出")
    a = ap.parse_args()
    if a.check:
        return run_check()

    port = find_free_port(a.port)
    if port is None:
        print("[demo] 错误：{}-{} 端口全部被占用，请用 --port 换一段".format(a.port, a.port + 10))
        return 2
    if port != a.port:
        print("[demo] 端口 {} 被占用，自动改用 {}".format(a.port, port))

    stage = "http://127.0.0.1:{}/stage.html".format(port)
    api = "http://127.0.0.1:{}/".format(port)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.Popen([sys.executable, API_SERVER, "--port", str(port)],
                                cwd=HERE, env=env)
    except OSError as e:
        print("[demo] 错误：无法启动 api_server：{}".format(e))
        return 1

    print(BANNER.format(stage=stage, api=api))
    print("[demo] 等待 api_server 就绪（最多 8 秒）…")
    if not wait_up(api):
        print("[demo] 错误：api_server {} 秒内未就绪。排查：".format(8))
        print("  1) 直接运行 python3 {} 看报错；".format(os.path.basename(API_SERVER)))
        print("  2) 确认端口 {} 未被其他程序长期占用；".format(port))
        print("  3) 运行 python3 demo.py --check 做完整自检。")
        if proc.poll() is None:
            proc.terminate()
        return 1

    print("[demo] 就绪。")
    if not a.no_browser:
        open_browser(stage)

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n[demo] Ctrl+C，正在退出…")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        print("[demo] 已退出，端口 {} 已释放。".format(port))
    return 0


if __name__ == "__main__":
    sys.exit(main())
