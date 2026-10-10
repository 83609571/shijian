/* ======================================================================
 * 赣鄱智轨 · 全局配置（线路/站点数据 + 百度地图 AK + 主题色）
 * ----------------------------------------------------------------------
 * 【用户必改】把下面 BMAP_AK 换成你自己的百度地图 AK：
 *   申请入口 https://lbs.baidu.com/apiconsole/key
 *   创建应用→类型选"浏览器端"→把本机调试地址(如 http://localhost:8000
 *   或 http://127.0.0.1:8000)加进 referer 白名单→复制 AK 粘贴到此处。
 *   不填 AK 时地图无法渲染，但 Python 仿真/智能体不受影响。
 * ----------------------------------------------------------------------
 * 坐标说明：下列坐标取自原方案文本，约为 GCJ02/WGS84 经纬度。
 * 百度地图 JSAPI GL 使用 BD09 坐标系，省级缩放下肉眼偏移可接受；
 * 如需精对齐，可用百度"坐标转换"Web服务API转成 BD09 后替换。
 * 2026-09-26 校准：三清山 / 庐山西海 / 龙虎山 / 龟峰 四站按实地位置修正
 * （三清山→118.06,28.91；庐山西海→115.55,29.24；龙虎山→116.96,28.10；
 *   龟峰→117.41,28.32），页面、轨迹与数据文件已同步。
 * ====================================================================== */
// —— 百度地图 AK：不再明文入库 ——
// 【安全说明】原先 AK 以明文写在本文件里（提交后等同于公开泄露，可被盗刷配额）。
//   现改为三级读取：① URL 参数 ?ak=xxx（便于临时换 key）
//                    ② 本地文件 js/local-ak.js（已在 .gitignore 中忽略，**不要**打进参赛包）
//                    ③ 占位符（未配置时地图不可用，但页面会给出明确提示）
//   部署前把真实 AK 填进 js/local-ak.js 即可，config.js 本身可以安全提交。
(function () {
  var qs = (location.search.match(/[?&]ak=([^&]+)/) || [])[1];
  window.GANPO_BMAP_AK = qs ? decodeURIComponent(qs)
    : (window.GANPO_BMAP_AK || '');   // 由 js/local-ak.js 提前注入
})();

