import json
from dataclasses import asdict, dataclass, field
from typing import List, Dict, Any

import pandas as pd


def should_stop_loss(entry_price: float, current_price: float, side: str, sl_pct: float) -> bool:
    if sl_pct <= 0:
        return False
    if side == "long":
        pnl_pct = current_price / entry_price - 1.0
    else:
        pnl_pct = entry_price / current_price - 1.0
    return pnl_pct <= -sl_pct


@dataclass
class StrategyParams:
    ma_fast: int = 10
    ma_slow: int = 20
    buy_pct: float = 0.15
    tp1_pct: float = 0.08
    tp2_pct: float = 0.14
    sl_pct: float = 0.18
    tp1_sell_prop: float = 0.9


@dataclass
class Entry:
    price: float
    size: float
    tp1_done: bool = False


@dataclass
class StrategyState:
    params: StrategyParams = field(default_factory=StrategyParams)
    long_entries: List[Entry] = field(default_factory=list)
    short_entries: List[Entry] = field(default_factory=list)
    completed_long_trades: int = 0
    completed_short_trades: int = 0

    def to_json(self) -> str:
        data = asdict(self)
        data["params"] = asdict(self.params)
        data["long_entries"] = [asdict(e) for e in self.long_entries]
        data["short_entries"] = [asdict(e) for e in self.short_entries]
        return json.dumps(data)

    @classmethod
    def from_json(cls, s: str) -> "StrategyState":
        raw = json.loads(s)
        params = StrategyParams(**raw.get("params", {}))
        long_entries = [Entry(**e) for e in raw.get("long_entries", [])]
        short_entries = [Entry(**e) for e in raw.get("short_entries", [])]
        completed_long_trades = raw.get("completed_long_trades", 0)
        completed_short_trades = raw.get("completed_short_trades", 0)
        return cls(
            params=params,
            long_entries=long_entries,
            short_entries=short_entries,
            completed_long_trades=completed_long_trades,
            completed_short_trades=completed_short_trades,
        )

    def process_bar(
        self,
        df: pd.DataFrame,
        account_value: float,
        cash: float,
    ) -> List[Dict[str, Any]]:
        if "close" not in df.columns:
            return []
        close = df["close"]
        max_period = max(self.params.ma_fast, self.params.ma_slow, 120)
        if len(close) < max_period + 1:
            return []

        ma_fast = close.rolling(self.params.ma_fast).mean()
        ma_slow = close.rolling(self.params.ma_slow).mean()
        ma120 = close.rolling(120).mean()

        idx = len(close) - 1
        price = float(close.iloc[idx])
        prev_price = float(close.iloc[idx - 1])
        last_ma_fast = float(ma_fast.iloc[idx])
        prev_ma_fast = float(ma_fast.iloc[idx - 1])
        last_ma_slow = float(ma_slow.iloc[idx])
        prev_ma_slow = float(ma_slow.iloc[idx - 1])
        last_ma120 = float(ma120.iloc[idx])

        if price <= 0:
            return []

        actions: List[Dict[str, Any]] = []

        long_signal = (
            prev_price < prev_ma_fast
            and price > last_ma_fast
            and prev_price < prev_ma_slow
            and price > last_ma_slow
            and price > last_ma120
        )

        if long_signal:
            buy_amount = account_value * self.params.buy_pct
            if cash >= buy_amount:
                size = buy_amount / price
                self.long_entries.append(Entry(price=price, size=size, tp1_done=False))
                actions.append(
                    {
                        "op": "open_long",
                        "side": "buy",
                        "size": size,
                        "price": price,
                        "notional": buy_amount,
                    }
                )
                return actions

        short_signal = (
            prev_price > prev_ma_fast
            and price < last_ma_fast
            and prev_price > prev_ma_slow
            and price < last_ma_slow
            and price < last_ma120
        )

        if short_signal:
            sell_amount = account_value * self.params.buy_pct
            size = sell_amount / price
            self.short_entries.append(Entry(price=price, size=size, tp1_done=False))
            actions.append(
                {
                    "op": "open_short",
                    "side": "sell",
                    "size": size,
                    "price": price,
                    "notional": sell_amount,
                }
            )
            return actions

        for i in range(len(self.long_entries) - 1, -1, -1):
            entry = self.long_entries[i]
            pnl_pct = price / entry.price - 1.0

            if not entry.tp1_done and pnl_pct >= self.params.tp1_pct:
                sell_size = entry.size * self.params.tp1_sell_prop
                entry.tp1_done = True
                entry.size -= sell_size
                actions.append(
                    {
                        "op": "tp1_long",
                        "side": "sell",
                        "size": sell_size,
                        "price": price,
                    }
                )
                return actions

            if should_stop_loss(entry.price, price, "long", self.params.sl_pct):
                sell_size = entry.size
                self.long_entries.pop(i)
                actions.append(
                    {
                        "op": "sl_long",
                        "side": "sell",
                        "size": sell_size,
                        "price": price,
                    }
                )
                return actions

            if entry.tp1_done and pnl_pct >= self.params.tp2_pct:
                sell_size = entry.size
                self.long_entries.pop(i)
                self.completed_long_trades += 1
                actions.append(
                    {
                        "op": "tp2_long",
                        "side": "sell",
                        "size": sell_size,
                        "price": price,
                    }
                )
                return actions

        for i in range(len(self.short_entries) - 1, -1, -1):
            entry = self.short_entries[i]
            pnl_pct = entry.price / price - 1.0

            if not entry.tp1_done and pnl_pct >= self.params.tp1_pct:
                buy_size = entry.size * self.params.tp1_sell_prop
                entry.tp1_done = True
                entry.size -= buy_size
                actions.append(
                    {
                        "op": "tp1_short",
                        "side": "buy",
                        "size": buy_size,
                        "price": price,
                    }
                )
                return actions

            if should_stop_loss(entry.price, price, "short", self.params.sl_pct):
                buy_size = entry.size
                self.short_entries.pop(i)
                actions.append(
                    {
                        "op": "sl_short",
                        "side": "buy",
                        "size": buy_size,
                        "price": price,
                    }
                )
                return actions

            if entry.tp1_done and pnl_pct >= self.params.tp2_pct:
                buy_size = entry.size
                self.short_entries.pop(i)
                self.completed_short_trades += 1
                actions.append(
                    {
                        "op": "tp2_short",
                        "side": "buy",
                        "size": buy_size,
                        "price": price,
                    }
                )
                return actions

        return actions
