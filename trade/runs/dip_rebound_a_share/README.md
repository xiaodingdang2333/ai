# A股大跌次日反弹回测

目标：逐只扫描沪深300、中证500、中证A500成分股，测试“当日大跌尾盘买入，次日反弹/开盘/收盘卖出”的短线均值回归策略。

当前实现使用标准库，不依赖 pandas/akshare。

数据源：
- 成分股：东方财富 `RPT_INDEX_TS_COMPONENT`
- 日线：新浪财经 `MoneyFinanceCNService.getKLineData`

股票池映射：
- `TYPE=1`: 沪深300
- `TYPE=3`: 中证500
- `TYPE=6`: 中证A500

核心假设：
- 买入价：信号日收盘价
- 卖出价：次日开盘、次日收盘，或次日触发止盈/止损，否则收盘
- 若次日止盈和止损都可能发生，保守假设先触发止损
- 排除 ST、当日一字跌停、信号日成交额低于 5000 万元的样本
- 费用：佣金 0.0115%，印花税 0.05%，单边滑点 0.05%

运行：

```bash
cd /home/admin/ai/trade/runs/dip_rebound_a_share
python3 backtest.py
```

输出：
- `results/summary.csv`: 参数组合汇总
- `results/trades.csv`: 展开的逐笔交易样本
- `results/run_meta.json`: 本次运行假设和规模
- `data/`: 缓存的成分股和日线
- `analysis_summary.md`: 本次回测结论和下一步筛选方向
