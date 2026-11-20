"""
B_Model.py

最小层级（hierarchical）投资组合模型（PyTorch）：
- 每个行业一个“行业表示”（融合：股票集合 summary + 行业价格特征 + 行业新闻特征）
- 可选 MoE（稀疏门控专家混合）：多模态融合头、个股打分头、行业打分头由多个专家组成，
  按 token（行业 / 个股）稀疏路由到 Top-K 专家，并输出负载均衡辅助损失
- 行业内：对成分股基本面特征打分 -> Top-K 选股（其余权重归 0）-> 按得分 softmax 分配行业内权重（行和=1）
- 跨行业：对所有行业表示输出打分 -> sigmoid -> 行业权重（可为 0，总和可小于 1）
- 现金上下界：max_cash_weight / min_cash_weight 约束行业权重和
- 最终个股权重 = 行业权重 × 行业内权重（保留四位小数）
- 现金权重 = 1 - sum(最终个股权重)（未分配部分全部视为 cash）

设计目标：
1) 易训练、易调试（先不做复杂 MARL / MAPPO）
2) 接口清晰，后续可平滑扩展为 centralized critic / 多智能体训练
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F


WEIGHT_DECIMALS = 2
INTRA_WEIGHT_DECIMALS = 2


def round_weights(x: torch.Tensor, decimals: int = WEIGHT_DECIMALS) -> torch.Tensor:
    factor = 10.0 ** decimals
    return torch.round(x * factor) / factor


def _cap_simplex(
    w: torch.Tensor,
    mask: torch.Tensor,
    dim: int = -1,
    eps: float = 1e-12,
) -> torch.Tensor:
    """将权重限制在 [0,1] 且沿 dim 求和不超过 1（可小于 1，余量留给 cash）。"""
    w = w.clamp(min=0.0) * mask.to(w.dtype)
    total = w.sum(dim=dim, keepdim=True)
    return torch.where(total > 1.0, w / total.clamp_min(eps), w)


def apply_cash_bounds(
    w_industry: torch.Tensor,
    industry_mask: torch.Tensor,
    min_cash_weight: float = 0.0,
    max_cash_weight: float = 1.0,
    eps: float = 1e-12,
) -> torch.Tensor:
    """
    将跨行业权重裁剪到现金上下界：
    - max_cash_weight：现金上限 => 行业权重和 >= 1 - max_cash
    - min_cash_weight：现金下限 => 行业权重和 <= 1 - min_cash
    若当前行业权重全 0 且要求最低投资额 > 0，则在有效行业上均匀分配。
    """
    min_cash = float(max(min_cash_weight, 0.0))
    max_cash = float(min(max(max_cash_weight, 0.0), 1.0))
    if min_cash > max_cash:
        min_cash = max_cash

    w = _cap_simplex(w_industry, industry_mask, dim=-1, eps=eps)
    invested = w.sum(dim=-1, keepdim=True)
    min_invested = 1.0 - max_cash
    max_invested = 1.0 - min_cash

    # 现金过高：放大行业权重
    need_up = invested < min_invested
    scale_up = torch.where(
        need_up & (invested > eps),
        min_invested / invested.clamp_min(eps),
        torch.ones_like(invested),
    )
    w = w * scale_up

    # 全 0 但要求最低仓位：等权铺到有效行业
    invested2 = w.sum(dim=-1, keepdim=True)
    zero_need = (invested2 <= eps) & (min_invested > eps)
    if bool(zero_need.any().item()):
        n_valid = industry_mask.to(w.dtype).sum(dim=-1, keepdim=True).clamp_min(1.0)
        equal = industry_mask.to(w.dtype) / n_valid * min_invested
        w = torch.where(zero_need, equal, w)

    # 现金过低：缩小行业权重
    invested3 = w.sum(dim=-1, keepdim=True)
    need_down = invested3 > max_invested
    scale_down = torch.where(
        need_down,
        max_invested / invested3.clamp_min(eps),
        torch.ones_like(invested3),
    )
    w = w * scale_down
    return _cap_simplex(w, industry_mask, dim=-1, eps=eps)


def discretize_hierarchical_weights(
    w_industry_cont: torch.Tensor,
    w_intra_cont: torch.Tensor,
    stock_mask_eff: torch.Tensor,
    industry_mask: torch.Tensor,
    decimals: int = WEIGHT_DECIMALS,
    intra_decimals: int = INTRA_WEIGHT_DECIMALS,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """
    将连续权重离散化为 decimals 位小数：
    - 行业/行业内权重允许为 0
    - w_stock_final 为绝对组合权重
    - w_cash = 1 - sum(w_stock_final)（余量全部视为现金）
    """
    ind_m = industry_mask.to(w_industry_cont.dtype)
    stk_m = stock_mask_eff.to(w_intra_cont.dtype)

    w_ind = round_weights(w_industry_cont.clamp(min=0.0) * ind_m, decimals)
    w_ind = _cap_simplex(w_ind, industry_mask, dim=-1)
    w_ind = round_weights(w_ind, decimals) * ind_m

    w_in = round_weights(w_intra_cont.clamp(min=0.0) * stk_m, intra_decimals)
    row_sum = w_in.sum(dim=-1, keepdim=True)
    w_in = torch.where(row_sum > 0, w_in / row_sum.clamp_min(1e-12), w_in)
    w_in = round_weights(w_in, intra_decimals) * stk_m

    w_fin = round_weights(w_ind.unsqueeze(-1) * w_in, decimals)
    w_fin = torch.where(stock_mask_eff, w_fin, torch.zeros_like(w_fin))

    invested = w_fin.sum(dim=(-2, -1))
    over = invested > 1.0
    if over.any():
        scale = torch.where(over, 1.0 / invested.clamp_min(1e-12), torch.ones_like(invested))
        w_fin = round_weights(w_fin * scale.view(-1, 1, 1), decimals)
        w_fin = torch.where(stock_mask_eff, w_fin, torch.zeros_like(w_fin))

    w_cash = round_weights((1.0 - w_fin.sum(dim=(-2, -1))).clamp(min=0.0, max=1.0), decimals)

    w_ind = round_weights(w_fin.sum(dim=-1), decimals) * ind_m
    denom = w_ind.unsqueeze(-1).clamp_min(1e-12)
    w_in = torch.where(
        (w_ind.unsqueeze(-1) > 0) & stock_mask_eff,
        round_weights(w_fin / denom, decimals),
        torch.zeros_like(w_fin),
    )
    w_in = torch.where(stock_mask_eff, w_in, torch.zeros_like(w_in))

    return w_ind, w_in, w_fin, w_cash


def straight_through_weights(continuous: torch.Tensor, discrete: torch.Tensor) -> torch.Tensor:
    """前向使用离散权重，反向对连续权重传梯度。"""
    return continuous + (discrete - continuous).detach()


def masked_softmax(
    logits: torch.Tensor,
    mask: torch.Tensor,
    dim: int = -1,
    eps: float = 1e-12,
) -> torch.Tensor:
    """
    带 mask 的 softmax：
    - mask=True 表示有效位置
    - mask=False 的位置输出为 0
    - 若某一行（在 dim 维度上）全为无效，则该行输出全 0（避免 NaN）

    参数：
    - logits: 任意形状张量
    - mask: 与 logits 可 broadcast 的 bool 张量
    - dim: softmax 维度
    """
    if mask.dtype != torch.bool:
        mask = mask.bool()

    # 数值清洗：避免输入特征中的 NaN/inf 经过网络传播后导致 softmax 输出 NaN
    logits = torch.where(torch.isfinite(logits), logits, torch.zeros_like(logits))

    # 将无效位置置为一个很小的负数（而不是 -inf，避免某些混合精度/导出场景不稳定）
    very_neg = torch.finfo(logits.dtype).min
    masked_logits = torch.where(mask, logits, torch.tensor(very_neg, device=logits.device, dtype=logits.dtype))

    # 标准 softmax
    w = torch.softmax(masked_logits, dim=dim)

    # 保险：把无效位置归零
    w = torch.where(mask, w, torch.zeros_like(w))

    # 若某一行全无效，softmax 会变成 uniform 或 NaN（视 very_neg 而定）；这里强制归一到 0
    denom = w.sum(dim=dim, keepdim=True)
    w = torch.where(denom > eps, w / denom, torch.zeros_like(w))
    return w


def masked_topk_sigmoid(
    logits: torch.Tensor,
    mask: torch.Tensor,
    top_k: int,
    temperature: float = 1.0,
    eps: float = 1e-12,
) -> torch.Tensor:
    """
    Top-K 稀疏行业权重（基于 sigmoid）：
    - 仅保留得分最高的 <= top_k 个行业
    - 未选中行业权重为 0
    - 选中行业保留 sigmoid 得分，再 cap 到 simplex <= 1（余量留给 cash）
    - 反向传播：straight-through，梯度经全量 sigmoid 回传
    """
    if mask.dtype != torch.bool:
        mask = mask.bool()

    t = float(max(temperature, 1e-6))
    logits = torch.where(torch.isfinite(logits), logits, torch.zeros_like(logits))
    scores = torch.sigmoid(logits / t) * mask.to(logits.dtype)

    if top_k is None or int(top_k) <= 0:
        return _cap_simplex(scores, mask, dim=-1)

    k = int(top_k)
    very_neg = torch.finfo(scores.dtype).min
    masked_scores = torch.where(mask, scores, torch.full_like(scores, very_neg))
    _, topk_idx = masked_scores.topk(k, dim=-1)
    topk_mask = torch.zeros_like(mask, dtype=torch.bool)
    topk_mask.scatter_(-1, topk_idx, True)
    topk_mask = topk_mask & mask

    w_full = _cap_simplex(scores, mask, dim=-1)
    w_topk = _cap_simplex(scores * topk_mask.to(scores.dtype), mask, dim=-1)
    return straight_through_weights(w_full, w_topk)


def masked_topk_softmax(
    logits: torch.Tensor,
    mask: torch.Tensor,
    top_k: int,
    dim: int = -1,
    eps: float = 1e-12,
) -> torch.Tensor:
    """
    Top-K 稀疏行业内权重：
    - 每个行业仅保留得分最高的 <= top_k 只成分股
    - 未选中股票权重为 0（清仓）
    - 选中股票按得分 softmax 分配（行和=1）
    - 反向传播：straight-through，梯度经全量 masked softmax 回传
    """
    if top_k is None or int(top_k) <= 0:
        return masked_softmax(logits, mask, dim=dim, eps=eps)

    if mask.dtype != torch.bool:
        mask = mask.bool()

    logits = torch.where(torch.isfinite(logits), logits, torch.zeros_like(logits))
    very_neg = torch.finfo(logits.dtype).min / 2
    masked_logits = torch.where(
        mask,
        logits,
        torch.full_like(logits, very_neg),
    )

    k = int(top_k)
    _, topk_idx = masked_logits.topk(k, dim=dim)
    topk_mask = torch.zeros_like(mask, dtype=torch.bool)
    topk_mask.scatter_(dim, topk_idx, True)
    topk_mask = topk_mask & mask

    w_full = masked_softmax(logits, mask, dim=dim, eps=eps)
    w_topk = masked_softmax(logits, topk_mask, dim=dim, eps=eps)
    return straight_through_weights(w_full, w_topk)


def _ensure_batch(x: torch.Tensor, target_dim: int) -> Tuple[torch.Tensor, bool]:
    """
    允许输入既可以是无 batch，也可以是带 batch。
    - 若 x.ndim == target_dim - 1：自动在最前面加 batch=1
    - 返回 (x_with_batch, added_batch_flag)
    """
    if x.ndim == target_dim - 1:
        return x.unsqueeze(0), True
    return x, False


class MLP(nn.Module):
    """简单 MLP：Linear -> (LayerNorm) -> GELU -> Dropout -> ... -> Linear"""

    def __init__(
        self,
        in_dim: int,
        hidden_dim: int,
        out_dim: int,
        num_layers: int = 2,
        dropout: float = 0.0,
        layer_norm: bool = True,
    ) -> None:
        super().__init__()
        if num_layers < 1:
            raise ValueError("num_layers 必须 >= 1")

        layers = []
        d = in_dim
        for li in range(num_layers - 1):
            layers.append(nn.Linear(d, hidden_dim))
            if layer_norm:
                layers.append(nn.LayerNorm(hidden_dim))
            layers.append(nn.GELU())
            if dropout > 0:
                layers.append(nn.Dropout(dropout))
            d = hidden_dim
        layers.append(nn.Linear(d, out_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class MoEFeedForward(nn.Module):
    """
    稀疏门控专家混合（Mixture-of-Experts）：
    - 每个 token（一个行业 / 一只股票）由门控网络打分，路由到 Top-K 个专家
    - 输出 = Top-K 专家输出的门控加权和（门控权重重新归一化，和为 1）
    - 同时返回负载均衡辅助损失（Switch Transformer 口径）：E * Σ_e f_e * P_e
      其中 f_e 为路由到专家 e 的 token 占比，P_e 为专家 e 的平均门控概率；
      完全均衡时该值为 1，越大说明路由越集中在少数专家上。

    说明：专家数量不多、token 数（行业×股票）也有限，这里对全部专家做稠密前向后再
    按路由结果 gather，实现简单且梯度稳定（不做跨设备的稀疏 dispatch）。
    """

    def __init__(
        self,
        in_dim: int,
        hidden_dim: int,
        out_dim: int,
        num_experts: int = 4,
        top_k: int = 2,
        num_layers: int = 2,
        dropout: float = 0.0,
        layer_norm: bool = True,
        gate_noise_std: float = 0.0,
    ) -> None:
        super().__init__()
        if num_experts < 1:
            raise ValueError("num_experts 必须 >= 1")
        self.num_experts = int(num_experts)
        self.top_k = int(max(1, min(top_k, self.num_experts)))
        self.gate_noise_std = float(max(gate_noise_std, 0.0))

        self.experts = nn.ModuleList(
            [
                MLP(
                    in_dim=in_dim,
                    hidden_dim=hidden_dim,
                    out_dim=out_dim,
                    num_layers=num_layers,
                    dropout=dropout,
                    layer_norm=layer_norm,
                )
                for _ in range(self.num_experts)
            ]
        )
        self.gate = nn.Linear(in_dim, self.num_experts)

    def forward(
        self,
        x: torch.Tensor,
        mask: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        输入：
        - x: [..., in_dim]
        - mask: [...]（可选 bool，True 为有效 token；仅用于统计负载均衡，padding 不计入）

        输出：(y [..., out_dim], aux_loss 标量)
        """
        gate_logits = self.gate(x)
        gate_logits = torch.where(torch.isfinite(gate_logits), gate_logits, torch.zeros_like(gate_logits))
        if self.training and self.gate_noise_std > 0:
            gate_logits = gate_logits + torch.randn_like(gate_logits) * self.gate_noise_std

        probs = torch.softmax(gate_logits, dim=-1)  # [..., E]
        topk_probs, topk_idx = probs.topk(self.top_k, dim=-1)  # [..., k]
        gate_w = topk_probs / topk_probs.sum(dim=-1, keepdim=True).clamp_min(1e-12)

        expert_out = torch.stack([expert(x) for expert in self.experts], dim=-2)  # [..., E, out]
        gather_idx = topk_idx.unsqueeze(-1).expand(*topk_idx.shape, expert_out.shape[-1])
        selected = torch.gather(expert_out, -2, gather_idx)  # [..., k, out]
        y = (selected * gate_w.unsqueeze(-1)).sum(dim=-2)  # [..., out]

        flat_probs = probs.reshape(-1, self.num_experts)
        flat_idx = topk_idx.reshape(-1, self.top_k)
        routed = torch.zeros_like(flat_probs).scatter(-1, flat_idx, 1.0)
        if mask is not None:
            m = mask.reshape(-1).to(flat_probs.dtype).unsqueeze(-1)
            denom = m.sum().clamp_min(1.0)
            f_e = (routed * m).sum(dim=0) / (denom * float(self.top_k))
            p_e = (flat_probs * m).sum(dim=0) / denom
        else:
            f_e = routed.mean(dim=0) / float(self.top_k)
            p_e = flat_probs.mean(dim=0)
        aux_loss = float(self.num_experts) * (f_e * p_e).sum()
        return y, aux_loss


