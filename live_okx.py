import os
import sys

import ccxt
import pandas as pd

from strategy_engine import StrategyState


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

SYMBOL = "BTC/USDT"
TIMEFRAME = "1d"
STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")


def load_state() -> StrategyState:
    if not os.path.exists(STATE_PATH):
        return StrategyState()
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        data = f.read()
    return StrategyState.from_json(data)


def save_state(state: StrategyState) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        f.write(state.to_json())


def create_exchange() -> ccxt.Exchange:
    ex = ccxt.okx(
        {
            "apiKey": API_KEY,
            "secret": SECRET,
            "password": PASSWORD,
            "enableRateLimit": True,
    #          "proxies": {
    #     "http": "http://127.0.0.1:7897",
    #     "https": "http://127.0.0.1:7897",
    # }
        }
    )
    ex.set_sandbox_mode(True)
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
    usdt_free = float(balance["USDT"]["free"])
    btc_total = float(balance.get("BTC", {}).get("total", 0) or 0)
    btc_value = btc_total * last_price
    account_value = usdt_free + btc_value
    return account_value, usdt_free


def execute_actions(exchange: ccxt.Exchange, actions: list[dict]) -> list[dict]:
    executed = []
    for act in actions:
        side = act["side"]
        size = act["size"]
        if size <= 0:
            continue
        if side == "buy":
            order = exchange.create_market_buy_order(SYMBOL, size)
        else:
            order = exchange.create_market_sell_order(SYMBOL, size)
        executed.append({"action": act, "order": order})
    return executed


def print_summary(exchange: ccxt.Exchange, df: pd.DataFrame, state: StrategyState, executed: list[dict]) -> None:
    balance = exchange.fetch_balance()
    usdt_free = float(balance["USDT"]["free"])
    btc_info = balance.get("BTC", {})
    btc_total = float(btc_info.get("total", 0) or 0)
    btc_free = float(btc_info.get("free", 0) or 0)
    last_price = float(df["close"].iloc[-1])
    btc_value = btc_total * last_price
    total_equity = usdt_free + btc_value

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

    print("\n--- Account Status ---")
    print("USDT free:", f"{usdt_free:.4f}")
    print("BTC total:", f"{btc_total:.6f}", "BTC free:", f"{btc_free:.6f}")
    print("Last close price:", f"{last_price:.2f}")
    print("BTC position value:", f"{btc_value:.2f}", "USDT")
    print("Approx total equity:", f"{total_equity:.2f}", "USDT")

    print("\n--- Strategy State ---")
    print("Long entries:", len(state.long_entries), "Completed longs:", state.completed_long_trades)
    print("Short entries:", len(state.short_entries), "Completed shorts:", state.completed_short_trades)
    print("==============================\n")


def run_once() -> None:
    exchange = create_exchange()
    state = load_state()
    df = fetch_ohlcv_df(exchange)
    last_price = float(df["close"].iloc[-1])
    account_value, cash = get_account_value_and_cash(exchange, last_price)
    actions = state.process_bar(df, account_value, cash)
    executed = execute_actions(exchange, actions)
    save_state(state)
    print_summary(exchange, df, state, executed)


if __name__ == "__main__":
    run_once()

