# Python Coding Style Guide & Patterns

A general-purpose style guide for modern Python applications and libraries. It captures the conventions, patterns, and
anti-patterns that produce code that is safe under concurrent use, easy to substitute and test, and legible to both
contributors and coding agents.

This guide is organized as a set of opinions with reasons. Where a rule carries **safety or correctness** consequences
(concurrency, errors, access control), read it as prescriptive — "do this." Where it captures **style** (naming, file
layout), follow it for consistency but don't block a review on it without cause.

---

## 1. Language baseline

- **Target Python 3.12+ with strict type checking.** Run `mypy --strict` (or `pyright` in strict mode) as part of CI.
  Treat type errors as correctness concerns, not warnings to suppress.
- **Use modern Python throughout:** `async`/`await`, `asyncio.TaskGroup`, `typing.Protocol`, `dataclasses`, `match`
  statements, `ExceptionGroup`. Do not introduce new callback-based concurrency unless bridging a library that requires
  it.
- **Do not use `threading`, `multiprocessing`, or `concurrent.futures` in new code.** `asyncio` gives the same
  capabilities with less ceremony and composable structured concurrency. The only acceptable use is bridging a blocking
  I/O library that has no async alternative — wrap it with `asyncio.to_thread`, not raw threads.
- **Do not use `queue.Queue` for inter-task coordination.** Use `asyncio.Queue` when tasks need to hand off work.
- **Annotate everything.** Function signatures, class attributes, and return types get type annotations. Use
  `from __future__ import annotations` at the top of files to enable forward references cheaply.

---

## 2. Naming

- **Classes** — `UpperCamelCase`, full words. No abbreviations except terms that are abbreviations everywhere (`URL`,
  `JSON`, `ID`, `HTTP`). Acronyms are uppercased: `JSONDecoder`, `HTTPClient`.
- **Functions & methods** — `lower_snake_case`, full words. Methods should read as English at the call site:
  `bridge.evaluate(script)`, `store.load(note_id)`, not `bridge.eval(s)`.
- **Protocols & abstract base classes** — name after the **capability or role** they represent: `NoteStore`,
  `PromptEncoder`, `Sendable`. Avoid `-Base`, `-Interface`, `-Mixin`, or `-Manager` suffixes glued onto names that
  aren't really capabilities. If you struggle to name a protocol after a real capability, it may not be earning its
  keep.
- **Parameters** — descriptive names. Avoid `value`, `data`, `result`, `item` unless the thing genuinely is opaque at
  that point.
- **Booleans** read as assertions: `is_enabled`, `has_changes`, `can_retry`.
- **Files / modules** — `lower_snake_case`, named after the primary type they contain (see §4).
- **Short local names** (`i`, `c`, `x`) are fine in tight scopes like loop bodies and short lambdas; full words
  everywhere persistent.
- **No leading underscores** on any name — no `_helper`, `__internal`, or `_MyClass`. Underscore-prefixed names
  communicate "private" by convention, and this guide bans that pattern entirely (see §5).

### Prefer enums over magic strings

**When a value is drawn from a small, closed set, model it as an `enum`, not a bare `str` (or `int`).** A field typed
`str` with a comment listing the allowed values is the type lying about itself — the comment drifts, typos pass type
checking, and the valid set isn't greppable. An enum makes the closed set explicit, lets the type checker reject invalid
members, and gives every value a greppable symbol.

```python
import enum

# Avoid — the type permits any string; the real contract lives in a comment that will drift:
auth_method: str | None = None  # "session" | "jwt" | "api_key" | None


# Correct — the closed set is the type. Subclass StrEnum when the wire/JSON value must stay a plain string:
class AuthMethod(enum.StrEnum):
    SESSION = "session"
    JWT = "jwt"
    API_KEY = "api_key"


auth_method: AuthMethod | None = None
```

Reach for `enum.StrEnum` (or `enum.IntEnum`) when the value crosses a serialization boundary and must compare equal to
its raw string (or int) form; use a plain `enum.Enum` otherwise. A `typing.Literal` is acceptable for a private, one-off
set that never needs members, iteration, or methods — but prefer an enum the moment the set is shared across modules or
gains behavior. Define the enum next to the type that owns it (§4) and import it where needed rather than re-spelling
the strings.

### Enum member qualification

**Always use fully qualified enum members.** Prefer `Color.BLUE` over a bare re-exported name, `TaskState.PENDING` over
an imported alias.

```python
# Correct — type is unambiguous without reading surrounding context:
language = NLLanguage.ENGLISH
state = TaskState.PENDING
raise PromptEncodingError.CANCELLED

# Avoid — type must be inferred; invisible in diffs and searches:
language = ENGLISH  # where did this come from?
state = PENDING
```

**Rationale:**

- Explicit types survive being read out of context (grep results, diffs, code review, agent analysis).
- Symbols are greppable — `TaskState.PENDING` appears in search results; a bare `PENDING` does not.
- Reduces ambiguity when the same name exists in multiple enums.

**Exception:** shorthand is acceptable inside a `match` arm, where the enum type is stated in the subject expression and
cannot be misread:

```python
match language:
    case NLLanguage.ENGLISH:  # type is declared in the match subject
        ...
    case NLLanguage.FRENCH:
        ...
```

---

## 3. Project layout

A project is **a package plus numbered scripts plus tests plus data**, in four top-level directories. The shape is the
same whether the thing is a library, a service, or a data pipeline, and it is worth being rigid about: a contributor (or
an agent) who knows the layout can find the reusable code, the entry points, and the fixtures without being told.

```
myproject/
├── pyproject.toml          # uv-managed; the package is the project
├── .python-version
├── src/myproject/          # the package: everything reusable and importable
│   ├── settings.py         # the root Settings (§6)
│   ├── services.py         # the Services registry (§6)
│   └── blob_store.py       # one primary class per file (§4)
├── scripts/                # runnable entry points, grouped by category
│   ├── data/
│   │   ├── 100_build_deduped.py
│   │   └── 110_fetch_base.py
│   ├── train/
│   │   ├── 100_train.py
│   │   └── 110_quantize.py
│   └── eval/
│       └── 100_eval.py
├── tests/                  # pytest suite, doubling as usage documentation (§11)
└── data/                   # gitignored; inputs, intermediates, outputs
```

### Start with `uv init`, and keep the package as the project

Create the project with `uv init --package` (or `uv init --lib`) so you get a `src/` layout, a `pyproject.toml`, and a
pinned `.python-version` from the start. Use `uv add` / `uv remove` to manage dependencies and commit `uv.lock`. Run
everything through `uv run` — `uv run pytest`, `uv run scripts/data/100_build_deduped.py` — so there is one environment
and no activation step to forget.

**Prefer the `src/` layout** over a bare package directory at the repo root. It makes the installed package the thing
under test: an import that only works because the CWD happens to be the repo root fails loudly instead of passing
locally and breaking on install.

### Never modify `sys.path`

**A script imports the package the same way any other consumer does — `from myproject.thing import X`.** `uv run` puts
the installed project on the path, so the import already works. Never append to or insert into `sys.path`, and never
reach for `sys.path.insert(0, str(REPO_ROOT / "src"))` to make an import resolve.

```python
# Don't
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from myproject.distillation import DistillationRun  # noqa: E402

# Do
from myproject.distillation import DistillationRun

REPO_ROOT = Path(__file__).resolve().parents[2]
```

A `REPO_ROOT = Path(__file__).resolve().parents[2]` constant is fine, and often needed — for default option paths
(`REPO_ROOT / "data" / "distilled"`) or for locating a `.env`. What's banned is using it to patch the import path. That
patch defeats the whole point of the `src/` layout (§ above): it makes an import work from a checkout that would fail
from an install, and it silently shadows the installed package with the working tree. It also forces imports below the
mutation, which is why the `noqa: E402` suppressions show up — treat that comment on an import as the smell that names
the problem.

If an import genuinely doesn't resolve, the fix is in the project, not the script: the module isn't under
`src/myproject/`, the package isn't installed (`uv sync`), or the script is being run with bare `python` instead of
`uv run`.

**The one exception is importing a numbered script itself** — from a test, or from a remote-execution wrapper that has
to load `100_train.py` on the far side. `scripts/` is not a package and `100_train` is not a valid identifier, so
`sys.path.insert` plus `importlib.import_module("100_train")` is the only way in. Keep it to that case, put it next to
the `importlib` call so the reason is visible, and note that this is a script import, not a package one. If you find
yourself wanting it for anything else, the code you're reaching for belongs in the package.

### The package holds everything reusable; scripts hold none of it

**`src/myproject/` is where logic lives.** Anything used by more than one script, or worth testing in isolation, belongs
in the package — models, clients, the `Services` registry, the `Settings` tree, domain functions. §4's rules (one
primary class per file, no `utils.py`, no globals) apply here.

**A script is a thin CLI over package code.** It parses arguments, calls into the package, and reports what happened —
ideally a few dozen lines. The moment a script grows a class, a non-trivial function, or logic a second script wants,
that code moves into the package and the script imports it. Two tests of whether the line has been crossed: could you
unit-test this without invoking the script, and would a second script have to copy-paste it?

This split is what keeps a pipeline maintainable. Logic in the package is importable, testable, and typed; logic in a
script is reachable only by running the script with the right arguments in the right order.

### Build every script's CLI with `click`

**Use `click` for script arguments — not `argparse`, not `sys.argv`, not a bare `input()`.** One decorated `main` gives
you typed options, defaults shown in `--help`, path and range validation, and flags, without hand-written parsing. Being
uniform matters more than the individual merits: every script in the repo is then invoked, documented, and validated the
same way.

- **Every script runs with no arguments.** `uv run scripts/data/110_fetch_base.py` must do the sensible default thing.
  This is the load-bearing rule here; see "Default every option" below for what it requires.
- **One `@click.command()` and a `main` function per script**, with `if __name__ == "__main__": main()` at the bottom.
  Reach for `@click.group()` only when a script genuinely has subcommands — usually that is a sign it should be two
  numbered scripts.
- **Let `click` do the validation.** `type=click.Path(path_type=Path, exists=True)` for an input that must exist,
  `click.IntRange(min=0)` for a bounded number, `type=click.Choice([...])` (or an enum, §2) for a closed set. A value
  `click` rejects is a clean error message instead of a traceback from deep inside the run. Validation is compatible
  with defaulting everything — `exists=True` checks the defaulted path just as it checks a supplied one; what's banned
  is `required=True`, not type-checking.
- **`show_default=True` on every option with a default**, and a `help=` string on every option. `--help` is the
  interface most people actually read.
- **Long-form option names** (`--max-epochs`, not `-e`) so an invocation pasted into a worklog or a README is
  self-explanatory. Add a short alias only for something typed constantly.
- **`click.echo` for output**, not `print`.
- **Annotate `main`'s parameters** like any other function (§1), matching the option types.

### Default every option so the script runs bare

**No `required=True`, and no positional arguments without a default.** Every option carries a default that makes
`uv run scripts/<category>/<NNN_name>.py` — with nothing after it — do the obvious right thing. A script that demands
five flags before it will start is one nobody runs without first reading its source, and it can't be the copy-pasteable
first line of its own `Usage:` block.

What this requires in practice:

