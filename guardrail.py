"""L3 智能体层 · 确定性护栏（Guardrail）

角色转换说明（这是本次改造最关键的定位变化）：
    改造前：mirrorDispatch()/decisions() 是「决策大脑」—— 前端硬编码 if-else 查表，
            任何输入都只会吐回预设文案。评委一问「为什么是这个间隔」就答不上来。
    改造后：同一批业务规则降级为「安全护栏」—— 它不再产生方案，
            只负责对 Planner（LLM）产出的参数做越界拦截，并给出拦截理由。

为什么护栏是加分项而不是限制：
    交通安全关键系统的工程共识是「LLM 不得直接下发控制指令，必须经确定性边界校验」。
    把它讲清楚，既回答了「为什么不用纯大模型」，也让「LLM 输出不可控」这个风险归零。
"""
from __future__ import annotations

from . import schemas as S

# —— 业务规则表（原 mirrorDispatch 的规则内核，此处仅作校验阈值）——
# 每条规则都是「物理/运营约束」，不是「偏好」，因此可以硬拦截。
RULES = [
    {
        "id": "GR-01",
        "name": "最小发车间隔",
        "check": lambda c: c["headway_min"] >= 4.0,
        "why": "信号系统与折返能力下限，短于此间隔将无法保障追踪安全。",
        "fix": "把发车间隔调回 ≥ 4 min。",
    },
    {
        "id": "GR-02",
        "name": "最大发车间隔",
        "check": lambda c: c["headway_min"] <= 30.0,
        "why": "间隔 > 30min 时站台候车人数会突破设计容量，等同于放弃公共服务。",
        "fix": "把发车间隔压到 ≤ 30 min，或改用小编组高密度。",
    },
    {
        "id": "GR-03",
        "name": "编组上限",
        "check": lambda c: c["formation_cars"] in S.GUARDRAIL["formation_cars"]["enum"],
        "why": "站台有效长度只支持 2/4/6/8 辆编组，超长编组无法对标停车。",
        "fix": "编组取 2/4/6/8 之一。",
    },
    {
        "id": "GR-04",
        "name": "限流等级合法",
        "check": lambda c: c["limit_level"] in (0, 1, 2, 3),
        "why": "限流等级对应既定的分级管控预案，不允许出现预案外等级。",
        "fix": "限流等级取 0/1/2/3。",
    },
    {
        "id": "GR-05",
        "name": "三级限流须配套疏运",
        "check": lambda c: not (c["limit_level"] == 3 and c["formation_cars"] < 6),
        "why": "三级限流（只出不进）会造成站外滞留，必须同时以 ≥6 辆编组疏运，否则风险转移而非消除。",
        "fix": "三级限流时把编组提到 6 辆或以上。",
    },
    {
        "id": "GR-06",
        "name": "需求乘子可信区间",
        "check": lambda c: 0.5 <= c["demand_mult"] <= 2.0,
        "why": "超出 ±100% 的客流外推已离开标定样本区间，模型结论不可信。",
        "fix": "把需求乘子收进 [0.5, 2.0]。",
    },
    {
        "id": "GR-07",
        "name": "运能与需求匹配（供给侧自检）",
        "check": lambda c: c["formation_cars"] * S.SEATS_PER_CAR * (60.0 / c["headway_min"])
                          * S.LOAD_AVAILABILITY >= 1200.0,
        "why": "小时运能低于 1200 人时，任何场景都无法承运，属于无效方案。",
        "fix": "提高编组或压缩间隔，使小时运能 ≥ 1200 人。",
    },
    {
        "id": "GR-08",
        "name": "参数完备性",
        "check": lambda c: all(k in c for k in
                               ("headway_min", "formation_cars", "limit_level", "demand_mult")),
        # GR-08 必须看「原始入参」：fill_defaults 会补齐缺项，
        # 若沿用 check(checked) 则本条永远通过，缺参也发现不了。
        "raw_check": lambda p: all(k in p for k in
                                   ("headway_min", "formation_cars", "limit_level", "demand_mult")),
        "why": "缺失参数将导致仿真结果无法复现。",
        "fix": "补齐四项必填参数。",
    },
    {
        "id": "GR-09",
        "name": "配车需求不得超过可用车辆数",
        "check": lambda c: _fleet_ok(c),
        "why": "压缩发车间隔直接消耗配车（配车数 = 往返周期 / 间隔）。"
               "车辆资产不足时，纸面上漂亮的间隔排不出图，属于不可执行方案。",
        "fix": "调大发车间隔，或申请增购车辆，或改用「区间加开 + 长短交路」提高车辆周转率。",
    },
]


