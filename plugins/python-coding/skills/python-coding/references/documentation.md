## 7. Documentation

- Use `"""docstrings"""` on every public class, method, and function. Non-trivial module-level helpers that another
  contributor would have to read the implementation to understand also get docstrings.
- **Document the contract, not the implementation.** State invariants, preconditions, what exceptions can be raised,
  ownership, performance constraints — the things the name doesn't already say.
- **Do not write docstrings that restate the code.** `Returns the item count.` above `def count(self) -> int` is noise
  that will drift. The name carries the "what"; comments are for the non-obvious "why" (a workaround, a subtle
  invariant, a performance constraint).
- **Don't reference tickets or PRs** in code (`# Added for JIRA-123`). Those rot. Put context in commit messages and PR
  descriptions; if a workaround needs explaining, write the _why_ directly.
- Keep docstrings present-tense and declarative: "Returns the …" not "Will return the …". Document each protocol method
  individually.

```python
class BridgeContext:
    """Live context that hosts agent-exposed tools.

    Hold one BridgeContext per logical session. Inject tools with
    inject() before evaluating any script that references them.
    """

    async def evaluate(self, script: str) -> Value:
        """Evaluate script in the underlying context.

        Raises:
            BridgeError: if the script raises or the context is invalid.
        """
        ...
```

---