- **Default paths to the conventional `data/` locations** the pipeline already uses — `data/base` for the fetch step's
  output, the previous stage's output directory for the next stage's input. Because the layout is a convention (§3
  above), the defaults are knowable rather than arbitrary, and the stages chain with no arguments at all.
- **Default the expensive knobs to something small.** A shard count, an epoch limit, or a sample size defaults to a
  slice that finishes quickly, with a flag to ask for the full run. The bare invocation should be safe to try, not a
  surprise 236 GB download.
- **Default flags to the safe side.** `is_flag=True` options default to `False`, so the destructive or costly behavior
  is the one you opt into — `--force`, `--overwrite`, `--all-shards`, never `--no-overwrite`.
- **Derive, don't demand.** Where a value could be required, compute it instead: find the newest checkpoint in the run
  directory, read the setting from `Settings` (§6), or pick the single obvious candidate — and say what was chosen in
  the output. Fail with a clear message naming the script that produces the missing input.

The payoff is that the pipeline is runnable end to end by someone who has read nothing, and every stage's default
invocation is a line you can paste into a README or a worklog.

### The script docstring is its usage documentation

**Every script opens with a module docstring that ends in a `Usage:` block of real, runnable command lines** — the exact
`uv run scripts/<category>/<NNN_name>.py --option value` invocations someone would type. Start with the bare no-argument
form, then the variations worth knowing, one per line with a short trailing comment where the flag's purpose isn't
obvious.

This is the same instinct as tests-as-documentation (§11): the usage lives next to the thing it describes, so it is
found by anyone opening the file, and it is written in the form you can copy and run rather than prose _about_ running
it. Above the `Usage:` block, say what the script does and anything a caller needs to know before running it — what it
writes, what it costs, what it depends on having been run first.

```python
#!/usr/bin/env python3
"""Fetch the base model weights and a slice of the pretraining corpus.

SYNTH is ~236 GB across 500 parquet shards, so the corpus download is capped by
`--shards` and defaults to a small slice. Pass `--shards 0` to take all 500 only
if you actually intend to pretrain from scratch.

Usage:
    uv run scripts/data/110_fetch_base.py                 # weights + 2 shards
    uv run scripts/data/110_fetch_base.py --shards 10
    uv run scripts/data/110_fetch_base.py --skip-corpus   # weights only
"""


@click.command(help="Fetch the base model weights and a slice of the pretraining corpus.")
@click.option(
    "--out", type=click.Path(path_type=Path), default=Path("data/base"), show_default=True
)
@click.option(
    "--shards",
    type=click.IntRange(min=0),
    default=2,
    show_default=True,
    help="Corpus shards; 0 for all.",
)
@click.option("--skip-corpus", is_flag=True, help="Fetch weights only.")
def main(out: Path, shards: int, skip_corpus: bool) -> None: ...


if __name__ == "__main__":
    main()
```

Keep the docstring's `Usage:` lines and the `click` options in sync — an invocation in the docstring that no longer
parses is worse than none, and it is the first thing to check when editing a script's options.

### Number scripts in execution order, grouped by category

Scripts live in `scripts/<category>/` — `data/`, `train/`, `eval/`, `deploy/` — and each is prefixed with a three-digit
number giving its **order of execution within that category**: `100_build_deduped.py`, then `110_fetch_base.py`, then
`120_distill.py`.

- **Step by tens.** `100`, `110`, `120` leaves room to insert `105` later without renumbering — which matters, because
  renumbering breaks every doc, worklog entry, and shell history that referenced the old name.
- **Numbers are per category**, restarting at `100` in each. `data/100_*.py` and `train/100_*.py` coexist fine.
- **The number is a reading order, not a dependency graph.** It tells a newcomer what runs first. Where a script truly
  requires an earlier one's output, it should fail with a clear message about which script to run — not rely on the
  number to have been noticed.
- **Name the verb**: `110_fetch_base.py`, `120_quantize.py`. The number orders; the name says what it does.

The payoff is that `ls scripts/data/` _is_ the pipeline documentation, in order, without a README that drifts.

### `data/` is gitignored, and nothing importable lives there

`data/` holds inputs, intermediates, and outputs — downloaded corpora, generated datasets, model weights, eval results.
**Gitignore it**, by subdirectory or wholesale. Datasets and weights are large, binary, and usually
externally-reproducible; a repo that swallows them becomes slow to clone and expensive to host forever, since git keeps
every version.

- **Make it reproducible instead of committing it.** A `scripts/data/` script that fetches or rebuilds a directory is
  worth more than the directory in git, because it also documents where the data came from.
- **Keep the layout under `data/` conventional and mirrored by stage**: `data/external/` for third-party downloads,
  `data/<stage>/` for each stage's output. A reader should be able to guess which script wrote a directory.
- **Never `import` from `data/`.** It is not a package; it holds bytes, not code.
- **Commit the small explanatory files** — an `INVENTORY.md` describing what a directory should contain and where it
  came from, or a tiny fixture a test needs. Negate the ignore for these deliberately (`!data/external/INVENTORY.md`).
- **Exclude it from tooling** that would otherwise walk it: add `data/` to `ruff`'s `exclude`, and keep it out of the
  package's build target.

---

## 4. File & module organization

- **A module is a unit of cohesion, not a line budget.** File size and line count are not something to optimize for in
  either direction — don't split a cohesive module to make it shorter, and don't pad a small one to look substantial.
  What matters is whether everything a reader needs to understand and use the thing lives in one place.
- **One module per client or subsystem, holding everything that belongs to it.** A self-contained integration — a Google
  auth client, an S3 client, OIDC middleware — is a single file containing its settings class, its request/response
  models, its exceptions, its module-level helper functions, and the client class itself. Splitting one client's
  settings into `s3_settings.py`, its response models into `s3_models.py`, and its client into `s3_client.py` scatters
  one concept across files a reader has to open and reassemble in their head; keep them together in `s3_client.py` even
  when that makes the file long. Length is not a reason to split — a module stays whole as long as it is cohesive; it
  splits when it stops being about one thing (it holds two unrelated clients, or a client plus domain logic that doesn't
  belong to it), never because it crossed a line count.
- **One primary class per file remains the default outside that case.** The file name matches the class: `blob_store.py`
  contains `BlobStore`. The client/subsystem module above is the deliberate exception: everything that exists only to
  support that one client lives beside it rather than fanned out into sibling files.
- **Co-locate small helpers.** Module-level helpers that support only the primary class in the same file, and small
  dataclasses used only by that class, live in the same file.
- **Use a descriptive suffix for focused extensions.** When a module extends a type with a focused capability, name the
  file `type_capability.py` (e.g., `date_formatting.py`). The scope is visible at a glance.
- **No catch-all modules.** Never create `helpers.py`, `utils.py`, `extensions.py`, or `common.py`. They become magnets
  for unowned code. Either the helper has a home with the type it operates on, or it deserves its own named module
  (`string_escaping.py`, not `string_helpers.py`).
- **Order within a file:** class attributes first, then `__init__`, then methods grouped by responsibility. When a
  module holds more than one class — settings, models, the client — order them in the sequence a reader needs them:
  settings and data types first, the class that consumes them last.
- **No global variables.** Module-level mutable state is banned. Constants (all-caps, immutable) are the sole exception.
  If you need shared mutable state, it belongs in a class — and state that outlives a single request belongs in an
  expirable cache, not an in-memory dict (§6).

---

## 5. Visibility & API design

Python has no enforced access control, so **this guide substitutes a strict naming rule: every name is public.** There
are no leading-underscore names, no double-underscore mangling, and no "internal" convention. If something genuinely
should not be part of the API, restructure so it doesn't need to exist as a name at all — move it inline, merge it into
the caller, or extract it to a helper class with its own clean surface.

**Why:** underscore-prefix "privacy" is unenforceable, ignored by IDEs and agents, and communicates "don't touch"
without enforcing anything. The real answer is a clean public surface, not a naming convention that pretends to hide
things.

### `__all__`

Declare `__all__` in every module that is part of a public package surface. It is the true visibility boundary — what
callers can rely on. Keep it intentionally small. Anything absent from `__all__` is treated as unstable even if
technically importable.

### Lead with protocols, not concrete types

This is the load-bearing design principle for any code meant to be **substitutable, testable, or reusable**.

- A module's public surface should be dominated by **`typing.Protocol` types and dataclasses**, not concrete classes.
  The concrete type can still be exported (so consumers use it out of the box), but the thing they _annotate their
  dependencies against_ is the protocol.
- Protocols have a **single, focused responsibility.** If adopters routinely implement only half of a protocol, split
  it.
- Use `typing.Protocol` (structural subtyping) by default — callers do not need to import or inherit from your protocol
  to satisfy it. Reserve `abc.ABC` (nominal subtyping) when you need to enforce the inheritance chain or provide
  meaningful default implementations.
- Default method implementations on `Protocol` subclasses are encouraged for _ergonomic_ methods, but not for behavior
  an adopter would reasonably want to override.

```python
from typing import Protocol, runtime_checkable


@runtime_checkable
class NoteStore(Protocol):
    async def load(self, note_id: str) -> Note: ...
    async def save(self, note: Note) -> None: ...


# A default implementation callers can use out of the box —
# but the type they annotate is `NoteStore`, not this class.
class FileNoteStore:
    async def load(self, note_id: str) -> Note: ...
    async def save(self, note: Note) -> None: ...
```

**Why:** a concrete-type-only public API forces forks. A protocol seam invites substitution and makes the code testable
with a fake.

### Keep modules from depending on each other's internals

Independent areas of a codebase should communicate only through **protocols and dataclasses** — never through shared
global state, singletons, or module-level symbols that happen to be importable. A dependency that looks harmless inside
the codebase becomes a forced dependency for anyone who wanted only one piece. If two areas need something shared, hoist
it cleanly above both and keep it small.

---

## 6. Application structure & dependency wiring

Dependencies are wired through a single `Services` registry and plain functions — not ad-hoc globals or service-locator
classes.

### Classes hold resources; functions use them

- A **class** earns its place when it owns a resource, client, or long-lived/mutable state: a database pool, a cache, an
  HTTP or directory client, a background-task supervisor. Construct and own these on the central `Services` registry and
  nowhere else (§4 forbids module-level globals; `Services` is where shared state lives), so lifecycle — setup and close
  — is in one place.
- **Behavior that merely uses those resources is a module-level function that takes `services` (or the single service it
  needs) as its first parameter** — not a class. Do not introduce a class just to hold a `services` reference and hang
  methods off it: it reads as something that ought to be registered on `Services`, yet registering it would only add
  wiring and often an import cycle. A function `do_thing(services, ...)` has no lifecycle and is trivially testable with
  a fake `services`.

```python
# Resource: constructed and owned by Services.
class Services:
    def __init__(self) -> None:
        self.cache = Cache(...)
        self.databases = PostgresRegistry(...)


# Behavior: a plain function taking services first.
async def list_api_keys(services: Services, *, dsid: str) -> list[ApiKeyInfo]:
    async with acquire(services) as conn:
        ...
```

### Prefer module-level functions to nested closures

