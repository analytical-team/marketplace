---
name: swift-coding
description: >
  Read BEFORE writing or editing ANY Swift code — new files, new types,
  edits to existing ones, tests, SwiftUI views, Package.swift, or a one-line
  fix. The house style guide: Swift 6 strict concurrency (actors, Sendable
  value types, structured concurrency, no GCD/Combine, reasoned unstructured
  tasks), fully qualified enum cases, one type per file with no catch-all
  Utils files, protocol-led APIs, typed throws with per-area error enums,
  doc comments that explain why, composable SwiftUI with no I/O in views,
  Swift Testing against the protocol surface, minimal dependencies, and
  SwiftLint thresholds. Triggers on: ".swift" files, Swift/SwiftUI/AppKit/
  UIKit/SPM work, concurrency or Sendable errors, refactoring Swift,
  reviewing Swift for style, or "how should I structure this in Swift".
  Also read it before reviewing someone else's Swift against these
  conventions.
---

# Swift coding style

Load `references/style-guide.md` for the full guide with rationale and worked
examples. Read the relevant section before writing code in that area — the
checklist below is a reminder, not a substitute.

Rules with **safety or correctness** consequences (concurrency, errors, access
control) are prescriptive. Style rules (naming, layout) are for consistency.

**Project instructions win.** If the repo's CLAUDE.md / AGENTS.md interprets or
overrides a rule (e.g. `defaultIsolation(MainActor)`, a project task wrapper, a
sleep helper, a lint config), follow the project. If the repo has its own copy
of the guide, that copy is authoritative.

## Before you write

1. If the rule you need is in the checklist and unambiguous, apply it.
2. Otherwise read the matching section of `references/style-guide.md`.
3. Match the surrounding code: comment density, naming, idiom. Don't reformat
   files you aren't otherwise changing.

## Checklist

**Language (§1)**
- Latest Swift language mode, strict concurrency on. `async/await`, `Sendable`,
  typed throws, value types.
- No Combine, GCD (`DispatchQueue`, semaphores), `OperationQueue`, or new
  completion handlers — except to bridge an API that demands one (bridge
  callbacks with a continuation).
- Honor the minimum OS. Don't add availability checks below the baseline.
- Cross-platform: `#if os(...)` only for code that can't exist elsewhere; no
  `#if canImport` in place of module structure.

**Naming (§2)**
- Full words; acronyms fully uppercased (`JSONDecoder`, `URLSession`).
- Methods read as English at the call site. Booleans read as assertions
  (`isEnabled`, `canRetry`).
- Protocols named after a real capability or role; no `-Protocol`/`-Manager`.
- **Fully qualified enum cases** (`TaskPriority.high`, not `.high`), except
  inside a `switch` or explicit enum initializer. SwiftUI static members
  (`.caption`, `.primary`, `.blue`) aren't enum cases; shorthand is fine there.

**Files (§3)**
- One primary type per file, file named after it. Extensions:
  `Type+Capability.swift`.
- Never `Helpers.swift`, `Utils.swift`, `Extensions.swift`, `Common.swift`.
- ~600 lines per file, ~400 per type body: split before you hit them.
- Stored properties, then inits, then methods by responsibility. `// MARK:`
  only when a file genuinely has several sections.

**Access & API (§4)**
- Default `internal`; `public` is a deliberate contract. `private` for helpers;
  `fileprivate` rarely. `final` classes by default.
- Lead with protocols (single responsibility) and value types; concrete types
  are defaults behind them. Prefer `any Foo` at boundaries over
  `associatedtype`.
- Areas talk through protocols and value types — no singletons, globals, or
  reaching into internals.

**Doc comments (§5)**
- `///` on public and non-obvious internal declarations. Document the contract
  and the *why* (invariants, errors, platform quirks), never restate the code.
- No ticket/PR references in code. Present tense.

**Concurrency (§6) — correctness**
- Mutable state shared across callers → `actor` with a small surface. Data
  crossing domains → `Sendable` value types (`let` properties).
- `nonisolated` for members that don't touch isolated state.
- `@MainActor` only for UI-owning code; non-UI mutable state goes in an actor.
- Fix a concurrency error in order: fix the design → `nonisolated` →
  `@unchecked Sendable` / `nonisolated(unsafe)` with an inline comment naming
  the invariant → suppress (basically never). Never `@preconcurrency` or
  escape valves just to silence the compiler.
- Prefer `async let`, task groups, SwiftUI `.task`. Unstructured tasks only when
  the work outlives the caller or a sync API needs a cancel handle — through the
  project's reasoned wrapper if it has one (e.g. `UnstructuredTask(reason:)`).
  `Task.detached` almost never.
- `AsyncStream` for real event streams; plain `async` for one value.
- Honor cancellation (`try Task.checkCancellation()`); never swallow
  `CancellationError`. Long-running actor work gets an explicit `cancel()`.
- Never block a cooperative-pool thread waiting on a process, semaphore, or
  callback.

**Errors (§7)**
- Per-area error `enum: Error, Sendable`; cases are failure modes; context in
  associated values; foreign causes as `underlying: any Error & Sendable`.
- Typed throws (`throws(NoteError)`) on public API; default typed internally
  too unless composing unrelated sources.
- Wrap foreign/`NSError` errors at the boundary. Wire-shaped error protocol
  (`code`/`message`/`context`) only at a real foreign boundary.
- `precondition`/`assert`/`fatalError("why")` for impossible states, never for
  user/external input. `try!` only with an inline invariant; `try?` only when
  "no value" is legitimate.
- Don't: throw `NSError`, return `Result` for throwing-shaped calls,
  catch-and-swallow, or log inside error types.

**SwiftUI (§8)**
- Compose, don't subclass: sub-views, `@ViewBuilder` slots, styles,
  environment, configuration types.
- No domain logic in view models; no I/O in views; no singleton view models.
- Accessibility built in (labels, Dynamic Type, contrast).
- State in `@Observable` classes passed via `.environment`, not
  `ObservableObject`/`@Published` (for modern OS baselines).

**Testing (§9)**
- Swift Testing (`@Suite`, `@Test`, `#expect`), `async throws` freely; names
  describe behavior. One concept per test, no shared mutable state.
- Test the protocol surface, not one concrete class; add a concurrency stress
  test for types with concurrent callers.
- Don't test the compiler, Apple frameworks, or implementation details. If the
  project's instructions set a stricter bar for *when* to write tests, follow it.

**Macros (§10)** — protocol usable by hand; expansion + runtime tests.

**Dependencies (§11)** — stdlib and first-party frameworks by default; a new
dependency needs concrete justification and goes in the inventory (`AUDIT.md`)
in the same change.

**Imports (§12)** — platform, then own modules, then third-party; nothing unused.

**Lint (§13)** — SwiftLint: line 140/220, function body 80/150, complexity
16/25, type body 400/600, file 600/1000. The warning is the ceiling. Suppress a
single site only, with a reason: `// swiftlint:disable:next <rule> — <reason>`.

## Before you finish

- Build (`swift build` or the project's build script) with no new warnings.
- Run `swiftlint lint --quiet` if the project has a `.swiftlint.yml`; fix what
  your change introduced.
- Run the relevant tests (`swift test`) when behavior changed.
- Scan §14 (anti-patterns) of the guide against your diff.
