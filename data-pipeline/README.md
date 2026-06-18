# SENTIO 选股达人 · data-pipeline

情绪温度采集（第①②层，零爬虫）+ **多因子策略引擎**（动量/趋势/资金/低波/情绪 → 达人评分
+ 交易计划 + 组合 + 回测）。前端「立即检查」按钮经 Rust `sentio_run` 调起 `run_all.py`。

## 跑法
```powershell
$env:PYTHONIOENCODING="utf-8"
python run_all.py            # ★一键闭环：采集情绪 → 多因子策略 → 月度回测（前端「立即检查」走这条）
python run_all.py 600519     # 指定代码（横截面会退化，建议全量）

python collect.py            # 只跑情绪采集（第①②层）
python strategy.py           # 只跑策略 + 回测（读 collect 产出的情绪 + 新浪日线）
```

## 三层闭环
1. **情绪层**（collect.py）：热度 H + 资金 F → 情绪温度（反向指标）→ `board.json` / `sentiment_latest.json`
2. **策略层**（strategy.py）：新浪日线算技术因子，横截面 z-score(winsorize±3) 复合「达人评分」
   - 权重：动量0.32 / 趋势0.20 / 资金0.18 / 低波0.10 / 情绪反向0.20；RSI>80 过热扣分
   - 每只交易计划：ATR/欧奈尔8% 止损 + 3R 目标 + 单笔风险≤2% 等风险仓位
   - 组合：评分 Top-8 + 按市场温度调现金缓冲 → `strategy.json`
3. **回测层**：月度横截面动量再平衡（净于成本），出 CAGR/月胜率/最大回撤/夏普，对标等权基准
   - ⚠ 宇宙是当下龙头精选，存在事后选择偏差，绝对收益会高估；看「超额 + 回撤/夏普」才诚实

> 取价用**新浪源** `stock_zh_a_daily`（前复权），而非东财 `stock_zh_a_hist`——东财大响应在本机
> 会 TLS 重置（schannel server closed abruptly / RemoteDisconnect），换 host 即稳。

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
- `output/sentiment_<date>.json` + `output/sentiment_latest.json`（情绪，喂决策层/前端）
- `output/board.json`（市场聚合：情绪温度/宽度/指数/反转预警）
- `output/strategy.json`（★达人评分 + 持仓交易计划 + 组合 + 回测，前端「建议策略」页直接渲染）
- 以上 JSON 同步写一份到 `../polaris-app/public/sentio/`（Vite 映射到根路径，前端 fetch）

## ⚠ 本机踩坑（重要）
1. **Clash 代理 127.0.0.1:7897 破坏东财 TLS**：报 `SSL DECRYPTION_FAILED_OR_BAD_RECORD_MAC`。
   东财是国内源，已在脚本顶部 monkeypatch `requests.Session.trust_env=False` 强制直连。
   （注意 `NO_PROXY=*` 无效——requests 不把 `*` 当通配，按 hostname 后缀匹配。）
2. **akshare 的 `_` 时间戳 cache-buster 致大响应 TLS 破坏**：每次唯一 URL 是缓存 MISS，
   大响应在本机被破坏。故资金流改为**自实现抓取且不带 `_` 参数**（走缓存路径即稳）。
   字段映射（klines f51..f65）：0=日期 1=主力净额 6=主力净占比。

## ★ 斐波那契趋势跟踪引擎（独立第二套策略）

源自桌面《斐波那契趋势跟踪策略报告.html》——把「截断亏损、让利润奔跑」的非对称下注哲学
落成事件驱动、无未来函数的逐股趋势策略。与上面的「横截面多因子」是**两套独立物种**，互不干扰。

```powershell
python fib_scan.py            # 全宇宙：取价 + 事件回测 + 参数寻优 + 今日选股
python fib_scan.py --quick    # 跳过寻优(默认配置 EMA21/55·趋势EMA34·斐波1.618×ATR)，盘后调度用
python run_fib.py             # 同上的一键编排(前端「斐波检查」/计划任务走这条)
python fib_scan.py 600519     # 指定代码
```

四大支柱（`fib_engine.py`）：
1. **进场** EMA21 上穿 EMA55(金叉) + 收盘站上 EMA34 + 慢线向上(趋势闸) + ATR 过滤震荡
2. **止损** 斐波那契硬止损 = 入场价 − **k×ATR(14)**，k∈{1.0,1.618,2.618}，黄金比 1.618 默认
3. **出场** 收盘 ≥ EMA(m) 一律持有(**不主动止盈**)；收盘 < EMA(m) 才离场 → 让利润奔跑
4. **仓位** 分数凯利(½) · 单笔风险≤2% · 单只≤30% · 斐波那契扩展位金字塔加码(可选)

回测口径：逐股 `simulate` → 池化交易统计(胜率/盈亏比/期望R/profit factor) + 组合层日频权益
曲线(固定分数风险·最多6并发·净于成本) 对标**等权买入持有**。参数网格(k×m)证明 edge 跨参数
普遍正期望=非过拟合。**实测(2023-06~2026-06, 32龙头)**：池化 156 笔、胜率 34.6%、盈亏比 7.6×、
期望 +1.45R、profit factor 4.05；组合 +135.8% vs 基准 +61.1%(超额 74.7%)、CAGR 33.4%、
最大回撤 −4.2%、夏普 1.3。**典型非对称**：平均盈利 +37% vs 平均亏损 −2.8%。

> ⚠ 宇宙为当下龙头精选，存在事后选择偏差，绝对收益高估；趋势策略震荡市必然连续小亏，靠少数
> 大趋势的非对称盈利覆盖。看「相对基准超额 + 回撤/夏普」才诚实。

产物：`output/fib_strategy.json`(+同步 `../polaris-app/public/sentio/`)，前端**「斐波选股」**页渲染。
Rust 命令 `fib_run` 调起 `run_fib.py`，事件 `fib:progress`/`fib:done`。

每日调度：`.\schedule_daily.ps1 install`（注册 Windows 计划任务，交易日 15:30 盘后自动选股；
`status`/`run`/`uninstall` 管理）。

研究参考工具，不构成投资建议。
