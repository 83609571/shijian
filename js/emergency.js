/* ======================================================================
 * 模块六 · 应急场景演示（三场景联动 · 依据《应急演示方案》）
 * ----------------------------------------------------------------------
 * 场景一 暴雨边坡滑坡（三清山—婺源段）
 *       · 风险区段红色闪烁
 *       · 改线路径绿色虚线（三清山→上饶→婺源绕行）
 *       · 应急接驳巴士黄色虚线（上饶→婺源）
 * 场景二 单轨列车故障（庐山—庐山西海段）
 *       · 故障区段红色 + 故障车红色图标
 *       · 备用列车蓝色轨迹（九江站 → 庐山站 连挂救援）
 * 场景三 节假日景区大客流（三清山 / 婺源 / 上饶）
 *       · 大客流站点红色脉冲光圈 + 限流标记
 * 由智能体面板场景切换驱动（window.GanpoEmergency.setScene）
 * ====================================================================== */
(function () {
  'use strict';

  var SCENES = {
    geo: {
      name: '暴雨引发边坡滑坡',
      risk: [[118.06, 28.91], [117.86, 29.25]],                    // 三清山—婺源
      detour: [[118.06, 28.91], [117.97, 28.45], [117.86, 29.25]],  // 改线：经上饶绕行
      bus: [[117.97, 28.45], [117.86, 29.25]],                      // 应急巴士
      label: '⚠ 边坡红色预警 · 三清山—婺源区段'
    },
    fault: {
      name: '单轨列车故障',
      risk: [[115.85, 29.55], [115.55, 29.24]],                     // 庐山—庐山西海
      rescue: [[116.00, 29.71], [115.85, 29.55]],                   // 备用列车：九江→庐山
      faultPt: [115.93, 29.50],
      label: '⚠ 牵引系统故障 · 庐山—庐山西海区段'
    },
    flow: {
      name: '节假日景区大客流',
      risk: [], detour: [], bus: [],
      hotspots: [[118.06, 28.91], [117.86, 29.25], [117.97, 28.45]],
      label: '⚠ 大客流预警 · 三清山站候车超设计容量 120%'
    }
  };
  var DETOUR = [[118.06, 28.91], [117.97, 28.45], [116.96, 28.10]]; // 三清山→上饶→龙虎山

  var state = { map: null, scene: 'normal', overlays: [], blinking: [], timer: null, bright: true };

  function toPoints(c) { return c.map(function (p) { return new BMapGL.Point(p[0], p[1]); }); }

  function add(o) { try { state.map.addOverlay(o); state.overlays.push(o); } catch (e) {} }

  function label(text, pt, bg) {
    try {
      var lb = new BMapGL.Label(text, { position: new BMapGL.Point(pt[0], pt[1]) });
      lb.setStyle({
        color: '#fff', background: bg || 'rgba(255,0,255,.92)',
        border: '1px solid rgba(255,255,255,.6)', padding: '4px 9px',
        fontSize: '12px', fontFamily: 'Microsoft YaHei', borderRadius: '4px',
        marginLeft: '-110px', marginTop: '-32px', whiteSpace: 'nowrap'
      });
      return lb;
    } catch (e) { return null; }
  }

  function clearAll() {
    state.overlays.forEach(function (o) { try { state.map.removeOverlay(o); } catch (e) {} });
    state.overlays = [];
    state.blinking = [];
    if (state.timer) { clearInterval(state.timer); state.timer = null; }
  }

  // 闪烁：周期性切换一组覆盖物的透明度
  function startBlink() {
    if (state.timer) clearInterval(state.timer);
    state.timer = setInterval(function () {
      state.bright = !state.bright;
      state.blinking.forEach(function (o) {
        try {
          if (o.setStrokeOpacity) o.setStrokeOpacity(state.bright ? 1 : 0.25);
          if (o.setFillOpacity) o.setFillOpacity(state.bright ? 0.45 : 0.1);
        } catch (e) {}
      });
    }, 620);
  }

  function setScene(kind) {
    if (!state.map) return;
    clearAll();
    state.scene = kind;

    if (kind === 'geo') {
      var s = SCENES.geo;
      // ① 风险区段：红色闪烁
      var risk = new BMapGL.Polyline(toPoints(s.risk), {
        strokeColor: '#ff00ff', strokeWeight: 10, strokeOpacity: 1
      });
      add(risk); state.blinking.push(risk);
      // ② 改线：绿色虚线
      var detour = new BMapGL.Polyline(toPoints(s.detour), {
        strokeColor: '#00ff88', strokeWeight: 5, strokeOpacity: 0.95,
        strokeStyle: 'dashed', strokeDashArray: [10, 8]
      });
      add(detour);
      // ③ 应急巴士：黄色虚线
      var bus = new BMapGL.Polyline(toPoints(s.bus), {
        strokeColor: '#ffcc00', strokeWeight: 4, strokeOpacity: 0.9,
        strokeStyle: 'dashed', strokeDashArray: [6, 8]
      });
      add(bus);
      var lb = label(s.label, s.risk[0]); if (lb) add(lb);
      startBlink();
    } else if (kind === 'fault') {
      var f = SCENES.fault;
      var fr = new BMapGL.Polyline(toPoints(f.risk), {
        strokeColor: '#ff00ff', strokeWeight: 10, strokeOpacity: 1
      });
      add(fr); state.blinking.push(fr);
      // 备用列车救援轨迹：蓝色
      var rescue = new BMapGL.Polyline(toPoints(f.rescue), {
        strokeColor: '#00b4ff', strokeWeight: 5, strokeOpacity: 0.95,
        strokeStyle: 'dashed', strokeDashArray: [8, 6]
      });
      add(rescue);
      // 故障车图标
      try {
        var mk = new BMapGL.Marker(new BMapGL.Point(f.faultPt[0], f.faultPt[1]));
        add(mk); state.blinking.push(null);
      } catch (e) {}
      var fl = label(f.label, f.faultPt); if (fl) add(fl);
      startBlink();
    } else if (kind === 'flow') {
      var c = SCENES.flow;
      c.hotspots.forEach(function (p) {
        try {
          var circle = new BMapGL.Circle(new BMapGL.Point(p[0], p[1]), 9000, {
            strokeColor: '#ff00ff', strokeWeight: 3, strokeOpacity: 0.95,
            fillColor: '#ff00ff', fillOpacity: 0.35
          });
          add(circle); state.blinking.push(circle);
        } catch (e) {}
      });
      var cl = label(c.label, c.hotspots[0]); if (cl) add(cl);
      startBlink();
    }
    // kind === 'normal' → 只清除，不绘制

    console.log('[赣鄱智轨] 应急场景切换 → ' + (SCENES[kind] ? SCENES[kind].name : '日常运营'));
  }

  function start() {
    state.map = (window.GanpoMap && window.GanpoMap.map) || null;
    if (!state.map) return;
    setScene('normal');
  }

  window.addEventListener('ganpo:mapready', start);

  // 对外接口（被 agent-panel broadcast 调用）
  window.GanpoEmergency = {
    setScene: setScene,
    // 兼容旧接口
    setAlert: function (al) { setScene(al === 'slope_risk' ? 'geo' : 'normal'); }
  };
})();
