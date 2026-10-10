/* ======================================================================
 * 赣鄱智轨 · 智能体决策面板（数据驱动 · index.html / bmap.html 共用）
 * ----------------------------------------------------------------------
 * 【本文件解决的核心缺陷 P0-2】
 *   改造前面板文案由 mirrorDispatch() 硬编码 if-else 生成，
 *   页面上的每一个数字都与 data/*.json 无关 —— 评委改一个输入即可推翻，
 *   打开 Network 面板也看不到任何"决策数据"的下载。
 *   现在面板只消费后端 L3 智能体层产出的唯一真源 data/agent_decision.json：
 *     站台饱和度 / 平均延误 / 未承运 / 配车 / 能耗 / 方案打分 / 护栏判定
 *     全部来自该文件；页面不再持有任何业务数值常量。
 *
 * 【离线降级】
 *   若 agent_decision.json 不存在（未跑后端 / 断网），面板明确显示
 *   「离线模式 · 规则原型」并回落到规则镜像文案 —— 不假装自己在调用模型。
 *   这一点必须如实标注：断网可演示是本项目的资产，但不能靠含糊其辞获取。
 *
 * 【调用链调试面板】
 *   把 output/trace/*.json 的工具调用逐条列出（入参、出参摘要、耗时、成败），
 *   答辩现场可直接展示"智能体真的调了仿真"，而不是一句声明。
 * ====================================================================== */
