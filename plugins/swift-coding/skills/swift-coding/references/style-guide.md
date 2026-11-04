# Swift Coding Style Guide & Patterns

A general-purpose style guide for modern Swift apps and frameworks. It captures
the conventions, patterns, and anti-patterns that produce code that is safe
under strict concurrency, easy to substitute and test, and legible to both
contributors and coding agents.

This guide is organized as a set of opinions with reasons. Where a rule carries
**safety or correctness** consequences (concurrency, errors, access control),
read it as prescriptive — "do this." Where it captures **style** (naming, file
layout), follow it for consistency but don't block a review on it without cause.

> How to adopt this in your own app: copy this file in, delete the sections that
> don't apply to your platform, and adjust the lint thresholds and minimum OS
> versions to match your targets. The principles travel; the specific numbers
> are yours to set.

---

## 1. Language baseline

- **Adopt the latest Swift language mode with strict concurrency checking on.**
  Treat concurrency as a correctness concern, not a warning to silence.
- **Use modern Swift throughout:** `async/await`, structured concurrency,
  `Sendable`, typed throws, value types. Do not introduce new completion-handler
  callbacks unless you are bridging an Objective-C / C API that requires one.
- **Don't reach for Combine, GCD (`DispatchQueue`), or `OperationQueue` in new
  code.** Async/await and actors give the same capabilities with less ceremony
  and compile-time guarantees. The only acceptable use is bridging to an Apple
  API that demands a queue.
- **Set a minimum-OS baseline and honor it.** Use `if #available(...)` for
  runtime checks and `@available(...)` on declarations that need a newer API
  than your baseline.

### Cross-platform code

If a target compiles for more than one platform (e.g. macOS + iOS), new API
should generally work on all of them unless there's a concrete reason it can't.

- Reserve `#if os(macOS)` / `#if os(iOS)` for code that genuinely cannot exist
  on the other platform (AppKit-only types, etc.). Most "feels different per
  platform" cases are handled by SwiftUI primitives that adapt automatically.
- Avoid `#if canImport(...)` as a substitute for proper module organization. If
  a feature is platform-specific, structure the code so its dependency is too —
  don't paper over it with conditional imports.
- The default reaction to "this needs to differ by platform" should be "the API
  is missing an abstraction," not "add a `#if`."

---

## 2. Naming

- **Types** — `UpperCamelCase`, full words. No abbreviations except terms that
  are abbreviations everywhere (`URL`, `JSON`, `ID`, `MCP`). Acronyms are
  uppercased throughout: `JSONDecoder`, `URLSession`, `HTTPClient`.
- **Methods & properties** — `lowerCamelCase`, full words. Methods should read
  as English at the call site: `bridge.evaluate(script:)`, `tools.list(limit:)`,
  not `bridge.eval(s:)`.
- **Protocols** — name them after the **capability or role** they represent
  (`AgentExposable`, `RandomAccessCollection`). Avoid cargo-culted `-Protocol`,
  `-able`, or `-Manager` suffixes glued onto names that aren't really
  capabilities. If you struggle to name a protocol after a real capability, it
  may not be earning its keep.
- **Closures & parameters** — descriptive names. Avoid `value`, `data`,
  `result`, `item` unless the thing genuinely is opaque at that point.
- **Booleans** read as assertions: `isEnabled`, `hasChanges`, `canRetry`.
- **Files** — match the primary type they contain (see §3).
- **Short local names** (`i`, `c`, `x`) are fine in tight scopes like loop
  bodies and short closures; full words everywhere persistent.

### Enum case qualification

**Always use fully qualified enum cases.** Prefer `NLLanguage.english` over
`.english`, `TaskPriority.high` over `.high`, `Color.blue` over `.blue`.

```swift
// Correct — type is unambiguous without reading surrounding context:
return recognizer.dominantLanguage ?? NLLanguage.english
let priority = TaskPriority.high
throw PromptEncodingError.cancelled

// Avoid — type must be inferred; invisible in diffs and searches:
return recognizer.dominantLanguage ?? .english
let priority: TaskPriority = .high
throw .cancelled
```

**Rationale:**

- Explicit types survive being read out of context (grep results, diffs,
  code review, AI agent analysis).
- Symbols are greppable — `NLLanguage.english` appears in search results;
  `.english` alone does not.
