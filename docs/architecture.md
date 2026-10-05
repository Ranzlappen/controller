# Architecture reference

Detail that would crowd out [`CLAUDE.md`](../CLAUDE.md), which is the architecture source of truth and wins over this file if the two ever disagree.

## Tech stack

| Layer | Technology | Why this one |
| --- | --- | --- |
| Input | pygame 2.x (SDL2) | One code path covers Windows/Linux/macOS |
| Output | pynput 1.x | Separate press/release, so keys can be *held* |
| Config | JSON + dataclasses | Hand-editable; no schema library needed |
| CLI | argparse (stdlib) | No dependency for twelve subcommands |
| Focus / doctor | ctypes + platform CLIs | No new dependency for a diagnostic |
| Lint/format | Ruff | One tool, config in `pyproject.toml` |
| Tray | pystray + Pillow | Only cross-platform option; an extra, not a dependency |
| Tests | pytest + pytest-cov | Coverage floor enforced in-process |
| Build | hatchling | src layout, bundles `profiles/*.json` |

## Deployment & CI/CD

padmap is installed locally with `pip install .`; nothing deploys. Three workflows, all validation only: `ci.yml` (ruff lint + format, pytest on 3.10 and 3.12, path-filtered to Python, `pyproject.toml`, `requirements*.txt` and bundled profiles), `security-scan.yml` (CodeQL, gitleaks, Scorecard — no path filter, so docs trigger it), and `dependency-review.yml`. Details and triggers in [`README.md`](./README.md#cicd-at-a-glance). Required secrets: none.

