# padmap

Maps an Xbox controller to keyboard keys and mouse movement — an xpadder-style remapper. Runs locally as a CLI; nothing is hosted.

## Architecture

One package, `src/padmap/`, entered through the `padmap` console script. A pipeline: **devices** reads the pad → **engine** decides what that means under the loaded **config** → **backends** performs it. `actions` and `curves` are the shared vocabulary and maths.

* **`actions.py`** — the action grammar (`"key:w"`, `"mouse:left"`, `"scroll:up"`, …). Parses and validates; owns the key-name tables.
* **`curves.py`** — deadzones, response curves, trigger normalisation, sub-pixel accumulation. Pure functions.
* **`config.py`** — the JSON profile schema. Loading, strict validation, `describe()`.
* **`devices.py`** — controller discovery and polling via pygame/SDL2. Owns the input-name vocabulary and the raw-index `Layout`.
* **`backends.py`** — keyboard/mouse output via pynput, plus `RecordingBackend`, the fake behind `--dry-run` and the tests.
* **`engine.py`** — the mapping loop. Edge detection, turbo, toggles, pointer motion.
* **`cli.py`** — `run`, `devices`, `monitor`, `profiles`, `validate`, `init`.
* **`profiles/`** — bundled JSON profiles (`desktop`, `fps`, `starter`).

## Key Conventions

* **Never leave a key stuck down.** This outranks every other consideration in the codebase. Every path that stops output — pause, quit, `Ctrl-C`, `SIGTERM`, an exception — goes through `Engine.release_all()`. `Engine.run()` calls it in a `finally`; `cli._cmd_run` calls it again. If you add a code path that can hold a key, it must have a matching release path, and a test that proves it.
* **pygame and pynput are imported lazily**, inside the functions and constructors that touch hardware — never at module scope. `import padmap` must stay cheap and must work on a headless machine, because that is what makes the whole engine testable. Importing pynput on a Linux box with no `DISPLAY` raises outright.
* **`Engine.tick(now, state)` takes its time and its state as arguments.** The loop in `run()` is the only thing that reads a clock or polls hardware. Keep new logic in `tick()` so it stays testable.
* **Validation is strict and errors name their path** (`sticks.left.curve: 9.0 is out of range [0.1, 6.0]`). Unknown keys are rejected, never ignored — a silently-ignored typo in a remapper is indistinguishable from broken hardware.
* **Deadzones are radial, not per-axis.** `curves.stick_vector` works on the magnitude of the pair. A per-axis deadzone leaves a cross-shaped dead area that makes diagonals snap to the nearest axis.
* **SDL's sign conventions differ between sticks and hats.** Sticks are y-up-**negative** (which conveniently matches screen coordinates); hats are y-up-**positive**. `devices.hat_to_dpad` is where that is reconciled, and it is pinned by a test.
* **Bundled profiles must bind a pause button.** A user with a misbehaving mapping needs a way to stop output without reaching for a keyboard they can no longer control. Enforced by a test.

## Build & Development

```
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"       # padmap plus pytest and ruff
pytest                         # full suite with coverage (80% floor, enforced by pytest)
ruff check .                   # lint
ruff format --check .          # formatting
pre-commit install             # optional: run the same checks on commit
```

Run it: `padmap run --dry-run` (safe anywhere), `padmap run -p desktop` (live), `padmap monitor` (raw indices).

**Runtime versions**: Python 3.10 is the floor (`requires-python`), 3.12 the ceiling CI tests. Both run in the CI matrix because the classifiers claim both.

## Testing

* **Unit + behaviour tests**: `pytest` — 144 tests across `tests/`. Coverage floor 80% lines/branches, configured in `pyproject.toml` and enforced by pytest itself, not a separate CI step.
* **Everything runs on fakes.** `conftest.FakeController` supplies states, `backends.RecordingBackend` records events. No controller, no display, and no synthetic input reaches the machine running the tests — which is why the suite is safe to run anywhere, including CI.
* `tests/test_engine.py` is the behavioural spec: press a button, get an event. New mapping behaviour belongs there first.
* **Not covered**: `PygameController` and `PynputBackend` — thin hardware wrappers, marked `# pragma: no cover`. They stay thin deliberately; anything with logic belongs in a covered module.
* **Manual smoke checklist** before releasing: `padmap devices` lists the pad; `padmap monitor` reacts to every button; `padmap run -p desktop` moves the pointer, scrolls and clicks; Back pauses and resumes; `Ctrl-C` leaves nothing held.

## Security & Secrets

* **Threat model**: padmap synthesises input on the local machine. No network code, no server, no telemetry, no credentials — there is nothing to leak. Two things are genuinely security-relevant:
  1. **A profile is executable intent.** It can bind a key combo or type a literal string, so running someone else's profile is equivalent to letting them type on your keyboard. `padmap validate <file>` prints every binding for exactly this reason.
  2. **A stuck modifier is a security bug**, not a papercut — a held `ctrl` or `cmd` reinterprets every later keystroke.
