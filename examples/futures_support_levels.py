#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
期货支撑点位自动识别（按需求文档三模块 + 汇总输出）。

输入：期货日线 OHLCV（列名可为 AKShare `futures_hist_em` 之中文列，或英文 open/high/low/close/volume）。

说明：仅供研究示例，不构成投资建议。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd


@dataclass
class SupportLevelResult:
    """单日收盘后计算结果。"""

    level_1_support: Optional[float]
    level_2_support: Optional[float]
    level_1_from_resistance: Optional[float]
    dynamic_support: Optional[float]
    module1_min_low: Optional[float]
    module1_density_count: int
    module1_density_ok: bool
    ma20_volume: Optional[float]
    today_close: float
    today_volume: float
    sentiment: str
    detail: dict[str, Any]


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """统一为英文列名。"""
    mapping = {
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
    }
    out = df.copy()
    for c_zh, c_en in mapping.items():
        if c_zh in out.columns:
            out[c_en] = pd.to_numeric(out[c_zh], errors="coerce")
    need = {"open", "high", "low", "close", "volume"}
    miss = need - set(out.columns)
    if miss:
        raise ValueError(f"缺少列: {miss}，请提供 OHLCV 或 futures_hist_em 输出。")
    return out[list(need)].copy()


def module_absolute_bottom(
    lows: pd.Series,
    density_range: float = 15.0,
    density_min_days: int = 5,
) -> tuple[Optional[float], int, bool]:
    """
    模块一：绝对底部。
    最近 N1 根 K 的最低价序列，Min_Low，统计落在 [Min_Low, Min_Low+density_range] 的天数。
    """
    min_low = float(lows.min())
    cnt = int(((lows >= min_low) & (lows <= min_low + density_range)).sum())
    ok = cnt >= density_min_days
    level_2 = min_low if ok else None
    return level_2, cnt, ok


def module_resistance_to_support(
    prior_high: pd.Series,
    today_close: float,
) -> Optional[float]:
    """模块二：前 N1 日（不含今日）Max_High，若今日收盘突破则该 Max_High 为第一防线。"""
    if prior_high.empty:
        return None
    max_high = float(prior_high.max())
    if today_close > max_high:
        return max_high
    return None


def module_volume_anchor(
    prior_volumes: pd.Series,
    today_volume: float,
    today_low: float,
    t_vol: float,
) -> tuple[Optional[float], float]:
    """
    模块三：前 20 日（不含今日）均量；若今日量 > MA20 * t_vol，则今日最低为动态资金位。
    """
    ma20 = float(prior_volumes.mean())
    if today_volume > ma20 * t_vol:
        return float(today_low), ma20
    return None, ma20


def compute_futures_support_levels(
    df: pd.DataFrame,
    n1: int = 10,
    n2: int = 20,
    t_vol: float = 1.5,
    density_range: float = 15.0,
    density_min_days: int = 5,
) -> SupportLevelResult:
    """
    在「已按日期升序、且含当日一根完整日线」的 DataFrame 上计算。

    参数与需求文档一致：N1=10, N2=20, T_vol=1.5，密集区宽度 15 个价格单位。
    """
    need_len = max(n1, n2) + 2
    if len(df) < need_len:
        raise ValueError(f"数据不足：至少需要约 {need_len} 根日线，当前 {len(df)}。")

    d = _normalize_columns(df)
    d = d.dropna(subset=["open", "high", "low", "close", "volume"]).reset_index(drop=True)
    if len(d) < need_len:
        raise ValueError("有效 OHLCV 行数不足。")

    today_close = float(d["close"].iloc[-1])
    today_vol = float(d["volume"].iloc[-1])
    today_low = float(d["low"].iloc[-1])

    lows_n1 = d["low"].iloc[-n1:]
    level_2, density_cnt, density_ok = module_absolute_bottom(
        lows_n1,
        density_range=density_range,
        density_min_days=density_min_days,
    )
    module1_min_low = float(lows_n1.min())

    prior_high_n1 = d["high"].iloc[-(n1 + 1) : -1]
    level_1_res = module_resistance_to_support(prior_high_n1, today_close)

    prior_vol_n2 = d["volume"].iloc[-(n2 + 1) : -1]
    if len(prior_vol_n2) < n2:
        prior_vol_n2 = d["volume"].iloc[-n2 - 1 : -1]
    dynamic_support, ma20_vol = module_volume_anchor(
        prior_vol_n2, today_vol, today_low, t_vol
    )

    parts = [x for x in (level_1_res, dynamic_support) if x is not None]
    if parts:
        level_1 = max(parts)
    else:
        level_1 = None

    if level_1 is not None and today_close > level_1 and today_vol > ma20_vol:
        sentiment = "放量突破，上行通道开启，建议买入/持仓"
    elif level_1 is not None and today_close < level_1:
        sentiment = "短期趋势走弱，回踩第二支撑位"
    else:
        sentiment = "未触发文档中的多空情绪模板，请结合 Level_1/Level_2 人工判断。"

    detail = {
        "n1": n1,
        "n2": n2,
        "t_vol": t_vol,
        "density_range": density_range,
        "density_min_days": density_min_days,
        "prior_max_high_n1": float(prior_high_n1.max()) if len(prior_high_n1) else None,
        "breakout_vs_prior_high": today_close > float(prior_high_n1.max())
        if len(prior_high_n1)
        else None,
    }

    return SupportLevelResult(
        level_1_support=level_1,
        level_2_support=level_2,
        level_1_from_resistance=level_1_res,
        dynamic_support=dynamic_support,
        module1_min_low=module1_min_low,
        module1_density_count=density_cnt,
        module1_density_ok=density_ok,
        ma20_volume=ma20_vol,
        today_close=today_close,
        today_volume=today_vol,
        sentiment=sentiment,
        detail=detail,
    )


def format_report(r: SupportLevelResult) -> str:
    lines = [
        "=== 期货支撑点位（自动识别）===",
        f"Level_1 Support（第一支撑）: {r.level_1_support}",
        f"  — 压力转支撑: {r.level_1_from_resistance}",
        f"  — 动态资金位: {r.dynamic_support}",
        f"Level_2 Support（绝对支撑）: {r.level_2_support}",
        f"模块一: Min_Low(10日)={r.module1_min_low}, 密集区[{r.module1_min_low}, {r.module1_min_low + 15}] 命中天数={r.module1_density_count}, 达标={'是' if r.module1_density_ok else '否'}",
        f"MA20成交量(不含今日): {r.ma20_volume:.4g}, 今日成交量: {r.today_volume:.4g}",
        f"市场情绪: {r.sentiment}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import akshare as ak

    symbol = "RB2505"
    raw = ak.futures_hist_em(symbol=symbol, period="daily", start_date="20230101", end_date="20500101")
    out = compute_futures_support_levels(raw)
    print(format_report(out))
