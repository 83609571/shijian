#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""赣鄱智轨 · 百度地图真实数据层 + 客流预测（赛后迭代，纯 Python 标准库）

设计边界（依据 决赛材料/交付接续说明_给学生_v1.0.md 1.1/1.2）：
  1) 只加新层：不改 sim/ agent/ experiments.py 任何常量，不写 data/ 冻结文件；
  2) 产物只进 output/scratch/baidu_cache/（不入库）；
  3) AK 三级读取，与 js/config.js 同口径：
       ① 调用方显式传入（前端 ?ak=xxx 透传）
       ② 环境变量 GANPO_BMAP_AK
       ③ 本地文件 js/local-ak.js（gitignore 忽略，解析 window.GANPO_BMAP_AK）
  4) 断网降级：无 AK / 请求失败 → 读缓存（过期也可用）→ 再退化为纯推演
     （modifier=1.0，来源标 offline_fallback），全链路不抛异常、不白屏；
  5) 口径纪律：所有预测值标"仿真推演"；百度数据标"百度地图公开接口"，
     两者分账，不混入 A1 冻结数字表。

对外一句话：百度数据的价值 = 给仿真锚点做外部校准 + 给预测提供真实特征。

用法：
    python3 predict.py --forecast --scenario holiday   # CLI 直出 JSON（离线安全）
    python3 predict.py --selftest                      # 离线自检（不联网）
