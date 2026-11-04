#!/usr/bin/env -S uv run --script
# /// script
# requires-python = "==3.12.*"
# dependencies = ["click==8.5.0", "pydantic==2.12.3", "pydantic-settings==2.11.0"]
# [tool.uv]
# exclude-newer = "2026-09-22T00:00:00Z"
# ///
"""Start, stop, find and audit named background jobs from any project, with one shared SQLite audit table.

`start NAME -- COMMAND...` runs COMMAND detached in its own session and process group, under a small supervisor that
records how it ended. `stop NAME` signals the whole group (SIGTERM, then SIGKILL after `--grace` seconds), after
checking that the group's leader is still the process jobctl started, so a reused PID is never signalled. Nothing is
ever matched by a command-line pattern.

Processes jobctl did not start are addressed by the port they hold (`:3000`) or by PID, never by name: `why` explains
who they are and what started them, `orphans` finds the ones left behind in a repository, and `stop :PORT` / `stop PID`
stops them with their children (after the same start-time identity check), recording the stop as a run.

Every run is one row of the `runs` table in `$JOBCTL_HOME/jobctl.sqlite` (default `~/.local/state/jobctl`), shared by
every project, shell and Claude session on the machine. A row is an OpenTelemetry span: trace and span ids, parent
span, start and end in Unix nanoseconds, status code, events, plus wide columns for the command, script path and
SHA-256, working directory, git commit, process group, observed listening ports, log path, host and launcher. A job
started from inside another job joins its trace (via `TRACEPARENT`). `export` writes OTLP/JSON for any collector.

Actions:
    skill [show|setup|status|remove] print the embedded guide or manage the small agent skill stub
    setup                initialize owned installation/preferences and discover optional Rex
    doctor               read-only checks; --fix repairs setup, --probe exercises a real viewer
    open [NAME|SPAN_ID]  open/reuse a Rex dashboard or job viewer; names follow restarts, span IDs pin
    dashboard            jobs dashboard in the current terminal
    start NAME -- CMD     start a job (--port P: refuse if P is taken, then wait until the job listens on it)
    stop NAME             stop the job's whole process group (--reason is recorded; --dry-run lists it first)
    stop :PORT | PID      stop what holds a port, or one PID, with its children; checks identity, records the stop
    restart NAME          stop, then start again with the recorded command, directory, ports and tags
    status                latest run of every job that is running or ran in --since (default 1d)
    logs NAME             end of the latest run's log (--follow to stream until it ends)
    wait NAME             block until the job ends; exit with its exit code
    ports                 every listening TCP port on the machine, with the job that holds it
    why :PORT | PID       who holds a port or what a PID is: job, directory, age, and the parents that started it
    orphans               processes under this repository whose parent has exited and that no job owns
    prune --older-than D  delete old finished runs' logs (--rows: and their rows; --keep-failed; --dry-run previews)
    history [NAME]        past runs, filtered by --project/--state/--since/--grep/--port
    show NAME|SPAN_ID     every column and event of one run
    sql "SELECT ..."      read-only SQL over the runs table (see `schema` for its columns)
    schema                every column of the runs table, its states, events, and example queries
    export                OTLP/JSON (ExportTraceServiceRequest) of the selected runs

NAME may be `project/name`; a bare name resolves in the current project first, then in any single project.
Noninteractive actions take --json. Exit codes: 0 ok, 1 other error, 2 bad input, 3 not found, 4 permission denied,
5 conflict (already running, port busy), 6 not ready (or port still busy after stop), 7 refused (PID reused, target runs
this jobctl, PID belongs to a job); `wait` exits with the job's own code.

Usage:
    uv run jobctl.py setup
    uv run jobctl.py doctor --probe --require-rex
    uv run jobctl.py start build --open -- swift build
    uv run jobctl.py open build
    uv run jobctl.py dashboard
    uv run jobctl.py status
    uv run jobctl.py start web --port 8081 -- uv run scripts/serve.py --port 8081
    uv run jobctl.py logs web --lines 50
    uv run jobctl.py stop web --reason "new export"
    uv run jobctl.py ports
    uv run jobctl.py why :3000
    uv run jobctl.py stop :3000 --dry-run
    uv run jobctl.py orphans
    uv run jobctl.py history --since 7d --grep train
    uv run jobctl.py schema
    uv run jobctl.py sql "SELECT project, name, state, exit_code FROM runs ORDER BY start_time_unix_nano DESC LIMIT 10"
    uv run jobctl.py export --since 1d > spans.json
"""

from __future__ import annotations

import asyncio
import base64
import codecs
import contextlib
import datetime
import errno
import fcntl
import getpass
import hashlib
import itertools
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import termios
import time
import tty
import unicodedata
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar
from urllib.parse import urlsplit

import click
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# Keep skill assets here: copying the standalone script carries its guide and installer.
SKILL_STUB = """---
name: jobs
description: >-
  Use jobctl as the default task runner whenever work involves executing commands:
  builds, tests, checks, scripts, installs, downloads, data processing, training,
  servers and local or remote jobs. Apply before starting work, even for short
  tasks or when background execution was not requested, and when monitoring logs,
  verifying results, finding ports, stopping/restarting processes or recovering
  interrupted work. Run task commands as named jobs and verify their recorded
  outcomes. Use Rex for interactive terminal programs.
metadata:
  short-description: "Default task execution and process lifecycle with jobctl"
  jobctl-stub: "2"
---
<!-- Installed by "jobctl skill setup". Remove it with "jobctl skill remove". -->

Before executing task commands, run `jobctl skill show` and follow its guide.
Use jobctl throughout the task: inspect existing runs, start named work, monitor
progress, verify the recorded outcome, and clean up only task-owned processes.
The complete guide is embedded in the installed script and matches its version.

If jobctl is not on PATH, run `uv run /path/to/jobctl.py skill show` using the
script's installed location (normally `~/.agents/skills/jobs/scripts/jobctl.py`).
"""
SKILL_OPENAI = """interface:
  display_name: "Jobctl"
  short_description: "Run, track and verify work across every project"
  default_prompt: "Use $jobs to run this task, track its progress, and verify the recorded result."
policy:
  allow_implicit_invocation: true
"""
SKILL_GUIDE = r"""# Run and supervise tasks with jobctl

`jobctl` is the default runner for executable work in every project: builds, tests, checks, scripts, installs,
downloads, data processing, training and services, including short tasks. Each command runs as a **named job** in
its own process group, under a supervisor that records its outcome and retains its logs. Apply this workflow even
when the user did not ask for background execution. Normal task authorization and permission checks still apply.

## Task workflow

1. Inspect existing project jobs with `jobctl status --project PROJECT` and use `show` or `history` when resuming.
   Reuse a relevant live job; inspect a failed run before starting it again.
2. Start task commands with `jobctl start NAME --project PROJECT -- COMMAND ARGS...`. Pick a name for the role,
   such as `build`, `test` or `lint`. Commands execute without a shell; specify `--cwd` when needed.
3. Monitor with `logs` or `open`. For finite work, wait on the returned span ID and inspect its recorded outcome.
   Starting successfully only means the command launched. A view or log follower ending does not prove it succeeded.
4. On failure, read the run and logs, fix the cause, then start a new run. Use `restart` when reusing the exact
   recorded command, directory, ports and tags. When arguments change, use `start` after the earlier run has ended.
5. Stop only work owned by this task and explicitly temporary services. Keep services the user wants running.
   Report verified results and relevant live jobs; do not equate a listening port with application health.

```bash
jobctl start test --project my-project -- swift test
jobctl wait SPAN_ID                # use the span ID returned by start; propagates the job's exit code
jobctl logs SPAN_ID
jobctl show SPAN_ID --json         # verify the recorded outcome
```

Use jobctl for work commands; its own guide, setup, status, logs, wait and other control commands run directly.
Quick read-only discovery such as reading a file or locating source text can stay in the foreground. Programs
requiring interactive input or a controlling terminal belong in Rex; jobctl supplies its own Rex progress views.
On remote machines, run the same jobctl script there through the available remote execution tool; state is per host.
Never substitute `&`, `nohup`, `setsid` or a terminal pane for supervised noninteractive work.

```bash
jobctl start classifier-server --port 8081 -- \
  uv run scripts/classify/060_topic_bank.py --export ~/data/x/export --device mps --port 8081
jobctl status                      # what is running (all projects) and what ran today
jobctl logs classifier-server      # end of its log; --follow to stream
jobctl stop classifier-server --reason "new export"
```

`jobctl` is a standalone `uv` script with pinned dependencies, normally linked as `~/.local/bin/jobctl`.
If it is not on PATH, run `uv run /path/to/jobctl.py ...`. Copying that one script to another machine also
copies this full guide.

## Skill installation and built-in guide

```bash
jobctl skill show                  # print this complete guide; jobctl skill does the same
jobctl skill setup                 # install/update the small jobs skill stub
jobctl skill status                # current, missing, outdated or conflict
jobctl skill remove                # remove owned skill assets; preserve scripts and other files
jobctl skill setup --agent claude  # select only Claude; --agent is repeatable
jobctl skill setup --skill-dir DIR # override with one explicit skill folder
jobctl skill setup --dry-run       # preview; --force explicitly replaces an unrelated SKILL.md
```

By default, setup installs into both `~/.claude/skills/jobs` and `~/.agents/skills/jobs`, including on a fresh
machine. Codex, OpenCode and Pi share the agents folder. Use repeatable `--agent claude|codex|opencode|pi` to
select agents, or `JOBCTL_SKILL_DIR` / `--skill-dir` for one explicit folder. Existing directory links are
preserved; a shared destination is written once. Status and removal use the same selection, and JSON emits
one record per destination. `jobctl setup` also installs the stub, and `doctor --fix` repairs it. The installed
stub tells agents to run `jobctl skill show`, so the guide always matches the script being used.
Setup installs the small `SKILL.md` and `agents/openai.yaml`. The latter supplies Codex UI metadata and explicitly
permits automatic skill selection. Claude's default invocation behavior also allows automatic selection.
Descriptions make the skill discoverable; they do not force invocation on every turn. Mandatory always-loaded
policy belongs in the agent's instructions. No tool permission grants or agent hooks are installed by this skill.
Setup recognizes previous shipped skill versions and upgrades them. Unknown or edited content
is reported as a conflict and preserved unless skill setup/remove receives `--force`. All selected destinations
are checked for conflicts before writing. Skill commands do not create
an audit database or contact Rex. `show` prints Markdown directly without a pager, including in a terminal;
`show --json` returns a document with the guide in `guide`.

## Setup, diagnosis and Rex views

Jobctl owns its Rex integration. Use its commands rather than constructing Rex launches, assigning pane IDs,
editing Rex's configuration or maintaining manual `rex.*` tags. Ordinary headless jobs still work without Rex.

```bash
jobctl setup                       # initialize state/link/skill, discover Rex; safe to repeat
jobctl doctor                      # read-only diagnostics; never autostarts Rex
jobctl doctor --fix                 # repair owned setup and reconcile recorded views
jobctl doctor --probe --require-rex # real terminal/job probe, isolated and cleaned up

jobctl start build --open -- swift build
jobctl open build                  # reuse a live view, or open a replacement
jobctl open build --layout tab      # below (default), right, or tab
jobctl open SPAN_ID                 # pin one run; a name follows restarts
jobctl dashboard --project cue-app # use the current terminal
jobctl open                       # explicitly open/reuse a Rex dashboard
```

On installation or presentation failure, run `doctor` first. Use `setup` for uninitialized state or a missing
executable link; use `doctor --fix` for jobctl-owned repairs. Neither replaces an unrelated executable or edits
Rex's `init.lua`. Setup can save a default with `--layout tab` and install a link in `--bin-dir DIR`.
`doctor` warns when optional Rex/context is absent; `--require-rex` makes that failure nonzero.
The probe creates its own temporary database, job and viewer; it verifies visible output and job survival after
quitting with `q` and verifying that its pane disappears, then stops the job. It does not validate an application's
provider or application health.

Use `start --open` when the user should see progress. Keep batch/child jobs quiet unless a view is useful.
`open` preserves current focus; add `--focus` to select the view. Use `--session SESSION --layout tab`
for another session. All jobctl/Rex execution is local to the selected Unix-socket host/account; run jobctl on
the remote machine for remote jobs. `JOBCTL_REX_EXECUTABLE` can select a CLI explicitly.

The dashboard puts running jobs first, keeps selection on the same job as runs arrive, and previews its command,
directory, ports and recent output when space permits. `/` searches job names, projects, commands and directories;
Enter applies the search and Escape cancels editing. Tab cycles All, Running, Problems (failed/lost) and Finished;
Escape clears applied search and filters. Counts refer to the latest run of each job, including live jobs older
than 24 hours. Start times in the table use local time. Narrow panes omit columns and previews.

The viewer shows run state, exit, duration, ports and logs and reports recorded state through Rex's program-status
protocol. Arrow keys or `j/k` scroll or select; Page Up/Down moves by a page; Home/End selects the first/last job.
Enter opens the selected job or historical run. Escape returns one screen, preserving selection, filters and log
position; it first cancels help, search editing or a pending action. Tab opens run history from logs; arrows select
a run and Enter opens its pinned logs. Breadcrumbs and contextual controls show the current screen. At the job list,
Escape clears filters. `h` and `b` remain optional aliases for history and back; `g` returns to recent logs (or the
first dashboard job; `G` selects the last). `?` shows keyboard help. `q` closes only
the view; while editing a search it types a literal q, and in help it returns to the view. Missing or unreadable
logs show a diagnostic while the viewer remains usable and recovers when the file returns. Press `s` twice to stop
or `r` twice to restart the selected run. A changed selection/run invalidates confirmation.
Ctrl+C detaches and restores terminal modes;
the supervised job keeps running. Quitting a jobctl-created Rex view removes its pane (and its tab if empty).
`jobctl view NAME` and `jobctl dashboard` run in the current foreground terminal and return to its
shell on quit. Use `show`, `logs`, `status` and `wait` for piped or machine-readable output.

A successful `start --open` or `restart --open` retains exit 0 if only the view fails: JSON keeps the audit row's
fields and adds a separate `presentation` result. Check that field before claiming the view opened; do not retry
the job start. Explicit `open` presentation failures exit 8. Names follow the newest run; span IDs
and `--pin` remain fixed. Plain `logs --follow` still follows one run and is not evidence of success; use `wait`
or `show` for the recorded outcome. Closing a view never stops its job.

Jobctl retains creation intent before asking Rex to open a pane. If a request has an uncertain outcome, inspect
with `doctor --fix` before retrying. `open --new` explicitly creates an additional view. Automatic retries do not
silently create duplicates. Origin session/block tags are automatic hints; live view links are stored separately
from audit rows. Agent launcher attribution remains independent of Rex workspace context.

## Why

Every rule here comes from a real failure that cost time, money, or results:

| What went wrong without it | What jobctl does instead |
| --- | --- |
| `pkill -f train` inside `ssh '...'` matched the remote shell's own command line and killed it (SSH exit 255); the rest of the script never ran | Nothing is matched by pattern. `stop NAME` signals the process group recorded at start, and nothing else |
| A pattern kill hit another experiment that ran the same script | Jobs are addressed by `project/name`, never by command text |
| Killing `mlflow ui` left its 4 uvicorn workers holding the port; the next start failed with "address already in use" | Each job has its own session and process group. `stop` sends SIGTERM to the **whole group**, then SIGKILL after `--grace` seconds. Children and workers stop with it |
| `kill <pid>` from an old note hit an unrelated process after PID reuse | `stop` first checks that the group leader's start time matches the recorded one; on a mismatch it refuses |
| `cd dir && setsid nohup cmd &` held the SSH session's stdout open, so the call hung until the job ended | `start` detaches with stdin set to `/dev/null` and output sent to a log file, and returns at once |
| A second start of the same server orphaned the first one, which kept running unseen | `start` refuses a name that is still running (use `restart`) |
| A server "started" but crashed on import; nobody noticed until a request failed | `--port P` refuses to start if P is taken (and names who holds it), then waits until the job listens on P. If the job dies first, the error prints the log's end |
| "Which port is the topic viewer on? Is anything still on 8081?" | `jobctl ports` lists every listening TCP port with the job that owns it |
| A dev server started with `&` in an old shell held port 3000; the only way out was `lsof -t -i :3000 \| xargs kill` | `jobctl why :3000` shows who holds it and which parents started it; `jobctl stop :3000` stops it and its children after an identity check, and records the stop |
| Servers left behind by closed terminals and ended sessions piled up unseen | `jobctl orphans` lists this repository's processes whose parent has exited and that no job owns |
| "Which arguments did yesterday's good run use? Which commit?" | Every run's command, script path, script SHA-256, cwd, git commit/branch/dirty, ports, exit code, timings and log are in the audit table |
| Output went to a terminal that closed; the error was lost | Every run gets its own log file, never overwritten: `logs NAME`, or `log_path` in the table |
| A Claude `run_in_background` shell died with the session, or was stopped while a job ran inside it | Jobs live outside any shell or session; any session in any folder can see, wait on, or stop them |

Benefits beyond safety: jobs are **reproducible** (the exact command and code hash are recorded), **visible from
anywhere** (no need to be in the project that started them), and **auditable** (who started what, when, why it
stopped).

## When to use it

Use `jobctl start` for task execution regardless of expected duration: builds, tests, linters, scripts, downloads,
installs, data processing, training, evaluation and batch work. Use it for services, watchers, mirrors and file syncs
that must keep running after the launching command returns, and always declare listening ports with `--port`.
Also use jobctl to inspect, wait for, restart or stop existing work, investigate occupied ports and orphaned processes,
compare previous runs and recover after interruptions. Do not require the user to name jobctl before choosing it.

Never use, for anything long-lived: `cmd &`, `nohup`, `setsid`, `disown`, `screen`/`tmux` sessions as a process
manager, `pkill`/`pgrep -f`/`killall` with a pattern, or `kill` on a PID you looked up. For a process jobctl did not
start, use `jobctl why` and `jobctl stop :PORT` / `jobctl stop PID` instead. The Bash tool's
`run_in_background` is **only** for blocking on `jobctl wait NAME` so you get notified when the job ends (see below).
It is never for the job itself.

## How

### Naming and projects

- A job is `project/name`. The project defaults to the git repository's directory name (else the current
  directory's name); override it with `--project`. Names use letters, digits, `-`, `_`, `.`.
- Pick names that say what the job is: `classifier-server`, `mlflow-ui`, `train-v3`, `mirror-runs`, `watch-corpus-v1`.
  Reuse the same name for the same role, so `history NAME` shows its whole past.
- A bare name in `stop`/`logs`/`wait`/`show`/`restart` resolves in the current project first, then in any single
  project that has it. Give `project/name` when two projects use it.

### Commands

```bash
jobctl start NAME [--port P ...] [--check CMD] [--on-exit CMD] [--tag k=v ...] -- COMMAND ARGS...
jobctl schedule add NAME EXPRESSION [OPTIONS] -- COMMAND ARGS... # "in 10m", "every 1h", "at 02:00"
jobctl schedule list [--json]
jobctl schedule cancel NAME                                      # cancel waiting timer; zero orphan shells
jobctl schedule trigger NAME                                     # run immediately on demand
jobctl stop NAME [--reason "why"] [--grace 30] [--dry-run]  # SIGTERM to the group, SIGKILL after grace
jobctl restart NAME [--reason "why"] [--dry-run] # same command, cwd, ports and tags; new run row
jobctl status [--since 1d] [--project P] [--json]
jobctl logs NAME [--lines 40] [--follow]
jobctl wait NAME                                 # blocks; exits with the job's exit code
jobctl stop :PORT|PID [--dry-run] [--reason ...] # a port's holder or one PID, with its children (see below)
jobctl ports [--json]                            # every listening TCP port, and its job
jobctl why :PORT|PID [--json]                    # who holds a port / what a PID is, and what started it
jobctl orphans [--cwd DIR] [--json]              # leftovers under this repository that no job owns
jobctl history [NAME] [--since 7d] [--state failed] [--grep text] [--port 8081] [--limit 30] [--json]
jobctl show NAME|SPAN_ID [--json]                # every column and event of the newest run
jobctl schema [--json]                           # every column of the runs table, its states, events, examples
jobctl sql "SELECT ..."                          # read-only SQL over the runs table
jobctl export [--since 1d] > spans.json          # OTLP/JSON for any OpenTelemetry collector
jobctl setup [--layout tab] [--bin-dir DIR] [--skill-dir DIR] # installation, skill and preferences
jobctl skill [show|setup|status|remove] [--skill-dir DIR] [--dry-run] [--force]
jobctl doctor [--fix] [--probe] [--require-rex] [--json]
jobctl open [NAME|SPAN_ID] [--pin] [--new] [--focus] [--layout below|right|tab]
jobctl dashboard [--project P]                 # dashboard in the current terminal
```

`stop` and `restart` take `--dry-run`: they list every process they would signal (and, for `restart`, the command
they would start) and change nothing. Noninteractive actions take `--json` (one object per line; `show` and dry runs print one
document).

Exit codes, so a script or agent can branch without parsing text:

| Code | Meaning |
| --- | --- |
| 0 | ok |
| 1 | other error |
| 2 | bad input: name, tag, `--since`, target, SQL, missing command |
| 3 | not found: no such job, span, PID, or nothing listens on the port |
| 4 | permission denied: another user's process, or a port held by a process this user cannot see |
| 5 | conflict: the job is already running, or a `--port` is taken |
| 6 | not ready: the job died or did not listen in time; or a port is still held after `stop :PORT` |
| 7 | refused: PID reused, the target runs this jobctl (your shell or Claude Code), or a PID belongs to a job |
| 8 | Rex presentation failed; optional start/restart --open reports this separately from job startup |

`wait` exits with the job's own exit code instead; use `wait NAME --json` when you must tell the two apart.

Options go **before** `--`; everything after `--` is the command, passed as an argument list (no shell). For shell
features (pipes, `&&`, redirects), say so explicitly: `-- sh -c '...'`. Prefer a script over a long `sh -c` string.

### Servers

```bash
jobctl start topic-viewer --port 8082 -- uv run scripts/classify/015_view_topics.py --port 8082
```

- Always pass `--port` with the port the server will use. jobctl refuses to start if the port is busy and names the
  holder (a job or a process). It then waits up to `--ready-timeout` (120 s) until the job listens. A non-zero exit
  means the server is not serving: read the printed log.
- Bind local tools to `127.0.0.1`. On macOS, port 5000 belongs to the AirPlay Receiver (`ControlCenter`/`AirTunes`).
  Pick another port for `mlflow ui` and similar tools.
- After changing the server's code or model, run `jobctl restart NAME --reason "..."`.
- "Address already in use"? Run `jobctl why :PORT`. If a job holds it, stop the job by name. If a finished job shows
  state `...+left`, its workers outlived it; `jobctl stop NAME` ends them. If no job holds it, see the next section.

### Processes jobctl did not start

Something started with `&`, in another terminal, or by a crashed session is addressed by its **port** (`:3000`) or its
**PID**, never by name or pattern:

```bash
jobctl why :3000                  # pid, command, directory, age, job (if any), and the parents that started it
jobctl orphans                    # this repo's processes whose parent has exited and that no job owns
jobctl stop :3000 --dry-run       # what would be signalled: the holders and all their children
jobctl stop :3000 --reason "stale dev server"   # SIGTERM, SIGKILL after --grace, then checks the port is released
jobctl stop 4242 --reason "..."   # one PID and its children (e.g. a row from `orphans`)
```

- A port held by a job stops that job, as `stop NAME` would. A PID that belongs to a job is refused (exit 7): stop the
  job by name.
- Before every signal, each PID's start time is checked against the one seen when the stop was planned, so a reused
  PID is never signalled. jobctl refuses (exit 7) to signal its own shell, terminal or Claude Code session, or any
  process tree that contains them.
- The stop is recorded as a `stopped` run named `port-3000` or `pid-4242` in the current project, with
  `tags.external = "true"`, the signalled PIDs in its events, and a log of what was sent. `history --port 3000` finds it.
- Always look first (`why` or `--dry-run`): the holder may be someone's real work. Then, if it should keep running,
  stop it and start it again as a job.
- `orphans` searches the git repository that contains `--cwd` (default: the current directory), else `--cwd` itself.
  A process counts when its parent has exited (it was adopted by PID 1 or a `systemd --user`) and its working directory
  is inside that folder.

### Long jobs (training, evaluation, batch work)

```bash
jobctl start train-v3 --tag run=v3 --tag budget_usd=5 -- uv run scripts/train/050_train.py --config v3.toml
```

Use `jobctl open train-v3` for a visible view in Rex; it reports completion/failure through Rex's status protocol.
Use `jobctl wait train-v3` with the tool's supported background-wait mechanism when an agent needs the exit code.
The waiter is not the job's owner. Do not poll status with shell `sleep` loops.

The job itself must still save its work: write results in batches with atomic writes (temp file, then rename), resume
on restart, keep checkpoints, and mirror outputs off the machine while it runs (mirrors are jobs too). jobctl keeps the
process safe and visible; it does not make a script resumable.

### Scheduling (daemonless)

Schedule tasks for future or recurring execution without a standing Python daemon:

```bash
# One-shot scheduled run (relative or wall-clock)
jobctl schedule add batch-export "in 2h" -- uv run scripts/export.py
jobctl schedule add nightly-eval "at 02:00" --on-exit "curl -s http://127.0.0.1:8080/wake" -- uv run scripts/eval.py

# Recurring execution
jobctl schedule add sync-metrics "every 30m" -- uv run scripts/sync.py

# Management
jobctl schedule list
jobctl schedule cancel sync-metrics   # cleanly terminates timer group; zero orphan shells
jobctl schedule trigger nightly-eval  # run immediately on demand
```

- **Daemonless**: While waiting between runs, `jobctl` uses a detached POSIX `sleep` trampoline in its own process group. Zero Python processes remain in memory while idle (<1 MB total).
- **Orphan-safe cancellation**: `jobctl schedule cancel NAME` terminates the entire trampoline group via `SIGTERM`, verified against PID start time (`lstart`).
- **Overlap protection**: If a scheduled interval arrives while the previous run is still active, `jobctl` detects the collision, logs `skipped_overlap`, and advances to the next tick without duplicate parallel instances.
- **Self-healing**: On reboot or external kill, `reconcile_schedules` automatically recovers recurring schedules on the next CLI command.

### In-Flight Health Checks and Exit Alerting

Long-running jobs can be monitored periodically and alert on completion:

```bash
jobctl start classifier-server --port 8081 \
  --check "curl -f -s http://127.0.0.1:8081/health" \
  --check-interval 60 \
  --check-fail-action stop \
  --on-exit 'curl -s -X POST http://127.0.0.1:8080/alert -d "job=$JOBCTL_JOB&state=$JOBCTL_STATE"' \
  -- uv run scripts/serve.py --port 8081
```

- `--check`: Runs a health check command every `--check-interval` seconds. If it fails, logs `check.failed` and terminates the job if `--check-fail-action stop` is set.
- `--on-exit`: Executes when the job ends (success, failure, or stop). Injects `$JOBCTL_JOB`, `$JOBCTL_STATE`, `$JOBCTL_EXIT_CODE`, `$JOBCTL_LOG_PATH`, and `$JOBCTL_DURATION`.

### Jobs that start jobs, and pods

- A job started from inside another job (for example a pipeline runner that starts its own mirrors) joins the
  parent's trace: same `trace_id`, `parent_span_id` = the parent's span, `launched_by = job`. The supervisor exports
  `TRACEPARENT`, `JOBCTL_JOB` and `JOBCTL_SPAN_ID` to every job. OpenTelemetry-instrumented code can use
  `TRACEPARENT` to attach its own spans.
- On a remote machine or pod, run the same script there (`uv run jobctl.py start ...` through your pod tool's `exec`).
  Do not hand-write `ssh 'nohup ...'` lines. Each machine keeps its own audit database; pull it with the run's results
  if you want it locally.

## Auditing

All runs from every project, shell and session go into one SQLite database:

- `~/.local/state/jobctl/jobctl.sqlite` (override with `JOBCTL_HOME`). It lives in XDG state, not in `~/.cache`,
  because cache directories may be wiped by cleanup tools, and the audit history must survive.
- Logs are in `~/.local/state/jobctl/logs/<project>/<name>/<UTC time>-<span>.log`, one file per run. Each starts with
  a header: job, span, start time, directory, and the exact command.
- WAL mode with a busy timeout: many supervisors and sessions write at once without blocking each other.

**One wide table, `runs`, one row per run = one OpenTelemetry span.** Run `jobctl schema` before writing SQL: it
prints every column with its SQLite type, meaning and OpenTelemetry name, the `state` values, the event names and their
attributes, and example queries that run as printed (`jobctl schema --json` for the same as data). In short: identity
(`span_id`, `trace_id`, `name`, `project`), outcome (`state`, `exit_code`, `status_message`), timing
(`start_time_unix_nano`, `started_at`, `duration_seconds`), what ran (`command`, `command_line`, `script`,
`script_sha256`, `cwd`, `git_*`), process (`pgid`, `declared_ports`, `ports`, `log_path`) and who (`host_name`,
`user_name`, `launched_by`, `tags`, `events`). `command`, `declared_ports`, `ports`, `tags` and `events` hold JSON:
query them with `json_extract` and `json_each`.

`launched_by` (and a stop's `by`) is `job` for a job started inside a job, else the name in `JOBCTL_LAUNCHER`
when an app that runs jobctl for an agent sets it, else `claude-code` inside Claude Code, else `terminal`.

Useful queries:

```bash
jobctl history --since 7d --state failed                   # what failed this week
jobctl history classifier-server --limit 5                 # the last 5 runs of one job
jobctl history --port 8081                                 # who has used port 8081
jobctl sql "SELECT project, name, state, exit_code, duration_seconds, command_line FROM runs
            WHERE script LIKE '%050_train%' ORDER BY start_time_unix_nano DESC"
jobctl sql "SELECT git_commit, script_sha256, command_line FROM runs WHERE name = 'train-v3' AND state = 'succeeded'"
jobctl sql "SELECT project, COUNT(*), SUM(duration_seconds)/3600 AS hours FROM runs GROUP BY project"
jobctl sql "SELECT name, json_extract(e.value, '$.attributes.reason') AS reason FROM runs, json_each(runs.events) e
            WHERE json_extract(e.value, '$.name') = 'stop.requested'"
sqlite3 -readonly ~/.local/state/jobctl/jobctl.sqlite      # any SQLite tool works; open read-only
```

To send runs to an OpenTelemetry backend: `jobctl export --since 1d > spans.json`, then
`curl -X POST -H 'Content-Type: application/json' --data @spans.json http://localhost:4318/v1/traces`.

## Caveats

- **Command lines are stored and logged in plain text.** Never put secrets in arguments; read them from `.env` or
  the environment.
- A program that daemonizes itself (its own `setsid`, `--daemon`, double fork) leaves the group, and jobctl cannot
  stop it. Run such programs in foreground mode (`--foreground`, `--no-daemon`).
- A job killed from outside jobctl (or by a reboot) shows as `lost`. A finished job whose workers outlived it shows
  as `<state>+left`; `stop` ends them.
- On Linux, ports of other users' processes are visible only to root. `--port` still refuses a busy port (it test-binds),
  but it may not be able to name the holder.
- Job names cannot be all digits: a bare number is read as a PID.
- Ports below 1024 cannot be test-bound without root, so `why :80` with no visible holder reports "not found" even if
  another user's process holds it.
- Logs are never deleted automatically. `jobctl prune --older-than 30d` deletes the logs of finished runs older than
  that and records a `log_pruned` event on each row; `--dry-run` previews, `--keep-failed` keeps failed and lost runs'
  logs, `--project`/`--grep`/NAME narrow it. `--rows` also deletes those runs' rows (each job's newest run stays, so
  `restart` still works) and runs VACUUM. Running jobs and log files outside the logs directory are never touched.
"""  # noqa: E501 — Markdown tables retain a complete row on each line.
LEGACY_SKILL_SHA256 = (
    "8c341d4f3f3dd7c82ed083effc8897d961631b812769ec894bc5379172101936",
    "8ca6555d7419b2ccdafdd7c8e7b90501188bab8ef835d653da5e5bd9954090bd",
)