* **Secrets handled by this project**: none. No `.env`, no `.env.example` — there is nothing to configure. `SDL_VIDEODRIVER` is the only environment variable padmap touches, and it sets it itself (to `dummy`, so SDL never opens a window).
* **Required CI secrets**: none. Every workflow runs on the built-in `GITHUB_TOKEN`.
* **Reporting**: [`.github/SECURITY.md`](./.github/SECURITY.md) — private advisories, not public issues.

## Tech Stack

| Layer | Technology | Role | Why |
| --- | --- | --- | --- |
| Input | pygame 2.x (SDL2) | Reads the controller | One code path covers Windows/Linux/macOS |
| Output | pynput 1.x | Synthesises keys and mouse | Separate press/release, so keys can be *held* |
| Config | JSON + dataclasses | Profiles | Hand-editable; no schema library needed |
| CLI | argparse (stdlib) | Commands | No dependency for six subcommands |
| Lint/format | Ruff | Both | One tool, config in `pyproject.toml` |
| Tests | pytest + pytest-cov | Suite | Coverage floor enforced in-process |
| Build | hatchling | Packaging | src layout, bundles `profiles/*.json` |

## Deployment & CI/CD

Nothing deploys — padmap is installed locally with `pip install .`.

| Workflow | Trigger | Scope | Deploys |
| --- | --- | --- | --- |
| `ci.yml` | PR + push to `main` | `**.py`, `pyproject.toml`, `requirements*.txt`, bundled profiles, itself | Nothing (validation only) |
| `security-scan.yml` | PR, push to `main`, weekly Mon 06:00 UTC, `branch_protection_rule` | Whole repo | Nothing (CodeQL + gitleaks + Scorecard) |
| `dependency-review.yml` | PR to `main` | Dependency manifests | Nothing (blocks high-severity CVEs) |

**What fires on a given change:**

| Change | CI | Security scan |
| --- | --- | --- |
| Source in `src/` or `tests/` | ✓ | ✓ |
| A bundled profile in `src/padmap/profiles/` | ✓ | ✓ |
| Docs (`README.md`, `CLAUDE.md`, `docs/`) | — | ✓ |

**Concurrency**: CI and dependency-review cancel in-progress runs per ref; security-scan cancels only for PRs and queues for `main` and scheduled runs.

## Conventional Commits

This project follows [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/): `feat` / `fix` / `docs` / `refactor` / `test` / `chore` / `ci` / `perf` / `style` / `revert`. Optional `(scope)` — useful ones here are `actions`, `config`, `curves`, `devices`, `engine`, `cli`, `profiles`. Breaking changes get `!` plus a `BREAKING CHANGE:` footer. The `commit-msg` pre-commit hook (see [`.pre-commit-config.yaml`](./.pre-commit-config.yaml)) blocks non-conformant messages locally.

## Behavior preservation (non-negotiable)

Every change follows [`repo-standards`](https://github.com/Ranzlappen/repo-standards) `PROMPT.md` rule 2: **100% of original functionality preserved**, the repo analyzed *before* editing, and a **Repo-specific risks / edge-cases** subsection in every PR description and post-task self-check ("None observed" is acceptable; the heading must be present).

Here, the observable behaviour that must not drift without a deliberate, documented decision is: **the action grammar** (a profile that worked keeps working), **the profile schema** (including what it rejects), **input names and the default layout**, **the CLI's commands, flags and exit codes**, and **the release-on-exit guarantee**.

## AI readiness

Source-of-truth hierarchy: `CLAUDE.md` (this file) → `README.md` → tool-specific entrypoints (`.cursorrules`). When a tool-specific file disagrees with this one, **this file wins**. See [`ai/AI_TEAM_PLAYBOOK.md`](./ai/AI_TEAM_PLAYBOOK.md) for multi-tool coordination.

## Out-of-scope findings, and plan hygiene

Work that surfaces something unrelated auto-files an issue by default (`gh issue create --label "out-of-scope,from-claude"`), linked from the PR's "Refactoring opportunities"; set the repo variable `DISABLE_OUT_OF_SCOPE_ISSUES=true` to keep such findings in the PR description only. Plan files start fresh or get pruned of shipped work — never appended to (`PROMPT.md` rules 13 and 15).

## Post-task self-check

After every turn that changes code, scan for things that should be codified in `README.md`, this file, `.github/workflows/*.yml`, or `.github/dependabot.yml` — new commands, action kinds, input names, profile options, path filters, dependencies, conventions. Per `PROMPT.md` rule 2, **always include a "Repo-specific risks / edge-cases" subsection**; "None observed" is acceptable.

Two padmap-specific checks belong in every self-check that touches the engine or backends:

* **Does any new code path hold a key without a matching release path?**
* **Does any new action kind, input name, or profile option need a row in the README's reference tables?**

* **Auto-implement** small, unambiguous updates (a new profile option → README table, a new module → the structure tree) and call it out in the summary.
* **Prompt first** for anything ambiguous or structurally significant — a new action kind, a schema change, restructuring a workflow.

If nothing is warranted, say "no doc/workflow updates needed". Skip entirely for pure Q&A turns.
