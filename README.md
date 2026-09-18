# padmap

[![CI](https://github.com/Ranzlappen/controller/actions/workflows/ci.yml/badge.svg)](https://github.com/Ranzlappen/controller/actions/workflows/ci.yml)
[![Security scan](https://github.com/Ranzlappen/controller/actions/workflows/security-scan.yml/badge.svg)](https://github.com/Ranzlappen/controller/actions/workflows/security-scan.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Standards](https://img.shields.io/badge/repo--standards-v3-informational)](https://github.com/Ranzlappen/repo-standards)

Map an Xbox controller to keyboard keys and mouse movement — an xpadder-style remapper in about a thousand lines of Python.

> **New here?** Install it, then run `padmap run --dry-run`. Nothing is sent to your desktop in dry-run mode, so you can watch what each button *would* do before you trust it. Jump to [Getting Started](#getting-started).

---

## What this is

padmap reads an Xbox One (or Xbox Series / Xbox 360) controller and turns it into keyboard and mouse input, so any program that takes a keyboard and mouse takes your controller too. Point-and-click from the couch. Play a keyboard-only game on a pad. Drive a media centre without getting up.

Mappings live in small JSON **profiles** you can read and edit by hand. Three are bundled — `desktop`, `fps` and a `starter` you copy and change.

It is deliberately small: two runtime dependencies, one command, no daemon, no tray icon, no GUI editor. `padmap monitor` tells you what your pad reports, `padmap calibrate` measures what your pad's sticks actually do, and the JSON tells padmap what to do about it.

---

## Quick Reference

| I want to... | Do this |
| --- | --- |
| **Stop the pointer drifting on its own** | `padmap calibrate --write mine.json` |
| **Tune the feel without restarting** | `padmap run -w -p mine.json` — edits apply live |
| See what my controller reports | `padmap devices`, then `padmap monitor` |
| Try it without affecting my desktop | `padmap run --dry-run` |
| Control the desktop from the couch | `padmap run -p desktop` |
| Play a keyboard game on the pad | `padmap run -p fps` |
| See what a profile does | `padmap validate fps` |
| Write my own profile | `padmap init my-profile.json`, edit, `padmap run -p my-profile.json` |
| Move the pointer precisely | Hold **LB** — the precision modifier |
| Reach a second set of bindings | Hold **RB** — the `nav` layer |
| Pause without quitting | Press the **Back / View** button on the pad |
| Stop everything | `Ctrl-C` in the terminal — every held key is released |
| Fix a button that maps to the wrong thing | `padmap monitor` for the real index, then set it under `device.layout` |
| Work out why nothing happens | [`docs/troubleshooting.md`](./docs/troubleshooting.md) — it is a permission problem more often than not |

---

## Getting Started

### Prerequisites

* **Python 3.10 or newer** — check with `python3 --version`.
* **An Xbox controller**, wired or paired over Bluetooth / the Xbox Wireless Adapter.
* **Per-platform input permission** — see [Platform notes](#platform-notes) below. This is the step people get stuck on.

### Install

```
git clone https://github.com/Ranzlappen/controller.git
cd controller
pip install .
```

### First run

```
padmap devices          # is the pad seen at all?
padmap run --dry-run    # watch what would be sent — nothing reaches the desktop
padmap run              # for real; Back pauses, Ctrl-C stops
```

**If the pointer drifts, or the sticks feel vague, calibrate before anything else:**

```
padmap init mine.json                      # your own copy to edit
padmap calibrate --write mine.json         # measure this pad's drift and travel
padmap run -w -p mine.json                 # -w reloads the file as you edit it
```

`padmap run` defaults to the `desktop` profile. Press **Back / View** at any time to suspend output without quitting — useful when you need the real keyboard for a moment.

### Platform notes

| Platform | What you need | Notes |
| --- | --- | --- |
| **Windows** | Nothing extra | Works out of the box. Some games with anti-cheat block synthetic input by design — padmap cannot work around that, and does not try. |
| **Linux (X11)** | Nothing extra | The controller arrives via the `xpad` kernel driver. |
| **Linux (Wayland)** | Not supported today | Wayland compositors reject synthetic input from an ordinary process. Log into an X11/Xorg session, or track [#1](https://github.com/Ranzlappen/controller/issues) for a `uinput` backend. |
| **macOS** | Accessibility permission | System Settings → Privacy & Security → Accessibility → enable your terminal app. Without it, keys are silently dropped. |

If `padmap devices` sees your pad but nothing reaches your applications, that is almost always one of the rows above — [`docs/troubleshooting.md`](./docs/troubleshooting.md) walks through it in order.

---

## How profiles work

A profile is a JSON file. Every controller input maps to an **action string**:

```json
{
  "name": "My profile",
  "poll_hz": 120,
  "buttons": {
    "a": "mouse:left",
    "b": "mouse:right",
    "back": "special:toggle_pause",
    "start": { "action": "key:enter", "turbo": 8 }
  },
  "dpad": { "up": "key:up", "down": "key:down" },
  "triggers": {
    "rt": { "action": "mouse:left", "threshold": 0.3 }
  },
  "sticks": {
    "left": { "mode": "mouse", "speed": 900, "deadzone": 0.15, "curve": 2.0 },
    "right": { "mode": "scroll", "speed": 12 }
  }
}
```

### Input names

| Section | Names you can bind |
| --- | --- |
| `buttons` | `a` `b` `x` `y` `lb` `rb` `back` `start` `ls` `rs` `guide` |
| `dpad` | `up` `down` `left` `right` |
| `triggers` | `lt` `rt` (analogue — bound with a `threshold`) |
| `sticks` | `left` `right` |

### Action strings

| Action | Does | Example |
| --- | --- | --- |
| `key:<name>` | Holds a key while the input is held | `key:w`, `key:page_up`, `key:f5` |
| `key:<a>+<b>` | Holds a combo, modifiers first | `key:ctrl+shift+s`, `key:alt+left` |
| `mouse:<button>` | Holds a mouse button (`left`, `middle`, `right`) | `mouse:left` |
| `scroll:<dir>` | Scrolls repeatedly while held (`up`, `down`, `left`, `right`) | `scroll:down` |
| `text:<string>` | Types a string once per press | `text:gg wp` |
| `special:toggle_pause` | Suspends and resumes all output | — |
| `special:precision` | While held, slows every stick to its `precision` factor | — |
| `special:layer:<name>` | While held, switches to a layer from the `layers` section | `special:layer:nav` |
| `special:quit` | Stops padmap from the pad | — |
| `noop` | Nothing — switches an input off without deleting the line | — |

Key names are the obvious ones (`a`, `7`, `/`, `space`, `enter`, `esc`, `tab`, `shift`, `ctrl`, `alt`, `cmd`, `up`, `page_down`, `f1`–`f20`, `media_volume_up`, …) plus friendly aliases (`escape`, `return`, `pgup`, `win`). A name padmap does not know is rejected when the profile loads, with the list of valid names — it never fails silently at 2am mid-game.

### Binding options

Write a binding as an object instead of a string to add:

| Option | Meaning |
| --- | --- |
| `turbo` | Auto-fire rate in presses per second while held (`"turbo": 12`). |
| `toggle` | A press latches the action on; the next press releases it. Good for sprint. |
| `repeat` | Re-fire rate for `scroll:` actions while held (default 15/s). |
| `threshold` | Triggers only: how far to pull before it counts (0–1, default 0.5). |

`turbo` and `toggle` are mutually exclusive — a latched auto-fire is a footgun, so the profile is rejected rather than guessing.

### Stick modes

| Mode | Behaviour | Tuning |
| --- | --- | --- |
| `mouse` | Moves the pointer | everything below |
| `scroll` | Scrolls the window | `speed` is clicks/second here, not pixels |
| `keys` | Presses `up`/`down`/`left`/`right` bindings past `threshold` — the WASD case | `threshold`, `deadzone` |
| `off` | Ignores the stick | — |

Every dial, and what it is actually for:

| Option | Default | What it does |
| --- | --- | --- |
| `speed` | 900 | Pixels/second (or scroll clicks/second) at full deflection. |
| `deadzone` | 0.15 | How far you must push before anything happens. **Radial** — measured on the stick's distance from centre, so diagonals don't snap to the nearest axis. With calibration you can drop this to ~0.08. |
| `outer_deadzone` | 1.0 | The deflection that counts as fully pushed. Lower it if a worn stick can't reach the rail and never hits full speed. |
| `curve` | 2.0 | `1.0` is linear; `2.0` gives a slow, precise centre with a fast outer range; below `1.0` is twitchier. |
| `smoothing` | 0.35 | Averages the stick over a short window. This is what stops the pointer wobbling while you hold a direction. `0` disables it. |
| `accel` | 1.0 (off) | Peak speed multiplier while the stick is held out near its edge. `2.5` means travelling across the screen is 2.5× faster than the first moment of a nudge. |
| `accel_time` | 0.6 | Seconds to reach full `accel`. Decay back to normal is 3× faster, so a brief correction returns you to precision. |
| `precision` | 0.25 | Speed multiplier while a `special:precision` binding is held. |
| `invert_x` / `invert_y` | false | Flip an axis. |

**Speed, accel and precision are meant to be used together.** One flat speed forces a bad choice: slow enough to hit a checkbox means crawling across the screen, fast enough to cross the screen means overshooting everything. Holding the stick out is an unambiguous "I am travelling" so `accel` builds; holding the precision button is an unambiguous "I am aiming" so everything slows. The bundled `desktop` profile ships `speed: 1000`, `accel: 2.5` and `precision: 0.22`, which spans roughly 220 to 2500 px/s on one stick.

### Drift, and why a deadzone isn't enough

A worn stick doesn't rest at zero. It rests at, say, `x = +0.18`. A deadzone is centred on zero, so the only way it can silence that is to be bigger than 0.18 — which throws away the same 0.18 of travel on the side that was never wrong. You buy "it stopped drifting" with "and now fine control is worse everywhere".

Calibration fixes it properly: measure where the stick actually rests, and subtract it.

```
padmap calibrate --write mine.json
```

Two phases, about ten seconds: let go of the sticks while it measures the rest position, then roll both sticks around their edge while it measures how far they really travel. It writes a block like this:

```json
"device": {
  "auto_centre": true,
  "calibration": {
    "left_x":  { "centre": 0.18, "low": -0.95, "high": 0.90 },
    "left_y":  { "centre": -0.07, "low": -0.92, "high": 0.94 }
  }
}
```

Each side of each axis is rescaled independently, so an off-centre rest costs you nothing on the good side, and a stick that only reaches 0.90 still gets to full speed.

**`auto_centre` is on by default**, so even with no stored calibration padmap spends the first 0.4 s of a run measuring where your sticks are resting and corrects for it. Pointer motion is suppressed for that fraction of a second; buttons work immediately. If you happen to be holding a stick it says so and carries on uncorrected rather than baking your thumb position in as "centre". Set `"auto_centre": false` to trust the stored numbers only.

Drift also shows up as *skew*: with a `y` drift of −0.07, pushing straight right also creeps upward — about 65 px per second on a 1000 px/s profile. Calibration takes that to ~1 px.

### Layers

An Xbox pad has ten buttons, which runs out fast. A **layer** is a second set of bindings you reach by holding a button — xpadder calls these shift sets.

```json
"buttons": {
  "rb": "special:layer:nav",
  "a": "mouse:left"
},
"layers": {
  "nav": {
    "description": "media and browser navigation",
    "buttons": { "a": "key:media_play_pause" },
    "dpad": { "left": "key:alt+left", "right": "key:alt+right" }
  }
}
```

Hold **RB** and `A` becomes play/pause; let go and it is left-click again. A layer overrides only the inputs it names — everything else keeps doing what the base profile says — and it can bind inputs the base leaves alone, or replace a whole stick (so one layer can turn the pointer stick into a scroll stick).

Two rules, both enforced when the profile loads:

- **Specials live in the base profile only.** A layer cannot contain `special:` anything. Otherwise "which layer am I in" could depend on which layer you are in, which has no good answer.
- **Every layer must be reachable, and every layer switch must point at a real layer.** A dangling `special:layer:typo` would just silently do nothing at runtime, which is indistinguishable from a broken button.

If a layer switch changes what a *held* button means, padmap releases the outgoing binding before pressing the new one — no stuck keys.

### Tuning it while it runs

```
padmap run -w -p mine.json
```

`-w` / `--watch` reloads the profile whenever you save the file. Change `speed`, save, feel the difference, repeat — no restarting, no losing your place. A broken edit doesn't stop the session: padmap prints the error and keeps running the last profile that worked.

### When a button maps to the wrong thing

Controller drivers do not always agree on which raw index is which button. Run `padmap monitor`, press the button, and note the index it prints. Then pin it in the profile:

```json
"device": {
  "match": "xbox",
  "layout": { "a": 0, "b": 1, "lt": 2, "rt": 5 },
  "trigger_mode": "auto"
}
```

`trigger_mode` handles the other common driver disagreement: most report the triggers as `-1` (released) to `1` (pulled), a few as `0` to `1`. `auto` samples them at rest and decides; set `signed` or `unipolar` to pin it.

---

## Developer Setup

```
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # install padmap plus pytest and ruff
pytest                        # run the test suite with coverage
ruff check . && ruff format --check .
```

The test suite runs entirely on fakes — no controller, no display, no synthetic input reaches the machine — so it is safe to run anywhere and it runs in CI on every PR.

### Architecture source of truth

[`CLAUDE.md`](./CLAUDE.md) is the authoritative architecture doc (module map, conventions, CI, security model). When this README and `CLAUDE.md` disagree, `CLAUDE.md` wins and this README needs updating.

### AI tooling

This repo supports multi-AI contributions. Tool-specific entrypoints (`.cursorrules`) defer to [`CLAUDE.md`](./CLAUDE.md) on disagreement. See [`ai/AI_TEAM_PLAYBOOK.md`](./ai/AI_TEAM_PLAYBOOK.md) for the coordination conventions.

### CI/CD at a glance

| Workflow | Trigger | What it does |
| --- | --- | --- |
| [`ci.yml`](./.github/workflows/ci.yml) | PR + push to `main` | Ruff lint, ruff format check, pytest with an 80% coverage floor |
| [`security-scan.yml`](./.github/workflows/security-scan.yml) | PR, push to `main`, weekly | CodeQL (Python), gitleaks, OpenSSF Scorecard |
| [`dependency-review.yml`](./.github/workflows/dependency-review.yml) | PR | Blocks dependency changes that introduce high-severity CVEs |

---

## Project Structure

```
controller/
├── src/padmap/
│   ├── actions.py            ← the action grammar ("key:w", "mouse:left")
│   ├── config.py             ← profile schema, loading, validation
│   ├── curves.py             ← deadzones, curves, smoothing, acceleration
│   ├── calibration.py        ← measuring stick drift and travel
│   ├── devices.py            ← controller discovery and polling (pygame)
│   ├── backends.py           ← keyboard/mouse output (pynput) + a recording fake
│   ├── engine.py             ← the mapping loop: state in, events out
│   ├── cli.py                ← the `padmap` command
│   └── profiles/             ← bundled JSON profiles
├── tests/                    ← runs on fakes; no hardware needed
├── docs/
│   └── troubleshooting.md    ← when it doesn't work
├── CLAUDE.md                 ← architecture source of truth
└── README.md                 ← this file
```

**For everyday use** you only touch:

* a profile `.json` — to change what buttons do
* `padmap monitor` — to find out what your pad actually reports

**For deeper changes** see [`CLAUDE.md`](./CLAUDE.md).

---

## Safety

A remapper holds keys down on your behalf, so the one rule that outranks everything in the code is **never leave a key stuck down**. Pausing, quitting, `Ctrl-C`, `SIGTERM` and any crash all release every held key and mouse button on the way out. If you ever do find a key stuck, press the pause button or `Ctrl-C` — and please [file a bug](https://github.com/Ranzlappen/controller/issues/new/choose), because that is the most serious class of bug this project can have.

padmap does not bypass anti-cheat, and will not gain features that try to. Games that block synthetic input block padmap.

---

## Community standards

Contributions to this repo are governed by three layered standards: the
[GitHub Community Guidelines](https://docs.github.com/en/site-policy/github-terms/github-community-guidelines),
the [GitHub Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies),
and this repo's [`CODE_OF_CONDUCT.md`](./.github/CODE_OF_CONDUCT.md). See
[`.github/CONTRIBUTING.md`](./.github/CONTRIBUTING.md) for the contributor-facing
version and the reporting routes.

## License

This project is released under the **MIT License**. The full text is in [`LICENSE`](./LICENSE) at the repo root — that file is the authoritative copy; this section is just a summary.

Copyright (c) 2026 Ranzlappen.

In short: do whatever you want with this code as long as you keep the copyright notice. No warranty.
