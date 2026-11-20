from __future__ import annotations

import threading
import time

import pytest

from services.pipeline_coordinator import (
    AnalysisPipelineCoordinator,
    PipelineStateConflictError,
    split_serial_nodes,
)


ANALYST_NAMES = ("market", "news", "fundamentals", "industry", "momentum")


def test_analysts_overlap_then_serial_chain_runs_on_caller_thread():
    barrier = threading.Barrier(5)
    lock = threading.Lock()
    analyst_threads = set()
    analyst_ends = []
    serial_calls = []
    caller_thread = threading.get_ident()

    def analyst(name):
        def run(state):
            with lock:
                analyst_threads.add(threading.get_ident())
            barrier.wait(timeout=2)
            time.sleep(0.01)
            with lock:
                analyst_ends.append(name)
            return {f"{name}_report": name}

        return run

    def serial(name):
        def run(state):
            assert len(analyst_ends) == 5
            serial_calls.append((name, threading.get_ident()))
            return {name: name}

        return run

    coordinator = AnalysisPipelineCoordinator(
        analyst_nodes={name: analyst(name) for name in ANALYST_NAMES},
        analyst_field_owners={name: {f"{name}_report"} for name in ANALYST_NAMES},
        serial_nodes=[
            (name, serial(name))
            for name in ("router", "manager", "risk", "final", "reflection")
        ],
    )

    result = coordinator.run({"symbol": "000001"})

    assert len(analyst_threads) == 5
    assert [name for name, _ in serial_calls] == [
        "router",
        "manager",
        "risk",
        "final",
        "reflection",
    ]
    assert {thread_id for _, thread_id in serial_calls} == {caller_thread}
    assert result["market_report"] == "market"
    assert result["reflection"] == "reflection"


def test_analyst_results_emit_on_completion_while_state_merge_stays_deterministic():
    completion_delays = {
        "market": 0.05,
        "news": 0.04,
        "fundamentals": 0.03,
        "industry": 0.02,
        "momentum": 0.01,
    }

    def analyst(name):
        def run(state):
            time.sleep(completion_delays[name])
            return {f"{name}_report": name}

        return run

    completed = []
    coordinator = AnalysisPipelineCoordinator(
        analyst_nodes={name: analyst(name) for name in ANALYST_NAMES},
        analyst_field_owners={name: {f"{name}_report"} for name in ANALYST_NAMES},
        serial_nodes=[],
        on_module_result=lambda name, delta, state: completed.append(name),
    )

    coordinator.run({})

    assert completed == list(reversed(ANALYST_NAMES))


def test_conflicting_analyst_field_ownership_is_rejected():
    coordinator = AnalysisPipelineCoordinator(
        analyst_nodes={"market": lambda state: {"shared": 1}, "news": lambda state: {"shared": 2}},
        analyst_field_owners={"market": {"shared"}, "news": {"shared"}},
        serial_nodes=[],
    )

    with pytest.raises(PipelineStateConflictError, match="shared.*market.*news"):
        coordinator.run({})


def test_serial_nodes_split_after_final_decision():
    nodes = [(name, object()) for name in (
        "router", "manager", "risk_manager", "final_decision",
        "environment_simulation", "reflector", "weekly_reflector",
    )]

    main, postprocessing = split_serial_nodes(nodes)

    assert [name for name, _ in main] == [
        "router", "manager", "risk_manager", "final_decision",
    ]
    assert [name for name, _ in postprocessing] == [
        "environment_simulation", "reflector", "weekly_reflector",
    ]
