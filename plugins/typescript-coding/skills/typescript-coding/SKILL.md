---
name: typescript-coding
description: >
  Read before writing, editing, refactoring, or reviewing TypeScript, TSX,
  or React code, including components, hooks, stores, tests, and Vite or
  tsconfig configuration. Analytical Team's house style covers strict
  TypeScript, boundary parsing, discriminated unions, React purity and
  effects, external stores, React Compiler, cancellable async work,
  accessibility, CSS Modules, browser security, Vitest, oxlint, and Prettier.
  Also use for hooks and effects bugs, Strict Mode warnings, and guidance
  on TypeScript or React project structure.
---

# TypeScript, React & Vite coding style

Load `references/style-guide.md` for the full guide with rationale and worked
examples. Read the relevant section before writing code in that area — the
checklist below is a reminder, not a substitute.

Rules with **safety or correctness** consequences (purity, effects, boundaries,
async, security) are prescriptive. Style rules (naming, layout) are for
consistency.

**Project instructions win.** If the repo's CLAUDE.md / AGENTS.md interprets or
overrides a rule (a different test runner, path aliases, a state library, a
lint setup), follow the project. If the repo has its own copy of the guide,
that copy is authoritative. Sections that assume tools the project doesn't use
(Vite config, oxlint, CSS Modules) don't apply; the language and React rules
do everywhere.

## Before you write

1. If the rule you need is in the checklist and unambiguous, apply it.
2. Otherwise read the matching section of `references/style-guide.md`. Section
   numbers below map to headings in that file.
3. Match the surrounding code: comment density, naming, idiom. Don't reformat
   files you aren't otherwise changing.
4. Check the toolchain the project actually has (`package.json` scripts,
   `tsconfig*.json`, lint config) before assuming the guide's tools.

## Checklist

**Toolchain (§1)**
- `strict` TypeScript, type-checked separately from the bundle: `tsc -b` before
  `vite build` and in CI. Vite only transpiles.
- TS 7 is `tsc`. Don't write `baseUrl`, `moduleResolution: node`,
  `target: es5`, or `esModuleInterop: false`.
