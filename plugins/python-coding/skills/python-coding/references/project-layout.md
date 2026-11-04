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

