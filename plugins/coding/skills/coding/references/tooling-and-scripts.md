# Tooling, scripts, and environment hygiene

This guide defines operational standards for running commands, managing processes, scripting repository tooling,
handling environment secrets, and tracking work across sessions.

---

## 1. Process management with `jobctl`

All non-trivial command execution, background services, build pipelines, and regression runs should be managed through
`jobs` (`jobctl`) when installed. Otherwise use the project's existing command
runner and preserve explicit process ownership and recorded outcomes.

### Why `jobctl` is required
- Provides deterministic task isolation, span IDs, execution receipts, and persistent structured logs.
- Allows monitoring background runs and checking exit status cleanly.
- Enables safe cleanup of task-owned processes upon completion or cancellation.

### Never kill processes blindly
> [!CAUTION]
> **Never use `pkill`, `pgrep`, `killall`, or manual PIDs with `kill`.**
> Pattern-matching process commands (e.g. `pkill -f node` or `killall python`) can match unrelated user processes,
> terminate developer daemons, or kill other sessions. Manage and terminate processes exclusively through their owned
> `jobctl` span or process handle.

---

## 2. Interactive terminal control with `rex`

For programs that require an interactive terminal (TUI applications, REPLs, interactive CLI wizards, pagers, or text
editors), use Rex when available, or the project's existing terminal tooling.

- `rex` manages real pseudo-terminals (PTYs), arranges panes, and drives keyboard input.
- Allows reading actual terminal screen renders, verifying visual output, scrolling short vs. tall content, testing
  interactive quit sequences, and confirming terminal restoration upon exit.

---

## 3. Tooling scripts: Python with `uv run`

Regardless of the primary programming language of the application codebase (whether Swift, TypeScript, Go, or Rust),
all auxiliary developer scripts, code generators, build helpers, and maintenance tooling must be written in Python and
executed exclusively via `uv run`.

### Rules for Python scripts
1. **Never call `python` or `python3` directly**: Always execute scripts via `uv run <script_path>`.
2. **Self-contained with inline dependencies (PEP 723)**: Every script must declare its dependencies and pinned Python
   version in an inline script block:
   ```python
   #!/usr/bin/env -S uv run --script
   #
   # /// script
   # requires-python = "==3.12.*"
   # dependencies = [
   #     "click==8.5.0",
   #     "pydantic==2.12.0",
   #     "pydantic-settings==2.10.0",
   # ]
   # [tool.uv]
   # exclude-newer = "2026-09-22T00:00:00Z"
   # ///
   ```
   - Pin all dependency versions.
   - Pin `requires-python = "==3.12.*"` (avoiding `">=3.12"` which can pick unverified newer interpreters without wheels).
3. **No ad-hoc shell scripts**: Shell scripts are error-prone and platform-dependent. Avoid shell scripts for any task
   containing logic, branching, or loops. Prefer Python with `uv run`.
4. **Self-contained scripts**: Scripts should not import from sibling scripts directly; common logic should be in
   explicit libraries or self-contained in the script.

### Numbered script organization
Organize repository tooling under `scripts/` using unique, three-digit prefixes that indicate purpose and phase:

| Category | Range | Purpose |
| --- | --- | --- |
| **Developer Tools** | `000`–`099` | Local developer tooling, snapshots, environment checks, fakes, fixtures. |
| **Build & Release** | `100`–`199` | Compilation, code signing, packaging, container builds, release automation. |
| **Code Generation** | `200`–`299` | Schema generation, protocol buffers, API client generation, vendoring. |
| **Assets & Media** | `300`–`399` | Asset optimization, image generation, icon rendering, font processing. |
| **Site & Services** | `400`–`499` | Documentation static site builds, search indexes, internal dashboards, cloud runners. |

### Linting and formatting tooling scripts
Maintain Python scripts with Ruff:
```sh
uvx ruff check --fix --select I,F,E,W,UP,B --line-length 120 scripts && uvx ruff format --line-length 120 scripts
```

---

## 4. Environment variable and secret hygiene

- **Keep configuration in `.env`**: Store local configuration variables and API keys in `.env`. Load them using
  `pydantic-settings` or `python-dotenv` in scripts.
- **Development overrides in `.env.dev`**: Any dev-specific or testing-specific overrides belong in `.env.dev` and
  override `.env` values.
- **Never commit environment files**: Keep `.env`, `.env.dev`, private keys, and signing certificates strictly out of
  version control (ensure they are listed in `.gitignore`).
- **Application runtime inheritance**: Application binaries should inherit standard environment variables from the
  parent environment or explicit CLI flags; the core app should not directly parse arbitrary `.env` files unless
  explicitly configured as a developer server mode.

---

## 5. Visual validation and screenshot discipline

When documenting visible UI changes or verifying graphical rendering:
- **Never take whole-screen screenshots**: Capturing the entire desktop risks leaking private user information, background
  windows, notifications, and desktop files.
- **Window-only capture**: Capture only the specific application window, terminal pane, or browser tab needed for the
  task.
- **Offscreen rendering fallback**: If window capture is unavailable, use offscreen rendering (e.g. headless browser
  screenshot or virtual framebuffer) or document the limitation; never fall back to full desktop capture.

---

## 6. Worklog tracking and continuity

Maintain a running `WORKLOG.md` in the project root:
- Format each entry with a timestamp: `date "+%Y-%m-%d %H:%M:%S"`.
- Record:
  - What was accomplished and why.
  - Explicit architectural decisions and tradeoffs.
  - Concrete verification evidence (commands executed, job spans, test outcomes).
  - Next steps and pending questions.
- A well-maintained worklog enables subagents and human collaborators to immediately understand project context and
  avoid repeating failed approaches across sessions.
