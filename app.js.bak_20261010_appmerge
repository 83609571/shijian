/* ======================================================================
 * app.js · 模块导航整合（6 模块快捷开关）
 * ----------------------------------------------------------------------
 * 把顶部 module-nav 接到各模块已暴露的 API。地图未就绪（AK 缺失）时，
 * 纯 DOM 模块（智能体面板/换乘仿真）仍可用；依赖地图的模块点击无操作
 * 但不报错。各模块自身按钮仍可独立使用。
 * ====================================================================== */
(function () {
  'use strict';

  // switchable:true 的条目是「开关型」按钮 ——
  //   点击只切换自身，不清除其他按钮高亮；按钮高亮 = 该层当前"显示中"。
  //   通勤层 / 旅游层各自独立，可同时开、可只开一个、可全部关掉。
  // ★ 2026-10-08：全部功能按钮统一改为开关型（再点一次即关闭），
  //   高亮状态由 syncNavStates() 依据各模块真实状态回填。
  var NAV = [
    { key: 'network',  label: '线网一张图',  act: resetView },
    { key: 'commuter', label: '通勤层',     act: toggleCommuter, switchable: true },
    { key: 'tourism',  label: '旅游层',     act: toggleTourism,  switchable: true },
    // 客流热力同样做成开关型：高亮 = 热力当前是否显示（默认关闭）
    { key: 'heat',     label: '客流热力',   act: toggleHeat,     switchable: true },
    { key: 'train',    label: '列车运行',   act: toggleTrain,    switchable: true },
    { key: 'agent',    label: '智能体面板', act: toggleAgent,    switchable: true },
    { key: 'transfer', label: '换乘仿真',   act: toggleTransfer, switchable: true },
    // ★ 仿真评价指标（依方案 2.7）：10 项指标 · 基准 vs 优化方案对比
    { key: 'metrics',  label: '仿真评价指标', act: toggleMetrics, switchable: true },
    // ★ 路段流量：区段断面客流着色 + 站点/新增站点客流标注
    { key: 'flow',     label: '路段流量',   act: toggleFlow,     switchable: true },
    // ★ 智能体决策面板已归入「应急演示」模块 ★
    // 面板的四个场景（日常运营 / 暴雨边坡 / 列车故障 / 大客流）本身就是应急场景，
    // 且原本就通过 broadcast() 调用 GanpoEmergency.setScene() 驱动地图，
    // 因此不再单列为一个平级模块，改为应急演示模块的主面板。
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
  // 客流热力显隐：统一走 heatmap 模块的 toggle（内部维护唯一状态源）
  // 修复点：旧写法用局部 h._on 自行计数，与模块内部 state.enabled 不同步，
  //         表现为「第一次点导航反而把热力关掉」——这正是用户反馈的"功能冲突"。
  // —— 客流热力开关（默认关闭，与应急演示互斥）——
  // 打开热力时先清空应急演示的覆盖物，保证"一次只看到一个模块的内容"。
  function toggleHeat() {
    var h = window.GanpoHeatmap;
    if (!h) return;
    var on;
    if (typeof h.toggle === 'function') {
      on = h.toggle();
    } else {
      on = !(h.isOn && h.isOn());
      on ? h.show() : h.hide();
    }
    if (on) {
      var em = window.GanpoEmergency;
      if (em && em.setScene) em.setScene('normal');
    }
    syncNavStates();
  }

  // —— 分层开关（通勤层 / 旅游层 两个可自主选择的模块）——
  // 切换时地图上的「线路 + 站点 + 大巴点」一起显隐。
  // 两层都关闭时，大巴随所属层一同消失，不会出现"线没了、白点还在飘"。
  function toggleCommuter() {
    var g = window.GanpoMap;
    if (!g || !g.setLayer) return;
    g.setLayer('commuter', !g.getLayer('commuter'));
    syncNavStates();
  }
  function toggleTourism() {
    var g = window.GanpoMap;
    if (!g || !g.setLayer) return;
    g.setLayer('tourism', !g.getLayer('tourism'));
    syncNavStates();
  }

  // 所有「开关型」按钮的高亮 = 对应功能当前是否开启（与"当前激活模块"是两回事）
  function syncNavStates() {
    var nav = document.getElementById('module-nav');
    if (!nav) return;
    function set(key, on) {
      var b = nav.querySelector('button[data-key="' + key + '"]');
      if (b) b.classList.toggle('active', !!on);
    }
    var g = window.GanpoMap;
    var ls = (g && g.getLayers) ? g.getLayers() : { commuter: true, tourism: true };
    set('commuter', ls.commuter);
    set('tourism',  ls.tourism);
    var h = window.GanpoHeatmap;
    set('heat', h && h.isOn ? h.isOn() : false);
    // —— 以下为各功能模块的真实开关状态（2026-10-08 统一开关型）——
    var t = window.GanpoTrainSim;
    set('train', !!(t && t._on));
    var tr = window.GanpoTransfer;
    set('transfer', !!(tr && tr._on));
    set('agent', agentPanelVisible());
    set('emergency', agentPanelVisible());
    var mt = window.GanpoMetrics;
    set('metrics', !!(mt && mt.state && mt.state.on));
    var fl = window.GanpoFlowLayer;
    set('flow', !!(fl && fl.state && fl.state.on));
  }
  function toggleTrain() {
    var t = window.GanpoTrainSim; if (!t) return;
    if (t._on) { t._on = false; t.stop(); } else { t._on = true; t.start(); }
    syncNavStates();
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
  // 路段流量图层（js/flow-layer.js）：区段拥挤度着色 + 站点/新增站点客流
  function toggleFlow() {
    var f = window.GanpoFlowLayer; if (!f) return;
    f.toggle();
    syncNavStates();
  }
  // 仿真评价指标：10 项指标面板 + 地图指标图层（与热力/应急互斥，一次只聚焦一层）
  function toggleMetrics() {
    var m = window.GanpoMetrics; if (!m) return;
    if (m.state && m.state.on) { m.hide(); }
    else {
      var h = window.GanpoHeatmap; if (h && h.hide) h.hide();
      var em = window.GanpoEmergency; if (em && em.setScene) em.setScene('normal');
      m.show();
    }
    syncNavStates();
  }
  // 应急演示 = 智能体决策面板（主体）+ 地图应急场景联动
  // 面板内容（四场景按钮 / 四智能体卡片 / 底部客流与数据来源）全部原样保留，
  // 仅改变它的模块归属层级：从"平级模块"变为"应急演示模块的主面板"。
  // ★ 2026-10-08：再点一次 = 关闭面板（需求：占据半屏的智能面板可以关闭）
  function toggleEmergency() {
    // 面板已打开 → 关闭并同步高亮
    if (agentPanelVisible()) { toggleAgent(); return; }
    // 应急演示与客流热力互斥：打开应急演示先把热力收起，避免两者叠在一起出现
    var h = window.GanpoHeatmap;
    if (h && h.hide) h.hide();

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

  // —— 左上工具栏可收起 / 右上地图缩放控件可开关（2026-10-08）——
  // 工具栏按钮由各模块在 mapready 后陆续插入，这里用重试轮询等容器就绪。
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
    syncNavStates();
  }

  if (document.readyState !== 'loading') { build(); initToolbarToggles(); }
  else document.addEventListener('DOMContentLoaded', function () { build(); initToolbarToggles(); });

  // 地图就绪（分层对象已建立）后再同步一次开关高亮
  window.addEventListener('ganpo:mapready', function () { syncNavStates(); initToolbarToggles(); });
})();
