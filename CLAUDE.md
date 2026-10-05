# padmap

Maps an Xbox controller to keyboard keys and mouse movement — an xpadder-style remapper. Runs locally as a CLI; nothing is hosted.

## Architecture

One package, `src/padmap/`, entered through the `padmap` console script. A pipeline: **devices** reads the pad → **engine** decides what that means under the loaded **config** → **backends** performs it. `actions` and `curves` are the shared vocabulary and maths.

* **`actions.py`** — the action grammar (`"key:w"`, `"mouse:left"`, `"scroll:up"`, …). Parses and validates; owns the key-name tables.
* **`curves.py`** — deadzones, response curves, trigger normalisation, smoothing, acceleration, sub-pixel accumulation. Pure functions plus three tiny stateful filters.
* **`calibration.py`** — where each axis rests and how far it travels. `CentreSampler`/`RangeSampler` turn readings into an `AxisCalibration`.
* **`zones.py`** — breakpoint ranges over one analogue input, and the hysteresis that keeps them from chattering. Payload-agnostic, so it knows nothing of the schema.
* **`macros.py`** — macro model plus `MacroRunner`, which advances in-flight macros a little per tick rather than sleeping.
* **`validate.py`** — profile value primitives; every error names its dotted path.
* **`loader.py`** — the only module that knows profiles live in files.
* **`config.py`** — the JSON profile schema. Loading, strict validation, `describe()`.
* **`devices.py`** — controller discovery and polling via pygame/SDL2. Owns the input-name vocabulary and the raw-index `Layout`.
* **`backends.py`** — keyboard/mouse output via pynput, plus `RecordingBackend`, the fake behind `--dry-run` and the tests.
* **`engine.py`** — the mapping loop. Edge detection, turbo, toggles, layers, precision, pointer motion, hot reload.
* **`display.py`** — the live status line and the dry-run trace. Renders an `EngineStatus`; touches nothing else.
* **`runtime.py`** — background sessions: the state file, and the stop protocol.
* **`tray.py`** — optional system-tray control surface (`padmap[tray]` extra).
* **`focus.py`** — which window has focus. A *diagnostic* only; see the convention below.
* **`doctor.py`** — environment verdicts. `probe()` gathers facts, `evaluate()` judges them purely.
* **`wizard.py`** — `padmap setup`. Decisions are pure functions; only the prompting needs a person.
* **`cli.py`** — `run`, `setup`, `doctor`, `tray`, `status`, `stop`, `devices`, `monitor`, `calibrate`, `profiles`, `validate`, `init`.
* **`profiles/`** — bundled JSON profiles (`desktop`, `fps`, `starter`).

## Key Conventions

* **Never leave a key stuck down.** Outranks everything else here. Every path that stops output — pause, quit, `Ctrl-C`, `SIGTERM`, an exception, a profile swap — goes through `Engine.release_all()`; `run()` calls it in a `finally` and `cli._cmd_run` again. A new code path that can hold a key needs a matching release path and a test proving it.
* **pygame and pynput are imported lazily**, inside the functions that touch hardware. `import padmap` must work headless — that is what makes the engine testable, and pynput raises outright with no `DISPLAY`.
* **`Engine.tick(now, state)` takes its time and state as arguments.** `run()` is the only thing that reads a clock or polls hardware. Keep new logic in `tick()`.
* **Validation is strict and errors name their path** (`sticks.left.curve: 9.0 is out of range [0.1, 6.0]`). Unknown keys are rejected — a silently-ignored typo is indistinguishable from broken hardware.
* **Deadzones are radial, not per-axis.** A per-axis deadzone leaves a cross-shaped dead area that makes diagonals snap to the nearest axis.
* **SDL's sign conventions differ between sticks and hats**: sticks are y-up-**negative** (matching screen coordinates), hats y-up-**positive**. Reconciled in `devices.hat_to_dpad`, pinned by a test.
* **Stick pipeline order is fixed: calibrate → deadzone → curve → smooth → speed.** Smoothing after the curve smooths what drives the pointer; on the raw axis it would smear the deadzone edge. Calibration is first because everything downstream assumes a true-centred axis.
* **A deadzone is not drift correction** — a deadzone is centred on zero and drift is not. "Just raise the deadzone" is always the wrong fix; see `calibration.py`'s docstring.
* **Specials resolve from the base profile only, never from a layer.** Enforced in `config._parse_sections`. Otherwise "which layer am I in" could depend on which layer is active.
* **A binding that changes while held must be released first.** `Engine._hold` compares the current action, not just slot occupancy — a layer switch under a held button would otherwise strand the outgoing key.
* **Stopping a detached session goes through a file, not a signal** (no usable cross-process `SIGTERM` on Windows). `runtime.clear_stop()` runs at every session start; a leftover file would kill the next one instantly.
* **Anything reaching in from another thread is queued, not applied** — `request_pause` / `request_profile` leave a value `_apply_pending` acts on next tick; mutating state mid-tick races against keys being pressed.
* **Input already goes to the focused window** — pynput injects at the OS level (`SendInput`, `CGEventPost`, XTEST). There is no window targeting to implement; "wrong window" is always really about which window had focus.
* **Exactly one zone is active per analogue input**, and each zone gets its own engine slot (`trigger.rt#1`) — so hold, turbo, toggle and release-on-leaving come for free. Hysteresis lives in `ZoneTracker`; without it a thumb on a boundary machine-guns two actions.
* **A macro never sleeps in the loop** — `MacroRunner.advance` runs once per tick. A stalled loop stretches a macro rather than compressing it; catching up would turn a hiccup into a burst of input.
* **Anything a macro still holds when it ends is released** — a latched modifier with no way up is the stuck-key bug.
* **`focus.py` is a diagnostic, never a prerequisite** — it answers `None` rather than raising, and nothing in the mapping path may depend on it.
* **`doctor.evaluate` is pure** — facts in, verdicts out, which is how verdicts for other platforms get tested. Every non-passing check carries a `fix`.
* **Bundled profiles must bind a pause button** — a misbehaving mapping needs stopping without the keyboard it has taken over. Enforced by a test.

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

