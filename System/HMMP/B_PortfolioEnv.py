"""
B_PortfolioEnv.py
- reset()：回到窗口第一个交易日，返回当日观测（与 B_DataLoader.build_sample 一致）
- step(policy_output)：用策略输出的权重计算 reward，并前进到下一交易日

观测为张量字典；动作由策略网络在 B_Train 中生成后传入 step。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F

from B_DataLoader import MultiModalIndustryDataLoader, NormalizerState


def turnover_penalty(
    w_now: torch.Tensor,  # [I, S]
    w_prev: Optional[torch.Tensor],  # [I, S] or None
    eff_mask: torch.Tensor,  # [I, S] bool
    cash_now: Optional[torch.Tensor] = None,   # [] or [1] scalar
    cash_prev: Optional[torch.Tensor] = None,  # [] or [1] scalar
) -> torch.Tensor:
    """
    计算换手惩罚（标量）：
      to = 0.5 * sum |w_now - w_prev|
    若 w_prev=None，则返回 0。
    """
    if w_prev is None:
        return torch.zeros((), device=w_now.device, dtype=w_now.dtype)

    if w_prev.ndim != 2 or w_now.ndim != 2:
        raise ValueError("turnover_penalty 期望 w_prev/w_now 为二维张量 [I, S]。")
    if w_prev.shape[0] != w_now.shape[0]:
        raise ValueError("w_prev 与 w_now 的行业维度 I 不一致。")
    if w_prev.shape[1] != w_now.shape[1]:
        s_now = int(w_now.shape[1])
        s_prev = int(w_prev.shape[1])
        s = max(s_now, s_prev)
        if s_now < s:
            w_now = F.pad(w_now, pad=(0, s - s_now), mode="constant", value=0.0)
            eff_mask = F.pad(eff_mask, pad=(0, s - s_now), mode="constant", value=False)
        if s_prev < s:
            w_prev = F.pad(w_prev, pad=(0, s - s_prev), mode="constant", value=0.0)

    diff = (w_now - w_prev).abs()
    diff = torch.where(eff_mask, diff, torch.zeros_like(diff))
    to = 0.5 * diff.sum()

    if cash_now is not None and cash_prev is not None:
        cash_now = cash_now.reshape(())
        cash_prev = cash_prev.reshape(())
        if torch.isfinite(cash_now) and torch.isfinite(cash_prev):
            to = to + 0.5 * (cash_now - cash_prev).abs()
    return to


def portfolio_return_from_sample(
    w_stock_final: torch.Tensor,
    target_ret_next: torch.Tensor,
    stock_mask: torch.Tensor,
    industry_mask: torch.Tensor,
) -> torch.Tensor:
    """下一交易日组合收益：sum(w * r_{t+1})，无效位置由 mask 屏蔽。"""
    eff = stock_mask & industry_mask.unsqueeze(-1)
    y = torch.where(torch.isfinite(target_ret_next), target_ret_next, torch.zeros_like(target_ret_next))
    return (w_stock_final * y * eff.to(w_stock_final.dtype)).sum()


def industry_returns_from_sample(
    w_stock_final: torch.Tensor,
    w_stock_intra: torch.Tensor,
    target_ret_next: torch.Tensor,
    stock_mask: torch.Tensor,
    industry_mask: torch.Tensor,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """
    按行业分解收益（与训练/回测同一口径：target_ret_next = 下一日个股 Close 收益）。

    返回（均为 [I]）：
    - intra_return:   sum_j w_intra_ij * r_ij        行业内选股收益
    - contrib:        sum_j w_final_ij * r_ij         对组合的总贡献
    - equal_weight:   mean_j r_ij                     等权基准（成分股算术平均）
    """
    eff = stock_mask & industry_mask.unsqueeze(-1)
    y = torch.where(torch.isfinite(target_ret_next), target_ret_next, torch.zeros_like(target_ret_next))
    y = y * eff.to(y.dtype)

    w_fin = w_stock_final * eff.to(w_stock_final.dtype)
    w_intra = w_stock_intra * eff.to(w_stock_intra.dtype)

    intra_return = (w_intra * y).sum(dim=-1)
    contrib = (w_fin * y).sum(dim=-1)
    n_stocks = eff.sum(dim=-1).clamp_min(1).to(y.dtype)
    equal_weight = y.sum(dim=-1) / n_stocks
    return intra_return, contrib, equal_weight


@dataclass
class PortfolioEnvConfig:
    reward_scale: float = 1.0
    lambda_turnover: float = 0.0
    # absolute: 优化绝对组合收益
    # excess_ew: 优化相对「行业等权均线」的超额收益（对齐画图绿线口径的近似）
    reward_mode: str = "absolute"


def equal_industry_benchmark_return(
    target_ret_next: torch.Tensor,
    stock_mask: torch.Tensor,
    industry_mask: torch.Tensor,
) -> torch.Tensor:
    """
    行业等权基准日收益：
      先对每个行业内有效股票取等权均值，再对有效行业取等权均值。
    与 Draw 中 Equal Industry Benchmark 的“行业均线再等权”思路一致（收益序列来自个股 next-day Close）。
    """
    _, _, bench_ind = industry_returns_from_sample(
        w_stock_final=torch.zeros_like(target_ret_next),
        w_stock_intra=torch.zeros_like(target_ret_next),
        target_ret_next=target_ret_next,
        stock_mask=stock_mask,
        industry_mask=industry_mask,
    )
    m = industry_mask.to(bench_ind.dtype)
    denom = m.sum().clamp_min(1.0)
    return (bench_ind * m).sum() / denom


class PortfolioEnv:
    """
    按交易日推进的序列环境。

    典型用法（训练循环在外部调用 model）：
        env = PortfolioEnv(loader, train_dates, normalizer, device, cfg=...)
        obs, info = env.reset()
        while not info.get("terminated", False):
            out = model(...)
            obs, reward, terminated, truncated, info = env.step(out)
    """

    def __init__(
        self,
        loader: MultiModalIndustryDataLoader,
        dates: np.ndarray,
        normalizer: NormalizerState,
        device: torch.device | str,
        cfg: Optional[PortfolioEnvConfig] = None,
    ) -> None:
        self.loader = loader
        self.dates = np.asarray(dates, dtype="datetime64[ns]")
        self.normalizer = normalizer
        self.device = torch.device(device)
        self.cfg = cfg or PortfolioEnvConfig()

        self._t = 0
        self._obs: Optional[Dict[str, torch.Tensor]] = None
        self._w_prev: Optional[torch.Tensor] = None
        self._cash_prev: Optional[torch.Tensor] = None
        self._last_bench: Optional[torch.Tensor] = None
        self._last_excess: Optional[torch.Tensor] = None

    @property
    def num_steps(self) -> int:
        return int(len(self.dates))

    @property
    def w_prev(self) -> Optional[torch.Tensor]:
        return self._w_prev

    @property
    def cash_prev(self) -> Optional[torch.Tensor]:
        return self._cash_prev

    def current_date(self) -> np.datetime64:
        return self.dates[self._t]

    def _load_obs(self, t: int) -> Dict[str, torch.Tensor]:
        return self.loader.build_sample(
            self.dates[t],
            normalizer=self.normalizer,
            include_target=True,
        )

    @staticmethod
    def day_tradeable(sample: Dict[str, torch.Tensor]) -> bool:
        return bool(sample.get("day_tradeable", torch.tensor(True)).detach().cpu().item())

    def effective_mask(self, sample: Dict[str, torch.Tensor]) -> torch.Tensor:
        return sample["stock_mask"] & sample["industry_mask"].unsqueeze(-1)

    def _info_base(self, sample: Dict[str, torch.Tensor]) -> Dict[str, Any]:
        return {
            "date": pd.Timestamp(self.current_date()).strftime("%Y-%m-%d"),
            "step": self._t + 1,
            "num_steps": self.num_steps,
            "day_tradeable": self.day_tradeable(sample),
            "terminated": False,
            "truncated": False,
        }

    def reset(
        self,
        *,
        seed: Optional[int] = None,
    ) -> Tuple[Dict[str, torch.Tensor], Dict[str, Any]]:
        if seed is not None:
            np.random.seed(seed)
            torch.manual_seed(seed)
        self._t = 0
        self._w_prev = None
        self._cash_prev = None
        self._obs = self._load_obs(0)
        info = self._info_base(self._obs)
        info["terminated"] = self.num_steps == 0
        return self._obs, info

    def _reward_components(
        self,
        policy_output: Dict[str, torch.Tensor],
        sample: Dict[str, torch.Tensor],
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        返回 (reward, portfolio_return, turnover)。
        absolute : reward = scale * (r_port - λ * turnover)
        excess_ew: reward = scale * ((r_port - r_ew) - λ * turnover)
        """
        w = policy_output["w_stock_final"]
        tradeable = self.day_tradeable(sample)
        if (not tradeable) and (self._w_prev is not None):
            zero = torch.zeros((), device=w.device, dtype=w.dtype)
            return zero, zero, zero

        r = portfolio_return_from_sample(
            w_stock_final=w,
            target_ret_next=sample["target_ret_next"],
            stock_mask=sample["stock_mask"],
            industry_mask=sample["industry_mask"],
        )
        cash_now = policy_output.get("w_cash")
        to = turnover_penalty(
            w,
            self._w_prev,
            self.effective_mask(sample),
            cash_now=cash_now,
            cash_prev=self._cash_prev,
        )

        mode = str(getattr(self.cfg, "reward_mode", "absolute")).strip().lower()
        if mode in {"excess_ew", "excess", "relative_ew"}:
            bench = equal_industry_benchmark_return(
                target_ret_next=sample["target_ret_next"],
                stock_mask=sample["stock_mask"],
                industry_mask=sample["industry_mask"],
            )
            pnl = r - bench
        else:
            bench = torch.zeros((), device=r.device, dtype=r.dtype)
            pnl = r

        raw = pnl - float(self.cfg.lambda_turnover) * to
        reward = (float(self.cfg.reward_scale) * raw).reshape(())
        # 附加到 tensor 上不便；step() 里用 info 记录 bench
        reward = reward.reshape(())
        self._last_bench = bench.detach().reshape(())
        self._last_excess = (r - bench).detach().reshape(())
        return reward, r.reshape(()), to.reshape(())

    def compute_reward(
        self,
        policy_output: Dict[str, torch.Tensor],
        sample: Optional[Dict[str, torch.Tensor]] = None,
    ) -> torch.Tensor:
        obs = sample if sample is not None else self._obs
        if obs is None:
            raise RuntimeError("环境尚未 reset，或缺少当日观测。")
        reward, _, _ = self._reward_components(policy_output, obs)
        return reward

    def _commit_weights(self, policy_output: Dict[str, torch.Tensor]) -> None:
        self._w_prev = policy_output["w_stock_final"].detach()
        cash = policy_output.get("w_cash")
        self._cash_prev = cash.detach() if cash is not None else None

    def step(
        self,
        policy_output: Dict[str, torch.Tensor],
    ) -> Tuple[Optional[Dict[str, torch.Tensor]], torch.Tensor, bool, bool, Dict[str, Any]]:
        """
        参数：
        - policy_output: 模型 forward 输出

        返回：
        - next_obs, reward, terminated, truncated, info
        """
        if self._obs is None:
            raise RuntimeError("请先调用 reset()。")

        sample = self._obs
        reward, portfolio_return, turnover = self._reward_components(policy_output, sample)
        if self.day_tradeable(sample) or self._w_prev is None:
            self._commit_weights(policy_output)
        info = self._info_base(sample)
        info["portfolio_return"] = float(portfolio_return.detach().cpu().item())
        info["turnover"] = float(turnover.detach().cpu().item())
        bench = getattr(self, "_last_bench", None)
        excess = getattr(self, "_last_excess", None)
        info["benchmark_return"] = float(bench.detach().cpu().item()) if bench is not None else 0.0
        info["excess_return"] = (
            float(excess.detach().cpu().item())
            if excess is not None
            else info["portfolio_return"]
        )
        info["raw_reward"] = float(
            (info["excess_return"] if str(getattr(self.cfg, "reward_mode", "absolute")).lower().startswith("excess")
             else info["portfolio_return"])
            - float(self.cfg.lambda_turnover) * info["turnover"]
        )
        info["raw_return"] = info["portfolio_return"]
        info["reward_mode"] = str(getattr(self.cfg, "reward_mode", "absolute"))

        self._t += 1
        terminated = self._t >= self.num_steps
        info["terminated"] = terminated
        info["truncated"] = False

        if terminated:
            self._obs = None
            return None, reward, True, False, info

        self._obs = self._load_obs(self._t)
        return self._obs, reward, False, False, info


if __name__ == "__main__":
    from B_DataLoader import MultiModalIndustryDataLoader

    loader = MultiModalIndustryDataLoader(device="cpu")
    loader.load_all()
    dates = loader.available_dates(intersection=True)
    n_train = max(1, int(np.floor(0.7 * len(dates))))
    train_dates = dates[:n_train]
    normalizer = loader.fit_normalizer(train_dates)

    env = PortfolioEnv(
        loader,
        train_dates[:5],
        normalizer,
        "cpu",
        cfg=PortfolioEnvConfig(reward_scale=1.0),
    )
    obs, info = env.reset()
    print("reset:", info)
    steps = 0
    while not info["terminated"]:
        I, S = obs["stock_x"].shape[:2]
        w = torch.zeros((I, S), device=obs["stock_x"].device)
        eff = env.effective_mask(obs)
        w = torch.where(eff, torch.ones_like(w), w)
        denom = w.sum().clamp_min(1e-12)
        w = w / denom
        obs, rew, term, trunc, info = env.step({"w_stock_final": w, "w_cash": torch.zeros((), device=w.device)})
        steps += 1
        print(f"step {steps}:", info.get("date"), "reward=", float(rew))
        if term:
            break
    print("done, steps=", steps)
