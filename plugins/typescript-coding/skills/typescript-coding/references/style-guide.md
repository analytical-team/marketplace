# TypeScript, React & Vite Style Guide & Patterns

A general-purpose style guide for TypeScript web apps built with Vite and React. It captures the conventions, patterns,
and anti-patterns that keep TypeScript code type-safe end to end, React components pure and predictable, and the build
fast — and keeps all of it legible to both contributors and coding agents.

It is distilled from primary sources rather than taste: the [Google TypeScript Style
Guide](https://google.github.io/styleguide/tsguide.html), the TypeScript team's [coding
guidelines](https://github.com/microsoft/TypeScript/wiki/Coding-guidelines) and [Do's and
Don'ts](https://www.typescriptlang.org/docs/handbook/declaration-files/do-s-and-don-ts.html), [VS
Code](https://github.com/microsoft/vscode/wiki/Coding-Guidelines), [Deno](https://docs.deno.com/runtime/contributing/style_guide/),
[react.dev](https://react.dev/reference/rules) (Rules of React, _You Might Not Need an Effect_, React Compiler), the
[Grafana frontend guide](https://github.com/grafana/grafana/blob/main/contribute/style-guides/frontend.md), [Bulletproof
React](https://github.com/alan2207/bulletproof-react/blob/master/docs/project-structure.md), the [Vite
docs](https://vite.dev/guide/performance), and the official `create-vite` React-TS template. Where those sources
disagree, the guide picks one and says why.

Rules with **safety or correctness** consequences (purity, effects, boundaries, async, security) are prescriptive — "do
this." Rules that capture **style** (naming, layout) are for consistency; follow them, but don't block a review on them
without cause. The linter and compiler enforce as much as they can; this document explains the rest.

> How to adopt this in your own app: copy this file in, delete the sections that don't apply (no Vite? skip §1's Vite
> config; no untrusted content? trim §16), and adjust the lint thresholds and browser floor to match your targets. The
> principles travel; the specific numbers are defaults.

> Versions this guide was written against (2026-10): TypeScript 7.0 (the native compiler, `tsc`), React 19.3, React
> Compiler 1.0, Vite 8 (Rolldown + Oxc), `@vitejs/plugin-react` 6, Vitest 5, oxlint 1.x with `oxlint-tsgolint` 7. Set
> your browser floor from your own support policy.

---

## 1. Toolchain baseline

- **Strict TypeScript, checked separately from the bundle.** Vite only _transpiles_ (Oxc, one file at a time, no type
  information); it never type-checks. `tsc -b` runs before `vite build`, and in CI, so a type error fails the build.
- **TypeScript 7 is the native compiler and ships as `tsc`.** The `tsgo` / `@typescript/native-preview` name is
  obsolete. TS 7 turns `strict` on by default, defaults `types` to `[]`, and makes `baseUrl`, `moduleResolution: node`,
  `target: es5`, and `esModuleInterop: false` hard errors — don't write any of them.
- **Lint with oxlint plus `oxlint-tsgolint` (type-aware).** typescript-eslint cannot run on TS 7.0 (no compiler API),
  and Biome's type inference is its own approximation. oxlint's type-aware engine runs the real TS 7 checker and covers
  the rules that matter (`no-floating-promises`, `no-misused-promises`, `switch-exhaustiveness-check`). It is also what
  the official Vite 8 template ships. Revisit ESLint once typescript-eslint supports the TS 7.1 API.
- **Format with Prettier.** oxfmt matches Prettier's output and will be a drop-in switch when it reaches 1.0; it is
  still 0.x.
- **One `check` script is the definition of done**: `tsc -b && oxlint && prettier --check .`, then the focused tests.

### tsconfig

Split the project like the `create-vite` template: `tsconfig.app.json` for `src/` (DOM lib, browser types) and
`tsconfig.node.json` for `vite.config.ts` (Node types, no DOM). A single tsconfig that includes both lets browser code
call Node APIs and the config call `window` without an error.

```jsonc
// tsconfig.app.json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
    "target": "es2024",
    "lib": ["ES2024", "DOM"],
    "module": "esnext",
    "moduleResolution": "bundler",
    "types": ["vite/client"], // TS 7 defaults types to []; without this import.meta.env is silently untyped
    "jsx": "react-jsx",
    "noEmit": true,
    "allowImportingTsExtensions": true,
    "skipLibCheck": true,

    "verbatimModuleSyntax": true, // forces `import type`; what you write is what Oxc emits
    "erasableSyntaxOnly": true, // bans enum, runtime namespace, parameter properties, import =/export =
    "isolatedModules": true, // Oxc transpiles per file with no type information
    "moduleDetection": "force",

    "noUncheckedIndexedAccess": true, // arr[i] and record[key] are T | undefined, as they are at runtime
    "exactOptionalPropertyTypes": true, // `x?: T` means "may be absent", not "may be undefined"
    "noImplicitOverride": true,
    "noPropertyAccessFromIndexSignature": true,
    "noFallthroughCasesInSwitch": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
  },
  "include": ["src"],
}
```

- `noUncheckedIndexedAccess` is the single most valuable flag outside `strict`: it makes the compiler agree with the
  runtime about missing array elements and map keys.
- `exactOptionalPropertyTypes` makes patch objects honest (`{ title?: string }` can't be handed `title: undefined` to
  "clear" a field by accident). If a third-party type fights it, fix the boundary, don't drop the flag.
- `isolatedDeclarations` is for libraries that emit `.d.ts`; it buys nothing in a `noEmit` app.
- Keep `tsBuildInfoFile` under `node_modules/.tmp`, not in the source tree.

### Vite config

```ts
// vite.config.ts
import babel from "@rolldown/plugin-babel";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// A relative base keeps every URL independent of where the bundle is served from. `strictPort` keeps the dev server
// where proxies and tooling expect it instead of silently moving to the next free port.
export default defineConfig({
  plugins: [react(), babel({ presets: [reactCompilerPreset()] })],
  base: "./",
  server: { port: 5173, strictPort: true },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: ["chrome130", "firefox130", "safari18"], // the oldest browsers you actually support
    cssTarget: ["chrome130", "firefox130", "safari18"],
    sourcemap: "hidden",
    assetsInlineLimit: 0, // no data: URIs, so the CSP needs no data: source
  },
});
```

- **Use only Vite 8 option names**: `oxc` not `esbuild`, `build.rolldownOptions` not `rollupOptions`,
  `output.codeSplitting` not the object form of `manualChunks`. The old names are deprecated aliases.
- **Set `build.target` to the real browser floor.** The default (`baseline-widely-available`) lowers syntax and flattens
  CSS nesting for browsers the app never runs in — or leaves out ones it must.
- **`vite preview` is not the real test.** It serves the build over plain `http://` with none of your production
  headers (CSP, caching) and none of your production host. Verify the build the way it is actually deployed.

---

## 2. Project layout

```
src/
  app/            # App shell: root component, screen routing, composition of features
  features/
    feed/         # Feed.tsx, FeedItem.tsx, feedStore.ts, feed.module.css, feedStore.test.ts
    editor/
    settings/
  api/            # The only code that touches the network, workers, or the host (fetch, WebSocket, postMessage)
  components/     # Shared, feature-agnostic UI (Button, Icon, VisuallyHidden)
  lib/            # Shared non-UI code with a real name (assertNever.ts, ids.ts)
  styles/         # tokens.css, base.css
  main.tsx
```

- **Organize by feature, not by kind.** A feature folder holds its components, hooks, store, styles, and tests. A new
  contributor deletes a feature by deleting a folder.
- **Imports flow one way: `components`/`lib`/`api` → `features` → `app`.** Features never import from each other;
  `app` composes them. When two features need the same thing, it moves down into `components/` or `lib/`. Cycles are a
  design bug, not a lint nit.
- **Colocate.** Tests, styles, and helpers live next to the code they serve. A helper stays in its file until a second
  caller appears.
- **Start flat and grow into the structure.** `src/components/` is fine for four components; introduce `features/` when
  a feature gains its own store, hooks, or styles — not before.

### Files

- **One responsibility per file; the file is named for its primary export.** `CommentBox.tsx` exports `CommentBox`.
  `feedStore.ts` exports the feed store and its hook.
- **`PascalCase.tsx` for component files, `camelCase.ts` for everything else.** Only files that contain JSX are `.tsx`.
- **No catch-all files.** No `utils.ts`, `helpers.ts`, `common.ts`, or `types.ts` grab-bags. A type lives with the code
  that owns it (`FeedItem` lives with the feed); a helper gets a file named for what it does (`formatRelativeDate.ts`,
  not `dateUtils.ts`).
- **Component files export only components** (and constants the component needs). React Fast Refresh falls back to a
  full reload otherwise; `react/only-export-components` enforces it.
- **Keep files small.** ~300 lines is a signal to split a component file, ~400 for any other module.
- **Order within a file:** imports, then exported types, then the primary export, then private helpers it uses. Private
  sub-components go below the component that renders them.

### Modules and exports

- **Named exports only; no `export default`.** A misspelled named import is a compile error; a default import binds to
  anything under any name, and renames don't follow it. Exceptions: `vite.config.ts` and a `React.lazy` target (or wrap
  it: `lazy(() => import("./Settings.tsx").then((m) => ({ default: m.Settings })))`).
- **No barrel files (`index.ts` that re-exports a folder).** Vite must load and transform every module a barrel
  re-exports, barrels turn HMR updates into full reloads, and they are the usual source of import cycles. Import from
  the file that defines the symbol.
- **`import type` / `export type` for type-only symbols.** `verbatimModuleSyntax` enforces it; it tells a per-file
  transpiler what to erase.
- **Write import extensions** (`./CommentBox.tsx`). Vite's performance guide recommends it — no filesystem probing — and
  it matches how the browser actually resolves modules. `allowImportingTsExtensions` permits it.
- **No path aliases.** Relative imports within a feature, and short ones across. TS 7 removed `baseUrl`, Vite's
  `resolve.tsconfigPaths` costs performance, and oxlint rejects `baseUrl`. If `../../../` ever genuinely hurts, use
  `package.json` subpath imports (`"imports": { "#src/*": "./src/*" }`), which TypeScript, Vite, and Node all resolve
  natively.
- **Export only what another module uses.** TypeScript has no `internal`; a small export surface is the only
  encapsulation.
- **No `export let`.** Importers see a live binding that can change under them. Export a function that returns the
  value.
- **No `namespace`, no `/// <reference>`, no `require()`.** ES modules only.
- **No static-only classes.** Export functions and constants from the module instead.
- **Import order:** platform and third-party packages, then project modules, then styles — one group each, sorted.
  Prettier (or oxfmt's import sorting, later) keeps it mechanical.

---

## 3. Naming

| Kind                                   | Style            | Example                                   |
| -------------------------------------- | ---------------- | ----------------------------------------- |
| Types, interfaces, components, classes | `UpperCamelCase` | `ProjectSummary`, `CommentBox`            |
| Values, functions, hooks, props        | `lowerCamelCase` | `saveProject`, `useFeed`, `onSubmit`      |
| Module-level true constants            | `CONSTANT_CASE`  | `MAX_RENDERED_ITEMS`                      |
| Union members / `as const` values      | as on the wire   | `"list"`, `"settings"`                    |
| Files                                  | see §2           | `CommentBox.tsx`, `feedStore.ts`          |

- **No `I` prefix on interfaces, no `T` prefix on types, no Hungarian notation, no leading or trailing `_`.** The type
  system already says what a thing is. (`_unused` parameters are the one tolerated exception, when a signature is
  fixed.)
- **Acronyms are words:** `loadHttpUrl`, `projectId`, `WebUrl` — not `loadHTTPURL`.
- **Callback props are `onX`; the component's own handler is `handleX`.** `<CommentBox onSubmit={handleSubmit} />`. The
  prop names the event, the handler names the reaction.
- **Booleans read as questions:** `isOnline`, `hasDraft`, `canSubmit`. But prefer a status union over two booleans (§5).
- **Hooks start with `use` and only functions that call hooks do.** A `useFormat` that calls no hook is just
  `format`, and naming it `use*` makes the linter enforce hook rules on it for nothing.
- **Name custom hooks for the use case** (`useFeed`, `useAutoScroll`), never for a lifecycle (`useMount`,
  `useUpdateEffect`) — those hide dependencies from the linter.
- **Name things after what they mean, not what they are made of.** `ProjectId`, not `IdString`; `draft`, not
  `textareaValue`.

---

## 4. Types

### `unknown`, never `any`

- **`any` disables type checking for everything it touches**, transitively. Use `unknown` for values whose type you
  don't know yet, and narrow before use. `catch (error)` is already `unknown` under `strict`.
- **No `{}`, `Object`, `String`, `Number`, `Boolean`** as types. Use `object`, `Record<string, unknown>`, or the
  lowercase primitives.
- **Callbacks whose result is ignored return `void`.** `(text: string) => void`, never `=> any` — `void` stops a caller
  from depending on a return value you never promised.

### `interface` for shapes, `type` for everything else

- `interface` for object shapes, including React props — error messages name the interface, and declaration merging is
  never what you want by accident because each interface lives in one file.
- `type` for unions, discriminated unions, tuples, function types, mapped and conditional types.
- Don't write a `type` alias for an object literal that an `interface` would express.

### No enums

- **`erasableSyntaxOnly` bans `enum`, `const enum`, runtime `namespace`, and parameter properties**, because a
  type-stripping compiler can't erase them. Use string-literal unions; they are also what crosses the wire as JSON.
- When you need the values at runtime (to iterate or validate), use an `as const` object and derive the type:

```ts
// Correct — the closed set is the type, and it is also a runtime value:
export const SCREENS = ["list", "settings"] as const;
export type Screen = (typeof SCREENS)[number];

// Avoid — enums don't erase, numeric members are falsy at 0, and the wire value isn't the source text:
enum Screen {
  List,
  Settings,
}
```

### Literals, `satisfies`, `as const`

- **Annotate, don't assert.** `const item: FeedItem = { ... }` catches a missing or misspelled field;
  `{ ... } as FeedItem` hides it.
- **`satisfies` checks a literal against a type while keeping its narrow inferred type** — the right tool for lookup
  tables and config.
- **`as const` for literal tables that never change.** It makes them deeply `readonly` and keeps literal types.

```ts
const SCREEN_TITLES = {
  list: "Projects",
  settings: "Settings",
} as const satisfies Record<Screen, string>; // adding a screen without a title is a compile error
```

### Assertions and suppressions

- **`as` only, never `<T>value`; every `as` gets a comment saying why it is safe.** Prefer a runtime check that narrows.
  A double cast (`as unknown as T`) is a code smell that needs a reason in the comment.
- **Non-null `!` is an assertion too.** Allowed where the DOM or framework guarantees it (`document.getElementById("root")!`
  for the node `index.html` defines), with the guarantee obvious or stated; otherwise narrow.
- **No `@ts-ignore` or `@ts-nocheck`.** `@ts-expect-error` only with a description of the specific error and why, so it
  fails loudly when the underlying issue is fixed.

### Optional, `null`, and `undefined`

- **Use `undefined` for "absent" internally; don't use `null` in app types.** The TypeScript team's own rule. Accept
  `null` only where a platform API or JSON produces it, and normalize it in the parser.
- **`x?: T` means the key may be absent; `x: T | undefined` means the key is present and may be `undefined`.** With
  `exactOptionalPropertyTypes` the compiler holds you to the difference — choose the one you mean.
- **`== null` is the one allowed loose equality** (it matches both `null` and `undefined`). Everything else is `===`.

### Other rules

- **Explicit return types on exported functions and hooks**; let inference handle locals and private helpers. An
  exported signature is a contract — it shouldn't change because an implementation detail did.
- **`readonly` by default for data.** `readonly` fields on shared data, `readonly T[]` for array parameters you don't
  own. Props and state are immutable by rule (§10); typing them so lets the compiler help.
- **`T[]` for simple element types, `Array<T>` / `ReadonlyArray<T>` for complex ones.**
- **`Map`/`Set` over index-signature objects** for dynamic keys — no prototype keys, real `size`, any key type.
- **Branded types for IDs and units that must not mix**, created only by the parser that validates them:

```ts
export type ProjectId = string & { readonly __brand: "ProjectId" };
```

- **`NoInfer<T>`** on a parameter that should be checked against `T` but not used to infer it (a default value checked
  against a list of options).
- **Prefer a union or optional parameter over overloads.** If you must overload, order them specific to general.
- **At most two positional parameters, then an options object.** Call sites stay readable and adding an option isn't a
  breaking change.

---

## 5. Modelling state and data

### Discriminated unions over boolean soup

Two related booleans encode four states, and usually only three are legal. A union makes the illegal one
unrepresentable, and narrowing gives each state exactly the fields it has.

```ts
// Correct — one status, each state carries its own data:
type Job =
  | { status: "idle" }
  | { status: "running"; jobId: string; progress: number }
  | { status: "failed"; jobId: string; error: string };

// Avoid — what does isRunning && error mean?
interface Job {
  isRunning: boolean;
  error?: string;
  progress?: number;
}
```

### Exhaustiveness, twice

`switch-exhaustiveness-check` catches a missing case at lint time; `assertNever` catches it at compile time _and_ throws
if an unexpected value arrives at runtime (a newer server sending a newer event, for example).

```ts
// lib/assertNever.ts
/** Marks a branch the type system proves unreachable; throws if a value arrives that the types didn't allow. */
export function assertNever(value: never): never {
  throw new Error(`Unexpected value: ${JSON.stringify(value)}`);
}

switch (event.type) {
  case "created": ...
  case "deleted": ...
  default:
    assertNever(event);
}
```

- In a `switch` over a union, the only permitted `default` is one that calls `assertNever`. A plain `default:` silently
  swallows the case someone adds next month.

### Parse, don't validate, at every boundary

Inside the app, trust the types. At the edges — `postMessage` and worker messages, WebSocket and SSE payloads,
`fetch` responses, `JSON.parse`, `localStorage`, URL parameters, anything from a host application — the type is a claim,
not a fact. Parse `unknown` into a typed value once, at the boundary, and reject what doesn't fit. **Never `as`-cast
parsed data.**

```ts
// Avoid — the cast is a promise nobody checked; a malformed event crashes deep inside a component:
const listener = (event: MessageEvent) => handler(event.data as ServerEvent);

// Correct — one parser per direction; unknown or malformed events are logged and dropped at the edge:
const listener = (event: MessageEvent<unknown>) => {
  const parsed = parseServerEvent(event.data);
  if (parsed.ok) handler(parsed.value);
  else console.warn("[events] dropped event:", parsed.error);
};
```

- For a handful of message types, a hand-written parser returning a result union is fine and has no dependency. When
  schemas grow, use a Standard Schema library — Valibot or `zod/mini` for a small bundle, Zod for ergonomics — and
  derive the TypeScript type from the schema so they can't drift.
- Each external channel has exactly one module per direction. Nothing else touches the raw transport (`fetch`,
  `WebSocket`, `postMessage`).
- Wire types mirror the other side's schema; change both sides in the same commit, and say so in a doc comment on each
  that names the file it mirrors.

### Immutability

- Treat arrays and objects as immutable once created. Build new ones (`[...list, item]`, `{ ...job, progress }`,
  `list.toSorted()`, `structuredClone` for deep copies) rather than mutating.
- This is a correctness rule in React (§10), and a readability rule everywhere else: a value that never changes never
  needs to be traced.

---

## 6. Error handling

- **Throw only `Error` or a subclass.** Anything else has no stack trace and breaks `instanceof`.
- **Wrap with `cause` when you rethrow** so the original is never lost:
  `throw new Error("Couldn't load project", { cause: error })`.
- **Expected failures are values; bugs are exceptions.** A parse failure, a "not found", a rejected save the UI must
  show — return a result union the caller has to handle. A violated invariant or impossible state — throw.

```ts
export type Result<T, E = string> = { ok: true; value: T } | { ok: false; error: E };
```

- Don't adopt Effect, neverthrow, or a monadic error library for an app this size. A two-member union is enough.
- **Custom error classes carry a typed `code`**, not information you'd have to parse out of `message`.
- **Narrow `catch (error)` with `instanceof`** before using it. Never assume a caught value is an `Error`.
- **No empty `catch`.** If ignoring an error is genuinely correct, the comment says why.
- **Keep `try` blocks small** — around the call that can fail, not the whole function.
- **Error boundaries catch render errors only.** Put one at the app root (and around any feature that renders untrusted
  content) so one broken item can't blank the window; event-handler and async errors are your code's to handle.
- **Messages are for people:** start with a capital, no trailing period, details after a colon —
  `"Couldn't parse event: missing type"`.

---

## 7. Async, cancellation, cleanup

- **No floating promises.** Every promise is `await`ed, returned, `.catch()`ed, or explicitly `void`ed with a comment
  explaining the fire-and-forget. A floating promise runs out of order and swallows its rejection.
  (`no-floating-promises`, `no-misused-promises`.)
- **Don't pass an async function where a `void` callback is expected** (`onClick={async () => ...}`). React ignores the
  promise, so its rejection is unhandled. Call a handler that catches:

```tsx
// Correct — the handler owns its errors; `void` marks the intentional fire-and-forget:
<button onClick={() => void handleRetry()}>Retry</button>;

async function handleRetry(): Promise<void> {
  try {
    await retryJob(jobId);
  } catch (error) {
    showError(error);
  }
}
```

- **Cancellable work takes an `AbortSignal`** in its options object and passes it down to `fetch` and to every child
  call. Combine sources with `AbortSignal.any([signal, AbortSignal.timeout(ms)])`; check `signal.throwIfAborted()` at
  checkpoints in long loops. An `AbortError` is not a failure to report.
- **An effect that starts async work aborts it in its cleanup**, so a fast unmount/remount (Strict Mode, a screen
  switch) can't apply a stale result.
- **`Promise.all` when every result is required** (fail fast); **`Promise.allSettled` when partial success is
  meaningful** and each outcome is reported. Never leave an array of promises un-combined.
- **Prefer `try/finally` and effect cleanups for resource cleanup.** `using` / `DisposableStack` are allowed for
  multi-resource cleanup (Oxc lowers them), but don't reach for them for a single listener.
- **Batch high-frequency updates.** Streaming tokens or socket messages arrive faster than the screen refreshes;
  accumulate them in the store and notify once per animation frame.
- **Timers are resources.** `setTimeout`/`setInterval` in a component is cleared in a cleanup, always.

---

## 8. Comments and documentation

- **`/** */` doc comments on exported API** — components, hooks, stores, API functions — that another contributor
  (or agent) would otherwise have to read the implementation to use. `//` for implementation notes.
- **Explain _why_, not what.** Browser quirks, message-ordering guarantees, why an effect must run before `ready` is
  posted, why a value is a ref and not state. A comment that restates the code will drift.
- **Never repeat types in JSDoc.** No `@param {string}`, `@type`, `@private`, `@enum` — TypeScript already says it.
  Write `@param`/`@returns` only when they add information the name and type don't.
- **Point across the boundary.** A wire type's doc comment names the file on the other side that mirrors it, so a
  change on one side leads to the other.
- **No ticket or PR references in code.** Context goes in commit messages.
- **Present tense, declarative:** "Subscribes to server events; returns the unsubscribe function."
- **Where this guide is silent, follow the surrounding file, then the surrounding folder.**

---

## 9. React components

### Declaring components

- **Function declarations with a typed props parameter. No `React.FC`, no class components.** `React.FC` adds nothing
  since React 18 and obscures the props type.
- **Props are an `interface` named `<Component>Props`** when there is more than one prop or the type is reused; inline
  for a single obvious prop.
- **`ref` is a plain prop.** `forwardRef` is unnecessary in React 19 and is slated for deprecation; don't use it in new
  code. `<Context value={...}>` replaces `<Context.Provider>` for the same reason.

```tsx
// Correct — React 19: ref arrives as a prop and the handle is a narrow interface:
export interface CommentBoxHandle {
  focus(): void;
}

interface CommentBoxProps {
  onSubmit: (text: string) => void;
  ref?: Ref<CommentBoxHandle>;
}

/** Enter submits, Shift-Enter adds a line. */
export function CommentBox({ onSubmit, ref }: CommentBoxProps) {
  const field = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => ({ focus: () => field.current?.focus() }), []);
  ...
}

// Avoid — forwardRef plus generic soup in the signature:
export const CommentBox = forwardRef<CommentBoxHandle, { onSubmit: (text: string) => void }>(function CommentBox(...) { ... });
```

- **Prefer passing data down over imperative handles.** `useImperativeHandle` is right for a genuinely imperative
  command from outside (a host application asking to focus the input); it is wrong for anything expressible as a prop.
- **Wrapping a native element? Extend its props** with `ComponentProps<"button">` (which includes `ref`) and spread the
  rest. Never give `className`, `style`, `onClick`, or `disabled` a different meaning.

### Component API design

- **Composition over configuration.** Accept `children` (typed `ReactNode`) or named slot props instead of a growing
  list of booleans (`showHeader`, `compact`, `withIcon`). A component that needs six booleans is two components.
- **Compound components (context-backed `Menu` / `MenuItem`) for tightly coupled groups**, not as a default.
- **Controlled or uncontrolled — per prop, never both.** Controlled takes `value` + `onChange`. Uncontrolled owns its
  state and takes a seed named `defaultX` or `initialX` so the reader knows later changes are ignored.
- **Avoid prop drilling with composition first** (pass the rendered child down instead of the data it needs), **context
  second.** Context is for values many distant components read and that change rarely (theme, text size); it re-renders
  every consumer on change.
- **Keep components small.** A component that scrolls off the screen, or that mixes data plumbing with layout, wants
  splitting into a container that reads stores and pure presentational children.
- **No I/O in presentational components.** Network calls, storage, and timers belong in stores, hooks, and event
  handlers — never in render.

### Lists and keys

- **Keys are stable IDs from the data.** Generate a local item's ID once, when the item is created (in the handler or
  store), with `crypto.randomUUID()` — never during render, never `Math.random()`, never the array index for a list that
  can reorder, insert, or delete.
- **Reset a subtree with `key`**, not an effect: `<Editor key={projectId} />` gives each project fresh scroll and draft
  state.

### JSX

- Self-close empty elements; boolean props in shorthand (`<textarea autoFocus />`, not `autoFocus={true}`).
- Conditional rendering with early returns or a ternary; avoid `count && <X />` (renders `0`). Use `count > 0 && …`.
- Extract a conditional or loop that needs a comment into a named sub-component.
- **No `dangerouslySetInnerHTML`** (§16).
- Icons: inline SVG components for the handful you have, or SVG files imported with `?url` / `?raw`. Don't add an
  SVG-to-component plugin; Vite's performance guide calls out its transform cost.

---

## 10. The Rules of React

These are not style. React (and especially the React Compiler) assumes them; breaking one produces bugs that only appear
under Strict Mode, concurrent rendering, or after compilation. The `react-hooks` lint rules encode them — treat every one
as an error.

- **Components and hooks are pure and idempotent.** Rendering may happen more than once, be paused, or be discarded.
  During render: no `Date.now()`, `Math.random()`, `crypto.randomUUID()`, no reading or writing `ref.current`, no
  mutating module state, no network or host calls. Side effects go in event handlers (first choice) or effects.
- **Props, state, hook arguments, hook return values, and anything already passed to JSX are immutable.** Make a new
  value; never `push`, `splice`, or assign into one.
- **Hooks are called only at the top level of components and hooks** — never in conditions, loops, callbacks, or after
  an early return.
- **Never call a component as a function** (`{FeedItem(props)}`) and never pass a hook around as a value. React must own
  the call to track identity and state.
- **Never define a component inside another component.** Each render creates a new type, so React remounts the subtree
  and throws its state away.
- **Keep `<StrictMode>`.** Its double render and double effect in development exist to expose impure renders and missing
  cleanups. Don't "fix" the double run with a ref guard — fix the missing cleanup.

---

## 11. State

### Choose the minimal structure

React's own five principles:

1. **Group state that changes together** into one object or one reducer.
2. **Avoid contradictions** — a status union, not `isSaving` + `isSaved` (§5).
3. **Avoid redundant state.** If it can be computed from props or other state, compute it during render.
4. **Avoid duplication.** Store an ID, not a copy of the object — a copy goes stale.
5. **Keep it flat.** Normalize nested collections into a map keyed by ID.

```tsx
// Correct — derive the selection from the source of truth:
const [selectedId, setSelectedId] = useState<ProjectId | undefined>();
const selected = projects.find((p) => p.id === selectedId);

// Avoid — a second copy that drifts when the list updates:
const [selected, setSelected] = useState<ProjectSummary>(projects[0]);
```

- **Never mirror a prop into state.** `useState(props.value)` reads the prop once. If that's intended, name the prop
  `initialValue`; otherwise use the prop directly.
- **State has exactly one owner**, lifted to the closest common parent of the components that need it — and no higher.
- **`useReducer` when the next state depends on the previous one in more than a line**, or when several fields move
  together. A reducer is a pure function: trivial to test against recorded event sequences.

### Where state lives

| Kind                                                    | Home                                                |
| ------------------------------------------------------- | --------------------------------------------------- |
| UI-only, one component (draft text, open/closed)        | `useState` in that component                        |
| Shared by a few nearby components                       | lifted `useState` / `useReducer`, passed down       |
| Rarely changing, read widely (text size, appearance)    | context                                             |
| Owned outside React (a socket, a worker, a host app)    | an external store read with `useSyncExternalStore`  |

Server-pushed data — a live feed, a conversation list, anything a socket or worker delivers — is **not React state**.
It lives in a small store module that the transport feeds and components subscribe to:

```ts
// features/feed/feedStore.ts — the only module that applies server events to the feed.
let snapshot: Feed = EMPTY_FEED;
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): Feed {
  return snapshot;
}

export function applyEvent(event: FeedEvent): void {
  snapshot = reduceFeed(snapshot, event); // pure; returns a new value only when something changed
  for (const listener of listeners) listener();
}

/** The current feed; re-renders when the server changes it. */
export function useFeed(): Feed {
  return useSyncExternalStore(subscribe, getSnapshot);
}
```

- `subscribe` is module-level (stable identity). `getSnapshot` returns the **same** immutable value until the data
  changes — returning a fresh object each call loops forever.
- Export hooks and commands, never the mutable variable.
- **Never copy store data into `useState`.** That forks the source of truth. (Seeding a form's draft is the one
  exception, and it's an `initialX`.)
- **No state library until a concrete need.** A push stream is not request/response, so a hand-written store fits.
  Zustand earns a place when many stores with selectors make hand-written ones unwieldy (then: export only custom
  hooks, atomic selectors, actions as events). TanStack Query earns a place when you have cached request/response
  calls.

### Actions and optimistic UI

- **Wrap async user operations in a transition** (`startTransition`, `useActionState`, or a form `action`) so React
  tracks `isPending` instead of a hand-rolled `isSaving` boolean.
- **`useOptimistic` to show the user's change immediately**, set inside the transition; React rolls it back if the
  action fails, so catch and show the error.

---

## 12. Effects

An effect synchronizes a component with an **external system** — a socket, the DOM, a timer, an observer. If no
external system is involved, it should not be an effect. Most effect bugs are effects that shouldn't exist.

- **Derived values are computed during render**, not set from an effect (which costs an extra render with stale data in
  between). If it's expensive, the React Compiler memoizes it.
- **Code caused by a user action goes in the event handler.** Submitting a form, notifying the parent, posting to the
  server — all handlers. "When the component appears" is an effect; "when the user clicked" never is.
- **Don't chain effects that set state in response to other state.** Compute the whole next state in one handler or
  reducer.
- **Every effect that sets something up returns a cleanup** that undoes it: listeners, subscriptions, observers, timers,
  in-flight requests (`AbortController`).
- **Dependencies are honest.** Never silence `exhaustive-deps`. If an effect re-runs too often, the fix is to move code
  out of it, split it, or read the latest value with `useEffectEvent` — not to lie about dependencies.
- **`useEffectEvent` for logic that is an event fired from inside an effect** (a subscription listener that must read
  the latest `isPaused` without resubscribing). Never call it during render, never pass it to children, never list it as
  a dependency.

```tsx
// Correct — subscribe once per job; the handler always sees current state:
const onProgress = useEffectEvent((update: Progress) => {
  if (!isPaused) applyProgress(update);
});
useEffect(() => subscribeToJob(jobId, onProgress), [jobId]);

// Avoid — `isPaused` in the deps resubscribes on every toggle; omitting it reads a stale value:
useEffect(() => subscribeToJob(jobId, (update) => { if (!isPaused) applyProgress(update); }), [jobId, isPaused]);
```

- **No `useMount` / `useUpdateEffect` / "run once" helpers.** They hide dependencies from the linter and fight Strict
  Mode.
- **Refs are for values that don't affect rendering** — DOM nodes, timer IDs, imperative handles. Don't read or write
  `ref.current` during render (lazy initialization `if (ref.current === null) ref.current = …` is the one exception).
  Callback refs may return a cleanup function; give them a block body.
- **Don't mutate DOM that React renders.** Imperative DOM work (scrolling, focus, measuring) is fine; inserting or
  restyling React-owned nodes is not.

---

## 13. Memoization and performance

### The React Compiler is on; manual memoization is the exception

- **Enable React Compiler** (via `@rolldown/plugin-babel` + `reactCompilerPreset()` — plugin-react 6 removed the inline
  `babel` option) and pin `babel-plugin-react-compiler` to an exact version: compiler upgrades can change when
  memoization applies.
- **Don't write `useMemo`, `useCallback`, or `memo` by default in new code.** The compiler memoizes more precisely than
  hand-written hooks, including after early returns. Keep manual memoization as an escape hatch — chiefly when a value
  must have a stable identity as an effect dependency — with a comment saying why.
- **Don't strip existing manual memoization casually**; it can change compiled output
  (`preserve-manual-memoization`).
- **A lint violation means the compiler skipped that component** — a silent performance loss on top of the bug. That's
  why the hooks rules are errors.
- **`"use no memo"` is a temporary escape hatch** with a comment naming the bug it works around.
- Oxc's faster React Compiler transform is promising but its Vite integration is experimental; revisit later.

### Before memoizing, restructure

- **Move state down** into the component that uses it, and **lift content up** by passing rendered elements as
  `children`. Both stop re-renders with no memoization at all.
- **Profile before optimizing** — React Performance Tracks in the browser's performance panel. An optimization without a
  measurement is a guess.

### Live feeds and long lists

- **A streaming update must re-render one item, not the whole list.** Keep items in the external store, and have each
  item subscribe to its own slice.
- **Start without virtualization; cap the rendered history.** Adopt TanStack Virtual (`anchorTo: "end"`,
  `followOnAppend`) when lists reach hundreds of heavy items. Exactly one piece of code owns `scrollTop`.
- **`useDeferredValue` for slow derived views** (filtering a long list). It doesn't debounce network calls; do that
  separately.
- **`<Activity mode="hidden">` to keep a hidden screen's state** (switching between tabs) instead of unmounting it. Its
  effects are torn down while hidden.
- **Code-split only what's heavy and rare** (a syntax highlighter, a diagram renderer) with `lazy` + `<Suspense>`.
  Splitting light code adds a request for nothing.

---

## 14. Accessibility

Accessibility is built into the component, not added by the caller.

- **Semantic HTML first.** `<button>` for actions (never a clickable `<div>`), `<form>` for submission, `<label>` or
  `aria-label` on every control, `<article>` per feed item, real headings. ARIA only where HTML has no element.
- **A live feed is a named `role="log"`.** While content streams in, set `aria-busy="true"` on it (or mark the streaming
  item `aria-live="off"`) so screen readers don't read half-words; announce completion once through a separate visually
  hidden `role="status"`. Keep the input and item chrome (timestamps, action bars) outside the log.
- **Keyboard-complete.** Submit, Stop, and every per-item action are reachable and operable from the keyboard, with a
  visible `:focus-visible` style.
- **Manage focus deliberately.** Focus stays in the input after submitting. Opening a dialog moves focus into it;
  closing restores it. Use the native `<dialog>` and `popover`, which get this right.
- **`autoFocus` only where focus is the obvious expectation** (the main input of a new, empty form), not as a habit.
- **Respect the user's settings:** `prefers-reduced-motion` disables non-essential animation; text sizes use relative
  units so browser and OS text settings apply, and layouts survive the largest value.
- **Lint with `jsx-a11y`** (oxlint plugin), and check with a screen reader for anything new and interactive. The linter
  catches missing labels, not confusing announcements.

---

## 15. Styling

**Plain CSS: global design tokens as custom properties, CSS Modules for component styles. No Tailwind, no Sass, no
CSS-in-JS.** Native CSS now covers what preprocessors did, Vite handles CSS Modules without configuration, and a
coherent look comes from semantic tokens, not a utility palette.

- **Tokens in one file** (`styles/tokens.css`): colors, spacing, radii, type scale, durations. Components use tokens,
  never raw hex values or magic pixel numbers.
- **Dark mode through the platform.** `:root { color-scheme: light dark; }` plus `light-dark()` in the tokens, so the
  page follows the system appearance with no JavaScript. Prefer system colors and fonts where they exist (`Canvas`,
  `CanvasText`, `AccentColor`, `font-family: system-ui`).
- **Component styles in `Component.module.css`** next to the component. Class names are scoped, so no naming scheme
  (BEM) is needed; name them for meaning (`.item`, `.assistant`), not appearance (`.grayBox`).
- **Explicit cascade order:** `@layer reset, tokens, base, components;` — no specificity wars, no `!important`.
- **Use modern CSS freely** within your browser floor — nesting, `:has()`, container queries, `@layer`, `color-mix()`,
  `light-dark()`, `@starting-style`, `text-wrap: balance`. Set `build.cssTarget` (§1) so Lightning CSS doesn't lower
  them.
- **Inline `style` only for values computed at runtime** (a measured height). Pass them as CSS custom properties and
  let the stylesheet use them, so the visual rules stay in CSS.
- **Animate `transform` and `opacity`;** respect `prefers-reduced-motion`.

---

## 16. Security

The page renders content it did not author — model output, user input, remote data — and may talk to backends or host
applications that can do real damage. Treat every boundary as an attack surface.

- **No `dangerouslySetInnerHTML`** (`react/no-danger` is an error). If raw HTML is ever unavoidable, it goes through
  DOMPurify with a strict allowlist in exactly one component.
- **Render model or user Markdown with `react-markdown` — never with `rehype-raw`.** Keep the default URL transform
  (blocks `javascript:`), set `skipHtml`, override `a` so external links open safely (`rel="noopener noreferrer"`, or
  through the host) instead of navigating the app away, and override `img` to block or proxy remote images (an image URL
  is an exfiltration channel). Add `rehype-sanitize` if any plugin emits HTML.
- **Every message from outside the page is untrusted `unknown`** until parsed (§5). Unknown `type`s are logged and
  dropped. Check `event.origin` on `postMessage`.
- **A strict Content Security Policy for the production build**, sent as a header by the server:
  `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none';
  base-uri 'none'; form-action 'none'` — widening `connect-src` only to the API origins you call. Never allow `data:` or
  `'unsafe-eval'` in `script-src`. The dev server needs inline scripts for React Refresh, which is why the policy
  applies to the production build only.
- **No secrets in the bundle.** Anything in `import.meta.env.VITE_*` is plain text in `dist/`. The client holds no
  credentials the user shouldn't see; the server does.
- **No `eval`, `new Function`, or string `setTimeout`.**

---

## 17. Testing

Whether to write a test is governed by one question: would it catch a realistic bug that simpler checks wouldn't? If the
project sets its own bar, follow it. Bugs hide at the boundaries.

**Worth testing:**

- **Boundary parsers** against recorded real payloads, plus malformed and unknown events.
- **Store reducers** against event sequences: streaming deltas, out-of-order or duplicate events, a reset mid-stream.
- **The Markdown renderer** against hostile content: `<script>`, `javascript:` links, remote images, raw HTML.
- **Interaction flows** that cross components: typing, Enter vs Shift-Enter, IME composition, submit, focus.

**Not worth testing:** markup snapshots, that a prop renders, styling, React itself.

### Conventions

- **Vitest, configured from `vite.config.ts`** (`test:` block) so tests transform and resolve exactly like the build.
- **Pure logic runs in Node** — no DOM environment for parsers and reducers.
- **Components run in Vitest Browser Mode on Playwright**, on the engines you ship to. jsdom and happy-dom simulate a DOM
  and miss real layout, focus, and CSS behavior.
- **Query the way a user (and a screen reader) does:** `getByRole` first, then `getByLabelText`, then `getByText`;
  `getByTestId` is a last resort. If a role query can't find it, that's an accessibility bug.
- **Simulate real interactions** with the browser-mode user-event API (or `@testing-library/user-event` v14), not
  `fireEvent`.
- **Test behavior, not implementation.** No asserting on state variables, hook call counts, or class names.
- **Test names read as sentences:** `it("drops events with an unknown type")`.
- **Colocate:** `feedStore.test.ts` next to `feedStore.ts`.
- **The real end-to-end surface is the production build served as it is deployed.** `vite dev` in a browser tab doesn't
  exercise your production headers, CSP, or host integration.

---

## 18. Dependencies

Every runtime dependency ships to every user and runs with the page's full privileges. The default is the platform:
`Intl`, `crypto.randomUUID`, `structuredClone`, `AbortSignal`, `<dialog>`, `popover`, CSS.

A new dependency earns its way in by clearing all of:

- **Concrete justification** — name the capability you'd otherwise build and maintain.
- **No reasonable platform path.**
- **Stable provenance** — maintained, typed, ESM, a clear release history.
- **Bounded scope and size** — check what it adds with `vite build` and the bundle analyzer (Vite DevTools, or
  `rollup-plugin-visualizer`), not the dev build.

Hygiene:

- **npm, with the committed `package-lock.json`; `npm ci` for builds.**
- **Exact versions in `package.json`**, so the manifest says what ships and every upgrade is a deliberate diff.
- **Supply-chain defaults in `.npmrc`:**

```ini
save-exact=true
; days: don't install a version published in the last 72 hours
min-release-age=3
engine-strict=true
allow-git=none
```

- npm 12 already blocks dependency install scripts by default; approve one only with `npm approve-scripts <pkg>` and a
  reason in the commit.
- `npm audit --omit=dev` periodically; upgrades in their own commits.

---

## 19. Lint and format configuration

```jsonc
// .oxlintrc.json (oxlint accepts comments; keep it otherwise plain JSON)
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc", "import", "jsx-a11y"],
  "options": { "typeAware": true },
  "categories": { "correctness": "error", "suspicious": "warn" },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/exhaustive-deps": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }],
    "react/no-danger": "error",
    "typescript/no-floating-promises": "error",
    "typescript/no-misused-promises": "error",
    "typescript/await-thenable": "error",
    "typescript/switch-exhaustiveness-check": ["error", { "considerDefaultExhaustiveForUnions": false }],
    "typescript/only-throw-error": "error",
    "typescript/restrict-template-expressions": "error",
    "typescript/no-explicit-any": "error",
    "typescript/ban-ts-comment": ["error", { "ts-expect-error": "allow-with-description" }],
    "import/no-default-export": "error",
    "import/no-cycle": "error"
  },
  "overrides": [{ "files": ["vite.config.ts"], "rules": { "import/no-default-export": "off" } }],
  "ignorePatterns": ["dist"]
}
```

- Enable oxlint's React Compiler rules (`react/purity`, `react/refs`, `react/immutability`,
  `react/preserve-manual-memoization`) as they leave experimental; until then they are part of review.
- **Disable a rule only with the rationale in the config itself**, and suppress a single line only with a comment
  saying why.
- **Prettier:** `printWidth: 120` (match the line width of your other languages), double quotes, semicolons, trailing
  commas — the defaults otherwise. Don't reformat files you aren't otherwise changing.

Scripts in `package.json`:

```json
{
  "dev": "vite",
  "build": "tsc -b && vite build",
  "lint": "oxlint",
  "format": "prettier --write .",
  "check": "tsc -b && oxlint && prettier --check .",
  "test": "vitest"
}
```

### Thresholds

| Rule                         | Signal to split | Hard ceiling |
| ---------------------------- | --------------- | ------------ |
| Line length                  | 120             | 120          |
| Function / component length  | 60              | 120          |
| Cyclomatic complexity        | 12              | 20           |
| Parameters                   | 2 + options     | 4            |
| File length                  | 300 (`.tsx`)    | 500          |

Treat the signal as the real ceiling: past it, the function or component almost always wants splitting. Enforce with
oxlint's `max-lines`, `max-lines-per-function`, `complexity`, and `max-params` as warnings.

---

## 20. Anti-patterns quick reference

When you find one of these, fix it.

**TypeScript**

- `any`, or `as` on parsed data → `unknown` and a parser at the boundary.
- `enum` / `namespace` / parameter properties → literal unions, `as const` objects, explicit fields.
- `export default` → named export.
- Barrel `index.ts` → import from the defining file.
- `utils.ts` / `helpers.ts` / `types.ts` grab-bags → give each thing a named home.
- Two booleans for one lifecycle → a discriminated union.
- `default:` in a union `switch` → `assertNever`.
- `@ts-ignore` → fix it, or `@ts-expect-error` with a reason.
- Throwing strings, or rethrowing without `cause` → `Error` subclasses with `cause`.
- Floating promises / async `onClick` → await, catch, or `void` a handler that catches.

**React**

- `React.FC`, `forwardRef`, `<Context.Provider>` → plain functions, `ref` as a prop, `<Context value>`.
- Derived data in state, or state set from an effect → compute during render.
- Effects for user actions → event handlers.
- Copying props or store data into `useState` → read the source; `initialX` if seeding is intended.
- Silencing `exhaustive-deps` → restructure, or `useEffectEvent`.
- Effects without cleanup → return the teardown.
- Default `useMemo` / `useCallback` / `memo` → let the compiler do it; profile first.
- Components defined inside components → module-level components.
- Index or random keys on dynamic lists → stable IDs created with the data.
- Network, `postMessage`, or host calls outside `api/` → go through the one module that owns that channel.

**Security and accessibility**

- `dangerouslySetInnerHTML` or `rehype-raw` on model or user content → `react-markdown` with safe overrides.
- Clickable `<div>` → `<button>`.
- Streaming text in a live region → `aria-busy` while streaming, one announcement on completion.

**Process**

- "It type-checks" or "it works in `vite dev`" treated as done → `npm run check`, focused tests, and the production
  build verified as deployed.

---

_The strong opinions here — parse at the boundary, unions over booleans, effects only for external systems, stores for
data React doesn't own, the compiler instead of hand-memoization, and the production build as the real test — are what
keep a TypeScript web app safe to change. Adjust the numbers; keep the principles._
