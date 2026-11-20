"""
B_WalkForward.py

提供 walk-forward（滚动 / 扩展窗口）切分逻辑，用于时间序列研究与回测：
- 输入：排序后的交易日列表、T_train、T_valid、T_test、step_size
- 输出：一组窗口，每个窗口包含 train/valid/test 的起止日期（闭区间）

约束：
- 严格按时间先后切分（chronological）
- 无未来信息泄漏（valid/test 不会出现在 train 之前）
- test 紧跟 valid（无间隔）
- 可选 align_end：强制最后一窗的 test 覆盖到样本最后一个交易日
- 可选 expanding：训练段从样本起点一直扩到 valid 之前（更充分利用历史）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class WalkForwardWindow:
    """一个滚动窗口（所有 end 均为闭区间）。"""

    window_id: int

    train_start: pd.Timestamp
    train_end: pd.Timestamp
    valid_start: pd.Timestamp
    valid_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp

    # 对应 dates 数组的索引范围（便于快速切片；end_idx 亦为闭区间）
    train_start_idx: int
    train_end_idx: int
    valid_start_idx: int
    valid_end_idx: int
    test_start_idx: int
    test_end_idx: int


def _as_sorted_unique_dates(dates: Sequence) -> np.ndarray:
    """
    将输入日期序列转为排序后的 numpy datetime64[ns] 并去重。
    允许输入为 str / datetime / pandas Timestamp / numpy datetime64 的混合序列。
    """
    if isinstance(dates, np.ndarray) and np.issubdtype(dates.dtype, np.datetime64):
        arr = dates.astype("datetime64[ns]")
    else:
        arr = np.array([pd.to_datetime(d).normalize().to_datetime64() for d in dates], dtype="datetime64[ns]")
    arr = np.unique(arr)  # unique 同时会排序
    return arr


def _make_window(
    d: np.ndarray,
    win_id: int,
    train_start_idx: int,
    train_end_idx: int,
    valid_start_idx: int,
    valid_end_idx: int,
    test_start_idx: int,
    test_end_idx: int,
) -> WalkForwardWindow:
    return WalkForwardWindow(
        window_id=win_id,
        train_start=pd.Timestamp(d[train_start_idx]),
        train_end=pd.Timestamp(d[train_end_idx]),
        valid_start=pd.Timestamp(d[valid_start_idx]),
        valid_end=pd.Timestamp(d[valid_end_idx]),
        test_start=pd.Timestamp(d[test_start_idx]),
        test_end=pd.Timestamp(d[test_end_idx]),
        train_start_idx=train_start_idx,
        train_end_idx=train_end_idx,
        valid_start_idx=valid_start_idx,
        valid_end_idx=valid_end_idx,
        test_start_idx=test_start_idx,
        test_end_idx=test_end_idx,
    )


def generate_walk_forward_windows(
    dates: Sequence,
    T_train: int,
    T_valid: int,
    T_test: int,
    step_size: int,
    drop_last: bool = True,
    align_end: bool = True,
    expanding: bool = False,
    min_test: int = 1,
) -> List[WalkForwardWindow]:
    """
    生成 walk-forward 窗口列表。

    参数：
    - dates：交易日序列
    - T_train：滚动模式下的固定训练长度；扩展模式下为最小训练长度（首窗）
    - T_valid / T_test：验证 / 测试长度（交易日）
    - step_size：窗口向前滚动步长
    - drop_last：若不足以构成完整窗且未开启 align_end，是否丢弃尾部
    - align_end：若尾部剩余天数不足以再开完整窗，则追加/调整最后一窗，
      使 test 覆盖到样本最后一个交易日（最后一窗的 test 可短于 T_test，但 >= min_test）
    - expanding：True 时 train 始终从样本第 0 日扩到 valid 前一日
    - min_test：align_end 时允许的最短 test 长度

    说明：
    - 前 T_train(+可选 warm-up) 天必然不会进入任何 Test（需先有训练/验证段），这是 walk-forward 的固有性质
    - align_end=True 可消除“末尾几天因 drop_last 永远不被测试”的空洞
    """
    if T_train <= 0 or T_valid <= 0 or T_test <= 0:
        raise ValueError("T_train/T_valid/T_test 必须均为正整数。")
    if step_size <= 0:
        raise ValueError("step_size 必须为正整数。")
    if min_test <= 0:
        raise ValueError("min_test 必须为正整数。")

    d = _as_sorted_unique_dates(dates)
    n = int(d.shape[0])
    total = T_train + T_valid + T_test
    if n < total:
        if drop_last and not align_end:
            return []
        raise ValueError(f"日期数量不足：n={n} < T_train+T_valid+T_test={total}")

    windows: List[WalkForwardWindow] = []
    start_train = 0
    win_id = 0

    while True:
        if expanding:
            # 扩展窗：train 从 0 开始，长度随滚动增长；首窗至少 T_train
            train_start_idx = 0
            train_end_idx = T_train - 1 + start_train
            valid_start_idx = train_end_idx + 1
            valid_end_idx = valid_start_idx + T_valid - 1
            test_start_idx = valid_end_idx + 1
            test_end_idx = test_start_idx + T_test - 1
        else:
            train_start_idx = start_train
            train_end_idx = train_start_idx + T_train - 1
            valid_start_idx = train_end_idx + 1
            valid_end_idx = valid_start_idx + T_valid - 1
            test_start_idx = valid_end_idx + 1
            test_end_idx = test_start_idx + T_test - 1

        if test_end_idx >= n:
            break

        windows.append(
            _make_window(
                d,
                win_id,
                train_start_idx,
                train_end_idx,
                valid_start_idx,
                valid_end_idx,
                test_start_idx,
                test_end_idx,
            )
        )
        win_id += 1
        start_train += step_size

        # 下一完整窗是否还能放下
        if expanding:
            next_train_end = T_train - 1 + start_train
            next_test_end = next_train_end + T_valid + T_test
            if next_test_end >= n:
                break
        else:
            if start_train + total > n:
                break

    # 尾部对齐：让最后一窗 test 覆盖到 n-1
    if align_end and n > 0:
        windows = _align_windows_to_end(
            d=d,
            windows=windows,
            T_train=T_train,
            T_valid=T_valid,
            T_test=T_test,
            expanding=expanding,
            min_test=min_test,
            drop_last=drop_last,
        )
    elif not windows and not drop_last:
        raise ValueError("无法生成任何完整 walk-forward 窗口。")

    return windows


def _align_windows_to_end(
    d: np.ndarray,
    windows: List[WalkForwardWindow],
    T_train: int,
    T_valid: int,
    T_test: int,
    expanding: bool,
    min_test: int,
    drop_last: bool,
) -> List[WalkForwardWindow]:
    """确保最后一窗 test_end 落到样本末日；必要时缩短最后 test 或新增一窗。"""
    n = int(d.shape[0])
    if n <= 0:
        return windows

    if not windows:
        # 尝试用尽可能长的 test 构造唯一一窗
        if n < T_train + T_valid + min_test:
            if drop_last:
                return []
            raise ValueError(
                f"样本过短，无法 align_end：n={n} < T_train+T_valid+min_test={T_train + T_valid + min_test}"
            )
        test_len = min(T_test, n - T_train - T_valid)
        test_end_idx = n - 1
        test_start_idx = test_end_idx - test_len + 1
        valid_end_idx = test_start_idx - 1
        valid_start_idx = valid_end_idx - T_valid + 1
        train_end_idx = valid_start_idx - 1
        train_start_idx = 0 if expanding else max(0, train_end_idx - T_train + 1)
        return [
            _make_window(
                d,
                0,
                train_start_idx,
                train_end_idx,
                valid_start_idx,
                valid_end_idx,
                test_start_idx,
                test_end_idx,
            )
        ]

    last = windows[-1]
    if last.test_end_idx >= n - 1:
        return windows

    # 从末日往回切一段 test（可短于 T_test）
    test_end_idx = n - 1
    # 尽量不与上一窗 test 重叠：从上一窗 test 结束后开始
    earliest_test_start = last.test_end_idx + 1
    desired_test_start = test_end_idx - T_test + 1
    test_start_idx = max(earliest_test_start, desired_test_start)
    test_len = test_end_idx - test_start_idx + 1
    if test_len < min_test:
        # 剩余过短：直接把上一窗 test 延伸到末日（允许略长于 T_test）
        extended = _make_window(
            d,
            last.window_id,
            last.train_start_idx,
            last.train_end_idx,
            last.valid_start_idx,
            last.valid_end_idx,
            last.test_start_idx,
            test_end_idx,
        )
        return windows[:-1] + [extended]

    valid_end_idx = test_start_idx - 1
    valid_start_idx = valid_end_idx - T_valid + 1
    if valid_start_idx < 0:
        if drop_last:
            return windows
        raise ValueError("align_end 失败：valid 段越界。")

    train_end_idx = valid_start_idx - 1
    if expanding:
        train_start_idx = 0
        if train_end_idx + 1 < T_train:
            if drop_last:
                return windows
            raise ValueError("align_end 失败：扩展训练段短于 T_train。")
    else:
        train_start_idx = train_end_idx - T_train + 1
        if train_start_idx < 0:
            if drop_last:
                return windows
            raise ValueError("align_end 失败：滚动训练段越界。")

    new_id = last.window_id + 1
    windows.append(
        _make_window(
            d,
            new_id,
            train_start_idx,
            train_end_idx,
            valid_start_idx,
            valid_end_idx,
            test_start_idx,
            test_end_idx,
        )
    )
    return windows


def coverage_report(
    windows: Sequence[WalkForwardWindow],
    dates: Sequence,
) -> Dict[str, object]:
    """统计 train/valid/test 覆盖情况，便于确认是否铺满样本。"""
    d = _as_sorted_unique_dates(dates)
    n = int(d.shape[0])
    train_cov = np.zeros(n, dtype=bool)
    valid_cov = np.zeros(n, dtype=bool)
    test_cov = np.zeros(n, dtype=bool)
    for w in windows:
        train_cov[w.train_start_idx : w.train_end_idx + 1] = True
        valid_cov[w.valid_start_idx : w.valid_end_idx + 1] = True
        test_cov[w.test_start_idx : w.test_end_idx + 1] = True

    never_test = np.where(~test_cov)[0]
    gaps = []
    if never_test.size:
        start = int(never_test[0])
        prev = start
        for i in never_test[1:]:
            i = int(i)
            if i != prev + 1:
                gaps.append(
                    {
                        "start": str(pd.Timestamp(d[start]).date()),
                        "end": str(pd.Timestamp(d[prev]).date()),
                        "n_days": prev - start + 1,
                    }
                )
                start = i
            prev = i
        gaps.append(
            {
                "start": str(pd.Timestamp(d[start]).date()),
                "end": str(pd.Timestamp(d[prev]).date()),
                "n_days": prev - start + 1,
            }
        )

    return {
        "n_dates": n,
        "date_start": str(pd.Timestamp(d[0]).date()) if n else None,
        "date_end": str(pd.Timestamp(d[-1]).date()) if n else None,
        "n_windows": len(windows),
        "train_covered_days": int(train_cov.sum()),
        "valid_covered_days": int(valid_cov.sum()),
        "test_covered_days": int(test_cov.sum()),
        "never_in_test_days": int((~test_cov).sum()),
        "never_in_test_gaps": gaps,
        "first_window_test": (
            [str(windows[0].test_start.date()), str(windows[0].test_end.date())] if windows else None
        ),
        "last_window_test": (
            [str(windows[-1].test_start.date()), str(windows[-1].test_end.date())] if windows else None
        ),
        "test_covers_sample_end": bool(windows and windows[-1].test_end_idx == n - 1),
    }


def validate_walk_forward_windows(
    windows: Sequence[WalkForwardWindow],
    dates: Sequence,
    strict_contiguous: bool = True,
) -> None:
    """
    校验生成的窗口是否满足关键约束：
    - train/valid/test 均为正长度
    - 时间严格递增
    - valid 紧接 train，test 紧接 valid（当 strict_contiguous=True）
    - 窗口内各段互不重叠
    - 索引范围合法（在 dates 范围内）
    """
    d = _as_sorted_unique_dates(dates)
    n = int(d.shape[0])

    for w in windows:
        for idx in (
            w.train_start_idx,
            w.train_end_idx,
            w.valid_start_idx,
            w.valid_end_idx,
            w.test_start_idx,
            w.test_end_idx,
        ):
            if not (0 <= idx < n):
                raise ValueError(f"窗口 {w.window_id} 存在越界索引 idx={idx}, n={n}")

        if w.train_end_idx < w.train_start_idx:
            raise ValueError(f"窗口 {w.window_id} train 段长度不合法")
        if w.valid_end_idx < w.valid_start_idx:
            raise ValueError(f"窗口 {w.window_id} valid 段长度不合法")
        if w.test_end_idx < w.test_start_idx:
            raise ValueError(f"窗口 {w.window_id} test 段长度不合法")

        if not (w.train_end_idx < w.valid_start_idx <= w.valid_end_idx < w.test_start_idx <= w.test_end_idx):
            raise ValueError(f"窗口 {w.window_id} 的 train/valid/test 段存在重叠或顺序错误")

        if strict_contiguous:
            if w.valid_start_idx != w.train_end_idx + 1:
                raise ValueError(f"窗口 {w.window_id} valid 未紧接 train")
            if w.test_start_idx != w.valid_end_idx + 1:
                raise ValueError(f"窗口 {w.window_id} test 未紧接 valid")

        if pd.Timestamp(d[w.train_start_idx]) != w.train_start:
            raise ValueError(f"窗口 {w.window_id} train_start 日期与索引不一致")
        if pd.Timestamp(d[w.test_end_idx]) != w.test_end:
            raise ValueError(f"窗口 {w.window_id} test_end 日期与索引不一致")

        if not (w.train_start <= w.train_end < w.valid_start <= w.valid_end < w.test_start <= w.test_end):
            raise ValueError(f"窗口 {w.window_id} 日期不满足严格递增顺序")


def pretty_print_windows(windows: Sequence[WalkForwardWindow]) -> str:
    """
    将窗口列表格式化为易读文本表格（返回字符串，便于 print 或写入日志）。
    """
    if not windows:
        return "（无窗口）"

    rows = []
    for w in windows:
        rows.append(
            {
                "window": w.window_id,
                "train": f"{w.train_start.date()} ~ {w.train_end.date()} ({w.train_end_idx - w.train_start_idx + 1})",
                "valid": f"{w.valid_start.date()} ~ {w.valid_end.date()} ({w.valid_end_idx - w.valid_start_idx + 1})",
                "test": f"{w.test_start.date()} ~ {w.test_end.date()} ({w.test_end_idx - w.test_start_idx + 1})",
            }
        )

    df = pd.DataFrame(rows)
    return df.to_string(index=False)


if __name__ == "__main__":
    demo_dates = pd.date_range("2020-01-01", periods=30, freq="B")
    windows = generate_walk_forward_windows(
        demo_dates, T_train=10, T_valid=5, T_test=5, step_size=5, align_end=True
    )
    validate_walk_forward_windows(windows, demo_dates)
    print(pretty_print_windows(windows))
    print(coverage_report(windows, demo_dates))