* **Unit + behaviour tests**: `pytest` — 407 tests across `tests/`. Coverage floor 80% lines/branches, configured in `pyproject.toml` and enforced by pytest itself, not a separate CI step.
* **Everything runs on fakes.** `conftest.FakeController` supplies states, `backends.RecordingBackend` records events — no controller, no display, and no synthetic input reaches the test machine.
* `tests/test_engine.py` is the behavioural spec: press a button, get an event. New mapping behaviour belongs there first.
* `tests/test_engine.py`'s `engine_for` helper turns `auto_centre` **off** unless a test supplies its own `device` block — auto-centring suppresses pointer motion for its first 0.4 s and would silently swallow the opening ticks of every pointer-maths test.
* **Not covered**: `PygameController`, `PynputBackend`, `TrayApp`'s pystray binding — thin wrappers over hardware or a desktop, marked `# pragma: no cover`. `tray.menu_model` and `tray.apply_action` hold the logic and are fully covered. They stay thin deliberately; anything with logic belongs in a covered module.
* **Manual smoke checklist**: `doctor` is honest about this machine; `setup` completes and writes a profile that `validate` accepts; `devices` lists the pad; `monitor` reacts to every button; `calibrate` completes; `run -p desktop` points, scrolls, clicks; LB slows the pointer; RB reaches `nav`; Back pauses; `Ctrl-C` leaves nothing held; `--detach`/`status`/`stop` round-trips; `tray` shows an icon that pauses and quits.

## Security & Secrets

* **Threat model**: padmap synthesises input locally. No network, no server, no telemetry, no credentials — nothing to leak. Two things are security-relevant: **a profile is executable intent** (running someone else's is letting them type on your keyboard — `padmap validate` prints every binding for this reason), and **a stuck modifier is a security bug**, since a held `ctrl` reinterprets every later keystroke.
* **State on disk**: a session state file and a stop file under `runtime.runtime_dir()` (`PADMAP_RUNTIME_DIR` overrides). Nothing sensitive; plain JSON, so a wedged session can be inspected with `cat`.
* **Secrets**: none. No `.env` — nothing to configure. `SDL_VIDEODRIVER` is the only env var padmap touches, and it sets it itself (`dummy`, so SDL never opens a window).
* **Required CI secrets**: none. Every workflow runs on the built-in `GITHUB_TOKEN`.
* **Reporting**: [`.github/SECURITY.md`](./.github/SECURITY.md) — private advisories, not public issues.

## Tech Stack and CI

pygame (SDL2) in, pynput out, JSON profiles, argparse, Ruff, pytest, hatchling; pystray+Pillow as an optional `[tray]` extra. Focus detection and the doctor use ctypes and platform CLIs rather than adding a dependency. Full table and the reasoning: [`docs/architecture.md`](./docs/architecture.md).

padmap installs locally with `pip install .`; nothing deploys. Three workflows, all validation only — `ci.yml` (ruff + pytest on 3.10 and 3.12), `security-scan.yml` (CodeQL, gitleaks, Scorecard), `dependency-review.yml`. Triggers in [`README.md`](./README.md#cicd-at-a-glance). Required secrets: none.

## Conventional Commits

[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). Useful scopes here: `actions`, `calibration`, `config`, `curves`, `devices`, `engine`, `cli`, `profiles`. Breaking changes get `!` plus a `BREAKING CHANGE:` footer; the `commit-msg` hook in [`.pre-commit-config.yaml`](./.pre-commit-config.yaml) blocks non-conformant messages locally.

## Behavior preservation (non-negotiable)

Per [`repo-standards`](https://github.com/Ranzlappen/repo-standards) `PROMPT.md` rule 2: **100% of original functionality preserved**, the repo analyzed *before* editing, and a **Repo-specific risks / edge-cases** subsection in every PR description and post-task self-check ("None observed" is fine; the heading must be there).

What must not drift without a deliberate, documented decision: **the action grammar** (a profile that worked keeps working), **the profile schema** including what it rejects, **input names and the default layout**, **the CLI's commands, flags and exit codes**, and **the release-on-exit guarantee**. `threshold` on a trigger or stick direction must keep meaning what it did — it is now sugar for a single zone, and that equivalence is load-bearing for every profile written before v0.4.0. Deliberate default changes go in `CHANGELOG.md` — v0.2.0 changed `smoothing` (now 0.35) and `device.auto_centre` (now true), both opt-out.

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
