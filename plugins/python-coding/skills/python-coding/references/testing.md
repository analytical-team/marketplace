## 11. Testing

### Tests are for tomorrow

**Checked-in tests exist to protect important behavior as the code changes.** Proving that code works today can be done
by hand. The durable value of an automated test is that it can be run tomorrow, after a refactor, a dependency or
compiler upgrade, or a change from someone unfamiliar with the system, and detect whether a behavior we care about has
regressed. Tests make otherwise risky change routine in proportion to how faithfully they exercise the application.

Automated tests are required for core application behavior. A behavior-changing fix is done when the relevant suite is
green and a regression test would fail without the fix. A new feature is done when its consequential behavior and
failure modes are protected. Do not add a test merely because a function exists or a line is uncovered: every test must
earn its long-term maintenance cost by protecting a real contract, invariant, edge case, regression, or user workflow.
Coverage is a way to find unexamined code, not a target and not evidence that the application works.

Tests live in `tests/` at the repo root (§3), outside the package.

### Ask what a test is actually for

Before writing a unit test, ask what it's actually for. Most unit tests don't find bugs — they mark territory, freezing
code in place so nobody casually rewrites it; if that is all this one does, skip it. Don't write tests that just
re-hardcode "this ran once and produced X" as correct — that's not verification, it's superstition. If correctness
genuinely matters, use randomized/property-based inputs against a stable API instead of a couple of hand-picked cases;
if the logic doesn't matter much, don't test it just to hit a coverage habit. And don't over-mock to isolate a "unit" —
if the test only checks that your mocks agree with your mocks, it's not testing anything real. Rather test against real
inputs and real outputs. **Write a test because a specific failure mode worries you, not because the code exists.**

### Tests are documentation

**A test is the executable example of how the code is meant to be used.** Someone who wants to know how to construct a
`BlobStore`, what a `Settings` tree looks like when populated, or what an eval script expects should be able to open
`tests/` and read it — and what they read is guaranteed current, because it runs in CI. Write with that reader in mind:

- **Name the behavior, not the function.** `test_store_returns_error_when_key_missing`, not `test_store_2`. Read the
  test names alone and you should get a specification of the area.
- **Make the body readable top to bottom** — construct, act, assert. Prefer a few explicit lines over a clever
  parametrization that no reader can follow back to a concrete case.
- **Favor a realistic setup over a minimal one.** A test that builds the object the way production builds it teaches the
  reader something; one that pokes a half-initialized instance teaches them a shortcut that doesn't work.
- **Keep the docstring where the "why" is non-obvious** — what invariant this pins down, why this edge case exists.

### Test real functionality; never mock it

**Do not use `unittest.mock`, `MagicMock`, `monkeypatch` of internals, or hand-written stand-ins that merely record
calls.** A mock asserts that your code called the API the way you _believed_ it works. When that belief is wrong — the
real client raises a different exception, returns a differently-shaped payload, coerces a type, paginates, or has since
changed — the mock keeps passing and the test is worse than nothing: it is a green light with no signal behind it.

The line is **replacing behavior with an assumption**, not any use of a fixture. Arranging real state is fine and
encouraged: `tmp_path` for a real file on disk, `monkeypatch.setenv` to set a real environment variable (which also
scopes the change to the test), a temporary database, or a local server on a free port. Those set up the world and then
let the real code run. What's banned is substituting a fake for a collaborator so that the integration being asserted
never executes.

Test against the real thing instead:

- **Framework test clients.** When a framework provides a test client, prefer it to calling route functions directly.
  Drive a FastAPI application through `TestClient` (or `httpx2.AsyncClient` with ASGI transport for async tests), for
  example, so routing, serialization, validation, middleware, lifespan, dependency wiring, and error handling all run.
  The test client is a real caller of the application boundary, not a mock of application behavior.
- **Real test databases.** Database-backed behavior always runs against a real, isolated test database using the same
  engine, schema, constraints, and migrations as production. Use an ephemeral database, container, isolated schema, or
  per-test transaction. Do not replace Postgres with SQLite, a dictionary, or an in-memory repository: doing so skips
  the query semantics, transactions, constraints, and driver behavior that the test is supposed to protect.
- **Real clients.** Use the production client implementation against a real local or CI instance whenever a behavior
  crosses a process or service boundary. Do not assert only that a method was called.
- **Real data.** Exercise real fixtures from `data/` (or a small committed sample) rather than synthetic records shaped
  to make the assertion pass. Real data carries the encodings, nulls, duplicates, and oddities that synthetic data
  invents its way around.
- **Skip, don't fake, when a resource is genuinely absent.** If a test needs weights or a corpus that a fresh clone
  doesn't have, mark it skipped with a message naming the script that fetches it. A skipped test tells the truth; a
  mocked one lies. Keep the suite green on a fresh clone this way.
- **For a genuinely external, paid, or non-deterministic dependency**, run a tagged integration test against the real
  service when credentials and the service are available; otherwise skip it with the reason. Do not turn a replayed
  response into proof that the current integration still works.

This is a deliberate trade: the suite is slower and needs more setup than a mock-based one. Take that trade. The purpose
of a test is to tell you the system works, and only the real system can answer that.

### Prefer the smallest scope that preserves the real signal