@dataclass(frozen=True)
class SkillDocument:
    """One executable-owned skill asset, with exact recognized upgrade sources."""

    path: Path
    content: str
    legacy_sha256: tuple[str, ...] = ()


SKILL_DOCUMENTS = (
    SkillDocument(Path("SKILL.md"), SKILL_STUB, LEGACY_SKILL_SHA256),
    SkillDocument(Path("agents/openai.yaml"), SKILL_OPENAI),
)

POLL_SECONDS = 0.5
PORT_SAMPLE_DELAYS = (1.0, 1.0, 3.0, 5.0, 20.0)  # first samples at 1, 2, 5, 10 and 30 s after start
PORT_SAMPLE_INTERVAL = 60.0
STARTING_GRACE_NANOS = 30 * 10**9  # a row without a process group yet is "starting" this long, then lost
JSON_COLUMNS = ("command", "declared_ports", "ports", "tags", "events")
SCHEDULE_JSON_COLUMNS = ("command", "declared_ports", "tags")
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    span_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    parent_span_id TEXT,
    name TEXT NOT NULL,
    project TEXT NOT NULL,
    state TEXT NOT NULL,
    status_code TEXT NOT NULL,
    status_message TEXT,
    exit_code INTEGER,
    start_time_unix_nano INTEGER NOT NULL,
    end_time_unix_nano INTEGER,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds REAL,
    command TEXT NOT NULL,
    command_line TEXT NOT NULL,
    script TEXT,
    script_sha256 TEXT,
    cwd TEXT NOT NULL,
    git_root TEXT,
    git_commit TEXT,
    git_branch TEXT,
    git_dirty INTEGER,
    log_path TEXT NOT NULL,
    pgid INTEGER,
    leader_started TEXT,
    declared_ports TEXT NOT NULL,
    ports TEXT NOT NULL,
    host_name TEXT NOT NULL,
    user_name TEXT NOT NULL,
    os_type TEXT NOT NULL,
    launched_by TEXT NOT NULL,
    tags TEXT NOT NULL,
    events TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_by_job ON runs (project, name, start_time_unix_nano);
CREATE INDEX IF NOT EXISTS runs_by_state ON runs (state);
CREATE INDEX IF NOT EXISTS runs_by_start ON runs (start_time_unix_nano);
CREATE TABLE IF NOT EXISTS schedules (
    schedule_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    project TEXT NOT NULL,
    expression TEXT NOT NULL,
    delay_seconds REAL NOT NULL,
    is_recurring INTEGER NOT NULL,
    command TEXT NOT NULL,
    command_line TEXT NOT NULL,
    cwd TEXT NOT NULL,
    log_path TEXT,
    declared_ports TEXT NOT NULL,
    tags TEXT NOT NULL,
    on_exit TEXT,
    check_cmd TEXT,
    check_interval REAL,
    check_fail_action TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    trampoline_pgid INTEGER,
    trampoline_leader_started TEXT,
    next_run_unix_nano INTEGER,
    last_run_unix_nano INTEGER,
    last_span_id TEXT,
    last_state TEXT,
    total_runs INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project, name)
);
CREATE INDEX IF NOT EXISTS idx_schedules_next ON schedules (enabled, next_run_unix_nano);
"""
VIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobctl_views (
    view_key TEXT PRIMARY KEY,
    document TEXT NOT NULL
);
"""


class SkillAgent(StrEnum):
    """Agent selection follows Rex; Codex, OpenCode and Pi share the agents skill folder."""

    CLAUDE = "claude"
    CODEX = "codex"
    OPENCODE = "opencode"
    PI = "pi"


class Settings(BaseSettings):
    """jobctl's configuration, read from the environment."""

    model_config = SettingsConfigDict(env_prefix="JOBCTL_")

    home: Path = Field(
        default=Path.home() / ".local" / "state" / "jobctl",
        description="Directory of the audit database and the job logs (JOBCTL_HOME).",
    )
    traceparent: str | None = Field(
        default=None,
        validation_alias="TRACEPARENT",
        description="W3C trace context of the job (if any) this process runs inside.",
    )
    claude_code: str | None = Field(
        default=None, validation_alias="CLAUDECODE", description="Set by Claude Code in the shells it runs."
    )
    launcher: str | None = Field(
        default=None,
        description="Who runs jobctl (JOBCTL_LAUNCHER), set by an app that runs it for an agent; recorded as "
        "launched_by and a stop's `by` in place of claude-code or terminal.",
    )
    rex_executable: Path | None = None
    rex_server: str | None = Field(default=None, validation_alias="REX_SERVER")
    rex_session: str | None = Field(default=None, validation_alias="REX_SESSION")
    rex_block: str | None = Field(default=None, validation_alias="REX_BLOCK")
    skill_dir: Path | None = Field(
        default=None,
        description="Optional single-destination override (JOBCTL_SKILL_DIR).",
    )
    agent_home: Path = Field(default=Path.home(), description="Account root for agent skill destinations.")
    skill_agents: tuple[SkillAgent, ...] = tuple(SkillAgent)

    @property
    def presentation(self) -> Path:
        """Jobctl-owned viewer preferences; Rex's configuration is untouched."""
        return self.home.expanduser() / "presentation.json"

    @property
    def database(self) -> Path:
        """The shared audit database."""
        return self.home.expanduser() / "jobctl.sqlite"

    @property
    def logs(self) -> Path:
        """Root of the per-run log files."""
        return self.home.expanduser() / "logs"


class Action(StrEnum):
    """What the command does."""

    START = "start"
    STOP = "stop"
    RESTART = "restart"
    STATUS = "status"
    LOGS = "logs"
    WAIT = "wait"
    PORTS = "ports"
    HISTORY = "history"
    SHOW = "show"
    SQL = "sql"
    EXPORT = "export"
    SCHEMA = "schema"
    WHY = "why"
    ORPHANS = "orphans"
    PRUNE = "prune"
    SETUP = "setup"
    SKILL = "skill"
    DOCTOR = "doctor"
    OPEN = "open"
    DASHBOARD = "dashboard"
    VIEW = "view"  # terminal UI, also usable without Rex
    SUPERVISE = "supervise"  # internal: the detached supervisor started by `start`
    SCHEDULE = "schedule"
    SCHEDULE_RUN = "schedule-run"


class SkillAction(StrEnum):
    """The guide is part of the executable; only setup/remove mutate the installed stub."""

    SHOW = "show"
    SETUP = "setup"
    STATUS = "status"
    REMOVE = "remove"


class SkillState(StrEnum):
    """Known content is owned; unknown or edited content requires an explicit override."""

    CURRENT = "current"
    MISSING = "missing"
    OUTDATED = "outdated"
    CONFLICT = "conflict"


class SkillFileReport(BaseModel):
    """Keep ownership and changes visible for each file in the installed skill."""

    path: Path
    state: SkillState
    changed: bool = False


class SkillReport(BaseModel):
    """The same installation result is exposed as readable text and structured JSON."""

    action: SkillAction
    path: Path
    state: SkillState
    changed: bool = False
    dry_run: bool = False
    files: tuple[SkillFileReport, ...] = ()


class RunState(StrEnum):
    """Lifecycle state of one run."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPED = "stopped"
    LOST = "lost"


RUN_STATE_MEANINGS = {
    RunState.RUNNING: "the job is running (or its supervisor is starting it)",
    RunState.SUCCEEDED: "exited with code 0",
    RunState.FAILED: "non-zero exit, killed by a signal jobctl did not send, or the command could not start",
    RunState.STOPPED: "stopped through jobctl (`stop`, `restart`, or a `stop :PORT`/`stop PID` row)",
    RunState.LOST: "recorded as running, but its process group is gone: killed outside jobctl, or a reboot",
}
EVENT_MEANINGS = {
    "process.start": "the command started; attributes: pid",
    "port.listen": "the job's group began listening on new TCP ports; attributes: ports",
    "stop.requested": """a stop was asked for; attributes: reason, by (claude-code, terminal or the JOBCTL_LAUNCHER \
name), by_user, signal, and pids for processes jobctl did not start""",
    "stop.stragglers": "a stop of leftover processes of an already finished run; attributes as stop.requested",
    "stop.escalated": "SIGKILL after the grace period; attributes: signal, after_seconds, pids (if not a job)",
    "job.lost": "the process group was found gone without a recorded exit; no attributes",
}
SQL_EXAMPLES = (
    "SELECT project, name, state, exit_code FROM runs ORDER BY start_time_unix_nano DESC LIMIT 10",
    "SELECT name, exit_code, status_message FROM runs WHERE state = 'failed' AND started_at >= date('now', '-7 day')",
    "SELECT git_commit, script_sha256, command_line FROM runs WHERE name = 'train-v3' AND state = 'succeeded'",
    "SELECT project, COUNT(*) AS runs, SUM(duration_seconds) / 3600 AS hours FROM runs GROUP BY project",
    "SELECT project, name FROM runs, json_each(runs.ports) AS p WHERE p.value = 8081",
    "SELECT name, json_extract(tags, '$.run') AS run_tag FROM runs WHERE json_extract(tags, '$.run') IS NOT NULL",
    "SELECT name, json_extract(e.value, '$.attributes.reason') AS reason FROM runs, json_each(runs.events) AS e "
    "WHERE json_extract(e.value, '$.name') = 'stop.requested'",
)


class StatusCode(StrEnum):
    """OpenTelemetry span status."""

    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


OTLP_STATUS = {StatusCode.UNSET: 0, StatusCode.OK: 1, StatusCode.ERROR: 2}


class JobctlError(click.ClickException):
    """A job cannot be started, found, stopped or queried. Exit code 1; subclasses carry their own code."""


class BadInput(JobctlError):
    """The command line is malformed: a bad name, tag, time, target, SQL, or a missing command."""

    exit_code = 2


class JobNotFound(JobctlError):
    """No run matches the name or span id."""

    exit_code = 3


class ProcessNotFound(JobctlError):
    """Nothing listens on the port, or no process has the PID."""

    exit_code = 3


class PermissionDenied(JobctlError):
    """The process belongs to another user, or this user cannot see who holds the port."""

    exit_code = 4


class JobAlreadyRunning(JobctlError):
    """A job of that project and name is still running."""

    exit_code = 5


class PortBusy(JobctlError):
    """A declared port is already in use."""

    exit_code = 5


class JobNotReady(JobctlError):
    """The job ended, or did not listen on its declared ports in time."""

    exit_code = 6


class PortStillBusy(JobctlError):
    """A port is still listened on after its holders were stopped."""

    exit_code = 6


class NotOurProcess(JobctlError):
    """The recorded process group now belongs to a different process (PID reuse); it is not signalled."""

    exit_code = 7


class RefusedTarget(JobctlError):
    """The target runs this jobctl (its shell, terminal or Claude Code session), or a PID belongs to a job."""

    exit_code = 7


class RexIssue(StrEnum):
    """Failures of presentation, independent of a job's lifecycle."""

    UNAVAILABLE = "unavailable"
    CONTEXT = "context"
    REMOTE = "remote"
    REQUEST = "request"
    RESPONSE = "response"
    UNCERTAIN = "uncertain"
    NOT_READY = "not_ready"


