/* ======================================================================
 * 模块三 · 列车运行仿真（轻量版）
 * ----------------------------------------------------------------------
 * 职责：在地图上模拟列车沿线路移动（进站→通过→出站），展示智能体
 *       调度下的列车运行逻辑。通勤蓝车走昌九走廊，旅游绿车走赣东北环线。
 * 实现：BMapGL.Marker + 自定义沿线动画（BMapGL 无原生 moveAlong），
 *       按 60ms 一帧推进预设插值点，到站短暂停留。
 * ====================================================================== */
(function () {
  'use strict';

  // —— 运行仿真线路清单（覆盖《以轨代巴》方案全部重点线路）——
  // 通勤层：昌九 / 昌抚 / 赣州通勤网络
  // 旅游层：赣东北环线 / 环庐山 / 大觉山支线 / 梅岭红轨
  // 坐标与站点一律从 config.js 同名线路读取，避免"地图画一套、仿真跑另一套"的漂移。
  var LINE_SPEC = [
    { name: '昌九通勤线', layer: 'commuter',
      tech: '标准轮轨制式（昌九走廊地形平缓，无需齿轨）' },
    { name: '昌抚通勤线', layer: 'commuter',
      tech: '标准轮轨为主；局部大坡度段借鉴重庆跨座式单轨（60‰，转弯半径 100m）' },
    { name: '京九通勤线', layer: 'commuter',
      tech: '标准轮轨；对应赣州通勤网络（京九/兴泉/赣韶/赣瑞龙四线增开市域列车）' },
    { name: '赣东北环线·上饶婺源段', layer: 'tourism',
      tech: '米轨+齿轨双制式，借鉴四川都四山地轨道交通（最大坡度 120‰）' },
    { name: '赣东北环线·三清山龙虎山段', layer: 'tourism',
      tech: '米轨+齿轨双制式，三清山段最大坡度 120‰，齿轨段时速 40km/h' },
    { name: '环庐山旅游线', layer: 'tourism',
      tech: '跨座式单轨 + 齿轨驱动模块，借鉴重庆单轨（60‰）与都四齿轨转向架' },
    { name: '大觉山旅游支线', layer: 'tourism',
      tech: '铰接式转向架+齿轨，借鉴江西大觉山"悬崖动车"（13.14km，日运量 2.5 万人次）' },
    { name: '梅岭红轨旅游线', layer: 'tourism',
      tech: '轮轨为主 + 局部齿轨组合，借鉴景区齿轨小火车（坡度 15%，造价约 950 万/列）' }
  ];

  // —— 运行仿真方案说明（点「列车运行仿真」时同步展示）——
  var RUN_INFO = {
    commuter: [
      ['昌九通勤线',     '南昌—永修—共青城—九江'],
      ['昌抚通勤线',     '南昌—向塘—云山—抚州'],
      ['赣州通勤网络',   '京九线 / 兴泉线 / 赣韶线 / 赣瑞龙线增开市域列车']
    ],
    tourism: [
      ['赣东北旅游环线', '上饶—三清山—婺源—龙虎山'],
      ['环庐山旅游线',   '九江—庐山—庐山西海'],
      ['大觉山旅游支线', '抚州—资溪—大觉山'],
      ['梅岭"红轨"旅游线', '南昌—湾里—梅岭']
    ],
    tech: [
      ['重庆跨座式单轨',     '橡胶轮胎',           '最大纵坡 60‰',    '转弯半径 100 米'],
      ['四川都四山地齿轨',   '米轨+齿轨双制式',    '最大坡度 120‰',   '齿轨段 40km/h'],
      ['景区齿轨小火车',     '齿轨+普通轨道组合',  '最大坡度 15%–25%', '约 950 万元/列'],
      ['江西大觉山悬崖动车', '铰接式转向架+齿轨',  '适配悬崖陡坡',     '13.14km · 日运量 2.5 万']
    ]
  };

  // 依 LINE_SPEC 从 config 装配列车（找不到的线路自动跳过，不会报错）
  function buildTrains() {
    var C = window.GanpoConfig;
    if (!C) return [];
    var out = [];
    LINE_SPEC.forEach(function (spec) {
      var pool = spec.layer === 'commuter' ? C.commuterLines : C.tourismLines;
      var line = null;
      (pool || []).forEach(function (l) { if (l.name === spec.name) line = l; });
      if (!line || !line.coords || line.coords.length < 2) return;
      out.push({
        id: spec.name,
        layer: spec.layer,
        name: spec.name,
        color: spec.layer === 'commuter' ? C.COLOR.commuter : C.COLOR.tourism,
        path: line.coords,
        stops: (line.stations || []).map(function (s) { return s.name; }),
        stepMs: spec.layer === 'commuter' ? 70 : 90,
        pause: 5,
        tech: spec.tech
      });
    });
    return out;
  }

  var TRAINS = buildTrains();

  var state = { map: null, trains: [], timer: null, running: false };

  function trainIcon(color) {
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">' +
      '<circle cx="10" cy="10" r="8" fill="' + color + '" stroke="#fff" stroke-width="3"/>' +
      '<circle cx="10" cy="10" r="3" fill="#fff"/></svg>';
    try { return new BMapGL.Icon('data:image/svg+xml;base64,' + btoa(svg), new BMapGL.Size(20, 20)); }
    catch (e) { return null; }
  }

  // 在两点间插值 n 份，返回 [lng,lat] 点序列（含起点，不含终点；逐段拼接）
  function interpPath(path, n) {
    var pts = [];
    for (var i = 0; i < path.length - 1; i++) {
      var a = path[i], b = path[i + 1];
      for (var j = 0; j < n; j++) {
        var t = j / n;
        pts.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
      }
    }
    pts.push(path[path.length - 1]);
    return pts;
  }

  function start() {
    if (state.running) return;
    // 清理旧
    state.trains.forEach(function (t) { if (t.marker) { try { state.map.removeOverlay(t.marker); } catch (e) {} } });
    state.trains = TRAINS.map(function (cfg) {
      var fullPath = interpPath(cfg.path, 40); // 每段插40点 → 平滑
      var segLen = 40; // 每段长度
      var icon = trainIcon(cfg.color);
      var marker = icon ? new BMapGL.Marker(new BMapGL.Point(fullPath[0][0], fullPath[0][1]), { icon: icon })
                        : new BMapGL.Marker(new BMapGL.Point(fullPath[0][0], fullPath[0][1]));
      state.map.addOverlay(marker);
      return { cfg: cfg, fullPath: fullPath, segLen: segLen, i: 0, pauseLeft: 0, marker: marker, label: null };
    });
    state.running = true;
    syncButton();
    showInfo();   // 同步展开方案说明：通勤层/旅游层重点线路 + 爬坡技术借鉴
    var tickIdx = 0;
    state.timer = setInterval(function () {
      tickIdx++;
      state.trains.forEach(function (t) {
        // 到站停留逻辑：当 i 落在段边界 → 暂停
        if (t.pauseLeft > 0) { t.pauseLeft--; return; }
        t.i++;
        if (t.i >= t.fullPath.length) t.i = 0;
        var p = t.fullPath[t.i];
        try { t.marker.setPosition(new BMapGL.Point(p[0], p[1])); } catch (e) {}
        // 段边界 → 到站，短暂停留
        var within = t.i % t.segLen;
        if (within === 0 && t.i !== 0 && t.i !== t.fullPath.length - 1) {
          t.pauseLeft = t.cfg.pause;
          var stopIdx = Math.floor(t.i / t.segLen);
          flashStation(t.cfg.stops[stopIdx]);
        }
      });
    }, 65);
  }

  function stop() {
    if (state.timer) { clearInterval(state.timer); state.timer = null; }
    state.running = false;
    state.trains.forEach(function (t) { if (t.marker) { try { state.map.removeOverlay(t.marker); } catch (e) {} } });
    state.trains = [];
    syncButton();
  }

  function flashStation(name) {
    // 到站时在列车位置闪现站点名
    // （线路区段数与站点数可能不等，取到空值时直接跳过，避免出现"undefined 到站"）
    if (!state.map || !window.BMapGL || !name) return;
    try {
      var label = new BMapGL.Label('🚉 ' + name + ' 到站', { position: state.trains.length ? state.trains[0].marker.getPosition() : new BMapGL.Point(116, 28.5) });
      label.setStyle({ color: '#fff', background: 'rgba(0,180,255,0.9)', border: '1px solid #00d4ff', padding: '3px 8px', fontSize: '12px', borderRadius: '3px', marginLeft: '-60px' });
      state.map.addOverlay(label);
      setTimeout(function () { try { state.map.removeOverlay(label); } catch (e) {} }, 1200);
    } catch (e) {}
  }

  // —— 运行仿真 · 方案说明面板 ——
  // 通勤层 / 旅游层重点线路（方案口径）+ 四类爬坡技术借鉴参数表。
  // 点击「列车运行仿真」时同步展开，让运行画面与方案依据同屏可见。
  function buildInfoPanel() {
    if (document.getElementById('run-panel')) return;
    var box = document.createElement('div');
    box.id = 'run-panel';
    box.innerHTML =
      '<div class="rp-head">' +
        '<span class="rp-title">运行仿真 · 方案说明</span>' +
        '<span class="rp-close" id="rp-close">✕</span>' +
      '</div>' +
      '<div class="rp-sec">' +
        '<div class="rp-sec-title" style="color:#ffcc00">通勤层 · 既有铁路公交化（替代城际大巴）</div>' +
        RUN_INFO.commuter.map(function (it) {
          return '<div class="rp-item"><b>' + it[0] + '</b><span>' + it[1] + '</span></div>';
        }).join('') +
      '</div>' +
      '<div class="rp-sec">' +
        '<div class="rp-sec-title" style="color:#ff3344">旅游层 · 轮轨+齿轨双制式单轨（替代景区大巴）</div>' +
        RUN_INFO.tourism.map(function (it) {
          return '<div class="rp-item"><b>' + it[0] + '</b><span>' + it[1] + '</span></div>';
        }).join('') +
      '</div>' +
      '<div class="rp-sec">' +
        '<div class="rp-sec-title" style="color:#ff8800">爬坡技术借鉴</div>' +
        '<table class="rp-table">' +
          '<tr><th>借鉴对象</th><th>制式</th><th>最大坡度</th><th>核心参数</th></tr>' +
          RUN_INFO.tech.map(function (t) {
            return '<tr><td>' + t[0] + '</td><td>' + t[1] + '</td><td>' + t[2] + '</td><td>' + t[3] + '</td></tr>';
          }).join('') +
        '</table>' +
      '</div>' +
      '<div class="rp-foot">黄点＝通勤层列车　红点＝旅游层列车　白点＝原大巴绕行（慢速对照）</div>';
    document.getElementById('app').appendChild(box);
    box.style.display = 'none';   // 随仿真启动一起展开
    document.getElementById('rp-close').onclick = function () { box.style.display = 'none'; };
  }

  function showInfo() {
    buildInfoPanel();
    var b = document.getElementById('run-panel');
    if (b) b.style.display = 'block';
  }

  function buildButton() {
    if (document.getElementById('train-btn')) return;
    var tb = document.getElementById('heatmap-toolbar') || document.querySelector('.toolbar');
    if (!tb) {
      tb = document.createElement('div'); tb.className = 'toolbar';
      document.getElementById('app').appendChild(tb);
    }
    var b = document.createElement('button');
    b.id = 'train-btn'; b.textContent = '列车运行仿真 ▶';
    b.onclick = function () { state.running ? stop() : start(); };
    tb.appendChild(b);
    buildInfoPanel();
  }
  function syncButton() {
    var b = document.getElementById('train-btn');
    if (b) { b.textContent = state.running ? '列车运行仿真 ⏸' : '列车运行仿真 ▶'; b.classList.toggle('active', state.running); }
  }

  function init() {
    state.map = (window.GanpoMap && window.GanpoMap.map) || null;
    if (!state.map) return;
    buildButton();
  }
  window.addEventListener('ganpo:mapready', init);
  window.GanpoTrainSim = { start: start, stop: stop };
})();
