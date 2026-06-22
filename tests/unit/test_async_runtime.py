import threading
import time

from extension.workflow import GenerationRuntime, RuntimeEvent


def test_runtime_returns_the_active_generation_result() -> None:
    runtime: GenerationRuntime[int] = GenerationRuntime()

    generation_id = runtime.start(lambda token: 42)
    event = _wait_for_event(runtime)

    assert event == RuntimeEvent(generation_id, value=42)
    assert runtime.is_running is False


def test_new_generation_discards_a_superseded_result() -> None:
    runtime: GenerationRuntime[str] = GenerationRuntime()
    first_started = threading.Event()
    release_first = threading.Event()

    def first_work(token: object) -> str:
        first_started.set()
        release_first.wait(timeout=2.0)
        return "old"

    runtime.start(first_work)
    assert first_started.wait(timeout=1.0)
    current_generation = runtime.start(lambda token: "current")

    release_first.set()
    event = _wait_for_event(runtime)

    assert event == RuntimeEvent(current_generation, value="current")
    assert runtime.poll() == ()


def test_cancel_and_shutdown_discard_worker_results() -> None:
    runtime: GenerationRuntime[str] = GenerationRuntime()
    release = threading.Event()
    runtime.start(lambda token: (release.wait(timeout=2.0), "result")[1])

    assert runtime.cancel_active() is not None
    release.set()
    time.sleep(0.02)
    assert runtime.poll() == ()

    runtime.shutdown()
    assert runtime.is_running is False


def _wait_for_event[T](runtime: GenerationRuntime[T]) -> RuntimeEvent[T]:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        events = runtime.poll()
        if events:
            return events[0]
        time.sleep(0.005)
    raise AssertionError("Background runtime did not produce an event.")
