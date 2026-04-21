#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Refresh docs/futures-tool/steel_spot_daily.json from 99qh spot trend data.

This script intentionally imports the target module directly to avoid importing
the whole akshare package tree and its optional heavy dependencies.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_SYMBOLS = [
    "螺纹钢",
    "热轧卷板",
    "线材",
    "不锈钢",
    "硅铁",
    "锰硅",
    "焦炭",
    "焦煤",
]

FALLBACK_100PPI_MAP = {
    "螺纹钢": "RB",
    "热轧卷板": "HC",
    "线材": "WR",
    "不锈钢": "SS",
    "硅铁": "SF",
    "锰硅": "SM",
    "焦炭": "J",
    "焦煤": "JM",
}


def _load_spot_price_func(repo_root: Path):
    module_path = repo_root / "akshare" / "spot" / "spot_price_qh.py"
    spec = importlib.util.spec_from_file_location("spot_price_qh_mod", str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.spot_price_qh


def _load_futures_spot_daily_func(repo_root: Path):
    module_path = repo_root / "akshare" / "futures" / "futures_basis.py"
    spec = importlib.util.spec_from_file_location("futures_basis_mod", str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.futures_spot_price_daily


def _to_float_or_none(value):
    try:
        v = float(value)
    except Exception:
        return None
    if v != v:
        return None
    return v


def _rows_from_99qh(df, limit: int) -> list[dict]:
    rows = []
    if df is None or df.empty:
        return rows
    df = df.sort_values("日期").tail(limit)
    for _, item in df.iterrows():
        rows.append(
            {
                "date": str(item["日期"]),
                "fp": _to_float_or_none(item["期货收盘价"]),
                "sp": _to_float_or_none(item["现货价格"]),
            }
        )
    return rows


def _rows_from_100ppi(df, symbol_code: str, limit: int) -> list[dict]:
    rows = []
    if df is None or df.empty:
        return rows
    cols = set(df.columns.tolist())
    if "symbol" not in cols or "spot_price" not in cols or "date" not in cols:
        return rows

    part = df[df["symbol"] == symbol_code].copy()
    if part.empty:
        return rows
    part["date"] = part["date"].astype(str)
    fp_col = "dom_price" if "dom_price" in cols else ("near_price" if "near_price" in cols else None)
    part = part.sort_values("date").tail(limit)

    for _, item in part.iterrows():
        rows.append(
            {
                "date": item["date"],
                "fp": _to_float_or_none(item[fp_col]) if fp_col else None,
                "sp": _to_float_or_none(item["spot_price"]),
            }
        )
    return rows


def build_snapshot(repo_root: Path, symbols: list[str], limit: int, fallback_start_day: str) -> dict:
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
    spot_price_qh = _load_spot_price_func(repo_root)
    futures_spot_price_daily = None
    fallback_boot_error = None
    try:
        futures_spot_price_daily = _load_futures_spot_daily_func(repo_root)
    except Exception as e:
        fallback_boot_error = e
    output_symbols = {}
    source_map = {}

    fallback_vars = sorted(
        {
            FALLBACK_100PPI_MAP[s]
            for s in symbols
            if s in FALLBACK_100PPI_MAP
        }
    )
    fallback_df = None
    if fallback_vars and futures_spot_price_daily is not None:
        try:
            fallback_df = futures_spot_price_daily(
                start_day=fallback_start_day,
                end_day=datetime.now().strftime("%Y%m%d"),
                vars_list=fallback_vars,
            )
        except Exception:
            fallback_df = None

    for symbol in symbols:
        rows = []
        src = "none"
        try:
            df = spot_price_qh(symbol=symbol)
            rows = _rows_from_99qh(df, limit=limit)
            if rows:
                src = "99qh"
        except Exception:
            rows = []
        if not rows and symbol in FALLBACK_100PPI_MAP:
            rows = _rows_from_100ppi(
                fallback_df,
                symbol_code=FALLBACK_100PPI_MAP[symbol],
                limit=limit,
            )
            if rows:
                src = "100ppi"
        output_symbols[symbol] = rows
        source_map[symbol] = src

    out = {
        "source": "99qh primary + 100ppi fallback via akshare snapshot",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": output_symbols,
        "sources": source_map,
    }
    if fallback_boot_error is not None:
        out["fallback_status"] = "disabled"
        out["fallback_error"] = str(fallback_boot_error)
    elif futures_spot_price_daily is None:
        out["fallback_status"] = "disabled"
    else:
        out["fallback_status"] = "enabled"
    return out


def main():
    parser = argparse.ArgumentParser(description="Update steel spot daily snapshot json")
    parser.add_argument("--limit", type=int, default=1500, help="Max rows per symbol")
    parser.add_argument(
        "--symbols",
        type=str,
        default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated symbol names",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="docs/futures-tool/steel_spot_daily.json",
        help="Output json path relative to repository root",
    )
    parser.add_argument(
        "--output-js",
        type=str,
        default="docs/futures-tool/steel_spot_daily.js",
        help="Output js path relative to repository root",
    )
    parser.add_argument(
        "--fallback-start-day",
        type=str,
        default="20240101",
        help="Start day for 100ppi fallback pull, format YYYYMMDD",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_path = repo_root / args.output
    output_js_path = repo_root / args.output_js
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    snapshot = build_snapshot(
        repo_root=repo_root,
        symbols=symbols,
        limit=args.limit,
        fallback_start_day=args.fallback_start_day,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    output_js_path.parent.mkdir(parents=True, exist_ok=True)
    with output_js_path.open("w", encoding="utf-8") as f:
        f.write("window.__steelSpotSnapshot = ")
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
        f.write(";\n")

    counts = {k: len(v) for k, v in snapshot["symbols"].items()}
    srcs = snapshot.get("sources", {})
    print("Updated snapshot:", output_path)
    print("Updated snapshot js:", output_js_path)
    print("Counts:", counts)
    print("Sources:", srcs)


if __name__ == "__main__":
    main()
