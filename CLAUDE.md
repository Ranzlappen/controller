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
* **`display.py`** — the live status line and the dry-run trace. Renders an `EngineStatus`; touches nothing else.
* **`runtime.py`** — background sessions: the state file, and the stop protocol.
* **`tray.py`** — optional system-tray control surface (`padmap[tray]` extra).
* **`cli.py`** — `run`, `tray`, `status`, `stop`, `devices`, `monitor`, `calibrate`, `profiles`, `validate`, `init`.
* **`profiles/`** — bundled JSON profiles (`desktop`, `fps`, `starter`).

## Key Conventions

* **Never leave a key stuck down.** This outranks every other consideration in the codebase. Every path that stops output — pause, quit, `Ctrl-C`, `SIGTERM`, an exception — goes through `Engine.release_all()`. `Engine.run()` calls it in a `finally`; `cli._cmd_run` calls it again. If you add a code path that can hold a key, it must have a matching release path, and a test that proves it.
* **pygame and pynput are imported lazily**, inside the functions that touch hardware — never at module scope. `import padmap` must work on a headless machine; that is what makes the engine testable. Importing pynput with no `DISPLAY` raises outright.
* **`Engine.tick(now, state)` takes its time and state as arguments.** `run()` is the only thing that reads a clock or polls hardware. Keep new logic in `tick()`.
* **Validation is strict and errors name their path** (`sticks.left.curve: 9.0 is out of range [0.1, 6.0]`). Unknown keys are rejected — a silently-ignored typo is indistinguishable from broken hardware.
* **Deadzones are radial, not per-axis.** A per-axis deadzone leaves a cross-shaped dead area that makes diagonals snap to the nearest axis.
* **SDL's sign conventions differ between sticks and hats**: sticks are y-up-**negative** (matching screen coordinates), hats y-up-**positive**. Reconciled in `devices.hat_to_dpad`, pinned by a test.
* **Stick pipeline order is fixed: calibrate → deadzone → curve → smooth → speed.** Smoothing after the curve smooths what actually drives the pointer; smoothing the raw axis would smear the deadzone edge and feel mushy to start. Calibration is first because everything downstream assumes a true-centred axis.
* **A deadzone is not drift correction** — a deadzone is centred on zero and drift is not. "Just raise the deadzone" is always the wrong fix; see `calibration.py`'s docstring.
* **Specials resolve from the base profile only, never from a layer.** Enforced in `config._parse_sections`. Otherwise "which layer am I in" could depend on which layer is active.
* **A binding that changes while held must be released first.** `Engine._hold` compares the current action, not just slot occupancy — a layer switch under a held button would otherwise strand the outgoing key.
* **Stopping a detached session goes through a file, not a signal** — Windows has no usable cross-process `SIGTERM`, and the engine already polls. `runtime.clear_stop()` runs at the start of every session; a leftover stop file would kill the next one instantly.
* **Anything reaching in from another thread is queued, not applied.** `request_pause` / `request_profile` leave a value that `_apply_pending` acts on at the top of the next tick — mutating engine state mid-tick would race against keys being pressed.
* **Input already goes to the focused window** — pynput injects at the OS level (`SendInput`, `CGEventPost`, XTEST). There is no window targeting to implement; "it went to the wrong window" is always really about which window had focus.
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

* **Unit + behaviour tests**: `pytest` — 267 tests across `tests/`. Coverage floor 80% lines/branches, configured in `pyproject.toml` and enforced by pytest itself, not a separate CI step.
* **Everything runs on fakes.** `conftest.FakeController` supplies states, `backends.RecordingBackend` records events — no controller, no display, and no synthetic input reaches the test machine.
* `tests/test_engine.py` is the behavioural spec: press a button, get an event. New mapping behaviour belongs there first.
* `tests/test_engine.py`'s `engine_for` helper turns `auto_centre` **off** unless a test supplies its own `device` block — auto-centring suppresses pointer motion for its first 0.4 s and would silently swallow the opening ticks of every pointer-maths test.
* **Not covered**: `PygameController`, `PynputBackend`, `TrayApp`'s pystray binding — thin wrappers over hardware or a desktop, marked `# pragma: no cover`. `tray.menu_model` and `tray.apply_action` hold the logic and are fully covered. They stay thin deliberately; anything with logic belongs in a covered module.
* **Manual smoke checklist**: `devices` lists the pad; `monitor` reacts to every button; `calibrate` completes; `run -p desktop` points, scrolls, clicks; LB slows the pointer; RB reaches `nav`; Back pauses; `Ctrl-C` leaves nothing held; `--detach`/`status`/`stop` round-trips; `tray` shows an icon that pauses and quits.

