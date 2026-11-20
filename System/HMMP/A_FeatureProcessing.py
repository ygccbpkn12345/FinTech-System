import argparse
import ast
import csv
import os
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Paths:
    news_full_csv: str
    industry_market_daily_csv: str
    industry_price_dir: str
    out_news_features_csv: str
    out_price_features_csv: str


_INDUSTRY_FILE_RE = re.compile(r"Industry(\d+)\.csv$", re.IGNORECASE)


def _parse_embedding_mean(embedding_raw: object) -> float:
    """
    NewsFullData.csv 的 embedding 字段是向量字符串（可能换行、可能包含 ... 省略号）。
    这里只抽取一个“语义中心”标量：embedding 向量各维均值。
    """
    if embedding_raw is None or (isinstance(embedding_raw, float) and np.isnan(embedding_raw)):
        return float("nan")
    s = str(embedding_raw).strip()
    if not s:
        return float("nan")
    try:
        if "," in s:
            arr = np.asarray(ast.literal_eval(s), dtype=float)
        else:
            s2 = (
                s.replace("[", " ")
                .replace("]", " ")
                .replace("\n", " ")
                .replace("\r", " ")
                .replace("...", " ")
            )
            vals: list[float] = []
            for t in s2.split():
                try:
                    vals.append(float(t))
                except Exception:
                    continue
            arr = np.asarray(vals, dtype=float)
    except Exception:
        return float("nan")
    if arr.size == 0:
        return float("nan")
    return float(np.nanmean(arr))


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    v = pd.to_numeric(values, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce").fillna(0.0)
    mask = v.notna() & (w > 0)
    if not mask.any():
        return float("nan")
    return float(np.average(v[mask].to_numpy(), weights=w[mask].to_numpy()))


def _weighted_std(values: pd.Series, weights: pd.Series) -> float:
    v = pd.to_numeric(values, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce").fillna(0.0)
    mask = v.notna() & (w > 0)
    if not mask.any():
        return float("nan")
    x = v[mask].to_numpy()
    ww = w[mask].to_numpy()
    mu = np.average(x, weights=ww)
    var = np.average((x - mu) ** 2, weights=ww)
    return float(np.sqrt(var))


def _read_news_full_csv(path: str) -> pd.DataFrame:
    # embedding 单元格内可能有换行：必须用 python 引擎解析
    return pd.read_csv(
        path,
        engine="python",
        quoting=csv.QUOTE_MINIMAL,
        escapechar="\\",
        on_bad_lines="warn",
    )


def build_industry_news_features(news_full: pd.DataFrame) -> pd.DataFrame:
    df = news_full.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date.astype("string")
    df["Industry_id"] = pd.to_numeric(df["Industry_id"], errors="coerce").astype("Int64")

    if "news_count" not in df.columns:
        df["news_count"] = 1.0
    df["news_count"] = pd.to_numeric(df["news_count"], errors="coerce").fillna(0.0)

    df["label"] = df.get("label", np.nan)
    df["label"] = df["label"].astype("string").str.lower()
    df["pos_w"] = np.where(df["label"] == "positive", df["news_count"], 0.0)
    df["neg_w"] = np.where(df["label"] == "negative", df["news_count"], 0.0)
    df["neu_w"] = np.where(df["label"] == "neutral", df["news_count"], 0.0)

    df["embedding_mean_row"] = df["embedding"].apply(_parse_embedding_mean) if "embedding" in df.columns else np.nan

    group_cols = ["Date", "Industry_id"]

    def _agg_one(g: pd.DataFrame) -> pd.Series:
        total = float(g["news_count"].sum())
        has_news = 1 if total > 0 else 0
        pos_ratio = float(g["pos_w"].sum() / total) if total > 0 else 0.0
        neg_ratio = float(g["neg_w"].sum() / total) if total > 0 else 0.0
        neu_ratio = float(g["neu_w"].sum() / total) if total > 0 else 0.0
        return pd.Series(
            {
                "news_count": total,
                "positive_ratio": pos_ratio,
                "negative_ratio": neg_ratio,
                "neutral_ratio": neu_ratio,
                "sentiment_score_mean": _weighted_mean(g.get("sentiment_score"), g["news_count"]),
                "sentiment_score_std": _weighted_std(g.get("sentiment_score"), g["news_count"]),
                "embedding_mean": _weighted_mean(g["embedding_mean_row"], g["news_count"]),
                "has_news_mask": has_news,
            }
        )

    daily = df.groupby(group_cols, dropna=False).apply(_agg_one, include_groups=False).reset_index()
    daily = daily.sort_values(["Industry_id", "Date"], kind="mergesort").reset_index(drop=True)

    # 新闻冲击：滚动和 / 滚动均值（过去 3/5/10 天）
    for w in (3, 5, 10):
        daily[f"news_count_roll_sum_{w}"] = (
            daily.groupby("Industry_id", dropna=False)["news_count"].transform(lambda s: s.rolling(w, min_periods=1).sum())
        )
        daily[f"news_count_roll_mean_{w}"] = (
            daily.groupby("Industry_id", dropna=False)["news_count"].transform(lambda s: s.rolling(w, min_periods=1).mean())
        )

    # 情绪动量：sentiment_score_mean 的变化率（pct_change，避免除零）
    s = daily.groupby("Industry_id", dropna=False)["sentiment_score_mean"]
    for k in (1, 3, 5):
        daily[f"sentiment_mom_{k}"] = s.transform(lambda x: x.pct_change(k))

    daily = daily.sort_values(["Date", "Industry_id"], kind="mergesort").reset_index(drop=True)
    return daily


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def build_industry_price_features(industry_market_daily: pd.DataFrame) -> pd.DataFrame:
    df = industry_market_daily.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Industry_id"] = pd.to_numeric(df["Industry_id"], errors="coerce").astype("Int64")
    df = df.sort_values(["Industry_id", "Date"], kind="mergesort").reset_index(drop=True)

    close = df["industry_close"]
    high = df["industry_high"]
    low = df["industry_low"]
    vol = df["industry_volume"]

    # 基础收益率（用 close 计算，避免缺失 industry_return 时不一致）
    g = df.groupby("Industry_id", dropna=False)
    ret1 = g["industry_close"].transform(lambda s: s.pct_change(1))
    df["ret_1"] = ret1
    for k in (3, 5, 10, 20):
        df[f"ret_{k}"] = g["industry_close"].transform(lambda s, kk=k: s.pct_change(kk))

    # 波动率：ret_1 的滚动标准差
    for w in (5, 10, 20):
        df[f"vol_{w}"] = g["ret_1"].transform(lambda s, ww=w: s.rolling(ww, min_periods=ww).std())

    # 均线乖离：close 相对 MA 的偏离
    for w in (5, 10, 20):
        ma = g["industry_close"].transform(lambda s, ww=w: s.rolling(ww, min_periods=ww).mean())
        df[f"ma_{w}_gap"] = df["industry_close"] / ma - 1.0

    # 振幅（当日高低价区间）
    df["high_low_range"] = (high - low) / close

    # 成交量变化 & 换手代理
    df["volume_change"] = g["industry_volume"].transform(lambda s: s.pct_change(1))
    vol_ma20 = g["industry_volume"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["turnover_proxy"] = vol / vol_ma20 - 1.0

    # 技术指标：RSI / MACD / momentum
    df["rsi_14"] = g["industry_close"].transform(lambda s: _rsi(s, 14))
    macd_line = g["industry_close"].transform(lambda s: _macd(s)[0])
    macd_signal = g["industry_close"].transform(lambda s: _macd(s)[1])
    macd_hist = g["industry_close"].transform(lambda s: _macd(s)[2])
    df["macd"] = macd_line
    df["macd_signal"] = macd_signal
    df["macd_hist"] = macd_hist
    df["momentum_10"] = g["industry_close"].transform(lambda s: s.pct_change(10))

    out = df.copy()
    out["Date"] = out["Date"].dt.date.astype("string")
    out = out.sort_values(["Date", "Industry_id"], kind="mergesort").reset_index(drop=True)

    return out[
        [
            "Date",
            "Industry_id",
            "ret_1",
            "ret_3",
            "ret_5",
            "ret_10",
            "ret_20",
            "vol_5",
            "vol_10",
            "vol_20",
            "ma_5_gap",
            "ma_10_gap",
            "ma_20_gap",
            "high_low_range",
            "volume_change",
            "turnover_proxy",
            "rsi_14",
            "macd",
            "macd_signal",
            "macd_hist",
            "momentum_10",
        ]
    ]


def _add_price_features_to_industry_stock_file(path: str) -> None:
    df = pd.read_csv(path, dtype={"StockCode": "string"})
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    for c in ["Open", "Close", "High", "Low", "Volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.sort_values(["StockCode", "Date"], kind="mergesort").reset_index(drop=True)
    g = df.groupby("StockCode", dropna=False)

    # 收益率族
    df["ret_1"] = g["Close"].transform(lambda s: s.pct_change(1))
    for k in (3, 5, 10, 20):
        df[f"ret_{k}"] = g["Close"].transform(lambda s, kk=k: s.pct_change(kk))

    # 波动率（ret_1 的滚动 std）
    for w in (5, 10, 20):
        df[f"vol_{w}"] = g["ret_1"].transform(lambda s, ww=w: s.rolling(ww, min_periods=ww).std())

    # 均线乖离
    for w in (5, 10, 20):
        ma = g["Close"].transform(lambda s, ww=w: s.rolling(ww, min_periods=ww).mean())
        df[f"ma_{w}_gap"] = df["Close"] / ma - 1.0

    # 振幅
    df["high_low_range"] = (df["High"] - df["Low"]) / df["Close"]

    # 量价变化
    df["volume_change"] = g["Volume"].transform(lambda s: s.pct_change(1))
    vol_ma20 = g["Volume"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["turnover_proxy"] = df["Volume"] / vol_ma20 - 1.0

    # RSI / MACD / momentum
    df["rsi_14"] = g["Close"].transform(lambda s: _rsi(s, 14))
    df["macd"] = g["Close"].transform(lambda s: _macd(s)[0])
    df["macd_signal"] = g["Close"].transform(lambda s: _macd(s)[1])
    df["macd_hist"] = g["Close"].transform(lambda s: _macd(s)[2])
    df["momentum_10"] = g["Close"].transform(lambda s: s.pct_change(10))

    # 输出回原文件（覆盖）
    df["Date"] = df["Date"].dt.date.astype("string")
    df.to_csv(path, index=False, encoding="utf-8-sig")


def main() -> None:
    parser = argparse.ArgumentParser(description="构造预测用新闻/价格/技术指标特征")
    parser.add_argument("--news_full", default=os.path.join("Data", "NewsFullData.csv"))
    parser.add_argument("--industry_market_daily", default=os.path.join("Data", "industry_market_daily.csv"))
    parser.add_argument("--industry_price_dir", default=os.path.join("Data", "IndustryPrice"))
    parser.add_argument("--out_news", default=os.path.join("Data", "industry_news_features.csv"))
    parser.add_argument("--out_price", default=os.path.join("Data", "industry_price_features.csv"))
    args = parser.parse_args()

    paths = Paths(
        news_full_csv=args.news_full,
        industry_market_daily_csv=args.industry_market_daily,
        industry_price_dir=args.industry_price_dir,
        out_news_features_csv=args.out_news,
        out_price_features_csv=args.out_price,
    )

    # 3.1 新闻特征
    news_full = _read_news_full_csv(paths.news_full_csv)
    news_feat = build_industry_news_features(news_full)
    os.makedirs(os.path.dirname(paths.out_news_features_csv) or ".", exist_ok=True)
    news_feat.to_csv(paths.out_news_features_csv, index=False, encoding="utf-8-sig")

    # 价格特征（行业-日）
    mkt = pd.read_csv(paths.industry_market_daily_csv)
    price_feat = build_industry_price_features(mkt)
    os.makedirs(os.path.dirname(paths.out_price_features_csv) or ".", exist_ok=True)
    price_feat.to_csv(paths.out_price_features_csv, index=False, encoding="utf-8-sig")

    # 回写到每个 Industry*.csv（逐股票）
    if os.path.isdir(paths.industry_price_dir):
        files = [
            os.path.join(paths.industry_price_dir, fn)
            for fn in os.listdir(paths.industry_price_dir)
            if _INDUSTRY_FILE_RE.search(fn)
        ]
        files = sorted(files, key=lambda p: int(_INDUSTRY_FILE_RE.search(os.path.basename(p)).group(1)))  # type: ignore[union-attr]
        for fp in files:
            _add_price_features_to_industry_stock_file(fp)

    print(
        "已生成：\n"
        f"- {paths.out_news_features_csv}\n"
        f"- {paths.out_price_features_csv}\n"
        f"并已回写特征到：{paths.industry_price_dir}/Industry*.csv"
    )


if __name__ == "__main__":
    main()

