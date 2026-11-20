"""
B_Train.py

Walk-forward / 固定切分 训练与回测脚本：
 - 使用 B_DataLoader / B_Model / B_PortfolioEnv / B_WalkForward
 - MAPPO（集中式 critic + PPO-clip）训练；策略头可选 MoE 专家混合（含负载均衡辅助损失）
 - 熵正则系数自适应：随训练轮次衰减，并按训练结果（valid Sharpe / reward）反馈调整
 - 默认 split_mode=fixed：训练集 = [train_start_date, train_end_date]（默认 2011-01-01 ~ 2020-06-16，
   含端点），其余日期全部作为测试集；train_end_date=None 时回退按 train_ratio 比例切分
 - 可选 split_mode=walk_forward：每窗 Train→Valid→Test，Valid Sharpe 选模
 - 输出：Results/ 下保存每日收益、权重、指标汇总与 best checkpoint
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F

from B_DataLoader import MultiModalIndustryDataLoader, NormalizerState, resolve_device
from B_Model import HierarchicalPortfolioModel, INTRA_WEIGHT_DECIMALS, WEIGHT_DECIMALS
from B_PortfolioEnv import (
    PortfolioEnv,
    PortfolioEnvConfig,
    industry_returns_from_sample,
    portfolio_return_from_sample,
)
from B_WalkForward import (
    generate_walk_forward_windows,
    pretty_print_windows,
    validate_walk_forward_windows,
    coverage_report,
)


# ----------------------------
# 可复现性 / 随机种子
# ----------------------------
def set_global_seed(seed: int) -> None:
    import random

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    # 尽量确定性（会稍慢；对研究复现更友好）
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


# ----------------------------
# 指标与工具函数
# ----------------------------
def annualized_return(daily_returns: np.ndarray, trading_days: int = 252) -> float:
    daily_returns = np.asarray(daily_returns, dtype=np.float64)
    if daily_returns.size == 0:
        return float("nan")
    equity = np.cumprod(1.0 + daily_returns)
    total = float(equity[-1])
    years = daily_returns.size / float(trading_days)
    if years <= 0:
        return float("nan")
    return total ** (1.0 / years) - 1.0


def sharpe_ratio(daily_returns: np.ndarray, trading_days: int = 252, eps: float = 1e-12) -> float:
    r = np.asarray(daily_returns, dtype=np.float64)
    if r.size == 0:
        return float("nan")
    mu = float(np.mean(r))
    sd = float(np.std(r, ddof=0))
    if sd < eps:
        return 0.0
    return float((mu / sd) * np.sqrt(trading_days))


def max_drawdown(daily_returns: np.ndarray) -> float:
    r = np.asarray(daily_returns, dtype=np.float64)
    if r.size == 0:
        return float("nan")
    equity = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    return float(np.min(dd))


def compute_turnover_from_weights(
    weights_long: pd.DataFrame,
    date_col: str = "Date",
    asset_col: str = "Asset",
    weight_col: str = "Weight",
) -> pd.Series:
    """
    基于 long-format 权重计算换手：
    turnover_t = 0.5 * sum_i |w_{t,i} - w_{t-1,i}|

    weights_long:
      Date | Asset | Weight
    其中 Asset 建议使用全局唯一标识（例如 StockCode）。
    """
    if weights_long.empty:
        return pd.Series(dtype=float)

    df = weights_long.copy()
    df[date_col] = pd.to_datetime(df[date_col]).dt.normalize()
    df = df.sort_values([date_col, asset_col], kind="mergesort")

    # pivot 到 wide，再 diff（资产可能很多，但窗口级别仍可接受）
    wide = df.pivot_table(index=date_col, columns=asset_col, values=weight_col, aggfunc="sum").fillna(0.0)
    diff = wide.diff().abs().fillna(0.0)
    turnover = 0.5 * diff.sum(axis=1)
    return turnover


class AdaptiveEntropyScheduler:
    """
    自适应熵系数：由“训练轮次”与“训练结果”共同决定。

    1) 轮次项（计划性衰减）：cosine 从 1.0 衰减到 final_ratio，随 epoch 推进由探索转向利用
    2) 结果项（反馈缩放）：跟踪监控指标（valid Sharpe 或 epoch 平均 reward）
       - 指标较历史最好值有提升：scale *= reward_decay（收紧探索，加速收敛）
       - 连续 patience 轮无提升：scale *= stall_boost（放大探索，跳出局部最优/权重塌缩）
       scale 被夹在 [scale_min, scale_max]，避免熵项失控淹没策略梯度

    最终系数 = 基础系数 × 轮次项 × 反馈项。
    """

    def __init__(
        self,
        base_intra: float,
        base_industry: float,
        epochs: int,
        final_ratio: float = 0.2,
        patience: int = 2,
        stall_boost: float = 1.5,
        reward_decay: float = 0.9,
        scale_min: float = 0.2,
        scale_max: float = 3.0,
        improve_tol: float = 1e-4,
        enabled: bool = True,
    ) -> None:
        self.base_intra = float(base_intra)
        self.base_industry = float(base_industry)
        self.epochs = int(max(1, epochs))
        self.final_ratio = float(min(max(final_ratio, 0.0), 1.0))
        self.patience = int(max(1, patience))
        self.stall_boost = float(max(stall_boost, 1.0))
        self.reward_decay = float(min(max(reward_decay, 0.0), 1.0))
        self.scale_min = float(max(scale_min, 1e-6))
        self.scale_max = float(max(scale_max, self.scale_min))
        self.improve_tol = float(improve_tol)
        self.enabled = bool(enabled)

        self.scale = 1.0
        self.best_metric = -float("inf")
        self.stall_count = 0
        self.last_epoch_factor = 1.0

    def _epoch_factor(self, epoch: int) -> float:
        if self.epochs <= 1:
            return 1.0
        progress = float(min(max(epoch, 0), self.epochs - 1)) / float(self.epochs - 1)
        cosine = 0.5 * (1.0 + float(np.cos(np.pi * progress)))
        return self.final_ratio + (1.0 - self.final_ratio) * cosine

    def coefficients(self, epoch: int) -> Tuple[float, float]:
        """返回当前 epoch 使用的 (intra 熵系数, industry 熵系数)。"""
        if not self.enabled:
            return self.base_intra, self.base_industry
        factor = self._epoch_factor(epoch)
        self.last_epoch_factor = factor
        adj = factor * self.scale
        return self.base_intra * adj, self.base_industry * adj

    def update(self, metric: Optional[float]) -> Dict[str, float]:
        """用本轮训练结果更新反馈缩放；metric 为 NaN/None 时视为无提升。"""
        improved = False
        if not self.enabled:
            return {
                "entropy_scale": self.scale,
                "entropy_epoch_factor": self.last_epoch_factor,
                "entropy_stall": float(self.stall_count),
                "entropy_improved": 0.0,
            }

        if metric is not None and np.isfinite(metric):
            m = float(metric)
            if m > self.best_metric + self.improve_tol:
                self.best_metric = m
                improved = True

        if improved:
            self.stall_count = 0
            self.scale *= self.reward_decay
        else:
            self.stall_count += 1
            if self.stall_count >= self.patience:
                self.scale *= self.stall_boost
                self.stall_count = 0
        self.scale = float(min(max(self.scale, self.scale_min), self.scale_max))

        return {
            "entropy_scale": self.scale,
            "entropy_epoch_factor": self.last_epoch_factor,
            "entropy_stall": float(self.stall_count),
            "entropy_improved": 1.0 if improved else 0.0,
        }


# ----------------------------
# 训练配置
# ----------------------------
@dataclass
class TrainConfig:
    # 切分模式：fixed（默认，70%/30%） / walk_forward（滚动）
    split_mode: str = "fixed"

    # walk-forward 参数（仅 split_mode=walk_forward 时使用）
    T_train: int = 250
    T_valid: int = 0  # fixed 默认 0=不占用训练集；walk_forward 建议设为 30
    T_test: int = 30
    step_size: int = 30
    # 最后一窗 test 强制覆盖到样本末日（避免尾部几天被 drop）
    align_end: bool = True
    # True：训练段从样本起点扩展到 valid 前（更充分利用历史）；False：固定长度滚动
    expanding: bool = False

    # 固定切分比例（仅 split_mode=fixed，且未指定 train_end_date 时生效）
    train_ratio: float = 0.70

    # 固定切分的日期边界（仅 split_mode=fixed）：训练集 = [train_start_date, train_end_date]（含端点），
    # 其余日期全部作为测试集。train_end_date=None 时回退为按 train_ratio 比例切分。
    train_start_date: Optional[str] = "2011-01-01"
    train_end_date: Optional[str] = "2020-06-16"

    # 优化超参
    epochs: int = 8
    lr: float =1e-5
    weight_decay: float = 1e-5

    # 损失权重
    lambda_turnover: float = 1e-2

    # Reward 缩放（用于稳定优化尺度）
    reward_scale: float = 1

    # 奖励模式：absolute=绝对收益；excess_ew=相对行业等权均线超额
    reward_mode: str = "absolute"
    # 训练细节
    seed: int = 42
    device: str = "auto"

    # MAPPO / PPO 超参
    gamma: float = 0.95
    gae_lambda: float = 0.95
    ppo_clip: float = 0.1
    ppo_epochs: int = 8
    vf_coef: float = 0.5
    ent_coef: float = 0.005
    ent_coef_intra: float = 0.008
    ent_coef_industry: float = 0.005

    # 熵系数自适应：基线随训练轮次衰减（探索→利用），再按训练结果反馈缩放
    # - ent_adaptive=False 时退化为固定 ent_coef_intra / ent_coef_industry
    # - ent_final_ratio：最后一轮的轮次衰减因子（相对初值）
    # - ent_metric：反馈指标，auto=有 valid 用 valid Sharpe，否则用 epoch 平均 reward
    # - 指标提升 -> 系数乘 ent_reward_decay（更利用）；连续 ent_patience 轮无提升 -> 乘 ent_stall_boost（更探索）
    ent_adaptive: bool = True
    ent_final_ratio: float = 0.2
    ent_metric: str = "auto"
    ent_patience: int = 2
    ent_stall_boost: float = 1.5
    ent_reward_decay: float = 0.9
    ent_scale_min: float = 0.2
    ent_scale_max: float = 3.0
    ent_improve_tol: float = 1e-4

    # MoE（专家混合）：作用于多模态融合头、个股打分头、行业打分头
    use_moe: bool = True
    moe_num_experts: int = 4
    moe_top_k: int = 2
    moe_gate_noise_std: float = 0.0
    # 负载均衡辅助损失权重（避免门控塌缩到单一专家）
    moe_aux_coef: float = 1e-2

    # softmax 温度（>1 更平滑；推理与训练都生效）
    intra_temperature: float = 0.5
    industry_temperature: float = 0.5

    # 行业内 Top-K 选股：每个行业仅保留得分最高的 K 只成分股，其余权重归 0
    intra_top_k: int = 5

    # 跨行业 Top-K 选行业：仅保留得分最高的 K 个行业，其余行业权重归 0
    industry_top_k: int = 5

    # 消融：不做行业选择，每天随机选 3 个行业并等权分配（行业层）
    random_industry_3_equal: bool = False
    # 消融：不做股票选择，在模型选出的 top-3 行业内每天随机选 10 只股票并等权分配（股票层）
    random_stock_10_from_top3_equal: bool = False

    # 权重保存精度（行业/行业内/最终权重均保留 4 位小数，余量计入 CASH）
    weight_decimals: int = WEIGHT_DECIMALS
    intra_weight_decimals: int = INTRA_WEIGHT_DECIMALS

    # 现金权重调节：
    # - cash_logit_bias：预留（当前 cash_head 未接入 forward）
    # - min_cash_weight：现金下限（0 表示不强制）
    # - max_cash_weight：现金上限（默认 0.2，避免长期高现金空仓）
    cash_logit_bias: float = 0.0
    min_cash_weight: float = 0.0
    max_cash_weight: float = 0.2

    # 数据日历：price=价格日为主+新闻ffill；intersection=旧行为（价格∩新闻）
    calendar_mode: str = "price"
    news_ffill: bool = True

    # 输出目录
    results_dir: str = "Results"
    run_name: Optional[str] = None  # None 则自动生成
    # 训练/测试参数保存目录；None 表示使用 {run_dir}/params
    params_dir: Optional[str] = None

    # 调试用：限制最多跑多少个窗口（None 表示跑满）
    max_windows: Optional[int] = None

    # 训练输出：每多少个 step 在终端打印一次 loss（0/None 表示不按 step 打印）
    log_every_steps: int = 100


def _date_range_info(dates: np.ndarray) -> Dict[str, object]:
    if dates.size == 0:
        return {"count": 0, "start": None, "end": None, "dates": []}
    ts = pd.to_datetime(dates)
    return {
        "count": int(dates.size),
        "start": pd.Timestamp(ts[0]).strftime("%Y-%m-%d"),
        "end": pd.Timestamp(ts[-1]).strftime("%Y-%m-%d"),
    }


def _serialize_normalizer(normalizer: NormalizerState) -> Dict[str, object]:
    return {
        "stock_mean": normalizer.stock_mean.tolist(),
        "stock_std": normalizer.stock_std.tolist(),
        "price_mean": normalizer.price_mean.tolist(),
        "price_std": normalizer.price_std.tolist(),
        "news_mean": normalizer.news_mean.tolist(),
        "news_std": normalizer.news_std.tolist(),
        "stock_feature_cols": normalizer.stock_feature_cols,
        "price_feature_cols": normalizer.price_feature_cols,
        "news_feature_cols": normalizer.news_feature_cols,
    }


def _deserialize_normalizer(ns: Dict[str, object]) -> NormalizerState:
    return NormalizerState(
        stock_mean=np.asarray(ns["stock_mean"], dtype=np.float32),
        stock_std=np.asarray(ns["stock_std"], dtype=np.float32),
        price_mean=np.asarray(ns["price_mean"], dtype=np.float32),
        price_std=np.asarray(ns["price_std"], dtype=np.float32),
        news_mean=np.asarray(ns["news_mean"], dtype=np.float32),
        news_std=np.asarray(ns["news_std"], dtype=np.float32),
        stock_feature_cols=list(ns["stock_feature_cols"]),
        price_feature_cols=list(ns["price_feature_cols"]),
        news_feature_cols=list(ns["news_feature_cols"]),
    )


def _metric_mean_std(values: List[float]) -> Dict[str, float]:
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {"mean": float("nan"), "std": float("nan"), "n": 0}
    return {
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0,
        "n": int(arr.size),
    }


def _to_plain(obj: object) -> object:
    """将 numpy / 嵌套结构转为可被 weights_only=True 安全反序列化的纯 Python 类型。"""
    if isinstance(obj, dict):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _torch_load_checkpoint(path: Path | str, map_location) -> Dict[str, object]:
    """加载本项目保存的 checkpoint；优先 weights_only，失败则回退（文件可信）。"""
    try:
        return torch.load(path, map_location=map_location, weights_only=True)
    except Exception as e:
        print(f"[warn] weights_only 加载失败，回退 weights_only=False：{e}")
        return torch.load(path, map_location=map_location, weights_only=False)


def _resolve_params_dir(cfg: TrainConfig, run_dir: Path) -> Path:
    if cfg.params_dir:
        return Path(cfg.params_dir).expanduser().resolve()
    return (run_dir / "params").resolve()


def _save_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


def save_run_params(
    params_dir: Path,
    *,
    cfg: TrainConfig,
    run_dir: Path,
    train_dates: np.ndarray,
    test_dates: np.ndarray,
    window_id: int = 0,
    valid_dates: Optional[np.ndarray] = None,
    model_params: Optional[Dict[str, object]] = None,
    train_metrics: Optional[Dict[str, object]] = None,
    valid_metrics: Optional[Dict[str, object]] = None,
    test_metrics: Optional[Dict[str, object]] = None,
    best_model_path: Optional[str] = None,
    best_epoch: Optional[int] = None,
    cli_args: Optional[Dict[str, object]] = None,
) -> Path:
    """
    将本次训练/测试用到的参数写入 params_dir。
    """
    params_dir.mkdir(parents=True, exist_ok=True)

    _save_json(
        params_dir / "config.json",
        {
            "run_dir": str(run_dir),
            "params_dir": str(params_dir),
            "saved_at": pd.Timestamp.now().isoformat(),
            **cfg.__dict__,
        },
    )

    if cli_args is not None:
        _save_json(params_dir / "cli_args.json", cli_args)

    split_payload: Dict[str, object] = {
        "window_id": window_id,
        "split_mode": str(getattr(cfg, "split_mode", "fixed")),
        "train": _date_range_info(train_dates),
        "test": _date_range_info(test_dates),
    }
    if valid_dates is not None:
        split_payload["valid"] = _date_range_info(valid_dates)
    if str(getattr(cfg, "split_mode", "")) == "fixed":
        if getattr(cfg, "train_end_date", None):
            split_payload["split_by"] = "date"
            split_payload["train_start_date"] = str(cfg.train_start_date)
            split_payload["train_end_date"] = str(cfg.train_end_date)
        else:
            split_payload["split_by"] = "ratio"
            split_payload["train_ratio"] = float(getattr(cfg, "train_ratio", 0.70))
    else:
        split_payload["walk_forward"] = {
            "T_train": cfg.T_train,
            "T_valid": cfg.T_valid,
            "T_test": cfg.T_test,
            "step_size": cfg.step_size,
        }
    _save_json(params_dir / "split_info.json", split_payload)

    if model_params is not None:
        _save_json(params_dir / "model_params.json", model_params)

    train_payload: Dict[str, object] = {
        "window_id": window_id,
        "phase": "train",
        "device": cfg.device,
        "date_range": _date_range_info(train_dates),
        "hyperparameters": {
            "epochs": cfg.epochs,
            "lr": cfg.lr,
            "weight_decay": cfg.weight_decay,
            "lambda_turnover": cfg.lambda_turnover,
            "reward_scale": cfg.reward_scale,
            "gamma": cfg.gamma,
            "gae_lambda": cfg.gae_lambda,
            "ppo_clip": cfg.ppo_clip,
            "ppo_epochs": cfg.ppo_epochs,
            "vf_coef": cfg.vf_coef,
            "ent_coef": cfg.ent_coef,
            "ent_coef_intra": cfg.ent_coef_intra,
            "ent_coef_industry": cfg.ent_coef_industry,
            "ent_adaptive": cfg.ent_adaptive,
            "ent_final_ratio": cfg.ent_final_ratio,
            "ent_metric": cfg.ent_metric,
            "ent_patience": cfg.ent_patience,
            "ent_stall_boost": cfg.ent_stall_boost,
            "ent_reward_decay": cfg.ent_reward_decay,
            "ent_scale_min": cfg.ent_scale_min,
            "ent_scale_max": cfg.ent_scale_max,
            "use_moe": cfg.use_moe,
            "moe_num_experts": cfg.moe_num_experts,
            "moe_top_k": cfg.moe_top_k,
            "moe_gate_noise_std": cfg.moe_gate_noise_std,
            "moe_aux_coef": cfg.moe_aux_coef,
            "intra_temperature": cfg.intra_temperature,
            "industry_temperature": cfg.industry_temperature,
            "intra_top_k": cfg.intra_top_k,
            "industry_top_k": cfg.industry_top_k,
            "cash_logit_bias": cfg.cash_logit_bias,
            "min_cash_weight": cfg.min_cash_weight,
            "max_cash_weight": cfg.max_cash_weight,
            "calendar_mode": cfg.calendar_mode,
            "news_ffill": cfg.news_ffill,
            "weight_decimals": cfg.weight_decimals,
            "intra_weight_decimals": cfg.intra_weight_decimals,
            "seed": cfg.seed,
            "log_every_steps": cfg.log_every_steps,
            "split_mode": cfg.split_mode,
            "T_train": cfg.T_train,
            "T_valid": cfg.T_valid,
            "T_test": cfg.T_test,
            "step_size": cfg.step_size,
        },
    }
    if train_metrics is not None:
        train_payload["metrics"] = train_metrics
    if best_epoch is not None:
        train_payload["best_epoch"] = int(best_epoch)
    _save_json(params_dir / "train_params.json", train_payload)

    if valid_dates is not None or valid_metrics is not None:
        valid_payload: Dict[str, object] = {
            "window_id": window_id,
            "phase": "valid",
            "device": cfg.device,
            "date_range": _date_range_info(valid_dates) if valid_dates is not None else None,
            "selection_metric": "Sharpe",
        }
        if valid_metrics is not None:
            valid_payload["metrics"] = valid_metrics
        if best_epoch is not None:
            valid_payload["best_epoch"] = int(best_epoch)
        _save_json(params_dir / "valid_params.json", valid_payload)

    test_payload: Dict[str, object] = {
        "window_id": window_id,
        "phase": "test",
        "device": cfg.device,
        "date_range": _date_range_info(test_dates),
        "inference": {
            "intra_temperature": cfg.intra_temperature,
            "industry_temperature": cfg.industry_temperature,
            "intra_top_k": cfg.intra_top_k,
            "industry_top_k": cfg.industry_top_k,
            "best_model_path": best_model_path,
            "best_epoch": best_epoch,
        },
    }
    if test_metrics is not None:
        test_payload["metrics"] = test_metrics
    _save_json(params_dir / "test_params.json", test_payload)

    summary: Dict[str, object] = {
        "window_id": window_id,
        "run_dir": str(run_dir),
        "params_dir": str(params_dir),
        "best_model_path": best_model_path,
        "best_epoch": best_epoch,
        "split_mode": cfg.split_mode,
        "train": {"date_range": _date_range_info(train_dates), "metrics": train_metrics},
        "test": {"date_range": _date_range_info(test_dates), "metrics": test_metrics},
    }
    if valid_dates is not None or valid_metrics is not None:
        summary["valid"] = {
            "date_range": _date_range_info(valid_dates) if valid_dates is not None else None,
            "metrics": valid_metrics,
        }
    _save_json(params_dir / "experiment_summary.json", summary)

    print(f"参数文件已保存到: {params_dir}")
    return params_dir


# ----------------------------
# 核心：单窗口训练/评估
# ----------------------------
def _get_window_dates(dates: np.ndarray, w) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    train_dates = dates[w.train_start_idx : w.train_end_idx + 1]
    valid_dates = dates[w.valid_start_idx : w.valid_end_idx + 1]
    test_dates = dates[w.test_start_idx : w.test_end_idx + 1]
    return train_dates, valid_dates, test_dates


def _save_split_eval(
    out_dir: Path,
    prefix: str,
    split_dates_np: np.ndarray,
    eval_out: Dict,
) -> None:
    """将 evaluate_period 输出保存为 CSV（与历史固定切分产物命名兼容）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    daily_df = pd.DataFrame({"Date": pd.to_datetime(split_dates_np), "Return": eval_out["daily_returns"]})
    daily_df["Return"] = pd.to_numeric(daily_df["Return"], errors="coerce").round(6)
    daily_df.to_csv(out_dir / f"{prefix}_daily_returns.csv", index=False, float_format="%.6f")

    eval_out["industry_daily_returns_wide"].reset_index().to_csv(
        out_dir / f"{prefix}_industry_daily_returns.csv",
        index=False,
        float_format="%.6f",
    )
    if "industry_benchmark_returns_wide" in eval_out:
        eval_out["industry_benchmark_returns_wide"].reset_index().to_csv(
            out_dir / f"{prefix}_industry_benchmark_returns.csv",
            index=False,
            float_format="%.6f",
        )
    eval_out["industry_weights_wide"].reset_index().to_csv(
        out_dir / f"{prefix}_industry_weights.csv",
        index=False,
        float_format="%.4f",
    )
    eval_out["stock_intra_weights_long"].to_csv(
        out_dir / f"{prefix}_stock_intra_weights.csv",
        index=False,
        float_format="%.4f",
    )

    intra_dir = out_dir / f"{prefix}_stock_intra_weights_by_industry"
    intra_dir.mkdir(parents=True, exist_ok=True)
    intra_long = eval_out["stock_intra_weights_long"].copy()
    if not intra_long.empty:
        intra_long["Date"] = pd.to_datetime(intra_long["Date"])
        intra_long["Industry_id"] = pd.to_numeric(intra_long["Industry_id"], errors="coerce")
        intra_long = intra_long.dropna(subset=["Industry_id"]).copy()
        intra_long["Industry_id"] = intra_long["Industry_id"].astype(int)
        for ind, g in intra_long.groupby("Industry_id", sort=True):
            g = g.sort_values(["Date", "StockCode"], kind="mergesort")
            g.to_csv(intra_dir / f"industry_{ind}_stock_intra_weights.csv", index=False, float_format="%.4f")


