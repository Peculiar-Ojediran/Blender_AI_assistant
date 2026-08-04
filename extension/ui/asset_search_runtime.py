"""Background runtime for candidate asset search and URL inspection."""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty, SimpleQueue
from typing import Any, Literal

from ..internet.models import AssetDiscoveryResult, AssetSearchRequest, LinkInspectionResult
from ..internet.policy import InternetDownloadPolicy
from ..internet.search_provider import AssetDiscoveryProvider
from ..internet.url_inspector import inspect_asset_url
from ..workflow.async_runtime import CancellationToken
from .asset_search import (
    apply_asset_discovery_result,
    apply_asset_search_error,
    apply_candidate_inspection_result,
)

POLL_INTERVAL_SECONDS = 0.2

type AssetSearchEventKind = Literal["search", "inspection"]


@dataclass(frozen=True, slots=True)
class AssetInspectionJobResult:
    candidate_index: int
    direct_url: str
    inspection: LinkInspectionResult


@dataclass(frozen=True, slots=True)
class AssetSearchEvent:
    generation_id: int
    kind: AssetSearchEventKind
    value: Any | None = None
    error: Exception | None = None


class AssetSearchCoordinator:
    """Own background asset-search generations and discard stale results."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: SimpleQueue[AssetSearchEvent] = SimpleQueue()
        self._next_generation = 0
        self._active_generation: int | None = None
        self._active_token: CancellationToken | None = None
        self._shutdown = False

    def start_search(self, work: Callable[[CancellationToken], Any]) -> int:
        return self._start("search", work)

    def start_inspection(self, work: Callable[[CancellationToken], Any]) -> int:
        return self._start("inspection", work)

    def cancel(self) -> int | None:
        with self._lock:
            generation_id = self._active_generation
            if self._active_token is not None:
                self._active_token.cancel()
            self._active_generation = None
            self._active_token = None
            return generation_id

    def inject_result(
        self,
        generation_id: int,
        value: Any,
        *,
        kind: AssetSearchEventKind = "search",
    ) -> None:
        self._events.put(AssetSearchEvent(generation_id, kind, value=value))

    def inject_error(
        self,
        generation_id: int,
        error: Exception,
        *,
        kind: AssetSearchEventKind = "search",
    ) -> None:
        self._events.put(AssetSearchEvent(generation_id, kind, error=error))

    def poll(self) -> tuple[AssetSearchEvent, ...]:
        accepted: list[AssetSearchEvent] = []
        while True:
            try:
                event = self._events.get_nowait()
            except Empty:
                break
            with self._lock:
                if event.generation_id != self._active_generation or self._shutdown:
                    continue
                self._active_generation = None
                self._active_token = None
            accepted.append(event)
        return tuple(accepted)

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._active_generation is not None and not self._shutdown

    def shutdown(self) -> None:
        with self._lock:
            self._shutdown = True
            if self._active_token is not None:
                self._active_token.cancel()
            self._active_generation = None
            self._active_token = None
        self.poll()

    def _start(
        self,
        kind: AssetSearchEventKind,
        work: Callable[[CancellationToken], Any],
    ) -> int:
        with self._lock:
            if self._shutdown:
                raise RuntimeError("The asset search runtime has been shut down.")
            if self._active_token is not None:
                self._active_token.cancel()
            self._next_generation += 1
            generation_id = self._next_generation
            token = CancellationToken()
            self._active_generation = generation_id
            self._active_token = token

        worker = threading.Thread(
            target=self._run,
            args=(generation_id, kind, token, work),
            name=f"blender-ai-asset-search-{generation_id}",
            daemon=True,
        )
        worker.start()
        return generation_id

    def _run(
        self,
        generation_id: int,
        kind: AssetSearchEventKind,
        token: CancellationToken,
        work: Callable[[CancellationToken], Any],
    ) -> None:
        try:
            token.raise_if_cancelled()
            value = work(token)
            token.raise_if_cancelled()
            event = AssetSearchEvent(generation_id, kind, value=value)
        except Exception as error:
            event = AssetSearchEvent(generation_id, kind, error=error)
        self._events.put(event)


_coordinator: AssetSearchCoordinator | None = None


def register_asset_search_runtime() -> None:
    global _coordinator

    import bpy

    if _coordinator is not None:
        _coordinator.shutdown()
    _coordinator = AssetSearchCoordinator()
    if not bpy.app.timers.is_registered(_poll_timer):
        bpy.app.timers.register(
            _poll_timer,
            first_interval=POLL_INTERVAL_SECONDS,
            persistent=True,
        )


def unregister_asset_search_runtime() -> None:
    global _coordinator

    import bpy

    if bpy.app.timers.is_registered(_poll_timer):
        bpy.app.timers.unregister(_poll_timer)
    if _coordinator is not None:
        _coordinator.shutdown()
        _coordinator = None


def start_asset_search_job(
    *,
    provider: AssetDiscoveryProvider,
    request: AssetSearchRequest,
) -> int:
    def search(token: CancellationToken) -> AssetDiscoveryResult:
        token.raise_if_cancelled()
        result = provider.search(request)
        token.raise_if_cancelled()
        return result

    return _get_coordinator().start_search(search)


def start_asset_inspection_job(
    *,
    candidate_index: int,
    direct_url: str,
    policy: InternetDownloadPolicy,
) -> int:
    def inspect(token: CancellationToken) -> AssetInspectionJobResult:
        token.raise_if_cancelled()
        result = inspect_asset_url(direct_url, policy=policy)
        token.raise_if_cancelled()
        return AssetInspectionJobResult(candidate_index, direct_url, result)

    return _get_coordinator().start_inspection(inspect)


def cancel_asset_search_job() -> int | None:
    return _get_coordinator().cancel()


def process_asset_search_events(context: Any) -> int:
    state = context.window_manager.blender_ai_state
    processed = 0
    for event in _get_coordinator().poll():
        processed += 1
        if event.error is not None:
            apply_asset_search_error(state, event.error, operation=event.kind)
            continue
        if event.kind == "search" and isinstance(event.value, AssetDiscoveryResult):
            apply_asset_discovery_result(state, event.value)
            continue
        if event.kind == "inspection" and isinstance(event.value, AssetInspectionJobResult):
            apply_candidate_inspection_result(
                state,
                event.value.inspection,
                candidate_index=event.value.candidate_index,
            )
    return processed


def _poll_timer() -> float:
    import bpy

    window_manager = getattr(bpy.context, "window_manager", None)
    try:
        if window_manager is not None and hasattr(window_manager, "blender_ai_state"):
            process_asset_search_events(bpy.context)
    except Exception:
        traceback.print_exc()
    return POLL_INTERVAL_SECONDS


def _get_coordinator() -> AssetSearchCoordinator:
    if _coordinator is None:
        raise RuntimeError("The asset search runtime is not registered.")
    return _coordinator
