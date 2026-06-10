# SENTIO 舆情采集器 · data-pipeline

MVP 第①②层（零爬虫零风险）情绪温度采集。对标 `A股舆情分析模块_实施规划`。

## 跑法
```powershell
$env:PYTHONIOENCODING="utf-8"
python collect.py            # 跑 watchlist.json 全部
python collect.py 600519     # 只跑指定代码（可多个，支持临时输入未在表内的代码）
```

## 数据源（akshare 官方聚合，合规）
- **第①层 热度 H**：`stock_comment_em`（千股千评·关注指数，全市场分位）+ `stock_hot_rank_em`（东财人气榜 Top100 加成）
- **第②层 资金 F**：东财个股资金流（主力净流入净占比）— 自实现 HTTP 抓取，见下「踩坑」
- **第③层 文本情感 S**：第二阶段接 finbert-tone-chinese，当前为 null

## 情绪温度
`温度 = (0.40·H + 0.35·F) / 0.75`（MVP 无 S，按 H+F 重归一）
反向信号：≥80 过热 / ≤20 冰点 / 65~80 偏热 / 35~20 偏冷 / 其余中性。
> 二阶动量（较5日均值飙升）才是反转信号——需每日累积，DB 已逐日落库。

## 产物
- `data/sentio.db`（SQLite，表 `sentiment`，主键 code+date，逐日历史）
- `output/sentiment_<date>.json` + `output/sentiment_latest.json`（喂给决策层/前端）

## ⚠ 本机踩坑（重要）
1. **Clash 代理 127.0.0.1:7897 破坏东财 TLS**：报 `SSL DECRYPTION_FAILED_OR_BAD_RECORD_MAC`。
   东财是国内源，已在脚本顶部 monkeypatch `requests.Session.trust_env=False` 强制直连。
   （注意 `NO_PROXY=*` 无效——requests 不把 `*` 当通配，按 hostname 后缀匹配。）
2. **akshare 的 `_` 时间戳 cache-buster 致大响应 TLS 破坏**：每次唯一 URL 是缓存 MISS，
   大响应在本机被破坏。故资金流改为**自实现抓取且不带 `_` 参数**（走缓存路径即稳）。
   字段映射（klines f51..f65）：0=日期 1=主力净额 6=主力净占比。

研究参考工具，不构成投资建议。
