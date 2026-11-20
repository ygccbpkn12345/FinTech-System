import argparse
import os
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Paths:
    input_dir: str
    output_csv: str


_INDUSTRY_FILE_RE = re.compile(r"Industry(\d+)\.csv$", re.IGNORECASE)


def _industry_id_from_filename(path: str) -> int:
    m = _INDUSTRY_FILE_RE.search(os.path.basename(path))
    if not m:
        raise ValueError(f"无法从文件名解析行业编号：{path}")
    return int(m.group(1))


def _read_industry_stock_prices(path: str) -> pd.DataFrame:
    # 保留股票代码前导 0
    df = pd.read_csv(
        path,
        dtype={"StockCode": "string"},
    )
    required = {"Date", "StockCode", "Open", "Close", "High", "Low", "Volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{os.path.basename(path)} 缺少列：{sorted(missing)}")

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    for c in ["Open", "Close", "High", "Low", "Volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _add_stock_returns(df: pd.DataFrame) -> pd.DataFrame:
    # 用“成分股收益率均值”构造行业收益率：单只股票日收益率 = Close / prev_close - 1
    out = df.sort_values(["StockCode", "Date"], kind="mergesort").copy()
    out["prev_close"] = out.groupby("StockCode", dropna=False)["Close"].shift(1)

    valid = out["prev_close"].notna() & (out["prev_close"] > 0) & out["Close"].notna()
    out["stock_return"] = np.where(valid, out["Close"] / out["prev_close"] - 1.0, np.nan)
    out["stock_log_return"] = np.where(valid, np.log(out["Close"] / out["prev_close"]), np.nan)
    return out


def build_industry_market_daily(industry_files: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    for fp in industry_files:
        industry_id = _industry_id_from_filename(fp)
        df = _read_industry_stock_prices(fp)
        df = _add_stock_returns(df)
        df["Industry_id"] = industry_id

        # 等权聚合：OHLC 取成分股均值；成交量用求和更符合“行业总量”
        daily = (
            df.groupby(["Date", "Industry_id"], dropna=False)
            .agg(
                industry_open=("Open", "mean"),
                industry_close=("Close", "mean"),
                industry_high=("High", "mean"),
                industry_low=("Low", "mean"),
                industry_volume=("Volume", "sum"),
                industry_return=("stock_return", "mean"),
                industry_log_return=("stock_log_return", "mean"),
                constituent_num=("StockCode", "nunique"),
            )
            .reset_index()
        )

        daily["Date"] = daily["Date"].dt.date.astype("string")
        daily["Industry_id"] = daily["Industry_id"].astype("Int64")
        daily["constituent_num"] = daily["constituent_num"].astype("Int64")
        frames.append(daily)

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["Date", "Industry_id"], kind="mergesort").reset_index(drop=True)
    return out[
        [
            "Date",
            "Industry_id",
            "industry_open",
            "industry_close",
            "industry_high",
            "industry_low",
            "industry_volume",
            "industry_return",
            "industry_log_return",
            "constituent_num",
        ]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="行业级行情聚合（由成分股等权聚合）")
    parser.add_argument(
        "--input_dir",
        default=os.path.join("Data", "IndustryPrice"),
        help="输入目录（默认：Data/IndustryPrice）",
    )
    parser.add_argument(
        "--output",
        default=os.path.join("Data", "industry_market_daily.csv"),
        help="输出 CSV（默认：Data/industry_market_daily.csv）",
    )
    args = parser.parse_args()

    paths = Paths(input_dir=args.input_dir, output_csv=args.output)
    if not os.path.isdir(paths.input_dir):
        raise FileNotFoundError(f"找不到输入目录：{paths.input_dir}")

    files = [
        os.path.join(paths.input_dir, fn)
        for fn in os.listdir(paths.input_dir)
        if _INDUSTRY_FILE_RE.search(fn)
    ]
    files = sorted(files, key=lambda p: _industry_id_from_filename(p))
    if not files:
        raise FileNotFoundError(f"在 {paths.input_dir} 下未找到 Industry*.csv")

    panel = build_industry_market_daily(files)
    os.makedirs(os.path.dirname(paths.output_csv) or ".", exist_ok=True)
    panel.to_csv(paths.output_csv, index=False, encoding="utf-8-sig")
    print(f"已生成：{paths.output_csv}，行数={len(panel)}，列数={panel.shape[1]}")


if __name__ == "__main__":
    main()

