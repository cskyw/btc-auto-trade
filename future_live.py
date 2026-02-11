import ccxt
import pandas as pd
import time
from future_strategy import BTCMaBreakoutTP
from API_sim import api_key, secret_key, passphrase

SYMBOL = "BTC/USDT"
TIMEFRAME = "1d"
POSITION_SIZE_PCT = 0.15


# ===== 连接 OKX =====
exchange = ccxt.okx({
    "apiKey": api_key,
    "secret": secret_key,
    "password": passphrase,
    "enableRateLimit": True,
    "proxies": {
        "http": "http://127.0.0.1:7897",
        "https": "http://127.0.0.1:7897",
    }

})

exchange.set_sandbox_mode(True)


def get_balance():
    balance = exchange.fetch_balance()
    return balance["USDT"]["free"]


def get_ohlcv():
    ohlcv = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=300)
    df = pd.DataFrame(
        ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    return df


def calculate_signal(df):
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # 上穿信号
    if prev["close"] < prev["ma10"] and last["close"] > last["ma10"]:
        return "buy"

    # 下穿信号
    if prev["close"] > prev["ma10"] and last["close"] < last["ma10"]:
        return "sell"

    return None


def place_order(signal, price):

    usdt_balance = get_balance()
    trade_amount = usdt_balance * POSITION_SIZE_PCT
    size = trade_amount / price

    order = None

    if signal == "buy":
        order = exchange.create_market_buy_order(SYMBOL, size)
        print("🔥 BUY ORDER SENT:", order)

    elif signal == "sell":
        order = exchange.create_market_sell_order(SYMBOL, size)
        print("🔥 SELL ORDER SENT:", order)

    return {
        "side": signal,
        "price": price,
        "size": size,
        "trade_amount": trade_amount,
        "order_id": order.get("id") if isinstance(order, dict) else None,
    }


# def run():

#     print("🚀 OKX Sandbox Live Trading Running")

#     while True:
#         df = get_ohlcv()
#         signal = calculate_signal(df)

#         if signal:
#             last_price = df.iloc[-1]["close"]
#             place_order(signal, last_price)

#         print("Checked at:", pd.Timestamp.now())
#         time.sleep(60 * 60 * 24)  # 每天运行一次

def print_account_summary(last_price, signal, trade_info):
    balance = exchange.fetch_balance()
    usdt_free = balance["USDT"]["free"]
    btc_info = balance.get("BTC", {})
    btc_total = btc_info.get("total", 0)
    btc_free = btc_info.get("free", 0)

    print("\n===== Daily Summary =====")
    print("Time:", pd.Timestamp.now())
    print("Symbol:", SYMBOL, "| Timeframe:", TIMEFRAME)
    print("Signal:", signal or "no signal")

    if trade_info is not None:
        print("\n--- Today Trade ---")
        print(f"Side: {trade_info['side']}")
        print(f"Size: {trade_info['size']:.6f} BTC  (~{trade_info['trade_amount']:.2f} USDT)")
        print(f"Price: {trade_info['price']:.2f}")
        if trade_info.get("order_id"):
            print(f"Order ID: {trade_info['order_id']}")

    print("\n--- Account Status ---")
    print(f"USDT free: {usdt_free:.4f}")
    print(f"BTC total: {btc_total:.6f}, BTC free: {btc_free:.6f}")

    if last_price is not None:
        btc_value = btc_total * last_price
        total_equity = usdt_free + btc_value
        print(f"Last close price: {last_price:.2f}")
        print(f"BTC position value: {btc_value:.2f} USDT")
        print(f"Approx total equity: {total_equity:.2f} USDT")

    print("=========================\n")


def run():

    print("🚀 Daily Strategy Check")

    df = get_ohlcv()
    last_price = df.iloc[-1]["close"]
    signal = calculate_signal(df)

    trade_info = None
    if signal:
        trade_info = place_order(signal, last_price)

    print_account_summary(last_price, signal, trade_info)



if __name__ == "__main__":
    run()
    run()