class RexError(JobctlError):
    """Rex presentation failed; the job itself may still be running. Exit 8."""

    exit_code = 8

    def __init__(self, kind: RexIssue, message: str, returncode: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.returncode = returncode


class ViewLayout(StrEnum):
    """Where a new viewer goes; only explicit open operations create panes."""

    BELOW = "below"
    RIGHT = "right"
    TAB = "tab"


class JobViewTarget(BaseModel):
    """A role-following view switches to the new run after a restart."""

    kind: Literal["job"] = "job"
    project: str
    name: str


class RunViewTarget(BaseModel):
    """A pinned view always displays exactly one audit span."""

    kind: Literal["run"] = "run"
    span_id: str


class DashboardTarget(BaseModel):
    """A project dashboard, or all projects when project is absent."""

    kind: Literal["dashboard"] = "dashboard"
    project: str | None = None


ViewTarget = Annotated[JobViewTarget | RunViewTarget | DashboardTarget, Field(discriminator="kind")]


class ViewState(StrEnum):
    """Creation uncertainty is retained so retrying cannot silently duplicate a pane."""

    CREATING = "creating"
    READY = "ready"
    CLOSED = "closed"
    UNCERTAIN = "uncertain"


class ViewRecord(BaseModel):
    """Jobctl's link to one replaceable viewer; independent of run audit rows."""

    view_key: str
    token: str
    target: ViewTarget
    endpoint: str
    host_id: str
    session_id: str
    label: str
    state: ViewState = ViewState.CREATING
    block_id: str | None = None
    window_id: str | None = None
    ready_at: str | None = None
    revision: int = 0
    rendered_revision: int = -1


class PresentationConfig(BaseModel):
    """Versioned preferences written only by setup or doctor --fix."""

    version: Literal[1] = 1
    layout: ViewLayout = ViewLayout.BELOW
    bin_dir: Path = Field(default_factory=lambda: Path.home() / ".local" / "bin")


class RexIdentity(BaseModel):
    """Only local Unix-socket servers may execute a viewer against this database."""

    endpoint: str
    host_id: str
    instance_id: str
    account: str
    session_id: str | None = None
    block_id: str | None = None


class RexBlock(BaseModel):
    """A server-provided resource, addressed by its complete opaque ID."""

    block_id: str
    host_id: str | None = None
    window_id: str | None = None
    label: str


class RexBlocks(BaseModel):
    """The server's structured list of blocks."""

    blocks: list[RexBlock] | None


class RexInspection(BaseModel):
    """A single block's identity and ownership domain."""

    session_id: str
    block: RexBlock


class RexSession(BaseModel):
    """An explicitly resolved session ID."""

    session_id: str


class RexCreated(BaseModel):
    """Creation replies identify the new block first, including for splits."""

    block_ids: list[str] = Field(min_length=1)
    window_id: str | None = None


class RexExit(BaseModel):
    """The terminal child's final exit, distinct from the supervised job's exit."""

    exit_code: int


class RexProcess(BaseModel):
    """An exited viewer cannot be reused merely because its pane remains open."""

    last_exit: RexExit | None = None


class PresentationResult(BaseModel):
    """A start may succeed even when its optional presentation fails."""

    state: Literal["created", "reused", "error"]
    view: ViewRecord | None = None
    issue: RexIssue | None = None
    message: str | None = None


class CheckState(StrEnum):
    """Optional Rex absence is a warning unless explicitly required."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class DoctorCheck(BaseModel):
    """A diagnostic with a stable check name and a human explanation."""

    name: str
    state: CheckState
    message: str


class DoctorReport(BaseModel):
    """Machine-readable diagnostics and explicit repairs."""

    checks: list[DoctorCheck] = Field(default_factory=list)
    repairs: list[str] = Field(default_factory=list)

    @property
    def healthy(self) -> bool:
        """Warnings preserve headless operation; actual errors fail doctor."""
        return all(check.state is not CheckState.ERROR for check in self.checks)


class Run(BaseModel):
    """One job run: one row of the `runs` table and one OpenTelemetry span."""

    span_id: str = Field(description="this run's span id (16 hex)", json_schema_extra={"otel": "spanId"})
    trace_id: str = Field(
        description="trace id (32 hex); shared with the parent job when started from inside one",
        json_schema_extra={"otel": "traceId"},
    )
    parent_span_id: str | None = Field(
        default=None,
        description="span id of the job that started this one, else null",
        json_schema_extra={"otel": "parentSpanId"},
    )
    name: str = Field(description="job name", json_schema_extra={"otel": "name, job.name"})
    project: str = Field(
        description="project: the git repository's directory name, else the directory name, or --project",
        json_schema_extra={"otel": "resource service.name"},
    )
    state: RunState = Field(
        default=RunState.RUNNING,
        description="running | succeeded | failed | stopped | lost (see the state list below)",
        json_schema_extra={"otel": "job.state"},
    )
    status_code: StatusCode = Field(
        default=StatusCode.UNSET,
        description="OK (succeeded), ERROR (failed, lost), UNSET (running, stopped)",
        json_schema_extra={"otel": "status.code"},
    )
    status_message: str | None = Field(
        default=None,
        description="why it ended, e.g. 'exit code 1', 'killed by SIGSEGV', 'stopped: <reason>'",
        json_schema_extra={"otel": "status.message"},
    )
    exit_code: int | None = Field(
        default=None,
        description="the job's exit code; 128+N when killed by signal N; null while running, lost, or not a job",
        json_schema_extra={"otel": "process.exit.code"},
    )
    start_time_unix_nano: int = Field(
        description="start, Unix nanoseconds (sort by this)", json_schema_extra={"otel": "startTimeUnixNano"}
    )
    end_time_unix_nano: int | None = Field(
        default=None,
        description="end, Unix nanoseconds; null while running",
        json_schema_extra={"otel": "endTimeUnixNano"},
    )
    started_at: str = Field(description="start, UTC ISO-8601 (e.g. 2026-10-26T12:40:12+00:00)")
    ended_at: str | None = Field(default=None, description="end, UTC ISO-8601; null while running")
    duration_seconds: float | None = Field(default=None, description="end minus start, seconds; null while running")
    command: list[str] = Field(
        description="JSON list: the exact argv (for a stop :PORT/PID row: the stopped commands)",
        json_schema_extra={"otel": "process.command_args"},
    )
    command_line: str = Field(
        description="the argv shell-quoted into one string (search it with LIKE)",
        json_schema_extra={"otel": "process.command_line"},
    )
    script: str | None = Field(
        default=None,
        description="the first .py argument, as an absolute path when it exists",
        json_schema_extra={"otel": "job.script"},
    )
    script_sha256: str | None = Field(
        default=None,
        description="SHA-256 of that script's contents at start",
        json_schema_extra={"otel": "job.script.sha256"},
    )
    cwd: str = Field(description="working directory", json_schema_extra={"otel": "process.working_directory"})
    git_root: str | None = Field(
        default=None,
        description="git repository root of cwd, else null",
        json_schema_extra={"otel": "vcs.repository.path"},
    )
    git_commit: str | None = Field(
        default=None, description="HEAD commit at start", json_schema_extra={"otel": "vcs.ref.head.revision"}
    )
    git_branch: str | None = Field(
        default=None, description="branch at start", json_schema_extra={"otel": "vcs.ref.head.name"}
    )
    git_dirty: bool | None = Field(
        default=None,
        description="1 when tracked files had uncommitted changes at start, 0 when clean",
        json_schema_extra={"otel": "job.git.dirty"},
    )
    log_path: str = Field(description="this run's log file (one per run)", json_schema_extra={"otel": "job.log"})
    pgid: int | None = Field(
        default=None,
        description="process group id = PID of the supervisor that leads it",
        json_schema_extra={"otel": "process.pid"},
    )
    leader_started: str | None = Field(
        default=None, description="the group leader's start time from ps; checked before any signal (PID reuse)"
    )
    declared_ports: list[int] = Field(
        default_factory=list,
        description="JSON list: the --port values given at start",
        json_schema_extra={"otel": "job.declared_ports"},
    )
    ports: list[int] = Field(
        default_factory=list,
        description="JSON list: TCP ports the job's group was seen listening on (sampled)",
        json_schema_extra={"otel": "job.ports"},
    )
    host_name: str = Field(description="machine", json_schema_extra={"otel": "resource host.name"})
    user_name: str = Field(description="user who started it", json_schema_extra={"otel": "resource user.name"})
    os_type: str = Field(description="darwin or linux", json_schema_extra={"otel": "resource os.type"})
    launched_by: str = Field(
        description="claude-code, terminal, job or the JOBCTL_LAUNCHER name; for a stop :PORT/PID row, who stopped it",
        json_schema_extra={"otel": "job.launched_by"},
    )
    tags: dict[str, str] = Field(
        default_factory=dict,
        description='JSON object of --tag key=value; {"external": "true"} on stop :PORT/PID rows',
        json_schema_extra={"otel": "job.tag.<key>"},
    )
    events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="JSON list of {time_unix_nano, name, attributes} (see the event list below)",
        json_schema_extra={"otel": "events"},
    )
    updated_at: str = Field(description="last change to this row, UTC ISO-8601")

    @property
    def job(self) -> str:
        """`project/name`."""
        return f"{self.project}/{self.name}"

    def to_row(self) -> dict[str, Any]:
        """Column values for SQLite (lists and dicts as JSON text)."""
        row = self.model_dump(mode="json")
        for column in JSON_COLUMNS:
            row[column] = json.dumps(row[column])
        return row

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Run:
        """Parse one `runs` row."""
        values = dict(row)
        for column in JSON_COLUMNS:
            values[column] = json.loads(values[column])
        return cls.model_validate(values)

    def add_event(self, name: str, **attributes: Any) -> None:
        """Append an OpenTelemetry span event stamped now."""
        self.events.append({"time_unix_nano": time.time_ns(), "name": name, "attributes": attributes})

    def finish(self, state: RunState, exit_code: int | None, message: str | None) -> None:
        """Record the end of the run: state, OTel status, end time and duration."""
        end = time.time_ns()
        self.state = state
        self.exit_code = exit_code
        self.status_message = message
        self.status_code = {RunState.SUCCEEDED: StatusCode.OK, RunState.STOPPED: StatusCode.UNSET}.get(
            state, StatusCode.ERROR
        )
        self.end_time_unix_nano = end
        self.ended_at = iso(end)
        self.duration_seconds = round((end - self.start_time_unix_nano) / 1e9, 3)



class Schedule(BaseModel):
    """A registered scheduled job."""

    schedule_id: str = Field(description="16 hex identifier")
    name: str = Field(description="job name")
    project: str = Field(description="project name")
    expression: str = Field(description="e.g. in 10s, every 5m, at 14:00")
    delay_seconds: float = Field(description="nominal delay in seconds")
    is_recurring: bool = Field(default=False)
    command: list[str] = Field(description="command argv")
    command_line: str = Field(description="quoted command line")
    cwd: str = Field(description="working directory")
    log_path: str | None = None
    declared_ports: list[int] = Field(default_factory=list)
    tags: dict[str, str] = Field(default_factory=dict)
    on_exit: str | None = None
    check_cmd: str | None = None
    check_interval: float | None = None
    check_fail_action: str = "stop"
    enabled: bool = True
    trampoline_pgid: int | None = None
    trampoline_leader_started: str | None = None
    next_run_unix_nano: int | None = None
    last_run_unix_nano: int | None = None
    last_span_id: str | None = None
    last_state: str | None = None
    total_runs: int = 0
    created_at: str
    updated_at: str

    @property
    def job(self) -> str:
        return f"{self.project}/{self.name}"

    def to_row(self) -> dict[str, Any]:
        row = self.model_dump(mode="json")
        for column in SCHEDULE_JSON_COLUMNS:
            row[column] = json.dumps(row[column])
        row["is_recurring"] = 1 if self.is_recurring else 0
        row["enabled"] = 1 if self.enabled else 0
        return row

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Schedule:
        values = dict(row)
        for column in SCHEDULE_JSON_COLUMNS:
            values[column] = json.loads(values[column])
        values["is_recurring"] = bool(values["is_recurring"])
        values["enabled"] = bool(values["enabled"])
        return cls.model_validate(values)


class RunStore:
    """The shared audit database. Every change is a short transaction, so many processes can write at once."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout=30000")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(SCHEMA)
        self.connection.executescript(VIEW_SCHEMA)

    def view(self, key: str) -> ViewRecord | None:
        """Read one presentation link without changing its run."""
        row = self.connection.execute("SELECT document FROM jobctl_views WHERE view_key = ?", (key,)).fetchone()
        return ViewRecord.model_validate_json(row[0]) if row else None

    def views(self) -> list[ViewRecord]:
        """All recorded views, including closed and uncertain creation attempts."""
        return [
            ViewRecord.model_validate_json(row[0])
            for row in self.connection.execute("SELECT document FROM jobctl_views ORDER BY view_key")
        ]

    def save_view(self, record: ViewRecord) -> None:
        """Persist identity before requesting pane creation, making uncertain outcomes recoverable."""
        self.connection.execute(
            "INSERT INTO jobctl_views VALUES (?, ?) ON CONFLICT(view_key) DO UPDATE SET document = excluded.document",
            (record.view_key, record.model_dump_json()),
        )

    @contextlib.contextmanager
    def edit_view(self, key: str) -> Generator[ViewRecord]:
        """Fence the launcher/viewer's read-modify-write handshake across processes."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            record = self.view(key)
            if record is None:
                raise JobNotFound(f"No recorded viewer {key}")
            yield record
            self.save_view(record)
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")


    def insert_schedule(self, schedule: Schedule) -> None:
        """Insert or replace a schedule."""
        row = schedule.to_row()
        columns = ", ".join(row)
        placeholders = ", ".join(f":{column}" for column in row)
        self.connection.execute(f"INSERT OR REPLACE INTO schedules ({columns}) VALUES ({placeholders})", row)

    def get_schedule(self, project: str, name: str) -> Schedule | None:
        """Fetch schedule by project and name."""
        row = self.connection.execute("SELECT * FROM schedules WHERE project = ? AND name = ?", (project, name)).fetchone()
        return Schedule.from_row(row) if row else None

    def get_schedule_by_id(self, schedule_id: str) -> Schedule | None:
        """Fetch schedule by id."""
        row = self.connection.execute("SELECT * FROM schedules WHERE schedule_id = ?", (schedule_id,)).fetchone()
        return Schedule.from_row(row) if row else None

    @contextlib.contextmanager
    def edit_schedule(self, schedule_id: str) -> Generator[Schedule]:
        """Edit a schedule under an immediate transaction."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            sched = self.get_schedule_by_id(schedule_id)
            if sched is None:
                raise JobNotFound(f"no schedule with id {schedule_id}")
            yield sched
            sched.updated_at = iso(time.time_ns())
            row = sched.to_row()
            assignments = ", ".join(f"{column} = :{column}" for column in row if column != "schedule_id")
            self.connection.execute(f"UPDATE schedules SET {assignments} WHERE schedule_id = :schedule_id", row)
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")

    def select_schedules(self, where: str = "1", parameters: tuple[Any, ...] = ()) -> list[Schedule]:
        """Select schedules matching where condition."""
        rows = self.connection.execute(f"SELECT * FROM schedules WHERE {where} ORDER BY created_at DESC", parameters).fetchall()
        return [Schedule.from_row(row) for row in rows]

    def delete_schedule(self, schedule_id: str) -> None:
        """Delete a schedule."""
        self.connection.execute("DELETE FROM schedules WHERE schedule_id = ?", (schedule_id,))

    def close(self) -> None:
        """Close the connection."""
        self.connection.close()

    def insert(self, run: Run) -> None:
        """Add a new run."""
        row = run.to_row()
        columns = ", ".join(row)
        placeholders = ", ".join(f":{column}" for column in row)
        self.connection.execute(f"INSERT INTO runs ({columns}) VALUES ({placeholders})", row)

    def get(self, span_id: str) -> Run:
        """The run with this span id.

        Raises:
            JobNotFound: no such span.
        """
        row = self.connection.execute("SELECT * FROM runs WHERE span_id = ?", (span_id,)).fetchone()
        if row is None:
            raise JobNotFound(f"no run with span id {span_id}")
        return Run.from_row(row)

    @contextlib.contextmanager
    def edit(self, span_id: str) -> Generator[Run]:
        """Load a run under a write lock, let the caller change it, and write it back (all or nothing)."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            run = self.get(span_id)
            yield run
            run.updated_at = iso(time.time_ns())
            row = run.to_row()
            assignments = ", ".join(f"{column} = :{column}" for column in row if column != "span_id")
            self.connection.execute(f"UPDATE runs SET {assignments} WHERE span_id = :span_id", row)
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")

    def select(self, where: str = "1", parameters: tuple[Any, ...] = (), limit: int = -1) -> list[Run]:
        """Runs matching a SQL condition (bound parameters only), newest first."""
        rows = self.connection.execute(
            f"SELECT * FROM runs WHERE {where} ORDER BY start_time_unix_nano DESC LIMIT ?", (*parameters, limit)
        )
        return [Run.from_row(row) for row in rows]

    def latest(self, where: str = "1", parameters: tuple[Any, ...] = ()) -> list[Run]:
        """The newest run of every project/name matching a condition, newest first."""
        condition = f"""start_time_unix_nano = (SELECT MAX(start_time_unix_nano) FROM runs AS other
                        WHERE other.project = runs.project AND other.name = runs.name) AND ({where})"""
        return self.select(condition, parameters)


@dataclass(frozen=True)
class GitInfo:
    """Where the working directory sits in git, if anywhere."""

    root: str | None = None
    commit: str | None = None
    branch: str | None = None
    dirty: bool | None = None


@dataclass(frozen=True)
class Listener:
    """One listening TCP socket."""

    port: int
    address: str
    pid: int
    pgid: int | None
    command: str


@dataclass(frozen=True)
class ProcessInfo:
    """One process as `ps` reports it. PID plus start time identify it across PID reuse."""

    pid: int
    ppid: int
    pgid: int
    stat: str
    user: str
    started: str  # `ps` lstart in the C locale, e.g. "Mon Oct 26 09:12:03 2026"
    command: str

    @property
    def is_zombie(self) -> bool:
        """Exited, waiting for its parent to collect its status."""
        return self.stat.startswith("Z")

    @property
    def start_time_unix_nano(self) -> int | None:
        """Start time (None when `ps` printed an unexpected format)."""
        try:
            moment = datetime.datetime.strptime(self.started, "%a %b %d %H:%M:%S %Y")
        except ValueError:
            return None
        return int(moment.timestamp() * 1e9)


@dataclass(frozen=True)
class ProcessTarget:
    """A process addressed by the port it listens on (`:3000`) or by PID (`4242`), rather than by job name."""

    port: int | None = None
    pid: int | None = None

    @property
    def label(self) -> str:
        """Job-name-safe label for the audit row of a stop: `port-3000` or `pid-4242`."""
        return f"port-{self.port}" if self.port is not None else f"pid-{self.pid}"


@dataclass(frozen=True)
class StopPlan:
    """What a stop signals: jobs (by process group) and processes jobctl did not start (by PID, with children)."""

    label: str
    ports: list[int]
    jobs: list[Run]
    roots: list[ProcessInfo]
    external: list[ProcessInfo]  # the roots and all their descendants


@dataclass(frozen=True)
class TraceContext:
    """Trace id and parent span of a new run."""

    trace_id: str
    parent_span_id: str | None


def iso(unix_nano: int) -> str:
    """UTC ISO-8601 time with seconds."""
    return datetime.datetime.fromtimestamp(unix_nano / 1e9, datetime.UTC).isoformat(timespec="seconds")


def local_time(unix_nano: int | None) -> str:
    """Local wall-clock time for display."""
    if unix_nano is None:
        return "-"
    return datetime.datetime.fromtimestamp(unix_nano / 1e9).strftime("%Y-%m-%d %H:%M:%S")


def human_duration(seconds: float) -> str:
    """`3d4h`, `2h05m`, `4m10s`, `12s`."""
    whole = int(seconds)
    days, rest = divmod(whole, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def parse_since(text: str) -> int:
    """Unix nanoseconds for `30m`, `6h`, `2d`, `1w` ago, or an ISO date/time (local time unless it has an offset).

    Raises:
        BadInput: not a duration or an ISO time.
    """
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    if text[:-1].isdigit() and text[-1:] in units:
        return time.time_ns() - int(text[:-1]) * units[text[-1]] * 10**9
    try:
        moment = datetime.datetime.fromisoformat(text)
    except ValueError as error:
        raise BadInput(f"--since {text!r}: give 30m, 6h, 2d, 1w or an ISO date") from error
    return int(moment.timestamp() * 1e9)


def parse_traceparent(value: str | None) -> TraceContext:
    """Join the W3C trace context we run inside, or start a new trace."""
    parts = (value or "").split("-")
    if len(parts) == 4 and len(parts[1]) == 32 and len(parts[2]) == 16:
        try:
            int(parts[1], 16), int(parts[2], 16)
        except ValueError:
            pass
        else:
            if parts[1] != "0" * 32 and parts[2] != "0" * 16:
                return TraceContext(trace_id=parts[1], parent_span_id=parts[2])
    return TraceContext(trace_id=secrets.token_hex(16), parent_span_id=None)


def run_quietly(arguments: list[str], cwd: Path | None = None, accept_failure: bool = False) -> str | None:
    """Stdout of a small helper command, or None when it fails or is missing.

    `accept_failure` keeps the output of a command that exits non-zero after partial success (`lsof` does when some
    processes cannot be inspected).
    """
    try:
        result = subprocess.run(arguments, cwd=cwd, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 or accept_failure else None


def git_info(cwd: Path) -> GitInfo:
    """Repository root, commit, branch and dirtiness of `cwd` (all None outside git)."""
    root = run_quietly(["git", "rev-parse", "--show-toplevel"], cwd)
    if root is None:
        return GitInfo()
    status = run_quietly(["git", "status", "--porcelain", "--untracked-files=no"], cwd)
    return GitInfo(
        root=root,
        commit=run_quietly(["git", "rev-parse", "HEAD"], cwd),
        branch=run_quietly(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd),
        dirty=None if status is None else bool(status),
    )


def default_project(cwd: Path) -> str:
    """The git repository's directory name, else the directory's own name."""
    root = run_quietly(["git", "rev-parse", "--show-toplevel"], cwd)
    return Path(root).name if root else cwd.resolve().name


def find_script(command: list[str], cwd: Path) -> tuple[str | None, str | None]:
    """The first `.py` argument as an absolute path, and the SHA-256 of its contents when it exists."""
    for argument in command:
        if argument.endswith(".py"):
            path = (cwd / Path(argument).expanduser()).resolve()
            if path.is_file():
                return str(path), hashlib.sha256(path.read_bytes()).hexdigest()
            return argument, None
    return None, None


def check_name(kind: str, value: str) -> None:
    """Names become path parts and lookup keys: letters, digits, `-`, `_` and `.` only, and never all digits (a bare
    number is read as a PID).

    Raises:
        BadInput: other characters, all digits, or empty.
    """
    if not value or not value.replace("-", "").replace("_", "").replace(".", "").isalnum() or value.startswith("."):
        raise BadInput(f"{kind} {value!r}: use letters, digits, '-', '_' and '.'")
    if value.isdigit():
        raise BadInput(f"{kind} {value!r}: a bare number is read as a PID; add a letter")


def process_started(pid: int) -> str:
    """The start time `ps` reports for `pid` (empty when no such process); identifies a process across PID reuse."""
    return " ".join((run_quietly(["ps", "-o", "lstart=", "-p", str(pid)]) or "").split())


def group_alive(pgid: int) -> bool:
    """Whether any process of the group still exists."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def live_group(pgid: int) -> bool:
    """A zombie-only group has already ended and cannot usefully be signalled."""
    return group_alive(pgid) and any(
        process.pgid == pgid and not process.is_zombie for process in process_table().values()
    )


def group_is_ours(run: Run) -> bool:
    """Whether the run's process group is alive and still the one jobctl started.

    A live leader with another start time means the PID was reused. A live group whose leader is gone is ours: a group
    id cannot be reused while any member is alive (those members are leftover workers).
    """
    if run.pgid is None or not group_alive(run.pgid):
        return False
    leader = process_started(run.pgid)
    return not leader or leader == run.leader_started


def has_stragglers(run: Run) -> bool:
    """A finished run whose supervisor is gone but whose process group still has members (orphaned workers)."""
    return (
        run.state is not RunState.RUNNING
        and run.pgid is not None
        and group_alive(run.pgid)
        and not process_started(run.pgid)
    )



def parse_schedule_expression(expression: str) -> tuple[float, bool]:
    """Parse schedule expression e.g. "in 10s", "every 5m", "at 14:00" into (delay_seconds, is_recurring).

    Raises:
        BadInput: expression format is invalid.
    """
    expr = expression.strip().lower()
    is_recurring = False
    if expr.startswith("every "):
        is_recurring = True
        body = expr[len("every "):].strip()
    elif expr.startswith("in "):
        body = expr[len("in "):].strip()
    elif expr.startswith("at "):
        body = expr
    else:
        body = expr

    if body.startswith("at "):
        time_part = body[len("at "):].strip()
        now = datetime.datetime.now()
        parts = time_part.split(":")
        if len(parts) in (2, 3) and all(p.isdigit() for p in parts):
            hour = int(parts[0])
            minute = int(parts[1])
            second = int(parts[2]) if len(parts) == 3 else 0
            target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            delay = (target - now).total_seconds()
            return max(delay, 0.1), True
        try:
            target = datetime.datetime.fromisoformat(time_part)
            if target.tzinfo is None:
                delay = (target - now).total_seconds()
            else:
                delay = (target - datetime.datetime.now(datetime.UTC)).total_seconds()
            return max(delay, 0.1), False
        except ValueError:
            raise BadInput(f"invalid at-time specification: {time_part!r}") from None

    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([smhd])?", body)
    if not match:
        raise BadInput(f"invalid schedule expression: {expression!r} (expected e.g. in 10s, every 5m, at 14:00)")
    amount = float(match.group(1))
    unit = match.group(2) or "s"
    multipliers = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
    delay = amount * multipliers[unit]
    if delay <= 0:
        raise BadInput(f"delay must be positive, got {delay}")
    return delay, is_recurring


