# padmap

Maps an Xbox controller to keyboard keys and mouse movement — an xpadder-style remapper. Runs locally as a CLI; nothing is hosted.

## Architecture

One package, `src/padmap/`, entered through the `padmap` console script. A pipeline: **devices** reads the pad → **engine** decides what that means under the loaded **config** → **backends** performs it. `actions` and `curves` are the shared vocabulary and maths.

* **`actions.py`** — the action grammar (`"key:w"`, `"mouse:left"`, `"scroll:up"`, …). Parses and validates; owns the key-name tables.
* **`curves.py`** — deadzones, response curves, trigger normalisation, smoothing, acceleration, sub-pixel accumulation. Pure functions plus three tiny stateful filters.
* **`calibration.py`** — where each axis rests and how far it travels. Pure data; `CentreSampler`/`RangeSampler` turn readings into an `AxisCalibration`.
* **`config.py`** — the JSON profile schema. Loading, strict validation, `describe()`.
* **`devices.py`** — controller discovery and polling via pygame/SDL2. Owns the input-name vocabulary and the raw-index `Layout`.
* **`backends.py`** — keyboard/mouse output via pynput, plus `RecordingBackend`, the fake behind `--dry-run` and the tests.
* **`engine.py`** — the mapping loop. Edge detection, turbo, toggles, layers, precision, pointer motion, hot reload.
* **`cli.py`** — `run`, `devices`, `monitor`, `calibrate`, `profiles`, `validate`, `init`.
* **`profiles/`** — bundled JSON profiles (`desktop`, `fps`, `starter`).

## Key Conventions

* **Never leave a key stuck down.** This outranks every other consideration in the codebase. Every path that stops output — pause, quit, `Ctrl-C`, `SIGTERM`, an exception — goes through `Engine.release_all()`. `Engine.run()` calls it in a `finally`; `cli._cmd_run` calls it again. If you add a code path that can hold a key, it must have a matching release path, and a test that proves it.
* **pygame and pynput are imported lazily**, inside the functions that touch hardware — never at module scope. `import padmap` must work on a headless machine; that is what makes the engine testable. Importing pynput with no `DISPLAY` raises outright.
* **`Engine.tick(now, state)` takes its time and state as arguments.** `run()` is the only thing that reads a clock or polls hardware. Keep new logic in `tick()`.
* **Validation is strict and errors name their path** (`sticks.left.curve: 9.0 is out of range [0.1, 6.0]`). Unknown keys are rejected, never ignored — a silently-ignored typo in a remapper is indistinguishable from broken hardware.
* **Deadzones are radial, not per-axis.** `curves.stick_vector` works on the magnitude of the pair. A per-axis deadzone leaves a cross-shaped dead area that makes diagonals snap to the nearest axis.
* **SDL's sign conventions differ between sticks and hats.** Sticks are y-up-**negative** (which conveniently matches screen coordinates); hats are y-up-**positive**. `devices.hat_to_dpad` is where that is reconciled, and it is pinned by a test.
* **Stick pipeline order is fixed: calibrate → deadzone → curve → smooth → speed.** Smoothing after the curve smooths what actually drives the pointer; smoothing the raw axis would smear the deadzone edge and feel mushy to start. Calibration is first because everything downstream assumes a true-centred axis.
* **A deadzone is not drift correction.** A deadzone is centred on zero; drift is not. Anything that looks like "just raise the deadzone" is the wrong fix — see `calibration.py`'s module docstring.
* **Specials resolve from the base profile only, never from a layer.** Enforced in `config._parse_sections`. Otherwise "which layer am I in" could depend on which layer is active.
* **A binding that changes while held must be released first.** `Engine._hold` compares the current action, not just slot occupancy — a layer switch under a held button would otherwise strand the outgoing key.
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

* **Unit + behaviour tests**: `pytest` — 212 tests across `tests/`. Coverage floor 80% lines/branches, configured in `pyproject.toml` and enforced by pytest itself, not a separate CI step.
* **Everything runs on fakes.** `conftest.FakeController` supplies states, `backends.RecordingBackend` records events — no controller, no display, and no synthetic input reaches the test machine.
* `tests/test_engine.py` is the behavioural spec: press a button, get an event. New mapping behaviour belongs there first.
* `tests/test_engine.py`'s `engine_for` helper turns `auto_centre` **off** unless a test supplies its own `device` block — auto-centring suppresses pointer motion for its first 0.4 s and would silently swallow the opening ticks of every pointer-maths test.
* **Not covered**: `PygameController` and `PynputBackend` — thin hardware wrappers, marked `# pragma: no cover`. They stay thin deliberately; anything with logic belongs in a covered module.
* **Manual smoke checklist** before releasing: `padmap devices` lists the pad; `padmap monitor` reacts to every button; `padmap calibrate` completes; `padmap run -p desktop` points, scrolls and clicks; LB slows the pointer; RB reaches the `nav` layer; Back pauses; `Ctrl-C` leaves nothing held.