class StockSetEncoder(nn.Module):
    """
    股票集合编码器（最小版 DeepSets 思路）：
    - 对每只股票特征做 token embedding（MLP）
    - 对 token embedding 做 masked mean pooling 得到行业股票 summary
    """

    def __init__(
        self,
        stock_feat_dim: int,
        token_dim: int,
        hidden_dim: int,
        num_layers: int = 2,
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        self.token_mlp = MLP(
            in_dim=stock_feat_dim,
            hidden_dim=hidden_dim,
            out_dim=token_dim,
            num_layers=num_layers,
            dropout=dropout,
            layer_norm=True,
        )

    def forward(self, stock_x: torch.Tensor, stock_mask: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        输入：
        - stock_x: [B, I, S, F_s]
        - stock_mask: [B, I, S] bool

        输出：
        - stock_tokens: [B, I, S, D]
        - stock_pooled: [B, I, D]
        """
        B, I, S, _ = stock_x.shape
        if stock_mask.dtype != torch.bool:
            stock_mask = stock_mask.bool()

        tokens = self.token_mlp(stock_x)  # [B, I, S, D]

        # masked mean pooling
        mask_f = stock_mask.to(tokens.dtype).unsqueeze(-1)  # [B, I, S, 1]
        tokens_masked = tokens * mask_f
        denom = mask_f.sum(dim=2).clamp_min(1.0)  # [B, I, 1]
        pooled = tokens_masked.sum(dim=2) / denom  # [B, I, D]
        return tokens, pooled


@dataclass
class HierOutput:
    """模型输出（方便 B_Train.py 使用）。"""

    w_stock_final: torch.Tensor        # [B, I, S]
    w_stock_intra: torch.Tensor        # [B, I, S]
    w_industry: torch.Tensor           # [B, I]（不含现金）
    w_cash: torch.Tensor               # [B] 或 [B,]（现金权重）
    industry_emb: torch.Tensor         # [B, I, H]
    moe_aux_loss: Optional[torch.Tensor] = None  # MoE 负载均衡辅助损失（未启用时为 None）


class HierarchicalPortfolioModel(nn.Module):
    """
    最小层级投资组合模型：
    - 行业内：成分股基本面特征 -> 打分 -> Top-K 选股 -> 按得分分配 w_stock_intra
    - 跨行业：行业 embedding -> logits -> Top-K 选行业 -> sigmoid 得 w_industry
    - w_stock_final = w_industry[..., None] * w_stock_intra
    """

    def __init__(
        self,
        stock_feat_dim: int,
        price_feat_dim: int,
        news_feat_dim: int,
        stock_token_dim: int = 64,
        industry_emb_dim: int = 128,
        mlp_hidden_dim: int = 128,
        dropout: float = 0.0,
        allow_cash: bool = True,
        critic_hidden_dim: int = 128,
        min_cash_weight: float = 0.0,
        max_cash_weight: float = 0.2,
        cash_logit_bias: float = 0.0,
        use_moe: bool = True,
        moe_num_experts: int = 4,
        moe_top_k: int = 2,
        moe_gate_noise_std: float = 0.0,
        random_industry_3_equal: bool = False,
        random_stock_10_from_top3_equal: bool = False,
    ) -> None:
        super().__init__()
        self.allow_cash = bool(allow_cash)
        self.min_cash_weight = float(max(min_cash_weight, 0.0))
        # allow_cash=False 时强制满仓
        raw_max_cash = 0.0 if not self.allow_cash else float(max_cash_weight)
        self.max_cash_weight = float(min(max(raw_max_cash, 0.0), 1.0))
        if self.min_cash_weight > self.max_cash_weight:
            self.min_cash_weight = self.max_cash_weight
        self.cash_logit_bias = float(cash_logit_bias)

        # MoE 配置：专家数 <= 1 时退化为普通 MLP
        self.moe_num_experts = int(max(1, moe_num_experts))
        self.moe_top_k = int(max(1, min(moe_top_k, self.moe_num_experts)))
        self.use_moe = bool(use_moe) and self.moe_num_experts > 1
        self.moe_gate_noise_std = float(max(moe_gate_noise_std, 0.0))
        self.random_industry_3_equal = bool(random_industry_3_equal)
        self.random_stock_10_from_top3_equal = bool(random_stock_10_from_top3_equal)

        def _make_block(in_dim: int, out_dim: int) -> nn.Module:
            """MoE 开启时返回专家混合块，否则返回等价结构的单一 MLP。"""
            if self.use_moe:
                return MoEFeedForward(
                    in_dim=in_dim,
                    hidden_dim=mlp_hidden_dim,
                    out_dim=out_dim,
                    num_experts=self.moe_num_experts,
                    top_k=self.moe_top_k,
                    num_layers=2,
                    dropout=dropout,
                    layer_norm=True,
                    gate_noise_std=self.moe_gate_noise_std,
                )
            return MLP(
                in_dim=in_dim,
                hidden_dim=mlp_hidden_dim,
                out_dim=out_dim,
                num_layers=2,
                dropout=dropout,
                layer_norm=True,
            )

        # 1) 股票集合编码
        self.stock_encoder = StockSetEncoder(
            stock_feat_dim=stock_feat_dim,
            token_dim=stock_token_dim,
            hidden_dim=mlp_hidden_dim,
            num_layers=2,
            dropout=dropout,
        )

        # 2) 行业价格 / 新闻编码（MLP）
        self.price_encoder = MLP(
            in_dim=price_feat_dim,
            hidden_dim=mlp_hidden_dim,
            out_dim=mlp_hidden_dim,
            num_layers=2,
            dropout=dropout,
            layer_norm=True,
        )
        self.news_encoder = MLP(
            in_dim=news_feat_dim,
            hidden_dim=mlp_hidden_dim,
            out_dim=mlp_hidden_dim,
            num_layers=2,
            dropout=dropout,
            layer_norm=True,
        )

        # 3) 多模态融合（concat -> MoE / MLP）
        fusion_in = stock_token_dim + mlp_hidden_dim + mlp_hidden_dim
        self.fusion = _make_block(fusion_in, industry_emb_dim)

        # 4) 行业内配置头：仅基于成分股基本面特征（stock_x）输出打分
        self.fundamental_score_head = _make_block(stock_feat_dim, 1)

        # 5) 跨行业协调头：对每个行业输出 logits
        self.global_head = _make_block(industry_emb_dim, 1)

        # 现金头：用“市场级”表示（行业 embedding 的 masked mean）输出 cash logit
        # 若 allow_cash=False，则不会使用该头
        self.cash_head = MLP(
            in_dim=industry_emb_dim,
            hidden_dim=mlp_hidden_dim,
            out_dim=1,
            num_layers=2,
            dropout=dropout,
            layer_norm=True,
        )

        # centralized critic：基于“市场级”表示输出 V(s)
        self.value_head = MLP(
            in_dim=industry_emb_dim,
            hidden_dim=critic_hidden_dim,
            out_dim=1,
            num_layers=2,
            dropout=dropout,
            layer_norm=True,
        )

    @staticmethod
    def _run_block(
        block: nn.Module,
        x: torch.Tensor,
        mask: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """统一 MoE / MLP 的调用方式，返回 (输出, MoE 辅助损失)。"""
        if isinstance(block, MoEFeedForward):
            return block(x, mask)
        return block(x), torch.zeros((), device=x.device, dtype=x.dtype)

    def forward(
        self,
        stock_x: torch.Tensor,
        stock_mask: torch.Tensor,
        price_x: torch.Tensor,
        news_x: torch.Tensor,
        industry_mask: Optional[torch.Tensor] = None,
        intra_temperature: float = 1.0,
        industry_temperature: float = 1.0,
        intra_top_k: int = 5,
        industry_top_k: int = 5,
        return_dict: bool = True,
    ) -> Dict[str, torch.Tensor] | HierOutput:
        """
        输入支持两种形状：
        - 无 batch：stock_x [I, S, F_s]；price_x/news_x [I, F]；mask [I, S] / [I]
        - 有 batch：stock_x [B, I, S, F_s]；price_x/news_x [B, I, F]；mask [B, I, S] / [B, I]

        返回：
        - w_stock_final: [B, I, S]
        - w_stock_intra: [B, I, S]
        - w_industry: [B, I]（不含现金）
        - w_cash: [B]
        - industry_emb: [B, I, H]
        - value: [B]（centralized critic 的 V(s)）
        - logits_stock: [B, I, S]
        - logits_ind: [B, I]
        - cash_logit: [B]（allow_cash=True 时）
        - w_all: [B, I+1]（allow_cash=True 时；否则为 None）
        """
        stock_x, added_b1 = _ensure_batch(stock_x, target_dim=4)
        stock_mask, _ = _ensure_batch(stock_mask, target_dim=3)
        price_x, _ = _ensure_batch(price_x, target_dim=3)
        news_x, _ = _ensure_batch(news_x, target_dim=3)

        # 防御：避免上游 NaN/inf 进入网络导致梯度/参数变 NaN
        stock_x = torch.nan_to_num(stock_x, nan=0.0, posinf=0.0, neginf=0.0)
        price_x = torch.nan_to_num(price_x, nan=0.0, posinf=0.0, neginf=0.0)
        news_x = torch.nan_to_num(news_x, nan=0.0, posinf=0.0, neginf=0.0)

        if industry_mask is None:
            # 若不提供行业 mask，则认为所有行业都有效
            industry_mask = torch.ones(stock_x.shape[:2], device=stock_x.device, dtype=torch.bool)
        else:
            industry_mask, _ = _ensure_batch(industry_mask, target_dim=2)
            if industry_mask.dtype != torch.bool:
                industry_mask = industry_mask.bool()

        B, I, S, _ = stock_x.shape
        stock_mask_eff = stock_mask & industry_mask.unsqueeze(-1)

        # ---- 1) 行业内股票 token + pooled summary
        stock_tokens, stock_pooled = self.stock_encoder(stock_x, stock_mask)  # [B,I,S,D], [B,I,D]

        # ---- 2) 行业价格/新闻编码
        price_emb = self.price_encoder(price_x)  # [B, I, Hh]
        news_emb = self.news_encoder(news_x)     # [B, I, Hh]

        # ---- 3) 多模态融合
        fused = torch.cat([stock_pooled, price_emb, news_emb], dim=-1)  # [B,I,*]
        industry_emb, aux_fusion = self._run_block(self.fusion, fused, industry_mask)  # [B, I, H]

        # 市场级表示：对行业 embedding 做 masked mean pooling（critic 与 cash_head 共用）
        mask_f = industry_mask.to(industry_emb.dtype).unsqueeze(-1)  # [B,I,1]
        denom = mask_f.sum(dim=1).clamp_min(1.0)  # [B,1]
        market_emb = (industry_emb * mask_f).sum(dim=1) / denom  # [B,H]
        value = self.value_head(market_emb).squeeze(-1)  # [B]

        # ---- 4) 行业内配置：基本面打分 -> Top-K 选股 -> 按得分分配权重
        fund_out, aux_fund = self._run_block(self.fundamental_score_head, stock_x, stock_mask_eff)
        fund_scores = fund_out.squeeze(-1)  # [B,I,S]
        intra_t = float(max(intra_temperature, 1e-6))
        logits_stock = fund_scores / intra_t

        w_intra_cont = masked_topk_softmax(
            logits_stock,
            stock_mask_eff,
            top_k=intra_top_k,
            dim=-1,
        )

        # ---- 5) 跨行业配置：Top-K 选行业 -> sigmoid -> [0,1]，总和可小于 1（余量为 cash）
        logits_ind_out, aux_global = self._run_block(self.global_head, industry_emb, industry_mask)
        logits_ind = logits_ind_out.squeeze(-1)  # [B, I]
        if self.random_industry_3_equal:
            w_industry_cont = torch.zeros_like(logits_ind)
            for b in range(B):
                valid = torch.nonzero(industry_mask[b], as_tuple=False).squeeze(-1)
                if valid.numel() == 0:
                    continue
                k = min(3, int(valid.numel()))
                perm = torch.randperm(int(valid.numel()), device=valid.device)
                chosen = valid[perm[:k]]
                w_industry_cont[b, chosen] = 1.0 / float(k)
            w_stock_cont = w_industry_cont.unsqueeze(-1) * w_intra_cont
        elif self.random_stock_10_from_top3_equal:
            top3_mask = torch.zeros_like(industry_mask, dtype=torch.bool)
            for b in range(B):
                valid = industry_mask[b]
                valid_idx = torch.nonzero(valid, as_tuple=False).squeeze(-1)
                if valid_idx.numel() == 0:
                    continue
                k_ind = min(3, int(valid_idx.numel()))
                valid_logits = logits_ind[b, valid]
                _, local_top = torch.topk(valid_logits, k=k_ind, dim=-1)
                chosen_ind = valid_idx[local_top]
                top3_mask[b, chosen_ind] = True

            candidate_mask = stock_mask_eff & top3_mask.unsqueeze(-1)
            w_stock_cont = torch.zeros_like(w_intra_cont)
            for b in range(B):
                cand = torch.nonzero(candidate_mask[b], as_tuple=False)  # [N,2] -> (ind, stock)
                if cand.numel() == 0:
                    continue
                k_stock = min(10, int(cand.shape[0]))
                perm = torch.randperm(int(cand.shape[0]), device=cand.device)
                chosen = cand[perm[:k_stock]]
                w_stock_cont[b, chosen[:, 0], chosen[:, 1]] = 1.0 / float(k_stock)

            w_industry_cont = w_stock_cont.sum(dim=-1)
            intra_denom = w_stock_cont.sum(dim=-1, keepdim=True).clamp_min(1e-12)
            w_intra_cont = torch.where(
                w_stock_cont > 0.0,
                w_stock_cont / intra_denom,
                torch.zeros_like(w_stock_cont),
            )
        else:
            w_industry_cont = masked_topk_sigmoid(
                logits_ind,
                industry_mask,
                top_k=industry_top_k,
                temperature=industry_temperature,
            )
            w_industry_cont = apply_cash_bounds(
                w_industry_cont,
                industry_mask,
                min_cash_weight=self.min_cash_weight,
                max_cash_weight=self.max_cash_weight,
            )
            w_stock_cont = w_industry_cont.unsqueeze(-1) * w_intra_cont

        w_ind_d, w_in_d, w_fin_d, w_cash_d = discretize_hierarchical_weights(
            w_industry_cont,
            w_intra_cont,
            stock_mask_eff,
            industry_mask,
        )

        w_industry = straight_through_weights(w_industry_cont, w_ind_d)
        w_stock_intra = straight_through_weights(w_intra_cont, w_in_d)
        w_stock_final = straight_through_weights(w_stock_cont, w_fin_d)
        w_cash = straight_through_weights(1.0 - w_stock_cont.sum(dim=(-2, -1)), w_cash_d)

        w_all = torch.cat([w_industry, w_cash.unsqueeze(-1)], dim=-1)
        cash_logit = None
        moe_aux_loss = aux_fusion + aux_fund + aux_global

        # 若输入无 batch，则输出时默认返回去掉 batch 的形状，便于调试
        if added_b1:
            w_stock_final = w_stock_final.squeeze(0)
            w_stock_intra = w_stock_intra.squeeze(0)
            w_industry = w_industry.squeeze(0)
            w_cash = w_cash.squeeze(0)
            industry_emb = industry_emb.squeeze(0)
            value = value.squeeze(0)
            logits_stock = logits_stock.squeeze(0)
            logits_ind = logits_ind.squeeze(0)
            if cash_logit is not None:
                cash_logit = cash_logit.squeeze(0)
            if w_all is not None:
                w_all = w_all.squeeze(0)

        if return_dict:
            return {
                "w_stock_final": w_stock_final,
                "w_stock_intra": w_stock_intra,
                "w_industry": w_industry,
                "w_cash": w_cash,
                "industry_emb": industry_emb,
                "value": value,
                "logits_stock": logits_stock,
                "logits_ind": logits_ind,
                "cash_logit": torch.zeros_like(w_cash),
                "w_all": w_all,
                "moe_aux_loss": moe_aux_loss,
            }

        return HierOutput(
            w_stock_final=w_stock_final,
            w_stock_intra=w_stock_intra,
            w_industry=w_industry,
            w_cash=w_cash,
            industry_emb=industry_emb,
            moe_aux_loss=moe_aux_loss,
        )


if __name__ == "__main__":
    # 最小 smoke check：随机张量前向
    torch.manual_seed(0)
    I, S = 11, 50
    Fs, Fp, Fn = 24, 19, 17
    model = HierarchicalPortfolioModel(Fs, Fp, Fn)
    stock_x = torch.randn(I, S, Fs)
    stock_mask = torch.rand(I, S) > 0.2
    price_x = torch.randn(I, Fp)
    news_x = torch.randn(I, Fn)
    industry_mask = torch.ones(I, dtype=torch.bool)
    out = model(stock_x, stock_mask, price_x, news_x, industry_mask)
    print(out["w_stock_final"].shape, out["w_industry"].shape, out["w_stock_intra"].shape, out["industry_emb"].shape)
    print("use_moe:", model.use_moe, "moe_aux_loss:", float(out["moe_aux_loss"]))
    total = float(out["w_stock_final"].sum().item() + out["w_cash"].sum().item())
    print("sum final+cash:", total)

