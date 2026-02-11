def should_stop_loss(entry_price: float, current_price: float, side: str, sl_pct: float) -> bool:
    """
    通用止损判断函数。

    :param entry_price: 开仓价格
    :param current_price: 当前价格
    :param side: 方向，"long" 或 "short"
    :param sl_pct: 止损百分比，例如 0.05 表示 5%
    :return: 达到止损条件则返回 True，否则 False
    """
    if sl_pct <= 0:
        return False

    if side == "long":
        pnl_pct = (current_price / entry_price) - 1.0
    elif side == "short":
        pnl_pct = (entry_price / current_price) - 1.0
    else:
        raise ValueError('side 必须是 "long" 或 "short"')

    return pnl_pct <= -sl_pct