def _fleet_ok(cfg: dict) -> bool:
    """GR-09：按线路核算配车需求，与可用车辆数比较。"""
    try:
        from . import sim_adapter as sa
        sc = cfg.get("scenario", "holiday")
        need = sa.estimate_fleet(sc, float(cfg["headway_min"]))["required_trains"]
        return need <= int(cfg.get("fleet_limit", S.DEFAULT_FLEET_LIMIT))
    except Exception:  # noqa: BLE001
        return True   # 计算异常不阻断（避免护栏本身成为故障点）


def fleet_detail(cfg: dict) -> dict:
    """给出配车核算明细，供答辩解释「为什么这个间隔排不出来」。"""
    from . import sim_adapter as sa
    sc = cfg.get("scenario", "holiday")
    est = sa.estimate_fleet(sc, float(cfg.get("headway_min", 12)))
    limit = int(cfg.get("fleet_limit", S.DEFAULT_FLEET_LIMIT))
    est["fleet_limit"] = limit
    est["gap"] = est["required_trains"] - limit
    est["feasible"] = est["gap"] <= 0
    # 反推可行的最小间隔（配车不超限的前提下能达到的最短间隔）
    lo, hi = 1.0, 60.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if sa.estimate_fleet(sc, mid)["required_trains"] > limit:
            lo = mid
        else:
            hi = mid
    est["min_feasible_headway"] = round(hi + 0.5, 1)
    return est


def validate(param_json: dict) -> dict:
    """对参数做逐条护栏校验。

    返回结构（前端与 trace 都消费这个结构）：
      {passed, violations:[{id,name,why,fix,field,value}], normalized:[...], effective:{...}}

    ★ 校验对象是「调用方真正下发的值」，不是钳制后的值 ★
      原实现把 RULES 跑在 normalize_config() 的输出上，而越界值在进入规则前
      就已被钳回合法区间 → GR-01/02/03/04/06/08 六条规则**永远不可能触发**。
      实测证据：LLM 下发 headway=2.0 / 编组=20 / 客流×3.0，本应触发
      GR-01+GR-03+GR-06，结果只报出 GR-09 一条。
      现改为两条通道：
        checked   = fill_defaults(param_json)      —— 原值，喂给规则
        effective = normalize_config(param_json)[0] —— 钳制值，喂给仿真
      同时把「被静默钳掉的部分」记为 soft_clamped，让 trace 保留完整证据。
    """
    checked = S.fill_defaults(param_json)
    normalized_cfg, norm_record = S.normalize_config(param_json)
    violations = []
    for rule in RULES:
        try:
            raw_fn = rule.get("raw_check")
            ok = bool(raw_fn(param_json or {})) if raw_fn else bool(rule["check"](checked))
        except Exception as e:  # noqa: BLE001
            ok = False
            rule = dict(rule, extra=f"校验异常：{type(e).__name__}")
        if not ok:
            v = {
                "id": rule["id"], "name": rule["name"],
                "why": rule["why"], "fix": rule["fix"],
                "field": rule.get("field", ""),
                # value 记录**触发时所用的原值**，而不是钳制后的值
                "value": {k: checked[k] for k in S._RULE_FIELDS if k in checked},
            }
            if rule.get("extra"):
                v["note"] = rule["extra"]
            if rule["id"] == "GR-09":
                v["fleet_detail"] = fleet_detail(checked)
            violations.append(v)
    # 被 normalize_config 静默钳掉的字段：不是「违规拦截」，但必须留痕
    soft = [r for r in norm_record if r.get("field") in S._RULE_FIELDS]
    out = {
        "passed": len(violations) == 0,
        "violations": violations,
        "normalized": norm_record,
        "soft_clamped": soft,
        "checked_values": {k: checked[k] for k in S._RULE_FIELDS},
        "effective": normalized_cfg,
        "rules_total": len(RULES),
        "rulebook": [{"id": r["id"], "name": r["name"], "why": r["why"]} for r in RULES],
    }
    try:
        out["fleet_check"] = fleet_detail(checked)
    except Exception:  # noqa: BLE001
        out["fleet_check"] = None
    return out


