/* ======================================================================
 * 决策地图 ·「节假日大客流 · 枢纽换乘拥堵治理」决策结果地图表达
 * ----------------------------------------------------------------------
 * 把 L3 智能体决策面板（data/agent_decision_*.json）的结果叠加到百度地图：
 *   ① 枢纽环：scenario.hub（南昌站）→ 青色脉冲环 + 换乘治理说明
 *   ② 瓶颈圈：baseline.top_bottlenecks → 站点脉冲圈（颜色按站台饱和度档位）
 *   ③ 线路光带：所选方案 per_line[*].saturation_section → 线路治理色光带
 *        （绿 <0.7 / 黄 0.7-0.9 / 橙 0.9-1.05 / 红 ≥1.05）
 *   ④ 决策摘要卡（顶部居中）：方案切换（基准 / A / B / C / D★）与关键指标随动
 *
 * 交互：
 *   · 打开节假日决策文档（?scenario=holiday）后自动开启；
 *   · 决策面板内点方案 Tab → 地图同步重绘（监听 gdp:planchange / gdp:ready）；
 *   · 工具栏按钮「决策地图·枢纽治理」可随时开关（手动关掉后不再自动弹出）。
 *
 * 数据唯一真源：决策文档（agent_decision.json）。
 *   本模块不持有业务数值；唯一的对照表是「线路名 → L2 仿真线路名」的命名映射
 *   （详见 LINE_PAIRS 注释），只用来说明"哪条地图线对应仿真里的哪条线"。
 *   站点圈的"治理后"数值为线路级近似（取该站所属线路中最紧断面），
 *   出现在标签中并明确标注「线路级」，不与站台级实测混同。
 * ====================================================================== */
