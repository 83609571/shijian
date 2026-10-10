"""L3 智能体层 · Planner-Executor-Critic 状态机

循环结构（三轮角色分工，全部入场 trace）：

    Planner  ── 决定「下一步调用哪些工具」，产出 tool_calls（LLM 或离线确定性策略）
       ↓
    Executor ── 严格执行工具调用（护栏、仿真、读结果、敏感性、出报告），逐步落 trace
       ↓
    Critic   ── 用确定性多目标打分评估结果；判定 accept / retry
       ↓ (retry)
    Planner  ── 收到 Critic 的「不达标」理由后生成强化档方案，重入 Executor

关键工程决策：
  * 打分与判定**不交给大模型**。LLM 负责「提出方案」和「解释结果」，
    而「方案好不好」由可复算的确定性评分函数给出。
    这样即使换了模型、甚至模型当时抽风，结论也不会漂。
  * LLM 模式与离线模式共用同一个 Executor 与 Critic，只有 Planner 实现不同。
    接 API 不需要改主循环 —— 这也是「可插拔」的实际含义。
  * 强制兜底：LLM 若在 max_rounds 内没跑完链路，由确定性策略补齐剩余工具调用，
    保证交付物永远完整（不会出现「模型没说够，报告就没了」）。
"""
from __future__ import annotations

import json

from . import data_layer as dl
from . import guardrail as gl
from . import llm_client as LC
from . import schemas as S
from . import sim_adapter as sa
from . import tools as T
from .trace import TraceRecorder

WEIGHTS = {"congestion": 0.40, "service": 0.30, "cost": 0.20, "robustness": 0.10}
ACCEPT_TOTAL = 55.0
ACCEPT_CONGESTION = 35.0
# 拥堵缓解评分曲线（分段线性，锚点取自站台服务水平的工程口径）：
#   饱和度 ≤ 0.70 → 100 分（余量充足）  |  0.85 → 80 分（达标）  |  1.00 → 50 分（临界）  |  ≥ 1.30 → 0 分
SAT_ANCHORS = [(1.30, 0.0), (1.00, 50.0), (0.85, 80.0), (0.70, 100.0)]
# 未承运 + 站外滞留 占全网需求的比重每 1% 扣多少分（×4 ⇒ 25% 即归零）
UNSERVED_PENALTY = 4.0


def _congestion_score(sat: float) -> float:
    a = SAT_ANCHORS
    if sat >= a[0][0]:
        return 0.0
    if sat <= a[-1][0]:
        return 100.0
    for i in range(len(a) - 1):
        hi, shi = a[i]
        lo, slo = a[i + 1]
        if lo <= sat <= hi:
            t = (hi - sat) / (hi - lo)
            return shi + t * (slo - shi)
    return 0.0

SYSTEM_PROMPT = """你是「赣鄱智轨」枢纽拥堵治理智能体，服务于江西省通勤-旅游复合轨道交通网络。
职责：把用户的自然语言问题拆解为可执行的仿真分析任务。

工作纪律（必须遵守）：
1. 先查数据可信度（query_data_anchor）与仿真引擎状态（get_engine_status），再规划方案。
2. 任何仿真参数必须先经 guardrail_validate 校验；参数越界必须采纳修正建议，不得强行下发。
3. 需要基准对照：未治理状态必须先用 baseline_flag=true 跑一次仿真。
4. 候选方案至少要覆盖「供给端加密」与「需求端限流」两类不同范式，并给出各自取舍。
5. 推荐方案必须做 sensitivity_scan，说明结论在客流 ±20% 扰动下是否成立。
6. 最后调用 export_report_markdown 产出治理报告。
7. 不要臆造数据：所有数字必须来自工具返回结果。
"""


def _key(cfg: dict) -> tuple:
    return (round(float(cfg.get("headway_min", 0)), 2), int(cfg.get("formation_cars", 0)),
            int(cfg.get("limit_level", 0)), round(float(cfg.get("demand_mult", 1)), 3))


