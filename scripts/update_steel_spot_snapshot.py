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


def _load_spot_price_func(repo_root: Path):
    module_path = repo_root / "akshare" / "spot" / "spot_price_qh.py"
    spec = importlib.util.spec_from_file_location("spot_price_qh_mod", str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.spot_price_qh


def _to_float_or_none(value):
    try:
        v = float(value)
    except Exception:
        return None
    if v != v:
        return None
    return v


def build_snapshot(repo_root: Path, symbols: list[str], limit: int) -> dict:
    spot_price_qh = _load_spot_price_func(repo_root)
    output_symbols = {}

    for symbol in symbols:
        rows = []
        try:
            df = spot_price_qh(symbol=symbol)
            if df is not None and not df.empty:
                df = df.sort_values("日期").tail(limit)
                for _, item in df.iterrows():
                    rows.append(
                        {
                            "date": str(item["日期"]),
                            "fp": _to_float_or_none(item["期货收盘价"]),
                            "sp": _to_float_or_none(item["现货价格"]),
                        }
                    )
        except Exception:
            rows = []
        output_symbols[symbol] = rows

    return {
        "source": "99qh via akshare snapshot",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": output_symbols,
    }


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
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_path = repo_root / args.output
    output_js_path = repo_root / args.output_js
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    snapshot = build_snapshot(repo_root=repo_root, symbols=symbols, limit=args.limit)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    output_js_path.parent.mkdir(parents=True, exist_ok=True)
    with output_js_path.open("w", encoding="utf-8") as f:
        f.write("window.__steelSpotSnapshot = ")
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
        f.write(";\n")

    counts = {k: len(v) for k, v in snapshot["symbols"].items()}
    print("Updated snapshot:", output_path)
    print("Updated snapshot js:", output_js_path)
    print("Counts:", counts)


if __name__ == "__main__":
    main()
