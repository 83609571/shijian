/* ======================================================================
 * 仿真评价指标 · 基准方案 vs 优化方案（依方案 2.7 仿真评价指标）
 * ----------------------------------------------------------------------
 * 职责：把方案文本 2.7 节列出的 10 项平台级评价指标落到地图上，并按
 *       「平台对基准方案和优化方案进行对比，形成方案评价结果」的要求，
 *       给出基准（未治理）与优化（推荐方案）的逐项对照。
 *
 *   10 项指标：
 *     ① 平均等待时间        ② 平均换乘时间     ③ 站点最大排队人数
 *     ④ 换乘通道拥挤度      ⑤ 线路最大断面客流 ⑥ 旅客滞留量
 *     ⑦ 应急接驳需求        ⑧ 线路恢复时间     ⑨ 列车开行数量
 *     ⑩ 车辆和接驳资源需求
 *
 * ★ 两种观察粒度（本次新增「运段」维度）：
 *     · 全网  —— 把 10 项指标按全网汇总对照；
 *     · 运段  —— 把 10 项指标落到**单条运营区段**，先在 **南昌—九江运段**
 *                （昌九通勤线）落地，并覆盖其余全部运段（昌抚 / 沪昆 / 京九 /
 *                皖赣 / 赣东北 / 环庐山 / 赣西 / 赣南 / 赣东 / 大觉山 / 梅岭）。
 *                选中运段后，地图自动定位并高亮该区段、逐站点标注，
 *                同时给出该运段内**每一个物理区段的断面客流**（南昌站→永修站…）。
 *
 * 数据唯一真源：
 *   · data/agent_decision_{holiday|weekday}.json —— 指标主数据（metrics.per_line 提供
 *     分区段的 headway / 断面客流 / 断面饱和度 / 未承运 / 配车；top_bottlenecks 提供
 *     站级排队与换乘通道饱和度）；
 *   · data/flow_{holiday|weekday}.json —— 区段断面客流的物理分段明细（segments）。
 *   · 无「△」标记：直接取自文档字段；带「△」：按文档字段做**确定性推演**，
 *     公式写在各行 title 与面板底部说明里，可当场复核，不虚构实测值。
 *
 * 地图表达（利用百度地图，把指标要素可视化）：
 *   · 全网视图：线路光带（断面饱和度上色）+ 瓶颈站排队圈 + 换乘枢纽环
 *   · 运段视图：定位缩放至该运段 + 高亮区段线 + 逐站点标注 + 断面客流标签
 * ====================================================================== */