- Reduces ambiguity when the same case name exists on multiple types.

**Exception:** shorthand `.case` is acceptable inside a `switch` body or an
explicit enum initializer, where the type is stated in the same expression and
cannot be misread:

```swift
switch language {
case .english: ...   // type is declared in the switch header
case .french: ...
}
```

---

## 3. File & type organization

- **One primary type per file.** The file name matches the type:
  `BlobStore.swift` contains `BlobStore`.
- **Co-locate small helpers.** Private nested types, fileprivate helpers, and
  small extensions of the primary type live in the same file.
- **Use a `+` suffix for cross-cutting extensions.** When you extend a type from
  elsewhere with a focused capability, name the file `Type+Capability.swift`
  (e.g. `Date+Formatting.swift`). The scope is visible at a glance.
- **No catch-all files.** Never create `Helpers.swift`, `Utils.swift`,
  `Extensions.swift`, or `Common.swift`. They become magnets for unowned code.
  Either the helper has a home with the type it operates on, or it deserves its
  own named file (`StringEscaping.swift`, not `StringHelpers.swift`).
- **Keep files small.** Treat ~600 lines as a real ceiling for files and ~400
  for type bodies. Hitting it is a signal to split, not to add more `// MARK:`
  dividers.
- **Order within a file:** stored properties first, then initializers, then
  methods grouped by responsibility. Use `// MARK: - Section` to group only when
  the file has more than one natural section — never to compensate for a file
  that should be split.

---

## 4. Access control & API design

**Default to `internal`.** Promote to `public` only when a type or member is
genuinely part of a module's contract.

- `public` is a contract: adding it is a decision, removing it is a breaking
  change. Be deliberate.
- `private` for type-internal helpers. Use `fileprivate` only when two types in
  the same file genuinely share a helper — otherwise split the file.
- `final` on classes by default, unless you specifically intend to allow
  subclassing.
- Underscore-prefixed names (`_Foo`) mean "technically public for tooling/macro
  reasons, not part of the supported surface." Don't introduce them casually,
  and never let them leak into adopter-facing docs, sample code, or diagnostics.

### Lead with protocols, not concrete types

This is the load-bearing design principle for any code meant to be
**substitutable, testable, or reusable**.

- A module's public surface should be dominated by **protocols and value
  types**, not concrete classes. The concrete type can still be `public` (so
  consumers use it out of the box), but the thing they _type their dependencies
  against_ is the protocol.
- Protocols have a **single, focused responsibility.** If adopters routinely
  implement only half of a protocol, split it.
- Default implementations (via protocol extensions) are encouraged for
  _ergonomic_ methods, but not for behavior an adopter would reasonably want to
  override.
- Prefer existentials (`any Foo`) at module boundaries; avoid `associatedtype`
  unless it materially improves the API.

```swift
// The contract adopters depend on:
public protocol NoteStore: Sendable {
    func load(_ id: String) async throws(NoteError) -> Note
    func save(_ note: Note) async throws(NoteError)
}

// A default implementation they can use out of the box — but the type
// they hold is `any NoteStore`, not this class.
public final class FileNoteStore: NoteStore { /* ... */ }
```

**Why:** a concrete-type-only public API forces forks. A protocol seam invites
substitution and makes the code testable with a fake.

### Keep modules from depending on each other's internals

Independent areas of a codebase should communicate only through **protocols and
value types** — never through shared global state, singletons, or `internal`
symbols that happen to be visible. A dependency that looks harmless inside the
codebase becomes a forced dependency for anyone who wanted only one piece. If
two areas need something shared, hoist it cleanly above both and keep it small.

---

## 5. Documentation comments

- Use `///` on every `public` declaration and any non-trivial `internal` one
  another contributor (or agent) would have to read the implementation to
  understand.
- **Document the contract, not the implementation.** State invariants,
  preconditions, error cases, ownership, performance constraints — the things
  the name doesn't already say.
- **Do not write comments that restate the code.**
  `/// Returns the count of items.` above `var count: Int` is noise that will
  drift. The name carries the "what"; comments are for the non-obvious "why" (a
  workaround, a subtle invariant, a performance constraint).
- **Don't reference tickets or PRs** in code (`// Added for JIRA-123`). Those
  rot. Put context in commit messages and PR descriptions; if a workaround needs
  explaining, write the _why_ directly.
