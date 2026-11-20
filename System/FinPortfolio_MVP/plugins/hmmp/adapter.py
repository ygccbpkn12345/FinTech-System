"""HMMP 插件适配器。

原则：不修改、不复制论文原始代码（System/HMMP/ 保持原样）。
B_Train.py 已具备完整 argparse CLI，且数据从 CWD 相对路径 Data/ 读取、
结果写入 CWD 相对路径 Results/。适配器因此：

1. 在实验工作目录构造 Data/（优先目录联接 junction，失败则复制文件）；
2. 以安全参数列表 subprocess 方式运行 B_Train.py（参数来自 manifest 白名单），
   子进程 stdout/stderr 直接透传到本进程 stdout（由任务管理器统一落盘）；
3. 训练结束后从 Results/<run_name>/ 读取论文输出并规范化为
   StandardPortfolioResult —— 最终权重按「行业资金权重 × 行业内条件权重」
   组合，CASH 记入 cash_weights（任务书第八节要求）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

try:
    from finportfolio_plugin_interface import BasePortfolioPlugin
except ImportError:
    class BasePortfolioPlugin:  # type: ignore
        pass

DATA_FILES = ("industry_price_features.csv", "industry_news_features.csv")
DATA_SUBDIR = "IndustryPrice"

# manifest.parameters[].cli_flag 白名单之外的参数一律拒绝传入
EXTRA_ALLOWED_FLAGS = {
    "--run_name": str,
}


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
            f"HMMP original code dir not found: {p} "
            f"(set FINPORTFOLIO_ORIGINAL_CODE_ROOT or check manifest)"
        )
    return p


def _stage_data_dir(dataset: dict, work_dir: Path) -> None:
    """把数据集内容以 Data/ 形态放入工作目录（junction 优先，复制兜底）。"""
    src = Path(dataset["storage_path"])
    data_dir = work_dir / "Data"
    if data_dir.exists():
        return
    for name in DATA_FILES:
        if not (src / name).is_file():
            raise ValueError(f"dataset missing required file: {src / name}")
    if not (src / DATA_SUBDIR).is_dir():
        raise ValueError(f"dataset missing required directory: {src / DATA_SUBDIR}")

    junction_made = False
    if os.name == "nt":
        try:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(data_dir), str(src)],
                check=True, capture_output=True,
            )
            junction_made = data_dir.is_dir()
        except (subprocess.CalledProcessError, OSError):
            junction_made = False
    if not junction_made:
        import shutil
        shutil.copytree(src, data_dir, dirs_exist_ok=True)
        print("[hmmp-adapter] data staged by copy (junction unavailable)")


class Adapter(BasePortfolioPlugin):
    capabilities = ("train", "portfolio_weights", "industry_allocation", "news_analysis")

    # ------------------------------------------------------------------
    def _build_argv(self, params: dict, run_name: str) -> list:
        manifest_params = {
            p["name"]: p for p in self.context.get("manifest", {}).get("parameters", [])
        }
        argv: list = []
        for name, value in params.items():
            spec = manifest_params.get(name)
            flag = (spec or {}).get("cli_flag")
            if not flag:
                continue  # 未声明 CLI 旗标的参数不传递（如纯元信息）
            if isinstance(value, bool):
                value = int(value)
            argv += [flag, str(value)]
        argv += ["--run_name", run_name]
        return argv

    # ------------------------------------------------------------------
    def _date_split_args(self, context: dict) -> list:
        """实验级时间切片 → 论文 CLI 原生日期参数（仅 fixed 模式有意义）。

        B_Train.py fixed 切分：训练集 = [train_start_date, train_end_date]（含端点），
        其余日期全部作为测试集 —— 因此 test_start/test_end 无法显式表达，
        如有提供则打印警告说明（不截断论文数据管线）。
        """
        split = (context.get("dataset", {}) or {}).get("date_split") or {}
        if not split:
            return []
        split_mode = str(self._effective_param(context, "split_mode", "fixed"))
        args: list = []
        if split.get("train_start"):
            args += ["--train_start_date", str(split["train_start"])]
        if split.get("train_end"):
            args += ["--train_end_date", str(split["train_end"])]
        if split_mode != "fixed":
            print(f"[hmmp-adapter] warning: split_mode={split_mode} ignores date "
                  f"split {split} (date boundaries apply to fixed mode only)")
        if split.get("test_start") or split.get("test_end"):
            print("[hmmp-adapter] warning: paper fixed protocol defines the test "
                  "set as all dates outside the train window; test_start/test_end "
                  "are not enforceable without modifying paper code - ignored")
        return args

    @staticmethod
    def _effective_param(context: dict, name: str, default: str) -> str:
        return str((context.get("params", {}) or {}).get(name, default))

    # ------------------------------------------------------------------
    def train(self, params: dict, context: dict) -> dict:
        original_dir = _find_original_dir(context)
        work_dir = Path(context["work_dir"])
        _stage_data_dir(context["dataset"], work_dir)

        run_name = f"finportfolio_{context['experiment_id']}"
        argv = self._build_argv(params, run_name)
        argv += self._date_split_args(context)
        entry = original_dir / "B_Train.py"

        print(f"[hmmp-adapter] running: python {entry.name} {' '.join(argv)}")
        print(f"[hmmp-adapter] cwd={work_dir} (Data/ and Results/ are relative to it)")

        proc = subprocess.run(          # 安全参数列表，无 shell
            [sys.executable, str(entry), *argv],
            cwd=str(work_dir),
            stdout=sys.stdout.buffer,
            stderr=sys.stderr.buffer,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"B_Train.py exited with code {proc.returncode}")

        results_dir = work_dir / "Results" / run_name
        return self._normalize(results_dir, context)

    # ------------------------------------------------------------------
    def _normalize(self, results_dir: Path, context: dict) -> dict:
        from finportfolio_metrics import compute_metrics, turnover_series, wealth_series

        returns_csv = results_dir / "test_daily_returns.csv"
        industry_csv = results_dir / "test_industry_weights.csv"
        intra_csv = results_dir / "test_stock_intra_weights.csv"
        for p in (returns_csv, industry_csv, intra_csv):
            if not p.is_file():
                raise RuntimeError(f"expected paper output missing: {p}")

        rf = pd.read_csv(returns_csv)
        rf.columns = [str(c).strip() for c in rf.columns]
        dcol = next(c for c in rf.columns if c.lower() == "date")
        rcol = next(c for c in rf.columns if c.lower() == "return")
        rf[dcol] = pd.to_datetime(rf[dcol], errors="coerce").dt.strftime("%Y-%m-%d")
        rf = rf.dropna(subset=[dcol, rcol]).sort_values(dcol)
        dates = rf[dcol].tolist()
        daily = rf[rcol].astype(float).tolist()

        # 行业权重（宽表，含 CASH）
        ind = pd.read_csv(industry_csv)
        ind.columns = [str(c).strip() for c in ind.columns]
        idcol = next(c for c in ind.columns if c.lower() == "date")
        ind[idcol] = pd.to_datetime(ind[idcol], errors="coerce").dt.strftime("%Y-%m-%d")
        ind = ind.sort_values(idcol)
        cash_col = next((c for c in ind.columns if str(c).upper() == "CASH"), None)
        industry_cols = [c for c in ind.columns if c not in (idcol, cash_col)]

        # 行业内条件权重（长表；股票代码保留前导零）
        intra = pd.read_csv(intra_csv, dtype={"StockCode": str, "Industry_id": str})
        intra.columns = [str(c).strip() for c in intra.columns]
        imap: dict[tuple, dict[str, float]] = {}
        for _, row in intra.iterrows():
            date = pd.to_datetime(row["Date"], errors="coerce")
            if pd.isna(date):
                continue
            key = (date.strftime("%Y-%m-%d"), str(row["Industry_id"]))
            imap.setdefault(key, {})[str(row["StockCode"])] = float(row["IntraWeight"])

        stock_rows: list[dict] = []
        cash_rows: list[float] = []
        industry_rows: list[dict] = []
        for _, row in ind.iterrows():
            date = row[idcol]
            cash = float(row[cash_col]) if cash_col and pd.notna(row[cash_col]) else 0.0
            stock_w: dict[str, float] = {}
            industry_w: dict[str, float] = {}
            for c in industry_cols:
                iw = float(row[c]) if pd.notna(row[c]) else 0.0
                industry_w[str(c)] = iw
                for scode, wgt in imap.get((date, str(c)), {}).items():
                    stock_w[scode] = iw * wgt          # 行业资金 × 行业内条件
            stock_rows.append(stock_w)
            cash_rows.append(cash)
            industry_rows.append(industry_w)

        m = min(len(dates), len(stock_rows))
        dates, daily = dates[:m], daily[:m]
        stock_rows = stock_rows[:m]
        cash_rows = cash_rows[:m]
        industry_rows = industry_rows[:m]

        turn = turnover_series(stock_rows, cash_rows)
        values = wealth_series(daily)
        mets = compute_metrics(daily, turn, cash_rows)

        arts = [
            {"name": p.name, "path": str(p), "kind": "csv",
             "description": "HMMP paper-original output"}
            for p in sorted(results_dir.glob("*.csv"))
        ]
        ckpt = results_dir / "best_model_window_0.pt"
        if ckpt.is_file():
            arts.append({"name": ckpt.name, "path": str(ckpt), "kind": "checkpoint"})

        split = (context.get("dataset", {}) or {}).get("date_split") or {}
        notes = [
            "HMMP final stock weight = industry capital weight x intra-industry "
            "conditional weight; CASH recorded as cash_weights.",
            "Paper env deducts no transaction cost; returns are gross.",
            "Weights exported at 4-decimal precision by the paper code; budget "
            "constraint checked with 5e-3 tolerance.",
        ]
        if split:
            notes.append(
                "user-selected train date split passed to B_Train.py via "
                f"--train_start_date/--train_end_date: {split}"
            )
        return {
            "backtest_mode": "paper_original",
            "trading_protocol": {
                "execution_timing": "paper original PortfolioEnv (MAPPO rollouts)",
                "cost_pct": 0.0,
                "cost_actually_deducted": False,
                "rebalance_freq": "daily",
                "date_split": split or None,
            },
            "dates": dates,
            "daily_returns": daily,
            "net_daily_returns": None,
            "cost_included": False,
            "portfolio_values": values,
            "stock_weights": stock_rows,
            "cash_weights": cash_rows,
            "industry_weights": industry_rows,
            "turnover": turn,
            "metrics": mets,
            "artifacts": arts,
            "notes": notes,
        }
