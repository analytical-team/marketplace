---
name: coding
description: >-
  Apply engineering standards when implementing, refactoring, or reviewing
  software across languages. Covers architecture and resource ownership,
  type-driven design, parsing at boundaries, integration-first testing,
  command execution, and validation of real user flows.
---

# Coding

Apply the project's instructions and the user's scope first. Use these standards
to make a complete, reviewable change without unrelated refactors. Language-specific
guides take precedence for language syntax and conventions.

## Reference guides

Read the references relevant to the task; do not load every guide by default.

| Guide | Read when working on |
| --- | --- |
| [Engineering principles](references/engineering-principles.md) | Architecture, contracts, shared state, resource ownership, and lifecycle boundaries |
| [Structure over strings](references/structure-over-strings.md) | Types, parsing, serialization, errors, and trust boundaries |
| [Testing philosophy](references/testing-philosophy.md) | Test selection, real integration boundaries, isolation, and user-flow validation |
| [Tooling and scripts](references/tooling-and-scripts.md) | Commands, process lifecycle, Python tooling, environment settings, and worklogs |

## Workflow

1. Read the implementation, callers, tests, and architecture notes. Trace the
   complete path across UI, transport, domain logic, and persistence. Verify runtime
   behavior rather than relying on a design document or familiar API name.
2. Establish observable success criteria, failure cases, and constraints. For
   cross-component changes, define contracts, state transitions, ownership, and
   verification before implementation.
3. Fix the violated invariant at its responsible component. Maintain one authority
   for each rule and state. Use cohesive modules and narrow, typed interfaces;
   avoid speculative frameworks, parallel parsers, and hidden global coupling.
4. Design cancellation, cleanup, timeouts, retries, and partial completion.
   Retry side effects only when idempotent, preserve uncertainty when completion
   cannot be proven, and report actionable errors without exposing secrets.
5. Validate behavior at real boundaries. Before adding a test, name the specific
   mistake it could catch. Avoid trivial tests, implementation snapshots, and mocks
   that replace the behavior under test. Isolate test data and clean up owned resources.
6. Review system fit as well as test results: misplaced policy, duplicated state,
   resource leaks, races, compatibility breaks, and missing user interactions.

## Before finishing

- Run both a strict type checker and a linter appropriate to the changed code.
  Passing dynamic tests does not detect every uncalled or misplaced method,
  unresolved attribute, or stale signature.
- Exercise the actual user or client flow. For interactive CLIs, use a real
  controlling terminal and check rendering, navigation, quit/interrupt behavior,
  exit codes, and terminal restoration. Test piped and JSON output separately.
- Test fresh and existing data without silently wiping or relocating user state.
  Verify both permitted access and justified refusal at permission boundaries.
- Keep a timestamped `WORKLOG.md` for substantial work. Record decisions, test
  evidence, limitations, and pending work. Turn recurring defects into maintained
  checks or typed invariants.
- Use concise, imperative commit subjects. When a PR is part of the authorized
  workflow, explain the problem, resulting behavior, concrete validation, and any
  visible UI changes. Follow the repository's identity and attribution policy.

## Companion tooling

When installed, use `python-coding`, `typescript-coding`, or `swift-coding` for the
language-specific conventions, and `jobs` for supervised command execution. For
interactive terminals use Rex when available. `user-flow-audit` can supply deeper
qualification methods when a feature audit is requested. These are separate
installations; if unavailable, use the project's existing tools and apply the
bundled guidance directly.
