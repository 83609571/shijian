#!/usr/bin/env python3
"""赣鄱智轨 · 智能体在线 API 服务（零第三方依赖，纯 Python 标准库）

作用：把 run_agent.py 包成 HTTP 接口，部署到任意支持 Python 的托管平台
      （Render / Hugging Face Spaces / 腾讯云开发等），让 GitHub Pages 平台
      拥有"真·实时后端"——答辩现场点按钮，0.3 秒返回新决策文档。

用法：
    python api_server.py                # 默认监听 0.0.0.0:8000
    PORT=9000 python api_server.py      # 自定义端口（多数托管平台用 PORT 环境变量）

接口：
    GET  /                                健康检查 + 使用说明
    GET  /decision?scenario=holiday       读取最近一次决策文档（不重跑）
    POST /run?scenario=holiday&hub=南昌站  现场运行完整智能体链路并返回结果

安全说明：/run 单飞（进程级锁），带 120 秒超时；只读本仓库数据，不写其它路径。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
RUN_AGENT = os.path.join(HERE, "run_agent.py")

# 智能体单次完整运行 0.23s，但首次冷启动含解释器/IO，给足余量
RUN_TIMEOUT = 120
LOCK = threading.Lock()  # 同一时刻只允许一次运行，防止产物竞争


def run_agent(scenario: str, hub: str) -> dict:
    """调用 run_agent.py 跑完整链路，返回决策文档 dict。"""
    out_path = os.path.join(HERE, "data", f"agent_decision_{scenario}.json")
    cmd = [sys.executable, RUN_AGENT,
           "--scenario", scenario, "--hub", hub,
           "--decision-out", out_path, "--quiet"]
    # 子进程强制 UTF-8 输出（Windows 控制台默认 GBK，混合解码会崩）
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=RUN_TIMEOUT, env=env)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        raise RuntimeError(f"run_agent.py 退出码 {proc.returncode}：{tail}")
    with open(out_path, encoding="utf-8") as f:
        return json.load(f)


def read_decision(scenario: str) -> dict | None:
    p = os.path.join(HERE, "data", f"agent_decision_{scenario}.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class Handler(BaseHTTPRequestHandler):

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")  # 供 GitHub Pages 跨域调用
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/health"):
            self._send(200, {
                "ok": True,
                "service": "赣鄱智轨 · L3 智能体在线 API",
                "endpoints": {
                    "GET /decision?scenario=holiday|weekday": "读取最近一次决策文档",
                    "POST /run?scenario=holiday|weekday&hub=南昌站": "现场运行完整智能体链路",
                },
            })
            return
        if u.path == "/decision":
            scen = (parse_qs(u.query).get("scenario") or ["holiday"])[0]
            if scen not in ("holiday", "weekday"):
                self._send(400, {"ok": False, "error": "scenario 必须是 holiday 或 weekday"})
                return
            doc = read_decision(scen)
            if doc is None:
                self._send(404, {"ok": False, "error": f"尚无 {scen} 决策文档，请先 POST /run"})
                return
            self._send(200, {"ok": True, "scenario": scen, "doc": doc})
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/run":
            self._send(404, {"ok": False, "error": "not found"})
            return
        q = parse_qs(u.query)
        scen = (q.get("scenario") or ["holiday"])[0]
        if scen not in ("holiday", "weekday"):
            self._send(400, {"ok": False, "error": "scenario 必须是 holiday 或 weekday"})
            return
        hub = (q.get("hub") or ["南昌站"])[0]
        with LOCK:
            try:
                doc = run_agent(scen, hub)
            except Exception as e:  # noqa: BLE001 —— 面向演示的 API，错误如实回传
                self._send(500, {"ok": False, "scenario": scen, "error": str(e)})
                return
        self._send(200, {"ok": True, "scenario": scen, "hub": hub, "doc": doc})

    def log_message(self, fmt, *args):
        sys.stderr.write("[api] " + (fmt % args) + "\n")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"赣鄱智轨 · 智能体在线API  http://0.0.0.0:{port}")
    print("  GET  /decision?scenario=holiday   读取最近决策文档")
    print("  POST /run?scenario=holiday        现场运行完整链路")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