- Keep doc comments present-tense and declarative: "Returns the …" not "Will
  return the …". Document each protocol requirement individually.

```swift
/// A live context that hosts agent-exposed tools.
///
/// Hold one `BridgeContext` per logical session. Inject tools with
/// ``inject(_:)`` before evaluating any script that references them.
public actor BridgeContext {
    /// Evaluates `script` in the underlying context.
    ///
    /// - Throws: ``BridgeError`` if the script throws or the context
    ///   is in an invalid state.
    public func evaluate(_ script: String) async throws -> Value { ... }
}
```

---

## 6. Concurrency

Under strict concurrency, this is a **correctness** domain. The model in one
paragraph: use **actors** to encapsulate mutable isolated state, **`Sendable`
value types** to move data between isolation domains, and **structured
concurrency** for asynchronous work.

### Actors

Use an `actor` when you have **mutable state** that must be safe across
concurrent callers and is reached from outside the type's own file.

- Make actors `public` only when callers need to hold or pass them; otherwise
  `internal actor`.
- Keep the actor's surface small — every method call is an isolation hop, and
  chatty actors get slow.
- Don't return `Sendable`-violating types from actor methods. Hand out a small
  `Sendable` proxy or take a closure parameter instead.
- Document the isolation contract in the type's doc comment ("Owns X; methods
  are serial," etc.).

### `nonisolated`

Mark actor members that don't touch isolated state (immutable stored properties,
pure helpers) `nonisolated` so callers aren't forced into an `await` for
nothing.

```swift
public actor BridgeContext {
    nonisolated public let id: UUID
    private var context: Context  // isolated
}
```

### `@MainActor`

Reserve it for **UI and view-model code that genuinely owns UIKit/AppKit/SwiftUI
state.** A framework should not force its callers onto the main actor. If you
reach for `@MainActor` inside non-UI code, you almost always want a plain
`actor` instead — adding `@MainActor` "to make the test pass" hides a real
isolation bug.

### `Sendable` and the escape valves

- Most data crossing isolation domains should be `Sendable`. Prefer `let`-only
  stored properties of `Sendable` types — then conformance is free.
- `@unchecked Sendable` is allowed **only** when the type is genuinely
  thread-safe by construction (e.g. immutable after init) _and_ you leave a
  comment explaining why. Never use it just to make a strict-concurrency error
  disappear — the error was pointing at a real isolation problem.
- `nonisolated(unsafe)` is a single-property release valve. Every use needs an
  inline comment naming the invariant that makes the access safe, scoped as
  tightly as possible. If you can't write the invariant honestly, you don't have
  a safe use.

When a strict-concurrency error appears, fix it in this order: (1) fix the
design — make the type properly `Sendable`, move state into an actor, or change
the call site; (2) apply `nonisolated` if the member truly doesn't touch
isolated state; (3) `@unchecked Sendable` / `nonisolated(unsafe)` with a written
invariant; (4) suppress — basically never.

### Structured concurrency

- Prefer `async let` and `withTaskGroup` over unstructured tasks when the work
  has a clear parent. You get cancellation, error propagation, and priority
  inheritance for free.
- Reach for an unstructured `Task { }` only when the lifetime truly outlives the
  calling scope, **or** an external API needs a synchronous handle on the work
  (e.g. a `cancel()` method that must not block). Document the reason inline.
- Consider funneling every unstructured task through a single wrapper that
  records a reason, so the codebase has one greppable inventory of where it
  escapes structured concurrency:

  ```swift
  let work = UnstructuredTask(reason: "send needs a sync cancel handle") {
      await runAlgorithm()
  }
  ```

  A lint rule can then forbid bare `Task { }` outside the wrapper.

- `Task.detached` should be exceedingly rare — it drops priority and isolation
  inheritance. If you use it, write down why.
- Use `AsyncSequence` / `AsyncStream` for a true stream of events. For a
  one-shot async result, just use `async` — don't dress a single value up as a
  stream.

### Cancellation

- Honor cancellation: call `try Task.checkCancellation()` at sensible boundaries
  in meaningful work.
- Never catch and swallow `CancellationError`.
- When an actor owns a long-running operation, give it an explicit `cancel()`
  method rather than relying on deinit timing.

---

## 7. Error handling

Errors are **first-class API surface**, not afterthoughts. Each area defines its
own error type and declares how a function fails.