def spawn_trampoline(schedule_id: str, delay_seconds: float, jobctl_script: Path, settings: Settings) -> tuple[int, str]:
    """Spawn a detached /bin/sh trampoline that sleeps delay_seconds and then runs jobctl schedule-run."""
    cmd = (
        f"sleep {delay_seconds:.2f} && "
        f"exec {shlex.quote(sys.executable)} {shlex.quote(str(jobctl_script))} schedule-run {shlex.quote(schedule_id)}"
    )
    env = os.environ.copy()
    env["JOBCTL_HOME"] = str(settings.home)
    proc = subprocess.Popen(
        ["sh", "-c", cmd],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    time.sleep(0.05)
    started = process_started(proc.pid) or ""
    return proc.pid, started


def cancel_trampoline(pgid: int | None, leader_started: str | None) -> bool:
    """Safely cancel a waiting trampoline process group."""
    if pgid is None or not group_alive(pgid):
        return False
    current_leader = process_started(pgid)
    if current_leader and leader_started and current_leader != leader_started:
        return False
    try:
        os.killpg(pgid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False


def reconcile_schedules(store: RunStore, settings: Settings, jobctl_script: Path) -> None:
    """Check for dead or lost trampolines and recover recurring schedules."""
    now = time.time_ns()
    now_sec = now / 1e9
    for sched in store.select_schedules("enabled = 1"):
        pgid = sched.trampoline_pgid
        is_alive = False
        if pgid is not None and group_alive(pgid):
            leader = process_started(pgid)
            if not leader or not sched.trampoline_leader_started or leader == sched.trampoline_leader_started:
                is_alive = True

        if not is_alive:
            if sched.is_recurring:
                delay, _ = parse_schedule_expression(sched.expression)
                next_nano = int((now_sec + delay) * 1e9)
                new_pgid, new_started = spawn_trampoline(sched.schedule_id, delay, jobctl_script, settings)
                with store.edit_schedule(sched.schedule_id) as cur:
                    cur.trampoline_pgid = new_pgid
                    cur.trampoline_leader_started = new_started
                    cur.next_run_unix_nano = next_nano
            else:
                with store.edit_schedule(sched.schedule_id) as cur:
                    cur.enabled = False
                    cur.trampoline_pgid = None


def reconcile(store: RunStore, settings: Settings | None = None) -> None:
    """Mark running rows whose process group is gone (or was reused) as lost."""
    if settings:
        reconcile_schedules(store, settings, Path(__file__).resolve())
    now = time.time_ns()
    for run in store.select("state = ?", (RunState.RUNNING.value,)):
        if run.pgid is None and now - run.start_time_unix_nano < STARTING_GRACE_NANOS:
            continue
        if not group_is_ours(run):
            with store.edit(run.span_id) as current:
                if current.state is RunState.RUNNING:
                    current.add_event("job.lost")
                    current.finish(
                        RunState.LOST,
                        None,
                        "process group gone without a recorded exit (killed outside jobctl, or a reboot)",
                    )


def lsof_listeners() -> list[Listener]:
    """Listening TCP sockets from `lsof` (macOS, and Linux when /proc is not used)."""
    output = run_quietly(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpgcn"]) or ""
    listeners: list[Listener] = []
    pid, pgid, command = 0, None, ""
    for line in output.splitlines():
        field, value = line[:1], line[1:]
        match field:
            case "p":
                pid, pgid, command = int(value), None, ""
            case "g":
                pgid = int(value)
            case "c":
                command = value
            case "n":
                address, _, port = value.rpartition(":")
                if port.isdigit():
                    listeners.append(Listener(port=int(port), address=address, pid=pid, pgid=pgid, command=command))
    return listeners


def proc_listeners() -> list[Listener]:
    """Listening TCP sockets from /proc (Linux; needs no lsof). Other users' processes show only with root."""
    sockets: dict[str, tuple[str, int]] = {}
    for table in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        if not table.exists():
            continue
        for line in table.read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) > 9 and fields[3] == "0A":  # 0A = LISTEN
                address, _, port = fields[1].rpartition(":")
                if len(address) == 8:
                    address = ".".join(str(byte) for byte in reversed(bytes.fromhex(address)))
                else:
                    address = "::" if set(address) == {"0"} else "ipv6"
                sockets[fields[9]] = (address, int(port, 16))
    listeners: list[Listener] = []
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            inodes = {
                os.readlink(fd)[8:-1] for fd in (process / "fd").iterdir() if os.readlink(fd).startswith("socket:[")
            }
            pid = int(process.name)
            matches = [sockets[inode] for inode in inodes if inode in sockets]
            if matches:
                pgid, command = os.getpgid(pid), (process / "comm").read_text().strip()
                listeners.extend(
                    Listener(port=port, address=address, pid=pid, pgid=pgid, command=command)
                    for address, port in matches
                )
        except OSError:  # the process ended, or belongs to another user
            continue
    return listeners


async def listening_sockets() -> list[Listener]:
    """Every listening TCP socket on the machine that this user may see."""
    if sys.platform.startswith("linux") and Path("/proc/net/tcp").exists():
        return await asyncio.to_thread(proc_listeners)
    return await asyncio.to_thread(lsof_listeners)


def port_free(port: int) -> bool:
    """Whether a server could bind `port` on every interface right now."""
    for family, host in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                probe.bind((host, port))
        except OSError as error:
            if error.errno == errno.EADDRINUSE:
                return False
            if error.errno not in (errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL):
                raise
    return True


def holder_description(store: RunStore, listeners: list[Listener], port: int) -> str:
    """Who holds `port`: a jobctl job if one owns the socket's process group, else the process."""
    holders = [listener for listener in listeners if listener.port == port]
    if not holders:
        return "another user's process, or one this user cannot see"
    jobs = job_by_group(store)
    descriptions = []
    for holder in holders:
        run = jobs.get(holder.pgid) if holder.pgid is not None else None
        owner = f"job {run.job}" if run else f"{holder.command} (pid {holder.pid})"
        descriptions.append(f"{owner} on {holder.address}")
    return ", ".join(sorted(set(descriptions)))


def job_by_group(store: RunStore) -> dict[int, Run]:
    """Running jobs, plus finished jobs with leftover processes, by process group id."""
    week_ago = time.time_ns() - 7 * 86400 * 10**9
    runs = store.select("state = ? OR end_time_unix_nano > ?", (RunState.RUNNING.value, week_ago))
    return {run.pgid: run for run in reversed(runs) if run.pgid is not None and group_alive(run.pgid)}


def parse_process_target(text: str) -> ProcessTarget | None:
    """`:PORT` is a port and a bare number a PID; anything else is a job name (None).

    Raises:
        BadInput: a `:` target that is not a port from 1 to 65535.
    """
    if text.startswith(":"):
        if not text[1:].isdigit() or not 0 < int(text[1:]) < 65536:
            raise BadInput(f"{text!r}: a port target is ':' and a number from 1 to 65535, e.g. :3000")
        return ProcessTarget(port=int(text[1:]))
    if text.isdigit():
        return ProcessTarget(pid=int(text))
    return None


def process_table() -> dict[int, ProcessInfo]:
    """Every process this user may see, by PID (`ps` in the C locale, so start times read the same everywhere).

    Raises:
        JobctlError: `ps` cannot run.
    """
    try:
        result = subprocess.run(
            ["ps", "-A", "-ww", "-o", "pid=,ppid=,pgid=,stat=,user=,lstart=,command="],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env=os.environ | {"LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise JobctlError(f"cannot list processes with ps: {error}") from error
    table: dict[int, ProcessInfo] = {}
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=10)  # pid ppid pgid stat user, five lstart words, then the command
        if len(fields) < 10 or not fields[0].isdigit():
            continue
        table[int(fields[0])] = ProcessInfo(
            pid=int(fields[0]),
            ppid=int(fields[1]),
            pgid=int(fields[2]),
            stat=fields[3],
            user=fields[4],
            started=" ".join(fields[5:10]),
            command=fields[10] if len(fields) > 10 else "",
        )
    return table


def ancestors(table: dict[int, ProcessInfo], pid: int) -> list[ProcessInfo]:
    """The parents of `pid`, nearest first, up to PID 1."""
    chain: list[ProcessInfo] = []
    current = table.get(pid)
    while current is not None and current.pid > 1 and len(chain) < len(table):
        current = table.get(current.ppid)
        if current is not None:
            chain.append(current)
    return chain


def descendants(table: dict[int, ProcessInfo], roots: list[int]) -> list[ProcessInfo]:
    """The processes `roots` and all their children, parents before children."""
    children: dict[int, list[ProcessInfo]] = {}
    for process in table.values():
        if process.pid != process.ppid:
            children.setdefault(process.ppid, []).append(process)
    found: dict[int, ProcessInfo] = {}
    queue = [table[pid] for pid in roots if pid in table]
    while queue:
        process = queue.pop(0)
        if process.pid not in found:
            found[process.pid] = process
            queue.extend(children.get(process.pid, []))
    return list(found.values())


def own_lineage(table: dict[int, ProcessInfo]) -> set[int]:
    """This process and its ancestors: the shell, terminal or Claude Code session running jobctl. Never signalled."""
    return {os.getpid(), os.getppid(), *(process.pid for process in ancestors(table, os.getpid()))}


def process_cwds(pids: list[int]) -> dict[int, str]:
    """The working directory of each process this user may inspect (others are missing from the result)."""
    if not pids:
        return {}
    cwds: dict[int, str] = {}
    if Path("/proc/self/cwd").exists():
        for pid in pids:
            with contextlib.suppress(OSError):
                cwds[pid] = os.readlink(f"/proc/{pid}/cwd")
        return cwds
    output = run_quietly(["lsof", "-a", "-p", ",".join(map(str, pids)), "-d", "cwd", "-Fpn"], accept_failure=True)
    pid = 0
    for line in (output or "").splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid:
            cwds[pid] = line[1:]
    return cwds


def brief(command: str, width: int = 80) -> str:
    """A command line cut to `width` characters for error messages."""
    return command if len(command) <= width else command[: width - 1] + "…"


def sockets_by_pid(listeners: list[Listener]) -> dict[int, list[str]]:
    """`address:port` of every listening socket, by PID."""
    sockets: dict[int, set[str]] = {}
    for listener in listeners:
        sockets.setdefault(listener.pid, set()).add(f"{listener.address}:{listener.port}")
    return {pid: sorted(names) for pid, names in sockets.items()}


def port_holders(listeners: list[Listener], port: int) -> list[int]:
    """PIDs listening on `port`.

    Raises:
        ProcessNotFound: nothing listens on it.
        PermissionDenied: it is taken, but by a process this user cannot see.
    """
    pids = sorted({listener.pid for listener in listeners if listener.port == port})
    if pids:
        return pids
    try:
        free = port_free(port)
    except PermissionError:  # a privileged port cannot be test-bound without root
        raise ProcessNotFound(f"no process this user can see listens on port {port}") from None
    if free:
        raise ProcessNotFound(f"nothing listens on port {port}")
    raise PermissionDenied(f"port {port} is taken by a process this user cannot see (another user's; root can)")


def target_pids(table: dict[int, ProcessInfo], listeners: list[Listener], target: ProcessTarget) -> list[int]:
    """The PIDs a port or PID target names.

    Raises:
        ProcessNotFound: nothing listens on the port, or no such PID.
        PermissionDenied: the port's holder is invisible to this user.
    """
    if target.port is not None:
        return [pid for pid in port_holders(listeners, target.port) if pid in table]
    if target.pid is None or target.pid not in table:
        raise ProcessNotFound(f"no process {target.pid}")
    return [target.pid]


def process_report(
    process: ProcessInfo, cwd: str | None, sockets: list[str], run: Run | None, now: int
) -> dict[str, Any]:
    """The JSON-ready description of one process shared by `why` and `orphans`."""
    started = process.start_time_unix_nano
    return {
        "pid": process.pid,
        "ppid": process.ppid,
        "pgid": process.pgid,
        "user": process.user,
        "command": process.command,
        "cwd": cwd,
        "start_time_unix_nano": started,
        "started_at": iso(started) if started is not None else None,
        "age_seconds": round((now - started) / 1e9) if started is not None else None,
        "listening": sockets,
        "job": run.job if run else None,
        "job_state": state_label(run) if run else None,
    }


def explain(store: RunStore, target: ProcessTarget) -> list[dict[str, Any]]:
    """Who each process behind a port or PID is: command, directory, start, job, sockets, and the chain of parents
    that started it.

    Raises:
        ProcessNotFound: nothing listens on the port, or no such PID.
        PermissionDenied: the port's holder is invisible to this user.
    """
    table = process_table()
    listeners = asyncio.run(listening_sockets())
    pids = target_pids(table, listeners, target)
    jobs = job_by_group(store)
    sockets = sockets_by_pid(listeners)
    cwds = process_cwds(pids)
    now = time.time_ns()
    reports = []
    for pid in pids:
        process = table[pid]
        report = process_report(process, cwds.get(pid), sockets.get(pid, []), jobs.get(process.pgid), now)
        report["ancestors"] = [{"pid": parent.pid, "command": parent.command} for parent in ancestors(table, pid)]
        reports.append(report)
    return reports


def render_explanation(report: dict[str, Any], target: ProcessTarget) -> str:
    """One `why` report as labelled lines, ending with how to stop the process."""
    job = report["job"]
    started = report["start_time_unix_nano"]
    age = human_duration(report["age_seconds"]) if report["age_seconds"] is not None else "?"
    fields = [
        ("listens on", ", ".join(report["listening"]) or "-"),
        ("job", f"{job} ({report['job_state']})" if job else "none: not started by jobctl"),
        ("user", report["user"]),
        ("directory", report["cwd"] or "unknown"),
        ("started", f"{local_time(started)} ({age} ago)"),
        ("process group", str(report["pgid"])),
    ]
    for index, parent in enumerate(report["ancestors"]):
        fields.append(("started by" if index == 0 else "", f"{parent['pid']:<7} {parent['command']}"))
    stop_target = f":{target.port}" if target.port is not None else str(report["pid"])
    fields.append(("stop it", f"jobctl stop {job}" if job else f"jobctl stop {stop_target} --dry-run, then without"))
    return "\n".join([f"pid {report['pid']}  {report['command']}"] + [f"  {k:<14}{v}" for k, v in fields])


def is_adopted(table: dict[int, ProcessInfo], process: ProcessInfo) -> bool:
    """Whether the process's parent has exited: it was re-parented to PID 1 or to a `systemd --user` subreaper."""
    if process.ppid == 1:
        return True
    parent = table.get(process.ppid)
    return parent is not None and Path(parent.command.split(" ")[0]).name == "systemd" and "--user" in parent.command


def find_orphans(store: RunStore, scope: Path) -> list[dict[str, Any]]:
    """This user's processes working under `scope` whose parent has exited and that no job owns: servers and watchers
    left behind by `&`, a closed terminal, or an ended session. Each comes with its children count and the sockets its
    whole tree listens on.
    """
    table = process_table()
    jobs = job_by_group(store)
    lineage = own_lineage(table)
    users = {getpass.getuser(), str(os.getuid())}
    candidates = [
        process
        for process in table.values()
        if process.pid > 1
        and process.user in users
        and not process.is_zombie
        and process.pgid not in jobs
        and process.pid not in lineage
        and is_adopted(table, process)
    ]
    cwds = process_cwds([process.pid for process in candidates])
    sockets = sockets_by_pid(asyncio.run(listening_sockets()))
    now = time.time_ns()
    orphans = []
    for process in sorted(candidates, key=lambda candidate: candidate.pid):
        cwd = cwds.get(process.pid)
        if cwd is None or not Path(cwd).is_relative_to(scope):
            continue
        tree = descendants(table, [process.pid])
        report = process_report(
            process, cwd, sorted({name for member in tree for name in sockets.get(member.pid, [])}), None, now
        )
        report["children"] = len(tree) - 1
        orphans.append(report)
    return orphans


def orphan_row(report: dict[str, Any], scope: Path) -> dict[str, str]:
    """One orphan as display columns."""
    relative = Path(report["cwd"]).relative_to(scope)
    return {
        "pid": str(report["pid"]),
        "started": local_time(report["start_time_unix_nano"]),
        "age": human_duration(report["age_seconds"]) if report["age_seconds"] is not None else "",
        "listening": ",".join(report["listening"]),
        "children": str(report["children"]),
        "directory": str(relative),
        "command": report["command"],
    }


def job_plan(run: Run) -> StopPlan:
    """A stop of one job by name: its process group, no port check."""
    return StopPlan(label=run.name, ports=[], jobs=[run], roots=[], external=[])


def plan_stop(store: RunStore, target: ProcessTarget) -> StopPlan:
    """What stopping a port or PID signals. A port held by a job stops that job; processes jobctl did not start are
    stopped by PID together with all their children.

    Raises:
        ProcessNotFound: nothing listens on the port, or no such PID.
        PermissionDenied: a process belongs to another user, or the port's holder is invisible.
        RefusedTarget: a process runs this jobctl (or contains it), or the PID belongs to a job (stop the job).
    """
    table = process_table()
    listeners = asyncio.run(listening_sockets())
    holders = [table[pid] for pid in target_pids(table, listeners, target)]
    jobs = job_by_group(store)
    owning = {jobs[process.pgid].span_id: jobs[process.pgid] for process in holders if process.pgid in jobs}
    if target.pid is not None and owning:
        run = next(iter(owning.values()))
        raise RefusedTarget(f"pid {target.pid} belongs to job {run.job}; stop the whole job: jobctl stop {run.job}")
    foreign = [process for process in holders if process.pgid not in jobs]
    foreign_pids = {process.pid for process in foreign}
    roots = [process for process in foreign if process.ppid not in foreign_pids]
    external = [process for process in descendants(table, [root.pid for root in roots]) if process.pgid not in jobs]
    lineage = own_lineage(table)
    for process in external:
        if process.pid <= 1 or process.pid in lineage:
            raise RefusedTarget(
                f"pid {process.pid} ({brief(process.command)}) runs this jobctl (its shell, terminal or Claude Code "
                "session); not signalling it"
            )
        try:
            os.kill(process.pid, 0)
        except ProcessLookupError:
            continue
        except PermissionError as error:
            raise PermissionDenied(
                f"pid {process.pid} ({brief(process.command)}) belongs to {process.user}; this user cannot signal it"
            ) from error
    return StopPlan(
        label=target.label,
        ports=[target.port] if target.port is not None else [],
        jobs=list(owning.values()),
        roots=roots,
        external=external,
    )


def describe_plan(plan: StopPlan, grace: float) -> dict[str, Any]:
    """A dry run: every process a stop would signal, without signalling anything."""
    table = process_table()
    processes: list[dict[str, Any]] = []
    notes: list[str] = []
    for run in plan.jobs:
        if run.pgid is None or not group_is_ours(run):
            notes.append(f"job {run.job} is not running and left no processes; nothing to signal")
            continue
        members = sorted((p for p in table.values() if p.pgid == run.pgid and not p.is_zombie), key=lambda p: p.pid)
        processes.extend(
            {"pid": p.pid, "ppid": p.ppid, "owner": run.job, "started": p.started, "command": p.command}
            for p in members
        )
    processes.extend(
        {"pid": p.pid, "ppid": p.ppid, "owner": "not a job", "started": p.started, "command": p.command}
        for p in plan.external
    )
    return {
        "dry_run": True,
        "signal": "SIGTERM",
        "kill_after_seconds": grace,
        "jobs": [run.job for run in plan.jobs],
        "ports": plan.ports,
        "processes": processes,
        "notes": notes,
    }


def echo_plan(document: dict[str, Any], as_json: bool) -> None:
    """Print a dry run as one JSON document, or as a table with what would follow."""
    if as_json:
        click.echo(json.dumps(document))
        return
    processes = document["processes"]
    if processes:
        click.echo(
            f"dry run: would send SIGTERM, then SIGKILL after {document['kill_after_seconds']:g} s, "
            f"to {len(processes)} process(es):"
        )
        click.echo(render_table([{key: str(value) for key, value in row.items()} for row in processes]))
    for note in document["notes"]:
        click.echo(f"dry run: {note}")
    if document["ports"]:
        click.echo(f"then check that port(s) {', '.join(map(str, document['ports']))} are no longer listened on")
    if "then_start" in document:
        start_plan = document["then_start"]
        click.echo(f"then start in {start_plan['cwd']}: {shlex.join(start_plan['command'])}")


def resolve(store: RunStore, reference: str, project: str) -> Run:
    """The newest run for `project/name`, a bare name (current project first, then any single project) or a span id.

    Raises:
        JobNotFound: nothing matches, or a bare name exists in several other projects.
    """
    if "/" in reference:
        project_part, _, name = reference.partition("/")
        found = store.select("project = ? AND name = ?", (project_part, name), limit=1)
        if found:
            return found[0]
        raise JobNotFound(f"no job {reference!r}")
    found = store.select("project = ? AND name = ?", (project, reference), limit=1)
    if found:
        return found[0]
    others = store.latest("name = ?", (reference,))
    if len(others) == 1:
        return others[0]
    if others:
        names = ", ".join(run.job for run in others)
        raise JobNotFound(f"{reference!r} exists in several projects ({names}); give project/name")
    found = store.select("span_id LIKE ?", (f"{reference}%",), limit=2) if len(reference) >= 6 else []
    if len(found) == 1:
        return found[0]
    raise JobNotFound(f"no job named {reference!r} (project {project!r} or any other), and no such span id")


def start(
    store: RunStore,
    settings: Settings,
    name: str,
    project: str,
    command: list[str],
    cwd: Path,
    log: Path | None,
    ports: list[int],
    tags: dict[str, str],
) -> Run:
    """Record a new run and start `command` detached under a supervisor in a new process group.

    Raises:
        BadInput: no command, or a bad name.
        JobAlreadyRunning: the same project/name is running.
        PortBusy: a declared port is taken.
    """
    if not command:
        raise BadInput("give the command after --, e.g. start sleeper -- sleep 60")
    check_name("job name", name)
    check_name("project", project)
    reconcile(store)
    running = store.select("project = ? AND name = ? AND state = ?", (project, name, RunState.RUNNING.value))
    if running:
        raise JobAlreadyRunning(
            f"job {running[0].job} is already running (process group {running[0].pgid}); stop it first or use restart"
        )
    busy = [port for port in ports if not port_free(port)]
    if busy:
        listeners = asyncio.run(listening_sockets())
        detail = "; ".join(f"port {port} is held by {holder_description(store, listeners, port)}" for port in busy)
        raise PortBusy(detail)
    cwd = cwd.expanduser().resolve()
    tags = dict(tags)
    if settings.rex_session:
        tags["rex.origin_session"] = settings.rex_session
    if settings.rex_block:
        tags["rex.origin_block"] = settings.rex_block
    trace = parse_traceparent(settings.traceparent)
    span_id = secrets.token_hex(8)
    started = time.time_ns()
    stamp = datetime.datetime.fromtimestamp(started / 1e9, datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    log_path = (log.expanduser() if log else settings.logs / project / name / f"{stamp}-{span_id}.log").resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    git = git_info(cwd)
    script, script_sha256 = find_script(command, cwd)
    launched_by = "job" if trace.parent_span_id else launcher_name(settings)
    run = Run(
        span_id=span_id,
        trace_id=trace.trace_id,
        parent_span_id=trace.parent_span_id,
        name=name,
        project=project,
        start_time_unix_nano=started,
        started_at=iso(started),
        command=command,
        command_line=shlex.join(command),
        script=script,
        script_sha256=script_sha256,
        cwd=str(cwd),
        git_root=git.root,
        git_commit=git.commit,
        git_branch=git.branch,
        git_dirty=git.dirty,
        log_path=str(log_path),
        declared_ports=sorted(set(ports)),
        host_name=socket.gethostname(),
        user_name=getpass.getuser(),
        os_type=platform.system().lower(),
        launched_by=launched_by,
        tags=tags,
        updated_at=iso(started),
    )
    store.insert(run)
    with log_path.open("ab") as handle:
        header = f"# jobctl {run.job} span {span_id} started {run.started_at} in {cwd}\n# $ {run.command_line}\n"
        handle.write(header.encode())
        handle.flush()
        supervisor = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), Action.SUPERVISE.value, span_id],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            # Forward the already parsed state directory even for an isolated doctor probe.
            env=os.environ | {"JOBCTL_HOME": str(settings.home.expanduser().resolve())},
        )
    with store.edit(span_id) as current:
        current.pgid = supervisor.pid
        current.leader_started = process_started(supervisor.pid)
    return store.get(span_id)


async def watch_ports(store: RunStore, span_id: str, pgid: int) -> None:
    """Record every TCP port the job's process group listens on (sampled at 1, 2, 5, 10, 30 s, then every minute)."""
    seen: set[int] = set()
    for delay in itertools.chain(PORT_SAMPLE_DELAYS, itertools.repeat(PORT_SAMPLE_INTERVAL)):
        await asyncio.sleep(delay)
        ports = {listener.port for listener in await listening_sockets() if listener.pgid == pgid}
        if ports - seen:
            new = sorted(ports - seen)
            seen |= ports
            with store.edit(span_id) as run:
                run.ports = sorted(seen)
                run.add_event("port.listen", ports=new)


async def supervise(settings: Settings, span_id: str) -> int:
    """Run the job's command as a child in this process group, then record how it ended."""
    store = RunStore(settings.database)
    run = store.get(span_id)
    terminated = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, terminated.set)  # the child got the same group signal; wait for it
    loop.add_signal_handler(signal.SIGINT, terminated.set)
    environment = os.environ | {
        "TRACEPARENT": f"00-{run.trace_id}-{run.span_id}-01",
        "JOBCTL_JOB": run.job,
        "JOBCTL_SPAN_ID": run.span_id,
    }
    try:
        process = await asyncio.create_subprocess_exec(
            *run.command, cwd=run.cwd, stdin=subprocess.DEVNULL, env=environment
        )
    except OSError as error:
        click.echo(f"# jobctl: cannot start: {error}", err=True)
        with store.edit(span_id) as current:
            current.finish(RunState.FAILED, 127, f"cannot start: {error}")
        return 127
    with store.edit(span_id) as current:
        current.add_event("process.start", pid=process.pid)
    watcher = asyncio.create_task(watch_ports(store, span_id, os.getpgid(0)))
    check_task = None
    check_cmd = run.tags.get("jobctl.check")
    if check_cmd:
        check_interval = float(run.tags.get("jobctl.check_interval", "60.0"))
        check_fail_action = run.tags.get("jobctl.check_fail_action", "stop")

        async def watch_checks() -> None:
            while True:
                await asyncio.sleep(check_interval)
                try:
                    check_proc = await asyncio.create_subprocess_shell(
                        check_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                    check_code = await check_proc.wait()
                    if check_code != 0:
                        with store.edit(span_id) as cur:
                            cur.add_event("check.failed", exit_code=check_code, command=check_cmd)
                        if check_fail_action == "stop":
                            click.echo(f"# jobctl: health check failed (code {check_code}), stopping job", err=True)
                            os.killpg(os.getpgid(0), signal.SIGTERM)
                            break
                    else:
                        with store.edit(span_id) as cur:
                            cur.add_event("check.ok")
                except Exception as error:
                    with store.edit(span_id) as cur:
                        cur.add_event("check.error", error=str(error))

        check_task = asyncio.create_task(watch_checks())

    code = await process.wait()
    watcher.cancel()
    if check_task:
        check_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await watcher
        if check_task:
            await check_task
    exit_code = code if code >= 0 else 128 - code
    with store.edit(span_id) as current:
        if terminated.is_set():
            current.finish(RunState.STOPPED, exit_code, stop_message(current))
        elif code == 0:
            current.finish(RunState.SUCCEEDED, 0, None)
        elif code < 0:
            current.finish(RunState.FAILED, exit_code, f"killed by {signal.Signals(-code).name}")
        else:
            current.finish(RunState.FAILED, exit_code, f"exit code {code}")
    click.echo(f"# jobctl: {run.job} ended: {current.state.value}, exit code {exit_code}, at {current.ended_at}")
    on_exit_cmd = run.tags.get("jobctl.on_exit")
    if on_exit_cmd:
        env = os.environ | {
            "JOBCTL_JOB": run.job,
            "JOBCTL_STATE": current.state.value,
            "JOBCTL_EXIT_CODE": str(exit_code),
            "JOBCTL_LOG_PATH": run.log_path,
            "JOBCTL_DURATION": str(current.duration_seconds or 0),
        }
        try:
            res = subprocess.run(on_exit_cmd, shell=True, env=env, timeout=30, capture_output=True)
            with store.edit(span_id) as cur:
                cur.add_event("on_exit.dispatched", exit_code=res.returncode)
        except Exception as error:
            with store.edit(span_id) as cur:
                cur.add_event("on_exit.failed", error=str(error))
    store.close()
    return exit_code


def stop_message(run: Run) -> str:
    """`stopped` plus the reason given to the latest stop request."""
    requests = [event for event in run.events if event["name"] == "stop.requested"]
    reason = requests[-1]["attributes"].get("reason") if requests else None
    return f"stopped: {reason}" if reason else "stopped"


async def stop(store: RunStore, settings: Settings, run: Run, grace: float, reason: str) -> Run:
    """SIGTERM the run's process group, SIGKILL it after `grace` seconds, and record the stop.

    Also stops leftover workers of a finished run. Does nothing to a group that is gone.

    Raises:
        NotOurProcess: the group's leader is a different process than the one jobctl started (PID reused).
    """
    if run.pgid is None or not live_group(run.pgid):
        reconcile(store)
        return store.get(run.span_id)
    leader = process_started(run.pgid)
    if leader and leader != run.leader_started:
        raise NotOurProcess(f"process {run.pgid} is not job {run.job} any more (started {leader}); not signalling it")
    stopper = launcher_name(settings)
    with store.edit(run.span_id) as current:
        name = "stop.requested" if current.state is RunState.RUNNING else "stop.stragglers"
        current.add_event(name, reason=reason, by=stopper, by_user=getpass.getuser(), signal="SIGTERM")
    # A group may exit after inspection and before signalling (including a repeated stop).
    with contextlib.suppress(ProcessLookupError):
        os.killpg(run.pgid, signal.SIGTERM)
    waited = 0.0
    while live_group(run.pgid) and waited < grace:
        await asyncio.sleep(POLL_SECONDS)
        waited += POLL_SECONDS
    if live_group(run.pgid):
        with store.edit(run.span_id) as current:
            current.add_event("stop.escalated", signal="SIGKILL", after_seconds=grace)
        leader = process_started(run.pgid)
        if leader and leader != run.leader_started:
            raise NotOurProcess(f"process {run.pgid} changed identity before escalation; not signalling it")
        with contextlib.suppress(ProcessLookupError):
            os.killpg(run.pgid, signal.SIGKILL)
        while live_group(run.pgid):
            await asyncio.sleep(POLL_SECONDS)
    with store.edit(run.span_id) as current:
        if current.state is RunState.RUNNING:  # the supervisor was killed before it could record the end
            current.finish(RunState.STOPPED, 128 + signal.SIGKILL, stop_message(current))
    return store.get(run.span_id)


def launcher_name(settings: Settings) -> str:
    """Who runs this jobctl: the `JOBCTL_LAUNCHER` name an app sets, else `claude-code` inside Claude Code, else
    `terminal`.

    Raises:
        BadInput: JOBCTL_LAUNCHER is not a valid name.
    """
    if settings.launcher:
        check_name("JOBCTL_LAUNCHER", settings.launcher)
        return settings.launcher
    return "claude-code" if settings.claude_code else "terminal"


def live(targets: list[ProcessInfo]) -> list[ProcessInfo]:
    """Those of `targets` still alive as the same process: same PID and start time, and not a zombie."""
    table = process_table()
    return [
        target
        for target in targets
        if (current := table.get(target.pid)) is not None
        and current.started == target.started
        and not current.is_zombie
    ]


def signal_processes(targets: list[ProcessInfo], signal_number: signal.Signals) -> list[int]:
    """Signal each target that is still the same process (a reused PID is skipped); return the PIDs signalled.

    Raises:
        PermissionDenied: a target belongs to another user.
    """
    signalled = []
    for target in live(targets):
        try:
            os.kill(target.pid, signal_number)
        except ProcessLookupError:
            continue
        except PermissionError as error:
            raise PermissionDenied(
                f"cannot signal pid {target.pid} ({brief(target.command)}): another user's"
            ) from error
        signalled.append(target.pid)
    return signalled


async def stop_external(
    store: RunStore, settings: Settings, plan: StopPlan, project: str, grace: float, reason: str
) -> Run:
    """SIGTERM processes jobctl did not start (with their children), SIGKILL survivors after `grace` seconds, and
    record the stop as a `stopped` run named for the target (`port-3000`, `pid-4242`), with a log of what was signalled.

    Raises:
        PermissionDenied: a process belongs to another user.
    """
    started = time.time_ns()
    span_id = secrets.token_hex(8)
    trace = parse_traceparent(settings.traceparent)
    stamp = datetime.datetime.fromtimestamp(started / 1e9, datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    log_path = (settings.logs / project / plan.label / f"{stamp}-{span_id}.log").resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stopper = launcher_name(settings)
    commands = [root.command for root in plan.roots]
    run = Run(
        span_id=span_id,
        trace_id=trace.trace_id,
        parent_span_id=trace.parent_span_id,
        name=plan.label,
        project=project,
        start_time_unix_nano=started,
        started_at=iso(started),
        command=commands,
        command_line="; ".join(commands),
        cwd=process_cwds([plan.roots[0].pid]).get(plan.roots[0].pid, "") if plan.roots else "",
        log_path=str(log_path),
        declared_ports=plan.ports,
        ports=plan.ports,
        host_name=socket.gethostname(),
        user_name=getpass.getuser(),
        os_type=platform.system().lower(),
        launched_by=stopper,
        tags={"external": "true"},
        updated_at=iso(started),
    )
    lines = [f"# jobctl {run.job} span {span_id} at {run.started_at}: stop processes jobctl did not start"]
    lines.extend(f"# pid {p.pid} (parent {p.ppid}, started {p.started}): {p.command}" for p in plan.external)
    run.add_event(
        "stop.requested",
        reason=reason,
        by=stopper,
        by_user=getpass.getuser(),
        signal="SIGTERM",
        pids=[process.pid for process in plan.external],
    )
    lines.append(f"SIGTERM to {signal_processes(plan.external, signal.SIGTERM)}")
    waited = 0.0
    survivors = live(plan.external)
    while survivors and waited < grace:
        await asyncio.sleep(POLL_SECONDS)
        waited += POLL_SECONDS
        survivors = live(plan.external)
    if survivors:
        run.add_event(
            "stop.escalated", signal="SIGKILL", after_seconds=grace, pids=[process.pid for process in survivors]
        )
        lines.append(f"SIGKILL after {grace:g} s to {signal_processes(survivors, signal.SIGKILL)}")
        for _ in range(20):
            if not live(survivors):
                break
            await asyncio.sleep(POLL_SECONDS)
    remaining = live(plan.external)
    message = f"stopped {len(plan.external) - len(remaining)} process(es) jobctl did not start"
    message += f": {reason}" if reason else ""
    message += f"; still alive: {[process.pid for process in remaining]}" if remaining else ""
    run.finish(RunState.STOPPED, None, message)
    lines.append(f"# {message}")
    log_path.write_text("\n".join(lines) + "\n")
    store.insert(run)
    return run


async def wait_port_released(port: int, timeout: float) -> bool:
    """Whether, within `timeout` seconds, no visible process listens on `port` any more."""
    deadline = time.monotonic() + timeout
    while any(listener.port == port for listener in await listening_sockets()):
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(POLL_SECONDS)
    return True


async def execute_stop(
    store: RunStore, settings: Settings, plan: StopPlan, project: str, grace: float, reason: str
) -> list[Run]:
    """Stop the plan's jobs and other processes, then check that its ports are no longer listened on.

    Raises:
        NotOurProcess: a job's process group was reused.
        PermissionDenied: a process belongs to another user.
        PortStillBusy: a port is still listened on afterwards.
    """
    runs = [await stop(store, settings, run, grace, reason) for run in plan.jobs]
    if plan.external:
        runs.append(await stop_external(store, settings, plan, project, grace, reason))
    for port in plan.ports:
        if not await wait_port_released(port, 10.0):
            holders = holder_description(store, await listening_sockets(), port)
            raise PortStillBusy(f"port {port} is still held by {holders} after the stop")
    return runs


async def wait_until_ready(store: RunStore, run: Run, timeout: float) -> Run:
    """Block until the job listens on all its declared ports.

    Raises:
        JobNotReady: the job ended first, or the ports are not listening after `timeout` seconds.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = store.get(run.span_id)
        if current.state is not RunState.RUNNING:
            raise JobNotReady(
                f"job {run.job} ended ({current.state.value}, {current.status_message}) before "
                f"listening on {current.declared_ports}:\n{tail(Path(current.log_path), 20)}"
            )
        owned = {listener.port for listener in await listening_sockets() if listener.pgid == run.pgid}
        if set(current.declared_ports) <= owned:
            return current
        await asyncio.sleep(POLL_SECONDS)
    raise JobNotReady(
        f"job {run.job} is running but not listening on {run.declared_ports} after {timeout:g} s; "
        f"check `logs {run.job}`"
    )


async def wait(store: RunStore, run: Run) -> Run:
    """Block until the run is no longer running; return its final row."""
    while True:
        reconcile(store)
        current = store.get(run.span_id)
        if current.state is not RunState.RUNNING:
            return current
        await asyncio.sleep(2)


def tail(path: Path, lines: int) -> str:
    """The last `lines` lines of a text file."""
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - 400 * lines - 4096))
        return "\n".join(handle.read().decode(errors="replace").splitlines()[-lines:])


async def follow_log(store: RunStore, run: Run, lines: int) -> None:
    """Print the log's end, then new output until the run ends."""
    path = Path(run.log_path)
    click.echo(tail(path, lines))
    position = path.stat().st_size if path.exists() else 0
    while True:
        reconcile(store)
        running = store.get(run.span_id).state is RunState.RUNNING
        if path.exists() and path.stat().st_size > position:
            with path.open("rb") as handle:
                handle.seek(position)
                chunk = handle.read()
                position += len(chunk)
            click.echo(chunk.decode(errors="replace"), nl=False)
        if not running:
            return
        await asyncio.sleep(1)


def state_label(run: Run) -> str:
    """State, with a warning when a finished run left processes behind."""
    if run.state is RunState.RUNNING:
        return "running"
    return f"{run.state.value}+left" if has_stragglers(run) else run.state.value


def summary_row(run: Run) -> dict[str, str]:
    """One run as display columns."""
    seconds = (
        run.duration_seconds
        if run.duration_seconds is not None
        else ((time.time_ns() - run.start_time_unix_nano) / 1e9)
    )
    ports = run.ports or run.declared_ports
    return {
        "job": run.job,
        "state": state_label(run),
        "code": "" if run.exit_code is None else str(run.exit_code),
        "ports": ",".join(map(str, ports)),
        "started": local_time(run.start_time_unix_nano),
        "duration": human_duration(seconds),
        "span": run.span_id,
        "command": run.command_line,
    }


def render_table(rows: list[dict[str, str]], width: int = 70) -> str:
    """Rows as aligned text columns; the last column is cut to `width` characters."""
    if not rows:
        return ""
    columns = list(rows[0])
    cells = [[str(row[column]) for column in columns] for row in rows]
    for cell in cells:
        if len(cell[-1]) > width:
            cell[-1] = cell[-1][: width - 1] + "…"
    widths = [max(len(column), *(len(cell[index]) for cell in cells)) for index, column in enumerate(columns)]
    lines = ["  ".join(column.upper().ljust(widths[index]) for index, column in enumerate(columns)).rstrip()]
    lines.extend(
        "  ".join(cell[index].ljust(widths[index]) for index in range(len(columns))).rstrip() for cell in cells
    )
    return "\n".join(lines)


def otlp_value(value: Any) -> dict[str, Any]:
    """An OTLP/JSON AnyValue."""
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, list):
        return {"arrayValue": {"values": [otlp_value(item) for item in value]}}
    return {"stringValue": str(value)}


def otlp_attributes(values: dict[str, Any]) -> list[dict[str, Any]]:
    """OTLP/JSON KeyValue list, skipping missing values."""
    return [{"key": key, "value": otlp_value(value)} for key, value in values.items() if value is not None]


def otlp_span(run: Run) -> dict[str, Any]:
    """One run as an OTLP/JSON span (semantic-convention names where one exists)."""
    attributes = {
        "job.name": run.name,
        "job.state": run.state.value,
        "job.script": run.script,
        "job.script.sha256": run.script_sha256,
        "job.log": run.log_path,
        "job.launched_by": run.launched_by,
        "job.ports": run.ports,
        "job.declared_ports": run.declared_ports,
        "job.git.dirty": run.git_dirty,
        "process.command_args": run.command,
        "process.command_line": run.command_line,
        "process.working_directory": run.cwd,
        "process.pid": run.pgid,
        "process.exit.code": run.exit_code,
        "vcs.repository.path": run.git_root,
        "vcs.ref.head.revision": run.git_commit,
        "vcs.ref.head.name": run.git_branch,
    } | {f"job.tag.{key}": value for key, value in run.tags.items()}
    span: dict[str, Any] = {
        "traceId": run.trace_id,
        "spanId": run.span_id,
        "name": run.name,
        "kind": 1,
        "startTimeUnixNano": str(run.start_time_unix_nano),
        "attributes": otlp_attributes(attributes),
        "events": [
            {
                "timeUnixNano": str(event["time_unix_nano"]),
                "name": event["name"],
                "attributes": otlp_attributes(event["attributes"]),
            }
            for event in run.events
        ],
        "status": {"code": OTLP_STATUS[run.status_code], "message": run.status_message or ""},
    }
    if run.parent_span_id:
        span["parentSpanId"] = run.parent_span_id
    if run.end_time_unix_nano is not None:
        span["endTimeUnixNano"] = str(run.end_time_unix_nano)
    return span


def to_otlp(runs: list[Run]) -> dict[str, Any]:
    """An OTLP/JSON ExportTraceServiceRequest, one resource per project, host and user."""
    resources: dict[tuple[str, str, str, str], list[Run]] = {}
    for run in runs:
        resources.setdefault((run.project, run.host_name, run.user_name, run.os_type), []).append(run)
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": otlp_attributes(
                        {"service.name": project, "host.name": host, "user.name": user, "os.type": os_type}
                    )
                },
                "scopeSpans": [
                    {"scope": {"name": "jobctl", "version": "1"}, "spans": [otlp_span(run) for run in reversed(group)]}
                ],
            }
            for (project, host, user, os_type), group in resources.items()
        ]
    }