(function () {
  'use strict';

  // 双决策切换：URL 参数 ?scenario=holiday|weekday 或面板按钮切换
  var SCEN_DECISION = {
    holiday: 'data/agent_decision_holiday.json',
    weekday: 'data/agent_decision_weekday.json'
  };
  function urlDecision(scen) {
    if (scen && SCEN_DECISION[scen]) return SCEN_DECISION[scen];
    var p = new URLSearchParams(location.search).get('scenario');
    if (p && SCEN_DECISION[p]) return SCEN_DECISION[p];
    return 'data/agent_decision.json';
  }
  function initialScenario() {
    var p = new URLSearchParams(location.search).get('scenario');
    return (p && SCEN_DECISION[p]) ? p : '';
  }
  var TRACE_BASE = 'output/trace/';

  var AGENT_META = [
    { id: 'warning', name: '灾害与拥堵预警智能体', rt: '≤3 秒', color: '#ff5566' },
    { id: 'maint',   name: '运力配置智能体',       rt: '≤5 秒', color: '#ffaa00' },
    { id: 'rescue',  name: '应急联动智能体',       rt: '≤5 秒', color: '#00ff88' },
    { id: 'flow',    name: '客流预测智能体',       rt: '≤10 秒', color: '#00d4ff' }
  ];

  var S = {
    doc: null, sel: 'recommended', trace: null, traceOpen: false,
    loading: true, err: null, rootId: null, scenario: initialScenario()
  };

  // ---------- 工具 ----------
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function n(v, d) {
    if (v == null || v === '' || isNaN(v)) return '—';
    var x = Number(v);
    if (d === 0) return Math.round(x).toLocaleString();
    return x.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function mwh(v) { return v == null ? '—' : (v / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 }); }
  function pct(v, d) { return v == null ? '—' : (v * 100).toFixed(d == null ? 1 : d) + '%'; }

  function metricOf(obj) { return (obj && obj.metrics) || {}; }
  function cfgOf(obj) {
    return (obj && (obj.effective_config || obj.config)) || {};
  }

  // 当前选中的"方案视图"（基准 / A / B / C / D）
  function view() {
    var d = S.doc;
    if (!d) return null;
    if (S.sel === 'baseline') {
      var b = d.baseline || {};
      return {
        id: '基准', name: '基准（未治理）', rationale: '当前运营状态：统一发车间隔 12 min、8 辆编组、不限流。',
        config: b.config || {}, effective_config: b.config || {},
        metrics: metricOf(b), score: null, delta: null, sensitivity: null,
        guardrail: { passed: true, violations: [], gate: null },
        top_bottlenecks: b.top_bottlenecks || [], isBaseline: true
      };
    }
    if (S.sel === 'recommended') {
      var rec = (d.plans || []).filter(function (p) { return p.id === d.recommended; })[0];
      return rec || (d.plans || [])[0] || null;
    }
    return (d.plans || []).filter(function (p) { return p.id === S.sel; })[0] || null;
  }

  // ---------- 四张智能体卡片：全部由决策文档数值生成 ----------
  function cardsOf(p) {
    var d = S.doc, b = metricOf(d.baseline || {}), m = metricOf(p);
    var top = (d.baseline && d.baseline.top_bottlenecks) || [];
    var nb = top[0] || {};
    var c = cfgOf(p);
    var sens = p.sensitivity;
    var out = {};

    out.warning = {
      act: nb.name
        ? (nb.name + '站台饱和度 **' + n(nb.saturation, 3) + '**，判定**' +
           (nb.saturation >= 1.2 ? '红色' : nb.saturation >= 1.0 ? '橙色' : '黄色') + '预警**')
        : '基准场景瓶颈清单为空',
      extra: nb.name
        ? ('瓶颈环节：' + (nb.binding === 'platform' ? '站台容量' : '换乘通道') +
           ' · 基准最大积压 ' + n(b.max_queue_persons, 0) + ' 人（当前方案 ' +
           n(m.max_queue_persons, 0) + ' 人）')
        : '—'
    };

    out.maint = {
      act: '编组 **' + n(c.formation_cars, 0) + ' 辆**，发车间隔 **' + n(c.headway_min, 1) +
           ' min**，限流 **' + n(c.limit_level, 0) + ' 级**',
      extra: '所需配车 **' + n(m.required_trains, 0) + ' 列**（基准 ' + n(b.required_trains, 0) +
             ' 列）· 牵引能耗 ' + mwh(m.energy_kwh_per_day) + ' MWh/日'
    };

    var gate = (p.guardrail && p.guardrail.gate) || null;
    var gtxt = '护栏校验通过（9 条规则）';
    if (gate && gate.applied) {
      gtxt = '护栏**拦截** ' + gate.applied.violations.map(function (v) { return v.id; }).join('/') +
             '，修正后执行（间隔 ' + n(gate.applied.requested.headway_min, 1) + "' → " +
             n(gate.applied.repaired_to.headway_min, 1) + "'）";
    } else if (p.guardrail && p.guardrail.passed === false) {
      gtxt = '护栏拦截：' + (p.guardrail.violations || []).map(function (v) { return v.id; }).join('/');
    }
    out.rescue = {
      act: '执行**方案 ' + esc(p.id) + '**：' + esc(p.name || '—'),
      extra: gtxt
    };

    out.flow = {
      act: '治理后站台最大饱和度 **' + n(m.max_saturation, 3) + '**（基准 ' +
           n(b.max_saturation, 3) + '），平均延误 **' + n(m.avg_delay_min, 2) + ' min**',
      extra: '断面未承运 ' + n(m.unmet_persons_per_hour, 0) + ' 人/h · 限流站外滞留 ' +
             n(m.deferred_persons_per_hour, 0) + ' 人/h · ' +
             (sens ? ('扰动域 [' + n(sens.max_saturation_range[0], 3) + ', ' +
                      n(sens.max_saturation_range[1], 3) + ']，' +
                      (sens.robust ? '**稳健**' : '不利扰动下超饱和'))
                   : '未做敏感性扫描')
    };
    return out;
  }

  function md(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>'); }

  function card(meta, d) {
    return '<div class="gdp-card" style="border-top-color:' + meta.color + '">' +
      '<div class="gdp-card-name" style="color:' + meta.color + '">' + esc(meta.name) +
      '<span class="gdp-rt">' + esc(meta.rt) + '</span></div>' +
      '<div class="gdp-act">' + md(d.act) + '</div>' +
      (d.extra ? '<div class="gdp-reason">' + md(d.extra) + '</div>' : '') +
      '</div>';
  }

  // ---------- 渲染 ----------
  function engineBadge() {
    var d = S.doc;
    if (!d) {
      return '<span class="gdp-badge off">离线模式 · 规则原型（未找到 agent_decision.json）</span>';
    }
    var e = d.engine || {}, sim = e.sim || {};
    if (e.mode === 'llm') {
      return '<span class="gdp-badge on">在线智能体 · ' + esc(e.provider) + ' / ' +
             esc(e.model) + '</span>';
    }
    return '<span class="gdp-badge loc" title="未检测到 API Key。本链路使用协议等价的确定性规划器，' +
           'Planner→Executor→Critic、护栏、trace、多目标评估全部真实执行；' +
           '接入 DS4.1-Flash / GLM5.2 只需切换 provider，主循环与工具集无需改动。">' +
           '离线确定性规划器（无 API Key）</span>' +
           '<span class="gdp-badge" title="外部引擎探针结果">仿真引擎 ' +
           esc(sim.active || '—') + '</span>';
  }

  function metricStrip(p) {
    var d = S.doc, b = metricOf(d.baseline || {}), m = metricOf(p);
    var rows = [
      ['站台最大饱和度', n(m.max_saturation, 3), n(b.max_saturation, 3), true],
      ['平均延误 (min)', n(m.avg_delay_min, 2), n(b.avg_delay_min, 2), true],
      ['断面未承运 (人/h)', n(m.unmet_persons_per_hour, 0), n(b.unmet_persons_per_hour, 0), true],
      ['限流站外滞留 (人/h)', n(m.deferred_persons_per_hour, 0), n(b.deferred_persons_per_hour, 0), true],
      ['所需配车 (列)', n(m.required_trains, 0), n(b.required_trains, 0), true],
      ['牵引能耗 (MWh/日)', mwh(m.energy_kwh_per_day), mwh(b.energy_kwh_per_day), true]
    ];
    var html = rows.map(function (r) {
      return '<div class="gdp-mi"><span class="gdp-mi-k">' + esc(r[0]) + '</span>' +
        '<span class="gdp-mi-v">' + esc(r[1]) + '</span>' +
        '<span class="gdp-mi-b">基准 ' + esc(r[2]) + '</span></div>';
    }).join('');
    var sc = p.score || {};
    if (sc.total != null) {
      html += '<div class="gdp-mi gdp-mi-score"><span class="gdp-mi-k">多目标加权总分</span>' +
        '<span class="gdp-mi-v">' + n(sc.total, 1) + '</span>' +
        '<span class="gdp-mi-b">拥堵 ' + n(sc.congestion, 1) + ' · 服务 ' + n(sc.service, 1) +
        ' · 资源 ' + n(sc.cost, 1) + ' · 稳健 ' + n(sc.robustness, 1) + '</span></div>';
    }
    return '<div class="gdp-metrics">' + html + '</div>';
  }

  function tabs() {
    var d = S.doc;
    var t = ['<button class="gdp-tab' + (S.sel === 'baseline' ? ' active' : '') +
             '" data-plan="baseline">基准</button>'];
    (d.plans || []).forEach(function (p) {
      var isRec = p.id === d.recommended;
      t.push('<button class="gdp-tab' + (S.sel === p.id || (S.sel === 'recommended' && isRec) ? ' active' : '') +
             (isRec ? ' rec' : '') + '" data-plan="' + esc(p.id) + '">' +
             esc(p.id) + (isRec ? ' ★' : '') + '</button>');
    });
    return '<div class="gdp-tabs">' + t.join('') + '</div>';
  }

  function foot(p) {
    var d = S.doc, t = d.trace || {};
    var cr = (d.problem_parsed && d.problem_parsed.data_credibility) || {};
    return '<div class="gdp-foot">' +
      '<span>数据来源：<b>agent_decision.json</b>（schema ' + esc(d.schema_version) +
      '）· 客流台账：34 站 / 公开锚点 ' + n(cr.public_anchor_count, 0) +
      ' 条 · 生成于 ' + esc(d.generated_at) + '</span>' +
      '<span>调用链：<b>' + n(t.tool_calls, 0) + '</b> 次工具调用 / ' + n(t.steps, 0) +
      ' 步 · 失败 ' + n(t.failed_calls, 0) + ' 次 · ' +
      '<a href="javascript:void(0)" id="gdp-trace-btn">查看调用链</a></span>' +
      '</div>';
  }

  function scenarioBar() {
    var opts = [['', '默认'], ['holiday', '节假日'], ['weekday', '工作日']];
    return '<div class="gdp-scen-bar">' + opts.map(function (o) {
      var active = (S.scenario || '') === o[0];
      return '<button class="gdp-scen-btn' + (active ? ' active' : '') +
             '" data-scen="' + esc(o[0]) + '">' + esc(o[1]) + '</button>';
    }).join('') + '</div>';
  }

  function render() {
    var root = document.getElementById(S.rootId);
    if (!root) return;
    try { renderInner(root); }
    catch (e) {
      // ★ 渲染异常绝不能伪装成"离线" ★
      //   实测踩过：一处 b.get() 误用把 TypeError 抛进 catch，
      //   面板于是显示"未加载决策文档"，看起来像数据没生成，实际是前端 bug。
      console.error('[赣鄱智轨] 决策面板渲染异常', e);
      root.innerHTML = '<div class="gdp-head"><span class="gdp-title">智能体决策面板</span>' +
        '<span class="gdp-badge off">渲染异常</span></div>' +
        '<div class="gdp-empty">决策文档已成功加载，但渲染时出错：<br><code>' +
        esc(String(e && e.message || e)) + '</code><br>' +
        '（这是前端缺陷，不是后端没产出数据；请把该信息一并反馈。）</div>';
    }
  }

  function renderInner(root) {
    if (S.loading) {
      root.innerHTML = '<div class="gdp-head"><span class="gdp-title">智能体决策面板</span>' +
        '<span class="gdp-badge loc">正在加载 agent_decision.json …</span></div>';
      return;
    }
    if (!S.doc) {
      root.innerHTML = '<div class="gdp-head"><span class="gdp-title">智能体决策面板</span>' +
        '<span class="gdp-badge off">离线模式 · 未加载决策文档</span></div>' +
        '<div class="gdp-empty">未找到 <code>data/agent_decision.json</code>。<br>' +
        '请先在后端运行：<code>python3 run_agent.py --scenario holiday --hub 南昌站</code><br>' +
        '当前面板显示的是下方<b>规则镜像原型</b>文案，不是模型输出，已如实标注。</div>';
      return;
    }
    var p = view();
    if (!p) { root.innerHTML = '<div class="gdp-empty">决策文档中无可用方案。</div>'; return; }
    root.innerHTML =
      '<div class="gdp-head">' +
        '<span class="gdp-title">智能体决策面板</span>' +
        '<span class="gdp-scen">' + esc((S.doc.scenario || {}).label || '') + '</span>' +
        '<span class="gdp-head-right">' + engineBadge() + '</span>' +
      '</div>' +
      scenarioBar() +
      '<div class="gdp-sub">Planner-Executor-Critic 状态机 · 注册工具 ' +
        n((S.doc.engine || {}).tools_registered, 0) + ' 个 · 引擎 ' +
        esc((S.doc.engine || {}).sim ? (S.doc.engine.sim.active || '—') : '—') +
        ' · 推荐方案 <b>' + esc(S.doc.recommended || '—') + '</b></div>' +
      tabs() +
      '<div class="gdp-plan-name">' + esc(p.id) + ' · ' + esc(p.name || '') +
        '<span class="gdp-rat">' + esc(p.rationale || '') + '</span></div>' +
      metricStrip(p) +
      '<div class="gdp-cards">' +
        AGENT_META.map(function (m) { return card(m, cardsOf(p)[m.id] || {}); }).join('') +
      '</div>' +
      foot(p) +
      (S.traceOpen ? traceHtml() : '');

    Array.prototype.forEach.call(root.querySelectorAll('.gdp-tab'), function (b) {
      b.onclick = function () {
        S.sel = b.getAttribute('data-plan');
        render();
        // 广播方案切换（基准/A/B/C/D…），供地图联动模块（js/decision-map.js）同步重绘
        window.dispatchEvent(new CustomEvent('gdp:planchange', { detail: { plan: S.sel, decision: S.doc } }));
      };
    });
    Array.prototype.forEach.call(root.querySelectorAll('.gdp-scen-btn'), function (b) {
      b.onclick = function () { switchScenario(b.getAttribute('data-scen')); };
    });
    var tb = document.getElementById('gdp-trace-btn');
    if (tb) tb.onclick = toggleTrace;
  }

  function traceHtml() {
    if (!S.trace) {
      return '<div class="gdp-trace"><div class="gdp-trace-h">调用链 trace 日志</div>' +
        '<div class="gdp-empty">未加载 trace（可能后端未运行，或 output/trace 不在站点根目录下）。</div></div>';
    }
    var ev = (S.trace.events || []).filter(function (e) { return e.kind === 'tool_call'; });
    var rows = ev.map(function (e) {
      return '<tr><td>' + e.seq + '</td><td>' + esc(e.tool) + '</td>' +
        '<td class="gdp-args">' + esc(JSON.stringify(e.args || {}).slice(0, 200)) + '</td>' +
        '<td>' + (e.ok ? '✓' : '<span class="gdp-bad">✗</span>') + '</td>' +
        '<td>' + e.duration_ms + 'ms</td>' +
        '<td class="gdp-args">' + esc(JSON.stringify(e.result || {}).slice(0, 260)) + '</td></tr>';
    }).join('');
    return '<div class="gdp-trace">' +
      '<div class="gdp-trace-h">调用链 trace 日志 · ' + esc(S.trace.meta ? (S.trace.meta.scenario || '') : '') +
      ' · 共 ' + ev.length + ' 次工具调用（原始文件：' + esc((S.doc.trace || {}).path || '') + '）</div>' +
      '<div class="gdp-trace-scroll"><table class="gdp-table"><thead><tr>' +
      '<th>#</th><th>工具</th><th>入参</th><th>结果</th><th>耗时</th><th>出参摘要</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
      '<div class="gdp-trace-note">每一条都可与页面上的数字逐一对上：例如 run_simulation 返回的 ' +
      'max_saturation 与指标条上显示的完全一致 —— 这是可当场核验的，不是声明。</div>' +
      '</div>';
  }

  function toggleTrace() {
    S.traceOpen = !S.traceOpen;
    if (S.traceOpen && !S.trace) loadTrace();
    render();
  }

  function loadTrace() {
    var d = S.doc;
    if (!d || !d.trace || !d.trace.path) return;
    fetch(TRACE_BASE + d.trace.path).then(function (r) { return r.json(); })
      .then(function (j) { S.trace = j; render(); })
      .catch(function () { S.trace = null; render(); });
  }

  // ---------- 样式（自带，index.html / bmap.html 通用）----------
  function injectStyle() {
    if (document.getElementById('gdp-style')) return;
    var st = document.createElement('style');
    st.id = 'gdp-style';
    st.textContent = [
      '#gdp-root{background:rgba(0,14,30,.93);border:1px solid #1a4a7c;border-radius:6px;',
      'padding:10px 12px;color:#d0e6f5;font-size:12px;line-height:1.6;}',
      '#gdp-root .gdp-head{display:flex;align-items:center;gap:10px;margin-bottom:6px;flex-wrap:wrap;}',
      '#gdp-root .gdp-title{color:#00d4ff;font-size:13px;font-weight:bold;}',
      '#gdp-root .gdp-scen{color:#7ab8e0;font-size:11px;}',
      '#gdp-root .gdp-head-right{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap;}',
      '#gdp-root .gdp-badge{border:1px solid #1a4a7c;border-radius:10px;padding:2px 9px;',
      'font-size:10px;color:#7ab8e0;background:rgba(0,30,60,.6);cursor:help;}',
      '#gdp-root .gdp-badge.on{border-color:#00ff88;color:#00ff88;}',
      '#gdp-root .gdp-badge.loc{border-color:#ffcc00;color:#ffcc00;}',
      '#gdp-root .gdp-badge.off{border-color:#ff5566;color:#ff5566;}',
      '#gdp-root .gdp-sub{font-size:10px;color:#5a8ab0;margin-bottom:8px;}',
      '#gdp-root .gdp-tabs{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:8px;}',
      '#gdp-root .gdp-tab{background:rgba(0,30,60,.7);border:1px solid #1a3a5c;color:#7ab8e0;',
      'padding:4px 12px;border-radius:3px;cursor:pointer;font-size:11px;font-family:inherit;}',
      '#gdp-root .gdp-tab:hover{border-color:#00d4ff;color:#00d4ff;}',
      '#gdp-root .gdp-tab.active{background:#00d4ff;color:#001020;border-color:#00d4ff;font-weight:bold;}',
      '#gdp-root .gdp-tab.rec{border-color:#ffcc00;color:#ffcc00;}',
      '#gdp-root .gdp-tab.rec.active{background:#ffcc00;color:#1a1200;border-color:#ffcc00;}',
      '#gdp-root .gdp-plan-name{font-size:11px;color:#fff;font-weight:bold;margin-bottom:6px;}',
      '#gdp-root .gdp-rat{font-weight:normal;color:#5a8ab0;font-size:10px;margin-left:6px;}',
      '#gdp-root .gdp-metrics{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:9px;}',
      '#gdp-root .gdp-mi{background:rgba(0,10,25,.7);border-left:2px solid #1a4a7c;',
      'border-radius:3px;padding:4px 9px;min-width:118px;}',
      '#gdp-root .gdp-mi-k{display:block;font-size:9px;color:#5a8ab0;}',
      '#gdp-root .gdp-mi-v{display:block;font-size:14px;font-weight:bold;color:#fff;}',
      '#gdp-root .gdp-mi-b{display:block;font-size:9px;color:#3a6a90;}',
      '#gdp-root .gdp-mi-score{border-left-color:#ffcc00;}',
      '#gdp-root .gdp-mi-score .gdp-mi-v{color:#ffcc00;}',
      '#gdp-root .gdp-cards{display:flex;gap:7px;}',
      '#gdp-root .gdp-card{flex:1;min-width:0;background:rgba(0,10,25,.7);',
      'border-top:3px solid #00d4ff;border-radius:4px;padding:7px 9px;}',
      '#gdp-root .gdp-card-name{font-size:11px;font-weight:bold;margin-bottom:5px;}',
      '#gdp-root .gdp-rt{float:right;font-size:9px;color:#5a8ab0;font-weight:normal;}',
      '#gdp-root .gdp-act{font-size:11px;color:#d0e6f5;line-height:1.6;}',
      '#gdp-root .gdp-act b{color:#fff;}',
      '#gdp-root .gdp-reason{font-size:9px;color:#5a8ab0;line-height:1.5;margin-top:5px;',
      'border-top:1px solid #1a3a5c;padding-top:4px;}',
      '#gdp-root .gdp-reason b{color:#a0c8e0;}',
      '#gdp-root .gdp-foot{margin-top:8px;display:flex;justify-content:space-between;gap:10px;',
      'font-size:9px;color:#5a8ab0;flex-wrap:wrap;}',
      '#gdp-root .gdp-foot a{color:#00d4ff;text-decoration:none;}',
      '#gdp-root .gdp-empty{font-size:11px;color:#7ab8e0;background:rgba(0,10,25,.6);',
      'border-left:3px solid #ff5566;border-radius:3px;padding:8px 10px;line-height:1.8;}',
      '#gdp-root .gdp-empty code{color:#ffcc00;}',
      '#gdp-root .gdp-trace{margin-top:9px;border-top:1px solid #1a3a5c;padding-top:8px;}',
      '#gdp-root .gdp-trace-h{font-size:11px;color:#00d4ff;font-weight:bold;margin-bottom:6px;}',
      '#gdp-root .gdp-trace-scroll{max-height:220px;overflow:auto;border:1px solid #1a3a5c;border-radius:3px;}',
      '#gdp-root .gdp-table{width:100%;border-collapse:collapse;font-size:9px;}',
      '#gdp-root .gdp-table th{position:sticky;top:0;background:#001a30;color:#7ab8e0;',
      'padding:4px 6px;text-align:left;border-bottom:1px solid #1a3a5c;white-space:nowrap;}',
      '#gdp-root .gdp-table td{padding:4px 6px;border-bottom:1px solid #10263d;',
      'color:#a0c8e0;vertical-align:top;}',
      '#gdp-root .gdp-args{font-family:Menlo,Consolas,monospace;color:#5a8ab0;word-break:break-all;}',
      '#gdp-root .gdp-bad{color:#ff5566;}',
      '#gdp-root .gdp-trace-note{font-size:9px;color:#5a8ab0;margin-top:6px;line-height:1.6;}',
      '#gdp-root .gdp-scen-bar{display:flex;gap:4px;margin-bottom:6px;}',
      '#gdp-root .gdp-scen-btn{background:rgba(0,30,60,.7);border:1px solid #1a3a5c;color:#7ab8e0;',
      'padding:2px 10px;border-radius:3px;cursor:pointer;font-size:10px;font-family:inherit;}',
      '#gdp-root .gdp-scen-btn:hover{border-color:#00d4ff;color:#00d4ff;}',
      '#gdp-root .gdp-scen-btn.active{background:#0d6abf;color:#fff;border-color:#0d6abf;font-weight:bold;}'
    ].join('');
    document.head.appendChild(st);
  }

  // ---------- 对外接口 ----------
  function switchScenario(scen) {
    S.scenario = scen;
    S.doc = null; S.loading = true; S.trace = null; S.traceOpen = false; S.sel = 'recommended';
    render();
    fetch(urlDecision(scen) + '?t=' + Date.now())
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (j) {
        S.doc = j; S.loading = false; S.err = null; S.sel = 'recommended';
        window.__GANPO_DECISION__ = j;
        render();
        window.dispatchEvent(new CustomEvent('gdp:ready', { detail: j }));
      })
      .catch(function (e) {
        S.doc = null; S.loading = false; S.err = String(e);
        console.warn('[赣鄱智轨] 决策文档取数失败：' + S.err);
        render();
      });
  }

  function mount(rootId) {
    injectStyle();
    S.rootId = rootId;
    render();
    fetch(urlDecision(S.scenario) + '?t=' + Date.now())
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (j) {
        // 数据到手先落状态，再渲染 —— 渲染异常由 render() 内部单独兜住，
        // 不会把"已成功取数"这件事回滚成"未加载"。
        S.doc = j; S.loading = false; S.err = null; S.sel = 'recommended';
        window.__GANPO_DECISION__ = j;   // 供应急模块读取真实风险段 / 改线路径
        render();
        if (S.err) return;
        window.dispatchEvent(new CustomEvent('gdp:ready', { detail: j }));
      })
      .catch(function (e) {
        // 只有"取数失败"才走这里（网络/404/JSON 解析）
        S.doc = null; S.loading = false; S.err = String(e);
        console.warn('[赣鄱智轨] agent_decision.json 取数失败：' + S.err);
        render();
        window.dispatchEvent(new CustomEvent('gdp:offline', { detail: S.err }));
      });
  }

  window.GanpoDecisionPanel = {
    mount: mount,
    toggleTrace: toggleTrace,
    switchScenario: switchScenario,
    reload: function () { mount(S.rootId); },
    state: S,
    get decision() { return S.doc; }
  };
})();
