# Evidence and completion

Maintain durable feature qualification records and run histories. A task-local evidence directory or test log artifact
retains execution outputs, diffs, and transcripts, but should remain linked to the primary project tracking document
or issue tracker. Never record secret tokens, API keys, private passwords, or sensitive user data in logs or reports.

## Scenario record structure

For every audited user scenario, record:

1. **Requirement and entry path**: The user goal, documented contract, and exact entry interface (CLI command, flag,
   UI element, keyboard shortcut, API endpoint, or configuration file). Define expected results **before** inspecting
   implementation outputs.
2. **Initial state**: Data state (clean, initialized, or migrated), configuration parameters, authentication/authorization
   levels, and the exact user action sequence.
3. **Target identities and versions**:
   - Source revision / git commit digest / input hash.
   - Built binary paths, container image tags, or package versions actually executed.
   - Explicit verification of which runtime process/daemon actually served the request (to prevent tests silently
     exercising a pre-installed background version rather than the development build).
   - Flag clearly when binary identity cannot be established.
4. **Execution parameters**: Command run, working directory, job/process ID, terminal/browser environment, exit code,
   and specific test cases executed. Record skips, warnings, and infrastructure errors.
5. **Observed outcomes across all three layers**:
   - *Presentation*: Observed terminal render, browser DOM change, status banner, HTTP status code.
   - *Authoritative State*: Verified persistent database rows, updated config keys, session store state.
   - *External Effect*: Verified disk writes, process spawns, network requests, or hardware/OS calls.
6. **Lifecycle and resilience**: Cancellation results, process restart behavior, session resumption, and error recovery.
7. **Mutation validation**: Baseline run, mutation patch applied, assertion tested, and mutant detection result.
8. **Exploration**: Notes from blind user-goal exploration (discoverability hurdles, documentation discrepancies).
9. **Untested boundaries**: Known exclusions, simulated dependencies, and required next steps.

---

## Result classification taxonomy

Classify each individual check under one of the following authoritative categories:

| Category | Definition and Required Evidence |
| --- | --- |
| **Passed** | All defined behavioral assertions (presentation, state, effect) executed and passed against verified target binaries under the specified initial conditions. |
| **Product Defect** | A documented or promised requirement fails with a reproducible user flow. Record the broken contract, reproduction steps, expected behavior, and observed failure. |
| **Coverage Gap** | A documented feature or required interaction completely lacks an automated scenario or verification check. (A coverage gap indicates unknown status, not verified failure). |
| **Check Weakness** | A verified plausible mutant (injected bug) survives undetected by the test suite, or the check derives its assertions from the same incomplete source that caused a defect. |
| **Unverified** | The check was skipped, blocked by a tooling limitation, aborted by infrastructure failure, or target binary identity was ambiguous. Record the specific blocker. |
| **Excluded** | The flow is deliberately unsupported, deprecated, or excluded for the specific platform, OS, or release tier. Cite the authoritative documentation or architecture decision. |

---

## Distinguishing evidence dimensions

Never collapse qualification into a single boolean "passed". Distinguish evidence across distinct dimensions:

- **Implemented**: Source code, types, and logic exist in the codebase. (Source inspection can confirm implementation,
  but cannot confirm usability).
- **Integration-Tested**: Automated harnesses successfully execute the flow end-to-end against real built binaries
  and services.
- **Manually Verified**: An operator or interactive agent verified visual presentation, screen rendering, keyboard
  navigation, and ergonomics in a real human interface (terminal PTY, browser window, native OS app).
- **Unqualified**: Scenarios that have not run against real built products, or whose tests rely on synthetic mocks of
  critical boundaries.

> [!NOTE]
> Build success, linting cleanliness, passing unit tests, and high line coverage percentages do **not** qualify a user
> flow. An application with 100% unit test coverage can still present a completely broken or missing CLI command or UI
> button.

---

## Audit completion criteria

An audit batch is complete only when all selected scenarios have reached a **conclusive outcome** (Passed, Product Defect,
Coverage Gap, Check Weakness, or Excluded).

- Conclusive product defects, coverage gaps, and check weaknesses are valid audit findings that complete the audit;
  they do not invalidate the audit itself, but they strictly prevent qualifying the affected feature as release-ready.
- Any unresolved `Unverified` checks leave the audit **partial**.
- Passing a focused audit batch qualifies only the audited features. Never generalize from a successful sample to claim
  the entire application or remaining unverified features are free of defects.
