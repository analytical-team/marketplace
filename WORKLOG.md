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

## 2026-11-04 12:49 EST — Python topic guides

- Split the 2,028-line Python guide into an overview and sixteen topic files using parsed Markdown heading boundaries, preserving all original content exactly.
- Added direct links to every topic in `SKILL.md`, with guidance to load only the topics needed for the task, and updated the code-review reference.
- Replaced the README's monolithic Python guide link with the topic index and bumped both Python plugin manifests to `0.1.1`.
- Removed `references/style-guide.md`; the split files retain original section numbers so existing section cross-references remain meaningful.
- The temporary migration script checks exact content preservation and refuses to overwrite destinations. It is outside the repository.
- Parsed-link verification confirms that every local documentation link resolves and `SKILL.md` directly references all seventeen topic files.
- Skill and native Claude validations passed. Isolated Claude and Codex installations of `0.1.1` preserve the complete skill directory, including every topic file.
- Both temporary Python scripts pass Ruff and strict mypy checks.

## 2026-11-04 12:52 EST — Jobs plugin

- Added `jobs` to both marketplace catalogs, with portable and Claude manifests and OpenAI skill metadata.
- Bundled the existing standalone `jobctl.py` runtime, including its embedded guide and pinned dependencies. The skill resolves this bundled copy when `jobctl` is absent from PATH.
- Documented `uv` and macOS/Linux requirements and optional Rex views. No global command links or personal skill settings are installed by the plugin.
- Fixed local table variable names in the imported CLI that conflicted with its boolean `rows` option under strict mypy; command behavior is unchanged.
- Skill and native Claude manifest validations passed. Initial isolated installations preserved the bundled files and an installed runtime successfully recorded a completed job.
- The existing isolated CLI integration suite passed again after the variable rename, covering skill setup conflicts, headless operation, scheduling, health checks, cancellation, and pruning.
- Final isolated Claude and Codex installations preserve every bundled file. Ruff and strict mypy pass for the bundled runtime.
- Trimmed the README to installation, invocation, available skills, and runtime requirements.

## 2026-11-04 — Repository access policy

- User requested that only the `tychoengr` GitHub account can push and that pull requests are not accepted.
- Added a pull-request-target workflow that closes opened or reopened PRs, with pull-request write permission and no checkout or execution of contributor code. Added a short contribution policy.
- Applied active all-branch ruleset 26551916 and all-tag ruleset 26551923, restricting creation, updates, and deletion to `tychoengr` (GitHub user ID 251394477), with no role or administrator bypass.
- GitHub does not provide a repository setting to disable PR creation. The workflow closes them automatically; repository administrators can still edit repository rules.
- Verified `asifr` cannot create a branch or tag, while `tychoengr` can create and delete a temporary verification branch. Removed the temporary branch.
- Actionlint passed for the PR-closing workflow, and GitHub reports it active. No open PRs existed; live PR closure has not been exercised.
- Published Jobs, the simplified README, and the contribution policy using the existing `tychoengr` credentials without changing the global GitHub CLI account selection.

## 2026-11-04 13:00 EST — Coding plugin

- Added the existing universal engineering guidance as `coding`, with no `skill` suffix in its package name, skill name, display name, or invocation metadata.
- Bundled the four existing topic guides and linked each from a concise skill entrypoint. Kept architecture, parsing, testing, tooling, static checks, real user-flow validation, and delivery guidance.
- Replaced links to unbundled sibling skills with optional companion names, aligned closed-set types with the TypeScript guide, and removed an unsupported research attribution from the imported testing reference.
- Registered the plugin in both catalogs and added its installation command and one-line description to the user README.
- Skill Creator and native Claude validators passed. Isolated Claude and Codex installations contain the complete guide tree; Claude reports exactly one skill named `coding`.
- Checked that the plugin contains no stale `coding-skill` names or sibling-file links and that all four guide links resolve within the installed package.