(function () {
  'use strict';

  var SCEN_DECISION = {
    holiday: 'data/agent_decision_holiday.json',
    weekday: 'data/agent_decision_weekday.json'
  };
  var SCEN_FLOW = {
    holiday: 'data/flow_holiday.json',
    weekday: 'data/flow_weekday.json'
  };

  // 线路名对照：config.js 的地图线路名 → 决策文档 per_line 的仿真线路名
  // （赣东北环线在仿真中合并为「赣东北旅游环线」一条计，3.2 拆段只是地图表现）
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

  // 运段元数据：仿真线路名 → 运段展示名（按"起点—讫点"命名，铁路运段惯例）
  var SEG_INFO = {
    '昌九通勤线':     { label: '南昌—九江运段',        kind: '通勤', short: '昌九' },
    '昌抚通勤线':     { label: '南昌—抚州运段',        kind: '通勤', short: '昌抚' },
    '沪昆通勤线':     { label: '沪昆（南昌—萍乡）运段',  kind: '通勤', short: '沪昆' },
    '京九通勤线':     { label: '京九（南昌—赣州）运段',  kind: '通勤', short: '京九' },
    '皖赣通勤线':     { label: '皖赣（南昌—景德镇）运段', kind: '通勤', short: '皖赣' },
    '赣东北旅游环线':  { label: '赣东北旅游环线运段',    kind: '旅游', short: '赣东北' },
    '环庐山旅游线':    { label: '环庐山（九江—庐山—西海）运段', kind: '旅游', short: '环庐山' },
    '赣西红色旅游线':  { label: '赣西红色旅游运段',      kind: '旅游', short: '赣西' },
    '赣南客家旅游线':  { label: '赣南客家旅游运段',      kind: '旅游', short: '赣南' },
    '赣东古韵旅游线':  { label: '赣东古韵旅游运段',      kind: '旅游', short: '赣东' },
    '大觉山旅游支线':  { label: '大觉山旅游支线运段',    kind: '旅游', short: '大觉山' },
    '梅岭红轨旅游线':  { label: '梅岭红轨旅游运段',      kind: '旅游', short: '梅岭' }
  };
  // 运段排序（把 南昌—九江 放前面，符合"先在南昌九江落地"的要求）
  var SEG_ORDER = [
    '昌九通勤线', '昌抚通勤线', '沪昆通勤线', '京九通勤线', '皖赣通勤线',
    '环庐山旅游线', '赣东北旅游环线', '赣西红色旅游线', '赣南客家旅游线',
    '赣东古韵旅游线', '大觉山旅游支线', '梅岭红轨旅游线'
  ];

  // —— 推演参数（集中在此，便于答辩口径统一）——
  var PARAM = {
    transferWalkMin: 2.0,     // 站内步行基线（min）
    transferQueueMinPer: 4.0, // 通道饱和度 → 排队分钟（min / 单位饱和度）
    busSeats: 45,             // 一辆接驳车可载（人）
    recoverFixedMin: 5.0,     // 事件处置基线（min）
    clearRate: 30,            // 站台疏散速率（人 / min）
    opWindowMin: 960          // 日运营窗口（16h），用于估算列车开行数量
  };

  var state = {
    map: null, doc: null, flow: null, rec: null, scenario: 'holiday',
    view: 'opt', seg: null, segInited: false, on: false, built: false,
    overlays: [], rings: [], timer: null, phase: true,
    zoom: 8        // 当前地图级别（饱和度框随缩放联动）
  };

  // —— 工具 ——
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function fmt(v, d) {
    if (v == null || v === '' || isNaN(v)) return '—';
    var x = Number(v);
    if (d === 0) return Math.round(x).toLocaleString();
    return x.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function maxBy(arr, f) {
    var m = null;
    (arr || []).forEach(function (x) { var v = f(x); if (v == null || isNaN(v)) return; if (m === null || v > m) m = v; });
    return m;
  }
  function sumBy(arr, f) {
    var s = 0;
    (arr || []).forEach(function (x) { var v = f(x); if (v == null || isNaN(v)) return; s += v; });
    return s;
  }
  function satColor(v) {
    if (v == null) return '#7ab8e0';
    if (v >= 1.05) return '#ff3344';
    if (v >= 0.9)  return '#ff8800';
    if (v >= 0.7)  return '#ffcc00';
    return '#00ff88';
  }
  // —— 饱和度框随地图缩放联动（2026-10-08）：放大时字号同步放大、
  //    圈的米制半径按像素口径回缩，zoomend 后整层幂等重绘 ——
  function zoomFontScale() {
    return Math.max(0.9, Math.min(1.5, Math.pow(1.1, (state.zoom || 8) - 8)));
  }
  function zoomRadiusScale() {
    return Math.pow(1.8, 8 - (state.zoom || 8));
  }
  function segMeta(name) {
    return SEG_INFO[name] || { label: name, kind: '—', short: name };
  }
  function findLineMetric(metrics, name) {
    var arr = (metrics || {}).per_line || [];
    for (var i = 0; i < arr.length; i++) { if (arr[i].line === name) return arr[i]; }
    return null;
  }
  function P(c) { return new BMapGL.Point(c[0], c[1]); }

  // ====================================================================
  // ① 全网口径：10 项指标
  // ====================================================================
  function buildIndicators() {
    var d = state.doc;
    if (!d) return [];
    var b = d.baseline || {}, bm = b.metrics || {}, bcfg = b.config || {};
    var p = state.rec || {}, pm = p.metrics || {}, pcfg = p.effective_config || p.config || {};
    var bTop = b.top_bottlenecks || [];
    var bLines = bm.per_line || [], pLines = pm.per_line || [];

    // 优化后按「站台最大饱和度」改善比例折算（用于文档未直接给出站内口径的指标）
    var ratio = (bm.max_saturation ? (pm.max_saturation != null ? pm.max_saturation : bm.max_saturation) / bm.max_saturation : 1);

    var bChan = maxBy(bTop, function (t) { return t.saturation_channel; });
    var pChan = (bChan != null) ? bChan * ratio : null;

    var bDemand = maxBy(bLines, function (l) { return l.demand_ph; });
    var pDemand = maxBy(pLines, function (l) { return l.demand_ph; });

    var bWait = (bcfg.headway_min || 12) / 2;
    var pWait = (pcfg.headway_min || bcfg.headway_min || 12) / 2;

    var bTrans = (bChan != null) ? PARAM.transferWalkMin + PARAM.transferQueueMinPer * bChan : null;
    var pTrans = (pChan != null) ? PARAM.transferWalkMin + PARAM.transferQueueMinPer * pChan : null;

    var bBus = Math.ceil((bm.unmet_persons_per_hour || 0) / PARAM.busSeats);
    var pBus = Math.ceil((pm.unmet_persons_per_hour || 0) / PARAM.busSeats);

    var bRecover = PARAM.recoverFixedMin + (bm.max_queue_persons || 0) / PARAM.clearRate;
    var pRecover = PARAM.recoverFixedMin + (pm.max_queue_persons || 0) / PARAM.clearRate;

    var bRetain = (bm.deferred_persons_per_hour || 0) + (bm.max_queue_persons || 0);
    var pRetain = (pm.deferred_persons_per_hour || 0) + (pm.max_queue_persons || 0);

    var bRuns = Math.round(sumBy(bLines, function (l) { return (PARAM.opWindowMin / (l.headway_min || 12)) * 2; }));
    var pRuns = Math.round(sumBy(pLines, function (l) { return (PARAM.opWindowMin / (l.headway_min || pcfg.headway_min || 12)) * 2; }));

    var bFleet = (bm.required_trains || 0) + bBus;
    var pFleet = (pm.required_trains || 0) + pBus;

    return [
      { name: '平均等待时间', unit: 'min', better: 'down', derived: true, base: bWait, opt: pWait,
        src: '全网发车间隔 ÷ 2（乘客均匀到达假设）' },
      { name: '平均换乘时间', unit: 'min', better: 'down', derived: true, base: bTrans, opt: pTrans,
        src: '站内步行 ' + PARAM.transferWalkMin + 'min + 通道排队（通道饱和度 × ' + PARAM.transferQueueMinPer + 'min）' },
      { name: '站点最大排队人数', unit: '人', better: 'down', derived: false, base: bm.max_queue_persons, opt: pm.max_queue_persons,
        src: 'metrics.max_queue_persons（决策文档）' },
      { name: '换乘通道拥挤度', unit: '饱和度', better: 'down', derived: true, base: bChan, opt: pChan,
        src: 'top_bottlenecks.saturation_channel 最大值；优化按断面饱和度改善比例折算' },
      { name: '线路最大断面客流', unit: '人/h', better: 'info', derived: false, base: bDemand, opt: pDemand,
        src: 'per_line.demand_ph 最大值（需求侧）' },
      { name: '旅客滞留量', unit: '人', better: 'down', derived: false, base: bRetain, opt: pRetain,
        src: '限流站外滞留 + 站点最大积压（metrics）' },
      { name: '应急接驳需求', unit: '辆', better: 'down', derived: true, base: bBus, opt: pBus,
        src: '断面未承运 ÷ ' + PARAM.busSeats + ' 人/辆（向上取整）' },
      { name: '线路恢复时间', unit: 'min', better: 'down', derived: true, base: bRecover, opt: pRecover,
        src: '处置 ' + PARAM.recoverFixedMin + 'min + 积压 ÷ ' + PARAM.clearRate + ' 人·min⁻¹' },
      { name: '列车开行数量', unit: '列/日', better: 'up', derived: true, base: bRuns, opt: pRuns,
        src: 'Σ(运营 ' + (PARAM.opWindowMin / 60) + 'h ÷ 间隔 × 2 方向)' },
      { name: '车辆与接驳资源需求', unit: '列+辆', better: 'info', derived: true, base: bFleet, opt: pFleet,
        src: '所需配车（列）+ 应急接驳车（辆）' }
    ];
  }

  // ====================================================================
  // ② 运段口径：单条运营区段的 10 项指标
  //    · 断面类（等待/断面客流/未承运/配车）来自 per_line，逐段精确；
  //    · 站内类（排队/通道）来自该运段各站的 top_bottlenecks；无站级数据时，
  //      以该运段断面饱和度作为"运段拥挤度"代理并标记 △；
  //    · 优化值按该运段自身断面饱和度改善比例折算（与全网口径一致的方法）。
  // ====================================================================
  function buildSegIndicators(segName) {
    var d = state.doc;
    if (!d) return [];
    var b = d.baseline || {}, bm = b.metrics || {};
    var p = state.rec || {}, pm = p.metrics || {};
    var bl = findLineMetric(bm, segName), pl = findLineMetric(pm, segName);
    if (!bl) return [];

    var ratio = (bl.saturation_section ? ((pl && pl.saturation_section != null ? pl.saturation_section : bl.saturation_section) / bl.saturation_section) : 1);

    // 该运段内的站级瓶颈（按站名归属筛选）
    var segStationNames = {};
    segStations(segName).forEach(function (s) { segStationNames[s.name] = true; });
    var bTop = (b.top_bottlenecks || []).filter(function (t) { return segStationNames[t.name]; });

    var bChanRaw = maxBy(bTop, function (t) { return t.saturation_channel; });
    var chanProxy = (bChanRaw == null) || (bChanRaw === 0);
    var bChan = chanProxy ? bl.saturation_section : bChanRaw;   // △ 代理
    var pChan = bChan * ratio;

    var bQueue = maxBy(bTop, function (t) { return t.queue_persons; }) || 0;
    var pQueue = (pm.max_queue_persons === 0) ? 0 : Math.round(bQueue * ratio);

    var bDefer = sumBy(bTop, function (t) { return t.deferred_persons_ph; }) || 0;
    var pDefer = (pm.deferred_persons_per_hour === 0) ? 0 : Math.round(bDefer * ratio);

    var bUnmet = bl.unmet_ph || 0;
    var pUnmet = (pl ? pl.unmet_ph : 0) || 0;

    var bWait = (bl.headway_min || 12) / 2;
    var pWait = ((pl ? pl.headway_min : bl.headway_min) || 12) / 2;

    var bTrans = PARAM.transferWalkMin + PARAM.transferQueueMinPer * bChan;
    var pTrans = PARAM.transferWalkMin + PARAM.transferQueueMinPer * pChan;

    var bBus = Math.ceil(bUnmet / PARAM.busSeats);
    var pBus = Math.ceil(pUnmet / PARAM.busSeats);

    var bRecover = PARAM.recoverFixedMin + bQueue / PARAM.clearRate;
    var pRecover = PARAM.recoverFixedMin + pQueue / PARAM.clearRate;

    var bRetain = bUnmet + bQueue + bDefer;
    var pRetain = pUnmet + pQueue + pDefer;

    var bRuns = Math.round((PARAM.opWindowMin / (bl.headway_min || 12)) * 2);
    var pRuns = Math.round((PARAM.opWindowMin / ((pl ? pl.headway_min : bl.headway_min) || 12)) * 2);

    var bFleet = (bl.trains || 0) + bBus;
    var pFleet = ((pl ? pl.trains : bl.trains) || 0) + pBus;

    return [
      { name: '平均等待时间', unit: 'min', better: 'down', derived: true, base: bWait, opt: pWait,
        src: '本运段发车间隔 ' + fmt(bl.headway_min, 1) + 'min ÷ 2（均匀到达假设）' },
      { name: '平均换乘时间', unit: 'min', better: 'down', derived: true, base: bTrans, opt: pTrans,
        src: (chanProxy ? '站内步行 ' + PARAM.transferWalkMin + 'min + 通道排队（本运段无站级通道数据，用断面饱和度代理 △）'
                        : '站内步行 ' + PARAM.transferWalkMin + 'min + 通道排队（本运段通道饱和度 ' + fmt(bChanRaw, 3) + '）') },
      { name: '站点最大排队人数', unit: '人', better: 'down', derived: false, base: bQueue, opt: pQueue,
        src: (bTop.length ? '本运段各站 top_bottlenecks.queue_persons 最大值' : '本运段各站未进入瓶颈清单，基准积压为 0') },
      { name: '换乘通道拥挤度', unit: '饱和度', better: 'down', derived: chanProxy, base: bChan, opt: pChan,
        src: (chanProxy ? '本运段无站级通道数据，暂以断面饱和度作为运段拥挤度代理 △'
                        : '本运段各站 top_bottlenecks.saturation_channel 最大值') },
      { name: '线路最大断面客流', unit: '人/h', better: 'info', derived: false, base: bl.demand_ph, opt: (pl ? pl.demand_ph : bl.demand_ph),
        src: 'per_line[' + segName + '].demand_ph（需求侧，不随方案变化）' },
      { name: '旅客滞留量', unit: '人', better: 'down', derived: false, base: bRetain, opt: pRetain,
        src: '本运段未承运 ' + fmt(bUnmet, 0) + ' + 积压 ' + fmt(bQueue, 0) + ' + 站外滞留 ' + fmt(bDefer, 0) },
      { name: '应急接驳需求', unit: '辆', better: 'down', derived: true, base: bBus, opt: pBus,
        src: '本运段断面未承运 ÷ ' + PARAM.busSeats + ' 人/辆（向上取整）' },
      { name: '线路恢复时间', unit: 'min', better: 'down', derived: true, base: bRecover, opt: pRecover,
        src: '处置 ' + PARAM.recoverFixedMin + 'min + 本运段积压 ÷ ' + PARAM.clearRate + ' 人·min⁻¹' },
      { name: '列车开行数量', unit: '列/日', better: 'up', derived: true, base: bRuns, opt: pRuns,
        src: '运营 ' + (PARAM.opWindowMin / 60) + 'h ÷ ' + fmt(bl.headway_min, 1) + 'min × 2 方向' },
      { name: '车辆与接驳资源需求', unit: '列+辆', better: 'info', derived: true, base: bFleet, opt: pFleet,
        src: '本运段配车 ' + fmt(bl.trains, 0) + ' 列 + 应急接驳 ' + bBus + ' 辆' }
    ];
  }

  // —— 变化单元格 ——
  function deltaCell(r) {
    if (r.base == null || r.opt == null) return '<span class="mt-flat">—</span>';
    if (r.base === 0) {
      return r.opt === 0 ? '<span class="mt-flat">持平</span>'
        : '<span class="mt-bad">+' + fmt(r.opt, 0) + '</span>';
    }
    var d = (r.opt - r.base) / r.base * 100;
    var cls = 'mt-info';
    if (r.better === 'down') cls = (d < 0) ? 'mt-good' : (d > 0 ? 'mt-bad' : 'mt-flat');
    else if (r.better === 'up') cls = (d > 0) ? 'mt-good' : (d < 0 ? 'mt-bad' : 'mt-flat');
    var arrow = d > 0 ? '↑' : (d < 0 ? '↓' : '—');
    var txt = (Math.abs(d) < 0.05) ? '持平' : (arrow + Math.abs(d).toFixed(1) + '%');
    return '<span class="' + cls + '">' + txt + '</span>';
  }

  // —— 地图覆盖物 ——
  function add(o) { try { state.map.addOverlay(o); state.overlays.push(o); } catch (e) {} }
  function clearOverlays() {
    state.overlays.forEach(function (o) { try { state.map.removeOverlay(o); } catch (e) {} });
    state.overlays = []; state.rings = [];
    stopPulse();
  }
  function stopPulse() { if (state.timer) { clearInterval(state.timer); state.timer = null; } }
  function startPulse() {
    stopPulse();
    if (!state.rings.length) return;
    state.phase = true;
    state.timer = setInterval(function () {
      state.phase = !state.phase;
      state.rings.forEach(function (c) {
        try { c.setFillOpacity(state.phase ? 0.22 : 0.06); c.setStrokeOpacity(state.phase ? 0.95 : 0.4); } catch (e) {}
      });
    }, 900);
  }
  function mkLabel(html, coord, borderColor, mLeft, mTop) {
    try {
      var fs = zoomFontScale();   // 字号与偏移随地图级别同步缩放
      var lb = new BMapGL.Label(html, { position: P(coord) });
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

  var SIM_OF_CONFIG = {}, CONFIG_OF_SIM = {};
  function buildNameMaps() {
    SIM_OF_CONFIG = {}; CONFIG_OF_SIM = {};
    LINE_PAIRS.forEach(function (pr) {
      SIM_OF_CONFIG[pr[0]] = pr[1];
      (CONFIG_OF_SIM[pr[1]] = CONFIG_OF_SIM[pr[1]] || []).push(pr[0]);
    });
  }
  function findLine(name) {
    var C = window.GanpoConfig; if (!C) return null;
    var pool = (C.commuterLines || []).concat(C.tourismLines || []);
    for (var i = 0; i < pool.length; i++) { if (pool[i].name === name) return pool[i]; }
    return null;
  }
  // 该运段对应的地图线路（可能 1 条或多条 config 线路）
  function segConfigLines(segName) {
    return (CONFIG_OF_SIM[segName] || []).map(findLine).filter(Boolean);
  }
  // 该运段去重后的站点清单（含坐标）
  function segStations(segName) {
    var out = [];
    segConfigLines(segName).forEach(function (line) {
      (line.stations || []).forEach(function (s) {
        if (!out.some(function (x) { return x.name === s.name; })) out.push(s);
      });
    });
    return out;
  }

  // —— 全网图层 ——
  function drawNetLayers() {
    var C = window.GanpoConfig;
    var b = state.doc.baseline || {};
    var plan = (state.view === 'base') ? null : state.rec;
    var m = plan ? (plan.metrics || {}) : (b.metrics || {});
    var perLine = m.per_line || [];
    var stationMap = {};
    (C.allStations() || []).forEach(function (s) { stationMap[s.name] = s; });

    // ① 线路光带（按断面饱和度上色，压在线网之上作"治理着色"）
    perLine.forEach(function (l) {
      var col = satColor(l.saturation_section);
      (CONFIG_OF_SIM[l.line] || [l.line]).forEach(function (cn) {
        var line = findLine(cn); if (!line || !line.coords || line.coords.length < 2) return;
        add(new BMapGL.Polyline(line.coords.map(P), { strokeColor: col, strokeWeight: 9, strokeOpacity: 0.4 }));
      });
    });

    // ② 瓶颈站排队圈（站点最大排队人数：半径随饱和度放大）
    var bmSat = ((b.metrics || {}).max_saturation);
    var pmSat = ((state.rec || {}).metrics || {}).max_saturation;
    var ratio = (bmSat && pmSat != null) ? pmSat / bmSat : 1;
    (b.top_bottlenecks || []).forEach(function (t) {
      var st = stationMap[t.name]; if (!st || !st.coord) return;
      var col = satColor(t.saturation);
      var r = Math.round((12000 + Math.min(1.5, t.saturation || 0) * 14000) * zoomRadiusScale());
      var c = new BMapGL.Circle(P(st.coord), r, {
        strokeColor: col, strokeWeight: 2.5, strokeOpacity: 0.95, fillColor: col, fillOpacity: 0.22
      });
      add(c); state.rings.push(c);
      var shownSat = plan ? (t.saturation * ratio) : t.saturation;
      var lb = mkLabel(
        '<b>' + esc(t.name) + '</b> 排队 <b style="color:' + col + '">' + fmt(t.queue_persons, 0) + '</b> 人' +
        '<br><span style="font-size:10px;color:#9fc3df">' + (state.view === 'base' ? '基准（未治理）' : '优化方案 ' + esc((state.rec || {}).id || '')) +
        ' · 站台饱和度 ' + fmt(shownSat, 3) + (plan ? '（按全网改善比例折算）' : '') + '</span>',
        st.coord, col
      );
      if (lb) add(lb);
    });

    // ②b 逐运段标签：在每条运段走廊中点标出该运段关键指标（断面客流/饱和度/未承运）
    perLine.forEach(function (l) {
      var mid = segMidCoord(l.line);
      if (!mid) return;
      var col = satColor(l.saturation_section);
      var lb = mkLabel(
        '<b style="color:' + col + '">' + esc(segMeta(l.line).label) + '</b>' +
        '<br><span style="font-size:9.5px;color:#9fc3df">断面 ' + fmt(l.demand_ph, 0) + ' 人/h · 饱和度 ' +
        fmt(l.saturation_section, 2) + ' · 未承运 ' + fmt(l.unmet_ph, 0) + '</span>',
        mid, col, -120, -34
      );
      if (lb) add(lb);
    });

    // ③ 换乘枢纽环（南昌站）：标注换乘通道拥挤度 / 换乘时间
    var hubName = (state.doc.scenario || {}).hub || '南昌站';
    var hub = stationMap[hubName];
    if (hub && hub.coord) {
      var hubCol = '#00d4ff';
      var ring = new BMapGL.Circle(P(hub.coord), Math.round(26000 * zoomRadiusScale()), {
        strokeColor: hubCol, strokeWeight: 3, strokeOpacity: 0.9, fillColor: hubCol, fillOpacity: 0.05
      });
      add(ring); state.rings.push(ring);
      var rows = buildIndicators();
      var chan = rows[3] ? (state.view === 'base' ? rows[3].base : rows[3].opt) : null;
      var trs = rows[1] ? (state.view === 'base' ? rows[1].base : rows[1].opt) : null;
      var hubLb = mkLabel(
        '<b style="color:#00d4ff">换乘枢纽 · ' + esc(hubName) + '</b>' +
        '<br><span style="font-size:10px;color:#9fc3df">通道拥挤度 ' + fmt(chan, 3) +
        ' △ · 平均换乘 ' + fmt(trs, 2) + ' min △</span>',
        hub.coord, hubCol, -150, -64
      );
      if (hubLb) add(hubLb);
    }
  }

  // —— 运段图层：定位 + 高亮 + 逐站标注 + 断面客流标签 ——
  function drawSegLayers(segName) {
    var plan = (state.view === 'base') ? null : state.rec;
    var bm = (state.doc.baseline || {}).metrics || {};
    var lm = plan ? (plan.metrics || {}) : bm;
    var bl = findLineMetric(bm, segName), l = findLineMetric(lm, segName) || bl;
    if (!bl) return;
    var col = satColor(l.saturation_section);
    var meta = segMeta(segName);

    // 走廊底线（暗色描边）+ 高亮线，形成"选中"观感
    var vp = [];
    segConfigLines(segName).forEach(function (line) {
      if (!line.coords || line.coords.length < 2) return;
      line.coords.forEach(function (c) { vp.push(P(c)); });
      add(new BMapGL.Polyline(line.coords.map(P), { strokeColor: '#001a30', strokeWeight: 17, strokeOpacity: 0.85 }));
      add(new BMapGL.Polyline(line.coords.map(P), { strokeColor: col, strokeWeight: 8, strokeOpacity: 0.95 }));
    });

    // 逐站点标注：站名 + 值班要素
    var bnMap = {};
    ((state.doc.baseline || {}).top_bottlenecks || []).forEach(function (t) { bnMap[t.name] = t; });
    segStations(segName).forEach(function (s) {
      if (!s.coord) return;
      var t = bnMap[s.name];
      var dot = new BMapGL.Circle(P(s.coord), Math.round(4200 * zoomRadiusScale()), {
        strokeColor: '#ffffff', strokeWeight: 1.5, strokeOpacity: 0.9, fillColor: col, fillOpacity: 0.95
      });
      add(dot);
      var lines2 = '<b>' + esc(s.name) + '</b>';
      if (t) {
        var q = (plan && state.view === 'opt') ? 0 : t.queue_persons;
        lines2 += '<br><span style="font-size:10px;color:#9fc3df">通道 ' + fmt(t.saturation_channel, 2) +
                  ' · 排队 ' + fmt(q, 0) + ' 人</span>';
      } else if (s.transfer) {
        lines2 += '<br><span style="font-size:10px;color:#9fc3df">换乘：' + esc(s.transfer) + '</span>';
      }
      var lb = mkLabel(lines2, s.coord, col, -60, -48);
      if (lb) add(lb);
    });

    // 运段总览标签（贴在走廊中点）
    var mid = segMidCoord(segName);
    if (mid) {
      add(mkLabel(
        '<b style="color:' + col + '">' + esc(meta.label) + '</b>' +
        '<br><span style="font-size:10px;color:#9fc3df">断面客流 ' + fmt(l.demand_ph, 0) + ' 人/h · 断面饱和度 ' +
        fmt(l.saturation_section, 3) + ' · 未承运 ' + fmt(l.unmet_ph, 0) + ' 人/h</span>',
        mid, col, -140, -30
      ));
    }

    // 地图定位缩放
    if (vp.length && state.map.setViewport) {
      try { state.map.setViewport(vp); } catch (e) {}
    }
  }

  function segMidCoord(segName) {
    var sts = segStations(segName).filter(function (s) { return s.coord; });
    if (!sts.length) return null;
    var s = sts[Math.floor(sts.length / 2)];
    return s.coord;
  }

  function drawMap() {
    clearOverlays();
    if (!state.on || !state.map || !state.doc || !window.BMapGL) return;
    if (!window.GanpoConfig) return;
    if (state.seg) drawSegLayers(state.seg); else drawNetLayers();
    startPulse();
    console.log('[赣鄱智轨] 仿真评价指标图层已重绘：' + (state.seg ? '运段=' + segMeta(state.seg).label : '全网') +
      ' · 视图=' + (state.view === 'base' ? '基准' : '优化'));
  }

  // ====================================================================
  // 面板
  // ====================================================================
  function injectStyle() {
    if (document.getElementById('mt-style')) return;
    var st = document.createElement('style');
    st.id = 'mt-style';
    st.textContent = [
      '#metrics-panel{position:absolute;top:118px;left:20px;z-index:9;width:474px;max-width:calc(100vw - 40px);',
      'max-height:calc(100vh - 160px);overflow-y:auto;background:rgba(0,14,30,.95);border:1px solid #1a4a7c;',
      'border-radius:8px;padding:11px 13px;color:#d0e6f5;font-size:12px;font-family:inherit;display:none;}',
      '#metrics-panel .mt-head{display:flex;align-items:center;gap:8px;}',
      '#metrics-panel .mt-title{color:#00d4ff;font-size:13.5px;font-weight:bold;}',
      '#metrics-panel .mt-sub{font-size:10px;color:#5a8ab0;font-weight:normal;}',
      '#metrics-panel .mt-close{margin-left:auto;cursor:pointer;color:#5a8ab0;font-size:13px;}',
      '#metrics-panel .mt-close:hover{color:#ff5566;}',
      '#metrics-panel .mt-ctrl{display:flex;gap:10px;align-items:center;margin:8px 0 6px;flex-wrap:wrap;}',
      '#metrics-panel .mt-ctrl .mt-grp{display:flex;gap:4px;align-items:center;}',
      '#metrics-panel .mt-ctrl label{font-size:10px;color:#5a8ab0;}',
      '#metrics-panel .mt-btn{background:rgba(0,30,60,.7);border:1px solid #1a3a5c;color:#7ab8e0;',
      'padding:3px 10px;border-radius:3px;cursor:pointer;font-size:11px;font-family:inherit;}',
      '#metrics-panel .mt-btn:hover{border-color:#00d4ff;color:#00d4ff;}',
      '#metrics-panel .mt-btn.active{background:#00d4ff;color:#001020;border-color:#00d4ff;font-weight:bold;}',
      '#metrics-panel .mt-segrow{display:flex;gap:5px;overflow-x:auto;padding:4px 0 7px;border-bottom:1px solid #12293f;margin-bottom:7px;}',
      '#metrics-panel .mt-segrow::-webkit-scrollbar{height:5px;}',
      '#metrics-panel .mt-segrow::-webkit-scrollbar-thumb{background:#1a4a7c;border-radius:3px;}',
      '#metrics-panel .mt-seg{flex:0 0 auto;background:rgba(0,30,60,.7);border:1px solid #1a3a5c;color:#7ab8e0;',
      'padding:3px 9px;border-radius:12px;cursor:pointer;font-size:10.5px;font-family:inherit;white-space:nowrap;}',
      '#metrics-panel .mt-seg:hover{border-color:#00d4ff;color:#00d4ff;}',
      '#metrics-panel .mt-seg.active{background:#00d4ff;color:#001020;border-color:#00d4ff;font-weight:bold;}',
      '#metrics-panel .mt-crumb{font-size:11.5px;color:#ffcc00;font-weight:bold;margin-bottom:5px;}',
      '#metrics-panel .mt-crumb span{color:#7ab8e0;font-weight:normal;}',
      '#metrics-panel table{width:100%;border-collapse:collapse;font-size:11px;}',
      '#metrics-panel th{position:sticky;top:0;background:#001a30;color:#7ab8e0;font-weight:normal;',
      'padding:5px 6px;text-align:right;border-bottom:1px solid #1a3a5c;white-space:nowrap;}',
      '#metrics-panel th:first-child{text-align:left;}',
      '#metrics-panel td{padding:5px 6px;border-bottom:1px solid #10263d;color:#c6d3e2;text-align:right;white-space:nowrap;}',
      '#metrics-panel td:first-child{text-align:left;color:#d0e6f5;}',
      '#metrics-panel td .mt-u{color:#5a8ab0;font-size:9px;margin-left:3px;}',
      '#metrics-panel .mt-opt{color:#fff;font-weight:bold;}',
      '#metrics-panel .mt-good{color:#00ff88;font-weight:bold;}',
      '#metrics-panel .mt-bad{color:#ff5566;font-weight:bold;}',
      '#metrics-panel .mt-info{color:#00d4ff;}',
      '#metrics-panel .mt-flat{color:#5a8ab0;}',
      '#metrics-panel .mt-dv{color:#ffcc00;font-size:9px;cursor:help;}',
      '#metrics-panel .mt-sub2{font-size:10.5px;color:#7ab8e0;font-weight:bold;margin:10px 0 4px;',
      'border-top:1px dashed #1a3a5c;padding-top:8px;}',
      '#metrics-panel .mt-flow td{color:#9fc3df;}',
      '#metrics-panel .mt-flow td.arrow{color:#3a6a90;text-align:center;}',
      '#metrics-panel .mt-legend{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:10px;color:#7ab8e0;margin-top:8px;',
      'border-top:1px solid #1a3a5c;padding-top:7px;}',
      '#metrics-panel .mt-legend i{display:inline-block;width:16px;height:7px;border-radius:2px;margin-right:5px;vertical-align:0;}',
      '#metrics-panel .mt-note{font-size:9.5px;color:#3a6a90;margin-top:6px;line-height:1.65;}'
    ].join('');
    document.head.appendChild(st);
  }

  function ensurePanel() {
    if (state.built && document.getElementById('metrics-panel')) return document.getElementById('metrics-panel');
    injectStyle();
    var box = document.createElement('div');
    box.id = 'metrics-panel';
    box.innerHTML =
      '<div class="mt-head">' +
        '<span class="mt-title">仿真评价指标</span>' +
        '<span class="mt-sub">基准方案 vs 优化方案 · 依方案 2.7</span>' +
        '<span class="mt-close" id="mt-close" title="关闭（可点工具栏按钮重开）">✕</span>' +
      '</div>' +
      '<div class="mt-ctrl">' +
        '<div class="mt-grp"><label>场景</label>' +
          '<button class="mt-btn" data-scen="holiday">节假日</button>' +
          '<button class="mt-btn" data-scen="weekday">工作日</button>' +
        '</div>' +
        '<div class="mt-grp" style="margin-left:auto"><label>地图视图</label>' +
          '<button class="mt-btn" data-view="base">基准</button>' +
          '<button class="mt-btn" data-view="opt">优化</button>' +
        '</div>' +
      '</div>' +
      '<div class="mt-segrow" id="mt-segrow"></div>' +
      '<div id="mt-body"></div>' +
      '<div class="mt-legend">' +
        '<span><i style="background:#00ff88"></i>&lt;0.70 充裕</span>' +
        '<span><i style="background:#ffcc00"></i>0.70–0.90 偏紧</span>' +
        '<span><i style="background:#ff8800"></i>0.90–1.05 逼近容量</span>' +
        '<span><i style="background:#ff3344"></i>≥1.05 超饱和</span>' +
      '</div>' +
      '<div class="mt-note" id="mt-note"></div>';
    document.getElementById('app').appendChild(box);
    document.getElementById('mt-close').onclick = function () { setOn(false); };
    box.querySelectorAll('.mt-btn[data-scen]').forEach(function (b) {
      b.onclick = function () { var s = b.getAttribute('data-scen'); if (s !== state.scenario) loadDoc(s); };
    });
    box.querySelectorAll('.mt-btn[data-view]').forEach(function (b) {
      b.onclick = function () { state.view = b.getAttribute('data-view'); syncCtrl(); drawMap(); };
    });
    state.built = true;
    return box;
  }

  function syncCtrl() {
    var box = document.getElementById('metrics-panel');
    if (!box) return;
    box.querySelectorAll('.mt-btn[data-scen]').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-scen') === state.scenario);
    });
    box.querySelectorAll('.mt-btn[data-view]').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-view') === state.view);
    });
  }

  // 运段选择条
  function renderSegRow() {
    var row = document.getElementById('mt-segrow');
    if (!row) return;
    if (!state.doc) { row.innerHTML = ''; return; }
    var chips = ['<button class="mt-seg' + (state.seg ? '' : ' active') + '" data-seg="">全网汇总</button>'];
    var names = ((state.doc.baseline || {}).metrics || {}).per_line || [];
    var order = names.map(function (l) { return l.line; })
      .sort(function (a, b) {
        var ia = SEG_ORDER.indexOf(a), ib = SEG_ORDER.indexOf(b);
        if (ia < 0) ia = 99; if (ib < 0) ib = 99;
        return ia - ib;
      });
    order.forEach(function (n) {
      var m = segMeta(n);
      chips.push('<button class="mt-seg' + (state.seg === n ? ' active' : '') + '" data-seg="' + esc(n) + '">' +
        esc(m.label) + '</button>');
    });
    row.innerHTML = chips.join('');
    row.querySelectorAll('.mt-seg').forEach(function (b) {
      b.onclick = function () {
        state.seg = b.getAttribute('data-seg') || null;
        renderPanel();
        drawMap();
      };
    });
  }

  function renderPanel() {
    var box = ensurePanel();
    if (!box) return;
    box.style.display = 'block';
    syncCtrl();
    var body = document.getElementById('mt-body');
    var note = document.getElementById('mt-note');
    if (!state.doc) {
      document.getElementById('mt-segrow').innerHTML = '';
      body.innerHTML = '<div style="font-size:11px;color:#7ab8e0;background:rgba(0,10,25,.6);' +
        'border-left:3px solid #ff5566;border-radius:3px;padding:8px 10px;line-height:1.8">' +
        '未找到决策文档 <code style="color:#ffcc00">agent_decision_' + esc(state.scenario) + '.json</code>。' +
        '请先运行后端 <code style="color:#ffcc00">python3 run_agent.py</code> 产出数据。</div>';
      if (note) note.textContent = '';
      return;
    }
    renderSegRow();

    var recId = (state.rec || {}).id || state.doc.recommended || '—';
    var recName = (state.rec || {}).name || '';
    var segName = state.seg;
    var rows = segName ? buildSegIndicators(segName) : buildIndicators();

    var crumb;
    if (segName) {
      var meta = segMeta(segName);
      var bl = findLineMetric((state.doc.baseline || {}).metrics || {}, segName) || {};
      var fromTo = segEndpoints(segName);
      crumb = '<div class="mt-crumb">运段：' + esc(meta.label) +
        (fromTo ? ' <span>（' + esc(fromTo) + '）</span>' : '') +
        '<br><span>属性 ' + esc(meta.kind) + ' · 线路长度 ' + fmt(bl.length_km, 1) + ' km · 断面客流 ' +
        fmt(bl.demand_ph, 0) + ' 人/h</span></div>';
    } else {
      crumb = '<div class="mt-crumb">粒度：<span>全网汇总（12 条线路 / 34 站）</span></div>';
    }

    var thead = '<tr><th>' + (segName ? '运段评价指标' : '评价指标') + '</th><th>基准方案</th>' +
      '<th>优化方案 ' + esc(recId) + '</th><th>变化</th></tr>';
    var tbody = rows.map(function (r) {
      var dv = r.derived ? ' <span class="mt-dv" title="△ 推演口径：' + esc(r.src) + '">△</span>' : '';
      return '<tr>' +
        '<td title="' + esc(r.src) + '">' + esc(r.name) + '<span class="mt-u">' + esc(r.unit) + '</span>' + dv + '</td>' +
        '<td>' + fmt(r.base, 2) + '</td>' +
        '<td class="mt-opt">' + fmt(r.opt, 2) + '</td>' +
        '<td>' + deltaCell(r) + '</td>' +
      '</tr>';
    }).join('');

    var html =
      crumb +
      '<div style="font-size:10px;color:#5a8ab0;margin-bottom:6px">' +
        '优化方案：<b style="color:#fff">' + esc(recId) + '</b> ' + esc(recName) + '</div>' +
      '<table><thead>' + thead + '</thead><tbody>' + tbody + '</tbody></table>';

    // 运段视图附加：该运段内每一物理区段的断面客流
    if (segName) html += flowSectionTable(segName);

    body.innerHTML = html;
    if (note) {
      note.innerHTML = '数据真源：<b style="color:#7ab8e0">agent_decision_' + esc(state.scenario) + '.json</b>' +
        (segName ? ' + <b style="color:#7ab8e0">flow_' + esc(state.scenario) + '.json</b>' : '') +
        '（本站点未持有业务常量）。标 <b style="color:#ffcc00">△</b> 的指标为按文档字段的确定性推演，悬停行首可见公式；' +
        '绿色=改善，红色=恶化，蓝色=中性（供需权衡项）。';
    }
  }

  // 运段起讫（首站—末站）
  function segEndpoints(segName) {
    var sts = segStations(segName);
    if (!sts.length) return '';
    var a = sts[0].name, b = sts[sts.length - 1].name;
    return (a && b && a !== b) ? (a + ' → ' + b) : '';
  }

  // 该运段各物理区段断面客流（来自 flow_*.json 的 segments）
  function flowSectionTable(segName) {
    var fl = state.flow;
    if (!fl || !fl.segments) {
      return '<div class="mt-sub2">区段断面客流</div>' +
        '<div style="font-size:10px;color:#3a6a90">未取到 <code>flow_' + esc(state.scenario) +
        '.json</code>，暂无区段明细。</div>';
    }
    var segs = fl.segments.filter(function (s) { return s.line === segName; });
    if (!segs.length) return '';
    var total = sumBy(segs, function (s) { return s.flow; });
    var maxSeg = maxBy(segs, function (s) { return s.flow; });
    var rows = segs.map(function (s) {
      var pct = total ? (s.flow / total * 100) : 0;
      var col = (s.flow === maxSeg) ? '#ff8800' : '#9fc3df';
      return '<tr class="mt-flow"><td>' + esc(s.from) + ' → ' + esc(s.to) + '</td>' +
        '<td class="arrow">▶</td>' +
        '<td style="color:' + col + '">' + fmt(s.flow, 0) + ' <span class="mt-u">人次/日</span></td>' +
        '<td style="color:#5a8ab0">占 ' + pct.toFixed(1) + '%</td></tr>';
    }).join('');
    return '<div class="mt-sub2">区段断面客流（' + fmt(segs.length, 0) + ' 个物理区段 · 最大 ' + fmt(maxSeg, 0) + ' 人次/日）</div>' +
      '<table><thead><tr><th>区段</th><th></th><th>断面客流</th><th>占比</th></tr></thead><tbody>' +
      rows + '</tbody></table>' +
      '<div style="font-size:9.5px;color:#3a6a90;margin-top:4px">来源：flow_' + esc(state.scenario) +
      '.json segments（段流量由两端站点仿真流量均值近似）</div>';
  }

  // —— 数据加载 ——
  function loadDoc(scen) {
    state.scenario = SCEN_DECISION[scen] ? scen : 'holiday';
    state.flow = null;
    renderPanel();
    loadFlow(state.scenario);
    fetch(SCEN_DECISION[state.scenario] + '?t=' + Date.now())
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (j) {
        state.doc = j;
        state.rec = (j.plans || []).filter(function (p) { return p.id === j.recommended; })[0] || (j.plans || [])[0] || null;
        // 运段仍不存在于新文档时回落到全网
        if (state.seg && !findLineMetric((j.baseline || {}).metrics || {}, state.seg)) state.seg = null;
        renderPanel();
        if (state.on) drawMap();
      })
      .catch(function (e) {
        state.doc = null; state.rec = null;
        console.warn('[赣鄱智轨] 仿真评价指标：决策文档取数失败 ' + e);
        renderPanel();
      });
  }

  function loadFlow(scen) {
    fetch(SCEN_FLOW[scen] + '?t=' + Date.now())
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (j) { state.flow = j; if (state.built) renderPanel(); })
      .catch(function (e) { state.flow = null; console.warn('[赣鄱智轨] 仿真评价指标：断面数据取数失败 ' + e); });
  }

  // —— 开关 ——
  function setOn(on) {
    state.on = !!on;
    var b = document.getElementById('metrics-btn');
    if (b) { b.classList.toggle('active', state.on); b.textContent = state.on ? '仿真评价指标·开启中' : '仿真评价指标'; }
    var box = state.built ? document.getElementById('metrics-panel') : null;
    if (state.on) {
      // 首次打开默认落到「南昌—九江运段」（符合"先在南昌九江落地"的要求），
      // 之后用户可在运段条里切到全网或任意运段。
      if (!state.segInited) { state.seg = '昌九通勤线'; state.segInited = true; }
      renderPanel();
      if (!state.doc) loadDoc(state.scenario); else drawMap();
    } else {
      clearOverlays();
      if (box) box.style.display = 'none';
    }
  }

  function buildButton(retries) {
    if (document.getElementById('metrics-btn')) return;
    var tb = document.getElementById('heatmap-toolbar') || document.querySelector('.toolbar');
    if (!tb) {
      if ((retries || 0) < 20) setTimeout(function () { buildButton((retries || 0) + 1); }, 400);
      return;
    }
    var b = document.createElement('button');
    b.id = 'metrics-btn';
    b.textContent = '仿真评价指标';
    b.title = '按方案 2.7 列出 10 项仿真评价指标，支持「全网 / 运段」两种粒度（先在南昌—九江等运段落地）；并在地图上按断面饱和度着色、标注瓶颈站排队人数';
    b.onclick = function () { setOn(!state.on); };
    tb.appendChild(b);
  }

  // —— 启动 ——
  window.addEventListener('ganpo:mapready', function () {
    state.map = (window.GanpoMap && window.GanpoMap.map) || null;
    try { state.zoom = state.map.getZoom(); } catch (e) {}
    // 缩放联动：级别变化后按新级别重算标注框字号与圈半径（幂等重绘）
    try {
      state.map.addEventListener('zoomend', function () {
        try { state.zoom = state.map.getZoom(); } catch (e) {}
        if (state.on) drawMap();
      });
    } catch (e) {}
    buildNameMaps();
    buildButton();
    if (state.doc && state.on) drawMap();
  });

  // 复用智能体决策面板已加载的文档（避免重复请求；场景跟随其 transport_scenario）
  window.addEventListener('gdp:ready', function (e) {
    var d = (e && e.detail) || window.__GANPO_DECISION__;
    if (!d) return;
    var ts = (d.scenario || {}).transport_scenario;
    if (!state.doc && (!ts || ts === state.scenario)) {
      state.doc = d;
      state.rec = (d.plans || []).filter(function (p) { return p.id === d.recommended; })[0] || (d.plans || [])[0] || null;
      if (!state.flow) loadFlow(state.scenario);
      if (state.built) renderPanel();
      if (state.on) drawMap();
    }
  });

  setTimeout(function () {
    if (!state.map && window.GanpoMap && window.GanpoMap.map) {
      state.map = window.GanpoMap.map; buildNameMaps(); buildButton();
    }
  }, 2500);

  window.GanpoMetrics = {
    toggle: function () { setOn(!state.on); },
    show: function () { setOn(true); },
    hide: function () { setOn(false); },
    // 供其它模块/控制台直接切到某个运段（如 南昌—九江）
    focusSeg: function (simLineName) {
      state.seg = simLineName || null;
      if (state.on) { renderPanel(); drawMap(); }
      return state.seg;
    },
    state: state
  };
})();