## Security & Secrets

* **Threat model**: padmap synthesises input locally. No network, no server, no telemetry, no credentials — nothing to leak. Two things are security-relevant: **a profile is executable intent** (running someone else's is letting them type on your keyboard — `padmap validate` prints every binding for this reason), and **a stuck modifier is a security bug**, since a held `ctrl` reinterprets every later keystroke.
* **Secrets**: none. No `.env` — nothing to configure. `SDL_VIDEODRIVER` is the only env var padmap touches, and it sets it itself (`dummy`, so SDL never opens a window).
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

padmap is installed locally with `pip install .`.

| Workflow | Trigger | Does |
| --- | --- | --- |
| `ci.yml` | PR + push to `main`, manual | ruff lint + format, pytest on 3.10 and 3.12 |
| `security-scan.yml` | PR, push to `main`, weekly Mon 06:00 UTC | CodeQL, gitleaks, OpenSSF Scorecard |
| `dependency-review.yml` | PR to `main` | Blocks high-severity CVEs in dependency changes |

Nothing deploys; all three are validation only. `ci.yml` is path-filtered to `**.py`, `pyproject.toml`, `requirements*.txt`, bundled profiles and itself.

**What fires**: source and bundled profiles trigger CI + security scan; docs trigger only the security scan (it has no path filter). CI and dependency-review cancel in-progress runs per ref; security-scan cancels for PRs only and queues for `main`.

## Conventional Commits

[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). Useful scopes here: `actions`, `calibration`, `config`, `curves`, `devices`, `engine`, `cli`, `profiles`. Breaking changes get `!` plus a `BREAKING CHANGE:` footer; the `commit-msg` hook in [`.pre-commit-config.yaml`](./.pre-commit-config.yaml) blocks non-conformant messages locally.

## Behavior preservation (non-negotiable)

Every change follows [`repo-standards`](https://github.com/Ranzlappen/repo-standards) `PROMPT.md` rule 2: **100% of original functionality preserved**, the repo analyzed *before* editing, and a **Repo-specific risks / edge-cases** subsection in every PR description and post-task self-check ("None observed" is fine; the heading must be there).

Here, the observable behaviour that must not drift without a deliberate, documented decision is: **the action grammar** (a profile that worked keeps working), **the profile schema** (including what it rejects), **input names and the default layout**, **the CLI's commands, flags and exit codes**, and **the release-on-exit guarantee**.

Two defaults were changed deliberately in v0.2.0 and are recorded in `CHANGELOG.md`: `smoothing` now defaults to 0.35 rather than being absent, and `device.auto_centre` defaults to true. Both change the feel of an existing profile that does not mention them. Both are opt-out (`"smoothing": 0`, `"auto_centre": false`).

## AI readiness

Source-of-truth hierarchy: `CLAUDE.md` → `README.md` → `.cursorrules`. When a tool-specific file disagrees with this one, **this file wins**. See [`ai/AI_TEAM_PLAYBOOK.md`](./ai/AI_TEAM_PLAYBOOK.md).

## Out-of-scope findings, and plan hygiene

Unrelated findings auto-file an issue (`--label "out-of-scope,from-claude"`) linked from the PR's "Refactoring opportunities"; `DISABLE_OUT_OF_SCOPE_ISSUES=true` keeps them in the PR description only. Plan files start fresh or get pruned — never appended to (`PROMPT.md` rules 13, 15).

## Post-task self-check

After every turn that changes code, scan for things to codify in `README.md`, this file, or `.github/` — new commands, action kinds, input names, profile options, path filters, dependencies, conventions. Per rule 2, **always include a "Repo-specific risks / edge-cases" subsection**; "None observed" is fine.

Two padmap-specific checks belong in every self-check that touches the engine or backends:

* **Does any new code path hold a key without a matching release path?**
* **Does any new action kind, input name, or profile option need a row in the README's reference tables?**

**Auto-implement** small, unambiguous updates (a new profile option → README table, a new module → the structure tree). **Prompt first** for anything structurally significant — a new action kind, a schema change, a workflow restructure. If nothing is warranted, say "no doc/workflow updates needed". Skip entirely for pure Q&A turns.