- tsconfig extras: `verbatimModuleSyntax`, `erasableSyntaxOnly`,
  `isolatedModules`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`,
  `noImplicitOverride`, `noPropertyAccessFromIndexSignature`. Split
  `tsconfig.app.json` (DOM) from `tsconfig.node.json` (Node).
- Vite 8 option names: `oxc`, `build.rolldownOptions`. Set `build.target` to the
  real browser floor. `vite preview` is not the real test.
- Lint with oxlint (+ type-aware `oxlint-tsgolint`); format with Prettier.
  `check` = `tsc -b && oxlint && prettier --check .`.

**Layout & modules (§2)**
- Organize by feature, not by kind. Imports flow one way:
  `components`/`lib`/`api` → `features` → `app`. Features never import each
  other; no cycles.
- One responsibility per file, named for its primary export. `PascalCase.tsx`
  for components, `camelCase.ts` for the rest; `.tsx` only if it has JSX.
- No `utils.ts` / `helpers.ts` / `common.ts` / `types.ts` grab-bags.
- **Named exports only** (no `export default`, except `vite.config.ts` and a
  `React.lazy` target). **No barrel `index.ts`.** No path aliases, no
  `namespace`, no `require()`, no static-only classes, no `export let`.
- `import type` for type-only symbols; write import extensions
  (`./CommentBox.tsx`). Export only what another module uses.
- Component files export only components. ~300 lines (`.tsx`) / ~400 (other):
  split.

**Naming (§3)**
- `UpperCamelCase` types/components; `lowerCamelCase` values/functions/hooks;
  `CONSTANT_CASE` true module constants.
- No `I`/`T` prefixes, no Hungarian, no leading/trailing `_`. Acronyms are words
  (`loadHttpUrl`).
- Callback props `onX`, own handlers `handleX`. Booleans read as questions
  (`isNative`, `canSend`). `use*` only for functions that call hooks, named for
  the use case — never `useMount` / `useUpdateEffect`.

**Types (§4)**
- `unknown`, never `any`. No `{}` / `Object` / `String`; ignored-result
  callbacks return `void`.
- `interface` for object shapes (incl. props); `type` for unions, tuples,
  functions, mapped types.
- **No enums.** String-literal unions; `as const` objects when you need the
  values at runtime, with the type derived.
- Annotate, don't assert. `satisfies` for lookup tables, `as const` for literal
  tables. Every `as` gets a comment saying why it is safe; `!` only where the
  guarantee is obvious. No `@ts-ignore`; `@ts-expect-error` with a reason.
- `undefined` for absent, not `null` (normalize `null` in the parser). `x?: T`
  ≠ `x: T | undefined`. `== null` is the only loose equality.
- Explicit return types on exports. `readonly` data. `Map`/`Set` for dynamic
  keys. Branded IDs. Max two positional params, then an options object.

**State & data (§5)**
- Discriminated union over two related booleans.
- Union `switch`: the only allowed `default` calls `assertNever`.
- **Parse `unknown` at every boundary** (`postMessage`, sockets, `fetch`,
  `JSON.parse`, storage, URL). Never `as`-cast parsed data. One parser per direction.
- Treat arrays/objects as immutable: build new ones.

**Errors (§6)**
- Throw only `Error` subclasses; rethrow with `{ cause }`. Expected failures are
  `Result` values, bugs are exceptions. Narrow `catch (error)` with
  `instanceof`; no empty `catch`; small `try` blocks. Error boundary at the app
  root.

**Async (§7)**
- No floating promises: `await`, return, `.catch()`, or `void` with a reason.
  Never `onClick={async () => ...}`.
- Cancellable work takes an `AbortSignal`; effects abort in cleanup. `Promise.all`
  when every result is required, `allSettled` when partial success matters.
- Timers and listeners are cleared in cleanup, always. Batch high-frequency
  updates per animation frame.

**Comments (§8)**
- `/** */` on exported API; explain *why*. Never repeat types in JSDoc. Wire
  types name the file on the other side they mirror. No ticket/PR references. Present tense.

**Components (§9)**
- Function declarations, typed props, `<Component>Props` interface. No
  `React.FC`, no class components, no `forwardRef` (`ref` is a prop),
  `<Context value>` not `<Context.Provider>`.
- Composition over boolean configuration; controlled *or* uncontrolled per prop
  (`defaultX` / `initialX` to seed). Props over `useImperativeHandle`.
- No I/O in presentational components. Keys are stable IDs created with the
  data — never index or `Math.random()` on dynamic lists. Reset with `key`.
- `count > 0 && …`, not `count && …`. No `dangerouslySetInnerHTML`.

**Rules of React (§10) — correctness**
- Render is pure and idempotent: no `Date.now()`, `Math.random()`,
  `crypto.randomUUID()`, ref reads/writes, module-state mutation, or network
  calls during render.
- Props/state/hook values are immutable. Hooks only at the top level. Never call
  a component as a function. Never define a component inside a component. Keep
  `<StrictMode>`; fix missing cleanups, don't guard the double run.

**State (§11)**
- Minimal state: group what changes together, avoid contradictions, derive
  instead of storing, store IDs not copies, keep it flat.
- Never mirror a prop or store data into `useState`. One owner, lifted no
  higher than needed. `useReducer` when next state depends on previous.
- State owned outside React → a store read with `useSyncExternalStore`
  (stable `subscribe`, `getSnapshot` returns the same value until data
  changes). No state library without a concrete need.
- Async user operations go in a transition (`useActionState`, `startTransition`);
  `useOptimistic` for immediate feedback.

**Effects (§12) — correctness**
- An effect synchronizes with an *external system* only. Derived values are
  computed in render; user-caused code lives in event handlers; don't chain
  effects.
- Every effect that sets something up returns its cleanup. Honest deps — never
  silence `exhaustive-deps`; use `useEffectEvent` for events fired from inside an
  effect.
- Refs are for values that don't affect rendering. Don't mutate React-owned DOM.

**Performance (§13)**
- React Compiler is on: no default `useMemo` / `useCallback` / `memo`; manual
  memoization only with a comment. A lint violation means the compiler skipped
  the component. Restructure (move state down, lift content up) before
  memoizing; profile first.
- A streaming update re-renders one item, not the whole list.

**Accessibility (§14)**
- Semantic HTML first (`<button>`, `<form>`, labels, headings, `<article>`); ARIA
  only where HTML has no element. Keyboard-complete with `:focus-visible`.
  Manage focus deliberately. Respect `prefers-reduced-motion` and text size.
  Streaming text: `aria-busy` while streaming, one `role="status"`
  announcement on completion.

**Styling (§15)**
- Plain CSS: tokens as custom properties, CSS Modules per component. No
  Tailwind, Sass, or CSS-in-JS. Tokens, not raw hex or magic pixels.
  `color-scheme: light dark` + `light-dark()`. `@layer` order, no `!important`.
  Inline `style` only for runtime-computed values (pass as custom properties).

**Security (§16) — correctness**
- No `dangerouslySetInnerHTML`, `eval`, `new Function`, or string `setTimeout`.
  Model output goes through `react-markdown` (never `rehype-raw`; `skipHtml`;
  links opened safely; block remote images).
- Every message from outside the page is untrusted until parsed. Strict CSP on the bundle. No
  secrets in the bundle (`VITE_*` is plaintext).

**Testing (§17)**
- Only where a realistic bug hides: boundary parsers, store reducers against event
  sequences, the Markdown renderer against hostile input, cross-component
  interactions. Not snapshots, not "a prop renders". If the project sets a
  stricter bar for *when* to write tests, follow it.
- Vitest configured from `vite.config.ts`; pure logic in Node; components in
  browser mode on the real engine. Query by role/label like a user; real
  user-event, not `fireEvent`. Behavior over implementation; sentence-style
  names; colocate tests.

**Dependencies (§18)** — platform first (`Intl`, `crypto.randomUUID`,
`structuredClone`, `AbortSignal`, `<dialog>`); a new one needs justification,
no platform path, stable provenance, bounded size. npm + committed lockfile,
`npm ci`, exact versions.

**Lint & format (§19)** — Prettier `printWidth: 120`. Line 120; function or
component 60 (ceiling 120); complexity 12 (20); 2 params + options (4); `.tsx`
file 300 (500). The signal is the real ceiling. Disable a rule only with the
rationale in the config.

## Before you finish

- Run the project's check script (`npm run check`, or `tsc -b`, the linter, and
  the formatter check) with no new warnings.
- Run the relevant tests when behavior changed.
- For UI work, verify the production build as it is deployed — a clean
  type-check and a working dev server are not done.
- Scan §20 (anti-patterns) of the guide against your diff.