Behavior belongs at module level, taking its dependencies as parameters — not nested inside another function as a `def`,
`async def`, or `lambda` that closes over them. A nested function hides a unit of behavior where it can't be imported,
named in a traceback, or tested on its own, and it usually closes over local state that a parameter would carry just as
well. This is the same instinct as preferring a function to a class that only holds `services` (above): if a nested
helper needs only values you could pass it, lift it to the module and pass them. A cross-cutting check is the worked
example — `forbid_unless_member(services, *, dsid, group_ids)` is a module-level function, and the dependency factory
that gates a route merely _calls_ it; it does not re-implement the check inside a closure.

Nesting is warranted only when a framework or library hands you state you cannot reach any other way — and even then the
closure stays a thin shell that delegates real work to a module-level function. The legitimate cases:

- a **FastAPI dependency factory** closing over its fixed arguments (see "Parametrize a dependency with a factory");
- an **ASGI middleware** wrapping the per-request `send`/`receive` it is handed in `__call__` — it closes over
  request-lifetime state (a response-started flag, an inbound queue, a cancel scope) that has no life outside that one
  call;
- a **`@functools.wraps` decorator** wrapping the handler it decorates;
- a **callback a C or library API demands** — an `asyncpg` type codec, a `threading.Timer` fire, a `StreamingResponse`
  generator binding the per-request spill file it must delete on completion.

Lambdas follow the same line: fine as a **deferred thunk an API demands**
(`cache.remember(key, ttl, lambda: fetch(...))`), a lazy accessor, or a sort `key=`; never as a place to park logic. Use
a named callable for `default_factory=` (`Field(default_factory=list)`), never `default_factory=lambda: ...`.

### Resources construct synchronously, set up asynchronously

A constructor cannot be `async`, so a resource that needs I/O to become usable splits initialization in two. `__init__`
does only cheap, synchronous wiring — open a handle, read settings, allocate the lock. An awaited `setup()` does the I/O
— connect the pool, fetch initial state, attach databases — and must run once before the first request is served.
Shutdown mirrors it: a `close()` (or `aclose()`) releases what `setup()` acquired. The composition root drives all three
from one place (a FastAPI `lifespan`, a CLI `main`), so every resource opens and closes in the same order, once.

A resource is legal to construct but not yet usable in the window between `__init__` and `setup()`; keep that window
inside single-threaded startup, before anything concurrent can touch it. Don't paper over a missing `setup()` with lazy
"connect on first use" guards scattered through the methods — that smears the lifecycle the registry exists to
centralize.

```python
class QueryEngine:
    def __init__(self, settings: Settings) -> None:
        self.connection = connect(settings)  # cheap, synchronous
        self.lock = asyncio.Lock()

    async def setup(self) -> None:
        """Awaited once at startup, before the server serves."""
        await self.attach_databases()
        self.lock_down()
```

### Optional resources are typed `T | None`, resolved through a `require_*` helper

A resource that may not be configured in a given deployment is typed `T | None` on `Services` and left `None` when its
configuration is absent — the app runs degraded rather than refusing to start. Callers do not each re-check for `None`:
a single `require_thing(services) -> Thing` helper returns the resource or raises one uniform "not configured" error (a
503 at an API boundary). Handlers then receive a non-`None` value, and the unconfigured branch — its message, its status
code — lives in exactly one place per resource.

```python
def require_platform_store(services: Services) -> PlatformStore:
    """Return the platform store, or raise 503 when it is not configured."""
    store = services.platform_store
    if store is None:
        raise HTTPException(status_code=503, detail="projects are unavailable")
    return store
```

### Cross-request state belongs in an expirable cache, not an in-memory dict

The tempting shortcut is a `dict` — module-level, or hung on a long-lived object — that accumulates state between
requests. It is a memory leak with no expiry, lost on restart, and wrong the moment a second instance runs. §4 already
bans the module-level case; the rule here is stronger: **state that outlives a single request belongs in a local cache
that can expire**, not in process memory.

Reach for a small SQLite-backed cache — one file, written and read by this process — keyed by a string, with a per-entry
TTL and a compute-on-miss helper. Sessions, resolved directory lookups, anything derived-and-reusable goes there: it
bounds memory by expiring rows, survives a restart, and gives every cached thing one place with one eviction story.
Reconstruct it on demand through the cache rather than holding it live.

```python
class Cache:
    """Async SQLite cache: get/set with TTL and compute-on-miss."""

    async def get(self, key: str, default: Any = None) -> Any:
        """Return the cached value, or default if missing or expired (deletes on expiry)."""
        ...

    async def set(self, key: str, value: Any, expire: float | None = None) -> None:
        """Store key -> value, expiring after `expire` seconds (None = no expiry)."""
        ...

    async def remember(
        self, key: str, ttl: float | None, callback: Callable[[], Awaitable[T]]
    ) -> T:
        """Return the cached value, or compute it via callback and store it under ttl."""
        cached = await self.get(key)
        if cached is not None:
            return cached
        value = await callback()
        await self.set(key, value, expire=ttl)
        return value
```

This is not a ban on an in-process collection that lives for a single operation and is guarded by a lock (§8) — a
request-scoped buffer or a bounded work queue is fine. The line is **accumulation across requests**: the moment a dict's
lifetime is "the process," it should have been a cache with a TTL.

### Dataclasses for internal data; BaseModel at boundaries

- Use `@dataclass` (frozen for anything passed between coroutines, §8) for internal domain types and data moved between
  functions. Build one straight from a database row with `Type(**dict(row))` when the selected columns match its fields,
  rather than a hand-written `from_row` constructor.
- Use a pydantic `BaseModel` at **boundaries** — API request/response shapes, settings and config, and anywhere input is
  untrusted or needs validation, coercion, or JSON (de)serialization. The validation is the reason to reach for it;
  don't use it for a plain internal record that a dataclass models more cheaply.

### Settings compose from the domains that own them

One `settings.py` defines the root `Settings(BaseSettings)` — built on `pydantic-settings`, loaded once at startup, held
on `Services` and reached as `services.settings`. Nothing else reads the environment; a setting that isn't on `Settings`
(or a domain settings class it composes) does not exist.

**Never read `os.environ` (or `os.getenv`) directly.** Every environment variable enters the program through a
`BaseSettings` field and nowhere else. A raw `os.environ["API_KEY"]` is an untyped, uncoerced, undocumented, unvalidated
read that fails at the moment of use rather than at startup, is invisible to anyone auditing what the program is
configured by, and can't be overridden in a test without mutating process state. A `BaseSettings` field gives you the
type, the default, the validation, and one greppable declaration of the whole configuration surface.

```python
# Avoid — untyped, unvalidated, undiscoverable, and blows up deep inside a request:
timeout = int(os.environ.get("HTTP_TIMEOUT", "30"))
api_key = os.environ["API_KEY"]  # KeyError at first use, not at startup


# Correct — the field is the declaration; pydantic coerces and validates at load.
class HTTPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HTTP_")
    timeout: int = 30
    api_key: SecretStr
```

**Load `.env` files with `python-dotenv`, before `Settings` is constructed.** Call `load_dotenv()` once at the
composition root (the CLI `main`, the `lifespan`) so the file's values are present in the environment by the time
pydantic reads them; keep `env_file` set on the root `model_config` as well, so settings still load correctly when a
process starts without the explicit call. `.env` is for local development only — it is gitignored, and deployed
environments supply real environment variables.

**Keep the variables in `.env`, and dev/test-specific overrides in `.env.dev`.** Both are gitignored. List them on the
root `model_config` in precedence order — `env_file=(".env", ".env.dev")` — where the later file wins, so `.env` holds
the shared baseline and `.env.dev` overrides only what a development or testing environment needs to differ. Don't fork
a whole second configuration file: if a value is the same everywhere, it belongs in `.env` alone.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", ".env.dev"), extra="ignore")
```

The narrow exemptions, and they are narrow: setting a variable for a **subprocess** you spawn (pass an `env=` dict, not
a mutation of `os.environ`), and a variable that must be set before an imported library reads it at import time. Both
happen at the composition root, with a comment saying why.

A domain module that has configuration of its own defines its own `BaseSettings` subclass next to the code that reads
it, scoped so its variables don't collide with another domain's — through an `env_prefix` for plain fields, or its own
collection logic when the keys are dynamic. The root `Settings` wires each one in as a nested field with
`Field(default_factory=...)`. Composition happens at the root, and the dependency points only downward — `settings.py`
imports the domain modules, never the reverse — the same direction as the route layer (§6). A domain with no
configuration provides no class; don't create empty settings shells.

```python
# cache.py — the domain owns its own settings class, scoped with an env_prefix
# so its variables don't collide with another domain's.
class CacheSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CACHE_")
    ttl_seconds: int = 60


# settings.py — the root composes each domain's settings; it is the only env reader.
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    cache: CacheSettings = Field(default_factory=CacheSettings)
```

Why this way: a domain's configuration lives beside the code that consumes it (the same ownership rule as types and
behavior), each domain namespaces its own variables through `env_prefix`, and the domain layer never depends back on the
settings root — so a new domain adds one field at the root and nothing above it has to change.

### Inject via a typed `Annotated` alias

FastAPI dependencies that inject a service or a resolved model are defined once as a `typing.Annotated` alias pairing
the type with its `Depends(...)`, then reused as the parameter annotation. Handlers then read as ordinary typed
parameters and the wiring lives in exactly one place.

```python
ServicesDep = Annotated[Services, Depends(get_services)]
ConnDep = Annotated[asyncpg.Connection, Depends(get_conn)]
CurrentUserDep = Annotated[AuthContext, Depends(require_user)]


async def me(services: ServicesDep, ctx: CurrentUserDep) -> MePayload:
    return await me_payload(services, ctx.user)
```

The conventions that keep this uniform:

- **Name every alias `SomethingDep`** and define it immediately beneath its resolver, in the module that owns the
  resolver (`ServicesDep` in `services.py`, `CurrentUserDep` in `authorization.py`). Cross-module handlers import the
  alias, never re-spell the `Depends(...)`.
- **Always the `Annotated` form.** Never the old default-value style (`param: T = Depends(fn)`), never a bare
  `Depends(...)` inline in a handler signature, and never a `dependencies=[...]` argument on the app or a router — those
  scatter the wiring the alias exists to centralize.
- **Shape the resolver to its job.** A resolver that only pulls an already-resolved object off the request
  (`Request -> request.app.state.services`, `request.scope["auth"]`) is a plain **sync** function taking `Request`. A
  resolver that does I/O to authenticate or resolve (an API-key hash lookup, token validation) is **async** and composes
  the aliases it needs (`async def authenticated_api_user(services: ServicesDep, request: Request)`).
- **No `yield` dependencies.** Per-request resource lifecycle lives on `Services` and the `lifespan` (§6), not in a
  yield-based dependency that opens and closes a resource per request.

### Parametrize a dependency with a factory

When a dependency needs arguments — gate on _these_ groups, require _this_ scope — write a factory that closes over them
and returns the dependency function, then wrap the result in an `Annotated` alias at each use. The arguments are fixed
at wiring time; the handler still reads as an ordinary typed parameter.

```python
def require_groups(*group_ids: int) -> Callable[..., Awaitable[AuthUser]]:
    """Build a dependency that admits only members of the given groups."""

    async def dependency(services: ServicesDep, user: CurrentUserDep) -> AuthUser:
        await forbid_unless_member(services, dsid=user.dsid, group_ids=list(group_ids))
        return user

    return dependency


