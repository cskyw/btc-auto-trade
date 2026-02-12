import os
import sys
import time

import ccxt
import pandas as pd

from strategy_engine import Entry, StrategyParams, StrategyState


BASE_DIR = os.path.dirname(os.path.dirname(__file__))
OKX_DIR = os.path.join(BASE_DIR, "okx")
if OKX_DIR not in sys.path:
    sys.path.append(OKX_DIR)


API_KEY = os.getenv("OKX_API_KEY")
SECRET = os.getenv("OKX_SECRET")
PASSWORD = os.getenv("OKX_PASSPHRASE")

# API_KEY = "a68e6fb1-d204-4a4b-b7c7-9087ebe8971d"
# SECRET = "239539AD4E99ACEAEC062E65369B58BA"
# PASSWORD = "Geyi761212."
# 现货
# SYMBOL = "BTC/USDT"
# TIMEFRAME = "1d"
# STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")

# ✅  合约 symbol（USDT 本位永续）
SYMBOL = "BTC/USDT:USDT"
TIMEFRAME = "1d"

# ✅ NEW: 合约交易参数（你可以按自己偏好调整）
TD_MODE = "cross"
HEDGE_MODE = True
SANDBOX_MODE = True
PROXY_URL = None


def create_strategy_state() -> StrategyState:
    params = StrategyParams(
        ma_fast=int(os.getenv("MA_FAST", "5")),
        ma_slow=int(os.getenv("MA_SLOW", "10")),
        buy_pct=float(os.getenv("BUY_PCT", "0.05")),
        tp1_pct=float(os.getenv("TP1_PCT", "0.05")),
        tp2_pct=float(os.getenv("TP2_PCT", "0.08")),
        sl_pct=float(os.getenv("SL_PCT", "0.18")),
        tp1_sell_prop=float(os.getenv("TP1_SELL_PROP", "0.9")),
    )
    return StrategyState(params=params)


def create_exchange() -> ccxt.Exchange:
    if not API_KEY or not SECRET or not PASSWORD:
        raise ValueError("Missing OKX credentials: OKX_API_KEY / OKX_SECRET / OKX_PASSPHRASE")

    config: dict = {
        "apiKey": API_KEY,
        "secret": SECRET,
        "password": PASSWORD,
        "enableRateLimit": True,
        "options": {
            "defaultType": "swap",
            "fetchCurrencies": False,
        },
        #          "proxies": {
        # "http": "http://127.0.0.1:7897",
        # "https": "http://127.0.0.1:7897",
        # }
    }
    if PROXY_URL:
        config["proxies"] = {"http": PROXY_URL, "https": PROXY_URL}
    ex = ccxt.okx(
        config
    )
    ex.set_sandbox_mode(SANDBOX_MODE)
    try:
        ex.set_position_mode(HEDGE_MODE)
    except Exception:
        pass
    return ex


