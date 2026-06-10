# SENTIO · AI 智能选股舆情终端

报告型 AI 选股舆情终端：输入自选股 → 自动产出**情绪温度 + 买卖建议 + 反向预警**。
桌面端 Tauri + Vue3 + Pinia + Rust，舆情数据走 akshare 官方聚合（合规零爬虫）。

> ⚠️ 研究参考工具，**不构成投资建议**。情绪是概率性反向信号，会出错；股市有风险，风险自负。

## 结构

```
智能选股应用/
├─ polaris-app/          # 桌面 App（Tauri + Vue3）
│  └─ src/components/sentio/   # 三屏：舆情看板 / 选股雷达 / 个股报告
├─ data-pipeline/        # Python 舆情采集器（akshare 第①②层情绪温度）
│  ├─ collect.py         # 采集 → SQLite + JSON（双写到前端 public/sentio/）
│  ├─ gen_report.py      # 生成 HTML 采集报告
│  └─ watchlist.json     # 自选股宇宙
└─ docs/                 # PRD 与实施规划
```

## 跑起来

```powershell
# 1) 采集舆情数据（写入前端 public/sentio/）
cd data-pipeline; pip install -r requirements.txt; python collect.py

# 2) 启动桌面 App
cd ../polaris-app; npm install; npm run tauri:dev
```

## 情绪温度

`温度 = (0.40·热度H + 0.35·资金F) / 0.75`（文本情感 S 第二阶段接入）
- 热度 H：东财千股千评关注指数（全市场分位）+ 人气榜
- 资金 F：主力净流入净占比
- 反向信号：≥80 过热（警惕回撤）/ ≤20 冰点（可关注）

## 设计语言

Web3 深空玻璃 × Apple 极简留白 × 赚钱感：深空底 `#070a12` · 翡翠绿 `#00e69a` · 流光金 `#ffcf6b` · 科技渐变 `#5b8cff→#00e0c6`。

---
基于自研母体改壳，与原项目数据隔离。