def _round_weight_value(value: float, decimals: int = WEIGHT_DECIMALS) -> float:
    return round(float(value), int(decimals))


def _build_industry_weights_row(
    w_ind: torch.Tensor,
    industry_ids: np.ndarray,
    decimals: int = WEIGHT_DECIMALS,
) -> Dict[str, float]:
    """行业权重保留 decimals 位小数，未分配部分计入 CASH。"""
    ind_weights = {
        str(industry_ids[i]): _round_weight_value(float(w_ind[i]), decimals)
        for i in range(len(industry_ids))
    }
    invested = sum(ind_weights.values())
    if invested > 1.0:
        scale = 1.0 / invested
        ind_weights = {
            k: _round_weight_value(v * scale, decimals) for k, v in ind_weights.items()
        }
        invested = sum(ind_weights.values())
    return {
        **ind_weights,
        "CASH": _round_weight_value(max(0.0, 1.0 - invested), decimals),
    }


def _build_weights_long_for_one_date(
    loader: MultiModalIndustryDataLoader,
    date64: np.datetime64,
    w_stock_final: np.ndarray,  # [I, S_max] padded weights
    stock_mask: np.ndarray,  # [I, S_max] bool
    industry_ids: np.ndarray,  # [I]
    decimals: int = WEIGHT_DECIMALS,
) -> pd.DataFrame:
    """
    将单日 padded 权重展开为 long-format，并尽量带上 StockCode。
    输出列：Date, Industry_id, StockCode, Asset, Weight
    """
    rows = []
    dt = pd.Timestamp(date64).normalize()

    # 访问 loader 内部缓存（不额外复杂化 DataLoader 抽象；后续可再封装成公开方法）
    for i, ind in enumerate(industry_ids.tolist()):
        sdf = loader._industry_stock_dfs[int(ind)]  # noqa: SLF001
        day_rows = sdf[sdf["Date"].values.astype("datetime64[ns]") == date64].sort_values(["StockCode"], kind="mergesort")
        codes = day_rows["StockCode"].astype(str).tolist()

        # 对应有效股票数量
        s_i = int(stock_mask[i].sum())
        codes = codes[:s_i]

        for j in range(s_i):
            w = _round_weight_value(float(w_stock_final[i, j]), decimals)
            if w == 0.0:
                continue
            code = codes[j]
            rows.append(
                {
                    "Date": dt,
                    "Industry_id": int(ind),
                    "StockCode": code,
                    "Asset": code,
                    "Weight": w,
                }
            )

    return pd.DataFrame(rows)

