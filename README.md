# Analytical Team marketplace

Reusable coding skills for ChatGPT and Claude Code. The first plugin,
**python-coding**, packages Analytical Team's Python conventions and full style
guide for writing, refactoring, and reviewing Python.

## Install in Claude Code

Run these commands inside Claude Code:

```text
/plugin marketplace add analytical-team/marketplace
/plugin install python-coding@analytical-team
```

Start a new session, then invoke `/python-coding:python-coding` with your task.
Claude can also select the skill automatically for relevant Python work.

See the [Claude Code marketplace guide](https://code.claude.com/docs/en/plugin-marketplaces).

## Install in ChatGPT desktop

For ChatGPT Work or Codex in the desktop app, register the Git marketplace using
Codex CLI:

```sh
codex plugin marketplace add analytical-team/marketplace
```

Restart ChatGPT, open the Plugins Directory, select **Analytical Team**, and
install **Python Coding**. Start a new conversation and select the skill from
the mention menu, or ask it to use Python Coding for your task.

For local development before the repository is published:

```sh
codex plugin marketplace add /absolute/path/to/marketplace
```

Repository marketplaces are a desktop/team distribution route. Availability
depends on the client and workspace policy; adding this repository does not
publish the plugin to the public ChatGPT directory. See OpenAI's
[plugin packaging and marketplace guide](https://developers.openai.com/plugins/build/plugins).

## Included skill

[`python-coding`](plugins/python-coding/skills/python-coding/SKILL.md) covers
strict typing, structured concurrency, protocol-based APIs, settings, typed
errors, parsing at trust boundaries, integration testing, and report generation.
Its [full style guide](plugins/python-coding/skills/python-coding/references/style-guide.md)
includes rationale and examples.

This is an opinionated house style. The plugin contains instructions and
references; it does not install Python, dependencies, services, or hooks.
Following its workflows requires `uv` and the tools appropriate to the task,
such as Ruff, mypy, pytest, and mdreport for report generation.

## Repository layout

```text
.agents/plugins/marketplace.json      ChatGPT / Codex catalog
.claude-plugin/marketplace.json       Claude Code catalog
plugins/python-coding/
  plugin.json                        Portable plugin manifest and OpenAI metadata
  .claude-plugin/plugin.json          Claude Code manifest
  skills/python-coding/
    SKILL.md                         Shared instructions for both platforms
    agents/openai.yaml               Skill presentation and invocation metadata
    references/style-guide.md        Full Python style guide
```

## Add or update a skill

Keep each independently installable plugin in `plugins/<name>/`, with its skills
under `skills/<skill-name>/SKILL.md`. Keep supporting references inside the
plugin so installation never depends on files elsewhere on a maintainer's Mac.
Register new plugins in both catalogs, using paths relative to this repository's
root. Keep names, versions, and descriptions consistent across plugin manifests.
Bump the plugin version when shipping changes.

Validate the Claude catalog and plugin from the repository root:

```sh
claude plugin validate .
claude plugin validate ./plugins/python-coding
```

For a local Claude session without installing the marketplace:

```sh
claude --plugin-dir ./plugins/python-coding
```

Before releasing, install through each client's local marketplace flow and
confirm that the skill and its bundled style guide load in a new session.
