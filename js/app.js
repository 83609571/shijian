/* ======================================================================
 * app.js · 模块导航整合（线路精简版）
 * ----------------------------------------------------------------------
 * 线路版变更（2026-10-10）：
 *   · 「通勤层 / 旅游层 / 工作日活动模式 / 周末节假日模式」四项合并为
 *     导航「线路」一个开关：只显示线路（通勤+旅游统一着色、不区分黄/红），
 *     不再显示站点圆点、站名、大巴白点、齿轨段等其他图案。
 *   · 移除「路段流量（客流标注）」模块与「百度实时路况」入口。
 *   · 「客流热力」模块已移除（2026-10-10 二次精简）。
 *   · 「线网一张图 / 线路 / 列车运行」合并为「线网一张图」一个开关
 *     （未全开→全开+视野重置；已全开→全关；2026-10-10 四次迭代）。
 * 其余模块（线网一张图 / 列车运行 / 智能体面板 / 换乘仿真 / 仿真评价指标 /
 * 应急演示）与工具栏折叠 / 地图控件开关原样保留。
 * ====================================================================== */
(function () {
  'use strict';

  // switchable:true 的条目是「开关型」按钮 ——
  //   点击只切换自身，不清除其他按钮高亮；按钮高亮 = 该功能当前"显示中"。
  //   高亮状态由 syncNavStates() 依据各模块真实状态回填（2026-10-08 统一口径）。
  var NAV = [
    // ★ 线网一张图 = 线路 + 列车运行 + 视野重置 三合一（2026-10-10）：
    //   未全开 → 点击全开（线路+站点流量标注、列车运行动画）并回到标准江西全景视野；
    //   已全开 → 点击全关。
    { key: 'network',  label: '线网一张图',  act: toggleNetwork,  switchable: true },
    { key: 'agent',    label: '智能体面板', act: toggleAgent,    switchable: true },
    { key: 'transfer', label: '换乘仿真',   act: toggleTransfer, switchable: true },
    // ★ 仿真评价指标（依方案 2.7）：10 项指标 · 基准 vs 优化方案对比
    { key: 'metrics',  label: '仿真评价指标', act: toggleMetrics, switchable: true },
    // ★ 智能体决策面板已归入「应急演示」模块 ★
    // 面板的四个场景（日常运营 / 暴雨边坡 / 列车故障 / 大客流）本身就是应急场景，
    // 且原本就通过 broadcast() 调用 GanpoEmergency.setScene() 驱动地图。
    { key: 'emergency', label: '应急演示',  act: toggleEmergency, switchable: true }
  ];

  function resetView() {
    var m = window.GanpoMap && window.GanpoMap.map;
    if (!m) return;
    try {
      // 与 map-base.js 初始视野保持一致：只显示江西省
      m.setHeading(30);
      m.setTilt(35);
      m.setViewport([new BMapGL.Point(113.5, 24.4), new BMapGL.Point(118.6, 30.2)]);
    } catch (e) {}
  }

  // —— 线网一张图（线路 + 列车运行 + 视野重置 三合一）——
  // 线路版地图只保留线路本体（统一着色），本开关同时控制：
  //   线路 + 站点小点 + 流量标注（GanpoMap 'lines' 总开关）、列车运行动画、标准视野。
  function isLinesOn() {
    var g = window.GanpoMap;
    return !!(g && g.getLayer && g.getLayer('lines'));
  }
  function isTrainOn() {
    var t = window.GanpoTrainSim;
    return !!(t && t._on);
  }
  function toggleNetwork() {
    var target = !(isLinesOn() && isTrainOn());   // 未全开 → 全开；已全开 → 全关
    var g = window.GanpoMap;
    if (g && g.setLayer && g.getLayer('lines') !== target) g.setLayer('lines', target);
    var t = window.GanpoTrainSim;
    if (t && !!t._on !== target) {
      t._on = target;
      try { target ? t.start() : t.stop(); } catch (e) {}
    }
    resetView();
    syncNavStates();
  }

  // —— 客流热力模块已移除（2026-10-10 二次精简）——

  // 所有「开关型」按钮的高亮 = 对应功能当前是否开启（与"当前激活模块"是两回事）
  function syncNavStates() {
    var nav = document.getElementById('module-nav');
    if (!nav) return;
    function set(key, on) {
      var b = nav.querySelector('button[data-key="' + key + '"]');
      if (b) b.classList.toggle('active', !!on);
    }
    var g = window.GanpoMap;
    var ls = (g && g.getLayers) ? g.getLayers() : { lines: true };
    set('network', ls.lines !== false);   // 「线网一张图」高亮 = 线路显示中（列车为伴生动效）
    // —— 以下为各功能模块的真实开关状态 ——
    var tr = window.GanpoTransfer;
    set('transfer', !!(tr && tr._on));
    set('agent', agentPanelVisible());
    set('emergency', agentPanelVisible());
    var mt = window.GanpoMetrics;
    set('metrics', !!(mt && mt.state && mt.state.on));
  }
  // 智能体面板当前是否可见（供开关高亮与开/关判断）
  function agentPanelVisible() {
    var p = document.getElementById('agent-panel');
    return !!(p && p.style.display !== 'none');
  }
  // 智能体面板：可开可关（已打开 → 再点关闭；已关闭 → 打开）
  function toggleAgent() {
    var ap = window.GanpoAgentPanel;
    if (agentPanelVisible()) {
      if (ap && ap.close) ap.close();
      else { var p = document.getElementById('agent-panel'); if (p) p.style.display = 'none'; }
    } else if (ap && ap.open) {
      ap.open();
    } else {
      var p2 = document.getElementById('agent-panel');
      if (p2) p2.style.display = 'block';
    }
    syncNavStates();
  }
  function toggleTransfer() {
    var t = window.GanpoTransfer; if (!t) return;
    t._on ? (t._on = false, t.hide()) : (t._on = true, t.show());
    syncNavStates();
  }
  // 仿真评价指标：10 项指标面板 + 地图指标图层（与热力/应急互斥，一次只聚焦一层）
  function toggleMetrics() {
    var m = window.GanpoMetrics; if (!m) return;
    if (m.state && m.state.on) { m.hide(); }
    else {
      var em = window.GanpoEmergency; if (em && em.setScene) em.setScene('normal');
      m.show();
    }
    syncNavStates();
  }
  // 应急演示 = 智能体决策面板（主体）+ 地图应急场景联动
  // ★ 再点一次 = 关闭面板
  function toggleEmergency() {
    // 面板已打开 → 关闭并同步高亮
    if (agentPanelVisible()) { toggleAgent(); return; }
    var ap = window.GanpoAgentPanel;
    if (ap && ap.open) {
      ap.open();
    } else {
      var p = document.getElementById('agent-panel');
      if (p) p.style.display = 'block';
    }
    // 若存在独立应急按钮则触发它；否则由面板自身的 broadcast() 驱动地图场景
    var b = document.getElementById('emergency-btn');
    if (b) { b.click(); }
    else if (ap && ap.applyScene) { ap.applyScene(); }

    syncNavStates();
  }

  // —— 左上工具栏可收起 / 右上地图缩放控件可开关 ——
  // 工具栏按钮由各模块在 mapready 后陆续插入，这里用重试轮询等容器就绪。
  // （线路版说明：热力工具栏已随场景按钮一并移除，容器以首个 .toolbar 为准。）
  function initToolbarToggles(retries) {
    var tb = document.getElementById('heatmap-toolbar') || document.querySelector('.toolbar');
    if (!tb) {
      if ((retries || 0) < 25) setTimeout(function () { initToolbarToggles((retries || 0) + 1); }, 400);
      return;
    }
    if (document.getElementById('tb-fold')) return;

    // ① 工具栏整体收起 / 展开
    var fold = document.createElement('button');
    fold.id = 'tb-fold';
    fold.textContent = '— 收起工具栏';
    fold.title = '收起 / 展开左上工具栏按钮';
    fold.onclick = function () {
      var folded = tb.classList.toggle('folded');
      fold.textContent = folded ? '＋ 展开工具栏' : '— 收起工具栏';
    };
    tb.insertBefore(fold, tb.firstChild);

    // ② 右上角地图缩放控件 显示 / 隐藏
    //    用几何特征定位（无文字、无图片、贴右上角的小尺寸浮层），
    //    与百度控件类名解耦；恢复时精确还原隐藏过的元素。
    var hiddenCtrls = [];
    function setMapCtrls(on) {
      var mc = document.getElementById('map_container');
      if (!mc) return;
      if (on) {
        hiddenCtrls.forEach(function (el) { try { el.style.display = ''; } catch (e) {} });
        hiddenCtrls = [];
        return;
      }
      var els = mc.querySelectorAll('div');
      for (var i = 0; i < els.length; i++) {
        var el = els[i];
        var cs = null;
        try { cs = window.getComputedStyle(el); } catch (e) { continue; }
        if (cs.position !== 'absolute' && cs.position !== 'fixed') continue;
        if ((el.textContent || '').trim()) continue;       // 有文字 = 标签/信息窗，跳过
        if (el.querySelector('img')) continue;             // 有图片 = 站点图标，跳过
        var r = el.getBoundingClientRect();
        if (r.width > 0 && r.width <= 150 && r.height > 0 && r.height <= 300 &&
            r.top < 90 && r.right > window.innerWidth - 110) {
          try { el.style.display = 'none'; hiddenCtrls.push(el); } catch (e) {}
        }
      }
    }
    var ctrl = document.createElement('button');
    ctrl.id = 'mapctrl-btn';
    ctrl.textContent = '隐藏地图控件';
    ctrl.title = '显示 / 隐藏右上角地图缩放控件';
    ctrl.onclick = function () {
      var off = document.body.classList.toggle('ganpo-mapctrl-off');   // true = 已隐藏
      setMapCtrls(!off);
      ctrl.textContent = off ? '显示地图控件' : '隐藏地图控件';
      ctrl.classList.toggle('active', off);
    };
    tb.appendChild(ctrl);
  }

  function build() {
    var nav = document.getElementById('module-nav');
    if (!nav) return;
    nav.innerHTML = '';
    NAV.forEach(function (item, i) {
      var b = document.createElement('button');
      b.textContent = item.label;
      b.dataset.key = item.key;
      if (item.switchable) b.dataset.switchable = '1';
      // 开关型按钮的 active 由 syncNavStates() 依真实开关状态设置
      b.className = item.switchable ? 'active' : (i === 0 ? 'active' : '');
      b.onclick = function () {
        if (item.switchable) {
          // 开关型：只切换自己，不影响其它按钮高亮
          try { item.act(); } catch (e) {
            console.warn('[赣鄱智轨] 开关 "' + item.label + '" 暂不可用（需地图就绪/AK）', e);
          }
          return;
        }
        // 模块型：只清除"模块型"按钮的高亮，不动开关型按钮的灯
        nav.querySelectorAll('button').forEach(function (x) {
          if (!x.dataset.switchable) x.classList.remove('active');
        });
        b.classList.add('active');
        try { item.act(); } catch (e) { console.warn('[赣鄱智轨] 模块 "' + item.label + '" 暂不可用（需地图就绪/AK）', e); }
        syncNavStates();   // 模块操作可能改变开关状态，回填按钮高亮
      };
      nav.appendChild(b);
    });
    // ★ 仿真实验入口（独立可视化页：消融 + 参数扫描，打开新标签）★
    //   build() 会重建导航，故在此处追加；点开即看 experiments.html
    var ex = document.createElement('a');
    ex.href = 'experiments.html';
    ex.target = '_blank';
    ex.textContent = '仿真实验';
    ex.title = '仿真实验可视化（消融 + 参数矩阵扫描）';
    ex.style.cssText = 'align-self:center;background:linear-gradient(180deg,rgba(20,80,120,.85),rgba(10,50,80,.85));border:1px solid #38bdf8;color:#8fd8ff;padding:6px 12px;border-radius:4px;font-size:12px;font-family:inherit;text-decoration:none;white-space:nowrap;';
    nav.appendChild(ex);
    syncNavStates();
  }

  if (document.readyState !== 'loading') { build(); initToolbarToggles(); }
  else document.addEventListener('DOMContentLoaded', function () { build(); initToolbarToggles(); });

  // 地图就绪（线路对象已建立）后再同步一次开关高亮
  window.addEventListener('ganpo:mapready', function () { syncNavStates(); initToolbarToggles(); });
})();