def _clip(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def make_reinforcement(scenario: str, existing_ids) -> list[dict]:
    """强化档方案（Critic 判定「不达标」或「最优方案被护栏拦下」时由 Planner 给出）。

    与普通候选方案的本质区别：**同步申请增购车辆**，把配车额度从 480 列提到 600 列。
    这正是被护栏 GR-09 拦下后 Planner 应该给出的正确应对 ——
    不是硬闯约束，而是把「扩容」作为一个显式的、要计代价的决策提出来。

    ★ 为什么放在循环层而不是只挂在离线规划器上 ★
      原实现只有 LocalDeterministicPlanner 有 reinforce()，于是**在线 LLM 模式下
      retry 分支永远进不去**（`hasattr(planner,'reinforce')` 为 False）——
      「不达标 → 强化档 → 重跑」这条闭环在真实大模型下会静默消失，
      最终推荐一个被自己护栏修正过的方案。实测已复现，此处改为两种模式共用。

    id 自动避让已有方案，避免与 LLM 自己生成的方案撞号导致静默去重。
    """
    used = set(existing_ids or ())
    pid = next((c for c in "DEFGHK" if c not in used), None)
    if pid is None:
        return []
    return [{
        "id": pid, "name": "强化档：增购车辆 + 8min 高密度运营",
        "rationale": "护栏 GR-09 表明 8min 间隔需配车 556 列 > 现有 480 列。"
                     "本方案显式申请增购至 600 列（+120 列），使高密度运营成为可执行方案；"
                     "代价计入资源代价分，由 Critic 与其余方案统一比较。",
        "config": {"scenario": scenario, "headway_min": 8.0, "formation_cars": 8,
                   "limit_level": 1, "demand_mult": 1.0, "fleet_limit": 600,
                   "baseline_flag": False},
    }]


class AgentLoop:
    def __init__(self, ctx: T.ToolContext, planner, trace: TraceRecorder,
                 *, scenario: str = "holiday", hub: str = "南昌站",
                 max_rounds: int = 12, max_retry: int = 1, verbose: bool = True):
        self.ctx = ctx
        self.planner = planner
        self.trace = trace
        self.scenario = scenario
        self.hub = hub
        self.max_rounds = max_rounds
        self.max_retry = max_retry
        self.verbose = verbose
        self.state: dict = {
            "user_query": "", "round": 0, "retry": 0, "tool_log": [],
            "baseline": None, "plans": [], "sensitivity": None,
            "engine_status": None, "data_anchor": None, "report_path": None,
            "recommended_plan": None, "critic_history": [], "narration": "",
            "config_cache": {},
        }

    def log(self, *a):
        if self.verbose:
            print(*a, flush=True)

    def _sens_of(self, p: dict) -> dict | None:
        """取某方案自己的敏感性扫描结果（优先按 id，退化按参数指纹）。"""
        m = self.state.get("sensitivity_by_plan") or {}
        return m.get(p["id"]) or m.get(
            _key(p.get("effective_config") or p.get("config") or {}))

    # ---- 按 plan_id 定位方案；缺 plan_id 时按参数指纹定位「第一个尚未落该字段的方案」----
    def _find_plan(self, r: dict, args: dict, field: str) -> dict | None:
        """身份定位：优先 plan_id；退化时按参数指纹 + 字段未填 双重条件。

        为什么必须这样：方案 C 与 D 只是配车额度不同，参数指纹完全相同。
        若仅按指纹匹配，D 的护栏结果会覆盖到 C 上 —— 这是实测踩到的真实缺陷。
        """
        st = self.state
        pid = r.get("plan_id") or (args or {}).get("plan_id")
        if pid:
            for p in st["plans"]:
                if p["id"] == pid:
                    return p
        src = (r.get("requested_config") or r.get("effective")
               or (args or {}).get("config_json") or (args or {}).get("base_config")
               or (args or {}).get("param_json") or {})
        k = _key(src)
        cands = [p for p in st["plans"] if _key(p["config"]) == k]
        for p in cands:
            if not p.get(field):
                return p
        return cands[0] if cands else None

    # ---------------- Executor ----------------
    def _report_plans(self) -> list[dict]:
        """把内部状态里的方案整理成报告可直接消费的形状。

        敏感性与评分分散在 state 的几个字典里，报告层不该去猜它们的存放位置 ——
        统一在这里做一次「装配」，避免出现「报告说未扫描、其实已扫描」这类自相矛盾。
        """
        st = self.state
        sens_map = st.get("sensitivity_by_plan") or {}
        out = []
        for p in st["plans"]:
            gate = p.get("guardrail_gate") or {}
            g = p.get("guardrail") or {}
            out.append({
                "id": p["id"], "name": p.get("name"), "rationale": p.get("rationale"),
                "config": p.get("config") or {},
                "effective_config": p.get("effective_config"),
                "metrics": p.get("metrics") or {},
                "score": p.get("score") or {},
                "delta": p.get("delta") or {},
                "sensitivity": self._sens_of(p),
                "guardrail": {
                    # 以「护栏闸门」的实际判定为准：它反映真正下发的参数是否合法
                    "passed": (gate.get("passed") if gate.get("passed") is not None
                               else (g.get("passed") if g else None)),
                    "violations": g.get("violations", []),
                    "normalized": g.get("normalized", []),
                    "gate": gate,
                },
            })
        return out

    def _apply(self, tool: str, args: dict, caller: str = "executor") -> dict:
        import time
        if tool == "export_report_markdown":
            args = dict(args or {})
            args["plans"] = self._report_plans()
        t0 = time.time()
        result = T.call(self.ctx, tool, args)
        ms = int((time.time() - t0) * 1000)
        self.trace.tool_call(tool, args, result, ms,
                             round_no=self.state["round"], caller=caller)
        self.state["tool_log"].append({"tool": tool, "args": args, "ok": bool(result.get("ok"))})
        self._absorb(tool, args, result)
        mark = "✓" if result.get("ok", True) else "✗"
        self.log(f"    {mark} {tool:<26} {ms:>5}ms  {self._one_line(tool, result)}")
        return result

    @staticmethod
    def _one_line(tool, r) -> str:
        if not r.get("ok", True):
            return "ERROR " + str(r.get("error"))[:90]
        if tool == "run_simulation":
            m = r["metrics"]
            return (f"engine={r['engine']} sat={m['max_saturation']} "
                    f"delay={m['avg_delay_min']}min unmet={m['unmet_persons_per_hour']}")
        if tool == "read_sim_result":
            return "contract=" + ("OK" if not r.get("contract_problems") else
                                  str(r["contract_problems"]))
        if tool == "guardrail_validate":
            return "passed" if r["passed"] else "BLOCKED " + ",".join(v["id"] for v in r["violations"])
        if tool == "sensitivity_scan":
            return f"robust={r['robust']} range={r['max_saturation_range']}"
        if tool == "export_report_markdown":
            return f"{r['chars']} chars → {r['report_path'].split('/')[-1]}"
        if tool == "query_data_anchor":
            c = r.get("credibility", {})
            return (f"公开锚点{len(r.get('public_anchors', []))}条 "
                    f"real={c.get('real_stat')}/{c.get('stations_total')}")
        if tool == "generate_candidate_plan":
            return " / ".join(f"{p['id']}:{p['config']['headway_min']}min,l{p['config']['limit_level']}"
                              for p in r["plans"])
        if tool == "get_engine_status":
            return f"active={r['active']} engineA_ok={r['engine_a']['available']}"
        return ""

    # ---- 把工具结果吸收进状态机 ----
    def _absorb(self, tool: str, args: dict, r: dict) -> None:
        st = self.state
        if not r.get("ok", True) and tool not in ("read_sim_result",):
            return
        if tool == "get_engine_status":
            st["engine_status"] = r
        elif tool == "query_data_anchor":
            st["data_anchor"] = r
        elif tool == "generate_candidate_plan":
            for p in r["plans"]:
                if not any(x["id"] == p["id"] for x in st["plans"]):
                    st["plans"].append(dict(p, guardrail=None, run_id=None,
                                            metrics=None, metrics_read=False,
                                            score=None, sensitivity=None, delta=None))
        elif tool == "config_simulation_param":
            cfg = r["config"]
            st["config_cache"][_key(cfg)] = cfg
            if cfg.get("baseline_flag"):
                st["baseline_config"] = cfg
        elif tool == "guardrail_validate":
            p = self._find_plan(r, args, "guardrail")
            if p is not None:
                p["guardrail"] = r
            else:
                st["last_guardrail"] = r
                if st.get("baseline_config") and \
                        _key(st["baseline_config"]) == _key(r.get("effective") or {}):
                    st["baseline_guardrail"] = r
        elif tool == "run_simulation":
            sres = {"run_id": r["run_id"], "metrics": r["metrics"],
                    "top_bottlenecks": r["top_bottlenecks"], "engine": r["engine"],
                    "engine_label": r["engine_label"], "engine_detail": r["engine_detail"],
                    "result_path": r["result_path"], "config": r["config"]}
            cfg = r["config"]
            gate = r.get("guardrail_gate") or {}
            if cfg.get("baseline_flag") and st.get("baseline") is None:
                st["baseline"] = sres
                st["baseline"]["guardrail_gate"] = gate
            else:
                p = self._find_plan(r, args, "run_id")
                if p is not None:
                    p.update(run_id=r["run_id"], metrics=r["metrics"],
                             top_bottlenecks=r["top_bottlenecks"],
                             result_path=r["result_path"], engine=r["engine"],
                             effective_config=cfg, guardrail_gate=gate)
                else:
                    st.setdefault("extra_runs", []).append(sres)
        elif tool == "read_sim_result":
            rid = r.get("run_id")
            for p in st["plans"]:
                if p.get("run_id") == rid:
                    p["metrics_read"] = True
                    p["contract_problems"] = r.get("contract_problems", [])
            if st.get("baseline") and st["baseline"].get("run_id") == rid:
                st["baseline"]["contract_problems"] = r.get("contract_problems", [])
        elif tool == "sensitivity_scan":
            pid = r.get("plan_id") or (args or {}).get("plan_id")
            st.setdefault("sensitivity_by_plan", {})[pid or _key(
                (args or {}).get("base_config") or {})] = r
            st["sensitivity"] = r          # 兼容：最后一次扫描结果
        elif tool == "export_report_markdown":
            st["report_path"] = r.get("report_path")
            st["report_done"] = True

    # ---------------- Critic ----------------
    def _score_plan(self, p: dict) -> dict:
        st = self.state
        b = (st.get("baseline") or {}).get("metrics") or {}
        m = p.get("metrics") or {}
        if not m or not b:
            return {}
        eps = 1e-9
        ref_demand = (b.get("throughput_persons_per_hour", 0)
                      + b.get("unmet_persons_per_hour", 0)) or 1
        base_sat = b.get("max_saturation", 1.0)
        sat = m.get("max_saturation", 1.0)
        base_delay = max(b.get("avg_delay_min", 1.0), 1e-6)
        delay = m.get("avg_delay_min", 0.0)
        base_e = max(b.get("energy_kwh_per_day", 1.0), 1.0)
        energy = m.get("energy_kwh_per_day", 0.0)
        base_t = max(b.get("required_trains", 1), 1)
        trains = max(m.get("required_trains", 1), 1)

        # ① 拥堵缓解：分段线性评分（0.70 满分 / 0.85 达标 / 1.00 临界 / ≥1.30 零分）
        congestion = _congestion_score(sat)
        # ② 服务水平：未承运 + 站外滞留 双重记账（限流的代价必须计入）
        unserved = (m.get("unmet_persons_per_hour", 0)
                    + m.get("deferred_persons_per_hour", 0))
        service = 100 * _clip(1 - (unserved / ref_demand) * UNSERVED_PENALTY
                              - max(0.0, delay / base_delay - 1.0) * 0.5)
        # ③ 资源代价：牵引能耗 + 配车需求（增购车辆不是免费的）
        cost_ratio = 0.5 * (energy / base_e) + 0.5 * (trains / base_t)
        cost_score = 100 * _clip(2 - cost_ratio)
        # ④ 稳健性：每个方案各自做过敏感性扫描，用各自的实测值 ——
        #    避免「A 验证过，B 也搭便车拿高分」这类评分偏差。
        sens = self._sens_of(p)
        if sens:
            worst = max(c["max_saturation"] for c in sens.get("cases", [])) if sens.get("cases") else sat
            robustness = 100 * _clip(1 - max(0.0, worst - 1.0) / 0.5)
        else:
            robustness = 60.0  # 未做敏感性 → 按保守值计，避免"没验证=满分"
        total = (WEIGHTS["congestion"] * congestion + WEIGHTS["service"] * service
                 + WEIGHTS["cost"] * cost_score + WEIGHTS["robustness"] * robustness)
        return {"congestion": round(congestion, 1), "service": round(service, 1),
                "cost": round(cost_score, 1), "robustness": round(robustness, 1),
                "total": round(total, 1),
                "required_trains": trains, "energy_kwh_per_day": round(energy)}

    def _delta(self, p: dict) -> dict:
        b = (self.state.get("baseline") or {}).get("metrics") or {}
        m = p.get("metrics") or {}
        if not m or not b:
            return {}
        d = {}
        def chg(k, label, unit, better_low=True, nd=3):
            bv, pv = b.get(k), m.get(k)
            if bv in (None, 0) or pv is None:
                return
            dd = (pv - bv) / abs(bv) * 100
            arrow = "↓" if dd < 0 else "↑"
            good = (dd < 0) if better_low else (dd > 0)
            d[label] = f"{arrow}{abs(dd):.1f}%（{bv:,.{nd}f} → {pv:,.{nd}f}）{'✓' if good else '⚠'}"
        chg("max_saturation", "站台最大饱和度", "—")
        chg("avg_delay_min", "平均延误", "min", nd=2)
        chg("max_queue_persons", "最大积压", "人", nd=0)
        chg("unmet_persons_per_hour", "未承运客流", "人/h", nd=0)
        chg("energy_kwh_per_day", "牵引能耗", "kWh/日", better_low=True, nd=0)
        return d

    def _critique(self) -> str:
        st = self.state
        if st.get("baseline") is None or not st.get("plans"):
            return "continue"
        scored = [p for p in st["plans"] if p.get("metrics")]
        if not scored:
            return "continue"
        # 硬性完备性：任一候选方案尚未完成仿真，就必须继续（不允许"漏评"就出结论）
        unrun = [p["id"] for p in st["plans"] if not p.get("run_id")]
        if unrun:
            self.trace.critic("continue", {"unrun": unrun},
                              f"候选方案 {'/'.join(unrun)} 尚未完成仿真，继续执行")
            self.log(f"  ◆ Critic: 待仿真方案 {unrun}")
            return "continue"

        # 敏感性：所有方案逐个扫描（各自独立，互不搭便车）
        sens_map = st.get("sensitivity_by_plan") or {}
        pending = [p for p in scored if self._sens_of(p) is None]
        for p in scored:
            p["score"] = self._score_plan(p) or p.get("score") or {}
            p["delta"] = self._delta(p) or p.get("delta") or {}
        if pending:
            best_now = max(scored, key=lambda p: (p.get("score") or {}).get("total", 0))
            st["recommended_plan"] = best_now
            st["narration"] = self._narrate(best_now)
            self.trace.critic("continue", {p["id"]: p["score"] for p in scored},
                              f"尚有 {len(pending)} 个方案未做敏感性扫描"
                              f"（{'/'.join(p['id'] for p in pending)}），本轮继续补齐")
            self.log(f"  ◆ Critic: 待补敏感性扫描 {[p['id'] for p in pending]}")
            return "continue"

        best = max(scored, key=lambda p: (p.get("score") or {}).get("total", 0))
        st["recommended_plan"] = best
        st["narration"] = self._narrate(best)
        reason = (f"推荐 {best['id']}（总分 {best['score'].get('total')}）；"
                  f"护栏{'通过' if (best.get('guardrail') or {}).get('passed') else '拦截-已修正'}；"
                  f"敏感性已完成（{len(sens_map)} 个方案）")
        self.trace.critic("evaluate", {p["id"]: p["score"] for p in scored}, reason)
        self.log(f"  ◆ Critic: {reason}")

        if st.get("report_done"):
            return "done"
        total = (best.get("score") or {}).get("total", 0)
        congr = (best.get("score") or {}).get("congestion", 0)
        # ---- 判定「为何不达标」：逐条列出**真实成立**的条件 ----
        # 原实现把三个条件用「或」拼成一句硬编码文案，无论哪条成立都照念全文，
        # 于是出现了「总分 75.9 < 阈值 55.0」这种自相矛盾的日志（实测已复现）。
        # 结论要能复核，日志就不能含糊——这里改成逐条陈述。
        reasons = []
        g_passed = (best.get("guardrail") or {}).get("passed")
        if g_passed is False:
            reasons.append(f"最优方案 {best['id']} 的参数触发护栏拦截"
                           f"（{best['id']} 是经修正后才跑通的，不能作为直接推荐）")
        if total < ACCEPT_TOTAL:
            reasons.append(f"总分 {total} < 阈值 {ACCEPT_TOTAL}")
        if congr < ACCEPT_CONGESTION:
            reasons.append(f"拥堵缓解分 {congr} < {ACCEPT_CONGESTION}")
        ok = not reasons
        if ok:
            # 结论已达标，但**报告尚未导出** —— 交付物不完备就不能结束
            return "continue"

        if st["retry"] < self.max_retry:
            add = self._escalate()
            added = []
            for p in add:
                if any(x["id"] == p["id"] for x in st["plans"]):
                    continue
                st["plans"].append(dict(p, guardrail=None, run_id=None, metrics=None,
                                        metrics_read=False, score=None,
                                        sensitivity=None, delta=None))
                added.append(p["id"])
            if added:
                rtxt = "；".join(reasons)
                self.trace.critic("retry",
                                  {"round": st["round"], "new_plans": added,
                                   "reasons": reasons, "best": best["id"],
                                   "best_total": total, "best_congestion": congr},
                                  f"{rtxt}；生成强化档方案 {'/'.join(added)} 重入仿真")
                self.log("  ◆ Critic: 不达标（" + rtxt + f"）→ 新增强化档 {'/'.join(added)} 重跑")
                # 在线 LLM 模式：把 Critic 的判定作为指令回灌，让 Planner 下一轮知情
                st.setdefault("planner_directives", []).append(
                    "【Critic 裁定：上一轮结论不成立】" + rtxt +
                    f"。已加入强化档方案 {'/'.join(added)}（同步申请增购车辆），"
                    "请在下一轮为其执行护栏校验、仿真、读结果与敏感性扫描；"
                    "不要重复调用已完成的工具，也不要改动既有方案。")
                st["retry"] += 1
                return "retry"
        # retry 预算用尽仍不达标 → 如实接受，并在 trace 中标注风险（不假装达标）
        self.trace.critic("accept_with_risk",
                          {"round": st["round"], "best": best["id"], "reasons": reasons,
                           "retry_used": st["retry"]},
                          "重试预算已用尽，按当前最优方案出结论；不达标原因已在报告中标注："
                          + "；".join(reasons))
        self.log("  ◆ Critic: 重试预算用尽，按 " + best["id"] + " 出结论（风险已标注）")
        return "accept"

    def _escalate(self) -> list[dict]:
        """生成强化档方案：优先用 Planner 自己的实现，缺失时用循环层的通用实现。

        在线 LLM 客户端的职责边界是"提出方案"——它原则上应由 LLM 自己给出强化档；
        但为保证闭环在任何 provider 下都不消失（评委现场断网/换模型也要能演示），
        这里必须有确定性路径兜底。
        """
        if hasattr(self.planner, "reinforce"):
            ids = [p["id"] for p in self.state["plans"]]
            try:
                got = self.planner.reinforce(ids)
            except TypeError:          # 兼容不支持 existing_ids 参数的旧签名
                got = self.planner.reinforce()
            if got:
                return got
        return make_reinforcement(self.scenario, [p["id"] for p in self.state["plans"]])

    def _narrate(self, rec: dict) -> str:
        st = self.state
        b = (st.get("baseline") or {}).get("metrics") or {}
        m = rec.get("metrics") or {}
        top = (st.get("baseline") or {}).get("top_bottlenecks") or []
        cfg = rec.get("config") or {}
        a = st.get("data_anchor") or {}
        c_ = a.get("credibility", {}) or {}
        anchor_names = "、".join(x.get("name", "") for x in (a.get("public_anchors") or [])[:4])
        head = "—"
        if top:
            head = f"{top[0]['name']}（饱和度 {top[0]['saturation']:.3f}，瓶颈环节：" \
                   f"{'站台容量' if top[0]['binding'] == 'platform' else '换乘通道'}）"
        return (
            f"1）问题定位：基准（未治理）状态下全网最紧约束为 {head}；"
            f"全网站台最大饱和度 {b.get('max_saturation')}，最大积压 {b.get('max_queue_persons')} 人，"
            f"平均延误 {b.get('avg_delay_min')} 分钟。\n"
            f"2）方案生成：按「供给端加密 / 需求端限流 / 增购扩容」三类范式生成候选参数，"
            f"全部先经 9 条确定性护栏校验再仿真 —— 越界参数不允许直接下发，"
            f"由护栏给出修正路径后执行，trace 中同时保留请求值与修正值。\n"
            f"3）方案取舍：推荐方案 {rec['id']}「{rec.get('name')}」，执行参数为发车间隔 "
            f"{cfg.get('headway_min')} min、编组 {cfg.get('formation_cars')} 辆、限流 "
            f"{cfg.get('limit_level')} 级。治理后站台最大饱和度 {m.get('max_saturation')}，"
            f"平均延误 {m.get('avg_delay_min')} 分钟，断面未承运 {m.get('unmet_persons_per_hour')} 人/小时，"
            f"限流站外滞留 {m.get('deferred_persons_per_hour')} 人/小时。\n"
            f"4）目标权衡：限流能压住站台集聚，但会把压力转为「站外滞留」；加密能同时改善拥堵与延误，"
            f"但直接消耗配车并推高牵引能耗。多目标打分（拥堵缓解 0.4 / 服务水平 0.3 / 资源代价 0.2 / "
            f"稳健性 0.1）正是把这一取舍显式化，而不是靠专家直觉拍板。\n"
            f"5）数据可信度（主动披露局限）：全网 {c_['stations_total']} 个站点中 "
            f"{c_['real_stat']} 个直接采用公开统计口径，其余 {c_['simulated']} 个为**仿真推演值**，"
            f"推演过程锚定 {len(a.get('public_anchors', []))} 条公开统计数据（{anchor_names}），"
            f"逐站推演依据见 `data/flow_*.json` 的 anchor 字段。"
            f"本报告不主张这些站点的数值等同于实测，{c_['with_basis']} 个站点均标注了推演依据以便复核。"
        )

    # ---------------- 组装交付文档 ----------------
    def _agents(self) -> list[dict]:
        st = self.state
        b = (st.get("baseline") or {}).get("metrics") or {}
        rec = st.get("recommended_plan") or {}
        m = rec.get("metrics") or {}
        cfg = rec.get("effective_config") or rec.get("config") or {}
        top = (st.get("baseline") or {}).get("top_bottlenecks") or []
        nb = top[0] if top else {}
        sens = st.get("sensitivity") or {}
        flow_top = (st.get("data_anchor") or {}).get("network", {})
        return [
            {"id": "warning", "name": "灾害与拥堵预警智能体", "rt": "≤3 秒",
             "act": f"{nb.get('name', '枢纽')}站台饱和度 **{nb.get('saturation', '—')}**，"
                    f"判定**大客流橙色预警**",
             "extra": f"瓶颈环节：{'站台容量' if nb.get('binding') == 'platform' else '换乘通道'} · "
                      f"最大积压 {b.get('max_queue_persons', '—')} 人"},
            {"id": "maint", "name": "运力配置智能体", "rt": "≤5 秒",
             "act": f"全网编组统一 **{cfg.get('formation_cars', '—')} 辆**，"
                    f"按线路属性差异化发车间隔（基准通勤 8min / 旅游 15min）",
             "extra": f"牵引能耗 {m.get('energy_kwh_per_day', '—')} kWh/日（基准 "
                      f"{b.get('energy_kwh_per_day', '—')}）"},
            {"id": "rescue", "name": "应急联动智能体", "rt": "≤5 秒",
             "act": f"执行**方案 {rec.get('id', '—')}**：{rec.get('name', '—')}；"
                    f"限流 **{cfg.get('limit_level', '—')} 级**，发车间隔 **{cfg.get('headway_min', '—')} min**",
             "extra": "三级限流时强制配套 ≥6 辆编组疏运（护栏 GR-05）"},
            {"id": "flow", "name": "客流预测智能体", "rt": "≤10 秒",
             "act": f"治理后最大饱和度 **{m.get('max_saturation', '—')}**"
                    f"（基准 {b.get('max_saturation', '—')}），平均延误 **{m.get('avg_delay_min', '—')} min**",
             "extra": f"扰动稳健性：{sens.get('verdict', '未扫描')}"},
        ]

    def _risk_segments(self) -> list[list[list[float]]]:
        """由**真实拓扑**推出风险段：取瓶颈站点所连的流量最大两条区间。"""
        st = self.state
        st_all = {s["name"]: s for s in dl.stations(self.scenario)}
        top = [x["name"] for x in ((st.get("baseline") or {}).get("top_bottlenecks") or [])[:3]]
        segs = dl.read_scenario(self.scenario).get("segments", [])
        out = []
        for nm in top[:2]:
            cand = [s for s in segs if s["from"] == nm or s["to"] == nm]
            cand.sort(key=lambda s: -s["flow"])
            for s in cand[:1]:
                a, b = st_all.get(s["from"]), st_all.get(s["to"])
                if a and b:
                    out.append([[a["lng"], a["lat"]], [b["lng"], b["lat"]]])
        return out

    def _reroute(self) -> list[list[float]]:
        """绕行路径：经换乘枢纽绕开最紧约束段（取方案文本口径：三清山→上饶→龙虎山）。"""
        st_all = {s["name"]: s for s in dl.stations(self.scenario)}
        names = ["三清山站", "上饶站", "龙虎山站"]
        pts = [[st_all[n]["lng"], st_all[n]["lat"]] for n in names if n in st_all]
        return pts if len(pts) >= 2 else []

    def _finalize(self) -> dict:
        st = self.state
        rec = st.get("recommended_plan") or {}
        engine_meta = self.trace.meta.get("engine", {})
        plans_out = []
        for p in st["plans"]:
            g = p.get("guardrail") or {}
            gate = p.get("guardrail_gate") or {}
            plans_out.append({
                "id": p["id"], "name": p.get("name"), "rationale": p.get("rationale"),
                "config": {kk: vv for kk, vv in (p.get("config") or {}).items()
                           if not kk.startswith("_")},
                "effective_config": p.get("effective_config"),
                "guardrail": {"passed": g.get("passed") if gate.get("passed") is None
                              else gate.get("passed"),
                              "violations": g.get("violations", []),
                              "normalized": g.get("normalized", []),
                              "gate": gate},
                "run_id": p.get("run_id"), "metrics": p.get("metrics") or {},
                "score": p.get("score") or {}, "delta": p.get("delta") or {},
                "sensitivity": self._sens_of(p),
            })
        baseline_out = None
        if st.get("baseline"):
            baseline_out = {"config": st["baseline"].get("config"),
                            "run_id": st["baseline"].get("run_id"),
                            "metrics": st["baseline"].get("metrics"),
                            "top_bottlenecks": st["baseline"].get("top_bottlenecks")}
        scenario_label = ("节假日大客流 · 枢纽换乘拥堵治理" if self.scenario == "holiday"
                          else "工作日通勤高峰 · 枢纽换乘拥堵治理")
        return S.decision_document(
            engine={**engine_meta,
                    "sim": sa.engine_status(),
                    "loop": "Planner-Executor-Critic",
                    "tools_registered": len(T.TOOL_NAMES)},
            scenario={"id": f"{self.scenario}_hub_congestion", "label": scenario_label,
                      "transport_scenario": self.scenario, "hub": self.hub},
            parsed={"user_query": st.get("user_query"),
                    "intent": "hub_congestion_relief",
                    "sub_questions": ["瓶颈定位", "候选方案生成与护栏校验",
                                      "方案仿真对比", "多目标排序", "敏感性验证"],
                    "data_credibility": (st.get("data_anchor") or {}).get("credibility"),
                    "network": (st.get("data_anchor") or {}).get("network")},
            baseline=baseline_out, plans=plans_out,
            recommended=rec.get("id"),
            agents=self._agents(),
            risk_segments=self._risk_segments(),
            reroute=self._reroute(),
            trace_meta={**self.trace.summary(), "critic_history": st.get("critic_history")},
            narration=st.get("narration", ""),
        )

    # ---------------- 主循环 ----------------
    def run(self, user_query: str) -> tuple[dict, TraceRecorder]:
        st = self.state
        st["user_query"] = user_query
        self.log(f"\n【Planner】用户问题：{user_query}")
        self.trace.phase("planner", "start", {"user_query": user_query,
                                              "planner": getattr(self.planner, "name", "?"),
                                              "loop": "Planner-Executor-Critic"})

        if isinstance(self.planner, LC.LocalDeterministicPlanner):
            self._run_local(user_query)
        else:
            self._run_llm(user_query)

        # 交付物完备性兜底：无论走哪条路径，报告都必须产出
        if not self.state.get("report_done") and self.state.get("recommended_plan"):
            self.log("  • 交付物兜底：强制导出治理报告")
            self.trace.phase("executor", "report_guarantee",
                             {"reason": "主循环结束时报告尚未导出，强制补齐"})
            rec = self.state["recommended_plan"]
            self._apply("export_report_markdown",
                        {"baseline": self.state.get("baseline") or {},
                         "plans": self.state.get("plans") or [],
                         "recommended": rec["id"],
                         "narration": self.state.get("narration", "")},
                        caller="report_guarantee")

        doc = self._finalize()
        st["critic_history"] = [e for e in self.trace.events if e.get("kind") == "critic"]
        doc["trace"]["critic_history"] = st["critic_history"]
        self.trace.phase("critic", "finish", {"recommended": doc.get("recommended"),
                                              "plans": [p["id"] for p in doc["plans"]]})
        return doc, self.trace

    def _run_local(self, user_query: str) -> None:
        for rnd in range(1, self.max_rounds + 1):
            st = self.state
            st["round"] = rnd
            dec = self.planner.decide(st)
            calls = dec.get("tool_calls") or []
            self.log(f"  ▸ 第 {rnd} 轮 Planner 决定调用 {len(calls)} 个工具")
            self.trace.phase("planner", f"round_{rnd}",
                             {"mode": "local", "n_calls": len(calls),
                              "content": dec.get("content"),
                              "tools": [c["name"] for c in calls]})
            if not calls:
                break
            for c in calls:
                self._apply(c["name"], c.get("arguments") or {})
            verdict = self._critique()
            if verdict in ("done", "accept"):
                self.trace.phase("executor", "loop_end", {"verdict": verdict, "round": rnd})
                break

    def _run_llm(self, user_query: str) -> None:
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_query}]
        for rnd in range(1, self.max_rounds + 1):
            st = self.state
            st["round"] = rnd
            # 把 Critic 的裁定回灌给 Planner（强化档指令），让它在真实 LLM 下也能知情
            pend = st.pop("planner_directives", None)
            for d in (pend or []):
                messages.append({"role": "user", "content": d})
            try:
                resp = self.planner.chat(messages, tools=T.AGENT_TOOLS)
            except Exception as e:  # noqa: BLE001
                self.log(f"  ! LLM 调用失败：{type(e).__name__}: {e} → 转确定性兜底")
                self.trace.phase("planner", f"round_{rnd}",
                                 {"mode": "llm", "error": f"{type(e).__name__}: {e}",
                                  "fallback": "deterministic_completion"})
                self._deterministic_completion()
                return
            calls = resp.get("tool_calls") or []
            self.trace.llm_call(getattr(self.planner, "name", "llm"),
                                getattr(self.planner, "name", "llm"),
                                len(messages), calls, resp.get("content"),
                                resp.get("duration_ms", 0),
                                mode="llm")
            self.log(f"  ▸ 第 {rnd} 轮 Planner 返回 {len(calls)} 个工具调用"
                     f"（{(resp.get('duration_ms') or 0)/1000:.1f}s）")
            if not calls:
                if resp.get("content"):
                    st["narration"] = st.get("narration") or resp["content"]
                break
            # ★ 兜底 tool_call_id 必须全局唯一 ★
            # 原实现回退为 f"call_{i}"（轮内编号）：若某轮 LLM 不返回 id，
            # 第 1 轮的 call_0 会与第 2 轮的 call_0 撞号，assistant/tool 两侧
            # 的对应关系被破坏（严格的 OpenAI 兼容网关会直接报 400）。
            # 这里把轮次编进 id，保证跨轮唯一，且两侧用同一份 id 列表。
            call_ids = [c.get("id") or f"call_r{rnd}_{i}" for i, c in enumerate(calls)]
            messages.append({"role": "assistant", "content": resp.get("content") or "",
                             "tool_calls": [{"id": call_ids[i], "type": "function",
                                             "function": {"name": c["name"],
                                                          "arguments": json.dumps(
                                                              c.get("arguments") or {},
                                                              ensure_ascii=False)}}
                                            for i, c in enumerate(calls)]})
            for i, c in enumerate(calls):
                res = self._apply(c["name"], c.get("arguments") or {}, caller="executor")
                messages.append({"role": "tool", "tool_call_id": call_ids[i],
                                 "content": json.dumps(res, ensure_ascii=False, default=str)[:6000]})
            verdict = self._critique()
            if verdict in ("done", "accept"):
                break
        # 兜底：LLM 未跑完链路时，用确定性策略补齐，保证交付物完整
        if not self.state.get("report_done"):
            self.log("  ⚠ LLM 未跑完完整链路 → 启用确定性补齐（deterministic completion）")
            self.trace.phase("executor", "deterministic_completion",
                             {"reason": "LLM 轮次/输出不足，补齐剩余工具调用以保证交付物完整"})
            self._deterministic_completion()

    def _deterministic_completion(self) -> None:
        """用离线策略补齐缺失的工具调用。

        ★ 为什么必须把 _critique() 的返回值接住 ★
          原实现调用 _critique() 但丢弃其返回值，于是当 Critic 判定「retry」、
          往 state 里塞入强化档方案 D 之后，循环已经结束 —— D 永远不会被护栏校验、
          不会被仿真，直接进入 _finalize()，表现为「方案 D 所有指标为空」。
          实测已复现。这里改为按裁定继续迭代，保证新加入的方案也被完整跑通。
        """
        planner = LC.LocalDeterministicPlanner(self.scenario, self.hub)
        for _ in range(6):
            dec = planner.decide(self.state)
            calls = dec.get("tool_calls") or []
            for c in calls:
                self._apply(c["name"], c.get("arguments") or {}, caller="deterministic_completion")
            verdict = self._critique()
            if verdict in ("done", "accept"):
                return
            if not calls and verdict != "retry":
                return
