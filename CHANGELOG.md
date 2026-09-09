# Changelog

All notable changes to **padmap** are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Ranzlappen/controller/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Ranzlappen/controller/releases/tag/v0.1.0
