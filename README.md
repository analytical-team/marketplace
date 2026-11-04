# Analytical Team marketplace

Reusable coding skills for ChatGPT and Claude Code. Each plugin packages
Analytical Team's conventions and full style guide for writing, refactoring,
and reviewing code.

## Install in Claude Code

Run these commands inside Claude Code:

```text
/plugin marketplace add analytical-team/marketplace
/plugin install python-coding@analytical-team
/plugin install typescript-coding@analytical-team
/plugin install swift-coding@analytical-team
```

Install the plugins you want. Start a new session, then invoke
`/python-coding:python-coding`, `/typescript-coding:typescript-coding`, or
`/swift-coding:swift-coding` with your task. Claude can also select the relevant
skill automatically.

See the [Claude Code marketplace guide](https://code.claude.com/docs/en/plugin-marketplaces).

## Install in ChatGPT desktop

For ChatGPT Work or Codex in the desktop app, register the Git marketplace using
Codex CLI:

```sh
codex plugin marketplace add analytical-team/marketplace
```

Restart ChatGPT, open the Plugins Directory, select **Analytical Team**, and
install **Python Coding**, **TypeScript Coding**, or **Swift Coding**. Start a
new conversation and select the skill from the mention menu, or ask it to use
the coding skill for your task.

For local development:

```sh
codex plugin marketplace add /absolute/path/to/marketplace
```

Repository marketplaces are a desktop/team distribution route. Availability
depends on the client and workspace policy; adding this repository does not
publish the plugin to the public ChatGPT directory. See OpenAI's
[plugin packaging and marketplace guide](https://developers.openai.com/plugins/build/plugins).

## Included skills

[`python-coding`](plugins/python-coding/skills/python-coding/SKILL.md) covers
strict typing, structured concurrency, protocol-based APIs, settings, typed
errors, parsing at trust boundaries, integration testing, and report generation.
Its [topic guides](plugins/python-coding/skills/python-coding/SKILL.md#reference-guides)
include rationale and examples, loaded as needed.

[`typescript-coding`](plugins/typescript-coding/skills/typescript-coding/SKILL.md)
covers strict TypeScript, React, Vite, boundary parsing, async work,
accessibility, browser security, and testing. Its
[full style guide](plugins/typescript-coding/skills/typescript-coding/references/style-guide.md)
includes rationale and examples.

[`swift-coding`](plugins/swift-coding/skills/swift-coding/SKILL.md) covers Swift
concurrency, actors, protocol-based APIs, typed errors, SwiftUI, testing, and
linting. Its [full style guide](plugins/swift-coding/skills/swift-coding/references/style-guide.md)
includes rationale and examples.

These are opinionated house styles. The plugins contain instructions and
references; they do not install language runtimes, dependencies, services, or
hooks. Following their workflows requires the tools appropriate to the project.

## Repository layout

```text
.agents/plugins/marketplace.json      ChatGPT / Codex catalog
.claude-plugin/marketplace.json       Claude Code catalog
plugins/<name>/
  plugin.json                        Portable plugin manifest and OpenAI metadata
  .claude-plugin/plugin.json          Claude Code manifest
  skills/<name>/
    SKILL.md                         Shared instructions for both platforms
    agents/openai.yaml               Skill presentation and invocation metadata
    references/                      Language guides, organized by topic as needed
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
claude plugin validate ./plugins/typescript-coding
claude plugin validate ./plugins/swift-coding
```

For a local Claude session without installing the marketplace:

```sh
claude --plugin-dir ./plugins/python-coding
```

Before releasing, install through each client's local marketplace flow and
confirm that the skill and its bundled style guide load in a new session.
