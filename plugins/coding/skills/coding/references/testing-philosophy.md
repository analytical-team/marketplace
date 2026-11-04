# Testing philosophy: integration first, no trivial unit tests

Software reliability is achieved through meaningful behavioral qualification at real boundaries, not through inflating
line coverage metrics with trivial unit tests and synthetic mocks.

---

## 1. Why trivial unit tests and mocks fail us

A pervasive anti-pattern in software testing is writing extensive suites of isolated unit tests using heavy mocking
frameworks. While this produces high coverage numbers, it actively harms long-term software health:

1. **Mocks test the mock, not reality**: When tests mock databases, HTTP clients, filesystems, or child processes, they
   test assumptions about how those dependencies behave—assumptions that frequently drift out of sync with real systems.
2. **False sense of security**: A green unit suite can miss a broken or absent user-facing command, flag, or UI when
   those tests never exercise the real entry point.
3. **High refactoring friction**: Trivial unit tests lock in incidental implementation details (private method signatures,
   internal call counts). When code is refactored for performance or clarity without changing observable behavior, dozens
   of brittle unit tests break.
4. **Bugs hide at boundaries**: Real-world defects congregate at component boundaries—data serialization, process
   lifecycles, state persistence, concurrency races, and user input parsing. Isolated unit tests explicitly bypass these
   boundaries.

---

## 2. Core testing rules

### Rule 1: Exclude trivial unit tests
Do **not** write tests merely to:
- Increase code coverage percentages (coverage is a diagnostic signal, never a target).
- Exercise lines of code or mirror the implementation structure.
- Test trivial getters, setters, constructors, or simple property wrappers.
- Assert obvious language constants or enum member counts.

### Rule 2: Prefer testing at the highest practical level
Test behavior at real boundaries. When verifying a component, let it interact with real sibling components, real file
systems, real databases (in isolated temporary directories), and real serialization pipelines rather than mock objects.

### Rule 3: The test justification requirement
Before writing any new test, you must be able to answer:
> **"What specific implementation mistake could make this test fail while simpler tests still pass?"**
If you cannot name a concrete, plausible defect mechanism, **do not write the test**.

### Rule 4: Delete low-value tests
Do not add low-value tests that create maintenance burden without catching bugs. Remove existing tests only when that
change is within the task's scope. Test sensitivity and boundary coverage matter more than test quantity.

---

## 3. Where to focus testing: where bugs actually hide

Direct testing efforts towards the high-risk failure mechanisms identified in systems engineering:

| Mechanism | What It Stresses | Example Test Approach |
| --- | --- | --- |
| **Interactions** | Multiple real components collaborating across architectural boundaries. | Drive a request from CLI argument parsing through daemon RPC to durable database write. |
| **State transitions** | Sequences of operations where order, repetition, rollback, cancellation, or retries matter. | Test `action → cancel → re-execute`, `grant → restart → resume`, and `grant → revoke → verify denial`. |
| **Properties & invariants** | System rules that must hold across wide inputs rather than hardcoded snapshots. | Assert that no valid sequence of operations can leave the database in an inconsistent state or corrupt schema. |
| **Differential tests** | Two independent implementations, parsers, or encoders that must agree. | Compare output of a fast optimized streaming parser against a canonical reference implementation. |
| **Regression tests** | Reproducing a specific bug previously observed in the field. | Write a test reproducing the exact user flow that failed; verify the test fails on unpatched code, then passes on patched code. |
| **Concurrency & timing** | Race conditions, duplicate execution prevention, cancellation, and task coordination. | Stress concurrent operations to ensure transactions do not interleave improperly or leak locks. |
| **Real boundaries** | Serialization, database migrations, process lifecycles, and network protocols. | Test serialization with real schema encoders; test process termination with SIGTERM and verify child process cleanup. |

---

## 4. Test hygiene and deterministic execution

- **Zero arbitrary sleeps**: Never use `sleep()` or timeout delays to wait for asynchronous operations. Injected manual
  clocks (e.g. `ManualClock`) or deterministic barriers and state polling must be used. Sleeps cause flaky tests in CI
  and slow down test runs.
- **Strict environment isolation**: Tests must never pollute the developer's system:
  - Database suites must run against ephemeral, temporary files in isolated scratch directories that are deleted on teardown.
  - Configuration suites must use unique test namespaces and remove them upon completion.
  - Never read or write to user home directories or default app locations during automated runs.
- **Process lifecycle safety**: Any background process or test daemon spawned by a test suite must be reliably cleaned
  up upon test completion or failure. Never orphan running processes.

---

## 5. Integrating with user flow audits

Integration tests are the foundation, but complete qualification requires human and external client reachability.
For feature qualification and gap discovery, use the bundled [user-flow audit guide](user-flows.md):
1. Validate interactive PTY terminals, exit codes, and screen rendering.
2. Confirm symmetric positive access and justified refusal.
3. Validate test sensitivity by running isolated mutation checks.
4. Conduct blind user-goal exploration.