AdminDep = Annotated[AuthUser, Depends(require_groups(GROUP_ADMIN))]
```

### A cross-cutting check is a function; the dependency is the thin wrapper

A check that must guard both route handlers and inner code paths — an authorization gate, a precondition — lives as a
plain function taking `services` first (the §6 rule), so any code path can call it directly. The dependency factory
above is then only a thin adapter: it resolves the caller and delegates to that function. The rule is defined once and
reachable two ways — as a handler dependency (`AdminDep`), and as a direct call deep in a request where no dependency
injection reaches (`await forbid_unless_member(services, dsid=..., group_ids=[...])`). Don't implement the gate _inside_
the dependency, or the inner code paths can't reuse it.

### Register routes explicitly, not with decorators

Define each route handler as a plain function and register it with `app.add_api_route(path, handler, methods=[...])`. Do
not use decorator routing (`@app.get`, `@router.post`, and the like). A decorator has to reference a module-level `app`
or `router` object — that is exactly the global state §4 bans. Explicit registration takes the `app` as a parameter
where routes are wired (in `create_app`), so handler modules stay free of any global, and handlers remain ordinary,
directly callable and testable functions.

```python
async def me(services: ServicesDep, ctx: CurrentUserDep) -> MePayload:
    return await me_payload(services, ctx.user)


app.add_api_route("/users/me", me, methods=["GET"], name="me", tags=["Users"])
```

### Route handlers live in a per-domain route layer, not in domain modules

A route handler routinely composes several domains — `GET /users/me` returns the user _and_ their API keys. If the
handler lives inside a domain module (`users.py`), that module must import every other domain it touches
(`api_keys.py`), and the moment two domains each need a handler that references the other you have an import cycle.
Co-locating handlers with domain types pulls cross-domain composition _down_ into the domain layer, which is exactly
where it causes cycles.

Put handlers in a dedicated route layer instead: one module per domain, named `domain_routes.py` (`user_routes.py`,
`api_key_routes.py`). Each module holds **bare handler functions and nothing else** — no `app`, no router, no per-module
registration hook. The composition root (`create_app`) imports every route module and is the single place that
enumerates the routes with `add_api_route` (see "Register routes explicitly"). This is a strict layering with one
invariant:

Route modules import domain modules. Domain modules never import route modules. Route modules never import each other.
Only `create_app` imports the route modules.

```python
# api_key_routes.py — bare handlers. The module knows nothing about `app` or routing.
from __future__ import annotations

from .api_keys import ApiKeyInfo, list_api_keys
from .services import ServicesDep
from .users import CurrentUserDep


async def list_keys(services: ServicesDep, ctx: CurrentUserDep) -> list[ApiKeyInfo]:
    return await list_api_keys(services, dsid=ctx.user.dsid)
```

```python
# asgi.py — create_app is the ONE place that enumerates every route, across all domains.
from . import api_key_routes, user_routes

def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan, ...)
    ...
    app.add_api_route("/users/me", user_routes.me, methods=["GET"], tags=["Users"])
    app.add_api_route("/api/keys", api_key_routes.list_keys, methods=["GET"], tags=["API Keys"])
    ...
    return app
```

Prefer this central enumeration over a per-module `register(app)` hook: one file lists the entire URL surface, so a
route's path, method, tags, and OpenAPI metadata are read and reviewed in one place, and no route module ever has to
touch `app`. Group the calls by domain with comments and shared response dicts; that grouping, not a function boundary,
is the only structure the list needs.

**Why this keeps the layer acyclic:** nothing depends back on the route layer except `create_app` (the composition root,
which is meant to know everything), so a handler can import as many domains as it needs — always downward. The "routes
use many domains" pressure never reaches the domain layer, because composition happens above it.

**What moves and what stays:** only the thin handler moves to the route module. Boundary models (`MePayload`,
`ApiKeyInfo`) and behavior functions (`me_payload`, `list_api_keys`) stay in their domain module — they are domain-owned
and the route module imports them. This is the deliberate trade: you give up handler-next-to-type co-location to keep
the domain layer acyclic. Co-location wins for types and the behavior that owns them; the route layer wins for
composition across domains.

`domain_routes.py` is not the catch-all §4 bans. A single `routes.py` holding every handler is the magnet for unowned
code; a route module scoped to one domain and named after it is the opposite. A handler spanning several domains lives
in the route module of its primary resource (the response type's owner), or its own `feature_routes.py` when it has no
natural primary.

### The composition root wires structure in one factory; the lifespan owns resources

`create_app() -> FastAPI` is the composition root: a zero-argument factory that builds a fully wired app and returns it.
It is the one place that knows the whole system — it enumerates every route, mounts every sub-app, and adds every
middleware — so nothing else has to. Because it takes no arguments and holds no module-level singleton, each call yields
an independent app, which is exactly what a test wants: call `create_app()`, drive it with a test client, and override
`app.state.services` (or the `get_services` dependency) to inject fakes. Production invokes it once; a reload server is
handed the `"package.asgi:create_app"` factory string so its workers re-invoke it.

The factory wires **structure**; it does not build **resources**. A module-level `lifespan` async context manager
(passed as `FastAPI(lifespan=...)`) owns the resource lifecycle: it constructs `Services`, awaits `setup()`, publishes
it on `app.state.services`, enters any mounted sub-app's own lifespan, `yield`s to serve, and awaits `shutdown()` in a
`finally`. Keep `lifespan` module-level rather than nested in `create_app` (the nested-closure rule above), so it is the
single, importable driver of the startup/teardown ordering §6 describes.

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    setup_logging()
    services = Services()
    await services.setup()              # the async half of the two-phase lifecycle (§6)
    app.state.services = services
    try:
        yield
    finally:
        await services.shutdown()       # mirrors setup in reverse, each resource None-guarded


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan, ...)
    app.add_middleware(InnermostMiddleware)    # added first → wraps innermost
    app.add_middleware(OutermostMiddleware)    # added last  → wraps outermost
    # ... add_api_route for every route, grouped by domain ...
    app.mount("/", static_fallback)            # catch-all mounts go LAST, after every explicit route
    return app
```

Two ordering rules the factory encodes, both easy to get subtly wrong:

- **Middleware is added in reverse of execution order** — the last `add_middleware` wraps outermost. Add the innermost
  layer first and say so in a comment; a reviewer cannot infer the intended nesting from source order alone.
- **Catch-all and static mounts (`/`, `/static`) go last,** after every explicit `add_api_route`, so the specific routes
  match before the fallback.

### Error rendering is chosen by the surface, not the domain

Domain functions raise presentation-neutral `AppError`s (`NotFound`, `Forbidden`); they never decide how the error
looks. The default rendering is the JSON envelope, produced by the outer `ErrorMiddleware` for any `AppError` — every
API route gets it for free.

A surface that needs a different representation translates at its own boundary: the route layer catches the domain
`AppError` and re-raises a surface-specific exception that is deliberately not an `AppError`, with a registered
exception handler that renders it. Because it is not an `AppError`, the middleware ignores it and the handler wins. The
HTML page routes do this — a `NotFound` from `get_project` becomes `PageNotFound`, rendered as an HTML 404; the same
`NotFound` on an API route stays JSON.

```python
# pages_routes.py — translate the domain error into an HTML-rendered one.
class PageNotFound(Exception):
    """Raised when the requested project or page does not exist.

    Deliberately not an AppError: that is what routes it to the HTML handler
    instead of the JSON envelope ErrorMiddleware produces for an AppError.
    """


async def authorize_page(services: ServicesDep, *, slug: str, name: str) -> AuthorizedPage:
    try:
        project = await get_project(services, slug=slug)
        page = await get_page(services, project_id=project.id, name=name)
    except NotFound as e:
        raise PageNotFound() from e
    ...
```

Two rules. The surface exception must not subclass `AppError` — that is what routes it to the HTML handler, so say so in
its docstring; otherwise someone "tidying up" by making it an `AppError` silently turns the page back into JSON. And the
translating `try/except` wraps only the lookups that produce the condition, never the whole handler, so an unrelated
error from deeper code isn't mislabeled.

---

## 7. Documentation

- Use `"""docstrings"""` on every public class, method, and function. Non-trivial module-level helpers that another
  contributor would have to read the implementation to understand also get docstrings.
- **Document the contract, not the implementation.** State invariants, preconditions, what exceptions can be raised,
  ownership, performance constraints — the things the name doesn't already say.
- **Do not write docstrings that restate the code.** `Returns the item count.` above `def count(self) -> int` is noise
  that will drift. The name carries the "what"; comments are for the non-obvious "why" (a workaround, a subtle
  invariant, a performance constraint).
- **Don't reference tickets or PRs** in code (`# Added for JIRA-123`). Those rot. Put context in commit messages and PR
  descriptions; if a workaround needs explaining, write the _why_ directly.
- Keep docstrings present-tense and declarative: "Returns the …" not "Will return the …". Document each protocol method
  individually.

```python
class BridgeContext:
    """Live context that hosts agent-exposed tools.

    Hold one BridgeContext per logical session. Inject tools with
    inject() before evaluating any script that references them.
    """

    async def evaluate(self, script: str) -> Value:
        """Evaluate script in the underlying context.

        Raises:
            BridgeError: if the script raises or the context is invalid.
        """
        ...
```

---

## 8. Concurrency

Under `asyncio`, this is a **correctness** domain. The model in one paragraph: use **async classes with explicit locks**
to encapsulate mutable shared state, **immutable dataclasses** to move data between coroutines, and **structured
concurrency** (`TaskGroup`) for async work.

### Async-safe classes

Use an async class with an `asyncio.Lock` when you have **mutable state** that must be safe across concurrent callers.

- Keep the class surface small — every `async def` is a potential contention point, and chatty classes degrade
  throughput.
- Prefer returning immutable dataclasses or copies from methods rather than references to internal state.
- Document the concurrency contract in the class docstring: what state is guarded, what operations are atomic.

```python
import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class BlobHandle:
    blob_id: str


class BlobStore:
    """Thread-safe in-memory blob store.

    All methods are safe to call concurrently. Mutations are serialized
    via an internal asyncio.Lock.
    """

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.blobs: dict[str, bytes] = {}

    async def store(self, data: bytes) -> BlobHandle:
        handle = BlobHandle(blob_id=str(id(data)))
        async with self.lock:
            self.blobs[handle.blob_id] = data
        return handle

    async def resolve(self, handle: BlobHandle) -> bytes:
        async with self.lock:
            return self.blobs[handle.blob_id]
```

### Immutability

Mark data transfer objects with `@dataclass(frozen=True)`. A frozen dataclass is safe to pass between coroutines without
copying. Mutable dataclasses and plain dicts are not safe to share without synchronization.

### Structured concurrency

- **Prefer `asyncio.TaskGroup`** over unstructured tasks when the work has a clear parent. You get cancellation, error
  propagation, and scope containment for free.
- **Use `asyncio.gather`** for a fixed set of independent awaitables that must all complete. Prefer
  `return_exceptions=False` (the default) — let errors propagate instead of collecting them silently.
- Reach for `asyncio.create_task` (unstructured) only when the lifetime truly outlives the calling scope. Document the
  reason inline and store the task in an instance attribute so it can be cancelled explicitly.
- `asyncio.ensure_future` should never appear in new code — use `create_task`.

```python
async def fetch_all(urls: list[str]) -> list[Response]:
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(fetch(url)) for url in urls]
    return [task.result() for task in tasks]
```