### The default shape: a typed enum

For most code, this is all you need:

```swift
public enum RAGClientError: Error, Sendable {
    case transportFailure(underlying: any Error & Sendable)
    case decodingFailure(reason: String)
    case unauthorized
    case rateLimited(retryAfter: Duration?)
}
```

- **Cases describe failure modes**, not error sites. A case maps to a thing that
  can go wrong, not to a line of code.
- **Associated values carry context** — use them; don't shove everything into
  one `description: String`.
- **Bridged foreign errors live in an associated value** typed as
  `any Error & Sendable`. Don't lose the underlying cause.

### Typed throws

Use typed throws on **public** functions that can fail:

```swift
public func loadNote(_ id: String) async throws(NoteError) -> Note { ... }
```

The call site sees exactly which errors are possible, exhaustive `catch` stays
finite, and diagnostics point at real failure modes. For **internal** functions,
default to typed and fall back to untyped only when the function genuinely
composes errors from multiple unrelated sources, or bridges to an API that
throws `NSError`.

### Adapt foreign errors at the boundary

Never let an `NSError` or third-party error type escape your area's surface.
Catch it at the boundary and wrap it:

```swift
do {
    try someAppleAPI()
} catch {
    throw RAGClientError.transportFailure(underlying: error)
}
```

### When errors cross a foreign boundary

If errors must cross into a non-Swift consumer (JavaScript, a wire protocol, a
remote API), the simple enum isn't enough — the far side needs a **stable,
machine-readable identifier** and **structured context** it can parse. For those
cases, define an error _protocol_ that adds the wire shape:

```swift
public protocol WireError: Error, Sendable {
    var code: String { get }                    // stable, dotted, lowercase
    var message: String { get }                 // human-readable, may change
    var context: [String: any Sendable] { get } // snake_case keys, Sendable values
}
```

`code` is what consumers switch on — keep it stable and scoped
(`note.not_found`). `message` is for humans and can change. `context` keys are
snake_case and stable; values must be `Sendable` (no `Error`s, no large blobs).
**Default to the simple enum** — only reach for the wire-shaped protocol when
you actually have a foreign boundary. Adding wire requirements later is
mechanical; removing them is not.

### Assertions vs. errors

Use language facilities for things that **should never happen** — they are not
error handling, and shouldn't mix with `throws`:

- `precondition(...)` for invariants that must hold in release builds.
- `assert(...)` for debug-only intent checks.
- `fatalError(...)` for truly unreachable code — but prefer to restructure so
  the impossible state is unrepresentable.

If a condition can be triggered by user input or external state, it is **not** a
precondition — throw an error.

`try!` and `try?` are last resorts. `try!` is acceptable only when failure is
provably impossible given the surrounding code, with an inline comment naming
the invariant. `try?` is acceptable only when "no value" is a legitimate,
non-exceptional outcome — never as a catch-suppressor.

### Don't

- **Don't throw `NSError`** from new code — no contract, no `Sendable`
  guarantee, no typed catch.
- **Don't use `Result<T, Error>`** as the return type for a throwing-shaped
  call. Throw instead. `Result` is for the rare case where errors are _values
  you pass around_.
- **Don't catch-and-swallow** (`catch { return defaultValue }`). The caller
  can't tell something failed. Let it propagate, or transform into a meaningful
  return shape (`Optional`) when "missing" is genuinely not exceptional.
- **Don't put logging inside an error type.** Errors describe failure; logging
  belongs at the catch site.

---

## 8. UI layer (SwiftUI)

- **Views are values; customize by composition, not subclassing.** The
  customization seams are decomposition (export sub-views), slots
  (`@ViewBuilder` parameters), style protocols, environment values, and
  configuration types — never `class FooView: OurView`.
- **Export the constituent pieces of a composite UI**, not just the monolith.
  Adopters who want anything but the default shouldn't have to fork.
- **No domain logic in view models.** A view model orchestrates the _UI's view
  of_ the domain; the domain itself lives in a non-UI area behind a protocol the
  view model consumes. A view model that does network calls, owns persistent
  state, or implements business rules stops being testable independently of the
  UI.
- **No direct I/O from views.** No `URLSession`, `FileManager`, or disk access
  in a view's `body` or lifecycle. Push it into a model or area; the view
  observes the result. Otherwise views become un-previewable and un-testable.