Cost is a tiebreaker among tests that protect the same behavior — never a reason to substitute a mock or bypass an
important application boundary.

1. **Focused tests** are appropriate when a domain invariant can be exercised completely through a real object with no
   meaningful collaborator or framework boundary.
2. **Integration tests** are the default when behavior emerges from pieces interacting: an API with its database, a
   parser with real files, or a service with its production client.
3. **End-to-end tests** protect the few core workflows that must survive changes across components, including running a
   numbered script end to end on representative data.

Do not force an area to have all three kinds. Choose tests by the behavior at risk. A narrow test that bypasses the very
boundary where the behavior emerges is cheap but has no useful signal.

### Prefer edge cases

The happy path is the case you already had in mind while writing the code, so it is the least likely to be broken and
the least informative to test. **Spend your test budget on the boundaries**, where real defects live:

- **Empty and singular** — zero rows, an empty string, a one-element batch, a file with only a header.
- **Boundaries and off-by-one** — exactly at a limit, one under, one over; the first and last element; a sequence
  exactly as long as the window it is chunked into.
- **Malformed and hostile input** — invalid UTF-8, truncated files, a duplicate key, a value of the wrong type, input
  that trips the parser rules of §10.
- **Absent and null** — a missing optional resource, an unset setting, `None` where a value usually is.
- **Extremes** — a very large input, a unicode-heavy string, a deeply nested structure, a number at the type's limit.
- **Repetition and concurrency** — calling twice (is it idempotent?), resuming after an interruption, concurrent callers
  (§8).

Cover the happy path once, to document intended use; then write the cases that would actually break.

### Do not write obvious tests

**Do not test a simple function merely by restating its implementation with literals.** Tests for getters, field
assignment, direct arithmetic, enum values, dataclass construction, or a one-branch wrapper usually verify nothing
beyond Python itself. The same applies to tests whose expected result is obvious from the setup and that cannot fail
during a realistic refactor.

This includes **fake Protocol implementations written only to prove the protocol is satisfiable.** A throwaway class
that implements `Analyzer` or `Rewriter` with a hardcoded body, paired with a test that asserts the class returns what
its own hardcoded body says, proves nothing beyond what `mypy --strict` already proved by type-checking the assignment
`x: Analyzer = FakeAnalyzer()`. Structural conformance is a type-checker's job, not a pytest job. Write a fake
implementation only when it exercises real logic the module under test owns (a real `to_dict`/`from_dict` round-trip, a
real state machine) — never merely to give a Protocol "test coverage" before a real implementation exists.

Instead, protect the core logic and the cases where an implementation can plausibly be wrong: business invariants, state
transitions, authorization decisions, persistence and transaction behavior, retry and idempotency rules, data loss
boundaries, malformed inputs, and complete user workflows. When an incident or bug reveals a missed case, add the
smallest regression test that reproduces it through the real application boundary.

### Conventions

- **Use `pytest` for all tests.** Use `pytest-asyncio` with `asyncio_mode = "auto"` for async tests.
- **Test names read as English** describing the behavior: `test_store_returns_error_when_key_missing`, not
  `test_load_1`.
- **One concept per test.** Multiple `assert`s are fine if they describe the same behavior; two behaviors means two
  tests.
- **No shared mutable state between tests.** Each test builds its own store / context / harness. Use `pytest` fixtures
  with `scope="function"` (the default) for anything mutable.
- **Use `pytest.raises` for expected exceptions**, not `try/except` in test bodies.

### Test the contract, not the implementation

- **Test against the protocol surface**, not one concrete class. A test that only passes because it exercises a specific
  concrete type locks in that implementation.
- **Run shared contract tests against every real implementation.** Do not introduce an in-memory implementation solely
  to make tests easier. If an in-memory implementation is itself a supported production implementation, it belongs in
  the contract suite alongside the database-backed implementation; it does not replace testing the latter against a real
  database.
- **Add a concurrency stress test** for anything that accepts concurrent callers — a `TaskGroup` hammering the class
  with thousands of iterations catches isolation bugs that single-coroutine tests miss. Keep iteration counts reasonable
  so CI stays fast.

```python
import asyncio
import pytest


@pytest.mark.asyncio
async def test_store_is_safe_under_concurrent_insert_lookup() -> None:
    store = BlobStore()
    async with asyncio.TaskGroup() as tg:
        for i in range(1_000):

            async def round_trip(n: int = i) -> None:
                handle = await store.store(str(n).encode())
                data = await store.resolve(handle)
                assert data == str(n).encode()

            tg.create_task(round_trip())
```

### Don't test

- The Python interpreter or third-party frameworks (don't re-prove what `asyncio.Lock` does, or how `httpx2` behaves).
- Implementation details that aren't part of the contract — tests should fail when behavior changes, not when refactors
  happen.
- Trivial functions, accessors, constructors, or wrappers whose assertions merely repeat their source code.
- Lines for the sake of coverage when they do not represent consequential application behavior.

### Build the seam as part of the change

If a behavior can't be tested because the seam doesn't exist — a missing protocol, application factory, dependency
override, test client, database fixture, or harness capability — the change isn't complete until the seam exists.
Building it is part of the change, not a follow-up.

---