### `asyncio.Queue` over polling

For producer/consumer coordination, use `asyncio.Queue`. Never busy-loop or `await asyncio.sleep(0)` in a spin-wait — it
burns CPU and starves the event loop.

### Blocking I/O

Blocking calls inside a coroutine stall the entire event loop. When you must call a blocking library:

```python
result = await asyncio.to_thread(blocking_library_call, arg)
```

Never call `time.sleep` in a coroutine — use `await asyncio.sleep(seconds)`.

### Cancellation

- Honor cancellation: check `asyncio.current_task().cancelled()` or let `asyncio.CancelledError` propagate at natural
  suspension points.
- Never `except asyncio.CancelledError: pass` — swallowing it breaks structured cancellation.
- When a class owns a long-running task, give it an explicit `cancel()` method rather than relying on garbage collection
  timing.

```python
class Worker:
    def __init__(self) -> None:
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.task = asyncio.create_task(self.run())  # unstructured: outlives caller

    def cancel(self) -> None:
        if self.task is not None:
            self.task.cancel()

    async def run(self) -> None:
        while True:
            await asyncio.sleep(1)
            await self.do_work()
```

---

## 9. Error handling

Errors are **first-class API surface**, not afterthoughts. Each area defines its own exception hierarchy and documents
what a function raises.

### The default shape: a typed exception hierarchy

For most code, a small exception class per area is all you need:

```python
from dataclasses import dataclass


class RAGClientError(Exception):
    """Base class for all RAG client errors."""


@dataclass
class TransportFailure(RAGClientError):
    underlying: Exception


@dataclass
class DecodingFailure(RAGClientError):
    reason: str


class Unauthorized(RAGClientError):
    pass


@dataclass
class RateLimited(RAGClientError):
    retry_after: float | None
```

- **Subclasses describe failure modes**, not error sites. A class maps to a thing that can go wrong, not a line of code.
- **Dataclass fields carry context** — use them; don't shove everything into `str(e)`.
- **Preserve the cause.** Use `raise MyError(...) from original` to chain exceptions so the traceback shows both.

### Annotate raises in docstrings

Python has no typed throws, so document exceptions in docstrings:

```python
async def load_note(self, note_id: str) -> Note:
    """Load note by ID.

    Raises:
        NoteNotFound: if no note exists with the given ID.
        StorageError: if the underlying store is unavailable.
    """
```

### Adapt foreign exceptions at the boundary

Never let a third-party exception type escape your area's surface. Catch it at the boundary and wrap it:

```python
try:
    response = await http_client.get(url)
except httpx2.HTTPError as exc:
    raise TransportFailure(underlying=exc) from exc
```

### Map the area's exception hierarchy to the surface in one function

Domain code raises its typed exceptions and stays presentation-neutral (§6: error rendering is chosen by the surface).
The surface translates them in a single pure function — `collection_http_error(e) -> HTTPException`,
`floodgate_http_status(e) -> int` — that maps each failure mode to its status, called at the route boundary. One
function per area _is_ the whole mapping: greppable, testable without a server, and the one place to look when a status
is wrong.

```python
def collection_http_error(e: CollectionError) -> HTTPException:
    if isinstance(e, ObjectNotFound):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, InvalidObjectData):
        return HTTPException(status_code=400, detail=e.reason)
    return HTTPException(status_code=400, detail=str(e))
```

### Keep messages caller-safe, and put the blame in the status code

What you return to a caller is API surface, not a debugging aid.

- **Only the caller's own fault is a 4xx.** A bad request or an exceeded rate limit is the caller's concern (400/429)
  and passes through. A failure that is really your side — a missing credential, an unreachable backend, a
  misconfiguration — is a 5xx (502/503) even when the upstream library reported it as 401/403, because nothing the
  caller sent was wrong.
- **Never leak internal detail.** Extract a bounded, caller-safe message (a known field, a truncated body) instead of
  forwarding a raw upstream error or an internal value. Log the full detail at the catch site; return only what a caller
  can act on.

```python
def floodgate_http_status(error: FloodgateError) -> int:
    # Bad request (400) and rate/budget (429) are the caller's concern and pass
    # through; auth/cert failures are server-side misconfiguration, so 502.
    if error.status in (400, 429):
        return error.status
    return 502
```

### When errors cross a foreign boundary

If errors must cross into a non-Python consumer (a wire protocol, a remote API), define an error protocol that adds the
wire shape:

```python
from typing import Protocol


class WireError(Protocol):
    @property
    def code(self) -> str: ...  # stable, dotted, lowercase: "note.not_found"
    @property
    def message(self) -> str: ...  # human-readable, may change
    @property
    def context(self) -> dict[str, object]: ...  # snake_case keys, JSON-safe values
```

`code` is what consumers match on — keep it stable and scoped. `message` is for humans and can change. **Default to the
simple exception hierarchy** — only reach for the wire protocol when you actually have a foreign boundary.

### Assertions vs. exceptions

Use assertions for things that **should never happen** in correct code:

- `assert condition, "message"` for debug-only invariant checks (stripped with `-O`). Never use `assert` for input
  validation.
- Raise `ValueError` for precondition violations on public API inputs.
- Use `raise RuntimeError("unreachable")` for truly unreachable branches — but prefer restructuring so the impossible
  state is unrepresentable.

If a condition can be triggered by user input or external state, it is **not** an assertion — raise a typed exception.

### Don't

- **Don't use bare `except Exception:`** in new code — name what you catch.
- **Don't swallow exceptions** (`except SomeError: pass`). The caller can't tell something failed. Let it propagate, or
  transform into a meaningful return shape (`None`) when "missing" is genuinely not exceptional.
- **Don't put logging inside an exception class.** Exceptions describe failure; logging belongs at the catch site.
- **Don't use `sys.exit()` inside library code.** Raise an exception; let the CLI boundary decide what to do.

---

## 10. Trust boundaries & untrusted input

When code accepts input from outside its trust boundary — a query a caller writes, a path a caller names, anything that
crosses from a user to an engine — treat **safety as a correctness domain** and read these as prescriptive.

### Validate by parsing, not by string-matching

To decide whether untrusted input is allowed, parse it into the same structure the engine will act on and inspect that —
never pattern-match the raw text. A denylist of forbidden substrings is bypassable (comments, casing, encoding,
whitespace) and an allowlist regex rejects valid input; both drift from what the engine actually does. Validate with the
engine's _own_ parser where you can, so there is no second grammar to diverge from and slip something past.

```python
def assert_read_only(self, sql: str) -> None:
    """Reject anything but a single read-only SELECT, using the engine's own parser.

    Validates with the engine's serializer so the parse matches exactly what it
    would execute — no second parser to diverge from and slip a write past.
    """
    parsed = self.serialize(sql)  # the engine's own parse, not a regex
    statements = parsed.get("statements", [])
    if len(statements) != 1:
        raise QueryRejected("exactly one statement is allowed")
    if statements[0]["node"]["type"] not in READ_ONLY_NODE_TYPES:
        raise QueryRejected("only read-only SELECT queries are allowed")
```

### Read structured formats with a parser, not with string operations

The same instinct applies outside the trust boundary, and it is not a rule about Python source: **whenever a format has
a grammar, use a parser for it — and where you must produce that format, use a serializer or a template engine.** This
covers everything a program routinely reads and writes: Python, JSON, YAML, TOML, SQL, reStructuredText, Markdown,
HTML/XML, CSV, URLs, dates, email messages, semantic versions, `.ini`/config files, log formats with a defined shape,
and any DSL you have invented yourself. Each of those has a specific library named below — pick from that list rather
than deciding per call site.

Reaching for `str.split`, `str.startswith`, `str.replace`, or a regex to pull a field out of one of these is
re-implementing a grammar you don't own. It fails on exactly the cases the real parser handles: nested quoting, escapes,
comments, line continuations, multi-line and folded values, significant indentation, delimiters appearing inside quoted
fields, anchors and references, encodings, BOMs, and every construct the format gained after you wrote the regex. The
failure is usually silent — the traversal returns a plausible-looking wrong answer rather than raising.

Reach for the grammar in this order: the format's **own parser** (best — no second grammar to diverge from), then the
**stdlib parser** where one exists, then the **established third-party parser** named below, then a **grammar you define
explicitly** for a format that has none off the shelf. Hand-rolled string traversal is not on the list.

Several of the libraries named below are third-party, which §12 would otherwise put a burden of proof on. Consider that
burden discharged: a format's parser is precisely the "concrete justification, no reasonable stdlib path, bounded scope"
case §12 describes — the alternative is maintaining a grammar yourself, which is the thing this section exists to
forbid. Still scope each one to the area that uses it and record it in the dependency inventory.

### The parser for each format

**Python** — `ast.parse`, then walk the tree with `ast.NodeVisitor`, `ast.walk`, or `ast.get_docstring` to find imports,
definitions, decorators, or call sites. A regex over source text cannot tell a name in a string literal from a name in
code, misses a call split across lines, and silently reports nothing when it drifts. Write source back with
`ast.unparse`, or edit the original text at the node's `lineno`/`col_offset` when formatting must be preserved.

**JSON** — `json.loads`/`json.dumps`. Never assemble JSON by concatenating or f-string-interpolating values into a
literal, and never pluck a field with a regex; one embedded quote or newline in a value produces text that is either
invalid or silently wrong. Serialize the object.

**YAML** — `yaml.safe_load` (never `yaml.load` with the default loader, which constructs arbitrary Python objects) and
`yaml.safe_dump` to write. YAML's indentation, anchors, aliases, block scalars, and implicit typing (`no` is a boolean,
`1.0` is a float, an unquoted version string is not what you meant) defeat line-oriented editing in particular.

**TOML** — `tomllib.load` (stdlib) to read. `tomllib` is read-only: to write, use `tomli-w`; to edit an existing file in
place while preserving comments and formatting, use `tomlkit`, whose round-tripping is the reason to prefer it over
load-then-dump. Don't regex `pyproject.toml`.

**SQL** — the strongest form of this rule, because it is also §10's trust boundary. Bind parameters rather than
interpolating values. Where you must _inspect_ or _rewrite_ a statement, use **`sqlglot`** — parse to an expression tree
with `sqlglot.parse_one(sql, dialect=...)`, walk or transform it with `find_all`/`transform`, and render it back with
`.sql(dialect=...)`. It is the default choice for SQL in this guide: it parses and transpiles across dialects, it gives
you a typed node tree rather than tokens, and it is pure Python with no engine to stand up. A regex cannot tell a
keyword from the same word inside a string literal or a comment, so "does this statement write?" answered by substring
match is answered wrong.

```python
# Avoid — substring matching over SQL; "delete" may be a column name, a string
# literal, or inside a comment, and a CTE hides the real statement type:
if "delete" in sql.lower() or "update" in sql.lower():
    raise QueryRejected("writes are not allowed")


# Correct — parse to an expression tree and ask what the statement IS:
def assert_read_only(sql: str, *, dialect: str) -> None:
    """Reject anything but a single read-only SELECT.

    Raises:
        QueryRejected: if sql is not exactly one read-only SELECT.
        sqlglot.ParseError: if sql does not parse in the given dialect.
    """
    statements = sqlglot.parse(sql, dialect=dialect)
    if len(statements) != 1:
        raise QueryRejected("exactly one statement is allowed")
    if not isinstance(statements[0], sqlglot.exp.Select):
        raise QueryRejected("only read-only SELECT queries are allowed")
```

