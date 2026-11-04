## 12. Dependencies

The default stance is **standard library only.** Every dependency you add becomes a dependency for everyone who adopts
your code: it enters their environment, adds install time and disk size, and ties them to a maintainer and a license.

A new dependency earns its way in by clearing all of:

- **Concrete justification** — name the capability you'd otherwise build and maintain. "It's convenient" doesn't count.
- **No reasonable stdlib path** — prefer `asyncio`, `dataclasses`, `typing`, `json`, `pathlib`, `logging`, `re` over
  third-party alternatives.
- **Stable provenance** — actively maintained, clear release discipline. Avoid one-person and abandoned projects.
- **Bounded scope** — a library that does exactly the one thing you need beats one that brings ten you don't.

Scope each dependency to the area that uses it with optional extras or a separate package, not a codebase-wide install.
Test-only dependencies face the same questions at a slightly lower bar. Keep an inventory (`AUDIT.md` or similar) and
update it in the same change that adds or removes a dependency.

---

