## 9. Error handling

Errors are **first-class API surface**, not afterthoughts. Each area defines its own exception hierarchy and documents
what a function raises.

### The default shape: a typed exception hierarchy

For most code, a small exception class per area is all you need:

```python
from dataclasses import dataclass


class RAGClientError(Exception):
    """Base class for all RAG client errors."""


@dataclass
class TransportFailure(RAGClientError):
    underlying: Exception


@dataclass
class DecodingFailure(RAGClientError):
    reason: str


class Unauthorized(RAGClientError):
    pass


@dataclass
class RateLimited(RAGClientError):
    retry_after: float | None
```

- **Subclasses describe failure modes**, not error sites. A class maps to a thing that can go wrong, not a line of code.
- **Dataclass fields carry context** — use them; don't shove everything into `str(e)`.
- **Preserve the cause.** Use `raise MyError(...) from original` to chain exceptions so the traceback shows both.

### Annotate raises in docstrings

Python has no typed throws, so document exceptions in docstrings:

```python
async def load_note(self, note_id: str) -> Note:
    """Load note by ID.

    Raises:
        NoteNotFound: if no note exists with the given ID.
        StorageError: if the underlying store is unavailable.
    """
```

### Adapt foreign exceptions at the boundary

Never let a third-party exception type escape your area's surface. Catch it at the boundary and wrap it:

```python
try:
    response = await http_client.get(url)
except httpx2.HTTPError as exc:
    raise TransportFailure(underlying=exc) from exc
```

### Map the area's exception hierarchy to the surface in one function

Domain code raises its typed exceptions and stays presentation-neutral (§6: error rendering is chosen by the surface).
The surface translates them in a single pure function — `collection_http_error(e) -> HTTPException`,
`floodgate_http_status(e) -> int` — that maps each failure mode to its status, called at the route boundary. One
function per area _is_ the whole mapping: greppable, testable without a server, and the one place to look when a status
is wrong.

```python
def collection_http_error(e: CollectionError) -> HTTPException:
    if isinstance(e, ObjectNotFound):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, InvalidObjectData):
        return HTTPException(status_code=400, detail=e.reason)
    return HTTPException(status_code=400, detail=str(e))
```

### Keep messages caller-safe, and put the blame in the status code

What you return to a caller is API surface, not a debugging aid.

- **Only the caller's own fault is a 4xx.** A bad request or an exceeded rate limit is the caller's concern (400/429)
  and passes through. A failure that is really your side — a missing credential, an unreachable backend, a
  misconfiguration — is a 5xx (502/503) even when the upstream library reported it as 401/403, because nothing the
  caller sent was wrong.
- **Never leak internal detail.** Extract a bounded, caller-safe message (a known field, a truncated body) instead of
  forwarding a raw upstream error or an internal value. Log the full detail at the catch site; return only what a caller
  can act on.

```python
def floodgate_http_status(error: FloodgateError) -> int:
    # Bad request (400) and rate/budget (429) are the caller's concern and pass
    # through; auth/cert failures are server-side misconfiguration, so 502.
    if error.status in (400, 429):
        return error.status
    return 502
```

### When errors cross a foreign boundary

If errors must cross into a non-Python consumer (a wire protocol, a remote API), define an error protocol that adds the
wire shape:

```python
from typing import Protocol


class WireError(Protocol):
    @property
    def code(self) -> str: ...  # stable, dotted, lowercase: "note.not_found"
    @property
    def message(self) -> str: ...  # human-readable, may change
    @property
    def context(self) -> dict[str, object]: ...  # snake_case keys, JSON-safe values
```

`code` is what consumers match on — keep it stable and scoped. `message` is for humans and can change. **Default to the
simple exception hierarchy** — only reach for the wire protocol when you actually have a foreign boundary.

### Assertions vs. exceptions

Use assertions for things that **should never happen** in correct code:

- `assert condition, "message"` for debug-only invariant checks (stripped with `-O`). Never use `assert` for input
  validation.
- Raise `ValueError` for precondition violations on public API inputs.
- Use `raise RuntimeError("unreachable")` for truly unreachable branches — but prefer restructuring so the impossible
  state is unrepresentable.

If a condition can be triggered by user input or external state, it is **not** an assertion — raise a typed exception.

### Don't

- **Don't use bare `except Exception:`** in new code — name what you catch.
- **Don't swallow exceptions** (`except SomeError: pass`). The caller can't tell something failed. Let it propagate, or
  transform into a meaningful return shape (`None`) when "missing" is genuinely not exceptional.
- **Don't put logging inside an exception class.** Exceptions describe failure; logging belongs at the catch site.
- **Don't use `sys.exit()` inside library code.** Raise an exception; let the CLI boundary decide what to do.

---