Where the engine exposes its **own** parser, prefer that for a gate you are relying on for safety (as `assert_read_only`
in "Validate by parsing" does) — there is then no second grammar to diverge from what actually executes. Use `sqlglot`
when there is no such parser to reach, when you need to work across dialects, or when you are transforming rather than
merely admitting a statement. Building SQL still means composing an expression tree or binding parameters, never
interpolating caller values into text (see "Compose, don't interpolate").

**reStructuredText** — `docutils`: `docutils.core.publish_doctree` gives a document tree you walk with a
`docutils.nodes.NodeVisitor` for directives, roles, sections, and links, and `publish_string` renders it back out. RST's
indentation-sensitive directive bodies and inline markup rules are not something a regex reproduces. Sphinx-flavored RST
needs Sphinx itself to resolve its extra directives and roles.

**Markdown** — `markdown-it-py`, which parses to a token stream you walk (and, with `mdformat`, re-serializes). Match
neither `^#` for headings nor `\[.*\]\(.*\)` for links: fenced and indented code blocks contain text that looks exactly
like markup and must not be treated as such, which is the single most common bug in regex-based Markdown handling. When
you emit Markdown, escape through the library rather than hoping the interpolated text contains no `*`, `_`, `[`, or
backtick.

**HTML** — `lxml.html` (fast, XPath) or `BeautifulSoup` (lenient, forgiving of real-world markup) to parse;
`html.parser` in the stdlib only for something trivial. Never a regex — HTML is not a regular language, and the classic
`<([a-z]+)[^>]*>` breaks on attributes containing `>`, unclosed tags, and comments. Use `lxml.cssselect` or XPath to
select nodes rather than walking text.

**XML** — `lxml.etree` or the stdlib `xml.etree.ElementTree` for trusted input; for **untrusted** XML use `defusedxml`,
because the stdlib parsers are vulnerable to entity-expansion and external-entity attacks (§10's trust boundary applies
directly here).

**CSV** — `csv` in the stdlib, which handles the embedded delimiters, quotes, and newlines that `str.split(",")`
corrupts. Reach for `pandas.read_csv` only when you are already doing dataframe work, not as a parser of first resort.

**URLs** — `urllib.parse` (`urlparse`, `parse_qs`, `urlencode`, `urljoin`) for parsing and for building query strings.
Never concatenate query parameters by hand; `urlencode` does the percent-encoding you will otherwise get wrong.

**Dates** — `datetime.fromisoformat` for ISO-8601 (Python 3.11+ handles offsets and `Z`),
`email.utils.parsedate_to_datetime` for HTTP/email dates, and `dateutil.parser` only for genuinely unknown-shape input
from humans. Never `strptime` against a format you guessed, and never slice a timestamp string by index.

### Produce markup with a template engine, not with string formatting

The mirror of the parsing rule: **when you generate a structured format, use its templating or serialization library —
never f-strings, `str.format`, `%`, or concatenation.** A hand-built string has no idea what context it is interpolating
into, so it cannot escape correctly, and the failure mode is not a cosmetic glitch — it is XSS in HTML, injection in
SQL, a corrupt document everywhere else.

- **HTML** — `jinja2` with `autoescape=True` (always; it is off by default in a bare `Environment`, so set it
  explicitly). Autoescaping is the whole reason to use the engine: it escapes `<`, `>`, `&`, and quotes per
  interpolation site. Mark a value safe with `markupsafe.Markup` only when you have escaped or sanitized it yourself,
  and treat every such call as a thing a reviewer must look at. In a FastAPI app this is `Jinja2Templates`; for
  standalone fragments, `markupsafe.escape` directly.
- **XML** — build a tree with `lxml.etree` / `ElementTree` and serialize it, rather than templating tags as text; the
  serializer escapes attribute and text content for you.
- **Email** — `email.message.EmailMessage` and the `email` package, which handle MIME structure, headers, and encoding.
  Never assemble headers by concatenation: a newline in an interpolated value is header injection.
- **Shell commands** — no template at all. Pass an argument list to `subprocess` with `shell=False` (the default), so
  there is no shell grammar to escape into. `shlex.quote` is for the case where a shell is genuinely unavoidable.
- **Everything else** — the format's serializer, per the list above: `json.dumps`, `yaml.safe_dump`, `csv.writer`,
  `urlencode`, `sqlglot` / bound parameters.

Jinja2 templates live in their own files loaded through a `FileSystemLoader`, not in Python string literals — they get
syntax highlighting, they are diffable, and the separation keeps markup out of logic. Reserve inline `Template(...)` for
a short fragment with no reuse.

```python
# Avoid — no escaping; a display name containing "<script>" is now executable,
# and one containing a quote breaks out of the attribute:
html = f'<a href="/users/{user.id}" title="{user.name}">{user.name}</a>'


# Correct — the engine escapes each interpolation for its context:
environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader("templates"),
    autoescape=True,  # off by default; the reason we are using jinja2 at all
)
html = environment.get_template("user_link.html").render(user=user)
```

```python
# Avoid — a regex guessing at Python's grammar; misses aliases, parenthesized
# and multi-line imports, and matches the word inside a comment or docstring:
imports = re.findall(r"^import (\w+)", source, re.M)


# Correct — the language's own parser answers the question:
def imported_modules(source: str) -> set[str]:
    """Returns every top-level module name imported by source.

    Raises:
        SyntaxError: if source is not valid Python.
    """
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names
```

The same shape holds for a data format — parse, then query the structure:

```python
# Avoid — line-oriented traversal of a format with significant indentation,
# block scalars, and implicit typing. Matches the key at any nesting depth,
# inside a comment, or inside a multi-line string value:
for line in config_text.splitlines():
    if line.strip().startswith("image:"):
        image = line.split(":", 1)[1].strip()


# Correct — parse once, then ask the structure:
def container_images(config_text: str) -> list[str]:
    """Returns the image of every container in a deployment manifest.

    Raises:
        yaml.YAMLError: if config_text is not valid YAML.
    """
    document = yaml.safe_load(config_text)
    containers = document["spec"]["template"]["spec"]["containers"]
    return [container["image"] for container in containers]
```

### Define a grammar when there isn't one to reuse

When you invent a format — a query mini-language, a rule expression, a structured log line, an ID with internal
structure — write down its grammar and drive a parser from it rather than growing a chain of `split` calls. A grammar is
a single reviewable statement of what is legal, it gives you a real error with a position when input doesn't match, and
it forces the ambiguous cases (escaping, precedence, empty fields) to be decided once instead of discovered later.
Prefer not inventing a format at all — an existing one with an existing parser is almost always cheaper.

### Let the parser's error be the failure signal

A `SyntaxError`, `JSONDecodeError`, or `yaml.YAMLError` reports the line and column and names the problem; a regex just
returns nothing and looks like a legitimate empty result. Wrap the parser's exception at your area's boundary (§9) so it
doesn't leak, but keep it as the thing that fires — don't pre-validate with a regex and then parse.

String operations remain appropriate for genuinely unstructured text (a free-form message, a log line you wrote
yourself), for cheap pre-filters before a real parse, and for building a string that is only ever read by a human. They
are never the parse itself, and never the serialization of a format someone else will parse.

### Compose, don't interpolate

Build the structured input you hand to the engine — SQL, a command — by composing an AST or binding parameters, not by
interpolating caller values into a string. A value the caller controls is a **parameter** (a numbered placeholder bound
out-of-band), never a fragment of the statement text. String interpolation is how injection happens; the boundary should
make it structurally impossible, not catch it after the fact. Reach for explicit quoting/escaping only where binding is
genuinely unavailable — and then through one audited helper, never ad hoc.

### Layer independent controls; apply irreversible locks last

Defense in depth: put more than one independent control between untrusted input and harm, so bypassing one does not open
the door. A statement-shape gate (the AST check above) proves what the query _is_; a separate engine sandbox — disabled
filesystems, frozen configuration — holds even if that gate is ever bypassed, and neither relies on the other. Apply
one-way lockdowns **last**, after everything else is in place, and document the ordering, because they cannot be undone
for the life of the resource.

```python
def lock_down(con: Connection) -> None:
    """Sandbox the connection. Applied once, last — these locks are one-way."""
    con.execute("SET disabled_filesystems = 'LocalFileSystem,HTTPFileSystem'")
    con.execute("SET autoload_known_extensions = false")
    con.execute("SET lock_configuration = true")  # freezes all of the above
```

---

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

## 12. Dependencies

The default stance is **standard library only.** Every dependency you add becomes a dependency for everyone who adopts
your code: it enters their environment, adds install time and disk size, and ties them to a maintainer and a license.

A new dependency earns its way in by clearing all of:

- **Concrete justification** — name the capability you'd otherwise build and maintain. "It's convenient" doesn't count.
- **No reasonable stdlib path** — prefer `asyncio`, `dataclasses`, `typing`, `json`, `pathlib`, `logging`, `re` over
  third-party alternatives.
- **Stable provenance** — actively maintained, clear release discipline. Avoid one-person and abandoned projects.
- **Bounded scope** — a library that does exactly the one thing you need beats one that brings ten you don't.

Scope each dependency to the area that uses it with optional extras or a separate package, not a codebase-wide install.
Test-only dependencies face the same questions at a slightly lower bar. Keep an inventory (`AUDIT.md` or similar) and
update it in the same change that adds or removes a dependency.

---

## 13. Imports

- Group imports in this order, with one blank line between groups:
  1. Standard library (`import asyncio`, `from typing import Protocol`)
  2. Third-party (`import httpx2`)
  3. Your own modules (`from .note_store import NoteStore`)
- **`from __future__ import annotations`** at the top of every file — it enables forward references and defers
  annotation evaluation cheaply.
- Don't import what you don't use — `ruff` and `mypy` will flag it.
- Never use wildcard imports (`from module import *`) in non-`__init__.py` files. In `__init__.py`, wildcards are
  acceptable only when the module explicitly defines `__all__`.
- Avoid import-time side effects. A module that runs code on import (opens sockets, writes files, mutates global state)
  is nearly impossible to test and fragile to import order.

---

## 14. Multi-line strings

- **Use a triple-quoted string for any string that spans more than one line** — SQL queries, multi-line messages,
  embedded templates. Write the content as it reads, on its own lines.
- **Never build a multi-line string by adjacent string-literal concatenation** (one quoted fragment per line with no
  operator between them). It is a correctness hazard: a single missing trailing space silently joins two tokens
  (`"...SET "` + `"username..."` is fine, but drop the space and you get `SETusername`), and the bug is invisible in
  review. It also makes the text hard to read and re-indent.

```python
# Correct — reads as the query it is, no hidden whitespace seams:
row = await conn.fetchrow(
    f"""
    INSERT INTO users (dsid, email)
    VALUES ($1, $2)
    ON CONFLICT (dsid) DO UPDATE SET email = EXCLUDED.email
    RETURNING {USER_COLUMNS}
    """,
    dsid,
    email,
)

# Avoid — implicit concatenation; one missing trailing space corrupts the SQL:
row = await conn.fetchrow(
    "INSERT INTO users (dsid, email) "
    "VALUES ($1, $2) "
    "ON CONFLICT (dsid) DO UPDATE SET email = EXCLUDED.email "
    f"RETURNING {USER_COLUMNS}",
    dsid,
    email,
)
```

