/* ======================================================================
 * 模块一 · 线网一张图（百度地图 JSAPI GL 基座）
 * ----------------------------------------------------------------------
 * 职责：初始化 3D 地图底座 + 通勤(蓝)/旅游(绿)线路 + 站点 Marker +
 *       点击 InfoWindow。暴露 window.GanpoMap 供后续模块(热力/列车/
 *       智能体面板/应急)复用地图实例与覆盖物。
 * 依赖：先加载 config.js（window.GanpoConfig），再由 index.html 动态
 *       注入百度地图 JSAPI GL（&ak=...），加载完成后回调 initMap()。
 * ====================================================================== */
(function () {
  'use strict';

  // 生成彩色圆点图标（SVG data URL），按线路类型染色
  function dotIcon(color) {
    var svg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18">' +
      '<circle cx="9" cy="9" r="6" fill="' + color + '" stroke="#ffffff" stroke-width="2"/>' +
      '</svg>';
    var url = 'data:image/svg+xml;base64,' + btoa(svg);
    // BMapGL.Icon(图片地址, 尺寸)；尺寸对象用 BMapGL.Size
    try {
      return new BMapGL.Icon(url, new BMapGL.Size(18, 18));
    } catch (e) {
      return null; // 退回默认红色 pin
    }
  }

  // 创建带样式的站点名 Label
  function makeLabel(name, pt, color) {
    try {
      var label = new BMapGL.Label(name, { position: pt });
      label.setStyle({
        color: '#fff',
        background: 'rgba(0,20,40,0.75)',
        border: '1px solid ' + color,
        padding: '2px 6px',
        fontSize: '11px',
        fontFamily: 'Microsoft YaHei, sans-serif',
        borderRadius: '3px',
        marginLeft: '-24px',
        marginTop: '-26px',
        whiteSpace: 'nowrap'
      });
      return label;
    } catch (e) {
      return null;
    }
  }

  // InfoWindow 内容
  function stationInfoHTML(s) {
    var typeName = s.type === 'commuter' ? '通勤层' : '旅游层';
    var typeColor = s.type === 'commuter' ? GanpoConfig.COLOR.commuter : GanpoConfig.COLOR.tourism;
    return '' +
      '<div style="font-family:Microsoft YaHei,sans-serif;min-width:200px;padding:4px 2px">' +
        '<h3 style="color:' + GanpoConfig.COLOR.accent + ';margin:0 0 8px;font-size:15px">' + s.name + '</h3>' +
        '<div style="font-size:12px;line-height:1.8;color:#d0e6f5">' +
          '日均客流：<b style="color:' + GanpoConfig.COLOR.accent + '">' + s.dailyFlow + '</b><br>' +
          '接驳方式：' + s.transfer + '<br>' +
          '周边景区：' + s.scenic + '<br>' +
          '线路类型：<b style="color:' + typeColor + '">' + typeName + '</b>' +
        '</div>' +
      '</div>';
  }

  // 齿轨爬坡段 InfoWindow 内容（依《以轨代巴》方案 5.2）
  function slopeInfoHTML(sg) {
    return '' +
      '<div style="font-family:Microsoft YaHei,sans-serif;min-width:230px;padding:4px 2px">' +
        '<h3 style="color:#ff8800;margin:0 0 8px;font-size:15px">⚙ ' + sg.name + '</h3>' +
        '<div style="font-size:12px;line-height:1.8;color:#d0e6f5">' +
          '爬坡坡度：<b style="color:#ff8800">' + sg.grade + '</b><br>' +
          '制式：' + sg.system + '<br>' +
          '借鉴案例：' + sg.ref + '<br>' +
          '技术要点：' + sg.note +
        '</div>' +
      '</div>';
  }

  window.initMap = function () {
    if (!window.BMapGL) {
      // ★ 降级保护 ★
      // 百度地图脚本未能加载时（AK 失效 / 白名单未放行当前域名 / 当日配额用尽 / 网络受限），
      // 不再只给一段冷冰冰的报错，而是直接给出可继续观看的入口：
      // 零 AK 版 index.html 不依赖百度地图，六大模块内容完全一致。
      // 这样"无论评委用什么网络、AK 是否可用"，都一定能看到这套内容。
      console.error('[赣鄱智轨] BMapGL 未加载：请检查 js/local-ak.js 是否已配置 AK（或 URL 带 ?ak=）、' +
                'referer 白名单是否包含当前域名与端口、当日配额是否用尽。');
      var box = document.getElementById('map_container');
      if (box) {
        box.innerHTML =
          '<div style="padding:70px 30px;color:#7ab8e0;font-family:Microsoft YaHei;text-align:center;line-height:1.95">' +
            '<h2 style="color:#00d4ff;margin-bottom:16px">百度底图暂时不可用</h2>' +
            '<p style="color:#a0c8e0">页面其余功能与数据均正常。<br>' +
            '可切换到<b style="color:#ffffff">零 AK 版</b>继续查看，六大模块完全一致。</p>' +
            '<p style="margin:26px 0">' +
              '<a href="index.html" style="display:inline-block;padding:13px 34px;background:#00d4ff;color:#001020;' +
              'border-radius:6px;text-decoration:none;font-weight:bold;font-size:15px">前往零 AK 版 →</a>' +
            '</p>' +
            '<p style="font-size:12px;color:#5a8ab0">可能原因：AK 未生效 / referer 白名单未包含当前域名 / 当日配额用尽 / 网络受限</p>' +
            '<p style="font-size:12px;color:#3a6a90">建议在百度控制台把 referer 白名单设为' +
              '<b>实际部署的域名/地址</b>（如 <code>localhost:8000</code>、<code>127.0.0.1:8000</code>）；' +
              '<b>不要设为 <code>*</code></b> —— 通配白名单配合已公开的 AK 等同于把配额敞开给任何人盗刷。</p>' +
          '</div>';
      }
      return;
    }

    var C = GanpoConfig;
    var map = new BMapGL.Map('map_container');

    // ==== 视野收束：只要江西省，不要周边省份 ====
    // 江西省实际地理范围约 经度 113.6~118.5、纬度 24.5~30.1
    var JX_MIN = new BMapGL.Point(113.5, 24.4);
    var JX_MAX = new BMapGL.Point(118.6, 30.2);
    var JX_CENTER = new BMapGL.Point(115.95, 27.35);

    map.enableScrollWheelZoom(true);
    map.enableDragging(true);

    // 3D 倾斜视角（原 55° 过斜，斜看会露出大片邻省；收到 35° 仍然立体但更聚焦）
    try {
      map.setHeading(30);   // 水平旋转角
      map.setTilt(35);      // 俯仰角
    } catch (e) {}

    // 先给一个近似值，再用 setViewport 按屏幕尺寸自适应，让省界刚好铺满视口
    map.centerAndZoom(JX_CENTER, 9);
    try { map.setViewport([JX_MIN, JX_MAX]); } catch (e) { map.setZoom(9); }

    // 缩放限位：7（略小于全省）~ 13（城区细节）
    // 防止滚轮缩到全国（<7）或放大到街道（>13）而丢失"江西全省"这个主体
    try { map.setMinZoom(7); map.setMaxZoom(13); } catch (e) {}

    // 拖拽回弹：把地图中心锁在江西省范围内，拖不出去
    function clampCenter() {
      try {
        var c = map.getCenter();
        var lng = Math.min(118.3, Math.max(113.7, c.lng));
        var lat = Math.min(29.9, Math.max(24.7, c.lat));
        if (Math.abs(lng - c.lng) > 1e-6 || Math.abs(lat - c.lat) > 1e-6) {
          map.panTo(new BMapGL.Point(lng, lat));
        }
      } catch (e) {}
    }
    map.addEventListener('dragend', clampCenter);

    // 江西省界高亮描边（强化"只关注江西"的视觉边界）
    try {
      var bd = new BMapGL.Boundary();
      bd.get('江西省', function (rs) {
        try {
          if (!rs || !rs.boundaries || !rs.boundaries.length) return;
          var pts = rs.boundaries[0].split(';').map(function (p) {
            var xy = p.split(',');
            return new BMapGL.Point(parseFloat(xy[0]), parseFloat(xy[1]));
          });
          map.addOverlay(new BMapGL.Polyline(pts, {
            strokeColor: '#00d4ff',
            strokeWeight: 2,
            strokeOpacity: 0.8
          }));
        } catch (e) {}
      });
    } catch (e) {}

    // —— 江西省 11 个设区市行政区划边界（市级划分）——
    // 百度 Boundary 按行政区名取边界；并发请求过多会触发限流 →
    // 改为「串行 + 间隔 180ms」逐个获取，逐个绘制。
    // 样式用低饱和青蓝细虚线：只作"市级划分"的地理参照，不与黄/红主色线网争焦点。
    (function cityBoundaries() {
      var CITIES = ['南昌市', '九江市', '景德镇市', '萍乡市', '新余市', '鹰潭市',
                    '赣州市', '吉安市', '宜春市', '抚州市', '上饶市'];
      var CITY_STYLE = {
        strokeColor: '#4fa8d8',
        strokeWeight: 1.3,
        strokeOpacity: 0.75,
        strokeStyle: 'dashed',
        strokeDashArray: [7, 6]
      };
      var idx = 0, done = 0;

      function next() {
        if (idx >= CITIES.length) {
          console.log('[赣鄱智轨] 市级行政区划边界已绘制：' + done + '/' + CITIES.length + ' 个设区市');
          return;
        }
        var name = CITIES[idx++];
        try {
          new BMapGL.Boundary().get(name, function (rs) {
            try {
              if (rs && rs.boundaries && rs.boundaries.length) {
                rs.boundaries.forEach(function (bd) {
                  var cpts = bd.split(';').map(function (s) {
                    var xy = s.split(',');
                    return new BMapGL.Point(parseFloat(xy[0]), parseFloat(xy[1]));
                  });
                  if (cpts.length > 1) map.addOverlay(new BMapGL.Polyline(cpts, CITY_STYLE));
                });
                done++;
              }
            } catch (e) {}
            setTimeout(next, 180);   // 串行节流，避开百度限流
          });
        } catch (e) { setTimeout(next, 180); }
      }
      next();
    })();

    // —— 百度实时路况：线路版已移除（2026-10-10）——

    // —— 省外遮罩：只保留江西省，省外用与背景同色的多边形盖住 ——
    // （百度 Polygon 不支持"挖洞"，故用 4 个矩形覆盖江西包围盒以外的全部区域）
    (function provinceMask() {
      var BOX = { minLng: 113.45, maxLng: 118.65, minLat: 24.35, maxLat: 30.25 };
      var rects = [
        // 上（北）
        [[-180, BOX.maxLat], [180, BOX.maxLat], [180, 85], [-180, 85]],
        // 下（南）
        [[-180, -85], [180, -85], [180, BOX.minLat], [-180, BOX.minLat]],
        // 左（西）
        [[-180, BOX.minLat], [BOX.minLng, BOX.minLat], [BOX.minLng, BOX.maxLat], [-180, BOX.maxLat]],
        // 右（东）
        [[BOX.maxLng, BOX.minLat], [180, BOX.minLat], [180, BOX.maxLat], [BOX.maxLng, BOX.maxLat]]
      ];
      rects.forEach(function (path) {
        try {
          map.addOverlay(new BMapGL.Polygon(
            path.map(function (p) { return new BMapGL.Point(p[0], p[1]); }),
            {
              strokeColor: 'transparent', strokeWeight: 0, strokeOpacity: 0,
              fillColor: '#0a1628', fillOpacity: 0.96
            }
          ));
        } catch (e) {}
      });
      console.log('[赣鄱智轨] 省外遮罩已启用：仅显示江西省');
    })();

    // 暗色底图
    try { map.setMapStyleV2(C.DARK_STYLE); } catch (e) {}

    var overlays = {
      commuterLines: [],   // Polyline 数组
      tourismLines:  [],
      stationMarkers: [],  // Marker 数组
      stationLabels:  []   // Label 数组
    };

    // —— 分层显隐管理（「通勤层」「旅游层」两个可自主选择的模块开关）——
    // 每一层的所有覆盖物（线路 / 站点 / 大巴点）都登记进 layerObjects，
    // 切换时统一 add / remove，保证「线、站、大巴」三者永远同进同出 ——
    // 因此"两层都不选"时，大巴会随线路一起消失，不会出现线没了白点还在飘。
    var LINES_ON = true;   // 线路总开关（线路版：全部线路统一显隐，不再分通勤/旅游两层）

    // —— 通勤层线路（黄）——
    C.commuterLines.forEach(function (line) {
      var pts = line.coords.map(function (c) { return new BMapGL.Point(c[0], c[1]); });
      var pl = new BMapGL.Polyline(pts, {
        strokeColor: C.COLOR.unified,
        strokeWeight: 4,          // 线宽 6 → 4：整体收细，减少对站名/热力的遮挡
        strokeOpacity: 0.9
      });
      map.addOverlay(pl);
      overlays.commuterLines.push(pl);
    });

    // —— 旅游层线路（红）——
    C.tourismLines.forEach(function (line) {
      var pts = line.coords.map(function (c) { return new BMapGL.Point(c[0], c[1]); });
      var pl = new BMapGL.Polyline(pts, {
        strokeColor: C.COLOR.unified,
        strokeWeight: 4,          // 线宽 6 → 4：与通勤层保持一致
        strokeOpacity: 0.9
      });
      map.addOverlay(pl);
      overlays.tourismLines.push(pl);
    });

    // —— 站点标注：线路版已移除（只显示线路，不显示站点等其他图案）——

    // —— 齿轨爬坡段：线路版已移除（不显示其他图案）——

    // —— 原大巴通行动画：线路版已移除（不显示其他图案）——


    // 暴露给后续模块
    window.GanpoMap = {
      map: map,
      overlays: overlays,
      config: C,

      // —— 分层显隐（导航「通勤层」「旅游层」两个模块开关调用）——
      // 一次性切换该层的：线路 + 站点 + 大巴点。
      // 两层都关闭 → 线路、站点、大巴全部消失
      // （大巴点也登记在 layerObjects 中，所以"不选模块时大巴一同消失"自动成立）。
      // —— 线路总开关（导航「线路」按钮调用）——
      setLayer: function (layer, on) {
        if (layer !== 'lines') return false;
        LINES_ON = !!on;
        overlays.commuterLines.concat(overlays.tourismLines).forEach(function (o) {
          try { LINES_ON ? map.addOverlay(o) : map.removeOverlay(o); } catch (e) {}
        });
        console.log('[赣鄱智轨] 线路 → ' + (LINES_ON ? '显示' : '隐藏'));
        return LINES_ON;
      },
      getLayer: function (layer) { return layer === 'lines' ? LINES_ON : true; },
      getLayers: function () { return { lines: LINES_ON, commuter: LINES_ON, tourism: LINES_ON }; },

      // 工具：按线路名找 Polyline（应急改线/高亮用）
      findLine: function (name) {
        var all = overlays.commuterLines.concat(overlays.tourismLines);
        // 注意：Polyline 本身没存 name，这里按索引与 config 顺序一致
        var idx = -1, pool = null;
        C.commuterLines.forEach(function (l, i) { if (l.name === name) { idx = i; pool = 'commuter'; } });
        C.tourismLines.forEach(function (l, i) { if (l.name === name) { idx = i; pool = 'tourism'; } });
        if (pool === 'commuter') return overlays.commuterLines[idx];
        if (pool === 'tourism')  return overlays.tourismLines[idx];
        return null;
      },
      // 工具：把 [lng,lat] 数组转 Point 数组
      toPoints: function (coords) {
        return coords.map(function (c) { return new BMapGL.Point(c[0], c[1]); });
      }
    };

    // 通知其他模块：地图就绪
    window.dispatchEvent(new CustomEvent('ganpo:mapready', { detail: window.GanpoMap }));
    console.log('[赣鄱智轨] 模块一·线网一张图 已就绪');
  };
})();