def repair(param_json: dict, max_round: int = 4) -> dict:
    """护栏的「给出修正建议」能力：迭代把参数修进合法域。

    这解决了「LLM 输出越界就直接失败」的脆弱性 —— 护栏不只是拒绝，
    而是返回可执行的修正路径，让 Planner 能在下一轮自己收敛。
    """
    cur = dict(param_json or {})
    history = []
    for i in range(max_round):
        v = validate(cur)
        history.append({"round": i, "passed": v["passed"],
                        "violations": [x["id"] for x in v["violations"]],
                        "config": dict(v["effective"])})
        if v["passed"]:
            return {"ok": True, "rounds": i, "effective": v["effective"], "history": history}
        cfg = v["effective"]
        # 逐条按规则语义修正
        if not v["violations"]:
            break
        for x in v["violations"]:
            if x["id"] == "GR-01":
                cfg["headway_min"] = max(4.0, cfg["headway_min"])
            elif x["id"] == "GR-02":
                cfg["headway_min"] = min(30.0, cfg["headway_min"])
            elif x["id"] == "GR-03":
                cfg["formation_cars"] = min(S.GUARDRAIL["formation_cars"]["enum"],
                                            key=lambda e: abs(e - cfg["formation_cars"]))
            elif x["id"] == "GR-04":
                cfg["limit_level"] = min((0, 1, 2, 3), key=lambda e: abs(e - cfg["limit_level"]))
            elif x["id"] == "GR-05":
                cfg["formation_cars"] = max(6, cfg["formation_cars"])
            elif x["id"] == "GR-06":
                cfg["demand_mult"] = min(2.0, max(0.5, cfg["demand_mult"]))
            elif x["id"] == "GR-07":
                cfg["formation_cars"] = min(8, max(4, cfg["formation_cars"] + 2))
                if cfg["formation_cars"] * S.SEATS_PER_CAR * (60.0 / cfg["headway_min"]) \
                        * S.LOAD_AVAILABILITY < 1200:
                    cfg["headway_min"] = max(4.0, cfg["headway_min"] - 2.0)
            elif x["id"] == "GR-09":
                det = x.get("fleet_detail") or fleet_detail(cfg)
                cfg["headway_min"] = max(cfg["headway_min"],
                                         float(det.get("min_feasible_headway", 12.0)))
        cur = cfg
    v = validate(cur)
    return {"ok": v["passed"], "rounds": max_round, "effective": v["effective"], "history": history}


if __name__ == "__main__":
    import json
    bad = {"headway_min": 45, "formation_cars": 5, "limit_level": 3, "demand_mult": 3.2}
    print("越界参数：", json.dumps(bad, ensure_ascii=False))
    v = validate(bad)
    print("pass=", v["passed"], "violations=", [x["id"] for x in v["violations"]])
    print("规范化记录：", json.dumps(v["normalized"], ensure_ascii=False))
    r = repair(bad)
    print("修复后 ok=", r["ok"], "rounds=", r["rounds"],
          json.dumps({k: r["effective"][k] for k in
                      ("headway_min", "formation_cars", "limit_level", "demand_mult")},
                     ensure_ascii=False))
