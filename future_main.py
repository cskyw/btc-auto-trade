# future_main.py
import backtrader as bt
from future_strategy import BTCMaBreakoutTP   


class CryptoCSVData(bt.feeds.GenericCSVData):
    """
    适配常见的 crypto CSV:
    date, open, high, low, close, volume

    默认：
    - datetime 在第0列（YYYY-MM-DD）
    - open=1, high=2, low=3, close=4, volume=5
    """
    params = (
        ("dtformat",  "%Y-%m-%d %H:%M:%S.%f"),
        ("datetime", 0),
        ("open", 1),
        ("high", 2),
        ("low", 3),
        ("close", 4),
        ("volume", 5),
        ("openinterest", -1),
        ("timeframe", bt.TimeFrame.Days),
        ("compression", 1),
        ("nullvalue", 0.0),
    )


def run_backtest(
    csv_path: str,
    init_cash: float = 10_000.0,
    commission: float = 0.001,  # 0.1%
    slippage_perc: float = 0.0, # 可自行设置模拟滑点
):
    cerebro = bt.Cerebro(stdstats=False)
    # 只添加账户价值观察者，不添加回撤观察者
    cerebro.addobserver(bt.observers.Value)
    # 添加买卖点观察者
    cerebro.addobserver(bt.observers.BuySell)

    data = CryptoCSVData(dataname=csv_path)
    cerebro.adddata(data)

    cerebro.broker.setcash(init_cash)
    cerebro.broker.setcommission(commission=commission)

    # 可选：百分比滑点
    if slippage_perc and slippage_perc > 0:
        cerebro.broker.set_slippage_perc(perc=slippage_perc)

    # 加载策略并设置参数
    cerebro.addstrategy(
        BTCMaBreakoutTP,
        ma_fast=10,
        ma_slow=20,
        buy_pct=0.15,          # 每次买入总资产的 10%
        tp1_pct=0.08,
        tp2_pct=0.14,
        tp1_sell_prop=0.9,    # 止盈 1 卖出该仓位的 90%
        printlog=False,        # 开启打印以便观察加仓情况
        csv_output="okx/backtest_trades.csv"
    )

    # 分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", timeframe=bt.TimeFrame.Days, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="dd")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="rets", timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    print("===== Backtest Start =====")
    print(f"CSV: {csv_path}")
    print(f"Initial Cash: {init_cash:.2f}, Commission: {commission}, Slippage: {slippage_perc}")
    print("==========================")

    results = cerebro.run()
    strat = results[0]

    final_value = cerebro.broker.getvalue()
    sharpe = strat.analyzers.sharpe.get_analysis()
    dd = strat.analyzers.dd.get_analysis()
    rets = strat.analyzers.rets.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    print("\n===== Summary =====")
    print(f"Final Value: {final_value:.4f}")
    
    # 手动计算更直观的百分比收益率（Crypto 365天/年）
    total_return_pct = (final_value / init_cash - 1) * 100
    
    # 获取总天数
    days_passed = len(data)
    if days_passed > 0:
        annual_return_pct = ((1 + total_return_pct/100) ** (365 / days_passed) - 1) * 100
    else:
        annual_return_pct = 0
        
    max_drawdown = dd.get('max', {}).get('drawdown', 0)
    sharpe_ratio = sharpe.get('sharperatio', 0)
    
    print(f"Total Return: {total_return_pct:.4f} %")
    print(f"Annual Return: {annual_return_pct:.4f} %")
    print(f"Max Drawdown: {max_drawdown:.4f} %")
    print(f"Sharpe: {sharpe_ratio:.4f}" if sharpe_ratio is not None else "Sharpe: N/A")
    
    # 统计交易次数
    print(f"Long Trades (Completed): {strat.completed_long_trades}")
    print(f"Short Trades (Completed): {strat.completed_short_trades}")
    print(f"Total Completed Entries: {strat.completed_long_trades + strat.completed_short_trades}")
    print("===================")

    # 画图
    cerebro.plot(style="candlestick", iplot=False)


if __name__ == "__main__":
    # 使用 2022-2023 年数据（大牛市）来验证多空双向策略
    CSV_PATH = "okx/BTCUSDT_1d_2022_2023.csv"

    run_backtest(
        csv_path=CSV_PATH,
        init_cash=80000.0,
        commission=0.0005,
        slippage_perc=0.0003,
    )
