"""
B_DataLoader.py

多模态数据加载器，用于：
- 股票层（行业成分股）特征（每个行业的股票数量可变）
- 行业层价格特征
- 行业层新闻特征

满足的关键需求：
1) 自动扫描并加载 Data/IndustryPrice/ 下所有 Industry*.csv
2) 将 Date 解析为 pandas datetime
3) 每个行业：保留 StockCode，并按 Date、StockCode 排序
4) 加载 industry_price_features.csv
5) 加载 industry_news_features.csv
6) 按 Date 与 Industry_id 对齐三类数据

该加载器支持：
- 返回可用日期列表
- 按日期范围切片
- 构建单日样本（padding + mask），以及“下一交易日收益”作为监督目标（可选）
- 只用训练窗口拟合标准化参数（避免未来信息泄漏）

该文件设计为后续可直接被 B_Train.py 调用。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import torch


def resolve_device(device: str | torch.device = "auto") -> torch.device:
    """
    解析张量设备；请求 CUDA 但不可用时自动回退 cpu。
    device='auto' 时：有 CUDA 用 cuda:0，否则 cpu。
    """
    raw = str(device).strip().lower()
    if raw == "auto":
        return torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    dev = torch.device(device)
    if dev.type != "cuda":
        return dev

    if not torch.cuda.is_available():
        print(f"[device] CUDA 不可用，已回退到 cpu（请求: {device}）")
        return torch.device("cpu")

    if dev.index is not None and dev.index >= torch.cuda.device_count():
        fallback = torch.device("cuda:0")
        print(f"[device] {device} 不存在，已改用 {fallback}")
        return fallback

    return dev


def _to_datetime_series(s: pd.Series) -> pd.Series:
    """将日期列解析为 pandas datetime（并 normalize 到日期粒度）。"""
    dt = pd.to_datetime(s, errors="coerce")
    # normalize 到 00:00:00，避免时区/时分秒造成的对齐问题
    return dt.dt.normalize()


def _safe_float_frame(df: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    """
    将指定列转换为 float32，并将 inf 替换为 nan。
    注意：保留 NaN（后续模型/标准化器会处理）。
    """
    out = df.loc[:, cols].copy()
    for c in cols:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.replace([np.inf, -np.inf], np.nan)
    return out.astype(np.float32)


def _extract_industry_id_from_filename(path: Path) -> int:
    """
    支持的文件名示例：
    - Industry0.csv
    - Industry_0.csv
    - industry10.csv
    返回整数 industry_id。
    """
    m = re.search(r"industry[_\-]?(?P<id>\d+)\.csv$", path.name, flags=re.IGNORECASE)
    if not m:
        raise ValueError(f"Cannot parse Industry_id from filename: {path.name}")
    return int(m.group("id"))


@dataclass
class NormalizerState:
    """各模态的 mean/std（仅用训练窗口拟合）。"""

    stock_mean: np.ndarray
    stock_std: np.ndarray
    price_mean: np.ndarray
    price_std: np.ndarray
    news_mean: np.ndarray
    news_std: np.ndarray

    stock_feature_cols: List[str]
    price_feature_cols: List[str]
    news_feature_cols: List[str]


class MultiModalIndustryDataLoader:
    """
    读取并对齐：
    - 行业成分股（股票层）特征表（来自 Data/IndustryPrice/Industry*.csv）
    - 行业价格特征表（Data/industry_price_features.csv）
    - 行业新闻特征表（Data/industry_news_features.csv）
    """

    def __init__(
        self,
        data_dir: str | Path = "Data",
        industry_dir: str | Path = "Data/IndustryPrice",
        industry_pattern: str = "Industry*.csv",
        price_features_file: str = "industry_price_features.csv",
        news_features_file: str = "industry_news_features.csv",
        device: str | torch.device = "auto",
        calendar_mode: str = "price",
        news_ffill: bool = True,
        news_ffill_limit: Optional[int] = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.industry_dir = Path(industry_dir)
        self.industry_pattern = industry_pattern
        self.price_features_path = self.data_dir / price_features_file
        self.news_features_path = self.data_dir / news_features_file
        self.device = resolve_device(device)
        # calendar_mode:
        #   - "price"：以价格特征交易日为主（新闻可缺失并用前向填充）
        #   - "intersection"：价格∩新闻（旧行为，2015 等年份会大量丢日）
        #   - "union"：价格∪新闻
        mode = str(calendar_mode).strip().lower()
        if mode not in {"price", "intersection", "union"}:
            raise ValueError(f"calendar_mode 必须是 price/intersection/union，收到: {calendar_mode}")
        self.calendar_mode = mode
        self.news_ffill = bool(news_ffill)
        self.news_ffill_limit = None if news_ffill_limit is None else int(news_ffill_limit)

        self._industry_stock_dfs: Dict[int, pd.DataFrame] = {}
        self._price_df: Optional[pd.DataFrame] = None
        self._news_df: Optional[pd.DataFrame] = None
        # 按价格日历展开、行业内前向填充后的新闻表（Date, Industry_id, features...）
        self._news_aligned_df: Optional[pd.DataFrame] = None

        self._industry_ids: Optional[np.ndarray] = None
        self._all_dates: Optional[np.ndarray] = None  # datetime64[ns]

        self.stock_feature_cols: List[str] = []
        self.price_feature_cols: List[str] = []
        self.news_feature_cols: List[str] = []

    # -------------------------
    # Public API
    # -------------------------
    def load_all(self) -> None:
        """加载所有必需 CSV 到内存，并准备索引信息。"""
        self._industry_stock_dfs = self._load_all_industry_stock_files()
        self._price_df = self._load_industry_price_features()
        self._news_df = self._load_industry_news_features()

        self._industry_ids = np.array(sorted(self._industry_stock_dfs.keys()), dtype=np.int64)
        self._infer_feature_columns()
        self._news_aligned_df = self._build_news_aligned_table()
        self._all_dates = self._compute_available_dates(mode=self.calendar_mode)

    def industry_ids(self) -> np.ndarray:
        self._ensure_loaded()
        assert self._industry_ids is not None
        return self._industry_ids.copy()

    def available_dates(self, intersection: Optional[bool] = None, mode: Optional[str] = None) -> np.ndarray:
        """
        返回排序后的可用日期。

        优先使用 mode；若未指定则：
        - intersection=True  -> "intersection"（兼容旧调用）
        - intersection=False -> "union"
        - 二者都未指定       -> 使用 self.calendar_mode（默认 "price"）
        """
        self._ensure_loaded()
        if mode is not None:
            use_mode = str(mode).strip().lower()
        elif intersection is True:
            use_mode = "intersection"
        elif intersection is False:
            use_mode = "union"
        else:
            use_mode = self.calendar_mode
        return self._compute_available_dates(mode=use_mode)

    def slice_dates(
        self,
        start_date: str | pd.Timestamp | None = None,
        end_date: str | pd.Timestamp | None = None,
        intersection: Optional[bool] = None,
        mode: Optional[str] = None,
    ) -> np.ndarray:
        """返回限定在 [start_date, end_date] 区间内的可用日期。"""
        dates = self.available_dates(intersection=intersection, mode=mode)
        if start_date is not None:
            start = pd.to_datetime(start_date).normalize().to_datetime64()
            dates = dates[dates >= start]
        if end_date is not None:
            end = pd.to_datetime(end_date).normalize().to_datetime64()
            dates = dates[dates <= end]
        return dates

    def fit_normalizer(
        self,
        train_dates: Sequence[np.datetime64] | Sequence[pd.Timestamp] | np.ndarray,
        ddof: int = 0,
        eps: float = 1e-6,
    ) -> NormalizerState:
        """
        仅使用训练日期拟合标准化统计量（严格避免未来信息泄漏）。
        使用 mean/std（float32），并忽略 NaN/inf。
        """
        self._ensure_loaded()
        assert self._price_df is not None and self._news_df is not None

        train_dates = self._as_datetime64_array(train_dates)
        # 说明：这里使用 numpy 的 membership 逻辑，避免 pandas/numpy API 不一致导致的问题
        train_dates = train_dates.astype("datetime64[ns]")

        # ---- 股票层（跨行业、跨股票）的统计量
        stock_sum = None
        stock_sumsq = None
        stock_cnt = None
        for _, sdf in self._industry_stock_dfs.items():
            date_arr = sdf["Date"].values.astype("datetime64[ns]")
            sdf_train = sdf[np.isin(date_arr, train_dates)]
            if sdf_train.empty:
                continue
            X = _safe_float_frame(sdf_train, self.stock_feature_cols).to_numpy()  # [N, F_s]
            # 忽略 NaN/inf
            mask = np.isfinite(X)
            X0 = np.where(mask, X, 0.0).astype(np.float64)
            if stock_sum is None:
                stock_sum = X0.sum(axis=0)
                stock_sumsq = (X0 * X0).sum(axis=0)
                stock_cnt = mask.sum(axis=0).astype(np.float64)
            else:
                stock_sum += X0.sum(axis=0)
                stock_sumsq += (X0 * X0).sum(axis=0)
                stock_cnt += mask.sum(axis=0).astype(np.float64)

        if stock_sum is None:
            raise RuntimeError("No stock rows found for the provided train_dates.")

        stock_mean = (stock_sum / np.maximum(stock_cnt, 1.0)).astype(np.float32)
        stock_var = (stock_sumsq / np.maximum(stock_cnt, 1.0) - stock_mean.astype(np.float64) ** 2).astype(
            np.float64
        )
        if ddof == 1:
            # 无偏方差：当 n>1 时，var 乘以 n/(n-1)
            adj = np.where(stock_cnt > 1, stock_cnt / (stock_cnt - 1.0), 1.0)
            stock_var *= adj
        stock_std = np.sqrt(np.maximum(stock_var, 0.0)).astype(np.float32)
        stock_std = np.maximum(stock_std, eps).astype(np.float32)

        # ---- 行业价格特征统计量
        price_date_arr = self._price_df["Date"].values.astype("datetime64[ns]")
        pdf_train = self._price_df[np.isin(price_date_arr, train_dates)]
        Xp = _safe_float_frame(pdf_train, self.price_feature_cols).to_numpy()
        price_mean, price_std = self._mean_std_ignore_nan(Xp, ddof=ddof, eps=eps)

        # ---- 行业新闻特征统计量
        news_date_arr = self._news_df["Date"].values.astype("datetime64[ns]")
        ndf_train = self._news_df[np.isin(news_date_arr, train_dates)]
        Xn = _safe_float_frame(ndf_train, self.news_feature_cols).to_numpy()
        news_mean, news_std = self._mean_std_ignore_nan(Xn, ddof=ddof, eps=eps)

        return NormalizerState(
            stock_mean=stock_mean,
            stock_std=stock_std,
            price_mean=price_mean,
            price_std=price_std,
            news_mean=news_mean,
            news_std=news_std,
            stock_feature_cols=list(self.stock_feature_cols),
            price_feature_cols=list(self.price_feature_cols),
            news_feature_cols=list(self.news_feature_cols),
        )

    def build_sample(
        self,
        date: str | pd.Timestamp | np.datetime64,
        normalizer: Optional[NormalizerState] = None,
        include_target: bool = True,
    ) -> Dict[str, torch.Tensor]:
        """
        构建“单日样本”（一个日期的一次前向输入）。

        返回位于 self.device 上的张量字典：
        - stock_x: [I, S_max, F_s]
        - stock_mask: [I, S_max]（bool，True 表示该位置股票有效）
        - price_x: [I, F_p]
        - news_x: [I, F_n]
        - industry_mask: [I]（bool，True 表示该日该行业价格特征可用；新闻可前向填充）
        - industry_tradeable: [I]（bool，True 表示该日该行业成交量/换手可用且 >0，可交易）
        - news_is_ffill: [I]（bool，True 表示该行业新闻来自前向填充而非当日原文）
        - day_tradeable: []（bool，True 表示该日存在至少一个可交易行业；否则视为停牌/休市，不交易）
        - target_ret_next: [I, S_max]（可选，float，该日特征对应“下一交易日收益”监督目标）
        """
        self._ensure_loaded()
        assert self._price_df is not None and self._news_df is not None
        assert self._news_aligned_df is not None
        assert self._industry_ids is not None

        dt64 = self._as_datetime64(date)

        # 基于“该日是否存在 price 行业行”确定行业可用；新闻从对齐表读取（可 ffill）
        price_rows = self._price_df[self._price_df["Date"].values.astype("datetime64[ns]") == dt64]
        news_rows = self._news_aligned_df[
            self._news_aligned_df["Date"].values.astype("datetime64[ns]") == dt64
        ]
        price_map = {int(r["Industry_id"]): r for _, r in price_rows.iterrows()}
        news_map = {int(r["Industry_id"]): r for _, r in news_rows.iterrows()}

        I = int(self._industry_ids.shape[0])

        # 该日各行业股票数量不同，这里取当日最大值作为 S_max（保证张量大小不过度膨胀）
        stock_counts = []
        per_industry_rows: Dict[int, pd.DataFrame] = {}
        for ind in self._industry_ids.tolist():
            sdf = self._industry_stock_dfs[int(ind)]
            rows = sdf[sdf["Date"].values.astype("datetime64[ns]") == dt64]
            rows = rows.sort_values(["StockCode"], kind="mergesort")
            per_industry_rows[int(ind)] = rows
            stock_counts.append(int(rows.shape[0]))
        S_max = int(max(stock_counts)) if stock_counts else 0
        if S_max <= 0:
            raise RuntimeError(f"No stock rows found for date={pd.Timestamp(dt64).date()}.")

        # 先分配 numpy 数组（更快），最后统一转 torch
        Fs = len(self.stock_feature_cols)
        Fp = len(self.price_feature_cols)
        Fn = len(self.news_feature_cols)

        stock_x = np.zeros((I, S_max, Fs), dtype=np.float32)
        stock_mask = np.zeros((I, S_max), dtype=bool)
        target_ret_next = np.zeros((I, S_max), dtype=np.float32)

        price_x = np.zeros((I, Fp), dtype=np.float32)
        news_x = np.zeros((I, Fn), dtype=np.float32)
        industry_mask = np.zeros((I,), dtype=bool)
        industry_tradeable = np.zeros((I,), dtype=bool)
        news_is_ffill = np.zeros((I,), dtype=bool)

        def _is_tradeable_from_price_row(pr: dict) -> bool:
            # 规则：优先使用 turnover_proxy，其次使用 vol_5/vol_10/vol_20；
            # 任一可用值 > 0 则认为可交易，否则视为成交量为 0 不交易。
            candidates = []
            for k in ("turnover_proxy", "vol_5", "vol_10", "vol_20"):
                if k in pr:
                    candidates.append(pr[k])
            vals = []
            for v in candidates:
                try:
                    fv = float(pd.to_numeric(v, errors="coerce"))
                except Exception:
                    fv = float("nan")
                if np.isfinite(fv):
                    vals.append(fv)
            if not vals:
                return False
            return float(np.nanmax(vals)) > 0.0

        for i, ind in enumerate(self._industry_ids.tolist()):
            # 行业层：有价格即可交易；新闻缺失时用对齐表（ffill）或 0 向量
            has_price = ind in price_map
            if has_price:
                industry_mask[i] = True
                pr = price_map[ind]
                price_x[i, :] = _safe_float_frame(pd.DataFrame([pr]), self.price_feature_cols).to_numpy()[0]
                industry_tradeable[i] = _is_tradeable_from_price_row(pr)

            if ind in news_map:
                nr = news_map[ind]
                news_x[i, :] = _safe_float_frame(pd.DataFrame([nr]), self.news_feature_cols).to_numpy()[0]
                if "news_is_ffill" in nr.index:
                    try:
                        news_is_ffill[i] = bool(nr["news_is_ffill"])
                    except Exception:
                        news_is_ffill[i] = False

            # 股票层特征（该行业、该日期）
            rows = per_industry_rows[ind]
            if rows.empty:
                continue
            Xs = _safe_float_frame(rows, self.stock_feature_cols).to_numpy()  # [S_i, Fs]
            s_i = int(Xs.shape[0])
            stock_x[i, :s_i, :] = Xs
            stock_mask[i, :s_i] = True

            if include_target:
                if "target_ret_next" not in rows.columns:
                    raise RuntimeError(
                        "内部错误：缺少 target_ret_next。"
                        "请先调用 load_all()（其会在加载成分股数据时计算目标）。"
                    )
                y = pd.to_numeric(rows["target_ret_next"], errors="coerce").replace([np.inf, -np.inf], np.nan).to_numpy(
                    dtype=np.float32
                )
                # 目标若为 NaN，这里先置 0；训练时应结合 stock_mask（以及 finite mask）将其屏蔽
                y = np.where(np.isfinite(y), y, 0.0).astype(np.float32)
                target_ret_next[i, :s_i] = y

        # 如提供 normalizer，则应用标准化（normalizer 必须仅由训练窗口拟合）
        if normalizer is not None:
            stock_x = (stock_x - normalizer.stock_mean[None, None, :]) / normalizer.stock_std[None, None, :]
            price_x = (price_x - normalizer.price_mean[None, :]) / normalizer.price_std[None, :]
            news_x = (news_x - normalizer.news_mean[None, :]) / normalizer.news_std[None, :]

            # 保持 padding 区域稳定（可选）：将 padding 位置强制回写为 0
            stock_x[~stock_mask] = 0.0

        # 关键：清洗 NaN/inf，避免污染网络与梯度（mask 逻辑保持不变）
        stock_x = np.nan_to_num(stock_x, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32, copy=False)
        price_x = np.nan_to_num(price_x, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32, copy=False)
        news_x = np.nan_to_num(news_x, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32, copy=False)

        # 转为 torch 张量
        sample = {
            "stock_x": torch.from_numpy(stock_x).to(self.device),
            "stock_mask": torch.from_numpy(stock_mask).to(self.device),
            "price_x": torch.from_numpy(price_x).to(self.device),
            "news_x": torch.from_numpy(news_x).to(self.device),
            "industry_mask": torch.from_numpy(industry_mask).to(self.device),
            "industry_tradeable": torch.from_numpy(industry_tradeable).to(self.device),
            "news_is_ffill": torch.from_numpy(news_is_ffill).to(self.device),
            "day_tradeable": torch.tensor(bool(np.any(industry_tradeable & industry_mask)), device=self.device),
        }
        if include_target:
            sample["target_ret_next"] = torch.from_numpy(target_ret_next).to(self.device)

        return sample

    # -------------------------
    # Internal helpers
    # -------------------------
    def _ensure_loaded(self) -> None:
        if (
            not self._industry_stock_dfs
            or self._price_df is None
            or self._news_df is None
            or self._news_aligned_df is None
        ):
            raise RuntimeError("数据尚未加载，请先调用 load_all()。")

    def _infer_feature_columns(self) -> None:
        # 股票层特征列：除标识列外全部保留，并保持稳定顺序
        any_ind = next(iter(self._industry_stock_dfs.keys()))
        sdf = self._industry_stock_dfs[any_ind]
        stock_cols = [c for c in sdf.columns if c not in ("Date", "StockCode", "Industry_id", "target_ret_next")]
        self.stock_feature_cols = stock_cols

        assert self._price_df is not None and self._news_df is not None
        self.price_feature_cols = [c for c in self._price_df.columns if c not in ("Date", "Industry_id")]
        self.news_feature_cols = [c for c in self._news_df.columns if c not in ("Date", "Industry_id")]

    def _build_news_aligned_table(self) -> pd.DataFrame:
        """
        将新闻特征对齐到价格交易日：
        - 默认按行业对新闻特征做前向填充（ffill），填补无新闻交易日
        - 首个新闻出现前的日期保持 NaN（build_sample 中会写成 0）
        - 额外列 news_is_ffill：True 表示该日新闻来自前向填充
        """
        assert self._price_df is not None and self._news_df is not None
        assert self._industry_ids is not None

        price_dates = np.unique(self._price_df["Date"].values.astype("datetime64[ns]"))
        date_index = pd.DatetimeIndex(pd.to_datetime(price_dates))
        frames: List[pd.DataFrame] = []

        for ind in self._industry_ids.tolist():
            sub = self._news_df[self._news_df["Industry_id"] == int(ind)].copy()
            if sub.empty:
                aligned = pd.DataFrame(index=date_index, columns=self.news_feature_cols, dtype=np.float32)
                observed = pd.Series(False, index=date_index)
            else:
                sub = sub.sort_values("Date", kind="mergesort")
                sub = sub.drop_duplicates(subset=["Date"], keep="last")
                sub = sub.set_index("Date")
                feat = _safe_float_frame(sub, self.news_feature_cols)
                observed = pd.Series(True, index=feat.index).reindex(date_index, fill_value=False)
                aligned = feat.reindex(date_index)
                if self.news_ffill:
                    aligned = aligned.ffill(limit=self.news_ffill_limit)

            out = aligned.copy()
            out["Date"] = date_index
            out["Industry_id"] = int(ind)
            # 有填充值、但当日无原始新闻 -> ffill
            has_val = aligned[self.news_feature_cols].notna().any(axis=1)
            out["news_is_ffill"] = has_val.to_numpy() & (~observed.to_numpy())
            frames.append(out.reset_index(drop=True))

        news_aligned = pd.concat(frames, ignore_index=True)
        news_aligned = news_aligned.sort_values(["Date", "Industry_id"], kind="mergesort").reset_index(drop=True)
        return news_aligned

    def _load_all_industry_stock_files(self) -> Dict[int, pd.DataFrame]:
        if not self.industry_dir.exists():
            raise FileNotFoundError(f"Industry directory not found: {self.industry_dir}")

        files = sorted(self.industry_dir.glob(self.industry_pattern))
        if not files:
            raise FileNotFoundError(f"No files matched {self.industry_pattern} under {self.industry_dir}")

        out: Dict[int, pd.DataFrame] = {}
        for fp in files:
            ind = _extract_industry_id_from_filename(fp)
            df = pd.read_csv(fp)
            if "Date" not in df.columns or "StockCode" not in df.columns:
                raise ValueError(f"{fp.name} missing required columns: Date, StockCode")

            df["Date"] = _to_datetime_series(df["Date"])
            df["Industry_id"] = int(ind)

            # 按 Date 再 StockCode 排序，保证对齐稳定可复现
            df = df.sort_values(["Date", "StockCode"], kind="mergesort").reset_index(drop=True)

            # 计算“下一交易日收益”监督目标（按 StockCode 分组）
            # 这里使用 Close 计算：close_{t+1}/close_t - 1
            # 避免直接使用 ret_1 产生“到底是过去收益还是未来收益”的歧义
            if "Close" not in df.columns:
                raise ValueError(f"{fp.name} missing required column for target construction: Close")
            df["Close"] = pd.to_numeric(df["Close"], errors="coerce").replace([np.inf, -np.inf], np.nan)
            df["target_ret_next"] = (
                df.groupby("StockCode", sort=False)["Close"].shift(-1) / df["Close"] - 1.0
            )

            out[int(ind)] = df
        return out

    def _load_industry_price_features(self) -> pd.DataFrame:
        if not self.price_features_path.exists():
            raise FileNotFoundError(f"Industry price features file not found: {self.price_features_path}")
        df = pd.read_csv(self.price_features_path)
        if "Date" not in df.columns or "Industry_id" not in df.columns:
            raise ValueError("industry_price_features.csv missing required columns: Date, Industry_id")
        df["Date"] = _to_datetime_series(df["Date"])
        df["Industry_id"] = pd.to_numeric(df["Industry_id"], errors="coerce").astype("Int64")
        df = df.dropna(subset=["Date", "Industry_id"]).copy()
        df["Industry_id"] = df["Industry_id"].astype(int)
        df = df.sort_values(["Date", "Industry_id"], kind="mergesort").reset_index(drop=True)
        return df

    def _load_industry_news_features(self) -> pd.DataFrame:
        if not self.news_features_path.exists():
            raise FileNotFoundError(f"Industry news features file not found: {self.news_features_path}")
        df = pd.read_csv(self.news_features_path)
        if "Date" not in df.columns or "Industry_id" not in df.columns:
            raise ValueError("industry_news_features.csv missing required columns: Date, Industry_id")
        df["Date"] = _to_datetime_series(df["Date"])
        df["Industry_id"] = pd.to_numeric(df["Industry_id"], errors="coerce").astype("Int64")
        df = df.dropna(subset=["Date", "Industry_id"]).copy()
        df["Industry_id"] = df["Industry_id"].astype(int)
        df = df.sort_values(["Date", "Industry_id"], kind="mergesort").reset_index(drop=True)
        return df

    def _dates_with_stock_rows(self) -> np.ndarray:
        """返回至少存在一只成分股记录的日期（用于过滤空样本日）。"""
        date_sets = []
        for sdf in self._industry_stock_dfs.values():
            date_sets.append(sdf["Date"].values.astype("datetime64[ns]"))
        if not date_sets:
            return np.array([], dtype="datetime64[ns]")
        return np.unique(np.concatenate(date_sets))

    def _compute_available_dates(self, mode: str = "price") -> np.ndarray:
        assert self._price_df is not None and self._news_df is not None
        price_dates = np.unique(self._price_df["Date"].values.astype("datetime64[ns]"))
        news_dates = np.unique(self._news_df["Date"].values.astype("datetime64[ns]"))
        use_mode = str(mode).strip().lower()
        if use_mode == "intersection":
            dates = np.intersect1d(price_dates, news_dates)
        elif use_mode == "union":
            dates = np.union1d(price_dates, news_dates)
        elif use_mode == "price":
            dates = price_dates
        else:
            raise ValueError(f"未知 calendar mode: {mode}")

        # 仅保留有成分股数据的日期，避免 build_sample 因 S_max=0 失败
        stock_dates = self._dates_with_stock_rows()
        dates = np.intersect1d(np.sort(dates), stock_dates)
        return dates

    @staticmethod
    def _as_datetime64(date: str | pd.Timestamp | np.datetime64) -> np.datetime64:
        if isinstance(date, np.datetime64):
            return date.astype("datetime64[ns]")
        return pd.to_datetime(date).normalize().to_datetime64()

    @staticmethod
    def _as_datetime64_array(
        dates: Sequence[np.datetime64] | Sequence[pd.Timestamp] | np.ndarray,
    ) -> np.ndarray:
        if isinstance(dates, np.ndarray) and np.issubdtype(dates.dtype, np.datetime64):
            return dates.astype("datetime64[ns]")
        out = [pd.to_datetime(d).normalize().to_datetime64() for d in dates]
        return np.array(out, dtype="datetime64[ns]")

    @staticmethod
    def _mean_std_ignore_nan(X: np.ndarray, ddof: int = 0, eps: float = 1e-6) -> Tuple[np.ndarray, np.ndarray]:
        """
        忽略 NaN/inf，计算每一列的 mean/std。
        返回 float32。
        """
        X = X.astype(np.float64, copy=False)
        mask = np.isfinite(X)
        X0 = np.where(mask, X, 0.0)
        cnt = mask.sum(axis=0).astype(np.float64)
        mean = (X0.sum(axis=0) / np.maximum(cnt, 1.0)).astype(np.float64)
        var = (X0 * X0).sum(axis=0) / np.maximum(cnt, 1.0) - mean * mean
        if ddof == 1:
            adj = np.where(cnt > 1, cnt / (cnt - 1.0), 1.0)
            var *= adj
        std = np.sqrt(np.maximum(var, 0.0))
        std = np.maximum(std, eps)
        return mean.astype(np.float32), std.astype(np.float32)


if __name__ == "__main__":
    # 最小化 smoke check（不涉及训练）
    loader = MultiModalIndustryDataLoader(device="auto")
    loader.load_all()
    dates = loader.available_dates()
    print(
        f"Loaded industries={loader.industry_ids().tolist()} "
        f"dates={len(dates)} mode={loader.calendar_mode} "
        f"from {dates[0]} to {dates[-1]}"
    )
    # 2015 覆盖应接近全年交易日
    n_2015 = int(np.sum((dates >= np.datetime64("2015-01-01")) & (dates <= np.datetime64("2015-12-31"))))
    print(f"2015 trading days under calendar_mode={loader.calendar_mode}: {n_2015}")
    # 构建首个可用日期的单日样本（个别行业在该日可能无成分股数据，会被 mask 掉）
    s = loader.build_sample(dates[0], normalizer=None, include_target=True)
    print({k: tuple(v.shape) for k, v in s.items() if hasattr(v, "shape")})