- **No singleton / global view models.** Each view scope creates its own view
  model (or accepts one from a parent). Shared state lives in the area that owns
  it, hoisted to a common ancestor.
- **Accessibility is built in, not bolted on.** A shipped UI component works
  with assistive technologies out of the box — correct labels, Dynamic Type,
  contrast — without the adopter adding modifiers. The only carve-out is content
  the adopter injects through a slot.
- **Make customization seams explicit and documented.** A behavior that's only
  configurable through an undocumented environment value or a magic init
  parameter isn't really a seam.

---

## 9. Testing

**Automated tests are required.** A change is done when the relevant test target
is green _and the new test would fail without the change_ — not when the build
compiles. "It compiles" proves type-correctness, not behavioral correctness. "I
ran it locally" catches the bug once, today; an automated test catches it
forever.

### Prefer the cheapest test that catches the regression

1. **Unit tests** — fast, isolated, in-memory. Most coverage lives here.
2. **Integration tests** — when behavior only emerges from multiple pieces
   interacting.
3. **UI tests** — screenshot tests for visual contract; app-level tests for
   navigation, enablement, and multi-component flows. Slowest and most fragile;
   use where they earn their keep.

Full coverage of an area usually needs all three. An area covered exclusively by
unit tests almost certainly has gaps.

### Conventions

- **Use the modern testing framework** (Swift Testing: `@Suite`, `@Test`) for
  new tests. Reserve XCTest for the narrow cases where an API only exists there
  (e.g. macro-expansion assertions).
- **Test names read as English** describing the behavior, not the method:
  `bridge_returns_error_when_promise_rejects`, not `testEvaluate1`.
- **One concept per test.** Multiple `#expect`s are fine if they describe the
  same behavior; two behaviors means two tests.
- **No shared mutable state between tests.** Each test builds its own store /
  context / harness.
- **Use `async throws` liberally** — it's idiomatic and avoids expectation
  boilerplate.

### Test the contract, not the implementation

- **Test against the protocol surface**, not one concrete class. A test that
  only passes because it exercises a specific concrete type locks in that
  implementation.
- **Ship a fake or in-memory implementation** of your protocols (in a
  testing-support module) so adopters can unit-test against them too.
- **Add a concurrency stress test** for anything that accepts concurrent callers
  — a `withTaskGroup` hammering the type with a few thousand iterations catches
  isolation bugs single-threaded tests miss. Keep iteration counts reasonable so
  CI stays fast.

```swift
@Test("Store is safe under concurrent insert/lookup")
func store_concurrent_access() async throws {
    let store = BlobStore()
    await withTaskGroup(of: Void.self) { group in
        for i in 0..<1_000 {
            group.addTask {
                let handle = await store.store(MyBlob(i))
                #expect(await store.resolve(handle).id == i)
            }
        }
    }
}
```

### Don't test

- The Swift compiler or Apple frameworks (don't re-prove what an actor does, or
  how `URLSession` behaves).
- Implementation details that aren't part of the contract — tests should fail
  when behavior changes, not when refactors happen.

### Build the seam as part of the change

If a behavior can't be tested because the seam doesn't exist — a missing
protocol, a missing fake, a missing harness capability — the change isn't
complete until the seam exists. Building it is part of the change, not a
follow-up.

---

## 10. Macros (if you use them)

Swift macros are a fine way to remove boilerplate, but treat them as an
**implementation strategy, not the API**:

- For every macro that generates conformance to a public protocol, the protocol
  must be **usable by hand without the macro.** Hand-written conformances are a
  supported path, and both paths get tested.
- Macro-generated code should read like reasonable hand-written code — no
  unprintable identifiers, no undocumented runtime support.
- Diagnostics must point at the **conceptual problem**, not at generated tokens.
- A macro is not done until it has both an expansion test (asserting the
  generated code) and a runtime test proving the generated code works. Keep
  expansion tests focused — one behavior each, not a single test asserting
  hundreds of lines.

If a piece of functionality _requires_ a macro to be adoptable, the macro has
become the contract instead of the protocol it generates — that's the failure
mode to avoid.

---

## 11. Dependencies

The default external-dependency stance is **standard library and first-party
platform frameworks only.** Every dependency you add becomes a dependency for
everyone who adopts your code: it enters their build graph, adds link time and
binary size, and ties them to a license and a maintainer.

