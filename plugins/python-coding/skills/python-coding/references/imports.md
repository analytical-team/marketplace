## 13. Imports

- Group imports in this order, with one blank line between groups:
  1. Standard library (`import asyncio`, `from typing import Protocol`)
  2. Third-party (`import httpx2`)
  3. Your own modules (`from .note_store import NoteStore`)
- **`from __future__ import annotations`** at the top of every file — it enables forward references and defers
  annotation evaluation cheaply.
- Don't import what you don't use — `ruff` and `mypy` will flag it.
- Never use wildcard imports (`from module import *`) in non-`__init__.py` files. In `__init__.py`, wildcards are
  acceptable only when the module explicitly defines `__all__`.
- Avoid import-time side effects. A module that runs code on import (opens sockets, writes files, mutates global state)
  is nearly impossible to test and fragile to import order.

---

