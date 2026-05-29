# -*- coding: utf-8 -*-
"""
A-share stock screener: PE (TTM, self-calculated), financial metrics, hard rules.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# 避免 Windows 上失效的系统代理导致东方财富请求失败
def _clear_proxy_env() -> None:
    if os.environ.get("AKSHARE_KEEP_PROXY") == "1":
        return
    for key in list(os.environ):
        if "proxy" in key.lower():
            os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"


_clear_proxy_env()

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import requests as _requests

_orig_session = _requests.Session


class _NoProxySession(_orig_session):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trust_env = False


_requests.Session = _NoProxySession
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

import pandas as pd

# akshare interfaces
from akshare.stock.stock_info import stock_info_a_code_name
from akshare.stock_feature.stock_hist_em import stock_zh_a_spot_em
from akshare.stock_feature.stock_three_report_em import (
    stock_balance_sheet_by_report_em,
    stock_profit_sheet_by_report_em,
)

PROFIT_FIELDS = {
    "revenue": "TOTAL_OPERATE_INCOME",
    "operate_cost": "TOTAL_OPERATE_COST",
    "deduct_net_parent": "DEDUCT_PARENT_NETPROFIT",
}
BALANCE_FIELDS = {
    "current_assets": "TOTAL_CURRENT_ASSETS",
    "current_liab": "TOTAL_CURRENT_LIAB",
}
SEMI_ANNUAL_SUFFIXES = ("-06-30", "-12-31")


@dataclass
class ScanConfig:
    pe_min: float = 5.0
    pe_max: float = 25.0
    periods: int = 8  # ~4 years of semi-annual + annual
    max_workers: int = 6
    request_delay: float = 0.15
    limit: int = 0  # 0 = no limit
    apply_hard_rules: bool = True
    min_current_ratio: float = 1.0
    revenue_growth_years: int = 3  # consecutive annual revenue increase


@dataclass
class ScanProgress:
    status: str = "idle"  # idle | running | done | error
    total: int = 0
    done: int = 0
    passed: int = 0
    message: str = ""
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


def to_em_symbol(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("5", "6", "9")):
        return f"SH{code}"
    return f"SZ{code}"


def normalize_report_date(value: Any) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return str(value)[:10]
    return ts.strftime("%Y-%m-%d")


def is_st_stock(name: str) -> bool:
    name = str(name).upper()
    return "ST" in name


def is_star_market(code: str) -> bool:
    return str(code).zfill(6).startswith("688")


def _universe_from_code_list() -> pd.DataFrame:
    """行情接口不可用时的备用股票池（无市值，后续按个股跳过 PE 或重试行情）。"""
    raw = stock_info_a_code_name()
    df = raw.rename(columns={"code": "code", "name": "name"})
    df["code"] = df["code"].astype(str).str.zfill(6)
    mask = ~df["name"].map(is_st_stock) & ~df["code"].map(is_star_market)
    df = df.loc[mask, ["code", "name"]].copy()
    df["market_cap"] = pd.NA
    df["price"] = pd.NA
    df["em_symbol"] = df["code"].map(to_em_symbol)
    return df.reset_index(drop=True)


def load_universe() -> pd.DataFrame:
    try:
        spot = stock_zh_a_spot_em()
        spot = spot.rename(
            columns={
                "代码": "code",
                "名称": "name",
                "总市值": "market_cap",
                "最新价": "price",
            }
        )
        spot["code"] = spot["code"].astype(str).str.zfill(6)
        spot["market_cap"] = pd.to_numeric(spot["market_cap"], errors="coerce")
        mask = (
            spot["market_cap"].notna()
            & (spot["market_cap"] > 0)
            & ~spot["name"].map(is_st_stock)
            & ~spot["code"].map(is_star_market)
        )
        universe = spot.loc[mask, ["code", "name", "market_cap", "price"]].copy()
        universe["em_symbol"] = universe["code"].map(to_em_symbol)
        return universe.reset_index(drop=True)
    except Exception:
        return _universe_from_code_list()


def _pick_report_row(df: pd.DataFrame, suffix: str, year: int) -> Optional[pd.Series]:
    target = f"{year}{suffix}"
    hits = df[df["report_date"] == target]
    if hits.empty:
        return None
    return hits.iloc[0]


def calc_ttm_deduct(profit_df: pd.DataFrame) -> Optional[float]:
    """TTM 归母扣非：按 A 股累计财报口径折算最近 12 个月。"""
    if profit_df.empty or "deduct_net_parent" not in profit_df.columns:
        return None
    df = profit_df.sort_values("report_date", ascending=False).reset_index(drop=True)
    latest = df.iloc[0]
    rd = latest["report_date"]
    deduct = latest.get("deduct_net_parent")
    if pd.isna(deduct):
        return None
    md = rd[5:10]  # MM-DD
    year = int(rd[:4])

    if md == "12-31":
        return float(deduct)

    prev_annual = _pick_report_row(df, "-12-31", year - 1)
    same_prev = _pick_report_row(df, rd[4:], year - 1)
    if prev_annual is None or same_prev is None:
        return None
    ann = prev_annual.get("deduct_net_parent")
    prev_same = same_prev.get("deduct_net_parent")
    if pd.isna(ann) or pd.isna(prev_same):
        return None
    ttm = float(deduct) + float(ann) - float(prev_same)
    return ttm if ttm > 0 else None


def _fetch_market_cap_em(code: str) -> Optional[float]:
    """单股总市值（绕过系统代理）。"""
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    market_code = 1 if str(code).startswith("6") else 0
    params = {
        "fltt": "2",
        "invt": "2",
        "fields": "f116,f43,f57",
        "secid": f"{market_code}.{code}",
    }
    try:
        with _NoProxySession() as session:
            r = session.get(url, params=params, timeout=15)
            r.raise_for_status()
            data = r.json().get("data") or {}
        cap = normalize_market_cap(data.get("f116"))
        return cap
    except Exception:
        return None


def normalize_market_cap(cap: Any) -> Optional[float]:
    """行情列表总市值多为万元，单股 f116 为元。"""
    if cap is None or pd.isna(cap):
        return None
    v = float(cap)
    if v <= 0:
        return None
    if v < 1e10:
        return v * 10000.0
    return v


def resolve_market_cap(code: str, market_cap: Any) -> Optional[float]:
    cap = normalize_market_cap(market_cap)
    if cap is not None:
        return cap
    return _fetch_market_cap_em(code)


def calc_pe_ttm(market_cap: float, ttm_profit: Optional[float]) -> Optional[float]:
    if ttm_profit is None or ttm_profit <= 0 or pd.isna(market_cap):
        return None
    return float(market_cap) / float(ttm_profit)


def build_period_metrics(
    profit_df: pd.DataFrame, balance_df: pd.DataFrame, periods: int
) -> pd.DataFrame:
    p = profit_df.copy()
    b = balance_df.copy()
    merged = p.merge(b, on="report_date", how="inner", suffixes=("_p", "_b"))
    merged = merged[merged["report_date"].str.endswith(SEMI_ANNUAL_SUFFIXES)]
    merged = merged.sort_values("report_date", ascending=False).head(periods)
    merged = merged.sort_values("report_date")

    rows = []
    for _, row in merged.iterrows():
        revenue = row.get("revenue")
        operate_cost = row.get("operate_cost")
        deduct = row.get("deduct_net_parent")
        ca = row.get("current_assets")
        cl = row.get("current_liab")

        gross_profit = (
            float(revenue) - float(operate_cost)
            if pd.notna(revenue) and pd.notna(operate_cost)
            else None
        )
        gross_margin = (
            gross_profit / float(revenue)
            if gross_profit is not None and revenue and float(revenue) > 0
            else None
        )
        net_margin = (
            float(deduct) / float(revenue)
            if pd.notna(deduct) and revenue and float(revenue) > 0
            else None
        )
        current_ratio = (
            float(ca) / float(cl)
            if pd.notna(ca) and pd.notna(cl) and float(cl) > 0
            else None
        )
        rows.append(
            {
                "report_date": row["report_date"],
                "report_type": row.get("report_type_p") or row.get("report_type"),
                "revenue": revenue,
                "operate_cost": operate_cost,
                "deduct_net_parent": deduct,
                "current_assets": ca,
                "current_liab": cl,
                "gross_profit": gross_profit,
                "gross_margin": gross_margin,
                "net_margin": net_margin,
                "current_ratio": current_ratio,
            }
        )
    return pd.DataFrame(rows)


def annual_revenue_increasing(profit_df: pd.DataFrame, years: int) -> bool:
    if profit_df.empty or "revenue" not in profit_df.columns:
        return False
    annual = profit_df[profit_df["report_date"].str.endswith("-12-31")].sort_values(
        "report_date"
    )
    if len(annual) < years:
        return False
    annual = annual.tail(years)
    revs = annual["revenue"].tolist()
    if any(pd.isna(r) for r in revs):
        return False
    return all(revs[i] < revs[i + 1] for i in range(len(revs) - 1))


def passes_hard_rules(
    metrics: pd.DataFrame, profit_df: pd.DataFrame, cfg: ScanConfig
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if metrics.empty:
        return False, ["无财报数据"]
    latest = metrics.iloc[-1]
    cr = latest.get("current_ratio")
    if pd.isna(cr) or float(cr) < cfg.min_current_ratio:
        reasons.append(f"流动比率<{cfg.min_current_ratio}")
    if not annual_revenue_increasing(profit_df, cfg.revenue_growth_years):
        reasons.append(f"最近{cfg.revenue_growth_years}个年报收入未连增")
    return len(reasons) == 0, reasons


def _extract_profit(em_symbol: str) -> pd.DataFrame:
    raw = stock_profit_sheet_by_report_em(symbol=em_symbol)
    if raw.empty:
        return pd.DataFrame()
    df = pd.DataFrame()
    df["report_date"] = raw["REPORT_DATE"].map(normalize_report_date)
    df["report_type"] = raw.get("REPORT_DATE_NAME", raw.get("REPORT_TYPE"))
    for key, col in PROFIT_FIELDS.items():
        if col in raw.columns:
            df[key] = pd.to_numeric(raw[col], errors="coerce")
    if "deduct_net_parent" not in df.columns or df["deduct_net_parent"].isna().all():
        for col in (
            "DEDUCT_PARENT_NETPROFIT",
            "DEDUCT_NETPROFIT",
            "PARENT_NETPROFIT",
            "NETPROFIT",
        ):
            if col in raw.columns:
                df["deduct_net_parent"] = pd.to_numeric(raw[col], errors="coerce")
                break
    return df.drop_duplicates(subset=["report_date"], keep="first")


def _extract_balance(em_symbol: str) -> pd.DataFrame:
    raw = stock_balance_sheet_by_report_em(symbol=em_symbol)
    if raw.empty:
        return pd.DataFrame()
    df = pd.DataFrame()
    df["report_date"] = raw["REPORT_DATE"].map(normalize_report_date)
    df["report_type"] = raw.get("REPORT_DATE_NAME", raw.get("REPORT_TYPE"))
    for key, col in BALANCE_FIELDS.items():
        if col in raw.columns:
            df[key] = pd.to_numeric(raw[col], errors="coerce")
    return df.drop_duplicates(subset=["report_date"], keep="first")


def analyze_stock(
    code: str,
    name: str,
    market_cap: float,
    em_symbol: str,
    cfg: ScanConfig,
) -> Optional[dict[str, Any]]:
    profit_df = _extract_profit(em_symbol)
    balance_df = _extract_balance(em_symbol)
    if profit_df.empty or balance_df.empty:
        return None

    ttm_profit = calc_ttm_deduct(profit_df)
    cap = resolve_market_cap(code, market_cap)
    if cap is None:
        return None
    pe_ttm = calc_pe_ttm(cap, ttm_profit)
    if pe_ttm is None or not (cfg.pe_min <= pe_ttm <= cfg.pe_max):
        return None

    metrics = build_period_metrics(profit_df, balance_df, cfg.periods)
    if metrics.empty:
        return None

    hard_ok, hard_reasons = passes_hard_rules(metrics, profit_df, cfg)
    if cfg.apply_hard_rules and not hard_ok:
        return None

    latest = metrics.iloc[-1]
    return {
        "code": code,
        "name": name,
        "market_cap": cap,
        "pe_ttm": round(pe_ttm, 2),
        "ttm_deduct_profit": ttm_profit,
        "latest_report_date": latest["report_date"],
        "latest_gross_margin": _pct(latest.get("gross_margin")),
        "latest_net_margin": _pct(latest.get("net_margin")),
        "latest_current_ratio": _round(latest.get("current_ratio"), 3),
        "hard_rules_pass": hard_ok,
        "hard_rules_note": "; ".join(hard_reasons) if hard_reasons else "通过",
        "periods": metrics.to_dict(orient="records"),
    }


def _pct(v: Any) -> Optional[str]:
    if v is None or pd.isna(v):
        return None
    return f"{float(v) * 100:.2f}%"


def _round(v: Any, n: int = 2) -> Optional[float]:
    if v is None or pd.isna(v):
        return None
    return round(float(v), n)


@dataclass
class ScanJob:
    config: ScanConfig
    progress: ScanProgress = field(default_factory=ScanProgress)
    results: list[dict[str, Any]] = field(default_factory=list)
    summary_rows: list[dict[str, Any]] = field(default_factory=list)


def run_scan(
    job: ScanJob,
    on_progress: Optional[Callable[[ScanProgress], None]] = None,
) -> None:
    cfg = job.config
    prog = job.progress
    prog.status = "running"
    prog.started_at = datetime.now().isoformat(timespec="seconds")
    prog.message = "加载股票池…"

    try:
        universe = load_universe()
        if cfg.limit and cfg.limit > 0:
            universe = universe.head(cfg.limit)
        prog.total = len(universe)
        prog.message = f"共 {prog.total} 只股票待分析"
        if on_progress:
            on_progress(prog)

        def _task(row: pd.Series) -> Optional[dict[str, Any]]:
            time.sleep(cfg.request_delay)
            try:
                return analyze_stock(
                    code=row["code"],
                    name=row["name"],
                    market_cap=float(row["market_cap"]),
                    em_symbol=row["em_symbol"],
                    cfg=cfg,
                )
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
            futures = {
                pool.submit(_task, row): row["code"] for _, row in universe.iterrows()
            }
            for fut in as_completed(futures):
                prog.done += 1
                item = fut.result()
                if item:
                    job.results.append(item)
                    job.summary_rows.append(_summary_row(item))
                    prog.passed += 1
                if on_progress and prog.done % 5 == 0:
                    on_progress(prog)
                if prog.done % 10 == 0:
                    prog.message = f"已处理 {prog.done}/{prog.total}，命中 {prog.passed}"

        job.summary_rows.sort(key=lambda x: x.get("pe_ttm") or 999)
        prog.status = "done"
        prog.message = f"完成：命中 {prog.passed} / {prog.total}"
        prog.finished_at = datetime.now().isoformat(timespec="seconds")
    except Exception as exc:
        prog.status = "error"
        prog.error = str(exc)
        prog.message = "扫描失败"
        prog.finished_at = datetime.now().isoformat(timespec="seconds")
    if on_progress:
        on_progress(prog)


def _summary_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": item["code"],
        "name": item["name"],
        "pe_ttm": item["pe_ttm"],
        "market_cap": item["market_cap"],
        "latest_report_date": item["latest_report_date"],
        "latest_gross_margin": item["latest_gross_margin"],
        "latest_net_margin": item["latest_net_margin"],
        "latest_current_ratio": item["latest_current_ratio"],
        "hard_rules_pass": item.get("hard_rules_pass"),
        "hard_rules_note": item.get("hard_rules_note"),
    }


def flatten_export_rows(results: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for stock in results:
        for p in stock.get("periods", []):
            rows.append(
                {
                    "代码": stock["code"],
                    "名称": stock["name"],
                    "PE_TTM": stock["pe_ttm"],
                    "总市值": stock["market_cap"],
                    "报告期": p["report_date"],
                    "报告类型": p.get("report_type"),
                    "营业总收入": p.get("revenue"),
                    "营业总成本": p.get("operate_cost"),
                    "归母扣非净利润": p.get("deduct_net_parent"),
                    "流动资产合计": p.get("current_assets"),
                    "流动负债合计": p.get("current_liab"),
                    "毛利润": p.get("gross_profit"),
                    "毛利率": _fmt_ratio(p.get("gross_margin")),
                    "净利率": _fmt_ratio(p.get("net_margin")),
                    "流动比率": p.get("current_ratio"),
                    "硬性规则": stock.get("hard_rules_note"),
                }
            )
    return pd.DataFrame(rows)


def _fmt_ratio(v: Any) -> Optional[str]:
    if v is None or pd.isna(v):
        return None
    return f"{float(v) * 100:.2f}%"
