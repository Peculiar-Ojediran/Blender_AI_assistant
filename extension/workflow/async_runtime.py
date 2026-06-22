"""Run generation-scoped work away from Blender's main thread."""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty, SimpleQueue


class RuntimeCancelledError(RuntimeError):
    """Raised inside workers when their logical generation is canceled."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise RuntimeCancelledError("The background generation was canceled.")


@dataclass(frozen=True, slots=True)
class RuntimeEvent[T]:
    generation_id: int
    value: T | None = None
    error: Exception | None = None


class GenerationRuntime[T]:
    """Run one logical job generation and discard stale worker results."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: SimpleQueue[RuntimeEvent[T]] = SimpleQueue()
        self._next_generation = 0
        self._active_generation: int | None = None
        self._active_token: CancellationToken | None = None
        self._pending: tuple[int, CancellationToken, Callable[[CancellationToken], T]] | None = None
        self._worker_running = False
        self._shutdown = False

    def start(self, work: Callable[[CancellationToken], T]) -> int:
        launch: tuple[int, CancellationToken, Callable[[CancellationToken], T]] | None = None
        with self._lock:
            if self._shutdown:
                raise RuntimeError("The background runtime has been shut down.")
            if self._active_token is not None:
                self._active_token.cancel()
            self._next_generation += 1
            generation_id = self._next_generation
            token = CancellationToken()
            self._active_generation = generation_id
            self._active_token = token

            if self._worker_running:
                if self._pending is not None:
                    self._pending[1].cancel()
                self._pending = (generation_id, token, work)
            else:
                self._worker_running = True
                launch = (generation_id, token, work)

        if launch is not None:
            self._launch(*launch)
        return generation_id

    def cancel_active(self) -> int | None:
        with self._lock:
            generation_id = self._active_generation
            if self._active_token is not None:
                self._active_token.cancel()
            if self._pending is not None and self._pending[0] == generation_id:
                self._pending[1].cancel()
                self._pending = None
            self._active_generation = None
            self._active_token = None
            return generation_id

    def poll(self) -> tuple[RuntimeEvent[T], ...]:
        accepted: list[RuntimeEvent[T]] = []
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

    @property
    def has_worker(self) -> bool:
        with self._lock:
            return self._worker_running

    def shutdown(self) -> None:
        with self._lock:
            self._shutdown = True
            if self._active_token is not None:
                self._active_token.cancel()
            if self._pending is not None:
                self._pending[1].cancel()
                self._pending = None
            self._active_generation = None
            self._active_token = None
        self.poll()

    def _launch(
        self,
        generation_id: int,
        token: CancellationToken,
        work: Callable[[CancellationToken], T],
    ) -> None:
        worker = threading.Thread(
            target=self._run,
            args=(generation_id, token, work),
            name=f"blender-ai-planning-{generation_id}",
            daemon=True,
        )
        worker.start()

    def _run(
        self,
        generation_id: int,
        token: CancellationToken,
        work: Callable[[CancellationToken], T],
    ) -> None:
        try:
            token.raise_if_cancelled()
            event = RuntimeEvent(generation_id, value=work(token))
            token.raise_if_cancelled()
        except Exception as error:
            event = RuntimeEvent[T](generation_id, error=error)
        self._events.put(event)

        launch: tuple[int, CancellationToken, Callable[[CancellationToken], T]] | None = None
        with self._lock:
            if self._shutdown:
                self._pending = None
                self._worker_running = False
            elif self._pending is not None:
                launch = self._pending
                self._pending = None
            else:
                self._worker_running = False

        if launch is not None:
            self._launch(*launch)
