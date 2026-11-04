---
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
---

# Jobs

Before executing task commands, run `jobctl skill show` and follow its guide.
Use jobctl throughout the task: inspect existing runs, start named work, monitor
progress, verify the recorded outcome, and clean up only task-owned processes.
The complete guide is embedded in the script and matches its version.

## Bundled command

If `jobctl` is not on PATH, use the bundled [scripts/jobctl.py](scripts/jobctl.py).
Resolve its absolute path relative to this `SKILL.md`, then run:

```sh
uv run /absolute/path/to/this/skill/scripts/jobctl.py skill show
```

Use that same `uv run /absolute/path/to/this/skill/scripts/jobctl.py` prefix in
place of `jobctl` for subsequent commands. Quote the path if it contains spaces.
Do not assume the plugin is installed in a particular user directory.

The bundled runner requires `uv` and a Unix-like host (macOS or Linux). Its inline
metadata pins Python and dependencies. Rex is optional for terminal views;
headless execution and recorded results work without it. Installing this plugin
does not require running `jobctl setup` or copying another skill into user settings.
