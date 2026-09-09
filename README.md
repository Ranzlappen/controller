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

It is deliberately small: two runtime dependencies, one command, no daemon, no tray icon, no GUI editor. `padmap monitor` tells you what your pad reports; the JSON tells padmap what to do about it.

---

## Quick Reference

| I want to... | Do this |
| --- | --- |
| See what my controller reports | `padmap devices`, then `padmap monitor` |
| Try it without affecting my desktop | `padmap run --dry-run` |
| Control the desktop from the couch | `padmap run -p desktop` |
| Play a keyboard game on the pad | `padmap run -p fps` |
| See what a profile does | `padmap validate fps` |
| Write my own profile | `padmap init my-profile.json`, edit, `padmap run -p my-profile.json` |
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
| `mouse` | Moves the pointer | `speed` (pixels/second at full deflection), `deadzone`, `curve` |
| `scroll` | Scrolls the window | `speed` (clicks/second), `deadzone`, `curve` |
| `keys` | Presses `up`/`down`/`left`/`right` bindings past `threshold` — the WASD case | `threshold`, `deadzone` |
| `off` | Ignores the stick | — |

`curve` shapes the response: `1.0` is linear, `2.0` (the default) gives a slow, precise centre and a fast outer range, below `1.0` is twitchier. `deadzone` is **radial** — measured on the stick's distance from centre, not per axis — so diagonals don't snap to the nearest axis.

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
│   ├── curves.py             ← deadzones, response curves, sub-pixel motion
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