A single-line string that happens to be long is fine as one quoted literal — this rule is about text that wraps across
source lines, not about line length.

---

## 15. Reports & diagrams

Any Markdown a program produces — an analysis writeup, a run summary, a generated doc page — is built with
[`mdreport`](https://mdreport.tycho.engineering/llms-full.txt), not f-strings or hand-assembled `"\n".join(...)`. Any
diagram that accompanies it is an `mdreport` `Diagram`, not Mermaid, Graphviz, or hand-written SVG. One library covers
both, the output is deterministic, and the escaping is handled for you — which is the §10 argument applied to Markdown:
compose through the emitter, don't interpolate into it.

### Reports

`MarkdownReport` is a chainable builder. Each method appends content and returns the report.

```python
from mdreport import CalloutKind, MarkdownReport

report = (
    MarkdownReport()
    .frontmatter(title="Nightly ingest", author="pipeline")
    .title("Nightly ingest")
    .table_of_contents()
    .heading("Summary")
    .text("Processed {{count}} records.", params={"count": record_count})
    .bullet_list(["12 jobs passed", "0 jobs failed"])
    .callout("Counts are provisional.", kind=CalloutKind.WARNING)
    .table(metrics, title="Revenue by region", decimal_places=1)
)
report.save(output_path)
```

What to reach for:

- `title`, `heading`, `text`, `bullet_list`, `numbered_list`, `code_block`, `markdown` for ordinary content. Both list
  methods nest — a list immediately after an item hangs beneath it.
- `callout(..., kind=CalloutKind.NOTE | TIP | IMPORTANT | WARNING | CAUTION)` for an admonition.
- `table(dataframe, ...)` and `csv(dataframe, ...)` for Polars DataFrames. Both emit every row; slice first.
- `figure(path, alt_text=..., caption=...)` for images. Captions are numbered `Figure 1`, `Figure 2` at render time, so
  never number them yourself. `is_embedded=True` inlines a local image (base64 for raster, inline markup for SVG).
- `frontmatter(...)` for YAML metadata, `table_of_contents(start_level=..., depth=...)` for the heading list.
- `render()` returns the string; `save(path)` writes UTF-8.

Templating is Jinja and runs **only** when you pass `params` — that is the seam for interpolated values, so pass data
through `params` rather than building the string yourself. Content with literal braces goes in without `params`.

Alt text is not optional. Every `figure` gets `alt_text` that describes what the reader would otherwise miss.

### Diagrams

A `Diagram` is a canvas with components at explicit coordinates. The library does not measure text, lay out graphs, or
stop nodes overlapping — you place things, and the same code always emits the same bytes.

```python
from pathlib import Path

from mdreport import (
    CENTERED_NODE_HEIGHT,
    TITLE_NODE_HEIGHT,
    Diagram,
    DiagramTheme,
    NodeRole,
    PortSide,
    centered_node,
    node_port,
    title_node,
)

diagram = Diagram(
    "Ingest",
    width=987,
    height=144,
    theme=DiagramTheme.LIGHT,
    palette={"background": "#ffffff"},
    background="background",
)
title_node(diagram, 34, 44.5, 288, "Source", role=NodeRole.ROOT)
centered_node(diagram, 466, 27.5, 288, "Transform", "Normalize the input", role=NodeRole.PARENT)
diagram.line(
    *node_port(34, 44.5, 288, TITLE_NODE_HEIGHT, PortSide.RIGHT),
    *node_port(466, 27.5, 288, CENTERED_NODE_HEIGHT, PortSide.LEFT),
    arrow=True,
)
diagram.save(Path("docs/ingest.svg"))
```

Rules that keep diagrams consistent across a codebase:

- **Role, not color.** `NodeRole.ROOT` for input, `PARENT` for processing, `LEAF` for output. Let the role pick the
  stroke and fill. Pass explicit `fill`/`stroke` only for a deliberate accent, and never to imply a role the node
  doesn't have.
- **Palette keys, not hex.** Paint arguments take keys — `"ink"`, `"muted"`, `"line"`, `"soft_line"`, `"panel"`,
  `"neutral_fill"`, `"root_fill"`, and so on — resolved against the active theme. In custom elements use
  `diagram.color("parent_fill")`. A literal hex value is a theme bug waiting to happen; the exceptions are Lucide icon
  colors, which must be hex. To brand a diagram, pass only the changed keys to `palette`, with separate overrides per
  theme.
- **Stay on the scale.** Sizes and offsets come from the golden-ratio scale the library ships: `FIBONACCI_SPACE` for
  spacing and widths, `TYPE_SCALE` for text sizes, and the named heights (`TITLE_NODE_HEIGHT` 55, `CENTERED_NODE_HEIGHT`
  and `ICON_NODE_HEIGHT` 89, `INFORMATION_NODE_HEIGHT` 144, `LANE_HEADER` 144). Use `golden_split`, `golden_height`, and
  `golden_point` rather than arithmetic on magic numbers. Components with content-dependent heights return their height
  — position the next component from the returned value, not a guess.
- **Pick the node for the copy.** `title_node` for a name, `centered_node` for a name plus one line,
  `information_node` for an eyebrow, title, and description lines, `icon_node` when an icon helps, `list_node` for
  fields, `decision_node` for a branch, `repeated_stack` for many-of-a-thing, `box_label` for a plain box. Text does not
  wrap, so every line must fit the width.
- **Size the box for the copy, not the other way around — and prove it by looking.** The library measures nothing: a
  line longer than its box silently overflows into whatever is next to it, and there is no exception to catch. Fixed
  node components don't expose a font-size override, so width and copy length are the only levers.
  - **Estimate before drawing.** At the library's default sizes, a bold title (`TYPE_SCALE` 21) runs about 12px/char
    and a regular description (18) about 9px/char; a node's usable width is roughly its declared width minus a ~40-unit
    inset (two 21-unit gutters). Check the longest string in your data — the longest role name, the longest label —
    against that budget before picking a node width, not after something clips.
  - **A floating label needs its gap sized to it, not the other way round.** `labeled_connector` and a bare
    `diagram.text` between two nodes aren't clipped by anything, so a label wider than the gap it sits in visually
    overlaps both neighbors even though nothing "errors." Either widen the gap to fit the longest label plus margin, or
    shorten the copy (`"building"`, not `"status:building"`) — check the widest label in the set, not just one.
  - **Detection is visual, not programmatic.** Coordinates that satisfy every `node_port` call can still overflow,
    because overflow is a text-vs-box comparison the library never makes. After every layout change, render the SVG to
    a raster image and look at it — `qlmanage -t -s 1600 -o /tmp <file>.svg` or, for something scriptable,
    `<chrome-binary> --headless --disable-gpu --screenshot=out.png --window-size=<w>,<h> file://<abs-path>.svg` — then
    read the PNG back. Check every box: does any title or description run past its border, does any connector label
    cross into a neighboring node, does any multi-line stack clip its own box.
  - **When it doesn't fit, fix the cause, not the symptom.** Widen the node, shorten the copy, or split it across
    `information_node`'s multiple description lines — don't shrink `stroke_width` or nudge coordinates by eye to hide
    an overflow one pixel at a time.
- **Use the connector helpers.** `node_port(x, y, width, height, side)` for an attachment point instead of a computed
  edge coordinate, `line`/`path` (`dashed=True` for conditional routes) for connectors, `labeled_connector` for a
  captioned horizontal arrow, `junction` for an intentional split, `annotation_callout` for a leader note.
- **A connector spans the gap, never the node.** `node_port` is only as good as the box you hand it: pass the
  component's real height and the arrow starts on the edge; pass a guessed one and the port lands inside the shape, so
  the line is drawn over the node it was leaving. A content-sized component (`information_node`, `list_node`,
  `legend_header`) returns its height — keep it and use it for the port, the next component's position, and anything
  aligned beside it. When the layout needs those heights before `Diagram(height=...)` exists, draw the components once
  on a scratch `Diagram` and read the heights back; measuring costs a few lines and survives a copy change that a
  hardcoded height does not. After rendering, look at every arrowhead and tail: leaking into a box is the failure this
  catches.
- **Fill the canvas.** Under the light theme `background` defaults to None, which leaves the SVG transparent, so the
  figure picks up whatever the host page is behind it — including a dark README. Pass a `background` always. For white,
  override the one key (`palette={"background": "#ffffff"}`) and pass `background="background"`; under
  `DiagramTheme.DARK` leave the theme's own color alone.
- **Frame and explain.** `group_panel` (reserve 55 above for the heading, 34 below for the caption), `swimlane` (first
  144 units are the header), and `boundary_frame` for containment. When roles or connector styles carry meaning, add a
  legend with `legend_header`, `color_key`, and `arrow_key`.
- **Light by default, dark only on request.** A diagram script's bare `uv run scripts/...` invocation writes the light
  theme only — don't render and save a dark copy alongside it unless the user asked for one. `--theme` (default
  `DiagramTheme.LIGHT`) is how a caller opts into dark, not something the script exercises for them. If a dark version
  is requested, check it in both themes before calling it done: the default dark palette draws every role in the same
  gray, so color keys mean nothing there — either omit them under `DiagramTheme.DARK` or override the role colors.
- **Reach for `svg_element` last.** It exists for shapes the library lacks. Resolve its colors with `diagram.color` and
  keep it on the scale.

A diagram is an artifact in its own right. Default to `diagram.save(path)`, with the document linking the SVG, so it
can be regenerated, diffed as text, and reused by more than one page without each one carrying its own copy. Reach
for `diagram.figure(caption=...)` inside a `MarkdownReport` when the Markdown has to travel as a single
self-contained file; that inlines the SVG and makes the page unreadable as a diff. Either way alt text defaults to the
diagram title, which is usually the wrong description, so pass real alt text whenever the title doesn't describe the
picture.

A diagram is a script, and this is the exception to §3's rule that logic belongs in the package. One numbered script
per diagram: the coordinates, the copy, and a `main` that saves the SVG. Nothing imports a diagram, so there is
nothing to reuse, and keeping the drawing beside the data it is drawn from is what makes it editable a year later.
Give the script options only where a caller would really choose — `--output`, `--theme` — each defaulting so the bare
`uv run scripts/...` invocation writes the committed file (§3). Move a diagram into the package only when the program
itself renders it at runtime, at which point it is a feature, not documentation.

---

## 16. Anti-patterns quick reference

The negative space around the rules above. When you find one of these, fix it.

**Architecture**

- Concrete-type-only public APIs (no protocol seam) → lead with a `Protocol`.
- Modules coupling through globals or singletons → talk through protocols and dataclasses.
- Catch-all `utils.py` / `helpers.py` / `models.py` files → give helpers a real home.
- Module-level mutable state → move into a class.
- In-memory dict accumulating state across requests → an expirable SQLite-backed cache with a per-entry TTL (§6).
- Leading-underscore names → restructure so the concept doesn't need to exist as a named thing at all.
- Class created only to hold a `services` reference → module function taking `services` (see §6).
- Behavior nested as a `def`/`async def`/`lambda` closure inside another function → module-level function taking its
  deps as parameters; nest only for a framework-forced callback (dependency factory, ASGI send/receive wrapper,
  decorator, C-library codec) (§6).