## Security & Secrets

* **Threat model**: padmap synthesises input locally. No network, no server, no telemetry, no credentials — nothing to leak. Two things are security-relevant: **a profile is executable intent** (running someone else's is letting them type on your keyboard — `padmap validate` prints every binding for this reason), and **a stuck modifier is a security bug**, since a held `ctrl` reinterprets every later keystroke.
* **State on disk**: a session state file and a stop file under `runtime.runtime_dir()` (`PADMAP_RUNTIME_DIR` overrides). Nothing sensitive; plain JSON, so a wedged session can be inspected with `cat`.
* **Secrets**: none. No `.env` — nothing to configure. `SDL_VIDEODRIVER` is the only env var padmap touches, and it sets it itself (`dummy`, so SDL never opens a window).
* **Required CI secrets**: none. Every workflow runs on the built-in `GITHUB_TOKEN`.
* **Reporting**: [`.github/SECURITY.md`](./.github/SECURITY.md) — private advisories, not public issues.

## Tech Stack

| Layer | Technology | Why this one |
| --- | --- | --- |
| Input | pygame 2.x (SDL2) | One code path covers Windows/Linux/macOS |
| Output | pynput 1.x | Separate press/release, so keys can be *held* |
| Config | JSON + dataclasses | Hand-editable; no schema library needed |
| CLI | argparse (stdlib) | No dependency for ten subcommands |
| Lint/format | Ruff | One tool, config in `pyproject.toml` |
| Tray | pystray + Pillow | Only cross-platform option; an extra, not a dependency |
| Tests | pytest + pytest-cov | Coverage floor enforced in-process |
| Build | hatchling | src layout, bundles `profiles/*.json` |

## Deployment & CI/CD

padmap is installed locally with `pip install .`; nothing deploys. Three workflows, all validation only: `ci.yml` (ruff lint + format, pytest on 3.10 and 3.12, path-filtered to Python, `pyproject.toml`, `requirements*.txt` and bundled profiles), `security-scan.yml` (CodeQL, gitleaks, Scorecard — no path filter, so docs trigger it), and `dependency-review.yml`. Details and triggers in [`README.md`](./README.md#cicd-at-a-glance). Required secrets: none.

## Conventional Commits

[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). Useful scopes here: `actions`, `calibration`, `config`, `curves`, `devices`, `engine`, `cli`, `profiles`. Breaking changes get `!` plus a `BREAKING CHANGE:` footer; the `commit-msg` hook in [`.pre-commit-config.yaml`](./.pre-commit-config.yaml) blocks non-conformant messages locally.

## Behavior preservation (non-negotiable)

Per [`repo-standards`](https://github.com/Ranzlappen/repo-standards) `PROMPT.md` rule 2: **100% of original functionality preserved**, the repo analyzed *before* editing, and a **Repo-specific risks / edge-cases** subsection in every PR description and post-task self-check ("None observed" is fine; the heading must be there).

What must not drift without a deliberate, documented decision: **the action grammar** (a profile that worked keeps working), **the profile schema** including what it rejects, **input names and the default layout**, **the CLI's commands, flags and exit codes**, and **the release-on-exit guarantee**. Deliberate default changes go in `CHANGELOG.md` — v0.2.0 changed `smoothing` (now 0.35) and `device.auto_centre` (now true), both opt-out.

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