(function () {
  'use strict';

  // 线路名对照：config.js 里的地图线路名 → 决策文档 per_line 里的仿真线路名。
  // 赣东北环线在仿真中合并为"赣东北旅游环线"一条计（3.2 拆段只是地图表现）。
  var LINE_PAIRS = [
    ['昌九通勤线', '昌九通勤线'],
    ['昌抚通勤线', '昌抚通勤线'],
    ['沪昆通勤线', '沪昆通勤线'],
    ['京九通勤线', '京九通勤线'],
    ['皖赣通勤线', '皖赣通勤线'],
    ['赣东北环线·上饶婺源段', '赣东北旅游环线'],
    ['赣东北环线·三清山龙虎山段', '赣东北旅游环线'],
    ['环庐山旅游线', '环庐山旅游线'],
    ['赣西红色旅游线', '赣西红色旅游线'],
    ['赣南客家旅游线', '赣南客家旅游线'],
    ['赣东古韵旅游线', '赣东古韵旅游线'],
    ['大觉山旅游支线', '大觉山旅游支线'],
    ['梅岭红轨旅游线', '梅岭红轨旅游线']
  ];

  // 枢纽换乘占比（节假日）：与 js/transfer-sim.js「换乘节点动态仿真」的
  // MODES.holiday.share 保持一致（该模块将其标注为仿真推演值）。
  // 决策文档本身不携带该比例，故此处以常量引用并在地图标签中注明「换乘仿真推演」。
  var HUB_TRANSFER_SHARE_HOLIDAY = 0.55;

  var state = {
    map: null,
    enabled: false,        // 图层是否开启
    userDisabled: false,   // 用户手动关掉后不再自动开启
    doc: null,             // 当前决策文档
    sel: 'recommended',    // 当前方案视图（baseline | recommended | A/B/C/D）
    overlays: [],
    rings: [],
    redLines: [],
    hubObjects: [],
    timer: null,
    phase: true,
    built: false,
    zoom: 8        // 当前地图级别（饱和度框随缩放联动，见 zoomFontScale/zoomRadiusScale）
  };

  // —— 工具 ——
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function fmt(v, d) {
    if (v == null || v === '' || isNaN(v)) return '—';
    var x = Number(v);
    if (d === 0) return Math.round(x).toLocaleString();
    return x.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function mwh(v) { return v == null ? '—' : (v / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 }); }

  // 饱和度 → 档位色
  function satColor(v) {
    if (v == null) return '#7ab8e0';
    if (v >= 1.05) return '#ff3344';
    if (v >= 0.9)  return '#ff8800';
    if (v >= 0.7)  return '#ffcc00';
    return '#00ff88';
  }

  // —— 饱和度框随地图缩放联动（2026-10-08）——
  // 放大地图时：标注框字号同步放大（更易读），圈的米制半径按像素口径回缩
  // （否则放大后几十公里的圈会吞掉整个屏幕）。zoomend 时整层幂等重绘。
  function zoomFontScale() {
    return Math.max(0.9, Math.min(1.5, Math.pow(1.1, (state.zoom || 8) - 8)));
  }
  function zoomRadiusScale() {
    return Math.pow(1.8, 8 - (state.zoom || 8));
  }

  // 线路名对照（运行时构建）
  var SIM_OF_CONFIG = {}, CONFIG_OF_SIM = {}, STATION_SIMLINES = {};
  function buildNameMaps() {
    var C = window.GanpoConfig;
    if (!C) return;
    SIM_OF_CONFIG = {}; CONFIG_OF_SIM = {}; STATION_SIMLINES = {};
    LINE_PAIRS.forEach(function (pr) {
      SIM_OF_CONFIG[pr[0]] = pr[1];
      (CONFIG_OF_SIM[pr[1]] = CONFIG_OF_SIM[pr[1]] || []).push(pr[0]);
    });
    ['commuterLines', 'tourismLines'].forEach(function (key) {
      (C[key] || []).forEach(function (line) {
        var sim = SIM_OF_CONFIG[line.name];
        if (!sim) return;
        (line.stations || []).forEach(function (s) {
          STATION_SIMLINES[s.name] = STATION_SIMLINES[s.name] || {};
          STATION_SIMLINES[s.name][sim] = true;
        });
      });
    });
  }
  function findConfigLine(name) {
    var C = window.GanpoConfig;
    var pool = (C.commuterLines || []).concat(C.tourismLines || []);
    for (var i = 0; i < pool.length; i++) { if (pool[i].name === name) return pool[i]; }
    return null;
  }
  // 站点 → 所选方案中的（线路级）最紧断面饱和度
  function stationPlanSat(stationName, perLine) {
    var sims = STATION_SIMLINES[stationName];
    if (!sims || !perLine) return null;
    var best = null;
    perLine.forEach(function (l) {
      if (sims[l.line] && l.saturation_section != null) {
        if (best === null || l.saturation_section > best) best = l.saturation_section;
      }
    });
    return best;
  }

  function add(o) { try { state.map.addOverlay(o); state.overlays.push(o); } catch (e) {} }
  function clearAll() {
    state.overlays.forEach(function (o) { try { state.map.removeOverlay(o); } catch (e) {} });
    state.overlays = []; state.rings = []; state.redLines = []; state.hubObjects = [];
    stopPulse();
  }
  function stopPulse() { if (state.timer) { clearInterval(state.timer); state.timer = null; } }
  function startPulse() {
    stopPulse();
    state.phase = true;
    state.timer = setInterval(function () {
      state.phase = !state.phase;
      state.rings.forEach(function (c) {
        try { c.setFillOpacity(state.phase ? 0.24 : 0.07); c.setStrokeOpacity(state.phase ? 0.95 : 0.4); } catch (e) {}
      });
      state.redLines.forEach(function (p) {
        try { p.setStrokeOpacity(state.phase ? 0.5 : 0.16); } catch (e) {}
      });
      state.hubObjects.forEach(function (c) {
        try { c.setStrokeOpacity(state.phase ? 0.9 : 0.35); } catch (e) {}
      });
    }, 900);
  }

  function mkLabel(html, coord, borderColor, mLeft, mTop) {
    try {
      var fs = zoomFontScale();   // 字号与偏移随地图级别同步缩放
      var lb = new BMapGL.Label(html, { position: new BMapGL.Point(coord[0], coord[1]) });
      lb.setStyle({
        color: '#eaf6ff', background: 'rgba(0,14,30,0.93)',
        border: '1px solid ' + (borderColor || '#1a4a7c'), padding: '3px 8px',
        fontSize: (11 * fs).toFixed(1) + 'px', fontFamily: 'Microsoft YaHei, sans-serif', borderRadius: '4px',
        marginLeft: Math.round((mLeft == null ? -96 : mLeft) * fs) + 'px',
        marginTop: Math.round((mTop == null ? -46 : mTop) * fs) + 'px',
        whiteSpace: 'nowrap', lineHeight: '1.55'
      });
      return lb;
    } catch (e) { return null; }
  }

  // —— 方案视图解析（与决策面板 view() 同逻辑）——
  function resolveView() {
    var d = state.doc;
    if (!d) return null;
    if (state.sel === 'baseline') {
      var b = d.baseline || {};
      return {
        id: '基准', name: '基准（未治理）', isBaseline: true,
        metrics: b.metrics || {}, perLine: (b.metrics || {}).per_line || [],
        top: b.top_bottlenecks || [], score: null, delta: null
      };
    }
    var plans = d.plans || [];
    var p = null;
    if (state.sel === 'recommended') p = plans.filter(function (x) { return x.id === d.recommended; })[0] || plans[0];
    else p = plans.filter(function (x) { return x.id === state.sel; })[0];
    if (!p) return null;
    return {
      id: p.id, name: p.name || '', isBaseline: false,
      metrics: p.metrics || {}, perLine: (p.metrics || {}).per_line || [],
      top: (d.baseline || {}).top_bottlenecks || [],
      score: p.score || null, delta: p.delta || null
    };
  }

  // —— 绘制：把决策结果落到地图上 ——
  function draw() {
    if (!state.map || !state.doc) return;
    clearAll();
    var v = resolveView();
    if (!v) return;
    var C = window.GanpoConfig;
    var stationMap = {};
    (C.allStations() || []).forEach(function (s) { stationMap[s.name] = s; });

    // ③ 线路治理光带（先画，压在圈层下面）
    (v.perLine || []).forEach(function (l) {
      var configNames = CONFIG_OF_SIM[l.line] || [];
      var col = satColor(l.saturation_section);
      configNames.forEach(function (cn) {
        var line = findConfigLine(cn);
        if (!line) return;
        var pts = (line.coords || []).map(function (c) { return new BMapGL.Point(c[0], c[1]); });
        if (pts.length < 2) return;
        var pl = new BMapGL.Polyline(pts, {
          strokeColor: col, strokeWeight: 10, strokeOpacity: 0.38
        });
        add(pl);
        if (l.saturation_section >= 1.05) state.redLines.push(pl);
      });
    });

    // ① 枢纽环（scenario.hub）
    var hubName = (state.doc.scenario || {}).hub || '南昌站';
    var hubSt = stationMap[hubName];
    if (hubSt && hubSt.coord) {
      var hubCol = '#00d4ff';
      var hubCircle = new BMapGL.Circle(new BMapGL.Point(hubSt.coord[0], hubSt.coord[1]), Math.round(30000 * zoomRadiusScale()), {
        strokeColor: hubCol, strokeWeight: 3, strokeOpacity: 0.9,
        fillColor: hubCol, fillOpacity: 0.06
      });
      add(hubCircle); state.hubObjects.push(hubCircle);
      var hubSat = (v.metrics || {}).hub_saturation;
      var shareTxt = ((state.doc.scenario || {}).transport_scenario === 'holiday')
        ? '节假日换乘占比约 ' + fmt(HUB_TRANSFER_SHARE_HOLIDAY * 100, 0) + '%（换乘仿真推演）'
        : '通勤高峰换乘压力点';
      var hubLb = mkLabel(
        '<b style="color:#00d4ff">枢纽换乘治理 · ' + esc(hubName) + '</b>' +
        '<br><span style="font-size:10px;color:#9fc3df">' + esc(shareTxt) +
        ' · 枢纽饱和度 ' + fmt(hubSat, 3) + '（仿真）</span>',
        hubSt.coord, hubCol, -150, -64
      );
      if (hubLb) add(hubLb);
    }

    // ② 基准瓶颈圈（top_bottlenecks）
    var rings = 0;
    (v.top || []).forEach(function (b) {
      var st = stationMap[b.name];
      if (!st || !st.coord) return;
      var col = satColor(b.saturation);
      var radius = Math.round((12000 + Math.min(1.5, b.saturation || 0) * 14000) * zoomRadiusScale());
      var circle = new BMapGL.Circle(new BMapGL.Point(st.coord[0], st.coord[1]), radius, {
        strokeColor: col, strokeWeight: 2.5, strokeOpacity: 0.95,
        fillColor: col, fillOpacity: 0.22
      });
      add(circle); state.rings.push(circle);

      var binding = (b.binding === 'platform') ? '站台容量瓶颈' : '换乘通道瓶颈';
      var l2 = binding + ' · 基准（未治理）';
      if (!v.isBaseline && v.perLine.length) {
        var ps = stationPlanSat(b.name, v.perLine);
        if (ps != null) {
          l2 += ' · 方案' + esc(v.id) + '治理后线路断面（线路级）<b style="color:' + satColor(ps) + '">' + fmt(ps, 3) + '</b>';
        }
      }
      var lb = mkLabel(
        '<b>' + esc(b.name) + '</b> 饱和度 <b style="color:' + col + '">' + fmt(b.saturation, 3) + '</b>' +
        '<br><span style="font-size:10px;color:#9fc3df">' + l2 + '</span>',
        st.coord, col
      );
      if (lb) add(lb);
      rings++;
    });

    renderSummary(v, rings);
    startPulse();
    console.log('[赣鄱智轨] 决策地图已重绘：方案视图=' + v.id +
      ' · 瓶颈圈 ' + rings + ' 个 · 线路光带 ' + (v.perLine || []).length + ' 条');
  }

  function dataFileHint() {
    var sc = (window.GanpoDecisionPanel && window.GanpoDecisionPanel.state)
      ? window.GanpoDecisionPanel.state.scenario : '';
    if (sc === 'holiday') return 'data/agent_decision_holiday.json';
    if (sc === 'weekday') return 'data/agent_decision_weekday.json';
    return 'data/agent_decision.json';
  }

  // —— ④ 摘要卡（顶部居中）——
  function ensurePanel() {
    if (state.built && document.getElementById('dmap-panel')) return document.getElementById('dmap-panel');
    injectStyle();
    var box = document.createElement('div');
    box.id = 'dmap-panel';
    box.innerHTML =
      '<div class="dm-head">' +
        '<span class="dm-title" id="dmap-title">决策地图</span>' +
        '<span class="dm-close" id="dmap-close" title="关闭决策地图（可点工具栏按钮重新开启）">✕</span>' +
      '</div>' +
      '<div class="dm-body" id="dmap-body"></div>';
    document.getElementById('app').appendChild(box);
    document.getElementById('dmap-close').onclick = function () { setEnabled(false); };
    state.built = true;
    return box;
  }

  function renderSummary(v, rings) {
    var box = ensurePanel();
    if (!box) return;
    var d = state.doc;
    var label = ((d.scenario || {}).label) || '决策输出';
    document.getElementById('dmap-title').textContent = '决策地图 · ' + label;

    var m = v.metrics || {}, bm = (d.baseline || {}).metrics || {};
    function chip(k, val, base) {
      return '<div class="dm-mi"><span class="dm-mi-k">' + esc(k) + '</span>' +
        '<span class="dm-mi-v">' + esc(val) + '</span>' +
        (base != null ? '<span class="dm-mi-b">基准 ' + esc(base) + '</span>' : '') +
        '</div>';
    }
    var chips = [
      chip('站台最大饱和度', fmt(m.max_saturation, 3), fmt(bm.max_saturation, 3)),
      chip('平均延误 (min)', fmt(m.avg_delay_min, 2), fmt(bm.avg_delay_min, 2)),
      chip('断面未承运 (人/h)', fmt(m.unmet_persons_per_hour, 0), fmt(bm.unmet_persons_per_hour, 0)),
      chip('所需配车 (列)', fmt(m.required_trains, 0), fmt(bm.required_trains, 0))
    ];
    if (m.energy_kwh_per_day != null) {
      chips.push(chip('牵引能耗 (MWh/日)', mwh(m.energy_kwh_per_day), mwh(bm.energy_kwh_per_day)));
    }
    var sc = v.score;
    if (sc && sc.total != null) {
      chips.push('<div class="dm-mi dm-mi-score"><span class="dm-mi-k">多目标总分</span>' +
        '<span class="dm-mi-v">' + fmt(sc.total, 1) + '</span>' +
        '<span class="dm-mi-b">拥堵 ' + fmt(sc.congestion, 1) + ' · 服务 ' + fmt(sc.service, 1) +
        ' · 资源 ' + fmt(sc.cost, 1) + ' · 稳健 ' + fmt(sc.robustness, 1) + '</span></div>');
    }

    // 方案切换（与决策面板双向联动）
    var planIds = ['baseline'].concat((d.plans || []).map(function (p) { return p.id; }));
    var tabsHtml = planIds.map(function (id) {
      var isRec = (id === d.recommended);
      var active = (state.sel === id) || (id === d.recommended && state.sel === 'recommended');
      var txt = (id === 'baseline') ? '基准' : (id + (isRec ? ' ★' : ''));
      return '<button class="dm-tab' + (active ? ' active' : '') + (isRec ? ' rec' : '') +
             '" data-plan="' + esc(id) + '">' + esc(txt) + '</button>';
    }).join('');

    document.getElementById('dmap-body').innerHTML =
      '<div class="dm-sub">' + esc(v.name || '') + ' · 瓶颈圈 ' + (rings == null ? '—' : rings) +
        ' 个（基准）· 数据：' + esc(dataFileHint()) + '</div>' +
      '<div class="dm-tabs">' + tabsHtml + '</div>' +
      '<div class="dm-metrics">' + chips.join('') + '</div>' +
      '<div class="dm-legend">' +
        '<span><span class="dm-dot" style="background:#ff3344"></span>≥1.05 超饱和</span>' +
        '<span><span class="dm-dot" style="background:#ff8800"></span>0.90–1.05 逼近容量</span>' +
        '<span><span class="dm-dot" style="background:#ffcc00"></span>0.70–0.90 偏紧</span>' +
        '<span><span class="dm-dot" style="background:#00ff88"></span>&lt;0.70 充裕</span>' +
        '<span><span class="dm-dot" style="background:#00d4ff"></span>枢纽节点</span>' +
      '</div>' +
      '<div class="dm-src">站点圈 = 基准瓶颈（baseline.top_bottlenecks 站台饱和度）· ' +
        '线路光带 = 所选方案线路断面饱和度 · 数值均来自决策文档，可复核</div>';

    Array.prototype.forEach.call(box.querySelectorAll('.dm-tab'), function (b) {
      b.onclick = function () {
        var id = b.getAttribute('data-plan');
        // 优先点决策面板里的同名 Tab，保持两处状态由同一真源渲染；找不到再本地切换
        var el = document.querySelector('#gdp-root .gdp-tab[data-plan="' + id + '"]');
        if (el) { el.click(); }
        else { state.sel = id; draw(); }
      };
    });
  }

  // —— 样式 ——
  function injectStyle() {
    if (document.getElementById('dmap-style')) return;
    var st = document.createElement('style');
    st.id = 'dmap-style';
    st.textContent = [
      '#dmap-panel{position:absolute;top:70px;left:50%;transform:translateX(-50%);z-index:9;',
      'width:470px;max-width:calc(100vw - 40px);background:rgba(0,14,30,.93);border:1px solid #1a4a7c;',
      'border-radius:8px;padding:9px 12px;color:#d0e6f5;font-size:12px;font-family:inherit;display:none;}',
      '#dmap-panel .dm-head{display:flex;align-items:center;gap:8px;}',
      '#dmap-panel .dm-title{color:#00d4ff;font-size:13px;font-weight:bold;}',
      '#dmap-panel .dm-close{margin-left:auto;cursor:pointer;color:#5a8ab0;font-size:13px;}',
      '#dmap-panel .dm-close:hover{color:#ff5566;}',
      '#dmap-panel .dm-sub{font-size:10px;color:#5a8ab0;margin:4px 0 7px;}',
      '#dmap-panel .dm-tabs{display:flex;gap:4px;margin-bottom:7px;flex-wrap:wrap;}',
      '#dmap-panel .dm-tab{background:rgba(0,30,60,.7);border:1px solid #1a3a5c;color:#7ab8e0;',
      'padding:3px 12px;border-radius:3px;cursor:pointer;font-size:11px;font-family:inherit;}',
      '#dmap-panel .dm-tab:hover{border-color:#00d4ff;color:#00d4ff;}',
      '#dmap-panel .dm-tab.active{background:#00d4ff;color:#001020;border-color:#00d4ff;font-weight:bold;}',
      '#dmap-panel .dm-tab.rec{border-color:#ffcc00;color:#ffcc00;}',
      '#dmap-panel .dm-tab.rec.active{background:#ffcc00;color:#1a1200;border-color:#ffcc00;}',
      '#dmap-panel .dm-metrics{display:flex;flex-wrap:wrap;gap:5px;}',
      '#dmap-panel .dm-mi{background:rgba(0,10,25,.7);border-left:2px solid #1a4a7c;',
      'border-radius:3px;padding:3px 8px;min-width:104px;}',
      '#dmap-panel .dm-mi-k{display:block;font-size:9px;color:#5a8ab0;}',
      '#dmap-panel .dm-mi-v{display:block;font-size:13px;font-weight:bold;color:#fff;}',
      '#dmap-panel .dm-mi-b{display:block;font-size:9px;color:#3a6a90;}',
      '#dmap-panel .dm-mi-score{border-left-color:#ffcc00;}',
      '#dmap-panel .dm-mi-score .dm-mi-v{color:#ffcc00;}',
      '#dmap-panel .dm-legend{display:flex;gap:10px;flex-wrap:wrap;font-size:10px;color:#7ab8e0;margin-top:7px;}',
      '#dmap-panel .dm-dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px;vertical-align:-1px;}',
      '#dmap-panel .dm-src{font-size:9px;color:#3a6a90;margin-top:5px;line-height:1.6;}'
    ].join('');
    document.head.appendChild(st);
  }

  // —— 开关与联动 ——
  function syncBtn() {
    var b = document.getElementById('decision-map-btn');
    if (!b) return;
    b.classList.toggle('active', !!state.enabled);
    b.textContent = state.enabled ? '决策地图·开启中' : '决策地图·枢纽治理';
  }

  function apply() {
    syncBtn();
    var panel = state.built ? document.getElementById('dmap-panel') : null;
    if (!state.enabled) {
      clearAll();
      if (panel) panel.style.display = 'none';
      return;
    }
    if (!state.map || !state.doc) {
      if (panel) {
        panel.style.display = 'block';
        var body = document.getElementById('dmap-body');
        if (body) body.innerHTML = '<div class="dm-sub">等待地图与决策文档就绪…（需在 HTTP 服务下打开，且已运行 run_agent.py 产出 data/agent_decision*.json）</div>';
      }
      return;
    }
    draw();
    panel = ensurePanel();
    if (panel) panel.style.display = 'block';
  }

  function setEnabled(on) {
    state.enabled = !!on;
    state.userDisabled = !on;   // 手动关掉后不再自动弹出；手动开启则恢复
    apply();
  }

  function buildButton(retries) {
    if (document.getElementById('decision-map-btn')) { syncBtn(); return; }
    var tb = document.getElementById('heatmap-toolbar') || document.querySelector('.toolbar');
    if (!tb) {
      if ((retries || 0) < 20) setTimeout(function () { buildButton((retries || 0) + 1); }, 400);
      return;
    }
    var b = document.createElement('button');
    b.id = 'decision-map-btn';
    b.textContent = '决策地图·枢纽治理';
    b.title = '在地图上表达「节假日大客流 · 枢纽换乘拥堵治理」决策结果（瓶颈圈 / 线路治理色 / 枢纽换乘环）';
    b.onclick = function () { setEnabled(!state.enabled); };
    tb.appendChild(b);
    syncBtn();
  }

  // —— 事件挂接 ——
  window.addEventListener('ganpo:mapready', function () {
    state.map = (window.GanpoMap && window.GanpoMap.map) || null;
    try { state.zoom = state.map.getZoom(); } catch (e) {}
    // 缩放联动：级别变化后按新级别重算标注框字号与圈半径（幂等重绘）
    try {
      state.map.addEventListener('zoomend', function () {
        try { state.zoom = state.map.getZoom(); } catch (e) {}
        if (state.enabled) apply();
      });
    } catch (e) {}
    buildNameMaps();
    buildButton();
    if (state.enabled) apply();
  });

  var settleTimer = null;   // 启动后延迟校准重绘：等相机/布局稳定后再绘制一遍（幂等），防止过渡态错位或残留
  window.addEventListener('gdp:ready', function (e) {
    state.doc = (e && e.detail) || window.__GANPO_DECISION__ || null;
    var ts = state.doc && state.doc.scenario && state.doc.scenario.transport_scenario;
    // 线路版（2026-10-10）：不再随节假日场景自动开启决策地图，
    // 加载即"只显示线路"的干净画面；需要时点工具栏「决策地图·枢纽治理」手动开启。
    if (state.enabled) apply();
    if (settleTimer) clearTimeout(settleTimer);
    settleTimer = setTimeout(function () {
      if (state.enabled) apply();   // 相机与布局稳定后的校准重绘（幂等）
    }, 1800);
  });

  window.addEventListener('gdp:planchange', function (e) {
    var p = e && e.detail && e.detail.plan;
    if (p) state.sel = (p === 'baseline') ? 'baseline' : p;
    if (state.enabled) apply();
  });

  // 兜底：若脚本加载晚于事件（极少见），做一次延迟自检
  setTimeout(function () {
    if (!state.doc && window.__GANPO_DECISION__) {
      state.doc = window.__GANPO_DECISION__;
      // 线路版：兜底路径同样不自动开启（保持加载画面干净）
      if (state.enabled) apply();
    }
    if (!state.map && window.GanpoMap && window.GanpoMap.map) {
      state.map = window.GanpoMap.map;
      buildNameMaps();
      buildButton();
    }
  }, 2500);

  window.GanpoDecisionMap = {
    toggle: function () { setEnabled(!state.enabled); },
    show: function () { setEnabled(true); },
    hide: function () { setEnabled(false); },
    redraw: function () { if (state.enabled) apply(); },
    state: state
  };
})();
