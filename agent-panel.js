/* ======================================================================
 * 模块四 · 智能体决策面板（可折叠隐藏 · 四类智能体 · 接入仿真模型数据）
 * ----------------------------------------------------------------------
 * 依据《应急演示方案——智联赣鄱轨道系统智能应急联动》实现：
 *   四类智能体：灾害预警(≤3s)、维保调度(≤5s)、应急联动(≤5s)、客流预测(≤10s)
 *   四个场景：①日常运营 ②暴雨边坡 ③单轨故障 ④节假日大客流
 * ★ 数据来源（P0-2 修复后的现状）★
 *   本文件负责的「地图应急场景」四张卡片仍是规则镜像 —— 它们的作用只是驱动
 *   地图上的覆盖物（风险段/改线/救援轨迹/大客流圈），不是智能体的决策输出，
 *   因此保留查表实现，并把来源如实标注为「规则镜像」。
 *   真正的智能体输出（Planner-Executor-Critic 的仿真结论、方案打分、护栏判定、
 *   trace 调用链）由 js/agent-decision.js 渲染，数据来自唯一真源：
 *     data/agent_decision.json   ← L3 智能体层产出（run_agent.py）
 *   两者在同一面板上下分列，互不混淆。
 * 面板支持折叠隐藏：点标题栏「—」收起为窄条，点窄条任意处展开。
 * ====================================================================== */