window.GanpoConfig = {
  BMAP_AK: window.GANPO_BMAP_AK || 'YOUR_BMAP_AK_HERE',

  // —— 主题色（科技深蓝）——
  COLOR: {
    bg:          '#0a1628',
    commuter:    '#ffcc00',   // 通勤层 黄
    tourism:     '#ff3344',   // 旅游层 红
    // ★ P0-3 修复：应急色原与旅游层同为 #ff3344，叠加时肉眼无法区分。
    //   现用品红 #ff00ff；改线路径用青绿 #00ffcc（与黄/红/橙/白均可辨）。
    emergency:   '#ff00ff',   // 应急 品红
    reroute:     '#00ffcc',   // 改线 青绿
    accent:      '#00d4ff',
    unified:     '#ffffff',   // 线路版：线路统一着色（不区分通勤/旅游）
    panelBg:     'rgba(0,20,40,0.9)',
    panelBorder: '#00d4ff'
  },

  // 百度地图暗色底图样式（setMapStyleV2 的 styleJson）
  DARK_STYLE: {
    styleJson: [
      // 线路版：隐藏底图 POI 图标与文字（景点等红点图案），画面只留线路与行政区划
      { featureType: 'poi',           elementType: 'geometry', stylers: { visibility: 'off' } },
      { featureType: 'poi',           elementType: 'labels',   stylers: { visibility: 'off' } },
      { featureType: 'scenic',        elementType: 'all',      stylers: { visibility: 'off' } },
      { featureType: 'education',     elementType: 'all',      stylers: { visibility: 'off' } },
      { featureType: 'medical',       elementType: 'all',      stylers: { visibility: 'off' } },
      { featureType: 'entertainment', elementType: 'all',      stylers: { visibility: 'off' } },
      { featureType: 'shopping',      elementType: 'all',      stylers: { visibility: 'off' } },
      { featureType: 'estate',        elementType: 'all',      stylers: { visibility: 'off' } },
      { featureType: 'company',       elementType: 'all',      stylers: { visibility: 'off' } },
      { featureType: 'manmade',       elementType: 'all',      stylers: { visibility: 'off' } },
      { featureType: 'land',     elementType: 'geometry', stylers: { color: '#0a1628' } },
      { featureType: 'water',    elementType: 'geometry', stylers: { color: '#0d2a4a' } },
      { featureType: 'road',     elementType: 'geometry', stylers: { color: '#1a3a5c' } },
      { featureType: 'building', elementType: 'geometry', stylers: { color: '#13243d' } },
      { featureType: 'label',    elementType: 'all',      stylers: { color: '#7ab8e0' } },
      { featureType: 'boundary', elementType: 'geometry', stylers: { color: '#2a5a8c' } }
    ]
  },

  // —— 通勤层（蓝色）—— 既有铁路公交化区段 ——
  commuterLines: [
    {
      name: '昌九通勤线',
      coords: [[115.89, 28.68], [115.98, 29.05], [115.99, 29.32], [116.00, 29.71]],
      stations: [
        { name: '南昌站',   coord: [115.89, 28.68], dailyFlow: '2.8万人次', transfer: '地铁1号线、公交', scenic: '滕王阁' },
        { name: '永修站',   coord: [115.98, 29.05], dailyFlow: '0.6万人次', transfer: '公交',           scenic: '云居山' },
        { name: '共青城站', coord: [115.99, 29.32], dailyFlow: '0.4万人次', transfer: '公交',           scenic: '—' },
        { name: '九江站',   coord: [116.00, 29.71], dailyFlow: '1.9万人次', transfer: '公交、旅游专线', scenic: '庐山' }
      ]
    },
    {
      name: '昌抚通勤线',
      coords: [[115.89, 28.68], [116.05, 28.45], [116.36, 27.95]],
      stations: [
        { name: '南昌站', coord: [115.89, 28.68], dailyFlow: '2.8万人次', transfer: '地铁1号线、公交', scenic: '滕王阁' },
        { name: '进贤站', coord: [116.05, 28.45], dailyFlow: '0.3万人次', transfer: '公交',           scenic: '—' },
        { name: '抚州站', coord: [116.36, 27.95], dailyFlow: '0.8万人次', transfer: '公交',           scenic: '大觉山' }
      ]
    },
    // —— 以下为「全省市区打通」扩展段（依原方案 2.2 拓展路径）——
    {
      name: '沪昆通勤线',
      coords: [[115.89, 28.68], [115.77, 28.16], [115.55, 28.06], [114.93, 27.81], [114.42, 27.80], [113.85, 27.62]],
      stations: [
        { name: '丰城站', coord: [115.77, 28.16], dailyFlow: '0.4万人次', transfer: '公交',           scenic: '洪州窑' },
        { name: '樟树站', coord: [115.55, 28.06], dailyFlow: '0.3万人次', transfer: '公交',           scenic: '阁皂山' },
        { name: '新余站', coord: [114.93, 27.81], dailyFlow: '0.6万人次', transfer: '公交',           scenic: '仙女湖' },
        { name: '宜春站', coord: [114.42, 27.80], dailyFlow: '0.7万人次', transfer: '公交、旅游专线', scenic: '明月山' },
        { name: '萍乡站', coord: [113.85, 27.62], dailyFlow: '0.7万人次', transfer: '公交',           scenic: '武功山、安源' }
      ]
    },
    {
      name: '京九通勤线',
      coords: [[115.89, 28.68], [114.99, 27.11], [115.36, 26.34], [114.94, 25.83]],
      stations: [
        { name: '吉安站', coord: [114.99, 27.11], dailyFlow: '0.9万人次', transfer: '公交、旅游专线', scenic: '井冈山' },
        { name: '兴国站', coord: [115.36, 26.34], dailyFlow: '0.3万人次', transfer: '公交',           scenic: '将军园' },
        { name: '赣州站', coord: [114.94, 25.83], dailyFlow: '1.5万人次', transfer: '高铁、公交',     scenic: '通天岩、瑞金' }
      ]
    },
    {
      name: '皖赣通勤线',
      coords: [[115.89, 28.68], [117.07, 28.26], [117.18, 29.27]],
      stations: [
        { name: '鹰潭站',   coord: [117.07, 28.26], dailyFlow: '0.7万人次', transfer: '公交、旅游专线', scenic: '龙虎山' },
        { name: '景德镇站', coord: [117.18, 29.27], dailyFlow: '0.6万人次', transfer: '公交、旅游专线', scenic: '古窑、瑶里' }
      ]
    }
  ],

  // —— 旅游层（绿色）—— 跨座式单轨旅游环线 ——
  tourismLines: [
    // 原为闭环；按要求断开「婺源↔三清山」的直接连接，拆为两段独立线路
    {
      name: '赣东北环线·上饶婺源段',
      coords: [[117.97, 28.45], [117.86, 29.25]],
      stations: [
        { name: '上饶站', coord: [117.97, 28.45], dailyFlow: '1.2万人次', transfer: '高铁、公交',     scenic: '灵山' },
        { name: '婺源站', coord: [117.86, 29.25], dailyFlow: '0.9万人次', transfer: '公交、旅游专线', scenic: '篁岭、江湾' }
      ]
    },
    {
      name: '赣东北环线·三清山龙虎山段',
      coords: [[118.06, 28.91], [116.96, 28.10], [117.97, 28.45]],
      stations: [
        { name: '三清山站', coord: [118.06, 28.91], dailyFlow: '0.7万人次', transfer: '景区接驳车',    scenic: '三清山' },
        { name: '龙虎山站', coord: [116.96, 28.10], dailyFlow: '0.5万人次', transfer: '公交',           scenic: '龙虎山、上清古镇' },
        { name: '上饶站',   coord: [117.97, 28.45], dailyFlow: '1.2万人次', transfer: '高铁、公交',     scenic: '灵山' }
      ]
    },
    {
      name: '环庐山旅游线',
      coords: [[116.00, 29.71], [115.85, 29.55], [115.55, 29.24], [116.00, 29.71]],
      stations: [
        { name: '九江站',       coord: [116.00, 29.71], dailyFlow: '1.9万人次', transfer: '公交、旅游专线',  scenic: '庐山' },
        { name: '庐山站',       coord: [115.85, 29.55], dailyFlow: '1.5万人次', transfer: '索道、景区接驳', scenic: '庐山风景区' },
        { name: '庐山西海站', coord: [115.55, 29.24], dailyFlow: '0.8万人次', transfer: '游船码头',       scenic: '庐山西海' }
      ]
    },
    // —— 以下为「全省市区打通」扩展段（原方案 3.3 环线段外补赣西·赣南·赣东）——
    {
      name: '赣西红色旅游线',
      coords: [[114.99, 27.11], [114.18, 26.75], [114.28, 27.72], [113.87, 27.63], [114.99, 27.11]],
      stations: [
        { name: '吉安站',   coord: [114.99, 27.11], dailyFlow: '0.9万人次', transfer: '公交、旅游专线', scenic: '井冈山' },
        { name: '井冈山站', coord: [114.18, 26.75], dailyFlow: '0.6万人次', transfer: '景区接驳车',    scenic: '井冈山' },
        { name: '明月山站', coord: [114.28, 27.72], dailyFlow: '0.5万人次', transfer: '索道、景区接驳', scenic: '明月山' },
        { name: '安源站',   coord: [113.87, 27.63], dailyFlow: '0.3万人次', transfer: '公交',           scenic: '安源路矿' }
      ]
    },
    {
      name: '赣南客家旅游线',
      coords: [[114.94, 25.83], [116.03, 25.88], [114.79, 24.91], [114.94, 25.83]],
      stations: [
        { name: '赣州站', coord: [114.94, 25.83], dailyFlow: '1.5万人次', transfer: '高铁、公交',     scenic: '通天岩、瑞金' },
        { name: '瑞金站', coord: [116.03, 25.88], dailyFlow: '0.4万人次', transfer: '景区接驳车',     scenic: '共和国摇篮' },
        { name: '龙南站', coord: [114.79, 24.91], dailyFlow: '0.3万人次', transfer: '公交',           scenic: '关西围屋' }
      ]
    },
    {
      name: '赣东古韵旅游线',
      coords: [[117.18, 29.27], [117.58, 29.42], [117.41, 28.32], [116.97, 27.97], [117.18, 29.27]],
      stations: [
        { name: '景德镇站',   coord: [117.18, 29.27], dailyFlow: '0.6万人次', transfer: '公交、旅游专线', scenic: '古窑、瑶里' },
        { name: '瑶里站',     coord: [117.58, 29.42], dailyFlow: '0.2万人次', transfer: '景区接驳车',    scenic: '瑶里古镇' },
        { name: '龟峰站',     coord: [117.41, 28.32], dailyFlow: '0.4万人次', transfer: '景区接驳车',    scenic: '龟峰' },
        { name: '上清古镇站', coord: [116.97, 27.97], dailyFlow: '0.3万人次', transfer: '景区接驳车',    scenic: '上清古镇' }
      ]
    },
    // —— 依《以轨代巴》方案 3.3：大觉山旅游支线（抚州—资溪—大觉山）——
    // 依托昌抚通勤线至抚州换乘；大觉山"悬崖动车"已验证铰接式转向架+齿轨在悬崖地形的可行性
    {
      name: '大觉山旅游支线',
      coords: [[116.36, 27.95], [117.07, 27.70], [117.03, 27.78]],
      stations: [
        { name: '抚州站',   coord: [116.36, 27.95], dailyFlow: '0.8万人次', transfer: '公交、接驳车', scenic: '大觉山' },
        { name: '资溪站',   coord: [117.07, 27.70], dailyFlow: '0.2万人次', transfer: '景区接驳车',   scenic: '大觉山、马头山' },
        { name: '大觉山站', coord: [117.03, 27.78], dailyFlow: '0.6万人次', transfer: '悬崖动车',     scenic: '大觉山' }
      ]
    },
    // —— 依《以轨代巴》方案 3.4：梅岭"红轨"旅游线（南昌—湾里—梅岭）——
    // 沿七彩路高架敷设，串联索道下站、洪崖丹井、湾里集散中心、月亮湾、梅岭游客中心等
    {
      name: '梅岭红轨旅游线',
      coords: [[115.89, 28.68], [115.78, 28.70], [115.74, 28.72], [115.72, 28.80]],
      stations: [
        { name: '南昌站',   coord: [115.89, 28.68], dailyFlow: '2.8万人次', transfer: '地铁1号线、公交', scenic: '滕王阁' },
        { name: '湾里站',   coord: [115.74, 28.72], dailyFlow: '0.4万人次', transfer: '索道、公交',      scenic: '洪崖丹井、月亮湾' },
        { name: '梅岭站',   coord: [115.72, 28.80], dailyFlow: '0.3万人次', transfer: '索道、景区接驳',  scenic: '梅岭、竹海明珠' }
      ]
    }
  ],

  // —— 齿轨爬坡段（依《以轨代巴》方案 5.2）——
  // 采用齿轨技术的陡坡路段，地图上以橙色闪烁标记；点击弹技术参数
  SLOPE_SEGMENTS: [
    { name: '三清山齿轨段',
      coords: [[117.86, 29.25], [118.06, 28.91]],
      grade: '最大坡度 120‰',
      system: '米轨+齿轨双制式',
      ref: '四川都四山地轨道交通',
      note: '齿轨段时速 40km/h，双线设计' },
    { name: '大觉山齿轨段',
      coords: [[117.07, 27.70], [117.03, 27.78]],
      grade: '适配悬崖陡坡',
      system: '铰接式转向架+齿轨',
      ref: '大觉山悬崖动车（13.14km，日运量2.5万人次）',
      note: '三分之一路段贴悬崖，运行海拔 850-1150m' },
    { name: '庐山陡坡段',
      coords: [[116.00, 29.71], [115.85, 29.55]],
      grade: '超过 60‰ 加装齿轨驱动',
      system: '跨座式单轨 + 齿轨驱动模块',
      ref: '重庆跨座式单轨 / 都四齿轨转向架',
      note: '橡胶轮胎爬坡附着力更强，最小转弯半径 100m' }
  ],

  // —— 原大巴通行路线（公路绕行走向）——
  // 用途：地图上用「白色圆点沿线移动」表示原大巴的通行方式，与轨道线形成快慢对比。
  // ★ layer 字段 ★ 决定该条公路归属哪一层：
  //   通勤层的大巴只随「通勤层」显隐，旅游层的大巴只随「旅游层」显隐。
  //   两层都关闭 → 所有大巴一起消失（不会出现"线没了、大巴还在飘"的情况）。
  BUS_ROUTES: [
    // ══ 通勤层（替代城际大巴）══
    { from: '南昌', to: '九江', layer: 'commuter',
      road: [[115.89, 28.68], [115.95, 28.76], [116.01, 28.87], [116.04, 28.99], [115.94, 29.12],
             [115.87, 29.26], [115.96, 29.39], [116.07, 29.50], [116.03, 29.61], [116.00, 29.71]] },
    { from: '南昌', to: '抚州', layer: 'commuter',
      road: [[115.89, 28.68], [115.94, 28.57], [116.06, 28.48], [116.28, 28.43], [116.52, 28.36],
             [116.70, 28.26], [116.66, 28.14], [116.50, 28.04], [116.36, 27.95]] },
    // 赣州通勤网络对应公路：大广高速走向（南昌→吉安→兴国→赣州）
    { from: '南昌', to: '赣州', layer: 'commuter',
      road: [[115.89, 28.68], [115.55, 28.30], [115.20, 27.85], [114.99, 27.11], [115.12, 26.62],
             [115.36, 26.34], [115.10, 26.05], [114.94, 25.83]] },

    // ══ 旅游层（替代景区大巴）══
    { from: '南昌', to: '庐山', layer: 'tourism',
      road: [[115.89, 28.68], [115.97, 28.82], [116.03, 28.97], [115.93, 29.10], [115.87, 29.25],
             [115.97, 29.38], [116.06, 29.49], [116.04, 29.60], [116.10, 29.67], [116.02, 29.70],
             [115.94, 29.68], [115.89, 29.64], [115.95, 29.61], [116.01, 29.59], [115.97, 29.63],
             [115.91, 29.61], [115.87, 29.58], [115.85, 29.55]] },
    { from: '南昌', to: '三清山', layer: 'tourism',
      road: [[115.89, 28.68], [116.06, 28.52], [116.30, 28.43], [116.58, 28.34], [116.88, 28.31],
             [117.20, 28.29], [117.55, 28.26], [117.88, 28.31], [118.12, 28.44], [118.26, 28.60],
             [118.18, 28.72], [118.03, 28.81], [118.05, 28.86], [118.06, 28.91]] },
    { from: '上饶', to: '三清山', layer: 'tourism',
      road: [[117.97, 28.45], [118.10, 28.54], [118.24, 28.66], [118.16, 28.76], [118.02, 28.84],
             [118.05, 28.88], [118.06, 28.91]] },
    { from: '九江', to: '庐山', layer: 'tourism',
      road: [[116.00, 29.71], [116.07, 29.68], [116.11, 29.63], [116.05, 29.60], [115.98, 29.64],
             [115.92, 29.66], [115.87, 29.62], [115.93, 29.59], [116.00, 29.57], [115.96, 29.62],
             [115.90, 29.60], [115.86, 29.57], [115.85, 29.55]] },
    { from: '南昌', to: '大觉山', layer: 'tourism',
      road: [[115.89, 28.68], [116.05, 28.45], [116.36, 27.95], [116.60, 27.98], [116.76, 27.92],
             [116.95, 27.80], [117.07, 27.70], [117.12, 27.74], [117.06, 27.79], [117.03, 27.78]] },
    { from: '南昌', to: '梅岭', layer: 'tourism',
      road: [[115.89, 28.68], [115.84, 28.72], [115.80, 28.76], [115.76, 28.73], [115.72, 28.70],
             [115.68, 28.73], [115.70, 28.77], [115.74, 28.81], [115.72, 28.80]] }
  ],

  // 汇总所有站点（去重同名），并打 type 标签，供地图 Marker / 热力图 / 智能体面板复用
  allStations: function () {
    var seen = {};
    var list = [];
    var push = function (s, type) {
      var key = s.name;
      if (!seen[key]) {
        list.push(Object.assign({}, s, { type: type }));
        seen[key] = true;
      } else {
        // 已存在则补全 type（换乘站可同时属通勤/旅游，这里保留首次类型）
      }
    };
    this.commuterLines.forEach(function (l) { l.stations.forEach(function (s) { push(s, 'commuter'); }); });
    this.tourismLines.forEach(function (l) { l.stations.forEach(function (s) { push(s, 'tourism'); }); });
    return list;
  }
};
