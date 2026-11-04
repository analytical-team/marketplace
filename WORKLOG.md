# Worklog

## 2026-11-04 12:38 EST — Initial marketplace

- Goal: distribute `python-coding` through one Git repository to ChatGPT and Claude Code.
- Repository started empty. Reuse the existing local Python skill and its full reference guide.
- Use two platform catalogs pointing at one plugin directory and one shared skill tree.
- Use a portable root manifest with OpenAI presentation metadata and a Claude compatibility manifest.
- Acceptance: valid catalogs and manifests, bundled reference available after installation, documented installation for both clients.
- No public directory submission or changes to personal plugin settings are part of this setup.

## 2026-11-04 12:39 EST — Validation

- Imported `SKILL.md` and `references/style-guide.md` unchanged from the existing local skill.
- Skill Creator's validator passed; both Claude manifests passed native validation with no warnings after adding the catalog description.
- Installed through each local marketplace using temporary `CODEX_HOME` and `CLAUDE_CONFIG_DIR` directories under `/tmp/marketplace-install.3tAz1G`.
- Codex lists version `0.1.0` installed and enabled. Claude's component inventory reports exactly one skill, `python-coding`.
- Checked catalog names and source paths agree; plugin manifest names, versions, and descriptions agree.
- Both installed skill directories match the source tree exactly, including the full style guide and OpenAI skill metadata.
- No Python implementation was added; linting and type checking do not apply to Markdown, JSON, and YAML packaging.
- ChatGPT desktop UI installation and model behavior have not been exercised. Repository files are local and have not been committed or pushed.

## 2026-11-04 12:47 EST — TypeScript and Swift plugins

- Removed the README's first-plugin wording and documented Python, TypeScript, and Swift installation and invocation.
- Added independently installable `typescript-coding` and `swift-coding` plugins to both catalogs, with portable manifests, Claude manifests, and OpenAI skill metadata.
- Imported both local coding skills and their full style guides. Shortened TypeScript's discovery description to satisfy the 1,024-character frontmatter limit; retained its instructions and reference guide.
- Native Claude manifest validation and Skill Creator validation passed for both new plugins.
- Both plugins installed through isolated Claude and Codex marketplace profiles; Claude inventories each bundled skill and Codex reports them enabled.
- Changes contain documentation and packaging only; no TypeScript or Swift implementation was added.
- Commit identity: Tycho Engineering <tychoengr@gmail.com>; no coauthor attribution.
