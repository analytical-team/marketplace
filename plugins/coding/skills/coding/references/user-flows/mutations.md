# Isolated mutation checks

Run mutation checks after a selected baseline scenario passes. The goal is to prove that the integration check is
sensitive enough to detect plausible behavioral omissions and logic bugs.

If an injected defect goes undetected by an end-to-end test, that survival reveals a **check weakness** (a blind spot
in test assertions or scenarios), not necessarily an existing bug in production code.

---

## 1. Prepare an isolated workspace

Never mutate your primary working directory or active development tree.

1. **Identify the exact production boundary and assertion**:
   Decide in advance what behavioral assertion should fail when the defect is introduced. Document the hypothesis
   before altering code.
2. **Create an isolated workspace**:
   - Allocate a temporary directory, clean git worktree, or isolated sandbox.
   - Copy only the necessary source files, build definitions, and test fixtures.
   - **Strictly exclude** personal configurations, `.env` files, production databases, signing certificates, and cloud
     credentials.
3. **Establish an unmodified baseline**:
   - Build and execute the target scenario in the isolated workspace without changes.
   - Verify that all assertions pass.
   - Confirm that the test runner is genuinely executing the binaries compiled inside the temporary workspace, rather
     than resolving pre-installed system binaries, global packages, or cached artifacts.
4. **Record build identities**:
   - Note the commit hash, source file checksums, and built binary digests to ensure reproducible comparisons.

---

## 2. Select plausible defect mutations

Choose realistic, subtle omissions that represent common developer mistakes at system boundaries. Avoid arbitrary syntax
corruptions or random character deletions that merely cause build or parse failures.

### Recommended mutation archetypes

| Mutation Archetype | Concrete Example | What It Tests |
| --- | --- | --- |
| **Parameter dropping** | Remove a flag or payload field when serializing a request from the client/CLI to the backend service. | Does the test verify that the specific option reached the backend, or is it silently accepting default values? |
| **Option omission** | Remove one choice from an interactive picker, dropdown menu, or keyboard shortcut cycle. | Does the test explicitly verify every advertised option, or does it only exercise the default choice? |
| **Premature UI acknowledgment** | Have the UI or CLI display "Operation Succeeded" immediately without awaiting backend/daemon response. | Does the test check actual backend completion, or does it only assert on stdout strings? |
| **State persistence skip** | Comment out the database write, config write, or file flush while returning an in-memory success response. | Does the test inspect durable storage across restarts, or does it only verify the immediate in-memory return? |
| **Resume / Reconnect omission** | Ignore a configured flag or mode during session resume or reconnection. | Does the test verify that state persists across session interruptions, or only within a single continuous run? |
| **Condition inversion** | Invert an authorization gate or grant check (`if (!authorized)` vs. `if (authorized)`). | Does the test suite verify both positive access and justified refusal? |

---

## 3. Compare each mutant against baseline

Apply one mutation at a time using a small, explicit diff. Rebuild and run the exact same test scenario.

### Evaluation matrix

| Outcome | Definition | Meaning and Action |
| --- | --- | --- |
| **Detected** | The expected behavioral assertion fails with a clear, relevant error message while the baseline passed. | The check is sensitive and effective. Record the detected mutant and restore baseline code. |
| **Undetected** | The code was modified, the relevant test ran, and the test **passed**. | **Check weakness**. The test has a blind spot. Investigate whether an assertion is missing, whether the test derives expected values from production data, or whether the scenario only tests happy paths. |
| **Inconclusive** | The mutation caused a compilation error, crash during fixture setup, unrelated timeout, or skipped execution. | Inconclusive. The test harness was unable to evaluate the runtime behavior. Adjust the mutation to be syntactically valid and targeted. |

> [!WARNING]
> A compiler error or build failure does **not** count as detecting a defect. The mutation must produce a runnable
> program that executes the faulty logic so the test's behavioral assertions are evaluated.

---

## 4. Remedying undetected mutants

When a mutant survives:

1. **Inspect test assertions**: Check whether the test only asserted on exit code 0 or presence of a generic success message
   rather than validating specific payload fields or state changes.
2. **Inspect data sources**: Check if the test generated its expected choices dynamically from the same helper function or
   data structure being mutated (the shared-omission trap).
3. **Add or strengthen assertions**: Update the test to verify the missing layer (e.g. read back database records or inspect
   spawned processes).
4. **Re-run baseline and mutant**: Confirm that the baseline passes and the mutant is now promptly detected.

---

## 5. Cleanup

- Revert or delete the isolated mutation workspace.
- Terminate any background processes or test daemons spawned during the run.
- Retain logs, diffs, and execution receipts in your task report or evidence directory.
- Never commit test mutations to version control.