def fetch_ohlcv_df(exchange: ccxt.Exchange) -> pd.DataFrame:
    ohlcv = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=300)
    df = pd.DataFrame(
        ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    return df


def get_account_value_and_cash(exchange: ccxt.Exchange, last_price: float) -> tuple[float, float]:
    balance = exchange.fetch_balance()
    usdt = balance.get("USDT", {})
    usdt_free = float(usdt.get("free", 0) or 0)
    usdt_total = float(usdt.get("total", 0) or 0)
    account_value = usdt_total if usdt_total > 0 else usdt_free
    return account_value, usdt_free


def _get_pos_side_from_trade(trade: dict) -> str | None:
    info = trade.get("info") or {}
    pos_side = trade.get("posSide") or info.get("posSide") or info.get("positionSide")
    if not pos_side:
        return None
    pos_side = str(pos_side).lower()
    if pos_side in {"long", "short"}:
        return pos_side
    return None


def _infer_tp1_done_from_trades(
    trades: list[dict],
    contract_size: float,
    pos_side: str,
) -> bool:
    relevant = []
    for t in trades:
        if _get_pos_side_from_trade(t) != pos_side:
            continue
        ts = t.get("timestamp")
        if ts is None:
            continue
        relevant.append(t)
    relevant.sort(key=lambda x: x["timestamp"])

    net = 0.0
    reduced_since_open = False
    for t in relevant:
        side = t.get("side")
        amount = float(t.get("amount", 0) or 0)
        btc = amount * contract_size
        if btc <= 0:
            continue

        if pos_side == "long":
            delta = btc if side == "buy" else -btc
        else:
            delta = btc if side == "sell" else -btc

        prev_net = net
        net += delta

        if prev_net <= 0 and net > 0:
            reduced_since_open = False
            continue

        if prev_net > 0 and delta < 0:
            reduced_since_open = True

        if net <= 0:
            reduced_since_open = False

    return reduced_since_open


def sync_state_from_exchange(exchange: ccxt.Exchange, state: StrategyState) -> None:
    try:
        markets = exchange.load_markets()
    except Exception as e:
        msg = str(e)
        if "50101" in msg or "does not match current environment" in msg:
            raise RuntimeError(
                "OKX APIKey 环境不匹配：如果是模拟盘/DEMO key，请设置 OKX_SANDBOX=true；"
                "如果是实盘 key，请设置 OKX_SANDBOX=false，并确保 key 来自对应环境。"
                f" 原始错误：{msg}"
            ) from e
        raise
    market = markets.get(SYMBOL) or exchange.market(SYMBOL)
    contract_size = float(market.get("contractSize", 1) or 1)

    try:
        positions = exchange.fetch_positions([SYMBOL])
    except Exception:
        positions = []

    try:
        trades = exchange.fetch_my_trades(SYMBOL, limit=300)
    except Exception:
        trades = []

    long_entry: Entry | None = None
    short_entry: Entry | None = None

    for p in positions:
        side = (p.get("side") or "").lower()
        contracts = float(p.get("contracts", 0) or 0)
        if contracts <= 0:
            continue
        btc_size = contracts * contract_size
        entry_price = float(p.get("entryPrice") or 0)
        if entry_price <= 0:
            entry_price = float(p.get("average") or 0)
        if entry_price <= 0:
            continue

        if side == "long":
            tp1_done = _infer_tp1_done_from_trades(trades, contract_size, "long") if HEDGE_MODE else False
            long_entry = Entry(price=entry_price, size=btc_size, tp1_done=tp1_done)
        elif side == "short":
            tp1_done = _infer_tp1_done_from_trades(trades, contract_size, "short") if HEDGE_MODE else False
            short_entry = Entry(price=entry_price, size=btc_size, tp1_done=tp1_done)

    state.long_entries = [long_entry] if long_entry else []
    state.short_entries = [short_entry] if short_entry else []


def execute_actions(exchange: ccxt.Exchange, actions: list[dict]) -> list[dict]:
    executed = []
    markets = exchange.load_markets()
    market = markets.get(SYMBOL) or exchange.market(SYMBOL)
    contract_size = float(market.get("contractSize", 1) or 1)
    for act in actions:
        side = act["side"]
        btc_size = float(act["size"])
        if btc_size <= 0:
            continue
        op = act.get("op", "")
        params: dict = {"tdMode": TD_MODE}
        pos_side = "long" if "long" in op else "short"
        if HEDGE_MODE:
            params["posSide"] = pos_side
        if op.startswith("tp1_") or op.startswith("tp2_") or op.startswith("sl_"):
            params["reduceOnly"] = True
        params["clOrdId"] = f"btc_{op[:10]}_{int(time.time())}"
        contracts = btc_size / contract_size
        if contracts <= 0:
            continue
        contracts = float(exchange.amount_to_precision(SYMBOL, contracts))
        if contracts <= 0:
            continue
        order = exchange.create_order(SYMBOL, "market", side, contracts, None, params)
        executed.append({"action": {**act, "contracts": contracts}, "order": order})
    return executed


def print_summary(exchange: ccxt.Exchange, df: pd.DataFrame, state: StrategyState, executed: list[dict]) -> None:
    balance = exchange.fetch_balance()
    usdt = balance.get("USDT", {})
    usdt_free = float(usdt.get("free", 0) or 0)
    usdt_total = float(usdt.get("total", 0) or 0)
    last_price = float(df["close"].iloc[-1])
    markets = exchange.load_markets()
    market = markets.get(SYMBOL) or exchange.market(SYMBOL)
    contract_size = float(market.get("contractSize", 1) or 1)
    try:
        positions = exchange.fetch_positions([SYMBOL])
    except Exception:
        positions = []
    try:
        recent_trades = exchange.fetch_my_trades(SYMBOL, limit=10)
    except Exception:
        recent_trades = []
    long_size = 0.0
    short_size = 0.0
    for p in positions:
        side = p.get("side")
        contracts = float(p.get("contracts", 0) or 0)
        if contracts <= 0:
            continue
        if side == "long":
            long_size += contracts
        elif side == "short":
            short_size += contracts
    total_equity = usdt_total if usdt_total > 0 else usdt_free

    print("\n===== BTC Strategy Daily Run =====")
    print("Time:", pd.Timestamp.now())
    print("Symbol:", SYMBOL, "| Timeframe:", TIMEFRAME)

    if executed:
        print("\n--- Executed Orders ---")
        for item in executed:
            act = item["action"]
            print(
                act["op"],
                "| side:", act["side"],
                "| size:", f"{act['size']:.6f}",
                "| price:", f"{act['price']:.2f}",
            )
    else:
        print("\nNo orders executed on this run.")

    print("\n--- Account Status (Swap) ---")
    print("USDT free:", f"{usdt_free:.4f}", "USDT total:", f"{usdt_total:.4f}")
    print("Last close price:", f"{last_price:.2f}")
    print(
        "Long contracts:", f"{long_size:.6f}",
        "(~", f"{long_size * contract_size:.6f}", "BTC )",
    )
    print(
        "Short contracts:", f"{short_size:.6f}",
        "(~", f"{short_size * contract_size:.6f}", "BTC )",
    )
    print("Approx account equity (USDT):", f"{total_equity:.2f}")

    print("\n--- Strategy State ---")
    print("Long entries:", len(state.long_entries), "Completed longs:", state.completed_long_trades)
    print("Short entries:", len(state.short_entries), "Completed shorts:", state.completed_short_trades)
    if recent_trades:
        print("\n--- Recent Trades ---")
        for t in sorted(recent_trades, key=lambda x: x.get("timestamp") or 0):
            ts = t.get("datetime") or t.get("timestamp")
            side = t.get("side")
            price = t.get("price")
            amount = t.get("amount")
            pos_side = _get_pos_side_from_trade(t)
            oid = t.get("order") or t.get("id")
            print("Time:", ts, "| posSide:", pos_side, "| side:", side, "| amount:", amount, "| price:", price, "| id:", oid)
    print("==============================\n")


def run_once() -> None:
    exchange = create_exchange()
    state = create_strategy_state()
    sync_state_from_exchange(exchange, state)
    df = fetch_ohlcv_df(exchange)
    last_price = float(df["close"].iloc[-1])
    account_value, cash = get_account_value_and_cash(exchange, last_price)
    actions = state.process_bar(df, account_value, cash)
    executed = execute_actions(exchange, actions)
    print_summary(exchange, df, state, executed)


if __name__ == "__main__":
    run_once()

