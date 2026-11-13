/* ======================================================================
 * 模块五 · 换乘节点动态仿真（最小 demo）
 * ----------------------------------------------------------------------
 * 职责：以南昌站为试点，预演节假日高峰通勤旅客→换乘通道→单轨旅游层
 *       的站内换乘流程，识别拥堵瓶颈。受"真实系统与小比例沙盘融合"思路
 *       启发，此处用 DOM 流向 sankey 表达（省去 3D 站建模成本）。
 * 触发：按钮"换乘仿真·南昌站" 切换显隐；面板内 工作日/节假日 切换换流量。
 * 数据：基于 flow_weekday/holiday.json 的南昌站流量做换乘比例推演（标仿真）。
 * ====================================================================== */
(function () {
  'use strict';

  // 南昌站换乘推演（仿真，标注依据）
  // share = 换乘/到达占比；bottleneck = 通道是否拥堵
  var MODES = {
    weekday:  { arrive: 28000, share: 0.10, tourism: 3000,  bottleneck: false, note: '工作日通勤为主，换乘占比~10%，通道畅通。' },
    holiday:  { arrive: 21000, share: 0.55, tourism: 31200, bottleneck: true,  note: '节假日大量通勤客转旅游，换乘占比~55%，通道拥堵风险高，建议加开疏运列车。' }
  };

  var state = { map: null, mode: 'weekday', animTimer: null, shown: false, phase: 0 };

  function build() {
    if (document.getElementById('transfer-panel')) return;
    var box = document.createElement('div');
    box.id = 'transfer-panel';
    box.innerHTML =
      '<div class="tp-head">' +
        '<span class="tp-title">换乘节点动态仿真 · 南昌站</span>' +
        '<span class="tp-close" id="tp-close">✕</span>' +
      '</div>' +
      '<div class="tp-modes">' +
        '<button data-mode="weekday" class="active">工作日</button>' +
        '<button data-mode="holiday">节假日</button>' +
      '</div>' +
      '<div class="tp-flow" id="tp-flow">' +
        '<div class="tp-col"><div class="tp-node" style="--c:#00b4ff">通勤层到达<div class="tp-val" id="tp-arrive">0</div></div></div>' +
        '<div class="tp-arrow"><div class="tp-bar" id="tp-bar1"></div><div class="tp-label">换乘通道</div></div>' +
        '<div class="tp-col"><div class="tp-node" style="--c:#ffaa00">通道疏运<div class="tp-val" id="tp-transfer">0</div></div></div>' +
        '<div class="tp-arrow"><div class="tp-bar" id="tp-bar2"></div><div class="tp-label">上车</div></div>' +
        '<div class="tp-col"><div class="tp-node" style="--c:#00ff88">单轨旅游层出发<div class="tp-val" id="tp-tourism">0</div></div></div>' +
      '</div>' +
      '<div class="tp-note" id="tp-note"></div>' +
      '<div class="tp-source">流量为仿真推演（基于 flow_*.json 南昌站流量做换乘比例推演）</div>';
    document.getElementById('app').appendChild(box);

    box.querySelector('#tp-close').onclick = hide;
    box.querySelectorAll('.tp-modes button').forEach(function (b) {
      b.onclick = function () {
        state.mode = b.getAttribute('data-mode');
        box.querySelectorAll('.tp-modes button').forEach(function (x) { x.classList.toggle('active', x === b); });
        update();
      };
    });
  }

  function update() {
    var m = MODES[state.mode];
    var max = Math.max(m.arrive, m.transfer || (m.arrive * m.share), m.tourism, 40000);
    var transfer = Math.round(m.arrive * m.share);
    document.getElementById('tp-arrive').textContent = m.arrive.toLocaleString();
    document.getElementById('tp-transfer').textContent = transfer.toLocaleString();
    document.getElementById('tp-tourism').textContent = m.tourism.toLocaleString();
    document.getElementById('tp-bar1').style.width = (transfer / max * 100) + '%';
    document.getElementById('tp-bar2').style.width = (m.tourism / max * 100) + '%';
    document.getElementById('tp-bar1').style.background = m.bottleneck ? '#ff3344' : '#00b4ff';
    var note = document.getElementById('tp-note');
    note.textContent = (m.bottleneck ? '⚠ 拥堵瓶颈：' : '✓ 通道畅通：') + m.note;
    note.className = 'tp-note' + (m.bottleneck ? ' warn' : '');
  }

  // 动画：让到达数字"跳动"模拟实时到达
  function animate() {
    if (state.animTimer) clearInterval(state.animTimer);
    state.phase = 0;
    state.animTimer = setInterval(function () {
      state.phase = (state.phase + 1) % 20;
      var m = MODES[state.mode];
      var jitter = Math.round(m.arrive * (0.95 + 0.1 * Math.sin(state.phase / 20 * Math.PI * 2)));
      var arr = document.getElementById('tp-arrive');
      if (arr) arr.textContent = jitter.toLocaleString();
    }, 200);
  }

  function show() {
    build();
    var box = document.getElementById('transfer-panel');
    box.style.display = 'block';
    state.shown = true;
    update();
    animate();
    if (state.map) {
      try { state.map.centerAndZoom(new BMapGL.Point(115.89, 28.68), 11); } catch (e) {}
    }
    syncButton(true);
  }
  function hide() {
    var box = document.getElementById('transfer-panel');
    if (box) box.style.display = 'none';
    if (state.animTimer) { clearInterval(state.animTimer); state.animTimer = null; }
    state.shown = false;
    syncButton(false);
  }
  function toggle() { state.shown ? hide() : show(); }

  function buildButton() {
    if (document.getElementById('transfer-btn')) return;
    var tb = document.getElementById('heatmap-toolbar') || document.querySelector('.toolbar');
    if (!tb) { tb = document.createElement('div'); tb.className = 'toolbar'; document.getElementById('app').appendChild(tb); }
    var b = document.createElement('button');
    b.id = 'transfer-btn'; b.textContent = '换乘仿真·南昌站';
    b.onclick = toggle;
    tb.appendChild(b);
  }
  function syncButton(active) {
    var b = document.getElementById('transfer-btn');
    if (b) b.classList.toggle('active', active);
  }

  function init() {
    state.map = (window.GanpoMap && window.GanpoMap.map) || null;
    buildButton();
  }
  window.addEventListener('ganpo:mapready', init);
  window.GanpoTransfer = { show: show, hide: hide };
})();