"""
from __future__ import annotations  # Python 3.9 兼容：X | None 注解不在定义期求值
import argparse
import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "output", "scratch", "baidu_cache")
LOCAL_AK_FILE = os.path.join(HERE, "js", "local-ak.js")
FLOW_FILE = os.path.join(HERE, "data", "flow_{}.json")

CACHE_TTL_S = 600          # 在线缓存 10 分钟；过期后离线仍可读（降级标注 stale）
HTTP_TIMEOUT_S = 5         # 现场演示断网时快速失败，不拖慢接口
BAIDU_TRAFFIC_URL = "https://api.map.baidu.com/traffic/v1/road"
BAIDU_POI_URL = "https://api.map.baidu.com/place/v2/search"

# 状态码 → 中文（traffic/v1/road congestion_status）
CONGESTION_LABEL = {1: "畅通", 2: "缓行", 3: "拥堵", 4: "严重拥堵"}

# ---------------- 站点 → 百度数据映射（可在本地编辑，不影响 data/ 冻结文件） ----------------
# city/road 供 traffic/v1/road（站旁主干道实时路况）；poi 供 place/v2/search（旅游需求拉力），
# poi=None 的通勤站不做旅游修正。键必须与 flow_*.json 的 stations[].name 一致。
STATION_MAP = {
    "南昌站":     {"city": "南昌市",   "road": "二七南路",   "poi": "滕王阁"},
    "永修站":     {"city": "九江市",   "road": "永修大道",   "poi": None},
    "共青城站":   {"city": "九江市",   "road": "共青大道",   "poi": None},
    "九江站":     {"city": "九江市",   "road": "长虹大道",   "poi": "九江烟水亭"},
    "进贤站":     {"city": "南昌市",   "road": "进贤大道",   "poi": None},
    "抚州站":     {"city": "抚州市",   "road": "赣东大道",   "poi": None},
    "上饶站":     {"city": "上饶市",   "road": "凤凰大道",   "poi": None},
    "婺源站":     {"city": "上饶市",   "road": "天佑大道",   "poi": "篁岭景区"},
    "三清山站":   {"city": "上饶市",   "road": "三清山大道", "poi": "三清山风景区"},
    "龙虎山站":   {"city": "鹰潭市",   "road": "龙虎山大道", "poi": "龙虎山风景区"},
    "庐山站":     {"city": "九江市",   "road": "庐山大道",   "poi": "庐山风景区"},
    "庐山西海站": {"city": "九江市",   "road": "西海大道",   "poi": "庐山西海风景区"},
    "丰城站":     {"city": "宜春市",   "road": "紫云大道",   "poi": None},
    "樟树站":     {"city": "宜春市",   "road": "药都大道",   "poi": None},
    "新余站":     {"city": "新余市",   "road": "新余大道",   "poi": None},
    "宜春站":     {"city": "宜春市",   "road": "宜阳大道",   "poi": "明月山"},
    "萍乡站":     {"city": "萍乡市",   "road": "建设路",     "poi": None},
    "吉安站":     {"city": "吉安市",   "road": "井冈山大道", "poi": None},
    "兴国站":     {"city": "赣州市",   "road": "将军大道",   "poi": None},
    "赣州站":     {"city": "赣州市",   "road": "赣江源大道", "poi": None},
    "鹰潭站":     {"city": "鹰潭市",   "road": "梅园大道",   "poi": None},
    "景德镇站":   {"city": "景德镇市", "road": "珠山大道",   "poi": None},
    "井冈山站":   {"city": "吉安市",   "road": "红军大道",   "poi": "井冈山风景区"},
    "明月山站":   {"city": "宜春市",   "road": "明月大道",   "poi": "明月山旅游区"},
    "安源站":     {"city": "萍乡市",   "road": "安源大道",   "poi": "安源景区"},
    "瑞金站":     {"city": "赣州市",   "road": "红都大道",   "poi": "共和国摇篮景区"},
    "龙南站":     {"city": "赣州市",   "road": "龙翔大道",   "poi": "南武当山"},
    "瑶里站":     {"city": "景德镇市", "road": "浮梁大道",   "poi": "瑶里古镇"},
    "龟峰站":     {"city": "上饶市",   "road": "龟峰大道",   "poi": "龟峰景区"},
    "上清古镇站": {"city": "鹰潭市",   "road": "上清大道",   "poi": "上清古镇"},
    "资溪站":     {"city": "抚州市",   "road": "资溪大道",   "poi": None},
    "大觉山站":   {"city": "抚州市",   "road": "大觉山大道", "poi": "大觉山景区"},
    "湾里站":     {"city": "南昌市",   "road": "湾里大道",   "poi": "梅岭国家森林公园"},
    "梅岭站":     {"city": "南昌市",   "road": "梅岭大道",   "poi": "梅岭狮子峰"},
}

# ---------------- 确定性 24 小时曲线（纯代码常量，可复算；份额和自动归一化） ----------------
# commuter = 双峰通勤；tourism = 节假日日间单峰。与 flow_*.json 的日客流相乘得逐小时推演。
HOURLY_CURVE = {
    "weekday_commuter": [1.5, 1.0, 0.6, 0.5, 1.0, 3.0, 6.5, 10.0, 8.0, 4.5, 3.5, 3.0,
                         3.2, 3.0, 3.4, 4.5, 6.0, 8.5, 8.0, 6.0, 4.5, 3.0, 2.0, 1.6],
    "weekday_tourism":  [1.2, 0.8, 0.5, 0.5, 0.8, 1.5, 3.0, 5.0, 6.5, 7.0, 6.5, 6.0,
                         6.2, 6.0, 6.5, 7.0, 6.8, 6.0, 5.0, 4.5, 3.5, 2.5, 1.8, 1.4],
    "holiday_commuter": [1.8, 1.2, 0.8, 0.6, 1.0, 2.5, 4.5, 6.5, 6.0, 5.0, 4.5, 4.2,
                         4.5, 4.2, 4.8, 5.5, 6.5, 7.5, 7.0, 6.0, 5.0, 3.5, 2.5, 2.0],
    "holiday_tourism":  [1.5, 1.0, 0.6, 0.5, 0.8, 1.5, 3.0, 5.5, 7.5, 8.5, 8.0, 7.5,
                         7.2, 7.0, 7.5, 8.0, 7.8, 7.0, 6.0, 5.0, 4.0, 3.0, 2.2, 1.6],
}


def hourly_curve(scenario: str, stype: str) -> list:
    key = "{}_{}".format(scenario, "tourism" if stype == "tourism" else "commuter")
    w = HOURLY_CURVE[key]
    s = sum(w)
    return [x / s for x in w]


# ---------------- AK 三级读取 ----------------
def read_ak(ak_override: str | None = None) -> tuple[str, str]:
    """返回 (ak, 来源)。来源 ∈ {caller, env, local-ak.js, none}。"""
    if ak_override:
        return ak_override.strip(), "caller"
    for env_key in ("GANPO_BMAP_AK", "BAIDU_AK"):
        v = os.environ.get(env_key, "").strip()
        if v:
            return v, "env:{}".format(env_key)
    try:
        with open(LOCAL_AK_FILE, encoding="utf-8") as f:
            m = re.search(r'GANPO_BMAP_AK\s*=\s*"([^"]+)"', f.read())
        if m and m.group(1) and not m.group(1).startswith("YOUR_"):
            return m.group(1), "js/local-ak.js"
    except OSError:
        pass
    return "", "none"


# ---------------- 缓存（output/scratch/baidu_cache/，不入库） ----------------
def _cache_path(url_no_ak: str) -> str:
    key = hashlib.md5(url_no_ak.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, key + ".json")


_FETCH_LOCK = threading.Lock()  # 串行化外部请求与缓存写入（短超时，不阻塞智能体运行）


def baidu_get(url: str, params: dict, ak: str) -> dict | None:
    """带缓存的百度接口调用。任何失败返回 None（含离线读旧缓存）。"""
    safe = {k: v for k, v in params.items()}
    url_no_ak = url + "?" + urllib.parse.urlencode(safe)
    cp = _cache_path(url_no_ak)
    now = time.time()
    with _FETCH_LOCK:
        if os.path.isfile(cp):
            try:
                with open(cp, encoding="utf-8") as f:
                    hit = json.load(f)
                if now - hit.get("_ts", 0) < CACHE_TTL_S:
                    hit["_fresh"] = True
                    return hit
                hit["_fresh"] = False   # 过期缓存：离线时仍可用（stale 降级）
            except Exception:
                hit = None
        else:
            hit = None
        if not ak:
            return hit
        full = url_no_ak + "&ak=" + urllib.parse.quote(ak)
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "ganpo-zhigui/3.0"})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
                data = json.loads(r.read().decode("utf-8"))
            data["_ts"] = now
            data["_fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            data["_fresh"] = True
            os.makedirs(CACHE_DIR, exist_ok=True)
            tmp = cp + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, cp)  # 原子替换，避免并发读到半截 JSON
            return data
        except Exception:
            return hit  # 网络失败 → 过期缓存或 None


def _find_first(obj, key):
    """在未知结构的响应里递归找第一个标量值（防御性解析，避免接口改版崩溃）。"""
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], (str, int, float)):
            return obj[key]
        for v in obj.values():
            r = _find_first(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_first(v, key)
            if r is not None:
                return r
    return None


# ---------------- 百度特征 ----------------
def fetch_traffic(name: str, cfg: dict, ak: str) -> dict:
    """站旁主干道实时路况 → 拥挤度外部校准特征。"""
    out = {"source": "百度地图路况公开接口", "road": cfg["road"], "city": cfg["city"],
           "status": None, "status_label": None, "provider": "offline_fallback"}
    data = baidu_get(BAIDU_TRAFFIC_URL,
                     {"road_name": cfg["road"], "city": cfg["city"], "extensions": "1"},
                     ak)
    if not data:
        return out
    raw = _find_first(data, "congestion_status")
    try:
        status = int(raw)
    except (TypeError, ValueError):
        status = None
    if status in CONGESTION_LABEL:
        out["status"] = status
        out["status_label"] = CONGESTION_LABEL[status]
        out["provider"] = "baidu_live" if data.get("_fresh") else "baidu_cache(stale)"
    if data.get("_fetched_at"):
        out["fetched_at"] = data["_fetched_at"]
    return out


def fetch_poi(name: str, cfg: dict, ak: str) -> dict:
    """景区 POI 评论量级 → 旅游需求拉力特征（仅 poi 非空的站）。"""
    out = {"source": "百度地图POI公开接口", "query": cfg["poi"], "comment_num": None,
           "provider": "offline_fallback"}
    if not cfg["poi"]:
        out["provider"] = "not_applicable"
        return out
    data = baidu_get(BAIDU_POI_URL,
                     {"query": cfg["poi"], "tag": "旅游景点", "region": cfg["city"],
                      "scope": "2", "output": "json"}, ak)
    if not data:
        return out
    raw = _find_first(data, "comment_num")
    try:
        out["comment_num"] = int(raw)
    except (TypeError, ValueError):
        pass
    out["provider"] = "baidu_live" if data.get("_fresh") else "baidu_cache(stale)"
    if data.get("_fetched_at"):
        out["fetched_at"] = data["_fetched_at"]
    return out


def congestion_modifier(status) -> float:
    """路况 → 拥挤修正：畅通 1.00 / 缓行 1.05 / 拥堵 1.10 / 严重拥堵 1.15。"""
    if status not in CONGESTION_LABEL:
        return 1.0
    return round(1.0 + 0.05 * (status - 1), 3)


def poi_modifier(comment_num) -> float:
    """评论量级 → 需求拉力（对数尺度，封顶 +10%；无数据 1.0）。"""
    if not comment_num or comment_num <= 0:
        return 1.0
    rank = min(1.0, math.log10(comment_num + 1) / 5.0)
    return round(1.0 + 0.10 * rank, 3)


# ---------------- 锚点校准 ----------------
def calibrate(stations: list) -> list:
    """仿真客流分位（1-4） vs 百度路况（1-4）→ 逐站一致性判定。
    两套数据独立来源，|差|<=1 记'一致'；2 个站及以上偏离才需要人工复核。"""
    flows = [s["flow_daily_pred"] for s in stations]
    order = sorted(flows)
    n = len(order)

    def quartile(v):
        return max(1, min(4, 1 + int(4.0 * order.index(v) / max(1, n - 1))))

    out = []
    for s in stations:
        sim_level = quartile(s["flow_daily_pred"])
        bd = s["baidu"]["traffic"].get("status")
        if bd is None:
            verdict, detail = "n/a", "无外部路况数据（离线降级）"
        else:
            gap = abs(sim_level - bd)
            verdict = "一致" if gap <= 1 else "偏离"
            detail = "仿真分位 {} 级 vs 路况 {} 级（{}）".format(
                sim_level, bd, s["baidu"]["traffic"].get("status_label"))
        out.append({"name": s["name"], "sim_level": sim_level, "baidu_level": bd,
                    "verdict": verdict, "detail": detail})
    return out


# ---------------- 主入口 ----------------
def forecast(scenario: str = "holiday", ak_override: str | None = None) -> dict:
    """逐小时客流预测（仿真推演）+ 百度真实特征（外部校准）。断网全程可跑。"""
    if scenario not in ("holiday", "weekday"):
        raise ValueError("scenario 必须是 holiday 或 weekday")
    ak, ak_source = read_ak(ak_override)
    with open(FLOW_FILE.format(scenario), encoding="utf-8") as f:
        flow = json.load(f)

    rows = []
    for st in flow.get("stations", []):
        name = st.get("name")
        cfg = STATION_MAP.get(name, {"city": None, "road": None, "poi": None})
        traffic = fetch_traffic(name, cfg, ak)
        poi = fetch_poi(name, cfg, ak)
        m_road = congestion_modifier(traffic.get("status"))
        m_poi = poi_modifier(poi.get("comment_num")) if cfg["poi"] else 1.0
        m_total = round(m_road * m_poi, 3)
        curve = hourly_curve(scenario, st.get("type", "commuter"))
        daily = float(st.get("flow", 0)) * m_total
        hourly = [round(daily * c) for c in curve]
        peak_i = max(range(24), key=lambda i: hourly[i])
        rows.append({
            "name": name, "type": st.get("type"), "real": st.get("real", False),
            "lng": st.get("lng"), "lat": st.get("lat"),
            "flow_daily_base": st.get("flow"),          # flow_*.json 原值（仿真推演）
            "flow_daily_pred": round(daily),            # 修正后预测（仿真推演）
            "hourly_pred": hourly,                      # 24 小时推演
            "peak_hour": peak_i, "peak_flow": hourly[peak_i],
            "modifiers": {"road": m_road, "poi": m_poi, "total": m_total},
            "baidu": {"traffic": traffic, "poi": poi},
        })

    calibration = calibrate(rows)
    ok_set = [c for c in calibration if c["verdict"] == "一致"]
    known = [c for c in calibration if c["verdict"] != "n/a"]
    provider_set = {r["baidu"]["traffic"]["provider"] for r in rows}
    online = any(p.startswith("baidu_live") for p in provider_set)

    return {
        "ok": True,
        "meta": {
            "scenario": scenario,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ak_configured": bool(ak), "ak_source": ak_source,
            "provider": "baidu_live" if online else "offline_fallback",
            "labels": {
                "flow_daily_base": "仿真推演（data/flow_*.json）",
                "flow_daily_pred": "仿真推演（本模块确定性外推）",
                "baidu_traffic": "百度地图公开接口（真实外部数据）",
                "baidu_poi": "百度地图公开接口（真实外部数据）",
            },
            "note": "预测与仿真分账：百度数据只做特征与校准，不回写 data/ 冻结文件，"
                    "不影响 A1 冻结数字（83.6 / 57.8×）。",
            "cache_dir": os.path.relpath(CACHE_DIR, HERE),
        },
        "summary": {
            "station_count": len(rows),
            "calibration_total": len(known),
            "calibration_consistent": len(ok_set),
            "calibration_rate": (round(len(ok_set) / len(known), 3) if known else None),
            "offline": not online,
        },
        "stations": rows,
        "calibration": calibration,
    }


# ---------------- CLI ----------------
def _selftest() -> int:
    """离线自检：无 AK、无网络下 forecast() 可跑、结构完整、不写 data/。"""
    for scen in ("holiday", "weekday"):
        d = forecast(scen)
        assert d["ok"] and d["stations"], scen
        assert len(d["stations"]) == 34, "{} 站数 {}".format(scen, len(d["stations"]))
        for s in d["stations"]:
            assert len(s["hourly_pred"]) == 24
            assert sum(s["hourly_pred"]) > 0
        assert d["meta"]["provider"] == "offline_fallback"
    print("[predict --selftest] PASS：离线降级可跑，34 站 × 24 小时结构完整，data/ 未写入")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="赣鄱智轨 · 百度数据层 + 客流预测")
    ap.add_argument("--forecast", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--scenario", default="holiday", choices=["holiday", "weekday"])
    ap.add_argument("--ak", default=None, help="临时指定百度 AK（优先级最高）")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.forecast:
        print(json.dumps(forecast(a.scenario, a.ak), ensure_ascii=False, indent=2))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