def history_filter(
    project: str | None,
    name: str,
    state: str | None,
    since: str | None,
    grep: str | None,
    port: int | None,
) -> tuple[str, tuple[Any, ...]]:
    """A SQL condition and its bound parameters for the history/export filters."""
    conditions: list[str] = []
    parameters: list[Any] = []
    if project:
        conditions.append("project = ?")
        parameters.append(project)
    if name:
        if "/" in name:
            project_part, _, name = name.partition("/")
            conditions.append("project = ?")
            parameters.append(project_part)
        conditions.append("name = ?")
        parameters.append(name)
    if state:
        conditions.append("state = ?")
        parameters.append(state)
    if since:
        conditions.append("start_time_unix_nano >= ?")
        parameters.append(parse_since(since))
    if grep:
        conditions.append("(command_line LIKE ? OR name LIKE ? OR project LIKE ? OR cwd LIKE ?)")
        parameters.extend([f"%{grep}%"] * 4)
    if port is not None:
        conditions.append("""(EXISTS (SELECT 1 FROM json_each(runs.ports) WHERE value = ?)
                              OR EXISTS (SELECT 1 FROM json_each(runs.declared_ports) WHERE value = ?))""")
        parameters.extend([port, port])
    return " AND ".join(conditions) or "1", tuple(parameters)


@dataclass(frozen=True)
class PruneCandidate:
    """One finished run that `prune` would clean up."""

    span_id: str
    job: str
    state: str
    ended: str
    log: Path | None  # the log file to delete; None when it is gone or lives outside the jobctl logs directory
    log_bytes: int
    delete_row: bool


def format_bytes(count: int) -> str:
    """Human-readable size, e.g. `3.2 MB`."""
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def prune_candidates(
    store: RunStore,
    settings: Settings,
    project: str | None,
    name: str,
    grep: str | None,
    older_than: str,
    keep_failed: bool,
    rows: bool,
) -> list[PruneCandidate]:
    """Finished runs older than the cutoff, with the log file each would lose.

    Only files under the jobctl logs directory are ever deleted: a run started with `--log` elsewhere keeps its file.
    With `rows`, every old run is a candidate except the newest run of each job, which `restart` needs.
    """
    condition, parameters = history_filter(project, name, None, None, grep, None)
    cutoff = parse_since(older_than)
    condition += " AND state != ? AND COALESCE(end_time_unix_nano, start_time_unix_nano) < ?"
    parameters = (*parameters, RunState.RUNNING.value, cutoff)
    if keep_failed:
        condition += " AND state NOT IN (?, ?)"
        parameters = (*parameters, RunState.FAILED.value, RunState.LOST.value)
    newest = {(run.project, run.name): run.span_id for run in store.latest()}
    logs_root = settings.logs.resolve()
    candidates: list[PruneCandidate] = []
    for run in store.select(condition, parameters):
        if rows and newest.get((run.project, run.name)) == run.span_id:
            continue
        path = Path(run.log_path).resolve()
        deletable = path.is_file() and path.is_relative_to(logs_root)
        if not deletable and not rows:
            continue
        candidates.append(
            PruneCandidate(
                span_id=run.span_id,
                job=run.job,
                state=run.state.value,
                ended=run.ended_at or run.started_at,
                log=path if deletable else None,
                log_bytes=path.stat().st_size if deletable else 0,
                delete_row=rows,
            )
        )
    return candidates


def prune(store: RunStore, settings: Settings, candidates: list[PruneCandidate]) -> None:
    """Delete the candidates' logs; then either record that on each row or, with `rows`, delete the rows and VACUUM."""
    for candidate in candidates:
        if candidate.log is not None:
            candidate.log.unlink(missing_ok=True)
        if candidate.delete_row:
            store.connection.execute("DELETE FROM runs WHERE span_id = ?", (candidate.span_id,))
        elif candidate.log is not None:
            with store.edit(candidate.span_id) as run:
                run.add_event("log_pruned", path=str(candidate.log), bytes=candidate.log_bytes)
    logs_root = settings.logs.resolve()
    for directory in sorted((path for path in logs_root.rglob("*") if path.is_dir()), reverse=True):
        with contextlib.suppress(OSError):  # not empty: leave it
            directory.rmdir()
    if any(candidate.delete_row for candidate in candidates):
        store.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        store.connection.execute("VACUUM")


def parse_tags(tags: tuple[str, ...]) -> dict[str, str]:
    """`key=value` pairs.

    Raises:
        BadInput: a tag without `=`.
    """
    parsed: dict[str, str] = {}
    for tag in tags:
        key, separator, value = tag.partition("=")
        if not separator or not key:
            raise BadInput(f"--tag {tag!r}: use key=value")
        parsed[key] = value
    return parsed


def echo_runs(runs: list[Run], as_json: bool, empty: str) -> None:
    """Print runs as a table, or as JSON lines of full rows."""
    if as_json:
        for run in runs:
            click.echo(run.model_dump_json())
    elif runs:
        click.echo(render_table([summary_row(run) for run in runs]))
    else:
        click.echo(empty)


def show(run: Run) -> str:
    """Every column of a run, then its events."""
    lines = [f"{key:<22} {value}" for key, value in run.model_dump(mode="json", exclude={"events"}).items()]
    lines.append("events:")
    lines.extend(
        f"  {local_time(event['time_unix_nano'])}  {event['name']}  {json.dumps(event['attributes'])}"
        for event in run.events
    )
    if has_stragglers(run):
        lines.append(f"warning: processes of group {run.pgid} are still alive; `stop {run.job}` ends them")
    return "\n".join(lines)


def read_only_query(database: Path, query: str) -> list[dict[str, Any]]:
    """Run SQL on a read-only connection (writes fail in SQLite itself, not in a filter)."""
    if not database.exists():
        return []
    with contextlib.closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in connection.execute(query)]
        except sqlite3.Error as error:
            raise BadInput(f"SQL error: {error}") from error


def describe_schema(store: RunStore, database: Path) -> dict[str, Any]:
    """The `runs` table as stored (column names and SQLite types) with each column's meaning, the state values, the
    event names, and example queries."""
    columns = []
    for row in store.connection.execute("PRAGMA table_info(runs)"):
        field = Run.model_fields.get(row["name"])
        extra = field.json_schema_extra if field is not None and isinstance(field.json_schema_extra, dict) else {}
        columns.append(
            {
                "name": row["name"],
                "type": row["type"],
                "json": row["name"] in JSON_COLUMNS,
                "description": field.description if field is not None and field.description else "",
                "otel": str(extra.get("otel", "")),
            }
        )
    return {
        "table": "runs",
        "database": str(database),
        "row": "one run = one OpenTelemetry span",
        "columns": columns,
        "states": {state.value: meaning for state, meaning in RUN_STATE_MEANINGS.items()},
        "events": EVENT_MEANINGS,
        "examples": list(SQL_EXAMPLES),
    }


def render_schema(schema: dict[str, Any]) -> str:
    """The schema as text: columns, states, events, and runnable examples."""
    rows = [
        {
            "column": column["name"],
            "type": column["type"] + (" (JSON)" if column["json"] else ""),
            "otel": column["otel"],
            "meaning": column["description"],
        }
        for column in schema["columns"]
    ]
    lines = [
        f"table {schema['table']}: {schema['row']}; database {schema['database']}",
        'query it read-only with: jobctl sql "SELECT ..." [--json]',
        "",
        render_table(rows, width=110),
        "",
        "JSON columns hold JSON text: read them with json_extract(column, '$.key') or json_each(column).",
        "",
        "state:",
        *(f"  {state:<10} {meaning}" for state, meaning in schema["states"].items()),
        "",
        "events (in the events column, oldest first):",
        *(f"  {name:<16} {meaning}" for name, meaning in schema["events"].items()),
        "",
        "examples:",
        *(f"  jobctl sql {shlex.quote(query)}" for query in schema["examples"]),
    ]
    return "\n".join(lines)


Reply = TypeVar("Reply", bound=BaseModel)


