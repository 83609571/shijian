# 赣鄱智轨 · 5G-A+AI 铁路智能决策验证平台

> 基于 5G-A 确定性网络与通感算智一体化能力的铁路智能决策验证平台。
> 不是"铁路业务仿真工具"，而是用**全确定性、可复算**的仿真证明 5G-A+AI 在铁路场景中能带来多少确定性提升。

## 在线预览（开启 GitHub Pages 后）

- 主界面（线网一张图）：`index.html`
- 实验可视化（实验①-⑥ + 网络SLA切换台）：`experiments.html`
- 应急一体化（五场景 + 四智能体时间线）：`emergency.html`
- 百度地图完整版：`bmap.html`（需自备百度地图 AK，见下方说明）

## 核心数字（全确定性可复算）

| 实验 | 结果 |
|---|---|
| 网络 SLA 对照 | 对照组 4G 链路 121.65s → 5G-A 实验组 2.104s（**57.8×**），成功率 95.08% → 99.998% |
| 治理方案 | 智能体推荐方案 D 总分 83.6（基准 57.8），Critic 闭环 75.4 → 83.6 |
| ISAC 通感 | 替代专用传感网：20× 感知提速、~35% 相对成本（37 断面口径） |
| AI 空口 | 弱覆盖山区段成功率 4G 73.1% → 5G-A+AI 空口 99.98% |
| 应急编排 | 四智能体全链路响应 ≈24-25s（人工流程 2 小时） |

## 本地运行

```bash
# Python >= 3.10，纯标准库，零第三方依赖
python -m sim.passenger_flow_sim --check   # 仿真引擎 + 数据一致性校验
python -m sim.comm_layer                   # 通信孪生层（生成 data/comm_capability.json）
python -m sim.emergency_orchestration      # 四智能体应急编排
python experiments.py                      # 实验①-⑥（生成 output/experiments/）
python run_agent.py                        # 智能体全链路（离线确定性模式）
python -m http.server 8000                 # 前端：访问 http://127.0.0.1:8000/index.html
```

云端 LLM（可选）：设置 `DS41_API_KEY` / `GLM_API_KEY` 环境变量后 `python run_agent.py --provider deepseek`（或 glm / openai）。

## 目录结构

```
sim/      仿真引擎（三层饱和度 + 通信数字孪生 + 应急编排）
agent/    智能体（Planner-Executor-Critic · 13 工具 · 10 护栏）
data/     数据底座（34 站双场景 · 19 条真实锚点 · 能力底账）
experiments.py  实验①-⑥统一脚本
output/experiments/  实验产物与报告
js/local-ak.example.js  百度地图 AK 模板（复制为 local-ak.js 并填入你的 AK）
```

## 数据可信度约定

- 真实锚点标注 `real=True` 并附官方来源；仿真推演值一律 `real=False` 并写明推演依据
- ISAC 成本为相对系数（专用传感网 = 1.0 基准），不冒充实测招标价
- 通信层为"能力档案 + 链路时序模型"，不做电磁级仿真；物理处置时间与通信增益分账列示

## 安全提示

`js/local-ak.js`（真实百度地图 AK）**不入库**，已被 `.gitignore` 排除；部署百度地图版时复制 `js/local-ak.example.js` 为 `local-ak.js` 并填入你在 [百度地图开放平台](https://lbsyun.baidu.com) 申请的浏览器端 AK 即可。
