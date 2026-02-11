import backtrader as bt
from stop_utils import should_stop_loss


class BTCMaBreakoutTP(bt.Strategy):
    """
    多空双向均线突破策略：
    - 多头：价格上穿 MA5 且上穿 MA10 -> 做多 (1x)
    - 空头：价格下穿 MA5 且下穿 MA10 -> 做空 (1x)
    - 止盈：每一笔仓位独立计算，TP1 (6%) 平一半，TP2 (12%) 全平
    """

    params = dict(
        ma_fast=5,
        ma_slow=10,
        buy_pct=0.05,          # 每次做多/做空占用当前总资产的比例
        tp1_pct=0.05,        # +4% (多头盈利) 或 -4% (空头价格下跌盈利)
        tp2_pct=0.08,        # +8%
        sl_pct=0.18,         # -5% 止损
        tp1_sell_prop=0.9,   # 第一段止盈平掉该仓位的比例
        printlog=False,      # 默认关闭打印
        csv_output="trades.csv", # 交易记录输出路径
    )

    def __init__(self):
        self.close = self.datas[0].close

        self.ma5 = bt.indicators.SimpleMovingAverage(self.close, period=self.p.ma_fast)
        self.ma10 = bt.indicators.SimpleMovingAverage(self.close, period=self.p.ma_slow)
        self.ma20= bt.indicators.SimpleMovingAverage(self.close, period=20)
        self.ma240= bt.indicators.SimpleMovingAverage(self.close, period=240)
        self.ma60= bt.indicators.SimpleMovingAverage(self.close, period=60)
        self.ma120= bt.indicators.SimpleMovingAverage(self.close, period=120)
        self.ma180= bt.indicators.SimpleMovingAverage(self.close, period=180)
        self.ma30= bt.indicators.SimpleMovingAverage(self.close, period=30)

        # 信号指标
        self.cross_ma5 = bt.indicators.CrossOver(self.close, self.ma5, plot=False)
        self.cross_ma10 = bt.indicators.CrossOver(self.close, self.ma10, plot=False)

        self.cross_ma20 = bt.indicators.CrossOver(self.close, self.ma20, plot=False)
        

        self.order = None

        # 交易状态：支持多空双向加仓
        self.long_entries = []   # 做多仓位列表
        self.short_entries = []  # 做空仓位列表

        # 用于保存交易记录
        self.trade_logs = []
        self.completed_long_trades = 0
        self.completed_short_trades = 0

    def log(self, txt):
        if self.p.printlog:
            dt = self.datas[0].datetime.date(0).isoformat()
            print(f"{dt} | {txt}")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            dt = self.datas[0].datetime.datetime(0).isoformat()
            type_str = "BUY" if order.isbuy() else "SELL"
            
            # 记录交易
            self.trade_logs.append({
                "datetime": dt,
                "type": type_str,
                "price": order.executed.price,
                "size": order.executed.size,
                "value": order.executed.value,
                "commission": order.executed.comm,
                "pnl": order.executed.pnl
            })

            self.log(
                f"{type_str} executed price={order.executed.price:.2f}, "
                f"size={order.executed.size:.8f}, value={order.executed.value:.2f}"
            )

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"Order {order.getstatusname()}")

        self.order = None

    def next(self):
        if self.order:
            return

        price = float(self.close[0])
        if price <= 0:
            return

        # ====== 信号检测 ======
        # 1. 做多信号：上穿 MA10 和 MA20 且价格在 MA120 之下
        if self.cross_ma10[0] > 0 and self.cross_ma20[0] > 0 and price > self.ma120[0]:
            total_value = self.broker.getvalue()
            buy_amount = total_value * self.p.buy_pct
            size_btc = buy_amount / price
            
            if self.broker.getcash() >= buy_amount:
                self.log(f"SIGNAL LONG: price={price:.2f}, amount={buy_amount:.2f}")
                self.order = self.buy(size=size_btc)
                # 记录这笔多单条目
                self.long_entries.append({
                    'price': price,
                    'size': size_btc,
                    'tp1_done': False
                })
                return

        # 2. 做空信号：下穿 MA10 和 MA20 且价格在 MA120 之上
        if self.cross_ma10[0] < 0 and self.cross_ma20[0] < 0 and price < self.ma120[0]:
            total_value = self.broker.getvalue()
            sell_amount = total_value * self.p.buy_pct
            size_btc = sell_amount / price
            
            # 1倍做空模拟：卖出 size_btc (即使无持仓也会产生负持仓)
            self.log(f"SIGNAL SHORT: price={price:.2f}, amount={sell_amount:.2f}")
            self.order = self.sell(size=size_btc)
            # 记录这笔空单条目
            self.short_entries.append({
                'price': price,
                'size': size_btc,
                'tp1_done': False
            })
            return

        # ====== 止盈 / 止损管理 (多头) ======
        for i in range(len(self.long_entries) - 1, -1, -1):
            entry = self.long_entries[i]
            pnl_pct = (price / entry['price']) - 1.0

            # 1) TP1: 小止盈优先，先平一半
            if (not entry['tp1_done']) and pnl_pct >= self.p.tp1_pct:
                sell_btc = entry['size'] * self.p.tp1_sell_prop
                self.log(f"LONG TP1 HIT @ {entry['price']:.2f}")
                entry['tp1_done'] = True
                entry['size'] -= sell_btc
                self.order = self.sell(size=sell_btc)
                return

            # 2) SL: 小止盈之后再看止损
            if should_stop_loss(entry['price'], price, "long", self.p.sl_pct):
                self.log(f"LONG SL HIT @ {entry['price']:.2f}")
                self.order = self.sell(size=entry['size'])
                self.long_entries.pop(i)
                return

            # 3) TP2: 只有在已经做过 TP1 后，才允许全平
            if entry['tp1_done'] and pnl_pct >= self.p.tp2_pct:
                self.log(f"LONG TP2 HIT @ {entry['price']:.2f}")
                self.order = self.sell(size=entry['size'])
                self.long_entries.pop(i)
                self.completed_long_trades += 1
                return

        # ====== 止盈 / 止损管理 (空头) ======
        for i in range(len(self.short_entries) - 1, -1, -1):
            entry = self.short_entries[i]
            # 空头盈利计算：(开仓价 / 当前价) - 1
            pnl_pct = (entry['price'] / price) - 1.0

            # 1) TP1: 小止盈优先，先平一半空单
            if (not entry['tp1_done']) and pnl_pct >= self.p.tp1_pct:
                buy_btc = entry['size'] * self.p.tp1_sell_prop
                self.log(f"SHORT TP1 HIT @ {entry['price']:.2f}")
                entry['tp1_done'] = True
                entry['size'] -= buy_btc
                self.order = self.buy(size=buy_btc)
                return

            # 2) SL: 小止盈之后再看止损 (买入回补)
            if should_stop_loss(entry['price'], price, "short", self.p.sl_pct):
                self.log(f"SHORT SL HIT @ {entry['price']:.2f}")
                self.order = self.buy(size=entry['size'])
                self.short_entries.pop(i)
                return

            # 3) TP2: 只有在已经做过 TP1 后，才允许全平
            if entry['tp1_done'] and pnl_pct >= self.p.tp2_pct:
                self.log(f"SHORT TP2 HIT @ {entry['price']:.2f}")
                self.order = self.buy(size=entry['size'])
                self.short_entries.pop(i)
                self.completed_short_trades += 1
                return

    def stop(self):
        self.log(
            f"STOP | Final Value: {self.broker.getvalue():.2f} | Cash: {self.broker.getcash():.2f}"
        )
        
        # 将交易记录保存到 CSV
        if self.trade_logs:
            import pandas as pd
            df = pd.DataFrame(self.trade_logs)
            df.to_csv(self.p.csv_output, index=False)
            print(f"\n交易记录已保存至: {self.p.csv_output}")