- `default_factory=lambda: ...`, or a lambda parking real logic → a named callable (§6).
- Resource/client constructed outside the `Services` registry → own it on `Services` so lifecycle lives in one place.
- `BaseModel` for a plain internal record → frozen dataclass; reserve `BaseModel` for boundaries and validation (§6).
- `os.environ` / `os.getenv` read anywhere in the program → a typed `BaseSettings` field on the root `Settings` or a
  domain settings class it composes (§6).
- Hand-rolled `.env` parsing, or config read before the file is loaded → `load_dotenv()` at the composition root plus
  `env_file` on the root `model_config` (§6).
- Inline `Depends(...)` repeated across handler signatures, old-style `param: T = Depends(fn)`, or `dependencies=[...]`
  on the app/router → a shared `Annotated[T, Depends(fn)]` alias named `SomethingDep` (§6).
- `yield`-based dependency opening/closing a resource per request → own the lifecycle on `Services`/`lifespan` (§6).
- Dependency that needs arguments, written inline or duplicated → a factory returning the dependency, wrapped in the
  alias (§6).
- Cross-cutting gate implemented inside the dependency (unreachable from inner code) → a plain `services`-first
  function, with the dependency as a thin wrapper (§6).
- Optional resource re-checked for `None` at every call site → type it `T | None`, resolve through one `require_*`
  helper (§6).
- `async __init__` faked with lazy connect-on-first-use → cheap sync `__init__` + awaited `setup()`/`close()` driven
  from the composition root (§6).
- Decorator-routed handlers (`@app.get`, `@router.post`) → plain functions registered with `app.add_api_route` (§6).
- Route handler living inside a domain module, forcing it to import sibling domains → move it to a per-domain
  `domain_routes.py` layer of bare handlers; routes import domains, never the reverse (§6).
- Per-module `register(app)` hook, or routes scattered across modules → bare handlers enumerated centrally in
  `create_app`, the one place that lists the whole URL surface (§6).

**Concurrency**

- `threading.Thread` or `multiprocessing` in new async code → `asyncio.TaskGroup` or `asyncio.to_thread` for blocking
  calls.
- Mutable objects shared between coroutines without a lock → `asyncio.Lock` or immutable dataclasses.
- Bare `asyncio.create_task` where `TaskGroup` would do → structured concurrency.
- `time.sleep` in a coroutine → `await asyncio.sleep`.
- Swallowed `CancelledError` → let it propagate; cancellation is not an error.
- Polling loops with `await asyncio.sleep(0)` → `asyncio.Queue` or an event.

**Errors**

- Bare `except Exception:` without re-raising → name what you catch.
- Catch-and-swallow → propagate or model "missing" honestly with `None`.
- Third-party exception leaking across area boundary → wrap at the boundary.
- Logging inside an exception class → log at the catch site.
- `sys.exit()` in library code → raise an exception.
- Domain-exception → HTTP-status mapping scattered across handlers → one translation function per area (§9).
- Server-side fault returned as 4xx, or raw upstream detail leaked to the caller → blame in the status code (your fault
  is 5xx), caller-safe message only (§9).

**Trust boundaries**

- Validating untrusted input with a substring denylist or regex → parse it with the engine's own parser and inspect the
  structure (§10).
- Regex or `str.split` pulling fields out of a format that has a grammar (Python, JSON, YAML, TOML, SQL, RST, Markdown,
  HTML, CSV, URLs, dates) → use the real parser and walk the structure (§10).
- A format emitted by string concatenation or f-string interpolation (hand-built JSON, hand-escaped Markdown, SQL
  assembled from values) → use the serializer, or bind parameters (§10).
- HTML built with f-strings, `str.format`, `%`, or concatenation → `jinja2` with `autoescape=True`, or
  `markupsafe.escape` for a fragment; hand-built HTML is an XSS hole, not a style issue (§10).
- `jinja2.Environment()` left with autoescaping off, or `Markup(...)` wrapping a value that was never escaped →
  `autoescape=True`, and `Markup` only over text you sanitized (§10).
- Jinja2 templates embedded in Python string literals → template files behind a `FileSystemLoader` (§10).
- XML or email assembled as text → build an `lxml.etree` tree, or an `email.message.EmailMessage`; a newline in an
  interpolated header value is header injection (§10).
- Shell command built by interpolating into a string with `shell=True` → an argument list with `shell=False` (§10).
- `yaml.load` with the default loader → `yaml.safe_load`; untrusted XML through the stdlib parsers → `defusedxml` (§10).
- Line-oriented editing of an indentation-sensitive format (YAML, RST) or of Markdown that may contain code fences →
  parse, transform the structure, re-serialize (§10).
- A home-grown format parsed by a chain of `split` calls → write the grammar and parse it, or reuse a format that
  already has a parser (§10).
- Caller values interpolated into SQL or a command string → compose an AST or bind parameters; interpolation is
  injection (§10).
- SQL inspected or rewritten with regex/substring matching → parse it with the engine's own parser, or `sqlglot` when
  there isn't one to reach (§10).
- A single control guarding untrusted input → layer independent controls; apply irreversible locks last (§10).

**Style**

- One client/subsystem's settings, models, and client class split across sibling files (`s3_settings.py`,
  `s3_models.py`, `s3_client.py`) → keep them together in one module named after the client (§4).
- A module split, or padded, to hit a line-count target → cohesion decides the split, not length (§4).
- Docstrings that restate the code → document the contract, or delete the docstring.
- Comments referencing tickets/PRs → context goes in git history.
- Value from a closed set typed as bare `str`/`int` (allowed values in a comment) → model it as an `enum` (§2).
- Shorthand bare enum member imports → use the fully qualified `EnumType.MEMBER` form.
- Wildcard imports → explicit names or `__all__`.
- Multi-line strings built by adjacent-literal concatenation (one quoted fragment per line) → triple-quoted string.

**Testing**

- Tests pinned to one concrete implementation → test the protocol.
- "It ran locally" treated as "it works" → write the automated test.
- Shared mutable fixtures between tests → `scope="function"` fixtures.
- Missing concurrency stress test for a concurrent type → add one.
- `unittest.mock` / `MagicMock` / `monkeypatch` of internals standing in for a client → use the production client
  against a real local, CI, or external instance (§11).
- API route functions called directly → drive the application through its framework test client (§11).
- Database behavior tested against SQLite, a dictionary, or an in-memory repository → use an isolated test database with
  the production engine, schema, constraints, and migrations (§11).
- Synthetic records shaped to make the assertion pass → real fixtures from `data/` or a committed sample (§11).
- A test faked so it passes without the resource it needs → skip it with a message naming the fetch script (§11).
- Tests that only cover the happy path → spend the budget on empty, boundary, malformed, absent, and repeated cases
  (§11).
- Trivial function checks or assertions that restate the implementation → test a consequential contract, invariant,
  regression, edge case, or core workflow instead (§11).
- Test named after the function rather than the behavior → name the behavior; the test list is the specification (§11).

**Reports & diagrams**

- Markdown built with f-strings, `"\n".join(...)`, or a hand-rolled template → `MarkdownReport` (§15).
- A value interpolated into report text with an f-string → `params` on the method, so Jinja does the substitution
  (§15).
- Hand-numbered figure captions (`"Figure 3: ..."`) → `figure(caption=...)`; `render` numbers them in document order
  (§15).
- Mermaid, Graphviz, or hand-written SVG for a diagram → an `mdreport` `Diagram` (§15).
- Hex colors in diagram code → palette keys, or `diagram.color(key)` inside a custom element; hex belongs only in
  Lucide icon arguments and palette overrides (§15).
- Magic coordinates and sizes → `FIBONACCI_SPACE`, `TYPE_SCALE`, the named component heights, and `golden_*` helpers
  (§15).
- A computed box-edge coordinate for a connector → `node_port(...)` (§15).
- The next component positioned by a guessed offset below a content-sized one → use the height that component returned
  (§15).
- A hardcoded height passed to `node_port` for a content-sized node → the port lands inside the shape and the arrow is
  drawn over the node; measure the height on a scratch `Diagram` and lay out from that (§15).
- An arrowhead or tail overlapping a node in the rendered SVG → the port is using the wrong box; fix the height, don't
  nudge the coordinate (§15).
- `Diagram(...)` under the light theme with no `background` → transparent canvas that inherits the host page; pass one
  (§15).
- A diagram inlined into Markdown by default → `diagram.save(path)` and reference the SVG; inline only when the file
  has to be self-contained (§15).
- Node color chosen to imply a role → set `role`; explicit `fill`/`stroke` is for accents only (§15).
- `figure` without `alt_text`, or a diagram figure relying on the title as alt text → describe the picture (§15).
- Color keys in a legend under `DiagramTheme.DARK` with the default palette → every role is the same gray; drop them or
  override the colors (§15).
- A documentation diagram hidden in the package behind a thin script → the drawing is the script; keep it there
  (§3, §15).
- Node text or a connector label that runs past its box/gap in the rendered SVG → widen the box, shorten the copy, or
  widen the gap; the library never wraps or clips, so this only shows up by rendering the file and looking (§15).
- Judging a diagram's layout from its coordinates alone → render it to a PNG (headless Chrome screenshot, `qlmanage
  -t`) and inspect every box before calling the layout done (§15).

**Project layout**

- Logic living in a script rather than the package → move it to `src/myproject/`; scripts are thin CLIs (§3). The
  one exception is a documentation diagram, which is the script (§15).
- `argparse`, raw `sys.argv`, or `input()` parsing in a script → one `@click.command()` over a typed `main` (§3).
- Hand-written validation of a path, range, or closed set → `click.Path(exists=True)`, `click.IntRange`, `click.Choice`
  / an enum; let `click` produce the error (§3).
- Option with a default but no `show_default=True`, or no `help=` → `--help` is the interface people read (§3).
- `required=True`, or a script that errors out when run with no arguments → default every option so the bare
  `uv run scripts/...` invocation works (§3).
- Bare invocation that triggers the expensive path (full corpus, all epochs) → default to a small slice, with a flag to
  ask for the full run (§3).
- Flag whose default is the destructive or costly behavior (`--no-overwrite`) → invert it so you opt in (§3).
- Script with no module docstring, or one lacking a `Usage:` block of runnable `uv run ...` lines → add it (§3).
- `Usage:` lines that no longer parse against the script's options → keep them in sync; a stale invocation is worse than
  none (§3).
- Scripts unnumbered, or numbered `1`, `2`, `3` with no room to insert → group by category and step by tens (§3).
- Renumbering existing scripts to make room → insert at an intermediate number instead; the old names are referenced
  elsewhere (§3).
- Datasets, weights, or generated outputs committed to git → gitignore `data/` and provide a script that reproduces it
  (§3).
- Code imported from `data/` → it holds bytes, not modules (§3).
- Package directory at the repo root instead of `src/` → use the `src/` layout so tests exercise the installed package
  (§3).

---

_This guide is a distillation of conventions from strict-typed, async-first Python. The strong opinions — protocol
seams, structured concurrency, typed exception hierarchies, tests as contract, no private names, no global state — are
what make the resulting code safe to change. Adjust the thresholds to your targets; keep the principles._
