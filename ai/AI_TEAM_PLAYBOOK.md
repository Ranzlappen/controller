# AI Team Playbook

How multiple AI coding tools — **Claude Code**, **Cursor**, **GitHub Copilot**, **Codex**, and friends — coexist on the same codebase without stepping on each other.

This file is the canonical multi-AI coordination doc. If your project has only one AI tool in use, you can ignore it; it becomes useful the moment a second tool starts contributing.

## Source-of-truth hierarchy

Every AI tool reads the same hierarchy in the same order:

1. **`CLAUDE.md`** at the repo root — authoritative architecture, build commands, conventions, tech stack. Universal: all tools read this.
2. **`README.md`** at the repo root — user-facing description; the source for "what is this project". Universal.
3. **Tool-specific entrypoints** (read by *only* that tool):
   - Claude Code → `CLAUDE.md` (above) plus any `claude.md` files anywhere in the tree (see Anthropic docs).
   - Cursor → `.cursorrules` at the repo root (or `.cursor/rules/*.md` for newer Cursor versions).
   - GitHub Copilot → `.github/copilot-instructions.md` (Copilot Workspace) or workspace settings.
4. **`ai/AI_TEAM_PLAYBOOK.md`** — *this* file. Coordination rules between tools.

When a tool-specific entrypoint disagrees with `CLAUDE.md`, **`CLAUDE.md` wins**. Update the tool-specific file to match, not the other way around.

## What each tool is best at

These are defaults; override per project as you learn the local fit.

| Tool | Best at | Avoid using for |
| --- | --- | --- |
| **Claude Code** (CLI / GitHub Action) | Multi-file refactors, repo-wide audits, executing the `repo-standards` PROMPT.md upgrade flow, opening PRs from issues, long-form planning. | Real-time line-by-line autocompletion. |
| **Cursor** | In-IDE iterative editing, exploratory "tab to accept" autocomplete, code search via natural language. | Sustained multi-PR campaigns; CI-side automation. |
| **GitHub Copilot** | Inline completion, boilerplate, well-known idioms. | Architectural decisions, refactors that span more than the visible buffer. |
| **Codex / `o`-style models** | One-shot scripts, throwaway tooling, prototypes. | Anything that ships to users without a human review pass. |

## Conventions all AI tools follow on this repo

These are non-negotiable for any AI-driven contribution:

- **Conventional Commits** on every commit message. Type + optional scope. Breaking changes get `!` and a `BREAKING CHANGE:` footer.
- **Tiny-commit rhythm** — one file per commit unless atomically inseparable. Each commit is preceded by a one-paragraph plain-English plan, followed by a post-task self-check.
- **Behavior preservation (non-negotiable)** — `repo-standards` PROMPT.md rule 2. Keep 100% of original functionality, analyze before editing, flag repo-specific risks / edge-cases in every PR description and post-task self-check.
- **No PR opens without explicit user confirmation** — even if the AI tool is fully autonomous in the IDE, opening a PR is a deliberate user action.
- **PR template applies** — see [`.github/PULL_REQUEST_TEMPLATE.md`](../.github/PULL_REQUEST_TEMPLATE.md).

## Conflict resolution between tools

If two tools propose conflicting changes (Cursor's autocomplete fights Copilot's; Claude Code's refactor conflicts with a Cursor-staged edit):

1. **Stop** — do not auto-merge. Resolve at the conversation level, not the diff level.
2. **Surface the disagreement explicitly** in the PR description: "Cursor proposed X; Claude Code's audit recommends Y; resolved as Y because…".
3. **The tool that owns the affected scope** (per the table above) wins by default. A multi-file refactor is Claude Code's scope; an in-buffer rename is Cursor's; an inline completion is Copilot's.
4. **The human is the tiebreaker** if the scope is ambiguous.

## How to disable a tool in a particular path

Sometimes a path is human-only or tool-specific:

- **Cursor**: add the path to `.cursorignore` (same syntax as `.gitignore`).
- **Copilot**: add the path to `.copilotignore` if your org config supports it; otherwise document it in `.github/copilot-instructions.md`.
- **Claude Code**: list the path in `CLAUDE.md` under a "Hands off" subsection. Claude Code respects the convention if the rule is explicit.

## When this playbook is wrong

This is a recommendation, not a contract. If your project has a different multi-AI setup that works, document it here in place of the defaults. Open a PR — playbook changes follow the same lifecycle as code changes.

## See also

- [`CLAUDE.md`](../CLAUDE.md) — architecture source of truth.
- [`.cursorrules`](../.cursorrules) — Cursor's tool-specific entrypoint, mirrors the rules above.
- [`repo-standards`](https://github.com/Ranzlappen/repo-standards) — upstream conventions this playbook is derived from.