A new dependency earns its way in by clearing all of:

- **Concrete justification** — name the capability you'd otherwise build and
  maintain. "It's convenient" doesn't count.
- **No reasonable first-party path** — prefer Foundation, the platform's own
  logging/observability, swift-syntax for macros, etc.
- **Stable provenance** — actively maintained, clear release discipline. Avoid
  one-person and abandoned projects.
- **Bounded scope** — a library that does exactly the one thing you need beats
  one that brings ten you don't.

Scope each dependency to the area that uses it; don't add a codebase-wide
dependency for one area's need. Test-only dependencies face the same questions
at a slightly lower bar, since they don't reach production. Keep an inventory
(an `AUDIT.md` or similar) and update it in the same change that adds or removes
a dependency.

---

## 12. Imports

- Group imports: standard library / platform frameworks first, your own modules
  second, third-party last. One blank line between groups.
- Don't import what you don't use — the compiler will tell you.
- Avoid `@_implementationOnly` and `@_exported` in shipping code without a
  written justification in the file.

---

## 13. Lint thresholds

Adopt a linter (SwiftLint or equivalent) covering every shipping and test
target. Keep thresholds tight enough that hitting one is a real signal to
refactor. A reasonable starting set:

| Rule                  | Warning | Error |
| --------------------- | ------- | ----- |
| Line length           | 140     | 220   |
| Function body length  | 80      | 150   |
| Cyclomatic complexity | 16      | 25    |
| Type body length      | 400     | 600   |
| File length           | 600     | 1000  |

Treat the **warning** as the real ceiling — exceeding it means the function,
type, or file probably wants splitting; hitting the error threshold almost
always does. Disable a default rule only with the rationale written in the
config itself, and re-enable via review. Custom rules (e.g. forbidding bare
`Task { }` outside a sanctioned wrapper) are a good way to make a convention
enforceable rather than aspirational.

---

## 14. Anti-patterns quick reference

The negative space around the rules above. When you find one of these, fix it.

**Architecture**

- Concrete-type-only public APIs (no protocol seam) → lead with a protocol.
- Modules coupling through internals, globals, or singletons → talk through
  protocols and value types.
- Functionality that _requires_ a macro to adopt → the protocol is the contract;
  the macro is a shortcut.
- Catch-all `Utils.swift` / `Helpers.swift` files → give helpers a real home.

**Concurrency**

- `@unchecked Sendable` / `nonisolated(unsafe)` to silence the compiler →
  restructure, or document the invariant.
- `@MainActor` on non-UI code as a workaround → use a plain `actor`.
- Bare `Task { }` / `Task.detached` where structured concurrency would do →
  `async let`, `withTaskGroup`, or a reasoned wrapper.
- `DispatchQueue` / `OperationQueue` in new code → actors + structured
  concurrency.

**Errors**

- Throwing `NSError` from new code → typed area error; wrap foreign errors at
  the boundary.
- `Result<T, Error>` for throwing-shaped calls → throw.
- Catch-and-swallow → propagate or model "missing" honestly.
- `try!` / `try?` to skip thinking → justify `try!` inline; use `try?` only when
  no-value is legitimate.

**Style**

- Files past the warning threshold → split before you hit it.
- Doc comments that restate the code → document the contract, or delete the
  comment.
- Comments referencing tickets/PRs → context goes in git history.
- Cargo-culted `-Protocol` / `-able` suffixes → name after the capability.
- Shorthand `.case` outside a `switch` or enum initializer → use the fully
  qualified `Type.case` form.

**UI**

- Monolithic views with no exported sub-pieces → export the constituents.
- View models owning domain logic or doing I/O → push it behind a protocol the
  view model consumes.
- Singleton / global view models → one per view scope; shared state in the
  owning area.
- Components that need adopter ceremony to be accessible → build accessibility
  in.

**Testing**

- Tests pinned to one concrete implementation → test the protocol.
- "It compiles" treated as "it works" → run the relevant test target.
- Manual verification offered as coverage → write the automated test.
- Huge brittle snapshot/expansion tests → one behavior per test.

---

_This guide is a distillation of conventions proven on a strict-Swift-6
framework. The strong opinions — protocol seams, typed throws, actors over
queues, tests as contract — are what make the resulting code safe to change.
Adjust the numbers to your targets; keep the principles._
