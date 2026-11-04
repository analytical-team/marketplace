# Analytical Team marketplace

Skills for ChatGPT and Claude Code.

## Install in Claude Code

Run inside Claude Code, choosing the skills you want:

```text
/plugin marketplace add analytical-team/marketplace
/plugin install python-coding@analytical-team
/plugin install typescript-coding@analytical-team
/plugin install swift-coding@analytical-team
/plugin install jobs@analytical-team
```

Start a new session. Skills activate for relevant tasks, or you can invoke one
directly, such as `/python-coding:python-coding` or `/jobs:jobs`.

## Install in ChatGPT desktop

Register the marketplace with Codex CLI:

```sh
codex plugin marketplace add analytical-team/marketplace
```

Restart ChatGPT, open the Plugins Directory, select **Analytical Team**, and
install the skills you want. Start a new conversation and select a skill from
the mention menu. Marketplace availability depends on your client and workspace.

## Available skills

| Skill | Use for |
| --- | --- |
| [Python Coding](plugins/python-coding/skills/python-coding/SKILL.md) | Writing and reviewing Python |
| [TypeScript Coding](plugins/typescript-coding/skills/typescript-coding/SKILL.md) | Writing and reviewing TypeScript and React |
| [Swift Coding](plugins/swift-coding/skills/swift-coding/SKILL.md) | Writing and reviewing Swift and SwiftUI |
| [Jobs](plugins/jobs/skills/jobs/SKILL.md) | Running and tracking builds, tests, servers, and other commands |

Jobs includes `jobctl` and requires `uv` on macOS or Linux. Rex is optional for
terminal views. Coding skills use your project's language tools.
