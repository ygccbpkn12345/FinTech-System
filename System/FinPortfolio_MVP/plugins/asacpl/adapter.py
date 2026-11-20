"""ASACPL 插件适配器。

原则：不修改、不复制论文原始代码（System/ASACPL/ 保持原样）。
本适配器在插件子进程中：

1. 把数据集提供的 02_train_CNN.csv / 02_test_CNN.csv 复制到实验工作目录；
2. 通过 importlib 以模块方式加载 original/04_CNNAndA3C.py
   （其 __main__ 块不会执行；模块级仅设置环境与导入依赖）；
3. 按论文脚本 __main__ 块的同一流程驱动训练与测试评估
   （env 参数、tech_indicator_list=['f1'..'f4']、A3C 结构均为论文原值）；
4. WorkerAgent.train 内部向论文作者机器的绝对路径追加 loss/reward CSV ——
   适配器只负责确保这些目录存在（os.makedirs），不改动该行为；
5. 将测试集输出 CSV 规范化为 StandardPortfolioResult。

已知限制（如实声明）：
- 原始脚本不保存模型权重，训练与测试评估在同一进程内完成，
  因此不提供独立的 predict 能力；
- HLB-AS 股票筛选位于论文 notebook（00/01），输入数据即筛选后产物，
  故本插件不声明 stock_selection 能力。
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pandas as pd

try:
    from finportfolio_plugin_interface import BasePortfolioPlugin
except ImportError:
    class BasePortfolioPlugin:  # type: ignore
        pass


TRAIN_LOGICAL = ("train_prices", "prices")
TEST_LOGICAL = ("test_prices",)

# 论文 04_CNNAndA3C.py __main__ 块中的环境参数（原值，不得改动）
PAPER_ENV_KWARGS = dict(
    hmax=500,
    initial_amount=1000000,
    transaction_cost_pct=0.001,
    reward_scaling=0,
    tech_indicator_list=["f1", "f2", "f3", "f4"],
)
# WorkerAgent.train 追加写入的论文作者机器绝对路径（原代码硬编码，仅确保目录存在）
HARDCODED_LOG_DIRS = [
    r"D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/result",
]


def _find_original_dir(context: dict) -> Path:
    sub = (context.get("manifest", {}).get("execution", {}) or {}).get("original_code_subdir")
    if not sub:
        raise RuntimeError("manifest.execution.original_code_subdir missing")
    p = Path(sub)
    if not p.is_absolute():
        root = Path(os.environ.get(
            "FINPORTFOLIO_ORIGINAL_CODE_ROOT",
            str(Path(context["plugin_dir"]).resolve().parents[2]),
        ))
        p = root / p
    if not p.is_dir():
        raise RuntimeError(
            f"ASACPL original code dir not found: {p} "
            f"(set FINPORTFOLIO_ORIGINAL_CODE_ROOT or check manifest)"
        )
    return p


def _load_original_module(original_dir: Path):
    path = original_dir / "04_CNNAndA3C.py"
    if not path.is_file():
        raise RuntimeError(f"original entry not found: {path}")
    if str(original_dir) not in sys.path:
        sys.path.insert(0, str(original_dir))   # env_new 等同目录依赖
    spec = importlib.util.spec_from_file_location("asacpl_04_cnn_and_a3c", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_actions(raw) -> list:
    """解析论文 actions 字段。

    论文 DRL_prediction 导出的 actions 列有两种形态：首行初始权重是 Python
    列表 repr（逗号分隔，ast 可解析）；其后各行为 numpy 数组 str()（空格
    分隔、长数组还会折行），ast.literal_eval 会抛 SyntaxError —— 用正则
    提取浮点数兜底。解析失败必须报错，禁止静默置空（否则权重和为 0，
    触发预算约束校验失败且难以定位）。
    """
    import ast
    import re

    if not isinstance(raw, str):
        return [float(v) for v in raw]
    try:
        return [float(v) for v in ast.literal_eval(raw)]
    except (ValueError, SyntaxError):
        vals = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw)]
        if not vals:
            raise ValueError(f"no numeric values in actions field: {raw[:60]!r}")
        return vals


def _slice_by_dates(
    df: pd.DataFrame, start: str | None, end: str | None
) -> pd.DataFrame:
    """按 date 列切片（含端点）。start/end 为 YYYY-MM-DD；空值不做限制。"""
    if not start and not end:
        return df
    d = pd.to_datetime(df["date"], errors="coerce")
    mask = pd.Series(True, index=df.index)
    if start:
        mask &= d >= pd.Timestamp(start)
    if end:
        mask &= d <= pd.Timestamp(end)
    out = df[mask]
    if out.empty:
        raise ValueError(
            f"date split [{start}, {end}] leaves an empty frame; "
            f"data covers {d.min().date()}~{d.max().date()}"
        )
    return out


class Adapter(BasePortfolioPlugin):
    capabilities = ("train", "portfolio_weights")

    # ------------------------------------------------------------------
    def _stage_dataset(self, dataset: dict, work_dir: Path) -> tuple[Path, Path]:
        files = dataset.get("files", {})
        train_key = next((k for k in TRAIN_LOGICAL if k in files), None)
        test_key = next((k for k in TEST_LOGICAL if k in files), None)
        if not train_key:
            raise ValueError(
                f"dataset '{dataset.get('dataset_id')}' lacks train prices "
                f"(expected one of {TRAIN_LOGICAL})"
            )
        if not test_key:
            raise ValueError("dataset lacks test prices (test_prices)")
        data_dir = work_dir / "datasets"
        data_dir.mkdir(parents=True, exist_ok=True)
        base = Path(dataset["storage_path"])
        train_path = data_dir / "02_train_CNN.csv"
        test_path = data_dir / "02_test_CNN.csv"
        shutil.copy2(base / files[train_key], train_path)
        shutil.copy2(base / files[test_key], test_path)
        return train_path, test_path

    # ------------------------------------------------------------------
    def train(self, params: dict, context: dict) -> dict:
        original_dir = _find_original_dir(context)
        work_dir = Path(context["work_dir"])
        train_path, test_path = self._stage_dataset(context["dataset"], work_dir)

        # 论文 WorkerAgent 向作者机器绝对路径写训练曲线；确保目录存在以避免崩溃
        for d in HARDCODED_LOG_DIRS:
            try:
                os.makedirs(d, exist_ok=True)
            except OSError as e:
                print(f"[asacpl-adapter] cannot create hardcoded log dir {d}: {e}")

        mod = _load_original_module(original_dir)

        train_df = pd.read_csv(train_path)
        test_df = pd.read_csv(test_path)
        # 实验级时间切片（可选）：train/test 文件各自按 date 列截取（含端点）
        split = (context.get("dataset", {}) or {}).get("date_split") or {}
        if split:
            train_df = _slice_by_dates(train_df, split.get("train_start"), split.get("train_end"))
            test_df = _slice_by_dates(test_df, split.get("test_start"), split.get("test_end"))
            print(f"[asacpl-adapter] date split applied: {split}")
            print(f"[asacpl-adapter] train {train_df.date.min()}~{train_df.date.max()}, "
                  f"test {test_df.date.min()}~{test_df.date.max()}")
        stock_dimension = len(train_df.tic.unique())
        env_kwargs = dict(PAPER_ENV_KWARGS)
        env_kwargs.update(
            state_space=stock_dimension,
            stock_dim=stock_dimension,
            action_space=stock_dimension,
            initial_weights=[1 / stock_dimension] * stock_dimension,
        )
        # DRL_prediction 引用模块级 state_space（原脚本在 __main__ 中定义）
        mod.state_space = stock_dimension

        max_episodes = int(params.get("max_episodes", 100))
        num_workers = int(params.get("num_workers", 5))

        print(f"[asacpl-adapter] train stocks={stock_dimension} "
              f"episodes={max_episodes} workers={num_workers}")
        print(f"[asacpl-adapter] train rows={len(train_df)} test rows={len(test_df)}")

        e_train_gym = mod.StockPortfolioEnv(df=train_df, **env_kwargs)
        env_train, _ = e_train_gym.get_sb_env()
        agent = mod.DRL_Agent(env=env_train)
        agent.num_workers = num_workers
        trained_model = agent.train(max_episodes=max_episodes)

        out_dir = work_dir / "result"
        out_dir.mkdir(parents=True, exist_ok=True)

        print("[asacpl-adapter] evaluating on train split (paper protocol)")
        e_trade_train = mod.StockPortfolioEnv(df=train_df, **env_kwargs)
        env_trade, obs_trade = e_trade_train.get_sb_env()
        tr_return, _ = mod.DRL_prediction(
            model=trained_model, test_data=train_df,
            test_env=env_trade, test_obs=obs_trade,
        )
        tr_return.to_csv(out_dir / "04_a3c_train_daily_return_CNN.csv", index=False)

        print("[asacpl-adapter] evaluating on test split (paper protocol)")
        e_trade_test = mod.StockPortfolioEnv(df=test_df, **env_kwargs)
        env_trade, obs_trade = e_trade_test.get_sb_env()
        te_return, te_weights = mod.DRL_prediction(
            model=trained_model, test_data=test_df,
            test_env=env_trade, test_obs=obs_trade,
        )
        te_return.to_csv(out_dir / "04_a3c_test_daily_return_CNN.csv", index=False)
        te_weights.to_csv(out_dir / "04_a3c_test_weights_CNN.csv", index=False)

        return self._normalize(
            returns_csv=out_dir / "04_a3c_test_daily_return_CNN.csv",
            weights_csv=out_dir / "04_a3c_test_weights_CNN.csv",
            test_df=test_df,
            context=context,
            artifacts_dir=out_dir,
        )

    # ------------------------------------------------------------------
    def _normalize(self, returns_csv: Path, weights_csv: Path, test_df: pd.DataFrame,
                   context: dict, artifacts_dir: Path) -> dict:
        import numpy as np

        from finportfolio_metrics import compute_metrics, turnover_series, wealth_series

        rf = pd.read_csv(returns_csv)
        cols = {str(c).lower(): c for c in rf.columns}
        rcol = cols.get("daily_return") or cols.get("return")
        dcol = cols.get("date")
        rf = rf.rename(columns={dcol: "date", rcol: "return"})
        rf["date"] = pd.to_datetime(rf["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        rf = rf.dropna().sort_values("date")
        dates = rf["date"].tolist()
        daily = rf["return"].astype(float).tolist()

        # actions 权重按当日 tic 顺序对齐真实代码（已验证：数据按 date,tic 排序）
        wf = pd.read_csv(weights_csv)
        wcols = {str(c).lower(): c for c in wf.columns}
        wf = wf.sort_values(wcols["date"])
        day_tics = (
            test_df.assign(date=lambda d: pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d"))
            .sort_values(["date", "tic"])
            .groupby("date")["tic"].apply(list)
        )
        stock_rows: list[dict] = []
        for _, row in wf.iterrows():
            date = pd.to_datetime(row[wcols["date"]]).strftime("%Y-%m-%d")
            vals = _parse_actions(row[wcols["actions"]])
            tics = day_tics.get(date)
            if tics is not None and len(tics) == len(vals):
                stock_rows.append({str(t): float(v) for t, v in zip(tics, vals)})
            else:
                stock_rows.append({f"Asset_{i+1}": float(v) for i, v in enumerate(vals)})
        label_mode = "ticker" if stock_rows and all(
            not k.startswith("Asset_") for k in stock_rows[-1]
        ) else "position_index"

        m = min(len(dates), len(stock_rows))
        dates, daily = dates[:m], daily[:m]
        stock_rows = stock_rows[:m]
        cash = [0.0] * m
        turn = turnover_series(stock_rows, cash)
        values = wealth_series(daily)
        mets = compute_metrics(daily, turn, cash)

        arts = [
            {"name": p.name, "path": str(p), "kind": "csv",
             "description": "ASACPL paper-original output"}
            for p in sorted(artifacts_dir.glob("*.csv"))
        ]
        split = (context.get("dataset", {}) or {}).get("date_split") or {}
        notes = [
            "ASACPL paper-original protocol: A3C trained on train split, "
            "evaluated on test split in one run (original code saves no weights).",
            "Original env stores transaction_cost_pct=0.001 but the step() return "
            "computation does not deduct it; returns are gross.",
        ]
        if split:
            notes.append(f"user-selected date split applied: {split}")
        return {
            "backtest_mode": "paper_original",
            "trading_protocol": {
                "execution_timing": "paper original StockPortfolioEnv",
                "cost_pct": 0.001,
                "cost_actually_deducted": False,
                "rebalance_freq": "daily",
                "date_split": split or None,
                "env_kwargs": {k: v for k, v in PAPER_ENV_KWARGS.items()
                               if k != "tech_indicator_list"},
            },
            "dates": dates,
            "daily_returns": daily,
            "net_daily_returns": None,
            "cost_included": False,
            "portfolio_values": values,
            "stock_weights": stock_rows,
            "cash_weights": cash,
            "industry_weights": None,
            "turnover": turn,
            "metrics": mets,
            "artifacts": arts,
            "asset_label_mode": label_mode,
            "notes": notes,
        }
