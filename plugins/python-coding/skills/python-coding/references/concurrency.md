## 8. Concurrency

Under `asyncio`, this is a **correctness** domain. The model in one paragraph: use **async classes with explicit locks**
to encapsulate mutable shared state, **immutable dataclasses** to move data between coroutines, and **structured
concurrency** (`TaskGroup`) for async work.

### Async-safe classes

Use an async class with an `asyncio.Lock` when you have **mutable state** that must be safe across concurrent callers.

- Keep the class surface small — every `async def` is a potential contention point, and chatty classes degrade
  throughput.
- Prefer returning immutable dataclasses or copies from methods rather than references to internal state.
- Document the concurrency contract in the class docstring: what state is guarded, what operations are atomic.

```python
import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class BlobHandle:
    blob_id: str


class BlobStore:
    """Thread-safe in-memory blob store.

    All methods are safe to call concurrently. Mutations are serialized
    via an internal asyncio.Lock.
    """

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.blobs: dict[str, bytes] = {}

    async def store(self, data: bytes) -> BlobHandle:
        handle = BlobHandle(blob_id=str(id(data)))
        async with self.lock:
            self.blobs[handle.blob_id] = data
        return handle

    async def resolve(self, handle: BlobHandle) -> bytes:
        async with self.lock:
            return self.blobs[handle.blob_id]
```

### Immutability

Mark data transfer objects with `@dataclass(frozen=True)`. A frozen dataclass is safe to pass between coroutines without
copying. Mutable dataclasses and plain dicts are not safe to share without synchronization.

### Structured concurrency

- **Prefer `asyncio.TaskGroup`** over unstructured tasks when the work has a clear parent. You get cancellation, error
  propagation, and scope containment for free.
- **Use `asyncio.gather`** for a fixed set of independent awaitables that must all complete. Prefer
  `return_exceptions=False` (the default) — let errors propagate instead of collecting them silently.
- Reach for `asyncio.create_task` (unstructured) only when the lifetime truly outlives the calling scope. Document the
  reason inline and store the task in an instance attribute so it can be cancelled explicitly.
- `asyncio.ensure_future` should never appear in new code — use `create_task`.

```python
async def fetch_all(urls: list[str]) -> list[Response]:
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(fetch(url)) for url in urls]
    return [task.result() for task in tasks]
```

### `asyncio.Queue` over polling

For producer/consumer coordination, use `asyncio.Queue`. Never busy-loop or `await asyncio.sleep(0)` in a spin-wait — it
burns CPU and starves the event loop.

### Blocking I/O

Blocking calls inside a coroutine stall the entire event loop. When you must call a blocking library:

```python
result = await asyncio.to_thread(blocking_library_call, arg)
```

Never call `time.sleep` in a coroutine — use `await asyncio.sleep(seconds)`.

### Cancellation

- Honor cancellation: check `asyncio.current_task().cancelled()` or let `asyncio.CancelledError` propagate at natural
  suspension points.
- Never `except asyncio.CancelledError: pass` — swallowing it breaks structured cancellation.
- When a class owns a long-running task, give it an explicit `cancel()` method rather than relying on garbage collection
  timing.

```python
class Worker:
    def __init__(self) -> None:
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.task = asyncio.create_task(self.run())  # unstructured: outlives caller

    def cancel(self) -> None:
        if self.task is not None:
            self.task.cancel()

    async def run(self) -> None:
        while True:
            await asyncio.sleep(1)
            await self.do_work()
```

---