def _build_intra_weights_long_for_one_date(
    loader: MultiModalIndustryDataLoader,
    date64: np.datetime64,
    w_stock_intra: np.ndarray,  # [I, S_max] padded intra weights
    stock_mask: np.ndarray,  # [I, S_max] bool
    industry_ids: np.ndarray,  # [I]
    decimals: int = INTRA_WEIGHT_DECIMALS,
) -> pd.DataFrame:
    """
    将单日 padded “行业内权重”展开为 long-format。
    输出列：Date, Industry_id, StockCode, IntraWeight
    """
    rows = []
    dt = pd.Timestamp(date64).normalize()

    for i, ind in enumerate(industry_ids.tolist()):
        sdf = loader._industry_stock_dfs[int(ind)]  # noqa: SLF001
        day_rows = sdf[sdf["Date"].values.astype("datetime64[ns]") == date64].sort_values(["StockCode"], kind="mergesort")
        codes = day_rows["StockCode"].astype(str).tolist()
        s_i = int(stock_mask[i].sum())
        codes = codes[:s_i]

        for j in range(s_i):
            w = _round_weight_value(float(w_stock_intra[i, j]), decimals)
            if w == 0.0:
                continue
            rows.append(
                {
                    "Date": dt,
                    "Industry_id": int(ind),
                    "StockCode": codes[j],
                    "IntraWeight": w,
                }
            )

    return pd.DataFrame(rows)


@torch.no_grad()
def evaluate_period(
    loader: MultiModalIndustryDataLoader,
    model: HierarchicalPortfolioModel,
    dates: np.ndarray,
    normalizer: NormalizerState,
    device: torch.device,
    intra_temperature: float = 1.0,
    industry_temperature: float = 1.0,
    intra_top_k: int = 5,
    industry_top_k: int = 5,
    weight_decimals: int = WEIGHT_DECIMALS,
) -> Dict:
    """
    在给定日期区间做逐日推理与回测。
    返回：
    - daily_returns: np.ndarray
    - industry_weights_wide: pd.DataFrame (Date x Industry_id + CASH)
    - industry_daily_returns_wide: 模型行业内选股收益 sum_j w_intra_ij * r_ij
    - industry_benchmark_returns_wide: 等权基准 mean_j r_ij（同批成分股）
    - stock_intra_weights_long: pd.DataFrame (Date, Industry_id, StockCode, IntraWeight)
    - metrics: dict
    """
    model.eval()

    industry_ids = loader.industry_ids()
    I = int(industry_ids.shape[0])

    daily_returns = []
    industry_rows = []
    industry_model_ret_rows = []
    industry_benchmark_ret_rows = []
    intra_long_list = []

    w_prev = None
    w_ind_prev = None
    w_cash_prev = None
    w_intra_prev = None
    for dt64 in dates:
        sample = loader.build_sample(dt64, normalizer=normalizer, include_target=True)
        day_tradeable = bool(sample.get("day_tradeable", torch.tensor(True)).detach().cpu().item())
        stock_mask_t = sample["stock_mask"].to(device)
        industry_mask_t = sample["industry_mask"].to(device)
        target_t = sample["target_ret_next"].to(device)

        if (not day_tradeable) and (w_prev is not None) and (w_ind_prev is not None):
            # 成交量为 0：不交易，当天收益为 0，权重沿用上一交易日
            w_stock_final = w_prev
            w_ind = w_ind_prev
            w_cash = w_cash_prev if w_cash_prev is not None else torch.zeros((), device=device)
            w_intra = w_intra_prev if w_intra_prev is not None else torch.zeros_like(w_stock_final)
            daily_returns.append(0.0)
            model_intra_ret = torch.zeros((I,), device=device, dtype=w_stock_final.dtype)
            bench_ret = torch.zeros((I,), device=device, dtype=w_stock_final.dtype)
        else:
            out = model(
                sample["stock_x"].to(device),
                stock_mask_t,
                sample["price_x"].to(device),
                sample["news_x"].to(device),
                industry_mask_t,
                intra_temperature=intra_temperature,
                industry_temperature=industry_temperature,
                intra_top_k=intra_top_k,
                industry_top_k=industry_top_k,
            )
            w_stock_final = out["w_stock_final"]  # [I,S]
            w_ind = out["w_industry"]  # [I]
            w_cash = out.get("w_cash", torch.zeros((), device=w_ind.device, dtype=w_ind.dtype))
            w_intra = out["w_stock_intra"]

            r = portfolio_return_from_sample(
                w_stock_final=w_stock_final,
                target_ret_next=target_t,
                stock_mask=stock_mask_t,
                industry_mask=industry_mask_t,
            )
            daily_returns.append(float(r.detach().cpu().item()))
            model_intra_ret, _, bench_ret = industry_returns_from_sample(
                w_stock_final=w_stock_final,
                w_stock_intra=w_intra,
                target_ret_next=target_t,
                stock_mask=stock_mask_t,
                industry_mask=industry_mask_t,
            )

        industry_model_ret_rows.append(
            {
                "Date": pd.Timestamp(dt64).normalize(),
                **{
                    str(industry_ids[i]): float(model_intra_ret[i].detach().cpu().item())
                    for i in range(I)
                },
            }
        )
        industry_benchmark_ret_rows.append(
            {
                "Date": pd.Timestamp(dt64).normalize(),
                **{
                    str(industry_ids[i]): float(bench_ret[i].detach().cpu().item())
                    for i in range(I)
                },
            }
        )

        # 行业权重（wide 方便画热力图/分析）
        industry_rows.append(
            {
                "Date": pd.Timestamp(dt64).normalize(),
                **_build_industry_weights_row(w_ind, industry_ids, decimals=weight_decimals),
            }
        )

        # 行业内成分股权重（long）
        w_intra_np = w_intra.detach().cpu().numpy()
        mask_np = sample["stock_mask"].cpu().numpy().astype(bool)
        intra_long_list.append(
            _build_intra_weights_long_for_one_date(
                loader, dt64, w_intra_np, mask_np, industry_ids, decimals=weight_decimals
            )
        )

        # 仅在可交易日更新“上一交易日权重”；不可交易日保持不变
        if day_tradeable or (w_prev is None):
            w_prev = w_stock_final.detach()
            w_ind_prev = w_ind.detach()
            w_cash_prev = w_cash.detach() if w_cash is not None else None
            w_intra_prev = w_intra.detach()

    daily_returns = np.asarray(daily_returns, dtype=np.float64)
    industry_wide = pd.DataFrame(industry_rows).set_index("Date").sort_index()
    industry_ret_wide = (
        pd.DataFrame(industry_model_ret_rows).set_index("Date").sort_index()
        if industry_model_ret_rows
        else pd.DataFrame(columns=["Date"]).set_index("Date")
    )
    industry_benchmark_wide = (
        pd.DataFrame(industry_benchmark_ret_rows).set_index("Date").sort_index()
        if industry_benchmark_ret_rows
        else pd.DataFrame(columns=["Date"]).set_index("Date")
    )
    intra_long = pd.concat(intra_long_list, ignore_index=True) if intra_long_list else pd.DataFrame(
        columns=["Date", "Industry_id", "StockCode", "IntraWeight"]
    )

    # 说明：这里的 turnover 指标仍然基于“最终组合权重”更合理；
    # 但用户当前只要求保存收益/行业权重/行业内权重，因此不再强制计算并保存 turnover 明细。
    turnover = pd.Series(dtype=float)
    metrics = {
        "AnnualReturn": annualized_return(daily_returns),
        "Sharpe": sharpe_ratio(daily_returns),
        "MaxDrawdown": max_drawdown(daily_returns),
        "AvgTurnover": float("nan"),
        "NumDays": int(daily_returns.size),
    }

    return {
        "daily_returns": daily_returns,
        "industry_weights_wide": industry_wide,
        "industry_daily_returns_wide": industry_ret_wide,
        "industry_benchmark_returns_wide": industry_benchmark_wide,
        "stock_intra_weights_long": intra_long,
        "metrics": metrics,
    }


