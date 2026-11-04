## 5. Visibility & API design

Python has no enforced access control, so **this guide substitutes a strict naming rule: every name is public.** There
are no leading-underscore names, no double-underscore mangling, and no "internal" convention. If something genuinely
should not be part of the API, restructure so it doesn't need to exist as a name at all — move it inline, merge it into
the caller, or extract it to a helper class with its own clean surface.

**Why:** underscore-prefix "privacy" is unenforceable, ignored by IDEs and agents, and communicates "don't touch"
without enforcing anything. The real answer is a clean public surface, not a naming convention that pretends to hide
things.

### `__all__`

Declare `__all__` in every module that is part of a public package surface. It is the true visibility boundary — what
callers can rely on. Keep it intentionally small. Anything absent from `__all__` is treated as unstable even if
technically importable.

### Lead with protocols, not concrete types

This is the load-bearing design principle for any code meant to be **substitutable, testable, or reusable**.

- A module's public surface should be dominated by **`typing.Protocol` types and dataclasses**, not concrete classes.
  The concrete type can still be exported (so consumers use it out of the box), but the thing they _annotate their
  dependencies against_ is the protocol.
- Protocols have a **single, focused responsibility.** If adopters routinely implement only half of a protocol, split
  it.
- Use `typing.Protocol` (structural subtyping) by default — callers do not need to import or inherit from your protocol
  to satisfy it. Reserve `abc.ABC` (nominal subtyping) when you need to enforce the inheritance chain or provide
  meaningful default implementations.
- Default method implementations on `Protocol` subclasses are encouraged for _ergonomic_ methods, but not for behavior
  an adopter would reasonably want to override.

```python
from typing import Protocol, runtime_checkable


@runtime_checkable
class NoteStore(Protocol):
    async def load(self, note_id: str) -> Note: ...
    async def save(self, note: Note) -> None: ...


# A default implementation callers can use out of the box —
# but the type they annotate is `NoteStore`, not this class.
class FileNoteStore:
    async def load(self, note_id: str) -> Note: ...
    async def save(self, note: Note) -> None: ...
```

**Why:** a concrete-type-only public API forces forks. A protocol seam invites substitution and makes the code testable
with a fake.

### Keep modules from depending on each other's internals

Independent areas of a codebase should communicate only through **protocols and dataclasses** — never through shared
global state, singletons, or module-level symbols that happen to be importable. A dependency that looks harmless inside
the codebase becomes a forced dependency for anyone who wanted only one piece. If two areas need something shared, hoist
it cleanly above both and keep it small.

---

