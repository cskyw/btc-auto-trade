# download_data.py
import okx.MarketData as MarketData
import pandas as pd
import time
from datetime import datetime
from API_real import api_key, secret_key, passphrase

flag = "0"  # 0=实盘  1=模拟s

marketAPI = MarketData.MarketAPI(api_key, secret_key, passphrase, False, flag)


def get_btc_daily(start="2022-05-01", end="2023-12-01"):
    start_ts = int(datetime.strptime(start, "%Y-%m-%d").timestamp() * 1000)
    end_ts = int(datetime.strptime(end, "%Y-%m-%d").timestamp() * 1000)

    all_data = []
    # 直接跳转到 end 日期的次日开始往回下载，跳过 2025/2026 年的数据
    jump_start_ts = end_ts + 86400000
    after = str(jump_start_ts)

    while True:
        # 使用 get_history_candlesticks 获取历史数据
        res = marketAPI.get_history_candlesticks(
            instId="SOL-USDT",
            bar="1D",
            after=after,
            limit=100
        )

        data = res["data"]
        if not data:
            break

        for row in data:
            ts = int(row[0])
            if ts < start_ts:
                break
            if start_ts <= ts <= end_ts:
                all_data.append(row)

        after = data[-1][0]

        if int(data[-1][0]) < start_ts:
            break

        time.sleep(0.1)

    df = pd.DataFrame(all_data, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "volCcy", "volCcyQuote", "confirm"
    ])

    df["date"] = pd.to_datetime(df["timestamp"], unit="ms")

    df = df.sort_values("date")

    df = df[["date", "open", "high", "low", "close", "volume"]]
    df = df.astype({
        "open": float,
        "high": float,
        "low": float,
        "close": float,
        "volume": float
    })

    df.to_csv("okx/SOLUSDT_1d_2022_2023.csv", index=False)
    print("数据已保存为 SOLUSDT_1d_2022_2023.csv")


if __name__ == "__main__":
    get_btc_daily()