def train_one_window(
    loader: MultiModalIndustryDataLoader,
    train_dates: np.ndarray,
    test_dates: np.ndarray,
    cfg: TrainConfig,
    window_id: int,
    out_dir: Path,
    valid_dates: Optional[np.ndarray] = None,
) -> Dict:
    """
    单窗口训练：
    - 拟合 normalizer（仅 train）
    - 训练若干 epoch
    - 若提供 valid_dates：按 Valid Sharpe 选 best checkpoint；否则保存末轮
    - 用 best checkpoint 在 test 上评估并返回结果
    """
    device = resolve_device(cfg.device)
    cfg.device = str(device)
    print(f"[device] 使用设备: {device}")

    use_valid = valid_dates is not None and int(np.asarray(valid_dates).size) > 0
    if use_valid:
        valid_dates = np.asarray(valid_dates)
        print(
            f"[window {window_id}] train={len(train_dates)} valid={len(valid_dates)} "
            f"test={len(test_dates)}"
        )
    else:
        print(f"[window {window_id}] train={len(train_dates)} test={len(test_dates)} (no valid)")

    # 1) 拟合标准化（只用 train）
    normalizer = loader.fit_normalizer(train_dates)

    # 2) 构建模型
    # 取一个样本来确定维度
    probe = loader.build_sample(train_dates[0], normalizer=normalizer, include_target=False)
    Fs = int(probe["stock_x"].shape[-1])
    Fp = int(probe["price_x"].shape[-1])
    Fn = int(probe["news_x"].shape[-1])
    model_params = {
        "stock_feat_dim": Fs,
        "price_feat_dim": Fp,
        "news_feat_dim": Fn,
        "cash_logit_bias": cfg.cash_logit_bias,
        "min_cash_weight": cfg.min_cash_weight,
        "max_cash_weight": cfg.max_cash_weight,
        "intra_weight_decimals": cfg.intra_weight_decimals,
        "intra_top_k": cfg.intra_top_k,
        "industry_top_k": cfg.industry_top_k,
        "weight_decimals": cfg.weight_decimals,
        "use_moe": bool(cfg.use_moe),
        "moe_num_experts": int(cfg.moe_num_experts),
        "moe_top_k": int(cfg.moe_top_k),
        "moe_gate_noise_std": float(cfg.moe_gate_noise_std),
        "moe_aux_coef": float(cfg.moe_aux_coef),
        "random_industry_3_equal": bool(cfg.random_industry_3_equal),
        "random_stock_10_from_top3_equal": bool(cfg.random_stock_10_from_top3_equal),
    }
    model = HierarchicalPortfolioModel(
        stock_feat_dim=Fs,
        price_feat_dim=Fp,
        news_feat_dim=Fn,
        cash_logit_bias=cfg.cash_logit_bias,
        min_cash_weight=cfg.min_cash_weight,
        max_cash_weight=cfg.max_cash_weight,
        use_moe=bool(cfg.use_moe),
        moe_num_experts=int(cfg.moe_num_experts),
        moe_top_k=int(cfg.moe_top_k),
        moe_gate_noise_std=float(cfg.moe_gate_noise_std),
        random_industry_3_equal=bool(cfg.random_industry_3_equal),
        random_stock_10_from_top3_equal=bool(cfg.random_stock_10_from_top3_equal),
    ).to(device)
    if model.use_moe:
        print(
            f"[model] MoE 已启用：experts={model.moe_num_experts} top_k={model.moe_top_k} "
            f"aux_coef={float(cfg.moe_aux_coef)}"
        )
    else:
        print("[model] MoE 未启用（use_moe=False 或 moe_num_experts<=1），使用单一 MLP 头")
    if bool(cfg.random_industry_3_equal):
        print("[ablation] 行业层：随机 3 行业等权（禁用行业选择头）")
    if bool(cfg.random_stock_10_from_top3_equal):
        print("[ablation] 股票层：top-3 行业内随机 10 只股票等权（禁用股票选择头）")

    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)

    best_path = out_dir / f"best_model_window_{window_id}.pt"
    # 防御：确保 checkpoint 目录存在（避免 cwd 变化或目录被清理导致 torch.save 失败）
    out_dir.mkdir(parents=True, exist_ok=True)
    best_path.parent.mkdir(parents=True, exist_ok=True)

    # 训练日志
    train_log_rows = []
    best_sharpe = -float("inf")
    best_epoch = 0
    best_valid_metrics: Optional[Dict[str, object]] = None

    def _param_norm_l2(m: torch.nn.Module) -> float:
        s = torch.zeros((), device=device)
        for p in m.parameters():
            if p is None:
                continue
            s = s + (p.detach() ** 2).sum()
        return float(torch.sqrt(s).detach().cpu().item())

    def _safe_log(x: torch.Tensor, eps: float = 1e-12) -> torch.Tensor:
        return torch.log(x.clamp_min(eps))

    def _forward_on_sample(sample: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        return model(
            sample["stock_x"].to(device),
            sample["stock_mask"].to(device),
            sample["price_x"].to(device),
            sample["news_x"].to(device),
            sample["industry_mask"].to(device),
            intra_temperature=cfg.intra_temperature,
            industry_temperature=cfg.industry_temperature,
            intra_top_k=cfg.intra_top_k,
            industry_top_k=cfg.industry_top_k,
        )

    def _policy_logp_and_entropy(
        sample: Dict[str, torch.Tensor],
        out_now: Dict[str, torch.Tensor],
        action_intra: torch.Tensor,
        action_ind: torch.Tensor,
        eps: float = 1e-12,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """分层 log_prob：行业内 softmax + 行业层 sigmoid，熵分开返回。"""
        stock_mask_eff = sample["stock_mask"].to(device) & sample["industry_mask"].to(device).unsqueeze(-1)
        industry_mask = sample["industry_mask"].to(device)

        pi_intra = out_now["w_stock_intra"]
        logp_intra = torch.where(
            stock_mask_eff,
            action_intra * _safe_log(pi_intra, eps),
            torch.zeros_like(action_intra),
        ).sum()
        n_intra = stock_mask_eff.sum().clamp_min(1).to(pi_intra.dtype)
        ent_intra = torch.where(
            stock_mask_eff,
            -(pi_intra * _safe_log(pi_intra, eps)),
            torch.zeros_like(pi_intra),
        ).sum() / n_intra

        pi_ind = out_now["w_industry"]
        ind_m = industry_mask.to(pi_ind.dtype)
        logp_ind = (action_ind * _safe_log(pi_ind.clamp_min(eps), eps) * ind_m).sum()
        n_ind = industry_mask.sum().clamp_min(1).to(pi_ind.dtype)
        ent_ind = -(pi_ind * _safe_log(pi_ind.clamp_min(eps), eps) * ind_m).sum() / n_ind

        return logp_intra + logp_ind, ent_intra, ent_ind

    train_env = PortfolioEnv(
        loader,
        train_dates,
        normalizer,
        device,
        cfg=PortfolioEnvConfig(
            reward_scale=float(cfg.reward_scale),
            lambda_turnover=float(cfg.lambda_turnover),
            reward_mode=str(getattr(cfg, "reward_mode", "absolute")),
        ),
    )
    num_steps = train_env.num_steps

    ent_scheduler = AdaptiveEntropyScheduler(
        base_intra=float(cfg.ent_coef_intra),
        base_industry=float(cfg.ent_coef_industry),
        epochs=int(cfg.epochs),
        final_ratio=float(cfg.ent_final_ratio),
        patience=int(cfg.ent_patience),
        stall_boost=float(cfg.ent_stall_boost),
        reward_decay=float(cfg.ent_reward_decay),
        scale_min=float(cfg.ent_scale_min),
        scale_max=float(cfg.ent_scale_max),
        improve_tol=float(cfg.ent_improve_tol),
        enabled=bool(cfg.ent_adaptive),
    )
    ent_metric_mode = str(getattr(cfg, "ent_metric", "auto")).strip().lower()
    if ent_metric_mode == "auto":
        ent_metric_mode = "valid_sharpe" if use_valid else "reward"
    print(
        f"[entropy] adaptive={bool(cfg.ent_adaptive)} metric={ent_metric_mode} "
        f"base_intra={cfg.ent_coef_intra} base_industry={cfg.ent_coef_industry} "
        f"final_ratio={cfg.ent_final_ratio} patience={cfg.ent_patience}"
    )

    for epoch in range(cfg.epochs):
        model.train()
        ent_coef_intra_ep, ent_coef_ind_ep = ent_scheduler.coefficients(epoch)
        rewards_epoch: List[float] = []
        raw_returns_epoch: List[float] = []
        grad_norms_epoch: List[float] = []

        # MAPPO：rollout -> GAE -> PPO-clip 更新（集中式 critic）
        traj_samples: List[Dict[str, torch.Tensor]] = []
        traj_actions_intra: List[torch.Tensor] = []
        traj_actions_ind: List[torch.Tensor] = []
        traj_logp_old: List[torch.Tensor] = []
        traj_values: List[torch.Tensor] = []
        traj_rewards: List[torch.Tensor] = []

        obs, info = train_env.reset()
        t_idx = 0
        while not info["terminated"]:
            t_idx += 1
            sample = obs
            out = _forward_on_sample(sample)

            action_intra = out["w_stock_intra"].detach()
            action_ind = out["w_industry"].detach()
            logp_old, _, _ = _policy_logp_and_entropy(sample, out, action_intra, action_ind)

            traj_samples.append(sample)
            traj_actions_intra.append(action_intra)
            traj_actions_ind.append(action_ind)
            traj_logp_old.append(logp_old.detach().reshape(()))
            traj_values.append(out["value"].detach().reshape(()))

            obs, reward, _, _, info = train_env.step(out)
            traj_rewards.append(reward.detach().reshape(()))
            rewards_epoch.append(float(reward.detach().cpu().item()))
            raw_returns_epoch.append(float(info.get("portfolio_return", 0.0)))

            if int(getattr(cfg, "log_every_steps", 0) or 0) > 0:
                log_every = int(cfg.log_every_steps)
                if (t_idx % log_every == 0) or (t_idx == num_steps):
                    print(
                        f"[train][mappo][rollout] "
                        f"epoch={epoch+1}/{cfg.epochs} step={t_idx}/{num_steps} date={info['date']} "
                        f"reward={float(reward.detach().cpu().item()):.6f} "
                        f"port_ret={float(info.get('portfolio_return', 0.0)):.6f} "
                        f"turnover={float(info.get('turnover', 0.0)):.6f}",
                        flush=True,
                    )

        T = len(traj_rewards)
        rewards = torch.stack(traj_rewards)  # [T]
        values = torch.stack(traj_values)    # [T]

        # bootstrap：末状态 value 置 0
        next_values = torch.cat([values[1:], torch.zeros((1,), device=device, dtype=values.dtype)], dim=0)
        deltas = rewards + float(cfg.gamma) * next_values - values

        adv_list = []
        gae = torch.zeros((), device=device, dtype=values.dtype)
        for t in reversed(range(T)):
            gae = deltas[t] + float(cfg.gamma) * float(cfg.gae_lambda) * gae
            adv_list.append(gae)
        adv = torch.stack(list(reversed(adv_list)))  # [T]
        returns = adv + values  # [T]，value 目标在 advantage 归一化前计算

        adv_std = adv.std(unbiased=False)
        if adv_std > 1e-6:
            adv = (adv - adv.mean()) / adv_std.clamp_min(1e-6)

        # PPO 更新
        last_loss = None
        last_p_loss = None
        last_v_loss = None
        last_ent_intra = None
        last_ent_ind = None
        last_moe_aux = None
        for _ in range(int(cfg.ppo_epochs)):
            p_loss_sum = torch.zeros((), device=device)
            v_loss_sum = torch.zeros((), device=device)
            ent_intra_sum = torch.zeros((), device=device)
            ent_ind_sum = torch.zeros((), device=device)
            moe_aux_sum = torch.zeros((), device=device)

            for t in range(T):
                sample = traj_samples[t]
                out = _forward_on_sample(sample)

                logp_new, ent_intra_new, ent_ind_new = _policy_logp_and_entropy(
                    sample,
                    out,
                    traj_actions_intra[t],
                    traj_actions_ind[t],
                )
                ratio = torch.exp(logp_new.reshape(()) - traj_logp_old[t])
                surr1 = ratio * adv[t]
                surr2 = torch.clamp(ratio, 1.0 - float(cfg.ppo_clip), 1.0 + float(cfg.ppo_clip)) * adv[t]
                p_loss = -torch.min(surr1, surr2)

                v_pred = out["value"].reshape(())
                v_loss = F.mse_loss(v_pred, returns[t])

                p_loss_sum = p_loss_sum + p_loss
                v_loss_sum = v_loss_sum + v_loss
                ent_intra_sum = ent_intra_sum + ent_intra_new.reshape(())
                ent_ind_sum = ent_ind_sum + ent_ind_new.reshape(())
                aux_t = out.get("moe_aux_loss")
                if aux_t is not None:
                    moe_aux_sum = moe_aux_sum + aux_t.reshape(())

            p_loss_mean = p_loss_sum / float(T)
            v_loss_mean = v_loss_sum / float(T)
            ent_intra_mean = ent_intra_sum / float(T)
            ent_ind_mean = ent_ind_sum / float(T)
            moe_aux_mean = moe_aux_sum / float(T)

            last_p_loss = p_loss_mean
            last_v_loss = v_loss_mean
            last_ent_intra = ent_intra_mean
            last_ent_ind = ent_ind_mean
            last_moe_aux = moe_aux_mean
            last_loss = (
                p_loss_mean
                + float(cfg.vf_coef) * v_loss_mean
                - float(ent_coef_intra_ep) * ent_intra_mean
                - float(ent_coef_ind_ep) * ent_ind_mean
                + float(cfg.moe_aux_coef) * moe_aux_mean
            )

            opt.zero_grad(set_to_none=True)
            last_loss.backward()
            gn = torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
            grad_norms_epoch.append(float(gn.detach().cpu().item()) if torch.is_tensor(gn) else float(gn))
            opt.step()

        epoch_losses = [float(last_loss.detach().cpu().item())] if last_loss is not None else []

        train_loss = float(np.mean(epoch_losses)) if epoch_losses else float("nan")
        policy_loss = float(last_p_loss.detach().cpu().item()) if last_p_loss is not None else float("nan")
        value_loss = float(last_v_loss.detach().cpu().item()) if last_v_loss is not None else float("nan")
        entropy_intra = float(last_ent_intra.detach().cpu().item()) if last_ent_intra is not None else float("nan")
        entropy_ind = float(last_ent_ind.detach().cpu().item()) if last_ent_ind is not None else float("nan")
        moe_aux = float(last_moe_aux.detach().cpu().item()) if last_moe_aux is not None else float("nan")
        r_mean = float(np.mean(rewards_epoch)) if rewards_epoch else float("nan")
        r_std = float(np.std(rewards_epoch, ddof=0)) if rewards_epoch else float("nan")
        raw_ret_mean = float(np.mean(raw_returns_epoch)) if raw_returns_epoch else float("nan")
        g_mean = float(np.mean(grad_norms_epoch)) if grad_norms_epoch else float("nan")
        p_norm = _param_norm_l2(model)
        print(
            f"[epoch {epoch+1}/{cfg.epochs}] "
            f"train_loss={train_loss:.6f} policy_loss={policy_loss:.6f} value_loss={value_loss:.6f} "
            f"entropy_intra={entropy_intra:.6f} entropy_ind={entropy_ind:.6f} "
            f"ent_coef_intra={ent_coef_intra_ep:.6f} ent_coef_ind={ent_coef_ind_ep:.6f} "
            f"moe_aux={moe_aux:.6f} "
            f"reward_mean={r_mean:.6f} raw_return_mean={raw_ret_mean:.6f} reward_std={r_std:.6f} "
            f"grad_norm_mean={g_mean:.6f} param_norm={p_norm:.6f}"
        )

        train_log_rows.append(
            {
                "window_id": window_id,
                "epoch": epoch + 1,
                "train_loss": train_loss,
                "policy_loss": policy_loss,
                "value_loss": value_loss,
                "entropy_intra": entropy_intra,
                "entropy_ind": entropy_ind,
                "ent_coef_intra": float(ent_coef_intra_ep),
                "ent_coef_industry": float(ent_coef_ind_ep),
                "moe_aux_loss": moe_aux,
                "reward_mean": r_mean,
                "raw_return_mean": raw_ret_mean,
            }
        )

        ckpt_payload = {
            "window_id": int(window_id),
            "epoch": int(epoch + 1),
            "model_state_dict": model.state_dict(),
            "normalizer_state": _serialize_normalizer(normalizer),
            "config": _to_plain(cfg.__dict__),
        }

        valid_sharpe_epoch = float("nan")
        if use_valid:
            valid_eval = evaluate_period(
                loader,
                model,
                valid_dates,
                normalizer,
                device,
                intra_temperature=cfg.intra_temperature,
                industry_temperature=cfg.industry_temperature,
                intra_top_k=cfg.intra_top_k,
                industry_top_k=cfg.industry_top_k,
                weight_decimals=cfg.weight_decimals,
            )
            vm = {k: _to_plain(v) for k, v in valid_eval["metrics"].items()}
            v_sharpe = float(vm.get("Sharpe", float("nan")))
            valid_sharpe_epoch = v_sharpe
            train_log_rows[-1]["valid_Sharpe"] = v_sharpe
            train_log_rows[-1]["valid_AnnualReturn"] = float(vm.get("AnnualReturn", float("nan")))
            train_log_rows[-1]["valid_MaxDrawdown"] = float(vm.get("MaxDrawdown", float("nan")))
            print(
                f"[valid][window {window_id}] epoch={epoch+1} "
                f"Sharpe={v_sharpe:.4f} AR={vm['AnnualReturn']:.4f} MDD={vm['MaxDrawdown']:.4f}"
            )
            improved = np.isfinite(v_sharpe) and (v_sharpe > best_sharpe)
            if improved or best_epoch == 0:
                best_sharpe = float(v_sharpe) if np.isfinite(v_sharpe) else float(best_sharpe)
                best_epoch = int(epoch + 1)
                best_valid_metrics = dict(vm)
                ckpt_payload["best_valid_sharpe"] = float(best_sharpe)
                ckpt_payload["best_valid_metrics"] = _to_plain(best_valid_metrics)
                torch.save(ckpt_payload, best_path)
                print(f"[checkpoint] window={window_id} 更新 best @ epoch={best_epoch} valid_Sharpe={best_sharpe:.4f}")
        else:
            # 无验证集：每个 epoch 覆盖保存，最终为末轮
            best_epoch = int(epoch + 1)
            torch.save(ckpt_payload, best_path)

        # 熵系数反馈：用本轮训练结果决定下一轮是加大探索还是收紧
        ent_metric_value = valid_sharpe_epoch if ent_metric_mode == "valid_sharpe" else r_mean
        ent_state = ent_scheduler.update(ent_metric_value)
        train_log_rows[-1].update(
            {
                "ent_metric": ent_metric_mode,
                "ent_metric_value": float(ent_metric_value),
                "ent_scale": ent_state["entropy_scale"],
                "ent_epoch_factor": ent_state["entropy_epoch_factor"],
                "ent_improved": ent_state["entropy_improved"],
            }
        )
        if bool(cfg.ent_adaptive):
            next_intra, next_ind = ent_scheduler.coefficients(min(epoch + 1, cfg.epochs - 1))
            print(
                f"[entropy][window {window_id}] epoch={epoch+1} metric({ent_metric_mode})="
                f"{ent_metric_value:.6f} improved={int(ent_state['entropy_improved'])} "
                f"scale={ent_state['entropy_scale']:.3f} "
                f"next_coef_intra={next_intra:.6f} next_coef_ind={next_ind:.6f}"
            )

    # 训练日志落盘
    if train_log_rows:
        pd.DataFrame(train_log_rows).to_csv(out_dir / f"train_log_window_{window_id}.csv", index=False)

    if not best_path.exists():
        raise RuntimeError(f"未找到 checkpoint：{best_path}")

    ckpt = _torch_load_checkpoint(best_path, map_location=device)
    model.load_state_dict(ckpt["model_state_dict"])
    normalizer = _deserialize_normalizer(ckpt["normalizer_state"])
    best_epoch = int(ckpt.get("epoch", best_epoch) or best_epoch)
    if best_valid_metrics is None and "best_valid_metrics" in ckpt:
        best_valid_metrics = dict(ckpt["best_valid_metrics"])

    # ---- test（仅用 best checkpoint）
    test_eval = evaluate_period(
        loader,
        model,
        test_dates,
        normalizer,
        device,
        intra_temperature=cfg.intra_temperature,
        industry_temperature=cfg.industry_temperature,
        intra_top_k=cfg.intra_top_k,
        industry_top_k=cfg.industry_top_k,
        weight_decimals=cfg.weight_decimals,
    )
    test_metrics = {k: _to_plain(v) for k, v in test_eval["metrics"].items()}
    print(
        f"[test][window {window_id}] best_epoch={best_epoch} "
        f"AnnualReturn={test_metrics['AnnualReturn']:.4f} "
        f"Sharpe={test_metrics['Sharpe']:.4f} "
        f"MaxDD={test_metrics['MaxDrawdown']:.4f}"
    )

    # ---- train 段再评估
    train_eval = evaluate_period(
        loader,
        model,
        train_dates,
        normalizer,
        device,
        intra_temperature=cfg.intra_temperature,
        industry_temperature=cfg.industry_temperature,
        intra_top_k=cfg.intra_top_k,
        industry_top_k=cfg.industry_top_k,
        weight_decimals=cfg.weight_decimals,
    )
    train_metrics = {k: _to_plain(v) for k, v in train_eval["metrics"].items()}

    # 立刻写出收益率等产物（避免外层崩溃导致无 CSV）
    _save_split_eval(out_dir, "train", train_dates, train_eval)
    _save_split_eval(out_dir, "test", test_dates, test_eval)
    if use_valid:
        valid_eval_final = evaluate_period(
            loader,
            model,
            valid_dates,
            normalizer,
            device,
            intra_temperature=cfg.intra_temperature,
            industry_temperature=cfg.industry_temperature,
            intra_top_k=cfg.intra_top_k,
            industry_top_k=cfg.industry_top_k,
            weight_decimals=cfg.weight_decimals,
        )
        _save_split_eval(out_dir, "valid", valid_dates, valid_eval_final)
        if best_valid_metrics is None:
            best_valid_metrics = {k: _to_plain(v) for k, v in valid_eval_final["metrics"].items()}

    print(
        f"[save][window {window_id}] 已写入 "
        f"{out_dir / 'train_daily_returns.csv'} , {out_dir / 'test_daily_returns.csv'}"
    )

    return {
        "best_model_path": str(best_path),
        "best_epoch": best_epoch,
        "best_valid_sharpe": float(best_sharpe) if use_valid else float("nan"),
        "valid_metrics": best_valid_metrics,
        "train_eval": train_eval,
        "train_metrics": train_metrics,
        "test_eval": test_eval,
        "test_metrics": test_metrics,
        "model_params": model_params,
        "normalizer": normalizer,
    }


# ----------------------------
# 主入口：walk-forward 实验
# ----------------------------
def run_walk_forward_experiment(cfg: TrainConfig, cli_args: Optional[Dict[str, object]] = None) -> None:
    set_global_seed(cfg.seed)
    device = resolve_device(cfg.device)
    cfg.device = str(device)

    split_mode = str(getattr(cfg, "split_mode", "walk_forward")).strip().lower()
    if split_mode not in {"walk_forward", "fixed"}:
        raise ValueError(f"split_mode 必须是 walk_forward / fixed，收到: {cfg.split_mode}")
    cfg.split_mode = split_mode

    results_root = Path(cfg.results_dir)
    results_root.mkdir(parents=True, exist_ok=True)
    run_name = cfg.run_name
    if run_name is None:
        prefix = "WalkForward_Run" if split_mode == "walk_forward" else "FixedSplit_Run"
        run_name = pd.Timestamp.now().strftime(f"{prefix}_%Y%m%d_%H%M%S")
    run_dir = results_root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    params_dir = _resolve_params_dir(cfg, run_dir)

    loader = MultiModalIndustryDataLoader(
        device=str(device),
        calendar_mode=cfg.calendar_mode,
        news_ffill=cfg.news_ffill,
    )
    loader.load_all()
    dates = loader.available_dates()
    print(
        f"[data] calendar_mode={cfg.calendar_mode} news_ffill={cfg.news_ffill} "
        f"available_dates={len(dates)} split_mode={split_mode}"
    )
    _save_json(run_dir / "config.json", cfg.__dict__)

    window_metrics_rows: List[Dict[str, object]] = []
    stitched_test_frames: List[pd.DataFrame] = []
    stitched_seen_dates: set = set()

    if split_mode == "walk_forward":
        windows = generate_walk_forward_windows(
            dates,
            T_train=int(cfg.T_train),
            T_valid=int(cfg.T_valid),
            T_test=int(cfg.T_test),
            step_size=int(cfg.step_size),
            drop_last=True,
            align_end=bool(getattr(cfg, "align_end", True)),
            expanding=bool(getattr(cfg, "expanding", False)),
        )
        validate_walk_forward_windows(windows, dates, strict_contiguous=True)
        if cfg.max_windows is not None:
            windows = windows[: int(cfg.max_windows)]
        if not windows:
            raise ValueError(
                "未生成任何 walk-forward 窗口，请检查 T_train/T_valid/T_test/step_size 与数据长度。"
            )

        cov = coverage_report(windows, dates)
        print(
            f"Walk-forward: T_train={cfg.T_train} T_valid={cfg.T_valid} "
            f"T_test={cfg.T_test} step={cfg.step_size} "
            f"align_end={getattr(cfg, 'align_end', True)} expanding={getattr(cfg, 'expanding', False)} "
            f"n_windows={len(windows)}"
        )
        print(pretty_print_windows(windows))
        print(
            "[coverage] "
            f"test_covered={cov['test_covered_days']}/{cov['n_dates']} "
            f"never_in_test={cov['never_in_test_days']} "
            f"test_covers_sample_end={cov['test_covers_sample_end']} "
            f"gaps={cov['never_in_test_gaps']}"
        )
        _save_json(run_dir / "coverage_report.json", cov)
        _save_json(
            run_dir / "windows.json",
            [
                {
                    "window_id": w.window_id,
                    "train": [str(w.train_start.date()), str(w.train_end.date())],
                    "valid": [str(w.valid_start.date()), str(w.valid_end.date())],
                    "test": [str(w.test_start.date()), str(w.test_end.date())],
                    "train_days": int(w.train_end_idx - w.train_start_idx + 1),
                    "valid_days": int(w.valid_end_idx - w.valid_start_idx + 1),
                    "test_days": int(w.test_end_idx - w.test_start_idx + 1),
                    "train_idx": [w.train_start_idx, w.train_end_idx],
                    "valid_idx": [w.valid_start_idx, w.valid_end_idx],
                    "test_idx": [w.test_start_idx, w.test_end_idx],
                }
                for w in windows
            ],
        )

        for w in windows:
            train_dates, valid_dates, test_dates = _get_window_dates(dates, w)
            win_dir = run_dir / f"window_{w.window_id:03d}"
            win_dir.mkdir(parents=True, exist_ok=True)
            print(
                f"\n===== Window {w.window_id}/{len(windows)-1} =====\n"
                f"train {pd.Timestamp(train_dates[0]).date()} ~ {pd.Timestamp(train_dates[-1]).date()}\n"
                f"valid {pd.Timestamp(valid_dates[0]).date()} ~ {pd.Timestamp(valid_dates[-1]).date()}\n"
                f"test  {pd.Timestamp(test_dates[0]).date()} ~ {pd.Timestamp(test_dates[-1]).date()}"
            )

            out = train_one_window(
                loader=loader,
                train_dates=train_dates,
                test_dates=test_dates,
                cfg=cfg,
                window_id=int(w.window_id),
                out_dir=win_dir,
                valid_dates=valid_dates,
            )

            # train_one_window 内已落盘；此处再写一次保证外层汇总前文件齐全
            _save_split_eval(win_dir, "train", train_dates, out["train_eval"])
            _save_split_eval(win_dir, "test", test_dates, out["test_eval"])
            save_run_params(
                win_dir / "params",
                cfg=cfg,
                run_dir=win_dir,
                train_dates=train_dates,
                test_dates=test_dates,
                window_id=int(w.window_id),
                valid_dates=valid_dates,
                model_params=out.get("model_params"),
                train_metrics=out.get("train_metrics"),
                valid_metrics=out.get("valid_metrics"),
                test_metrics=out.get("test_metrics"),
                best_model_path=out.get("best_model_path"),
                best_epoch=out.get("best_epoch"),
                cli_args=cli_args,
            )

            tm = out["test_metrics"]
            vm = out.get("valid_metrics") or {}
            window_metrics_rows.append(
                {
                    "window_id": int(w.window_id),
                    "train_start": pd.Timestamp(train_dates[0]).date(),
                    "train_end": pd.Timestamp(train_dates[-1]).date(),
                    "valid_start": pd.Timestamp(valid_dates[0]).date(),
                    "valid_end": pd.Timestamp(valid_dates[-1]).date(),
                    "test_start": pd.Timestamp(test_dates[0]).date(),
                    "test_end": pd.Timestamp(test_dates[-1]).date(),
                    "best_epoch": out.get("best_epoch"),
                    "valid_Sharpe": vm.get("Sharpe", float("nan")),
                    "valid_AnnualReturn": vm.get("AnnualReturn", float("nan")),
                    "valid_MaxDrawdown": vm.get("MaxDrawdown", float("nan")),
                    "test_AnnualReturn": tm["AnnualReturn"],
                    "test_Sharpe": tm["Sharpe"],
                    "test_MaxDrawdown": tm["MaxDrawdown"],
                    "test_AvgTurnover": tm.get("AvgTurnover", float("nan")),
                    "test_NumDays": tm.get("NumDays", len(test_dates)),
                    "best_model_path": out["best_model_path"],
                }
            )
            # 每窗结束后立刻刷新汇总表，中断也不丢指标
            pd.DataFrame(window_metrics_rows).to_csv(run_dir / "window_metrics.csv", index=False)

            # 拼接 OOS 测试收益：重叠日期保留先出现的窗口
            test_df = pd.DataFrame(
                {
                    "Date": pd.to_datetime(test_dates),
                    "Return": out["test_eval"]["daily_returns"],
                    "window_id": int(w.window_id),
                }
            )
            keep_mask = []
            for d in test_df["Date"]:
                key = pd.Timestamp(d).normalize()
                if key in stitched_seen_dates:
                    keep_mask.append(False)
                else:
                    stitched_seen_dates.add(key)
                    keep_mask.append(True)
            stitched_test_frames.append(test_df.loc[keep_mask].copy())

            # 增量写出根目录收益率文件（供 Draw.ipynb / test.py 直接读取）
            oos_partial = pd.concat(stitched_test_frames, ignore_index=True).sort_values("Date")
            oos_partial["Return"] = pd.to_numeric(oos_partial["Return"], errors="coerce")
            oos_partial.to_csv(run_dir / "oos_test_daily_returns.csv", index=False, float_format="%.6f")
            oos_partial[["Date", "Return"]].to_csv(
                run_dir / "test_daily_returns.csv", index=False, float_format="%.6f"
            )
            shutil.copy2(win_dir / "train_daily_returns.csv", run_dir / "train_daily_returns.csv")
            shutil.copy2(
                win_dir / "test_daily_returns.csv",
                run_dir / f"window_{w.window_id:03d}_test_daily_returns.csv",
            )
            print(
                f"[save][root] 已更新 {run_dir / 'test_daily_returns.csv'} "
                f"(OOS days={len(oos_partial)})"
            )
        metrics_df = pd.DataFrame(window_metrics_rows)
        metrics_df.to_csv(run_dir / "window_metrics.csv", index=False)

        summary = {
            "split_mode": "walk_forward",
            "n_windows": int(len(metrics_df)),
            "T_train": cfg.T_train,
            "T_valid": cfg.T_valid,
            "T_test": cfg.T_test,
            "step_size": cfg.step_size,
            "align_end": bool(getattr(cfg, "align_end", True)),
            "expanding": bool(getattr(cfg, "expanding", False)),
            "coverage": cov,
            "test_AnnualReturn": _metric_mean_std(metrics_df["test_AnnualReturn"].tolist()),
            "test_Sharpe": _metric_mean_std(metrics_df["test_Sharpe"].tolist()),
            "test_MaxDrawdown": _metric_mean_std(metrics_df["test_MaxDrawdown"].tolist()),
            "valid_Sharpe": _metric_mean_std(metrics_df["valid_Sharpe"].tolist()),
        }
        _save_json(run_dir / "walkforward_summary.json", summary)
        _save_json(params_dir / "walkforward_summary.json", summary)
        metrics_df.to_csv(params_dir / "window_metrics.csv", index=False)

        print("\n===== Walk-Forward Test 汇总 (mean ± std) =====")
        for key in ("test_AnnualReturn", "test_Sharpe", "test_MaxDrawdown", "valid_Sharpe"):
            s = summary[key]
            print(f"{key}: {s['mean']:.4f} ± {s['std']:.4f} (n={s['n']})")

        if stitched_test_frames:
            oos = pd.concat(stitched_test_frames, ignore_index=True).sort_values("Date")
            oos["Return"] = pd.to_numeric(oos["Return"], errors="coerce")
            oos.to_csv(run_dir / "oos_test_daily_returns.csv", index=False, float_format="%.6f")
            oos_ret = oos["Return"].to_numpy(dtype=np.float64)
            oos_metrics = {
                "AnnualReturn": annualized_return(oos_ret),
                "Sharpe": sharpe_ratio(oos_ret),
                "MaxDrawdown": max_drawdown(oos_ret),
                "NumDays": int(oos_ret.size),
                "CumValue": float(np.cumprod(1.0 + oos_ret)[-1]) if oos_ret.size else float("nan"),
            }
            _save_json(run_dir / "oos_test_metrics.json", oos_metrics)
            print(
                f"[OOS stitched] days={oos_metrics['NumDays']} "
                f"AR={oos_metrics['AnnualReturn']:.4f} "
                f"Sharpe={oos_metrics['Sharpe']:.4f} "
                f"MDD={oos_metrics['MaxDrawdown']:.4f} "
                f"Cum={oos_metrics['CumValue']:.4f}"
            )

        # 顶层 params：记录整体配置与汇总
        _save_json(
            params_dir / "config.json",
            {
                "run_dir": str(run_dir),
                "params_dir": str(params_dir),
                "saved_at": pd.Timestamp.now().isoformat(),
                **cfg.__dict__,
            },
        )
        if cli_args is not None:
            _save_json(params_dir / "cli_args.json", cli_args)
        _save_json(
            params_dir / "experiment_summary.json",
            {
                "split_mode": "walk_forward",
                "run_dir": str(run_dir),
                "walkforward_summary": summary,
                "oos_test_metrics": oos_metrics if stitched_test_frames else None,
            },
        )
        print(f"结果已保存到: {run_dir}")
        return

    # -------------------- fixed 切分（默认）--------------------
    # 优先按日期边界切分（train_end_date 非空）；否则回退按 train_ratio 比例切分
    n = int(len(dates))
    if n < 10:
        raise ValueError(f"可用日期太少，无法稳定切分：n={n}")

    train_ratio = float(getattr(cfg, "train_ratio", 0.70))
    train_start_date = getattr(cfg, "train_start_date", None)
    train_end_date = getattr(cfg, "train_end_date", None)
    use_date_split = bool(train_end_date)

    if use_date_split:
        train_end64 = pd.to_datetime(train_end_date).normalize().to_datetime64()
        in_train = dates <= train_end64
        if train_start_date:
            train_start64 = pd.to_datetime(train_start_date).normalize().to_datetime64()
            in_train = in_train & (dates >= train_start64)
        # 训练区间之外（含 train_end_date 之后、以及 train_start_date 之前）全部作为测试集
        train_dates_full = dates[in_train]
        test_dates = dates[~in_train]
        if train_dates_full.size == 0:
            raise ValueError(
                f"按日期切分后训练集为空：train_start_date={train_start_date} "
                f"train_end_date={train_end_date}，数据范围 "
                f"{pd.Timestamp(dates[0]).date()} ~ {pd.Timestamp(dates[-1]).date()}"
            )
        if test_dates.size == 0:
            raise ValueError(
                f"按日期切分后测试集为空：train_end_date={train_end_date} 晚于数据末日 "
                f"{pd.Timestamp(dates[-1]).date()}"
            )
        train_ratio = float(train_dates_full.size) / float(n)
        print(
            f"[split] 按日期切分：train {pd.Timestamp(train_dates_full[0]).date()} ~ "
            f"{pd.Timestamp(train_dates_full[-1]).date()}（{train_dates_full.size} 日，含 {train_end_date}）"
            f" | test {pd.Timestamp(test_dates[0]).date()} ~ {pd.Timestamp(test_dates[-1]).date()}"
            f"（{test_dates.size} 日）"
        )
    else:
        if not (0.05 < train_ratio < 0.95):
            raise ValueError(f"train_ratio 应在 (0.05, 0.95) 内，收到: {train_ratio}")

        n_train = int(np.floor(train_ratio * n))
        n_test = n - n_train
        if n_train <= 0 or n_test <= 0:
            raise ValueError(f"固定比例切分失败：n_train={n_train}, n_test={n_test}, n={n}")

        # 严格按时间：前 train_ratio 为训练段，后 (1-train_ratio) 为测试段
        train_dates_full = dates[:n_train]
        test_dates = dates[n_train:]

    valid_dates = None
    train_dates = train_dates_full

    # 可选：从训练集末尾切出 valid 仅用于选模（不改变测试集 30%）
    if int(cfg.T_valid) > 0 and len(train_dates_full) > int(cfg.T_valid) + 10:
        valid_dates = train_dates_full[-int(cfg.T_valid) :]
        train_dates = train_dates_full[: -int(cfg.T_valid)]
        print(
            f"Fixed split (chronological, {train_ratio:.0%}/{1.0-train_ratio:.0%}; "
            f"valid={cfg.T_valid}d from train tail): "
            f"train={len(train_dates)} valid={len(valid_dates)} test={len(test_dates)}\n"
            f"  train {pd.Timestamp(train_dates[0]).date()} ~ {pd.Timestamp(train_dates[-1]).date()}\n"
            f"  valid {pd.Timestamp(valid_dates[0]).date()} ~ {pd.Timestamp(valid_dates[-1]).date()}\n"
            f"  test  {pd.Timestamp(test_dates[0]).date()} ~ {pd.Timestamp(test_dates[-1]).date()}"
        )
    else:
        print(
            f"Fixed split (chronological, {train_ratio:.0%}/{1.0-train_ratio:.0%}): "
            f"train={len(train_dates)} test={len(test_dates)}\n"
            f"  train {pd.Timestamp(train_dates[0]).date()} ~ {pd.Timestamp(train_dates[-1]).date()}\n"
            f"  test  {pd.Timestamp(test_dates[0]).date()} ~ {pd.Timestamp(test_dates[-1]).date()}"
        )

    _save_json(
        run_dir / "split_info.json",
        {
            "split_mode": "fixed",
            "split_by": "date" if use_date_split else "ratio",
            "train_start_date": str(train_start_date) if use_date_split else None,
            "train_end_date": str(train_end_date) if use_date_split else None,
            "train_ratio": train_ratio,
            "test_ratio": 1.0 - train_ratio,
            "n_total": n,
            "train": _date_range_info(train_dates),
            "valid": _date_range_info(valid_dates) if valid_dates is not None else None,
            "test": _date_range_info(test_dates),
            "train_full": _date_range_info(train_dates_full),
        },
    )

    window_id = 0
    out = train_one_window(
        loader=loader,
        train_dates=train_dates,
        test_dates=test_dates,
        cfg=cfg,
        window_id=window_id,
        out_dir=run_dir,
        valid_dates=valid_dates,
    )

    tm = out["test_metrics"]
    window_metrics_rows.append(
        {
            "window_id": window_id,
            "train_start": pd.Timestamp(train_dates[0]).date(),
            "train_end": pd.Timestamp(train_dates[-1]).date(),
            "test_start": pd.Timestamp(test_dates[0]).date(),
            "test_end": pd.Timestamp(test_dates[-1]).date(),
            "best_epoch": out.get("best_epoch"),
            "test_AnnualReturn": tm["AnnualReturn"],
            "test_Sharpe": tm["Sharpe"],
            "test_MaxDrawdown": tm["MaxDrawdown"],
            "test_AvgTurnover": tm.get("AvgTurnover", float("nan")),
            "best_model_path": out["best_model_path"],
        }
    )
    pd.DataFrame(window_metrics_rows).to_csv(run_dir / "window_metrics.csv", index=False)

    train_eval = out["train_eval"]
    test_eval = out["test_eval"]
    # train_one_window 内已写过；这里再写保证根目录产物齐全
    _save_split_eval(run_dir, "train", train_dates, train_eval)
    _save_split_eval(run_dir, "test", test_dates, test_eval)

    # All = 完整 70%（train[+valid]）+ Test，便于画全样本曲线
    if valid_dates is not None:
        # 加载 best 模型，对 valid 再评估一次并写入 CSV
        ckpt = _torch_load_checkpoint(out["best_model_path"], map_location=device)
        normalizer = out["normalizer"]
        probe = loader.build_sample(train_dates[0], normalizer=normalizer, include_target=False)
        model = HierarchicalPortfolioModel(
            stock_feat_dim=int(probe["stock_x"].shape[-1]),
            price_feat_dim=int(probe["price_x"].shape[-1]),
            news_feat_dim=int(probe["news_x"].shape[-1]),
            cash_logit_bias=cfg.cash_logit_bias,
            min_cash_weight=cfg.min_cash_weight,
            max_cash_weight=cfg.max_cash_weight,
            use_moe=bool(cfg.use_moe),
            moe_num_experts=int(cfg.moe_num_experts),
            moe_top_k=int(cfg.moe_top_k),
            moe_gate_noise_std=float(cfg.moe_gate_noise_std),
        ).to(device)
        model.load_state_dict(ckpt["model_state_dict"])
        valid_eval = evaluate_period(
            loader,
            model,
            valid_dates,
            normalizer,
            device,
            intra_temperature=cfg.intra_temperature,
            industry_temperature=cfg.industry_temperature,
            intra_top_k=cfg.intra_top_k,
            industry_top_k=cfg.industry_top_k,
            weight_decimals=cfg.weight_decimals,
        )
        _save_split_eval(run_dir, "valid", valid_dates, valid_eval)
        all_dates_np = np.concatenate([train_dates, valid_dates, test_dates])
        all_ret = np.concatenate(
            [
                train_eval["daily_returns"],
                valid_eval["daily_returns"],
                test_eval["daily_returns"],
            ]
        ).astype(np.float64)
        all_ind = pd.concat(
            [
                train_eval["industry_weights_wide"].reset_index(),
                valid_eval["industry_weights_wide"].reset_index(),
                test_eval["industry_weights_wide"].reset_index(),
            ],
            ignore_index=True,
        ).sort_values("Date")
        all_ind_ret = pd.concat(
            [
                train_eval["industry_daily_returns_wide"].reset_index(),
                valid_eval["industry_daily_returns_wide"].reset_index(),
                test_eval["industry_daily_returns_wide"].reset_index(),
            ],
            ignore_index=True,
        ).sort_values("Date")
        all_ind_bench = pd.concat(
            [
                train_eval["industry_benchmark_returns_wide"].reset_index(),
                valid_eval["industry_benchmark_returns_wide"].reset_index(),
                test_eval["industry_benchmark_returns_wide"].reset_index(),
            ],
            ignore_index=True,
        ).sort_values("Date")
        all_intra = pd.concat(
            [
                train_eval["stock_intra_weights_long"],
                valid_eval["stock_intra_weights_long"],
                test_eval["stock_intra_weights_long"],
            ],
            ignore_index=True,
        )
    else:
        all_dates_np = np.concatenate([train_dates, test_dates])
        all_ret = np.concatenate(
            [train_eval["daily_returns"], test_eval["daily_returns"]]
        ).astype(np.float64)
        all_ind = pd.concat(
            [
                train_eval["industry_weights_wide"].reset_index(),
                test_eval["industry_weights_wide"].reset_index(),
            ],
            ignore_index=True,
        ).sort_values("Date")
        all_ind_ret = pd.concat(
            [
                train_eval["industry_daily_returns_wide"].reset_index(),
                test_eval["industry_daily_returns_wide"].reset_index(),
            ],
            ignore_index=True,
        ).sort_values("Date")
        all_ind_bench = pd.concat(
            [
                train_eval["industry_benchmark_returns_wide"].reset_index(),
                test_eval["industry_benchmark_returns_wide"].reset_index(),
            ],
            ignore_index=True,
        ).sort_values("Date")
        all_intra = pd.concat(
            [train_eval["stock_intra_weights_long"], test_eval["stock_intra_weights_long"]],
            ignore_index=True,
        )

    all_daily_df = pd.DataFrame({"Date": pd.to_datetime(all_dates_np), "Return": all_ret})
    all_daily_df.to_csv(run_dir / "all_daily_returns.csv", index=False, float_format="%.6f")
    all_ind.to_csv(run_dir / "all_industry_weights.csv", index=False, float_format="%.4f")
    all_ind_ret.to_csv(run_dir / "all_industry_daily_returns.csv", index=False, float_format="%.6f")
    all_ind_bench.to_csv(run_dir / "all_industry_benchmark_returns.csv", index=False, float_format="%.6f")
    all_intra = all_intra.sort_values(["Date", "Industry_id", "StockCode"], kind="mergesort")
    all_intra.to_csv(run_dir / "all_stock_intra_weights.csv", index=False, float_format="%.4f")

    save_run_params(
        params_dir,
        cfg=cfg,
        run_dir=run_dir,
        train_dates=train_dates,
        test_dates=test_dates,
        window_id=window_id,
        valid_dates=valid_dates,
        model_params=out.get("model_params"),
        train_metrics=out.get("train_metrics"),
        valid_metrics=out.get("valid_metrics"),
        test_metrics=out.get("test_metrics"),
        best_model_path=out.get("best_model_path"),
        best_epoch=out.get("best_epoch"),
        cli_args=cli_args,
    )
    print(
        f"[done] Fixed {train_ratio:.0%}/{1.0-train_ratio:.0%} 完成。\n"
        f"  主结论请看: {run_dir / 'test_daily_returns.csv'}\n"
        f"  训练收益:   {run_dir / 'train_daily_returns.csv'}\n"
        f"  全样本:     {run_dir / 'all_daily_returns.csv'}\n"
        f"结果目录: {run_dir}"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "训练层级组合模型（MAPPO + MoE + 自适应熵；"
            "默认 fixed 按日期切分 2011-01-01~2020-06-16 为训练集，其余为测试集）"
        )
    )
    parser.add_argument(
        "--device",
        type=str,
        default="auto",
        help="训练设备：auto / cpu / cuda / cuda:0（auto：有 GPU 用 cuda:0，否则 cpu）",
    )
    parser.add_argument(
        "--split_mode",
        type=str,
        default="fixed",
        choices=["walk_forward", "fixed"],
        help="切分模式：fixed=按日期切分训练/测试（默认）；walk_forward=滚动窗口",
    )
    parser.add_argument(
        "--train_ratio",
        type=float,
        default=0.70,
        help="fixed 模式下训练集比例（仅在 --train_end_date none 时生效；默认 0.70）",
    )
    parser.add_argument(
        "--train_start_date",
        type=str,
        default=None,
        help="fixed 模式训练集起始日（含，默认 2011-01-01）",
    )
    parser.add_argument(
        "--train_end_date",
        type=str,
        default=None,
        help=(
            "fixed 模式训练集结束日（含，默认 2020-06-16），其后全部为测试集；"
            "传 none 则改用 --train_ratio 比例切分"
        ),
    )
    parser.add_argument("--T_train", type=int, default=250, help="walk-forward 训练窗口长度（交易日）")
    parser.add_argument(
        "--T_valid",
        type=int,
        default=None,
        help="验证集长度（交易日）。fixed 默认 0（不占用 70%% 训练段）；walk_forward 默认 30",
    )
    parser.add_argument("--T_test", type=int, default=30, help="walk-forward 测试窗口长度（交易日）")
    parser.add_argument("--step_size", type=int, default=30, help="walk-forward 滚动步长（交易日）")
    parser.add_argument(
        "--align_end",
        type=int,
        default=1,
        choices=[0, 1],
        help="walk-forward：是否强制最后一窗 test 覆盖到样本末日（1/0，默认 1）",
    )
    parser.add_argument(
        "--expanding",
        type=int,
        default=0,
        choices=[0, 1],
        help="walk-forward：是否使用扩展训练窗（1/0，默认 0）",
    )
    parser.add_argument(
        "--max_windows",
        type=int,
        default=None,
        help="walk-forward：最多训练多少个窗口（调试用；默认跑满）",
    )
    parser.add_argument("--lr", type=float, default=3e-4, help="AdamW 学习率（默认 3e-4）")
    parser.add_argument("--epoch", type=int, default=2, help="训练轮数（epochs），例如 10")
    parser.add_argument("--epochs", type=int, default=None, help="训练轮数（epochs），优先级高于 --epoch")
    parser.add_argument("--run_name", type=str, default=None, help="结果目录名（默认自动生成）")
    parser.add_argument(
        "--params_dir",
        type=str,
        default=None,
        help="训练/测试参数保存目录（默认 {run_dir}/params）",
    )
    parser.add_argument(
        "--industry_temperature",
        type=float,
        default=None,
        help="行业 softmax 温度（越小越尖锐，默认 0.5）",
    )
    parser.add_argument(
        "--intra_temperature",
        type=float,
        default=None,
        help="行业内 softmax 温度（越小越尖锐，默认 0.5）",
    )
    parser.add_argument(
        "--intra_top_k",
        type=int,
        default=None,
        help="行业内 Top-K 选股数量（默认 5）",
    )
    parser.add_argument(
        "--industry_top_k",
        type=int,
        default=None,
        help="跨行业 Top-K 选行业数量（默认 5）",
    )
    parser.add_argument("--cash_logit_bias", type=float, default=None, help="现金 logit 偏置（预留）")
    parser.add_argument("--max_cash_weight", type=float, default=None, help="现金权重上限（默认 0.2）")
    parser.add_argument("--min_cash_weight", type=float, default=None, help="现金权重下限（默认 0.0）")
    parser.add_argument(
        "--calendar_mode",
        type=str,
        default=None,
        choices=["price", "intersection", "union"],
        help="交易日日历：price=价格日+新闻ffill（默认）",
    )
    parser.add_argument(
        "--news_ffill",
        type=int,
        default=None,
        choices=[0, 1],
        help="是否对缺失新闻做行业内前向填充（1/0，默认 1）",
    )
    parser.add_argument(
        "--ent_adaptive",
        type=int,
        default=None,
        choices=[0, 1],
        help="熵系数是否自适应（随轮次衰减 + 按训练结果反馈调整；1/0，默认 1）",
    )
    parser.add_argument(
        "--ent_final_ratio",
        type=float,
        default=None,
        help="自适应熵：末轮的轮次衰减因子（相对初值，默认 0.2）",
    )
    parser.add_argument(
        "--ent_metric",
        type=str,
        default=None,
        choices=["auto", "valid_sharpe", "reward"],
        help="自适应熵的反馈指标（auto=有 valid 用 valid Sharpe，否则用 reward 均值）",
    )
    parser.add_argument(
        "--ent_patience",
        type=int,
        default=None,
        help="自适应熵：连续多少轮无提升就放大熵系数（默认 2）",
    )
    parser.add_argument(
        "--ent_stall_boost",
        type=float,
        default=None,
        help="自适应熵：停滞时的放大倍数（默认 1.5）",
    )
    parser.add_argument(
        "--ent_reward_decay",
        type=float,
        default=None,
        help="自适应熵：指标提升时的收紧倍数（默认 0.9）",
    )
    parser.add_argument(
        "--use_moe",
        type=int,
        default=None,
        choices=[0, 1],
        help="是否启用 MoE 专家混合头（1/0，默认 1）",
    )
    parser.add_argument("--moe_num_experts", type=int, default=None, help="MoE 专家数量（默认 4）")
    parser.add_argument("--moe_top_k", type=int, default=None, help="MoE 每个 token 激活的专家数（默认 2）")
    parser.add_argument(
        "--moe_aux_coef",
        type=float,
        default=None,
        help="MoE 负载均衡辅助损失权重（默认 1e-2）",
    )
    parser.add_argument(
        "--moe_gate_noise_std",
        type=float,
        default=None,
        help="MoE 门控噪声标准差（仅训练期生效，默认 0=关闭）",
    )
    parser.add_argument(
        "--random_industry_3_equal",
        type=int,
        default=None,
        choices=[0, 1],
        help="消融开关：1=不做行业选择，每天随机 3 个行业等权",
    )
    parser.add_argument(
        "--random_stock_10_from_top3_equal",
        type=int,
        default=None,
        choices=[0, 1],
        help="消融开关：1=不做股票选择，在 top-3 行业中随机 10 只股票等权",
    )
    parser.add_argument("--ent_coef", type=float, default=None, help="同时设置 industry 熵系数（兼容旧参数）")
    parser.add_argument("--ent_coef_intra", type=float, default=None, help="行业内熵正则（默认 0.008；增大可减轻过拟合）")
    parser.add_argument("--ent_coef_industry", type=float, default=None, help="跨行业熵正则（默认 0.005）")
    parser.add_argument("--lambda_turnover", type=float, default=None, help="换手惩罚系数（默认 1e-2；增大可降换手）")
    parser.add_argument("--weight_decay", type=float, default=None, help="AdamW weight decay（默认 1e-5）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子（默认 42）")
    parser.add_argument(
        "--reward_mode",
        type=str,
        default=None,
        choices=["absolute", "excess_ew"],
        help="奖励：absolute=绝对收益；excess_ew=相对行业等权均线超额（冲均线用这个）",
    )
    args = parser.parse_args()

    epochs = int(args.epochs) if args.epochs is not None else int(args.epoch)
    split_mode = str(args.split_mode)

    # train_end_date：None=用 TrainConfig 默认（2020-06-16）；"none"/"" =关闭日期切分改用比例
    train_end_date_arg = args.train_end_date
    if train_end_date_arg is not None:
        cleaned = str(train_end_date_arg).strip()
        train_end_date_arg = None if cleaned.lower() in {"none", "null", ""} else cleaned
        date_split_on = train_end_date_arg is not None
    else:
        date_split_on = bool(TrainConfig.train_end_date)

    # fixed + 日期切分：默认不再从训练段尾部切 valid（保证训练集严格等于指定日期区间）
    if args.T_valid is not None:
        t_valid = int(args.T_valid)
    elif split_mode != "fixed":
        t_valid = 30
    else:
        t_valid = 0 if date_split_on else 252

    cfg_kwargs: Dict[str, object] = dict(
        split_mode=split_mode,
        train_ratio=float(args.train_ratio),
        T_train=args.T_train,
        T_valid=t_valid,
        T_test=args.T_test,
        step_size=args.step_size,
        align_end=bool(int(args.align_end)),
        expanding=bool(int(args.expanding)),
        max_windows=args.max_windows,
        epochs=epochs,
        lr=args.lr,
        seed=int(args.seed),
        device=str(args.device),
        results_dir="Results",
        run_name=args.run_name,
        params_dir=args.params_dir,
    )
    if args.industry_temperature is not None:
        cfg_kwargs["industry_temperature"] = float(args.industry_temperature)
    if args.intra_temperature is not None:
        cfg_kwargs["intra_temperature"] = float(args.intra_temperature)
    if args.intra_top_k is not None:
        cfg_kwargs["intra_top_k"] = int(args.intra_top_k)
    if args.industry_top_k is not None:
        cfg_kwargs["industry_top_k"] = int(args.industry_top_k)
    if args.cash_logit_bias is not None:
        cfg_kwargs["cash_logit_bias"] = float(args.cash_logit_bias)
    if args.max_cash_weight is not None:
        cfg_kwargs["max_cash_weight"] = float(args.max_cash_weight)
    if args.min_cash_weight is not None:
        cfg_kwargs["min_cash_weight"] = float(args.min_cash_weight)
    if args.calendar_mode is not None:
        cfg_kwargs["calendar_mode"] = str(args.calendar_mode)
    if args.news_ffill is not None:
        cfg_kwargs["news_ffill"] = bool(int(args.news_ffill))
    if args.lambda_turnover is not None:
        cfg_kwargs["lambda_turnover"] = float(args.lambda_turnover)
    if args.weight_decay is not None:
        cfg_kwargs["weight_decay"] = float(args.weight_decay)
    if args.ent_coef is not None:
        cfg_kwargs["ent_coef"] = float(args.ent_coef)
        cfg_kwargs["ent_coef_industry"] = float(args.ent_coef)
    if args.ent_coef_industry is not None:
        cfg_kwargs["ent_coef_industry"] = float(args.ent_coef_industry)
        cfg_kwargs["ent_coef"] = float(args.ent_coef_industry)
    if args.ent_coef_intra is not None:
        cfg_kwargs["ent_coef_intra"] = float(args.ent_coef_intra)
    if args.reward_mode is not None:
        cfg_kwargs["reward_mode"] = str(args.reward_mode)
    if args.train_start_date is not None:
        cfg_kwargs["train_start_date"] = str(args.train_start_date).strip()
    if args.train_end_date is not None:
        cfg_kwargs["train_end_date"] = train_end_date_arg
    if args.ent_adaptive is not None:
        cfg_kwargs["ent_adaptive"] = bool(int(args.ent_adaptive))
    if args.ent_final_ratio is not None:
        cfg_kwargs["ent_final_ratio"] = float(args.ent_final_ratio)
    if args.ent_metric is not None:
        cfg_kwargs["ent_metric"] = str(args.ent_metric)
    if args.ent_patience is not None:
        cfg_kwargs["ent_patience"] = int(args.ent_patience)
    if args.ent_stall_boost is not None:
        cfg_kwargs["ent_stall_boost"] = float(args.ent_stall_boost)
    if args.ent_reward_decay is not None:
        cfg_kwargs["ent_reward_decay"] = float(args.ent_reward_decay)
    if args.use_moe is not None:
        cfg_kwargs["use_moe"] = bool(int(args.use_moe))
    if args.moe_num_experts is not None:
        cfg_kwargs["moe_num_experts"] = int(args.moe_num_experts)
    if args.moe_top_k is not None:
        cfg_kwargs["moe_top_k"] = int(args.moe_top_k)
    if args.moe_aux_coef is not None:
        cfg_kwargs["moe_aux_coef"] = float(args.moe_aux_coef)
    if args.moe_gate_noise_std is not None:
        cfg_kwargs["moe_gate_noise_std"] = float(args.moe_gate_noise_std)
    if args.random_industry_3_equal is not None:
        cfg_kwargs["random_industry_3_equal"] = bool(int(args.random_industry_3_equal))
    if args.random_stock_10_from_top3_equal is not None:
        cfg_kwargs["random_stock_10_from_top3_equal"] = bool(int(args.random_stock_10_from_top3_equal))

    cfg = TrainConfig(**cfg_kwargs)
    cli_args = {k: v for k, v in vars(args).items() if v is not None}
    run_walk_forward_experiment(cfg, cli_args=cli_args)
