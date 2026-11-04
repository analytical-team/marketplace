## 1. Language baseline

- **Target Python 3.12+ with strict type checking.** Run `mypy --strict` (or `pyright` in strict mode) as part of CI.
  Treat type errors as correctness concerns, not warnings to suppress.
- **Use modern Python throughout:** `async`/`await`, `asyncio.TaskGroup`, `typing.Protocol`, `dataclasses`, `match`
  statements, `ExceptionGroup`. Do not introduce new callback-based concurrency unless bridging a library that requires
  it.
- **Do not use `threading`, `multiprocessing`, or `concurrent.futures` in new code.** `asyncio` gives the same
  capabilities with less ceremony and composable structured concurrency. The only acceptable use is bridging a blocking
  I/O library that has no async alternative — wrap it with `asyncio.to_thread`, not raw threads.
- **Do not use `queue.Queue` for inter-task coordination.** Use `asyncio.Queue` when tasks need to hand off work.
- **Annotate everything.** Function signatures, class attributes, and return types get type annotations. Use
  `from __future__ import annotations` at the top of files to enable forward references cheaply.

---