(function () {
  'use strict';

  var URL_DISPATCH = 'data/dispatch_demo.json';
  var URL_FLOW = { weekday: 'data/flow_weekday.json', holiday: 'data/flow_holiday.json' };

  var SCENARIOS = [
    { icon: '🚆', label: '①日常运营',  kind: 'normal', flow: 'weekday' },
    { icon: '⛰',  label: '②暴雨边坡',  kind: 'geo',    flow: 'weekday' },
    { icon: '🛠',  label: '③列车故障',  kind: 'fault',  flow: 'weekday' },
    { icon: '👥', label: '④大客流',    kind: 'flow',   flow: 'holiday' }
  ];

  // 四类智能体（响应时间取自《方案》三、智能体响应逻辑）
  var AGENTS = [
    { id: 'warning', name: '灾害预警智能体', rt: '≤3 秒',  color: '#ff5566' },
    { id: 'maint',   name: '维保调度智能体', rt: '≤5 秒',  color: '#ffaa00' },
    { id: 'rescue',  name: '应急联动智能体', rt: '≤5 秒',  color: '#00ff88' },
    { id: 'flow',    name: '客流预测智能体', rt: '≤10 秒', color: '#00d4ff' }
  ];

  var state = { current: 0, collapsed: false, flow: {}, dispatch: null };

  // ---------- 客流 Top3（来自客流仿真模型输出）----------
  function top3(flowData) {
    if (!flowData || !flowData.stations || !flowData.stations.length) return '客流仿真数据接入中…';
    var arr = flowData.stations.slice().sort(function (a, b) { return b.flow - a.flow; }).slice(0, 3);
    return 'Top3：' + arr.map(function (s) { return s.name + ' ' + Number(s.flow).toLocaleString(); }).join(' · ');
  }
  function total(flowData) {
    if (!flowData || !flowData.stations) return '—';
    var sum = flowData.stations.reduce(function (a, s) { return a + Number(s.flow || 0); }, 0);
    return Number(sum).toLocaleString() + ' 人次/日';
  }

  // ---------- 各场景 × 四类智能体的决策内容 ----------
  function decisions(kind, flowData) {
    var t3 = top3(flowData);
    if (kind === 'geo') return {
      warning: { act: '边坡位移超限，判定地质灾害**红色预警**', extra: '三清山—婺源区间 · 连续降雨超阈值 · 位移传感器触发' },
      maint:   { act: '区段单轨列车**限速 20 km/h**，轨道状态加密巡检', extra: '监测数据实时回传数字孪生平台' },
      rescue:  { act: '列车**改经婺源东站**绕行风险区；启动上饶—婺源应急接驳巴士；昌九线加开 1 列临时列车疏解滞留旅客', extra: '改线路径绿色虚线动画 · 应急巴士黄色虚线' },
      flow:    { act: '预测滞留旅客峰值，环线发车间隔动态调整至 **30 分钟**', extra: t3 }
    };
    if (kind === 'fault') return {
      warning: { act: '车辆状态监测自动报警：**牵引逆变器过温保护**', extra: '庐山—庐山西海区间 · 列车失去动力迫停' },
      maint:   { act: '先尝试**远程复位**；失败则从九江站调派备用单轨前往**连挂救援**，工单自动派发最近维修班组', extra: '闭环处置方案 ≤5 秒生成' },
      rescue:  { act: '昌九通勤线九江站**加开临时列车**接驳受影响旅客；车载广播 + APP 同步推送', extra: '旅客疏散路径绿色箭头引导' },
      flow:    { act: '调整后续环庐山线发车间隔，**避免列车积压**', extra: t3 }
    };
    if (kind === 'flow') return {
      warning: { act: '三清山站、婺源站热力值**飙红**，触发大客流预警', extra: '上饶站单轨站台候车超设计容量 120%' },
      maint:   { act: '站台设备与闸机状态巡检，保障疏散通道畅通', extra: '—' },
      rescue:  { act: '启动**三级限流**（三清山站只出不进）；环线发车间隔 **15→8 分钟**；加开上饶—南昌/九江临时市域列车', extra: '联动通勤层疏解返程客流' },
      flow:    { act: '节假日全网客流为工作日 **2.02 倍**，建议提前加密班次', extra: t3 }
    };
    return {
      warning: { act: '全线监测中，无异常告警', extra: '边坡 / 降雨 / 轨道状态正常' },
      maint:   { act: '设备健康度正常，无待办工单', extra: '—' },
      rescue:  { act: '通勤层与旅游层**按计划运行**', extra: '一线两用，运力互备' },
      flow:    { act: '按既定发车间隔运行', extra: t3 }
    };
  }

  function md(s) {
    return String(s || '').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  }

  // ---------- DOM ----------
  function build() {
    if (document.getElementById('agent-panel')) return;
    var box = document.createElement('div');
    box.id = 'agent-panel';
    box.innerHTML =
      '<div class="ap-head" id="ap-head">' +
        '<span class="ap-title">应急演示 · 智能体决策面板</span>' +
        '<span class="ap-agents-tag">四智能体协同</span>' +
        '<span class="ap-fold" id="ap-fold" title="收起/展开">—</span>' +
        '<span class="ap-close" id="ap-close" title="关闭面板（可点顶部导航「智能体面板」重新打开）">✕</span>' +
      '</div>' +
      '<div class="ap-body" id="ap-body">' +
        '<div class="ap-scenarios" id="ap-scenarios"></div>' +
        '<div class="ap-sub">地图应急场景（驱动地图覆盖物 · 规则镜像）</div>' +
        '<div class="ap-cards" id="ap-cards"></div>' +
        '<hr class="ap-sep">' +
        '<div id="gdp-root"></div>' +
        '<div class="ap-foot" id="ap-foot"></div>' +
      '</div>';
    document.getElementById('app').appendChild(box);
    // 线路版（2026-10-10）：智能体面板初始收起——加载即"只显示线路"；
    // 需要时点顶部导航「智能体面板」或「应急演示」打开。
    box.style.display = 'none';

    var sc = document.getElementById('ap-scenarios');
    SCENARIOS.forEach(function (s, i) {
      var b = document.createElement('button');
      b.className = 'ap-btn' + (i === 0 ? ' active' : '');
      b.innerHTML = s.icon + ' ' + s.label;
      b.onclick = function () { select(i); };
      sc.appendChild(b);
    });

    // 折叠 / 展开
    document.getElementById('ap-fold').onclick = function (e) {
      e.stopPropagation();
      setCollapsed(!state.collapsed);
    };
    document.getElementById('ap-head').onclick = function () {
      if (state.collapsed) setCollapsed(false);
    };
    // ★ 完全关闭（2026-10-08）：面板占半屏，点 ✕ 整体隐藏；
    //   顶部导航「智能体面板 / 应急演示」按钮可重新打开。
    document.getElementById('ap-close').onclick = function (e) {
      e.stopPropagation();
      var box = document.getElementById('agent-panel');
      if (box) box.style.display = 'none';
    };
  }

  function setCollapsed(v) {
    state.collapsed = v;
    var box = document.getElementById('agent-panel');
    if (!box) return;
    box.classList.toggle('ap-collapsed', v);
    document.getElementById('ap-fold').textContent = v ? '+' : '—';
    document.getElementById('ap-fold').title = v ? '展开面板' : '收起面板';
  }

  function syncButtons() {
    document.querySelectorAll('#ap-scenarios .ap-btn').forEach(function (b, i) {
      b.classList.toggle('active', i === state.current);
    });
  }

  function card(agent, d) {
    return '<div class="ap-card" style="border-top-color:' + agent.color + '">' +
      '<div class="ap-card-name" style="color:' + agent.color + '">' +
        agent.name + '<span class="ap-rt">' + agent.rt + '</span></div>' +
      '<div class="ap-act">' + md(d.act) + '</div>' +
      (d.extra ? '<div class="ap-reason">' + md(d.extra) + '</div>' : '') +
      '</div>';
  }

  function render() {
    var s = SCENARIOS[state.current];
    var fd = state.flow[s.flow];
    var d = decisions(s.kind, fd);
    document.getElementById('ap-cards').innerHTML =
      AGENTS.map(function (a) { return card(a, d[a.id] || {}); }).join('');
    document.getElementById('ap-foot').innerHTML =
      '<span>地图应急场景：' + s.icon + ' ' + s.label + '　全网客流 <b>' + total(fd) + '</b></span>' +
      '<span class="ap-source">本行文案来源：<b>规则镜像</b>（仅驱动地图覆盖物）· ' +
      '智能体真实输出见上方决策面板（agent_decision.json）</span>';
  }

  // ---------- 场景联动：只驱动「应急演示」 ----------
  // ★ 已解除对客流热力的联动 ★
  // 原先这里还会调用 hm.setScenario()，于是"打开应急演示"会顺带切换热力场景，
  // 两个模块总是叠在一起出现。现在彻底分开、一一对应：
  //   应急演示 → 只改地图上的应急覆盖物（风险区段 / 改线 / 救援轨迹 / 大客流圈）
  //   客流热力 → 只改热力图层（由导航「客流热力」按钮独立开关）
  function broadcast() {
    var s = SCENARIOS[state.current];
    var em = window.GanpoEmergency;
    if (em && em.setScene) em.setScene(s.kind);
  }

  function select(i) {
    state.current = i;
    syncButtons();
    render();
    broadcast();
  }

  // ---------- 数据加载 ----------
  function loadFlow() {
    Object.keys(URL_FLOW).forEach(function (k) {
      fetch(URL_FLOW[k]).then(function (r) { return r.json(); })
        .then(function (j) { state.flow[k] = j; render(); })
        .catch(function () {});
    });
  }

  function start() {
    build();
    loadFlow();
    // ★ 挂载 L3 智能体决策面板（消费 data/agent_decision.json）★
    if (window.GanpoDecisionPanel) {
      window.GanpoDecisionPanel.mount('gdp-root');
      // 决策文档就绪后重绘一次应急覆盖物：风险段/改线改为取自文档（由真实拓扑推出）
      window.addEventListener('gdp:ready', function () {
        var em = window.GanpoEmergency;
        if (em && em.setScene) em.setScene(state.sceneKind || 'normal');
      });
    } else {
      console.warn('[赣鄱智轨] js/agent-decision.js 未加载，智能体决策面板不可用。');
    }
    fetch(URL_DISPATCH).then(function (r) { return r.json(); })
      .then(function (j) { state.dispatch = j; render(); })
      .catch(function () { render(); });
    render();
  }

  window.addEventListener('ganpo:mapready', start);
  if (document.readyState !== 'loading') start();
  else document.addEventListener('DOMContentLoaded', start);

  window.GanpoAgentPanel = {
    setScenario: function (i) { select(i); },
    toggle: function () { setCollapsed(!state.collapsed); },

    // —— 以下供「应急演示」模块调用（面板已归入该模块）——
    // open()：展开面板（尚未构建则先构建），
    //         四个场景按钮 / 四张智能体卡片 / 底部客流与数据来源全部原样保留。
    open: function () {
      if (!document.getElementById('agent-panel')) build();
      var box = document.getElementById('agent-panel');
      if (!box) return;
      box.style.display = 'block';
      setCollapsed(false);
      render();
    },
    close: function () {
      var box = document.getElementById('agent-panel');
      if (box) box.style.display = 'none';
    },
    // 面板当前是否可见（供 app.js 导航开关高亮回填）
    isOpen: function () {
      var p = document.getElementById('agent-panel');
      return !!(p && p.style.display !== 'none');
    },
    // 把当前场景同步到地图（客流热力 + 应急覆盖物）
    applyScene: broadcast
  };
})();
