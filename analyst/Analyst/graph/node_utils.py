"""Graph 节点耗时日志与 LLM 并发控制。"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, TypeVar

T = TypeVar("T")

_analyst_semaphore: threading.Semaphore | None = None
_semaphore_lock = threading.Lock()


def get_analyst_concurrency_limit() -> int:
    raw = os.getenv("LLM_ANALYST_CONCURRENCY", "5").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 5
    return max(1, min(value, 5))


def set_analyst_concurrency_limit(limit: int) -> None:
    """每次分析前按配置重置分析师 LLM 并发上限。"""
    global _analyst_semaphore
    value = max(1, min(int(limit), 5))
    with _semaphore_lock:
        _analyst_semaphore = threading.Semaphore(value)


def _get_analyst_semaphore() -> threading.Semaphore:
    global _analyst_semaphore
    with _semaphore_lock:
        if _analyst_semaphore is None:
            _analyst_semaphore = threading.Semaphore(get_analyst_concurrency_limit())
        return _analyst_semaphore


def wrap_node(node_name: str, node_fn: Callable[..., T], *, limit_analyst_concurrency: bool = False) -> Callable[..., T]:
    """为 graph 节点包装 start/done/elapsed 日志。"""

    def wrapped(state, *args, **kwargs):
        start = time.perf_counter()
        print(f"[{node_name}] start", flush=True)
        try:
            if limit_analyst_concurrency:
                with _get_analyst_semaphore():
                    result = node_fn(state, *args, **kwargs)
            else:
                result = node_fn(state, *args, **kwargs)
        except Exception:
            elapsed = time.perf_counter() - start
            print(f"[{node_name}] error elapsed={elapsed:.2f}s", flush=True)
            raise

        elapsed = time.perf_counter() - start
        print(f"[{node_name}] done elapsed={elapsed:.2f}s", flush=True)
        return result

    wrapped.__name__ = getattr(node_fn, "__name__", node_name)
    return wrapped