def rex_executable(settings: Settings) -> Path:
    """Find Rex without changing PATH or depending on a particular version directory."""
    if settings.rex_executable is not None:
        candidates = [settings.rex_executable.expanduser()]
    else:
        on_path = shutil.which("rex")
        candidates = ([Path(on_path)] if on_path else []) + [
            Path.home()
            / "Library/Application Support/com.superlogical.rex/RexServer/Versions/Current"
            / "Rex Server.app/Contents/MacOS/rex",
            Path("/Applications/Rex.app/Contents/MacOS/rex"),
            Path.home() / "Applications/Rex.app/Contents/MacOS/rex",
        ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise RexError(
        RexIssue.UNAVAILABLE, "Rex CLI not found. Install Rex, then run jobctl setup; headless jobs still work."
    )


class RexClient:
    """Bounded CLI requests using argv and typed JSON, with no shell or screen parsing."""

    def __init__(self, settings: Settings) -> None:
        self.executable = rex_executable(settings)
        self.endpoint = settings.rex_server

    async def text(self, arguments: list[str]) -> str:
        """Execute a request without autostart; timeouts may have uncertain mutation outcomes."""
        argv = [str(self.executable), "--autostart=false", "--timeout", "5s"]
        if self.endpoint:
            argv.extend(["--server", self.endpoint])
        try:
            process = await asyncio.create_subprocess_exec(
                *argv, *arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        except OSError as error:
            raise RexError(RexIssue.UNAVAILABLE, f"Cannot execute Rex: {error}") from error
        try:
            async with asyncio.timeout(12):
                stdout, stderr = await process.communicate()
        except (TimeoutError, asyncio.CancelledError) as error:
            if process.returncode is None:
                process.kill()  # Reap only this owned CLI request, never a server or job.
            await process.wait()
            if isinstance(error, asyncio.CancelledError):
                raise
            raise RexError(
                RexIssue.UNCERTAIN, "Rex request timed out; inspect existing views before retrying."
            ) from error
        if process.returncode != 0:
            raise RexError(
                RexIssue.REQUEST,
                f"Rex exited {process.returncode}: {stderr.decode(errors='replace').strip()}",
                process.returncode,
            )
        return stdout.decode(errors="replace")

    async def model(self, arguments: list[str], reply: type[Reply]) -> Reply:
        """Parse the documented reply at the process boundary."""
        raw = await self.text(arguments)
        try:
            return reply.model_validate_json(raw)
        except ValidationError as error:
            raise RexError(
                RexIssue.RESPONSE, f"Unexpected Rex response for {arguments[0]}; run jobctl doctor."
            ) from error

    async def identity(self) -> RexIdentity:
        """Refuse to execute local paths on a remote or another account's Rex server."""
        identity = await self.model(["whoami", "--json"], RexIdentity)
        if urlsplit(identity.endpoint).scheme != "unix" or identity.account != getpass.getuser():
            raise RexError(
                RexIssue.REMOTE,
                "This jobctl database is local. Run jobctl on the remote host to open that host's jobs.",
            )
        self.endpoint = identity.endpoint
        return identity


def presentation_config(settings: Settings) -> PresentationConfig:
    """An invalid preferences file is diagnosed, never silently replaced."""
    try:
        return PresentationConfig.model_validate_json(settings.presentation.read_bytes())
    except FileNotFoundError:
        return PresentationConfig()
    except (OSError, ValidationError) as error:
        raise JobctlError(f"Cannot read {settings.presentation}: {error}") from error


def skill_state(path: Path, document: SkillDocument) -> SkillState:
    """Recognize exact shipped content; never infer ownership from prose or a partial marker."""
    if path.is_symlink():
        return SkillState.CONFLICT
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return SkillState.MISSING
    if content == document.content.encode("utf-8"):
        return SkillState.CURRENT
    if hashlib.sha256(content).hexdigest() in document.legacy_sha256:
        return SkillState.OUTDATED
    return SkillState.CONFLICT


def skill_report_state(files: tuple[SkillFileReport, ...]) -> SkillState:
    """A partial installation needs updating; unknown content is always a conflict."""
    states = {file.state for file in files}
    if SkillState.CONFLICT in states:
        return SkillState.CONFLICT
    if states == {SkillState.CURRENT}:
        return SkillState.CURRENT
    if states == {SkillState.MISSING}:
        return SkillState.MISSING
    return SkillState.OUTDATED


def inspect_skill(directory: Path, action: SkillAction, dry_run: bool) -> SkillReport:
    """Read every owned asset without creating files or following file-level links."""
    directory = directory.expanduser().absolute()
    files = tuple(
        SkillFileReport(path=directory / document.path, state=skill_state(directory / document.path, document))
        for document in SKILL_DOCUMENTS
    )
    return SkillReport(
        action=action, path=directory / "SKILL.md", state=skill_report_state(files), dry_run=dry_run, files=files
    )


def skill_installation(directory: Path, action: SkillAction, dry_run: bool = False, force: bool = False) -> SkillReport:
    """Manage owned assets, preserving bundled scripts, unrelated files and directory links."""
    report = inspect_skill(directory, action, dry_run)
    if action is SkillAction.STATUS:
        return report
    if report.state is SkillState.CONFLICT and not force:
        raise JobctlError(f"Refusing unrecognized skill assets in {directory}. Use --force to proceed.")
    for document, file in zip(SKILL_DOCUMENTS, report.files, strict=True):
        if action is SkillAction.SETUP:
            if file.state is SkillState.CURRENT:
                continue
            file.changed = True
            if not dry_run:
                file.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = file.path.with_name(f".jobctl-skill-{secrets.token_hex(8)}.tmp")
                try:
                    with temporary.open("x", encoding="utf-8") as handle:
                        handle.write(document.content)
                    temporary.replace(file.path)
                finally:
                    temporary.unlink(missing_ok=True)
                file.state = SkillState.CURRENT
        elif action is SkillAction.REMOVE and file.state is not SkillState.MISSING:
            file.changed = True
            if not dry_run:
                file.path.unlink()
                file.state = SkillState.MISSING
    report.changed = any(file.changed for file in report.files)
    report.state = skill_report_state(report.files)
    return report


def emit_skill(report: SkillReport, as_json: bool) -> None:
    """Describe actual or proposed changes without hiding the destination."""
    if as_json:
        click.echo(report.model_dump_json())
    else:
        change = "would change" if report.dry_run and report.changed else "changed" if report.changed else "unchanged"
        click.echo(f"{report.state.value}: {report.path} ({report.action.value}; {change})")


def skill_directories(settings: Settings) -> tuple[Path, ...]:
    """Select both standard destinations by default, writing shared agent directories once."""
    if settings.skill_dir is not None:
        return (settings.skill_dir.expanduser().absolute(),)
    home = settings.agent_home.expanduser().absolute()
    directories = (
        home / (".claude" if agent is SkillAgent.CLAUDE else ".agents") / "skills" / "jobs"
        for agent in settings.skill_agents
    )
    return tuple(dict.fromkeys(directories))


def skill_installations(
    settings: Settings, action: SkillAction, dry_run: bool = False, force: bool = False
) -> tuple[SkillReport, ...]:
    """Preflight all destinations before writes; retain existing directory links and agent-owned files."""
    directories = skill_directories(settings)
    if action is not SkillAction.STATUS and not force:
        conflicts = tuple(
            file.path
            for directory in directories
            for file in inspect_skill(directory, action, dry_run).files
            if file.state is SkillState.CONFLICT
        )
        if conflicts:
            paths = ", ".join(str(path) for path in conflicts)
            raise JobctlError(f"Refusing unrecognized skills: {paths}. Use skill {action.value} --force to proceed.")
    return tuple(skill_installation(directory, action, dry_run, force) for directory in directories)


def skill_command(
    name: str, command: tuple[str, ...], settings: Settings, dry_run: bool, force: bool, as_json: bool
) -> None:
    """Print the embedded guide or manage its small agent-facing entrypoint without opening state."""
    try:
        action = SkillAction(name or SkillAction.SHOW)
    except ValueError as error:
        raise BadInput("skill expects show, setup, status or remove.") from error
    if command:
        raise BadInput("skill expects one subcommand. Use --skill-dir DIR to select its destination.")
    try:
        if action is SkillAction.SHOW:
            click.echo(json.dumps({"guide": SKILL_GUIDE}) if as_json else SKILL_GUIDE, nl=as_json)
        else:
            for report in skill_installations(settings, action, dry_run, force):
                emit_skill(report, as_json)
    except OSError as error:
        raise JobctlError(f"Cannot {action.value} skill: {error}") from error


def setup_presentation(settings: Settings, layout: ViewLayout | None, bin_dir: Path | None) -> list[str]:
    """Idempotently initialize jobctl and its link; never edit Rex or replace unrelated executables."""
    preferences = presentation_config(settings)
    preferences = preferences.model_copy(
        update={
            "layout": layout or preferences.layout,
            "bin_dir": (bin_dir or preferences.bin_dir).expanduser().absolute(),
        }
    )
    changes: list[str] = []
    store = RunStore(settings.database)
    store.close()
    preferences.bin_dir.mkdir(parents=True, exist_ok=True)
    link = preferences.bin_dir / "jobctl"
    source = Path(__file__).resolve()
    if not os.access(source, os.X_OK):
        source.chmod(source.stat().st_mode | 0o100)
        changes.append(f"Made {source} executable")
    if link.is_symlink() and link.resolve() == source:
        pass
    elif link.exists() or link.is_symlink():
        raise JobctlError(f"Refusing to replace {link}; it is not this jobctl installation.")
    else:
        link.symlink_to(source)
        changes.append(f"Linked {link} to {source}")
    encoded = preferences.model_dump_json(indent=2) + "\n"
    if not settings.presentation.exists() or settings.presentation.read_text() != encoded:
        temporary = settings.presentation.with_name(f"presentation-{secrets.token_hex(8)}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                os.chmod(temporary, 0o600)
                handle.write(encoded)
            temporary.replace(settings.presentation)
        finally:
            temporary.unlink(missing_ok=True)
        changes.append(f"Saved {settings.presentation}")
    for skill in skill_installations(settings, SkillAction.SETUP):
        if skill.changed:
            changes.append(f"Installed skill {skill.path}; full guide: jobctl skill show")
    return changes


@contextlib.asynccontextmanager
async def view_lock(settings: Settings) -> AsyncGenerator[None]:
    """Serialize create/reuse decisions across CLI processes, without holding SQLite writes."""
    with (settings.home.expanduser() / "views.lock").open("a") as handle:
        deadline = time.monotonic() + 20
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RexError(
                        RexIssue.NOT_READY, "Another jobctl is opening a viewer; try again shortly."
                    ) from None
                await asyncio.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def view_target(store: RunStore, reference: str, project: str, pin: bool) -> JobViewTarget | RunViewTarget:
    """Resolve through the existing typed run boundary; span references pin automatically."""
    run = resolve(store, reference, project)
    if pin or reference not in {run.job, run.name}:
        return RunViewTarget(span_id=run.span_id)
    return JobViewTarget(project=run.project, name=run.name)


def target_run(store: RunStore, target: JobViewTarget | RunViewTarget) -> Run:
    """Select the exact span or the newest run of a role."""
    match target:
        case JobViewTarget():
            return resolve(store, f"{target.project}/{target.name}", target.project)
        case RunViewTarget():
            return store.get(target.span_id)


def target_title(store: RunStore, target: ViewTarget) -> str:
    """A readable label is kept separate from opaque IDs."""
    if isinstance(target, DashboardTarget):
        return f"Jobs {target.project or 'all projects'}"
    return target_run(store, target).job


async def view_block(client: RexClient, record: ViewRecord) -> RexBlock | None:
    """Find a created pane by its returned ID or exact recorded creation label."""
    blocks = await client.model(["block", "ls", "-s", record.session_id, "--json"], RexBlocks)
    for block in blocks.blocks or []:
        if block.block_id == record.block_id or block.label == record.label:
            if block.host_id != record.host_id:
                raise RexError(RexIssue.REMOTE, "Recorded viewer belongs to a different Rex host.")
            return block
    return None


def viewer_command(settings: Settings, target: ViewTarget, key: str, token: str) -> list[str]:
    """Re-execute the interpreter selected by uv, as the existing supervisor does."""
    arguments = [
        "/usr/bin/env",
        f"JOBCTL_HOME={settings.home.expanduser().resolve()}",
        sys.executable,
        str(Path(__file__).resolve()),
    ]
    match target:
        case JobViewTarget():
            arguments.extend(["view", f"{target.project}/{target.name}"])
        case RunViewTarget():
            arguments.extend(["view", target.span_id])
        case DashboardTarget():
            arguments.append("dashboard")
            if target.project:
                arguments.extend(["--project", target.project])
    arguments.extend(["--view-id", key, "--view-token", token])
    return arguments


async def rendered_view(store: RunStore, key: str, revision: int) -> ViewRecord:
    """An existing pane must render the requested target before open reports it reused."""
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        record = store.view(key)
        if record and record.state is ViewState.READY and record.rendered_revision >= revision:
            return record
        if record and record.state is ViewState.CLOSED:
            break
        await asyncio.sleep(0.1)
    raise RexError(RexIssue.NOT_READY, "Viewer did not render the requested view; run jobctl doctor.")


async def open_view(
    store: RunStore,
    settings: Settings,
    target: ViewTarget,
    layout: ViewLayout | None = None,
    session: str | None = None,
    new: bool = False,
    focus: bool = False,
) -> PresentationResult:
    """Reuse a live viewer, or create one with a persistent intent and readiness handshake."""
    client = RexClient(settings)
    identity = await client.identity()
    session_id = session or identity.session_id
    if not session_id:
        raise RexError(RexIssue.CONTEXT, "No live Rex session. Run here in Rex or pass --session SESSION.")
    selected = await client.model(["session", "inspect", session_id, "--json"], RexSession)
    session_id = selected.session_id
    selected_layout = layout or presentation_config(settings).layout
    anchor = identity.block_id if session_id == identity.session_id else None
    if selected_layout is not ViewLayout.TAB:
        if not anchor:
            raise RexError(RexIssue.CONTEXT, "No live split anchor in that session; use --layout tab.")
        inspected = await client.model(["block", "inspect", anchor, "-s", session_id, "--json"], RexInspection)
        if inspected.block.host_id != identity.host_id:
            raise RexError(RexIssue.REMOTE, "The split anchor runs on another Rex host.")
    key = hashlib.sha256(
        json.dumps(
            [identity.host_id, identity.endpoint, session_id, target.model_dump(mode="json")], sort_keys=True
        ).encode()
    ).hexdigest()
    async with view_lock(settings):
        existing = store.view(key)
        if existing and not new:
            block = await view_block(client, existing)
            if block:
                process = await client.model(
                    ["block", "call", "-s", session_id, "-b", block.block_id, "process"], RexProcess
                )
                if process.last_exit is None:
                    if not existing.ready_at:
                        raise RexError(RexIssue.NOT_READY, "Viewer exists but has not rendered; run jobctl doctor.")
                    with store.edit_view(key) as current:
                        current.block_id = block.block_id
                        current.window_id = block.window_id
                        current.state = ViewState.READY
                        current.revision += 1
                    existing = await rendered_view(store, key, current.revision)
                    if focus:
                        await client.text(["focus", "-s", session_id, block.block_id])
                    return PresentationResult(state="reused", view=existing)
            elif existing.state in {ViewState.CREATING, ViewState.UNCERTAIN}:
                raise RexError(
                    RexIssue.UNCERTAIN,
                    "Pane creation is uncertain. Run jobctl doctor --fix to reconcile, or --new to create another.",
                )
        token = secrets.token_hex(8)
        record = ViewRecord(
            view_key=key,
            token=token,
            target=target,
            endpoint=identity.endpoint,
            host_id=identity.host_id,
            session_id=session_id,
            label=f"{target_title(store, target)} [jobctl {token}]",
        )
        store.save_view(record)
        arguments = [
            "run",
            "-s",
            session_id,
            "--label",
            record.label,
            "--shell=none",
            f"--focus={str(focus).lower()}",
            "--json",
            "-c",
            str(Path.cwd()),
        ]
        if selected_layout is not ViewLayout.TAB:
            arguments.extend(["-b", str(anchor), f"--split={selected_layout.value}", "--ratio", "30"])
        arguments.extend(["--", *viewer_command(settings, target, key, token)])
        try:
            created = await client.model(arguments, RexCreated)
            inspected = await client.model(
                ["block", "inspect", created.block_ids[0], "-s", session_id, "--json"], RexInspection
            )
            if inspected.block.host_id != identity.host_id:
                raise RexError(RexIssue.REMOTE, "The created pane belongs to another Rex host.")
        except RexError:
            with store.edit_view(key) as current:
                current.state = ViewState.UNCERTAIN
            raise
        deadline = time.monotonic() + 8
        while True:
            with store.edit_view(key) as current:
                current.block_id = created.block_ids[0]
                current.window_id = created.window_id or inspected.block.window_id
            if current.ready_at and current.state is ViewState.READY and current.rendered_revision >= current.revision:
                return PresentationResult(state="created", view=current)
            if current.state is ViewState.CLOSED or time.monotonic() >= deadline:
                raise RexError(
                    RexIssue.NOT_READY,
                    f"Viewer did not become ready in {current.block_id}. Inspect that pane or run jobctl doctor.",
                )
            await asyncio.sleep(0.1)


def emit_presentation(result: PresentationResult, as_json: bool) -> None:
    """Report presentation separately from job outcomes."""
    if as_json:
        click.echo(result.model_dump_json())
    elif result.view:
        click.echo(f"{result.state} viewer: {result.view.block_id}")
    else:
        click.echo(result.message, err=True)


class ViewerOperation(StrEnum):
    """Lifecycle operations require an explicit repeated key for the displayed span."""

    STOP = "stop"
    RESTART = "restart"


@dataclass(frozen=True)
class ViewerConfirmation:
    """Confirmation is invalidated when selection or the role's current run changes."""

    operation: ViewerOperation
    span_id: str


def terminal_text(value: str) -> str:
    """Logs and labels are untrusted text, never terminal control sequences."""
    return "".join(character if character.isprintable() or character == "\n" else " " for character in value)


def program_status(run: Run) -> str:
    """Translate recorded outcomes, without inferring progress or blocked states from logs."""
    match run.state:
        case RunState.RUNNING:
            state = "working"
        case RunState.SUCCEEDED:
            state = "done"
        case RunState.FAILED | RunState.LOST:
            state = "error"
        case RunState.STOPPED:
            state = "idle"
    message = base64.b64encode(terminal_text(f"{run.job}: {run.state.value}").replace("\n", " ").encode()).decode()
    return f"\x1b]7501;state={state}:id=jobs/{run.span_id}:app=jobctl:msg={message}\x1b\\"


def mark_view(
    store: RunStore, settings: Settings, key: str | None, token: str | None, state: ViewState, revision: int = -1
) -> None:
    """Only the viewer that owns this creation token may update its readiness."""
    if key is None:
        return
    with store.edit_view(key) as record:
        if record.token != token:
            return
        record.state = state
        if state is ViewState.READY:
            record.ready_at = iso(time.time_ns())
            record.block_id = settings.rex_block or record.block_id
            record.rendered_revision = revision


class ViewerKey(StrEnum):
    """Terminal input is decoded before it reaches navigation or lifecycle controls."""

    TEXT = "text"
    UP = "up"
    DOWN = "down"
    PAGE_UP = "page-up"
    PAGE_DOWN = "page-down"
    HOME = "home"
    END = "end"
    ENTER = "enter"
    ESCAPE = "escape"
    TAB = "tab"
    BACKSPACE = "backspace"
    QUIT = "quit"
    OVERFLOW = "overflow"


@dataclass(frozen=True)
class ViewerInput:
    """Text keys carry a character; navigation keys have no text payload."""

    key: ViewerKey
    text: str = ""


class ViewerInputReader:
    """Own fragmented UTF-8/VT input and the timer distinguishing Escape from a key sequence."""

    def __init__(self, queue: asyncio.Queue[ViewerInput], descriptor: int) -> None:
        self.queue = queue
        self.descriptor = descriptor
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.sequence = ""
        self.timer: asyncio.TimerHandle | None = None
        self.discarding = False

    def offer(self, event: ViewerInput) -> None:
        """Bound pending input; overflow cancels confirmation instead of replaying a partial key burst."""
        if self.discarding:
            return
        if self.queue.full():
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(ViewerInput(ViewerKey.OVERFLOW))
            self.discarding = True
            return
        self.queue.put_nowait(event)

    def close(self) -> None:
        """Release the pending Escape timer when the terminal view ends."""
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def escape(self) -> None:
        """Resolve an isolated Escape; incomplete control sequences are discarded."""
        if self.sequence == "\x1b":
            self.offer(ViewerInput(ViewerKey.ESCAPE))
        self.sequence = ""
        self.timer = None

    def read(self) -> None:
        """Event-loop callback; EOF quits and control sequences never become action letters."""
        self.discarding = False
        try:
            data = os.read(self.descriptor, 4096)
        except OSError:
            data = b""
        if not data:
            self.offer(ViewerInput(ViewerKey.QUIT))
            return
        for character in self.decoder.decode(data):
            self.character(character)

    def character(self, character: str) -> None:
        """Parse VT's CSI/SS3 grammar, accepting only the navigation keys we support."""
        if character == "\x1b":
            if self.sequence == "\x1b":
                self.offer(ViewerInput(ViewerKey.ESCAPE))
            self.close()
            self.sequence = character
            # Escape is also the prefix of cursor keys. This is an input disambiguation deadline.
            self.timer = asyncio.get_running_loop().call_later(0.08, self.escape)
            return
        if self.sequence == "\x1b" and character not in {"[", "O"}:
            # Escape followed quickly by Tab/text is two keys, not an unsupported cursor sequence.
            self.close()
            self.sequence = ""
            self.offer(ViewerInput(ViewerKey.ESCAPE))
        if self.sequence:
            self.sequence += character
            if len(self.sequence) == 2 and character in {"[", "O"}:
                return
            if len(self.sequence) > 2 and "@" <= character <= "~":
                navigation = {
                    "\x1b[A": ViewerKey.UP,
                    "\x1bOA": ViewerKey.UP,
                    "\x1b[B": ViewerKey.DOWN,
                    "\x1bOB": ViewerKey.DOWN,
                    "\x1b[H": ViewerKey.HOME,
                    "\x1bOH": ViewerKey.HOME,
                    "\x1b[F": ViewerKey.END,
                    "\x1bOF": ViewerKey.END,
                    "\x1b[1~": ViewerKey.HOME,
                    "\x1b[7~": ViewerKey.HOME,
                    "\x1b[4~": ViewerKey.END,
                    "\x1b[8~": ViewerKey.END,
                    "\x1b[5~": ViewerKey.PAGE_UP,
                    "\x1b[6~": ViewerKey.PAGE_DOWN,
                }.get(self.sequence)
                if navigation:
                    self.offer(ViewerInput(navigation))
                self.close()
                self.sequence = ""
            elif len(self.sequence) == 2 or len(self.sequence) > 32:
                self.close()
                self.sequence = ""
            return
        control = {
            "\r": ViewerKey.ENTER,
            "\n": ViewerKey.ENTER,
            "\t": ViewerKey.TAB,
            "\x7f": ViewerKey.BACKSPACE,
            "\b": ViewerKey.BACKSPACE,
        }.get(character)
        if control:
            self.offer(ViewerInput(control))
        elif character.isprintable():
            self.offer(ViewerInput(ViewerKey.TEXT, character))


class ViewerPage(StrEnum):
    """Job screens share navigation while retaining independent local state."""

    LOGS = "Logs"
    HISTORY = "Runs"


class ViewerFilter(StrEnum):
    """Local presentation filters; the audit store remains the lifecycle authority."""

    ALL = "All"
    RUNNING = "Running"
    PROBLEMS = "Problems"
    FINISHED = "Finished"


@dataclass
class ViewerState:
    """Ephemeral UI state, owned by one foreground terminal view."""

    selected: int = 0
    selected_job: tuple[str, str] | None = None
    selected_span: str | None = None
    scroll: int = 0
    page_size: int = 1
    offset: int = 0
    page: ViewerPage = ViewerPage.LOGS
    help: bool = False
    query: str = ""
    saved_query: str = ""
    searching: bool = False
    filter: ViewerFilter = ViewerFilter.ALL
    message: str = "Closing this view leaves the job running."


@dataclass(frozen=True)
class ViewerFrame:
    """A saved parent owns its selection, filters, viewport and log position."""

    target: ViewTarget
    state: ViewerState


def viewer_parents(store: RunStore, target: ViewTarget) -> list[ViewerFrame]:
    """Direct job viewers can return to the job's own project without widening scope."""
    if isinstance(target, DashboardTarget):
        return []
    run = target_run(store, target)
    return [ViewerFrame(DashboardTarget(project=run.project), ViewerState(selected_job=(run.project, run.name)))]


class ViewerStyle(StrEnum):
    """ANSI styles are trusted renderer constants, never sourced from job output."""

    NORMAL = "0"
    TITLE = "1;36"
    MUTED = "2"
    HEADER = "1"
    SELECTED = "1;7"
    RUNNING = "36"
    SUCCESS = "32"
    PROBLEM = "31"
    NOTICE = "33"


@dataclass(frozen=True)
class ViewerLine:
    """Sanitize and clip text before adding trusted terminal styling."""

    text: str = ""
    style: ViewerStyle = ViewerStyle.NORMAL


def viewer_cell(value: str, width: int, pad: bool = False) -> str:
    """Clip by display cells, keeping wide characters out of adjacent columns."""
    text = terminal_text(value).replace("\n", " ")
    used = 0
    characters: list[str] = []
    for character in text:
        size = viewer_character_width(character)
        if used + size > max(0, width):
            if characters and width > 0:
                while characters and used > width - 1:
                    removed = characters.pop()
                    used -= viewer_character_width(removed)
                characters.append("…")
                used += 1
            break
        characters.append(character)
        used += size
    return "".join(characters) + (" " * max(0, width - used) if pad else "")


def viewer_character_width(character: str) -> int:
    """Measure a printable Unicode character in terminal cells."""
    if character == "\ufe0f":
        # Emoji presentation can widen an otherwise narrow symbol. Reserve that extra cell conservatively.
        return 1
    if unicodedata.combining(character) or unicodedata.category(character) in {"Mn", "Me"}:
        return 0
    return 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1


def viewer_search(query: str, width: int, editing: bool) -> str:
    """Keep the insertion end visible when a search is longer than the terminal."""
    suffix = "▏" if editing else ""
    available = max(1, width - 8 - len(suffix))
    if sum(viewer_character_width(character) for character in query) > available:
        characters: list[str] = []
        used = 1
        for character in reversed(query):
            size = viewer_character_width(character)
            if used + size > available:
                break
            characters.append(character)
            used += size
        query = "…" + "".join(reversed(characters))
    return f"Search: {query}{suffix}"


def viewer_duration(run: Run) -> str:
    """Use recorded elapsed time for completed runs and wall time only for live runs."""
    seconds = max(
        0,
        int(
            run.duration_seconds
            if run.duration_seconds is not None
            else (time.time_ns() - run.start_time_unix_nano) / 1e9
        ),
    )
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02}s"
    if seconds < 86400:
        return f"{seconds // 3600}h {seconds % 3600 // 60:02}m"
    return f"{seconds // 86400}d {seconds % 86400 // 3600:02}h"


def viewer_style(run: Run) -> ViewerStyle:
    """Text labels carry status even when terminal colors are unavailable."""
    match run.state:
        case RunState.RUNNING:
            return ViewerStyle.RUNNING
        case RunState.SUCCEEDED:
            return ViewerStyle.SUCCESS
        case RunState.FAILED | RunState.LOST:
            return ViewerStyle.PROBLEM
        case RunState.STOPPED:
            return ViewerStyle.MUTED


def viewer_filtered(runs: list[Run], state: ViewerState) -> list[Run]:
    """Search unstructured job labels/commands; typed state controls membership and ordering."""
    query = state.query.casefold()
    visible: list[Run] = []
    for run in runs:
        match state.filter:
            case ViewerFilter.RUNNING if run.state is not RunState.RUNNING:
                continue
            case ViewerFilter.PROBLEMS if run.state not in {RunState.FAILED, RunState.LOST}:
                continue
            case ViewerFilter.FINISHED if run.state is RunState.RUNNING:
                continue
        # A user-entered search is genuinely unstructured text, not classification of a structured format.
        if query and query not in f"{run.job} {run.command_line} {run.cwd}".casefold():
            continue
        visible.append(run)
    return sorted(visible, key=viewer_order)


def viewer_order(run: Run) -> tuple[bool, int]:
    """Running jobs precede completed jobs; each group is newest first."""
    return run.state is not RunState.RUNNING, -run.start_time_unix_nano


def viewer_runs(store: RunStore, target: ViewTarget) -> list[Run]:
    """Load current roles from the audit store, including live jobs older than one day."""
    if isinstance(target, DashboardTarget):
        cutoff = time.time_ns() - 86400 * 10**9
        condition = "(state = ? OR start_time_unix_nano >= ?)"
        parameters: tuple[Any, ...] = (RunState.RUNNING.value, cutoff)
        if target.project:
            condition += " AND project = ?"
            parameters += (target.project,)
        return store.latest(condition, parameters)
    return [target_run(store, target)]


def viewer_screen(
    store: RunStore,
    target: ViewTarget,
    runs: list[Run],
    all_runs: list[Run],
    state: ViewerState,
    columns: int,
    rows: int,
    parents: list[ViewerFrame],
) -> list[str]:
    """Reserve controls/details first, then size the list or log viewport to fit."""
    width, height = max(1, columns - 1), max(1, rows - 1)
    lines = [ViewerLine(f"jobctl — {target_title(store, target)}", ViewerStyle.TITLE)]
    if height < 7 or width < 24:
        lines += [ViewerLine("Enlarge pane to see jobs."), ViewerLine("q close · ? help")]
    elif state.help:
        lines += [
            ViewerLine("Keyboard shortcuts", ViewerStyle.HEADER),
            ViewerLine("↑/↓ or j/k   Select job / scroll logs"),
            ViewerLine("PgUp/PgDn    Move one page"),
            ViewerLine("Home/End     First / last job"),
            ViewerLine("Enter        Open selected job / run"),
            ViewerLine("/            Search jobs and commands"),
            ViewerLine("Tab          Job filters / run history"),
            ViewerLine("Esc          Back / cancel / clear filters"),
            ViewerLine("g            First job / latest logs"),
            ViewerLine("G            Last job / latest logs"),
            ViewerLine("s s / r r    Confirm stop / restart"),
            ViewerLine("q / Ctrl+C   Close view; jobs keep running"),
            ViewerLine("? / Esc      Close this help", ViewerStyle.NOTICE),
        ]
        lines = lines[: height - 1] + [ViewerLine("? / Esc close help · q also returns", ViewerStyle.NOTICE)]
    elif isinstance(target, DashboardTarget):
        running = sum(run.state is RunState.RUNNING for run in all_runs)
        problems = sum(run.state in {RunState.FAILED, RunState.LOST} for run in all_runs)
        lines.append(
            ViewerLine(f"{running} running   {problems} problems   {len(all_runs)} jobs · last 24h", ViewerStyle.MUTED)
        )
        filters = "  ".join(f"[{item.value}]" if item is state.filter else item.value for item in ViewerFilter)
        if width < 54:
            filters = f"Filter: [{state.filter.value}]"
        lines.append(ViewerLine(filters + "   · Tab to filter", ViewerStyle.HEADER))
        search = (
            viewer_search(state.query, width, state.searching)
            if state.searching or state.query
            else "/ Search jobs or commands"
        )
        if state.searching and len(search) + 27 <= width:
            search += "   Enter apply · Esc cancel"
        lines.append(ViewerLine(search, ViewerStyle.NOTICE if state.searching else ViewerStyle.MUTED))
        name_width = min(52, width - 38) if width >= 90 else width - (28 if width >= 54 else 15)
        heading = "  " + viewer_cell("JOB", name_width, True) + "  " + viewer_cell("STATE", 10, True)
        if width >= 54:
            heading += "  " + viewer_cell("ELAPSED", 8, True)
        if width >= 90:
            heading += "  " + viewer_cell("STARTED", 8, True)
        if width >= 110:
            heading += "  COMMAND"
        lines.append(ViewerLine(heading, ViewerStyle.HEADER))
        if height < 10:
            lines = [lines[0], lines[3] if state.searching or state.query else lines[2], lines[4]]
        preview_rows = 7 if height >= 23 else 4 if height >= 16 else 0
        footer_rows = 3
        capacity = max(1, height - len(lines) - preview_rows - footer_rows)
        state.page_size = capacity
        state.scroll = min(state.scroll, state.selected)
        state.scroll = max(state.scroll, state.selected - capacity + 1)
        state.scroll = min(state.scroll, max(0, len(runs) - capacity))
        for index in range(state.scroll, min(len(runs), state.scroll + capacity)):
            run = runs[index]
            marker = "› " if index == state.selected else "  "
            label = run.name if target.project else run.job
            row = marker + viewer_cell(label, name_width, True) + "  " + viewer_cell(run.state.value, 10, True)
            if width >= 54:
                row += "  " + viewer_cell(viewer_duration(run), 8, True)
            if width >= 90:
                row += "  " + datetime.datetime.fromisoformat(run.started_at).astimezone().strftime("%H:%M:%S")
            if width >= 110:
                row += f"  {run.command_line}"
            lines.append(ViewerLine(row, ViewerStyle.SELECTED if index == state.selected else viewer_style(run)))
        if not runs:
            lines.append(
                ViewerLine(
                    "No matching jobs. Esc clears filters." if all_runs else "No running or recent jobs.",
                    ViewerStyle.MUTED,
                )
            )
        lines.extend(ViewerLine() for unused in range(max(0, height - footer_rows - preview_rows - len(lines))))
        if preview_rows:
            if runs:
                run = runs[state.selected]
                ports = ", ".join(map(str, sorted(set(run.declared_ports + run.ports)))) or "none"
                result = f"exit {run.exit_code}" if run.exit_code is not None else run.state.value
                preview = [
                    ViewerLine("─" * width, ViewerStyle.MUTED),
                    ViewerLine(f"{run.job} · {result} · {viewer_duration(run)}", ViewerStyle.HEADER),
                    ViewerLine(f"$ {run.command_line}"),
                    ViewerLine(f"Directory: {run.cwd}", ViewerStyle.MUTED),
                    ViewerLine(f"Ports: {ports} · span {run.span_id}", ViewerStyle.MUTED),
                ]
                if preview_rows == 7:
                    preview.append(ViewerLine("Recent output", ViewerStyle.MUTED))
                    preview.extend(viewer_log_lines(run, 1, 0))
                lines.extend(preview[:preview_rows])
            else:
                lines.extend(ViewerLine() for unused in range(preview_rows))
        position = f"{state.selected + 1}/{len(runs)}" if runs else "0/0"
        visible_end = min(len(runs), state.scroll + capacity)
        navigation = (
            f"{position} jobs · rows {state.scroll + 1}–{visible_end} · ↑/↓ select · Enter logs · ? help"
            if runs
            else "0/0 jobs · Esc clears filters"
        )
        if width < 54:
            navigation = f"{position} jobs · ↑/↓ · Enter logs"
        lines.append(ViewerLine(navigation, ViewerStyle.MUTED))
        lines.append(ViewerLine(state.message, ViewerStyle.NOTICE))
        controls = "q close · / search · ? help" if width < 54 else "s stop · r restart · Tab filter · q close"
        lines.append(ViewerLine(controls, ViewerStyle.HEADER))
    else:
        run = runs[state.selected] if state.page is ViewerPage.HISTORY else runs[0]
        path = ["Jobs", run.name]
        if state.page is ViewerPage.HISTORY or any(frame.state.page is ViewerPage.HISTORY for frame in parents):
            path.append("Runs")
        if state.page is ViewerPage.LOGS:
            if isinstance(target, RunViewTarget) and width >= 54:
                path.append(run.span_id[:8])
            path.append("Logs")
        reserved = sum(len(part) for index, part in enumerate(path) if index != 1) + 3 * (len(path) - 1)
        path[1] = viewer_cell(run.name, max(1, width - reserved))
        lines.append(ViewerLine(" › ".join(path), ViewerStyle.MUTED))
        ports = ", ".join(map(str, sorted(set(run.declared_ports + run.ports)))) or "none"
        outcome = f"exit {run.exit_code}" if run.exit_code is not None else "exit —"
        lines.append(
            ViewerLine(f"{run.state.value} · {outcome} · {viewer_duration(run)} · ports {ports}", viewer_style(run))
        )
        lines.append(ViewerLine(f"span {run.span_id}", ViewerStyle.MUTED))
        if height >= 10:
            lines.append(ViewerLine(f"$ {run.command_line}"))
        if height >= 16:
            lines.append(ViewerLine(f"Directory: {run.cwd}", ViewerStyle.MUTED))
        title = (
            ("Run history · latest 200 runs" if len(runs) == 200 else "Run history")
            if state.page is ViewerPage.HISTORY
            else (
                f"Logs · {state.offset} lines above latest · g to follow"
                if state.offset
                else "Logs · following latest output"
            )
        )
        lines.append(ViewerLine(title, ViewerStyle.HEADER))
        footer_rows = 3 if height >= 10 else 2
        available = max(1, height - len(lines) - footer_rows)
        state.page_size = available
        if state.page is ViewerPage.HISTORY:
            state.scroll = max(min(state.scroll, state.selected), state.selected - available + 1)
            content = []
            for index in range(state.scroll, min(len(runs), state.scroll + available)):
                item = runs[index]
                marker = "› " if index == state.selected else "  "
                started = datetime.datetime.fromisoformat(item.started_at).astimezone().strftime("%m-%d %H:%M:%S")
                exit_code = str(item.exit_code) if item.exit_code is not None else "—"
                content.append(
                    ViewerLine(
                        f"{marker}{started}  {item.state.value}  exit {exit_code}  {item.span_id}",
                        ViewerStyle.SELECTED if index == state.selected else viewer_style(item),
                    )
                )
        else:
            content = viewer_log_lines(run, available, state.offset)
        lines.extend(content)
        lines.extend(ViewerLine() for unused in range(max(0, height - footer_rows - len(lines))))
        if height >= 10:
            navigation = (
                f"{state.selected + 1}/{len(runs)} runs · ↑/↓ select · Enter logs"
                if state.page is ViewerPage.HISTORY
                else "↑/↓ scroll · PgUp/PgDn page · Tab runs"
            )
            lines.append(ViewerLine(navigation, ViewerStyle.MUTED))
        lines.append(ViewerLine(state.message, ViewerStyle.NOTICE))
        controls = (
            "Esc back · Enter logs · q close" if state.page is ViewerPage.HISTORY else "Esc back · Tab runs · q close"
        )
        if width >= 54:
            controls += " · s stop · r restart · ? help"
        lines.append(ViewerLine(controls, ViewerStyle.HEADER))
    visible = lines[:height]
    visible.extend(ViewerLine() for unused in range(height - len(visible)))
    return [
        f"\x1b[{line.style.value}m{viewer_cell(line.text, width, line.style is ViewerStyle.SELECTED)}\x1b[0m"
        for line in visible
    ]


def viewer_log_lines(run: Run, available: int, offset: int) -> list[ViewerLine]:
    """Bound retained output and keep missing/unreadable files visible without disabling controls."""
    path = Path(run.log_path)
    try:
        if not path.exists():
            return [ViewerLine(f"Log file is missing: {path}", ViewerStyle.NOTICE)]
        # Log lines are genuinely unstructured text; slicing is only for the user's scroll position.
        log_lines = terminal_text(tail(path, available + offset)).splitlines()
        end = max(0, len(log_lines) - offset)
        visible = log_lines[max(0, end - available) : end]
        return [ViewerLine(line) for line in visible] or [
            ViewerLine("No output yet." if not offset else "Start of retained output · g latest", ViewerStyle.MUTED)
        ]
    except OSError as error:
        return [ViewerLine(f"Log unavailable: {error}", ViewerStyle.NOTICE)]


async def viewer_operation(store: RunStore, settings: Settings, operation: ViewerOperation, run: Run) -> str:
    """Reuse the lifecycle implementation; a stale selection cannot restart a newer run."""
    try:
        current = resolve(store, run.job, run.project)
        if current.span_id != run.span_id:
            return "The job has a newer run. Select it and confirm again."
        await stop(store, settings, current, 30, f"Rex viewer requested {operation.value}")
        if operation is ViewerOperation.STOP:
            return f"Stopped {run.job}."
        replacement = start(
            store, settings, run.name, run.project, run.command, Path(run.cwd), None, run.declared_ports, run.tags
        )
        if replacement.declared_ports:
            await wait_until_ready(store, replacement, 120)
        return f"Restarted {run.job}: {replacement.span_id}."
    except (JobctlError, OSError, sqlite3.Error) as error:
        return f"{operation.value} failed: {error}"


async def terminal_view(
    store: RunStore, settings: Settings, initial: ViewTarget, key: str | None, token: str | None
) -> None:
    """Use a controlling foreground terminal, restoring its modes on every exit path."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise BadInput("The viewer needs a terminal. Use jobctl show/logs --json for captured output.")
    descriptor = sys.stdin.fileno()
    if os.tcgetpgrp(descriptor) != os.getpgrp():
        raise BadInput("The viewer must run in the terminal's foreground process group.")
    previous = termios.tcgetattr(descriptor)
    queue: asyncio.Queue[ViewerInput] = asyncio.Queue(maxsize=512)
    reader = ViewerInputReader(queue, descriptor)
    loop = asyncio.get_running_loop()
    target = initial
    state = ViewerState()
    parents = viewer_parents(store, initial)
    confirmation: ViewerConfirmation | None = None
    action_task: asyncio.Task[str] | None = None
    previous_status = ""
    registered = False
    revision = -1
    quit_requested = False
    previous_frame: list[str] = []
    previous_size = (0, 0)
    try:
        tty.setcbreak(descriptor)
        loop.add_reader(descriptor, reader.read)
        click.echo("\x1b[?1049h\x1b[?25l\x1b[2J", nl=False)
        async with asyncio.TaskGroup() as tasks:
            while True:
                record = store.view(key) if key else None
                requested_revision = record.revision if record and record.token == token else revision
                if requested_revision != revision:
                    target = initial
                    state = ViewerState()
                    parents = viewer_parents(store, initial)
                    confirmation = None
                    revision = requested_revision
                    registered = False
                reconcile(store)
                all_runs = viewer_runs(store, target)
                board = isinstance(target, DashboardTarget)
                history = state.page is ViewerPage.HISTORY
                if history and not isinstance(target, DashboardTarget):
                    run = target_run(store, target)
                    all_runs = store.select("project = ? AND name = ?", (run.project, run.name), limit=200)
                runs = viewer_filtered(all_runs, state) if board else all_runs
                if board:
                    if state.selected_job is not None:
                        state.selected = next(
                            (index for index, run in enumerate(runs) if (run.project, run.name) == state.selected_job),
                            state.selected,
                        )
                    state.selected = min(state.selected, max(0, len(runs) - 1))
                    state.selected_job = (runs[state.selected].project, runs[state.selected].name) if runs else None
                elif history:
                    if state.selected_span is not None:
                        state.selected = next(
                            (index for index, run in enumerate(runs) if run.span_id == state.selected_span),
                            state.selected,
                        )
                    state.selected = min(state.selected, max(0, len(runs) - 1))
                    state.selected_span = runs[state.selected].span_id if runs else None
                current = runs[state.selected] if (board or history) and runs else runs[0] if runs else None
                if confirmation and (current is None or confirmation.span_id != current.span_id):
                    confirmation = None
                    state.message = "Selection changed; confirm the current run again."
                if action_task is not None and action_task.done():
                    state.message = action_task.result()
                    action_task = None
                    if quit_requested:
                        break
                columns, rows = os.get_terminal_size(sys.stdout.fileno())
                frame = viewer_screen(store, target, runs, all_runs, state, columns, rows, parents)
                if previous_size != (columns, rows):
                    previous_frame = []
                    click.echo("\x1b[2J", nl=False)
                    previous_size = (columns, rows)
                # Update only changed rows, without clearing a live screen once per second.
                paint = "".join(
                    f"\x1b[{index + 1};1H{line}\x1b[K"
                    for index, line in enumerate(frame)
                    if index >= len(previous_frame) or previous_frame[index] != line
                )
                if paint:
                    click.echo(paint, nl=False)
                previous_frame = frame
                statuses = "".join(program_status(run) for run in runs[:64])
                if statuses != previous_status:
                    click.echo("\x1b]7501;state=clear\x1b\\" + statuses, nl=False)
                    previous_status = statuses
                if not registered:
                    mark_view(store, settings, key, token, ViewState.READY, revision)
                    registered = True
                try:
                    async with asyncio.timeout(1):
                        event = await queue.get()
                except TimeoutError:
                    continue
                pressed = event.text if event.key is ViewerKey.TEXT else ""
                if event.key is ViewerKey.OVERFLOW:
                    confirmation = None
                    state.message = "Input buffer full; pending keys discarded. Type again."
                    continue
                if state.help and event.key is not ViewerKey.QUIT:
                    if pressed in {"?", "q"} or event.key is ViewerKey.ESCAPE:
                        state.help = False
                    continue
                if state.searching and event.key is not ViewerKey.QUIT:
                    confirmation = None
                    if event.key is ViewerKey.ENTER:
                        state.searching = False
                    elif event.key is ViewerKey.ESCAPE:
                        state.query, state.searching = state.saved_query, False
                    elif event.key is ViewerKey.BACKSPACE:
                        state.query = state.query[:-1]
                    elif event.key is ViewerKey.TEXT:
                        if len(state.query) < 256:
                            state.query += pressed
                        else:
                            state.message = "Search is limited to 256 characters."
                    state.selected, state.selected_job, state.scroll = 0, None, 0
                    continue
                if event.key is ViewerKey.ESCAPE or pressed == "b":
                    if confirmation:
                        confirmation = None
                        state.message = "Action cancelled."
                    elif parents:
                        parent = parents.pop()
                        target, state = parent.target, parent.state
                    elif board:
                        state.query, state.filter = "", ViewerFilter.ALL
                    continue
                if pressed == "q" or event.key is ViewerKey.QUIT:
                    if action_task is None:
                        break
                    quit_requested = True
                    state.message = "Closing after the requested operation finishes; Ctrl+C detaches now."
                elif pressed in {"s", "r"} and current and action_task is None:
                    operation = ViewerOperation.STOP if pressed == "s" else ViewerOperation.RESTART
                    proposed = ViewerConfirmation(operation, current.span_id)
                    if confirmation == proposed:
                        action_task = tasks.create_task(viewer_operation(store, settings, operation, current))
                        confirmation = None
                        state.message = f"{operation.value} in progress…"
                    else:
                        confirmation = proposed
                        state.message = (
                            f"Press {pressed} again to {operation.value} {current.job} ({proposed.span_id})."
                        )
                else:
                    if confirmation:
                        state.message = "Action cancelled."
                    confirmation = None
                    page = state.page_size
                    if pressed == "j" or event.key in {ViewerKey.DOWN, ViewerKey.PAGE_DOWN}:
                        step = page if event.key is ViewerKey.PAGE_DOWN else 1
                        if board or history:
                            state.selected = min(state.selected + step, max(0, len(runs) - 1))
                        else:
                            state.offset = max(0, state.offset - (page if event.key is ViewerKey.PAGE_DOWN else 5))
                    elif pressed == "k" or event.key in {ViewerKey.UP, ViewerKey.PAGE_UP}:
                        step = page if event.key is ViewerKey.PAGE_UP else 1
                        if board or history:
                            state.selected = max(0, state.selected - step)
                        else:
                            state.offset = min(10000, state.offset + (page if event.key is ViewerKey.PAGE_UP else 5))
                    elif event.key is ViewerKey.ENTER and (board or history) and current:
                        parents.append(ViewerFrame(target, state))
                        target = (
                            JobViewTarget(project=current.project, name=current.name)
                            if board
                            else RunViewTarget(span_id=current.span_id)
                        )
                        state = ViewerState()
                        continue
                    elif (pressed == "h" or event.key is ViewerKey.TAB) and not board:
                        if history or (parents and parents[-1].state.page is ViewerPage.HISTORY):
                            parent = parents.pop()
                            target, state = parent.target, parent.state
                        else:
                            parents.append(ViewerFrame(target, state))
                            state = ViewerState(
                                page=ViewerPage.HISTORY, selected_span=current.span_id if current else None
                            )
                        continue
                    elif pressed == "g" or event.key is ViewerKey.HOME:
                        if board or history:
                            state.selected = 0
                        else:
                            state.offset = 0 if pressed == "g" else 10000
                    elif pressed == "G" or event.key is ViewerKey.END:
                        if board or history:
                            state.selected = max(0, len(runs) - 1)
                        else:
                            state.offset = 0
                    elif pressed == "/" and board:
                        state.saved_query, state.searching = state.query, True
                    elif event.key is ViewerKey.TAB and board:
                        filters = list(ViewerFilter)
                        state.filter = filters[(filters.index(state.filter) + 1) % len(filters)]
                        state.selected, state.selected_job, state.scroll = 0, None, 0
                        continue
                    elif pressed == "?":
                        state.help = True
                    if board and runs:
                        state.selected_job = (runs[state.selected].project, runs[state.selected].name)
                    elif history and runs:
                        state.selected_span = runs[state.selected].span_id
    finally:
        loop.remove_reader(descriptor)
        reader.close()
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)
        click.echo("\x1b]7501;state=clear\x1b\\\x1b[?25h\x1b[?1049l", nl=False)
        mark_view(store, settings, key, token, ViewState.CLOSED)


class RexMethod(BaseModel):
    """Capability names are read from the connected server, never inferred from versions."""

    name: str


class RexCapabilities(BaseModel):
    """Only required server operations are needed by jobctl's Rex adapter."""

    methods: list[RexMethod]


async def probe_presentation(settings: Settings) -> str:
    """Exercise the actual CLI/terminal boundary with isolated state and an owned harmless job."""
    with tempfile.TemporaryDirectory(prefix="jobctl-rex-probe-") as directory:
        isolated = settings.model_copy(update={"home": Path(directory), "traceparent": None})
        store = RunStore(isolated.database)
        run: Run | None = None
        record: ViewRecord | None = None
        client = RexClient(isolated)
        try:
            run = start(
                store, isolated, "viewer-probe", "jobctl-probe", ["/bin/sleep", "45"], Path(directory), None, [], {}
            )
            result = await open_view(store, isolated, RunViewTarget(span_id=run.span_id), ViewLayout.TAB)
            record = result.view
            if record is None or record.block_id is None:
                raise RexError(RexIssue.NOT_READY, "Probe did not obtain a ready viewer.")
            screen = await client.text(["capture", "-s", record.session_id, "-b", record.block_id, "--trim"])
            # Terminal contents are unstructured user-visible text, inspected only for probe output.
            if "viewer-probe" not in screen or run.span_id not in screen:
                raise RexError(RexIssue.NOT_READY, "Probe viewer did not display its job and span.")
            await client.text(["send", "-s", record.session_id, "-b", record.block_id, "q"])
            deadline = time.monotonic() + 5
            while await view_block(client, record) is not None:
                if time.monotonic() >= deadline:
                    raise RexError(RexIssue.NOT_READY, "Quitting the probe left an exited viewer pane behind.")
                await asyncio.sleep(0.1)
            record = None
            reconcile(store)
            if store.get(run.span_id).state is not RunState.RUNNING:
                raise RexError(RexIssue.NOT_READY, "Closing the probe viewer ended its detached job.")
            stopped = await stop(store, isolated, store.get(run.span_id), 2, "doctor probe complete")
            if stopped.state is not RunState.STOPPED:
                raise RexError(RexIssue.NOT_READY, "Probe job did not record its stop.")
            return (
                "Read a viewer; q removed its pane and preserved the job; stop recorded its outcome. Probe cleaned up."
            )
        finally:
            try:
                if record is not None and record.block_id:
                    block = await view_block(client, record)
                    if block:
                        await client.text(["block", "close", "-s", record.session_id, block.block_id])
                elif record is None:
                    for pending in store.views():
                        if pending.state in {ViewState.CREATING, ViewState.UNCERTAIN}:
                            block = await view_block(client, pending)
                            if block:
                                await client.text(["block", "close", "-s", pending.session_id, block.block_id])
            finally:
                try:
                    if run is not None:
                        await stop(store, isolated, store.get(run.span_id), 2, "doctor probe cleanup")
                finally:
                    store.close()


def inspect_state(settings: Settings, report: DoctorReport) -> list[ViewRecord]:
    """Inspect existing files and schema through a read-only connection; never create them."""
    home = settings.home.expanduser()
    if not home.exists():
        report.checks.append(
            DoctorCheck(name="state", state=CheckState.WARNING, message=f"Not initialized: {home}; run jobctl setup.")
        )
        return []
    if not home.is_dir() or not os.access(home, os.W_OK | os.X_OK):
        report.checks.append(
            DoctorCheck(name="state", state=CheckState.ERROR, message=f"State directory is not writable: {home}")
        )
        return []
    try:
        preferences = presentation_config(settings)
        report.checks.append(
            DoctorCheck(name="preferences", state=CheckState.OK, message=f"Default layout: {preferences.layout.value}")
        )
        link = preferences.bin_dir / "jobctl"
        correct = link.is_file() and link.resolve() == Path(__file__).resolve()
        report.checks.append(
            DoctorCheck(
                name="installation",
                state=CheckState.OK if correct else CheckState.WARNING,
                message=f"{link}" if correct else f"Missing or different jobctl at {link}; run jobctl setup.",
            )
        )
        if not settings.database.exists():
            report.checks.append(
                DoctorCheck(name="database", state=CheckState.WARNING, message="No audit database; run jobctl setup.")
            )
            return []
        with contextlib.closing(
            sqlite3.connect(settings.database.resolve().as_uri() + "?mode=ro", uri=True)
        ) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
            missing = set(Run.model_fields) - columns
            if missing:
                raise JobctlError(
                    f"Unsupported audit schema; missing columns: {', '.join(sorted(missing))}. Database preserved."
                )
            integrity = connection.execute("PRAGMA quick_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise JobctlError(f"Audit database integrity check failed: {integrity}")
            report.checks.append(
                DoctorCheck(
                    name="database", state=CheckState.OK, message=f"Supported schema and integrity: {settings.database}"
                )
            )
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "jobctl_views" not in tables:
                report.checks.append(
                    DoctorCheck(
                        name="views",
                        state=CheckState.WARNING,
                        message="Viewer schema not initialized; run jobctl setup.",
                    )
                )
                return []
            return [
                ViewRecord.model_validate_json(row[0])
                for row in connection.execute("SELECT document FROM jobctl_views")
            ]
    except (JobctlError, sqlite3.Error, OSError, ValidationError) as error:
        report.checks.append(DoctorCheck(name="state", state=CheckState.ERROR, message=str(error)))
        return []


async def doctor(
    settings: Settings, require_rex: bool, fix: bool, probe: bool, layout: ViewLayout | None, bin_dir: Path | None
) -> DoctorReport:
    """Inspect optional Rex and owned state; repairs and real-terminal probes are explicit."""
    report = DoctorReport()
    uv = shutil.which("uv")
    report.checks.append(
        DoctorCheck(
            name="runtime",
            state=CheckState.OK if uv else CheckState.WARNING,
            message=f"Python {platform.python_version()}; uv: {uv or 'not on PATH; use uv run with its full path'}",
        )
    )
    if fix:
        try:
            report.repairs.extend(setup_presentation(settings, layout, bin_dir))
        except (JobctlError, OSError, sqlite3.Error) as error:
            report.checks.append(DoctorCheck(name="setup", state=CheckState.ERROR, message=str(error)))
    views = inspect_state(settings, report)
    try:
        client = RexClient(settings)
        identity = await client.identity()
        capabilities = await client.model(["api", "list", "--json"], RexCapabilities)
        required = {
            "session.new_window",
            "session.new_split",
            "session.list_blocks",
            "session.describe_block",
            "block.method",
            "block.close",
        }
        missing = required - {method.name for method in capabilities.methods}
        if missing:
            raise RexError(RexIssue.RESPONSE, f"Rex lacks required methods: {', '.join(sorted(missing))}")
        report.checks.append(
            DoctorCheck(
                name="rex",
                state=CheckState.OK,
                message=f"Reachable local Rex with required methods: {identity.host_id}",
            )
        )
        if identity.session_id and identity.block_id:
            inspected = await client.model(
                ["block", "inspect", identity.block_id, "-s", identity.session_id, "--json"], RexInspection
            )
            if inspected.block.host_id != identity.host_id:
                raise RexError(RexIssue.REMOTE, "Current pane belongs to another host.")
            report.checks.append(
                DoctorCheck(
                    name="context",
                    state=CheckState.OK,
                    message=f"Live session and pane: {identity.session_id}, {identity.block_id}",
                )
            )
        else:
            report.checks.append(
                DoctorCheck(
                    name="context",
                    state=CheckState.ERROR if require_rex or probe else CheckState.WARNING,
                    message="No live inherited Rex session/pane; open with --session SESSION --layout tab.",
                )
            )
        for record in views:
            if (
                record.host_id != identity.host_id
                or record.endpoint != identity.endpoint
                or record.state is ViewState.CLOSED
            ):
                continue
            try:
                block = await view_block(client, record)
                if block:
                    process = await client.model(
                        ["block", "call", "-s", record.session_id, "-b", block.block_id, "process"], RexProcess
                    )
                    valid = (
                        process.last_exit is None
                        and record.ready_at is not None
                        and record.rendered_revision >= record.revision
                    )
                else:
                    valid = False
                state = CheckState.OK if valid else CheckState.WARNING
                report.checks.append(
                    DoctorCheck(
                        name="view",
                        state=state,
                        message=f"{record.label}: {'ready' if valid else 'stale or not ready'}",
                    )
                )
                if fix and (valid or record.state is ViewState.READY or block is not None):
                    store = RunStore(settings.database)
                    try:
                        with store.edit_view(record.view_key) as current:
                            if current.token == record.token:
                                current.state = ViewState.READY if valid else ViewState.CLOSED
                                if block:
                                    current.block_id = block.block_id
                                    current.window_id = block.window_id
                        report.repairs.append(f"Reconciled {record.label}")
                    finally:
                        store.close()
            except RexError as error:
                report.checks.append(
                    DoctorCheck(name="view", state=CheckState.WARNING, message=f"{record.label}: {error}")
                )
                if fix and error.returncode == 3:
                    # Full recorded IDs cannot be ambiguous: the session was removed, so no late pane can appear there.
                    store = RunStore(settings.database)
                    try:
                        with store.edit_view(record.view_key) as current:
                            if current.token == record.token:
                                current.state = ViewState.CLOSED
                        report.repairs.append(f"Closed stale link for removed session: {record.label}")
                    finally:
                        store.close()
        if probe:
            result = await probe_presentation(settings)
            report.checks.append(DoctorCheck(name="probe", state=CheckState.OK, message=result))
    except (RexError, JobctlError, OSError, sqlite3.Error) as error:
        report.checks.append(
            DoctorCheck(
                name="rex", state=CheckState.ERROR if require_rex or probe else CheckState.WARNING, message=str(error)
            )
        )
    return report


def emit_doctor(report: DoctorReport, as_json: bool) -> None:
    """Both formats describe the same health and explicit repairs."""
    if as_json:
        click.echo(json.dumps({"healthy": report.healthy, **report.model_dump(mode="json")}))
    else:
        for repair in report.repairs:
            click.echo(f"fixed: {repair}")
        for check in report.checks:
            click.echo(f"{check.state.value}: {check.name}: {check.message}")


def announce(
    store: RunStore,
    settings: Settings,
    run: Run,
    verb: str,
    ready_timeout: float,
    as_json: bool,
    open_requested: bool = False,
    layout: ViewLayout | None = None,
    session: str | None = None,
    focus: bool = False,
) -> None:
    """Report a started run; with declared ports, first wait until it listens on them.

    Raises:
        JobNotReady: the job ended, or did not listen in time.
    """
    if not as_json:
        click.echo(f"{verb} {run.job}: process group {run.pgid}, span {run.span_id}, log {run.log_path}")
    if run.declared_ports and ready_timeout > 0:
        asyncio.run(wait_until_ready(store, run, ready_timeout))
        if not as_json:
            click.echo(f"{run.job} is listening on {run.declared_ports}")
    presentation: PresentationResult | None = None
    if open_requested:
        try:
            presentation = asyncio.run(
                open_view(
                    store, settings, JobViewTarget(project=run.project, name=run.name), layout, session, focus=focus
                )
            )
        except (JobctlError, OSError, sqlite3.Error) as error:
            presentation = PresentationResult(
                state="error",
                issue=error.kind if isinstance(error, RexError) else RexIssue.RESPONSE,
                message=str(error),
            )
        if not as_json:
            emit_presentation(presentation, False)
    if as_json:
        document = store.get(run.span_id).model_dump(mode="json")
        if presentation:
            document["presentation"] = presentation.model_dump(mode="json")
        click.echo(json.dumps(document))


@click.command(
    no_args_is_help=True,
    context_settings={
        "ignore_unknown_options": True,
        "help_option_names": ["-h", "--help"],
        "max_content_width": 120,
    },
)
@click.argument("action", type=click.Choice([action.value for action in Action]), metavar="ACTION")
@click.argument("name", default="")
@click.argument("command", nargs=-1, type=click.UNPROCESSED)
@click.option("--project", default=None, help="Project of the job (default: git repository name, else directory name).")
@click.option(
    "--cwd",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("."),
    show_default=True,
    help="start: working directory of the job. orphans: look in the git repository containing it, else in it.",
)
@click.option(
    "--log",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="start: log file (default $JOBCTL_HOME/logs/<project>/<name>/<time>-<span>.log, one per run).",
)
@click.option(
    "--port",
    "ports",
    type=int,
    multiple=True,
    help="start: TCP port the job will listen on; refused if taken, then waited for. Repeatable. "
    "history/export: runs that declared or listened on this port.",
)
@click.option(
    "--ready-timeout",
    type=float,
    default=120.0,
    show_default=True,
    help="start/restart with --port: seconds to wait for the job to listen (0: do not wait).",
)
@click.option("--tag", "tags", multiple=True, help="start: key=value recorded with the run. Repeatable.")
@click.option(
    "--grace", type=float, default=30.0, show_default=True, help="stop/restart: seconds between SIGTERM and SIGKILL."
)
@click.option("--reason", default="", help="stop/restart: why, recorded in the audit table.")
@click.option("--dry-run", is_flag=True, help="stop/restart/prune or skill setup/remove: preview the action; change nothing.")
@click.option("--lines", type=int, default=40, show_default=True, help="logs: lines to print.")
@click.option("--follow", is_flag=True, help="logs: keep printing until the job ends.")
@click.option("--since", default=None, help="status (default 1d)/history/export: 30m, 6h, 2d, 1w or an ISO time.")
@click.option(
    "--state",
    type=click.Choice([state.value for state in RunState]),
    default=None,
    help="history/export: only runs in this state.",
)
@click.option("--grep", default=None, help="history/export: substring of the command, name, project or directory.")
@click.option(
    "--older-than", default=None, help="prune: only runs that ended before this long ago (30m, 6h, 2d, 1w) or ISO time."
)
@click.option("--keep-failed", is_flag=True, help="prune: keep the logs of failed and lost runs.")
@click.option(
    "--rows", is_flag=True, help="prune: also delete the old runs' rows (each job's newest run stays), then VACUUM."
)
@click.option("--limit", type=int, default=30, show_default=True, help="history: newest runs to show (-1: all).")
@click.option(
    "--open",
    "open_requested",
    is_flag=True,
    help="start/restart: open or reuse a Rex viewer; failure does not undo a started job.",
)
@click.option(
    "--layout",
    type=click.Choice([item.value for item in ViewLayout]),
    default=None,
    help="open/start --open: below, right or tab; setup: save default (initially below).",
)
@click.option("--session", default=None, help="Rex destination session; default: the live inherited session.")
@click.option("--new", "new_view", is_flag=True, help="open: create another viewer instead of reusing one.")
@click.option("--focus", is_flag=True, help="Focus the requested Rex view; default preserves your current focus.")
@click.option(
    "--pin",
    is_flag=True,
    help="open/view: pin this run instead of following the job across restarts; span IDs always pin.",
)
@click.option(
    "--fix", is_flag=True, help="doctor: repair jobctl-owned installation/preferences and reconcile recorded views."
)
@click.option(
    "--probe",
    is_flag=True,
    help="doctor: verify a real Rex viewer and detached job with isolated state; clean both up.",
)
@click.option(
    "--require-rex", is_flag=True, help="doctor/setup: fail if Rex or the inherited terminal context is unavailable."
)
@click.option(
    "--bin-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="setup/doctor --fix: directory for the jobctl link (initially ~/.local/bin).",
)
@click.option("--view-id", default=None, hidden=True)
@click.option(
    "--skill-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    show_default=True,
    help="skill/setup/doctor --fix: one skill folder instead of both default agent folders (or JOBCTL_SKILL_DIR).",
)
@click.option(
    "--agent",
    "agents",
    multiple=True,
    type=click.Choice([agent.value for agent in SkillAgent]),
    show_default=True,
    help="skill/setup/doctor --fix: select agents; repeatable. Default installs for Claude and shared agents.",
)
@click.option("--force", is_flag=True, help="skill setup/remove: explicitly replace/remove unrecognized skill assets.")
@click.option("--view-token", default=None, hidden=True)
@click.option("--on-exit", default=None, help="Command to run when the job ends ($JOBCTL_JOB, $JOBCTL_STATE, $JOBCTL_EXIT_CODE).")
@click.option("--check", "check_cmd", default=None, help="In-flight periodic health check command.")
@click.option("--check-interval", type=float, default=60.0, show_default=True, help="Seconds between health checks.")
@click.option(
    "--check-fail-action",
    type=click.Choice(["stop", "continue"]),
    default="stop",
    show_default=True,
    help="Action when health check fails.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Noninteractive actions: JSON output, one object per line (show and dry runs: one document).",
)
def main(
    action: str,
    name: str,
    command: tuple[str, ...],
    project: str | None,
    cwd: Path,
    log: Path | None,
    ports: tuple[int, ...],
    ready_timeout: float,
    tags: tuple[str, ...],
    grace: float,
    reason: str,
    dry_run: bool,
    lines: int,
    follow: bool,
    since: str | None,
    state: str | None,
    grep: str | None,
    older_than: str | None,
    keep_failed: bool,
    rows: bool,
    limit: int,
    open_requested: bool,
    layout: str | None,
    session: str | None,
    new_view: bool,
    focus: bool,
    pin: bool,
    fix: bool,
    probe: bool,
    require_rex: bool,
    bin_dir: Path | None,
    skill_dir: Path | None,
    agents: tuple[str, ...],
    force: bool,
    view_id: str | None,
    view_token: str | None,
    on_exit: str | None,
    check_cmd: str | None,
    check_interval: float,
    check_fail_action: str,
    as_json: bool,
) -> None:
    """Manage named background jobs by process group, with a shared audit table of every run.

    \b
    Actions:
        start NAME -- CMD     start a job (--port P: refuse if P is taken, then wait until the job listens on it)
        stop NAME             stop the job's whole process group (--reason is recorded; --dry-run lists it first)
        stop :PORT | PID      stop what holds a port (a job, or processes jobctl did not start, with their
                              children) or one PID and its children; checks identity, records the stop
        restart NAME          stop, then start again with the recorded command, directory, ports and tags
        status                latest run of every job that is running or ran in --since (default 1d)
        logs NAME             end of the latest run's log (--follow to stream until it ends)
        wait NAME             block until the job ends; exit with its exit code
        ports                 every listening TCP port on the machine, with the job that holds it
        why :PORT | PID       who holds a port or what a PID is: job, directory, age, and the parents that started it
        orphans               processes under this repository whose parent has exited and that no job owns
        prune --older-than D  delete old finished runs' logs (--rows: and their rows; --keep-failed; --dry-run previews)
    prune --older-than D  delete old finished runs' logs (--rows: and their rows; --keep-failed; --dry-run previews)
        history [NAME]        past runs, filtered by --project/--state/--since/--grep/--port
        show NAME|SPAN_ID     every column and event of one run
        sql "SELECT ..."      read-only SQL over the runs table (see `schema` for its columns)
        schema                every column of the runs table, its states, events, and example queries
        export                OTLP/JSON (ExportTraceServiceRequest) of the selected runs
        setup                 initialize jobctl, executable link and skill; discover optional Rex
        skill [show|setup|status|remove]  print the embedded guide or manage the small installed skill
        doctor                read-only health checks; --fix repairs owned setup, --probe tests a real viewer
        open [NAME|SPAN_ID]   open/reuse a Rex dashboard or job view; names follow restarts, span IDs pin
        dashboard             display the jobs dashboard in the current terminal
        view NAME|SPAN_ID     display the terminal job viewer here, without requiring Rex

    NAME may be `project/name`; a bare name resolves in the current project first, then in any single project.

    \b
    Exit codes:
        0 ok   1 other error   2 bad input   3 job, process or listener not found   4 permission denied
        5 conflict: already running, port busy   6 not ready: died or did not listen; port still busy after stop
        7 refused: PID reused, target runs this jobctl, or PID belongs to a job
        8 Rex presentation failed; optional start/restart --open still reports successful job startup separately
        wait exits with the job's own code; use --json to tell the two apart

    \b
    Examples:
        jobctl status
        jobctl start web --port 8081 -- uv run scripts/serve.py --port 8081
        jobctl logs web --lines 50
        jobctl stop web --reason "new export"
        jobctl why :3000
        jobctl stop :3000 --dry-run
        jobctl orphans
        jobctl history --since 7d --grep train
        jobctl schema
        jobctl sql "SELECT project, name, state, exit_code FROM runs ORDER BY start_time_unix_nano DESC LIMIT 10"
    """
    settings = Settings()
    if skill_dir is not None:
        settings = settings.model_copy(update={"skill_dir": skill_dir})
    if agents:
        if settings.skill_dir is not None:
            raise BadInput("--agent cannot be combined with --skill-dir or JOBCTL_SKILL_DIR.")
        settings = settings.model_copy(update={"skill_agents": tuple(SkillAgent(agent) for agent in agents)})
    chosen = Action(action)
    if chosen is Action.SKILL:
        skill_command(name, command, settings, dry_run, force, as_json)
        return
    selected_layout = ViewLayout(layout) if layout else None
    if chosen in {Action.SETUP, Action.DOCTOR}:
        try:
            repairs = setup_presentation(settings, selected_layout, bin_dir) if chosen is Action.SETUP else []
            health_report = asyncio.run(doctor(settings, require_rex, fix, probe, selected_layout, bin_dir))
            health_report.repairs = repairs + health_report.repairs
        except (JobctlError, OSError, sqlite3.Error) as error:
            health_report = DoctorReport(checks=[DoctorCheck(name="setup", state=CheckState.ERROR, message=str(error))])
        emit_doctor(health_report, as_json)
        if not health_report.healthy:
            raise click.exceptions.Exit(1)
        return
    if chosen is Action.SUPERVISE:
        sys.exit(asyncio.run(supervise(settings, name)))
    if chosen is Action.SQL:
        query_rows = read_only_query(settings.database, " ".join((name, *command)))
        if as_json:
            for row in query_rows:
                click.echo(json.dumps(row))
        else:
            click.echo(
                render_table(
                    [{key: "" if value is None else str(value) for key, value in row.items()} for row in query_rows],
                    width=120,
                )
                or "no rows"
            )
        return
    needs_name = {
        Action.START,
        Action.STOP,
        Action.RESTART,
        Action.LOGS,
        Action.WAIT,
        Action.SHOW,
        Action.WHY,
        Action.VIEW,
    }
    if chosen in needs_name and not name:
        raise BadInput(f"{action} needs a job name" if chosen is not Action.WHY else "why needs :PORT or a PID")
    current_project = project or default_project(cwd.expanduser())
    store = RunStore(settings.database)
    if chosen is Action.SCHEDULE_RUN:
        schedule_id = name
        sched = store.get_schedule_by_id(schedule_id)
        if not sched or not sched.enabled:
            return
        running = store.select("project = ? AND name = ? AND state = ?", (sched.project, sched.name, RunState.RUNNING.value))
        if running:
            with store.edit_schedule(schedule_id) as cur:
                cur.last_state = "skipped_overlap"
            if sched.is_recurring:
                delay, _ = parse_schedule_expression(sched.expression)
                next_nano = int((time.time() + delay) * 1e9)
                new_pgid, new_started = spawn_trampoline(schedule_id, delay, Path(__file__).resolve(), settings)
                with store.edit_schedule(schedule_id) as cur:
                    cur.trampoline_pgid = new_pgid
                    cur.trampoline_leader_started = new_started
                    cur.next_run_unix_nano = next_nano
            return
        run = start(
            store=store,
            settings=settings,
            name=sched.name,
            project=sched.project,
            command=sched.command,
            cwd=Path(sched.cwd),
            log=Path(sched.log_path) if sched.log_path else None,
            ports=sched.declared_ports,
            tags=sched.tags,
        )
        with store.edit_schedule(schedule_id) as cur:
            cur.last_run_unix_nano = run.start_time_unix_nano
            cur.last_span_id = run.span_id
            cur.last_state = run.state.value
            cur.total_runs += 1
            if sched.is_recurring:
                delay, _ = parse_schedule_expression(sched.expression)
                next_nano = int((time.time() + delay) * 1e9)
                new_pgid, new_started = spawn_trampoline(schedule_id, delay, Path(__file__).resolve(), settings)
                cur.trampoline_pgid = new_pgid
                cur.trampoline_leader_started = new_started
                cur.next_run_unix_nano = next_nano
            else:
                cur.enabled = False
                cur.trampoline_pgid = None
        return

    if chosen is Action.SCHEDULE:
        subaction = name or "list"
        reconcile_schedules(store, settings, Path(__file__).resolve())
        match subaction:
            case "list":
                condition = "project = ?" if project else "1"
                params = (project,) if project else ()
                schedules = store.select_schedules(condition, params)
                if as_json:
                    for s in schedules:
                        click.echo(s.model_dump_json())
                else:
                    schedule_rows = [
                        {
                            "name": s.name,
                            "project": s.project,
                            "expression": s.expression,
                            "recurring": "yes" if s.is_recurring else "no",
                            "enabled": "yes" if s.enabled else "no",
                            "last_state": s.last_state or "-",
                            "runs": str(s.total_runs),
                            "command": s.command_line,
                        }
                        for s in schedules
                    ]
                    click.echo(render_table(schedule_rows, width=120) or "no schedules")
                return
            case "add":
                if not command or len(command) < 2:
                    raise BadInput("schedule add needs: NAME EXPRESSION -- COMMAND...")
                sched_name = command[0]
                expression = command[1]
                cmd_args = list(command[2:])
                if cmd_args and cmd_args[0] == "--":
                    cmd_args = cmd_args[1:]
                if not cmd_args:
                    raise BadInput("schedule add needs a command after --")
                check_name("job name", sched_name)
                check_name("project", current_project)
                existing = store.get_schedule(current_project, sched_name)
                if existing and existing.enabled:
                    cancel_trampoline(existing.trampoline_pgid, existing.trampoline_leader_started)
                delay, is_recurring = parse_schedule_expression(expression)
                sched_id = secrets.token_hex(8)
                now = time.time_ns()
                next_nano = int((now / 1e9 + delay) * 1e9)
                sched_tags = parse_tags(tags)
                if on_exit:
                    sched_tags["jobctl.on_exit"] = on_exit
                if check_cmd:
                    sched_tags["jobctl.check"] = check_cmd
                    sched_tags["jobctl.check_interval"] = str(check_interval)
                    sched_tags["jobctl.check_fail_action"] = check_fail_action
                sched = Schedule(
                    schedule_id=sched_id,
                    name=sched_name,
                    project=current_project,
                    expression=expression,
                    delay_seconds=delay,
                    is_recurring=is_recurring,
                    command=cmd_args,
                    command_line=shlex.join(cmd_args),
                    cwd=str(cwd.expanduser().resolve()),
                    log_path=str(log) if log else None,
                    declared_ports=sorted(set(ports)),
                    tags=sched_tags,
                    on_exit=on_exit,
                    check_cmd=check_cmd,
                    check_interval=check_interval if check_cmd else None,
                    check_fail_action=check_fail_action,
                    enabled=True,
                    next_run_unix_nano=next_nano,
                    created_at=iso(now),
                    updated_at=iso(now),
                )
                pgid, started = spawn_trampoline(sched_id, delay, Path(__file__).resolve(), settings)
                sched.trampoline_pgid = pgid
                sched.trampoline_leader_started = started
                store.insert_schedule(sched)
                if as_json:
                    click.echo(sched.model_dump_json())
                else:
                    rec_str = "recurring" if is_recurring else "one-shot"
                    click.echo(f"scheduled {current_project}/{sched_name} ({rec_str}, {expression}, next in {delay:.1f}s, timer PID {pgid})")
                return
            case "cancel":
                if not command:
                    raise BadInput("schedule cancel needs a job name")
                sched_name = command[0]
                sched = store.get_schedule(current_project, sched_name)
                if not sched:
                    raise JobNotFound(f"no schedule named {sched_name!r} in project {current_project!r}")
                cancelled = cancel_trampoline(sched.trampoline_pgid, sched.trampoline_leader_started)
                with store.edit_schedule(sched.schedule_id) as cur:
                    cur.enabled = False
                    cur.trampoline_pgid = None
                if as_json:
                    click.echo(json.dumps({"cancelled": True, "job": sched.job, "timer_killed": cancelled}))
                else:
                    click.echo(f"cancelled schedule {sched.job} (timer stopped: {cancelled})")
                return
            case "trigger":
                if not command:
                    raise BadInput("schedule trigger needs a job name")
                sched_name = command[0]
                sched = store.get_schedule(current_project, sched_name)
                if not sched:
                    raise JobNotFound(f"no schedule named {sched_name!r} in project {current_project!r}")
                run = start(
                    store=store,
                    settings=settings,
                    name=sched.name,
                    project=sched.project,
                    command=sched.command,
                    cwd=Path(sched.cwd),
                    log=Path(sched.log_path) if sched.log_path else None,
                    ports=sched.declared_ports,
                    tags=sched.tags,
                )
                with store.edit_schedule(sched.schedule_id) as cur:
                    cur.last_run_unix_nano = run.start_time_unix_nano
                    cur.last_span_id = run.span_id
                    cur.last_state = run.state.value
                    cur.total_runs += 1
                announce(store, settings, run, "started (manual trigger)", ready_timeout, as_json)
                return
            case _:
                raise BadInput(f"unknown schedule action {subaction!r}; use add, list, cancel, trigger")

    port_filter = ports[0] if ports else None
    try:
        match chosen:
            case Action.OPEN | Action.DASHBOARD | Action.VIEW:
                try:
                    presentation_target: ViewTarget = (
                        DashboardTarget(project=project)
                        if chosen is Action.DASHBOARD or (chosen is Action.OPEN and not name)
                        else view_target(store, name, current_project, pin)
                    )
                    if chosen in {Action.VIEW, Action.DASHBOARD}:
                        if as_json:
                            raise BadInput("Terminal views do not emit JSON. Use show, logs, status or wait --json.")
                        try:
                            asyncio.run(terminal_view(store, settings, presentation_target, view_id, view_token))
                        except KeyboardInterrupt:
                            # An interrupted managed viewer is a deliberate detach, not a quick startup failure.
                            if view_id is None or view_token is None:
                                raise
                    else:
                        result = asyncio.run(
                            open_view(store, settings, presentation_target, selected_layout, session, new_view, focus)
                        )
                        emit_presentation(result, as_json)
                except RexError as error:
                    if as_json:
                        emit_presentation(PresentationResult(state="error", issue=error.kind, message=str(error)), True)
                        raise click.exceptions.Exit(error.exit_code) from error
                    raise
            case Action.START:
                start_tags = parse_tags(tags)
                if on_exit:
                    start_tags["jobctl.on_exit"] = on_exit
                if check_cmd:
                    start_tags["jobctl.check"] = check_cmd
                    start_tags["jobctl.check_interval"] = str(check_interval)
                    start_tags["jobctl.check_fail_action"] = check_fail_action
                run = start(
                    store, settings, name, current_project, list(command), cwd, log, list(ports), start_tags
                )
                announce(
                    store,
                    settings,
                    run,
                    "started",
                    ready_timeout,
                    as_json,
                    open_requested,
                    selected_layout,
                    session,
                    focus,
                )
            case Action.STOP:
                target = parse_process_target(name)
                plan = plan_stop(store, target) if target else job_plan(resolve(store, name, current_project))
                if dry_run:
                    echo_plan(describe_plan(plan, grace), as_json)
                else:
                    runs = asyncio.run(execute_stop(store, settings, plan, current_project, grace, reason))
                    echo_runs(runs, as_json, "nothing to stop")
            case Action.RESTART:
                previous = resolve(store, name, current_project)
                if dry_run:
                    document = describe_plan(job_plan(previous), grace)
                    document["then_start"] = {
                        "command": previous.command,
                        "cwd": previous.cwd,
                        "ports": previous.declared_ports,
                        "tags": previous.tags,
                    }
                    echo_plan(document, as_json)
                else:
                    asyncio.run(stop(store, settings, previous, grace, reason or "restart"))
                    run = start(
                        store,
                        settings,
                        previous.name,
                        previous.project,
                        previous.command,
                        Path(previous.cwd),
                        None,
                        previous.declared_ports,
                        previous.tags,
                    )
                    announce(
                        store,
                        settings,
                        run,
                        "restarted",
                        ready_timeout,
                        as_json,
                        open_requested,
                        selected_layout,
                        session,
                        focus,
                    )
            case Action.STATUS:
                reconcile(store)
                where = "(state = ? OR start_time_unix_nano >= ? OR end_time_unix_nano >= ?)"
                cutoff = parse_since(since or "1d")
                condition = f"{where} AND project = ?" if project else where
                parameters = (RunState.RUNNING.value, cutoff, cutoff, *((project,) if project else ()))
                echo_runs(store.latest(condition, parameters), as_json, f"no jobs ran in the last {since or '1d'}")
            case Action.LOGS:
                run = resolve(store, name, current_project)
                if follow:
                    asyncio.run(follow_log(store, run, lines))
                else:
                    click.echo(tail(Path(run.log_path), lines))
            case Action.WAIT:
                run = asyncio.run(wait(store, resolve(store, name, current_project)))
                echo_runs([run], as_json, "")
                sys.exit(run.exit_code if run.exit_code is not None else 1)
            case Action.PORTS:
                reconcile(store)
                listeners = asyncio.run(listening_sockets())
                jobs = job_by_group(store)
                port_rows: list[dict[str, str]] = []
                for listener in sorted(listeners, key=lambda item: (item.port, item.address)):
                    owner = jobs.get(listener.pgid) if listener.pgid is not None else None
                    port_rows.append(
                        {
                            "port": str(listener.port),
                            "address": listener.address,
                            "pid": str(listener.pid),
                            "job": owner.job if owner else "",
                            "state": state_label(owner) if owner else "",
                            "command": owner.command_line if owner else listener.command,
                        }
                    )
                unique = list({(row["port"], row["address"], row["pid"]): row for row in port_rows}.values())
                if as_json:
                    for row in unique:
                        click.echo(json.dumps(row))
                else:
                    click.echo(render_table(unique) or "no listening TCP ports")
            case Action.HISTORY:
                reconcile(store)
                condition, parameters = history_filter(project, name, state, since, grep, port_filter)
                echo_runs(store.select(condition, parameters, limit), as_json, "no matching runs")
            case Action.SHOW:
                reconcile(store)
                run = resolve(store, name, current_project)
                click.echo(run.model_dump_json(indent=2) if as_json else show(run))
            case Action.SCHEMA:
                schema = describe_schema(store, settings.database)
                click.echo(json.dumps(schema) if as_json else render_schema(schema))
            case Action.WHY:
                target = parse_process_target(name)
                if target is None:
                    raise BadInput(f"why takes :PORT or a PID, not {name!r}; for a job use: jobctl show {name}")
                reports = explain(store, target)
                if as_json:
                    for report in reports:
                        click.echo(json.dumps(report))
                else:
                    click.echo("\n\n".join(render_explanation(report, target) for report in reports))
            case Action.ORPHANS:
                directory = cwd.expanduser().resolve()
                scope = Path(run_quietly(["git", "rev-parse", "--show-toplevel"], directory) or directory).resolve()
                orphans = find_orphans(store, scope)
                if as_json:
                    for report in orphans:
                        click.echo(json.dumps(report))
                elif orphans:
                    click.echo(f"processes under {scope} whose parent has exited, owned by no job:")
                    click.echo(render_table([orphan_row(report, scope) for report in orphans]))
                    click.echo("inspect one with `jobctl why PID`; stop it and its children with `jobctl stop PID`")
                else:
                    click.echo(f"no orphaned processes under {scope}")
            case Action.PRUNE:
                if not older_than:
                    raise BadInput("prune needs --older-than, for example --older-than 30d")
                reconcile(store)
                candidates = prune_candidates(store, settings, project, name, grep, older_than, keep_failed, rows)
                freed = sum(candidate.log_bytes for candidate in candidates)
                deleted_rows = sum(candidate.delete_row for candidate in candidates)
                if not dry_run:
                    prune(store, settings, candidates)
                if as_json:
                    click.echo(
                        json.dumps(
                            {
                                "dry_run": dry_run,
                                "runs": len(candidates),
                                "logs": sum(candidate.log is not None for candidate in candidates),
                                "rows": deleted_rows,
                                "bytes": freed,
                                "spans": [candidate.span_id for candidate in candidates],
                            }
                        )
                    )
                elif candidates:
                    click.echo(
                        render_table(
                            [
                                {
                                    "job": candidate.job,
                                    "state": candidate.state,
                                    "ended": candidate.ended,
                                    "size": format_bytes(candidate.log_bytes) if candidate.log else "-",
                                    "span": candidate.span_id,
                                }
                                for candidate in candidates
                            ]
                        )
                    )
                    verb = "would delete" if dry_run else "deleted"
                    row_note = f" and {deleted_rows} rows" if deleted_rows else ""
                    click.echo(f"{verb} {format_bytes(freed)} of logs{row_note} from {len(candidates)} runs")
                else:
                    click.echo(f"nothing to prune older than {older_than}")
            case Action.EXPORT:
                reconcile(store)
                condition, parameters = history_filter(project, name, state, since, grep, port_filter)
                click.echo(json.dumps(to_otlp(store.select(condition, parameters))))
    finally:
        store.close()


if __name__ == "__main__":
    main()
