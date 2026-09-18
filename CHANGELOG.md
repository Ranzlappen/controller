# Changelog

All notable changes to **padmap** are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] — 2026-09-18

Controllability pass. v0.1.0 had one dial for stick drift — a deadzone — and a
deadzone cannot fix drift: it is centred on zero and a worn stick is not, so
silencing 0.18 of drift costs 0.18 of travel on the side that was never wrong.
This release measures the stick instead.

### Added

- **Stick calibration** (`padmap calibrate`). Measures where each axis rests and
  how far it actually travels, then writes a `device.calibration` block into a
  profile with `--write`. Each side of each axis is rescaled independently, so
  an off-centre rest costs nothing on the good side and a stick that only
  reaches 0.90 still gets to full speed.
- **Auto-centring at startup**, on by default. Spends the first 0.4 s measuring
  the resting sticks and corrects for them; suppresses pointer motion for that
  window (buttons respond immediately). Refuses, with an explanation, if a stick
  looks held or moving rather than baking a thumb position in as "centre".
- **Smoothing** (`sticks.*.smoothing`). Frame-rate-independent exponential
  filter over the stick vector — this is what stops the pointer wobbling while
  you hold a direction. Settles to exactly zero on release rather than decaying
  towards it forever.
- **Acceleration** (`sticks.*.accel`, `accel_time`). Speed builds while the
  stick is held out near its edge and decays three times faster when eased off,
  so one stick can be both precise and fast.
- **A precision modifier** (`special:precision`). Hold a button to scale every
  stick by its `precision` factor.
- **Layers** (`layers` section, `special:layer:<name>`). Hold a button for a
  second set of bindings — xpadder's shift sets. A layer overrides only what it
  names, can bind inputs the base leaves alone, and can replace a whole stick.
- **Hot reload** (`padmap run --watch`). Reloads the profile when the file
  changes, so tuning does not need a restart. A broken edit is reported and the
  last working profile stays in force.
- **`outer_deadzone`** for sticks that cannot reach the rail.

### Changed

- **`smoothing` now defaults to 0.35** rather than being absent. This changes
  the feel of an existing profile that does not mention it. Set
  `"smoothing": 0` for the previous raw behaviour.
- **`device.auto_centre` defaults to true**, so drift is corrected even with no
  stored calibration. Set `"auto_centre": false` to trust stored numbers only.
- Bundled profiles rebuilt around the new options. `desktop` drops its deadzone
  from 0.15 to 0.10 (calibration handles what the deadzone used to), gains
  acceleration, puts the precision modifier on **LB** and a media/navigation
  layer on **RB**. `fps` gains light smoothing on the aim stick and keeps
  acceleration off, because aim should stay linear.
- A binding that changes while held is now released before the new one is
  pressed, so a layer switch under a held button cannot strand a key down.

### Fixed

- Cross-axis drift skew: with a y-drift of −0.07, pushing straight right also
  crept upward by roughly 65 px per second on a 1000 px/s profile. Calibration
  takes that to about 1 px.

## [0.1.0] — 2026-09-09

### Added

- Initial release: an xpadder-style remapper that maps an Xbox controller to
  keyboard keys and mouse movement.
- **Action grammar** — `key:` (single keys and combos), `mouse:`, `scroll:`,
  `text:`, `special:` (`toggle_pause`, `quit`) and `noop`, validated at profile
  load time with errors that name the offending path.
- **JSON profiles** for buttons, d-pad, analogue triggers (with a pull
  threshold) and both sticks, plus per-binding `turbo`, `toggle` and `repeat`
  options. Three bundled: `desktop`, `fps`, `starter`.
- **Stick modes** — `mouse` (radial deadzone, response curve, sub-pixel
  accumulation so slow movement works), `scroll`, `keys` (WASD-style) and `off`.
- **Controller layer** on pygame/SDL2 with the standard Xbox layout, per-profile
  raw-index overrides, hat *and* axis d-pads, and trigger-range auto-detection.
- **CLI** — `run` (with `--dry-run`), `devices`, `monitor`, `profiles`,
  `validate` and `init`.
- **Release-on-exit guarantee**: pause, quit, `Ctrl-C`, `SIGTERM` and any
  exception all release every held key and mouse button.
- Repo set up to [`repo-standards`](https://github.com/Ranzlappen/repo-standards)
  v3: CI (ruff + pytest on Python 3.10 and 3.12, 80% coverage floor), CodeQL,
  gitleaks, OpenSSF Scorecard, dependency review, Dependabot, and the community
  health files.

<!--
Workflow:
  1. Append to [Unreleased] as you merge PRs.
  2. When cutting a release, rename [Unreleased] to [X.Y.Z] — <date>
     and add a fresh empty [Unreleased] heading at the top.
  3. Update the comparison links at the bottom of this file.
  4. Tag the merge commit (e.g. `git tag -a vX.Y.Z -m "vX.Y.Z"`).

Sections to use (omit any that don't apply for a given release):
  Added | Changed | Deprecated | Removed | Fixed | Security
-->

[Unreleased]: https://github.com/Ranzlappen/controller/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Ranzlappen/controller/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Ranzlappen/controller/releases/tag/v0.1.0
