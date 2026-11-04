# Research foundation and empirical evidence

This user flow audit methodology is grounded in published industry research, empirical testing studies, and evaluations
of agentic engineering workflows. It synthesizes findings from Anthropic, OpenAI, Google, Microsoft, NIST, and property-based
testing research.

---

## Published research and core findings

| Organization / Source | Published Work & Empirical Findings | Core Engineering Lesson | Application to User Flow Audits |
| --- | --- | --- | --- |
| **Anthropic** | [Effective harnesses for long-running agents](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents) *(Nov 2025)*<br><br>In long-running application tasks, agents routinely claimed completion after unit tests or mock HTTP checks passed, despite user-facing features being completely broken or unreachable. | Unit tests and mock checks create a false sense of security; they do not qualify user-facing interaction. | Formulate explicit, end-to-end user scenarios from the person's starting point. Drive real interaction via shipped executables, real terminal PTYs, or browser sessions. |
| **Anthropic** | [Demystifying evals for AI agents](https://www.anthropic.com/research/demystifying-evals-for-ai-agents) *(Jan 2026)*<br><br>Detailed analysis of evaluation failure modes. Foundational distinction between an agent transcript's claims and the authoritative, final environment state. | Do not trust self-reporting, exit logs, or conversational claims; measure final environment ground truth. | Verify three independent layers: user presentation, authoritative state store, and external side effects. Inspect unexpected passes as rigorously as failures. |
| **Anthropic** | [Harness design for long-running apps](https://www.anthropic.com/research/harness-design-long-running-apps) *(Mar 2026)*<br><br>Demonstrated severe cognitive bias in self-evaluation when the same agent generates code and validates it; separating generation and evaluation produced significantly higher defect discovery. | Builders have blind spots for their own omissions and take implicit shortcuts. | Conduct blind user-goal exploration: give an evaluator only the goal and normal help; withhold internal architecture, intended code paths, and direct API shortcuts. |
| **OpenAI** | [Evaluate agent workflows](https://developers.openai.com/api/docs/guides/agent-evals) and [Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)<br><br>Guides for continuous evaluation. Emphasizes end-to-end workflow tracing, task-specific criteria, and avoiding subjective "vibes" or surface plausibility. | Correlate evidence across the entire transaction; use deterministic assertions for functional correctness. | Trace the complete chain from user input → argument parsing → RPC/protocol → policy check → state persistence → external effect. LLM grading cannot replace deterministic state checks. |
| **Google** | [Mutation Testing at Scale](https://testing.googleblog.com/2021/04/mutation-testing.html) *(Apr 2021)*<br><br>Demonstrates that high test coverage percentages often correlate poorly with actual bug detection. Google injects realistic AST mutations into code during code review to test whether tests actually fail. | A passing test suite is meaningless if it cannot detect a plausible behavioral defect. | Apply isolated mutations (drop a request field, omit a menu choice, skip persistence) to verify test sensitivity. An undetected mutant exposes a check weakness. |
| **Microsoft Playwright** | [Testing Best Practices](https://playwright.dev/docs/best-practices)<br><br>Core philosophy of modern integration testing: prioritize user-visible behavior and real interface interactions over internal implementation details. | Testing internal methods creates brittle tests that pass while user interaction is broken. | Test at the true boundary (controlling PTY, rendered DOM, network gateway). Direct backend calls cannot substitute for driving the feature through the UI. |
| **NIST** | [Combinatorial Methods in Testing](https://csrc.nist.gov/Projects/automated-combinatorial-testing-for-software/combinatorial-methods-in-testing/interactions-involved-in-software-failures)<br><br>Extensive empirical studies on software failure triggers. Most bugs involve 1-2 interacting parameters, but security, privilege escalation, and recovery failures frequently require 3-4 interacting factors. | Pairwise testing is cost-effective for general options, but insufficient for critical authorization and lifecycle paths. | Apply pairwise combinatorial coverage across general parameters, but mandate explicit higher-order testing for authority, trust, restart, and recovery combinations. |
| **Hypothesis** | [Stateful Testing](https://hypothesis.readthedocs.io/en/latest/stateful.html)<br><br>Technique for generating sequences of actions against a stateful system, comparing transitions against a simplified model, and shrinking failing runs to minimal reproductions. | Real-world bugs hide in sequences of actions and state transitions, not isolated one-shot operations. | Exercise stateful sequences: `select → cancel → select`, `grant → restart → resume`, `grant → revoke → verify immediate denial`. Minimize failing sequences before reporting. |

---

## Key generalized learnings

### 1. The Presentation-State-Effect Triad
Research consistently reveals that verifying only one layer leads to false passes:
- **Presentation only**: Verifying a banner or stdout message passes even when the underlying action was never performed.
- **State only**: Verifying an in-memory or database record passes even when the UI never displayed the result to the
  user or when the actual external action failed.
- **Effect only**: Verifying a file was written passes even when the system failed to enforce authorization or record
  durable session metadata.
*Audit rule*: An operation is only qualified when presentation, authoritative state, and external effect all agree.

### 2. Symmetric access and refusal verification
NIST and security research demonstrate that testing only negative refusal cases creates a dangerous illusion of
security. A system with a broken parser or dead entry point will refuse everyone and pass 100% of refusal tests.
Conversely, testing only positive access will pass even if authorization checks are completely bypassed.
*Audit rule*: Every gated feature must be verified as a pair: positive access with prerequisites satisfied via normal
flows, and justified refusal with one prerequisite removed.

### 3. The Shared-Omission Trap
When test authors derive test inputs or assertion expectations dynamically from production code (e.g. `for mode in
SupportedModes.allCases`), any omission in production code causes the test to omit that case as well. Both sides agree,
yet the user feature is completely missing.
*Audit rule*: Expected choices, flags, and interactions must be derived independently from user requirements and
documentation, never from the internal enum or parser under test.

### 4. Test sensitivity validation (mutation testing)
Google's empirical findings prove that tests frequently assert on incidental details (like exit status or log formatting)
rather than actual behavioral requirements.
*Audit rule*: Prove that the check would fail if a realistic omission occurred (such as dropping a serialized field,
omitting an option from a picker, or failing to persist a setting).

### 5. Blind user-goal exploration
Anthropic's harness experiments highlight that developers and agents naturally follow the specific path they just coded,
taking implicit prerequisites for granted.
*Audit rule*: A real user or independent evaluator must attempt the goal using only public documentation and `--help`,
starting from a clean slate. Backdoor DB injections and internal API shortcuts are strictly forbidden.
