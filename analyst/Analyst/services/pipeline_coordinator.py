"""Explicit fan-out/fan-in coordination for the analysis model pipeline."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

State = dict[str, Any]
Node = Callable[[State], Mapping[str, Any]]
ModuleResultCallback = Callable[[str, State, State], None]


class PipelineStateConflictError(RuntimeError):
    """Raised when multiple analysts claim the same output field."""


@dataclass(frozen=True)
class SerialNode:
    name: str
    function: Node


class AnalysisPipelineCoordinator:
    """Run analyst nodes concurrently and all downstream nodes serially."""

    def __init__(
        self,
        *,
        analyst_nodes: Mapping[str, Node],
        analyst_field_owners: Mapping[str, set[str]],
        serial_nodes: Sequence[tuple[str, Node] | SerialNode],
        on_module_result: ModuleResultCallback | None = None,
    ) -> None:
        self._analyst_nodes = dict(analyst_nodes)
        self._analyst_field_owners = {
            name: set(fields) for name, fields in analyst_field_owners.items()
        }
        self._serial_nodes = [
            item if isinstance(item, SerialNode) else SerialNode(*item)
            for item in serial_nodes
        ]
        self._on_module_result = on_module_result

    def _validate_ownership(self) -> None:
        owner_by_field: dict[str, str] = {}
        for analyst_name in self._analyst_nodes:
            for field in self._analyst_field_owners.get(analyst_name, set()):
                previous = owner_by_field.get(field)
                if previous is not None:
                    raise PipelineStateConflictError(
                        f"field {field!r} is owned by both {previous!r} and {analyst_name!r}"
                    )
                owner_by_field[field] = analyst_name

    def _run_analyst(self, name: str, initial_state: State) -> State:
        result = dict(self._analyst_nodes[name](dict(initial_state)))
        allowed = self._analyst_field_owners.get(name, set())
        unexpected = set(result) - allowed
        if unexpected:
            fields = ", ".join(sorted(unexpected))
            raise PipelineStateConflictError(
                f"analyst {name!r} returned fields it does not own: {fields}"
            )
        return result

    def run(self, initial_state: Mapping[str, Any]) -> State:
        self._validate_ownership()
        state = dict(initial_state)
        futures: dict[str, Future[State]] = {}
        with ThreadPoolExecutor(
            max_workers=5, thread_name_prefix="analyst"
        ) as analyst_executor:
            for name in self._analyst_nodes:
                futures[name] = analyst_executor.submit(
                    self._run_analyst, name, dict(state)
                )
            try:
                names_by_future = {future: name for name, future in futures.items()}
                deltas = {}
                for future in as_completed(names_by_future):
                    name = names_by_future[future]
                    delta = future.result()
                    deltas[name] = delta
                    if self._on_module_result is not None:
                        self._on_module_result(name, dict(delta), dict(state))
            except Exception:
                for future in futures.values():
                    future.cancel()
                raise

        for name in self._analyst_nodes:
            delta = deltas[name]
            state.update(delta)

        for node in self._serial_nodes:
            delta = dict(node.function(dict(state)))
            state.update(delta)
            if self._on_module_result is not None:
                self._on_module_result(node.name, dict(delta), dict(state))
        return state
def split_serial_nodes(serial_nodes, boundary: str = "final_decision"):
    """Split an ordered node list, keeping the boundary in the main pipeline."""
    for index, (name, _) in enumerate(serial_nodes):
        if name == boundary:
            return list(serial_nodes[: index + 1]), list(serial_nodes[index + 1 :])
    raise ValueError(f"serial pipeline boundary not found: {boundary}")
